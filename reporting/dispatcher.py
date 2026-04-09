"""Regulatory Reporting Dispatcher.

Orchestrates the generation of all regulatory reports for a given tenant and
reporting period by:

1. Fetching audit records from the audit log via
   ``audit.logger.get_audit_records_by_period()``.
2. Generating each report in parallel (using ``asyncio.gather``).
3. Returning a ``DispatchResult`` containing all generated reports.

Supported report types (controlled by the *reports* argument):
  "cra"      → CRAActivityReport     (reporting.cra_activity)
  "udaap"    → UDAAPSummaryReport    (reporting.udaap_summary)
  "metro2"   → List[Metro2Record]    (reporting.fcra_metro2)

Usage example::

    from datetime import date
    from reporting.dispatcher import dispatch_reports

    result = await dispatch_reports(
        tenant_id="tenant-a",
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        db_url="sqlite+aiosqlite:///./decision_audit.db",
    )
    print(result.cra_report.total_applications)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Literal, Optional, Sequence

from audit.logger import get_audit_records_by_period
from reporting.cra_activity import CRAActivityReport, generate_cra_activity_report
from reporting.fcra_metro2 import Metro2Record, from_audit_log_record
from reporting.udaap_summary import UDAAPSummaryReport, generate_udaap_summary

logger = logging.getLogger(__name__)

ReportType = Literal["cra", "udaap", "metro2"]
_ALL_REPORT_TYPES: List[ReportType] = ["cra", "udaap", "metro2"]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DispatchResult:
    """Container for all reports generated in a single dispatch run."""

    tenant_id: str
    period_start: date
    period_end: date
    total_audit_records_fetched: int = 0

    cra_report: Optional[CRAActivityReport] = None
    udaap_report: Optional[UDAAPSummaryReport] = None
    metro2_records: List[Metro2Record] = field(default_factory=list)

    errors: Dict[str, str] = field(default_factory=dict)

    @property
    def reports_generated(self) -> List[str]:
        generated = []
        if self.cra_report is not None:
            generated.append("cra")
        if self.udaap_report is not None:
            generated.append("udaap")
        if self.metro2_records:
            generated.append("metro2")
        return generated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "total_audit_records_fetched": self.total_audit_records_fetched,
            "reports_generated": self.reports_generated,
            "cra_report": self.cra_report.to_dict() if self.cra_report else None,
            "udaap_report": self.udaap_report.to_dict() if self.udaap_report else None,
            "metro2_record_count": len(self.metro2_records),
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def dispatch_reports(
    tenant_id: str,
    period_start: date,
    period_end: date,
    db_url: str,
    reports: Optional[Sequence[ReportType]] = None,
    ami: float = 75_000.0,
    metro2_subscriber_id: str = "UNKNOWN",
    complaint_records: Optional[Sequence[Dict[str, Any]]] = None,
    max_audit_records: int = 50_000,
) -> DispatchResult:
    """Fetch audit records and generate the requested regulatory reports.

    Parameters
    ----------
    tenant_id:
        Tenant to generate reports for.
    period_start / period_end:
        Inclusive date range.
    db_url:
        Async SQLAlchemy URL for the audit-log database.
    reports:
        Subset of ``["cra", "udaap", "metro2"]`` to generate.
        Defaults to all three.
    ami:
        Area Median Income used by CRA and UDAAP income-tier classification.
    metro2_subscriber_id:
        CRA Data furnisher subscriber ID stamped on Metro 2 records.
    complaint_records:
        Optional pre-fetched complaint records for UDAAP analysis.
        When None an empty list is used.
    max_audit_records:
        Safety cap passed to ``get_audit_records_by_period``.
    """
    requested: List[ReportType] = list(reports) if reports else _ALL_REPORT_TYPES
    result = DispatchResult(
        tenant_id=tenant_id,
        period_start=period_start,
        period_end=period_end,
    )

    # ------------------------------------------------------------------
    # 1. Fetch audit records
    # ------------------------------------------------------------------
    try:
        audit_records = await get_audit_records_by_period(
            tenant_id=tenant_id,
            period_start=period_start,
            period_end=period_end,
            db_url=db_url,
            max_records=max_audit_records,
        )
    except Exception as exc:
        logger.error("Failed to fetch audit records for tenant=%s: %s", tenant_id, exc)
        result.errors["audit_fetch"] = str(exc)
        audit_records = []

    result.total_audit_records_fetched = len(audit_records)
    logger.info(
        "Fetched %d audit records for tenant=%s period=%s→%s",
        len(audit_records),
        tenant_id,
        period_start,
        period_end,
    )

    # ------------------------------------------------------------------
    # 2. Generate each report in parallel
    # ------------------------------------------------------------------
    comp_records = list(complaint_records) if complaint_records else []

    async def _gen_cra() -> None:
        try:
            result.cra_report = generate_cra_activity_report(
                audit_records, tenant_id, period_start, period_end, ami
            )
            logger.info("CRA report generated for tenant=%s", tenant_id)
        except Exception as exc:
            logger.error("CRA report generation failed for tenant=%s: %s", tenant_id, exc)
            result.errors["cra"] = str(exc)

    async def _gen_udaap() -> None:
        try:
            result.udaap_report = generate_udaap_summary(
                audit_records, comp_records, tenant_id, period_start, period_end, ami
            )
            logger.info("UDAAP report generated for tenant=%s", tenant_id)
        except Exception as exc:
            logger.error("UDAAP report generation failed for tenant=%s: %s", tenant_id, exc)
            result.errors["udaap"] = str(exc)

    async def _gen_metro2() -> None:
        try:
            result.metro2_records = [
                from_audit_log_record(rec, subscriber_id=metro2_subscriber_id)
                for rec in audit_records
            ]
            logger.info(
                "Metro 2 records built: %d for tenant=%s",
                len(result.metro2_records),
                tenant_id,
            )
        except Exception as exc:
            logger.error("Metro 2 generation failed for tenant=%s: %s", tenant_id, exc)
            result.errors["metro2"] = str(exc)

    tasks = []
    if "cra" in requested:
        tasks.append(_gen_cra())
    if "udaap" in requested:
        tasks.append(_gen_udaap())
    if "metro2" in requested:
        tasks.append(_gen_metro2())

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=False)

    return result
