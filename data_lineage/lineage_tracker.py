"""
data_lineage/lineage_tracker.py
================================
Source → transform → feature → model provenance captured as an append-only DAG.

DDL creates two tables: ``lineage_nodes`` and ``lineage_edges``.

Public API
----------
>>> from data_lineage.lineage_tracker import (
...     LineageNode, LineageEdge, DataLineageReport,
...     record_node, record_edge, get_lineage_graph, export_lineage_report,
... )
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Shared engine cache (same pattern as audit.logger)
# ---------------------------------------------------------------------------
try:
    from audit.logger import _ENGINE_CACHE, _get_engine  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _ENGINE_CACHE: dict = {}  # type: ignore[assignment]

    def _get_engine(db_url: str):  # type: ignore[return]
        if db_url not in _ENGINE_CACHE:
            _ENGINE_CACHE[db_url] = create_async_engine(db_url, echo=False)
        return _ENGINE_CACHE[db_url]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_NODES = """
CREATE TABLE IF NOT EXISTS lineage_nodes (
    node_id     TEXT PRIMARY KEY,
    node_type   TEXT NOT NULL,
    name        TEXT NOT NULL,
    version     TEXT NOT NULL,
    schema_hash TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ln_type_name_ver
    ON lineage_nodes (node_type, name, version);
"""

_CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS lineage_edges (
    edge_id               TEXT PRIMARY KEY,
    from_node_id          TEXT NOT NULL,
    to_node_id            TEXT NOT NULL,
    transform_description TEXT NOT NULL DEFAULT '',
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_le_from ON lineage_edges (from_node_id);
CREATE INDEX IF NOT EXISTS idx_le_to   ON lineage_edges (to_node_id);
"""

_UPSERT_NODE = """
INSERT INTO lineage_nodes (node_id, node_type, name, version, schema_hash, created_at)
VALUES (:node_id, :node_type, :name, :version, :schema_hash, :created_at)
ON CONFLICT (node_type, name, version) DO NOTHING
"""

_INSERT_EDGE = """
INSERT OR IGNORE INTO lineage_edges (edge_id, from_node_id, to_node_id, transform_description, created_at)
VALUES (:edge_id, :from_node_id, :to_node_id, :transform_description, :created_at)
"""

_SELECT_NODE_BY_NAME = """
SELECT node_id, node_type, name, version, schema_hash, created_at
FROM lineage_nodes
WHERE name = :name
LIMIT 1
"""

_SELECT_ALL_NODES = """
SELECT node_id, node_type, name, version, schema_hash, created_at
FROM lineage_nodes
ORDER BY created_at ASC
"""

_SELECT_ALL_EDGES = """
SELECT edge_id, from_node_id, to_node_id, transform_description, created_at
FROM lineage_edges
ORDER BY created_at ASC
"""

_SELECT_EDGES_FROM = """
SELECT edge_id, from_node_id, to_node_id, transform_description, created_at
FROM lineage_edges
WHERE from_node_id = :node_id OR to_node_id = :node_id
"""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LineageNode:
    """Represents a single entity in the data lineage DAG."""

    node_id: str
    node_type: str      # "source" | "transform" | "feature" | "model"
    name: str
    version: str
    schema_hash: str    # sha256 of the column-list
    created_at: str     # ISO-8601 UTC


@dataclass
class LineageEdge:
    """A directed edge from one LineageNode to another."""

    edge_id: str
    from_node_id: str
    to_node_id: str
    transform_description: str
    created_at: str


@dataclass
class DataLineageReport:
    """Full lineage report returned by export_lineage_report()."""

    generated_at: str
    node_count: int
    nodes: List[LineageNode] = field(default_factory=list)
    edges: List[LineageEdge] = field(default_factory=list)
    data_dictionary: Dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_schema(db_url: str) -> None:
    """Create tables if they do not yet exist."""
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        for ddl in (_CREATE_NODES, _CREATE_EDGES):
            for stmt in ddl.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))


def _row_to_node(row: Any) -> LineageNode:
    return LineageNode(
        node_id=row["node_id"],
        node_type=row["node_type"],
        name=row["name"],
        version=row["version"],
        schema_hash=row["schema_hash"],
        created_at=row["created_at"],
    )


def _row_to_edge(row: Any) -> LineageEdge:
    return LineageEdge(
        edge_id=row["edge_id"],
        from_node_id=row["from_node_id"],
        to_node_id=row["to_node_id"],
        transform_description=row["transform_description"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def record_node(node: LineageNode, db_url: str) -> str:
    """Upsert *node* keyed by (node_type, name, version).

    Returns the node_id actually stored.
    """
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(_UPSERT_NODE),
            {
                "node_id":     node.node_id,
                "node_type":   node.node_type,
                "name":        node.name,
                "version":     node.version,
                "schema_hash": node.schema_hash,
                "created_at":  node.created_at,
            },
        )
        # Look up the canonical node_id (could be pre-existing)
        result = await conn.execute(
            text(
                "SELECT node_id FROM lineage_nodes "
                "WHERE node_type=:t AND name=:n AND version=:v"
            ),
            {"t": node.node_type, "n": node.name, "v": node.version},
        )
        row = result.fetchone()
        return row[0] if row else node.node_id


async def record_edge(edge: LineageEdge, db_url: str) -> str:
    """Insert *edge* (idempotent by edge_id).  Returns ``edge_id``."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(_INSERT_EDGE),
            {
                "edge_id":               edge.edge_id,
                "from_node_id":          edge.from_node_id,
                "to_node_id":            edge.to_node_id,
                "transform_description": edge.transform_description,
                "created_at":            edge.created_at,
            },
        )
    return edge.edge_id


async def get_lineage_graph(root_node_name: str, db_url: str) -> Dict[str, Any]:
    """Return a subgraph dict reachable from *root_node_name*.

    Returns ``{"nodes": [...], "edges": [...]}`` where each entry is a plain dict.
    """
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        # Find root node
        result = await conn.execute(text(_SELECT_NODE_BY_NAME), {"name": root_node_name})
        root_row = result.fetchone()
        if not root_row:
            return {"nodes": [], "edges": []}

        # BFS over edges
        visited_nodes: Dict[str, Dict] = {}
        visited_edges: Dict[str, Dict] = {}
        queue = [root_row[0]]  # node_ids to visit

        while queue:
            nid = queue.pop(0)
            if nid in visited_nodes:
                continue
            # Load node details
            nr = await conn.execute(
                text("SELECT node_id, node_type, name, version, schema_hash, created_at FROM lineage_nodes WHERE node_id=:nid"),
                {"nid": nid},
            )
            node_row = nr.fetchone()
            if node_row:
                visited_nodes[nid] = dict(zip(["node_id", "node_type", "name", "version", "schema_hash", "created_at"], node_row))
            # Expand edges
            er = await conn.execute(text(_SELECT_EDGES_FROM), {"node_id": nid})
            for erow in er.fetchall():
                eid = erow[0]
                if eid not in visited_edges:
                    visited_edges[eid] = dict(zip(["edge_id", "from_node_id", "to_node_id", "transform_description", "created_at"], erow))
                    # Enqueue both ends
                    for neighbour in (erow[1], erow[2]):
                        if neighbour not in visited_nodes:
                            queue.append(neighbour)

    return {
        "nodes": list(visited_nodes.values()),
        "edges": list(visited_edges.values()),
    }


async def export_lineage_report(tenant_id: str, db_url: str) -> DataLineageReport:
    """Return a full DataLineageReport for all recorded lineage nodes/edges.

    *tenant_id* is accepted for API symmetry but the current SQLite store is
    not tenant-partitioned (all lineage records are platform-wide).
    """
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        nr = await conn.execute(text(_SELECT_ALL_NODES))
        nodes = [_row_to_node(r) for r in nr.mappings().fetchall()]

        er = await conn.execute(text(_SELECT_ALL_EDGES))
        edges = [_row_to_edge(r) for r in er.mappings().fetchall()]

    # Build a minimal data dictionary from node names
    data_dict: Dict[str, str] = {
        n.name: f"{n.node_type} (v{n.version}, schema_hash={n.schema_hash})"
        for n in nodes
    }

    return DataLineageReport(
        generated_at=datetime.now(timezone.utc).isoformat() + "Z",
        node_count=len(nodes),
        nodes=nodes,
        edges=edges,
        data_dictionary=data_dict,
    )
