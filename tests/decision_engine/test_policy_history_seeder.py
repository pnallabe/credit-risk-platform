"""
Smoke tests for decision_engine/policy_history_seeder.py
"""
from __future__ import annotations

import pytest

from decision_engine.policy_history_seeder import (
    _build_snapshots,
    _make_cc_params,
    _make_pl_params,
    _make_mort_params,
    seed,
)


def test_build_snapshots_returns_22():
    snapshots = _build_snapshots()
    assert len(snapshots) == 22


def test_snapshots_have_required_keys():
    snapshots = _build_snapshots()
    for snap in snapshots:
        for key in ("version_tag", "effective_from", "parameters"):
            assert key in snap, f"Missing key '{key}' in snapshot {snap.get('version_tag')}"


def test_snapshots_have_product_types():
    snapshots = _build_snapshots()
    # Each snapshot's parameters should include at least one product type
    for snap in snapshots:
        params = snap["parameters"]
        assert len(params) > 0


def test_make_cc_params_structure():
    params = _make_cc_params(fico_floor=620, max_dti=0.50)
    assert params["fico_floor"] == 620
    assert params["max_dti"] == 0.50
    assert "max_pd_hard" in params
    assert "apr_floor" in params


def test_make_pl_params_structure():
    params = _make_pl_params(580, 620, 640, 0.40, 0.50)
    assert params["fico_floor_hard_decline"] == 580
    assert params["fico_floor_soft_decline"] == 620
    assert params["max_dti_preferred"] == 0.40
    assert "max_loan_amount" in params
    assert "base_rate" in params


def test_make_mort_params_structure():
    params = _make_mort_params(fico_floor_conforming=620, max_dti_qm=0.43)
    assert params["fico_floor_conforming"] == 620
    assert params["max_dti_qm"] == 0.43
    assert "jumbo_enabled" in params
    assert "conforming_loan_limit" in params


def test_seed_dry_run_returns_empty(tmp_path):
    db_path = str(tmp_path / "test_policy.db")
    result = seed(db_path=db_path, dry_run=True)
    assert result == []


def test_seed_writes_to_db(tmp_path):
    db_path = str(tmp_path / "test_policy.db")
    created = seed(db_path=db_path)
    assert len(created) == 22


def test_seed_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test_policy.db")
    first = seed(db_path=db_path)
    second = seed(db_path=db_path)
    assert len(first) == 22
    assert len(second) == 0  # all skipped on second run


def test_snapshot_version_tags_unique():
    snapshots = _build_snapshots()
    tags = [s["version_tag"] for s in snapshots]
    assert len(tags) == len(set(tags)), "Version tags should be unique"


def test_snapshot_effective_dates_parseable():
    from datetime import datetime
    snapshots = _build_snapshots()
    for snap in snapshots:
        # Should not raise
        datetime.fromisoformat(snap["effective_from"])
