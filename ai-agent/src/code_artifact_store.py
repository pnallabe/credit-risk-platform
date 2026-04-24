"""
code_artifact_store.py — Prompt 19-A
Persist per-answer code artifacts (SQL / Python) alongside their cryptographic
fingerprints. The store is append-only; no UPDATE or DELETE is permitted at
the application layer.
"""
from __future__ import annotations

import asyncio
import hashlib
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Module-level schema-init guard
# ---------------------------------------------------------------------------
_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALISED: set[str] = set()


def _strip_url_prefix(db_url: str) -> str:
    """Convert 'sqlite:///foo.db' -> 'foo.db', pass bare filenames unchanged."""
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    return db_url


def _ensure_schema(db_url: str) -> None:
    db_path = _strip_url_prefix(db_url)
    with _SCHEMA_INIT_LOCK:
        if db_path in _SCHEMA_INITIALISED:
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_code_artifacts (
                    artifact_id    TEXT    PRIMARY KEY,
                    session_id     TEXT    NOT NULL,
                    turn_id        TEXT    NOT NULL,
                    artifact_type  TEXT    NOT NULL,
                    content        TEXT    NOT NULL,
                    content_hash   TEXT    NOT NULL,
                    source_table   TEXT,
                    partition_date TEXT,
                    created_at     TEXT    NOT NULL
                )
            """)
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_INITIALISED.add(db_path)


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


def _row_to_artifact(row: sqlite3.Row) -> CodeArtifact:
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
    )


# ---------------------------------------------------------------------------
# Synchronous inner functions (run in thread)
# ---------------------------------------------------------------------------
def _sync_store_artifact(
    db_path: str,
    session_id: str,
    turn_id: str,
    artifact_type: Literal["sql", "python"],
    content: str,
    source_table: Optional[str],
    partition_date: Optional[str],
) -> CodeArtifact:
    _ensure_schema(db_path)
    if artifact_type not in ("sql", "python"):
        raise ValueError(f"artifact_type must be 'sql' or 'python', got: {artifact_type!r}")

    artifact_id = str(uuid.uuid4())
    content_hash = _sha256(content)
    if source_table is None:
        source_table = _extract_source_table(content)
    created_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            INSERT INTO agent_code_artifacts
                (artifact_id, session_id, turn_id, artifact_type, content,
                 content_hash, source_table, partition_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (artifact_id, session_id, turn_id, artifact_type, content,
             content_hash, source_table, partition_date, created_at),
        )
        conn.commit()
    finally:
        conn.close()

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
    )


def _sync_get_for_turn(db_path: str, turn_id: str) -> list[CodeArtifact]:
    _ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM agent_code_artifacts WHERE turn_id = ? ORDER BY created_at ASC",
            (turn_id,),
        ).fetchall()
        return [_row_to_artifact(r) for r in rows]
    finally:
        conn.close()


def _sync_get_for_session(
    db_path: str,
    session_id: str,
    from_date: Optional[str],
    to_date: Optional[str],
) -> list[CodeArtifact]:
    _ensure_schema(db_path)
    query = "SELECT * FROM agent_code_artifacts WHERE session_id = ?"
    params: list = [session_id]
    if from_date:
        query += " AND created_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND created_at <= ?"
        params.append(to_date)
    query += " ORDER BY created_at ASC"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_artifact(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------
async def store_artifact(
    db_url: str,
    session_id: str,
    turn_id: str,
    artifact_type: Literal["sql", "python"],
    content: str,
    source_table: Optional[str] = None,
    partition_date: Optional[str] = None,
) -> CodeArtifact:
    """
    Compute content_hash = SHA-256(content), assign a new UUID4 artifact_id,
    insert a row, and return the CodeArtifact dataclass.
    Raises ValueError if artifact_type is not 'sql' or 'python'.
    """
    db_path = _strip_url_prefix(db_url)
    return await asyncio.to_thread(
        _sync_store_artifact,
        db_path, session_id, turn_id, artifact_type, content, source_table, partition_date,
    )


async def get_artifacts_for_turn(
    db_url: str,
    turn_id: str,
) -> list[CodeArtifact]:
    """Return all artifacts for a given turn_id ordered by created_at ASC."""
    db_path = _strip_url_prefix(db_url)
    return await asyncio.to_thread(_sync_get_for_turn, db_path, turn_id)


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
    db_path = _strip_url_prefix(db_url)
    return await asyncio.to_thread(
        _sync_get_for_session, db_path, session_id, from_date, to_date
    )
