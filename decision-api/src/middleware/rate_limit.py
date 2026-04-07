"""
Redis Token-Bucket Rate Limiter — Decision API
===============================================
Scopes each limit to the tuple ``(tenant_id, route)`` so tenants cannot
exhaust each other's quota.

Algorithm: sliding-window counter backed by Redis INCR + EXPIRE.
The window resets on the first request in each period.

Environment variables
---------------------
REDIS_URL          Redis DSN (default: redis://localhost:6379/0)
RATE_LIMIT_WINDOW  Window length in seconds (default: 60)
RATE_LIMIT_MAX     Maximum requests per window per (tenant, route)
                   (default: 100 for the decision endpoint)

Each route can override the default limit via the RATE_LIMITS dict.

Usage
-----
    from decision_api.middleware.rate_limit import RateLimitMiddleware
    app.add_middleware(RateLimitMiddleware)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWT helpers — lightweight token parse (no signature verification) used
# solely to extract tenant_id for rate-limit key construction.  Full sig
# validation still happens in the verify_bearer dependency.
# ---------------------------------------------------------------------------
try:
    import jwt as _pyjwt  # type: ignore[import]
    _JWT_AVAILABLE = True
except ImportError:
    _JWT_AVAILABLE = False

_JWT_SECRET: Optional[str] = os.getenv("JWT_SECRET")
_JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")


def _extract_tenant_id(request: Request) -> str:
    """Best-effort tenant_id extraction from the Authorization header.

    Falls back to 'anonymous' if the token is absent or malformed.
    The actual security check is enforced by the verify_bearer dependency.
    """
    auth: Optional[str] = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return "anonymous"
    token = auth[len("Bearer "):]
    if _JWT_AVAILABLE and _JWT_SECRET:
        try:
            payload = _pyjwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
            return str(payload.get("tenant_id", "anonymous"))
        except Exception:
            pass
    # Fallback: base64-decode payload section (no verification)
    try:
        import base64, json as _json  # noqa: E401
        parts = token.split(".")
        if len(parts) == 3:
            padded = parts[1] + "=" * (-len(parts[1]) % 4)
            data = _json.loads(base64.urlsafe_b64decode(padded))
            return str(data.get("tenant_id", "anonymous"))
    except Exception:
        pass
    return "anonymous"


REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "60"))

# Per-route request limits within RATE_LIMIT_WINDOW seconds.
# Keys are the *path prefix* (startswith match).  Falls back to DEFAULT_LIMIT.
RATE_LIMITS: dict[str, int] = {
    "/v1/decisions/batch": int(os.getenv("RATE_LIMIT_BATCH", "10")),
    "/v1/decisions": int(os.getenv("RATE_LIMIT_DECISIONS", "100")),
}
DEFAULT_LIMIT: int = int(os.getenv("RATE_LIMIT_DEFAULT", "200"))

# ---------------------------------------------------------------------------
# Optional redis import — middleware degrades gracefully (pass-through) if
# redis-py is not installed or the server is unreachable.
# ---------------------------------------------------------------------------
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
        "[rate_limit] redis-py not installed — rate limiting is DISABLED. "
        "Add 'redis[asyncio]' to requirements.txt."
    )


def _resolve_limit(path: str) -> int:
    """Return the configured request limit for *path*."""
    # Match longest prefix first
    for prefix in sorted(RATE_LIMITS, key=len, reverse=True):
        if path.startswith(prefix):
            return RATE_LIMITS[prefix]
    return DEFAULT_LIMIT


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window counter rate limiter scoped by (tenant_id, route)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if not _REDIS_AVAILABLE:
            return await call_next(request)

        # Health-check and non-decision routes bypass rate limiting
        path: str = request.url.path
        if path in ("/v1/health", "/", "/docs", "/redoc", "/openapi.json"):
            return await call_next(request)

        # Extract tenant_id from JWT header (best-effort, no sig verification).
        # Full auth validation happens in verify_bearer dependency.
        # Unauthenticated / malformed requests fall back to 'anonymous' and are
        # rejected by the auth dependency before the pipeline executes.
        tenant_id: str = _extract_tenant_id(request)

        limit = _resolve_limit(path)
        window = RATE_LIMIT_WINDOW
        redis_key = f"rl:{tenant_id}:{path}"

        try:
            redis = _get_redis()
            pipe = redis.pipeline()
            pipe.incr(redis_key)
            pipe.ttl(redis_key)
            count_str, ttl = await pipe.execute()
            count = int(count_str)

            # First request in this window — set expiry
            if ttl == -1:
                await redis.expire(redis_key, window)

            remaining = max(0, limit - count)
            reset_secs = ttl if ttl > 0 else window

            if count > limit:
                logger.warning(
                    "Rate limit exceeded: tenant=%s path=%s count=%d limit=%d",
                    tenant_id,
                    path,
                    count,
                    limit,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded.",
                        "retry_after_seconds": reset_secs,
                        "limit": limit,
                        "window_seconds": window,
                    },
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(int(time.time()) + reset_secs),
                        "Retry-After": str(reset_secs),
                    },
                )

            response: Response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(int(time.time()) + reset_secs)
            return response

        except Exception as exc:
            # Redis failure is non-fatal — pass the request through and log
            logger.error("[rate_limit] Redis error, bypassing rate limit: %s", exc)
            return await call_next(request)
