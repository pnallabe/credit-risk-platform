"""
synonym_resolver.py — GraphSynonymResolver

Uses the knowledge graph SYNONYM_OF edges plus Jaccard similarity on node
labels to resolve colloquial terms to canonical attribute or metric node IDs.

This supplements SynonymMapper (which uses YAML-defined synonyms) with
graph-structural similarity — e.g., if two attributes share many source
mappings, they are likely semantically related.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional

from analytics_api.src.knowledge_graph.graph_model import EdgeType, NodeType
from analytics_api.src.knowledge_graph.graph_store import KnowledgeGraphStore, get_graph_store

logger = logging.getLogger(__name__)

_TOKENIZE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set:
    return set(_TOKENIZE.findall(text.lower()))


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class GraphSynonymResolver:
    """Resolve terms to canonical node IDs via graph structure + Jaccard fallback.

    Example::

        resolver = GraphSynonymResolver()
        node_id = resolver.resolve("FICO score")
        # → "Customer.fico_score"

        node_id = resolver.resolve("bad debt rate")
        # → "Loan.charge_off_rate"
    """

    JACCARD_THRESHOLD = 0.40   # slightly lower than SynonymMapper since we're matching node labels

    def __init__(self, store: Optional[KnowledgeGraphStore] = None) -> None:
        self._store = store or get_graph_store()
        self._label_index: Dict[str, str] = {}    # lower label → node_id
        self._token_index: Dict[str, set] = {}    # node_id → token set
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, term: str) -> Optional[str]:
        """Return the best-matching node ID for a term, or None."""
        self._ensure_built()
        key = term.lower().strip()

        # 1. Exact label match
        if key in self._label_index:
            return self._label_index[key]

        # 2. Substring match on labels
        best_len, best_id = 0, None
        for label, node_id in self._label_index.items():
            if label in key and len(label) > best_len:
                best_len = len(label)
                best_id = node_id
        if best_id:
            return best_id

        # 3. Jaccard fallback on node labels
        key_tokens = _tokens(key)
        best_score, best_fuzzy = 0.0, None
        for node_id, node_tokens in self._token_index.items():
            score = _jaccard(key_tokens, node_tokens)
            if score > best_score and score >= self.JACCARD_THRESHOLD:
                best_score = score
                best_fuzzy = node_id
        if best_fuzzy:
            logger.debug(
                "GraphSynonymResolver fuzzy: '%s' → '%s' (score=%.2f)",
                term, best_fuzzy, best_score
            )
            return best_fuzzy

        return None

    def resolve_all(self, text: str) -> Dict[str, str]:
        """Scan free text and return all matched {term → node_id} pairs."""
        self._ensure_built()
        text_lower = text.lower()
        results: Dict[str, str] = {}
        matches = []
        for label, node_id in self._label_index.items():
            if label in text_lower:
                matches.append((len(label), label, node_id))
        matches.sort(reverse=True)
        covered: set = set()
        for length, label, node_id in matches:
            start = text_lower.find(label)
            positions = set(range(start, start + length))
            if not positions & covered:
                results[label] = node_id
                covered.update(positions)
        return results

    def get_synonyms(self, node_id: str) -> List[str]:
        """Return all node IDs connected to this node via SYNONYM_OF edges."""
        self._ensure_built()
        G = self._store.graph
        if not G.has_node(node_id):
            return []
        return [
            nbr for nbr in G.successors(node_id)
            if G.edges[node_id, nbr].get("edge_type") == EdgeType.SYNONYM_OF.value
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            G = self._store.graph
            for node_id, data in G.nodes(data=True):
                label = data.get("label", node_id)
                label_lower = label.lower()
                self._label_index[label_lower] = node_id
                self._token_index[node_id] = _tokens(label)
                # Also index last segment: "Loan.fico_score" → "fico score"
                if "." in node_id:
                    short = node_id.split(".")[-1].replace("_", " ")
                    self._label_index[short.lower()] = node_id
            self._built = True
            logger.debug("GraphSynonymResolver: indexed %d node labels", len(self._label_index))
