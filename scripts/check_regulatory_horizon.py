#!/usr/bin/env python3
"""
check_regulatory_horizon.py — Section 23.4 / 23.12
====================================================
Nightly Cloud Scheduler job: 0 6 * * * (06:00 UTC)

1. Updates days_until_effective for all non-deployed horizon items.
2. Scans for items crossing 180/90/60/30/7 day thresholds and emits
   structured WARNING logs (picked up by Cloud Logging alert policies).
3. Flags any past-effective items that are not yet DEPLOYED — these are
   quality-gate failures that must be escalated to the CRO immediately.

Quality gate (Section 23.12):
  [ ] CRITICAL items (<=30 days) trigger PagerDuty alert to owner + CRO.
  [ ] No horizon items with past effective_date have tracking_status != "DEPLOYED".

Exit codes:
  0 — all items within acceptable thresholds
  1 — at least one past-effective item is not DEPLOYED (CI/pipeline blocker)
  2 — BigQuery unavailable
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        from compliance.regulatory_horizon import (
            update_days_remaining,
            scan_horizon,
            flag_overdue_horizon_items,
        )
    except ImportError as exc:
        logger.error("Cannot import compliance package: %s", exc)
        return 2

    logger.info("Updating days_until_effective ...")
    try:
        update_days_remaining()
    except Exception as exc:
        logger.error("update_days_remaining failed: %s", exc)
        return 2

    logger.info("Scanning regulatory horizon ...")
    alerts = scan_horizon()
    if alerts:
        logger.warning("Horizon alerts raised: %d", len(alerts))
        for a in alerts:
            logger.warning(
                "[ALERT] %s | %s (%s) | effective=%s | days_left=%d | status=%s",
                a["severity"],
                a["regulation"],
                a["jurisdiction"],
                a["effective_date"],
                a["days_until_effective"],
                a["tracking_status"],
            )
    else:
        logger.info("No new horizon alerts.")

    logger.info("Checking for overdue (past-effective) items ...")
    overdue = flag_overdue_horizon_items()
    if overdue:
        logger.error(
            "COMPLIANCE GATE FAILURE: %d past-effective horizon items "
            "not yet DEPLOYED: %s",
            len(overdue),
            [r["horizon_id"] for r in overdue],
        )
        return 1

    logger.info("Regulatory horizon check complete — no quality-gate failures.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
