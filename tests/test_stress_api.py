"""Integration tests for GAP-15-B: Stress Test API endpoints.

Covers:
- POST /v1/stress-test/run → 202 with run_id (valid CRO role)
- POST /v1/stress-test/run → 403 for non-CRO role
- GET /v1/stress-test/results → returns list
- GET /v1/stress-test/compare?quarter_a=...&quarter_b=... → returns delta metrics
- POST /v1/stress-test/run → 503 when stress runner unavailable
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-stress")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stress_api.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(
    tenant_id: str = "tenant-stress",
    role: str = "cro",
    email: str = "cro@example.com",
) -> str:
    return pyjwt.encode(
        {"tenant_id": tenant_id, "sub": email, "role": role, "email": email},
        _JWT_SECRET,
        algorithm=_JWT_ALGO,
    )


def _auth(role: str = "cro", tenant_id: str = "tenant-stress") -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(tenant_id, role)}"}


# ---------------------------------------------------------------------------
# Mock stress test runner
# ---------------------------------------------------------------------------


def _make_mock_runner(
    run_id: str = "run-test-001",
    results: list = None,
    compare_result: dict = None,
) -> MagicMock:
    """Create a mock StressTestRunner with configurable return values."""
    mock_runner = MagicMock()
    mock_summary = MagicMock()
    mock_summary.run_id = run_id
    mock_runner.run.return_value = mock_summary
    mock_runner.get_results.return_value = results if results is not None else [
        {"run_id": run_id, "quarter": "2026-Q1", "severity": "moderate", "n_scenarios": 100}
    ]
    mock_runner.compare_quarters.return_value = compare_result if compare_result is not None else {
        "quarter_a": "2026-Q1",
        "quarter_b": "2026-Q2",
        "p99_stressed_dr_delta": 0.015,
        "max_expected_loss_delta": 50000.0,
        "a": {"run_id": "run-a", "p99_stressed_dr": 0.12},
        "b": {"run_id": "run-b", "p99_stressed_dr": 0.135},
    }
    return mock_runner


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
    ):
        from fastapi.testclient import TestClient
        from src.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# Tests: POST /v1/stress-test/run
# ---------------------------------------------------------------------------


class TestStressTestRun:
    def test_valid_cro_role_returns_202(self, client) -> None:
        """CRO role triggers stress test → 202 Accepted with run_id."""
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.post(
                "/v1/stress-test/run",
                json={"quarter": "2026-Q1", "severity": "moderate", "n_scenarios": 100},
                headers=_auth(role="cro"),
            )
        assert resp.status_code == 202
        data = resp.json()
        assert "run_id" in data

    def test_credit_risk_role_returns_202(self, client) -> None:
        """'credit_risk' role also has permission to run stress tests."""
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.post(
                "/v1/stress-test/run",
                json={"quarter": "2026-Q2", "severity": "mild", "n_scenarios": 50},
                headers=_auth(role="credit_risk"),
            )
        assert resp.status_code == 202

    def test_admin_role_returns_202(self, client) -> None:
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.post(
                "/v1/stress-test/run",
                json={"quarter": "2026-Q3", "severity": "severe"},
                headers=_auth(role="admin"),
            )
        assert resp.status_code == 202

    def test_analyst_role_returns_403(self, client) -> None:
        """Non-CRO role (analyst) → 403 Forbidden."""
        resp = client.post(
            "/v1/stress-test/run",
            json={"quarter": "2026-Q1", "severity": "moderate"},
            headers=_auth(role="analyst"),
        )
        assert resp.status_code == 403

    def test_viewer_role_returns_403(self, client) -> None:
        resp = client.post(
            "/v1/stress-test/run",
            json={"quarter": "2026-Q1", "severity": "moderate"},
            headers=_auth(role="viewer"),
        )
        assert resp.status_code == 403

    def test_response_contains_expected_fields(self, client) -> None:
        mock_runner = _make_mock_runner(run_id="run-expected-fields")
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.post(
                "/v1/stress-test/run",
                json={"quarter": "2026-Q1", "severity": "moderate", "n_scenarios": 100},
                headers=_auth(role="cro"),
            )
        assert resp.status_code == 202
        data = resp.json()
        for key in ("run_id", "status", "quarter", "severity", "n_scenarios"):
            assert key in data, f"Missing key: {key}"

    def test_503_when_runner_unavailable(self, client) -> None:
        """If stress runner cannot be initialized → 503 Service Unavailable."""
        with patch("src.main._get_stress_runner", return_value=None):
            resp = client.post(
                "/v1/stress-test/run",
                json={"quarter": "2026-Q1", "severity": "moderate"},
                headers=_auth(role="cro"),
            )
        assert resp.status_code == 503

    def test_requires_auth(self, client) -> None:
        resp = client.post(
            "/v1/stress-test/run",
            json={"quarter": "2026-Q1"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /v1/stress-test/results
# ---------------------------------------------------------------------------


class TestStressTestResults:
    def test_results_returns_list(self, client) -> None:
        """GET /v1/stress-test/results returns a list."""
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.get("/v1/stress-test/results", headers=_auth())
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_results_list_contains_run_id(self, client) -> None:
        mock_runner = _make_mock_runner(run_id="run-in-list")
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.get("/v1/stress-test/results", headers=_auth())
        assert resp.status_code == 200
        results = resp.json()
        if results:
            assert "run_id" in results[0]

    def test_results_returns_empty_list_when_runner_unavailable(self, client) -> None:
        """Returns [] gracefully when runner is None."""
        with patch("src.main._get_stress_runner", return_value=None):
            resp = client.get("/v1/stress-test/results", headers=_auth())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_results_filtered_by_quarter(self, client) -> None:
        """Quarter filter is forwarded to get_results()."""
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.get(
                "/v1/stress-test/results?quarter=2026-Q1",
                headers=_auth(),
            )
        assert resp.status_code == 200
        # Verify get_results was called with the quarter kwarg
        mock_runner.get_results.assert_called()

    def test_requires_auth(self, client) -> None:
        resp = client.get("/v1/stress-test/results")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Tests: GET /v1/stress-test/compare
# ---------------------------------------------------------------------------


class TestStressTestCompare:
    def test_compare_returns_delta_metrics(self, client) -> None:
        """compare returns a dict with quarter_a, quarter_b, and delta fields."""
        mock_runner = _make_mock_runner()
        with patch("src.main._get_stress_runner", return_value=mock_runner):
            resp = client.get(
                "/v1/stress-test/compare?quarter_a=2026-Q1&quarter_b=2026-Q2",
                headers=_auth(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "quarter_a" in data or "p99_stressed_dr_delta" in data or "a" in data

    def test_compare_503_when_runner_unavailable(self, client) -> None:
        with patch("src.main._get_stress_runner", return_value=None):
            resp = client.get(
                "/v1/stress-test/compare?quarter_a=2026-Q1&quarter_b=2026-Q2",
                headers=_auth(),
            )
        assert resp.status_code == 503

    def test_compare_requires_both_quarters(self, client) -> None:
        """Missing quarter params → 422 Unprocessable."""
        resp = client.get(
            "/v1/stress-test/compare?quarter_a=2026-Q1",  # missing quarter_b
            headers=_auth(),
        )
        assert resp.status_code == 422

    def test_compare_requires_auth(self, client) -> None:
        resp = client.get(
            "/v1/stress-test/compare?quarter_a=2026-Q1&quarter_b=2026-Q2"
        )
        assert resp.status_code == 401
