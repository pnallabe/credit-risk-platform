"""
schema.py — Canonical entity and metric dataclasses for the Semantic Layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CanonicalAttribute:
    name: str
    type: str                         # string | decimal | integer | date | boolean | integer(ns)
    description: str
    mappings: dict[str, str]          # source_name → physical column
    allowed_values: list[str] = field(default_factory=list)
    nullable: bool = True


@dataclass
class EntitySource:
    name: str                         # e.g. "credit_risk.personal_loans_funded"
    join_key: Optional[str]           # physical column that is the join key (None for aggregated tables)
    freshness_sla_hours: int = 24


@dataclass
class CanonicalEntity:
    name: str
    description: str
    primary_key: str
    sources: list[EntitySource]
    attributes: dict[str, CanonicalAttribute]  # attr_name → CanonicalAttribute


@dataclass
class MetricVariant:
    name: str
    description: str
    filter_expression: str            # SQL fragment or column reference
    severity: Optional[str] = None   # moderate | high | critical


@dataclass
class MetricFormula:
    type: str                         # ratio | sum | count | average | rate
    numerator_filter: Optional[str]
    numerator_aggregation: str
    denominator_filter: Optional[str]
    denominator_aggregation: Optional[str]
    multiply_by: float = 1.0


@dataclass
class MetricDefinition:
    name: str
    description: str
    category: str
    unit: str                         # percentage | currency | count | ratio
    required_entities: list[str]
    required_attributes: list[str]
    formula: MetricFormula
    variants: list[MetricVariant]
    dimensions: list[str]             # valid GROUP BY dimension names
    expected_range: Optional[tuple[float, float]]
    preferred_source: Optional[str]
    bq_sql: Optional[str] = None      # pre-built BigQuery SQL template
    bq_sql_timeseries: Optional[str] = None


@dataclass
class Relationship:
    name: str
    from_entity: str
    from_attribute: str
    to_entity: str
    to_attribute: str
    cardinality: str                  # one_to_one | one_to_many | many_to_many
    join_type: str                    # INNER | LEFT | LEFT OUTER
    description: str
