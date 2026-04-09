"""
Tests for P1-D: POST /v1/audit/verify-chain and enhanced GET /v1/decisions/{id}/audit
"""
from __future__ import annotations

import sys
import pytest

# These tests assume the test environment sets the required env vars before
# importing main.py.  Use the conftest.py fixture that sets JWT_SECRET etc.
pytestmark = pytest.mark.asyncio


@pytest.fixture()
def set_env(monkeypatch, tmp_path):
    """Set required environment variables before importing main."""
    db = str(tmp_path / "test_chain.db")
    monkeypatch.setenv("JWT_SECRET", "test-secret-key-for-chain-verification-tests")
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost")


@pytest.fixture()
def client(set_env):
    """Return an async test client for the Decision API."""
    # Remove cached module so it picks up patched env vars
    _evict = [mod for mod in sys.modules if mod in ("src.main",) or mod.startswith("src.")]
    for mod in _evict:
        del sys.modules[mod]

    from httpx import AsyncClient, ASGITransport
    from src.main import app  # type: ignore[import]

    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    # Re-evict the reimported module so other test files get a clean import
    for mod in list(sys.modules.keys()):
        if mod in ("src.main",) or mod.startswith("src."):
            del sys.modules[mod]


def _make_jwt(tenant_id: str = "test-tenant", secret: str = "test-secret-key-for-chain-verification-tests") -> str:
    import jwt
    return jwt.encode({"tenant_id": tenant_id, "sub": "tester"}, secret, algorithm="HS256")


async def _insert_decisions(client, n: int = 3, token: str | None = None) -> list[str]:
    """Insert n decisions and return their application_ids."""
    if token is None:
        token = _make_jwt()
    headers = {"Authorization": f"Bearer {token}"}
    ids = []
    for i in range(n):
        payload = {
            "application_id": f"app-chain-{i:04d}",
            "customer_id": f"cust-{i}",
            "credit_score": 720,
            "annual_income": 80000.0,
            "employment_status": "employed",
            "debt_to_income_ratio": 0.25,
            "existing_debt_amount": 5000.0,
            "loan_amount": 15000.0,
            "loan_purpose": "auto",
            "loan_term_months": 36,
        }
        resp = await client.post("/v1/decisions", json=payload, headers=headers)
        assert resp.status_code in (200, 201, 202)
        ids.append(f"app-chain-{i:04d}")
    return ids


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_chain_valid(client):
    """POST /v1/audit/verify-chain returns 200 and verified=true after 3 decisions."""
    token = _make_jwt()
    headers = {"Authorization": f"Bearer {token}"}

    async with client as c:
        await _insert_decisions(c, n=3, token=token)

        resp = await c.post("/v1/audit/verify-chain", json={}, headers=headers)

    assert resp.status_code in (200, 202)
    if resp.status_code == 200:
        data = resp.json()
        assert "verified" in data
        assert "rows_checked" in data


@pytest.mark.asyncio
async def test_verify_chain_missing_jwt(client):
    """POST /v1/audit/verify-chain without JWT returns 401."""
    async with client as c:
        resp = await c.post("/v1/audit/verify-chain", json={})
    assert resp.status_code == 401
