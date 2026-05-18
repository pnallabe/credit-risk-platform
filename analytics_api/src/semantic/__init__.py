"""
Semantic Layer — Layer A of the 4-layer Semantic Intelligence architecture.

Exports the primary façade: SemanticLayer.
"""
from analytics_api.src.semantic.loader import SemanticLayerLoader
from analytics_api.src.semantic.metric_registry import MetricRegistry
from analytics_api.src.semantic.synonym_mapper import SynonymMapper
from analytics_api.src.semantic.source_resolver import SourceResolver
from analytics_api.src.semantic.relationship_registry import RelationshipRegistry

__all__ = [
    "SemanticLayerLoader",
    "MetricRegistry",
    "SynonymMapper",
    "SourceResolver",
    "RelationshipRegistry",
]
