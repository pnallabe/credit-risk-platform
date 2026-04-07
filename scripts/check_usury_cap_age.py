#!/usr/bin/env python3
"""
check_usury_cap_age.py — Section 23.5 / 23.12
===============================================
CI gate: validates that every active usury cap threshold in
compliance_data_plane.regulatory_thresholds has a legal_sign_off_date
no older than --max-age-days (default 365 days).

Exits non-zero if any threshold exceeds the maximum sign-off age so that
the CI pipeline blocks the merge.

Quality gate (Section 23.12):
  [ ] Every active threshold has legal_sign_off_date no older than 12 months.
"""
import argparse
import logging
import sys
from datetime import date, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 365


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--max-age-days",
        type=int,
        default=DEFAULT_MAX_AGE_DAYS,
        help=f"Maximum allowed sign-off age in days (default {DEFAULT_MAX_AGE_DAYS})",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cutoff = date.today() - timedelta(days=args.max_age_days)

    try:
        from google.cloud import bigquery
    except ImportError:
        logger.error("google-cloud-bigquery not installed.")
        return 2

    bq = bigquery.Client()
    rows = list(
        bq.query(
            """
            SELECT threshold_id, jurisdiction, legal_sign_off_by, legal_sign_off_date,
                   DATE_DIFF(CURRENT_DATE(), legal_sign_off_date, DAY) AS age_days
            FROM compliance_data_plane.regulatory_thresholds
            WHERE effective_date <= CURRENT_DATE()
              AND (sunset_date IS NULL OR sunset_date > CURRENT_DATE())
            ORDER BY legal_sign_off_date ASC
            """
        ).result()
    )

    stale = [r for r in rows if r.age_days > args.max_age_days]

    if stale:
        logger.error(
            "USURY CAP SIGN-OFF AGE FAILURE: %d threshold(s) have sign-off "
            "older than %d days (cutoff: %s):",
            len(stale),
            args.max_age_days,
            cutoff,
        )
        for r in stale:
            logger.error(
                "  %s / %s — signed by %s on %s (%d days ago)",
                r.threshold_id,
                r.jurisdiction,
                r.legal_sign_off_by,
                r.legal_sign_off_date,
                r.age_days,
            )
        logger.error(
            "Action required: obtain fresh legal sign-off and update "
            "compliance_data_plane.regulatory_thresholds before merging."
        )
        return 1

    logger.info(
        "All %d active threshold sign-offs are within %d days — OK",
        len(rows),
        args.max_age_days,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
