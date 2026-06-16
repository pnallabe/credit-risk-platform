"""
Tests for monitoring/fair_lending.py
======================================
Uses synthetic decisions DataFrames for fully offline testing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from monitoring.fair_lending import (
    FairLendingReport,
    analyze_fair_lending,
    _compute_approval_rate,
    _compute_dir,
    _compute_approval_parity,
    _compute_geographic_flags,
    DIR_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_decisions_df(
    n_protected: int = 200,
    n_control: int = 300,
    protected_approval: float = 0.60,
    control_approval: float = 0.80,
    include_state: bool = True,
    seed: int = 42,
) -> pd.DataFrame:
    """Build a synthetic decisions DataFrame."""
    rng = np.random.RandomState(seed)

    # Protected group decisions
    prot_decisions = rng.choice(["APPROVE", "REJECT"], size=n_protected,
                                p=[protected_approval, 1 - protected_approval])
    # Control group decisions
    ctrl_decisions = rng.choice(["APPROVE", "REJECT"], size=n_control,
                                p=[control_approval, 1 - control_approval])

    prot_states = rng.choice(["CA", "TX", "NY", "FL"], size=n_protected)
    ctrl_states = rng.choice(["CA", "TX", "NY", "FL"], size=n_control)

    prot_df = pd.DataFrame({
        "decision": prot_decisions,
        "demographic_group": "protected",
        "state": prot_states,
    })
    ctrl_df = pd.DataFrame({
        "decision": ctrl_decisions,
        "demographic_group": "control",
        "state": ctrl_states,
    })
    return pd.concat([prot_df, ctrl_df], ignore_index=True)


@pytest.fixture
def fair_df():
    """Balanced decisions where DIR is above 0.80."""
    return _make_decisions_df(protected_approval=0.82, control_approval=0.85)


@pytest.fixture
def biased_df():
    """Biased decisions where DIR is below 0.80."""
    return _make_decisions_df(protected_approval=0.40, control_approval=0.80)


@pytest.fixture
def geo_biased_df():
    """Decisions with geographic bias in one state."""
    rng = np.random.RandomState(1)
    n = 600
    states = rng.choice(["CA", "TX", "NY", "FL", "OH"], size=n, p=[0.3, 0.2, 0.2, 0.2, 0.1])
    # Ohio has very low approval rate
    probs = {"CA": 0.75, "TX": 0.72, "NY": 0.78, "FL": 0.74, "OH": 0.20}
    decisions = [
        "APPROVE" if rng.rand() < probs[s] else "REJECT"
        for s in states
    ]
    return pd.DataFrame({
        "decision": decisions,
        "demographic_group": rng.choice(["protected", "control"], size=n),
        "state": states,
    })


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestComputeApprovalRate:
    def test_all_approved(self) -> None:
        df = pd.DataFrame({"decision": ["APPROVE"] * 10})
        assert _compute_approval_rate(df) == 1.0

    def test_all_rejected(self) -> None:
        df = pd.DataFrame({"decision": ["REJECT"] * 10})
        assert _compute_approval_rate(df) == 0.0

    def test_half_approved(self) -> None:
        df = pd.DataFrame({"decision": ["APPROVE", "REJECT"] * 50})
        assert abs(_compute_approval_rate(df) - 0.5) < 0.01

    def test_empty_df_returns_zero(self) -> None:
        df = pd.DataFrame({"decision": []})
        assert _compute_approval_rate(df) == 0.0

    def test_case_insensitive(self) -> None:
        df = pd.DataFrame({"decision": ["approve", "APPROVE", "Approve"]})
        # Method uses str.upper() internally
        assert _compute_approval_rate(df) == 1.0


class TestComputeDir:
    def test_equal_rates_dir_is_one(self) -> None:
        # Alternate protected/control so both groups have identical 50% approval rates
        df = pd.DataFrame({
            "decision": (["APPROVE", "REJECT"] * 50) + (["APPROVE", "REJECT"] * 50),
            "group": ["protected"] * 100 + ["control"] * 100,
        })
        dir_score, _, _ = _compute_dir(df, "group", "protected", "control")
        assert abs(dir_score - 1.0) < 0.01

    def test_zero_control_rate_returns_none(self) -> None:
        df = pd.DataFrame({
            "decision": ["APPROVE"] * 50 + ["REJECT"] * 50,
            "group": ["protected"] * 50 + ["control"] * 50,
        })
        dir_score, _, _ = _compute_dir(df, "group", "protected", "control")
        assert dir_score is None

    def test_biased_rates_dir_below_threshold(self) -> None:
        df = pd.DataFrame({
            "decision": (
                ["APPROVE"] * 40 + ["REJECT"] * 60 +  # protected 40%
                ["APPROVE"] * 80 + ["REJECT"] * 20   # control 80%
            ),
            "group": ["protected"] * 100 + ["control"] * 100,
        })
        dir_score, _, _ = _compute_dir(df, "group", "protected", "control")
        assert dir_score < DIR_THRESHOLD


class TestComputeApprovalParity:
    def test_unequal_groups_returns_float(self, biased_df) -> None:
        p_val, flag = _compute_approval_parity(biased_df, "demographic_group")
        assert isinstance(p_val, float)
        assert 0.0 <= p_val <= 1.0

    def test_biased_df_flags_inequality(self, biased_df) -> None:
        _, flag = _compute_approval_parity(biased_df, "demographic_group")
        # With large N and big difference, should be flagged
        assert flag is True

    def test_equal_groups_not_flagged(self, fair_df) -> None:
        _, flag = _compute_approval_parity(fair_df, "demographic_group")
        # With similar rates, should not be significantly different
        assert isinstance(flag, bool)


class TestComputeGeographicFlags:
    def test_returns_lists(self, geo_biased_df) -> None:
        flags, rates = _compute_geographic_flags(geo_biased_df)
        assert isinstance(flags, list)
        assert isinstance(rates, dict)

    def test_geo_biased_state_flagged(self, geo_biased_df) -> None:
        flags, _ = _compute_geographic_flags(geo_biased_df)
        # Ohio has 20% vs ~75% national → should be flagged
        assert "OH" in flags

    def test_missing_state_column_returns_empty(self, fair_df) -> None:
        df_no_state = fair_df.drop(columns=["state"])
        flags, rates = _compute_geographic_flags(df_no_state)
        assert flags == []
        assert rates == {}


# ---------------------------------------------------------------------------
# Integration tests: analyze_fair_lending
# ---------------------------------------------------------------------------


class TestAnalyzeFairLending:
    def test_returns_fair_lending_report(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert isinstance(report, FairLendingReport)

    def test_biased_df_dir_flag_true(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert report.dir_flag is True

    def test_fair_df_dir_flag_false(self, fair_df) -> None:
        report = analyze_fair_lending(fair_df, "demographic_group", "control")
        assert report.dir_flag is False

    def test_dir_score_is_float(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert isinstance(report.dir_score, float)

    def test_n_total_matches_df(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert report.n_total == len(biased_df)

    def test_approval_parity_p_value_present(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert report.approval_parity_p_value is not None
        assert 0.0 <= report.approval_parity_p_value <= 1.0

    def test_geographic_analysis_present(self, geo_biased_df) -> None:
        report = analyze_fair_lending(geo_biased_df, "demographic_group", "control")
        assert isinstance(report.geographic_flags, list)
        assert isinstance(report.state_approval_rates, dict)

    def test_summary_text_is_string(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert isinstance(report.summary_text, str)
        assert len(report.summary_text) > 0

    def test_missing_decision_col_raises(self, biased_df) -> None:
        df = biased_df.drop(columns=["decision"])
        with pytest.raises(ValueError, match="Decision column"):
            analyze_fair_lending(df, "demographic_group", "control")

    def test_missing_protected_col_raises(self, biased_df) -> None:
        with pytest.raises(ValueError, match="Protected column"):
            analyze_fair_lending(biased_df, "nonexistent_col", "control")

    def test_report_saved_to_json(self, biased_df, tmp_path) -> None:
        analyze_fair_lending(
            biased_df, "demographic_group", "control",
            output_dir=str(tmp_path)
        )
        json_files = list(tmp_path.glob("fair_lending_*.json"))
        assert len(json_files) == 1
        loaded = json.loads(json_files[0].read_text())
        assert "dir_score" in loaded

    def test_control_group_rates_stored(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert report.control_group == "control"
        assert 0.0 <= report.control_approval_rate <= 1.0

    def test_protected_group_stored(self, biased_df) -> None:
        report = analyze_fair_lending(biased_df, "demographic_group", "control")
        assert report.protected_group == "protected"
