"""
monitoring/tests/test_referral_sla.py
=======================================
Tests for the referral SLA monitor (GAP-23).
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def _make_breach(referral_id: str = None) -> object:
    class _R:
        pass
    r = _R()
    r.referral_id = referral_id or str(uuid.uuid4())
    r.status = "sla_breached"
    return r


@pytest.mark.asyncio
async def test_no_breaches_returns_zero_report(tmp_path):
    """When no SLA breaches exist, report has breach_count=0."""
    from monitoring.referral_sla_monitor import monitor_referral_sla

    async def _empty_breaches(db_url, tenant_id):
        return []

    report = await monitor_referral_sla(
        db_url=str(tmp_path / "ref.db"),
        tenant_id="t1",
        get_breaches_fn=_empty_breaches,
        alert_router=None,
    )

    assert report.breach_count == 0
    assert report.alert_fired is False
    assert report.tenant_id == "t1"


@pytest.mark.asyncio
async def test_breaches_fires_alert():
    """When SLA breaches exist, alert_router.dispatch is called."""
    from monitoring.referral_sla_monitor import monitor_referral_sla

    breach_ids = [str(uuid.uuid4()) for _ in range(3)]
    breaches = [_make_breach(rid) for rid in breach_ids]

    async def _with_breaches(db_url, tenant_id):
        return breaches

    mock_router = MagicMock()
    mock_router.dispatch = MagicMock(return_value=True)

    report = await monitor_referral_sla(
        db_url="test.db",
        tenant_id="t1",
        get_breaches_fn=_with_breaches,
        alert_router=mock_router,
    )

    assert report.breach_count == 3
    assert report.alert_fired is True
    mock_router.dispatch.assert_called_once()


@pytest.mark.asyncio
async def test_alert_router_none_no_exception():
    """No exception when alert_router is None and breaches exist."""
    from monitoring.referral_sla_monitor import monitor_referral_sla

    async def _with_breaches(db_url, tenant_id):
        return [_make_breach()]

    report = await monitor_referral_sla(
        db_url="test.db",
        tenant_id="t1",
        get_breaches_fn=_with_breaches,
        alert_router=None,
    )

    assert report.breach_count == 1
    assert report.alert_fired is False


@pytest.mark.asyncio
async def test_breach_ids_in_report():
    """breach_referral_ids contains the IDs of all breached cases."""
    from monitoring.referral_sla_monitor import monitor_referral_sla

    expected_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

    async def _breaches(db_url, tenant_id):
        return [_make_breach(rid) for rid in expected_ids]

    report = await monitor_referral_sla(
        db_url="test.db",
        tenant_id="t1",
        get_breaches_fn=_breaches,
        alert_router=None,
    )

    assert set(report.breach_referral_ids) == set(expected_ids)


@pytest.mark.asyncio
async def test_get_breaches_error_returns_zero_report():
    """If get_breaches_fn raises, report has breach_count=0 and no exception."""
    from monitoring.referral_sla_monitor import monitor_referral_sla

    async def _broken(db_url, tenant_id):
        raise RuntimeError("DB failure")

    report = await monitor_referral_sla(
        db_url="test.db",
        tenant_id="t1",
        get_breaches_fn=_broken,
        alert_router=None,
    )

    assert report.breach_count == 0
    assert report.alert_fired is False
