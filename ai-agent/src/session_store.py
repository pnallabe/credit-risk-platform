"""
session_store.py — Prompt 20-D (GAP-20)
Redis-backed (with in-process dict fallback for dev/test) session memory store.
Stores the last MAX_TURNS turns per session as a sliding window.
PRD §7.2 (Redis)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Multi-turn session memory with sliding window of MAX_TURNS.
    Backend: Redis (if available) or in-process dict (dev/test only).

    WARNING: The in-process dict fallback is process-local and NOT suitable
    for multi-instance / horizontally-scaled deployments.
    """

    MAX_TURNS = 20

    def __init__(
        self,
        redis_url: Optional[str] = None,
        sqlite_path: str = ":memory:",
    ) -> None:
        self._redis = None
        self._local: dict[str, list[dict]] = {}

        if redis_url:
            try:
                import redis  # type: ignore[import]
                self._redis = redis.from_url(redis_url, decode_responses=True)
                # Test connectivity
                self._redis.ping()
                logger.info("SessionStore: using Redis backend (%s)", redis_url)
            except ImportError:
                logger.info("SessionStore: redis package not installed; falling back to in-process dict.")
                self._redis = None
            except Exception as exc:
                logger.info("SessionStore: Redis unavailable (%s); falling back to in-process dict.", exc)
                self._redis = None
        else:
            logger.info("SessionStore: no redis_url provided; using in-process dict.")

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _redis_key(self, session_id: str) -> str:
        return f"agent:session:{session_id}:turns"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_turn(self, session_id: str, turn: dict) -> None:
        """
        Append turn dict to session history. Trims to MAX_TURNS (oldest removed).
        """
        if self._redis is not None:
            try:
                key = self._redis_key(session_id)
                self._redis.rpush(key, json.dumps(turn, default=str))
                self._redis.ltrim(key, -self.MAX_TURNS, -1)
                return
            except Exception as exc:
                logger.warning("Redis append_turn failed: %s; falling back to local.", exc)

        # Local fallback
        turns = self._local.setdefault(session_id, [])
        turns.append(turn)
        if len(turns) > self.MAX_TURNS:
            self._local[session_id] = turns[-self.MAX_TURNS:]

    def get_history(self, session_id: str) -> list[dict]:
        """Return list of turn dicts for session_id. Returns [] if not found."""
        if self._redis is not None:
            try:
                key = self._redis_key(session_id)
                raw_items = self._redis.lrange(key, 0, -1)
                return [json.loads(item) for item in raw_items]
            except Exception as exc:
                logger.warning("Redis get_history failed: %s; falling back to local.", exc)

        return list(self._local.get(session_id, []))

    def clear_session(self, session_id: str) -> None:
        """Delete session history."""
        if self._redis is not None:
            try:
                self._redis.delete(self._redis_key(session_id))
                return
            except Exception as exc:
                logger.warning("Redis clear_session failed: %s; falling back to local.", exc)

        self._local.pop(session_id, None)
