#!/usr/bin/env python3
"""
check_audit_completeness.py — Section 23.12
============================================
Quality gate: verifies that 0 credit decisions in the last 24 hours are
missing a corresponding audit.audit_log entry.

Every evaluate_application() call in cc_origination_policy MUST produce
exactly one audit row.  Any gap is a compliance defect.

Exits 0 if gap_count == 0, 1 otherwise.
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    try:
        from google.cloud import bigquery
    except ImportError:
        logger.error("google-cloud-bigquery not installed.")
        return 2

    bq = bigquery.Client()

    # Count decisions that have no corresponding audit_log row.
    # The decision_events table is written by the decision engine
    # BEFORE evaluate_application() returns; audit_log is written
    # by audit.logger AFTER the response is assembled.
    try:
        rows = list(
            bq.query(
                """
                SELECT COUNT(*) AS gap_count
                FROM audit.decision_events de
                LEFT JOIN audit.audit_log al
                  ON de.decision_id = al.decision_id
                WHERE al.decision_id IS NULL
                  AND de.created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
                """
            ).result()
        )
        gap_count: int = int(rows[0].gap_count)
    except Exception as exc:
        logger.error("BQ query failed: %s", exc)
        return 2

    if gap_count > 0:
        logger.error(
            "AUDIT COMPLETENESS FAILURE: %d decision(s) in last 24 hours "
            "have no audit_log entry.",
            gap_count,
        )
        return 1

    logger.info("Audit completeness check passed — 0 gaps in last 24 hours.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
