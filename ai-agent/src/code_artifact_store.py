"""
code_artifact_store.py — Prompt 19-A / OV-02
Persist per-answer code artifacts (SQL / Python) alongside their cryptographic
fingerprints. The store is append-only; no UPDATE or DELETE is permitted at
the application layer.

OV-02: Migrated from sqlite3 to SQLAlchemy async (asyncpg / aiosqlite).
"""
from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from dataclasses import dataclass

from sqlalchemy import text as _sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# ---------------------------------------------------------------------------
# Engine cache (one engine per normalized URL)
# ---------------------------------------------------------------------------
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SCHEMA_DONE: set[str] = set()


def _normalize_url(url: str) -> str:
    """Normalise db_url to a fully-qualified SQLAlchemy async URL."""
    if not url:
        raise ValueError("db_url must not be empty.")
    if "://" not in url:
        return f"sqlite+aiosqlite:///{url}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite+"):
        return "sqlite+aiosqlite" + url[6:]
    return url


def _get_engine(db_url: str) -> AsyncEngine:
    norm = _normalize_url(db_url)
    if norm not in _ENGINE_CACHE:
        _ENGINE_CACHE[norm] = create_async_engine(norm, echo=False)
    return _ENGINE_CACHE[norm]


_CREATE_ARTIFACTS_TABLE = """
CREATE TABLE IF NOT EXISTS agent_code_artifacts (
    artifact_id    TEXT    PRIMARY KEY,
    session_id     TEXT    NOT NULL,
    turn_id        TEXT    NOT NULL,
    artifact_type  TEXT    NOT NULL,
    content        TEXT    NOT NULL,
    content_hash   TEXT    NOT NULL,
    source_table   TEXT,
    partition_date TEXT,
    created_at     TEXT    NOT NULL,
    tenant_id      TEXT    NOT NULL DEFAULT 'default'
)
"""


async def _ensure_schema(db_url: str) -> None:
    norm = _normalize_url(db_url)
    if norm in _SCHEMA_DONE:
        return
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(_sa_text(_CREATE_ARTIFACTS_TABLE))
    _SCHEMA_DONE.add(norm)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------
@dataclass
class CodeArtifact:
    artifact_id: str
    session_id: str
    turn_id: str
    artifact_type: Literal["sql", "python"]
    content: str
    content_hash: str       # SHA-256 hex of content
    source_table: Optional[str]
    partition_date: Optional[str]
    created_at: str
    tenant_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _extract_source_table(sql: str) -> Optional[str]:
    """Best-effort: return first table name following FROM or JOIN."""
    match = re.search(r'\b(?:FROM|JOIN)\s+([`"\[]?[\w.]+[`"\]]?)', sql, re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).strip('`"[]')
    # Strip schema prefix e.g. schema.table -> table
    if "." in name:
        name = name.split(".")[-1]
    return name or None


def _mapping_to_artifact(row) -> CodeArtifact:
    return CodeArtifact(
        artifact_id=row["artifact_id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        artifact_type=row["artifact_type"],
        content=row["content"],
        content_hash=row["content_hash"],
        source_table=row["source_table"],
        partition_date=row["partition_date"],
        created_at=row["created_at"],
        tenant_id=row.get("tenant_id", "default"),
    )


# ---------------------------------------------------------------------------
# Public async API (OV-02: native async SQLAlchemy, no asyncio.to_thread)
# ---------------------------------------------------------------------------
async def store_artifact(
    db_url: str,
    session_id: str,
    turn_id: str,
    artifact_type: Literal["sql", "python"],
    content: str,
    tenant_id: str,
    source_table: Optional[str] = None,
    partition_date: Optional[str] = None,
) -> CodeArtifact:
    """
    Compute content_hash = SHA-256(content), assign a new UUID4 artifact_id,
    insert a row, and return the CodeArtifact dataclass.
    Raises ValueError if artifact_type is not 'sql' or 'python'.
    """
    if artifact_type not in ("sql", "python"):
        raise ValueError(f"artifact_type must be 'sql' or 'python', got: {artifact_type!r}")

    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    artifact_id = str(uuid.uuid4())
    content_hash = _sha256(content)
    if source_table is None:
        source_table = _extract_source_table(content)
    created_at = datetime.now(timezone.utc).isoformat()

    async with engine.begin() as conn:
        await conn.execute(
            _sa_text("""
                INSERT INTO agent_code_artifacts
                    (artifact_id, session_id, turn_id, artifact_type, content,
                     content_hash, source_table, partition_date, created_at, tenant_id)
                VALUES
                    (:artifact_id, :session_id, :turn_id, :artifact_type, :content,
                     :content_hash, :source_table, :partition_date, :created_at, :tenant_id)
            """),
            {
                "artifact_id": artifact_id, "session_id": session_id,
                "turn_id": turn_id, "artifact_type": artifact_type,
                "content": content, "content_hash": content_hash,
                "source_table": source_table, "partition_date": partition_date,
                "created_at": created_at, "tenant_id": tenant_id,
            },
        )

    return CodeArtifact(
        artifact_id=artifact_id,
        session_id=session_id,
        turn_id=turn_id,
        artifact_type=artifact_type,
        content=content,
        content_hash=content_hash,
        source_table=source_table,
        partition_date=partition_date,
        created_at=created_at,
        tenant_id=tenant_id,
    )


async def get_artifacts_for_turn(
    db_url: str,
    turn_id: str,
) -> list[CodeArtifact]:
    """Return all artifacts for a given turn_id ordered by created_at ASC."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            _sa_text(
                "SELECT * FROM agent_code_artifacts "
                "WHERE turn_id = :turn_id ORDER BY created_at ASC"
            ),
            {"turn_id": turn_id},
        )
        rows = result.mappings().all()
    return [_mapping_to_artifact(r) for r in rows]


async def get_artifacts_for_session(
    db_url: str,
    session_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list[CodeArtifact]:
    """
    Return all artifacts for a session optionally filtered by created_at
    ISO date range [from_date, to_date] (both inclusive, both optional).
    """
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    conditions = ["session_id = :session_id"]
    params: dict = {"session_id": session_id}
    if from_date:
        conditions.append("created_at >= :from_date")
        params["from_date"] = from_date
    if to_date:
        conditions.append("created_at <= :to_date")
        params["to_date"] = to_date

    sql = (
        f"SELECT * FROM agent_code_artifacts WHERE {' AND '.join(conditions)}"
        " ORDER BY created_at ASC"
    )

    async with engine.connect() as conn:
        result = await conn.execute(_sa_text(sql), params)
        rows = result.mappings().all()
    return [_mapping_to_artifact(r) for r in rows]


async def get_artifact(
    db_url: str,
    artifact_id: str,
) -> Optional[CodeArtifact]:
    """Return a single artifact by artifact_id or None if not found."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            _sa_text("SELECT * FROM agent_code_artifacts WHERE artifact_id = :artifact_id"),
            {"artifact_id": artifact_id},
        )
        row = result.mappings().first()
    return _mapping_to_artifact(row) if row else None


async def get_artifact_history(
    db_url: str,
    session_id: str,
    tenant_id: str,
) -> list[CodeArtifact]:
    """Return all artifacts for a session ordered by created_at ASC."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    sql = (
        "SELECT * FROM agent_code_artifacts WHERE session_id = :session_id AND tenant_id = :tenant_id "
        "ORDER BY created_at ASC"
    )

    async with engine.connect() as conn:
        result = await conn.execute(_sa_text(sql), {"session_id": session_id, "tenant_id": tenant_id})
        rows = result.mappings().all()
    return [_mapping_to_artifact(r) for r in rows]
