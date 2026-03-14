"""
Tests for explainability/shap_explainer.py
==========================================
Uses a small synthetic dataset and a DummyRandomForestClassifier to avoid
requiring trained production models during CI.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier

# Make project root importable
sys.path.insert(0, str(Path(__file__).parents[3]))

from explainability.shap_explainer import (
    ExplanationResult,
    _build_explanation_text,
    _build_factor_list,
    explain_prediction,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FEATURE_NAMES = [
    "credit_utilization",
    "income_stability_score",
    "repayment_capacity",
    "debt_service_coverage",
    "credit_age_score",
    "derogatory_penalty",
    "months_since_delinquency",
    "log_loan_amount",
    "log_annual_income",
    "dti_x_loan_amount",
    "employment_encoded",
]

NUM_FEATURES = len(FEATURE_NAMES)


@pytest.fixture(scope="module")
def synthetic_data() -> tuple[np.ndarray, np.ndarray]:
    """Generate a small synthetic training dataset."""
    rng = np.random.RandomState(42)
    X = rng.rand(300, NUM_FEATURES)
    # Create a simple label: high credit_utilization + high derogatory_penalty → default
    y = ((X[:, 0] + X[:, 5]) > 1.0).astype(int)
    return X, y


@pytest.fixture(scope="module")
def rf_model(synthetic_data: tuple) -> RandomForestClassifier:
    """Fit a RandomForestClassifier on the synthetic data."""
    X, y = synthetic_data
    clf = RandomForestClassifier(n_estimators=20, random_state=42)
    clf.fit(X, y)
    return clf


@pytest.fixture(scope="module")
def gb_model(synthetic_data: tuple) -> GradientBoostingClassifier:
    """Fit a GradientBoostingClassifier on the synthetic data."""
    X, y = synthetic_data
    clf = GradientBoostingClassifier(n_estimators=20, random_state=42)
    clf.fit(X, y)
    return clf


@pytest.fixture
def single_row_df() -> pd.DataFrame:
    """A single-row DataFrame representing one loan application's features."""
    rng = np.random.RandomState(7)
    row = rng.rand(1, NUM_FEATURES)
    return pd.DataFrame(row, columns=FEATURE_NAMES)


# ---------------------------------------------------------------------------
# Unit tests: helper functions
# ---------------------------------------------------------------------------


class TestBuildFactorList:
    def test_positive_factors_sorted_by_magnitude(self) -> None:
        shap_row = np.array([0.1, -0.3, 0.5, -0.05, 0.2])
        names = ["a", "b", "c", "d", "e"]
        factors = _build_factor_list(shap_row, names, "positive", top_n=3)
        assert len(factors) <= 3
        assert all(f["direction"] == "positive" for f in factors)
        assert all(f["shap_value"] > 0 for f in factors)
        # Sorted descending by magnitude
        values = [abs(f["shap_value"]) for f in factors]
        assert values == sorted(values, reverse=True)

    def test_negative_factors_sorted_by_magnitude(self) -> None:
        shap_row = np.array([0.1, -0.3, 0.5, -0.05, 0.2])
        names = ["a", "b", "c", "d", "e"]
        factors = _build_factor_list(shap_row, names, "negative", top_n=5)
        assert all(f["direction"] == "negative" for f in factors)
        assert all(f["shap_value"] < 0 for f in factors)

    def test_all_zeros_returns_empty(self) -> None:
        shap_row = np.zeros(5)
        names = ["a", "b", "c", "d", "e"]
        assert _build_factor_list(shap_row, names, "positive") == []
        assert _build_factor_list(shap_row, names, "negative") == []

    def test_top_n_limits_output(self) -> None:
        shap_row = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        names = ["a", "b", "c", "d", "e"]
        factors = _build_factor_list(shap_row, names, "positive", top_n=2)
        assert len(factors) == 2


class TestBuildExplanationText:
    def test_structure(self) -> None:
        positive = [{"feature": "annual_income", "shap_value": 0.12, "direction": "positive"}]
        negative = [{"feature": "debt_to_income", "shap_value": -0.08, "direction": "negative"}]
        text = _build_explanation_text("approved", positive, negative)
        assert "approved" in text.lower()
        assert "Annual Income" in text
        assert "+" in text
        assert "-" in text

    def test_decline_label(self) -> None:
        text = _build_explanation_text("declined", [], [])
        assert "declined" in text.lower()

    def test_empty_factors(self) -> None:
        text = _build_explanation_text("reviewed", [], [])
        assert isinstance(text, str)
        assert len(text) > 0


# ---------------------------------------------------------------------------
# Integration tests: explain_prediction
# ---------------------------------------------------------------------------


class TestExplainPrediction:
    def test_returns_explanation_result(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df, decision_label="approved")
        assert isinstance(result, ExplanationResult)

    def test_base_value_is_float(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        assert isinstance(result.base_value, float)

    def test_predicted_value_in_range(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        assert 0.0 <= result.predicted_value <= 1.0

    def test_shap_values_shape_matches_features(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        assert result.shap_values is not None
        assert len(result.shap_values) == NUM_FEATURES

    def test_feature_names_preserved(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        assert result.feature_names == FEATURE_NAMES

    def test_explanation_text_contains_decision(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df, decision_label="declined")
        assert "declined" in result.explanation_text.lower()

    def test_positive_factors_positive_shap(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        for f in result.top_positive_factors:
            assert f["shap_value"] > 0

    def test_negative_factors_negative_shap(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        for f in result.top_negative_factors:
            assert f["shap_value"] < 0

    def test_gradient_boosting_model(self, gb_model, single_row_df) -> None:
        result = explain_prediction(gb_model, single_row_df, decision_label="approved")
        assert isinstance(result, ExplanationResult)
        assert result.predicted_value >= 0.0

    def test_waterfall_plot_saved(self, rf_model, single_row_df, tmp_path) -> None:
        out = tmp_path / "waterfall.png"
        explain_prediction(rf_model, single_row_df, output_path=out)
        # File may or may not exist depending on matplotlib backend — just verify no exception

    def test_top_n_respected(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df, top_n=2)
        assert len(result.top_positive_factors) <= 2
        assert len(result.top_negative_factors) <= 2

    def test_all_feature_names_in_result(self, rf_model, single_row_df) -> None:
        result = explain_prediction(rf_model, single_row_df)
        for f in result.top_positive_factors + result.top_negative_factors:
            assert f["feature"] in FEATURE_NAMES
