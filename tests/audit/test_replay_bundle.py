"""
Smoke tests for audit/replay_bundle.py
"""
from __future__ import annotations

from audit.replay_bundle import ReplayBundle, _sha256_file


def _make_bundle(**kwargs) -> ReplayBundle:
    defaults = dict(
        decision_id="app-001",
        tenant_id="tenant-a",
        decided_at="2026-01-01T00:00:00+00:00",
        raw_inputs={"fico_score": 720, "annual_income": 80000},
        feature_version="v1.2.0",
        feature_values={"fico_score": 720, "dti": 0.35},
        model_artifact_hashes={"credit_risk": "sha256:abc123", "fraud": "sha256:def456"},
        policy_version="v10.0",
        policy_params_snapshot={"fico_floor": 620, "max_dti": 0.50},
        tenant_config_version="v2.1",
        tenant_config_sha256="sha256:aabbcc",
        decision="APPROVE",
        reason_codes=[],
        audit_log_row_hash="sha256:aabbccdd",
        bundle_sha256="sha256:deadbeef",
    )
    defaults.update(kwargs)
    return ReplayBundle(**defaults)


def test_replay_bundle_creation():
    bundle = _make_bundle()
    assert bundle.decision_id == "app-001"
    assert bundle.tenant_id == "tenant-a"
    assert bundle.decision == "APPROVE"
    assert bundle.feature_version == "v1.2.0"
    assert bundle.policy_version == "v10.0"


def test_replay_bundle_is_frozen():
    """ReplayBundle is frozen=True — fields are immutable."""
    bundle = _make_bundle()
    import pytest
    with pytest.raises((AttributeError, TypeError)):
        bundle.decision = "REJECT"  # type: ignore[misc]


def test_replay_bundle_reason_codes():
    bundle = _make_bundle(reason_codes=["AA04", "SHAP_CREDIT_SCORE"], decision="REJECT")
    assert "AA04" in bundle.reason_codes
    assert bundle.decision == "REJECT"


def test_sha256_file_missing_path():
    result = _sha256_file("/nonexistent/path/file.pkl")
    assert result == "sha256:unavailable"


def test_sha256_file_existing_file(tmp_path):
    f = tmp_path / "model.pkl"
    f.write_bytes(b"fake model data")
    result = _sha256_file(str(f))
    assert result.startswith("sha256:")
    assert len(result) == len("sha256:") + 64


def test_replay_bundle_model_artifact_hashes():
    bundle = _make_bundle(model_artifact_hashes={"credit_risk": "sha256:abc", "fraud": "sha256:def"})
    assert "credit_risk" in bundle.model_artifact_hashes
    assert bundle.model_artifact_hashes["fraud"] == "sha256:def"
