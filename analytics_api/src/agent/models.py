"""
models.py — Raw intent models extracted by IntentParser (LLM output).

These are the "raw" Pydantic models that the LLM populates.
SemanticResolver converts them into the typed ResolvedIntent.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, field_validator


class FilterCondition(BaseModel):
    field: str
    operator: str     # "=", "!=", ">", ">=", "<", "<=", "IN", "BETWEEN"
    value: Any


class TimeRange(BaseModel):
    start: Optional[str] = None   # ISO date string or None
    end: Optional[str] = None

    @field_validator("start", "end", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        return v.strip() if isinstance(v, str) else v


class QueryIntent(BaseModel):
    """Structured query intent extracted from a natural language question.

    The LLM populates this from the user's question. All fields are optional
    so that partial extraction still succeeds.
    """
    metric: Optional[str] = None            # e.g. "DelinquencyRate"
    dimensions: List[str] = []              # e.g. ["product_type", "quarter"]
    filters: List[FilterCondition] = []
    time_range: Optional[TimeRange] = None
    product_type: Optional[str] = None      # PERSONAL_LOAN | MORTGAGE | CREDIT_CARD | ALL
    is_timeseries: bool = False             # user asked "over time" / "by month"
    is_breakdown: bool = False              # user asked "by X" where X is a dimension
    raw_question: str = ""
