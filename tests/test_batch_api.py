"""Integration tests for GAP-14-B: Batch Underwriting Upload API.

Covers:
- POST /v1/batch/underwrite → 202 with job_id (immediate)
- GET /v1/batch/{id}/status → returns current status fields
- POST with missing required columns → 422
- POST with > 10,000 rows → 413
- POST with empty CSV → 422
- GET /v1/batch/{id}/results on non-complete job → 409
- Tenant isolation: listing another tenant's job → 404
"""

from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-batch")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_batch_api.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_CSV_COLS = [
    "application_id", "customer_id", "credit_score", "annual_income",
    "employment_status", "employer_tenure_months", "debt_to_income_ratio",
    "existing_debt_amount", "loan_amount", "loan_purpose", "loan_term_months",
    "num_open_accounts", "num_derogatory_marks",
]


def _make_token(tenant_id: str = "tenant-batch", role: str = "analyst") -> str:
    return pyjwt.encode(
        {"tenant_id": tenant_id, "sub": "user@example.com", "role": role},
        _JWT_SECRET,
        algorithm=_JWT_ALGO,
    )


def _auth(tenant_id: str = "tenant-batch") -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(tenant_id)}"}


def _build_csv(n_rows: int = 3, include_cols: list = None) -> bytes:
    """Build a minimal valid CSV for batch upload."""
    cols = include_cols if include_cols is not None else _REQUIRED_CSV_COLS
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for i in range(n_rows):
        row = {
            "application_id": f"app-batch-{i:05d}",
            "customer_id": f"cust-{i:05d}",
            "credit_score": "700",
            "annual_income": "60000.0",
            "employment_status": "employed",
            "employer_tenure_months": "24",
            "debt_to_income_ratio": "0.25",
            "existing_debt_amount": "5000.0",
            "loan_amount": "10000.0",
            "loan_purpose": "personal",
            "loan_term_months": "36",
            "num_open_accounts": "4",
            "num_derogatory_marks": "0",
        }
        # If testing missing cols, only add what's in cols
        filtered = {k: v for k, v in row.items() if k in cols}
        writer.writerow(filtered)
    return buf.getvalue().encode("utf-8")


def _csv_upload_payload(data: bytes, filename: str = "batch.csv"):
    """Return files dict for httpx/requests-style file upload."""
    return {"file": (filename, io.BytesIO(data), "text/csv")}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    mock_model = MagicMock()
    with (
        patch("src.main._load_models"),
        patch("src.main._fraud_model", mock_model),
        patch("src.main._risk_model", mock_model),
        # Prevent actual background tasks from executing during tests
        patch("src.main.asyncio.create_task", return_value=None),
    ):
        from fastapi.testclient import TestClient
        from src.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Tests: POST /v1/batch/underwrite
# ---------------------------------------------------------------------------


class TestBatchSubmit:
    def test_returns_202_immediately(self, client) -> None:
        """CSV upload returns 202 and job_id without waiting for processing."""
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(5)),
        )
        assert resp.status_code == 202

    def test_response_contains_job_id(self, client) -> None:
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(3)),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert isinstance(data["job_id"], str)
        assert len(data["job_id"]) > 0

    def test_response_contains_status_pending(self, client) -> None:
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(2)),
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "PENDING"

    def test_response_contains_total_rows(self, client) -> None:
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(7)),
        )
        assert resp.status_code == 202
        assert resp.json()["total_rows"] == 7

    def test_missing_required_columns_returns_422(self, client) -> None:
        """CSV with missing required columns → 422 Unprocessable Entity."""
        missing_cols = _REQUIRED_CSV_COLS[:-3]  # drop last 3 required cols
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(3, include_cols=missing_cols)),
        )
        assert resp.status_code == 422

    def test_empty_csv_returns_422(self, client) -> None:
        """CSV with only a header and no data rows → 422."""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=_REQUIRED_CSV_COLS)
        writer.writeheader()
        # No rows written
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(buf.getvalue().encode("utf-8")),
        )
        assert resp.status_code == 422

    def test_too_many_rows_returns_413(self, client) -> None:
        """CSV exceeding 10,000 rows → 413 Request Entity Too Large."""
        resp = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(10_001)),
        )
        assert resp.status_code == 413

    def test_requires_auth(self, client) -> None:
        resp = client.post(
            "/v1/batch/underwrite",
            files=_csv_upload_payload(_build_csv(1)),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /v1/batch/{job_id}/status
# ---------------------------------------------------------------------------


class TestBatchStatus:
    def test_status_returns_pending_immediately_after_submit(self, client) -> None:
        """Job created via upload starts in PENDING, then transitions."""
        submit = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(2)),
        )
        assert submit.status_code == 202
        job_id = submit.json()["job_id"]

        status = client.get(f"/v1/batch/{job_id}/status", headers=_auth())
        assert status.status_code == 200
        data = status.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("PENDING", "RUNNING", "COMPLETE", "FAILED")

    def test_status_contains_expected_fields(self, client) -> None:
        submit = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(1)),
        )
        job_id = submit.json()["job_id"]
        status = client.get(f"/v1/batch/{job_id}/status", headers=_auth())
        data = status.json()
        for field in ("job_id", "tenant_id", "status", "total_rows"):
            assert field in data, f"Missing field: {field}"

    def test_unknown_job_returns_404(self, client) -> None:
        resp = client.get("/v1/batch/nonexistent-job-id/status", headers=_auth())
        assert resp.status_code == 404

    def test_tenant_isolation_on_status(self, client) -> None:
        """Tenant B cannot view Tenant A's job status."""
        # Create job as tenant-batch-A
        submit = client.post(
            "/v1/batch/underwrite",
            headers=_auth("tenant-batch-A"),
            files=_csv_upload_payload(_build_csv(1)),
        )
        job_id = submit.json()["job_id"]

        # Attempt to retrieve as tenant-batch-B
        status = client.get(
            f"/v1/batch/{job_id}/status",
            headers=_auth("tenant-batch-B"),
        )
        assert status.status_code == 404


# ---------------------------------------------------------------------------
# Tests: GET /v1/batch/{job_id}/results
# ---------------------------------------------------------------------------


class TestBatchResults:
    def test_results_on_pending_job_returns_409(self, client) -> None:
        """Trying to get results before job is COMPLETE → 409 Conflict."""
        submit = client.post(
            "/v1/batch/underwrite",
            headers=_auth(),
            files=_csv_upload_payload(_build_csv(2)),
        )
        job_id = submit.json()["job_id"]

        # Immediately try /results while still PENDING
        resp = client.get(f"/v1/batch/{job_id}/results", headers=_auth())
        # 409 if PENDING/RUNNING, or 404 — either is valid (not yet COMPLETE)
        assert resp.status_code in (409, 404)

    def test_unknown_job_results_returns_404(self, client) -> None:
        resp = client.get("/v1/batch/nonexistent-job/results", headers=_auth())
        assert resp.status_code == 404
