"""
loader.py — SemanticLayerLoader

Loads entity, metric, synonym, and relationship YAML files from disk into
strongly-typed dataclasses. Acts as the single source of truth for all
semantic definitions consumed by higher layers (B, C, D).
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from analytics_api.src.semantic.exceptions import (
    AttributeNotFoundError,
    EntityNotFoundError,
    MetricNotFoundError,
    SourceNotFoundError,
)
from analytics_api.src.semantic.schema import (
    CanonicalAttribute,
    CanonicalEntity,
    EntitySource,
    MetricDefinition,
    MetricFormula,
    MetricVariant,
    Relationship,
)

logger = logging.getLogger(__name__)

# Directory layout relative to this file
_BASE = Path(__file__).parent
_ENTITIES_DIR = _BASE / "entities"
_METRICS_DIR = _BASE / "metrics"
_SYNONYMS_FILE = _BASE / "synonyms" / "synonyms.yaml"
_RELATIONSHIPS_FILE = _BASE / "relationships" / "relationships.yaml"


class SemanticLayerLoader:
    """Load and cache all semantic definitions from YAML.

    Usage::

        loader = SemanticLayerLoader()
        entity = loader.get_entity("Loan")
        metric = loader.get_metric("DelinquencyRate")
        col    = loader.get_source_column("Loan", "fico_score",
                                          "credit_risk.personal_loans_funded")
    """

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        self._base = base_dir or _BASE
        self._entities: Dict[str, CanonicalEntity] = {}
        self._metrics: Dict[str, MetricDefinition] = {}
        self._synonyms: Dict[str, str] = {}          # term (lower) → canonical name
        self._relationships: List[Relationship] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_all(self) -> None:
        """Load everything from disk. Idempotent — subsequent calls are no-ops."""
        if self._loaded:
            return
        self._load_entities()
        self._load_metrics()
        self._load_synonyms()
        self._load_relationships()
        self._loaded = True
        logger.info(
            "SemanticLayerLoader: %d entities, %d metrics, %d synonyms, %d relationships",
            len(self._entities),
            len(self._metrics),
            len(self._synonyms),
            len(self._relationships),
        )

    def get_entity(self, name: str) -> CanonicalEntity:
        self._ensure_loaded()
        try:
            return self._entities[name]
        except KeyError:
            raise EntityNotFoundError(f"Entity '{name}' not found. Available: {list(self._entities)}")

    def list_entities(self) -> List[CanonicalEntity]:
        self._ensure_loaded()
        return list(self._entities.values())

    def get_metric(self, name: str) -> MetricDefinition:
        self._ensure_loaded()
        try:
            return self._metrics[name]
        except KeyError:
            raise MetricNotFoundError(f"Metric '{name}' not found. Available: {list(self._metrics)}")

    def list_metrics(self) -> List[MetricDefinition]:
        self._ensure_loaded()
        return list(self._metrics.values())

    def get_canonical_attribute(self, entity_name: str, attr_name: str) -> CanonicalAttribute:
        """Return the CanonicalAttribute for ``entity.attribute``."""
        entity = self.get_entity(entity_name)
        attr = entity.attributes.get(attr_name)
        if attr is None:
            raise AttributeNotFoundError(
                f"Attribute '{attr_name}' not found on entity '{entity_name}'. "
                f"Available: {list(entity.attributes)}"
            )
        return attr

    def get_source_column(
        self, entity_name: str, attr_name: str, source_name: str
    ) -> str:
        """Return the physical column name for an attribute in a specific source table."""
        attr = self.get_canonical_attribute(entity_name, attr_name)
        col = attr.mappings.get(source_name)
        if col is None:
            raise SourceNotFoundError(
                f"Attribute '{entity_name}.{attr_name}' has no mapping for source '{source_name}'. "
                f"Available sources: {list(attr.mappings)}"
            )
        return col

    def get_synonyms(self) -> Dict[str, str]:
        """Return the full synonym map: term → canonical name."""
        self._ensure_loaded()
        return dict(self._synonyms)

    def get_relationships(self) -> List[Relationship]:
        self._ensure_loaded()
        return list(self._relationships)

    # ------------------------------------------------------------------
    # Internal loaders
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load_all()

    def _load_entities(self) -> None:
        entities_dir = self._base / "entities"
        if not entities_dir.exists():
            logger.warning("Entities dir not found: %s", entities_dir)
            return
        for path in sorted(entities_dir.glob("*.yaml")):
            try:
                with path.open() as f:
                    data = yaml.safe_load(f)
                entity = self._parse_entity(data)
                self._entities[entity.name] = entity
                logger.debug("Loaded entity: %s from %s", entity.name, path.name)
            except Exception as exc:
                logger.error("Failed to load entity %s: %s", path.name, exc)

    def _parse_entity(self, data: dict) -> CanonicalEntity:
        sources = [
            EntitySource(
                name=s["name"],
                join_key=s.get("join_key"),
                freshness_sla_hours=s.get("freshness_sla_hours", 24),
            )
            for s in data.get("sources", [])
        ]
        attributes: Dict[str, CanonicalAttribute] = {}
        for attr_name, attr_data in data.get("attributes", {}).items():
            attributes[attr_name] = CanonicalAttribute(
                name=attr_name,
                type=attr_data["type"],
                description=attr_data.get("description", ""),
                mappings=attr_data.get("mappings", {}),
                allowed_values=attr_data.get("allowed_values", []),
                nullable=attr_data.get("nullable", True),
            )
        return CanonicalEntity(
            name=data["entity"],
            description=data.get("description", ""),
            primary_key=data["primary_key"],
            sources=sources,
            attributes=attributes,
        )

    def _load_metrics(self) -> None:
        metrics_dir = self._base / "metrics"
        if not metrics_dir.exists():
            logger.warning("Metrics dir not found: %s", metrics_dir)
            return
        for path in sorted(metrics_dir.glob("*.yaml")):
            try:
                with path.open() as f:
                    data = yaml.safe_load(f)
                metric = self._parse_metric(data)
                self._metrics[metric.name] = metric
                logger.debug("Loaded metric: %s from %s", metric.name, path.name)
            except Exception as exc:
                logger.error("Failed to load metric %s: %s", path.name, exc)

    def _parse_metric(self, data: dict) -> MetricDefinition:
        formula_data = data.get("formula", {})
        num = formula_data.get("numerator", {})
        den = formula_data.get("denominator", {})
        formula = MetricFormula(
            type=formula_data.get("type", "ratio"),
            numerator_filter=num.get("filter"),
            numerator_aggregation=num.get("aggregation", "COUNT(*)"),
            denominator_filter=den.get("filter") if den else None,
            denominator_aggregation=den.get("aggregation") if den else None,
            multiply_by=float(formula_data.get("multiply_by", 1.0)),
        )
        variants = [
            MetricVariant(
                name=v["name"],
                description=v.get("description", ""),
                filter_expression=v.get("filter", ""),
                severity=v.get("severity"),
            )
            for v in data.get("variants", [])
        ]
        requires = data.get("requires", {})
        sla = data.get("sla", {})
        expected_range = sla.get("expected_range")
        if expected_range:
            expected_range = (float(expected_range[0]), float(expected_range[1]))
        return MetricDefinition(
            name=data["metric"],
            description=data.get("description", ""),
            category=data.get("category", "general"),
            unit=data.get("unit", "ratio"),
            required_entities=requires.get("entities", []),
            required_attributes=requires.get("attributes", []),
            formula=formula,
            variants=variants,
            dimensions=data.get("dimensions", []),
            expected_range=expected_range,
            preferred_source=data.get("preferred_source"),
            bq_sql=data.get("bq_sql"),
            bq_sql_timeseries=data.get("bq_sql_timeseries"),
        )

    def _load_synonyms(self) -> None:
        if not _SYNONYMS_FILE.exists():
            logger.warning("Synonyms file not found: %s", _SYNONYMS_FILE)
            return
        with _SYNONYMS_FILE.open() as f:
            data = yaml.safe_load(f)
        for canonical, terms in data.get("synonyms", {}).items():
            for term in terms:
                self._synonyms[term.lower()] = canonical
        # Also map the canonical name itself → itself (case-insensitive)
        for canonical in list(self._synonyms.values()):
            self._synonyms[canonical.lower()] = canonical
        logger.debug("Loaded %d synonym entries", len(self._synonyms))

    def _load_relationships(self) -> None:
        if not _RELATIONSHIPS_FILE.exists():
            logger.warning("Relationships file not found: %s", _RELATIONSHIPS_FILE)
            return
        with _RELATIONSHIPS_FILE.open() as f:
            data = yaml.safe_load(f)
        for r in data.get("relationships", []):
            self._relationships.append(
                Relationship(
                    name=r["name"],
                    from_entity=r["from_entity"],
                    from_attribute=r["from_attribute"],
                    to_entity=r["to_entity"],
                    to_attribute=r["to_attribute"],
                    cardinality=r.get("cardinality", "one_to_many"),
                    join_type=r.get("join_type", "LEFT"),
                    description=r.get("description", ""),
                )
            )
        logger.debug("Loaded %d relationships", len(self._relationships))


@lru_cache(maxsize=1)
def get_loader() -> SemanticLayerLoader:
    """Return the process-wide SemanticLayerLoader singleton."""
    loader = SemanticLayerLoader()
    loader.load_all()
    return loader
