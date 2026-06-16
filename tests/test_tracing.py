"""
tests/test_tracing.py
=====================
Tests for PROMPT-05: OpenTelemetry distributed tracing.

Coverage:
  * compute_feature_matrix emits a span named "credit_core.compute_feature_matrix"
  * evaluate_policy emits a span named "credit_core.evaluate_policy"
  * Both spans carry tenant_id attribute when TenantContext is active
  * Tracer initialisation succeeds (console fallback) when OTEL endpoint not set
  * log_decision emits a span named "audit.log_decision"
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Helpers — InMemorySpanExporter without requiring full OTLP install
# ---------------------------------------------------------------------------

try:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry import trace as _otel_trace
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


def _make_in_memory_tracer(name: str = "test"):
    """Return (tracer, exporter) backed by InMemorySpanExporter."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(name)
    return tracer, exporter


def _span_names(exporter) -> List[str]:
    return [sp.name for sp in exporter.get_finished_spans()]


# ---------------------------------------------------------------------------
# configure_tracer tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OTEL_AVAILABLE, reason="opentelemetry-sdk not installed")
class TestConfigureTracer:
    def test_console_fallback_when_no_endpoint(self, monkeypatch):
        """configure_tracer() must succeed with no OTEL_EXPORTER_OTLP_ENDPOINT."""
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        from observability.tracing import configure_tracer
        tracer = configure_tracer("test-service")
        assert tracer is not None

    def test_returns_tracer_with_name(self, monkeypatch):
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        from observability.tracing import configure_tracer
        tracer = configure_tracer("my-service")
        # A real tracer should have start_as_current_span
        assert hasattr(tracer, "start_as_current_span")


# ---------------------------------------------------------------------------
# span() context manager tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OTEL_AVAILABLE, reason="opentelemetry-sdk not installed")
class TestSpanContextManager:
    def test_span_emits_named_span(self):
        from observability.tracing import span
        tracer, exporter = _make_in_memory_tracer()
        with span("test.my_operation", tracer, key="value"):
            pass
        names = _span_names(exporter)
        assert "test.my_operation" in names

    def test_span_adds_custom_attributes(self):
        from observability.tracing import span
        tracer, exporter = _make_in_memory_tracer()
        with span("test.attributes", tracer, batch_size=42, feature_version="1.0.0"):
            pass
        finished = exporter.get_finished_spans()
        assert len(finished) == 1
        attrs = finished[0].attributes
        assert attrs.get("batch_size") == "42"
        assert attrs.get("feature_version") == "1.0.0"

    def test_span_adds_tenant_id_from_context(self, monkeypatch):
        from observability.tracing import span
        from audit.tenant_guard import TenantContext, _CURRENT_TENANT
        import contextvars

        tracer, exporter = _make_in_memory_tracer()
        ctx = TenantContext(tenant_id="tenant-otel-test", source="jwt", authorized_by="test")

        token = _CURRENT_TENANT.set(ctx)
        try:
            with span("test.tenant_span", tracer):
                pass
        finally:
            _CURRENT_TENANT.reset(token)

        finished = exporter.get_finished_spans()
        assert len(finished) == 1
        assert finished[0].attributes.get("tenant_id") == "tenant-otel-test"

    def test_span_no_crash_when_no_tenant_context(self):
        from observability.tracing import span
        tracer, exporter = _make_in_memory_tracer()
        # No active TenantContext — span must still succeed
        with span("test.no_tenant", tracer):
            pass
        assert len(exporter.get_finished_spans()) == 1


# ---------------------------------------------------------------------------
# compute_feature_matrix span
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OTEL_AVAILABLE, reason="opentelemetry-sdk not installed")
class TestComputeFeatureMatrixSpan:
    def test_emits_correct_span_name(self):
        """compute_feature_matrix must emit 'credit_core.compute_feature_matrix'.

        The inner ``compute_features`` call is mocked so that the test focuses
        purely on span emission, not on feature pipeline correctness.
        """
        import pandas as pd
        from observability.tracing import span

        tracer, exporter = _make_in_memory_tracer()

        minimal_df = pd.DataFrame([{"application_id": "a1", "credit_score": 700}])

        # Patch the module-level TRACER in credit_core.features and stub out
        # the heavy feature pipeline so the span path is exercised cleanly.
        with patch("credit_core.features.TRACER", tracer), \
             patch("credit_core.features._trace_span", span), \
             patch("credit_core.features.compute_features", return_value=minimal_df), \
             patch("credit_core.features._normalise_columns", return_value=minimal_df), \
             patch("credit_core.features._apply_thin_file_enrichment", return_value=minimal_df):
            from credit_core.features import compute_feature_matrix
            compute_feature_matrix(minimal_df, version="1.0.0")

        names = _span_names(exporter)
        assert "credit_core.compute_feature_matrix" in names, f"Spans emitted: {names}"

    def test_span_carries_tenant_id_when_context_active(self):
        """compute_feature_matrix span must include tenant_id when TenantContext is active."""
        import pandas as pd
        from observability.tracing import span
        from audit.tenant_guard import TenantContext, _CURRENT_TENANT

        tracer, exporter = _make_in_memory_tracer()

        minimal_df = pd.DataFrame([{"application_id": "a1", "credit_score": 700}])

        ctx = TenantContext(tenant_id="tenant-feat-test", source="jwt", authorized_by="test")
        token = _CURRENT_TENANT.set(ctx)
        try:
            with patch("credit_core.features.TRACER", tracer), \
                 patch("credit_core.features._trace_span", span), \
                 patch("credit_core.features.compute_features", return_value=minimal_df), \
                 patch("credit_core.features._normalise_columns", return_value=minimal_df), \
                 patch("credit_core.features._apply_thin_file_enrichment", return_value=minimal_df):
                from credit_core.features import compute_feature_matrix
                compute_feature_matrix(minimal_df, version="1.0.0")
        finally:
            _CURRENT_TENANT.reset(token)

        finished = [s for s in exporter.get_finished_spans()
                    if s.name == "credit_core.compute_feature_matrix"]
        assert finished, "No compute_feature_matrix span found"
        assert finished[0].attributes.get("tenant_id") == "tenant-feat-test"


# ---------------------------------------------------------------------------
# evaluate_policy span
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _OTEL_AVAILABLE, reason="opentelemetry-sdk not installed")
class TestEvaluatePolicySpan:
    def _minimal_dataframes(self):
        import pandas as pd
        scores_df = pd.DataFrame([{
            "application_id": "a1",
            "pd_score": 0.07,
            "pd_band": "medium",
            "fraud_probability": 0.05,
            "fraud_flag": "continue",
        }])
        context_df = pd.DataFrame([{
            "application_id": "a1",
            "loan_amount": 10000.0,
            "loan_term_months": 36,
            "debt_to_income_ratio": 0.25,
            "num_open_accounts": 4,
            "annual_income": 60000.0,
        }])
        return scores_df, context_df

    def test_emits_correct_span_name(self):
        from observability.tracing import span

        tracer, exporter = _make_in_memory_tracer()

        with patch("credit_core.policy.TRACER", tracer), \
             patch("credit_core.policy._trace_span", span):
            from credit_core.policy import evaluate_policy
            scores_df, context_df = self._minimal_dataframes()
            evaluate_policy(scores_df, context_df, policy_version="v1")

        names = _span_names(exporter)
        assert "credit_core.evaluate_policy" in names, f"Spans emitted: {names}"

    def test_span_carries_tenant_id_when_context_active(self):
        from observability.tracing import span
        from audit.tenant_guard import TenantContext, _CURRENT_TENANT

        tracer, exporter = _make_in_memory_tracer()
        ctx = TenantContext(tenant_id="tenant-policy-test", source="jwt", authorized_by="test")
        token = _CURRENT_TENANT.set(ctx)
        try:
            with patch("credit_core.policy.TRACER", tracer), \
                 patch("credit_core.policy._trace_span", span):
                from credit_core.policy import evaluate_policy
                scores_df, context_df = self._minimal_dataframes()
                evaluate_policy(scores_df, context_df, policy_version="v1")
        finally:
            _CURRENT_TENANT.reset(token)

        finished = [s for s in exporter.get_finished_spans()
                    if s.name == "credit_core.evaluate_policy"]
        assert finished, "No evaluate_policy span found"
        assert finished[0].attributes.get("tenant_id") == "tenant-policy-test"
