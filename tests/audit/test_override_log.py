"""
Smoke tests for audit/override_log.py
"""
from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from audit.override_log import (
    OVERRIDE_LOG_DDL,
    PolicyOverrideRecord,
    _compute_record_hash,
    log_override,
    get_override_rate,
    verify_override_chain,
)


def _make_record(**kwargs) -> PolicyOverrideRecord:
    defaults = dict(
        override_id="ov-001",
        decision_id="app-001",
        tenant_id="tenant-a",
        override_type="pd_threshold",
        original_value=0.25,
        override_value=0.30,
        justification="Seasonal credit tightening for Q4 risk management",
        submitted_by="alice@example.com",
        approved_by="bob@example.com",
        approved_at="2026-01-01T12:00:00+00:00",
        record_hash="",
        previous_hash="GENESIS",
    )
    defaults.update(kwargs)
    return PolicyOverrideRecord(**defaults)


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------

def test_policy_override_record_creation():
    r = _make_record()
    assert r.override_id == "ov-001"
    assert r.tenant_id == "tenant-a"
    assert r.submitted_by == "alice@example.com"
    assert r.approved_by == "bob@example.com"


def test_policy_override_record_default_hashes():
    r = _make_record()
    assert r.record_hash == ""
    assert r.previous_hash == "GENESIS"


def test_compute_record_hash_is_deterministic():
    r = _make_record()
    h1 = _compute_record_hash(r)
    h2 = _compute_record_hash(r)
    assert h1 == h2


def test_compute_record_hash_changes_on_field_change():
    r1 = _make_record(override_value=0.30)
    r2 = _make_record(override_value=0.35)
    assert _compute_record_hash(r1) != _compute_record_hash(r2)


def test_compute_record_hash_is_sha256():
    r = _make_record()
    h = _compute_record_hash(r)
    # SHA-256 hex digest is 64 chars
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_override_log_ddl_contains_table_name():
    assert "policy_overrides_log" in OVERRIDE_LOG_DDL


def test_compute_record_hash_matches_manual():
    r = _make_record(record_hash="", previous_hash="GENESIS")
    expected = hashlib.sha256(
        json.dumps(dataclasses.asdict(r), sort_keys=True).encode()
    ).hexdigest()
    assert _compute_record_hash(r) == expected


# ---------------------------------------------------------------------------
# Async DB tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_log_override_and_get_rate():
    db_url = "sqlite+aiosqlite://"
    r = _make_record()
    override_id = await log_override(r, db_url)
    assert override_id is not None and len(override_id) > 0

    # get_override_rate for the same tenant/window
    rate = await get_override_rate("tenant-a", "2025-01-01", "2027-01-01", db_url)
    assert isinstance(rate, float)
    assert rate >= 0.0


@pytest.mark.asyncio
async def test_verify_override_chain_empty_db():
    db_url = "sqlite+aiosqlite://"
    valid = await verify_override_chain("tenant-a", db_url)
    assert valid is True  # empty chain is valid


@pytest.mark.asyncio
async def test_verify_override_chain_with_one_record():
    db_url = "sqlite+aiosqlite:///file:chain_test?mode=memory&cache=shared&uri=true"
    r = _make_record(tenant_id="tenant-chain")
    await log_override(r, db_url)
    valid = await verify_override_chain("tenant-chain", db_url)
    assert valid is True
