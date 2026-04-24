"""
compliance/tests/test_exam_packet_approval.py
=============================================
Tests for the HITL exam packet approval gate (GAP-22).
"""
from __future__ import annotations

import json
import uuid

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _db_url(tmp_path) -> str:
    return str(tmp_path / "approvals.db")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_creates_pending_record(tmp_path):
    from compliance.exam_packet_approval_store import submit_packet_for_approval

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    record = await submit_packet_for_approval(
        db_url=db_url,
        packet_id=packet_id,
        tenant_id="tenant_a",
        generated_by="user_a",
        packet_json=json.dumps({"packet_id": packet_id}),
    )

    assert record.packet_id == packet_id
    assert record.status == "pending_approval"
    assert record.reviewed_by is None


@pytest.mark.asyncio
async def test_approve_transitions_to_approved(tmp_path):
    from compliance.exam_packet_approval_store import (
        submit_packet_for_approval,
        approve_packet,
        get_approved_packet_json,
    )

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())
    packet_json = json.dumps({"packet_id": packet_id, "data": "test"})

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json=packet_json,
    )
    record = await approve_packet(db_url, packet_id, reviewed_by="user_b", review_notes="Looks good")

    assert record.status == "approved"
    assert record.reviewed_by == "user_b"

    retrieved_json = await get_approved_packet_json(db_url, packet_id)
    assert retrieved_json == packet_json


@pytest.mark.asyncio
async def test_reject_transitions_to_rejected(tmp_path):
    from compliance.exam_packet_approval_store import submit_packet_for_approval, reject_packet

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json="{}",
    )
    record = await reject_packet(db_url, packet_id, reviewed_by="user_b", review_notes="Missing data sections")

    assert record.status == "rejected"


@pytest.mark.asyncio
async def test_sod_violation_raises_permission_error(tmp_path):
    from compliance.exam_packet_approval_store import submit_packet_for_approval, approve_packet

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json="{}",
    )

    with pytest.raises(PermissionError) as exc_info:
        await approve_packet(db_url, packet_id, reviewed_by="user_a")
    assert "SOD" in str(exc_info.value)


@pytest.mark.asyncio
async def test_double_approval_raises_value_error(tmp_path):
    from compliance.exam_packet_approval_store import (
        submit_packet_for_approval,
        approve_packet,
    )

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json="{}",
    )
    await approve_packet(db_url, packet_id, reviewed_by="user_b")

    with pytest.raises(ValueError):
        await approve_packet(db_url, packet_id, reviewed_by="user_c")


@pytest.mark.asyncio
async def test_get_approved_raises_permission_error_when_pending(tmp_path):
    from compliance.exam_packet_approval_store import (
        submit_packet_for_approval,
        get_approved_packet_json,
    )

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json="{}",
    )

    with pytest.raises(PermissionError):
        await get_approved_packet_json(db_url, packet_id)


@pytest.mark.asyncio
async def test_reject_requires_notes(tmp_path):
    from compliance.exam_packet_approval_store import submit_packet_for_approval, reject_packet

    db_url = _db_url(tmp_path)
    packet_id = str(uuid.uuid4())

    await submit_packet_for_approval(
        db_url=db_url, packet_id=packet_id, tenant_id="t1",
        generated_by="user_a", packet_json="{}",
    )

    with pytest.raises(ValueError):
        await reject_packet(db_url, packet_id, reviewed_by="user_b", review_notes="")


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending(tmp_path):
    from compliance.exam_packet_approval_store import (
        submit_packet_for_approval,
        approve_packet,
        reject_packet,
        list_pending_packets,
    )

    db_url = _db_url(tmp_path)

    ids = [str(uuid.uuid4()) for _ in range(3)]
    for i, pid in enumerate(ids):
        await submit_packet_for_approval(
            db_url=db_url, packet_id=pid, tenant_id="t1",
            generated_by=f"user_{i}", packet_json="{}"
        )

    # Approve first, reject second, leave third pending
    await approve_packet(db_url, ids[0], reviewed_by="approver_a")
    await reject_packet(db_url, ids[1], reviewed_by="approver_b", review_notes="Rejected for testing reasons")

    pending = await list_pending_packets(db_url, tenant_id="t1")
    assert len(pending) == 1
    assert pending[0].packet_id == ids[2]
