"""
Smoke tests for compliance/committee_approval_store.py
"""
from __future__ import annotations

import uuid

import pytest

from compliance.committee_approval_store import (
    CommitteeApproval,
    save_approval,
    list_approvals,
)


def _make_approval(**kwargs) -> CommitteeApproval:
    defaults = dict(
        approval_id=str(uuid.uuid4()),
        tenant_id="tenant-a",
        subject="Q4 Credit Policy Update",
        approval_type="POLICY_CHANGE",
        submitted_by="alice@example.com",
        approved_by="bob@example.com",
        approved_at="2026-01-15T10:00:00+00:00",
        notes="Approved after quarterly review",
        effective_date="2026-02-01",
    )
    defaults.update(kwargs)
    return CommitteeApproval(**defaults)


def test_committee_approval_dataclass():
    a = _make_approval()
    assert a.tenant_id == "tenant-a"
    assert a.approval_type == "POLICY_CHANGE"
    assert a.submitted_by == "alice@example.com"
    assert a.approved_by == "bob@example.com"


@pytest.mark.asyncio
async def test_save_approval_returns_id():
    db_url = "sqlite+aiosqlite://"
    approval = _make_approval()
    result_id = await save_approval(approval, db_url)
    assert result_id == approval.approval_id


@pytest.mark.asyncio
async def test_list_approvals_returns_saved():
    db_url = "sqlite+aiosqlite://"
    approval = _make_approval(tenant_id="tenant-list", approved_at="2026-03-01T10:00:00+00:00")
    await save_approval(approval, db_url)

    results = await list_approvals("tenant-list", "2026-01-01", "2026-12-31", db_url)
    assert len(results) >= 1
    assert any(r.approval_id == approval.approval_id for r in results)


@pytest.mark.asyncio
async def test_list_approvals_filters_by_tenant():
    db_url = "sqlite+aiosqlite://"
    a1 = _make_approval(tenant_id="tenant-X", approved_at="2026-03-01T10:00:00+00:00")
    a2 = _make_approval(tenant_id="tenant-Y", approved_at="2026-03-01T10:00:00+00:00")
    await save_approval(a1, db_url)
    await save_approval(a2, db_url)

    results = await list_approvals("tenant-X", "2026-01-01", "2026-12-31", db_url)
    tenant_ids = {r.tenant_id for r in results}
    assert "tenant-Y" not in tenant_ids


@pytest.mark.asyncio
async def test_list_approvals_empty_range():
    db_url = "sqlite+aiosqlite://"
    results = await list_approvals("tenant-empty", "2025-01-01", "2025-01-31", db_url)
    assert isinstance(results, list)
    assert results == []
