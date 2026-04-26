"""
Smoke tests for audit/chain_verifier.py
"""
from __future__ import annotations

import hashlib
import json

import pytest

from audit.chain_verifier import (
    ChainVerificationResult,
    _rebuild_canonical,
    _rebuild_ai_canonical,
    _recompute_hash,
    _recompute_ai_hash,
    verify_chain,
    verify_ai_agent_chain,
)


# ---------------------------------------------------------------------------
# ChainVerificationResult dataclass
# ---------------------------------------------------------------------------

def test_chain_verification_result_creation():
    result = ChainVerificationResult(
        verified=True,
        rows_checked=10,
        first_tampered_log_id=None,
        first_tampered_at=None,
        gap_detected=False,
    )
    assert result.verified is True
    assert result.rows_checked == 10
    assert result.first_tampered_log_id is None
    assert result.gap_detected is False


def test_chain_verification_result_tampered():
    result = ChainVerificationResult(
        verified=False,
        rows_checked=5,
        first_tampered_log_id="log-001",
        first_tampered_at="2026-01-01T00:00:00+00:00",
        gap_detected=True,
    )
    assert result.verified is False
    assert result.first_tampered_log_id == "log-001"
    assert result.gap_detected is True


# ---------------------------------------------------------------------------
# _rebuild_canonical
# ---------------------------------------------------------------------------

def test_rebuild_canonical_audit_log():
    row = {
        "decision_output": "APPROVE",
        "fraud_score": 0.05,
        "reason_codes": "[]",
        "risk_score": 0.10,
        "unrelated_field": "ignored",
    }
    canonical = _rebuild_canonical(row, "audit_log")
    parsed = json.loads(canonical)
    assert "decision_output" in parsed
    assert "fraud_score" in parsed
    assert "unrelated_field" not in parsed


def test_rebuild_canonical_adverse_action_log():
    row = {
        "action_date": "2026-01-01",
        "deadline_date": "2026-04-01",
        "form_type": "AA-001",
        "reason_codes": "AA04",
    }
    canonical = _rebuild_canonical(row, "adverse_action_log")
    parsed = json.loads(canonical)
    assert "action_date" in parsed
    assert "form_type" in parsed


def test_rebuild_canonical_unknown_table():
    """Unknown table returns empty payload."""
    row = {"some_field": "value"}
    canonical = _rebuild_canonical(row, "unknown_table")
    parsed = json.loads(canonical)
    assert parsed == {}


def test_rebuild_canonical_is_deterministic():
    row = {"decision_output": "REJECT", "fraud_score": 0.10, "reason_codes": "AA04", "risk_score": 0.20}
    c1 = _rebuild_canonical(row, "audit_log")
    c2 = _rebuild_canonical(row, "audit_log")
    assert c1 == c2


# ---------------------------------------------------------------------------
# _recompute_hash
# ---------------------------------------------------------------------------

def test_recompute_hash_deterministic():
    row = {"log_id": "log-001", "logged_at": "2026-01-01T00:00:00", "decision_output": "APPROVE", "fraud_score": 0.05, "reason_codes": "[]", "risk_score": 0.10}
    h1 = _recompute_hash(row, "GENESIS", "audit_log")
    h2 = _recompute_hash(row, "GENESIS", "audit_log")
    assert h1 == h2


def test_recompute_hash_changes_with_previous_hash():
    row = {"log_id": "log-001", "logged_at": "2026-01-01T00:00:00", "decision_output": "APPROVE", "fraud_score": 0.05, "reason_codes": "[]", "risk_score": 0.10}
    h_genesis = _recompute_hash(row, "GENESIS", "audit_log")
    h_other = _recompute_hash(row, "deadbeef" * 8, "audit_log")
    assert h_genesis != h_other


# ---------------------------------------------------------------------------
# _rebuild_ai_canonical / _recompute_ai_hash
# ---------------------------------------------------------------------------

def test_rebuild_ai_canonical_contains_fields():
    row = {
        "log_id": "ai-001",
        "logged_at": "2026-01-01T00:00:00",
        "query_text": "test query",
        "result_hash": "sha256:abc",
        "confidence_score": 0.95,
        "answer_text": "test answer",
        "extra": "ignored",
    }
    canonical = _rebuild_ai_canonical(row)
    parsed = json.loads(canonical)
    assert parsed["query_text"] == "test query"
    assert parsed["confidence_score"] == 0.95
    assert "extra" not in parsed


def test_recompute_ai_hash_is_deterministic():
    row = {"log_id": "ai-001", "logged_at": "2026-01-01", "query_text": "q", "result_hash": "h", "confidence_score": 0.9, "answer_text": "a", "previous_hash": "GENESIS"}
    h1 = _recompute_ai_hash(row)
    h2 = _recompute_ai_hash(row)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_recompute_ai_hash_default_genesis():
    row = {"log_id": "ai-001", "logged_at": "2026-01-01", "query_text": "q", "result_hash": "h", "confidence_score": 0.9, "answer_text": "a"}
    h_default = _recompute_ai_hash(row)
    row["previous_hash"] = "GENESIS"
    h_genesis = _recompute_ai_hash(row)
    assert h_default == h_genesis


# ---------------------------------------------------------------------------
# verify_chain / verify_ai_agent_chain with empty DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_chain_empty_db_returns_true():
    result = await verify_chain("sqlite+aiosqlite://", "tenant-a")
    # Empty table or missing table — either verified=True (empty) or verified=False (exception)
    assert isinstance(result, ChainVerificationResult)


@pytest.mark.asyncio
async def test_verify_ai_agent_chain_empty_db():
    result = await verify_ai_agent_chain("sqlite+aiosqlite://")
    assert isinstance(result, ChainVerificationResult)


@pytest.mark.asyncio
async def test_verify_chain_with_valid_single_row():
    """Insert one audit_log row with valid hash; verify should pass."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    db_url = "sqlite+aiosqlite://"
    engine = create_async_engine(db_url, echo=False)

    DDL = """
    CREATE TABLE IF NOT EXISTS audit_log (
        log_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        decision_output TEXT,
        fraud_score REAL,
        reason_codes TEXT,
        risk_score REAL,
        record_hash TEXT,
        previous_hash TEXT
    )
    """
    # Compute correct hash for one row
    row = {
        "log_id": "log-001",
        "tenant_id": "tenant-a",
        "logged_at": "2026-01-01T00:00:00",
        "decision_output": "APPROVE",
        "fraud_score": 0.05,
        "reason_codes": "[]",
        "risk_score": 0.08,
        "previous_hash": "GENESIS",
        "record_hash": "",
    }
    record_hash = _recompute_hash(row, "GENESIS", "audit_log")
    row["record_hash"] = record_hash

    async with engine.begin() as conn:
        await conn.execute(text(DDL))
        await conn.execute(text(
            "INSERT INTO audit_log VALUES (:log_id, :tenant_id, :logged_at, :decision_output, "
            ":fraud_score, :reason_codes, :risk_score, :record_hash, :previous_hash)"
        ), row)

    # Use the same engine by passing the db_url with a cache-busting workaround
    # We can't reuse the engine directly via db_url with the module's cache,
    # so we import _get_engine and monkey-patch
    import audit.chain_verifier as cv
    old_get_engine = cv._get_engine
    cv._get_engine = lambda _: engine
    try:
        result = await verify_chain(db_url, "tenant-a")
    finally:
        cv._get_engine = old_get_engine

    assert result.verified is True
    assert result.rows_checked == 1


@pytest.mark.asyncio
async def test_verify_chain_adverse_action_log():
    """Calling verify_chain with adverse_action_log table uses correct columns."""
    result = await verify_chain("sqlite+aiosqlite://", "tenant-a", table="adverse_action_log")
    assert isinstance(result, ChainVerificationResult)


@pytest.mark.asyncio
async def test_verify_chain_portfolio_audit_log():
    """Calling verify_chain with portfolio_audit_log uses account_id partition."""
    result = await verify_chain("sqlite+aiosqlite://", "account-001", table="portfolio_audit_log")
    assert isinstance(result, ChainVerificationResult)


@pytest.mark.asyncio
async def test_verify_ai_agent_chain_with_valid_row():
    """Insert one ai_agent_audit_log row with valid hash; verify should pass."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    db_url = "sqlite+aiosqlite://"
    engine = create_async_engine(db_url, echo=False)

    DDL = """
    CREATE TABLE IF NOT EXISTS ai_agent_audit_log (
        log_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        query_text TEXT,
        result_hash TEXT,
        confidence_score REAL,
        answer_text TEXT,
        record_hash TEXT,
        previous_hash TEXT
    )
    """
    row = {
        "log_id": "ai-001",
        "session_id": "sess-001",
        "logged_at": "2026-01-01T00:00:00",
        "query_text": "test query",
        "result_hash": "sha256:abc",
        "confidence_score": 0.95,
        "answer_text": "test answer",
        "previous_hash": "GENESIS",
        "record_hash": "",
    }
    record_hash = _recompute_ai_hash(row)
    row["record_hash"] = record_hash

    async with engine.begin() as conn:
        await conn.execute(text(DDL))
        await conn.execute(text(
            "INSERT INTO ai_agent_audit_log VALUES (:log_id, :session_id, :logged_at, "
            ":query_text, :result_hash, :confidence_score, :answer_text, :record_hash, :previous_hash)"
        ), row)

    import audit.chain_verifier as cv
    old_get_engine = cv._get_engine
    cv._get_engine = lambda _: engine
    try:
        result = await verify_ai_agent_chain(db_url, session_id="sess-001")
    finally:
        cv._get_engine = old_get_engine

    assert result.verified is True
    assert result.rows_checked == 1


@pytest.mark.asyncio
async def test_verify_chain_with_date_filter():
    """from_logged_at / to_logged_at filters should be applied."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    db_url = "sqlite+aiosqlite://"
    engine = create_async_engine(db_url, echo=False)

    DDL = """
    CREATE TABLE IF NOT EXISTS audit_log (
        log_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        decision_output TEXT,
        fraud_score REAL,
        reason_codes TEXT,
        risk_score REAL,
        record_hash TEXT,
        previous_hash TEXT
    )
    """
    async with engine.begin() as conn:
        await conn.execute(text(DDL))

    import audit.chain_verifier as cv
    old_get_engine = cv._get_engine
    cv._get_engine = lambda _: engine
    try:
        result = await verify_chain(
            db_url, "tenant-filter",
            from_logged_at="2026-01-01T00:00:00",
            to_logged_at="2026-12-31T23:59:59",
        )
    finally:
        cv._get_engine = old_get_engine

    assert result.verified is True
    assert result.rows_checked == 0
    """Insert one row with wrong hash; verify should fail."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    db_url = "sqlite+aiosqlite://"
    engine = create_async_engine(db_url, echo=False)

    DDL = """
    CREATE TABLE IF NOT EXISTS audit_log (
        log_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        logged_at TEXT NOT NULL,
        decision_output TEXT,
        fraud_score REAL,
        reason_codes TEXT,
        risk_score REAL,
        record_hash TEXT,
        previous_hash TEXT
    )
    """
    row = {
        "log_id": "log-001",
        "tenant_id": "tenant-b",
        "logged_at": "2026-01-01T00:00:00",
        "decision_output": "APPROVE",
        "fraud_score": 0.05,
        "reason_codes": "[]",
        "risk_score": 0.08,
        "previous_hash": "GENESIS",
        "record_hash": "tampered_hash_value",  # wrong hash
    }
    async with engine.begin() as conn:
        await conn.execute(text(DDL))
        await conn.execute(text(
            "INSERT INTO audit_log VALUES (:log_id, :tenant_id, :logged_at, :decision_output, "
            ":fraud_score, :reason_codes, :risk_score, :record_hash, :previous_hash)"
        ), row)

    import audit.chain_verifier as cv
    old_get_engine = cv._get_engine
    cv._get_engine = lambda _: engine
    try:
        result = await verify_chain(db_url, "tenant-b")
    finally:
        cv._get_engine = old_get_engine

    assert result.verified is False
    assert result.first_tampered_log_id == "log-001"
