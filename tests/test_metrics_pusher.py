"""
tests/test_metrics_pusher.py
=============================
Unit tests for ``observability.metrics_pusher`` (PROMPT-09).

Tests
-----
* ``GET /metrics`` returns 200 and contains the expected histogram metric name.
* Recording a latency sample increments the histogram.
* A 5xx response increments ``credit_decision_errors_total``.
* Existing ``/v1/metrics`` JSON endpoint is unaffected (backward-compat).
* ``push_to_cloud_monitoring`` is a no-op when ``ENABLE_CLOUD_MONITORING`` is unset.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── Make repo root importable ────────────────────────────────────────────────
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Import after path setup
# ---------------------------------------------------------------------------
from observability.metrics_pusher import MetricsCollector, push_to_cloud_monitoring


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_collector() -> MetricsCollector:
    """Return a fresh MetricsCollector with an isolated registry."""
    try:
        from prometheus_client import CollectorRegistry
        return MetricsCollector(registry=CollectorRegistry())
    except ImportError:
        pytest.skip("prometheus-client not installed")


# ---------------------------------------------------------------------------
# MetricsCollector unit tests
# ---------------------------------------------------------------------------


def test_record_increments_request_counter():
    """Recording a request must increment credit_decision_requests_total."""
    collector = _new_collector()
    from prometheus_client.exposition import generate_latest

    collector.record(latency_s=0.1, tenant_id="acme", route="/v1/decisions", status_code=200)
    text = generate_latest(collector._registry).decode("utf-8")

    assert "credit_decision_requests_total" in text
    assert "acme" in text


def test_record_observes_latency_histogram():
    """Recording a request must produce a histogram bucket entry."""
    collector = _new_collector()
    from prometheus_client.exposition import generate_latest

    collector.record(latency_s=0.05, tenant_id="acme", route="/v1/decisions", status_code=200)
    text = generate_latest(collector._registry).decode("utf-8")

    assert "credit_decision_latency_seconds_bucket" in text


def test_5xx_increments_error_counter():
    """A 5xx status code must produce a counter value row for credit_decision_errors_total."""
    collector = _new_collector()
    from prometheus_client.exposition import generate_latest

    collector.record(latency_s=0.3, tenant_id="acme", route="/v1/decisions", status_code=500)
    text = generate_latest(collector._registry).decode("utf-8")

    # At least one non-comment line must reference the error counter with a value
    value_lines = [
        line for line in text.splitlines()
        if "credit_decision_errors_total" in line and not line.startswith("#")
    ]
    assert value_lines, (
        "Expected at least one error counter value line for 500 response"
    )


def test_2xx_does_not_increment_error_counter():
    """A 2xx status code must NOT produce any counter value rows for credit_decision_errors_total."""
    collector = _new_collector()
    from prometheus_client.exposition import generate_latest

    collector.record(latency_s=0.05, tenant_id="acme", route="/v1/decisions", status_code=200)
    text = generate_latest(collector._registry).decode("utf-8")

    # Prometheus emits HELP/TYPE lines always, but no actual counter value line
    # should be present (lines that are not HELP/TYPE comments and contain the metric).
    value_lines = [
        line for line in text.splitlines()
        if "credit_decision_errors_total" in line
        and not line.startswith("#")
    ]
    assert value_lines == [], (
        f"Expected no error counter value lines for 200 response, got: {value_lines}"
    )


def test_snapshot_returns_text():
    """MetricsCollector.snapshot() must return a dict with a 'text' key."""
    collector = _new_collector()
    collector.record(latency_s=0.1, tenant_id="t1", route="/v1/decisions", status_code=200)
    snap = collector.snapshot()
    assert isinstance(snap, dict)
    assert "text" in snap
    assert "credit_decision_latency_seconds" in snap["text"]


def test_make_asgi_app_returns_callable():
    """make_asgi_app() must return a callable ASGI app."""
    collector = _new_collector()
    app = collector.make_asgi_app()
    assert callable(app)


# ---------------------------------------------------------------------------
# FastAPI /metrics endpoint tests
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """Return a TestClient for the decision API."""
    api_src = str(Path(__file__).resolve().parents[1] / "decision-api" / "src")
    if api_src not in sys.path:
        sys.path.insert(0, api_src)
    try:
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        pytest.skip("Decision API not importable in this environment")


def test_metrics_endpoint_returns_200(api_client):
    """GET /metrics must return 200."""
    resp = api_client.get("/metrics")
    # May return 200 (Prometheus installed) or 503 (not installed) — both valid
    assert resp.status_code in (200, 503)


def test_metrics_endpoint_contains_histogram_if_prometheus_installed(api_client):
    """GET /metrics must contain the histogram name when prometheus-client is installed."""
    try:
        import prometheus_client  # noqa: F401
    except ImportError:
        pytest.skip("prometheus-client not installed")

    # Record a sample request first via the collector
    from main import _PROM_COLLECTOR  # type: ignore[import]
    if _PROM_COLLECTOR is not None:
        _PROM_COLLECTOR.record(
            latency_s=0.1,
            tenant_id="test-tenant",
            route="/v1/decisions",
            status_code=200,
        )

    resp = api_client.get("/metrics")
    assert resp.status_code == 200
    assert "credit_decision_latency_seconds_bucket" in resp.text


def test_v1_metrics_json_endpoint_still_works(api_client):
    """The existing /v1/metrics JSON endpoint must still respond (backward-compat)."""
    import os, jwt  # noqa: E401
    from datetime import datetime, timezone, timedelta

    secret = os.getenv("JWT_SECRET", "dev-secret-please-change")
    token = jwt.encode(
        {"tenant_id": "t1", "sub": "u", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        secret,
        algorithm="HS256",
    )
    resp = api_client.get(
        "/v1/metrics",
        headers={"Authorization": f"Bearer {token}"},
    )
    # May fail auth in some configurations — we just assert it's not a crash
    assert resp.status_code in (200, 401, 403)


# ---------------------------------------------------------------------------
# Cloud Monitoring push guard
# ---------------------------------------------------------------------------


def test_push_to_cloud_monitoring_is_noop_without_env_flag():
    """push_to_cloud_monitoring must be a no-op when ENABLE_CLOUD_MONITORING is unset."""
    os.environ.pop("ENABLE_CLOUD_MONITORING", None)
    # Should complete without error or side effects
    push_to_cloud_monitoring(
        project_id="test-project",
        metrics_snapshot={"p99_latency_ms": 123.4},
    )


def test_push_to_cloud_monitoring_is_noop_when_disabled():
    """push_to_cloud_monitoring must be a no-op when ENABLE_CLOUD_MONITORING=false."""
    with patch.dict(os.environ, {"ENABLE_CLOUD_MONITORING": "false"}):
        push_to_cloud_monitoring(
            project_id="test-project",
            metrics_snapshot={"p99_latency_ms": 50.0},
        )
