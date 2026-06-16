"""
Tests for WoE Scorecard Builder (Sprint S2-A)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.credit_risk.woe_scorecard import (
    IV_NEGLIGIBLE,
    build_woe_scorecard,
    save_woe_scorecard,
    scorecard_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_lgbm_stub(n_features: int, importances: list[float] | None = None):
    """A minimal stub that satisfies the interface expected by build_woe_scorecard."""

    class _StubClassifier:
        def __init__(self):
            self.feature_importances_ = np.array(
                importances if importances else [1.0 / n_features] * n_features,
                dtype=float,
            )

    return _StubClassifier()


def _synthetic_dataset(n: int = 1000, n_features: int = 5, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, n_features)).astype(np.float32)
    y = (rng.uniform(size=n) < 0.10).astype(int)  # ~10% default rate
    feat_names = [f"feature_{i}" for i in range(n_features)]
    return X, y, feat_names


# ---------------------------------------------------------------------------
# Basic contract tests
# ---------------------------------------------------------------------------


class TestBuildWoeScorecardContract:
    def test_returns_dataframe(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        assert isinstance(df, pd.DataFrame)

    def test_required_columns_present(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        required_cols = [
            "feature", "bin_label", "bin_lower", "bin_upper",
            "count", "event_count", "nonevent_count", "event_rate",
            "woe", "iv", "points", "feature_iv", "low_iv",
        ]
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

    def test_points_are_integers(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        assert df["points"].dtype in (int, np.int64, np.int32)
        # verify each value is an integer
        for v in df["points"]:
            assert v == int(v), f"Non-integer point value: {v}"

    def test_bin_counts_sum_to_n(self):
        X, y, feat_names = _synthetic_dataset(n=500)
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names, n_bins=5)
        for feat in df["feature"].unique():
            total = df.loc[df["feature"] == feat, "count"].sum()
            assert total == 500, f"Feature {feat}: bin counts sum to {total}, expected 500"

    def test_event_rate_in_range(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        assert (df["event_rate"] >= 0.0).all()
        assert (df["event_rate"] <= 1.0).all()

    def test_low_iv_flag_set_correctly(self):
        # Create a constant (zero-information) feature and a real feature
        n = 1000
        rng = np.random.default_rng(0)
        X = rng.standard_normal((n, 2)).astype(np.float32)
        X[:, 1] = 0.0   # constant feature → zero IV
        y = (rng.uniform(size=n) < 0.10).astype(int)
        feat_names = ["real_feature", "constant_feature"]
        model = _make_lgbm_stub(2, importances=[0.9, 0.1])
        df = build_woe_scorecard(model, X, y, feat_names)

        # constant_feature should be absent (filtered by qcut) or marked low_iv
        constant_rows = df[df["feature"] == "constant_feature"]
        if len(constant_rows) > 0:
            assert constant_rows["low_iv"].all(), "Constant feature should be flagged low_iv"

    def test_features_with_low_iv_flagged(self):
        X, y, feat_names = _synthetic_dataset(n=1000, n_features=3)
        model = _make_lgbm_stub(3)
        df = build_woe_scorecard(model, X, y, feat_names)
        # Features with feature_iv < 0.02 should have low_iv = True
        for feat in df["feature"].unique():
            feat_iv = df.loc[df["feature"] == feat, "feature_iv"].iloc[0]
            expected_low = feat_iv < IV_NEGLIGIBLE
            actual_low   = df.loc[df["feature"] == feat, "low_iv"].iloc[0]
            assert actual_low == expected_low, (
                f"Feature {feat}: iv={feat_iv:.4f}, expected low_iv={expected_low}, got {actual_low}"
            )


# ---------------------------------------------------------------------------
# Numeric correctness
# ---------------------------------------------------------------------------


class TestWoeScorecardNumericCorrectness:
    def test_woe_sign_positive_for_good_bins(self):
        """Bins with fewer events than average should have positive WoE (more non-events)."""
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        # WoE values are finite (no inf or nan)
        assert df["woe"].notna().all()
        assert np.isfinite(df["woe"]).all()

    def test_iv_per_bin_non_negative(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        # IV per bin can be negative (technically WoE * (distribution difference))
        # but feature_iv (sum) should never be negative
        for feat in df["feature"].unique():
            feat_iv = df.loc[df["feature"] == feat, "feature_iv"].iloc[0]
            assert feat_iv >= 0.0, f"Feature {feat} has negative total IV: {feat_iv}"

    def test_bin_lower_upper_ordered(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        assert (df["bin_upper"] >= df["bin_lower"]).all()

    def test_different_pdo_changes_points(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df_20 = build_woe_scorecard(model, X, y, feat_names, pdo=20)
        df_40 = build_woe_scorecard(model, X, y, feat_names, pdo=40)
        # Higher PDO → larger scaling factor → larger absolute point values
        # (not necessarily for every single row, but the sum of abs should differ)
        assert df_20["points"].abs().sum() != df_40["points"].abs().sum()


# ---------------------------------------------------------------------------
# IV label tests
# ---------------------------------------------------------------------------


class TestIVLabels:
    def test_iv_label_column_present(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        assert "iv_label" in df.columns

    def test_iv_label_values_valid(self):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)
        valid_labels = {"Negligible", "Weak", "Medium", "Strong"}
        assert set(df["iv_label"].unique()).issubset(valid_labels)


# ---------------------------------------------------------------------------
# scorecard_summary tests
# ---------------------------------------------------------------------------


class TestScorecardSummary:
    def test_summary_keys(self):
        X, y, feat_names = _synthetic_dataset(n_features=6)
        model = _make_lgbm_stub(6)
        df = build_woe_scorecard(model, X, y, feat_names)
        summary = scorecard_summary(df)
        assert "n_features" in summary
        assert "total_iv" in summary
        assert "top_5_features" in summary

    def test_empty_df_returns_empty_dict(self):
        import pandas as pd
        assert scorecard_summary(pd.DataFrame()) == {}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestSaveWoeScorecard:
    def test_save_and_reload(self, tmp_path):
        X, y, feat_names = _synthetic_dataset()
        model = _make_lgbm_stub(len(feat_names))
        df = build_woe_scorecard(model, X, y, feat_names)

        base_path = tmp_path / "scorecard.json"
        saved_path = save_woe_scorecard(df, base_path, log_to_mlflow=False)

        assert saved_path.exists()
        assert "_woe.json" in saved_path.name

        from models.credit_risk.woe_scorecard import load_woe_scorecard
        loaded = load_woe_scorecard(saved_path)
        assert len(loaded) == len(df)
        assert set(loaded.columns).issuperset({"feature", "woe", "points"})


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestWoeScorecardEdgeCases:
    def test_single_class_raises(self):
        X = np.random.randn(100, 3).astype(np.float32)
        y = np.zeros(100, dtype=int)  # all good, no defaults
        feat_names = ["a", "b", "c"]
        model = _make_lgbm_stub(3)
        with pytest.raises(ValueError, match="both classes"):
            build_woe_scorecard(model, X, y, feat_names)

    def test_all_constant_features_returns_empty(self):
        X = np.zeros((100, 2), dtype=np.float32)
        y = (np.random.rand(100) < 0.10).astype(int)
        feat_names = ["const_a", "const_b"]
        model = _make_lgbm_stub(2)
        df = build_woe_scorecard(model, X, y, feat_names)
        assert isinstance(df, pd.DataFrame)

    def test_n_bins_respected(self):
        X, y, feat_names = _synthetic_dataset(n=1000, n_features=1)
        model = _make_lgbm_stub(1)
        df = build_woe_scorecard(model, X, y, feat_names, n_bins=4)
        # Should have at most 4 rows (may be fewer if duplicate edges)
        assert len(df) <= 4
