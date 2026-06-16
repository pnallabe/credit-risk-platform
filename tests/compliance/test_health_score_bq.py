"""
Tests for compliance/health_score.py — BQ-mocked paths.

Strategy: monkeypatch _bq_lib with a mock client whose .query().result()
returns controlled row iterables, enabling full coverage of compute_health_score().
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

import compliance.health_score as hs_mod
from compliance.health_score import (
    DIMENSION_WEIGHTS,
    ComplianceHealthScore,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _query_result(value):
    """Return a mock BQ query result that yields [[value]]."""
    m = MagicMock()
    m.result.return_value = [[value]]
    return m


def _make_bq_client(*query_values):
    """
    Create a mock BQ client where successive .query() calls return
    the provided values in order.  insert_rows_json returns [].
    """
    mock_client = MagicMock()
    mock_client.query.side_effect = [_query_result(v) for v in query_values]
    mock_client.insert_rows_json.return_value = []
    return mock_client


def _bq_lib_for(client):
    """Wrap a mock BQ client in a module-like mock."""
    mock_lib = MagicMock()
    mock_lib.Client.return_value = client
    return mock_lib


# ---------------------------------------------------------------------------
# Helpers: query call order inside compute_health_score
# 1. usury_violations      (_count)
# 2. mil_violations        (_count)
# 3. dir_failures          (_count)
# 4. aa_breaches           (_count)
# 5. missing_disclosures   (_count)
# 6. model_governance      (_fetch_dimension_score)
# 7. policy_lifecycle      (_fetch_dimension_score)
# 8. audit_completeness    (_fetch_dimension_score)
# ---------------------------------------------------------------------------

GREEN_CALLS    = [0, 0, 0, 0, 0, 100.0, 100.0, 100.0]
YELLOW_CALLS   = [0, 1, 0, 1, 0, 100.0, 100.0, 100.0]   # zero-tolerance x2 → ~75
RED_CALLS      = [0, 1, 3, 2, 10, 100.0, 100.0, 100.0]  # see expected overall below


# ---------------------------------------------------------------------------
# Tests: compute_health_score with mocked BQ
# ---------------------------------------------------------------------------

def test_compute_health_score_green(monkeypatch):
    client = _make_bq_client(*GREEN_CALLS)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert isinstance(score, ComplianceHealthScore)
    assert score.overall == 100.0
    assert score.status == "GREEN"
    assert score.failing_dimensions == []
    assert score.dimension_scores["usury_compliance"] == 100.0
    assert score.dimension_scores["military_lending_compliance"] == 100.0


def test_compute_health_score_yellow(monkeypatch):
    """Zero-tolerance dimensions hit → YELLOW (overall ≈ 75)."""
    client = _make_bq_client(*YELLOW_CALLS)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.status == "YELLOW"
    assert score.dimension_scores["military_lending_compliance"] == 0.0
    assert score.dimension_scores["adverse_action_sla"] == 0.0
    assert "military_lending_compliance" in score.failing_dimensions
    assert "adverse_action_sla" in score.failing_dimensions
    assert 70.0 <= score.overall < 90.0


def test_compute_health_score_red(monkeypatch):
    """Multiple violations → RED overall."""
    client = _make_bq_client(*RED_CALLS)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.status == "RED"
    assert score.overall < 70.0


def test_compute_health_score_usury_violations(monkeypatch):
    """1 usury violation → 90 pts (100 - 10×1)."""
    calls = [1, 0, 0, 0, 0, 100.0, 100.0, 100.0]
    client = _make_bq_client(*calls)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.dimension_scores["usury_compliance"] == 90.0


def test_compute_health_score_tila_violations(monkeypatch):
    """3 TILA violations → 85 pts (100 - 5×3)."""
    calls = [0, 0, 0, 0, 3, 100.0, 100.0, 100.0]
    client = _make_bq_client(*calls)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.dimension_scores["tila_disclosure_coverage"] == 85.0


def test_compute_health_score_dir_violations_floored_at_zero(monkeypatch):
    """10 DIR violations → floor 0 (would be 100 - 200 = -100 → clamped to 0)."""
    calls = [0, 0, 10, 0, 0, 100.0, 100.0, 100.0]
    client = _make_bq_client(*calls)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.dimension_scores["fair_lending_dir"] == 0.0


def test_compute_health_score_returns_computed_at(monkeypatch):
    client = _make_bq_client(*GREEN_CALLS)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.computed_at is not None
    assert len(score.computed_at) > 0


def test_compute_health_score_persist_called(monkeypatch):
    """_persist_score should be invoked → insert_rows_json called once."""
    client = _make_bq_client(*GREEN_CALLS)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    hs_mod.compute_health_score()

    client.insert_rows_json.assert_called_once()


def test_compute_health_score_dim_score_from_bq(monkeypatch):
    """_fetch_dimension_score returns BQ value when it is non-None."""
    calls = [0, 0, 0, 0, 0, 87.5, 92.0, 95.0]
    client = _make_bq_client(*calls)
    monkeypatch.setattr(hs_mod, "_bq_lib", _bq_lib_for(client))
    monkeypatch.setattr(hs_mod, "_BQ_AVAILABLE", True)

    score = hs_mod.compute_health_score()

    assert score.dimension_scores["model_governance"] == 87.5
    assert score.dimension_scores["policy_lifecycle"] == 92.0
    assert score.dimension_scores["audit_completeness"] == 95.0
