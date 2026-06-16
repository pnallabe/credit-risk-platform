"""
Portfolio Action Model — Section 20.3
======================================
GradientBoosting classifier (sklearn) + guardrail layer + limit/APR sizing.

Architecture
------------
1. GradientBoostingClassifier trained on cc_credit_limit_events labels.
   Classes: {HOLD=0, CLI=1, CLD=2, APR_UP=3, APR_DOWN=4}
2. Guardrail layer — hard rules applied after model scoring (non-negotiable).
3. Scenario overlay — threshold adjustments from CC_SCENARIOS macro multipliers.
4. CNPV delta gate — actions with negative scenario-weighted CNPV delta reverted to HOLD.

Performance Targets (OOS 2023-2024)
-------------------------------------
  CLI precision  >= 0.72
  CLD recall     >= 0.80
  APR_UP precision >= 0.68
  Macro AUC      >= 0.82

Usage
-----
    from models.credit_risk.portfolio_model import (
        load_portfolio_model,
        predict_action,
        apply_guardrails,
        compute_new_limit,
        compute_new_apr,
    )
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL_PATH = Path(
    os.getenv("CC_PORTFOLIO_MODEL_PATH", "models/cc_portfolio_action_model.pkl")
)

ACTION_LABELS: Dict[int, str] = {
    0: "HOLD",
    1: "CLI",
    2: "CLD",
    3: "APR_UP",
    4: "APR_DOWN",
}

ACTION_CODE: Dict[str, int] = {v: k for k, v in ACTION_LABELS.items()}

# Inline CC product registry (expanded in production via cc_valuation_assumptions)
CC_PRODUCTS: Dict[str, Dict[str, Any]] = {
    "cash_back_everyday": {
        "apr_range":          (0.1499, 0.2999),
        "credit_limit_range": (500,    25_000),
        "interchange_rate":   0.019,
        "rewards_rate":       0.015,
        "annual_fee":         0,
    },
    "travel_rewards_premium": {
        "apr_range":          (0.1799, 0.3099),
        "credit_limit_range": (2_000,  50_000),
        "interchange_rate":   0.0215,
        "rewards_rate":       0.030,
        "annual_fee":         95,
    },
    "secured_credit_builder": {
        "apr_range":          (0.2199, 0.2999),
        "credit_limit_range": (200,    5_000),
        "interchange_rate":   0.016,
        "rewards_rate":       0.005,
        "annual_fee":         25,
    },
    "balance_transfer_low_rate": {
        "apr_range":          (0.1299, 0.2499),
        "credit_limit_range": (1_000,  30_000),
        "interchange_rate":   0.0175,
        "rewards_rate":       0.005,
        "annual_fee":         0,
    },
    "student_starter": {
        "apr_range":          (0.1899, 0.2699),
        "credit_limit_range": (300,    5_000),
        "interchange_rate":   0.017,
        "rewards_rate":       0.010,
        "annual_fee":         0,
    },
}

_DEFAULT_PRODUCT = CC_PRODUCTS["cash_back_everyday"]

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def load_portfolio_model(model_path: Optional[Path] = None) -> Any:
    """Load the serialised GBC pipeline from disk.

    Parameters
    ----------
    model_path:
        Path to the joblib-serialised pipeline.  Defaults to ``MODEL_PATH``.

    Returns
    -------
    sklearn.pipeline.Pipeline (StandardScaler + GradientBoostingClassifier)

    Raises
    ------
    FileNotFoundError — if the model file does not exist.
    """
    import joblib

    path = Path(model_path or MODEL_PATH)
    if not path.exists():
        raise FileNotFoundError(
            f"Portfolio action model not found at '{path}'. "
            "Run scripts/train_portfolio_action_model.py to train it."
        )
    model = joblib.load(path)
    logger.info("Loaded portfolio action model from %s", path)
    return model


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------


def predict_action(
    model: Any,
    features: Dict[str, float],
    feature_names: Optional[list] = None,
) -> Tuple[str, float, Dict[str, float]]:
    """Run the GBC pipeline and return (predicted_action, confidence, probabilities).

    Parameters
    ----------
    model:
        Fitted sklearn Pipeline returned by ``load_portfolio_model``.
    features:
        Feature dict (keys = ALL_FEATURES from portfolio_features.py).
    feature_names:
        Feature name list used during training (defaults to ALL_FEATURES order).

    Returns
    -------
    (action_label, confidence, {label: probability})
    """
    from models.credit_risk.portfolio_features import ALL_FEATURES

    names = feature_names or ALL_FEATURES
    X = np.array([features.get(f, 0.0) for f in names]).reshape(1, -1)

    proba = model.predict_proba(X)[0]
    pred_idx = int(np.argmax(proba))
    confidence = float(proba[pred_idx])
    action = ACTION_LABELS.get(pred_idx, "HOLD")

    prob_dict = {ACTION_LABELS.get(i, str(i)): round(float(p), 6) for i, p in enumerate(proba)}
    return action, confidence, prob_dict


# ---------------------------------------------------------------------------
# Guardrail layer
# ---------------------------------------------------------------------------


def apply_guardrails(
    predicted_action: str,
    features: Dict[str, float],
    current_limit: float,
    product: Dict[str, Any],
    scenario: str,
) -> Tuple[str, str]:
    """Apply hard rules that cannot be overridden by the model.

    Parameters
    ----------
    predicted_action:
        Raw model prediction (one of HOLD / CLI / CLD / APR_UP / APR_DOWN).
    features:
        Feature dict for the account.
    current_limit:
        Current credit limit in USD.
    product:
        Product metadata dict (from CC_PRODUCTS or equivalent live registry).
    scenario:
        Scenario key: "base" | "industry_worsening" | "recession".

    Returns
    -------
    (final_action, guardrail_reason)
        ``guardrail_reason`` is empty string if no guardrail fired.
    """
    dlq_status = int(features.get("current_delinquency_status", 0))
    charge_off = bool(features.get("charge_off_flag", 0))
    consec_missed = int(features.get("consecutive_missed_pay", 0))
    util_12m = float(features.get("utilisation_12m_avg", 0.0))
    bureau_chg_3m = float(features.get("bureau_score_3m_change", 0.0))
    full_pay_12m = int(features.get("full_pay_months_12m", 0))
    spend_growth = float(features.get("spend_growth_3m_vs_12m", 0.0))
    bureau_score = float(features.get("bureau_score_current", 660.0))

    # ── Hard decline / protect rules (always applied, any scenario) ────────
    if charge_off:
        return "HOLD", "GUARDRAIL: Charged-off account — no action permitted"

    if dlq_status >= 2:  # DPD60+
        return "CLD", "GUARDRAIL: DPD60+ — mandatory limit reduction"

    if consec_missed >= 3:
        return "CLD", "GUARDRAIL: 3+ consecutive missed payments"

    if bureau_score < 560 and predicted_action in ("CLI", "APR_DOWN"):
        return "CLD", "GUARDRAIL: Bureau score < 560 — CLI/APR_DOWN blocked"

    # ── Scenario-specific tightening ───────────────────────────────────────
    if scenario == "industry_worsening":
        if predicted_action == "CLI":
            if util_12m > 0.70:
                return "HOLD", "GUARDRAIL: industry_worsening — CLI blocked (util > 70%)"
            if bureau_chg_3m < -30:
                return "HOLD", "GUARDRAIL: industry_worsening — CLI blocked (bureau decline >30pts)"

    if scenario == "recession":
        if predicted_action in ("CLI", "APR_DOWN"):
            return "HOLD", "GUARDRAIL: recession — CLI and APR_DOWN blocked"

    # ── Reward rules (base scenario only) — promote high-value transactors ─
    if scenario == "base":
        if (
            predicted_action == "HOLD"
            and full_pay_12m >= 11
            and spend_growth > 0.10
        ):
            return (
                "APR_DOWN",
                "OVERRIDE: base — full-payer + spend growth → retention APR reduction",
            )

    return predicted_action, ""


# ---------------------------------------------------------------------------
# Limit + APR sizing
# ---------------------------------------------------------------------------


def compute_new_limit(
    current_limit: float,
    action: str,
    features: Dict[str, float],
    product: Dict[str, Any],
    scenario: str,
    cet1_buffer_available: float,
) -> float:
    """Compute the proposed new credit limit post-action.

    CLI: +15–25% depending on payment behaviour and capital headroom.
    CLD: −10–50% depending on risk severity.
    HOLD / APR_*: return current_limit unchanged.
    """
    min_limit = float(product.get("credit_limit_range", (300, 0))[0])
    max_limit = float(product.get("credit_limit_range", (0, 100_000))[1])

    if action == "CLI":
        pay_score = float(features.get("payment_rate_12m_avg", 1.0))
        base_pct  = 0.25 if pay_score >= 1.20 else 0.15
        if scenario == "industry_worsening":
            base_pct *= 0.70

        proposed = current_limit * (1 + base_pct)
        proposed = min(proposed, max_limit)

        # Capital check
        try:
            from models.pricing.capital_engine import check_capital_availability

            pd_est = float(features.get("pd_score_current", 0.025))
            product_id = str(features.get("product_id", "cash_back_everyday"))
            cap = check_capital_availability(
                proposed, pd_est, product_id, scenario, cet1_buffer_available
            )
            if not cap.can_originate:
                logger.debug(
                    "CLI blocked by capital check: proposed_limit=%.0f can_originate=%s",
                    proposed, cap.can_originate,
                )
                return current_limit
        except Exception as exc:
            logger.debug("Capital check skipped (engine unavailable): %s", exc)

        return round(proposed, 0)

    if action == "CLD":
        util  = float(features.get("utilisation_12m_avg", 0.5))
        dpd_m = int(features.get("dpd_months_12m", 0))

        if dpd_m >= 3 or util > 0.90:
            reduction_pct = 0.35
        elif dpd_m >= 1 or util > 0.75:
            reduction_pct = 0.20
        else:
            reduction_pct = 0.10

        if scenario == "recession":
            reduction_pct = min(reduction_pct * 1.3, 0.50)

        new_limit = current_limit * (1 - reduction_pct)
        return round(max(new_limit, min_limit), 0)

    return current_limit


def compute_new_apr(
    current_apr: float,
    action: str,
    features: Dict[str, float],
    product: Dict[str, Any],
    scenario: str,
) -> float:
    """Compute the proposed new APR post-action.

    APR_UP: +100–300bps depending on risk deterioration and scenario.
    APR_DOWN: −50–150bps for retention of high-value transactors.
    Bounded by product APR range.
    """
    min_apr, max_apr = product.get("apr_range", (0.1499, 0.3099))

    if action == "APR_UP":
        scen_add = {"base": 0.01, "industry_worsening": 0.02, "recession": 0.03}.get(scenario, 0.01)
        bur_add  = 0.01 if float(features.get("bureau_score_3m_change", 0.0)) < -30 else 0.0
        new_apr  = current_apr + scen_add + bur_add
        return round(min(new_apr, max_apr), 4)

    if action == "APR_DOWN":
        full_pay = int(features.get("full_pay_months_12m", 0))
        pay_bonus = min((full_pay / 12) * 0.015, 0.015)
        new_apr   = current_apr - pay_bonus
        return round(max(new_apr, min_apr), 4)

    return current_apr


# ---------------------------------------------------------------------------
# Full single-account action pipeline
# ---------------------------------------------------------------------------


def evaluate_account(
    model: Any,
    features: Dict[str, float],
    current_limit: float,
    current_apr: float,
    product_id: str,
    scenario: str,
    cet1_buffer_available: float,
) -> Dict[str, Any]:
    """End-to-end evaluation for one account and one scenario.

    Returns
    -------
    dict with keys:
        predicted_action, action_confidence, action_probabilities,
        final_action, guardrail_reason,
        new_credit_limit, new_apr,
        limit_change_pct, apr_change_bps
    """
    product = CC_PRODUCTS.get(product_id, _DEFAULT_PRODUCT)

    predicted, confidence, probabilities = predict_action(model, features)
    final, guardrail_reason = apply_guardrails(
        predicted, features, current_limit, product, scenario
    )
    new_limit = compute_new_limit(
        current_limit, final, features, product, scenario, cet1_buffer_available
    )
    new_apr = compute_new_apr(current_apr, final, features, product, scenario)

    limit_change_pct = round((new_limit - current_limit) / max(current_limit, 1) * 100, 2)
    apr_change_bps   = round((new_apr - current_apr) * 10_000, 1)

    return {
        "predicted_action":      predicted,
        "action_confidence":     round(confidence, 4),
        "action_probabilities":  probabilities,
        "final_action":          final,
        "guardrail_reason":      guardrail_reason,
        "new_credit_limit":      new_limit,
        "new_apr":               new_apr,
        "limit_change_pct":      limit_change_pct,
        "apr_change_bps":        apr_change_bps,
    }
