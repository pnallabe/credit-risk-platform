"""
decision-api/tests/test_referral_queue.py
==========================================
Tests for the referral queue and override workflow (GAP-23).
"""
from __future__ import annotations

import uuid

import pytest


def _db_url(tmp_path) -> str:
    return str(tmp_path / "referral.db")


@pytest.mark.asyncio
async def test_create_referral_inserts_pending(tmp_path):
    from referral_store import create_referral

    db_url = _db_url(tmp_path)
    app_id = str(uuid.uuid4())

    record = await create_referral(
        db_url=db_url,
        application_id=app_id,
        tenant_id="t1",
        audit_log_id="audit_123",
        pd_score=0.08,
        fraud_probability=0.02,
        sla_hours=72,
    )

    assert record.status == "pending"
    assert record.application_id == app_id
    assert record.sla_deadline > record.created_at


@pytest.mark.asyncio
async def test_claim_referral_transitions_status(tmp_path):
    from referral_store import create_referral, claim_referral

    db_url = _db_url(tmp_path)
    record = await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")
    claimed = await claim_referral(db_url, record.referral_id, claimed_by="officer_a")

    assert claimed.status == "claimed"
    assert claimed.claimed_by == "officer_a"


@pytest.mark.asyncio
async def test_claim_pending_only_raises_on_already_claimed(tmp_path):
    from referral_store import create_referral, claim_referral

    db_url = _db_url(tmp_path)
    record = await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")
    await claim_referral(db_url, record.referral_id, claimed_by="officer_a")

    with pytest.raises(ValueError):
        await claim_referral(db_url, record.referral_id, claimed_by="officer_b")


@pytest.mark.asyncio
async def test_resolve_referral_approve(tmp_path):
    from referral_store import create_referral, claim_referral, resolve_referral

    db_url = _db_url(tmp_path)
    record = await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")
    await claim_referral(db_url, record.referral_id, claimed_by="officer_a")
    resolved = await resolve_referral(
        db_url=db_url,
        referral_id=record.referral_id,
        resolved_by="officer_a",
        resolution="APPROVE",
        resolution_notes="Verified income documentation thoroughly",
        approved_by="supervisor_b",
    )

    assert resolved.status == "resolved"
    assert resolved.resolution == "APPROVE"
    assert resolved.override_id is not None


@pytest.mark.asyncio
async def test_resolve_four_eyes_violation(tmp_path):
    from referral_store import create_referral, claim_referral, resolve_referral

    db_url = _db_url(tmp_path)
    record = await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")
    await claim_referral(db_url, record.referral_id, claimed_by="officer_a")

    with pytest.raises(PermissionError):
        await resolve_referral(
            db_url=db_url,
            referral_id=record.referral_id,
            resolved_by="officer_a",
            resolution="APPROVE",
            resolution_notes="Valid resolution with enough characters",
            approved_by="officer_a",  # same user — SOD violation
        )


@pytest.mark.asyncio
async def test_resolve_notes_too_short(tmp_path):
    from referral_store import create_referral, resolve_referral

    db_url = _db_url(tmp_path)
    record = await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")

    with pytest.raises(ValueError):
        await resolve_referral(
            db_url=db_url,
            referral_id=record.referral_id,
            resolved_by="officer_a",
            resolution="REJECT",
            resolution_notes="Too short",
            approved_by="supervisor_b",
        )


@pytest.mark.asyncio
async def test_get_queue_pagination(tmp_path):
    from referral_store import create_referral, get_queue

    db_url = _db_url(tmp_path)
    for _ in range(5):
        await create_referral(db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1")

    records, total = await get_queue(db_url, "t1", per_page=2, page=1)
    assert len(records) == 2
    assert total == 5


@pytest.mark.asyncio
async def test_sla_breach_detection(tmp_path):
    from referral_store import create_referral, get_sla_breaches

    db_url = _db_url(tmp_path)
    await create_referral(
        db_url=db_url,
        application_id=str(uuid.uuid4()),
        tenant_id="t1",
        sla_hours=0,  # immediately breached
    )

    breaches = await get_sla_breaches(db_url, "t1")
    assert len(breaches) >= 1


@pytest.mark.asyncio
async def test_sla_status_updated_on_queue_query(tmp_path):
    from referral_store import create_referral, get_queue

    db_url = _db_url(tmp_path)
    await create_referral(
        db_url=db_url,
        application_id=str(uuid.uuid4()),
        tenant_id="t1",
        sla_hours=0,
    )

    records, _ = await get_queue(db_url, "t1")
    assert any(r.status == "sla_breached" for r in records)
