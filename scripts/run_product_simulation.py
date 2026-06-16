"""
Prompt 10: Cross-product simulation harness for BNPL, Personal Loan, and SMB Secured.

Run via:
    python scripts/run_product_simulation.py

Or via pytest (produces deterministic output assertions):
    python -m pytest tests/test_cross_product_simulation.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decision_engine.product_policies import (
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
)

# ---------------------------------------------------------------------------
# Scenario fixture sets — one pack per primary product
# ---------------------------------------------------------------------------

PERSONAL_LOAN_SCENARIOS: List[Dict[str, Any]] = [
    dict(  # prime applicant → approve
        label="PL_prime_approve",
        application_id="sim-pl-001",
        product_type="PERSONAL_LOAN",
        credit_score=760,
        annual_income_usd=90000.0,
        debt_to_income_ratio=0.20,
        num_open_accounts=5,
        loan_amount_usd=20000.0,
        fraud_probability=0.02,
        pd_score=0.03,
    ),
    dict(  # near-miss DTI → should fail DTI gate
        label="PL_high_dti_reject",
        application_id="sim-pl-002",
        product_type="PERSONAL_LOAN",
        credit_score=700,
        annual_income_usd=50000.0,
        debt_to_income_ratio=0.55,
        num_open_accounts=3,
        loan_amount_usd=15000.0,
        fraud_probability=0.03,
        pd_score=0.08,
    ),
    dict(  # fraud flag → manual review
        label="PL_fraud_review",
        application_id="sim-pl-003",
        product_type="PERSONAL_LOAN",
        credit_score=720,
        annual_income_usd=70000.0,
        debt_to_income_ratio=0.28,
        num_open_accounts=4,
        loan_amount_usd=10000.0,
        fraud_probability=0.40,
        pd_score=0.04,
    ),
    dict(  # thin-file — missing credit_score
        label="PL_thin_file",
        application_id="sim-pl-004",
        product_type="PERSONAL_LOAN",
        credit_score=None,
        annual_income_usd=48000.0,
        debt_to_income_ratio=0.30,
        num_open_accounts=2,
        loan_amount_usd=8000.0,
        fraud_probability=0.05,
        pd_score=0.07,
    ),
]

BNPL_SCENARIOS: List[Dict[str, Any]] = [
    dict(  # standard approval
        label="BNPL_standard_approve",
        application_id="sim-bnpl-001",
        product_type="BNPL",
        credit_score=640,
        payment_history="good",
        debt_to_income_ratio=0.30,
        loan_amount_usd=250.0,
        num_open_accounts=2,
        fraud_probability=0.04,
        pd_score=0.06,
        concurrent_bnpl_plans=1,
        merchant_category="electronics",
    ),
    dict(  # too many concurrent plans
        label="BNPL_concurrent_plans_reject",
        application_id="sim-bnpl-002",
        product_type="BNPL",
        credit_score=600,
        payment_history="fair",
        debt_to_income_ratio=0.40,
        loan_amount_usd=150.0,
        num_open_accounts=5,
        fraud_probability=0.05,
        pd_score=0.10,
        concurrent_bnpl_plans=5,
        merchant_category="fashion",
    ),
    dict(  # blocked merchant
        label="BNPL_gambling_merchant_reject",
        application_id="sim-bnpl-003",
        product_type="BNPL",
        credit_score=680,
        payment_history="good",
        debt_to_income_ratio=0.25,
        loan_amount_usd=100.0,
        num_open_accounts=1,
        fraud_probability=0.04,
        pd_score=0.05,
        concurrent_bnpl_plans=0,
        merchant_category="gambling",
    ),
    dict(  # high fraud → reject
        label="BNPL_high_fraud_reject",
        application_id="sim-bnpl-004",
        product_type="BNPL",
        credit_score=650,
        payment_history="good",
        debt_to_income_ratio=0.28,
        loan_amount_usd=200.0,
        num_open_accounts=2,
        fraud_probability=0.80,
        pd_score=0.07,
        concurrent_bnpl_plans=1,
        merchant_category="home_goods",
    ),
]

SMB_SECURED_SCENARIOS: List[Dict[str, Any]] = [
    dict(  # healthy secured SMB
        label="SMB_SEC_healthy_approve",
        application_id="sim-smb-001",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=1_200_000.0,
        years_in_business=6,
        debt_service_coverage_ratio=1.60,
        business_type="llc",
        collateral_type="real_estate",
        collateral_value=600_000.0,
        collateral_ltv=0.50,
        loan_amount_usd=300_000.0,
        debt_to_income_ratio=0.35,
        fraud_probability=0.03,
        pd_score=0.07,
    ),
    dict(  # low DSCR
        label="SMB_SEC_low_dscr_reject",
        application_id="sim-smb-002",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=500_000.0,
        years_in_business=3,
        debt_service_coverage_ratio=1.05,
        business_type="sole_proprietor",
        collateral_type="equipment",
        collateral_value=400_000.0,
        collateral_ltv=0.60,
        loan_amount_usd=240_000.0,
        debt_to_income_ratio=0.42,
        fraud_probability=0.04,
        pd_score=0.15,
    ),
    dict(  # excessive collateral LTV
        label="SMB_SEC_high_ltv_reject",
        application_id="sim-smb-003",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=800_000.0,
        years_in_business=4,
        debt_service_coverage_ratio=1.40,
        business_type="llc",
        collateral_type="real_estate",
        collateral_value=500_000.0,
        collateral_ltv=0.90,
        loan_amount_usd=450_000.0,
        debt_to_income_ratio=0.38,
        fraud_probability=0.04,
        pd_score=0.12,
    ),
    dict(  # seasonal stress: high DTI
        label="SMB_SEC_seasonal_stress_reject",
        application_id="sim-smb-004",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=700_000.0,
        years_in_business=5,
        debt_service_coverage_ratio=1.30,
        business_type="llc",
        collateral_type="inventory",
        collateral_value=350_000.0,
        collateral_ltv=0.70,
        loan_amount_usd=245_000.0,
        debt_to_income_ratio=0.58,
        fraud_probability=0.03,
        pd_score=0.18,
    ),
]

ALL_SCENARIOS = PERSONAL_LOAN_SCENARIOS + BNPL_SCENARIOS + SMB_SECURED_SCENARIOS


# ---------------------------------------------------------------------------
# Simulation runner
# ---------------------------------------------------------------------------

SimulationResult = Dict[str, Any]


def run_simulation(scenarios: List[Dict[str, Any]]) -> List[SimulationResult]:
    """Evaluate all scenarios and return structured result rows."""
    results: List[SimulationResult] = []
    for s in scenarios:
        label = s.pop("label", s["application_id"])
        inp = ProductPolicyEvaluationInput(**s)
        policy = get_product_policy(inp.product_type)
        result = evaluate_product_policy(inp, policy)

        # Determine top-level verdict
        if not result.pre_qualification_passed:
            verdict = "DECLINE"
        elif result.fraud_verdict == "MANUAL_REVIEW":
            verdict = "REVIEW"
        else:
            verdict = "APPROVE"

        # Expected loss proxy: PD × loan amount
        el = inp.pd_score * inp.loan_amount_usd

        results.append({
            "label": label,
            "application_id": inp.application_id,
            "product_type": inp.product_type,
            "verdict": verdict,
            "fraud_verdict": result.fraud_verdict,
            "pre_qualification_passed": result.pre_qualification_passed,
            "dti_passed": result.dti_passed,
            "policy_decline_codes": result.policy_decline_codes,
            "flags": result.pre_qualification_flags,
            "pd_score": inp.pd_score,
            "loan_amount_usd": inp.loan_amount_usd,
            "expected_loss_proxy": round(el, 2),
        })
        # Restore label for next run (in case scenarios are reused)
        s["label"] = label
    return results


def print_report(results: List[SimulationResult]) -> None:
    approve = sum(1 for r in results if r["verdict"] == "APPROVE")
    review = sum(1 for r in results if r["verdict"] == "REVIEW")
    decline = sum(1 for r in results if r["verdict"] == "DECLINE")
    total_el = sum(r["expected_loss_proxy"] for r in results)

    print(f"\n{'='*60}")
    print("Cross-Product Simulation Report")
    print(f"{'='*60}")
    print(f"  Total scenarios : {len(results)}")
    print(f"  APPROVE         : {approve}")
    print(f"  REVIEW          : {review}")
    print(f"  DECLINE         : {decline}")
    print(f"  Total EL proxy  : ${total_el:,.2f}")
    print(f"\n{'Scenario':<35} {'Product':<20} {'Verdict':<10} {'EL Proxy':>10}")
    print("-" * 80)
    for r in results:
        print(f"  {r['label']:<33} {r['product_type']:<20} {r['verdict']:<10} ${r['expected_loss_proxy']:>8,.2f}")
    print()


if __name__ == "__main__":
    scenarios = [dict(s) for s in ALL_SCENARIOS]
    results = run_simulation(scenarios)
    print_report(results)
    output_path = ROOT / "reports" / "cross_product_simulation.json"
    output_path.parent.mkdir(exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {output_path}")
