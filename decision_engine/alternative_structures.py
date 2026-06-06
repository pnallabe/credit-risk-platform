"""
Alternative Structures Generator — S4-A
=========================================
Proposes alternative loan structures when a decision is REJECT.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Literal, Optional


@dataclass
class AlternativeStructure:
    rank: int
    structure_type: Literal["REDUCED_AMOUNT", "ADD_COLLATERAL", "REPRICE"]
    description: str
    suggested_loan_amount: Optional[float]
    suggested_collateral_type: Optional[str]
    suggested_apr: Optional[float]
    feasibility_score: float
    estimated_pd_at_structure: Optional[float]


def generate_alternatives(
    request: Any,
    pd_score: float,
    decision: str,
) -> List[AlternativeStructure]:
    """Generate alternative structures for a rejected application.

    Parameters
    ----------
    request:
        DecisionRequest with at minimum loan_amount, debt_to_income_ratio,
        pricing_result.recommended_rate, and optionally features dict.
    pd_score:
        The pd_score from the credit model.
    decision:
        The current decision string.

    Returns
    -------
    List of up to 3 AlternativeStructure objects, sorted by feasibility descending.
    """
    if decision != "REJECT":
        return []

    alternatives: List[AlternativeStructure] = []
    loan_amount: float = float(getattr(request, "loan_amount", 0) or 0)
    dti: float = float(getattr(request, "debt_to_income_ratio", 0.5) or 0.5)
    annual_income: float = float(getattr(request, "annual_income", 0) or 0)
    current_apr: float = 0.0
    try:
        current_apr = float(getattr(request.pricing_result, "recommended_rate", 18.0))
    except Exception:
        current_apr = 18.0

    features: dict = getattr(request, "features", {}) or {}
    has_collateral = bool(features.get("collateral_value"))
    ltv = float(features.get("ltv", 1.0))

    # -------------------------------------------------------------------
    # Option A: REDUCED_AMOUNT
    # Find largest amount where projected DTI < 0.40
    # -------------------------------------------------------------------
    reduced_amount: Optional[float] = None
    reduced_feasibility = 0.0
    if annual_income > 0 and loan_amount > 0:
        # Current monthly debt payment proxy: dti * annual_income / 12
        monthly_income = annual_income / 12.0
        # Estimate new loan monthly payment: 1% of loan amount (rough proxy)
        # Find amount where total dti stays < 0.40
        # new_dti ≈ (existing_monthly_debt + 0.01 * new_amount) / monthly_income < 0.40
        existing_monthly_debt = max(0.0, (dti - 0.01) * monthly_income)
        budget = 0.40 * monthly_income - existing_monthly_debt
        if budget > 0:
            # new_amount ≈ budget / 0.01
            reduced_amount = min(loan_amount, budget / 0.01)
            if reduced_amount >= 0.5 * loan_amount:
                reduced_feasibility = 0.8
            elif reduced_amount > 0:
                reduced_feasibility = 0.4
    else:
        reduced_amount = loan_amount * 0.6
        reduced_feasibility = 0.5

    if reduced_feasibility > 0 and reduced_amount and reduced_amount > 0:
        alternatives.append(
            AlternativeStructure(
                rank=0,
                structure_type="REDUCED_AMOUNT",
                description=(
                    f"Reduce requested amount to ${reduced_amount:,.0f} "
                    f"(from ${loan_amount:,.0f}) to bring projected DTI below 0.40."
                ),
                suggested_loan_amount=round(reduced_amount, 2),
                suggested_collateral_type=None,
                suggested_apr=None,
                feasibility_score=reduced_feasibility,
                estimated_pd_at_structure=None,
            )
        )

    # -------------------------------------------------------------------
    # Option B: ADD_COLLATERAL
    # -------------------------------------------------------------------
    if not has_collateral:
        alternatives.append(
            AlternativeStructure(
                rank=0,
                structure_type="ADD_COLLATERAL",
                description=(
                    "No collateral on file. Adding real estate or vehicle as collateral "
                    "may satisfy underwriting requirements."
                ),
                suggested_loan_amount=None,
                suggested_collateral_type="real_estate or vehicle",
                suggested_apr=None,
                feasibility_score=0.6,
                estimated_pd_at_structure=None,
            )
        )
    elif ltv > 0.75:
        alternatives.append(
            AlternativeStructure(
                rank=0,
                structure_type="ADD_COLLATERAL",
                description=(
                    f"Current LTV of {ltv:.2f} exceeds threshold. "
                    f"Reducing LTV to ≤ 0.75 via additional collateral or larger down payment."
                ),
                suggested_loan_amount=None,
                suggested_collateral_type="additional_pledge",
                suggested_apr=None,
                feasibility_score=0.7,
                estimated_pd_at_structure=None,
            )
        )

    # -------------------------------------------------------------------
    # Option C: REPRICE
    # -------------------------------------------------------------------
    price_premium = max(0.0, (pd_score - 0.10) * 200)  # bps → percentage points (bps/100)
    suggested_apr = current_apr + price_premium / 100.0
    alternatives.append(
        AlternativeStructure(
            rank=0,
            structure_type="REPRICE",
            description=(
                f"Risk-based repricing: increase APR by {price_premium:.0f} bps to "
                f"{suggested_apr:.2f}% to compensate for elevated PD of {pd_score:.3f}. "
                f"Note: repricing alone does not reduce credit risk."
            ),
            suggested_loan_amount=None,
            suggested_collateral_type=None,
            suggested_apr=round(suggested_apr, 4),
            feasibility_score=0.5,
            estimated_pd_at_structure=pd_score,
        )
    )

    # Sort by feasibility and assign ranks
    alternatives.sort(key=lambda a: a.feasibility_score, reverse=True)
    for i, alt in enumerate(alternatives[:3]):
        alt.rank = i + 1

    return alternatives[:3]
