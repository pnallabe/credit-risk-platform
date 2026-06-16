"""
Tests for GAP-03-B: Application-layer tenant re-verification on audit record reads.

Validates:
1. JWT tenant-a + record tenant-a → 200
2. JWT tenant-a + record tenant-b (DB bypass simulated) → 403
3. Non-existent record → 404
4. 403 path emits WARNING log containing "SECURITY"
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "test-secret-pytest")  # nosec B105

import jwt as _jwt  # noqa: E402


def _make_token(tenant_id: str) -> str:
    return _jwt.encode(
        {"sub": "user", "tenant_id": tenant_id},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _auth(tenant_id: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(tenant_id)}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """TestClient with models pre-loaded (mocked) to bypass startup checks."""
    import src.main as api_module

    # Suppress model-load side-effects
    api_module._fraud_model = MagicMock()
    api_module._risk_model = MagicMock()

    from src.main import app

    with patch("src.main._load_models"):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTenantIsolationAuditEndpoint:
    """G3-B acceptance tests."""

    # Record owned by tenant-a
    _RECORD_TENANT_A: Dict[str, Any] = {
        "log_id": "log-001",
        "tenant_id": "tenant-a",
        "application_id": "app-001",
        "decision_output": "APPROVE",
        "logged_at": "2026-04-07T00:00:00",
        "record_hash": "abc123",
        "previous_hash": None,
        "hash_algorithm": "SHA-256",
    }

    def test_correct_tenant_gets_200(self, client: TestClient) -> None:
        """JWT tenant-a + record owned by tenant-a → 200 OK."""
        # The chain integrity check uses a local import inside the endpoint; if it fails,
        # the endpoint swallows the exception and still returns the record. So patch only
        # get_audit_record and let the chain check be handled gracefully.
        with patch(
            "src.main.get_audit_record",
            new=AsyncMock(return_value=self._RECORD_TENANT_A),
        ):
            response = client.get("/v1/decisions/app-001/audit", headers=_auth("tenant-a"))
        assert response.status_code == 200

    def test_cross_tenant_bypass_returns_403(self, client: TestClient) -> None:
        """JWT tenant-a + DB mistakenly returns record owned by tenant-b → 403."""
        wrong_tenant_record = {**self._RECORD_TENANT_A, "tenant_id": "tenant-b"}
        with patch(
            "src.main.get_audit_record",
            new=AsyncMock(return_value=wrong_tenant_record),
        ):
            response = client.get("/v1/decisions/app-001/audit", headers=_auth("tenant-a"))
        assert response.status_code == 403
        assert "Forbidden" in response.json()["detail"]

    def test_missing_record_returns_404(self, client: TestClient) -> None:
        """Non-existent record (get_audit_record returns None) → 404."""
        with patch(
            "src.main.get_audit_record",
            new=AsyncMock(return_value=None),
        ):
            response = client.get("/v1/decisions/nonexistent/audit", headers=_auth("tenant-a"))
        assert response.status_code == 404

    def test_cross_tenant_logs_security_warning(
        self, client: TestClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cross-tenant mismatch must emit a WARNING log containing 'SECURITY'."""
        wrong_tenant_record = {**self._RECORD_TENANT_A, "tenant_id": "tenant-b"}
        with caplog.at_level(logging.WARNING, logger="src.main"):
            with patch(
                "src.main.get_audit_record",
                new=AsyncMock(return_value=wrong_tenant_record),
            ):
                client.get("/v1/decisions/app-001/audit", headers=_auth("tenant-a"))
        assert any("SECURITY" in r.message for r in caplog.records)
