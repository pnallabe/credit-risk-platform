"""
ontology_parser.py — OntologyParser

Loads the domain ontology YAML and exposes:
  - concept hierarchy traversal (ancestors, descendants)
  - metric → concept lookup
  - variant filter extraction
  - intent term → concept mapping
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from analytics_api.src.domain_ontology.concept import (
    ConceptVariant,
    OntologyConcept,
    OntologyRule,
)

logger = logging.getLogger(__name__)

_ONTOLOGY_FILE = Path(__file__).parent / "credit_risk_ontology.yaml"


class OntologyParser:
    """Parse and query the credit risk domain ontology.

    Example::

        parser = OntologyParser()
        ancestors = parser.get_ancestors("Delinquency_30DPD")
        # → ["Delinquency", "PortfolioPerformance"]

        concept = parser.find_by_metric("DelinquencyRate")
        # → OntologyConcept(name="Delinquency", ...)

        variant_filter = parser.get_variant_filter("Delinquency", "30_DPD")
        # → "`30dpd_rate`"
    """

    def __init__(self, ontology_file: Optional[Path] = None) -> None:
        self._file = ontology_file or _ONTOLOGY_FILE
        self._concepts: Dict[str, OntologyConcept] = {}
        self._metric_index: Dict[str, str] = {}       # metric → concept name
        self._intent_index: Dict[str, str] = {}       # lower term → concept name
        self._loaded = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        if self._loaded:
            return
        with self._file.open() as f:
            data = yaml.safe_load(f)
        for c in data.get("concepts", []):
            concept = self._parse_concept(c)
            self._concepts[concept.name] = concept
            if concept.metric:
                self._metric_index[concept.metric] = concept.name
        for mapping in data.get("intent_mappings", []):
            cname = mapping["concept"]
            for term in mapping.get("terms", []):
                self._intent_index[term.lower()] = cname
        self._loaded = True
        logger.debug(
            "OntologyParser: %d concepts, %d metric mappings, %d intent terms",
            len(self._concepts),
            len(self._metric_index),
            len(self._intent_index),
        )

    def get_concept(self, name: str) -> Optional[OntologyConcept]:
        self._ensure_loaded()
        return self._concepts.get(name)

    def list_concepts(self) -> List[OntologyConcept]:
        self._ensure_loaded()
        return list(self._concepts.values())

    def get_ancestors(self, concept_name: str) -> List[str]:
        """Return parent chain from direct parent to root (exclusive of concept_name)."""
        self._ensure_loaded()
        ancestors: List[str] = []
        current = self._concepts.get(concept_name)
        while current and current.parent:
            ancestors.append(current.parent)
            current = self._concepts.get(current.parent)
        return ancestors

    def get_descendants(self, concept_name: str) -> List[str]:
        """Return all direct and transitive children of a concept."""
        self._ensure_loaded()
        results: List[str] = []
        for name, concept in self._concepts.items():
            if name == concept_name:
                continue
            if concept_name in self.get_ancestors(name) or concept.parent == concept_name:
                if name not in results:
                    results.append(name)
        return results

    def find_by_metric(self, metric_name: str) -> Optional[OntologyConcept]:
        """Return the concept that owns a given metric name."""
        self._ensure_loaded()
        cname = self._metric_index.get(metric_name)
        if cname:
            return self._concepts.get(cname)
        return None

    def find_by_term(self, term: str) -> Optional[OntologyConcept]:
        """Map an intent term to a concept via the intent_mappings table."""
        self._ensure_loaded()
        cname = self._intent_index.get(term.lower())
        if cname:
            return self._concepts.get(cname)
        # Substring scan
        term_lower = term.lower()
        for known_term, cname in self._intent_index.items():
            if known_term in term_lower:
                return self._concepts.get(cname)
        return None

    def get_variant_filter(self, concept_name: str, variant_name: str) -> Optional[str]:
        """Return the SQL filter expression for a named variant of a concept."""
        self._ensure_loaded()
        concept = self._concepts.get(concept_name)
        if not concept:
            return None
        for v in concept.variants:
            if v.name == variant_name or v.name.endswith(f"_{variant_name}"):
                return v.filter_expression
        return None

    def get_rules(self, concept_name: str, inherited: bool = True) -> List[OntologyRule]:
        """Return all rules for a concept, optionally including inherited rules."""
        self._ensure_loaded()
        concept = self._concepts.get(concept_name)
        if not concept:
            return []
        rules: List[OntologyRule] = list(concept.rules)
        if inherited:
            for ancestor in self.get_ancestors(concept_name):
                parent = self._concepts.get(ancestor)
                if parent:
                    rules.extend(parent.rules)
        return rules

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def _parse_concept(self, data: dict) -> OntologyConcept:
        variants = [
            ConceptVariant(
                name=v["name"],
                description=v.get("description", ""),
                filter_expression=v.get("filter", ""),
                severity=v.get("severity"),
            )
            for v in data.get("variants", [])
        ]
        rules = [
            OntologyRule(
                id=r["id"],
                description=r.get("description", ""),
                expression=r.get("expression", "true"),
                severity=r.get("severity", "error"),
            )
            for r in data.get("rules", [])
        ]
        return OntologyConcept(
            name=data["name"],
            description=data.get("description", ""),
            parent=data.get("parent"),
            metric=data.get("metric"),
            variants=variants,
            rules=rules,
        )


@lru_cache(maxsize=1)
def get_ontology() -> OntologyParser:
    """Return the process-wide OntologyParser singleton."""
    parser = OntologyParser()
    parser.load()
    return parser
