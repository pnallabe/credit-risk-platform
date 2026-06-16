"""
Tests for explainability/lime_explainer.py
==========================================
Uses a small synthetic dataset and a RandomForestClassifier.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier

sys.path.insert(0, str(Path(__file__).parents[3]))

from explainability.lime_explainer import explain_with_lime

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
def rf_model():
    rng = np.random.RandomState(42)
    X = rng.rand(200, NUM_FEATURES)
    y = (X[:, 0] > 0.5).astype(int)
    clf = RandomForestClassifier(n_estimators=10, random_state=42)
    clf.fit(X, y)
    return clf, X


@pytest.fixture
def single_row_array():
    rng = np.random.RandomState(7)
    return rng.rand(NUM_FEATURES)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExplainWithLime:
    def test_returns_dict_with_required_keys(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        required_keys = {
            "feature_contributions",
            "prediction_probability",
            "intercept",
            "score",
            "explanation_text",
        }
        assert required_keys.issubset(set(result.keys()))

    def test_prediction_probability_in_range(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        assert 0.0 <= result["prediction_probability"] <= 1.0

    def test_feature_contributions_is_list(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        assert isinstance(result["feature_contributions"], list)
        assert len(result["feature_contributions"]) <= 5

    def test_contribution_dicts_have_correct_keys(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        for item in result["feature_contributions"]:
            assert "feature" in item
            assert "weight" in item
            assert "value" in item

    def test_accepts_dataframe_input(self, rf_model) -> None:
        model, training_data = rf_model
        rng = np.random.RandomState(3)
        row_df = pd.DataFrame(rng.rand(1, NUM_FEATURES), columns=FEATURE_NAMES)
        result = explain_with_lime(
            model, row_df, FEATURE_NAMES,
            num_features=3, num_samples=100, training_data=training_data,
        )
        assert "prediction_probability" in result

    def test_explanation_text_is_non_empty(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        assert isinstance(result["explanation_text"], str)
        assert len(result["explanation_text"]) > 0

    def test_score_is_float(self, rf_model, single_row_array) -> None:
        model, training_data = rf_model
        result = explain_with_lime(
            model, single_row_array, FEATURE_NAMES,
            num_features=5, num_samples=100, training_data=training_data,
        )
        assert isinstance(result["score"], float)
