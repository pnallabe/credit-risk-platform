"""
Pricing Engine
==============
Rule-based + ML pricing model that calculates the recommended interest
rate, expected loss, expected profit, and profitability for a loan
application given its PD score and fraud assessment.

Public API
----------
>>> from models.pricing.engine import PricingConfig, PricingResult, calculate_pricing
>>> config = PricingConfig()
>>> result = calculate_pricing(pd_score=0.04, fraud_flag="continue",
...                            loan_amount=25_000.0, config=config)
>>> print(result.recommended_rate, result.profitability_flag)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# CRIT-05: State-level APR caps (US consumer loans, as of 2026-04).
# Sources: state usury statutes, PLPA, UCCC jurisdiction limits.
# Keys are ISO 3166-2 two-letter state codes; values are maximum APR (%).
#
# This list covers the most restrictive states.  States not in this table
# fall back to the global PricingConfig.rate_cap.  Keep this table updated
# as statutes change; flag any state with cap < PricingConfig.rate_cap.
# ---------------------------------------------------------------------------
STATE_APR_CAPS: Dict[str, float] = {
    # States with statutory all-in APR caps at or below 36 %
    "AR": 17.0,   # Arkansas Constitution Art. 19 §13 — 17 % usury cap
    "CO": 36.0,   # Colorado UCCC (SB10-100) — 36 % cap incl. fees
    "IL": 36.0,   # Illinois PLPA (effective 2021) — 36 % all-in cap
    "MN": 33.0,   # Minnesota §47.59 — 33 % on personal loans
    "MT": 36.0,   # Montana MCA §31-1-107 — 36 % cap
    "NM": 36.0,   # New Mexico §58-15-17 — 36 % cap (eff. 2023)
    "NE": 21.0,   # Nebraska §45-101.03 — 21 % on unsecured consumer loans
    "ND": 7.0,    # North Dakota NDCC §47-14-09 — 5.5 % above prime; ~7 % typical
    "VA": 36.0,   # Virginia Consumer Protection Act — 36 % cap (eff. 2021)
    "WV": 31.0,   # West Virginia Code §47-6-5(a)(2) — 31 % on personal loans
    # California: tiered caps
    # $2,500–$10,000 → no statutory cap; >$10,000 → lender discretion
    # SB539 (2020) for loans <$10,000: 36 % + fed funds rate
    "CA": 36.0,   # proxy for SB539 cap on loans under $10 k; validate per loan amount
}


def get_state_apr_cap(state: Optional[str], global_cap: float) -> float:
    """Return the effective APR cap for *state*, falling back to *global_cap*.

    Parameters
    ----------
    state:
        Two-letter ISO 3166-2 state code, or ``None`` if unknown.
    global_cap:
        The ``PricingConfig.rate_cap`` to use when the state has no lower cap.

    Returns
    -------
    float
        The lower of the state statutory cap and the global cap.
    """
    if not state:
        return global_cap
    state_cap = STATE_APR_CAPS.get(state.upper())
    if state_cap is None:
        return global_cap
    return min(state_cap, global_cap)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class PricingConfig:
    """All configurable rate parameters for the pricing model.

    Attributes
    ----------
    base_rate:
        Floor interest rate (%) charged even to the lowest-risk borrowers.
    rate_floor:
        Hard floor on the final recommended rate (%).
    rate_cap:
        Hard cap on the final recommended rate (%).
    risk_premium_multiplier:
        Maps PD score to additional basis points.
        recommended_rate = base_rate + pd_score × risk_premium_multiplier
    fraud_review_addition:
        Extra rate (%) added when fraud_flag == "manual_review".
    lgd:
        Loss Given Default — fraction of the loan amount lost on default.
    funding_cost_rate:
        Annual cost of capital as a decimal fraction of loan amount.
    """

    base_rate: float = 5.0
    rate_floor: float = 5.0
    rate_cap: float = 36.0
    risk_premium_multiplier: float = 25.0   # pd_score * 25 → extra %
    fraud_review_addition: float = 2.0
    lgd: float = 0.45
    funding_cost_rate: float = 0.035        # 3.5 %


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class PricingResult:
    """Output of the pricing engine for a single application.

    Attributes
    ----------
    recommended_rate:
        Final annual interest rate (%) to offer the borrower,
        clipped to [rate_floor, effective_rate_cap].
    expected_loss:
        Expected monetary loss (USD) = pd_score × loan_amount × LGD.
    expected_profit:
        Expected monetary profit (USD) =
            (rate/100 × loan_amount) - expected_loss - (funding_cost × loan_amount).
    profitability_flag:
        True when expected_profit > 0.
    pd_score:
        Input PD score (stored for traceability).
    fraud_flag:
        Input fraud flag (stored for traceability).
    loan_amount:
        Input loan amount (stored for traceability).
    borrower_state:
        Two-letter state code used for APR cap derivation (stored for audit).
    effective_rate_cap:
        The APR cap actually applied (state cap or global cap, whichever is lower).
    """

    recommended_rate: float
    expected_loss: float
    expected_profit: float
    profitability_flag: bool
    pd_score: float
    fraud_flag: str
    loan_amount: float
    borrower_state: Optional[str] = None
    effective_rate_cap: float = 36.0


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def calculate_pricing(
    pd_score: float,
    fraud_flag: str,
    loan_amount: float,
    config: "PricingConfig | None" = None,
    borrower_state: Optional[str] = None,
) -> PricingResult:
    """Calculate loan pricing for a single application.

    Parameters
    ----------
    pd_score:
        Probability of default in [0, 1] from the credit risk model.
    fraud_flag:
        One of ``"continue"``, ``"manual_review"``, or ``"reject"``.
    loan_amount:
        Requested loan amount in USD.
    config:
        Pricing configuration.  Defaults to ``PricingConfig()`` (all PRD values).
    borrower_state:
        ISO 3166-2 two-letter US state code (e.g. ``"CA"``, ``"IL"``).
        Used to enforce state-level usury/APR caps (CRIT-05).  When ``None``
        or the state has no lower statutory cap, ``config.rate_cap`` applies.

    Returns
    -------
    PricingResult

    Notes
    -----
    Formulae (from PRD):
        risk_premium       = pd_score × risk_premium_multiplier
        fraud_adjustment   = fraud_review_addition  if fraud_flag == "manual_review" else 0
        raw_rate           = base_rate + risk_premium + fraud_adjustment
        effective_cap      = min(state_apr_cap, rate_cap)
        recommended_rate   = clip(raw_rate, rate_floor, effective_cap)
        expected_loss      = pd_score × loan_amount × LGD
        expected_profit    = (rate/100 × loan_amount)
                             - expected_loss
                             - (funding_cost_rate × loan_amount)
    """
    if config is None:
        config = PricingConfig()

    # ── CRIT-05: Derive the effective APR cap for this borrower's state ──────
    effective_cap = get_state_apr_cap(borrower_state, config.rate_cap)

    # ── Rate calculation ─────────────────────────────────────────────────────
    risk_premium = pd_score * config.risk_premium_multiplier
    fraud_adjustment = config.fraud_review_addition if fraud_flag == "manual_review" else 0.0
    raw_rate = config.base_rate + risk_premium + fraud_adjustment
    recommended_rate = max(config.rate_floor, min(effective_cap, raw_rate))

    # ── Expected Loss / Profit ────────────────────────────────────────────────
    expected_loss = pd_score * loan_amount * config.lgd
    interest_income = (recommended_rate / 100.0) * loan_amount
    funding_cost = config.funding_cost_rate * loan_amount
    expected_profit = interest_income - expected_loss - funding_cost

    return PricingResult(
        recommended_rate=round(recommended_rate, 4),
        expected_loss=round(expected_loss, 2),
        expected_profit=round(expected_profit, 2),
        profitability_flag=expected_profit > 0,
        pd_score=pd_score,
        fraud_flag=fraud_flag,
        loan_amount=loan_amount,
        borrower_state=borrower_state,
        effective_rate_cap=round(effective_cap, 4),
    )
