"""
ai_audit_log.py — Prompt 20-A
Append-only, cryptographically hash-chained audit log for every AI agent
query turn.  Implements GNRI-011 requirements.

APPEND-ONLY — no UPDATE or DELETE operations are permitted.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Schema-init guard (once per process per db_path)
# ---------------------------------------------------------------------------
_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALISED: set[str] = set()


def _strip_prefix(db_url: str) -> str:
    if db_url.startswith("sqlite:///"):
        return db_url[len("sqlite:///"):]
    return db_url


def _ensure_schema(db_path: str) -> None:
    with _SCHEMA_INIT_LOCK:
        if db_path in _SCHEMA_INITIALISED:
            return
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("""
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
                    hash_algorithm      TEXT    NOT NULL DEFAULT 'sha256'
                )
            """)
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_INITIALISED.add(db_path)


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
) -> str:
    canonical = _build_canonical_ai(
        log_id, logged_at, query_text, result_hash, confidence_score, answer_text
    )
    raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical
    return hashlib.sha256(raw.encode()).hexdigest()


def _get_previous_hash(conn: sqlite3.Connection, session_id: str) -> str:
    """Return the record_hash of the most recent entry for this session,
    or 'GENESIS' if no prior entries exist."""
    row = conn.execute(
        "SELECT record_hash FROM ai_agent_audit_log "
        "WHERE session_id = ? ORDER BY logged_at DESC, log_id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
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


def _row_to_record(row: sqlite3.Row) -> AIAgentAuditRecord:
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
        previous_hash=row["previous_hash"],
    )


# ---------------------------------------------------------------------------
# Synchronous inner functions (wrapped in asyncio.to_thread)
# ---------------------------------------------------------------------------
def _sync_log_ai_turn(
    db_path: str,
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
    tenant_id: str,
    bq_job_id: Optional[str],
    source_table: Optional[str],
    partition_date: Optional[str],
) -> AIAgentAuditRecord:
    _ensure_schema(db_path)

    log_id = str(uuid.uuid4())
    logged_at = datetime.now(timezone.utc).isoformat()
    plan_text = json.dumps(plan_steps) if plan_steps else None
    tools_called_str = json.dumps(tools_called) if tools_called else None
    code_artifact_ref = ",".join(code_artifact_ids) if code_artifact_ids else None

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        previous_hash = _get_previous_hash(conn, session_id)
        record_hash = _compute_chain_hash(
            log_id=log_id,
            logged_at=logged_at,
            previous_hash=previous_hash,
            query_text=query_text,
            result_hash=result_hash,
            confidence_score=confidence_score,
            answer_text=answer_text,
        )
        conn.execute(
            """
            INSERT INTO ai_agent_audit_log (
                log_id, session_id, turn_id, tenant_id, persona, query_text,
                plan_text, tools_called, sql_executed, result_hash, query_hash,
                code_artifact_ref, confidence_score, confidence_label, answer_text,
                grounded, bq_job_id, source_table, partition_date,
                logged_at, record_hash, previous_hash, hash_algorithm
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, 'sha256'
            )
            """,
            (
                log_id, session_id, turn_id, tenant_id, persona, query_text,
                plan_text, tools_called_str, sql_executed, result_hash, query_hash,
                code_artifact_ref, confidence_score, confidence_label, answer_text,
                1 if grounded else 0, bq_job_id, source_table, partition_date,
                logged_at, record_hash, previous_hash,
            ),
        )
        conn.commit()
    finally:
        conn.close()

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
    )


def _sync_get_ai_audit_records(
    db_path: str,
    session_id: Optional[str],
    from_date: Optional[str],
    to_date: Optional[str],
    tenant_id: Optional[str],
    limit: int,
) -> list[AIAgentAuditRecord]:
    _ensure_schema(db_path)
    query = "SELECT * FROM ai_agent_audit_log WHERE 1=1"
    params: list = []
    if session_id:
        query += " AND session_id = ?"
        params.append(session_id)
    if from_date:
        query += " AND logged_at >= ?"
        params.append(from_date)
    if to_date:
        query += " AND logged_at <= ?"
        params.append(to_date)
    if tenant_id:
        query += " AND tenant_id = ?"
        params.append(tenant_id)
    query += " ORDER BY logged_at ASC LIMIT ?"
    params.append(limit)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
        return [_row_to_record(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public async API
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
) -> AIAgentAuditRecord:
    """
    Insert one row into ai_agent_audit_log with a computed hash chain.
    Raises ValueError if session_id is None or empty.
    """
    if not session_id:
        raise ValueError("session_id is required for AI audit log entries.")
    db_path = _strip_prefix(db_url)
    return await asyncio.to_thread(
        _sync_log_ai_turn,
        db_path, session_id, turn_id, persona, query_text, answer_text,
        plan_steps, tools_called, sql_executed, result_hash, query_hash,
        code_artifact_ids, confidence_score, confidence_label, grounded,
        tenant_id, bq_job_id, source_table, partition_date,
    )


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
    db_path = _strip_prefix(db_url)
    return await asyncio.to_thread(
        _sync_get_ai_audit_records,
        db_path, session_id, from_date, to_date, tenant_id, limit,
    )
