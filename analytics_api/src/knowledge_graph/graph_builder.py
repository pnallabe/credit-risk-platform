"""
graph_builder.py — KnowledgeGraphBuilder

Constructs the NetworkX DiGraph from the three layers of definitions:
  - Layer A: entities, attributes, metrics, relationships (SemanticLayerLoader)
  - Layer B: concepts, IS-A hierarchy (OntologyParser)

Run once at startup. The resulting graph is held in KnowledgeGraphStore.
"""
from __future__ import annotations

import logging
from typing import Optional

import networkx as nx

from analytics_api.src.domain_ontology.ontology_parser import OntologyParser, get_ontology
from analytics_api.src.knowledge_graph.graph_model import EdgeType, NodeType
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """Build the full knowledge graph from semantic + ontology definitions.

    Example::

        builder = KnowledgeGraphBuilder()
        G = builder.build()
        # → nx.DiGraph with ENTITY, ATTRIBUTE, SOURCE, METRIC, CONCEPT nodes
    """

    def __init__(
        self,
        loader: Optional[SemanticLayerLoader] = None,
        ontology: Optional[OntologyParser] = None,
    ) -> None:
        self._loader = loader or get_loader()
        self._ontology = ontology or get_ontology()

    def build(self) -> nx.DiGraph:
        G: nx.DiGraph = nx.DiGraph()
        self._add_entities(G)
        self._add_metrics(G)
        self._add_relationships(G)
        self._add_concepts(G)
        logger.info(
            "KnowledgeGraphBuilder: %d nodes, %d edges",
            G.number_of_nodes(),
            G.number_of_edges(),
        )
        return G

    # ------------------------------------------------------------------
    # Node/edge builders
    # ------------------------------------------------------------------

    def _add_node(self, G: nx.DiGraph, node_id: str, node_type: NodeType, label: str, **meta) -> None:
        G.add_node(node_id, node_type=node_type.value, label=label, **meta)

    def _add_edge(self, G: nx.DiGraph, from_id: str, to_id: str, edge_type: EdgeType, **meta) -> None:
        G.add_edge(from_id, to_id, edge_type=edge_type.value, **meta)

    # ------------------------------------------------------------------
    # Entity + attribute + source nodes
    # ------------------------------------------------------------------

    def _add_entities(self, G: nx.DiGraph) -> None:
        for entity in self._loader.list_entities():
            entity_id = entity.name
            self._add_node(G, entity_id, NodeType.ENTITY, entity.name,
                           description=entity.description,
                           primary_key=entity.primary_key)

            # Source nodes for each physical table the entity maps to
            for source in entity.sources:
                source_id = f"source:{source.name}"
                if not G.has_node(source_id):
                    self._add_node(G, source_id, NodeType.SOURCE, source.name,
                                   join_key=source.join_key,
                                   freshness_sla_hours=source.freshness_sla_hours)

            # Attribute nodes
            for attr_name, attr in entity.attributes.items():
                attr_id = f"{entity.name}.{attr_name}"
                self._add_node(G, attr_id, NodeType.ATTRIBUTE, attr_id,
                               attr_type=attr.type,
                               description=attr.description,
                               allowed_values=attr.allowed_values)
                # ENTITY → ATTRIBUTE edge
                self._add_edge(G, entity_id, attr_id, EdgeType.HAS_ATTRIBUTE)

                # ATTRIBUTE → SOURCE edges (one per mapping)
                for source_name, physical_col in attr.mappings.items():
                    source_id = f"source:{source_name}"
                    if not G.has_node(source_id):
                        self._add_node(G, source_id, NodeType.SOURCE, source_name)
                    self._add_edge(G, attr_id, source_id, EdgeType.MAPS_TO_SOURCE,
                                   physical_column=physical_col)

    # ------------------------------------------------------------------
    # Metric nodes
    # ------------------------------------------------------------------

    def _add_metrics(self, G: nx.DiGraph) -> None:
        for metric in self._loader.list_metrics():
            metric_id = f"metric:{metric.name}"
            self._add_node(G, metric_id, NodeType.METRIC, metric.name,
                           category=metric.category,
                           unit=metric.unit,
                           preferred_source=metric.preferred_source)

            # ATTRIBUTE → METRIC edges for each required attribute
            for attr_ref in metric.required_attributes:
                parts = attr_ref.split(".", 1)
                if len(parts) == 2:
                    attr_id = attr_ref
                else:
                    # Best-effort: search all entities for this attr
                    attr_id = None
                    for entity in self._loader.list_entities():
                        if attr_ref in entity.attributes:
                            attr_id = f"{entity.name}.{attr_ref}"
                            break
                if attr_id and G.has_node(attr_id):
                    self._add_edge(G, attr_id, metric_id, EdgeType.USED_BY_METRIC)

    # ------------------------------------------------------------------
    # Relationship edges (ENTITY → ENTITY)
    # ------------------------------------------------------------------

    def _add_relationships(self, G: nx.DiGraph) -> None:
        for rel in self._loader.get_relationships():
            from_id = rel.from_entity
            to_id = rel.to_entity
            if G.has_node(from_id) and G.has_node(to_id):
                self._add_edge(G, from_id, to_id, EdgeType.REFERENCES,
                               relationship_name=rel.name,
                               from_attribute=rel.from_attribute,
                               to_attribute=rel.to_attribute,
                               cardinality=rel.cardinality,
                               join_type=rel.join_type)

    # ------------------------------------------------------------------
    # Concept nodes and ontology hierarchy
    # ------------------------------------------------------------------

    def _add_concepts(self, G: nx.DiGraph) -> None:
        for concept in self._ontology.list_concepts():
            concept_id = f"concept:{concept.name}"
            self._add_node(G, concept_id, NodeType.CONCEPT, concept.name,
                           metric=concept.metric)

            # METRIC → CONCEPT edge
            if concept.metric:
                metric_id = f"metric:{concept.metric}"
                if G.has_node(metric_id):
                    self._add_edge(G, metric_id, concept_id, EdgeType.HAS_CONCEPT)

            # IS-A edge to parent concept
            if concept.parent:
                parent_id = f"concept:{concept.parent}"
                if not G.has_node(parent_id):
                    self._add_node(G, parent_id, NodeType.CONCEPT, concept.parent)
                self._add_edge(G, concept_id, parent_id, EdgeType.IS_A)
