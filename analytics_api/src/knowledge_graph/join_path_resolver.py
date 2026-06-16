"""
join_path_resolver.py — JoinPathResolver

Resolves the BigQuery JOIN chain needed to satisfy a multi-entity query.
Uses the RelationshipRegistry for entity-level BFS and the KnowledgeGraph
to verify that the physical source tables are actually joinable.

Also performs a simple cardinality estimate:
  one_to_one → safe (1:1)
  one_to_many → warn if joining in the many-end first (potential fan-out)
  many_to_many → always warn
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from analytics_api.src.knowledge_graph.graph_store import KnowledgeGraphStore, get_graph_store
from analytics_api.src.semantic.exceptions import NoJoinPathError
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader
from analytics_api.src.semantic.relationship_registry import (
    JoinStep,
    RelationshipRegistry,
)

logger = logging.getLogger(__name__)

BQ_PROJECT = "ai-risk-workflow"


@dataclass
class ResolvedJoin:
    """A single JOIN hop with BQ-qualified table references."""
    from_entity: str
    from_table_ref: str             # fully qualified BQ ref e.g. `ai-risk-workflow.credit_risk.x`
    from_column: str
    to_entity: str
    to_table_ref: str
    to_column: str
    join_type: str                  # LEFT | INNER
    cardinality: str                # one_to_one | one_to_many | many_to_many
    fan_out_warning: bool


class JoinPathResolver:
    """Resolve multi-entity queries into an ordered list of BQ JOIN operations.

    Example::

        resolver = JoinPathResolver()
        joins = resolver.resolve(
            from_entity="Customer",
            to_entities=["Loan", "Transaction"],
            source_map={"Customer": "credit_risk.personal_loan_applications",
                        "Loan": "credit_risk.personal_loans_funded",
                        "Transaction": "credit_risk.personal_loan_payments"}
        )
        sql_fragment = resolver.build_join_sql(joins)
    """

    def __init__(
        self,
        loader: Optional[SemanticLayerLoader] = None,
        graph: Optional[KnowledgeGraphStore] = None,
    ) -> None:
        self._loader = loader or get_loader()
        self._graph = graph or get_graph_store()
        self._rel_registry = RelationshipRegistry(loader=self._loader)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        from_entity: str,
        to_entities: List[str],
        source_map: Optional[Dict[str, str]] = None,
    ) -> List[ResolvedJoin]:
        """Resolve join path from ``from_entity`` through each entity in ``to_entities``.

        ``source_map`` maps entity names → preferred source table names.
        If omitted, the primary source for each entity is used.
        """
        source_map = source_map or {}
        self._fill_default_sources(from_entity, to_entities, source_map)

        joins: List[ResolvedJoin] = []
        current = from_entity
        visited = {from_entity}

        for target in to_entities:
            if target in visited:
                continue
            path = self._rel_registry.find_path(current, target)
            for step in path:
                resolved = self._resolve_step(step, source_map)
                joins.append(resolved)
                visited.add(step.to_entity)
            current = target

        return joins

    def build_join_sql(self, joins: List[ResolvedJoin]) -> str:
        """Return a newline-separated BQ JOIN clause string from resolved joins."""
        lines: List[str] = []
        for j in joins:
            from_table = j.from_table_ref.strip("`").split(".")[-1]
            to_table = j.to_table_ref.strip("`").split(".")[-1]
            lines.append(
                f"{j.join_type} JOIN {j.to_table_ref} AS {to_table} "
                f"ON {from_table}.{j.from_column} = {to_table}.{j.to_column}"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fill_default_sources(
        self,
        from_entity: str,
        to_entities: List[str],
        source_map: Dict[str, str],
    ) -> None:
        all_entities = [from_entity] + to_entities
        for entity_name in all_entities:
            if entity_name not in source_map:
                try:
                    entity = self._loader.get_entity(entity_name)
                    if entity.sources:
                        source_map[entity_name] = entity.sources[0].name
                except Exception:
                    pass

    def _resolve_step(
        self, step: JoinStep, source_map: Dict[str, str]
    ) -> ResolvedJoin:
        from_source = source_map.get(step.from_entity, "")
        to_source = source_map.get(step.to_entity, "")

        if not to_source:
            raise NoJoinPathError(
                f"No source table found for entity '{step.to_entity}' in source_map"
            )

        from_ref = self._to_bq_ref(from_source) if from_source else step.from_entity
        to_ref = self._to_bq_ref(to_source)

        # Cardinality and fan-out warning
        rel = self._rel_registry.get(step.relationship_name)
        fan_out = rel.cardinality in ("one_to_many", "many_to_many")
        if fan_out:
            logger.debug(
                "JoinPathResolver: potential fan-out on %s → %s (%s)",
                step.from_entity,
                step.to_entity,
                rel.cardinality,
            )

        return ResolvedJoin(
            from_entity=step.from_entity,
            from_table_ref=from_ref,
            from_column=step.from_attribute,
            to_entity=step.to_entity,
            to_table_ref=to_ref,
            to_column=step.to_attribute,
            join_type=step.join_type,
            cardinality=rel.cardinality,
            fan_out_warning=fan_out,
        )

    @staticmethod
    def _to_bq_ref(source_name: str) -> str:
        dataset, table = source_name.split(".", 1)
        return f"`{BQ_PROJECT}.{dataset}.{table}`"
