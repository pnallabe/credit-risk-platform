"""
Idempotency Middleware — Decision API
======================================
Allows callers to pass an ``Idempotency-Key`` request header so that
replaying the same request does not double-write audit logs or produce
different outcomes.

Behaviour
---------
* On the *first* call for a ``(tenant_id, idempotency_key)`` pair the
  response is stored in Redis with a configurable TTL.
* Subsequent calls with the same key (within TTL) return the cached
  response immediately — the pipeline is **not** re-executed.
* Idempotency is only applied to **mutating** endpoints (POST / PATCH).
* If the ``Idempotency-Key`` header is absent the request passes through normally.
* Redis errors are non-fatal: the request executes normally and a warning is logged.

Environment variables
---------------------
REDIS_URL                Redis DSN (default: redis://localhost:6379/0)
IDEMPOTENCY_TTL_SECONDS  Cache TTL in seconds (default: 86400 = 24 h)

Header
------
Idempotency-Key: <caller-supplied UUID or nonce>

Response extra headers
----------------------
Idempotency-Replayed: true   — only present on replayed responses
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
IDEMPOTENCY_TTL: int = int(os.getenv("IDEMPOTENCY_TTL_SECONDS", str(24 * 3600)))
IDEMPOTENCY_HEADER = "Idempotency-Key"

# Paths that support idempotency (POST operations on decision endpoints)
_IDEMPOTENCY_PATHS = {"/v1/decisions", "/v1/decisions/batch"}

try:
    import redis.asyncio as aioredis  # type: ignore[import]

    _REDIS_CLIENT: Optional[aioredis.Redis] = None

    def _get_redis() -> aioredis.Redis:
        global _REDIS_CLIENT
        if _REDIS_CLIENT is None:
            _REDIS_CLIENT = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
        return _REDIS_CLIENT

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    logger.warning(
        "[idempotency] redis-py not installed — idempotency is DISABLED."
    )


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """
    Cache POST response body keyed by ``(tenant_id, Idempotency-Key)`` in Redis.

    Replay returns the cached JSON body with status 200 and the header
    ``Idempotency-Replayed: true`` so callers can detect replay.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Only applies to mutating methods on supported paths
        if request.method not in ("POST", "PATCH"):
            return await call_next(request)

        if request.url.path not in _IDEMPOTENCY_PATHS:
            return await call_next(request)

        idempotency_key: Optional[str] = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        if not _REDIS_AVAILABLE:
            return await call_next(request)

        # Extract tenant_id best-effort from the JWT Authorization header.
        # Full validation is enforced by verify_bearer; this is only used as the
        # namespace for the idempotency cache key.
        from middleware.rate_limit import _extract_tenant_id  # noqa: PLC0415
        tenant_id: str = _extract_tenant_id(request)
        redis_key = f"idem:{tenant_id}:{idempotency_key}"

        try:
            redis = _get_redis()

            # Check for a cached response
            cached = await redis.get(redis_key)
            if cached is not None:
                logger.info(
                    "[idempotency] Replaying cached response: tenant=%s key=%s",
                    tenant_id,
                    idempotency_key,
                )
                try:
                    blob = json.loads(cached)
                    return JSONResponse(
                        status_code=blob["status_code"],
                        content=blob["body"],
                        headers={"Idempotency-Replayed": "true"},
                    )
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.error("[idempotency] Cache blob corrupt, re-executing: %s", exc)
                    await redis.delete(redis_key)

            # Execute the actual request
            response: Response = await call_next(request)

            # Capture body — Starlette responses are streaming; we need to buffer
            chunks: list[bytes] = []
            async for chunk in response.body_iterator:  # type: ignore[attr-defined]
                chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
            body_bytes = b"".join(chunks)

            # Only cache successful, JSON-serialisable responses
            content_type = response.headers.get("content-type", "")
            if response.status_code < 500 and "application/json" in content_type:
                try:
                    body_obj = json.loads(body_bytes.decode())
                    blob = json.dumps(
                        {"status_code": response.status_code, "body": body_obj}
                    )
                    await redis.set(redis_key, blob, ex=IDEMPOTENCY_TTL)
                    logger.info(
                        "[idempotency] Stored response: tenant=%s key=%s ttl=%ds",
                        tenant_id,
                        idempotency_key,
                        IDEMPOTENCY_TTL,
                    )
                except Exception as exc:
                    logger.warning("[idempotency] Failed to cache response: %s", exc)

            # Rebuild the response with the buffered body
            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        except Exception as exc:
            logger.error("[idempotency] Redis error, bypassing idempotency: %s", exc)
            return await call_next(request)
