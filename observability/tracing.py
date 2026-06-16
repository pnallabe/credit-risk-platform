"""
observability.tracing — OpenTelemetry SDK initialisation and span helpers
=========================================================================
Usage
-----
    from observability.tracing import TRACER, span

    with span("my_service.operation", TRACER, tenant_id="acme", rows=100):
        do_work()

Tracer initialisation
---------------------
The module-level ``TRACER`` singleton is created at import time using the
service name from ``OTEL_SERVICE_NAME`` (default ``"credit-risk-platform"``).

* If ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, spans are exported via OTLP HTTP.
* Otherwise, a ``ConsoleSpanExporter`` is used (zero-configuration fallback —
  no import errors when the OTLP endpoint is unreachable).

Standard attributes added to every span
-----------------------------------------
``service.name``, ``environment``, and ``tenant_id`` (read from
``audit.tenant_guard.TenantContext`` when a context is active).
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenTelemetry imports — graceful degradation if SDK not installed
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SimpleSpanProcessor,
    )
    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OTEL_AVAILABLE = False
    logger.warning(
        "opentelemetry-sdk not installed — tracing is a no-op. "
        "Add opentelemetry-sdk>=1.24.0 to requirements.txt."
    )


# ---------------------------------------------------------------------------
# Tracer factory
# ---------------------------------------------------------------------------

def configure_tracer(service_name: str) -> Any:
    """Initialise the OTel SDK and return a named Tracer.

    Parameters
    ----------
    service_name:
        Logical name for the service (e.g. ``"credit-risk-platform"``).

    Returns
    -------
    opentelemetry.trace.Tracer
        Live tracer when the SDK is available; a no-op tracer proxy otherwise.
    """
    if not _OTEL_AVAILABLE:
        return _NoOpTracer()

    provider = TracerProvider()

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # noqa: PLC0415
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            processor = BatchSpanProcessor(exporter)
            logger.info("OTel OTLP exporter configured: %s", otlp_endpoint)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OTel OTLP exporter unavailable (%s) — falling back to console", exc)
            processor = SimpleSpanProcessor(ConsoleSpanExporter())
    else:
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        logger.debug("OTel OTLP endpoint not set — using ConsoleSpanExporter")

    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


# ---------------------------------------------------------------------------
# span() context manager
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def span(name: str, tracer: Any, **attributes: Any):
    """Start an OTel span as a context manager, enriched with standard attributes.

    Automatically adds:
    - ``service.name`` from ``OTEL_SERVICE_NAME``
    - ``environment`` from ``ENVIRONMENT``
    - ``tenant_id`` from ``audit.tenant_guard.TenantContext`` (if active)
    - Any caller-supplied ``**attributes``

    Parameters
    ----------
    name:
        Span name, e.g. ``"credit_core.compute_feature_matrix"``.
    tracer:
        Tracer instance (from ``TRACER`` or ``configure_tracer()``).
    **attributes:
        Extra span attributes added to the span (e.g. ``rows=1000``).
    """
    if not _OTEL_AVAILABLE or isinstance(tracer, _NoOpTracer):
        yield
        return

    # Collect standard attributes
    std_attrs: dict[str, Any] = {
        "service.name": os.getenv("OTEL_SERVICE_NAME", "credit-risk-platform"),
        "environment": os.getenv("ENVIRONMENT", "dev"),
    }

    # Read tenant_id from TenantContext if one is active
    try:
        from audit.tenant_guard import _CURRENT_TENANT  # noqa: PLC0415
        ctx = _CURRENT_TENANT.get(None)
        if ctx is not None:
            std_attrs["tenant_id"] = ctx.tenant_id
    except Exception:  # noqa: BLE001
        pass  # TenantContext not available in this call path

    std_attrs.update(attributes)

    with tracer.start_as_current_span(name) as current_span:
        try:
            for k, v in std_attrs.items():
                current_span.set_attribute(k, str(v) if v is not None else "")
        except Exception:  # noqa: BLE001
            pass  # span attribute errors must never crash the application
        yield current_span


# ---------------------------------------------------------------------------
# No-op tracer (used when opentelemetry-sdk is not installed)
# ---------------------------------------------------------------------------

class _NoOpTracer:
    """Stub tracer that silently discards all spans."""

    def start_as_current_span(self, name: str, **_kwargs: Any) -> Any:
        return _NoOpSpan()

    def start_span(self, name: str, **_kwargs: Any) -> Any:
        return _NoOpSpan()


class _NoOpSpan:
    def __enter__(self) -> "_NoOpSpan":
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    def set_attribute(self, *_: Any) -> None:
        pass

    def record_exception(self, *_: Any) -> None:
        pass

    def set_status(self, *_: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

TRACER: Any = configure_tracer(os.getenv("OTEL_SERVICE_NAME", "credit-risk-platform"))
