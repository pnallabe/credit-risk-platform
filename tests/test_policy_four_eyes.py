"""Integration tests for GAP-11-B: Four-eyes policy config staging & approval endpoints.

Covers:
- POST /v1/config/stage + POST /v1/config/approve (two different users) → 200
- Approve with same email as author → 409
- Approve with wrong role → 403
- Reject staged config → 200, active config unchanged
- POST /v1/config without bypass header → 428
- POST /v1/config WITH bypass header → 201
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-four-eyes")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_four_eyes.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"

# ---------------------------------------------------------------------------
# Helper: JWT token builders
# ---------------------------------------------------------------------------


def _make_token(
    tenant_id: str = "tenant-four-eyes",
    email: str = "author@example.com",
    role: str = "analyst",
) -> str:
    return pyjwt.encode(
        {"tenant_id": tenant_id, "sub": email, "email": email, "role": role},
        _JWT_SECRET,
        algorithm=_JWT_ALGO,
    )


def _auth(tenant_id: str = "tenant-four-eyes", email: str = "author@example.com", role: str = "analyst"):
    return {"Authorization": f"Bearer {_make_token(tenant_id, email, role)}"}


def _cro_auth(tenant_id: str = "tenant-four-eyes", email: str = "cro@example.com"):
    return _auth(tenant_id, email, role="cro")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    """Create a TestClient with models mocked out."""
    mock_model = MagicMock()
    with (
        patch("src.main._load_models"),
        patch("src.main._fraud_model", mock_model),
        patch("src.main._risk_model", mock_model),
    ):
        from fastapi.testclient import TestClient
        from src.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture()
def staged_version_tag(client):
    """Stage a config as user A and return the version_tag."""
    resp = client.post(
        "/v1/config/stage",
        json={
            "config_json": {"policy_cutoffs": {"pd_threshold": 0.35}},
            "note": "New thresholds for Q1",
            "authored_by": "author@example.com",
        },
        headers=_auth(),
    )
    assert resp.status_code == 202, resp.text
    return resp.json()["version_tag"]


# ---------------------------------------------------------------------------
# Tests: Stage + Approve with different users
# ---------------------------------------------------------------------------


class TestFourEyesHappyPath:
    def test_stage_config_returns_202(self, client) -> None:
        resp = client.post(
            "/v1/config/stage",
            json={
                "config_json": {"policy_cutoffs": {"pd_threshold": 0.30}},
                "note": "New policy for Q2",
                "authored_by": "author@example.com",
            },
            headers=_auth(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "staged"

    def test_approve_with_different_email_returns_200(self, client, staged_version_tag) -> None:
        """User B (approver) can approve a config staged by User A."""
        resp = client.post(
            "/v1/config/approve",
            json={
                "approver_email": "cro@example.com",
                "note": "Looks good",
            },
            headers=_cro_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "active"


# ---------------------------------------------------------------------------
# Tests: Four-eyes violation (same actor == approver)
# ---------------------------------------------------------------------------


class TestFourEyesViolation:
    def test_same_actor_approver_returns_409(self, client) -> None:
        """If the approver_email matches the actor's JWT email → 409 Conflict."""
        # First stage something
        client.post(
            "/v1/config/stage",
            json={
                "config_json": {"policy_cutoffs": {"pd_threshold": 0.28}},
                "note": "Testing violation",
                "authored_by": "cro@example.com",
            },
            headers=_cro_auth(),
        )
        # Try to self-approve
        resp = client.post(
            "/v1/config/approve",
            json={
                "approver_email": "cro@example.com",  # same as JWT sub
                "note": "",
            },
            headers=_cro_auth(email="cro@example.com"),
        )
        assert resp.status_code == 409
        assert "four-eyes" in resp.json().get("detail", "").lower() or \
               "violation" in resp.json().get("detail", "").lower() or \
               "separation" in resp.json().get("detail", "").lower()

    def test_wrong_role_cannot_approve(self, client) -> None:
        """Non-CRO/compliance_officer role attempting approve → 403."""
        # Stage first
        client.post(
            "/v1/config/stage",
            json={
                "config_json": {"policy_cutoffs": {}},
                "note": "Wrong role test",
                "authored_by": "analyst@example.com",
            },
            headers=_auth(email="analyst@example.com", role="analyst"),
        )
        # Attempt approval with analyst role
        resp = client.post(
            "/v1/config/approve",
            json={"approver_email": "someone@example.com", "note": ""},
            headers=_auth(email="analyst@example.com", role="analyst"),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: Reject staged config
# ---------------------------------------------------------------------------


class TestRejectStagedConfig:
    def test_reject_staged_config_returns_200(self, client) -> None:
        # Stage
        client.post(
            "/v1/config/stage",
            json={
                "config_json": {"policy_cutoffs": {"pd_threshold": 0.99}},
                "note": "To be rejected",
                "authored_by": "cro@example.com",
            },
            headers=_cro_auth(),
        )
        # Reject
        resp = client.post(
            "/v1/config/reject",
            json={
                "rejected_by": "compliance@example.com",
                "reason": "Thresholds too permissive",
            },
            headers=_cro_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "rejected"

    def test_active_config_unchanged_after_reject(self, client) -> None:
        """Rejecting a staged config should not change active config."""
        # Get current active
        active_resp = client.get("/v1/config", headers=_cro_auth())
        if active_resp.status_code == 200:
            active_before = active_resp.json()
        else:
            active_before = None

        # Stage and reject
        client.post(
            "/v1/config/stage",
            json={"config_json": {"dummy": True}, "note": "staging", "authored_by": "cro@example.com"},
            headers=_cro_auth(),
        )
        client.post(
            "/v1/config/reject",
            json={"rejected_by": "other@example.com", "reason": "not needed"},
            headers=_cro_auth(),
        )

        # Active config should still be the same
        active_resp_after = client.get("/v1/config", headers=_cro_auth())
        if active_resp_after.status_code == 200 and active_before:
            assert active_resp_after.json().get("version_tag") == active_before.get("version_tag")


# ---------------------------------------------------------------------------
# Tests: X-Allow-Bypass-Four-Eyes header on POST /v1/config
# ---------------------------------------------------------------------------


class TestBypassHeader:
    def test_post_config_without_bypass_header_returns_428(self, client) -> None:
        """POST /v1/config without X-Allow-Bypass-Four-Eyes: true → HTTP 428."""
        resp = client.post(
            "/v1/config",
            json={"config_json": {"test": True}, "note": "bypass test"},
            headers=_auth(),  # no bypass header
        )
        assert resp.status_code == 428
        body = resp.json()
        assert "detail" in body
        detail_text = str(body["detail"])
        assert "X-Allow-Bypass-Four-Eyes" in detail_text or "bypass" in detail_text.lower()

    def test_post_config_with_bypass_header_returns_201(self, client) -> None:
        """POST /v1/config WITH X-Allow-Bypass-Four-Eyes: true → 201 (original behavior)."""
        headers = {
            **_auth(),
            "X-Allow-Bypass-Four-Eyes": "true",
        }
        resp = client.post(
            "/v1/config",
            json={"config_json": {"policy_cutoffs": {}}, "note": "bypass allowed"},
            headers=headers,
        )
        assert resp.status_code == 201

    def test_post_config_with_false_bypass_header_returns_428(self, client) -> None:
        """X-Allow-Bypass-Four-Eyes: false still blocks (not truthy string)."""
        headers = {
            **_auth(),
            "X-Allow-Bypass-Four-Eyes": "false",
        }
        resp = client.post(
            "/v1/config",
            json={"config_json": {}, "note": "should fail"},
            headers=headers,
        )
        assert resp.status_code == 428
