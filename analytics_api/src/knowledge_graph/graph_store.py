"""
graph_store.py — KnowledgeGraphStore

Wraps the NetworkX DiGraph built by KnowledgeGraphBuilder and exposes
high-level query methods used by the agent pipeline.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import networkx as nx

from analytics_api.src.knowledge_graph.graph_model import EdgeType, NodeType

logger = logging.getLogger(__name__)


class KnowledgeGraphStore:
    """Query interface over the knowledge graph.

    Example::

        store = KnowledgeGraphStore()
        store.build()

        # Find metrics that use a particular attribute
        metrics = store.get_metrics_using_attribute("Loan.delinquency_rate")
        # → ["metric:DelinquencyRate"]

        # Check if two sources are joinable
        path = store.find_source_path(
            "credit_risk.personal_loans_funded",
            "credit_risk.loan_monthly_ledger"
        )
    """

    def __init__(self, graph: Optional[nx.DiGraph] = None) -> None:
        self._g: Optional[nx.DiGraph] = graph
        self._built = graph is not None

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        if self._built:
            return
        from analytics_api.src.knowledge_graph.graph_builder import KnowledgeGraphBuilder
        builder = KnowledgeGraphBuilder()
        self._g = builder.build()
        self._built = True

    @property
    def graph(self) -> nx.DiGraph:
        self._ensure_built()
        return self._g  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Node queries
    # ------------------------------------------------------------------

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_built()
        if self._g.has_node(node_id):
            return dict(self._g.nodes[node_id])
        return None

    def list_nodes_by_type(self, node_type: NodeType) -> List[str]:
        self._ensure_built()
        return [
            n for n, d in self._g.nodes(data=True)
            if d.get("node_type") == node_type.value
        ]

    # ------------------------------------------------------------------
    # Attribute → Metric
    # ------------------------------------------------------------------

    def get_metrics_using_attribute(self, attr_id: str) -> List[str]:
        """Return metric node IDs that depend on the given attribute node."""
        self._ensure_built()
        return [
            nbr for nbr in self._g.successors(attr_id)
            if self._g.nodes[nbr].get("node_type") == NodeType.METRIC.value
        ]

    # ------------------------------------------------------------------
    # Entity join paths (REFERENCES edges)
    # ------------------------------------------------------------------

    def find_entity_path(
        self, from_entity: str, to_entity: str
    ) -> Optional[List[str]]:
        """Return shortest entity-to-entity path via REFERENCES edges, or None."""
        self._ensure_built()
        # Build a subgraph of only ENTITY nodes and REFERENCES edges
        ref_edges = [
            (u, v) for u, v, d in self._g.edges(data=True)
            if d.get("edge_type") == EdgeType.REFERENCES.value
        ]
        sub = nx.DiGraph()
        sub.add_edges_from(ref_edges)
        # Make bidirectional so BFS works regardless of FK direction
        sub.add_edges_from([(v, u) for u, v in ref_edges])
        try:
            path = nx.shortest_path(sub, from_entity, to_entity)
            return path
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    # ------------------------------------------------------------------
    # Source path (attribute → source table)
    # ------------------------------------------------------------------

    def find_source_path(self, source_a: str, source_b: str) -> Optional[List[str]]:
        """Return a join path between two source tables via their shared entities."""
        self._ensure_built()
        source_a_id = f"source:{source_a}"
        source_b_id = f"source:{source_b}"
        if not self._g.has_node(source_a_id) or not self._g.has_node(source_b_id):
            return None
        # Find entities connected to each source
        def entities_for_source(source_id: str) -> Set[str]:
            return {
                pred for pred in self._g.predecessors(source_id)
                if self._g.nodes.get(pred, {}).get("node_type") == NodeType.ATTRIBUTE.value
                for ent in self._g.predecessors(pred)
                if self._g.nodes.get(ent, {}).get("node_type") == NodeType.ENTITY.value
            }

        ents_a = entities_for_source(source_a_id)
        ents_b = entities_for_source(source_b_id)
        # If they share an entity, they're directly joinable
        if ents_a & ents_b:
            return [source_a, list(ents_a & ents_b)[0], source_b]
        return None

    # ------------------------------------------------------------------
    # Serialize / deserialize (for caching)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        self._ensure_built()
        data = nx.node_link_data(self._g)
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "KnowledgeGraphStore":
        data = json.loads(json_str)
        G = nx.node_link_graph(data)
        return cls(graph=G)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json())
        logger.info("KnowledgeGraphStore: saved to %s", path)

    @classmethod
    def load(cls, path: Path) -> "KnowledgeGraphStore":
        store = cls.from_json(path.read_text())
        logger.info("KnowledgeGraphStore: loaded from %s", path)
        return store

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            self.build()


@lru_cache(maxsize=1)
def get_graph_store() -> KnowledgeGraphStore:
    """Return the process-wide KnowledgeGraphStore singleton."""
    store = KnowledgeGraphStore()
    store.build()
    return store
