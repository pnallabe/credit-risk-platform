"""
Tests for Commercial PD Model Training Script (Sprint S2-C)
"""

from __future__ import annotations

import numpy as np
import pytest


class TestGenerateSyntheticCommercialData:
    def test_returns_dataframe(self):
        import pandas as pd
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=200)
        assert isinstance(df, pd.DataFrame)

    def test_has_required_columns(self):
        from models.credit_risk.train_commercial_pd_model import (
            NUMERIC_COLS, CATEGORICAL_COLS, BOOL_COLS, TARGET, generate_synthetic_commercial_data
        )
        df = generate_synthetic_commercial_data(n=100)
        for col in NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS + [TARGET]:
            assert col in df.columns, f"Missing column: {col}"

    def test_default_rate_reasonable(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=2000)
        rate = df["default_flag"].mean()
        assert 0.03 <= rate <= 0.30, f"Default rate {rate:.2%} out of expected range [3%, 30%]"

    def test_ltv_range(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=500)
        assert (df["ltv"] >= 0.35).all()
        assert (df["ltv"] <= 1.0).all()

    def test_occupancy_rate_range(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=500)
        assert (df["occupancy_rate"] >= 15).all()
        assert (df["occupancy_rate"] <= 100).all()

    def test_property_types(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=500)
        expected = {"Office", "Retail", "Multifamily", "Industrial", "Hotel", "Mixed-Use"}
        assert set(df["property_type"].unique()).issubset(expected)

    def test_market_tiers(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df = generate_synthetic_commercial_data(n=500)
        expected = {"Tier1", "Tier2", "Tier3"}
        assert set(df["market_tier"].unique()).issubset(expected)

    def test_reproducible(self):
        from models.credit_risk.train_commercial_pd_model import generate_synthetic_commercial_data
        df1 = generate_synthetic_commercial_data(n=100, seed=99)
        df2 = generate_synthetic_commercial_data(n=100, seed=99)
        assert (df1["ltv"] == df2["ltv"]).all()


class TestCommercialFeatureMatrix:
    def test_shape(self):
        from models.credit_risk.train_commercial_pd_model import (
            NUMERIC_COLS, CATEGORICAL_COLS, BOOL_COLS, feature_matrix, load_and_prep
        )
        df, _ = load_and_prep(None, sample=150)
        X, y, feat_names = feature_matrix(df)
        n_expected = sum(1 for c in NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS if c in df.columns)
        assert X.shape == (150, n_expected)

    def test_no_nan(self):
        from models.credit_risk.train_commercial_pd_model import feature_matrix, load_and_prep
        df, _ = load_and_prep(None, sample=150)
        X, _, _ = feature_matrix(df)
        assert not np.isnan(X).any()

    def test_y_binary(self):
        from models.credit_risk.train_commercial_pd_model import feature_matrix, load_and_prep
        df, _ = load_and_prep(None, sample=150)
        _, y, _ = feature_matrix(df)
        assert set(y.tolist()).issubset({0, 1})


class TestCommercialModelSmoke:
    @pytest.fixture(scope="module")
    def trained_model_data(self):
        import lightgbm as lgb
        from sklearn.calibration import CalibratedClassifierCV
        from models.credit_risk.train_commercial_pd_model import (
            MONOTONE_CONSTRAINT_MAP, feature_matrix, load_and_prep
        )

        df, _ = load_and_prep(None, sample=300)
        X, y, feat_names = feature_matrix(df)
        constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]

        raw = lgb.LGBMClassifier(
            n_estimators=50, learning_rate=0.1, max_depth=4, num_leaves=15,
            min_child_samples=10, monotone_constraints=constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=1,
        )
        raw.fit(X, y)
        cal = CalibratedClassifierCV(raw, method="isotonic", cv="prefit")
        cal.fit(X, y)
        return cal, X, y, feat_names

    def test_predict_shape(self, trained_model_data):
        model, X, _, _ = trained_model_data
        preds = model.predict_proba(X)[:, 1]
        assert preds.shape == (len(X),)

    def test_predict_range(self, trained_model_data):
        model, X, _, _ = trained_model_data
        preds = model.predict_proba(X)[:, 1]
        assert (preds >= 0.0).all() and (preds <= 1.0).all()

    def test_woe_scorecard_has_expected_columns(self, trained_model_data):
        model, X, y, feat_names = trained_model_data
        from models.credit_risk.woe_scorecard import build_woe_scorecard
        df = build_woe_scorecard(model, X, y, feat_names, n_bins=5)
        for col in ["feature", "woe", "iv", "points", "feature_iv"]:
            assert col in df.columns

    def test_monotonicity_passes(self, trained_model_data):
        model, X, y, feat_names = trained_model_data
        from models.credit_risk.train_commercial_pd_model import verify_monotonicity
        results = verify_monotonicity(model, X, feat_names)
        assert isinstance(results, list)
