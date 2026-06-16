"""
source_resolver.py — SourceResolver

Given a metric name (or a set of required attributes), picks the single best
authoritative BigQuery table to query. Uses a greedy cover algorithm:

  1. If the metric has a preferred_source → use it directly.
  2. Otherwise, score each candidate source by the number of required
     attribute mappings it covers, and pick the highest-scoring one.
  3. If multiple sources tie, prefer the one with the lowest freshness SLA
     (i.e. most up-to-date data).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from analytics_api.src.semantic.exceptions import SourceNotFoundError
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.schema import CanonicalAttribute, EntitySource

logger = logging.getLogger(__name__)

BQ_PROJECT = "ai-risk-workflow"


@dataclass
class ResolvedSource:
    """Result of resolving the best source for a set of attributes."""
    source_name: str                        # e.g. "credit_risk.org_balance_sheet"
    full_table_ref: str                     # BQ 3-part: `ai-risk-workflow.credit_risk.org_balance_sheet`
    join_key: Optional[str]                 # physical column name, None for aggregate tables
    freshness_sla_hours: int
    covered_attributes: Dict[str, str]      # attr_name → physical_column


class SourceResolver:
    """Resolve the best source table for a metric or attribute set.

    Example::

        resolver = SourceResolver()

        # Metric-based resolution
        source = resolver.resolve_metric("DelinquencyRate")
        print(source.full_table_ref)
        # → `ai-risk-workflow.credit_risk.org_balance_sheet`

        # Attribute-based resolution
        source = resolver.resolve(
            entity_name="Loan",
            required_attrs=["loan_id", "current_balance", "loan_status"]
        )
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve_metric(self, metric_name: str) -> ResolvedSource:
        """Return the best source for a named metric."""
        metric = self._loader.get_metric(metric_name)
        if metric.preferred_source:
            return self._build_resolved(
                source_name=metric.preferred_source,
                entity_name=metric.required_entities[0] if metric.required_entities else None,
                required_attrs=metric.required_attributes,
            )
        # Fall back to attribute-based resolution
        entity_name = metric.required_entities[0] if metric.required_entities else None
        return self.resolve(
            entity_name=entity_name,
            required_attrs=metric.required_attributes,
        )

    def resolve(
        self,
        entity_name: Optional[str],
        required_attrs: Optional[List[str]] = None,
    ) -> ResolvedSource:
        """Return the best source table for an entity + attribute list."""
        if not entity_name:
            raise SourceNotFoundError("entity_name is required for attribute-based resolution")
        entity = self._loader.get_entity(entity_name)
        required_attrs = required_attrs or []

        # Strip entity prefix from attr references like "Loan.fico_score" → "fico_score"
        clean_attrs = [a.split(".")[-1] for a in required_attrs]

        best_source: Optional[EntitySource] = None
        best_score = -1
        best_covered: Dict[str, str] = {}

        for source in entity.sources:
            covered: Dict[str, str] = {}
            for attr_name in clean_attrs:
                attr = entity.attributes.get(attr_name)
                if attr and source.name in attr.mappings:
                    covered[attr_name] = attr.mappings[source.name]
            score = len(covered)
            if score > best_score or (
                score == best_score
                and best_source is not None
                and source.freshness_sla_hours < best_source.freshness_sla_hours
            ):
                best_score = score
                best_source = source
                best_covered = covered

        if best_source is None:
            raise SourceNotFoundError(
                f"No sources registered for entity '{entity_name}'"
            )

        return self._build_resolved(
            source_name=best_source.name,
            entity_name=entity_name,
            required_attrs=required_attrs,
            _override_source=best_source,
            _override_covered=best_covered,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_resolved(
        self,
        source_name: str,
        entity_name: Optional[str],
        required_attrs: Optional[List[str]],
        _override_source: Optional[EntitySource] = None,
        _override_covered: Optional[Dict[str, str]] = None,
    ) -> ResolvedSource:
        dataset, table = source_name.split(".", 1)
        full_ref = f"`{BQ_PROJECT}.{dataset}.{table}`"

        # Find EntitySource metadata
        entity_source: Optional[EntitySource] = _override_source
        if entity_source is None and entity_name:
            entity = self._loader.get_entity(entity_name)
            for s in entity.sources:
                if s.name == source_name:
                    entity_source = s
                    break

        join_key = entity_source.join_key if entity_source else None
        freshness = entity_source.freshness_sla_hours if entity_source else 24

        # Build covered attributes if not already provided
        covered: Dict[str, str] = _override_covered or {}
        if not covered and entity_name and required_attrs:
            entity = self._loader.get_entity(entity_name)
            for ref in required_attrs:
                attr_name = ref.split(".")[-1]
                attr = entity.attributes.get(attr_name)
                if attr and source_name in attr.mappings:
                    covered[attr_name] = attr.mappings[source_name]

        return ResolvedSource(
            source_name=source_name,
            full_table_ref=full_ref,
            join_key=join_key,
            freshness_sla_hours=freshness,
            covered_attributes=covered,
        )
