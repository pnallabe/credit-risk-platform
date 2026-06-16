"""
relationship_registry.py — RelationshipRegistry

Maintains the entity relationship graph and provides:
  - ``find_path(from_entity, to_entity)`` — BFS shortest join path
  - ``build_join_sql(path, source_map)`` — produces a JOIN clause string

The registry is bidirectional: every relationship is indexed in both
directions so that path-finding works regardless of traversal order.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from analytics_api.src.semantic.exceptions import (
    NoJoinPathError,
    RelationshipNotFoundError,
)
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.schema import Relationship

logger = logging.getLogger(__name__)


@dataclass
class JoinStep:
    """One hop in a join path."""
    relationship_name: str
    from_entity: str
    from_attribute: str
    to_entity: str
    to_attribute: str
    join_type: str                  # INNER | LEFT | LEFT OUTER


class RelationshipRegistry:
    """Lookup and join-path resolution over entity relationships.

    Example::

        registry = RelationshipRegistry()
        path = registry.find_path("Customer", "Transaction")
        # [JoinStep(Customer→Loan via customer_id),
        #  JoinStep(Loan→Transaction via loan_id)]

        sql = registry.build_join_sql(
            path,
            source_map={"Customer": "credit_risk.personal_loan_applications",
                        "Loan": "credit_risk.personal_loans_funded",
                        "Transaction": "credit_risk.personal_loan_payments"}
        )
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()
        # adjacency: entity → [(rel_name, to_entity)]
        self._adj: Dict[str, List[Tuple[str, str]]] = {}
        self._rels: Dict[str, Relationship] = {}
        self._built = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, name: str) -> Relationship:
        """Return a relationship by name."""
        self._ensure_built()
        try:
            return self._rels[name]
        except KeyError:
            raise RelationshipNotFoundError(
                f"Relationship '{name}' not found. Available: {list(self._rels)}"
            )

    def list_all(self) -> List[Relationship]:
        self._ensure_built()
        return list(self._rels.values())

    def find_path(self, from_entity: str, to_entity: str) -> List[JoinStep]:
        """BFS shortest path between two entities.

        Returns an ordered list of JoinSteps that, when applied left-to-right,
        join ``from_entity`` to ``to_entity``.

        Raises ``NoJoinPathError`` if no path exists.
        """
        self._ensure_built()
        if from_entity == to_entity:
            return []

        visited: set = {from_entity}
        # queue items: (current_entity, path_so_far)
        queue: deque[Tuple[str, List[JoinStep]]] = deque([(from_entity, [])])

        while queue:
            current, path = queue.popleft()
            for rel_name, neighbor in self._adj.get(current, []):
                if neighbor in visited:
                    continue
                rel = self._rels[rel_name]
                # Determine direction of this hop
                if rel.from_entity == current:
                    step = JoinStep(
                        relationship_name=rel_name,
                        from_entity=rel.from_entity,
                        from_attribute=rel.from_attribute,
                        to_entity=rel.to_entity,
                        to_attribute=rel.to_attribute,
                        join_type=rel.join_type,
                    )
                else:
                    # Reverse traversal
                    step = JoinStep(
                        relationship_name=rel_name,
                        from_entity=rel.to_entity,
                        from_attribute=rel.to_attribute,
                        to_entity=rel.from_entity,
                        to_attribute=rel.from_attribute,
                        join_type=rel.join_type,
                    )
                new_path = path + [step]
                if neighbor == to_entity:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))

        raise NoJoinPathError(
            f"No join path from '{from_entity}' to '{to_entity}'. "
            f"Known entities: {list(self._adj)}"
        )

    def build_join_sql(
        self,
        path: List[JoinStep],
        source_map: Dict[str, str],
        bq_project: str = "ai-risk-workflow",
    ) -> str:
        """Convert a list of JoinSteps into a BQ-compatible JOIN clause string.

        ``source_map`` maps entity names → source table names (without project),
        e.g. ``{"Loan": "credit_risk.personal_loans_funded"}``.
        """
        if not path:
            return ""

        clauses: List[str] = []
        for step in path:
            to_source = source_map.get(step.to_entity)
            if not to_source:
                raise NoJoinPathError(
                    f"source_map has no entry for entity '{step.to_entity}'"
                )
            dataset, table = to_source.split(".", 1)
            full_ref = f"`{bq_project}.{dataset}.{table}`"

            from_source = source_map.get(step.from_entity, "")
            from_table = from_source.split(".")[-1] if from_source else step.from_entity.lower()
            to_table = table

            clauses.append(
                f"{step.join_type} JOIN {full_ref} AS {to_table} "
                f"ON {from_table}.{step.from_attribute} = {to_table}.{step.to_attribute}"
            )
        return "\n".join(clauses)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_built(self) -> None:
        if not self._built:
            for rel in self._loader.get_relationships():
                self._rels[rel.name] = rel
                # Forward edge
                self._adj.setdefault(rel.from_entity, []).append((rel.name, rel.to_entity))
                # Reverse edge (bidirectional)
                self._adj.setdefault(rel.to_entity, []).append((rel.name, rel.from_entity))
            self._built = True
            logger.debug(
                "RelationshipRegistry: %d relationships, %d entities",
                len(self._rels),
                len(self._adj),
            )
