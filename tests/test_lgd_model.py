"""
Tests for LGD Model (Sprint S2-D)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Synthetic data generator
# ---------------------------------------------------------------------------


class TestGenerateSyntheticLGDData:
    def test_returns_dataframe(self):
        from models.lgd.train_lgd_model import generate_synthetic_lgd_data
        df = generate_synthetic_lgd_data(n=200)
        assert isinstance(df, pd.DataFrame)

    def test_has_feature_and_target_columns(self):
        from models.lgd.train_lgd_model import FEATURES, TARGET, generate_synthetic_lgd_data
        df = generate_synthetic_lgd_data(n=100)
        for col in FEATURES + [TARGET]:
            assert col in df.columns, f"Missing column: {col}"

    def test_target_in_range(self):
        from models.lgd.train_lgd_model import generate_synthetic_lgd_data, TARGET
        df = generate_synthetic_lgd_data(n=500)
        assert (df[TARGET] >= 0.0).all()
        assert (df[TARGET] <= 1.0).all()

    def test_secured_lower_lgd_than_unsecured_on_average(self):
        from models.lgd.train_lgd_model import generate_synthetic_lgd_data, TARGET
        df = generate_synthetic_lgd_data(n=2000)
        # Collateral type 5 = "Unsecured", types 0-2 = secured
        secured   = df[df["collateral_type_encoded"].isin([0, 1, 2])][TARGET].mean()
        unsecured = df[df["collateral_type_encoded"] == 5][TARGET].mean()
        assert secured < unsecured, (
            f"Expected secured LGD ({secured:.2f}) < unsecured LGD ({unsecured:.2f})"
        )


# ---------------------------------------------------------------------------
# LGD model training (small synthetic run)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def trained_lgd_artefact():
    """Train a minimal LGD model on synthetic data."""
    import lightgbm as lgb
    from models.lgd.train_lgd_model import (
        FEATURES, TARGET, SigmoidLGBMRegressor, feature_matrix,
        generate_synthetic_lgd_data,
    )

    df = generate_synthetic_lgd_data(n=500)
    X, y = feature_matrix(df)

    params = dict(
        n_estimators=50, learning_rate=0.1, max_depth=4, num_leaves=15,
        min_child_samples=10, objective="regression",
        random_state=42, verbose=-1, n_jobs=1,
    )
    raw = lgb.LGBMRegressor(**params)
    raw.fit(X, y)
    model = SigmoidLGBMRegressor(raw)
    return model, X, y


class TestLGDModelContract:
    def test_predict_shape(self, trained_lgd_artefact):
        model, X, _ = trained_lgd_artefact
        preds = model.predict(X)
        assert preds.shape == (len(X),)

    def test_predict_range_zero_to_one(self, trained_lgd_artefact):
        model, X, _ = trained_lgd_artefact
        preds = model.predict(X)
        assert preds.min() >= 0.0, f"LGD below 0: min={preds.min():.6f}"
        assert preds.max() <= 1.0, f"LGD above 1: max={preds.max():.6f}"

    def test_predict_not_all_identical(self, trained_lgd_artefact):
        model, X, _ = trained_lgd_artefact
        preds = model.predict(X)
        assert preds.std() > 1e-4, "LGD predictions are all identical"

    def test_feature_importances_available(self, trained_lgd_artefact):
        model, X, _ = trained_lgd_artefact
        imp = model.feature_importances_
        assert len(imp) == X.shape[1]


# ---------------------------------------------------------------------------
# predict_lgd() API
# ---------------------------------------------------------------------------


class TestPredictLGDAPI:
    def test_returns_dataframe_with_expected_columns(self):
        from models.lgd.predict import predict_lgd
        df_in = pd.DataFrame({
            "collateral_type_encoded": [0.0, 5.0],
            "ltv": [0.70, 0.0],
            "loan_term_months": [60.0, 36.0],
            "product_type_encoded": [0.0, 3.0],
            "borrower_segment_encoded": [0.0, 1.0],
            "fico_score": [720.0, 580.0],
            "dti": [0.28, 0.48],
            "months_on_book": [12.0, 6.0],
            "economic_cycle": [0.0, 1.0],
        })
        result = predict_lgd(df_in)
        assert "lgd_score" in result.columns
        assert "lgd_band"  in result.columns
        assert len(result) == 2

    def test_lgd_score_in_range(self):
        from models.lgd.predict import predict_lgd
        df_in = pd.DataFrame({col: [0.0] for col in [
            "collateral_type_encoded", "ltv", "loan_term_months",
            "product_type_encoded", "borrower_segment_encoded",
            "fico_score", "dti", "months_on_book", "economic_cycle",
        ]})
        result = predict_lgd(df_in)
        assert 0.0 <= result.iloc[0]["lgd_score"] <= 1.0

    def test_lgd_band_values_valid(self):
        from models.lgd.predict import predict_lgd
        df_in = pd.DataFrame({col: [0.0, 0.5, 1.0] for col in [
            "collateral_type_encoded", "ltv", "loan_term_months",
            "product_type_encoded", "borrower_segment_encoded",
            "fico_score", "dti", "months_on_book", "economic_cycle",
        ]})
        result = predict_lgd(df_in)
        valid_bands = {"Low", "Medium", "High", "Severe"}
        for band in result["lgd_band"]:
            assert band in valid_bands, f"Invalid band: {band}"

    def test_missing_columns_handled_gracefully(self):
        from models.lgd.predict import predict_lgd
        # Pass only partial features — should not raise
        df_in = pd.DataFrame({"fico_score": [700.0, 600.0]})
        result = predict_lgd(df_in)
        assert len(result) == 2

    @pytest.mark.parametrize("score,expected_band", [
        (0.10, "Low"),
        (0.30, "Medium"),
        (0.55, "High"),
        (0.80, "Severe"),
    ])
    def test_band_thresholds(self, score, expected_band):
        from models.lgd.predict import _lgd_band
        assert _lgd_band(score) == expected_band


# ---------------------------------------------------------------------------
# ModelScores lgd_score field
# ---------------------------------------------------------------------------


class TestModelScoresLGDFields:
    def test_model_scores_has_lgd_fields(self):
        from schemas.contracts import ModelScores
        import inspect
        fields = ModelScores.model_fields
        assert "lgd_score" in fields, "ModelScores missing lgd_score field"
        assert "lgd_band"  in fields, "ModelScores missing lgd_band field"

    def test_model_scores_default_lgd(self):
        from schemas.contracts import ModelScores
        ms = ModelScores(
            application_id="test-001",
            tenant_id="tenant-1",
            pd_score=0.05,
            pd_band="low",
            fraud_probability=0.02,
            fraud_flag="continue",
        )
        assert ms.lgd_score == 0.40
        assert ms.lgd_band == "Medium"

    def test_model_scores_custom_lgd(self):
        from schemas.contracts import ModelScores
        ms = ModelScores(
            application_id="test-002",
            tenant_id="tenant-1",
            pd_score=0.08,
            pd_band="medium",
            fraud_probability=0.03,
            fraud_flag="continue",
            lgd_score=0.25,
            lgd_band="Medium",
        )
        assert ms.lgd_score == 0.25

    def test_lgd_score_validation_bounds(self):
        from schemas.contracts import ModelScores
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ModelScores(
                application_id="t", tenant_id="t",
                pd_score=0.05, pd_band="low",
                fraud_probability=0.02, fraud_flag="continue",
                lgd_score=1.5,   # > 1.0 — should fail validation
            )


# ---------------------------------------------------------------------------
# ECL engine integration — exposure_record_from_model_scores
# ---------------------------------------------------------------------------


class TestECLIntegration:
    def test_exposure_record_uses_lgd_score(self):
        from risk_models.ecl_engine import exposure_record_from_model_scores

        class FakeModelScores:
            application_id = "APP-001"
            pd_score = 0.06
            lgd_score = 0.30

        record = exposure_record_from_model_scores(
            FakeModelScores(),
            outstanding_balance=10_000,
            credit_limit=15_000,
        )
        assert record.lgd == pytest.approx(0.30)
        assert record.pd_12m == pytest.approx(0.06)

    def test_exposure_record_uses_fallback_when_default_sentinel(self):
        from risk_models.ecl_engine import exposure_record_from_model_scores

        class DefaultModelScores:
            application_id = "APP-002"
            pd_score = 0.06
            lgd_score = 0.40   # == DEFAULT sentinel

        record = exposure_record_from_model_scores(
            DefaultModelScores(),
            outstanding_balance=10_000,
            credit_limit=15_000,
            fallback_lgd=0.65,
        )
        # Should fall back to 0.65 since lgd_score == 0.40 sentinel
        assert record.lgd == pytest.approx(0.65)

    def test_ecl_calculation_uses_lgd_score(self):
        from risk_models.ecl_engine import (
            exposure_record_from_model_scores,
            compute_12m_ecl,
        )

        class ScoresLowLGD:
            application_id = "A"
            pd_score = 0.10
            lgd_score = 0.10

        class ScoresHighLGD:
            application_id = "B"
            pd_score = 0.10
            lgd_score = 0.80

        rec_low  = exposure_record_from_model_scores(ScoresLowLGD(),  10_000, 15_000)
        rec_high = exposure_record_from_model_scores(ScoresHighLGD(), 10_000, 15_000)

        ecl_low  = compute_12m_ecl(rec_low)
        ecl_high = compute_12m_ecl(rec_high)

        assert ecl_high > ecl_low, (
            f"Higher LGD should produce higher ECL: ecl_low={ecl_low:.2f}, ecl_high={ecl_high:.2f}"
        )

    def test_exposure_record_from_dict(self):
        from risk_models.ecl_engine import exposure_record_from_model_scores
        scores_dict = {"application_id": "D", "pd_score": 0.05, "lgd_score": 0.20}
        record = exposure_record_from_model_scores(scores_dict, 5_000, 10_000)
        assert record.lgd == pytest.approx(0.20)
        assert record.pd_12m == pytest.approx(0.05)
