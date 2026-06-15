"""
Tests for ai-agent/src/ai_audit_log.py — GAP-20 (Prompt 20-E)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai_audit_log import (
    log_ai_turn,
    get_ai_audit_records,
    get_ai_audit_records_by_session,
)
import src.ai_audit_log as ai_audit_log_module

# Import verify_ai_agent_chain from src.ai_audit_log
from src.ai_audit_log import verify_ai_agent_chain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _log(db_url: str, session_id: str, turn_id: str, query: str = "SELECT 1") -> object:
    return await log_ai_turn(
        db_url=db_url,
        session_id=session_id,
        turn_id=turn_id,
        persona="data_analyst",
        query_text=query,
        answer_text="The answer is 42.",
        plan_steps=[{"thought": "x", "action": "sql_query_tool",
                     "action_input": query, "observation": "1"}],
        tools_called=["sql_query_tool"],
        sql_executed=query,
        result_hash="abc123",
        query_hash="def456",
        code_artifact_ids=["art-1"],
        confidence_score=0.85,
        confidence_label="high",
        grounded=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_ai_turn_creates_record(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())

    record = await _log(db_url, session_id, turn_id)

    # Valid UUID4 log_id
    parsed = uuid.UUID(record.log_id, version=4)
    assert str(parsed) == record.log_id

    # record_hash is 64-char hex
    assert len(record.record_hash) == 64
    assert all(c in "0123456789abcdef" for c in record.record_hash)

    # First record → previous_hash == "GENESIS"
    assert record.previous_hash == "GENESIS"


@pytest.mark.asyncio
async def test_hash_chain_links_correctly(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())

    r1 = await _log(db_url, session_id, str(uuid.uuid4()))
    r2 = await _log(db_url, session_id, str(uuid.uuid4()))

    assert r2.previous_hash == r1.record_hash


@pytest.mark.asyncio
async def test_verify_ai_agent_chain_clean(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())

    for _ in range(5):
        await _log(db_url, session_id, str(uuid.uuid4()))

    result = await verify_ai_agent_chain(db_url, session_id=session_id)
    assert result.is_intact is True
    assert result.verified_records == 5


@pytest.mark.asyncio
async def test_verify_ai_agent_chain_detects_tamper(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())

    r1 = await _log(db_url, session_id, str(uuid.uuid4()))
    r2 = await _log(db_url, session_id, str(uuid.uuid4()))
    r3 = await _log(db_url, session_id, str(uuid.uuid4()))

    # Tamper: directly overwrite record_hash of the second row
    conn = sqlite3.connect(db_url)
    conn.execute(
        "UPDATE ai_agent_audit_log SET record_hash = 'tampered' WHERE log_id = ?",
        (r2.log_id,),
    )
    conn.commit()
    conn.close()

    result = await verify_ai_agent_chain(db_url, session_id=session_id)
    assert result.is_intact is False
    assert r2.log_id in result.broken_at


@pytest.mark.asyncio
async def test_no_update_or_delete_functions():
    for bad in ("update_ai_turn", "delete_ai_turn", "delete_audit_record"):
        assert not hasattr(ai_audit_log_module, bad), f"Found forbidden symbol: {bad}"


@pytest.mark.asyncio
async def test_get_ai_audit_records_date_filter(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())

    r1 = await _log(db_url, session_id, str(uuid.uuid4()))
    r2 = await _log(db_url, session_id, str(uuid.uuid4()))

    # Filter from r2's logged_at (only r2 should match)
    records = await get_ai_audit_records(db_url, session_id=session_id, from_date=r2.logged_at)
    assert any(r.log_id == r2.log_id for r in records)


@pytest.mark.asyncio
async def test_plan_steps_serialised_to_json(tmp_path):
    db_url = str(tmp_path / "test.db")
    session_id = str(uuid.uuid4())
    turn_id = str(uuid.uuid4())

    record = await log_ai_turn(
        db_url=db_url,
        session_id=session_id,
        turn_id=turn_id,
        persona="data_analyst",
        query_text="SELECT 1",
        answer_text="ok",
        plan_steps=[{"thought": "x", "action": "sql_query_tool",
                     "action_input": "SELECT 1", "observation": "1"}],
        tools_called=["sql_query_tool"],
        sql_executed="SELECT 1",
        result_hash=None,
        query_hash=None,
        code_artifact_ids=None,
        confidence_score=0.9,
        confidence_label="high",
        grounded=True,
    )
    assert record.plan_text is not None
    parsed = json.loads(record.plan_text)
    assert any("sql_query_tool" in str(v) for step in parsed for v in step.values())


@pytest.mark.asyncio
async def test_retention_schedule_contains_ai_audit_log():
    from compliance.retention_policy import RETENTION_SCHEDULE
    assert "audit.ai_agent_audit_log" in RETENTION_SCHEDULE
    assert RETENTION_SCHEDULE["audit.ai_agent_audit_log"] == 7


# ---------------------------------------------------------------------------
# GAP-22: Array fields tests
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_log_ai_turn_array_fields(tmp_path):
    """log_ai_turn() with list args stores/retrieves correctly via get_ai_audit_records_by_session."""
    db_url = str(tmp_path / "test_arr.db")
    session_id = str(uuid.uuid4())

    record = await log_ai_turn(
        db_url=db_url,
        session_id=session_id,
        turn_id=str(uuid.uuid4()),
        persona="data_analyst",
        query_text="SELECT 1",
        answer_text="Done.",
        plan_steps=None,
        tools_called=None,
        sql_executed="SELECT 1",
        result_hash=None,
        query_hash=None,
        code_artifact_ids=None,
        confidence_score=0.9,
        confidence_label="high",
        grounded=True,
        code_artifact_uris=["gs://bucket/a.sql", "gs://bucket/b.py"],
        bq_job_ids=["job-001", "job-002"],
        code_zip_uri="gs://bucket/archive.zip",
        code_sha256_hashes=["aabbcc", "ddeeff"],
    )

    dicts = await get_ai_audit_records_by_session(session_id, db_url)
    assert len(dicts) == 1
    d = dicts[0]
    assert d["code_artifact_uris"] == ["gs://bucket/a.sql", "gs://bucket/b.py"]
    assert d["bq_job_ids"] == ["job-001", "job-002"]
    assert d["code_zip_uri"] == "gs://bucket/archive.zip"
    assert d["code_sha256_hashes"] == ["aabbcc", "ddeeff"]


@pytest.mark.asyncio
async def test_hash_chain_integrity_array_fields(tmp_path):
    """Hash chain still verifies after the array field extension."""
    db_path = str(tmp_path / "test_chain.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"
    session_id = str(uuid.uuid4())

    for i in range(3):
        await log_ai_turn(
            db_url=db_url,
            session_id=session_id,
            turn_id=str(uuid.uuid4()),
            persona="data_analyst",
            query_text=f"SELECT {i}",
            answer_text="ok",
            plan_steps=None,
            tools_called=None,
            sql_executed=f"SELECT {i}",
            result_hash=None,
            query_hash=None,
            code_artifact_ids=None,
            confidence_score=0.8,
            confidence_label="medium",
            grounded=True,
            code_artifact_uris=[f"gs://b/q{i}.sql"],
            bq_job_ids=[f"job-{i}"],
            code_zip_uri=None,
            code_sha256_hashes=[],
        )

    result = await verify_ai_agent_chain(db_url, session_id=session_id)
    assert result.is_intact is True
    assert result.verified_records == 3


@pytest.mark.asyncio
async def test_migration_idempotent(tmp_path):
    """Starting with old schema (no array cols), _ensure_schema adds them without error."""
    import aiosqlite

    db_path = str(tmp_path / "old_schema.db")

    # Create table with OLD schema (no array columns)
    old_ddl = """
    CREATE TABLE IF NOT EXISTS ai_agent_audit_log (
        log_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL UNIQUE,
        tenant_id TEXT NOT NULL DEFAULT 'default',
        persona TEXT NOT NULL,
        query_text TEXT NOT NULL,
        plan_text TEXT, tools_called TEXT, sql_executed TEXT,
        result_hash TEXT, query_hash TEXT, code_artifact_ref TEXT,
        confidence_score REAL, confidence_label TEXT, answer_text TEXT,
        grounded INTEGER NOT NULL DEFAULT 1,
        bq_job_id TEXT, source_table TEXT, partition_date TEXT,
        logged_at TEXT NOT NULL, record_hash TEXT NOT NULL,
        previous_hash TEXT NOT NULL,
        hash_algorithm TEXT NOT NULL DEFAULT 'sha256'
    )
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(old_ddl)
        await db.commit()

    # Now run ensure_schema — should add the 4 new columns
    import src.ai_audit_log as m
    # Clear cache so _ensure_schema runs fresh
    norm = m._normalize_url(db_path)
    m._SCHEMA_DONE.discard(norm)
    if norm in m._ENGINE_CACHE:
        await m._ENGINE_CACHE[norm].dispose()
        del m._ENGINE_CACHE[norm]

    await m._ensure_schema(db_path)

    # Verify columns exist
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("PRAGMA table_info(ai_agent_audit_log)")
        cols = {row[1] for row in await cursor.fetchall()}

    for col in ("code_artifact_uris", "bq_job_ids", "code_zip_uri", "code_sha256_hashes"):
        assert col in cols, f"Missing column: {col}"
