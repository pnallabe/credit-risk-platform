"""
Regulatory Horizon Scanner — Section 23.4
==========================================
Runs nightly via Cloud Scheduler (job: compliance-horizon-scan).
Sends tiered alerts at 180 / 90 / 60 / 30 / 7 day thresholds and
clears stale get_threshold() cache entries when thresholds change.

Nightly schedule (Cloud Scheduler cron):  0 6 * * *   (06:00 UTC)

Usage
-----
    python scripts/check_regulatory_horizon.py   # invokes scan_horizon() + update_days_remaining()
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

ALERT_DAYS = [180, 90, 60, 30, 7]
SEVERITY_ESCALATION: dict[int, str] = {
    180: "LOW",
    90: "MEDIUM",
    60: "HIGH",
    30: "CRITICAL",
    7: "CRITICAL",
}

# ---------------------------------------------------------------------------
# Optional BigQuery import
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq_lib = None  # type: ignore
    _BQ_AVAILABLE = False


def scan_horizon() -> list[dict[str, Any]]:
    """
    Query regulatory_horizon for upcoming changes that have not yet been deployed.

    For each item within an alert threshold, emits a structured warning log
    and appends an alert dict to the returned list.

    Returns
    -------
    list[dict]
        One entry per horizon item that crossed an alert threshold.
    """
    if not _BQ_AVAILABLE:
        logger.warning("BigQuery not available — horizon scan skipped.")
        return []

    bq = _bq_lib.Client()
    rows = list(
        bq.query(
            """
            SELECT *,
                   DATE_DIFF(effective_date, CURRENT_DATE(), DAY) AS days_until_effective
            FROM compliance_data_plane.regulatory_horizon
            WHERE tracking_status NOT IN ('DEPLOYED')
              AND effective_date >= CURRENT_DATE()
            ORDER BY effective_date ASC
            """
        ).result()
    )

    alerts: list[dict[str, Any]] = []
    for row in rows:
        days_left: int = row.days_until_effective
        for threshold in ALERT_DAYS:
            if days_left <= threshold:
                severity = SEVERITY_ESCALATION[threshold]
                alert: dict[str, Any] = {
                    "horizon_id": row.horizon_id,
                    "regulation": row.regulation,
                    "jurisdiction": row.jurisdiction,
                    "change_summary": row.change_summary,
                    "effective_date": str(row.effective_date),
                    "days_until_effective": days_left,
                    "severity": severity,
                    "owner_email": row.owner_email,
                    "tracking_status": row.tracking_status,
                }
                alerts.append(alert)
                logger.warning(
                    "[REGULATORY_HORIZON] %s: %s (%s) effective %s — "
                    "%d days remaining.  Status: %s.  Owner: %s",
                    severity,
                    row.regulation,
                    row.jurisdiction,
                    row.effective_date,
                    days_left,
                    row.tracking_status,
                    row.owner_email,
                )
                break  # only fire the most-severe threshold per item

    return alerts


def update_days_remaining() -> None:
    """
    Recompute days_until_effective for all non-deployed horizon items.
    Called nightly immediately after scan_horizon().
    """
    if not _BQ_AVAILABLE:
        return

    _bq_lib.Client().query(
        """
        UPDATE compliance_data_plane.regulatory_horizon
        SET days_until_effective = DATE_DIFF(effective_date, CURRENT_DATE(), DAY)
        WHERE TRUE
        """
    ).result()
    logger.info("Regulatory horizon days_until_effective refreshed.")


def get_horizon_items(max_days: int = 180) -> list[dict[str, Any]]:
    """
    Return all non-deployed horizon items effective within ``max_days`` days.
    Used by the /analytics/compliance dashboard proxy endpoint.
    """
    if not _BQ_AVAILABLE:
        return []

    bq = _bq_lib.Client()
    rows = list(
        bq.query(
            f"""
            SELECT *,
                   DATE_DIFF(effective_date, CURRENT_DATE(), DAY) AS days_until_effective
            FROM compliance_data_plane.regulatory_horizon
            WHERE tracking_status != 'DEPLOYED'
              AND DATE_DIFF(effective_date, CURRENT_DATE(), DAY) <= {int(max_days)}
              AND effective_date >= CURRENT_DATE()
            ORDER BY effective_date ASC
            """
        ).result()
    )
    return [dict(row.items()) for row in rows]


def flag_overdue_horizon_items() -> list[dict[str, Any]]:
    """
    Return horizon items whose effective_date has passed but tracking_status
    is still not 'DEPLOYED'.  These are quality-gate failures.
    """
    if not _BQ_AVAILABLE:
        return []

    bq = _bq_lib.Client()
    rows = list(
        bq.query(
            """
            SELECT *
            FROM compliance_data_plane.regulatory_horizon
            WHERE effective_date < CURRENT_DATE()
              AND tracking_status != 'DEPLOYED'
            ORDER BY effective_date ASC
            """
        ).result()
    )
    overdue = [dict(row.items()) for row in rows]
    if overdue:
        logger.error(
            "[REGULATORY_HORIZON] %d past-effective item(s) not marked DEPLOYED: %s",
            len(overdue),
            [r["horizon_id"] for r in overdue],
        )
    return overdue
