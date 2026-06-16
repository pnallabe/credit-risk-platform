"""
intent_normalizer.py — IntentNormalizer

Converts a raw intent term (from the LLM's ``QueryIntent.metric`` field or
from synonym resolution) into:
  1. A canonical metric name (e.g. "DelinquencyRate")
  2. An ontology concept (e.g. OntologyConcept for "Delinquency")
  3. An optional variant (e.g. "30_DPD") if a severity keyword was detected

The normalizer is the bridge between Layer D (agent intent) and Layer B
(ontology concepts) — it runs deterministically with no LLM calls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from analytics_api.src.domain_ontology.concept import OntologyConcept
from analytics_api.src.domain_ontology.ontology_parser import OntologyParser, get_ontology
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.synonym_mapper import SynonymMapper

logger = logging.getLogger(__name__)

# Variant keywords → variant name suffix (matched against concept variants)
_VARIANT_PATTERNS = [
    (re.compile(r"\b90\s*dpd\b|\b90\s*days?\s*past\s*due\b", re.I), "90_DPD"),
    (re.compile(r"\b60\s*dpd\b|\b60\s*days?\s*past\s*due\b", re.I), "60_DPD"),
    (re.compile(r"\b30\s*dpd\b|\b30\s*days?\s*past\s*due\b", re.I), "30_DPD"),
    (re.compile(r"\bnet\s*charge[\s-]?off\b|\bnco\b", re.I), "NetChargeOff"),
    (re.compile(r"\bgross\s*charge[\s-]?off\b", re.I), "GrossChargeOff"),
    (re.compile(r"\bover\s*time\b|\btime[\s-]?series\b|\btrend\b|\bby\s+month\b|\bby\s+quarter\b", re.I), "ExposureOverTime"),
    (re.compile(r"\bby\s*fico\b|\bfico\s*tier\b", re.I), "ApprovalByFICO"),
    (re.compile(r"\bby\s*state\b|\bstate\b", re.I), "ApprovalByState"),
]


@dataclass
class NormalizedIntent:
    metric_name: Optional[str]          # e.g. "DelinquencyRate"
    concept: Optional[OntologyConcept]  # e.g. OntologyConcept("Delinquency")
    variant: Optional[str]              # e.g. "30_DPD"
    canonical_ref: Optional[str]        # e.g. "Loan.delinquency_rate"


class IntentNormalizer:
    """Normalize a free-text metric intent into a canonical metric + concept + variant.

    Example::

        normalizer = IntentNormalizer()

        result = normalizer.normalize("charge off rate for Q2")
        # NormalizedIntent(metric_name="ChargeOffRate",
        #                  concept=OntologyConcept("ChargeOff"),
        #                  variant="GrossChargeOff", ...)

        result = normalizer.normalize("90 DPD rate")
        # NormalizedIntent(metric_name="DelinquencyRate",
        #                  variant="90_DPD", ...)
    """

    def __init__(
        self,
        loader: Optional[SemanticLayerLoader] = None,
        ontology: Optional[OntologyParser] = None,
    ) -> None:
        self._loader = loader or get_loader()
        self._ontology = ontology or get_ontology()
        self._synonym_mapper = SynonymMapper(loader=self._loader)

    def normalize(self, term: str) -> NormalizedIntent:
        """Normalize a metric term or phrase into a structured NormalizedIntent."""
        # Step 1: detect variant from keywords
        variant = self._detect_variant(term)

        # Step 2: resolve canonical via synonym mapper
        canonical_ref = self._synonym_mapper.resolve(term)

        # Step 3: map canonical ref → metric name
        metric_name = self._canonical_to_metric(canonical_ref, term)

        # Step 4: map metric → concept
        concept: Optional[OntologyConcept] = None
        if metric_name:
            concept = self._ontology.find_by_metric(metric_name)
        if concept is None:
            concept = self._ontology.find_by_term(term)

        # Step 5: attempt direct metric name match if still unresolved
        if not metric_name:
            for m in self._loader.list_metrics():
                if m.name.lower() in term.lower() or term.lower() in m.name.lower():
                    metric_name = m.name
                    if concept is None:
                        concept = self._ontology.find_by_metric(m.name)
                    break

        return NormalizedIntent(
            metric_name=metric_name,
            concept=concept,
            variant=variant,
            canonical_ref=canonical_ref,
        )

    def detect_variant(self, term: str) -> Optional[str]:
        """Public wrapper around variant detection for use by the agent."""
        return self._detect_variant(term)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _detect_variant(self, term: str) -> Optional[str]:
        for pattern, variant_name in _VARIANT_PATTERNS:
            if pattern.search(term):
                return variant_name
        return None

    def _canonical_to_metric(
        self, canonical_ref: Optional[str], original_term: str
    ) -> Optional[str]:
        """Map a canonical synonym ref (e.g. 'Loan.charge_off_rate') to a metric name."""
        if not canonical_ref:
            return None

        # Direct metric name match (e.g. canonical_ref IS a metric name)
        try:
            self._loader.get_metric(canonical_ref)
            return canonical_ref
        except Exception:
            pass

        # Attribute-based mapping: "Loan.delinquency_rate" → "DelinquencyRate"
        attr_part = canonical_ref.split(".")[-1] if "." in canonical_ref else canonical_ref
        # Try to find a metric whose name is a camelCase version of the attr
        for m in self._loader.list_metrics():
            if m.name.lower().replace("_", "") == attr_part.lower().replace("_", ""):
                return m.name
            if attr_part.lower() in m.name.lower():
                return m.name

        return None
