"""
confidence_scorer.py — Prompt 19-B
Compute a grounding confidence score (0.0–1.0) for an AI agent answer based
on the quality and coverage of the data the agent retrieved.

No external dependencies. Pure Python only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass
class ConfidenceFactors:
    row_count: int            # number of rows returned by the primary SQL tool call
    query_error: bool         # True if the SQL tool returned an error string
    empty_result: bool        # True if row_count == 0
    tools_called: list[str]   # names of tools invoked during the turn
    has_sql_artifact: bool    # True if at least one SQL artifact was stored


@dataclass
class ConfidenceScore:
    score: float                        # 0.0 – 1.0, rounded to 4 decimal places
    label: Literal["high", "medium", "low", "none"]
    factors: ConfidenceFactors
    explanation: str                    # one-sentence plain English explanation


# ---------------------------------------------------------------------------
# Scoring algorithm
# ---------------------------------------------------------------------------
def compute_confidence(factors: ConfidenceFactors) -> ConfidenceScore:
    """
    Scoring algorithm:
      base_score = 0.0

    Adjustments applied in order:
      - query_error=True  → base_score = 0.0, stop
      - empty_result=True → base_score = 0.05 (slight signal the query ran)
      - row_count > 0     → base_score += min(0.5, row_count / 100 * 0.5)
                            (capped so 100+ rows doesn't overflow)
      - has_sql_artifact  → +0.15
      - tool diversity    → +0.05 per unique tool beyond the first, capped at +0.20

    label assignment (after clamping to [0.0, 1.0]):
      score >= 0.75  → "high"
      score >= 0.40  → "medium"
      score >= 0.10  → "low"
      else           → "none"
    """
    base_score = 0.0

    if factors.query_error:
        # Hard-zero on SQL error
        score = 0.0
        label: Literal["high", "medium", "low", "none"] = "none"
        explanation = (
            "SQL execution error encountered; answer has no valid data grounding."
        )
        return ConfidenceScore(
            score=round(score, 4),
            label=label,
            factors=factors,
            explanation=explanation,
        )

    if factors.empty_result or factors.row_count == 0:
        # Empty result: only a minimal signal that the query ran
        base_score = 0.05
        # No artifact/tool bonuses applied on empty results
    else:
        # Row count contribution: up to +0.55 (saturates at 100 rows)
        base_score += min(0.55, factors.row_count / 100 * 0.55)

        # SQL artifact stored (only meaningful when data was returned)
        if factors.has_sql_artifact:
            base_score += 0.15

        # Tool diversity bonus (each additional unique tool beyond the first)
        n_unique = len(set(factors.tools_called))
        if n_unique > 1:
            base_score += min(0.20, (n_unique - 1) * 0.05)

    # Clamp
    unique_tools = len(set(factors.tools_called))
    score = max(0.0, min(1.0, base_score))
    score = round(score, 4)

    # Label
    if score >= 0.75:
        label = "high"
    elif score >= 0.40:
        label = "medium"
    elif score >= 0.10:
        label = "low"
    else:
        label = "none"

    # Explanation
    if factors.empty_result or factors.row_count == 0:
        explanation = (
            "No data rows returned; answer may not reflect current portfolio state."
        )
    elif factors.row_count > 0 and unique_tools >= 2:
        explanation = (
            f"Answer grounded in {factors.row_count} data rows "
            f"from {unique_tools} tool calls."
        )
    else:
        explanation = (
            f"Answer grounded in {factors.row_count} data rows from 1 tool call."
        )

    return ConfidenceScore(
        score=score,
        label=label,
        factors=factors,
        explanation=explanation,
    )


# ---------------------------------------------------------------------------
# Grounding gate
# ---------------------------------------------------------------------------
def should_refuse(score: ConfidenceScore, *, threshold: float = 0.10) -> bool:
    """
    Return True when the label is "none" OR when empty_result is True
    AND score.score < threshold.

    Strict grounding gate: if row_count == 0 AND has_sql_artifact is False
    AND query_error is False, refuse unconditionally.
    """
    f = score.factors
    # Strict grounding gate
    if f.row_count == 0 and not f.has_sql_artifact and not f.query_error:
        return True

    if score.label == "none":
        return True
    if f.empty_result and score.score < threshold:
        return True
    return False


# ---------------------------------------------------------------------------
# Refusal message template
# ---------------------------------------------------------------------------
REFUSAL_MESSAGE = (
    "I was unable to retrieve data to answer this question. "
    "The underlying query returned no results for the specified parameters. "
    "This may indicate the data is outside the available date range, "
    "the tenant has no records matching the criteria, or the relevant "
    "table is empty. Please refine your question or verify the data availability."
)
