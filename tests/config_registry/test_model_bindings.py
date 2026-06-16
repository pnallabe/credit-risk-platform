"""
tests/config_registry/test_model_bindings.py
=============================================
Tests for PROMPT-04: Per-tenant model artefact URI overrides via config registry.

Coverage:
  * TenantConfigVersion.get_model_bindings() returns dict from config_json
  * get_model_bindings() returns empty dict when key absent
  * RiskModelingAgent applies pd_champion override before preload
  * RiskModelingAgent uses env-var defaults when no bindings provided
  * Invalid/missing local artefact raises FileNotFoundError at construction
  * CreditRiskPipeline.from_config() passes bindings when tenant has config
  * CreditRiskPipeline.from_config() uses defaults when tenant has no config
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from config_registry.models import TenantConfigVersion
from config_registry.service import ConfigRegistryService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(tmp_path):
    return ConfigRegistryService(db_url=str(tmp_path / "bindings_test.db"))


@pytest.fixture()
def tenant(svc):
    return svc.ensure_tenant("t-model-bindings", name="Model Binding Tenant")


# ---------------------------------------------------------------------------
# TenantConfigVersion.get_model_bindings()
# ---------------------------------------------------------------------------


class TestGetModelBindings:
    def test_returns_bindings_when_present(self):
        cfg = TenantConfigVersion(
            tenant_id="t1",
            config_version="v1",
            config_json={
                "model_bindings": {
                    "pd_champion": "/tmp/pd_v2.pkl",
                    "fraud_champion": "models:/fraud/Production",
                }
            },
            approved_by="admin",
            note="test",
        )
        bindings = cfg.get_model_bindings()
        assert bindings["pd_champion"] == "/tmp/pd_v2.pkl"
        assert bindings["fraud_champion"] == "models:/fraud/Production"

    def test_returns_empty_dict_when_absent(self):
        cfg = TenantConfigVersion(
            tenant_id="t1",
            config_version="v1",
            config_json={"policy_cutoffs": {"pd_threshold": 0.10}},
            approved_by="admin",
            note="test",
        )
        assert cfg.get_model_bindings() == {}

    def test_returns_empty_dict_on_empty_config(self):
        cfg = TenantConfigVersion(
            tenant_id="t1",
            config_version="v1",
            config_json={},
            approved_by="admin",
            note="test",
        )
        assert cfg.get_model_bindings() == {}

    def test_returns_all_supported_role_keys(self):
        expected_roles = {
            "pd_champion", "pd_challenger",
            "fraud_champion",
            "cc_val_champion", "cc_val_challenger",
            "cc_port_champion", "cc_port_challenger",
            "mort_champion", "mort_challenger",
        }
        role_bindings = {role: f"/tmp/{role}.pkl" for role in expected_roles}
        cfg = TenantConfigVersion(
            tenant_id="t1",
            config_version="v1",
            config_json={"model_bindings": role_bindings},
            approved_by="admin",
            note="test",
        )
        bindings = cfg.get_model_bindings()
        for role in expected_roles:
            assert role in bindings


# ---------------------------------------------------------------------------
# RiskModelingAgent — tenant model bindings
# ---------------------------------------------------------------------------


class TestRiskModelingAgentBindings:
    def test_uses_env_var_defaults_when_no_bindings(self):
        """When no tenant_model_bindings supplied, env-var paths are used."""
        from agents.risk_modeling_agent import RiskModelingAgent

        with patch.object(RiskModelingAgent, "_preload_agent_models"):
            agent = RiskModelingAgent(
                config={"credit_risk": {"champion_model_path": "/env/path/pd.pkl"}},
                tenant_model_bindings=None,
            )
            assert agent._champion_pd_path == "/env/path/pd.pkl"

    def test_applies_pd_champion_binding(self):
        """pd_champion binding overrides _champion_pd_path."""
        from agents.risk_modeling_agent import RiskModelingAgent

        bindings = {"pd_champion": "models:/credit_risk/Production"}
        with patch.object(RiskModelingAgent, "_preload_agent_models"):
            agent = RiskModelingAgent(
                config={"credit_risk": {"champion_model_path": "/env/path/pd.pkl"}},
                tenant_model_bindings=bindings,
            )
            assert agent._champion_pd_path == "models:/credit_risk/Production"

    def test_applies_fraud_champion_binding(self):
        """fraud_champion binding overrides _fraud_model_path."""
        from agents.risk_modeling_agent import RiskModelingAgent

        bindings = {"fraud_champion": "gs://my-bucket/fraud_v2.pkl"}
        with patch.object(RiskModelingAgent, "_preload_agent_models"):
            agent = RiskModelingAgent(
                config={},
                tenant_model_bindings=bindings,
            )
            assert agent._fraud_model_path == "gs://my-bucket/fraud_v2.pkl"

    def test_binding_applied_before_preload(self):
        """_apply_tenant_model_bindings must be called before _preload_agent_models."""
        from agents.risk_modeling_agent import RiskModelingAgent

        call_order = []

        with (
            patch.object(
                RiskModelingAgent,
                "_apply_tenant_model_bindings",
                side_effect=lambda b: call_order.append("apply"),
            ),
            patch.object(
                RiskModelingAgent,
                "_preload_agent_models",
                side_effect=lambda: call_order.append("preload"),
            ),
        ):
            # _MODELS_AVAILABLE must be True for preload to be called
            with patch("agents.risk_modeling_agent._MODELS_AVAILABLE", True):
                RiskModelingAgent(
                    config={},
                    tenant_model_bindings={"pd_champion": "gs://bucket/pd.pkl"},
                )

        assert call_order == ["apply", "preload"], (
            "Bindings must be applied before model preload"
        )

    def test_invalid_local_path_raises_file_not_found(self):
        """A local (non-URI) path that does not exist must raise FileNotFoundError."""
        from agents.risk_modeling_agent import RiskModelingAgent

        bindings = {"pd_champion": "/nonexistent/path/pd.pkl"}
        with patch.object(RiskModelingAgent, "_preload_agent_models"):
            with pytest.raises(FileNotFoundError, match="pd_champion"):
                RiskModelingAgent(config={}, tenant_model_bindings=bindings)

    def test_mlflow_uri_does_not_validate_path(self):
        """MLflow registry URIs (models:/) must NOT trigger local path validation."""
        from agents.risk_modeling_agent import RiskModelingAgent

        bindings = {"pd_champion": "models:/credit_risk/Production"}
        with patch.object(RiskModelingAgent, "_preload_agent_models"):
            # Should not raise
            agent = RiskModelingAgent(config={}, tenant_model_bindings=bindings)
            assert agent._champion_pd_path == "models:/credit_risk/Production"


# ---------------------------------------------------------------------------
# CreditRiskPipeline.from_config() — model binding integration
# ---------------------------------------------------------------------------


class TestPipelineModelBindings:
    def test_passes_bindings_when_tenant_has_config(self, svc, tenant):
        """from_config(tenant_id=...) must pass bindings to RiskModelingAgent."""
        from orchestration.pipeline import CreditRiskPipeline, _CONFIG_REGISTRY
        from agents.risk_modeling_agent import RiskModelingAgent

        mock_active = MagicMock()
        mock_active.get_model_bindings.return_value = {"pd_champion": "models:/pd/Production"}

        constructed_agents: list = []

        original_init = RiskModelingAgent.__init__

        def capture_init(self_, config=None, tenant_model_bindings=None):
            constructed_agents.append(tenant_model_bindings)
            # Don't call original to avoid preload
            self_.config = config or {}
            self_._champion_pd_path = None
            self_._challenger_pd_path = None
            self_._fraud_model_path = None
            self_._val_champion_path = None
            self_._val_challenger_path = None
            self_._port_champion_path = None
            self_._port_challenger_path = None
            self_._mort_champion_path = None
            self_._mort_challenger_path = None
            self_._pd_thresholds = {}
            self_._challenger_pct = 0.0
            self_._val_challenger_pct = 0.0
            self_._port_challenger_pct = 0.0
            self_._mort_challenger_pct = 0.0
            self_._log = __import__("logging").getLogger("test")
            self_.name = "RiskModelingAgent"

        mock_svc = MagicMock()
        mock_svc.get_active.return_value = mock_active

        with (
            patch("orchestration.pipeline._CONFIG_REGISTRY", mock_svc),
            patch.object(RiskModelingAgent, "__init__", capture_init),
        ):
            CreditRiskPipeline.from_config(tenant_id="t-model-bindings")

        assert len(constructed_agents) == 1
        assert constructed_agents[0] == {"pd_champion": "models:/pd/Production"}

    def test_uses_defaults_when_no_tenant_config(self):
        """from_config() without tenant_id must pass None bindings to RiskModelingAgent."""
        from orchestration.pipeline import CreditRiskPipeline
        from agents.risk_modeling_agent import RiskModelingAgent

        constructed_agents: list = []

        def capture_init(self_, config=None, tenant_model_bindings=None):
            constructed_agents.append(tenant_model_bindings)
            self_.config = config or {}
            self_._champion_pd_path = None
            self_._challenger_pd_path = None
            self_._fraud_model_path = None
            self_._val_champion_path = None
            self_._val_challenger_path = None
            self_._port_champion_path = None
            self_._port_challenger_path = None
            self_._mort_champion_path = None
            self_._mort_challenger_path = None
            self_._pd_thresholds = {}
            self_._challenger_pct = 0.0
            self_._val_challenger_pct = 0.0
            self_._port_challenger_pct = 0.0
            self_._mort_challenger_pct = 0.0
            self_._log = __import__("logging").getLogger("test")
            self_.name = "RiskModelingAgent"

        with patch.object(RiskModelingAgent, "__init__", capture_init):
            CreditRiskPipeline.from_config()  # no tenant_id

        # tenant_model_bindings should be None (empty) → uses env-var defaults
        assert constructed_agents[0] is None
