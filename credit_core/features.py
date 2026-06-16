"""
credit_core.features — Canonical Feature Matrix
================================================
Single entry point for feature engineering used by ALL channels:

  * Decision API
  * FeatureEngineeringAgent (batch / agent pipeline)
  * Offline model training scripts

Usage
-----
>>> from credit_core.features import compute_feature_matrix
>>> df_features = compute_feature_matrix(df_raw, version="1.0.0")

Design
------
This module is a thin orchestration layer that:

1.  Normalises column aliases across the two historical naming conventions
    (``existing_debt_amount`` / ``existing_debt``, ``debt_to_income_ratio`` / ``dti``, etc.)
    into the canonical schema understood by ``feature_pipeline.features``.
2.  Delegates core feature computation to ``feature_pipeline.features.compute_features``
    (the authoritative implementation).
3.  Applies thin-file alt-data enrichment on top.
4.  Returns a DataFrame that is *identical in structure* regardless of
    whether the caller is the API, the agent pipeline, or a batch job.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from feature_pipeline.features import FeaturePipelineConfig, compute_features

logger = logging.getLogger(__name__)

# PROMPT-05: Import tracing — no-op if opentelemetry-sdk is not installed
try:
    from observability.tracing import TRACER, span as _trace_span
except ImportError:  # pragma: no cover
    TRACER = None  # type: ignore[assignment]
    import contextlib as _contextlib
    _trace_span = _contextlib.nullcontext  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Column alias normalisation
# ---------------------------------------------------------------------------

# Maps legacy/agent column names → canonical feature_pipeline column names.
# Keys that are already canonical are not listed here.
_COLUMN_ALIASES: Dict[str, str] = {
    "existing_debt": "existing_debt_amount",
    "dti": "debt_to_income_ratio",
}

# Alt-data columns carried through for thin-file enrichment
_ALT_DATA_COLS = [
    "rent_payment_months",
    "utility_payment_months",
    "mobile_data_score",
    "bank_account_age_months",
    "avg_monthly_cash_inflow",
    "avg_monthly_cash_outflow",
    # Open-banking enrichment signals (optional — contributed only when present)
    "nsfv_last_90_days",
    "returned_payment_count",
    "income_confidence",
    "avg_monthly_end_balance",
    "min_balance_90d",
]


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename legacy column aliases to their canonical equivalents."""
    rename_map = {
        alias: canonical
        for alias, canonical in _COLUMN_ALIASES.items()
        if alias in df.columns and canonical not in df.columns
    }
    if rename_map:
        logger.debug("credit_core.features: normalising column aliases: %s", rename_map)
        df = df.rename(columns=rename_map)
    return df


# ---------------------------------------------------------------------------
# Thin-file enrichment (applied AFTER canonical feature computation)
# ---------------------------------------------------------------------------

def _compute_thin_file_alt_score(
    df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """Additive composite score derived from alt-data signals.

    Each signal contributes only when the standard bureau features are
    absent/null.  Result is clipped to [0, 1].

    Positive contributors
    ---------------------
    rent_payment_months      : on-time rent history (capped at 12 months)
    utility_payment_months   : on-time utility history (capped at 12 months)
    mobile_data_score        : normalised mobile-usage signal
    bank_account_age_months  : account tenure as stability proxy
    cash_flow_stability      : (inflow - outflow) / inflow ratio
    income_confidence        : confidence of open-banking income estimate

    Negative contributors (deductions for risk signals)
    ---------------------------------------------------
    nsfv_last_90_days        : NSF / overdraft events — each event reduces score
    returned_payment_count   : returned payments — each event reduces score
    balance_stress           : penalty when min_balance_90d is negative (chronic overdraft)

    Model-risk note (for reviewers)
    --------------------------------
    All weights default to conservative values.  Callers may override via
    ``alt_weights`` for tenant-specific tuning; overrides must be four-eyes
    approved via the Config Registry.  The score is clipped to [0, 1] so
    downstream model inputs remain bounded.
    """
    if weights is None:
        weights = {}

    rent_w      = weights.get("rent_payment_weight", 0.05)
    util_w      = weights.get("utility_payment_weight", 0.03)
    mob_w       = weights.get("mobile_data_weight", 0.10)
    bank_w      = weights.get("bank_age_weight", 0.04)
    cf_w        = weights.get("cashflow_stability_weight", 0.06)
    income_w    = weights.get("income_confidence_weight", 0.04)
    nsf_pen     = weights.get("nsf_penalty_per_event", 0.03)
    return_pen  = weights.get("return_payment_penalty_per_event", 0.05)
    bal_stress_w = weights.get("balance_stress_weight", 0.05)

    score = pd.Series(0.0, index=df.index)

    # --- Positive contributions ---
    if "rent_payment_months" in df.columns:
        score += (df["rent_payment_months"].fillna(0).clip(0, 12) / 12) * rent_w
    if "utility_payment_months" in df.columns:
        score += (df["utility_payment_months"].fillna(0).clip(0, 12) / 12) * util_w
    if "mobile_data_score" in df.columns:
        score += df["mobile_data_score"].fillna(0).clip(0, 1) * mob_w
    if "bank_account_age_months" in df.columns:
        score += (df["bank_account_age_months"].fillna(0).clip(0, 24) / 24) * bank_w

    # Cash-flow stability proxy: (inflow - outflow) / inflow
    if "avg_monthly_cash_inflow" in df.columns and "avg_monthly_cash_outflow" in df.columns:
        inflow = df["avg_monthly_cash_inflow"].fillna(0)
        outflow = df["avg_monthly_cash_outflow"].fillna(0)
        cashflow_ratio = (inflow - outflow) / inflow.clip(lower=1)
        score += cashflow_ratio.clip(0, 1) * cf_w

    # Income confidence from open-banking enrichment
    if "income_confidence" in df.columns:
        score += df["income_confidence"].fillna(0).clip(0, 1) * income_w

    # --- Negative contributions (deductions) ---
    if "nsfv_last_90_days" in df.columns:
        nsf_events = df["nsfv_last_90_days"].fillna(0).clip(lower=0)
        # Diminishing deduction: capped at 3 events (max -0.09 at default weight)
        score -= nsf_events.clip(0, 3) * nsf_pen

    if "returned_payment_count" in df.columns:
        returned = df["returned_payment_count"].fillna(0).clip(lower=0)
        # Each returned payment is a stronger signal; capped at 2 events
        score -= returned.clip(0, 2) * return_pen

    if "min_balance_90d" in df.columns:
        # Negative minimum balance → chronic overdraft stress penalty
        min_bal = df["min_balance_90d"].fillna(0)
        overdraft_depth = (-min_bal).clip(lower=0)  # 0 when never negative
        # Normalise against avg inflow; penalty proportional to overdraft depth
        if "avg_monthly_cash_inflow" in df.columns:
            inflow_ref = df["avg_monthly_cash_inflow"].fillna(1).clip(lower=1)
            overdraft_fraction = (overdraft_depth / inflow_ref).clip(0, 1)
        else:
            overdraft_fraction = overdraft_depth.clip(0, 1) / 1000.0
        score -= overdraft_fraction * bal_stress_w

    return score.clip(0, 1)


def _apply_thin_file_enrichment(
    df: pd.DataFrame,
    alt_weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Compute ``thin_file_alt_score`` and boost ``income_stability_score`` for thin-file rows."""
    df["thin_file_alt_score"] = _compute_thin_file_alt_score(df, alt_weights)

    # Boost income_stability_score for applicants flagged as thin-file
    # (i.e. those without a traditional credit_score)
    if "credit_score" in df.columns:
        is_thin = df["credit_score"].isna()
        if is_thin.any():
            df.loc[is_thin, "income_stability_score"] = (
                df.loc[is_thin, "income_stability_score"]
                + df.loc[is_thin, "thin_file_alt_score"]
            ).clip(0, 1)

    return df


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_feature_matrix(
    applications_df: pd.DataFrame,
    *,
    version: str = "1.0.0",
    alt_weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Compute the canonical feature matrix for a batch of loan applications.

    This is the **single** function that all channels (Decision API, agent
    pipeline, batch jobs) must call.  Direct calls to
    ``feature_pipeline.features.compute_features`` from outside this module
    are deprecated.

    Parameters
    ----------
    applications_df:
        Raw loan application DataFrame.  Accepts both the canonical column
        names (``existing_debt_amount``, ``debt_to_income_ratio``) and the
        legacy agent names (``existing_debt``, ``dti``) — they are
        normalised internally.
    version:
        Pipeline version string used for logging and lineage tracking.
        Must match the version in ``FeaturePipelineConfig``.
    alt_weights:
        Optional override for thin-file alt-data signal weights.
        When ``None``, the defaults from ``_compute_thin_file_alt_score``
        are used.

    Returns
    -------
    pd.DataFrame
        Input DataFrame extended with all engineered feature columns,
        including ``thin_file_alt_score``.
    """
    logger.info(
        "credit_core.features: computing feature matrix (version=%s) for %d rows",
        version,
        len(applications_df),
    )

    with _trace_span("credit_core.compute_feature_matrix", TRACER,
                     feature_version=version, rows=len(applications_df)):
        # 1. Normalise column aliases → canonical names
        df = _normalise_columns(applications_df.copy())

        # 2. Delegate to canonical feature_pipeline implementation.
        #    thin_file_alt_score is NOT produced by compute_features — it's added
        #    by our enrichment step below, so we exclude it from the validation list.
        base_feature_list = [
            f for f in FeaturePipelineConfig(version=version).feature_list
            if f != "thin_file_alt_score"
        ]
        config = FeaturePipelineConfig(version=version, feature_list=base_feature_list)
        df = compute_features(df, config)

        # 3. Apply thin-file enrichment (alt-data signals + thin-file boost)
        df = _apply_thin_file_enrichment(df, alt_weights=alt_weights)

    logger.info(
        "credit_core.features: feature matrix complete — %d cols on %d rows",
        len(df.columns),
        len(df),
    )
    return df
