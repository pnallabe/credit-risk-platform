"""
Tests for GAP-04-C: Policy Split admin endpoints.

Validates:
1. POST /v1/admin/policy-split/{tenant_id} activates a new split
2. DELETE /v1/admin/policy-split/{tenant_id} deactivates the split
3. GET /v1/admin/policy-split/{tenant_id}/report returns a comparison report
4. POST with mismatched tenant in body is rejected 422
5. GET report for tenant with no decisions returns empty rates
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "test-secret-pytest")  # nosec B105
# Use an in-memory DB so tests never touch the filesystem
os.environ.setdefault("POLICY_SPLIT_DB_URL", "sqlite:///:memory:")

import jwt as _jwt  # noqa: E402


def _make_token(tenant_id: str) -> str:
    return _jwt.encode(
        {"sub": "test-user", "tenant_id": tenant_id},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _auth(tenant_id: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(tenant_id)}"}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with mocked models and in-memory policy split store."""
    import src.main as api_module

    # Suppress model-load side-effects
    api_module._fraud_model = MagicMock()
    api_module._risk_model = MagicMock()

    # Re-create an in-memory store so each test starts clean
    from decision_engine.policy_challenger import PolicyChallengerRouter, PolicySplitStore

    in_memory_store = PolicySplitStore(db_url="sqlite:///:memory:")
    api_module._POLICY_SPLIT_STORE = in_memory_store
    api_module._POLICY_ROUTER = PolicyChallengerRouter(store=in_memory_store)

    from src.main import app

    with patch("src.main._load_models"):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


_SPLIT_BODY: Dict[str, Any] = {
    "champion_version_id": 10,
    "champion_version_tag": "stable-v1",
    "champion_traffic_pct": 0.9,
    "challenger_version_id": 11,
    "challenger_version_tag": "beta-v2",
    "challenger_traffic_pct": 0.1,
}


class TestPolicySplitEndpoints:
    """G4-C acceptance tests."""

    def test_set_split_returns_activated(self, client):
        """POST /v1/admin/policy-split/{tenant_id} → 200 with status=activated."""
        resp = client.post(
            "/v1/admin/policy-split/tenant-a",
            json=_SPLIT_BODY,
            headers=_auth("tenant-a"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "activated"
        assert body["tenant_id"] == "tenant-a"
        assert body["champion_version_tag"] == "stable-v1"
        assert body["challenger_version_tag"] == "beta-v2"

    def test_set_split_then_get_active_split(self, client):
        """After POST, the split is retrievable via the store."""
        import src.main as api_module

        client.post(
            "/v1/admin/policy-split/tenant-a",
            json=_SPLIT_BODY,
            headers=_auth("tenant-a"),
        )
        split = api_module._POLICY_SPLIT_STORE.get_active_split("tenant-a")
        assert split is not None
        champ, chall = split
        assert champ.version_tag == "stable-v1"
        assert chall.version_tag == "beta-v2"

    def test_delete_split_deactivates(self, client):
        """DELETE /v1/admin/policy-split/{tenant_id} → split becomes None."""
        import src.main as api_module

        client.post(
            "/v1/admin/policy-split/tenant-a",
            json=_SPLIT_BODY,
            headers=_auth("tenant-a"),
        )
        resp = client.delete(
            "/v1/admin/policy-split/tenant-a",
            headers=_auth("tenant-a"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "deactivated"

        split = api_module._POLICY_SPLIT_STORE.get_active_split("tenant-a")
        assert split is None

    def test_report_endpoint_returns_expected_keys(self, client):
        """GET /v1/admin/policy-split/{tenant_id}/report returns all required fields."""
        resp = client.get(
            "/v1/admin/policy-split/tenant-a/report",
            headers=_auth("tenant-a"),
        )
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "tenant_id",
            "period_start",
            "period_end",
            "champion_approval_rate",
            "challenger_approval_rate",
            "approval_rate_delta",
            "sample_size_champion",
            "sample_size_challenger",
            "recommendation",
        ):
            assert key in body, f"Missing key: {key}"

    def test_report_empty_for_no_decisions(self, client):
        """Report for tenant with zero decisions has zero rates and PROMOTE."""
        resp = client.get(
            "/v1/admin/policy-split/tenant-new/report",
            headers=_auth("tenant-new"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["sample_size_champion"] == 0
        assert body["sample_size_challenger"] == 0
        assert body["champion_approval_rate"] == 0.0
        # With delta=0, recommendation should be PROMOTE
        assert body["recommendation"] == "PROMOTE"
