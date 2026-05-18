"""
concept.py — Domain Ontology dataclasses

These are the typed in-memory representation of concepts loaded from
credit_risk_ontology.yaml. They are read-only after construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class ConceptVariant:
    name: str
    description: str
    filter_expression: str          # SQL fragment used to narrow the concept
    severity: Optional[str]         # moderate | high | critical | None


@dataclass(frozen=True)
class OntologyRule:
    id: str
    description: str
    expression: str                 # safe expression string, evaluated by RuleEngine
    severity: str                   # error | warning


@dataclass(frozen=True)
class OntologyConcept:
    name: str
    description: str
    parent: Optional[str]           # parent concept name, or None for root
    metric: Optional[str]           # associated MetricDefinition name, or None
    variants: List[ConceptVariant]
    rules: List[OntologyRule]
