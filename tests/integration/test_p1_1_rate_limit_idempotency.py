"""
P1.1 — Rate Limiting + Idempotency Integration Tests
=======================================================
Tests use a mocked Redis client so they run without a live Redis server.

Coverage
--------
* RateLimitMiddleware — allows requests within quota, rejects when over limit
* RateLimitMiddleware — different tenants have independent quotas
* IdempotencyMiddleware — same Idempotency-Key does not re-execute pipeline
* IdempotencyMiddleware — absent key passes through normally
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make project root importable
ROOT = Path(__file__).parents[2]
SRC = ROOT / "decision-api" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Minimal FastAPI test app (avoids loading real models / DB)
# ---------------------------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from middleware.idempotency import IdempotencyMiddleware
from middleware.rate_limit import RateLimitMiddleware


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/v1/decisions")
    async def echo_decision(request: Request):
        body = await request.body()
        return JSONResponse({"ok": True, "body": body.decode()})

    @app.get("/v1/health")
    async def health():
        return {"status": "ok"}

    return app


# ---------------------------------------------------------------------------
# Redis mock helpers
# ---------------------------------------------------------------------------

class _FakeRedis:
    """In-memory Redis substitute for unit tests."""

    def __init__(self):
        self._store: Dict[str, Any] = {}
        self._ttl: Dict[str, int] = {}

    def pipeline(self):
        return _FakePipeline(self)

    async def expire(self, key: str, ttl: int):
        self._ttl[key] = ttl

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int = None):
        self._store[key] = value
        if ex:
            self._ttl[key] = ex

    async def delete(self, key: str):
        self._store.pop(key, None)

    async def ping(self):
        return True


class _FakePipeline:
    def __init__(self, redis: _FakeRedis):
        self._redis = redis
        self._cmds: list = []

    def incr(self, key: str):
        self._cmds.append(("incr", key))
        return self

    def ttl(self, key: str):
        self._cmds.append(("ttl", key))
        return self

    async def execute(self):
        results = []
        for cmd, key in self._cmds:
            if cmd == "incr":
                val = int(self._redis._store.get(key, 0)) + 1
                self._redis._store[key] = str(val)
                results.append(str(val))
            elif cmd == "ttl":
                results.append(self._redis._ttl.get(key, -1))
        return results


# ---------------------------------------------------------------------------
# Tests — Rate Limiting
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_redis():
    return _FakeRedis()


def _make_auth_header(tenant_id: str = "tenant-a") -> Dict[str, str]:
    """Return a fake Authorization header that the JWT extractor will decode."""
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"HS256"}').rstrip(b"=").decode()
    payload_data = json.dumps({"tenant_id": tenant_id, "sub": "test"}).encode()
    payload = base64.urlsafe_b64encode(payload_data).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(b"fakesig").rstrip(b"=").decode()
    token = f"{header}.{payload}.{sig}"
    return {"Authorization": f"Bearer {token}"}


class TestRateLimitMiddleware:

    def test_allows_requests_within_quota(self, fake_redis):
        """Requests within the limit should receive 200."""
        import middleware.rate_limit as rl

        with patch.object(rl, "_REDIS_AVAILABLE", True), \
             patch.object(rl, "_REDIS_CLIENT", None), \
             patch.object(rl, "_get_redis", return_value=fake_redis):

            app = _make_test_app()
            client = TestClient(app, raise_server_exceptions=True)
            headers = _make_auth_header("tenant-a")

            # Override limit to 3 for test
            with patch.dict(rl.RATE_LIMITS, {"/v1/decisions": 3}):
                for _ in range(3):
                    resp = client.post("/v1/decisions", json={}, headers=headers)
                    assert resp.status_code in (200, 422), resp.text
                    assert "X-RateLimit-Limit" in resp.headers

    def test_rejects_over_limit(self, fake_redis):
        """Requests exceeding the limit should receive 429."""
        import middleware.rate_limit as rl

        with patch.object(rl, "_REDIS_AVAILABLE", True), \
             patch.object(rl, "_REDIS_CLIENT", None), \
             patch.object(rl, "_get_redis", return_value=fake_redis):

            app = _make_test_app()
            client = TestClient(app, raise_server_exceptions=True)
            headers = _make_auth_header("tenant-b")

            with patch.dict(rl.RATE_LIMITS, {"/v1/decisions": 2}):
                # First 2 within limit
                for _ in range(2):
                    client.post("/v1/decisions", json={}, headers=headers)
                # 3rd request should be rejected
                resp = client.post("/v1/decisions", json={}, headers=headers)
                assert resp.status_code == 429
                data = resp.json()
                assert "retry_after_seconds" in data

    def test_independent_quotas_per_tenant(self, fake_redis):
        """Tenant A exhausting quota must not affect Tenant B."""
        import middleware.rate_limit as rl

        with patch.object(rl, "_REDIS_AVAILABLE", True), \
             patch.object(rl, "_REDIS_CLIENT", None), \
             patch.object(rl, "_get_redis", return_value=fake_redis):

            app = _make_test_app()
            client = TestClient(app, raise_server_exceptions=True)

            with patch.dict(rl.RATE_LIMITS, {"/v1/decisions": 1}):
                # Exhaust tenant-a quota
                client.post("/v1/decisions", json={}, headers=_make_auth_header("tenant-x"))
                blocked = client.post("/v1/decisions", json={}, headers=_make_auth_header("tenant-x"))
                assert blocked.status_code == 429

                # tenant-y must still be allowed
                resp_y = client.post("/v1/decisions", json={}, headers=_make_auth_header("tenant-y"))
                assert resp_y.status_code in (200, 422)

    def test_health_endpoint_bypasses_rate_limit(self, fake_redis):
        """Health endpoint should never be rate-limited."""
        import middleware.rate_limit as rl

        with patch.object(rl, "_REDIS_AVAILABLE", True), \
             patch.object(rl, "_REDIS_CLIENT", None), \
             patch.object(rl, "_get_redis", return_value=fake_redis):

            app = _make_test_app()
            client = TestClient(app, raise_server_exceptions=True)

            with patch.dict(rl.RATE_LIMITS, {}), \
                 patch.object(rl, "DEFAULT_LIMIT", 0):
                resp = client.get("/v1/health")
                assert resp.status_code == 200
                assert "X-RateLimit-Limit" not in resp.headers

    def test_redis_failure_is_non_fatal(self):
        """Redis error must not block the request — middleware passes through."""
        import middleware.rate_limit as rl

        broken_redis = MagicMock()
        broken_redis.pipeline.side_effect = Exception("Redis down")

        with patch.object(rl, "_REDIS_AVAILABLE", True), \
             patch.object(rl, "_REDIS_CLIENT", None), \
             patch.object(rl, "_get_redis", return_value=broken_redis):

            app = _make_test_app()
            client = TestClient(app, raise_server_exceptions=True)
            resp = client.post("/v1/decisions", json={}, headers=_make_auth_header())
            # Should still get a response (not 500)
            assert resp.status_code in (200, 422, 429)


# ---------------------------------------------------------------------------
# Tests — Idempotency
# ---------------------------------------------------------------------------

class TestIdempotencyMiddleware:

    def test_replay_returns_cached_response(self, fake_redis):
        """Same Idempotency-Key within TTL should return cached body without re-executing."""
        import middleware.idempotency as idm
        import middleware.rate_limit as rl

        call_count = 0

        with patch.object(idm, "_REDIS_AVAILABLE", True), \
             patch.object(idm, "_REDIS_CLIENT", None), \
             patch.object(idm, "_get_redis", return_value=fake_redis), \
             patch.object(rl, "_REDIS_AVAILABLE", False):  # disable rate limiter

            app = FastAPI()
            app.add_middleware(IdempotencyMiddleware)

            @app.post("/v1/decisions")
            async def handler(request: Request):
                nonlocal call_count
                call_count += 1
                return JSONResponse({"execution": call_count})

            client = TestClient(app, raise_server_exceptions=True)
            headers = {**_make_auth_header(), "Idempotency-Key": "key-abc-123"}

            r1 = client.post("/v1/decisions", json={"x": 1}, headers=headers)
            r2 = client.post("/v1/decisions", json={"x": 1}, headers=headers)

            assert r1.status_code == 200
            assert r2.status_code == 200
            # Body should be identical on replay
            assert r1.json() == r2.json()
            # Execution count must be 1 — handler only ran once
            assert call_count == 1
            assert r2.headers.get("Idempotency-Replayed") == "true"

    def test_absent_key_passes_through(self, fake_redis):
        """Without an Idempotency-Key header the request executes normally."""
        import middleware.idempotency as idm
        import middleware.rate_limit as rl

        call_count = 0

        with patch.object(idm, "_REDIS_AVAILABLE", True), \
             patch.object(idm, "_REDIS_CLIENT", None), \
             patch.object(idm, "_get_redis", return_value=fake_redis), \
             patch.object(rl, "_REDIS_AVAILABLE", False):

            app = FastAPI()
            app.add_middleware(IdempotencyMiddleware)

            @app.post("/v1/decisions")
            async def handler():
                nonlocal call_count
                call_count += 1
                return {"execution": call_count}

            client = TestClient(app, raise_server_exceptions=True)
            headers = _make_auth_header()

            client.post("/v1/decisions", json={}, headers=headers)
            client.post("/v1/decisions", json={}, headers=headers)

            assert call_count == 2

    def test_different_keys_are_independent(self, fake_redis):
        """Different Idempotency-Keys must not share cached responses."""
        import middleware.idempotency as idm
        import middleware.rate_limit as rl

        call_count = 0

        with patch.object(idm, "_REDIS_AVAILABLE", True), \
             patch.object(idm, "_REDIS_CLIENT", None), \
             patch.object(idm, "_get_redis", return_value=fake_redis), \
             patch.object(rl, "_REDIS_AVAILABLE", False):

            app = FastAPI()
            app.add_middleware(IdempotencyMiddleware)

            @app.post("/v1/decisions")
            async def handler():
                nonlocal call_count
                call_count += 1
                return {"execution": call_count}

            client = TestClient(app, raise_server_exceptions=True)

            r1 = client.post("/v1/decisions", json={}, headers={
                **_make_auth_header(), "Idempotency-Key": "key-1"
            })
            r2 = client.post("/v1/decisions", json={}, headers={
                **_make_auth_header(), "Idempotency-Key": "key-2"
            })

            assert call_count == 2
            assert r1.json()["execution"] != r2.json()["execution"]
