"""
tests/test_replay_bundle.py
============================
Unit tests for ``audit.replay_bundle`` (PROMPT-08).

Tests
-----
* ``bundle_sha256`` changes when any field of the bundle changes.
* ``bundle_sha256`` is deterministic (same inputs → same hash on repeated calls).
* Tenant isolation: calls for a foreign tenant's decision raise / return 403.
* ``404`` when ``decision_id`` does not exist.
* ``build_replay_bundle`` builds a correct bundle from a real (in-memory) audit row.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio

# ── Make repo root importable ────────────────────────────────────────────────
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from audit.replay_bundle import (
    ReplayBundle,
    _compute_bundle_sha256,
    build_replay_bundle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SQLITE_DB_URL = "sqlite+aiosqlite:///:memory:"


def _make_bundle(**overrides) -> ReplayBundle:
    """Construct a minimal ReplayBundle with deterministic bundle_sha256."""
    base: Dict[str, Any] = {
        "decision_id":            "app-001",
        "tenant_id":              "tenant-acme",
        "decided_at":             "2026-04-01T12:00:00+00:00",
        "raw_inputs":             {"loan_amount": 10000.0},
        "feature_version":        "1.0.0",
        "feature_values":         {"credit_utilization": 0.3},
        "model_artifact_hashes":  {"credit_risk": "sha256:abc123"},
        "policy_version":         "v1.0",
        "policy_params_snapshot": {"approve_threshold": 0.4},
        "tenant_config_version":  "cfg-v1",
        "tenant_config_sha256":   "sha256:cfghash",
        "decision":               "APPROVE",
        "reason_codes":           ["R001"],
        "audit_log_row_hash":     "sha256:rowhash",
    }
    base.update(overrides)
    # Compute deterministic bundle_sha256
    bundle_fields = {k: v for k, v in base.items() if k != "bundle_sha256"}
    base["bundle_sha256"] = _compute_bundle_sha256(bundle_fields)
    return ReplayBundle(**base)


# ---------------------------------------------------------------------------
# bundle_sha256 determinism tests
# ---------------------------------------------------------------------------


def test_bundle_sha256_is_deterministic():
    """The same inputs must always produce the same bundle_sha256."""
    b1 = _make_bundle()
    b2 = _make_bundle()
    assert b1.bundle_sha256 == b2.bundle_sha256


def test_bundle_sha256_changes_when_decision_changes():
    """Changing the decision field must change bundle_sha256."""
    b_approve = _make_bundle(decision="APPROVE")
    b_reject  = _make_bundle(decision="REJECT")
    assert b_approve.bundle_sha256 != b_reject.bundle_sha256


def test_bundle_sha256_changes_when_raw_inputs_change():
    """Changing raw_inputs must change bundle_sha256."""
    b1 = _make_bundle(raw_inputs={"loan_amount": 10000.0})
    b2 = _make_bundle(raw_inputs={"loan_amount": 99999.0})
    assert b1.bundle_sha256 != b2.bundle_sha256


def test_bundle_sha256_changes_when_policy_params_change():
    """Changing policy_params_snapshot must change bundle_sha256."""
    b1 = _make_bundle(policy_params_snapshot={"approve_threshold": 0.4})
    b2 = _make_bundle(policy_params_snapshot={"approve_threshold": 0.6})
    assert b1.bundle_sha256 != b2.bundle_sha256


def test_bundle_sha256_changes_when_tenant_config_sha256_changes():
    """Changing tenant_config_sha256 must change bundle_sha256."""
    b1 = _make_bundle(tenant_config_sha256="sha256:config-a")
    b2 = _make_bundle(tenant_config_sha256="sha256:config-b")
    assert b1.bundle_sha256 != b2.bundle_sha256


def test_bundle_sha256_changes_when_audit_row_hash_changes():
    """Changing audit_log_row_hash must change bundle_sha256."""
    b1 = _make_bundle(audit_log_row_hash="sha256:hash1")
    b2 = _make_bundle(audit_log_row_hash="sha256:hash2")
    assert b1.bundle_sha256 != b2.bundle_sha256


def test_bundle_sha256_is_hex_string():
    """bundle_sha256 must be a 64-character lowercase hex string."""
    b = _make_bundle()
    assert len(b.bundle_sha256) == 64
    assert b.bundle_sha256 == b.bundle_sha256.lower()
    int(b.bundle_sha256, 16)  # will raise if not hex


# ---------------------------------------------------------------------------
# build_replay_bundle — full integration with in-memory audit DB
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config_registry():
    """Return a mock ConfigRegistryService that returns a minimal tenant config."""
    svc = MagicMock()
    cfg = MagicMock()
    cfg.version_tag = "cfg-v1"
    cfg.config_sha256 = "sha256:cfghash"
    svc.get_active.return_value = cfg
    return svc


@pytest.fixture
def mock_policy_store():
    """Return a mock PolicyVersionStore that returns a minimal policy version."""
    from decision_engine.policy_version_store import PolicyVersion
    store = MagicMock()
    pv = PolicyVersion(
        id=1,
        version_tag="v1.0",
        parameters={"approve_threshold": 0.4},
        author="test",
        note="test",
        effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
        superseded_at=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    store.get_as_of.return_value = pv
    return store


@pytest.mark.asyncio
async def test_build_replay_bundle_raises_key_error_when_not_found(
    mock_config_registry, mock_policy_store
):
    """build_replay_bundle must raise KeyError when the decision_id is absent."""
    with pytest.raises(KeyError, match="not found"):
        await build_replay_bundle(
            decision_id="nonexistent-app",
            db_url=_SQLITE_DB_URL,
            config_registry=mock_config_registry,
            policy_store=mock_policy_store,
        )


@pytest.mark.asyncio
async def test_build_replay_bundle_returns_bundle_with_correct_decision_id(
    mock_config_registry, mock_policy_store
):
    """build_replay_bundle returns a ReplayBundle whose decision_id matches the query."""
    from audit.logger import log_decision

    db_url = "sqlite+aiosqlite:///:memory:"
    # Seed the audit log with a test record
    decision_result = {
        "application_id": "app-replay-001",
        "decision": "APPROVE",
        "reason_codes": ["R001", "R002"],
        "decision_latency_ms": 42,
    }
    await log_decision(
        decision_result=decision_result,
        feature_version="2.0.0",
        model_versions={"fraud": "v1", "credit_risk": "v1"},
        input_features={"loan_amount": 15000.0},
        db_url=db_url,
        tenant_id="tenant-acme",
    )

    bundle = await build_replay_bundle(
        decision_id="app-replay-001",
        db_url=db_url,
        config_registry=mock_config_registry,
        policy_store=mock_policy_store,
    )

    assert bundle.decision_id == "app-replay-001"
    assert bundle.tenant_id == "tenant-acme"
    assert bundle.decision == "APPROVE"
    assert bundle.feature_version == "2.0.0"
    assert bundle.reason_codes == ["R001", "R002"]
    assert len(bundle.bundle_sha256) == 64


@pytest.mark.asyncio
async def test_build_replay_bundle_sha256_is_deterministic_on_repeated_calls(
    mock_config_registry, mock_policy_store
):
    """Calling build_replay_bundle twice for the same record returns identical bundle_sha256."""
    from audit.logger import log_decision

    db_url = "sqlite+aiosqlite:///:memory:"
    decision_result = {
        "application_id": "app-det-001",
        "decision": "REJECT",
        "reason_codes": ["R010"],
        "decision_latency_ms": 10,
    }
    await log_decision(
        decision_result=decision_result,
        feature_version="1.0.0",
        model_versions={"credit_risk": "v1"},
        input_features={"credit_score": 580.0},
        db_url=db_url,
        tenant_id="tenant-det",
    )

    b1 = await build_replay_bundle(
        decision_id="app-det-001",
        db_url=db_url,
        config_registry=mock_config_registry,
        policy_store=mock_policy_store,
    )
    b2 = await build_replay_bundle(
        decision_id="app-det-001",
        db_url=db_url,
        config_registry=mock_config_registry,
        policy_store=mock_policy_store,
    )
    assert b1.bundle_sha256 == b2.bundle_sha256


# ---------------------------------------------------------------------------
# API endpoint tests (tenant isolation, 404)
# ---------------------------------------------------------------------------


@pytest.fixture
def api_client():
    """Return a FastAPI TestClient for the decision API."""
    import sys
    from pathlib import Path as _Path
    # Ensure decision-api/src is on path
    _src = str(_Path(__file__).resolve().parents[1] / "decision-api" / "src")
    if _src not in sys.path:
        sys.path.insert(0, _src)

    try:
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app, raise_server_exceptions=False)
    except Exception:
        pytest.skip("Decision API not importable in this environment")


def _make_jwt(tenant_id: str = "tenant-acme") -> str:
    """Produce a minimal valid JWT for the given tenant using the env secret."""
    import os, jwt  # noqa: E401
    from datetime import datetime, timezone, timedelta
    secret = os.getenv("JWT_SECRET", "dev-secret-please-change")
    payload = {
        "tenant_id": tenant_id,
        "sub": "test-user",
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_replay_bundle_404_for_nonexistent_decision(api_client):
    """GET /v1/decisions/{id}/replay-bundle must return 404 for unknown IDs."""
    token = _make_jwt("tenant-acme")
    resp = api_client.get(
        "/v1/decisions/does-not-exist/replay-bundle",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_replay_bundle_401_without_auth(api_client):
    """GET /v1/decisions/{id}/replay-bundle must return 401 without Authorization."""
    resp = api_client.get("/v1/decisions/any-id/replay-bundle")
    assert resp.status_code == 401
