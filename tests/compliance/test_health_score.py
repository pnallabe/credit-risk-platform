"""
Smoke tests for compliance/health_score.py
"""
from __future__ import annotations

import pytest

import compliance.health_score as hs
from compliance.health_score import ComplianceHealthScore, DIMENSION_WEIGHTS


def test_dimension_weights_sum_to_one():
    total = sum(DIMENSION_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-6


def test_dimension_weights_keys():
    expected = {
        "usury_compliance",
        "military_lending_compliance",
        "fair_lending_dir",
        "adverse_action_sla",
        "tila_disclosure_coverage",
        "model_governance",
        "policy_lifecycle",
        "audit_completeness",
    }
    assert set(DIMENSION_WEIGHTS.keys()) == expected


def test_compliance_health_score_dataclass():
    score = ComplianceHealthScore(
        overall=95.0,
        dimension_scores={"usury_compliance": 100.0},
        failing_dimensions=[],
        status="GREEN",
    )
    assert score.overall == 95.0
    assert score.status == "GREEN"
    assert score.failing_dimensions == []
    assert score.computed_at  # non-empty string


def test_compliance_health_score_red_status():
    score = ComplianceHealthScore(
        overall=60.0,
        dimension_scores={"adverse_action_sla": 0.0},
        failing_dimensions=["adverse_action_sla"],
        status="RED",
    )
    assert score.status == "RED"
    assert "adverse_action_sla" in score.failing_dimensions


def test_compute_health_score_raises_without_bq(monkeypatch):
    """Without BigQuery, compute_health_score should raise RuntimeError."""
    monkeypatch.setattr(hs, "_BQ_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="BigQuery unavailable"):
        hs.compute_health_score()


def test_compute_health_score_raises_without_bq_lib_none(monkeypatch):
    monkeypatch.setattr(hs, "_BQ_AVAILABLE", True)
    monkeypatch.setattr(hs, "_bq_lib", None)
    with pytest.raises(RuntimeError, match="BigQuery unavailable"):
        hs.compute_health_score()
