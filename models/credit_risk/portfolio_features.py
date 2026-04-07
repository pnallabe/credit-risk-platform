"""
Feature Engineering for Credit Line / APR Management Model
===========================================================
Section 20.2 — Portfolio Action Model Features

Source: BigQuery cc_monthly_statements (12-month window per account)
        + cc_transactions (category-level spend)
        + cc_credit_limit_events (prior CLI/CLD history)

35 features across 5 groups:
  - PAYMENT_BEHAVIOUR_FEATURES   (9 features)
  - SPEND_BEHAVIOUR_FEATURES     (11 features)
  - UTILISATION_FEATURES         (8 features)
  - RISK_SIGNALS                 (10 features)
  - ACCOUNT_TENURE_FEATURES      (6 features)  [6 defined, subset contributes to ALL_FEATURES]

Usage
-----
    from models.credit_risk.portfolio_features import compute_account_features, ALL_FEATURES
    feats = compute_account_features(df_stmts, df_txns, df_events)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Feature name lists (used as column ordering contract for model training/scoring)
# ---------------------------------------------------------------------------

PAYMENT_BEHAVIOUR_FEATURES: List[str] = [
    "payment_rate_3m_avg",           # avg(actual_payment/minimum_payment) last 3 months
    "payment_rate_6m_avg",           # avg(actual_payment/minimum_payment) last 6 months
    "payment_rate_12m_avg",          # avg(actual_payment/minimum_payment) last 12 months
    "full_pay_months_12m",           # count of months with payment_ratio >= 0.99
    "missed_payment_months_12m",     # count of months with actual_payment < minimum_payment
    "consecutive_full_pay_streak",   # current streak of consecutive full-payment months
    "consecutive_missed_pay",        # current streak of consecutive missed/partial payments
    "payment_volatility_12m",        # std(payment_ratio) over 12 months
    "early_payment_flag",            # 1 if avg payment date < due date; 0 otherwise
]

SPEND_BEHAVIOUR_FEATURES: List[str] = [
    "spend_3m_avg_usd",              # avg monthly spend last 3 months
    "spend_12m_avg_usd",             # avg monthly spend last 12 months
    "spend_growth_3m_vs_12m",        # (spend_3m - spend_12m) / spend_12m
    "spend_growth_yoy",              # spend last 3m vs same 3m prior year
    "mcc_diversity_score",           # entropy of spend across MCC categories
    "recurring_spend_pct",           # % spend in recurring MCC (utilities, subscriptions)
    "discretionary_spend_pct",       # % in discretionary MCC (restaurants, travel)
    "international_spend_pct",       # % flagged is_international
    "cash_advance_pct_12m",          # cash_advance_usd / total_spend
    "balance_transfer_pct_12m",      # balance_transfer_usd / credit_limit
    "spend_trend_slope_12m",         # OLS slope of monthly spend over 12 months
]

UTILISATION_FEATURES: List[str] = [
    "utilisation_3m_avg",            # avg(balance/credit_limit) last 3 months
    "utilisation_6m_avg",
    "utilisation_12m_avg",
    "utilisation_volatility_12m",    # std(utilisation)
    "utilisation_trend_slope_12m",   # OLS slope of utilisation over 12 months
    "peak_utilisation_12m",          # max utilisation in any single month
    "months_near_limit",             # months where utilisation > 90%
    "months_utilisation_zero",       # months with zero balance
]

RISK_SIGNALS: List[str] = [
    "current_delinquency_status",    # CURRENT=0 / DPD30=1 / DPD60=2 / DPD90=3 / DPD120=4 / CHARGED_OFF=5
    "dpd_months_12m",                # count of months with any DPD
    "max_dpd_12m",                   # max days-past-due observed in 12 months
    "bureau_score_current",          # modelled current bureau score
    "bureau_score_3m_change",        # delta from 3 months ago
    "bureau_score_12m_change",       # delta from 12 months ago
    "bureau_score_vs_origination",   # current score minus origination score
    "times_30dpd_lifetime",          # lifetime 30+ DPD count
    "times_90dpd_lifetime",          # lifetime 90+ DPD count
    "charge_off_flag",               # 1 if account has been charged off
]

ACCOUNT_TENURE_FEATURES: List[str] = [
    "account_age_months",
    "months_since_last_cli",         # -1 if never had a CLI
    "months_since_last_cld",         # -1 if never had a CLD
    "prior_cli_count",
    "prior_cld_count",
    "prior_cli_accepted_flag",       # 1 if offered CLI and accepted
]

ALL_FEATURES: List[str] = (
    PAYMENT_BEHAVIOUR_FEATURES
    + SPEND_BEHAVIOUR_FEATURES
    + UTILISATION_FEATURES
    + RISK_SIGNALS
    + ACCOUNT_TENURE_FEATURES
)

# ---------------------------------------------------------------------------
# MCC category mappings  (simplified)
# ---------------------------------------------------------------------------

_RECURRING_MCC_PREFIXES = {
    "4900", "4911", "4816", "5960", "5963",  # utilities and subscriptions
    "4812", "4813", "4814", "4899",           # telecom
}

_DISCRETIONARY_MCC_PREFIXES = {
    "5812", "5813", "5814", "5411", "5912",  # restaurants, food
    "4511", "7011", "7012", "7999",           # travel, hotels, leisure
}

_DELINQUENCY_STATUS_MAP = {
    "CURRENT": 0, "DPD30": 1, "DPD60": 2,
    "DPD90": 3, "DPD120": 4, "CHARGED_OFF": 5,
}


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------


def compute_account_features(
    df_stmts: pd.DataFrame,
    df_txns: pd.DataFrame,
    df_events: pd.DataFrame,
    origination_score: Optional[float] = None,
) -> Dict[str, float]:
    """Compute all Section 20 features for a single account.

    Parameters
    ----------
    df_stmts:
        12-month monthly statement rows for the account, sorted ascending by
        ``statement_date``.  Required columns: ``payment_ratio``,
        ``purchase_volume_usd``, ``utilization_rate``, ``bureau_score_current``,
        ``delinquency_status``.
    df_txns:
        Transaction rows for the account (12-month window).  Optional columns
        used if present: ``merchant_category_code``, ``transaction_type``,
        ``is_international``, ``amount_usd``.
    df_events:
        Credit limit event rows for the account.  Expected columns:
        ``event_type`` ("CLI" | "CLD"), ``event_date``.
    origination_score:
        Bureau score at origination (for ``bureau_score_vs_origination``).

    Returns
    -------
    dict
        Keys = ALL_FEATURES; all values are numeric (int or float).
        NaN values are replaced with 0.0.
    """
    feats: Dict[str, float] = {}

    # ── Payment behaviour ──────────────────────────────────────────────────
    if not df_stmts.empty and "payment_ratio" in df_stmts.columns:
        pr = df_stmts["payment_ratio"].fillna(0.0)
        feats["payment_rate_3m_avg"]           = float(pr.tail(3).mean())
        feats["payment_rate_6m_avg"]           = float(pr.tail(6).mean())
        feats["payment_rate_12m_avg"]          = float(pr.mean())
        feats["full_pay_months_12m"]           = int((pr >= 0.99).sum())
        feats["missed_payment_months_12m"]     = int((pr < 1.0).sum())
        feats["consecutive_full_pay_streak"]   = _latest_streak(pr >= 0.99)
        feats["consecutive_missed_pay"]        = _latest_streak(pr < 1.0, from_end=True)
        feats["payment_volatility_12m"]        = float(pr.std()) if len(pr) > 1 else 0.0
        feats["early_payment_flag"]            = 0  # not available in synthetic data
    else:
        for f in PAYMENT_BEHAVIOUR_FEATURES:
            feats[f] = 0.0

    # ── Spend behaviour ────────────────────────────────────────────────────
    spend = None
    if not df_stmts.empty and "purchase_volume_usd" in df_stmts.columns:
        spend = df_stmts["purchase_volume_usd"].fillna(0.0)
        s3   = float(spend.tail(3).mean())
        s12  = float(spend.mean())
        feats["spend_3m_avg_usd"]          = s3
        feats["spend_12m_avg_usd"]         = s12
        feats["spend_growth_3m_vs_12m"]    = _safe_div(s3 - s12, s12)
        feats["spend_growth_yoy"]          = _yoy_growth(spend)
        n = len(spend)
        feats["spend_trend_slope_12m"]     = (
            float(np.polyfit(np.arange(n), spend.values, 1)[0]) if n >= 2 else 0.0
        )
    else:
        for f in ("spend_3m_avg_usd", "spend_12m_avg_usd", "spend_growth_3m_vs_12m",
                  "spend_growth_yoy", "spend_trend_slope_12m"):
            feats[f] = 0.0

    # Spend-quality features from transactions
    if not df_txns.empty and "amount_usd" in df_txns.columns:
        total_txn   = float(df_txns["amount_usd"].sum()) or 1.0
        credit_limit = float(
            df_stmts["credit_limit_usd"].iloc[-1]
            if not df_stmts.empty and "credit_limit_usd" in df_stmts.columns
            else 1.0
        )

        if "merchant_category_code" in df_txns.columns:
            mcc = df_txns["merchant_category_code"].astype(str)
            counts = mcc.value_counts(normalize=True)
            feats["mcc_diversity_score"] = float(-(counts * np.log(counts + 1e-9)).sum())
            feats["recurring_spend_pct"] = float(
                df_txns[mcc.isin(_RECURRING_MCC_PREFIXES)]["amount_usd"].sum() / total_txn
            )
            feats["discretionary_spend_pct"] = float(
                df_txns[mcc.isin(_DISCRETIONARY_MCC_PREFIXES)]["amount_usd"].sum() / total_txn
            )
        else:
            feats["mcc_diversity_score"]      = 0.0
            feats["recurring_spend_pct"]      = 0.0
            feats["discretionary_spend_pct"]  = 0.0

        feats["international_spend_pct"] = (
            float(df_txns["is_international"].mean())
            if "is_international" in df_txns.columns else 0.0
        )

        if "transaction_type" in df_txns.columns:
            ca_amount = float(df_txns[df_txns["transaction_type"] == "CASH_ADV"]["amount_usd"].sum())
            bt_amount = float(df_txns[df_txns["transaction_type"] == "BALANCE_TRANSFER"]["amount_usd"].sum())
            feats["cash_advance_pct_12m"]       = _safe_div(ca_amount, total_txn)
            feats["balance_transfer_pct_12m"]   = _safe_div(bt_amount, credit_limit)
        else:
            feats["cash_advance_pct_12m"]     = 0.0
            feats["balance_transfer_pct_12m"] = 0.0
    else:
        for f in ("mcc_diversity_score", "recurring_spend_pct", "discretionary_spend_pct",
                  "international_spend_pct", "cash_advance_pct_12m", "balance_transfer_pct_12m"):
            feats[f] = 0.0

    # ── Utilisation ────────────────────────────────────────────────────────
    if not df_stmts.empty and "utilization_rate" in df_stmts.columns:
        util = df_stmts["utilization_rate"].fillna(0.0)
        n    = len(util)
        feats["utilisation_3m_avg"]          = float(util.tail(3).mean())
        feats["utilisation_6m_avg"]          = float(util.tail(6).mean())
        feats["utilisation_12m_avg"]         = float(util.mean())
        feats["utilisation_volatility_12m"]  = float(util.std()) if n > 1 else 0.0
        feats["utilisation_trend_slope_12m"] = (
            float(np.polyfit(np.arange(n), util.values, 1)[0]) if n >= 2 else 0.0
        )
        feats["peak_utilisation_12m"]        = float(util.max())
        feats["months_near_limit"]           = int((util > 0.90).sum())
        feats["months_utilisation_zero"]     = int((util == 0.0).sum())
    else:
        for f in UTILISATION_FEATURES:
            feats[f] = 0.0

    # ── Risk signals ───────────────────────────────────────────────────────
    if not df_stmts.empty and "delinquency_status" in df_stmts.columns:
        dlq = df_stmts["delinquency_status"].fillna("CURRENT")
        feats["current_delinquency_status"] = int(
            _DELINQUENCY_STATUS_MAP.get(str(dlq.iloc[-1]), 0)
        )
        feats["dpd_months_12m"] = int((dlq != "CURRENT").sum())
        # max dpd: map status to approximate days
        dpd_days_map = {"CURRENT": 0, "DPD30": 30, "DPD60": 60,
                        "DPD90": 90, "DPD120": 120, "CHARGED_OFF": 180}
        feats["max_dpd_12m"] = int(max(dpd_days_map.get(s, 0) for s in dlq.values))
    else:
        feats["current_delinquency_status"] = 0
        feats["dpd_months_12m"]             = 0
        feats["max_dpd_12m"]                = 0

    if not df_stmts.empty and "bureau_score_current" in df_stmts.columns:
        bs = df_stmts["bureau_score_current"].fillna(660.0)
        current_bs = float(bs.iloc[-1])
        feats["bureau_score_current"]       = current_bs
        feats["bureau_score_3m_change"]     = (
            float(bs.iloc[-1] - bs.iloc[-4]) if len(bs) >= 4 else 0.0
        )
        feats["bureau_score_12m_change"]    = (
            float(bs.iloc[-1] - bs.iloc[0]) if len(bs) >= 2 else 0.0
        )
        feats["bureau_score_vs_origination"] = (
            current_bs - origination_score if origination_score is not None else 0.0
        )
    else:
        feats["bureau_score_current"]        = 660.0
        feats["bureau_score_3m_change"]      = 0.0
        feats["bureau_score_12m_change"]     = 0.0
        feats["bureau_score_vs_origination"] = 0.0

    # Lifetime delinquency counts from statements if present
    if not df_stmts.empty and "times_30dpd_lifetime" in df_stmts.columns:
        feats["times_30dpd_lifetime"] = int(df_stmts["times_30dpd_lifetime"].iloc[-1])
    else:
        feats["times_30dpd_lifetime"] = int(feats.get("dpd_months_12m", 0))

    if not df_stmts.empty and "times_90dpd_lifetime" in df_stmts.columns:
        feats["times_90dpd_lifetime"] = int(df_stmts["times_90dpd_lifetime"].iloc[-1])
    else:
        feats["times_90dpd_lifetime"] = 0

    feats["charge_off_flag"] = int(
        feats.get("current_delinquency_status", 0) == 5
    )

    # ── Account tenure & CLI/CLD history ──────────────────────────────────
    if not df_stmts.empty and "account_age_months" in df_stmts.columns:
        feats["account_age_months"] = int(df_stmts["account_age_months"].iloc[-1])
    elif not df_stmts.empty:
        feats["account_age_months"] = len(df_stmts)
    else:
        feats["account_age_months"] = 0

    if not df_events.empty and "event_type" in df_events.columns:
        cli_events = df_events[df_events["event_type"] == "CLI"]
        cld_events = df_events[df_events["event_type"] == "CLD"]
        feats["prior_cli_count"] = int(len(cli_events))
        feats["prior_cld_count"] = int(len(cld_events))

        feats["months_since_last_cli"] = (
            _months_since_last_event(cli_events) if not cli_events.empty else -1
        )
        feats["months_since_last_cld"] = (
            _months_since_last_event(cld_events) if not cld_events.empty else -1
        )
        feats["prior_cli_accepted_flag"] = (
            1 if "accepted" in df_events.columns and bool(
                cli_events["accepted"].any()
            ) else 0
        )
    else:
        feats["prior_cli_count"]         = 0
        feats["prior_cld_count"]         = 0
        feats["months_since_last_cli"]   = -1
        feats["months_since_last_cld"]   = -1
        feats["prior_cli_accepted_flag"] = 0

    # ── Validation clamp + NaN fill ────────────────────────────────────────
    feats = _clamp_and_fill(feats)

    # Return in canonical ALL_FEATURES order
    return {k: feats.get(k, 0.0) for k in ALL_FEATURES}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _latest_streak(mask: pd.Series, from_end: bool = False) -> int:
    """Count the current consecutive True streak (from the end if from_end)."""
    vals = mask.values[::-1] if from_end else mask.values
    streak = 0
    for v in vals:
        if bool(v):
            streak += 1
        else:
            break
    return streak


def _safe_div(a: float, b: float) -> float:
    return float(a) / float(b) if abs(float(b)) > 1e-9 else 0.0


def _yoy_growth(series: pd.Series) -> float:
    """3-month trailing avg this year vs same window prior year."""
    if len(series) < 15:
        return 0.0
    recent  = float(series.tail(3).mean())
    prior   = float(series.iloc[-15:-12].mean()) if len(series) >= 15 else float(series.head(3).mean())
    return _safe_div(recent - prior, prior)


def _months_since_last_event(events: pd.DataFrame) -> int:
    """Return approximate months since the most recent event."""
    if events.empty or "event_date" not in events.columns:
        return -1
    try:
        import pandas as pd
        last = pd.to_datetime(events["event_date"]).max()
        delta = pd.Timestamp.now() - last
        return max(int(delta.days // 30), 0)
    except Exception:
        return -1


def _clamp_and_fill(feats: Dict[str, float]) -> Dict[str, float]:
    """Replace NaN / inf with 0 and apply hard clamps from the quality gate spec."""
    clamps = {
        "payment_rate_3m_avg":    (0.0, 5.0),
        "payment_rate_6m_avg":    (0.0, 5.0),
        "payment_rate_12m_avg":   (0.0, 5.0),
        "utilisation_12m_avg":    (0.0, 1.2),
        "utilisation_3m_avg":     (0.0, 1.2),
        "utilisation_6m_avg":     (0.0, 1.2),
        "peak_utilisation_12m":   (0.0, 2.0),
        "bureau_score_current":   (300.0, 850.0),
        "cash_advance_pct_12m":   (0.0, 1.0),
        "balance_transfer_pct_12m": (0.0, 1.0),
        "international_spend_pct":  (0.0, 1.0),
        "recurring_spend_pct":      (0.0, 1.0),
        "discretionary_spend_pct":  (0.0, 1.0),
    }
    result = {}
    for k, v in feats.items():
        try:
            v_float = float(v)
        except (ValueError, TypeError):
            v_float = 0.0
        if not np.isfinite(v_float):
            v_float = 0.0
        if k in clamps:
            lo, hi = clamps[k]
            v_float = float(np.clip(v_float, lo, hi))
        result[k] = v_float
    return result
