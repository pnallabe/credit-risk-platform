"""
Feature engineering pipeline for the Credit Risk Platform.

All feature functions are **pure** — they perform no I/O and have no
side effects.  Each function accepts a pandas Series (or scalar array)
and returns a transformed Series so they compose cleanly.

Top-level entry point
---------------------
>>> from feature_pipeline.features import compute_features, FeaturePipelineConfig
>>> config = FeaturePipelineConfig()
>>> df_with_features = compute_features(df_raw, config)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Ordered list of every feature column produced by this pipeline version.
DEFAULT_FEATURE_LIST: List[str] = [
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
    "thin_file_alt_score",
]


@dataclass
class FeaturePipelineConfig:
    """Versioned configuration for the feature pipeline.

    Attributes
    ----------
    version:
        Semantic version string logged to the feature store so every
        prediction can be traced back to an exact pipeline snapshot.
    feature_list:
        Ordered list of feature column names produced by this version.
        Downstream consumers use this to select the right columns.
    """

    version: str = "1.0.0"
    feature_list: List[str] = field(default_factory=lambda: list(DEFAULT_FEATURE_LIST))


# ---------------------------------------------------------------------------
# Individual feature functions
# ---------------------------------------------------------------------------


def _sigmoid(x: pd.Series) -> pd.Series:
    """Numerically stable sigmoid function."""
    return 1.0 / (1.0 + np.exp(-x))


def compute_credit_utilization(
    existing_debt_amount: pd.Series,
    annual_income: pd.Series,
) -> pd.Series:
    """Estimate how much of the applicant's available credit capacity is in use.

    Credit rationale
    ----------------
    High utilization (close to 1) signals that the borrower has borrowed up to
    the limits implied by their income, increasing default risk.  We normalise to
    [0, 1] so it is well-behaved for models and scorecards.

    Formula
    -------
    credit_utilization = clip( existing_debt / (annual_income × 0.4), 0, 1 )

    The 0.4 factor approximates the maximum unsecured credit capacity typically
    extended by lenders at 40 % of gross annual income.
    """
    denominator = annual_income * 0.4
    # Avoid division by zero: when income is 0 utilisation defaults to 1 (max risk)
    utilization = existing_debt_amount / denominator.replace(0, np.nan)
    return utilization.fillna(1.0).clip(0.0, 1.0)


def compute_income_stability_score(employer_tenure_months: pd.Series) -> pd.Series:
    """Score the stability of the applicant's income based on employment tenure.

    Credit rationale
    ----------------
    Longer continuous employment with the same employer is a strong predictor
    of stable future income and therefore lower default risk.  The sigmoid
    function produces a smooth 0-to-1 score:
    - 0 months tenure  → ~0.50 (no evidence of stability)
    - 12 months tenure → ~0.73
    - 36 months tenure → ~0.95 (high stability)

    Formula
    -------
    income_stability_score = sigmoid( employer_tenure_months / 12 )
    """
    return _sigmoid(employer_tenure_months / 12.0)


def compute_repayment_capacity(debt_to_income_ratio: pd.Series) -> pd.Series:
    """Estimate the fraction of income available for new debt repayments.

    Credit rationale
    ----------------
    A DTI of 0.40 leaves 60 % of income available; a DTI of 0.65 (maximum
    in our data) leaves only 35 %.  Higher repayment capacity → lower default.

    Formula
    -------
    repayment_capacity = 1 - debt_to_income_ratio
    """
    return (1.0 - debt_to_income_ratio).clip(0.0, 1.0)


def compute_debt_service_coverage(
    annual_income: pd.Series,
    existing_debt_amount: pd.Series,
) -> pd.Series:
    """Measure how comfortably income covers existing debt obligations.

    Credit rationale
    ----------------
    A ratio > 1 indicates income exceeds existing debt (healthy); a ratio < 1
    indicates income is insufficient to cover outstanding obligations.  Adding 1
    to the denominator avoids division by zero and gives zero-debt applicants the
    full income score.

    Formula
    -------
    debt_service_coverage = annual_income / (existing_debt_amount + 1)
    """
    return annual_income / (existing_debt_amount + 1.0)


def compute_credit_age_score(num_open_accounts: pd.Series) -> pd.Series:
    """Score the breadth of the applicant's credit experience.

    Credit rationale
    ----------------
    Applicants with more open accounts have demonstrated the ability to manage
    multiple credit lines, which correlates with responsible credit behaviour.
    Score saturates at 1.0 once ≥ 10 accounts are open.

    Formula
    -------
    credit_age_score = min( num_open_accounts / 10, 1.0 )
    """
    return (num_open_accounts / 10.0).clip(0.0, 1.0)


def compute_derogatory_penalty(num_derogatory_marks: pd.Series) -> pd.Series:
    """Quantify the credit risk signal from derogatory marks.

    Credit rationale
    ----------------
    Each derogatory mark (collections, charge-offs, public records) adds 5 %
    to the risk penalty, capped at 50 % to prevent extreme outliers from
    dominating the model input space.

    Formula
    -------
    derogatory_penalty = clip( num_derogatory_marks × 0.05, 0, 0.5 )
    """
    return (num_derogatory_marks * 0.05).clip(0.0, 0.5)


def compute_months_since_delinquency(months_since_last_delinquency: pd.Series) -> pd.Series:
    """Encode recency of the last delinquency in a model-friendly way.

    Credit rationale
    ----------------
    Null means the applicant has *never* been delinquent, which is the most
    favourable case.  We encode this as 999 (the practical maximum), so the
    feature is monotonically beneficial: higher value → lower recent delinquency.

    Formula
    -------
    months_since_delinquency = fillna(999).clip(0, 999)
    """
    return months_since_last_delinquency.fillna(999).clip(0, 999)


def compute_log_loan_amount(loan_amount: pd.Series) -> pd.Series:
    """Log-transform loan amount to reduce right-skew.

    Credit rationale
    ----------------
    Loan amounts span three orders of magnitude (1k–100k).  The log transform
    compresses this range so that large loans do not unduly dominate linear
    model components or distance-based algorithms.

    Formula
    -------
    log_loan_amount = log1p( loan_amount )
    """
    return np.log1p(loan_amount)


def compute_log_annual_income(annual_income: pd.Series) -> pd.Series:
    """Log-transform annual income to reduce right-skew.

    Credit rationale
    ----------------
    Income distributions are typically log-normal.  Log-transforming exposes
    the proportional differences between income levels rather than absolute
    differences, making the feature more informative for both linear and
    tree-based models.

    Formula
    -------
    log_annual_income = log1p( annual_income )
    """
    return np.log1p(annual_income)


def compute_dti_x_loan_amount(
    debt_to_income_ratio: pd.Series,
    loan_amount: pd.Series,
) -> pd.Series:
    """Interaction feature capturing combined leverage risk.

    Credit rationale
    ----------------
    A high DTI on a large loan is more dangerous than either signal alone.
    This multiplicative interaction lets models capture the non-linear
    joint effect of existing leverage and new borrowing size.

    Formula
    -------
    dti_x_loan_amount = debt_to_income_ratio × loan_amount
    """
    return debt_to_income_ratio * loan_amount


_EMPLOYMENT_ORDINAL_MAP = {
    "unemployed": 0,
    "retired": 1,
    "self-employed": 2,
    "employed": 3,
}


def compute_employment_encoded(employment_status: pd.Series) -> pd.Series:
    """Ordinal-encode employment status by income stability risk level.

    Credit rationale
    ----------------
    Employment type is a strong proxy for income certainty.  We assign an
    ordinal value reflecting the typical rank-ordering of default risk:

    0 unemployed    — no stable income source
    1 retired       — fixed income, lower growth
    2 self-employed — variable income, some uncertainty
    3 employed      — regular salary, most stable

    Using ordinal rather than one-hot encoding preserves this natural ordering
    while adding only a single column.
    """
    return employment_status.str.lower().map(_EMPLOYMENT_ORDINAL_MAP).fillna(0).astype(int)


# ---------------------------------------------------------------------------
# Top-level pipeline
# ---------------------------------------------------------------------------


def compute_features(df: pd.DataFrame, config: FeaturePipelineConfig) -> pd.DataFrame:
    """Compute all engineered features and append them to *df*.

    Parameters
    ----------
    df:
        Raw loan application DataFrame.  Must contain the columns produced
        by ``data/generate_synthetic_data.py``.
    config:
        A ``FeaturePipelineConfig`` instance specifying the pipeline version
        and expected feature list.  The version string is used for logging
        and should be written to the feature store alongside the features.

    Returns
    -------
    pd.DataFrame
        A copy of *df* with all feature columns from ``config.feature_list``
        appended.  The original columns are preserved unchanged.

    Raises
    ------
    KeyError
        If a required raw input column is missing from *df*.
    """
    logger.info("Computing features (pipeline version %s) on %d rows", config.version, len(df))

    result = df.copy()

    result["credit_utilization"] = compute_credit_utilization(
        result["existing_debt_amount"],
        result["annual_income"],
    )
    result["income_stability_score"] = compute_income_stability_score(
        result["employer_tenure_months"]
    )
    result["repayment_capacity"] = compute_repayment_capacity(
        result["debt_to_income_ratio"]
    )
    result["debt_service_coverage"] = compute_debt_service_coverage(
        result["annual_income"],
        result["existing_debt_amount"],
    )
    result["credit_age_score"] = compute_credit_age_score(
        result["num_open_accounts"]
    )
    result["derogatory_penalty"] = compute_derogatory_penalty(
        result["num_derogatory_marks"]
    )
    result["months_since_delinquency"] = compute_months_since_delinquency(
        result["months_since_last_delinquency"]
    )
    result["log_loan_amount"] = compute_log_loan_amount(result["loan_amount"])
    result["log_annual_income"] = compute_log_annual_income(result["annual_income"])
    result["dti_x_loan_amount"] = compute_dti_x_loan_amount(
        result["debt_to_income_ratio"],
        result["loan_amount"],
    )
    result["employment_encoded"] = compute_employment_encoded(
        result["employment_status"]
    )
    # Default thin-file alt score: 0.0 (no signal).  The credit_core enrichment
    # step overrides this for thin-file applicants via alternative data sources.
    if "thin_file_alt_score" in config.feature_list:
        if "thin_file_alt_score" not in result.columns:
            result["thin_file_alt_score"] = 0.0
        else:
            result["thin_file_alt_score"] = result["thin_file_alt_score"].fillna(0.0)

    missing = [col for col in config.feature_list if col not in result.columns]
    if missing:
        raise ValueError(f"Feature pipeline failed to produce columns: {missing}")

    logger.info("Feature computation complete — %d feature columns produced", len(config.feature_list))
    return result
