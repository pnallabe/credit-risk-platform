"""
Tests for GAP-03-A: tenant_id mandatory guard in CreditRiskPipeline.run()
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from agents.base import AgentResult, AgentStatus
from orchestration.pipeline import CreditRiskPipeline, PipelineRun


# ---------------------------------------------------------------------------
# Helper: build a minimal pipeline with all agents mocked
# ---------------------------------------------------------------------------

def _make_mock_agent(payload: Dict[str, Any]) -> MagicMock:
    """Return a mock agent whose execute() returns a successful AgentResult."""
    agent = MagicMock()
    result = AgentResult(
        agent_name="mock",
        status=AgentStatus.SUCCESS,
        payload=payload,
        duration_seconds=0.001,
        errors=[],
        warnings=[],
    )
    agent.execute.return_value = result
    return agent


def _make_pipeline() -> CreditRiskPipeline:
    """Build a CreditRiskPipeline where every agent is mocked to succeed."""
    ingestion_payload = {
        "validated": [{"application_id": "app-001", "credit_score": 700}],
        "quarantined": [],
        "stats": {"total": 1, "valid": 1, "quarantined": 0},
    }
    feature_payload = {
        "feature_df": MagicMock(),
        "feature_vectors": [{"credit_score": 700}],
        "feature_version": "v1",
    }
    model_payload = {
        "model_scores": [{"pd_score": 0.05}],
        "model_version": "v1",
    }
    decision_payload = {
        "decisions": [{"decision": "APPROVE"}],
        "stats": {"approved": 1, "rejected": 0, "manual_review": 0},
    }
    explain_payload = {
        "explanations": [{"shap_values": {}}],
        "adverse_action_notices": [],
    }

    pipeline = CreditRiskPipeline(
        ingestion_agent=_make_mock_agent(ingestion_payload),
        feature_agent=_make_mock_agent(feature_payload),
        modeling_agent=_make_mock_agent(model_payload),
        decision_agent=_make_mock_agent(decision_payload),
        explain_agent=_make_mock_agent(explain_payload),
        monitoring_agent=None,
        experimentation_agent=None,
        bq_writer_agent=None,
    )
    return pipeline


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineTenantGuard:
    """G3-A acceptance tests: tenant_id mandatory guard."""

    def test_empty_string_tenant_id_raises_value_error(self) -> None:
        """Calling run() with tenant_id="" raises ValueError."""
        pipeline = _make_pipeline()
        with pytest.raises(ValueError, match="tenant_id is required"):
            pipeline.run(applicant_dicts=[{"application_id": "app-001"}], tenant_id="")

    def test_whitespace_only_tenant_id_raises_value_error(self) -> None:
        """Calling run() with tenant_id='   ' raises ValueError."""
        pipeline = _make_pipeline()
        with pytest.raises(ValueError, match="tenant_id is required"):
            pipeline.run(applicant_dicts=[{"application_id": "app-001"}], tenant_id="   ")

    def test_missing_tenant_id_raises_type_error(self) -> None:
        """Calling run() without tenant_id raises TypeError from Python's argument binding."""
        pipeline = _make_pipeline()
        with pytest.raises(TypeError):
            pipeline.run(applicant_dicts=[{"application_id": "app-001"}])  # type: ignore[call-arg]

    @patch("orchestration.pipeline._CONFIG_REGISTRY")
    def test_valid_tenant_id_in_to_dict(self, mock_registry: MagicMock) -> None:
        """run() returns a PipelineRun whose to_dict()['tenant_id'] matches the input."""
        mock_registry.resolve.return_value = {}
        pipeline = _make_pipeline()
        result = pipeline.run(
            applicant_dicts=[{"application_id": "app-001"}],
            tenant_id="tenant-abc",
        )
        assert isinstance(result, PipelineRun)
        assert result.to_dict()["tenant_id"] == "tenant-abc"

    @patch("orchestration.pipeline._CONFIG_REGISTRY")
    def test_valid_tenant_id_on_pipeline_run_object(self, mock_registry: MagicMock) -> None:
        """The returned PipelineRun.tenant_id field equals the passed tenant_id."""
        mock_registry.resolve.return_value = {}
        pipeline = _make_pipeline()
        result = pipeline.run(
            applicant_dicts=[{"application_id": "app-001"}],
            tenant_id="tenant-abc",
        )
        assert result.tenant_id == "tenant-abc"

    def test_from_config_stores_default_tenant_id(self) -> None:
        """from_config() stores default_tenant_id on the instance when present in YAML."""
        import yaml
        import tempfile
        import os

        cfg = {
            "default_tenant_id": "platform-default",
            "data_ingestion": {},
            "feature_engineering": {},
            "risk_modeling": {},
            "decision_engine": {},
            "explainability": {},
            "monitoring": {},
            "experimentation": {},
            "bigquery": {"enabled": False},
            "orchestration": {},
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(cfg, f)
            tmp_path = f.name

        try:
            with patch("orchestration.pipeline.BQWriterAgent"):
                pipeline = CreditRiskPipeline.from_config(config_path=tmp_path)
            assert pipeline._default_tenant_id == "platform-default"
        finally:
            os.unlink(tmp_path)
