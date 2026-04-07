#!/usr/bin/env python3
"""
check_compliance_schema.py — Section 23.5 / 23.12
===================================================
CI gate: validates that all required compliance_data_plane BQ tables exist
and have the expected columns with the correct types.

Tables validated:
  - compliance_data_plane.regulatory_thresholds
  - compliance_data_plane.compliance_events
  - compliance_data_plane.regulatory_horizon
  - compliance_data_plane.consent_and_disclosures

Exits 0 if schema is valid, 1 if any table/column is missing or mistyped.
"""
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Expected schema: { table: { column: expected_bq_type_prefix } }
EXPECTED_SCHEMA: dict[str, dict[str, str]] = {
    "compliance_data_plane.regulatory_thresholds": {
        "threshold_id": "STRING",
        "regulation": "STRING",
        "jurisdiction": "STRING",
        "threshold_type": "STRING",
        "threshold_value": "FLOAT",
        "effective_date": "DATE",
        "legal_citation": "STRING",
        "legal_sign_off_by": "STRING",
        "legal_sign_off_date": "DATE",
        "last_reviewed_date": "DATE",
        "review_cycle_days": "INTEGER",
        "created_at": "TIMESTAMP",
    },
    "compliance_data_plane.compliance_events": {
        "event_id": "STRING",
        "event_type": "STRING",
        "source_system": "STRING",
        "check_name": "STRING",
        "check_result": "STRING",
        "run_by": "STRING",
        "run_at": "TIMESTAMP",
    },
    "compliance_data_plane.regulatory_horizon": {
        "horizon_id": "STRING",
        "regulation": "STRING",
        "jurisdiction": "STRING",
        "change_summary": "STRING",
        "effective_date": "DATE",
        "days_until_effective": "INTEGER",
        "severity": "STRING",
        "owner_email": "STRING",
        "tracking_status": "STRING",
        "created_at": "TIMESTAMP",
    },
    "compliance_data_plane.consent_and_disclosures": {
        "disclosure_id": "STRING",
        "applicant_id_hash": "STRING",
        "disclosure_type": "STRING",
        "product_id": "STRING",
        "disclosure_version": "STRING",
        "disclosure_hash": "STRING",
        "disclosed_at": "TIMESTAMP",
        "channel": "STRING",
    },
}


def main() -> int:
    try:
        from google.cloud import bigquery
    except ImportError:
        logger.error("google-cloud-bigquery not installed.")
        return 2

    bq = bigquery.Client()
    failures: list[str] = []

    for full_table, expected_cols in EXPECTED_SCHEMA.items():
        dataset_id, table_id = full_table.split(".")
        try:
            table = bq.get_table(f"{bq.project}.{dataset_id}.{table_id}")
        except Exception as exc:
            failures.append(f"Table '{full_table}' not found: {exc}")
            continue

        actual_cols = {field.name: field.field_type for field in table.schema}
        for col, expected_type in expected_cols.items():
            if col not in actual_cols:
                failures.append(f"{full_table}.{col} — column missing")
            elif not actual_cols[col].startswith(expected_type):
                failures.append(
                    f"{full_table}.{col} — expected {expected_type}, "
                    f"got {actual_cols[col]}"
                )

    if failures:
        logger.error("COMPLIANCE SCHEMA FAILURES (%d):", len(failures))
        for f in failures:
            logger.error("  %s", f)
        return 1

    logger.info("All compliance data plane tables present and schema-valid — OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
