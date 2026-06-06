"""
Tests for SMB PD Model Training Script (Sprint S2-B)
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_synthetic_smb(n: int = 500):
    from models.credit_risk.train_smb_pd_model import generate_synthetic_smb_data
    return generate_synthetic_smb_data(n=n)


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------


class TestGenerateSyntheticSMBData:
    def test_returns_dataframe(self):
        import pandas as pd
        df = _get_synthetic_smb(200)
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self):
        from models.credit_risk.train_smb_pd_model import (
            NUMERIC_COLS, CATEGORICAL_COLS, BOOL_COLS, TARGET
        )
        df = _get_synthetic_smb(100)
        for col in NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS + [TARGET]:
            assert col in df.columns, f"Missing column: {col}"

    def test_default_rate_reasonable(self):
        df = _get_synthetic_smb(2000)
        rate = df["default_flag"].mean()
        # Expect ~12% ± 5%
        assert 0.05 <= rate <= 0.25, f"Default rate {rate:.2%} out of expected range"

    def test_reproducible_with_seed(self):
        from models.credit_risk.train_smb_pd_model import generate_synthetic_smb_data
        df1 = generate_synthetic_smb_data(n=100, seed=42)
        df2 = generate_synthetic_smb_data(n=100, seed=42)
        assert (df1["owner_fico"] == df2["owner_fico"]).all()

    def test_dscr_range(self):
        df = _get_synthetic_smb(500)
        assert (df["dscr"] >= 0.4).all()
        assert (df["dscr"] <= 3.1).all()

    def test_owner_fico_range(self):
        df = _get_synthetic_smb(500)
        assert (df["owner_fico"] >= 449).all()
        assert (df["owner_fico"] <= 851).all()

    def test_legal_entity_types(self):
        df = _get_synthetic_smb(500)
        expected = {"LLC", "S-Corp", "C-Corp", "Sole-Prop"}
        assert set(df["legal_entity_type"].unique()).issubset(expected)


# ---------------------------------------------------------------------------
# Feature matrix
# ---------------------------------------------------------------------------


class TestFeatureMatrix:
    def test_shape_correct(self):
        from models.credit_risk.train_smb_pd_model import (
            NUMERIC_COLS, CATEGORICAL_COLS, BOOL_COLS, feature_matrix, load_and_prep
        )
        df, _ = load_and_prep(None, sample=200)
        X, y, feat_names = feature_matrix(df)
        n_expected = sum(1 for c in NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS if c in df.columns)
        assert X.shape == (200, n_expected)
        assert y.shape == (200,)
        assert len(feat_names) == n_expected

    def test_no_nan_in_x(self):
        from models.credit_risk.train_smb_pd_model import feature_matrix, load_and_prep
        df, _ = load_and_prep(None, sample=200)
        X, y, _ = feature_matrix(df)
        assert not np.isnan(X).any(), "NaN values in feature matrix"

    def test_y_is_binary(self):
        from models.credit_risk.train_smb_pd_model import feature_matrix, load_and_prep
        df, _ = load_and_prep(None, sample=200)
        _, y, _ = feature_matrix(df)
        assert set(y.tolist()).issubset({0, 1})


# ---------------------------------------------------------------------------
# Smoke test: train → predict → correct shape
# ---------------------------------------------------------------------------


class TestSMBModelSmoke:
    @pytest.fixture(scope="module")
    def trained_model(self):
        """Train a tiny SMB model for testing."""
        from models.credit_risk.train_smb_pd_model import (
            feature_matrix, load_and_prep
        )
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV
        from models.credit_risk.train_smb_pd_model import MONOTONE_CONSTRAINT_MAP

        df, _ = load_and_prep(None, sample=300)
        X, y, feat_names = feature_matrix(df)
        constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]

        params = dict(
            n_estimators=50, learning_rate=0.1, max_depth=4, num_leaves=15,
            min_child_samples=10, monotone_constraints=constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=1,
        )
        raw_model = lgb.LGBMClassifier(**params)
        raw_model.fit(X, y)
        cal_model = CalibratedClassifierCV(raw_model, method="isotonic", cv="prefit")
        cal_model.fit(X, y)
        return cal_model, X, y, feat_names

    def test_predict_shape(self, trained_model):
        model, X, y, _ = trained_model
        preds = model.predict_proba(X)[:, 1]
        assert preds.shape == (len(X),)

    def test_predict_range(self, trained_model):
        model, X, y, _ = trained_model
        preds = model.predict_proba(X)[:, 1]
        assert (preds >= 0.0).all()
        assert (preds <= 1.0).all()

    def test_both_classes_predicted(self, trained_model):
        model, X, y, _ = trained_model
        preds = model.predict_proba(X)[:, 1]
        # Predictions should span some range (not all identical)
        assert preds.max() - preds.min() > 0.01


# ---------------------------------------------------------------------------
# Monotonicity
# ---------------------------------------------------------------------------


class TestSMBMonotonicity:
    def test_verify_monotonicity_passes(self):
        """Train a small model and verify monotonicity check doesn't raise."""
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV
        from models.credit_risk.train_smb_pd_model import (
            MONOTONE_CONSTRAINT_MAP, feature_matrix, load_and_prep, verify_monotonicity
        )

        df, _ = load_and_prep(None, sample=500)
        X, y, feat_names = feature_matrix(df)
        constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]

        params = dict(
            n_estimators=100, learning_rate=0.1, max_depth=4, num_leaves=15,
            min_child_samples=20, monotone_constraints=constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=1,
        )
        raw_model = lgb.LGBMClassifier(**params)
        raw_model.fit(X, y)
        cal_model = CalibratedClassifierCV(raw_model, method="isotonic", cv="prefit")
        cal_model.fit(X, y)

        # Should not raise
        results = verify_monotonicity(cal_model, X, feat_names)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# WoE Scorecard
# ---------------------------------------------------------------------------


class TestSMBWoeScorecard:
    def test_woe_scorecard_structure(self):
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV
        from models.credit_risk.train_smb_pd_model import (
            MONOTONE_CONSTRAINT_MAP, feature_matrix, load_and_prep
        )
        from models.credit_risk.woe_scorecard import build_woe_scorecard

        df, _ = load_and_prep(None, sample=300)
        X, y, feat_names = feature_matrix(df)
        constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]

        raw_model = lgb.LGBMClassifier(
            n_estimators=50, learning_rate=0.1, max_depth=4, num_leaves=15,
            min_child_samples=10, monotone_constraints=constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=1,
        )
        raw_model.fit(X, y)
        cal_model = CalibratedClassifierCV(raw_model, method="isotonic", cv="prefit")
        cal_model.fit(X, y)

        woe_df = build_woe_scorecard(cal_model, X, y, feat_names, n_bins=5)
        assert "feature" in woe_df.columns
        assert "woe" in woe_df.columns
        assert "points" in woe_df.columns
        assert len(woe_df) > 0
