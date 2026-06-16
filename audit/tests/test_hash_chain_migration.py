"""
Tests for P1-A: Hash chain schema migration  (audit/logger.py)
and P1-B: Hash chain writer.
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest
import pytest_asyncio

DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fresh_engine(tmp_db_url: str = DB_URL):
    """Return a fresh AsyncEngine scoped to one test."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(tmp_db_url, echo=False)
    # Prime the cache with this engine instance
    from audit import logger as _logger
    _logger._ENGINE_CACHE[tmp_db_url] = engine
    return engine


async def _column_names(engine, table: str) -> set[str]:
    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        return {row[1] for row in result.fetchall()}


# ---------------------------------------------------------------------------
# P1-A tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_migrate_adds_hash_columns():
    """Fresh DB: after migration, all three hash columns must exist."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    engine = await _fresh_engine(url)

    from audit.logger import migrate_audit_schema

    await migrate_audit_schema(url)

    for table in ("audit_log", "portfolio_audit_log"):
        cols = await _column_names(engine, table)
        assert "record_hash" in cols, f"record_hash missing in {table}"
        assert "previous_hash" in cols, f"previous_hash missing in {table}"
        assert "hash_algorithm" in cols, f"hash_algorithm missing in {table}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_migrate_idempotent():
    """Calling migrate twice must not raise."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    await _fresh_engine(url)

    from audit.logger import migrate_audit_schema

    await migrate_audit_schema(url)
    # Second call must not raise
    await migrate_audit_schema(url)


@pytest.mark.asyncio
async def test_migrate_does_not_alter_existing_rows():
    """Rows written before migration must survive intact."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    engine = await _fresh_engine(url)

    from audit.logger import log_decision, migrate_audit_schema

    class FakeResult:
        application_id = "app-001"
        decision = "APPROVE"
        reason_codes = ["AA01"]
        decision_latency_ms = 42

    log_id = await log_decision(
        decision_result=FakeResult(),
        feature_version="v1",
        model_versions={"fraud": "v1", "credit_risk": "v1"},
        input_features={"pd_score": 0.03, "fraud_probability": 0.01},
        db_url=url,
        tenant_id="tenant-test",
    )

    await migrate_audit_schema(url)

    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT log_id, decision_output FROM audit_log WHERE log_id = :lid"),
            {"lid": log_id},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] == log_id
    assert row[1] == "APPROVE"

    await engine.dispose()


# ---------------------------------------------------------------------------
# P1-B tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hash_chain_linked():
    """Row N's previous_hash must equal row N-1's record_hash."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    engine = await _fresh_engine(url)

    from audit.logger import log_decision, migrate_audit_schema

    await migrate_audit_schema(url)

    class FakeResult:
        def __init__(self, n):
            self.application_id = f"app-{n:03d}"
            self.decision = "APPROVE"
            self.reason_codes = ["AA01"]
            self.decision_latency_ms = 10

    log_ids = []
    for i in range(3):
        lid = await log_decision(
            decision_result=FakeResult(i),
            feature_version="v1",
            model_versions={"fraud": "v1", "credit_risk": "v1"},
            input_features={"pd_score": 0.03, "fraud_probability": 0.01},
            db_url=url,
            tenant_id="tenant-chain",
        )
        log_ids.append(lid)

    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT log_id, record_hash, previous_hash"
                " FROM audit_log WHERE tenant_id = :tid"
                " ORDER BY logged_at ASC"
            ),
            {"tid": "tenant-chain"},
        )
        rows = result.fetchall()

    assert len(rows) == 3

    # Row 1: previous_hash == ""
    assert rows[0][2] == "" or rows[0][2] is None, (
        "First row should have empty/NULL previous_hash"
    )

    # Row 2: previous_hash == row 1's record_hash
    assert rows[1][2] == rows[0][1], "Chain link 1→2 broken"

    # Row 3: previous_hash == row 2's record_hash
    assert rows[2][2] == rows[1][1], "Chain link 2→3 broken"

    await engine.dispose()


@pytest.mark.asyncio
async def test_first_row_empty_previous_hash():
    """The very first row for a tenant must have previous_hash == ''."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    engine = await _fresh_engine(url)

    from audit.logger import log_decision, migrate_audit_schema

    await migrate_audit_schema(url)

    class FakeResult:
        application_id = "app-first"
        decision = "REJECT"
        reason_codes = ["AA01"]
        decision_latency_ms = 5

    await log_decision(
        decision_result=FakeResult(),
        feature_version="v1",
        model_versions={"fraud": "v1", "credit_risk": "v1"},
        input_features={"pd_score": 0.15, "fraud_probability": 0.01},
        db_url=url,
        tenant_id="tenant-first",
    )

    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT previous_hash FROM audit_log WHERE tenant_id = :tid"),
            {"tid": "tenant-first"},
        )
        row = result.fetchone()

    assert row is not None
    assert row[0] == "" or row[0] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_record_hash_is_64_char_hex():
    """record_hash must be a 64-character hex string for every row."""
    import uuid
    url = f"sqlite+aiosqlite:///:memory:{uuid.uuid4().hex}"
    engine = await _fresh_engine(url)

    from audit.logger import log_decision, migrate_audit_schema

    await migrate_audit_schema(url)

    class FakeResult:
        def __init__(self, n):
            self.application_id = f"app-hex-{n}"
            self.decision = "APPROVE"
            self.reason_codes = []
            self.decision_latency_ms = 1

    for i in range(3):
        await log_decision(
            decision_result=FakeResult(i),
            feature_version="v1",
            model_versions={"fraud": "v1", "credit_risk": "v1"},
            input_features={"pd_score": 0.02, "fraud_probability": 0.005},
            db_url=url,
            tenant_id="tenant-hex",
        )

    from sqlalchemy import text

    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT record_hash FROM audit_log WHERE tenant_id = :tid"),
            {"tid": "tenant-hex"},
        )
        rows = result.fetchall()

    assert len(rows) == 3
    hex_pattern = re.compile(r"^[0-9a-f]{64}$")
    for (h,) in rows:
        assert h is not None, "record_hash must not be NULL"
        assert hex_pattern.match(h), f"record_hash is not 64-char hex: {h!r}"

    await engine.dispose()
