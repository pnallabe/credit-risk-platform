"""
Data Retention Policy Enforcer — Section 23.7
==============================================
Enforces the regulatory data retention schedule by:
 1. Archiving data to GCS cold storage before deletion.
 2. Deleting BigQuery partitions that have exceeded their platform retention
    period.

Retention schedule (from Section 23.7)
---------------------------------------
Table                                        Min (regulation)  Platform  Action
audit.audit_log                              25 months         7 years   Archive -> delete
audit.adverse_action_notice_queue            25 months         7 years   Archive -> delete
compliance_data_plane.compliance_events      5 years           7 years   Archive -> delete
compliance_data_plane.consent_and_disclosures 2 years          7 years   Archive -> delete
audit.policy_version_log                     Permanent         Permanent NEVER DELETE
audit.governance_approval_log                Permanent         Permanent NEVER DELETE
audit.portfolio_audit_log                    25 months         7 years   Archive -> delete
feature_store.*                              5 years           5 years   BQ partition expiry
mlflow artefacts                             5 years post-sunset 7 years GCS lifecycle rule

Notes
-----
- Tables in RETENTION_EXEMPT_TABLES are NEVER deleted regardless of age.
- Archive files land in gs://credit-risk-platform-archive/<table>/<YYYY>/<MM>/
- Deletion uses BQ partition-range DELETE via DML to preserve streaming buffer
  compatibility.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BigQuery optional import
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq_lib = None  # type: ignore
    _BQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GCS_ARCHIVE_BUCKET = "credit-risk-platform-archive"

RETENTION_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        "audit.policy_version_log",
        "audit.governance_approval_log",
        "audit.model_validation_log",
        "audit.policy_approval_log",
        "compliance_data_plane.regulatory_thresholds",
    }
)

# platform_retention_years -> years to keep; None = permanent
RETENTION_SCHEDULE: dict[str, Optional[int]] = {
    "audit.audit_log": 7,
    "audit.adverse_action_notice_queue": 7,
    "audit.portfolio_audit_log": 7,
    "audit.access_event_log": 7,
    "compliance_data_plane.compliance_events": 7,
    "compliance_data_plane.consent_and_disclosures": 7,
    "compliance_data_plane.compliance_health_score_log": 7,
    "audit.policy_version_log": None,      # Permanent — will not be processed
    "audit.governance_approval_log": None,  # Permanent — will not be processed
}


@dataclass
class RetentionReport:
    table: str
    rows_archived: int
    rows_deleted: int
    cutoff_date: str
    status: str  # "OK" | "SKIPPED" | "ERROR"
    error: Optional[str] = None


def enforce_retention_schedule() -> list[RetentionReport]:
    """
    Iterate over RETENTION_SCHEDULE and delete rows older than the platform
    retention period, after archiving them to GCS.

    Returns a list of RetentionReport objects for audit logging.
    """
    if not _BQ_AVAILABLE:
        logger.warning("BigQuery unavailable — retention enforcement skipped.")
        return []

    reports: list[RetentionReport] = []
    for table, retention_years in RETENTION_SCHEDULE.items():
        if table in RETENTION_EXEMPT_TABLES or retention_years is None:
            reports.append(
                RetentionReport(
                    table=table,
                    rows_archived=0,
                    rows_deleted=0,
                    cutoff_date="",
                    status="SKIPPED",
                )
            )
            continue
        report = _process_table(table, retention_years)
        reports.append(report)
    return reports


def _process_table(table: str, retention_years: int) -> RetentionReport:
    cutoff = datetime.utcnow() - timedelta(days=retention_years * 365)
    cutoff_str = cutoff.strftime("%Y-%m-%d")
    bq = _bq_lib.Client()

    try:
        archive_count = _archive_to_gcs(bq, table, cutoff_str)
        delete_count = _delete_old_rows(bq, table, cutoff_str)
        logger.info(
            "[RETENTION] %s: archived=%d deleted=%d cutoff=%s",
            table,
            archive_count,
            delete_count,
            cutoff_str,
        )
        return RetentionReport(
            table=table,
            rows_archived=archive_count,
            rows_deleted=delete_count,
            cutoff_date=cutoff_str,
            status="OK",
        )
    except Exception as exc:  # pragma: no cover
        logger.error("[RETENTION] Error processing %s: %s", table, exc)
        return RetentionReport(
            table=table,
            rows_archived=0,
            rows_deleted=0,
            cutoff_date=cutoff_str,
            status="ERROR",
            error=str(exc),
        )


def _archive_to_gcs(
    bq: "bigquery.Client",  # type: ignore[name-defined]
    table: str,
    cutoff_str: str,
) -> int:
    """Export rows older than cutoff to GCS Coldline via BQ extract."""
    uri_prefix = (
        f"gs://{GCS_ARCHIVE_BUCKET}/{table.replace('.', '/')}/"
        f"{cutoff_str[:7]}/"  # YYYY-MM prefix
        "*.json.gz"
    )
    dataset, tbl = table.split(".")
    extract_job = bq.extract_table(
        f"{dataset}.{tbl}",
        uri_prefix,
        job_config=_bq_lib.ExtractJobConfig(
            destination_format=_bq_lib.DestinationFormat.NEWLINE_DELIMITED_JSON,
            compression=_bq_lib.Compression.GZIP,
        ),
    )
    extract_job.result()
    # Return approximate row count from job stats
    return getattr(extract_job, "output_rows", 0) or 0


def _delete_old_rows(
    bq: "bigquery.Client",  # type: ignore[name-defined]
    table: str,
    cutoff_str: str,
) -> int:
    """Delete rows older than cutoff_str using partition-range DML."""
    # Determine timestamp column (most tables use created_at / run_at)
    ts_col = "created_at"
    if table == "compliance_data_plane.compliance_events":
        ts_col = "run_at"
    elif table == "audit.adverse_action_notice_queue":
        ts_col = "enqueued_at"

    job = bq.query(
        f"DELETE FROM `{table}` WHERE DATE({ts_col}) < '{cutoff_str}'"
    )
    result = job.result()
    return getattr(result, "num_dml_affected_rows", 0) or 0
