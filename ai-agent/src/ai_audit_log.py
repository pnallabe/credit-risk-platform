"""
ai_audit_log.py — Prompt 20-A / OV-02
Append-only, cryptographically hash-chained audit log for every AI agent
query turn.  Implements GNRI-011 requirements.

APPEND-ONLY — no UPDATE or DELETE operations are permitted.

OV-02: Migrated from sqlite3 to SQLAlchemy async (asyncpg for PostgreSQL,
aiosqlite for SQLite in tests). The bare sqlite3 dependency is removed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text as _sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# ---------------------------------------------------------------------------
# Engine cache (one engine per db_url, same pattern as audit/logger.py)
# ---------------------------------------------------------------------------
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SCHEMA_DONE: set[str] = set()


def _normalize_url(url: str) -> str:
    """Normalise db_url to a fully-qualified SQLAlchemy URL.

    - Bare file path  → ``sqlite+aiosqlite:///path``
    - ``sqlite:///``  → ``sqlite+aiosqlite:///`` (adds async driver)
    - Everything else → passed through unchanged (e.g. ``postgresql+asyncpg://…``)
    """
    if not url:
        raise ValueError("db_url must not be empty.")
    if "://" not in url:
        # Bare file path
        return f"sqlite+aiosqlite:///{url}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite+"):
        return "sqlite+aiosqlite" + url[6:]
    return url


def _get_engine(db_url: str) -> AsyncEngine:
    norm = _normalize_url(db_url)
    if norm not in _ENGINE_CACHE:
        _ENGINE_CACHE[norm] = create_async_engine(norm, echo=False)
    return _ENGINE_CACHE[norm]


_CREATE_AI_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS ai_agent_audit_log (
    log_id              TEXT    PRIMARY KEY,
    session_id          TEXT    NOT NULL,
    turn_id             TEXT    NOT NULL UNIQUE,
    tenant_id           TEXT    NOT NULL DEFAULT 'default',
    persona             TEXT    NOT NULL,
    query_text          TEXT    NOT NULL,
    plan_text           TEXT,
    tools_called        TEXT,
    sql_executed        TEXT,
    result_hash         TEXT,
    query_hash          TEXT,
    code_artifact_ref   TEXT,
    confidence_score    REAL,
    confidence_label    TEXT,
    answer_text         TEXT,
    grounded            INTEGER NOT NULL DEFAULT 1,
    bq_job_id           TEXT,
    source_table        TEXT,
    partition_date      TEXT,
    logged_at           TEXT    NOT NULL,
    record_hash         TEXT    NOT NULL,
    previous_hash       TEXT    NOT NULL,
    hash_algorithm      TEXT    NOT NULL DEFAULT 'sha256',
    code_artifact_uris  TEXT,
    bq_job_ids          TEXT,
    code_zip_uri        TEXT,
    code_sha256_hashes  TEXT
)
"""

# Migration: add new array columns to existing DBs
_MIGRATION_STMTS = [
    "ALTER TABLE ai_agent_audit_log ADD COLUMN code_artifact_uris TEXT",
    "ALTER TABLE ai_agent_audit_log ADD COLUMN bq_job_ids TEXT",
    "ALTER TABLE ai_agent_audit_log ADD COLUMN code_zip_uri TEXT",
    "ALTER TABLE ai_agent_audit_log ADD COLUMN code_sha256_hashes TEXT",
]


async def _ensure_schema(db_url: str) -> None:
    norm = _normalize_url(db_url)
    if norm in _SCHEMA_DONE:
        return
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(_sa_text(_CREATE_AI_AUDIT_TABLE))
        # Alembic-style migration guard for existing DBs
        for stmt in _MIGRATION_STMTS:
            try:
                await conn.execute(_sa_text(stmt))
            except Exception:
                pass  # Column already exists
    _SCHEMA_DONE.add(norm)


# ---------------------------------------------------------------------------
# Hash-chain algorithm (mirrors audit/logger.py pattern)
# ---------------------------------------------------------------------------
CANONICAL_FIELDS_AI = ("query_text", "result_hash", "confidence_score", "answer_text")


def _build_canonical_ai(
    log_id: str,
    logged_at: str,
    query_text: str,
    result_hash: Optional[str],
    confidence_score: Optional[float],
    answer_text: Optional[str],
) -> str:
    payload = {
        "log_id": log_id,
        "logged_at": logged_at,
        "query_text": query_text,
        "result_hash": result_hash,
        "confidence_score": confidence_score,
        "answer_text": answer_text,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _compute_chain_hash(
    log_id: str,
    logged_at: str,
    previous_hash: str,
    query_text: str,
    result_hash: Optional[str],
    confidence_score: Optional[float],
    answer_text: Optional[str],
    code_artifact_uris: Optional[list] = None,
    bq_job_ids: Optional[list] = None,
    code_zip_uri: Optional[str] = None,
    code_sha256_hashes: Optional[list] = None,
) -> str:
    canonical = _build_canonical_ai(
        log_id, logged_at, query_text, result_hash, confidence_score, answer_text
    )
    # Append new array fields for determinism (sorted for stability)
    extension = "|".join([
        json.dumps(sorted(code_artifact_uris or []), sort_keys=True),
        json.dumps(sorted(bq_job_ids or []), sort_keys=True),
        code_zip_uri or "",
        json.dumps(sorted(code_sha256_hashes or []), sort_keys=True),
    ])
    raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical + "|" + extension
    return hashlib.sha256(raw.encode()).hexdigest()


async def _get_previous_hash(conn, session_id: str) -> str:
    """Return the record_hash of the most recent entry for this session,
    or 'GENESIS' if no prior entries exist."""
    result = await conn.execute(
        _sa_text(
            "SELECT record_hash FROM ai_agent_audit_log "
            "WHERE session_id = :sid ORDER BY logged_at DESC, log_id DESC LIMIT 1"
        ),
        {"sid": session_id},
    )
    row = result.fetchone()
    return row[0] if row else "GENESIS"


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------
@dataclass
class AIAgentAuditRecord:
    log_id: str
    session_id: str
    turn_id: str
    tenant_id: str
    persona: str
    query_text: str
    plan_text: Optional[str]
    tools_called: Optional[str]
    sql_executed: Optional[str]
    result_hash: Optional[str]
    query_hash: Optional[str]
    code_artifact_ref: Optional[str]
    confidence_score: Optional[float]
    confidence_label: Optional[str]
    answer_text: Optional[str]
    grounded: bool
    bq_job_id: Optional[str]
    source_table: Optional[str]
    partition_date: Optional[str]
    logged_at: str
    record_hash: str
    previous_hash: str
    code_artifact_uris: Optional[list] = None
    bq_job_ids: Optional[list] = None
    code_zip_uri: Optional[str] = None
    code_sha256_hashes: Optional[list] = None


def _mapping_to_record(row) -> AIAgentAuditRecord:
    return AIAgentAuditRecord(
        log_id=row["log_id"],
        session_id=row["session_id"],
        turn_id=row["turn_id"],
        tenant_id=row["tenant_id"],
        persona=row["persona"],
        query_text=row["query_text"],
        plan_text=row["plan_text"],
        tools_called=row["tools_called"],
        sql_executed=row["sql_executed"],
        result_hash=row["result_hash"],
        query_hash=row["query_hash"],
        code_artifact_ref=row["code_artifact_ref"],
        confidence_score=row["confidence_score"],
        confidence_label=row["confidence_label"],
        answer_text=row["answer_text"],
        grounded=bool(row["grounded"]),
        bq_job_id=row["bq_job_id"],
        source_table=row["source_table"],
        partition_date=row["partition_date"],
        logged_at=row["logged_at"],
        record_hash=row["record_hash"],
        code_artifact_uris=json.loads(row["code_artifact_uris"]) if row["code_artifact_uris"] else None,
        bq_job_ids=json.loads(row["bq_job_ids"]) if row["bq_job_ids"] else None,
        code_zip_uri=row["code_zip_uri"] if "code_zip_uri" in row.keys() else None,
        code_sha256_hashes=json.loads(row["code_sha256_hashes"]) if row["code_sha256_hashes"] else None,
        previous_hash=row["previous_hash"],
    )


# ---------------------------------------------------------------------------
# Public async API (OV-02: native async SQLAlchemy, no asyncio.to_thread)
# ---------------------------------------------------------------------------
async def log_ai_turn(
    db_url: str,
    session_id: str,
    turn_id: str,
    persona: str,
    query_text: str,
    answer_text: Optional[str],
    plan_steps: Optional[list[dict]],
    tools_called: Optional[list[str]],
    sql_executed: Optional[str],
    result_hash: Optional[str],
    query_hash: Optional[str],
    code_artifact_ids: Optional[list[str]],
    confidence_score: Optional[float],
    confidence_label: Optional[str],
    grounded: bool,
    tenant_id: str = "default",
    bq_job_id: Optional[str] = None,
    source_table: Optional[str] = None,
    partition_date: Optional[str] = None,
    code_artifact_uris: Optional[list[str]] = None,
    bq_job_ids: Optional[list[str]] = None,
    code_zip_uri: Optional[str] = None,
    code_sha256_hashes: Optional[list[str]] = None,
) -> AIAgentAuditRecord:
    """
    Insert one row into ai_agent_audit_log with a computed hash chain.
    Previous-hash fetch and INSERT are executed in a single transaction to
    prevent hash-chain forks under concurrent writes.
    Raises ValueError if session_id is None or empty.
    """
    if not session_id:
        raise ValueError("session_id is required for AI audit log entries.")

    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    log_id = str(uuid.uuid4())
    logged_at = datetime.now(timezone.utc).isoformat()
    plan_text = json.dumps(plan_steps) if plan_steps else None
    tools_called_str = json.dumps(tools_called) if tools_called else None
    code_artifact_ref = ",".join(code_artifact_ids) if code_artifact_ids else None
    code_artifact_uris_str = json.dumps(code_artifact_uris or [])
    bq_job_ids_str = json.dumps(bq_job_ids or [])
    code_sha256_hashes_str = json.dumps(code_sha256_hashes or [])

    async with engine.begin() as conn:
        # Fetch previous hash in the same transaction for chain integrity
        previous_hash = await _get_previous_hash(conn, session_id)
        record_hash = _compute_chain_hash(
            log_id=log_id,
            logged_at=logged_at,
            previous_hash=previous_hash,
            query_text=query_text,
            result_hash=result_hash,
            confidence_score=confidence_score,
            answer_text=answer_text,
            code_artifact_uris=code_artifact_uris,
            bq_job_ids=bq_job_ids,
            code_zip_uri=code_zip_uri,
            code_sha256_hashes=code_sha256_hashes,
        )
        await conn.execute(
            _sa_text("""
                INSERT INTO ai_agent_audit_log (
                    log_id, session_id, turn_id, tenant_id, persona, query_text,
                    plan_text, tools_called, sql_executed, result_hash, query_hash,
                    code_artifact_ref, confidence_score, confidence_label, answer_text,
                    grounded, bq_job_id, source_table, partition_date,
                    logged_at, record_hash, previous_hash, hash_algorithm,
                    code_artifact_uris, bq_job_ids, code_zip_uri, code_sha256_hashes
                ) VALUES (
                    :log_id, :session_id, :turn_id, :tenant_id, :persona, :query_text,
                    :plan_text, :tools_called, :sql_executed, :result_hash, :query_hash,
                    :code_artifact_ref, :confidence_score, :confidence_label, :answer_text,
                    :grounded, :bq_job_id, :source_table, :partition_date,
                    :logged_at, :record_hash, :previous_hash, :hash_algorithm,
                    :code_artifact_uris, :bq_job_ids, :code_zip_uri, :code_sha256_hashes
                )
            """),
            {
                "log_id": log_id, "session_id": session_id, "turn_id": turn_id,
                "tenant_id": tenant_id, "persona": persona, "query_text": query_text,
                "plan_text": plan_text, "tools_called": tools_called_str,
                "sql_executed": sql_executed, "result_hash": result_hash,
                "query_hash": query_hash, "code_artifact_ref": code_artifact_ref,
                "confidence_score": confidence_score, "confidence_label": confidence_label,
                "answer_text": answer_text, "grounded": 1 if grounded else 0,
                "bq_job_id": bq_job_id, "source_table": source_table,
                "partition_date": partition_date, "logged_at": logged_at,
                "record_hash": record_hash, "previous_hash": previous_hash,
                "hash_algorithm": "sha256",
                "code_artifact_uris": code_artifact_uris_str,
                "bq_job_ids": bq_job_ids_str,
                "code_zip_uri": code_zip_uri,
                "code_sha256_hashes": code_sha256_hashes_str,
            },
        )

    return AIAgentAuditRecord(
        log_id=log_id,
        session_id=session_id,
        turn_id=turn_id,
        tenant_id=tenant_id,
        persona=persona,
        query_text=query_text,
        plan_text=plan_text,
        tools_called=tools_called_str,
        sql_executed=sql_executed,
        result_hash=result_hash,
        query_hash=query_hash,
        code_artifact_ref=code_artifact_ref,
        confidence_score=confidence_score,
        confidence_label=confidence_label,
        answer_text=answer_text,
        grounded=grounded,
        bq_job_id=bq_job_id,
        source_table=source_table,
        partition_date=partition_date,
        logged_at=logged_at,
        record_hash=record_hash,
        previous_hash=previous_hash,
        code_artifact_uris=code_artifact_uris or [],
        bq_job_ids=bq_job_ids or [],
        code_zip_uri=code_zip_uri,
        code_sha256_hashes=code_sha256_hashes or [],
    )


async def get_ai_audit_records_by_session(
    session_id: str,
    db_url: str,
) -> list[dict]:
    """Return all audit records for a session as dicts with array fields deserialized.
    Consumed by compliance/exam_packet_builder.py build_ai_agent_audit_component()."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            _sa_text(
                "SELECT * FROM ai_agent_audit_log "
                "WHERE session_id = :sid ORDER BY logged_at ASC"
            ),
            {"sid": session_id},
        )
        rows = result.mappings().all()

    records = []
    for row in rows:
        d = dict(row)
        for col in ("code_artifact_uris", "bq_job_ids", "code_sha256_hashes"):
            raw = d.get(col)
            d[col] = json.loads(raw) if raw else []
        records.append(d)
    return records


async def get_ai_audit_records(
    db_url: str,
    session_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
    limit: int = 1000,
) -> list[AIAgentAuditRecord]:
    """Query ai_agent_audit_log. All filter parameters are optional.
    Results ordered by logged_at ASC."""
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    conditions = ["1=1"]
    params: dict = {}
    if session_id:
        conditions.append("session_id = :session_id")
        params["session_id"] = session_id
    if from_date:
        conditions.append("logged_at >= :from_date")
        params["from_date"] = from_date
    if to_date:
        conditions.append("logged_at <= :to_date")
        params["to_date"] = to_date
    if tenant_id:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id
    params["limit"] = limit

    sql = (
        f"SELECT * FROM ai_agent_audit_log WHERE {' AND '.join(conditions)}"
        " ORDER BY logged_at ASC LIMIT :limit"
    )

    async with engine.connect() as conn:
        result = await conn.execute(_sa_text(sql), params)
        rows = result.mappings().all()

    return [_mapping_to_record(r) for r in rows]
