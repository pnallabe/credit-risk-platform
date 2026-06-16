"""Tests for GAP-12-A: _ServiceMetrics class and GET /v1/metrics endpoint.

Covers:
- _ServiceMetrics.record() + snapshot() correctness
- p99_latency_ms() within ±5% of expected
- error_rate() accuracy
- GET /v1/metrics via TestClient returns canary_healthy key
- canary_healthy == False when p99 > threshold (via env var manipulation)
- METRICS_AUTH_TOKEN accepted as bearer
- Invalid token → 401
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-metrics")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_metrics.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"


def _make_token(tenant_id: str = "tenant-metrics-test") -> str:
    return pyjwt.encode({"tenant_id": tenant_id}, _JWT_SECRET, algorithm=_JWT_ALGO)


def _auth(tenant_id: str = "tenant-metrics-test"):
    return {"Authorization": f"Bearer {_make_token(tenant_id)}"}


# ---------------------------------------------------------------------------
# Unit tests: _ServiceMetrics class
# ---------------------------------------------------------------------------


class TestServiceMetricsClass:
    """Direct unit tests against the _ServiceMetrics data class."""

    @pytest.fixture(autouse=True)
    def metrics(self):
        # Import fresh each test to avoid state bleed
        with (
            patch("src.main._load_models"),
            patch("src.main._fraud_model", MagicMock()),
            patch("src.main._risk_model", MagicMock()),
        ):
            from src.main import _ServiceMetrics
            self._ServiceMetrics = _ServiceMetrics
        self.m = self._ServiceMetrics()

    def test_initial_snapshot_zero(self) -> None:
        snap = self.m.snapshot()
        assert snap["total_requests"] == 0
        assert snap["total_5xx"] == 0
        assert snap["p99_latency_ms"] == 0.0

    def test_p99_within_tolerance(self) -> None:
        """Record 100 latencies with known distribution; p99 should be within ±5%."""
        import numpy as np
        np.random.seed(42)
        latencies = np.random.normal(loc=200, scale=20, size=1000).tolist()
        for lat in latencies:
            self.m.record(lat, is_error=False)
        snap = self.m.snapshot()
        expected_p99 = float(np.percentile(latencies, 99))
        actual_p99 = snap["p99_latency_ms"]
        assert abs(actual_p99 - expected_p99) / max(expected_p99, 1.0) < 0.05

    def test_p50_p95_p99_ordering(self) -> None:
        """Statistical ordering must hold: p50 ≤ p95 ≤ p99."""
        for i in range(100):
            self.m.record(float(i * 5), is_error=False)
        snap = self.m.snapshot()
        assert snap["p50_latency_ms"] <= snap["p95_latency_ms"] <= snap["p99_latency_ms"]

    def test_error_rate_accuracy(self) -> None:
        """10 errors in 100 requests → error_rate ≈ 0.10."""
        for i in range(90):
            self.m.record(100.0, is_error=False)
        for _ in range(10):
            self.m.record(100.0, is_error=True)
        snap = self.m.snapshot()
        assert abs(snap["error_rate_5xx"] - 0.10) < 0.01

    def test_canary_healthy_true_by_default(self) -> None:
        """With no errors and low latencies, canary_healthy should be True."""
        for _ in range(50):
            self.m.record(100.0, is_error=False)
        snap = self.m.snapshot()
        assert snap["canary_healthy"] is True

    def test_canary_healthy_false_when_p99_exceeds_threshold(self) -> None:
        """canary_healthy == False when p99 > CANARY_P99_THRESHOLD_MS."""
        # Set threshold to 50ms, record latencies around 500ms
        with patch.dict(os.environ, {"CANARY_P99_THRESHOLD_MS": "50"}):
            m = self._ServiceMetrics()
            for _ in range(200):
                m.record(600.0, is_error=False)
            snap = m.snapshot()
        assert snap["canary_healthy"] is False

    def test_canary_healthy_false_when_error_rate_exceeds_threshold(self) -> None:
        """canary_healthy == False when error_rate > CANARY_ERROR_RATE_THRESHOLD."""
        with patch.dict(os.environ, {"CANARY_ERROR_RATE_THRESHOLD": "0.01"}):
            m = self._ServiceMetrics()
            for _ in range(80):
                m.record(100.0, is_error=False)
            for _ in range(20):  # 20% error rate
                m.record(100.0, is_error=True)
            snap = m.snapshot()
        assert snap["canary_healthy"] is False

    def test_thread_safe_concurrent_records(self) -> None:
        """Concurrent records from multiple threads produce correct total_requests."""
        import threading
        n = 200
        errors = 0

        def _record():
            for _ in range(n):
                self.m.record(50.0, is_error=False)

        threads = [threading.Thread(target=_record) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = self.m.snapshot()
        assert snap["total_requests"] == 4 * n


# ---------------------------------------------------------------------------
# Integration tests: GET /v1/metrics endpoint
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """HTTP-level tests against GET /v1/metrics."""

    @pytest.fixture(autouse=True)
    def client(self):
        mock_model = MagicMock()
        with (
            patch("src.main._load_models"),
            patch("src.main._fraud_model", mock_model),
            patch("src.main._risk_model", mock_model),
        ):
            from fastapi.testclient import TestClient
            from src.main import app
            with TestClient(app, raise_server_exceptions=False) as c:
                self._client = c
                yield c

    def test_canary_healthy_key_present(self) -> None:
        """GET /v1/metrics returns canary_healthy in response."""
        resp = self._client.get("/v1/metrics", headers=_auth())
        assert resp.status_code == 200
        assert "canary_healthy" in resp.json()

    def test_metrics_token_accepted(self) -> None:
        """METRICS_AUTH_TOKEN env var accepted as bearer token."""
        with patch.dict(os.environ, {"METRICS_AUTH_TOKEN": "secret-metrics-token"}):
            resp = self._client.get(
                "/v1/metrics",
                headers={"Authorization": "Bearer secret-metrics-token"},
            )
        assert resp.status_code == 200

    def test_invalid_token_returns_401(self) -> None:
        """Invalid JWT → 401 Unauthorized."""
        resp = self._client.get(
            "/v1/metrics",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
        assert resp.status_code == 401

    def test_missing_auth_returns_401(self) -> None:
        resp = self._client.get("/v1/metrics")
        assert resp.status_code == 401

    def test_p99_latency_key_present(self) -> None:
        """Response includes p99_latency_ms key."""
        resp = self._client.get("/v1/metrics", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "p99_latency_ms" in data

    def test_error_rate_key_present(self) -> None:
        resp = self._client.get("/v1/metrics", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "error_rate_5xx" in data

    def test_total_requests_key_present(self) -> None:
        resp = self._client.get("/v1/metrics", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert "total_requests" in data
