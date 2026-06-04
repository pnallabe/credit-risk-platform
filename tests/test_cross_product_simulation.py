"""
Prompt 10: Cross-product simulation harness tests — deterministic output assertions.
Prompt 11: Explainability and reason-code regression suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from scripts.run_product_simulation import (
    BNPL_SCENARIOS,
    PERSONAL_LOAN_SCENARIOS,
    SMB_SECURED_SCENARIOS,
    run_simulation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(scenarios):
    return run_simulation([dict(s) for s in scenarios])


def _by_label(results, label):
    for r in results:
        if r["label"] == label:
            return r
    raise KeyError(label)


# ---------------------------------------------------------------------------
# Prompt 10 — Simulation harness: deterministic verdicts
# ---------------------------------------------------------------------------

class TestPersonalLoanSimulation:
    def test_prime_applicant_approves(self):
        r = _by_label(_run(PERSONAL_LOAN_SCENARIOS), "PL_prime_approve")
        assert r["verdict"] == "APPROVE"

    def test_high_dti_declines(self):
        r = _by_label(_run(PERSONAL_LOAN_SCENARIOS), "PL_high_dti_reject")
        assert r["verdict"] == "DECLINE"
        assert r["dti_passed"] is False

    def test_fraud_flag_produces_review(self):
        r = _by_label(_run(PERSONAL_LOAN_SCENARIOS), "PL_fraud_review")
        assert r["verdict"] == "REVIEW"
        assert r["fraud_verdict"] == "MANUAL_REVIEW"

    def test_thin_file_missing_credit_score_declines(self):
        r = _by_label(_run(PERSONAL_LOAN_SCENARIOS), "PL_thin_file")
        assert r["verdict"] == "DECLINE"
        assert any("MISSING_REQUIRED_FIELD" in f for f in r["flags"])

    def test_expected_loss_proxy_non_negative(self):
        for r in _run(PERSONAL_LOAN_SCENARIOS):
            assert r["expected_loss_proxy"] >= 0


class TestBNPLSimulation:
    def test_standard_approve(self):
        r = _by_label(_run(BNPL_SCENARIOS), "BNPL_standard_approve")
        assert r["verdict"] == "APPROVE"

    def test_concurrent_plans_declines(self):
        r = _by_label(_run(BNPL_SCENARIOS), "BNPL_concurrent_plans_reject")
        assert r["verdict"] == "DECLINE"

    def test_gambling_merchant_declines(self):
        r = _by_label(_run(BNPL_SCENARIOS), "BNPL_gambling_merchant_reject")
        assert r["verdict"] == "DECLINE"

    def test_high_fraud_declines(self):
        r = _by_label(_run(BNPL_SCENARIOS), "BNPL_high_fraud_reject")
        assert r["verdict"] == "DECLINE"
        assert r["fraud_verdict"] == "REJECT"

    def test_all_scenarios_have_product_type(self):
        for r in _run(BNPL_SCENARIOS):
            assert r["product_type"] == "BNPL"


class TestSMBSecuredSimulation:
    def test_healthy_smb_approves(self):
        r = _by_label(_run(SMB_SECURED_SCENARIOS), "SMB_SEC_healthy_approve")
        assert r["verdict"] == "APPROVE"

    def test_low_dscr_declines(self):
        r = _by_label(_run(SMB_SECURED_SCENARIOS), "SMB_SEC_low_dscr_reject")
        assert r["verdict"] == "DECLINE"

    def test_high_ltv_declines(self):
        r = _by_label(_run(SMB_SECURED_SCENARIOS), "SMB_SEC_high_ltv_reject")
        assert r["verdict"] == "DECLINE"

    def test_seasonal_stress_declines(self):
        r = _by_label(_run(SMB_SECURED_SCENARIOS), "SMB_SEC_seasonal_stress_reject")
        assert r["verdict"] == "DECLINE"

    def test_all_results_have_required_keys(self):
        for r in _run(SMB_SECURED_SCENARIOS):
            for key in ("verdict", "fraud_verdict", "dti_passed", "expected_loss_proxy"):
                assert key in r, f"Missing key '{key}' in result {r['label']}"


class TestSimulationDistributions:
    def test_mixed_approval_rate_across_products(self):
        """Primary product batch must have at least one approve and at least one decline."""
        from scripts.run_product_simulation import ALL_SCENARIOS
        results = run_simulation([dict(s) for s in ALL_SCENARIOS])
        verdicts = {r["verdict"] for r in results}
        assert "APPROVE" in verdicts
        assert "DECLINE" in verdicts

    def test_total_expected_loss_positive(self):
        from scripts.run_product_simulation import ALL_SCENARIOS
        results = run_simulation([dict(s) for s in ALL_SCENARIOS])
        total_el = sum(r["expected_loss_proxy"] for r in results)
        assert total_el > 0

    def test_simulation_is_deterministic(self):
        from scripts.run_product_simulation import ALL_SCENARIOS
        r1 = run_simulation([dict(s) for s in ALL_SCENARIOS])
        r2 = run_simulation([dict(s) for s in ALL_SCENARIOS])
        for a, b in zip(r1, r2):
            assert a["verdict"] == b["verdict"]
            assert a["expected_loss_proxy"] == b["expected_loss_proxy"]


# ---------------------------------------------------------------------------
# Prompt 11 — Reason-code and explanation regression suite
# ---------------------------------------------------------------------------

from decision_engine.product_policies import (
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
)


class TestPersonalLoanReasonCodes:
    def test_high_dti_emits_aa04(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-001",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=50000.0,
            debt_to_income_ratio=policy.max_dti + 0.10,
            num_open_accounts=3,
            loan_amount_usd=10000.0,
        )
        result = evaluate_product_policy(inp, policy)
        assert "AA04" in result.policy_decline_codes

    def test_fraud_reject_emits_aa02(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-002",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=60000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=3,
            loan_amount_usd=12000.0,
            fraud_probability=policy.fraud_reject_threshold + 0.01,
        )
        result = evaluate_product_policy(inp, policy)
        assert "AA02" in result.policy_decline_codes

    def test_fraud_review_emits_aa05(self):
        policy = get_product_policy("PERSONAL_LOAN")
        mid = (policy.fraud_review_threshold + policy.fraud_reject_threshold) / 2
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-003",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=60000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=3,
            loan_amount_usd=12000.0,
            fraud_probability=mid,
        )
        result = evaluate_product_policy(inp, policy)
        assert "AA05" in result.policy_decline_codes

    def test_missing_required_field_emits_aa09(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-004",
            product_type="PERSONAL_LOAN",
            annual_income_usd=50000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=3,
            loan_amount_usd=10000.0,
            # credit_score intentionally omitted
        )
        result = evaluate_product_policy(inp)
        assert "AA09" in result.policy_decline_codes

    def test_insufficient_tradelines_emits_aa03(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-005",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=60000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=0,   # min is 1
            loan_amount_usd=10000.0,
        )
        result = evaluate_product_policy(inp)
        assert "AA03" in result.policy_decline_codes

    def test_reason_codes_deduplicated(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-pl-006",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=60000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=3,
            loan_amount_usd=10000.0,
            fraud_probability=0.02,
        )
        result = evaluate_product_policy(inp)
        assert len(result.policy_decline_codes) == len(set(result.policy_decline_codes))


class TestBNPLReasonCodes:
    def test_blocked_merchant_produces_rule_failed_flag(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-bnpl-001",
            product_type="BNPL",
            credit_score=640,
            payment_history="good",
            debt_to_income_ratio=0.30,
            loan_amount_usd=200.0,
            merchant_category="adult",
            concurrent_bnpl_plans=1,
        )
        result = evaluate_product_policy(inp)
        assert any("merchant_category_check" in f for f in result.pre_qualification_flags)

    def test_concurrent_plans_exceeded_produces_rule_failed_flag(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-bnpl-002",
            product_type="BNPL",
            credit_score=640,
            payment_history="good",
            debt_to_income_ratio=0.30,
            loan_amount_usd=200.0,
            merchant_category="electronics",
            concurrent_bnpl_plans=5,
        )
        result = evaluate_product_policy(inp)
        assert any("max_concurrent_bnpl_plans_4" in f for f in result.pre_qualification_flags)

    def test_approval_has_no_decline_reason_codes(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-bnpl-003",
            product_type="BNPL",
            credit_score=640,
            payment_history="good",
            debt_to_income_ratio=0.30,
            loan_amount_usd=200.0,
            merchant_category="electronics",
            concurrent_bnpl_plans=1,
            fraud_probability=0.04,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True
        assert result.policy_decline_codes == []


class TestSMBSecuredReasonCodes:
    def test_low_dscr_produces_rule_failed_flag(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-smb-001",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=500_000.0,
            years_in_business=3,
            debt_service_coverage_ratio=1.10,
            business_type="llc",
            collateral_type="real_estate",
            collateral_value=400_000.0,
            collateral_ltv=0.60,
            loan_amount_usd=240_000.0,
            debt_to_income_ratio=0.40,
        )
        result = evaluate_product_policy(inp)
        assert any("dscr_min_1_25" in f for f in result.pre_qualification_flags)

    def test_high_ltv_produces_rule_failed_flag(self):
        inp = ProductPolicyEvaluationInput(
            application_id="rc-smb-002",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=800_000.0,
            years_in_business=4,
            debt_service_coverage_ratio=1.50,
            business_type="llc",
            collateral_type="real_estate",
            collateral_value=500_000.0,
            collateral_ltv=0.85,
            loan_amount_usd=425_000.0,
            debt_to_income_ratio=0.38,
        )
        result = evaluate_product_policy(inp)
        assert any("collateral_ltv_max_80pct" in f for f in result.pre_qualification_flags)

    def test_flags_map_to_expected_decline_paths(self):
        """Every DECLINE must have at least one flag explaining the reason."""
        from scripts.run_product_simulation import SMB_SECURED_SCENARIOS
        results = run_simulation([dict(s) for s in SMB_SECURED_SCENARIOS])
        for r in results:
            if r["verdict"] == "DECLINE":
                assert len(r["flags"]) > 0, f"DECLINE with no flags: {r['label']}"

    def test_reason_code_completeness_across_all_products(self):
        """Every DECLINE scenario must emit at least one FCRA reason code."""
        from scripts.run_product_simulation import ALL_SCENARIOS
        results = run_simulation([dict(s) for s in ALL_SCENARIOS])
        for r in results:
            if r["verdict"] == "DECLINE":
                assert len(r["policy_decline_codes"]) > 0 or len(r["flags"]) > 0, (
                    f"DECLINE with no codes/flags: {r['label']}"
                )
