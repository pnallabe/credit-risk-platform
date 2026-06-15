"""
Alternative Structures Generator
=========================================
Proposes alternative loan structures when a decision is DECLINE.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, List, Optional

@dataclass
class AlternativeStructure:
    structure_type: str  # "reduced_amount", "higher_down_payment", "income_documentation", "reduced_term"
    description: str
    adjusted_pd: float
    adjusted_dti: float
    feasibility: str     # "High" | "Medium" | "Low"

def compute_alternatives(
    request: Any,
    decision_result: Any,
    policy_config: dict,
) -> List[AlternativeStructure]:
    """Compute alternative structures for a rejected application."""
    decision = getattr(decision_result, "decision", "") if not isinstance(decision_result, dict) else decision_result.get("decision")
    if decision != "REJECT":
        return []

    alternatives: List[AlternativeStructure] = []

    # Extract request properties
    loan_amount = float(getattr(request, "loan_amount", 0.0) or 0.0)
    dti = float(getattr(request, "debt_to_income_ratio", 0.5) or 0.5)
    annual_income = float(getattr(request, "annual_income", 0.0) or 0.0)
    monthly_income = annual_income / 12.0
    term_months = int(getattr(request, "loan_term_months", 36) or 36)
    emp_status = getattr(request, "employment_status", "employed")

    # Calculate original monthly payment (approx based on loan amount / term)
    current_payment = loan_amount / term_months if term_months > 0 else 0.0
    other_debt = max(0.0, (dti * monthly_income) - current_payment)

    # Policy configs
    dti_limit = float(policy_config.get("dti_limit", 0.43))
    approval_threshold = float(policy_config.get("pd_threshold", 0.10))

    pd_score = getattr(decision_result, "pd_score", 0.15) if not isinstance(decision_result, dict) else decision_result.get("pd_score", 0.15)

    # 1. reduced_amount (binary search)
    if loan_amount > 0 and annual_income > 0:
        low = 0.60 * loan_amount  # up to 40% reduction
        high = loan_amount
        best_amount = None
        best_dti = dti

        # 10 steps of binary search
        for _ in range(10):
            mid = (low + high) / 2
            mid_payment = mid / term_months
            new_dti = (other_debt + mid_payment) / monthly_income if monthly_income > 0 else 1.0

            # Simple assumption: PD decreases proportionally with amount reduction (for illustrative purposes in tests)
            # A real model would be re-invoked
            reduction_ratio = mid / loan_amount
            new_pd = pd_score * reduction_ratio

            if new_pd < approval_threshold and new_dti < dti_limit:
                best_amount = mid
                best_dti = new_dti
                low = mid  # Try to find a higher amount that still passes
            else:
                high = mid  # Need to reduce amount further

        if best_amount is not None:
            feasibility = "High" if best_amount >= 0.8 * loan_amount else "Medium"
            alternatives.append(AlternativeStructure(
                structure_type="reduced_amount",
                description=f"Approval likely at ${best_amount:,.0f} (vs. requested ${loan_amount:,.0f})",
                adjusted_pd=pd_score * (best_amount / loan_amount),
                adjusted_dti=best_dti,
                feasibility=feasibility
            ))

    # 2. higher_down_payment (secured loans)
    features = getattr(request, "features", {}) or {}
    collateral_value = float(features.get("collateral_value", 0.0) or 0.0)
    if collateral_value > 0 and loan_amount > 0:
        ltv = loan_amount / collateral_value
        if ltv >= 0.80:
            required_collateral = loan_amount / 0.79
            uplift = required_collateral - collateral_value
            if uplift > 0:
                alternatives.append(AlternativeStructure(
                    structure_type="higher_down_payment",
                    description=f"Increase down payment or collateral value by ${uplift:,.0f} to bring LTV below 80%.",
                    adjusted_pd=pd_score,
                    adjusted_dti=dti,
                    feasibility="Medium"
                ))

    # 3. income_documentation
    income_verif_score = float(features.get("income_verification_score", 100) or 100)
    if emp_status != "employed" or income_verif_score < 60:
        alternatives.append(AlternativeStructure(
            structure_type="income_documentation",
            description="Verified income documentation (e.g., W-2s, tax returns) could improve the decision.",
            adjusted_pd=pd_score * 0.9, # assumed improvement
            adjusted_dti=dti,
            feasibility="High"
        ))

    # 4. reduced_term
    if dti > dti_limit and loan_amount > 0 and monthly_income > 0:
        # A shorter term means HIGHER monthly payment, which INCREASES DTI.
        # But wait, Prompt 12: "reduced_term: For DTI-constrained declines — show DTI impact of a shorter term (higher monthly payment, faster payoff)"
        # We'll just show the alternative even if it raises DTI, as requested.
        shorter_term = max(12, term_months - 12)
        if shorter_term < term_months:
            new_payment = loan_amount / shorter_term
            new_dti = (other_debt + new_payment) / monthly_income
            alternatives.append(AlternativeStructure(
                structure_type="reduced_term",
                description=f"A shorter term of {shorter_term} months would increase DTI to {new_dti:.2%} but pay off the loan faster.",
                adjusted_pd=pd_score,
                adjusted_dti=new_dti,
                feasibility="Low"
            ))

    # Sort by feasibility: High, Medium, Low
    feasibility_order = {"High": 0, "Medium": 1, "Low": 2}
    alternatives.sort(key=lambda x: feasibility_order.get(x.feasibility, 3))

    return alternatives[:3]
