"""Acceptance tests for reporting/cra_activity.py (G5-A)."""

from __future__ import annotations

import csv
import io
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.cra_activity import (  # noqa: E402
    CRAActivityReport,
    from_audit_log_records,
    generate_cra_activity_report,
    to_csv,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

AMI = 80_000.0
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)
TENANT = "tenant-a"


def _rec(
    decision: str,
    annual_income: float,
    loan_amount: float = 10_000.0,
    tenant_id: str = TENANT,
    logged_at: str = "2025-06-15",
) -> dict:
    return {
        "decision_output": decision,
        "annual_income": annual_income,
        "loan_amount": loan_amount,
        "tenant_id": tenant_id,
        "logged_at": logged_at,
    }


# ---------------------------------------------------------------------------
# Test 1: Empty records → zero totals
# ---------------------------------------------------------------------------

def test_empty_records():
    report = generate_cra_activity_report([], TENANT, PERIOD_START, PERIOD_END, AMI)
    assert report.total_applications == 0
    assert report.total_approvals == 0
    assert report.overall_approval_rate == 0.0


# ---------------------------------------------------------------------------
# Test 2: Income tiers are classified correctly
# ---------------------------------------------------------------------------

def test_income_tier_classification():
    records = [
        _rec("APPROVE", annual_income=30_000),   # < 50% of 80k = 40k → LOW
        _rec("APPROVE", annual_income=55_000),   # 50-80% → MODERATE
        _rec("APPROVE", annual_income=90_000),   # 80-120% → MIDDLE
        _rec("APPROVE", annual_income=120_000),  # ≥ 120% → UPPER
    ]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert "LOW" in report.tiers
    assert "MODERATE" in report.tiers
    assert "MIDDLE" in report.tiers
    assert "UPPER" in report.tiers
    assert report.total_applications == 4


# ---------------------------------------------------------------------------
# Test 3: Approval rate computed correctly per tier
# ---------------------------------------------------------------------------

def test_approval_rate_per_tier():
    records = [
        _rec("APPROVE", annual_income=30_000),   # LOW APPROVE
        _rec("DECLINE", annual_income=35_000),   # LOW DECLINE
        _rec("APPROVE", annual_income=55_000),   # MODERATE APPROVE
    ]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert report.tiers["LOW"].approval_rate == pytest.approx(0.5)
    assert report.tiers["MODERATE"].approval_rate == pytest.approx(1.0)
    assert report.total_approvals == 2
    assert report.total_denials == 1


# ---------------------------------------------------------------------------
# Test 4: Tenant filter — records for other tenants are excluded
# ---------------------------------------------------------------------------

def test_tenant_filtering():
    records = [
        _rec("APPROVE", annual_income=50_000, tenant_id="tenant-a"),
        _rec("APPROVE", annual_income=50_000, tenant_id="tenant-b"),  # should be excluded
    ]
    report = generate_cra_activity_report(records, "tenant-a", PERIOD_START, PERIOD_END, AMI)
    assert report.total_applications == 1
    assert report.total_approvals == 1


# ---------------------------------------------------------------------------
# Test 5: Period filter — records outside window are excluded
# ---------------------------------------------------------------------------

def test_period_filtering():
    records = [
        _rec("APPROVE", annual_income=50_000, logged_at="2025-06-15"),  # in window
        _rec("APPROVE", annual_income=50_000, logged_at="2024-12-31"),  # before
        _rec("APPROVE", annual_income=50_000, logged_at="2026-01-01"),  # after
    ]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert report.total_applications == 1


# ---------------------------------------------------------------------------
# Test 6: from_audit_log_records alias works
# ---------------------------------------------------------------------------

def test_from_audit_log_records_alias():
    records = [_rec("APPROVE", annual_income=60_000)]
    report = from_audit_log_records(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert isinstance(report, CRAActivityReport)
    assert report.total_approvals == 1


# ---------------------------------------------------------------------------
# Test 7: to_csv produces valid CSV with correct columns
# ---------------------------------------------------------------------------

def test_to_csv_structure():
    records = [
        _rec("APPROVE", annual_income=30_000),
        _rec("DECLINE", annual_income=60_000),
    ]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    csv_str = to_csv(report)
    reader = csv.DictReader(io.StringIO(csv_str))
    rows = list(reader)
    assert len(rows) > 0
    assert "tenant_id" in rows[0]
    assert "tier" in rows[0]
    assert "approval_rate" in rows[0]


# ---------------------------------------------------------------------------
# Test 8: Loan amounts aggregated correctly
# ---------------------------------------------------------------------------

def test_loan_amount_aggregation():
    records = [
        _rec("APPROVE", annual_income=30_000, loan_amount=5_000),
        _rec("APPROVE", annual_income=30_000, loan_amount=10_000),
    ]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert report.total_loan_amount == pytest.approx(15_000.0)
    assert report.tiers["LOW"].approved_loan_amount == pytest.approx(15_000.0)


# ---------------------------------------------------------------------------
# Test 9: Records without annual_income land in UNKNOWN tier
# ---------------------------------------------------------------------------

def test_missing_income_goes_to_unknown():
    records = [{"decision_output": "APPROVE", "tenant_id": TENANT, "logged_at": "2025-06-15"}]
    report = generate_cra_activity_report(records, TENANT, PERIOD_START, PERIOD_END, AMI)
    assert "UNKNOWN" in report.tiers
    assert report.tiers["UNKNOWN"].total_applications == 1
