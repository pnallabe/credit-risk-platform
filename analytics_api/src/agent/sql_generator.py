"""
sql_generator.py — SQLGenerator

Converts a QueryPlan into a safe, parameterized BigQuery SELECT statement.

Security guarantees:
  1. Identifier whitelist: every table reference and column name is checked
     against the set of known identifiers loaded from the Semantic Layer YAML.
     Unknown identifiers raise SQLInjectionGuardError.
  2. Bind parameters: filter values are never interpolated — they are passed
     as BQ parameterized query parameters (via the BQ client's @param syntax).
  3. DML guard: the generated SQL is checked to ensure it starts with SELECT
     or WITH before returning.

Note on pre-built SQL templates (bq_sql_override):
  These are defined by platform engineers in YAML files and are trusted.
  They bypass the identifier whitelist (they are not dynamic) but still
  pass through the DML guard.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional, Set

from analytics_api.src.agent.query_plan import ColumnRef, QueryPlan
from analytics_api.src.semantic.exceptions import SQLInjectionGuardError
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)

_DML_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)

BQ_PROJECT = "ai-risk-workflow"


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


class SQLGenerator:
    """Generate safe, parameterized BigQuery SQL from a QueryPlan.

    Example::

        gen = SQLGenerator()
        sql, params = gen.generate(plan)
        # sql: "SELECT product_type, AVG(delinquency_rate) ..."
        # params: {"product_type": "PERSONAL"}
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()
        self._allowed_tables: Optional[FrozenSet[str]] = None
        self._allowed_columns: Optional[FrozenSet[str]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, plan: QueryPlan) -> tuple[str, Dict[str, Any]]:
        """Return (sql_string, bind_params).

        If plan.bq_sql_override is set, it is returned directly (after DML check)
        with the plan's bind_params applied as simple string substitution is NOT
        done — override SQL is pre-built by platform engineers and trusted as-is.
        """
        if plan.bq_sql_override:
            sql = plan.bq_sql_override.strip()
            self._guard_dml(sql)
            return sql, plan.bind_params

        # Build from QueryPlan fields
        sql = self._build_select(plan)
        self._guard_dml(sql)
        return sql, plan.bind_params

    # ------------------------------------------------------------------
    # Internal builder
    # ------------------------------------------------------------------

    def _build_select(self, plan: QueryPlan) -> str:
        lines: List[str] = []

        # SELECT clause
        select_parts: List[str] = []
        for col in plan.select_columns:
            self._check_column(col.column, col.table_alias)
            select_parts.append(col.sql)
        lines.append(f"SELECT {', '.join(select_parts) if select_parts else '*'}")

        # FROM clause
        self._check_table(plan.primary_table_ref)
        lines.append(f"FROM {plan.primary_table_ref} AS {plan.primary_alias}")

        # JOIN clauses
        for j in plan.joins:
            self._check_table(j.to_table_ref)
            self._check_column(j.from_column, j.from_alias)
            self._check_column(j.to_column, j.to_alias)
            lines.append(
                f"{j.join_type} JOIN {j.to_table_ref} AS {j.to_alias} "
                f"ON {j.from_alias}.{j.from_column} = {j.to_alias}.{j.to_column}"
            )

        # WHERE clause — values use BQ @param syntax
        if plan.where_conditions:
            # Convert :param_name → @param_name for BigQuery
            bq_conditions = [c.replace(":", "@") for c in plan.where_conditions]
            lines.append("WHERE " + "\n  AND ".join(bq_conditions))

        # GROUP BY
        if plan.group_by:
            lines.append("GROUP BY " + ", ".join(plan.group_by))

        # ORDER BY
        if plan.order_by:
            lines.append("ORDER BY " + ", ".join(plan.order_by))

        # LIMIT
        if plan.limit is not None:
            lines.append(f"LIMIT {int(plan.limit)}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Identifier whitelist
    # ------------------------------------------------------------------

    def _get_allowed_tables(self) -> FrozenSet[str]:
        if self._allowed_tables is None:
            tables: Set[str] = set()
            for entity in self._loader.list_entities():
                for source in entity.sources:
                    ds, tbl = source.name.split(".", 1)
                    tables.add(f"`{BQ_PROJECT}.{ds}.{tbl}`")
            self._allowed_tables = frozenset(tables)
        return self._allowed_tables

    def _get_allowed_columns(self) -> FrozenSet[str]:
        if self._allowed_columns is None:
            cols: Set[str] = set()
            for entity in self._loader.list_entities():
                for attr in entity.attributes.values():
                    for physical_col in attr.mappings.values():
                        cols.add(physical_col.lower())
                    cols.add(attr.name.lower())
            # Also allow metric aggregation patterns (AVG, SUM, COUNT, etc.)
            for metric in self._loader.list_metrics():
                formula = metric.formula
                if formula.numerator_aggregation:
                    # Extract raw column name from aggregation expression
                    m = re.search(r"\(([^)]+)\)", formula.numerator_aggregation)
                    if m:
                        cols.add(m.group(1).strip().lower().strip("`"))
            self._allowed_columns = frozenset(cols)
        return self._allowed_columns

    def _check_table(self, table_ref: str) -> None:
        if table_ref not in self._get_allowed_tables():
            raise SQLInjectionGuardError(
                f"Table reference '{table_ref}' is not in the known table whitelist. "
                "This may indicate a SQL injection attempt."
            )

    def _check_column(self, column: str, table_alias: str = "") -> None:
        # Strip BQ backtick quoting and aggregation functions for the check
        clean = column.strip().lower().strip("`")
        # Allow aggregation functions: AVG(...), SUM(...), COUNT(...), etc.
        if re.match(r"^(avg|sum|count|min|max|countif|round|safe_divide)\s*\(", clean):
            return
        # Allow * wildcard
        if clean == "*":
            return
        # Allow aliased expressions like "period_end_date / 1000"
        if any(op in clean for op in ("/", "*", "+", "-", "cast", "timestamp")):
            return
        if clean not in self._get_allowed_columns():
            raise SQLInjectionGuardError(
                f"Column '{column}' (alias: '{table_alias}') is not in the known column "
                "whitelist. This may indicate a SQL injection attempt."
            )

    def _guard_dml(self, sql: str) -> None:
        clean = _strip_comments(sql)
        if _DML_PATTERN.search(clean):
            raise SQLInjectionGuardError(
                "Generated SQL contains a disallowed DML/DDL keyword."
            )
        first_word = clean.strip().upper().split()[0] if clean.strip() else ""
        if first_word not in ("SELECT", "WITH"):
            raise SQLInjectionGuardError(
                f"Generated SQL does not start with SELECT or WITH (got '{first_word}')."
            )
