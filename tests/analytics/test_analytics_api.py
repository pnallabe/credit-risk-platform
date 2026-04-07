"""
tests/analytics/test_analytics_api.py
=====================================
Tests for the P2.2 Analytics API endpoints.

Strategy
--------
* Uses httpx TestClient (via starlette) — no real BQ or live DB required.
* analytics_api._backend is patched to return synthetic rows.
* JWT auth is mocked so tests focus on business logic, pagination, and
  tenant scoping rather than auth mechanics.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Set JWT_SECRET before importing the app so startup validation passes
import os
os.environ.setdefault("JWT_SECRET", "test-secret-analytics-api-42")  # pragma: allowlist secret

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_USER = {"tenant_id": "test_tenant", "sub": "alice@test.com"}


def _make_client():
    from analytics_api.src.main import app, verify_bearer

    # Bypass auth for all tests
    app.dependency_overrides[verify_bearer] = lambda: _FAKE_USER
    return TestClient(app)


def _fake_rows_vintage() -> List[Dict[str, Any]]:
    return [
        {
            "origination_month": "2025-01-01",
            "bucket": "LOW",
            "cohort_count": 120,
            "total_originated_amount": 1_200_000.0,
            "decline_rate": 0.05,
            "cumulative_default_rate": 0.0,
            "net_loss_rate": 0.0,
        }
    ]


def _fake_rows_rollrates() -> List[Dict[str, Any]]:
    return [
        {
            "dpd_bucket": "Current",
            "pd_band": "LOW",
            "account_count": 500,
            "total_balance": 5_000_000.0,
            "pct_of_pd_band": 0.90,
            "roll_rate_to_next_bucket": None,
        }
    ]


def _fake_rows_profit() -> List[Dict[str, Any]]:
    return [
        {
            "segment": "LOW",
            "segment_type": "pd_band",
            "total_applications": 200,
            "approved_count": 160,
            "rejected_count": 30,
            "manual_review_count": 10,
            "approval_rate": 0.80,
            "avg_approved_amount": 12_000.0,
            "total_approved_amount": 1_920_000.0,
            "avg_pd_score_approved": 0.025,
            "expected_profit_usd": 48_000.0,
            "expected_return_rate": 0.025,
        }
    ]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_ok():
    client = _make_client()
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "backend" in data


# ---------------------------------------------------------------------------
# Vintage curves
# ---------------------------------------------------------------------------


def test_vintage_curves_returns_data():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = _fake_rows_vintage()
        resp = client.get("/v1/analytics/vintage-curves?months_back=12")

    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    assert "meta" in body
    assert len(body["data"]) == 1
    assert body["data"][0]["bucket"] == "LOW"


def test_vintage_curves_has_pagination_meta():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = _fake_rows_vintage()
        resp = client.get("/v1/analytics/vintage-curves?limit=10&offset=20")

    meta = resp.json()["meta"]
    assert meta["limit"] == 10
    assert meta["offset"] == 20
    assert meta["returned"] == 1


def test_vintage_curves_backend_failure_returns_500():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.side_effect = RuntimeError("BQ unavailable")
        resp = client.get("/v1/analytics/vintage-curves")

    assert resp.status_code == 500
    assert "Query execution failed" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Roll rates
# ---------------------------------------------------------------------------


def test_roll_rates_returns_data():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = _fake_rows_rollrates()
        resp = client.get("/v1/analytics/roll-rates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"][0]["dpd_bucket"] == "Current"


def test_roll_rates_accepts_as_of_date():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = []
        resp = client.get("/v1/analytics/roll-rates?as_of_date=2025-06-01&months_back=6")

    assert resp.status_code == 200
    # Verify params were forwarded (check call args)
    _, kwargs = mock_backend.run_sql.call_args
    # params is second positional arg
    call_args = mock_backend.run_sql.call_args
    params_arg = call_args[0][1] if len(call_args[0]) >= 2 else call_args[1].get("params", {})
    assert params_arg.get("as_of_date") == "2025-06-01"


# ---------------------------------------------------------------------------
# Approval profit
# ---------------------------------------------------------------------------


def test_approval_profit_returns_data():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = _fake_rows_profit()
        resp = client.get("/v1/analytics/approval-profit")

    assert resp.status_code == 200
    row = resp.json()["data"][0]
    assert row["approval_rate"] == 0.80
    assert row["expected_profit_usd"] == 48_000.0


def test_approval_profit_min_applications_param():
    client = _make_client()
    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.return_value = []
        resp = client.get("/v1/analytics/approval-profit?min_applications=50")

    assert resp.status_code == 200
    call_args = mock_backend.run_sql.call_args
    params_arg = call_args[0][1]
    assert params_arg["min_applications"] == 50


# ---------------------------------------------------------------------------
# Tenant scoping — verify tenant_id is always injected into query params
# ---------------------------------------------------------------------------


def test_tenant_id_injected_into_query_params():
    client = _make_client()
    captured_params: Dict = {}

    def capture(sql, params):
        captured_params.update(params)
        return []

    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.side_effect = capture
        client.get("/v1/analytics/vintage-curves")

    assert captured_params.get("tenant_id") == "test_tenant"


def test_vintage_curves_tenant_scoped_different_tenant():
    """Simulate two tenants calling the same endpoint — each gets their own cache key."""
    fake_a = {"tenant_id": "tenant_a", "sub": "a"}
    fake_b = {"tenant_id": "tenant_b", "sub": "b"}

    from analytics_api.src.main import app, verify_bearer

    calls: List[str] = []

    def capture(sql, params):
        calls.append(params["tenant_id"])
        return []

    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.side_effect = capture

        app.dependency_overrides[verify_bearer] = lambda: fake_a
        c = TestClient(app)
        c.get("/v1/analytics/vintage-curves?months_back=6")

        app.dependency_overrides[verify_bearer] = lambda: fake_b
        c2 = TestClient(app)
        c2.get("/v1/analytics/vintage-curves?months_back=6")

    assert "tenant_a" in calls
    assert "tenant_b" in calls


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


def test_missing_auth_returns_401():
    from analytics_api.src.main import app

    # Remove override so real auth runs
    app.dependency_overrides.clear()
    client = TestClient(app)
    # No Authorization header
    resp = client.get("/v1/analytics/vintage-curves")
    # 401 or 403
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def test_cache_hit_skips_backend_call():
    """Second identical request should not call backend.run_sql again."""
    import analytics_api.src.main as analytics_main

    # Clear cache first
    analytics_main._cache.clear()

    client = _make_client()

    call_count = 0

    def counting_run(sql, params):
        nonlocal call_count
        call_count += 1
        return _fake_rows_vintage()

    with patch("analytics_api.src.main._backend") as mock_backend:
        mock_backend.run_sql.side_effect = counting_run
        client.get("/v1/analytics/vintage-curves?months_back=3")
        client.get("/v1/analytics/vintage-curves?months_back=3")

    # First call should hit backend; second should be served from cache
    assert call_count == 1
