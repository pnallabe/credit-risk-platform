"""Health-check helpers for the Decision API.

``check_redis`` is used at startup (when ENVIRONMENT=prod) to confirm Redis
is reachable before the service accepts traffic.  If Redis is down, rate-limiting
and idempotency would silently degrade, so we treat it as a hard failure.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Module-level import so that tests can patch ``health.aioredis``.
try:
    import redis.asyncio as aioredis  # type: ignore[import]
    _REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover
    aioredis = None  # type: ignore[assignment]
    _REDIS_AVAILABLE = False


async def check_redis(url: str, timeout: float = 2.0) -> bool:
    """Attempt a ``PING`` against the Redis server and return ``True`` on success.

    Parameters
    ----------
    url:
        Redis connection URL, e.g. ``redis://localhost:6379/0``.
    timeout:
        Maximum seconds to wait for a response before declaring the check
        failed.  Defaults to 2 seconds.

    Returns
    -------
    ``True`` if Redis responds to PING within *timeout* seconds, ``False``
    on any connection error, timeout, or unexpected response.
    """
    if not _REDIS_AVAILABLE or aioredis is None:
        logger.warning("redis-py not installed — check_redis always returns False")
        return False
    try:
        client = aioredis.from_url(
            url,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            decode_responses=True,
        )
        try:
            result = await asyncio.wait_for(client.ping(), timeout=timeout)
            return bool(result)
        finally:
            await client.aclose()
    except asyncio.TimeoutError:
        logger.warning("Redis health check timed out after %.1fs (url=%s)", timeout, url)
        return False
    except Exception as exc:
        logger.warning("Redis health check failed: %s (url=%s)", exc, url)
        return False
