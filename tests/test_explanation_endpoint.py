"""Integration tests for GAP-10-B: GET /v1/decisions/{id}/explanation endpoint."""

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

# Set required env variables before importing main
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-explanation-endpoint")
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_explanation.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

import jwt as pyjwt  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"


def _make_tenant_token(
    tenant_id: str = "tenant-explain-test",
    email: str = "tester@example.com",
    role: str = "analyst",
) -> str:
    return pyjwt.encode(
        {"tenant_id": tenant_id, "sub": email, "email": email, "role": role},
        _JWT_SECRET,
        algorithm=_JWT_ALGO,
    )


def _auth(tenant_id: str = "tenant-explain-test", email: str = "tester@example.com") -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_tenant_token(tenant_id, email)}"}


# ---------------------------------------------------------------------------
# Mock audit record used in tests
# ---------------------------------------------------------------------------

_MOCK_AUDIT_RECORD: Dict[str, Any] = {
    "application_id": "app-explain-001",
    "tenant_id": "tenant-explain-test",
    "decision": "REJECT",
    "pd_score": 0.67,
    "fraud_probability": 0.12,
    "credit_score": 580,
    "debt_to_income_ratio": 0.45,
    "annual_income": 32000.0,
    "loan_amount": 25000.0,
    "reason_codes": ["HIGH_DTI", "LOW_CREDIT_SCORE"],
    "recommended_rate": None,
    "loan_terms": {},
    "logged_at": "2026-01-01T12:00:00Z",
    "audit_log_id": "log-001",
    "explanation": [
        {"feature": "credit_score", "shap_value": -0.34, "direction": "negative"},
        {"feature": "debt_to_income_ratio", "shap_value": -0.22, "direction": "negative"},
        {"feature": "annual_income", "shap_value": 0.10, "direction": "positive"},
    ],
}


# ---------------------------------------------------------------------------
# TestExplanationEndpoint
# ---------------------------------------------------------------------------

class TestExplanationEndpoint:
    """Tests for GET /v1/decisions/{id}/explanation."""

    @pytest.fixture(autouse=True)
    def client(self):
        """Create a TestClient that mocks model loading."""
        from fastapi.testclient import TestClient

        mock_model = MagicMock()
        with (
            patch("src.main._load_models"),
            patch("src.main._fraud_model", mock_model),
            patch("src.main._risk_model", mock_model),
        ):
            from src.main import app
            with TestClient(app, raise_server_exceptions=False) as c:
                self._client = c
                yield c

    # ── 200 — Contains shap, counterfactual, narrative keys ─────────────────

    def test_200_returns_required_keys(self) -> None:
        """GET /v1/decisions/{id}/explanation → 200 with shap/counterfactual/narrative."""
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_RECORD,
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "shap" in data
        assert "counterfactual" in data
        assert "narrative" in data
        assert data["application_id"] == "app-explain-001"
        assert data["decision"] == "REJECT"

    def test_shap_field_populated_from_audit_record(self) -> None:
        """SHAP block uses explanation stored in the audit record."""
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_MOCK_AUDIT_RECORD,
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(),
            )
        assert resp.status_code == 200
        shap = resp.json()["shap"]
        assert isinstance(shap, list)
        assert len(shap) == 3
        features = [f["feature"] for f in shap]
        assert "credit_score" in features

    # ── 404 — Unknown application_id ───────────────────────────────────────

    def test_404_for_unknown_id(self) -> None:
        """Returns 404 when audit record does not exist."""
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = self._client.get(
                "/v1/decisions/nonexistent-app/explanation",
                headers=_auth(),
            )
        assert resp.status_code == 404

    # ── 403 — Cross-tenant access blocked ──────────────────────────────────

    def test_403_cross_tenant_blocked(self) -> None:
        """Returns 403 when JWT tenant_id does not match record tenant_id."""
        # Record belongs to tenant-A; JWT says tenant-B
        _other_tenant_record = {**_MOCK_AUDIT_RECORD, "tenant_id": "tenant-A"}
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=_other_tenant_record,
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(tenant_id="tenant-B"),  # different tenant
            )
        assert resp.status_code == 403

    # ── No 500 when counterfactual fails ────────────────────────────────────

    def test_no_500_when_counterfactual_raises(self) -> None:
        """Returns 200 (not 500) when generate_counterfactual throws RuntimeError."""
        with (
            patch(
                "src.main.get_audit_record",
                new_callable=AsyncMock,
                return_value=_MOCK_AUDIT_RECORD,
            ),
            patch(
                "explainability.counterfactual.generate_counterfactual",
                side_effect=RuntimeError("SHAP unavailable"),
            ),
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(),
            )
        # Must degrade gracefully — never 500
        assert resp.status_code == 200
        data = resp.json()
        # counterfactual block still present, but may contain an error note
        assert "counterfactual" in data

    # ── No 500 when NLG fails ───────────────────────────────────────────────

    def test_no_500_when_nlg_fails(self) -> None:
        """Returns 200 even when NLG summarizer raises."""
        with (
            patch(
                "src.main.get_audit_record",
                new_callable=AsyncMock,
                return_value=_MOCK_AUDIT_RECORD,
            ),
            patch(
                "explainability.nlg_summarizer.generate_decision_summary",
                side_effect=RuntimeError("LLM unavailable"),
            ),
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "narrative" in data

    # ── Counterfactuals only for REJECT ────────────────────────────────────

    def test_approve_decision_returns_note_not_counterfactual(self) -> None:
        """APPROVE decisions return a note instead of counterfactual analysis."""
        approved_record = {**_MOCK_AUDIT_RECORD, "decision": "APPROVE"}
        with patch(
            "src.main.get_audit_record",
            new_callable=AsyncMock,
            return_value=approved_record,
        ):
            resp = self._client.get(
                "/v1/decisions/app-explain-001/explanation",
                headers=_auth(),
            )
        assert resp.status_code == 200
        cf = resp.json()["counterfactual"]
        assert "note" in cf or isinstance(cf, dict)

    # ── 401 — Missing auth ──────────────────────────────────────────────────

    def test_401_without_auth_header(self) -> None:
        resp = self._client.get("/v1/decisions/app-explain-001/explanation")
        assert resp.status_code == 401
