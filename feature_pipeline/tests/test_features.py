"""
Unit tests for feature_pipeline/features.py

Covers:
- Normal operation of every individual feature function
- Edge cases: zero income, missing delinquency, max DTI, zero tenure
- compute_features() end-to-end on a minimal DataFrame
- FeaturePipelineConfig version tracking
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from feature_pipeline.features import (
    DEFAULT_FEATURE_LIST,
    FeaturePipelineConfig,
    compute_credit_age_score,
    compute_credit_utilization,
    compute_debt_service_coverage,
    compute_derogatory_penalty,
    compute_dti_x_loan_amount,
    compute_employment_encoded,
    compute_features,
    compute_income_stability_score,
    compute_log_annual_income,
    compute_log_loan_amount,
    compute_months_since_delinquency,
    compute_repayment_capacity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_df() -> pd.DataFrame:
    """Minimal raw loan application DataFrame (5 rows) covering edge cases."""
    return pd.DataFrame(
        {
            "application_id": ["a1", "a2", "a3", "a4", "a5"],
            "customer_id": ["c1", "c2", "c3", "c4", "c5"],
            "credit_score": [750, 600, 500, 800, 350],
            "annual_income": [100_000.0, 50_000.0, 0.0, 200_000.0, 30_000.0],
            "employment_status": [
                "employed",
                "self-employed",
                "unemployed",
                "employed",
                "retired",
            ],
            "employer_tenure_months": [36, 12, 0, 120, 0],
            "debt_to_income_ratio": [0.10, 0.35, 0.65, 0.05, 0.50],
            "existing_debt_amount": [10_000.0, 20_000.0, 0.0, 5_000.0, 25_000.0],
            "loan_amount": [15_000.0, 30_000.0, 5_000.0, 50_000.0, 10_000.0],
            "loan_purpose": ["personal"] * 5,
            "loan_term_months": [36, 60, 12, 48, 24],
            "num_open_accounts": [5, 3, 0, 15, 2],
            "num_derogatory_marks": [0, 1, 5, 0, 3],
            "months_since_last_delinquency": [24.0, float("nan"), float("nan"), 6.0, 48.0],
            "state": ["CA"] * 5,
            "zip_code_prefix": ["900"] * 5,
            "submitted_at": pd.to_datetime(["2024-01-01"] * 5),
        }
    )


# ---------------------------------------------------------------------------
# credit_utilization
# ---------------------------------------------------------------------------


class TestCreditUtilization:
    def test_normal(self):
        result = compute_credit_utilization(
            pd.Series([10_000.0]), pd.Series([100_000.0])
        )
        assert pytest.approx(result.iloc[0], rel=1e-4) == 10_000 / (100_000 * 0.4)

    def test_zero_income_returns_one(self):
        """Zero income → utilisation defaults to 1 (maximum risk)."""
        result = compute_credit_utilization(pd.Series([5_000.0]), pd.Series([0.0]))
        assert result.iloc[0] == 1.0

    def test_clipped_to_one(self):
        """Result must never exceed 1."""
        result = compute_credit_utilization(
            pd.Series([999_999.0]), pd.Series([10_000.0])
        )
        assert result.iloc[0] == 1.0

    def test_clipped_to_zero(self):
        """Negative debt (would be unusual but must not go below 0)."""
        result = compute_credit_utilization(pd.Series([0.0]), pd.Series([50_000.0]))
        assert result.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# income_stability_score
# ---------------------------------------------------------------------------


class TestIncomeStabilityScore:
    def test_zero_tenure_near_half(self):
        result = compute_income_stability_score(pd.Series([0]))
        assert pytest.approx(result.iloc[0], abs=0.01) == 0.5

    def test_twelve_months(self):
        result = compute_income_stability_score(pd.Series([12]))
        expected = 1 / (1 + math.exp(-1.0))
        assert pytest.approx(result.iloc[0], rel=1e-5) == expected

    def test_long_tenure_near_one(self):
        result = compute_income_stability_score(pd.Series([240]))
        assert result.iloc[0] > 0.99

    def test_bounded_0_1(self):
        result = compute_income_stability_score(pd.Series([0, 12, 240]))
        assert (result >= 0).all() and (result <= 1).all()


# ---------------------------------------------------------------------------
# repayment_capacity
# ---------------------------------------------------------------------------


class TestRepaymentCapacity:
    def test_zero_dti(self):
        result = compute_repayment_capacity(pd.Series([0.0]))
        assert result.iloc[0] == 1.0

    def test_max_dti(self):
        result = compute_repayment_capacity(pd.Series([0.65]))
        assert pytest.approx(result.iloc[0], abs=1e-9) == 0.35

    def test_never_negative(self):
        """Even a DTI slightly above 1 (edge data) should not produce negative."""
        result = compute_repayment_capacity(pd.Series([1.0]))
        assert result.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# debt_service_coverage
# ---------------------------------------------------------------------------


class TestDebtServiceCoverage:
    def test_normal(self):
        result = compute_debt_service_coverage(
            pd.Series([100_000.0]), pd.Series([10_000.0])
        )
        assert pytest.approx(result.iloc[0], rel=1e-5) == 100_000 / 10_001

    def test_zero_debt(self):
        """Zero existing debt — denominator becomes 1 → coverage equals income."""
        result = compute_debt_service_coverage(
            pd.Series([50_000.0]), pd.Series([0.0])
        )
        assert pytest.approx(result.iloc[0], rel=1e-5) == 50_000.0

    def test_zero_income(self):
        result = compute_debt_service_coverage(pd.Series([0.0]), pd.Series([5_000.0]))
        assert result.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# credit_age_score
# ---------------------------------------------------------------------------


class TestCreditAgeScore:
    def test_zero_accounts(self):
        result = compute_credit_age_score(pd.Series([0]))
        assert result.iloc[0] == 0.0

    def test_ten_accounts_is_one(self):
        result = compute_credit_age_score(pd.Series([10]))
        assert result.iloc[0] == 1.0

    def test_over_ten_clipped(self):
        result = compute_credit_age_score(pd.Series([20]))
        assert result.iloc[0] == 1.0

    def test_five_accounts(self):
        result = compute_credit_age_score(pd.Series([5]))
        assert pytest.approx(result.iloc[0]) == 0.5


# ---------------------------------------------------------------------------
# derogatory_penalty
# ---------------------------------------------------------------------------


class TestDerogatoryPenalty:
    def test_zero_marks(self):
        result = compute_derogatory_penalty(pd.Series([0]))
        assert result.iloc[0] == 0.0

    def test_one_mark(self):
        result = compute_derogatory_penalty(pd.Series([1]))
        assert pytest.approx(result.iloc[0]) == 0.05

    def test_ten_marks_capped(self):
        """Even 10 derogatory marks must not exceed 0.50."""
        result = compute_derogatory_penalty(pd.Series([10]))
        assert result.iloc[0] == 0.5

    def test_max_marks_capped(self):
        result = compute_derogatory_penalty(pd.Series([100]))
        assert result.iloc[0] == 0.5


# ---------------------------------------------------------------------------
# months_since_delinquency
# ---------------------------------------------------------------------------


class TestMonthsSinceDelinquency:
    def test_null_filled_with_999(self):
        """Null (never delinquent) must be encoded as 999."""
        result = compute_months_since_delinquency(pd.Series([float("nan")]))
        assert result.iloc[0] == 999.0

    def test_normal_value_preserved(self):
        result = compute_months_since_delinquency(pd.Series([24.0]))
        assert result.iloc[0] == 24.0

    def test_clipped_above_999(self):
        result = compute_months_since_delinquency(pd.Series([5000.0]))
        assert result.iloc[0] == 999.0

    def test_zero_preserved(self):
        result = compute_months_since_delinquency(pd.Series([0.0]))
        assert result.iloc[0] == 0.0

    def test_mixed_null_and_real(self):
        result = compute_months_since_delinquency(pd.Series([float("nan"), 12.0, float("nan")]))
        assert result.iloc[0] == 999.0
        assert result.iloc[1] == 12.0
        assert result.iloc[2] == 999.0


# ---------------------------------------------------------------------------
# log transforms
# ---------------------------------------------------------------------------


class TestLogTransforms:
    def test_log_loan_amount(self):
        result = compute_log_loan_amount(pd.Series([0.0, 1000.0]))
        assert result.iloc[0] == 0.0
        assert pytest.approx(result.iloc[1], rel=1e-5) == math.log1p(1000.0)

    def test_log_annual_income(self):
        result = compute_log_annual_income(pd.Series([0.0, 100_000.0]))
        assert result.iloc[0] == 0.0
        assert pytest.approx(result.iloc[1], rel=1e-5) == math.log1p(100_000.0)


# ---------------------------------------------------------------------------
# dti_x_loan_amount interaction
# ---------------------------------------------------------------------------


class TestDtiXLoanAmount:
    def test_normal(self):
        result = compute_dti_x_loan_amount(pd.Series([0.3]), pd.Series([10_000.0]))
        assert pytest.approx(result.iloc[0]) == 3_000.0

    def test_zero_dti(self):
        result = compute_dti_x_loan_amount(pd.Series([0.0]), pd.Series([50_000.0]))
        assert result.iloc[0] == 0.0


# ---------------------------------------------------------------------------
# employment_encoded
# ---------------------------------------------------------------------------


class TestEmploymentEncoded:
    def test_all_categories(self):
        s = pd.Series(["employed", "self-employed", "unemployed", "retired"])
        result = compute_employment_encoded(s)
        assert list(result) == [3, 2, 0, 1]

    def test_unknown_maps_to_zero(self):
        result = compute_employment_encoded(pd.Series(["contractor"]))
        assert result.iloc[0] == 0

    def test_case_insensitive(self):
        result = compute_employment_encoded(pd.Series(["Employed", "UNEMPLOYED"]))
        assert list(result) == [3, 0]


# ---------------------------------------------------------------------------
# compute_features — end-to-end
# ---------------------------------------------------------------------------


class TestComputeFeatures:
    def test_all_feature_columns_produced(self, minimal_df):
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        for col in DEFAULT_FEATURE_LIST:
            assert col in result.columns, f"Missing feature column: {col}"

    def test_original_columns_preserved(self, minimal_df):
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        for col in minimal_df.columns:
            assert col in result.columns

    def test_row_count_unchanged(self, minimal_df):
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        assert len(result) == len(minimal_df)

    def test_input_df_not_mutated(self, minimal_df):
        """compute_features must not modify the input DataFrame."""
        original_cols = set(minimal_df.columns)
        config = FeaturePipelineConfig()
        compute_features(minimal_df, config)
        assert set(minimal_df.columns) == original_cols

    def test_zero_income_handled(self, minimal_df):
        """Row with annual_income=0 must not raise."""
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        zero_income_row = result[result["annual_income"] == 0.0]
        assert len(zero_income_row) == 1
        assert zero_income_row["credit_utilization"].iloc[0] == 1.0

    def test_missing_delinquency_handled(self, minimal_df):
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        null_rows = minimal_df["months_since_last_delinquency"].isna()
        assert (result.loc[null_rows, "months_since_delinquency"] == 999).all()

    def test_max_dti_handled(self, minimal_df):
        """Row with DTI=0.65 should produce repayment_capacity ≈ 0.35."""
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        max_dti_mask = minimal_df["debt_to_income_ratio"] == 0.65
        cap = result.loc[max_dti_mask, "repayment_capacity"].iloc[0]
        assert pytest.approx(cap, abs=1e-6) == 0.35

    def test_no_nan_in_feature_columns(self, minimal_df):
        """After feature computation all engineered columns should be non-null."""
        config = FeaturePipelineConfig()
        result = compute_features(minimal_df, config)
        for col in DEFAULT_FEATURE_LIST:
            n_null = result[col].isna().sum()
            assert n_null == 0, f"Column '{col}' has {n_null} NaN values"


# ---------------------------------------------------------------------------
# FeaturePipelineConfig
# ---------------------------------------------------------------------------


class TestFeaturePipelineConfig:
    def test_default_version(self):
        config = FeaturePipelineConfig()
        assert config.version == "1.0.0"

    def test_custom_version(self):
        config = FeaturePipelineConfig(version="2.3.1")
        assert config.version == "2.3.1"

    def test_feature_list_matches_defaults(self):
        config = FeaturePipelineConfig()
        assert config.feature_list == DEFAULT_FEATURE_LIST

    def test_feature_list_is_independent_copy(self):
        """Mutating one config's list must not affect another."""
        c1 = FeaturePipelineConfig()
        c2 = FeaturePipelineConfig()
        c1.feature_list.append("extra_feature")
        assert "extra_feature" not in c2.feature_list
