"""
Tests for audit/replay_bundle.py — pure helpers + build_replay_bundle with SQLite.

Strategy:
- _sha256_file, _compute_bundle_sha256, _extract_model_paths are pure helpers
  tested directly.
- build_replay_bundle requires an audit_log record in SQLite, written via
  audit.logger.log_decision.  config_registry and policy_store are mocks with
  controlled return values (all wrapped in try/except inside the function).
"""
from __future__ import annotations

import json
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from audit.replay_bundle import (
    ReplayBundle,
    _sha256_file,
    _compute_bundle_sha256,
    _extract_model_paths,
    build_replay_bundle,
)

DB_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# _sha256_file
# ---------------------------------------------------------------------------

def test_sha256_file_missing_path():
    result = _sha256_file("/nonexistent/path/model.pkl")
    assert result == "sha256:unavailable"


def test_sha256_file_existing_file(tmp_path):
    f = tmp_path / "model.pkl"
    f.write_bytes(b"fake model weights")
    result = _sha256_file(str(f))
    assert result.startswith("sha256:")
    assert len(result) == 7 + 64  # "sha256:" + 64 hex chars


def test_sha256_file_deterministic(tmp_path):
    f = tmp_path / "model2.pkl"
    f.write_bytes(b"deterministic content")
    assert _sha256_file(str(f)) == _sha256_file(str(f))


def test_sha256_file_different_content_differs(tmp_path):
    f1 = tmp_path / "a.pkl"
    f2 = tmp_path / "b.pkl"
    f1.write_bytes(b"content A")
    f2.write_bytes(b"content B")
    assert _sha256_file(str(f1)) != _sha256_file(str(f2))


# ---------------------------------------------------------------------------
# _compute_bundle_sha256
# ---------------------------------------------------------------------------

def test_compute_bundle_sha256_returns_hex():
    fields = {"a": 1, "b": "hello", "c": [1, 2, 3]}
    result = _compute_bundle_sha256(fields)
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


def test_compute_bundle_sha256_is_deterministic():
    fields = {"decision": "APPROVE", "pd": 0.05, "tenant": "t-1"}
    assert _compute_bundle_sha256(fields) == _compute_bundle_sha256(fields)


def test_compute_bundle_sha256_changes_with_input():
    fields_a = {"x": 1}
    fields_b = {"x": 2}
    assert _compute_bundle_sha256(fields_a) != _compute_bundle_sha256(fields_b)


def test_compute_bundle_sha256_is_sorted():
    """Key ordering should not affect the digest."""
    f1 = {"a": 1, "b": 2}
    f2 = {"b": 2, "a": 1}
    assert _compute_bundle_sha256(f1) == _compute_bundle_sha256(f2)


def test_compute_bundle_sha256_manual():
    fields = {"decision": "APPROVE"}
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    expected = hashlib.sha256(canonical.encode()).hexdigest()
    assert _compute_bundle_sha256(fields) == expected


# ---------------------------------------------------------------------------
# _extract_model_paths
# ---------------------------------------------------------------------------

def test_extract_model_paths_empty_record():
    paths = _extract_model_paths({})
    assert "fraud" in paths
    assert "credit_risk" in paths


def test_extract_model_paths_with_model_version_dict():
    record = {"model_version": {"fraud": "v1.0", "credit_risk": "v2.0"}}
    paths = _extract_model_paths(record)
    assert "fraud" in paths
    assert "credit_risk" in paths


def test_extract_model_paths_with_model_version_json_string():
    record = {"model_version": '{"fraud": "v1.0"}'}
    paths = _extract_model_paths(record)
    assert "fraud" in paths


def test_extract_model_paths_with_bad_json_string():
    """Malformed JSON string → treated as empty dict, still returns default paths."""
    record = {"model_version": "{not valid json}"}
    paths = _extract_model_paths(record)
    assert isinstance(paths, dict)


def test_extract_model_paths_returns_strings():
    paths = _extract_model_paths({})
    for role, path in paths.items():
        assert isinstance(role, str)
        assert isinstance(path, str)


# ---------------------------------------------------------------------------
# build_replay_bundle — SQLite + mock config_registry / policy_store
# ---------------------------------------------------------------------------

class _MockPolicyStore:
    def get_as_of(self, dt):
        return SimpleNamespace(
            version_tag="v10.0",
            parameters={"pd_threshold": 0.10, "dti_high": 0.45},
        )


class _MockConfigRegistry:
    def get_active(self, tenant_id):
        return SimpleNamespace(
            version_tag="cfg-v1",
            config_sha256="sha256:aabb1122",
        )


class _FailingPolicyStore:
    def get_as_of(self, dt):
        raise RuntimeError("policy store unavailable")


class _FailingConfigRegistry:
    def get_active(self, tenant_id):
        raise RuntimeError("config registry unavailable")


async def _seed_audit_row(app_id: str, tenant_id: str) -> None:
    """Write a minimal audit_log row using audit.logger.log_decision."""
    from audit.logger import log_decision

    decision_result = {
        "application_id": app_id,
        "decision": "APPROVE",
        "reason_codes": ["AA04"],
        "decision_latency_ms": 45,
    }
    await log_decision(
        decision_result=decision_result,
        feature_version="v1.0",
        model_versions={
            "credit_risk": "v1.0",
            "fraud": "v1.0",
            "risk_score": 0.045,
            "fraud_score": 0.09,
        },
        input_features={"fico_score": 720, "annual_income": 80000},
        db_url=DB_URL,
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_build_replay_bundle_returns_bundle():
    app_id = "replay-001"
    tenant_id = "tenant-a"
    await _seed_audit_row(app_id, tenant_id)

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    assert isinstance(bundle, ReplayBundle)
    assert bundle.decision_id == app_id
    assert bundle.decision == "APPROVE"


@pytest.mark.asyncio
async def test_build_replay_bundle_has_valid_sha256():
    app_id = "replay-002"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    assert len(bundle.bundle_sha256) == 64


@pytest.mark.asyncio
async def test_build_replay_bundle_uses_policy_store():
    app_id = "replay-003"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    assert bundle.policy_version == "v10.0"
    assert bundle.policy_params_snapshot == {"pd_threshold": 0.10, "dti_high": 0.45}


@pytest.mark.asyncio
async def test_build_replay_bundle_uses_config_registry():
    app_id = "replay-004"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    assert bundle.tenant_config_version == "cfg-v1"
    assert bundle.tenant_config_sha256 == "sha256:aabb1122"


@pytest.mark.asyncio
async def test_build_replay_bundle_graceful_on_failing_policy_store():
    """Failing policy store → exception caught → unknown version fallback."""
    app_id = "replay-005"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_FailingPolicyStore(),
    )

    assert isinstance(bundle, ReplayBundle)
    # Policy version falls back to whatever was in the audit record
    assert bundle.policy_version is not None


@pytest.mark.asyncio
async def test_build_replay_bundle_graceful_on_failing_config_registry():
    """Failing config registry → exception caught → unknown config version."""
    app_id = "replay-006"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_FailingConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    assert isinstance(bundle, ReplayBundle)
    assert bundle.tenant_config_version == "unknown"


@pytest.mark.asyncio
async def test_build_replay_bundle_raises_key_error_for_missing_decision_id():
    """No matching row → KeyError raised."""
    with pytest.raises(KeyError, match="Audit record not found"):
        await build_replay_bundle(
            decision_id="nonexistent-app-999",
            db_url=DB_URL,
            config_registry=_MockConfigRegistry(),
            policy_store=_MockPolicyStore(),
        )


@pytest.mark.asyncio
async def test_build_replay_bundle_model_artifact_hashes():
    app_id = "replay-007"
    await _seed_audit_row(app_id, "tenant-a")

    bundle = await build_replay_bundle(
        decision_id=app_id,
        db_url=DB_URL,
        config_registry=_MockConfigRegistry(),
        policy_store=_MockPolicyStore(),
    )

    # Model paths may point to nonexistent files → sha256:unavailable
    assert isinstance(bundle.model_artifact_hashes, dict)
    for role, h in bundle.model_artifact_hashes.items():
        assert h.startswith("sha256:")
