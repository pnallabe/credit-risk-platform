"""
resolved_intent.py — ResolvedIntent and related models

These are the typed, validated results of SemanticResolver's work.
They represent what the agent actually plans to query, as opposed to
the raw LLM extraction in QueryIntent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from analytics_api.src.domain_ontology.concept import OntologyConcept
from analytics_api.src.semantic.schema import MetricDefinition
from analytics_api.src.semantic.source_resolver import ResolvedSource


@dataclass
class ResolvedFilter:
    field: str
    physical_column: str           # actual BQ column name
    operator: str
    value: Any


@dataclass
class ResolvedDimension:
    canonical_name: str            # e.g. "product_type"
    physical_column: str           # BQ column name in the resolved source
    source_name: str               # which source table this lives in


@dataclass
class ResolvedMetric:
    metric: MetricDefinition
    source: ResolvedSource
    variant: Optional[str]         # e.g. "30_DPD"
    concept: Optional[OntologyConcept]
    is_timeseries: bool


@dataclass
class ResolvedIntent:
    """Fully resolved query intent — ready for QueryPlanner."""
    raw_question: str
    resolved_metric: Optional[ResolvedMetric]
    dimensions: List[ResolvedDimension]
    filters: List[ResolvedFilter]
    entities_needed: List[str]           # canonical entity names
    needs_join: bool
    is_timeseries: bool
    product_type: Optional[str]
    clarification_needed: bool = False
    clarification_reason: Optional[str] = None
