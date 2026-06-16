"""Tests for P2-F: check_adverse_action_deadlines in monitoring/alert_router.py"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine


async def _make_url():
    import uuid as _uuid
    return f"sqlite+aiosqlite:///:memory:{_uuid.uuid4().hex}"


async def _setup(url: str):
    from audit.logger import _ENGINE_CACHE
    engine = create_async_engine(url, echo=False)
    _ENGINE_CACHE[url] = engine
    return engine


def _make_notice_with_deadline(suffix: str, deadline_days_from_now: int, status: str, tenant_id: str):
    """Create and return an AdverseActionNotice with a specific deadline."""
    import uuid as _uuid
    from compliance.adverse_action import AdverseActionNotice

    today = date.today()
    deadline = (today + timedelta(days=deadline_days_from_now)).isoformat()

    return AdverseActionNotice(
        notice_id=str(_uuid.uuid4()),
        application_id=f"app-{suffix}",
        tenant_id=tenant_id,
        applicant_name="Test User",
        creditor_name="Acme Bank",
        action_taken="Application Denied",
        action_date=today.isoformat(),
        deadline_date=deadline,
        reason_codes=["AA01"],
        reason_texts=["High probability of default based on credit history"],
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


def _make_router_with_mock():
    """Return an AlertRouter with a spy so we can count send_alert calls."""
    from monitoring.alert_router import AlertRouter, LogOnlyChannel

    alerts_sent = []

    class SpyChannel(LogOnlyChannel):
        def send(self, subject: str, body: str, severity: str) -> bool:
            alerts_sent.append({"subject": subject, "severity": severity})
            return True

    router = AlertRouter(channels={
        "CRITICAL": [SpyChannel()],
        "HIGH": [SpyChannel()],
        "MEDIUM": [SpyChannel()],
        "LOW": [SpyChannel()],
    })
    return router, alerts_sent


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_alert_fired_for_notice_3_days_away():
    """PENDING notice with deadline in 3 days → returns 1 alert."""
    url = await _make_url()
    engine = await _setup(url)

    notice = _make_notice_with_deadline("3days", 3, "PENDING", "t-alert")
    await _save(notice, url)

    from monitoring.alert_router import check_adverse_action_deadlines
    router, alerts = _make_router_with_mock()

    count = await check_adverse_action_deadlines(url, "t-alert", router, warn_days_before=5)

    assert count == 1
    assert len(alerts) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_alert_for_notice_10_days_away():
    """PENDING notice with deadline in 10 days is NOT in the 5-day window → 0 alerts."""
    url = await _make_url()
    engine = await _setup(url)

    notice = _make_notice_with_deadline("10days", 10, "PENDING", "t-alert-2")
    await _save(notice, url)

    from monitoring.alert_router import check_adverse_action_deadlines
    router, alerts = _make_router_with_mock()

    count = await check_adverse_action_deadlines(url, "t-alert-2", router, warn_days_before=5)

    assert count == 0
    assert len(alerts) == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_no_alert_for_delivered_notice():
    """DELIVERED notice with deadline in 3 days → 0 alerts (already delivered)."""
    url = await _make_url()
    engine = await _setup(url)
    from compliance.adverse_action_store import mark_delivered
    from datetime import timezone

    notice = _make_notice_with_deadline("delivered", 3, "PENDING", "t-alert-3")
    await _save(notice, url)
    await mark_delivered(
        notice.notice_id, "email",
        datetime.now(timezone.utc).isoformat(),
        url, "t-alert-3"
    )

    from monitoring.alert_router import check_adverse_action_deadlines
    router, alerts = _make_router_with_mock()

    count = await check_adverse_action_deadlines(url, "t-alert-3", router, warn_days_before=5)

    assert count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_empty_table_returns_zero():
    """No notices in table → 0 alerts."""
    url = await _make_url()
    engine = await _setup(url)

    from monitoring.alert_router import check_adverse_action_deadlines
    router, alerts = _make_router_with_mock()

    count = await check_adverse_action_deadlines(url, "t-alert-empty", router)

    assert count == 0
    assert len(alerts) == 0

    await engine.dispose()
