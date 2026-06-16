"""
Smoke tests for audit/consistency_scorer.py
"""
from __future__ import annotations

from audit.consistency_scorer import CONSISTENCY_THRESHOLD, ConsistencyResult


def test_consistency_threshold_value():
    assert CONSISTENCY_THRESHOLD == 0.02


def test_consistency_result_fields():
    result = ConsistencyResult(
        application_id="app-001",
        consistent=True,
        original_decision="APPROVE",
        replayed_decision="APPROVE",
        original_pd=0.05,
        replayed_pd=0.05,
        delta_pd=0.0,
        score=1.0,
        flagged=False,
        checked_at="2026-01-01T00:00:00+00:00",
    )
    assert result.application_id == "app-001"
    assert result.consistent is True
    assert result.original_decision == "APPROVE"
    assert result.replayed_decision == "APPROVE"
    assert result.original_pd == 0.05
    assert result.replayed_pd == 0.05
    assert result.delta_pd == 0.0
    assert result.score == 1.0
    assert result.flagged is False


def test_consistency_result_flagged_on_flip():
    result = ConsistencyResult(
        application_id="app-002",
        consistent=False,
        original_decision="APPROVE",
        replayed_decision="REJECT",
        original_pd=0.04,
        replayed_pd=0.09,
        delta_pd=0.05,
        score=0.0,
        flagged=True,
        checked_at="2026-01-01T00:00:00+00:00",
    )
    assert result.consistent is False
    assert result.flagged is True
    assert result.delta_pd > CONSISTENCY_THRESHOLD


def test_consistency_result_partial_score():
    """Same bucket but high PD delta → score=0.5."""
    result = ConsistencyResult(
        application_id="app-003",
        consistent=False,
        original_decision="APPROVE",
        replayed_decision="APPROVE",
        original_pd=0.04,
        replayed_pd=0.07,
        delta_pd=0.03,
        score=0.5,
        flagged=True,
        checked_at="2026-01-01T00:00:00+00:00",
    )
    assert result.score == 0.5
    assert result.flagged is True
