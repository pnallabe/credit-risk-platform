"""
metric_registry.py — MetricRegistry

Provides lookup, filtering, and source requirements for metric definitions
loaded from YAML. Higher layers use this instead of parsing YAML directly.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from analytics_api.src.semantic.exceptions import MetricNotFoundError
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.schema import MetricDefinition

logger = logging.getLogger(__name__)


class MetricRegistry:
    """Registry of all named metrics derived from the semantic layer YAML.

    Example::

        registry = MetricRegistry()
        m = registry.get("DelinquencyRate")
        by_category = registry.find_by_category("credit_risk")
        sources = registry.get_required_sources("ChargeOffRate")
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()
        self._index: Dict[str, MetricDefinition] = {}
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str) -> MetricDefinition:
        """Return a metric definition by exact name (e.g. "DelinquencyRate")."""
        self._ensure_built()
        try:
            return self._index[name]
        except KeyError:
            raise MetricNotFoundError(
                f"Metric '{name}' not found. Available: {self.list_names()}"
            )

    def list_all(self) -> List[MetricDefinition]:
        """Return all registered metric definitions."""
        self._ensure_built()
        return list(self._index.values())

    def list_names(self) -> List[str]:
        self._ensure_built()
        return list(self._index.keys())

    def find_by_category(self, category: str) -> List[MetricDefinition]:
        """Return all metrics in a given category (e.g. "credit_risk")."""
        self._ensure_built()
        return [m for m in self._index.values() if m.category == category]

    def get_required_sources(self, name: str) -> List[str]:
        """Return the preferred source + all entity sources required by a metric."""
        m = self.get(name)
        sources: List[str] = []
        if m.preferred_source:
            sources.append(m.preferred_source)
        # Add sources from required entities
        for entity_name in m.required_entities:
            try:
                entity = self._loader.get_entity(entity_name)
                for s in entity.sources:
                    if s.name not in sources:
                        sources.append(s.name)
            except Exception:
                pass
        return sources

    def get_bq_sql(self, name: str) -> Optional[str]:
        """Return the pre-built BigQuery SQL template for a metric, if available."""
        return self.get(name).bq_sql

    def get_bq_sql_timeseries(self, name: str) -> Optional[str]:
        """Return the time-series variant BigQuery SQL for a metric, if available."""
        return self.get(name).bq_sql_timeseries

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            for m in self._loader.list_metrics():
                self._index[m.name] = m
            self._built = True
            logger.debug("MetricRegistry: indexed %d metrics", len(self._index))
