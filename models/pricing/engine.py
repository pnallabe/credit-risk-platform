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
        clipped to [rate_floor, rate_cap].
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
    """

    recommended_rate: float
    expected_loss: float
    expected_profit: float
    profitability_flag: bool
    pd_score: float
    fraud_flag: str
    loan_amount: float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def calculate_pricing(
    pd_score: float,
    fraud_flag: str,
    loan_amount: float,
    config: PricingConfig | None = None,
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

    Returns
    -------
    PricingResult

    Notes
    -----
    Formulae (from PRD):
        risk_premium       = pd_score × risk_premium_multiplier
        fraud_adjustment   = fraud_review_addition  if fraud_flag == "manual_review" else 0
        raw_rate           = base_rate + risk_premium + fraud_adjustment
        recommended_rate   = clip(raw_rate, rate_floor, rate_cap)
        expected_loss      = pd_score × loan_amount × LGD
        expected_profit    = (rate/100 × loan_amount)
                             - expected_loss
                             - (funding_cost_rate × loan_amount)
    """
    if config is None:
        config = PricingConfig()

    # ── Rate calculation ────────────────────────────────────────────────────
    risk_premium = pd_score * config.risk_premium_multiplier
    fraud_adjustment = config.fraud_review_addition if fraud_flag == "manual_review" else 0.0
    raw_rate = config.base_rate + risk_premium + fraud_adjustment
    recommended_rate = max(config.rate_floor, min(config.rate_cap, raw_rate))

    # ── Expected Loss / Profit ───────────────────────────────────────────────
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
    )
