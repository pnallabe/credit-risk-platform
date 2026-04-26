"""
Smoke tests for compliance/retention_policy.py

With no BigQuery available, all functions return safe no-ops.
"""
from __future__ import annotations

from compliance.retention_policy import (
    GCS_ARCHIVE_BUCKET,
    RETENTION_EXEMPT_TABLES,
    RetentionReport,
    enforce_retention_schedule,
)


def test_enforce_retention_no_bq_returns_list():
    """With no BigQuery, enforce_retention_schedule() must return a list (possibly empty)."""
    result = enforce_retention_schedule()
    assert isinstance(result, list)


def test_retention_exempt_tables_non_empty():
    assert len(RETENTION_EXEMPT_TABLES) > 0
    assert "audit.policy_version_log" in RETENTION_EXEMPT_TABLES
    assert "audit.governance_approval_log" in RETENTION_EXEMPT_TABLES


def test_gcs_archive_bucket_configured():
    assert isinstance(GCS_ARCHIVE_BUCKET, str)
    assert len(GCS_ARCHIVE_BUCKET) > 0


def test_retention_report_dataclass():
    report = RetentionReport(
        table="audit.audit_log",
        rows_archived=100,
        rows_deleted=50,
        cutoff_date="2024-01-01",
        status="OK",
    )
    assert report.table == "audit.audit_log"
    assert report.rows_archived == 100
    assert report.status == "OK"
