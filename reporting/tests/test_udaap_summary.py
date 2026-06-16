"""Acceptance tests for reporting/udaap_summary.py (G5-C)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.udaap_summary import (  # noqa: E402
    UDAAPSummaryReport,
    from_audit_log_records,
    generate_udaap_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AMI = 80_000.0
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)
TENANT = "tenant-a"


def _audit(
    decision: str,
    state: str = "CA",
    annual_income: float = 60_000.0,
    apr: float = 0.10,
    tenant_id: str = TENANT,
    logged_at: str = "2025-06-15",
) -> dict:
    return {
        "decision_output": decision,
        "borrower_state": state,
        "annual_income": annual_income,
        "apr": apr if decision == "APPROVE" else None,
        "tenant_id": tenant_id,
        "logged_at": logged_at,
    }


def _complaint(
    category: str = "BILLING",
    status: str = "UNRESOLVED",
    tenant_id: str = TENANT,
    filed_at: str = "2025-06-15",
) -> dict:
    return {
        "category": category,
        "status": status,
        "tenant_id": tenant_id,
        "filed_at": filed_at,
    }


# ---------------------------------------------------------------------------
# Test 1: Empty inputs → zero counts
# ---------------------------------------------------------------------------

def test_empty_inputs():
    report = generate_udaap_summary([], [], TENANT, PERIOD_START, PERIOD_END)
    assert report.total_applications == 0
    assert report.total_complaints == 0
    assert report.risk_flags == []


# ---------------------------------------------------------------------------
# Test 2: Denial rates computed per state
# ---------------------------------------------------------------------------

def test_denial_rate_by_state():
    records = [
        _audit("APPROVE", state="CA"),
        _audit("DECLINE", state="CA"),
        _audit("APPROVE", state="TX"),
    ]
    report = generate_udaap_summary(records, [], TENANT, PERIOD_START, PERIOD_END)
    ca_stats = report.denial_by_state["CA"]
    tx_stats = report.denial_by_state["TX"]
    assert ca_stats.denial_rate == pytest.approx(0.5)
    assert tx_stats.denial_rate == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Test 3: Denial rates computed per income tier
# ---------------------------------------------------------------------------

def test_denial_rate_by_income_tier():
    records = [
        _audit("DECLINE", annual_income=20_000),  # < 50% AMI → LOW
        _audit("DECLINE", annual_income=25_000),  # LOW
        _audit("APPROVE", annual_income=25_000),  # LOW approve
        _audit("APPROVE", annual_income=90_000),  # MIDDLE
    ]
    report = generate_udaap_summary(records, [], TENANT, PERIOD_START, PERIOD_END, AMI)
    assert "LOW" in report.denial_by_income_tier
    low_stats = report.denial_by_income_tier["LOW"]
    assert low_stats.total_applications == 3
    assert low_stats.denials == 2
    assert low_stats.denial_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Test 4: APR variance is computed for approved applications
# ---------------------------------------------------------------------------

def test_apr_variance_computed():
    records = [
        _audit("APPROVE", apr=0.10),
        _audit("APPROVE", apr=0.12),
        _audit("APPROVE", apr=0.15),
        _audit("DECLINE", apr=None),
    ]
    report = generate_udaap_summary(records, [], TENANT, PERIOD_START, PERIOD_END)
    assert report.apr_variance.total_approved == 3
    assert report.apr_variance.median_apr is not None
    assert report.apr_variance.mean_apr is not None


# ---------------------------------------------------------------------------
# Test 5: Complaint aggregation by category
# ---------------------------------------------------------------------------

def test_complaint_aggregation():
    complaints = [
        _complaint("BILLING", status="RESOLVED"),
        _complaint("BILLING", status="UNRESOLVED"),
        _complaint("PRICING", status="UNRESOLVED"),
    ]
    report = generate_udaap_summary([], complaints, TENANT, PERIOD_START, PERIOD_END)
    assert report.total_complaints == 3
    assert report.unresolved_complaints == 2
    assert report.complaints["BILLING"].count == 2
    assert report.complaints["BILLING"].resolved == 1
    assert report.complaints["PRICING"].count == 1


# ---------------------------------------------------------------------------
# Test 6: Tenant filter — other-tenant records excluded
# ---------------------------------------------------------------------------

def test_tenant_filter():
    records = [
        _audit("APPROVE", tenant_id="tenant-a"),
        _audit("DECLINE", tenant_id="tenant-b"),
    ]
    complaints = [
        _complaint(tenant_id="tenant-a"),
        _complaint(tenant_id="tenant-b"),
    ]
    report = generate_udaap_summary(records, complaints, "tenant-a", PERIOD_START, PERIOD_END)
    assert report.total_applications == 1
    assert report.total_complaints == 1


# ---------------------------------------------------------------------------
# Test 7: Period filter — records outside window excluded
# ---------------------------------------------------------------------------

def test_period_filter():
    records = [
        _audit("APPROVE", logged_at="2025-06-15"),  # in window
        _audit("DECLINE", logged_at="2024-12-31"),  # before window
    ]
    report = generate_udaap_summary(records, [], TENANT, PERIOD_START, PERIOD_END)
    assert report.total_applications == 1


# ---------------------------------------------------------------------------
# Test 8: HIGH_OVERALL_DENIAL_RATE risk flag raised when > 50%
# ---------------------------------------------------------------------------

def test_high_denial_rate_flag():
    # 3 denials, 1 approval → 75% denial
    records = [_audit("DECLINE")] * 3 + [_audit("APPROVE")]
    report = generate_udaap_summary(records, [], TENANT, PERIOD_START, PERIOD_END)
    flags = " ".join(report.risk_flags)
    assert "HIGH_OVERALL_DENIAL_RATE" in flags


# ---------------------------------------------------------------------------
# Test 9: ELEVATED_UNRESOLVED_COMPLAINTS flag raised at threshold
# ---------------------------------------------------------------------------

def test_unresolved_complaint_flag():
    import reporting.udaap_summary as mod
    old_threshold = mod.UNRESOLVED_COMPLAINT_FLAG_THRESHOLD
    mod.UNRESOLVED_COMPLAINT_FLAG_THRESHOLD = 3
    try:
        complaints = [_complaint(status="UNRESOLVED") for _ in range(4)]
        report = generate_udaap_summary([], complaints, TENANT, PERIOD_START, PERIOD_END)
        flags = " ".join(report.risk_flags)
        assert "ELEVATED_UNRESOLVED_COMPLAINTS" in flags
    finally:
        mod.UNRESOLVED_COMPLAINT_FLAG_THRESHOLD = old_threshold


# ---------------------------------------------------------------------------
# Test 10: from_audit_log_records alias works
# ---------------------------------------------------------------------------

def test_from_audit_log_records_alias():
    records = [_audit("APPROVE")]
    report = from_audit_log_records(records, [], TENANT, PERIOD_START, PERIOD_END)
    assert isinstance(report, UDAAPSummaryReport)
    assert report.total_applications == 1


# ---------------------------------------------------------------------------
# Test 11: to_dict returns all required keys
# ---------------------------------------------------------------------------

def test_to_dict_structure():
    report = generate_udaap_summary(
        [_audit("APPROVE")],
        [_complaint()],
        TENANT,
        PERIOD_START,
        PERIOD_END,
    )
    d = report.to_dict()
    for key in (
        "tenant_id",
        "period_start",
        "period_end",
        "total_applications",
        "total_approvals",
        "total_denials",
        "overall_denial_rate",
        "denial_by_state",
        "denial_by_income_tier",
        "apr_variance",
        "complaints",
        "total_complaints",
        "unresolved_complaints",
        "risk_flags",
    ):
        assert key in d, f"Missing key: {key}"
