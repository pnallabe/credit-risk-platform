"""
query_plan.py — QueryPlan and related models

The QueryPlanner produces a QueryPlan from a ResolvedIntent.
SQLGenerator converts the QueryPlan into a parameterized BigQuery SQL string.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ColumnRef:
    """A fully-qualified reference to a BQ column."""
    table_alias: str               # e.g. "org_balance_sheet"
    column: str                    # e.g. "delinquency_rate"
    alias: Optional[str] = None   # SELECT alias for this column

    @property
    def sql(self) -> str:
        ref = f"{self.table_alias}.{self.column}"
        return f"{ref} AS {self.alias}" if self.alias else ref


@dataclass
class JoinPath:
    from_table_ref: str
    from_alias: str
    from_column: str
    to_table_ref: str
    to_alias: str
    to_column: str
    join_type: str                 # LEFT | INNER


@dataclass
class MetricComputationSpec:
    """Describes how to compute the metric aggregate."""
    aggregation_sql: str           # e.g. "AVG(delinquency_rate)"
    result_alias: str              # e.g. "delinquency_rate"
    multiply_by: float = 1.0


@dataclass
class QueryPlan:
    """Complete, parameterized query plan ready for SQL generation."""
    primary_table_ref: str         # BQ 3-part ref e.g. `ai-risk-workflow.credit_risk.org_balance_sheet`
    primary_alias: str             # short alias e.g. "org_balance_sheet"
    select_columns: List[ColumnRef]
    metric_spec: Optional[MetricComputationSpec]
    joins: List[JoinPath]
    where_conditions: List[str]    # parameterized SQL fragments e.g. "product_type = :product_type"
    bind_params: Dict[str, Any]    # e.g. {"product_type": "PERSONAL"}
    group_by: List[str]            # column references for GROUP BY
    order_by: List[str]            # column references for ORDER BY
    limit: Optional[int]
    is_timeseries: bool
    bq_sql_override: Optional[str] = None   # if set, use pre-built SQL directly
