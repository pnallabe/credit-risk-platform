"""Integration tests for GAP-13-B: Borrower Portal API endpoints.

Covers:
- POST /v1/portal/token → returns borrower JWT
- GET /v1/portal/applications/{id}/status → 200 for valid borrower token
- GET /v1/portal/applications/{id}/status → 403 when app not in token's application_ids
- Tenant JWT on /v1/portal/ → 403 (wrong token_type)
- pd_score and fraud_probability NOT in status or explanation responses
- GET /v1/portal/applications/{id}/explanation → 200 and returns applicant_narrative
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent), str(DECISION_API_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("JWT_SECRET", "test-secret-key-for-portal")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret-for-portal")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_portal.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_BORROWER_SECRET = os.environ["BORROWER_JWT_SECRET"]
_JWT_ALGO = "HS256"

# ---------------------------------------------------------------------------
# Helper: Build tokens
# ---------------------------------------------------------------------------


def _make_tenant_token(
    tenant_id: str = "tenant-portal",
    email: str = "lender@example.com",
    role: str = "admin",
) -> str:
    return pyjwt.encode(
        {"tenant_id": tenant_id, "sub": email, "email": email, "role": role},
        _JWT_SECRET,
        algorithm=_JWT_ALGO,
    )


def _tenant_auth(tenant_id: str = "tenant-portal") -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_tenant_token(tenant_id)}"}


def _make_borrower_token(
    borrower_id: str = "borrower-001",
    tenant_id: str = "tenant-portal",
    application_ids: list = None,
) -> str:
    from datetime import datetime, timedelta, timezone
    if application_ids is None:
        application_ids = ["app-p-001"]
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=72)
    payload = {
        "borrower_id": borrower_id,
        "tenant_id": tenant_id,
        "application_ids": application_ids,
        "issued_at": now.isoformat(),
        "expires_at": exp.isoformat(),
        "token_type": "borrower",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return pyjwt.encode(payload, _BORROWER_SECRET, algorithm=_JWT_ALGO)


def _borrower_auth(
    borrower_id: str = "borrower-001",
    tenant_id: str = "tenant-portal",
    application_ids: list = None,
) -> Dict[str, str]:
    token = _make_borrower_token(borrower_id, tenant_id, application_ids)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Mock audit record
# ---------------------------------------------------------------------------

_MOCK_AUDIT_PORTAL: Dict[str, Any] = {
    "application_id": "app-p-001",
    "tenant_id": "tenant-portal",
    "decision": "REJECT",
    "pd_score": 0.72,
    "fraud_probability": 0.08,
    "recommended_rate": None,
    "loan_terms": {"amount": 10000, "term_months": 36},
    "reason_codes": ["HIGH_DTI", "LOW_CREDIT_SCORE"],
    "logged_at": "2026-01-01T10:00:00Z",
    "audit_log_id": "audit-portal-001",
    "explanation": [],
    "applicant_narrative": "Your application was declined due to high debt-to-income ratio.",
    "adverse_action_body": "...",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
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


# ---------------------------------------------------------------------------
# Tests: POST /v1/portal/token
# ---------------------------------------------------------------------------


class TestPortalTokenEndpoint:
    def test_issue_token_returns_200(self, client) -> None:
        resp = client.post(
            "/v1/portal/token",
            json={"borrower_id": "b-001", "application_ids": ["app-1", "app-2"]},
            headers=_tenant_auth(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["token_type"] == "borrower"

    def test_issue_token_requires_tenant_jwt(self, client) -> None:
        """Issuing a borrower token requires a valid tenant JWT."""
        resp = client.post(
            "/v1/portal/token",
            json={"borrower_id": "b-001", "application_ids": ["app-1"]},
        )
        assert resp.status_code == 401

    def test_issue_token_missing_borrower_id_returns_422(self, client) -> None:
        resp = client.post(
            "/v1/portal/token",
            json={"application_ids": ["app-1"]},  # missing borrower_id
            headers=_tenant_auth(),
        )
        assert resp.status_code == 422

    def test_issued_token_is_valid_borrower_jwt(self, client) -> None:
        """The issued token can be decoded as a valid borrower JWT."""
        resp = client.post(
            "/v1/portal/token",
            json={"borrower_id": "b-xyz", "application_ids": ["app-xyz"]},
            headers=_tenant_auth(),
        )
        assert resp.status_code == 200
        token = resp.json()["token"]
        payload = pyjwt.decode(token, _BORROWER_SECRET, algorithms=[_JWT_ALGO])
        assert payload["token_type"] == "borrower"
        assert payload["borrower_id"] == "b-xyz"


# ---------------------------------------------------------------------------
# Tests: GET /v1/portal/applications/{id}/status
# ---------------------------------------------------------------------------


class TestPortalApplicationStatus:
    def test_valid_borrower_token_returns_200(self, client) -> None:
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/status",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision"] is not None
        assert "application_id" in data

    def test_pd_score_not_in_status_response(self, client) -> None:
        """pd_score must NOT appear in the borrower portal status response."""
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/status",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert resp.status_code == 200
        assert "pd_score" not in resp.json()

    def test_fraud_probability_not_in_status_response(self, client) -> None:
        """fraud_probability must NOT appear in the borrower portal status response."""
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/status",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert resp.status_code == 200
        assert "fraud_probability" not in resp.json()

    def test_403_when_app_not_in_token_application_ids(self, client) -> None:
        """Application ID not in token's application_ids → 403."""
        resp = client.get(
            "/v1/portal/applications/app-p-999/status",  # not in ["app-p-001"]
            headers=_borrower_auth(application_ids=["app-p-001"]),
        )
        assert resp.status_code == 403

    def test_tenant_jwt_rejected_on_portal_status(self, client) -> None:
        """A tenant JWT (not borrower JWT) hitting /v1/portal/ → 403."""
        resp = client.get(
            "/v1/portal/applications/app-p-001/status",
            headers=_tenant_auth(),  # tenant JWT, NOT borrower JWT
        )
        # Should be 403 (wrong token_type) or 401
        assert resp.status_code in (401, 403)

    def test_403_cross_tenant_application(self, client) -> None:
        """Borrower token for tenant-A cannot access application of tenant-B."""
        other_tenant_record = {**_MOCK_AUDIT_PORTAL, "tenant_id": "other-tenant"}
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=other_tenant_record,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/status",
                headers=_borrower_auth(tenant_id="tenant-portal", application_ids=["app-p-001"]),
            )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Tests: GET /v1/portal/applications/{id}/explanation
# ---------------------------------------------------------------------------


class TestPortalApplicationExplanation:
    def test_explanation_returns_200(self, client) -> None:
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/explanation",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert resp.status_code == 200

    def test_explanation_contains_applicant_narrative(self, client) -> None:
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/explanation",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "applicant_narrative" in data
        assert data["applicant_narrative"] != ""

    def test_explanation_excludes_pd_score(self, client) -> None:
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/explanation",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert "pd_score" not in resp.json()

    def test_explanation_excludes_fraud_probability(self, client) -> None:
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_PORTAL,
        ):
            resp = client.get(
                "/v1/portal/applications/app-p-001/explanation",
                headers=_borrower_auth(application_ids=["app-p-001"]),
            )
        assert "fraud_probability" not in resp.json()

    def test_explanation_403_app_not_in_token(self, client) -> None:
        resp = client.get(
            "/v1/portal/applications/app-unlisted-999/explanation",
            headers=_borrower_auth(application_ids=["app-p-001"]),
        )
        assert resp.status_code == 403
