"""
Tests for ai-agent/src/confidence_scorer.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.confidence_scorer import (
    ConfidenceFactors,
    ConfidenceScore,
    compute_confidence,
    should_refuse,
    REFUSAL_MESSAGE,
)


def _make_factors(**kwargs) -> ConfidenceFactors:
    defaults = dict(
        row_count=0,
        query_error=False,
        empty_result=True,
        tools_called=[],
        has_sql_artifact=False,
    )
    defaults.update(kwargs)
    return ConfidenceFactors(**defaults)


def test_high_confidence_many_rows():
    factors = _make_factors(
        row_count=100,
        query_error=False,
        empty_result=False,
        tools_called=["sql_query_tool", "metrics_tool"],
        has_sql_artifact=True,
    )
    result = compute_confidence(factors)
    assert result.score >= 0.75
    assert result.label == "high"


def test_none_confidence_empty_result():
    factors = _make_factors(
        row_count=0,
        query_error=False,
        empty_result=True,
        tools_called=["sql_query_tool"],
        has_sql_artifact=True,
    )
    result = compute_confidence(factors)
    assert result.label == "none" or result.score < 0.10


def test_none_confidence_sql_error():
    factors = _make_factors(
        row_count=0,
        query_error=True,
        empty_result=False,
        tools_called=[],
        has_sql_artifact=False,
    )
    result = compute_confidence(factors)
    assert result.score == 0.0
    assert result.label == "none"


def test_should_refuse_on_empty_result():
    conf = ConfidenceScore(
        score=0.0,
        label="none",
        factors=_make_factors(),
        explanation="test",
    )
    assert should_refuse(conf) is True


def test_should_not_refuse_on_high_confidence():
    conf = ConfidenceScore(
        score=0.9,
        label="high",
        factors=_make_factors(row_count=80, empty_result=False),
        explanation="test",
    )
    assert should_refuse(conf) is False


def test_refusal_message_is_non_empty_string():
    assert isinstance(REFUSAL_MESSAGE, str)
    assert len(REFUSAL_MESSAGE) > 20


def test_should_refuse_configurable_threshold_passes():
    factors = _make_factors(empty_result=True, has_sql_artifact=True)
    conf = ConfidenceScore(score=0.08, label="low", factors=factors, explanation="")
    assert should_refuse(conf, threshold=0.05) is False


def test_should_refuse_configurable_threshold_refuses():
    factors = _make_factors(empty_result=True, has_sql_artifact=True)
    conf = ConfidenceScore(score=0.25, label="low", factors=factors, explanation="")
    assert should_refuse(conf, threshold=0.30) is True


def test_strict_grounding_gate():
    factors = _make_factors(row_count=0, has_sql_artifact=False, query_error=False, empty_result=True)
    conf = ConfidenceScore(score=0.50, label="medium", factors=factors, explanation="")
    assert should_refuse(conf, threshold=0.10) is True
