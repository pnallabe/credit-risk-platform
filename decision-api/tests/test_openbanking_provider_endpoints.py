from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import jwt as _jwt
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ingestion-api" / "src"))

os.environ.setdefault("JWT_SECRET", "test-secret-pytest")


def _make_test_token(tenant_id: str = "test-tenant") -> str:
    return _jwt.encode(
        {"sub": "test-user", "tenant_id": tenant_id},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


AUTH_HEADERS = {"Authorization": f"Bearer {_make_test_token()}"}


@pytest.fixture
def app_client():
    import src.main as api_module

    from src.main import app

    with patch("src.main._load_models"):
        with TestClient(app, headers=AUTH_HEADERS) as client:
            yield client


def test_bank_enrich_obp_success(app_client, monkeypatch):
    from plaid_connector import BankDataSummary

    async def _fake_enrich(**kwargs):
        return BankDataSummary(
            application_id=kwargs["user_id"],
            provider="openbankproject",
            generated_at="2026-01-01T00:00:00Z",
            lookback_days=90,
            monthly_net_income=3200.0,
            monthly_gross_income_est=4096.0,
        )

    monkeypatch.setattr(
        "plaid_connector.enrich_with_cash_flow_data",
        _fake_enrich,
    )

    resp = app_client.post(
        "/v1/bank/enrich/app-obp-1",
        json={"access_token": "token-1", "provider": "openbankproject"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["application_id"] == "app-obp-1"
    assert body["provider"] == "openbankproject"


def test_bank_enrich_invalid_provider_returns_422(app_client):
    resp = app_client.post(
        "/v1/bank/enrich/app-1",
        json={"access_token": "token-1", "provider": "not-supported"},
    )
    assert resp.status_code == 422
    assert "Invalid provider" in resp.json()["detail"]


def test_bank_enrich_timeout_maps_to_504(app_client, monkeypatch):
    from plaid_connector import ProviderResponseError

    async def _fake_enrich(**kwargs):
        raise ProviderResponseError(
            provider="openbankproject",
            application_id=kwargs["user_id"],
            error_category="timeout",
            message="OBP timed out",
        )

    monkeypatch.setattr(
        "plaid_connector.enrich_with_cash_flow_data",
        _fake_enrich,
    )

    resp = app_client.post(
        "/v1/bank/enrich/app-timeout",
        json={"access_token": "token-1", "provider": "openbankproject"},
    )
    assert resp.status_code == 504


def test_bank_enrich_invalid_account_link_maps_to_400(app_client, monkeypatch):
    from plaid_connector import ProviderConfigurationError

    async def _fake_enrich(**kwargs):
        raise ProviderConfigurationError(
            provider="openbankproject",
            application_id=kwargs["user_id"],
            error_category="invalid_account_link",
            message="Invalid link",
        )

    monkeypatch.setattr(
        "plaid_connector.enrich_with_cash_flow_data",
        _fake_enrich,
    )

    resp = app_client.post(
        "/v1/bank/enrich/app-bad-link",
        json={"access_token": "token-1", "provider": "openbankproject"},
    )
    assert resp.status_code == 400
