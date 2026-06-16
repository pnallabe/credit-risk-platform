"""
Tests for decision-api/src/main.py
===================================
Tests the FastAPI decision service using httpx AsyncClient.
All model calls use mock models to avoid requiring trained .pkl files.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# JWT auth setup — must happen before src.main is imported so the module-level
# JWT_SECRET check in main.py does not raise RuntimeError([CRIT-01]).
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET", "test-secret-pytest")  # nosec B105

import jwt as _jwt  # noqa: E402 – must be after sys.path setup


def _make_test_token(tenant_id: str = "test-tenant") -> str:
    """Return a signed HS256 JWT containing the required tenant_id claim."""
    return _jwt.encode(
        {"sub": "test-user", "tenant_id": tenant_id},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


# Reusable auth header injected into every TestClient fixture.
AUTH_HEADERS: Dict[str, str] = {"Authorization": f"Bearer {_make_test_token()}"}

# ---------------------------------------------------------------------------
# Mock models to avoid requiring .pkl files
# ---------------------------------------------------------------------------


def _make_mock_model(proba: float = 0.05):
    """Create a mock sklearn-style model returning fixed probabilities."""
    model = MagicMock()
    model.predict_proba = MagicMock(
        return_value=np.array([[1 - proba, proba]])
    )
    model.predict = MagicMock(return_value=np.array([1 if proba > 0.5 else 0]))
    return model


LOW_RISK_MODEL = _make_mock_model(proba=0.03)   # low PD → approve
HIGH_RISK_MODEL = _make_mock_model(proba=0.30)  # high PD → reject
FRAUD_MODEL_LOW = _make_mock_model(proba=0.05)   # low fraud → continue
FRAUD_MODEL_HIGH = _make_mock_model(proba=0.70)  # high fraud → reject


# ---------------------------------------------------------------------------
# App fixture with injected mock models
# ---------------------------------------------------------------------------


@pytest.fixture
def app_with_low_risk():
    """FastAPI test client with low-risk mock models."""
    import src.main as api_module

    api_module._fraud_model = FRAUD_MODEL_LOW
    api_module._risk_model = LOW_RISK_MODEL
    from src.main import app
    # Patch _load_models so startup completes (including _batch_semaphore init)
    # without trying to load missing .pkl files from disk.
    with patch("src.main._load_models"):
        with TestClient(app, headers=AUTH_HEADERS) as client:
            yield client


@pytest.fixture
def app_with_high_risk():
    """FastAPI test client with high-risk mock models."""
    import src.main as api_module

    api_module._fraud_model = _make_mock_model(proba=0.05)
    api_module._risk_model = HIGH_RISK_MODEL
    from src.main import app
    with patch("src.main._load_models"):
        with TestClient(app, headers=AUTH_HEADERS) as client:
            yield client


@pytest.fixture
def app_with_fraud():
    """FastAPI test client with fraud-triggering mock model."""
    import src.main as api_module

    api_module._fraud_model = FRAUD_MODEL_HIGH
    api_module._risk_model = LOW_RISK_MODEL
    from src.main import app
    with patch("src.main._load_models"):
        with TestClient(app, headers=AUTH_HEADERS) as client:
            yield client


# ---------------------------------------------------------------------------
# Sample payloads
# ---------------------------------------------------------------------------


LOW_RISK_PAYLOAD = {
    "application_id": "app-lr-001",
    "customer_id": "cust-001",
    "credit_score": 780,
    "annual_income": 120000.0,
    "employment_status": "employed",
    "employer_tenure_months": 48,
    "debt_to_income_ratio": 0.15,
    "existing_debt_amount": 5000.0,
    "loan_amount": 25000.0,
    "loan_purpose": "home_improvement",
    "loan_term_months": 36,
    "num_open_accounts": 5,
    "num_derogatory_marks": 0,
    "months_since_last_delinquency": None,
}

HIGH_RISK_PAYLOAD = {
    **LOW_RISK_PAYLOAD,
    "application_id": "app-hr-001",
    "credit_score": 490,
    "annual_income": 25000.0,
    "debt_to_income_ratio": 0.60,
    "existing_debt_amount": 40000.0,
    "loan_amount": 50000.0,
    "num_derogatory_marks": 5,
    "num_open_accounts": 0,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_returns_200(self, app_with_low_risk) -> None:
        response = app_with_low_risk.get("/v1/health")
        assert response.status_code == 200

    def test_health_has_model_info(self, app_with_low_risk) -> None:
        data = app_with_low_risk.get("/v1/health").json()
        assert "models" in data
        assert "fraud_detection" in data["models"]
        assert "credit_risk" in data["models"]

    def test_health_has_feature_pipeline(self, app_with_low_risk) -> None:
        data = app_with_low_risk.get("/v1/health").json()
        assert "feature_pipeline" in data
        assert "version" in data["feature_pipeline"]


class TestCreateDecision:
    def test_low_risk_returns_approve(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        assert resp.status_code in (200, 202)
        data = resp.json()
        assert data["decision"] == "APPROVE"

    def test_high_risk_returns_reject(self, app_with_high_risk) -> None:
        resp = app_with_high_risk.post("/v1/decisions", json=HIGH_RISK_PAYLOAD)
        data = resp.json()
        assert data["decision"] == "REJECT"

    def test_response_has_application_id(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        assert resp.json()["application_id"] == "app-lr-001"

    def test_response_has_audit_log_id(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        data = resp.json()
        assert "audit_log_id" in data
        assert len(data["audit_log_id"]) == 36  # UUID

    def test_response_has_pd_score(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        data = resp.json()
        assert "pd_score" in data
        assert 0.0 <= data["pd_score"] <= 1.0

    def test_response_has_fraud_probability(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        data = resp.json()
        assert "fraud_probability" in data
        assert 0.0 <= data["fraud_probability"] <= 1.0

    def test_approve_has_recommended_rate(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        data = resp.json()
        if data["decision"] == "APPROVE":
            assert data["recommended_rate"] is not None
            assert 5.0 <= data["recommended_rate"] <= 36.0

    def test_reject_has_reason_codes(self, app_with_high_risk) -> None:
        resp = app_with_high_risk.post("/v1/decisions", json=HIGH_RISK_PAYLOAD)
        data = resp.json()
        if data["decision"] == "REJECT":
            assert isinstance(data["reason_codes"], list)
            assert len(data["reason_codes"]) > 0

    def test_invalid_credit_score_returns_422(self, app_with_low_risk) -> None:
        bad_payload = {**LOW_RISK_PAYLOAD, "credit_score": 200}
        resp = app_with_low_risk.post("/v1/decisions", json=bad_payload)
        assert resp.status_code == 422

    def test_invalid_loan_amount_returns_422(self, app_with_low_risk) -> None:
        bad_payload = {**LOW_RISK_PAYLOAD, "loan_amount": 500.0}
        resp = app_with_low_risk.post("/v1/decisions", json=bad_payload)
        assert resp.status_code == 422

    def test_fraud_detection_high_prob(self, app_with_fraud) -> None:
        fraud_payload = {
            **LOW_RISK_PAYLOAD,
            "application_id": "app-fraud-001",
            "loan_amount": 100000.0,
            "annual_income": 5000.0,
            "num_open_accounts": 0,
            "employer_tenure_months": 0,
        }
        resp = app_with_fraud.post("/v1/decisions", json=fraud_payload)
        data = resp.json()
        # Fraud model returns >0.6 probability → reject
        assert data["decision"] in ("REJECT", "MANUAL_REVIEW")

    def test_decision_latency_ms_present(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions", json=LOW_RISK_PAYLOAD)
        data = resp.json()
        assert "decision_latency_ms" in data
        assert data["decision_latency_ms"] >= 0


class TestBatchDecisions:
    def test_batch_returns_correct_count(self, app_with_low_risk) -> None:
        payload = [LOW_RISK_PAYLOAD] * 3
        resp = app_with_low_risk.post("/v1/decisions/batch", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["batch_summary"]["total"] == 3
        assert len(data["results"]) == 3

    def test_batch_summary_counts_add_up(self, app_with_low_risk) -> None:
        payload = [LOW_RISK_PAYLOAD] * 4
        data = app_with_low_risk.post("/v1/decisions/batch", json=payload).json()
        summary = data["batch_summary"]
        assert summary["approved"] + summary["rejected"] + summary["manual_review"] == summary["total"]

    def test_batch_over_limit_returns_422(self, app_with_low_risk) -> None:
        payload = [LOW_RISK_PAYLOAD] * 1001
        resp = app_with_low_risk.post("/v1/decisions/batch", json=payload)
        assert resp.status_code == 422

    def test_empty_batch_returns_422(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.post("/v1/decisions/batch", json=[])
        assert resp.status_code == 422

    def test_batch_has_avg_latency(self, app_with_low_risk) -> None:
        payload = [LOW_RISK_PAYLOAD] * 2
        data = app_with_low_risk.post("/v1/decisions/batch", json=payload).json()
        assert "avg_latency_ms" in data["batch_summary"]


class TestAuditEndpoint:
    def test_audit_returns_404_for_unknown(self, app_with_low_risk) -> None:
        resp = app_with_low_risk.get("/v1/decisions/nonexistent-app-id/audit")
        assert resp.status_code == 404

    def test_audit_returns_record_after_decision(self, app_with_low_risk) -> None:
        # Submit a decision first
        unique_id = "app-audit-test-xyz"
        payload = {**LOW_RISK_PAYLOAD, "application_id": unique_id}
        app_with_low_risk.post("/v1/decisions", json=payload)
        # Retrieve audit record
        resp = app_with_low_risk.get(f"/v1/decisions/{unique_id}/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["application_id"] == unique_id

    def test_audit_record_has_required_fields(self, app_with_low_risk) -> None:
        unique_id = "app-audit-fields-test"
        payload = {**LOW_RISK_PAYLOAD, "application_id": unique_id}
        app_with_low_risk.post("/v1/decisions", json=payload)
        data = app_with_low_risk.get(f"/v1/decisions/{unique_id}/audit").json()
        required = {"application_id", "logged_at", "decision_output", "fraud_score", "risk_score"}
        for field in required:
            assert field in data, f"Missing field: {field}"
