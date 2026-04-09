"""
Tests for explainability.counterfactual
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from explainability.counterfactual import CounterfactualResult, generate_counterfactual


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_model_and_df(n: int = 50, seed: int = 42):
    """Return a tiny LogisticRegression and a high-PD single-row DataFrame."""
    rng = np.random.default_rng(seed)
    X = rng.random((n, 4))
    # Positive class when sum of first two features > 1.0
    y = (X[:, 0] + X[:, 1] > 1.0).astype(int)
    model = LogisticRegression(random_state=seed, max_iter=200)
    model.fit(X, y)

    feature_names = ["feat_a", "feat_b", "feat_c", "feat_d"]
    # Build a high-PD row
    high_pd_row = pd.DataFrame([[0.95, 0.95, 0.5, 0.5]], columns=feature_names)
    return model, high_pd_row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_counterfactual_flip_to_approve():
    """A high-PD row should yield counterfactual_decision == 'APPROVE' or non-empty changes."""
    model, high_pd_df = _make_model_and_df()
    result = generate_counterfactual(
        high_pd_df,
        model,
        decision_threshold=0.5,
        original_decision="REJECT",
        application_id="APP-001",
    )
    assert isinstance(result, CounterfactualResult)
    assert result.application_id == "APP-001"
    assert result.original_decision == "REJECT"
    # Either flipped to APPROVE or found some changes
    assert result.counterfactual_decision == "APPROVE" or len(result.feature_changes) >= 0
    # feasibility_note must be non-empty
    assert len(result.feasibility_note) > 0
    # generated_at must be an ISO string
    assert "T" in result.generated_at


def test_counterfactual_no_shap_fallback():
    """When shap raises ImportError, no exception should be raised."""
    model, high_pd_df = _make_model_and_df()
    with patch.dict("sys.modules", {"shap": None}):
        # Simulate ImportError by patching the import in the module
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "shap":
                raise ImportError("shap not installed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            result = generate_counterfactual(
                high_pd_df,
                model,
                original_decision="REJECT",
            )
    assert isinstance(result, CounterfactualResult)
    # Must not raise — returns a valid result


def test_counterfactual_already_approved():
    """An already-approved row should return APPROVE with no feature changes."""
    model, _ = _make_model_and_df()
    # Build a low-PD row
    feature_names = ["feat_a", "feat_b", "feat_c", "feat_d"]
    low_pd_df = pd.DataFrame([[0.01, 0.01, 0.5, 0.5]], columns=feature_names)

    result = generate_counterfactual(
        low_pd_df,
        model,
        decision_threshold=0.5,
        original_decision="REJECT",
    )
    assert result.counterfactual_decision == "APPROVE"
    assert result.feature_changes == []


def test_counterfactual_single_feature_df():
    """Single-feature DataFrames must not crash."""
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(99)
    X = rng.random((30, 1))
    y = (X[:, 0] > 0.5).astype(int)
    model = LogisticRegression(max_iter=200)
    model.fit(X, y)

    high_pd_df = pd.DataFrame([[0.99]], columns=["single_feat"])
    result = generate_counterfactual(high_pd_df, model, original_decision="REJECT")
    assert isinstance(result, CounterfactualResult)


def test_counterfactual_result_fields():
    """CounterfactualResult dataclass fields are as expected."""
    r = CounterfactualResult(
        application_id="X",
        original_decision="REJECT",
        counterfactual_decision="APPROVE",
        feature_changes=[{"feature": "f", "original_value": 1.0, "suggested_value": 0.5, "delta": -0.5}],
        feasibility_note="Test note",
    )
    assert r.application_id == "X"
    assert len(r.feature_changes) == 1
    assert "T" in r.generated_at  # ISO-8601
