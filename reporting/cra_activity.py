"""CRA (Community Reinvestment Act) Activity Report generator.

Produces a structured CRA activity report from underwriting audit-log records,
categorising each application by income tier (as a percentage of the Area Median
Income, AMI) and by action taken.

Income tier definitions (OCC/Federal Reserve standard):
  LOW         : annual_income < 50 % of AMI
  MODERATE    : 50 % ≤ annual_income < 80 % of AMI
  MIDDLE      : 80 % ≤ annual_income < 120 % of AMI
  UPPER       : annual_income ≥ 120 % of AMI

Output:
  CRAActivityReport  — aggregate statistics object
  to_csv()           — write the report as a single-row CSV
  from_audit_log_records()  — build a report from raw audit-log dicts

All monetary amounts are in US Dollars.  When annual_income is absent or
non-numeric the application is counted in an UNKNOWN bucket and excluded from
the AMI-based categories.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CRA income-tier thresholds expressed as fractions of AMI.
# The caller supplies the AMI for the relevant geography; the defaults below
# are illustrative placeholders.
_DEFAULT_AMI: float = 75_000.0  # USD — override via generate_cra_activity_report()

# Income tier fractions (lower bound inclusive, upper bound exclusive)
_TIER_LOW_MAX: float = 0.50        # < 50 % AMI
_TIER_MOD_MIN: float = 0.50        # 50 %
_TIER_MOD_MAX: float = 0.80        # 80 %
_TIER_MID_MIN: float = 0.80        # 80 %
_TIER_MID_MAX: float = 1.20        # 120 %
_TIER_UPPER_MIN: float = 1.20      # ≥ 120 %


def _classify_income_tier(annual_income: float, ami: float) -> str:
    """Return the CRA income tier for *annual_income* relative to *ami*."""
    if ami <= 0:
        return "UNKNOWN"
    ratio = annual_income / ami
    if ratio < _TIER_LOW_MAX:
        return "LOW"
    elif ratio < _TIER_MOD_MAX:
        return "MODERATE"
    elif ratio < _TIER_MID_MAX:
        return "MIDDLE"
    else:
        return "UPPER"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CRAIncomeTierStats:
    """Decision counts and aggregate loan amounts for one income tier."""

    tier: str
    total_applications: int = 0
    approvals: int = 0
    denials: int = 0
    total_loan_amount: float = 0.0
    approved_loan_amount: float = 0.0

    @property
    def approval_rate(self) -> float:
        if self.total_applications == 0:
            return 0.0
        return self.approvals / self.total_applications

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tier": self.tier,
            "total_applications": self.total_applications,
            "approvals": self.approvals,
            "denials": self.denials,
            "approval_rate": round(self.approval_rate, 4),
            "total_loan_amount": round(self.total_loan_amount, 2),
            "approved_loan_amount": round(self.approved_loan_amount, 2),
        }


@dataclass
class CRAActivityReport:
    """Aggregate CRA activity statistics for a single tenant and period."""

    tenant_id: str
    period_start: date
    period_end: date
    ami: float
    total_applications: int = 0
    total_approvals: int = 0
    total_denials: int = 0
    total_loan_amount: float = 0.0
    # Per-tier stats — populated by generate_cra_activity_report()
    tiers: Dict[str, CRAIncomeTierStats] = field(default_factory=dict)

    @property
    def overall_approval_rate(self) -> float:
        if self.total_applications == 0:
            return 0.0
        return self.total_approvals / self.total_applications

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "ami": self.ami,
            "total_applications": self.total_applications,
            "total_approvals": self.total_approvals,
            "total_denials": self.total_denials,
            "total_loan_amount": round(self.total_loan_amount, 2),
            "overall_approval_rate": round(self.overall_approval_rate, 4),
            "tiers": {k: v.to_dict() for k, v in self.tiers.items()},
        }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def to_csv(report: CRAActivityReport, output: Optional[io.StringIO] = None) -> str:
    """Serialise *report* to CSV (flat row per income tier).

    If *output* is None a new ``StringIO`` is created; the final CSV string is
    returned.
    """
    buf = output or io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "tenant_id",
            "period_start",
            "period_end",
            "ami",
            "tier",
            "total_applications",
            "approvals",
            "denials",
            "approval_rate",
            "total_loan_amount",
            "approved_loan_amount",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for tier_name in ("LOW", "MODERATE", "MIDDLE", "UPPER", "UNKNOWN"):
        stats = report.tiers.get(tier_name)
        if stats is None:
            continue
        writer.writerow(
            {
                "tenant_id": report.tenant_id,
                "period_start": report.period_start.isoformat(),
                "period_end": report.period_end.isoformat(),
                "ami": report.ami,
                **stats.to_dict(),
            }
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def generate_cra_activity_report(
    records: Sequence[Dict[str, Any]],
    tenant_id: str,
    period_start: date,
    period_end: date,
    ami: float = _DEFAULT_AMI,
) -> CRAActivityReport:
    """Build a ``CRAActivityReport`` from a sequence of audit-log record dicts.

    Expected keys in each record dict (all optional except *decision_output*):
      - ``decision_output`` : "APPROVE", "DECLINE", "REVIEW", ... (required)
      - ``annual_income``   : float — borrower annual income in USD
      - ``loan_amount``     : float — requested loan amount in USD
      - ``logged_at``       : ISO-8601 string — used to filter by period
      - ``tenant_id``       : str — records not matching *tenant_id* are skipped
    """
    report = CRAActivityReport(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
        ami=ami,
    )

    for rec in records:
        # Filter by tenant
        rec_tenant = rec.get("tenant_id", tenant_id)
        if str(rec_tenant) != str(tenant_id):
            continue

        # Filter by period
        logged_at_raw = rec.get("logged_at") or rec.get("timestamp", "")
        if logged_at_raw:
            try:
                logged_date = date.fromisoformat(str(logged_at_raw)[:10])
                if not (period_start <= logged_date <= period_end):
                    continue
            except (ValueError, TypeError):
                pass  # If parsing fails, include the record

        decision = str(rec.get("decision_output", rec.get("decision", ""))).upper()
        is_approve = decision == "APPROVE"
        is_deny = decision in ("DECLINE", "REJECT", "DENY")

        loan_amount = _safe_float(rec.get("loan_amount", 0.0))
        annual_income = _safe_float(rec.get("annual_income") or rec.get("input_features", {}).get("annual_income"))

        tier = _classify_income_tier(annual_income, ami) if annual_income is not None else "UNKNOWN"

        if tier not in report.tiers:
            report.tiers[tier] = CRAIncomeTierStats(tier=tier)

        t = report.tiers[tier]
        t.total_applications += 1
        t.total_loan_amount += loan_amount

        if is_approve:
            t.approvals += 1
            t.approved_loan_amount += loan_amount
        elif is_deny:
            t.denials += 1

        report.total_applications += 1
        report.total_loan_amount += loan_amount
        if is_approve:
            report.total_approvals += 1
        elif is_deny:
            report.total_denials += 1

    return report


def from_audit_log_records(
    records: Sequence[Dict[str, Any]],
    tenant_id: str,
    period_start: date,
    period_end: date,
    ami: float = _DEFAULT_AMI,
) -> CRAActivityReport:
    """Alias for ``generate_cra_activity_report`` — preferred public entry point."""
    return generate_cra_activity_report(records, tenant_id, period_start, period_end, ami)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> Optional[float]:
    """Convert *value* to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
