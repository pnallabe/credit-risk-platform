"""
Smoke tests for compliance/regulatory_horizon.py

All BigQuery-dependent paths return no-ops when BigQuery is absent (the default
in CI / local dev).  These tests verify the no-op paths and the pure-logic helpers.
"""
from __future__ import annotations

from compliance.regulatory_horizon import (
    ALERT_DAYS,
    SEVERITY_ESCALATION,
    flag_overdue_horizon_items,
    get_horizon_items,
    scan_horizon,
    update_days_remaining,
)


def test_scan_horizon_no_bq_returns_empty(monkeypatch):
    """With no BigQuery, scan_horizon() must return an empty list, not raise."""
    import compliance.regulatory_horizon as rh
    monkeypatch.setattr(rh, "_BQ_AVAILABLE", False)
    result = scan_horizon()
    assert isinstance(result, list)
    assert result == []


def test_get_horizon_items_no_bq_returns_empty(monkeypatch):
    import compliance.regulatory_horizon as rh
    monkeypatch.setattr(rh, "_BQ_AVAILABLE", False)
    result = get_horizon_items(max_days=90)
    assert isinstance(result, list)
    assert result == []


def test_flag_overdue_no_bq_returns_empty(monkeypatch):
    import compliance.regulatory_horizon as rh
    monkeypatch.setattr(rh, "_BQ_AVAILABLE", False)
    result = flag_overdue_horizon_items()
    assert isinstance(result, list)
    assert result == []


def test_update_days_remaining_no_bq_is_noop(monkeypatch):
    """Must not raise when BigQuery is absent."""
    import compliance.regulatory_horizon as rh
    monkeypatch.setattr(rh, "_BQ_AVAILABLE", False)
    update_days_remaining()


def test_alert_days_are_sorted_descending():
    assert ALERT_DAYS == sorted(ALERT_DAYS, reverse=True)


def test_severity_escalation_covers_all_alert_days():
    for day in ALERT_DAYS:
        assert day in SEVERITY_ESCALATION, f"SEVERITY_ESCALATION missing key {day}"


def test_severity_escalation_critical_at_30_days():
    assert SEVERITY_ESCALATION[30] == "CRITICAL"
    assert SEVERITY_ESCALATION[7] == "CRITICAL"
