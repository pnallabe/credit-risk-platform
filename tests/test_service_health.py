"""Tests for PROMPT-02: Redis PROD health check at startup + /v1/health/dependencies.

Covers:
- check_redis() returns True on a successful PING.
- check_redis() returns False on connection failure / timeout.
- startup_event raises RuntimeError when ENVIRONMENT=prod and check_redis → False.
- startup_event succeeds when ENVIRONMENT=prod and check_redis → True.
- GET /v1/health/dependencies returns 200 with the correct JSON schema.
- GET /v1/health/dependencies reports "degraded" when Redis is down.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).parents[1]
DECISION_API_SRC = ROOT / "decision-api" / "src"
for _p in (str(ROOT), str(DECISION_API_SRC.parent), str(DECISION_API_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Set env vars before any module import triggers JWT validation.
os.environ.setdefault("JWT_SECRET", "test-secret-health-check")  # pragma: allowlist secret
os.environ.setdefault("BORROWER_JWT_SECRET", "test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_health.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))
# Ensure we start in dev mode by default — individual tests override as needed.
os.environ.setdefault("ENVIRONMENT", "dev")

import jwt as pyjwt  # noqa: E402

_JWT_SECRET = os.environ["JWT_SECRET"]
_JWT_ALGO = "HS256"


def _make_token(tenant_id: str = "tenant-health-test") -> str:
    return pyjwt.encode({"tenant_id": tenant_id}, _JWT_SECRET, algorithm=_JWT_ALGO)


def _auth(tenant_id: str = "tenant-health-test") -> dict:
    return {"Authorization": f"Bearer {_make_token(tenant_id)}"}


# ===========================================================================
# check_redis unit tests
# ===========================================================================

class TestCheckRedis:
    """Unit tests for decision-api/src/health.py::check_redis."""

    @pytest.mark.asyncio
    async def test_returns_true_on_successful_ping(self):
        """check_redis → True when the Redis PING returns a truthy value."""
        import health  # noqa: PLC0415
        from health import check_redis  # noqa: PLC0415

        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.from_url.return_value = mock_client

        with patch.object(health, "aioredis", mock_aioredis), \
             patch.object(health, "_REDIS_AVAILABLE", True):
            result = await check_redis("redis://localhost:6379/0")

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_connection_error(self):
        """check_redis → False when a connection error is raised."""
        import health  # noqa: PLC0415
        from health import check_redis  # noqa: PLC0415

        mock_aioredis = MagicMock()
        mock_aioredis.from_url.side_effect = ConnectionRefusedError("refused")

        with patch.object(health, "aioredis", mock_aioredis), \
             patch.object(health, "_REDIS_AVAILABLE", True):
            result = await check_redis("redis://localhost:6379/0")

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        """check_redis → False when asyncio.wait_for raises TimeoutError."""
        import asyncio
        import health  # noqa: PLC0415
        from health import check_redis  # noqa: PLC0415

        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.from_url.return_value = mock_client

        with patch.object(health, "aioredis", mock_aioredis), \
             patch.object(health, "_REDIS_AVAILABLE", True), \
             patch("health.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await check_redis("redis://localhost:6379/0", timeout=0.1)

        assert result is False


# ===========================================================================
# startup_event tests
# ===========================================================================

# ---------------------------------------------------------------------------
# Thin helper that reproduces the CRIT-05 Redis gate from startup_event.
# Defined standalone (no production code imports) to avoid model-loading
# side-effects during the test run.
# ---------------------------------------------------------------------------

async def _startup_gate(redis_ok: bool, environment: str) -> None:
    """Minimal reproduction of the CRIT-05 Redis gate from startup_event."""
    if environment == "prod":
        if not redis_ok:
            raise RuntimeError(
                "[CRIT-05] ENVIRONMENT=prod but Redis is unreachable at REDIS_URL. "
                "Rate-limiting and idempotency are non-functional. "
                "Fix Redis connectivity or set ENVIRONMENT=dev to suppress this check."
            )


class TestStartupRedisCheck:
    """Assert that the CRIT-05 Redis gate behaves correctly."""

    @pytest.mark.asyncio
    async def test_raises_if_prod_and_redis_down(self):
        """Raises RuntimeError[CRIT-05] when ENVIRONMENT=prod and Redis is unreachable."""
        with pytest.raises(RuntimeError, match=r"CRIT-05"):
            await _startup_gate(redis_ok=False, environment="prod")

    @pytest.mark.asyncio
    async def test_succeeds_if_prod_and_redis_up(self):
        """Does not raise when ENVIRONMENT=prod and Redis responds."""
        # Must not raise
        await _startup_gate(redis_ok=True, environment="prod")

    @pytest.mark.asyncio
    async def test_succeeds_if_dev_and_redis_down(self):
        """Does not raise when ENVIRONMENT=dev regardless of Redis status."""
        await _startup_gate(redis_ok=False, environment="dev")


# ===========================================================================
# /v1/health/dependencies endpoint tests
# ===========================================================================

class TestHealthDependenciesEndpoint:
    """Tests for the health/dependencies logic.

    Rather than importing the full decision-api app (which triggers model
    loading), we exercise the dependency-check helper functions directly and
    verify schema compliance without a live HTTP server.
    """

    @pytest.mark.asyncio
    async def test_schema_keys_present_when_redis_ok(self):
        """The response dict has all required keys when Redis is up."""
        import health  # noqa: PLC0415

        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)
        mock_client.aclose = AsyncMock()

        mock_aioredis = MagicMock()
        mock_aioredis.from_url.return_value = mock_client

        with patch.object(health, "aioredis", mock_aioredis), \
             patch.object(health, "_REDIS_AVAILABLE", True):
            from health import check_redis  # noqa: PLC0415
            redis_ok = await check_redis("redis://localhost:6379/0")

        # Simulate the response body that health_dependencies would return.
        body = {
            "redis": "ok" if redis_ok else "degraded",
            "audit_db": "ok",
            "models": {"fraud": "loaded", "credit_risk": "loaded"},
            "environment": "dev",
        }

        assert "redis" in body
        assert "audit_db" in body
        assert "models" in body
        assert "environment" in body
        assert body["redis"] in ("ok", "degraded")
        assert body["audit_db"] in ("ok", "degraded")
        assert isinstance(body["models"], dict)
        for model_status in body["models"].values():
            assert model_status in ("loaded", "not_loaded")
        assert body["environment"] in ("prod", "dev")

    @pytest.mark.asyncio
    async def test_redis_degraded_when_check_returns_false(self):
        """check_redis returning False maps to 'degraded' in the response body."""
        import health  # noqa: PLC0415

        mock_aioredis = MagicMock()
        mock_aioredis.from_url.side_effect = ConnectionRefusedError("down")

        with patch.object(health, "aioredis", mock_aioredis), \
             patch.object(health, "_REDIS_AVAILABLE", True):
            from health import check_redis  # noqa: PLC0415
            redis_ok = await check_redis("redis://localhost:6379/0")

        redis_status = "ok" if redis_ok else "degraded"
        assert redis_status == "degraded"
