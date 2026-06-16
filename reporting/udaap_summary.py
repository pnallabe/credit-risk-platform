"""UDAAP (Unfair, Deceptive, or Abusive Acts or Practices) Summary Report.

Aggregates complaint and adverse-action records to surface potential UDAAP
risk signals for periodic regulatory review.

The report focuses on three primary risk dimensions:

1. Adverse-Action Concentration
   High denial rates for protected-class proxies (state, income tier) may
   indicate disparate impact warranting review under UDAAP / ECOA.

2. Fee / APR Variance
   Approved applications whose APR differs markedly from the median suggest
   pricing inconsistency that could be construed as deceptive or unfair.

3. Complaint Volume
   Complaints are aggregated by category and tenant; elevated complaint rates
   signal potential abusive practices.

Output:
  UDAAPSummaryReport   — top-level aggregate
  to_dict()            — serialisable representation
  generate_udaap_summary()  — main entry point
  from_audit_log_records()  — convenience alias with same signature
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AdverseActionStats:
    """Denial statistics broken out by a single dimension value."""

    dimension: str      # e.g. state code "CA" or income tier "LOW"
    value: str
    total_applications: int = 0
    denials: int = 0

    @property
    def denial_rate(self) -> float:
        if self.total_applications == 0:
            return 0.0
        return self.denials / self.total_applications


@dataclass
class ComplaintSummary:
    """Aggregated complaint count by category."""

    category: str
    count: int = 0
    resolved: int = 0
    unresolved: int = 0


@dataclass
class APRVarianceSummary:
    """Summary of APR spread for approved applications."""

    total_approved: int = 0
    median_apr: Optional[float] = None
    mean_apr: Optional[float] = None
    stdev_apr: Optional[float] = None
    pct_above_median_plus_2stdev: float = 0.0  # fraction with APR > median + 2σ


@dataclass
class UDAAPSummaryReport:
    """Top-level UDAAP summary for a single tenant and reporting period."""

    tenant_id: str
    period_start: date
    period_end: date

    # Overall counts
    total_applications: int = 0
    total_approvals: int = 0
    total_denials: int = 0

    # Adverse-action dimension breakdowns
    denial_by_state: Dict[str, AdverseActionStats] = field(default_factory=dict)
    denial_by_income_tier: Dict[str, AdverseActionStats] = field(default_factory=dict)

    # APR analysis
    apr_variance: APRVarianceSummary = field(default_factory=APRVarianceSummary)

    # Complaint summary
    complaints: Dict[str, ComplaintSummary] = field(default_factory=dict)
    total_complaints: int = 0
    unresolved_complaints: int = 0

    # Risk signals
    risk_flags: List[str] = field(default_factory=list)

    @property
    def overall_denial_rate(self) -> float:
        if self.total_applications == 0:
            return 0.0
        return self.total_denials / self.total_applications

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_applications": self.total_applications,
            "total_approvals": self.total_approvals,
            "total_denials": self.total_denials,
            "overall_denial_rate": round(self.overall_denial_rate, 4),
            "denial_by_state": {
                k: {
                    "total": v.total_applications,
                    "denials": v.denials,
                    "denial_rate": round(v.denial_rate, 4),
                }
                for k, v in self.denial_by_state.items()
            },
            "denial_by_income_tier": {
                k: {
                    "total": v.total_applications,
                    "denials": v.denials,
                    "denial_rate": round(v.denial_rate, 4),
                }
                for k, v in self.denial_by_income_tier.items()
            },
            "apr_variance": {
                "total_approved": self.apr_variance.total_approved,
                "median_apr": (
                    round(self.apr_variance.median_apr, 4)
                    if self.apr_variance.median_apr is not None
                    else None
                ),
                "mean_apr": (
                    round(self.apr_variance.mean_apr, 4)
                    if self.apr_variance.mean_apr is not None
                    else None
                ),
                "stdev_apr": (
                    round(self.apr_variance.stdev_apr, 4)
                    if self.apr_variance.stdev_apr is not None
                    else None
                ),
                "pct_above_median_plus_2stdev": round(
                    self.apr_variance.pct_above_median_plus_2stdev, 4
                ),
            },
            "complaints": {
                k: {
                    "count": v.count,
                    "resolved": v.resolved,
                    "unresolved": v.unresolved,
                }
                for k, v in self.complaints.items()
            },
            "total_complaints": self.total_complaints,
            "unresolved_complaints": self.unresolved_complaints,
            "risk_flags": self.risk_flags,
        }


# ---------------------------------------------------------------------------
# Income tier helper (mirrors cra_activity.py to avoid circular import)
# ---------------------------------------------------------------------------

_DEFAULT_AMI = 75_000.0


def _classify_income_tier(annual_income: Optional[float], ami: float) -> str:
    if annual_income is None or ami <= 0:
        return "UNKNOWN"
    ratio = annual_income / ami
    if ratio < 0.50:
        return "LOW"
    elif ratio < 0.80:
        return "MODERATE"
    elif ratio < 1.20:
        return "MIDDLE"
    else:
        return "UPPER"


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Risk flag thresholds (configurable in tests via module attributes)
# ---------------------------------------------------------------------------

DENIAL_RATE_FLAG_THRESHOLD: float = 0.50      # Flag when denial rate > 50 %
APR_OUTLIER_FLAG_THRESHOLD: float = 0.10      # Flag when > 10 % approved above median + 2σ
UNRESOLVED_COMPLAINT_FLAG_THRESHOLD: int = 5  # Flag when ≥ 5 unresolved complaints


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


def generate_udaap_summary(
    audit_records: Sequence[Dict[str, Any]],
    complaint_records: Sequence[Dict[str, Any]],
    tenant_id: str,
    period_start: date,
    period_end: date,
    ami: float = _DEFAULT_AMI,
) -> UDAAPSummaryReport:
    """Build a ``UDAAPSummaryReport`` from audit-log and complaint records.

    ``audit_records`` expected keys (all optional except ``decision_output``):
      - ``decision_output`` : "APPROVE", "DECLINE", "REJECT", ...
      - ``borrower_state``  : 2-char state code
      - ``annual_income``   : float (USD)
      - ``apr``             : float (approved APR as decimal, e.g. 0.12)
      - ``logged_at``       : ISO-8601 date string for period filtering
      - ``tenant_id``       : str

    ``complaint_records`` expected keys:
      - ``category``   : str
      - ``status``     : "RESOLVED" or "UNRESOLVED"
      - ``filed_at``   : ISO-8601 date string
      - ``tenant_id``  : str
    """
    report = UDAAPSummaryReport(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )

    approved_aprs: List[float] = []

    # --------------------------------------------------------
    # Process audit records
    # --------------------------------------------------------
    for rec in audit_records:
        rec_tenant = rec.get("tenant_id", tenant_id)
        if str(rec_tenant) != str(tenant_id):
            continue

        logged_at_raw = rec.get("logged_at") or rec.get("timestamp", "")
        if logged_at_raw:
            try:
                logged_date = date.fromisoformat(str(logged_at_raw)[:10])
                if not (period_start <= logged_date <= period_end):
                    continue
            except (ValueError, TypeError):
                pass

        decision = str(rec.get("decision_output", rec.get("decision", ""))).upper()
        is_approve = decision == "APPROVE"
        is_deny = decision in ("DECLINE", "REJECT", "DENY")

        annual_income = _safe_float(
            rec.get("annual_income")
            or (rec.get("input_features") or {}).get("annual_income")
        )
        state = str(rec.get("borrower_state") or "UNKNOWN").upper()
        income_tier = _classify_income_tier(annual_income, ami)
        apr = _safe_float(rec.get("apr"))

        # Totals
        report.total_applications += 1
        if is_approve:
            report.total_approvals += 1
            if apr is not None:
                approved_aprs.append(apr)
        elif is_deny:
            report.total_denials += 1

        # Denial by state
        if state not in report.denial_by_state:
            report.denial_by_state[state] = AdverseActionStats(dimension="state", value=state)
        s = report.denial_by_state[state]
        s.total_applications += 1
        if is_deny:
            s.denials += 1

        # Denial by income tier
        if income_tier not in report.denial_by_income_tier:
            report.denial_by_income_tier[income_tier] = AdverseActionStats(
                dimension="income_tier", value=income_tier
            )
        t = report.denial_by_income_tier[income_tier]
        t.total_applications += 1
        if is_deny:
            t.denials += 1

    # --------------------------------------------------------
    # APR variance analysis
    # --------------------------------------------------------
    if approved_aprs:
        med = statistics.median(approved_aprs)
        mean_ = statistics.mean(approved_aprs)
        stdev_ = statistics.pstdev(approved_aprs)  # population stdev for full-period analysis
        threshold = med + 2 * stdev_
        outliers = sum(1 for a in approved_aprs if a > threshold)
        pct_outlier = outliers / len(approved_aprs)

        report.apr_variance = APRVarianceSummary(
            total_approved=len(approved_aprs),
            median_apr=med,
            mean_apr=mean_,
            stdev_apr=stdev_,
            pct_above_median_plus_2stdev=pct_outlier,
        )

    # --------------------------------------------------------
    # Process complaint records
    # --------------------------------------------------------
    for comp in complaint_records:
        comp_tenant = comp.get("tenant_id", tenant_id)
        if str(comp_tenant) != str(tenant_id):
            continue

        filed_at_raw = comp.get("filed_at") or comp.get("logged_at", "")
        if filed_at_raw:
            try:
                filed_date = date.fromisoformat(str(filed_at_raw)[:10])
                if not (period_start <= filed_date <= period_end):
                    continue
            except (ValueError, TypeError):
                pass

        category = str(comp.get("category", "GENERAL")).upper()
        status = str(comp.get("status", "UNRESOLVED")).upper()
        is_resolved = status in ("RESOLVED", "CLOSED")

        if category not in report.complaints:
            report.complaints[category] = ComplaintSummary(category=category)
        c = report.complaints[category]
        c.count += 1
        if is_resolved:
            c.resolved += 1
        else:
            c.unresolved += 1
            report.unresolved_complaints += 1

        report.total_complaints += 1

    # --------------------------------------------------------
    # Risk flags
    # --------------------------------------------------------
    if report.overall_denial_rate > DENIAL_RATE_FLAG_THRESHOLD:
        report.risk_flags.append(
            f"HIGH_OVERALL_DENIAL_RATE: {report.overall_denial_rate:.1%}"
        )

    for state, stats in report.denial_by_state.items():
        if stats.total_applications >= 5 and stats.denial_rate > DENIAL_RATE_FLAG_THRESHOLD:
            report.risk_flags.append(
                f"HIGH_STATE_DENIAL_RATE:{state}:{stats.denial_rate:.1%}"
            )

    for tier, stats in report.denial_by_income_tier.items():
        if tier in ("LOW", "MODERATE") and stats.total_applications >= 5 and stats.denial_rate > DENIAL_RATE_FLAG_THRESHOLD:
            report.risk_flags.append(
                f"HIGH_DENIAL_RATE_PROTECTED_TIER:{tier}:{stats.denial_rate:.1%}"
            )

    if report.apr_variance.pct_above_median_plus_2stdev > APR_OUTLIER_FLAG_THRESHOLD:
        report.risk_flags.append(
            f"APR_OUTLIER_CONCENTRATION:{report.apr_variance.pct_above_median_plus_2stdev:.1%}"
        )

    if report.unresolved_complaints >= UNRESOLVED_COMPLAINT_FLAG_THRESHOLD:
        report.risk_flags.append(
            f"ELEVATED_UNRESOLVED_COMPLAINTS:{report.unresolved_complaints}"
        )

    return report


def from_audit_log_records(
    audit_records: Sequence[Dict[str, Any]],
    complaint_records: Sequence[Dict[str, Any]],
    tenant_id: str,
    period_start: date,
    period_end: date,
    ami: float = _DEFAULT_AMI,
) -> UDAAPSummaryReport:
    """Alias for ``generate_udaap_summary`` — preferred public entry point."""
    return generate_udaap_summary(
        audit_records, complaint_records, tenant_id, period_start, period_end, ami
    )
