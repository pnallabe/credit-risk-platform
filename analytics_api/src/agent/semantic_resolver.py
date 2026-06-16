"""
semantic_resolver.py — SemanticResolver

Converts a raw QueryIntent (LLM output) into a fully typed ResolvedIntent
using the Semantic Layer (A) and Domain Ontology (B).

No LLM calls. All resolution is deterministic.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from analytics_api.src.agent.models import FilterCondition, QueryIntent
from analytics_api.src.agent.resolved_intent import (
    ResolvedDimension,
    ResolvedFilter,
    ResolvedIntent,
    ResolvedMetric,
)
from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
from analytics_api.src.domain_ontology.ontology_parser import OntologyParser, get_ontology
from analytics_api.src.semantic.exceptions import MetricNotFoundError, SourceNotFoundError
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.metric_registry import MetricRegistry
from analytics_api.src.semantic.source_resolver import SourceResolver
from analytics_api.src.semantic.synonym_mapper import SynonymMapper

logger = logging.getLogger(__name__)


class SemanticResolver:
    """Resolve a QueryIntent into a ResolvedIntent.

    Example::

        resolver = SemanticResolver()
        intent = QueryIntent(metric="DelinquencyRate",
                             product_type="PERSONAL_LOAN",
                             is_timeseries=True, ...)
        resolved = resolver.resolve(intent)
        # ResolvedIntent with metric, source, entities, filters all populated
    """

    def __init__(
        self,
        loader: Optional[SemanticLayerLoader] = None,
        ontology: Optional[OntologyParser] = None,
    ) -> None:
        self._loader = loader or get_loader()
        self._ontology = ontology or get_ontology()
        self._metric_registry = MetricRegistry(loader=self._loader)
        self._source_resolver = SourceResolver(loader=self._loader)
        self._synonym_mapper = SynonymMapper(loader=self._loader)
        self._normalizer = IntentNormalizer(loader=self._loader, ontology=self._ontology)
        self._constraint_validator = DomainConstraintValidator(loader=self._loader)

    def resolve(self, intent: QueryIntent) -> ResolvedIntent:
        # Step 1: Resolve metric name (normalize if needed)
        metric_name = intent.metric
        if not metric_name:
            # Try synonym resolution on the raw question
            norm = self._normalizer.normalize(intent.raw_question)
            metric_name = norm.metric_name

        resolved_metric: Optional[ResolvedMetric] = None
        if metric_name:
            resolved_metric = self._resolve_metric(metric_name, intent)

        if resolved_metric is None and intent.metric:
            logger.warning("SemanticResolver: could not resolve metric '%s'", intent.metric)

        # Step 2: Resolve filters
        filter_dict = {f.field: f.value for f in intent.filters}
        constraint_violations = self._constraint_validator.validate_filters(filter_dict)
        if constraint_violations:
            violation_msg = "; ".join(v.reason for v in constraint_violations)
            return ResolvedIntent(
                raw_question=intent.raw_question,
                resolved_metric=None,
                dimensions=[],
                filters=[],
                entities_needed=[],
                needs_join=False,
                is_timeseries=intent.is_timeseries,
                product_type=intent.product_type,
                clarification_needed=True,
                clarification_reason=violation_msg,
            )

        resolved_filters = self._resolve_filters(intent.filters, resolved_metric)

        # Step 3: Resolve dimensions
        resolved_dims = self._resolve_dimensions(intent.dimensions, resolved_metric)

        # Step 4: Determine entities needed
        entities_needed: List[str] = []
        if resolved_metric:
            entities_needed = list(resolved_metric.metric.required_entities)

        needs_join = len(entities_needed) > 1

        return ResolvedIntent(
            raw_question=intent.raw_question,
            resolved_metric=resolved_metric,
            dimensions=resolved_dims,
            filters=resolved_filters,
            entities_needed=entities_needed,
            needs_join=needs_join,
            is_timeseries=intent.is_timeseries,
            product_type=intent.product_type,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_metric(
        self, metric_name: str, intent: QueryIntent
    ) -> Optional[ResolvedMetric]:
        try:
            metric = self._metric_registry.get(metric_name)
        except MetricNotFoundError:
            # Try case-insensitive match
            for m in self._loader.list_metrics():
                if m.name.lower() == metric_name.lower():
                    metric = m
                    break
            else:
                return None

        try:
            source = self._source_resolver.resolve_metric(metric.name)
        except SourceNotFoundError as exc:
            logger.warning("SemanticResolver: %s", exc)
            return None

        # Detect variant from question or intent
        norm = self._normalizer.normalize(intent.raw_question)
        variant = norm.variant or self._normalizer.detect_variant(metric_name or "")
        concept = norm.concept or self._ontology.find_by_metric(metric.name)

        return ResolvedMetric(
            metric=metric,
            source=source,
            variant=variant,
            concept=concept,
            is_timeseries=intent.is_timeseries,
        )

    def _resolve_filters(
        self,
        filters: List[FilterCondition],
        resolved_metric: Optional[ResolvedMetric],
    ) -> List[ResolvedFilter]:
        result: List[ResolvedFilter] = []
        source_name = resolved_metric.source.source_name if resolved_metric else None

        for f in filters:
            physical_col = f.field  # default: use as-is
            if source_name:
                # Try to find a canonical mapping
                for entity in self._loader.list_entities():
                    attr = entity.attributes.get(f.field)
                    if attr and source_name in attr.mappings:
                        physical_col = attr.mappings[source_name]
                        break
            result.append(
                ResolvedFilter(
                    field=f.field,
                    physical_column=physical_col,
                    operator=f.operator,
                    value=f.value,
                )
            )
        return result

    def _resolve_dimensions(
        self,
        dimensions: List[str],
        resolved_metric: Optional[ResolvedMetric],
    ) -> List[ResolvedDimension]:
        result: List[ResolvedDimension] = []
        source_name = resolved_metric.source.source_name if resolved_metric else None

        for dim in dimensions:
            physical_col = dim
            if source_name:
                for entity in self._loader.list_entities():
                    attr = entity.attributes.get(dim)
                    if attr and source_name in attr.mappings:
                        physical_col = attr.mappings[source_name]
                        break
            result.append(
                ResolvedDimension(
                    canonical_name=dim,
                    physical_column=physical_col,
                    source_name=source_name or "",
                )
            )
        return result
