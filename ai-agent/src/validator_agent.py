"""
validator_agent.py — Prompt 20-C (GAP-20)
Reconciles every number cited in AI-generated narrative against the actual
rows returned by executed SQL queries. Primary anti-hallucination enforcement layer.
PRD §5.2 (Enforcement Layer 4), §4.6.6
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class HallucinationAttempt(BaseModel):
    suppressed_sentence: str
    claimed_value: str            # Number as it appeared in narrative
    nearest_result_value: Optional[str]   # Closest value in result_rows, or None
    delta_pct: Optional[float]            # Absolute % difference, or None


class ValidationResult(BaseModel):
    passed: bool
    validated_narrative: str
    hallucination_count: int
    suppressed_sentences: list[str]
    attempts: list[HallucinationAttempt]


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ValidatorAgent:
    """
    Reconciles numeric claims in narrative against SQL result rows.
    Synchronous — no I/O.
    """

    TOLERANCE_PCT = 1.0    # Numbers within 1% are considered matching

    # Regex for numeric tokens including percentages and decimals
    _NUM_RE = re.compile(r'\b\d+(?:[.,]\d+)?%?\b')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten_numerics(result_rows: list[dict]) -> list[float]:
        """Recursively collect all values castable to float from result_rows."""
        values: list[float] = []
        stack = list(result_rows)
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(item.values())
            elif isinstance(item, (list, tuple)):
                stack.extend(item)
            else:
                try:
                    values.append(float(item))
                except (TypeError, ValueError):
                    pass
        return values

    @classmethod
    def _parse_claimed_value(cls, token: str) -> float:
        """Parse a numeric token (possibly with % or comma) to float."""
        clean = token.rstrip("%").replace(",", ".")
        return float(clean)

    @classmethod
    def _is_within_tolerance(cls, claimed: float, result_values: list[float]) -> tuple[bool, Optional[float], Optional[float]]:
        """
        Check if claimed value matches any result value within TOLERANCE_PCT.
        Also checks claimed*100 and claimed/100 to handle percentage vs decimal conversions.
        Returns (matched, nearest_value, delta_pct).
        """
        candidates = [claimed, claimed * 100, claimed / 100]
        best_delta: Optional[float] = None
        best_match: Optional[float] = None

        for rv in result_values:
            if rv == 0:
                # If claimed also 0, it's a match
                for c in candidates:
                    if c == 0:
                        return True, rv, 0.0
                continue
            for c in candidates:
                delta = abs((c - rv) / rv) * 100
                if delta <= cls.TOLERANCE_PCT:
                    return True, rv, delta
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    best_match = rv

        return False, best_match, best_delta

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reconcile(
        self,
        narrative: str,
        result_rows: list[dict],
    ) -> ValidationResult:
        """
        Reconcile numbers in narrative against result_rows.
        Returns ValidationResult (synchronous, no I/O).
        """
        # Fast path: no numeric tokens in narrative
        if not self._NUM_RE.search(narrative):
            return ValidationResult(
                passed=True,
                validated_narrative=narrative,
                hallucination_count=0,
                suppressed_sentences=[],
                attempts=[],
            )

        # Flatten all numeric values from result rows
        result_values = self._flatten_numerics(result_rows)

        # Tokenize narrative into sentences
        # TODO: replace with spaCy sentence tokenization for better accuracy
        sentences = narrative.split(". ")

        valid_sentences: list[str] = []
        suppressed: list[str] = []
        attempts: list[HallucinationAttempt] = []

        for sentence in sentences:
            numeric_tokens = self._NUM_RE.findall(sentence)
            if not numeric_tokens:
                # No numbers — keep sentence
                valid_sentences.append(sentence)
                continue

            sentence_has_hallucination = False

            for token in numeric_tokens:
                try:
                    claimed = self._parse_claimed_value(token)
                except (ValueError, OverflowError):
                    continue  # Non-parseable token — skip

                matched, nearest, delta = self._is_within_tolerance(claimed, result_values)

                if not matched:
                    sentence_has_hallucination = True
                    attempts.append(
                        HallucinationAttempt(
                            suppressed_sentence=sentence,
                            claimed_value=token,
                            nearest_result_value=str(nearest) if nearest is not None else None,
                            delta_pct=round(delta, 2) if delta is not None else None,
                        )
                    )
                    # Only record the first failing token per sentence to avoid duplication
                    break

            if sentence_has_hallucination:
                suppressed.append(sentence)
            else:
                valid_sentences.append(sentence)

        validated_narrative = ". ".join(valid_sentences)
        hallucination_count = len(suppressed)

        return ValidationResult(
            passed=(hallucination_count == 0),
            validated_narrative=validated_narrative,
            hallucination_count=hallucination_count,
            suppressed_sentences=suppressed,
            attempts=attempts,
        )

    def emit_hallucination_webhook(
        self,
        result: ValidationResult,
        session_id: str,
        query_id: str,
    ) -> None:
        """
        Emit HALLUCINATION_DETECTED webhook if hallucinations were found.
        Fire-and-forget via threading.Thread to avoid blocking.
        Catches ImportError silently.
        """
        if result.hallucination_count == 0:
            return

        logger.warning(
            "Hallucination detected — session=%s query=%s count=%d",
            session_id, query_id, result.hallucination_count,
        )

        def _emit() -> None:
            try:
                from webhooks.dispatcher import WebhookDispatcher
                from webhooks.store import WebhookStore
                import os

                db_url = os.getenv("DATABASE_URL", "webhooks.db")
                store = WebhookStore(db_url=db_url)
                dispatcher = WebhookDispatcher(store=store)
                payload = {
                    "event": "hallucination.detected",
                    "data": {
                        "session_id": session_id,
                        "query_id": query_id,
                        "suppressed_sentence_count": len(result.suppressed_sentences),
                        "hallucination_count": result.hallucination_count,
                    },
                }
                dispatcher.dispatch(session_id, "hallucination.detected", payload)
            except ImportError as exc:
                logger.warning("Webhook import failed (hallucination.detected): %s", exc)
            except Exception as exc:
                logger.warning("Webhook emission failed (hallucination.detected): %s", exc)

        thread = threading.Thread(target=_emit, daemon=True)
        thread.start()
