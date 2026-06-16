"""
observability/metrics_pusher.py
================================
Prometheus metrics collector and optional Cloud Monitoring pusher (PROMPT-09).

Exposes
-------
* ``credit_decision_latency_seconds`` — Histogram, labels: tenant_id, route, environment.
* ``credit_decision_errors_total``    — Counter,   labels: tenant_id, route, status_code.
* ``credit_decision_requests_total``  — Counter,   labels: tenant_id, route.

Usage
-----
    from observability.metrics_pusher import MetricsCollector

    collector = MetricsCollector()

    # Record a request
    collector.record(latency_s=0.12, tenant_id="acme", route="/v1/decisions", status_code=200)

    # Mount the Prometheus ASGI endpoint
    app.mount("/metrics", collector.make_asgi_app())

Cloud Monitoring push (optional)
---------------------------------
Set ``ENABLE_CLOUD_MONITORING=true`` and ensure ``google-cloud-monitoring`` is
installed.  Guarded behind an env-var flag so installs without GCP credentials
do not fail.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prometheus client — graceful degradation if not installed
# ---------------------------------------------------------------------------

try:
    import prometheus_client as _prom
    from prometheus_client import (
        Counter,
        Histogram,
        CollectorRegistry,
        make_asgi_app as _prom_make_asgi_app,
    )
    _PROM_AVAILABLE = True
except ImportError:
    _prom = None  # type: ignore[assignment]
    _PROM_AVAILABLE = False
    logger.warning(
        "prometheus-client not installed — Prometheus metrics are disabled. "
        "Add prometheus-client>=0.20.0 to requirements.txt."
    )


# ---------------------------------------------------------------------------
# MetricsCollector
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Thread-safe Prometheus metrics collector for the Credit Risk Decision API.

    Creates a *private* ``CollectorRegistry`` per instance so tests can
    instantiate multiple collectors without metric-name conflicts.

    Parameters
    ----------
    registry:
        Optional custom ``CollectorRegistry``.  Defaults to a new private
        registry so that the collector is isolated from the default
        ``prometheus_client.REGISTRY``.
    environment:
        Value of the ``environment`` label (e.g. ``"prod"``).
    """

    # Histogram buckets aligned with SLA thresholds
    _LATENCY_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5)

    def __init__(
        self,
        registry: Optional[Any] = None,
        environment: Optional[str] = None,
    ) -> None:
        self._environment = environment or os.getenv("ENVIRONMENT", "dev")

        if not _PROM_AVAILABLE:
            self._registry = None
            self._latency_hist = None
            self._error_counter = None
            self._request_counter = None
            return

        self._registry: CollectorRegistry = registry or CollectorRegistry()

        self._latency_hist: Histogram = Histogram(
            "credit_decision_latency_seconds",
            "End-to-end decision API request latency in seconds.",
            labelnames=["tenant_id", "route", "environment"],
            buckets=self._LATENCY_BUCKETS,
            registry=self._registry,
        )

        self._error_counter: Counter = Counter(
            "credit_decision_errors_total",
            "Total number of 5xx error responses.",
            labelnames=["tenant_id", "route", "status_code"],
            registry=self._registry,
        )

        self._request_counter: Counter = Counter(
            "credit_decision_requests_total",
            "Total number of requests handled.",
            labelnames=["tenant_id", "route"],
            registry=self._registry,
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def record(
        self,
        latency_s: float,
        tenant_id: str,
        route: str,
        status_code: int,
    ) -> None:
        """Record metrics for a single request.

        Parameters
        ----------
        latency_s:
            Request latency in *seconds* (float).
        tenant_id:
            Tenant identifier extracted from the request JWT / middleware state.
        route:
            Request path, e.g. ``"/v1/decisions"``.
        status_code:
            HTTP response status code.
        """
        if not _PROM_AVAILABLE or self._latency_hist is None:
            return

        env = self._environment

        try:
            self._latency_hist.labels(
                tenant_id=tenant_id,
                route=route,
                environment=env,
            ).observe(latency_s)

            self._request_counter.labels(
                tenant_id=tenant_id,
                route=route,
            ).inc()

            if status_code >= 500:
                self._error_counter.labels(
                    tenant_id=tenant_id,
                    route=route,
                    status_code=str(status_code),
                ).inc()
        except Exception as exc:
            logger.warning("MetricsCollector.record failed: %s", exc)

    def make_asgi_app(self) -> Any:
        """Return a Prometheus ASGI application that serves ``/metrics``.

        Mount this at ``/metrics`` using ``app.mount("/metrics", collector.make_asgi_app())``.
        """
        if not _PROM_AVAILABLE:
            # Return a minimal ASGI app that returns 503
            async def _unavailable(scope, receive, send):
                if scope["type"] == "http":
                    body = b"prometheus_client not installed\n"
                    await send({
                        "type": "http.response.start",
                        "status": 503,
                        "headers": [(b"content-type", b"text/plain")],
                    })
                    await send({"type": "http.response.body", "body": body})
            return _unavailable

        return _prom_make_asgi_app(registry=self._registry)

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain-dict snapshot of current metric families (for tests/debug)."""
        if not _PROM_AVAILABLE or self._registry is None:
            return {}
        from prometheus_client.exposition import generate_latest  # noqa: PLC0415
        return {"text": generate_latest(self._registry).decode("utf-8")}


# ---------------------------------------------------------------------------
# Cloud Monitoring push (optional)
# ---------------------------------------------------------------------------


def push_to_cloud_monitoring(project_id: str, metrics_snapshot: Dict[str, Any]) -> None:
    """Push a ``custom.googleapis.com/credit_risk/p99_latency_ms`` time series.

    Guarded behind ``ENABLE_CLOUD_MONITORING=true``.  No-op when the flag is
    unset or when ``google-cloud-monitoring`` is not installed.

    Parameters
    ----------
    project_id:
        GCP project ID.
    metrics_snapshot:
        Dict containing at least ``p99_latency_ms`` (float) from
        ``_ServiceMetrics.snapshot()``.
    """
    if os.getenv("ENABLE_CLOUD_MONITORING", "false").lower() != "true":
        return

    try:
        from google.cloud import monitoring_v3  # noqa: PLC0415
        from google.protobuf import timestamp_pb2  # noqa: PLC0415
        import time as _time  # noqa: PLC0415
    except ImportError:
        logger.warning(
            "google-cloud-monitoring not installed — Cloud Monitoring push is disabled. "
            "Add google-cloud-monitoring>=2.20.0 to push metrics."
        )
        return

    try:
        client = monitoring_v3.MetricServiceClient()
        project_name = f"projects/{project_id}"

        series = monitoring_v3.TimeSeries()
        series.metric.type = "custom.googleapis.com/credit_risk/p99_latency_ms"
        series.resource.type = "global"

        now = _time.time()
        seconds = int(now)
        nanos = int((now - seconds) * 10 ** 9)
        interval = monitoring_v3.TimeInterval(
            {"end_time": {"seconds": seconds, "nanos": nanos}}
        )
        point = monitoring_v3.Point(
            {
                "interval": interval,
                "value": {"double_value": float(metrics_snapshot.get("p99_latency_ms", 0.0))},
            }
        )
        series.points = [point]

        client.create_time_series(name=project_name, time_series=[series])
        logger.info("Pushed p99_latency_ms=%.2f to Cloud Monitoring", metrics_snapshot.get("p99_latency_ms", 0))
    except Exception as exc:
        logger.error("Cloud Monitoring push failed: %s", exc)
