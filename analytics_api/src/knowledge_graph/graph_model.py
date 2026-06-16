"""
graph_model.py — Knowledge Graph node/edge type definitions

The graph uses NetworkX DiGraph. Nodes are identified by a string ID and carry
a ``node_type`` attribute. Edges carry an ``edge_type`` attribute.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class NodeType(str, Enum):
    ENTITY = "ENTITY"           # canonical entity (Loan, Customer, Transaction)
    ATTRIBUTE = "ATTRIBUTE"     # canonical attribute (Loan.fico_score)
    SOURCE = "SOURCE"           # physical BQ table (credit_risk.personal_loans_funded)
    METRIC = "METRIC"           # named metric (DelinquencyRate)
    CONCEPT = "CONCEPT"         # ontology concept (Delinquency)


class EdgeType(str, Enum):
    HAS_ATTRIBUTE = "HAS_ATTRIBUTE"     # ENTITY → ATTRIBUTE
    MAPS_TO_SOURCE = "MAPS_TO_SOURCE"   # ATTRIBUTE → SOURCE
    REFERENCES = "REFERENCES"           # ENTITY → ENTITY (FK join)
    USED_BY_METRIC = "USED_BY_METRIC"  # ATTRIBUTE → METRIC
    SYNONYM_OF = "SYNONYM_OF"          # ATTRIBUTE → ATTRIBUTE (synonym)
    HAS_CONCEPT = "HAS_CONCEPT"        # METRIC → CONCEPT
    IS_A = "IS_A"                      # CONCEPT → CONCEPT (ontology hierarchy)


@dataclass
class GraphNode:
    id: str                             # unique node ID, e.g. "Loan.fico_score"
    node_type: NodeType
    label: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphEdge:
    from_node: str
    to_node: str
    edge_type: EdgeType
    metadata: Dict[str, Any] = field(default_factory=dict)
