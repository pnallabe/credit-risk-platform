"""
Tests for monitoring/drift_monitor.py
======================================
Uses synthetic DataFrames for fully offline, reproducible testing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from monitoring.drift_monitor import (
    _compute_psi,
    _psi_status,
    monitor_drift,
    DriftReport,
    FeatureDriftResult,
    STATUS_MAJOR,
    STATUS_MINOR,
    STATUS_STABLE,
    PSI_STABLE_THRESHOLD,
    PSI_MINOR_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FEATURES = [
    "credit_utilization",
    "income_stability_score",
    "repayment_capacity",
    "debt_service_coverage",
    "credit_age_score",
]


@pytest.fixture
def reference_df() -> pd.DataFrame:
    """Stable reference distribution (uniform [0, 1] per feature)."""
    rng = np.random.RandomState(42)
    return pd.DataFrame(
        rng.uniform(0, 1, (1000, len(FEATURES))), columns=FEATURES
    )


@pytest.fixture
def stable_prod_df(reference_df) -> pd.DataFrame:
    """Production data with same distribution — no drift expected."""
    rng = np.random.RandomState(99)
    return pd.DataFrame(
        rng.uniform(0, 1, (500, len(FEATURES))), columns=FEATURES
    )


@pytest.fixture
def drifted_prod_df() -> pd.DataFrame:
    """Production data with significantly shifted distribution — drift expected."""
    rng = np.random.RandomState(7)
    # Shift all features to uniform [0.5, 1.5] instead of [0, 1]
    return pd.DataFrame(
        rng.uniform(0.5, 1.5, (500, len(FEATURES))), columns=FEATURES
    )


# ---------------------------------------------------------------------------
# Unit tests: _compute_psi
# ---------------------------------------------------------------------------


class TestComputePsi:
    def test_identical_distributions_psi_near_zero(self, reference_df) -> None:
        rng = np.random.RandomState(42)
        same = rng.uniform(0, 1, 1000)
        ref = reference_df["credit_utilization"].values
        psi = _compute_psi(ref, same)
        assert psi < PSI_STABLE_THRESHOLD

    def test_different_distributions_psi_positive(self, reference_df) -> None:
        rng = np.random.RandomState(7)
        shifted = rng.uniform(0.5, 1.5, 1000)
        ref = reference_df["credit_utilization"].values
        psi = _compute_psi(ref, shifted)
        assert psi > 0

    def test_extreme_shift_psi_exceeds_minor_threshold(self) -> None:
        rng = np.random.RandomState(1)
        ref = rng.normal(0, 1, 2000)
        prod = rng.normal(5, 1, 2000)  # completely different distribution
        psi = _compute_psi(ref, prod)
        assert psi > PSI_MINOR_THRESHOLD, f"Expected high PSI, got {psi}"

    def test_psi_non_negative(self, reference_df) -> None:
        rng = np.random.RandomState(5)
        ref = reference_df["credit_utilization"].values
        prod = rng.uniform(0, 2, 200)
        assert _compute_psi(ref, prod) >= 0

    def test_degenerate_case_single_unique_value(self) -> None:
        ref = np.ones(100)
        prod = np.ones(50)
        psi = _compute_psi(ref, prod)
        assert isinstance(psi, float)


class TestPsiStatus:
    def test_below_stable_threshold(self) -> None:
        assert _psi_status(0.05) == STATUS_STABLE

    def test_between_stable_and_minor(self) -> None:
        assert _psi_status(0.15) == STATUS_MINOR

    def test_above_minor_threshold(self) -> None:
        assert _psi_status(0.30) == STATUS_MAJOR

    def test_exactly_at_stable_threshold(self) -> None:
        # 0.10 is not < 0.10, so it's minor
        assert _psi_status(PSI_STABLE_THRESHOLD) == STATUS_MINOR

    def test_exactly_at_minor_threshold(self) -> None:
        # 0.25 is not < 0.25, so it's major
        assert _psi_status(PSI_MINOR_THRESHOLD) == STATUS_MAJOR


# ---------------------------------------------------------------------------
# Integration tests: monitor_drift
# ---------------------------------------------------------------------------


class TestMonitorDrift:
    def test_returns_drift_report(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        assert isinstance(report, DriftReport)

    def test_stable_distribution_no_major_drift(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        assert report.overall_drift_status in (STATUS_STABLE, STATUS_MINOR)

    def test_drifted_distribution_detected(self, reference_df, drifted_prod_df) -> None:
        report = monitor_drift(reference_df, drifted_prod_df, FEATURES)
        # Significantly shifted distribution should have at least minor or major drift
        assert report.overall_drift_status in (STATUS_MINOR, STATUS_MAJOR)

    def test_feature_results_count(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        assert len(report.feature_results) == len(FEATURES)

    def test_feature_results_have_correct_type(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        for fr in report.feature_results:
            assert isinstance(fr, FeatureDriftResult)

    def test_psi_non_negative_for_all_features(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        for fr in report.feature_results:
            assert fr.psi >= 0, f"Negative PSI for {fr.feature_name}"

    def test_ks_p_value_in_range(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        for fr in report.feature_results:
            assert 0.0 <= fr.ks_p_value <= 1.0

    def test_major_drift_in_features_list(self, reference_df, drifted_prod_df) -> None:
        report = monitor_drift(reference_df, drifted_prod_df, FEATURES)
        for feature_name in report.features_with_major_drift:
            assert feature_name in FEATURES

    def test_report_has_row_counts(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        assert report.n_reference_rows == len(reference_df)
        assert report.n_production_rows == len(stable_prod_df)

    def test_missing_features_skipped_gracefully(self, reference_df, stable_prod_df) -> None:
        features_with_missing = FEATURES + ["nonexistent_feature"]
        report = monitor_drift(reference_df, stable_prod_df, features_with_missing)
        # Should not raise, and only valid features are in results
        result_names = [fr.feature_name for fr in report.feature_results]
        assert "nonexistent_feature" not in result_names

    def test_report_saved_to_json(self, reference_df, stable_prod_df, tmp_path) -> None:
        monitor_drift(reference_df, stable_prod_df, FEATURES, output_dir=str(tmp_path))
        json_files = list(tmp_path.glob("drift_report_*.json"))
        assert len(json_files) == 1
        loaded = json.loads(json_files[0].read_text())
        assert "overall_drift_status" in loaded

    def test_timestamp_is_iso_format(self, reference_df, stable_prod_df) -> None:
        from datetime import datetime
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        # Should parse without error
        datetime.fromisoformat(report.report_timestamp.replace("Z", "+00:00"))

    def test_reference_mean_close_to_expected(self, reference_df, stable_prod_df) -> None:
        report = monitor_drift(reference_df, stable_prod_df, FEATURES)
        for fr in report.feature_results:
            # Uniform[0,1] → mean ≈ 0.5
            assert 0.3 < fr.reference_mean < 0.7, (
                f"{fr.feature_name} reference mean {fr.reference_mean} not near 0.5"
            )
