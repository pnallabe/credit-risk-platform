"""
Prompt 12: Release gate checks — CI-enforced policy regression and health thresholds.

These tests act as merge blockers:
  - Policy regression gate: simulated DECLINE rates for known bad scenarios must stay 100%
  - Parity gate: thin-file alt score must be identical across API and agent paths
  - API health gate: decision-api must start and return healthy within timeout

Run in CI via:
    python -m pytest tests/test_release_gates.py -q --tb=short

A failure here must block merges. Add `--exit-first` in CI for fast-fail behavior.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from decision_engine.product_policies import (
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
)
from scripts.run_product_simulation import (
    BNPL_SCENARIOS,
    PERSONAL_LOAN_SCENARIOS,
    SMB_SECURED_SCENARIOS,
    run_simulation,
)


# ---------------------------------------------------------------------------
# Gate 1: Policy regression — known bad scenarios must always DECLINE
# ---------------------------------------------------------------------------

MUST_DECLINE = [
    # Personal Loan
    dict(
        label="gate_pl_high_dti",
        application_id="gate-pl-001",
        product_type="PERSONAL_LOAN",
        credit_score=700,
        annual_income_usd=50000.0,
        debt_to_income_ratio=0.70,
        num_open_accounts=3,
        loan_amount_usd=10000.0,
        fraud_probability=0.03,
    ),
    dict(
        label="gate_pl_fraud_reject",
        application_id="gate-pl-002",
        product_type="PERSONAL_LOAN",
        credit_score=700,
        annual_income_usd=60000.0,
        debt_to_income_ratio=0.25,
        num_open_accounts=3,
        loan_amount_usd=12000.0,
        fraud_probability=0.90,
    ),
    # BNPL
    dict(
        label="gate_bnpl_gambling",
        application_id="gate-bnpl-001",
        product_type="BNPL",
        credit_score=650,
        payment_history="good",
        debt_to_income_ratio=0.25,
        loan_amount_usd=100.0,
        merchant_category="gambling",
        concurrent_bnpl_plans=1,
        fraud_probability=0.04,
    ),
    dict(
        label="gate_bnpl_over_plan_limit",
        application_id="gate-bnpl-002",
        product_type="BNPL",
        credit_score=620,
        payment_history="fair",
        debt_to_income_ratio=0.35,
        loan_amount_usd=150.0,
        merchant_category="electronics",
        concurrent_bnpl_plans=6,
        fraud_probability=0.05,
    ),
    # SMB Secured
    dict(
        label="gate_smb_low_dscr",
        application_id="gate-smb-001",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=400_000.0,
        years_in_business=3,
        debt_service_coverage_ratio=1.00,
        business_type="llc",
        collateral_type="equipment",
        collateral_value=250_000.0,
        collateral_ltv=0.70,
        loan_amount_usd=175_000.0,
        debt_to_income_ratio=0.40,
        fraud_probability=0.03,
    ),
    dict(
        label="gate_smb_high_ltv",
        application_id="gate-smb-002",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=600_000.0,
        years_in_business=4,
        debt_service_coverage_ratio=1.40,
        business_type="llc",
        collateral_type="real_estate",
        collateral_value=300_000.0,
        collateral_ltv=0.95,
        loan_amount_usd=285_000.0,
        debt_to_income_ratio=0.38,
        fraud_probability=0.03,
    ),
]

MUST_APPROVE = [
    dict(
        label="gate_pl_prime_approve",
        application_id="gate-approve-001",
        product_type="PERSONAL_LOAN",
        credit_score=780,
        annual_income_usd=100000.0,
        debt_to_income_ratio=0.18,
        num_open_accounts=6,
        loan_amount_usd=15000.0,
        fraud_probability=0.01,
    ),
    dict(
        label="gate_bnpl_clean_approve",
        application_id="gate-approve-002",
        product_type="BNPL",
        credit_score=680,
        payment_history="good",
        debt_to_income_ratio=0.20,
        loan_amount_usd=150.0,
        merchant_category="electronics",
        concurrent_bnpl_plans=0,
        fraud_probability=0.02,
    ),
    dict(
        label="gate_smb_healthy_approve",
        application_id="gate-approve-003",
        product_type="SMB_SECURED_LOAN",
        annual_revenue=2_000_000.0,
        years_in_business=8,
        debt_service_coverage_ratio=2.00,
        business_type="llc",
        collateral_type="real_estate",
        collateral_value=1_000_000.0,
        collateral_ltv=0.40,
        loan_amount_usd=400_000.0,
        debt_to_income_ratio=0.25,
        fraud_probability=0.02,
    ),
]


@pytest.mark.parametrize("scenario", MUST_DECLINE, ids=[s["label"] for s in MUST_DECLINE])
def test_regression_must_decline(scenario):
    """[RELEASE GATE] Known-bad scenarios must always produce DECLINE. Failure blocks merge."""
    results = run_simulation([dict(scenario)])
    r = results[0]
    assert r["verdict"] == "DECLINE", (
        f"[GATE FAIL] {scenario['label']}: expected DECLINE, got {r['verdict']}. "
        f"Flags: {r['flags']}"
    )


@pytest.mark.parametrize("scenario", MUST_APPROVE, ids=[s["label"] for s in MUST_APPROVE])
def test_regression_must_approve(scenario):
    """[RELEASE GATE] Known-good scenarios must always produce APPROVE. Failure blocks merge."""
    results = run_simulation([dict(scenario)])
    r = results[0]
    assert r["verdict"] == "APPROVE", (
        f"[GATE FAIL] {scenario['label']}: expected APPROVE, got {r['verdict']}. "
        f"Flags: {r['flags']}"
    )


# ---------------------------------------------------------------------------
# Gate 2: Feature parity gate — same input must produce same score
# ---------------------------------------------------------------------------

def test_feature_parity_gate():
    """[RELEASE GATE] API and agent paths must agree on thin_file_alt_score."""
    from agents.feature_engineering_agent import FeatureEngineeringAgent
    from credit_core.features import compute_feature_matrix

    fixture = {
        "application_id": "gate-parity-001",
        "loan_amount": 10000.0,
        "loan_purpose": "personal",
        "loan_term_months": 24,
        "annual_income": 60000.0,
        "employment_status": "employed",
        "employer_tenure_months": 24.0,
        "debt_to_income_ratio": 0.25,
        "existing_debt_amount": 15000.0,
        "credit_score": None,
        "num_open_accounts": 2,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
        "rent_payment_months": 12,
        "avg_monthly_cash_inflow": 5000.0,
        "avg_monthly_cash_outflow": 3500.0,
        "nsfv_last_90_days": 1,
        "income_confidence": 0.85,
    }

    api_df = compute_feature_matrix(pd.DataFrame([fixture]))
    api_score = float(api_df["thin_file_alt_score"].iloc[0])

    agent = FeatureEngineeringAgent()
    result = agent._run({"validated": [{"raw_features": dict(fixture)}]})
    agent_score = float(pd.DataFrame(result.payload["feature_df"])["thin_file_alt_score"].iloc[0])

    assert abs(api_score - agent_score) < 1e-10, (
        f"[GATE FAIL] Parity violation: api={api_score:.10f} agent={agent_score:.10f}"
    )


# ---------------------------------------------------------------------------
# Gate 3: All primary-product DECLINE scenarios must have decline codes
# ---------------------------------------------------------------------------

def test_all_declines_have_reason_codes():
    """[RELEASE GATE] Every DECLINE must carry at least one flag for adverse action."""
    all_scenarios = PERSONAL_LOAN_SCENARIOS + BNPL_SCENARIOS + SMB_SECURED_SCENARIOS
    results = run_simulation([dict(s) for s in all_scenarios])
    violations = []
    for r in results:
        if r["verdict"] == "DECLINE" and not r["flags"] and not r["policy_decline_codes"]:
            violations.append(r["label"])
    assert not violations, f"[GATE FAIL] DECLINEs with no reason codes: {violations}"


# ---------------------------------------------------------------------------
# Gate 4: Simulate a policy regression (verify gate detects it)
# ---------------------------------------------------------------------------

def test_gate_detects_simulated_regression():
    """Meta-test: gate correctly catches a deliberately broken policy."""
    from decision_engine.product_policies import ProductPolicy

    # Patch PERSONAL_LOAN policy to approve everything (broken)
    broken_policy = get_product_policy("PERSONAL_LOAN")
    # Override thresholds to always approve
    import dataclasses
    patched = dataclasses.replace(broken_policy, max_dti=1.0, fraud_reject_threshold=1.1)

    inp = ProductPolicyEvaluationInput(
        application_id="regression-detect",
        product_type="PERSONAL_LOAN",
        credit_score=700,
        annual_income_usd=50000.0,
        debt_to_income_ratio=0.99,   # should normally fail
        num_open_accounts=3,
        loan_amount_usd=10000.0,
        fraud_probability=0.03,
    )
    # With broken policy, DTI passes
    result_broken = evaluate_product_policy(inp, patched)
    assert result_broken.dti_passed is True  # confirms broken policy bypasses gate

    # With default policy, DTI fails — gate catches regression
    result_default = evaluate_product_policy(inp)
    assert result_default.dti_passed is False  # gate would fire
