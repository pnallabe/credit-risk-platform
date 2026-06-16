"""
Tests for audit/override_log.py
================================
Uses SQLite in-memory via aiosqlite for full CI compatibility.
"""

from __future__ import annotations

import dataclasses
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parents[3]))

from audit.override_log import (
    PolicyOverrideRecord,
    _compute_record_hash,
    _get_engine,
    log_override,
    get_override_rate,
    verify_override_chain,
    OVERRIDE_LOG_DDL,
    _ensure_table,
)
from audit.logger import log_decision
from compliance.rbac import SeparationOfDutiesViolation

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DB_URL = "sqlite+aiosqlite:///:memory:"
TENANT = "test-tenant-override"


def _make_record(
    *,
    override_type: str = "pd_threshold_low",
    original_value: float = 0.05,
    override_value: float = 0.03,
    submitted_by: str = "alice@co.com",
    approved_by: str = "bob@co.com",
    decision_id: str | None = None,
    tenant_id: str = TENANT,
) -> PolicyOverrideRecord:
    return PolicyOverrideRecord(
        override_id=str(uuid.uuid4()),
        decision_id=decision_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        override_type=override_type,
        original_value=original_value,
        override_value=override_value,
        justification="Business justification for this override",
        submitted_by=submitted_by,
        approved_by=approved_by,
        approved_at=datetime.now(tz=timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# test_chain_genesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_genesis():
    """The very first record for a tenant must have previous_hash == 'GENESIS'."""
    rec = _make_record()
    await log_override(rec, DB_URL)
    assert rec.previous_hash == "GENESIS"
    assert len(rec.record_hash) == 64  # sha256 hex digest


# ---------------------------------------------------------------------------
# test_chain_links
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_links():
    """The second record's previous_hash must equal the first record's record_hash."""
    db = "sqlite+aiosqlite:///:memory:"
    rec1 = _make_record()
    await log_override(rec1, db)
    first_hash = rec1.record_hash

    rec2 = _make_record()
    await log_override(rec2, db)

    assert rec2.previous_hash == first_hash


# ---------------------------------------------------------------------------
# test_verify_chain_valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_chain_valid():
    """verify_override_chain returns True on an intact chain."""
    db = "sqlite+aiosqlite:///:memory:"
    for _ in range(3):
        await log_override(_make_record(), db)

    result = await verify_override_chain(TENANT, db)
    assert result is True


# ---------------------------------------------------------------------------
# test_verify_chain_tampered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_chain_tampered():
    """verify_override_chain returns False after a record_hash is corrupted."""
    from sqlalchemy import text

    db = "sqlite+aiosqlite:///:memory:"
    rec = _make_record()
    await log_override(rec, db)

    # Directly corrupt the record_hash in the database
    engine = _get_engine(db)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE policy_overrides_log SET record_hash = 'deadbeef'"
                " WHERE override_id = :oid"
            ),
            {"oid": rec.override_id},
        )

    result = await verify_override_chain(TENANT, db)
    assert result is False


# ---------------------------------------------------------------------------
# test_four_eyes_enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_four_eyes_enforced():
    """log_override raises SeparationOfDutiesViolation when submitted_by == approved_by.

    The four-eyes check is enforced at the decision engine / rbac layer, but we
    also verify it here by calling validate_override_submission directly.
    """
    from compliance.rbac import validate_override_submission

    with pytest.raises(SeparationOfDutiesViolation):
        validate_override_submission(
            submitted_by="alice@co.com",
            approved_by="alice@co.com",
            justification="Justification text here",
        )


# ---------------------------------------------------------------------------
# test_override_rate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_override_rate(tmp_path):
    """With 3 override rows and 10 audit_log rows, rate equals 0.3."""
    # Use a file-based SQLite so that audit.logger and audit.override_log
    # share the same physical database (they have separate engine caches,
    # and SQLite :memory: creates a separate DB per engine connection).
    db_file = str(tmp_path / "test_rate.db")
    db = f"sqlite+aiosqlite:///{db_file}"
    tenant = "rate-test-tenant"

    # Seed 10 audit decisions for the tenant
    _dummy_dr = {
        "application_id": "app-placeholder",
        "decision": "APPROVE",
        "reason_codes": [],
        "decision_latency_ms": 50,
    }
    for i in range(10):
        dr = dict(_dummy_dr, application_id=f"app-{i:03d}")
        await log_decision(
            decision_result=dr,
            feature_version="v1",
            model_versions={"fraud": "v1", "credit_risk": "v1"},
            input_features={"pd_score": 0.03, "fraud_probability": 0.05},
            db_url=db,
            tenant_id=tenant,
        )

    # Insert 3 override records
    from_date = "2000-01-01"
    to_date = "2099-12-31"
    for _ in range(3):
        rec = _make_record(tenant_id=tenant)
        await log_override(rec, db)

    rate = await get_override_rate(tenant, from_date, to_date, db)
    assert rate == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# test_empty_chain_is_valid
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_chain_is_valid():
    """An empty chain (no records for a tenant) is considered valid."""
    db = "sqlite+aiosqlite:///:memory:"
    result = await verify_override_chain("nonexistent-tenant", db)
    assert result is True
