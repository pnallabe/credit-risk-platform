"""Acceptance tests for G5-D: dispatcher + audit bulk fetch.

Covers:
1. audit.logger.get_audit_records_by_period returns records within the window
2. audit.logger.get_audit_records_by_period filters by tenant_id
3. audit.logger.get_audit_records_by_period raises ValueError for empty tenant_id
4. dispatch_reports generates CRA, UDAAP, and Metro2 reports
5. dispatch_reports returns only requested report types
6. dispatch_reports handles audit fetch failure gracefully
7. reporting.__init__ exports all public names
8. DispatchResult.to_dict() has all required keys
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT = "tenant-a"
PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)

DB_URL = "sqlite+aiosqlite:///:memory:"


def _audit_rec(
    tenant_id: str = TENANT,
    decision: str = "APPROVE",
    logged_at: str = "2025-06-15T10:00:00+00:00",
    annual_income: float = 60_000.0,
    apr: float = 0.12,
    loan_amount: float = 10_000.0,
    application_id: str | None = None,
) -> Dict[str, Any]:
    return {
        "application_id": application_id or str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "decision_output": decision,
        "logged_at": logged_at,
        "annual_income": annual_income,
        "apr": apr if decision == "APPROVE" else None,
        "loan_amount": loan_amount,
        "borrower_state": "CA",
        "input_features": {"annual_income": annual_income},
        "reason_codes": [],
    }


# ---------------------------------------------------------------------------
# Fixture: in-memory SQLite audit-log database (async)
# ---------------------------------------------------------------------------

@pytest.fixture()
async def populated_db():
    """Create an in-memory SQLite DB with a few audit_log rows."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text

    # Use a named in-memory URL with StaticPool so all connections share state
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit_log (
                log_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                application_id TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                decision_output TEXT,
                input_features TEXT,
                reason_codes TEXT,
                model_version TEXT
            )
        """))

        rows = [
            {"log_id": "log-1", "tenant_id": "tenant-a", "application_id": "app-1", "logged_at": "2025-06-15T10:00:00", "decision_output": "APPROVE", "input_features": '{"annual_income": 60000}', "reason_codes": '[]', "model_version": '"v1"'},
            {"log_id": "log-2", "tenant_id": "tenant-a", "application_id": "app-2", "logged_at": "2025-07-01T10:00:00", "decision_output": "DECLINE", "input_features": '{"annual_income": 20000}', "reason_codes": '[]', "model_version": '"v1"'},
            {"log_id": "log-3", "tenant_id": "tenant-b", "application_id": "app-3", "logged_at": "2025-06-20T10:00:00", "decision_output": "APPROVE", "input_features": '{"annual_income": 80000}', "reason_codes": '[]', "model_version": '"v1"'},
            # Outside period
            {"log_id": "log-4", "tenant_id": "tenant-a", "application_id": "app-4", "logged_at": "2024-12-31T10:00:00", "decision_output": "APPROVE", "input_features": '{}', "reason_codes": '[]', "model_version": '"v1"'},
        ]
        for row in rows:
            await conn.execute(
                text("INSERT INTO audit_log VALUES (:log_id, :tenant_id, :application_id, :logged_at, :decision_output, :input_features, :reason_codes, :model_version)"),
                row,
            )

    return engine


# ---------------------------------------------------------------------------
# Test 1: get_audit_records_by_period returns records within window
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_fetch_within_period(populated_db):
    from audit.logger import get_audit_records_by_period

    with patch("audit.logger._get_engine", return_value=populated_db):
        records = await get_audit_records_by_period(
            tenant_id="tenant-a",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )

    assert len(records) == 2  # log-1 and log-2 match tenant-a in 2025
    app_ids = {r["application_id"] for r in records}
    assert "app-1" in app_ids
    assert "app-2" in app_ids


# ---------------------------------------------------------------------------
# Test 2: get_audit_records_by_period filters by tenant_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_fetch_tenant_isolation(populated_db):
    from audit.logger import get_audit_records_by_period

    with patch("audit.logger._get_engine", return_value=populated_db):
        records_b = await get_audit_records_by_period(
            tenant_id="tenant-b",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )

    assert len(records_b) == 1
    assert records_b[0]["tenant_id"] == "tenant-b"


# ---------------------------------------------------------------------------
# Test 3: get_audit_records_by_period raises ValueError for empty tenant_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bulk_fetch_empty_tenant_raises():
    from audit.logger import get_audit_records_by_period

    with pytest.raises(ValueError, match="tenant_id is required"):
        await get_audit_records_by_period(
            tenant_id="",
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )


# ---------------------------------------------------------------------------
# Test 4: dispatch_reports generates CRA, UDAAP, Metro2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_all_reports():
    from reporting.dispatcher import dispatch_reports

    fake_records = [_audit_rec() for _ in range(3)]

    with patch(
        "reporting.dispatcher.get_audit_records_by_period",
        new=AsyncMock(return_value=fake_records),
    ):
        result = await dispatch_reports(
            tenant_id=TENANT,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )

    assert result.total_audit_records_fetched == 3
    assert result.cra_report is not None
    assert result.udaap_report is not None
    assert len(result.metro2_records) == 3
    assert "cra" in result.reports_generated
    assert "udaap" in result.reports_generated
    assert "metro2" in result.reports_generated


# ---------------------------------------------------------------------------
# Test 5: dispatch_reports respects requested subset
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_subset_of_reports():
    from reporting.dispatcher import dispatch_reports

    fake_records = [_audit_rec()]

    with patch(
        "reporting.dispatcher.get_audit_records_by_period",
        new=AsyncMock(return_value=fake_records),
    ):
        result = await dispatch_reports(
            tenant_id=TENANT,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
            reports=["cra"],
        )

    assert result.cra_report is not None
    assert result.udaap_report is None
    assert result.metro2_records == []


# ---------------------------------------------------------------------------
# Test 6: dispatch_reports handles audit fetch failure gracefully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_handles_fetch_failure():
    from reporting.dispatcher import dispatch_reports

    with patch(
        "reporting.dispatcher.get_audit_records_by_period",
        new=AsyncMock(side_effect=RuntimeError("DB connection failed")),
    ):
        result = await dispatch_reports(
            tenant_id=TENANT,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )

    assert "audit_fetch" in result.errors
    assert result.total_audit_records_fetched == 0
    # Reports should still be generated (empty) without raising
    assert result.cra_report is not None  # generated from empty list
    assert result.cra_report.total_applications == 0


# ---------------------------------------------------------------------------
# Test 7: reporting.__init__ exports all required names
# ---------------------------------------------------------------------------

def test_reporting_init_exports():
    import reporting

    required = [
        "HMDALARRecord",
        "CRAActivityReport",
        "generate_cra_activity_report",
        "Metro2Record",
        "export_metro2",
        "UDAAPSummaryReport",
        "generate_udaap_summary",
        "DispatchResult",
        "dispatch_reports",
    ]
    for name in required:
        assert hasattr(reporting, name), f"reporting.{name} not exported"


# ---------------------------------------------------------------------------
# Test 8: DispatchResult.to_dict() contains required keys
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_result_to_dict():
    from reporting.dispatcher import dispatch_reports

    with patch(
        "reporting.dispatcher.get_audit_records_by_period",
        new=AsyncMock(return_value=[]),
    ):
        result = await dispatch_reports(
            tenant_id=TENANT,
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            db_url=DB_URL,
        )

    d = result.to_dict()
    for key in (
        "tenant_id",
        "period_start",
        "period_end",
        "total_audit_records_fetched",
        "reports_generated",
        "cra_report",
        "udaap_report",
        "metro2_record_count",
        "errors",
    ):
        assert key in d, f"Missing key: {key}"
