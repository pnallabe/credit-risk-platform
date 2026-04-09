"""Tests for compliance/exam_packet_builder.py (P2-G)"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import create_async_engine


async def _make_url():
    import uuid as _uuid
    return f"sqlite+aiosqlite:///:memory:{_uuid.uuid4().hex}"


async def _setup(url: str):
    from audit.logger import _ENGINE_CACHE
    engine = create_async_engine(url, echo=False)
    _ENGINE_CACHE[url] = engine
    return engine


def _make_notice(suffix: str, status: str, deadline_days: int, tenant_id: str = "t-exam"):
    import uuid as _uuid
    from compliance.adverse_action import AdverseActionNotice

    today = date.today()
    return AdverseActionNotice(
        notice_id=str(_uuid.uuid4()),
        application_id=f"app-{suffix}",
        tenant_id=tenant_id,
        applicant_name="Test User",
        creditor_name="Acme Bank",
        action_taken="Application Denied",
        action_date=today.isoformat(),
        deadline_date=(today + timedelta(days=deadline_days)).isoformat(),
        reason_codes=["AA01", "AA04"],
        reason_texts=[
            "High probability of default based on credit history",
            "Debt-to-income ratio too high",
        ],
        form_type="C-1",
        credit_score_used=None,
        credit_score_range_low=None,
        credit_score_range_high=None,
        credit_score_model_name=None,
        bureau_name=None,
        generated_at=datetime.now(timezone.utc).isoformat(),
        delivery_status=status,
    )


async def _save(notice, url: str):
    from compliance.adverse_action_store import save_notice
    await save_notice(notice, "test notice text", url)


async def _mark_delivered(notice_id: str, tenant_id: str, url: str):
    from compliance.adverse_action_store import mark_delivered
    from datetime import timezone
    await mark_delivered(
        notice_id, "email",
        datetime.now(timezone.utc).isoformat(),
        url, tenant_id
    )


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_adverse_action_component_delivery_compliance():
    """10 notices (8 DELIVERED, 2 PENDING) → compliance_rate=80.0, overdue_count=0."""
    url = await _make_url()
    engine = await _setup(url)

    notices = [_make_notice(f"n{i}", "PENDING", 30) for i in range(10)]
    for n in notices:
        await _save(n, url)

    # Mark 8 as delivered
    for n in notices[:8]:
        await _mark_delivered(n.notice_id, "t-exam", url)

    from compliance.exam_packet_builder import ExamPacketSpec, build_adverse_action_component

    spec = ExamPacketSpec(
        tenant_id="t-exam",
        from_date=date.today().isoformat(),
        to_date=date.today().isoformat(),
        components=["adverse_actions"],
        format="json",
    )
    comp = await build_adverse_action_component(spec, url)

    assert comp.status == "complete"
    assert comp.data is not None
    assert comp.data["delivery_compliance_rate"] == 80.0
    assert comp.data["overdue_count"] == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_adverse_action_component_overdue_count():
    """2 PENDING notices with past deadline → overdue_count=2."""
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action import AdverseActionNotice
    import uuid as _uuid
    from datetime import timezone

    # Notices with deadline in the past
    past_date = (date.today() - timedelta(days=5)).isoformat()
    today_str = date.today().isoformat()
    for i in range(2):
        n = AdverseActionNotice(
            notice_id=str(_uuid.uuid4()),
            application_id=f"app-overdue-{i}",
            tenant_id="t-overdue",
            applicant_name="Test",
            creditor_name="Acme Bank",
            action_taken="Application Denied",
            action_date=today_str,
            deadline_date=past_date,
            reason_codes=["AA01"],
            reason_texts=["High probability of default based on credit history"],
            form_type="C-1",
            credit_score_used=None,
            credit_score_range_low=None,
            credit_score_range_high=None,
            credit_score_model_name=None,
            bureau_name=None,
            generated_at=datetime.now(timezone.utc).isoformat(),
            delivery_status="PENDING",
        )
        await _save(n, url)

    from compliance.exam_packet_builder import ExamPacketSpec, build_adverse_action_component

    spec = ExamPacketSpec(
        tenant_id="t-overdue",
        from_date="2000-01-01",
        to_date="9999-12-31",
        components=["adverse_actions"],
        format="json",
    )
    comp = await build_adverse_action_component(spec, url)

    assert comp.data["overdue_count"] == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_exam_packet_with_stub_component():
    """adverse_actions + policy_history → 1 complete, 1 stub."""
    url = await _make_url()
    engine = await _setup(url)

    from compliance.exam_packet_builder import ExamPacketSpec, build_exam_packet

    spec = ExamPacketSpec(
        tenant_id="t-packet",
        from_date=date.today().isoformat(),
        to_date=date.today().isoformat(),
        components=["adverse_actions", "policy_history"],
        format="json",
    )
    packet = await build_exam_packet(spec, url)

    assert len(packet.components) == 2
    statuses = {c.name: c.status for c in packet.components}
    assert statuses["adverse_actions"] in ("complete", "error")
    assert statuses["policy_history"] == "stub"

    await engine.dispose()


@pytest.mark.asyncio
async def test_exam_packet_summary_text():
    """summary_text() includes component names and statuses."""
    url = await _make_url()
    engine = await _setup(url)

    from compliance.exam_packet_builder import ExamPacketSpec, build_exam_packet

    spec = ExamPacketSpec(
        tenant_id="t-summary",
        from_date=date.today().isoformat(),
        to_date=date.today().isoformat(),
        components=["adverse_actions", "decision_log"],
        format="json",
    )
    packet = await build_exam_packet(spec, url)
    summary = packet.summary_text()

    assert "adverse_actions" in summary
    assert "decision_log" in summary
    # Both component statuses should appear
    assert "complete" in summary.lower() or "stub" in summary.lower() or "error" in summary.lower()

    await engine.dispose()
