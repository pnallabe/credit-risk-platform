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
)
import src.ai_audit_log as ai_audit_log_module

# Also need verify_ai_agent_chain from audit/chain_verifier
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
from audit.chain_verifier import verify_ai_agent_chain


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
    assert result.verified is True
    assert result.rows_checked == 5


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
    assert result.verified is False
    assert result.first_tampered_log_id is not None


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
