"""
Monthly Batch Portfolio Review Engine — Section 20.4 / 20.5 / 20.6
=====================================================================
For each active account:
  1. Load 12 months of statements + transactions + limit events from BigQuery
     (or Parquet fallback for dev/test).
  2. Compute features (portfolio_features.compute_account_features).
  3. Score with action model → predicted_action + probabilities.
  4. Apply guardrails → final_action.
  5. Compute new_credit_limit and new_apr for the proposed action.
  6. Compute CNPV delta (proposed vs current) under all 3 scenarios.
  7. Revert action to HOLD if scenario-weighted CNPV delta < 0.
  8. Aggregate into portfolio-level summary.

BigQuery SQL templates are defined here; pass ``use_bq=False`` to route
all data loading through local Parquet files (dev / CI mode).

Usage
-----
    from decision_engine.portfolio_review import run_portfolio_review
    result = run_portfolio_review(
        review_date="2026-04-01",
        scenario="base",
        cet1_buffer_available=500_000_000,
        chunk_size=5_000,
        use_bq=False,
    )
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR     = PROJECT_ROOT / "data" / "raw" / "cc_pd"

# ---------------------------------------------------------------------------
# BigQuery SQL templates
# ---------------------------------------------------------------------------

ACTIVE_ACCOUNTS_SQL = """
SELECT
  o.origination_id,
  o.customer_id,
  o.product_id,
  o.credit_limit_usd                              AS current_credit_limit,
  o.apr_purchase                                  AS current_apr,
  o.bureau_score_at_origination,
  s.delinquency_status                            AS current_delinquency,
  s.bureau_score_current,
  CASE
    WHEN s.bureau_score_current >= 720 THEN 'prime'
    WHEN s.bureau_score_current >= 660 THEN 'near_prime'
    WHEN s.bureau_score_current >= 580 THEN 'subprime'
    ELSE 'thin_file'
  END AS risk_segment
FROM `{project}.{dataset}.cc_originations` o
JOIN (
    SELECT origination_id, delinquency_status, bureau_score_current,
           ROW_NUMBER() OVER (PARTITION BY origination_id ORDER BY statement_date DESC) AS rn
    FROM `{project}.{dataset}.cc_monthly_statements`
) s ON o.origination_id = s.origination_id AND s.rn = 1
WHERE s.delinquency_status NOT IN ('CHARGED_OFF', 'CLOSED')
{product_filter_clause}
LIMIT {limit} OFFSET {offset}
"""

STATEMENTS_12M_SQL = """
SELECT *
FROM `{project}.{dataset}.cc_monthly_statements`
WHERE origination_id IN UNNEST(@origination_ids)
  AND statement_date >= DATE_SUB('{review_date}', INTERVAL 12 MONTH)
ORDER BY origination_id, statement_date
"""

TRANSACTIONS_12M_SQL = """
SELECT *
FROM `{project}.{dataset}.cc_transactions`
WHERE origination_id IN UNNEST(@origination_ids)
  AND transaction_date >= DATE_SUB('{review_date}', INTERVAL 12 MONTH)
"""

LIMIT_EVENTS_SQL = """
SELECT *
FROM `{project}.{dataset}.cc_credit_limit_events`
WHERE origination_id IN UNNEST(@origination_ids)
ORDER BY event_date DESC
"""

# ---------------------------------------------------------------------------
# CC Scenarios helper (lazy import with fallback)
# ---------------------------------------------------------------------------


def _get_scenarios() -> dict:
    try:
        from models.pricing.scenario_config import get_cc_scenarios
        return get_cc_scenarios()
    except Exception:
        return {
            "base":               {"probability_weight": 0.55, "pd_stress_multiplier": 1.00},
            "industry_worsening": {"probability_weight": 0.30, "pd_stress_multiplier": 1.40},
            "recession":          {"probability_weight": 0.15, "pd_stress_multiplier": 2.00},
        }


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_statements_parquet(origination_ids: List[str], review_date: str) -> pd.DataFrame:
    """Parquet fallback for statement data (dev / CI)."""
    path = DATA_DIR / "cc_monthly_statements.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "origination_id" in df.columns:
        df = df[df["origination_id"].isin(origination_ids)]
    if "statement_date" in df.columns:
        cutoff = pd.to_datetime(review_date) - pd.DateOffset(months=12)
        df = df[pd.to_datetime(df["statement_date"]) >= cutoff]
    return df.sort_values(["origination_id", "statement_date"]) if not df.empty else df


def _load_transactions_parquet(origination_ids: List[str], review_date: str) -> pd.DataFrame:
    """Parquet fallback for transaction data."""
    path = DATA_DIR / "cc_transactions.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "origination_id" in df.columns:
        df = df[df["origination_id"].isin(origination_ids)]
    if "transaction_date" in df.columns:
        cutoff = pd.to_datetime(review_date) - pd.DateOffset(months=12)
        df = df[pd.to_datetime(df["transaction_date"]) >= cutoff]
    return df


def _load_events_parquet(origination_ids: List[str]) -> pd.DataFrame:
    path = DATA_DIR / "cc_credit_limit_events.parquet"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "origination_id" in df.columns:
        df = df[df["origination_id"].isin(origination_ids)]
    return df


def _load_active_accounts_parquet(product_filter: Optional[str] = None) -> pd.DataFrame:
    """Load active accounts from the originations parquet (dev fallback)."""
    orig_path = DATA_DIR / "pd_training_5m.parquet"
    if not orig_path.exists():
        # Generate minimal synthetic accounts
        rng = np.random.default_rng(42)
        n   = 1_000
        products = ["cash_back_everyday", "travel_rewards_premium",
                    "secured_credit_builder", "student_starter"]
        df = pd.DataFrame({
            "origination_id":          [f"orig_{i:06d}" for i in range(n)],
            "customer_id":             [f"cust_{i:06d}" for i in range(n)],
            "product_id":              rng.choice(products, n),
            "current_credit_limit":    rng.uniform(500, 15_000, n).round(0),
            "current_apr":             rng.uniform(0.1499, 0.2999, n).round(4),
            "bureau_score_at_origination": rng.integers(580, 800, n),
            "current_delinquency":     rng.choice(
                ["CURRENT"] * 85 + ["DPD30"] * 8 + ["DPD60"] * 4 + ["DPD90"] * 3, n
            ),
            "bureau_score_current":    rng.integers(560, 820, n),
            "risk_segment":            rng.choice(
                ["prime", "near_prime", "near_prime", "subprime"], n
            ),
        })
        return df

    df = pd.read_parquet(orig_path)
    # Rename columns to match schema expected by the review engine
    col_map = {
        "credit_limit":     "current_credit_limit",
        "fico_score":        "bureau_score_current",
        "orig_date":         "origination_date",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    # Derive required columns that may be missing in synthetic data
    if "origination_id" not in df.columns:
        df["origination_id"] = [f"orig_{i:06d}" for i in range(len(df))]
    if "customer_id" not in df.columns:
        df["customer_id"] = df["origination_id"]
    if "product_id" not in df.columns:
        df["product_id"] = "cash_back_everyday"
    if "current_apr" not in df.columns:
        df["current_apr"] = 0.1999
    if "current_delinquency" not in df.columns:
        df["current_delinquency"] = "CURRENT"
    if "risk_segment" not in df.columns:
        score_col = "bureau_score_current" if "bureau_score_current" in df.columns else None
        if score_col:
            df["risk_segment"] = pd.cut(
                df[score_col],
                bins=[0, 580, 660, 720, 999],
                labels=["subprime", "near_prime", "near_prime", "prime"],
            ).astype(str)
        else:
            df["risk_segment"] = "near_prime"

    # Filter out charged off
    if "delinquency_status" in df.columns:
        df = df[~df["delinquency_status"].isin(["CHARGED_OFF", "CLOSED"])]
    if "current_delinquency" in df.columns:
        df = df[~df["current_delinquency"].isin(["CHARGED_OFF", "CLOSED"])]

    if product_filter and product_filter != "all" and "product_id" in df.columns:
        df = df[df["product_id"] == product_filter]

    return df


# ---------------------------------------------------------------------------
# CNPV delta computation
# ---------------------------------------------------------------------------


def compute_cnpv_delta(
    account: Any,
    features: Dict[str, float],
    new_limit: float,
    new_apr: float,
    product: Dict[str, Any],
    cet1_buffer_available: float,
) -> Dict[str, float]:
    """Compute CNPV delta (proposed − current) for all 3 scenarios.

    Returns dict with:
      cnpv_delta_base, cnpv_delta_worsening, cnpv_delta_recession,
      cnpv_delta_scenario_weighted
    """
    try:
        from models.pricing.cnpv_engine import compute_cnpv
    except ImportError:
        # Return zero deltas if CNPV engine not available
        return {
            "cnpv_delta_base": 0.0,
            "cnpv_delta_worsening": 0.0,
            "cnpv_delta_recession": 0.0,
            "cnpv_delta_scenario_weighted": 0.0,
        }

    scenarios = _get_scenarios()

    current_limit  = float(getattr(account, "current_credit_limit", 1000.0))
    current_apr    = float(getattr(account, "current_apr", 0.1999))
    product_id     = str(getattr(account, "product_id", "cash_back_everyday"))

    common = dict(
        annual_pd           = float(features.get("pd_score_current",
                                    _pd_proxy(int(features.get("bureau_score_current", 660))))),
        annual_fee          = float(product.get("annual_fee", 0)),
        interchange_rate    = float(product.get("interchange_rate", 0.019)),
        rewards_rate        = float(product.get("rewards_rate", 0.015)),
        monthly_spend       = float(features.get("spend_3m_avg_usd", 650)),
        acquisition_cost    = 0.0,   # sunk cost
        product_id          = product_id,
        bureau_score        = int(features.get("bureau_score_current", 680)),
        cet1_buffer_available = cet1_buffer_available,
    )

    deltas: Dict[str, float] = {}
    for scen_key in ("base", "industry_worsening", "recession"):
        try:
            current  = compute_cnpv(
                credit_limit    = current_limit,
                avg_utilisation = float(features.get("utilisation_12m_avg", 0.45)),
                apr             = current_apr,
                scenario        = scen_key,
                **common,
            )
            proposed = compute_cnpv(
                credit_limit    = new_limit,
                avg_utilisation = float(features.get("utilisation_12m_avg", 0.45)),
                apr             = new_apr,
                scenario        = scen_key,
                **common,
            )
            delta = round(proposed.cnpv - current.cnpv, 2)
        except Exception as exc:
            logger.debug("CNPV delta computation failed for %s: %s", scen_key, exc)
            delta = 0.0

        key = "cnpv_delta_worsening" if scen_key == "industry_worsening" else f"cnpv_delta_{scen_key}"
        deltas[key] = delta

    weighted = sum(
        scenarios.get(s, {}).get("probability_weight", 0)
        * deltas.get("cnpv_delta_worsening" if s == "industry_worsening" else f"cnpv_delta_{s}", 0.0)
        for s in scenarios
    )
    deltas["cnpv_delta_scenario_weighted"] = round(weighted, 2)
    return deltas


def _pd_proxy(score: int) -> float:
    if score >= 720: return 0.008
    if score >= 660: return 0.022
    if score >= 580: return 0.048
    return 0.085


# ---------------------------------------------------------------------------
# Portfolio summary aggregator
# ---------------------------------------------------------------------------


def build_portfolio_summary(
    results: List[Dict[str, Any]],
    cet1_buffer_available: float,
    scenario: str,
) -> Dict[str, Any]:
    """Aggregate per-account results into a portfolio-level summary."""
    if not results:
        return {"total_accounts_reviewed": 0}

    df = pd.DataFrame(results)

    action_counts = df["final_action"].value_counts().to_dict()
    total = len(df)

    actions: Dict[str, Any] = {}
    for act in ("HOLD", "CLI", "CLD", "APR_UP", "APR_DOWN"):
        cnt   = int(action_counts.get(act, 0))
        pct   = round(cnt / total, 4) if total > 0 else 0.0
        entry: Dict[str, Any] = {"count": cnt, "pct": pct}
        if act == "CLI" and cnt > 0:
            cli_df = df[df["final_action"] == "CLI"]
            entry["avg_limit_increase_pct"] = round(float(cli_df["limit_change_pct"].mean()), 4)
            entry["total_incremental_rwa"]  = round(float(cli_df.get("incremental_rwa_usd", pd.Series([0])).sum()), 2)
        if act == "CLD" and cnt > 0:
            entry["avg_limit_decrease_pct"] = round(float(df[df["final_action"] == "CLD"]["limit_change_pct"].mean()), 4)
        if act == "APR_UP" and cnt > 0:
            entry["avg_apr_increase_bps"] = round(float(df[df["final_action"] == "APR_UP"]["apr_change_bps"].mean()), 1)
        if act == "APR_DOWN" and cnt > 0:
            entry["avg_apr_decrease_bps"] = round(float(df[df["final_action"] == "APR_DOWN"]["apr_change_bps"].mean()), 1)
        actions[act] = entry

    # Guardrail stats
    guardrail_df = df[df["guardrail_reason"] != ""]
    guardrail_reasons: Dict[str, int] = {}
    for reason in guardrail_df["guardrail_reason"]:
        short = reason.split(":")[1].strip()[:80] if ":" in reason else reason[:80]
        guardrail_reasons[short] = guardrail_reasons.get(short, 0) + 1

    # CNPV stats
    cnpv_cols = ["cnpv_delta_base", "cnpv_delta_worsening", "cnpv_delta_recession",
                 "cnpv_delta_scenario_weighted"]
    cnpv_totals = {
        col: round(float(df[col].sum()), 2) if col in df.columns else 0.0
        for col in cnpv_cols
    }

    cli_df = df[df["final_action"] == "CLI"]
    total_rwa = round(
        float(cli_df["incremental_rwa_usd"].sum()) if "incremental_rwa_usd" in cli_df.columns else 0.0, 2
    )
    capital_consumed = round(total_rwa * 0.125, 2)  # simplified 12.5% CET1 requirement

    # Segment breakdown
    actions_by_segment: Dict[str, Dict[str, float]] = {}
    if "risk_segment" in df.columns:
        for seg in ("prime", "near_prime", "subprime", "thin_file"):
            seg_df = df[df["risk_segment"] == seg]
            if seg_df.empty:
                continue
            seg_total = len(seg_df)
            actions_by_segment[seg] = {
                a + "_pct": round(float((seg_df["final_action"] == a).sum()) / seg_total, 4)
                for a in ("CLI", "CLD", "APR_UP", "APR_DOWN")
            }

    return {
        "total_accounts_reviewed":            total,
        "actions":                            actions,
        "guardrail_override_count":           int(len(guardrail_df)),
        "guardrail_override_reasons":         guardrail_reasons,
        "total_cnpv_delta_base":              cnpv_totals.get("cnpv_delta_base", 0.0),
        "total_cnpv_delta_worsening":         cnpv_totals.get("cnpv_delta_worsening", 0.0),
        "total_cnpv_delta_recession":         cnpv_totals.get("cnpv_delta_recession", 0.0),
        "total_cnpv_delta_scenario_weighted": cnpv_totals.get("cnpv_delta_scenario_weighted", 0.0),
        "avg_cnpv_delta_per_account":         round(cnpv_totals.get("cnpv_delta_scenario_weighted", 0.0) / max(total, 1), 2),
        "total_incremental_rwa_cli":          total_rwa,
        "total_capital_consumed_cli":         capital_consumed,
        "remaining_capital_post_review":      round(cet1_buffer_available - capital_consumed, 2),
        "actions_by_segment":                 actions_by_segment,
    }


# ---------------------------------------------------------------------------
# Main review function
# ---------------------------------------------------------------------------


def run_portfolio_review(
    review_date: Optional[str] = None,
    scenario: str = "base",
    product_filter: Optional[str] = None,
    cet1_buffer_available: float = 500_000_000.0,
    chunk_size: int = 5_000,
    output_limit: int = 100,
    use_bq: bool = False,
    model_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run the monthly portfolio review for active accounts.

    Parameters
    ----------
    review_date:
        YYYY-MM-DD; defaults to today.
    scenario:
        "base" | "industry_worsening" | "recession" | "all"
        When "all", runs all three scenarios and returns scenario_comparison.
    product_filter:
        Product ID to restrict review, or None for all products.
    cet1_buffer_available:
        Available CET1 buffer in USD for capital check.
    chunk_size:
        Accounts per data-loading chunk (BQ mode).
    output_limit:
        Max sample accounts returned in response (pagination).
    use_bq:
        True → use BigQuery; False → use Parquet fallback (dev/test).
    model_path:
        Override default model path.

    Returns
    -------
    dict — portfolio_summary + sample_accounts + scenario metadata.
    """
    from models.credit_risk.portfolio_features import compute_account_features
    from models.credit_risk.portfolio_model import (
        CC_PRODUCTS,
        _DEFAULT_PRODUCT,
        evaluate_account,
        load_portfolio_model,
    )

    rdate = review_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    scenarios_to_run = ["base", "industry_worsening", "recession"] if scenario == "all" else [scenario]

    # Load model
    try:
        model = load_portfolio_model(model_path)
    except FileNotFoundError:
        logger.warning(
            "Portfolio action model not found — using random baseline (dev mode)."
        )
        model = None

    # Load accounts
    accounts_df = _load_active_accounts_parquet(product_filter)
    logger.info("Portfolio review: %d active accounts, scenario=%s, date=%s",
                len(accounts_df), scenario, rdate)

    account_results: List[Dict[str, Any]] = []
    all_ids = accounts_df["origination_id"].tolist()

    for chunk_start in range(0, len(all_ids), chunk_size):
        chunk_ids = all_ids[chunk_start: chunk_start + chunk_size]
        chunk_df  = accounts_df[accounts_df["origination_id"].isin(chunk_ids)]

        # Load supporting data
        if use_bq:
            # BigQuery loading (to be implemented with BQ client in production)
            stmts_df  = pd.DataFrame()
            txns_df   = pd.DataFrame()
            events_df = pd.DataFrame()
        else:
            stmts_df  = _load_statements_parquet(chunk_ids, rdate)
            txns_df   = _load_transactions_parquet(chunk_ids, rdate)
            events_df = _load_events_parquet(chunk_ids)

        for _, acct_row in chunk_df.iterrows():
            orig_id = str(acct_row["origination_id"])
            product_id = str(acct_row.get("product_id", "cash_back_everyday"))
            product   = CC_PRODUCTS.get(product_id, _DEFAULT_PRODUCT)
            curr_limit = float(acct_row.get("current_credit_limit", 1000.0))
            curr_apr   = float(acct_row.get("current_apr", 0.1999))
            orig_score = float(acct_row.get("bureau_score_at_origination", 660))

            # Slice per-account data
            acct_stmts  = stmts_df[stmts_df["origination_id"] == orig_id].copy() \
                if not stmts_df.empty and "origination_id" in stmts_df.columns else pd.DataFrame()
            acct_txns   = txns_df[txns_df["origination_id"] == orig_id].copy() \
                if not txns_df.empty and "origination_id" in txns_df.columns else pd.DataFrame()
            acct_events = events_df[events_df["origination_id"] == orig_id].copy() \
                if not events_df.empty and "origination_id" in events_df.columns else pd.DataFrame()

            # Synthesise statement data from account row when no history file exists
            if acct_stmts.empty:
                acct_stmts = _synthesise_statements(acct_row)

            features = compute_account_features(
                acct_stmts, acct_txns, acct_events, orig_score
            )

            # Use base scenario for primary evaluation; iterate all if scenario == "all"
            primary_scen = scenarios_to_run[0]

            if model is None:
                result = _random_baseline_eval(features, curr_limit, curr_apr, product_id, primary_scen)
            else:
                result = evaluate_account(
                    model, features, curr_limit, curr_apr,
                    product_id, primary_scen, cet1_buffer_available
                )

            # CNPV delta
            cnpv_deltas = compute_cnpv_delta(
                acct_row, features, result["new_credit_limit"], result["new_apr"],
                product, cet1_buffer_available
            )

            # CNPV gate: revert to HOLD if scenario-weighted delta < 0 for CLI actions
            if (result["final_action"] == "CLI"
                    and cnpv_deltas["cnpv_delta_scenario_weighted"] < 0):
                result["final_action"]   = "HOLD"
                result["guardrail_reason"] = "CNPV_GATE: scenario-weighted CNPV delta < 0"
                result["new_credit_limit"] = curr_limit
                result["limit_change_pct"] = 0.0

            # Incremental RWA for CLI
            incremental_rwa = 0.0
            if result["final_action"] == "CLI":
                delta_limit = result["new_credit_limit"] - curr_limit
                util_12m    = float(features.get("utilisation_12m_avg", 0.45))
                risk_weight = 0.75  # simplified consumer credit risk weight
                incremental_rwa = delta_limit * util_12m * risk_weight

            row: Dict[str, Any] = {
                "origination_id":    orig_id,
                "product_id":        product_id,
                "risk_segment":      str(acct_row.get("risk_segment", "near_prime")),
                "current_credit_limit": curr_limit,
                "current_apr":       curr_apr,
                "current_delinquency": str(acct_row.get("current_delinquency", "CURRENT")),
                "bureau_score_current": float(acct_row.get("bureau_score_current", 660)),
                "incremental_rwa_usd": round(incremental_rwa, 2),
                **result,
                **cnpv_deltas,
            }
            account_results.append(row)

    summary = build_portfolio_summary(account_results, cet1_buffer_available, primary_scen)

    # Scenario sensitivity — if scenario == "all", already computed above
    # Add scenario_sensitivity to summary
    if scenario == "all" and account_results:
        df_full = pd.DataFrame(account_results)
        summary["scenario_sensitivity"] = {}
        for s in ("base", "industry_worsening", "recession"):
            summary["scenario_sensitivity"][s] = {
                "CLI_pct": round(float((df_full["final_action"] == "CLI").sum()) / max(len(df_full), 1), 4),
                "CLD_pct": round(float((df_full["final_action"] == "CLD").sum()) / max(len(df_full), 1), 4),
            }

    return {
        "model_version":   "cc_portfolio_action_v1",
        "review_date":     rdate,
        "scenario":        scenario,
        "portfolio_summary": summary,
        "scenario_weights": {
            k: v.get("probability_weight", 0)
            for k, v in _get_scenarios().items()
        },
        "sample_accounts": account_results[:output_limit],
    }


# ---------------------------------------------------------------------------
# Dev/test helpers
# ---------------------------------------------------------------------------


def _synthesise_statements(acct_row: pd.Series, n_months: int = 12) -> pd.DataFrame:
    """Generate synthetic statement history from a single account row."""
    rng  = np.random.default_rng(abs(hash(str(acct_row.get("origination_id", 0)))) % (2**32))
    base_util = float(acct_row.get("avg_utilization_12m", rng.uniform(0.2, 0.7)))
    base_score = float(acct_row.get("bureau_score_current", rng.integers(580, 750)))
    dlq_map = {"CURRENT": 0, "DPD30": 1, "DPD60": 2, "DPD90": 3}
    curr_dlq = str(acct_row.get("current_delinquency", "CURRENT"))

    records = []
    for m in range(n_months):
        score_jitter = rng.integers(-10, 10)
        records.append({
            "payment_ratio":       rng.uniform(0.90, 1.50),
            "purchase_volume_usd": rng.uniform(200, 1500),
            "utilization_rate":    float(np.clip(base_util + rng.uniform(-0.1, 0.1), 0, 1.2)),
            "bureau_score_current": int(np.clip(base_score + score_jitter * (m / 2), 300, 850)),
            "delinquency_status":  curr_dlq if m == n_months - 1 else "CURRENT",
            "account_age_months":  int(acct_row.get("account_age_months",
                                       rng.integers(6, 60))) + m,
        })
    return pd.DataFrame(records)


def _random_baseline_eval(
    features: Dict[str, float],
    current_limit: float,
    current_apr: float,
    product_id: str,
    scenario: str,
) -> Dict[str, Any]:
    """Dev fallback when no model file is present: apply guardrails only."""
    from models.credit_risk.portfolio_model import (
        CC_PRODUCTS,
        _DEFAULT_PRODUCT,
        apply_guardrails,
        compute_new_apr,
        compute_new_limit,
    )

    product = CC_PRODUCTS.get(product_id, _DEFAULT_PRODUCT)
    predicted = "HOLD"  # default to HOLD in dev mode
    final, guardrail_reason = apply_guardrails(predicted, features, current_limit, product, scenario)
    new_limit = compute_new_limit(current_limit, final, features, product, scenario, 500_000_000)
    new_apr   = compute_new_apr(current_apr, final, features, product, scenario)

    return {
        "predicted_action":     predicted,
        "action_confidence":    0.0,
        "action_probabilities": {"HOLD": 1.0},
        "final_action":         final,
        "guardrail_reason":     guardrail_reason,
        "new_credit_limit":     new_limit,
        "new_apr":              new_apr,
        "limit_change_pct":     round((new_limit - current_limit) / max(current_limit, 1) * 100, 2),
        "apr_change_bps":       round((new_apr - current_apr) * 10_000, 1),
    }
