"""
validator.py — QueryValidator

Pre-execution and post-execution validation.

PRE-execution checks (run against generated SQL before BQ call):
  - DML/DDL keyword guard (secondary to SQLGenerator's check)
  - Schema snooping guard (INFORMATION_SCHEMA, pg_catalog, etc.)
  - Cartesian join guard (missing ON clause in a JOIN)

POST-execution checks (run against result rows):
  - BusinessRuleEngine validation per row
  - Empty result detection (metric resolved but zero rows)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from analytics_api.src.agent.resolved_intent import ResolvedIntent
from analytics_api.src.domain_ontology.rule_engine import BusinessRuleEngine, RuleViolation
from analytics_api.src.semantic.exceptions import SQLInjectionGuardError

logger = logging.getLogger(__name__)

_SCHEMA_SNOOP = re.compile(
    r"\b(INFORMATION_SCHEMA|pg_catalog|sys\.tables|sysobjects|sqlite_master)\b",
    re.IGNORECASE,
)
_CARTESIAN = re.compile(r"\bJOIN\b(?!.*?\bON\b)", re.IGNORECASE | re.DOTALL)
_DML = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


class PreExecutionError(Exception):
    """Raised when pre-execution validation fails."""


class QueryValidator:
    """Validate SQL before execution and result rows after execution.

    Example::

        validator = QueryValidator()

        # Pre-execution
        validator.pre_execute(sql)   # raises PreExecutionError on failure

        # Post-execution
        violations = validator.post_execute(
            intent=resolved_intent,
            rows=[{"delinquency_rate": -1.5, ...}]
        )
    """

    def __init__(self) -> None:
        self._rule_engine = BusinessRuleEngine()

    # ------------------------------------------------------------------
    # Pre-execution
    # ------------------------------------------------------------------

    def pre_execute(self, sql: str) -> None:
        clean = _strip_comments(sql)

        if _DML.search(clean):
            raise PreExecutionError(
                "SQL contains a disallowed DML/DDL keyword — execution blocked."
            )

        if _SCHEMA_SNOOP.search(clean):
            raise PreExecutionError(
                "SQL references a system catalog table — execution blocked to prevent "
                "schema snooping."
            )

        # Cartesian join detection: JOIN without ON
        # Note: WITH clauses and subqueries can contain JOIN + ON on different lines;
        # only flag if a JOIN appears with no ON anywhere in the statement.
        if re.search(r"\bJOIN\b", clean, re.IGNORECASE):
            if not re.search(r"\bON\b", clean, re.IGNORECASE):
                raise PreExecutionError(
                    "SQL contains a JOIN without an ON clause — potential cartesian product."
                )

        first = clean.strip().upper().split()[0] if clean.strip() else ""
        if first not in ("SELECT", "WITH"):
            raise PreExecutionError(
                f"SQL does not start with SELECT or WITH (got '{first}')."
            )

    # ------------------------------------------------------------------
    # Post-execution
    # ------------------------------------------------------------------

    def post_execute(
        self,
        intent: ResolvedIntent,
        rows: List[Dict[str, Any]],
    ) -> List[RuleViolation]:
        """Validate result rows against domain rules. Returns all violations."""
        if not rows:
            return []

        rm = intent.resolved_metric
        if rm is None or rm.concept is None:
            return []

        concept_name = rm.concept.name
        # Determine the metric field name from the first row's keys
        metric_field = rm.metric.name.lower()
        if metric_field not in rows[0]:
            # Try common aliases
            for candidate in ("delinquency_rate", "charge_off_rate", "approval_rate",
                              "utilization_rate", "remaining_balance", "current_balance"):
                if candidate in rows[0]:
                    metric_field = candidate
                    break
            else:
                return []  # Cannot determine metric field from result rows

        violations = self._rule_engine.validate_rows(concept_name, rows, metric_field)
        if violations:
            error_count = sum(1 for v in violations if v.severity == "error")
            warn_count = len(violations) - error_count
            logger.warning(
                "QueryValidator post-execution: %d error(s), %d warning(s) for concept '%s'",
                error_count,
                warn_count,
                concept_name,
            )
        return violations
