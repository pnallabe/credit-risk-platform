"""
Prompt 6: Product policy validation — required-field validation and policy gate tests.
Prompt 7: Personal Loan hardening — boundary tests for PD/DTI/amount thresholds.
Prompt 8: BNPL hardening — merchant-category, concurrent-plan, fraud routing.
Prompt 9: SMB Secured Loan hardening — DSCR, collateral LTV, adequacy tests.
"""
from __future__ import annotations

import pytest

from decision_engine.product_policies import (
    ALL_PRODUCT_TYPES,
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
    validate_required_features,
)


# ---------------------------------------------------------------------------
# Prompt 6 — required-field validation
# ---------------------------------------------------------------------------


class TestRequiredFieldValidation:
    def test_personal_loan_missing_credit_score_flagged(self):
        inp = ProductPolicyEvaluationInput(
            application_id="app-1",
            product_type="PERSONAL_LOAN",
            annual_income_usd=50000.0,
            debt_to_income_ratio=0.30,
            num_open_accounts=2,
        )
        missing = validate_required_features("PERSONAL_LOAN", inp)
        assert any("credit_score" in f for f in missing)

    def test_personal_loan_all_fields_present_no_flags(self):
        inp = ProductPolicyEvaluationInput(
            application_id="app-2",
            product_type="PERSONAL_LOAN",
            credit_score=700,
            annual_income_usd=60000.0,
            debt_to_income_ratio=0.25,
            num_open_accounts=3,
        )
        missing = validate_required_features("PERSONAL_LOAN", inp)
        assert missing == []

    def test_smb_secured_loan_missing_collateral_flagged(self):
        inp = ProductPolicyEvaluationInput(
            application_id="app-3",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=500000.0,
            years_in_business=5,
            debt_service_coverage_ratio=1.5,
            business_type="llc",
        )
        missing = validate_required_features("SMB_SECURED_LOAN", inp)
        assert any("collateral_type" in f for f in missing)
        assert any("collateral_value" in f for f in missing)
        assert any("collateral_ltv" in f for f in missing)

    def test_missing_required_fields_fail_prequalification(self):
        """Missing required fields must cause pre_qualification_passed=False."""
        inp = ProductPolicyEvaluationInput(
            application_id="app-4",
            product_type="PERSONAL_LOAN",
            # credit_score intentionally omitted
            annual_income_usd=50000.0,
            debt_to_income_ratio=0.30,
            loan_amount_usd=10000.0,
            num_open_accounts=2,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is False
        assert any("MISSING_REQUIRED_FIELD" in f for f in result.pre_qualification_flags)

    def test_missing_required_fields_emit_aa09_code(self):
        inp = ProductPolicyEvaluationInput(
            application_id="app-5",
            product_type="PERSONAL_LOAN",
            annual_income_usd=50000.0,
            debt_to_income_ratio=0.20,
            loan_amount_usd=10000.0,
        )
        result = evaluate_product_policy(inp)
        assert "AA09" in result.policy_decline_codes

    def test_bnpl_missing_payment_history_flagged(self):
        inp = ProductPolicyEvaluationInput(
            application_id="app-6",
            product_type="BNPL",
            credit_score=650,
        )
        missing = validate_required_features("BNPL", inp)
        assert any("payment_history" in f for f in missing)

    def test_regression_valid_personal_loan_passes(self):
        inp = ProductPolicyEvaluationInput(
            application_id="happy-path",
            product_type="PERSONAL_LOAN",
            credit_score=720,
            annual_income_usd=80000.0,
            debt_to_income_ratio=0.25,
            loan_amount_usd=15000.0,
            num_open_accounts=3,
            fraud_probability=0.02,
            pd_score=0.04,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True


# ---------------------------------------------------------------------------
# Prompt 7 — Personal Loan boundary tests
# ---------------------------------------------------------------------------


class TestPersonalLoanBoundaries:
    def _inp(self, **kwargs) -> ProductPolicyEvaluationInput:
        base = dict(
            application_id="pl-test",
            product_type="PERSONAL_LOAN",
            credit_score=720,
            annual_income_usd=80000.0,
            debt_to_income_ratio=0.25,
            loan_amount_usd=15000.0,
            num_open_accounts=3,
            fraud_probability=0.02,
        )
        base.update(kwargs)
        return ProductPolicyEvaluationInput(**base)

    def test_pd_just_below_approve_threshold_passes(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(pd_score=policy.pd_threshold_approve - 0.001)
        result = evaluate_product_policy(inp, policy)
        assert result.dti_passed is True

    def test_dti_at_max_passes(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(debt_to_income_ratio=policy.max_dti)
        result = evaluate_product_policy(inp, policy)
        assert result.dti_passed is True

    def test_dti_one_basis_point_over_max_fails(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(debt_to_income_ratio=policy.max_dti + 0.0001)
        result = evaluate_product_policy(inp, policy)
        assert result.dti_passed is False
        assert "DTI_TOO_HIGH" in " ".join(result.pre_qualification_flags)

    def test_loan_below_minimum_fails(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(loan_amount_usd=policy.min_loan_amount_usd - 1)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False
        assert "LOAN_BELOW_MINIMUM" in " ".join(result.pre_qualification_flags)

    def test_loan_above_maximum_fails(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(loan_amount_usd=policy.max_loan_amount_usd + 1)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False
        assert "LOAN_ABOVE_MAXIMUM" in " ".join(result.pre_qualification_flags)

    def test_high_fraud_probability_produces_reject_verdict(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(fraud_probability=policy.fraud_reject_threshold + 0.01)
        result = evaluate_product_policy(inp, policy)
        assert result.fraud_verdict == "REJECT"
        assert result.pre_qualification_passed is False

    def test_borderline_fraud_produces_review_verdict(self):
        policy = get_product_policy("PERSONAL_LOAN")
        mid = (policy.fraud_review_threshold + policy.fraud_reject_threshold) / 2
        inp = self._inp(fraud_probability=mid)
        result = evaluate_product_policy(inp, policy)
        assert result.fraud_verdict == "MANUAL_REVIEW"

    def test_decline_reason_code_aa04_on_high_dti(self):
        policy = get_product_policy("PERSONAL_LOAN")
        inp = self._inp(debt_to_income_ratio=policy.max_dti + 0.10)
        result = evaluate_product_policy(inp, policy)
        assert "AA04" in result.policy_decline_codes


# ---------------------------------------------------------------------------
# Prompt 8 — BNPL hardening
# ---------------------------------------------------------------------------


class TestBNPLHardening:
    def _inp(self, **kwargs) -> ProductPolicyEvaluationInput:
        base = dict(
            application_id="bnpl-test",
            product_type="BNPL",
            credit_score=640,
            payment_history="good",
            debt_to_income_ratio=0.30,
            loan_amount_usd=300.0,
            num_open_accounts=2,
            fraud_probability=0.05,
            concurrent_bnpl_plans=1,
        )
        base.update(kwargs)
        return ProductPolicyEvaluationInput(**base)

    def test_valid_bnpl_passes(self):
        result = evaluate_product_policy(self._inp())
        assert result.pre_qualification_passed is True

    def test_concurrent_plans_at_limit_passes(self):
        result = evaluate_product_policy(self._inp(concurrent_bnpl_plans=4))
        assert result.extra_rule_results.get("max_concurrent_bnpl_plans_4") is True

    def test_concurrent_plans_over_limit_fails(self):
        result = evaluate_product_policy(self._inp(concurrent_bnpl_plans=5))
        assert result.extra_rule_results.get("max_concurrent_bnpl_plans_4") is False
        assert result.pre_qualification_passed is False

    def test_blocked_merchant_category_fails(self):
        result = evaluate_product_policy(self._inp(merchant_category="gambling"))
        assert result.extra_rule_results.get("merchant_category_check") is False
        assert result.pre_qualification_passed is False

    def test_allowed_merchant_category_passes(self):
        result = evaluate_product_policy(self._inp(merchant_category="electronics"))
        assert result.extra_rule_results.get("merchant_category_check") is True

    def test_high_fraud_probability_rejects(self):
        policy = get_product_policy("BNPL")
        result = evaluate_product_policy(self._inp(fraud_probability=policy.fraud_reject_threshold + 0.01))
        assert result.fraud_verdict == "REJECT"
        assert result.pre_qualification_passed is False

    def test_high_dti_fails_bnpl(self):
        policy = get_product_policy("BNPL")
        result = evaluate_product_policy(self._inp(debt_to_income_ratio=policy.max_dti + 0.05))
        assert result.dti_passed is False

    def test_regression_personal_loan_unaffected_by_bnpl_rules(self):
        """BNPL rules must not affect Personal Loan evaluation."""
        inp = ProductPolicyEvaluationInput(
            application_id="pl-regression",
            product_type="PERSONAL_LOAN",
            credit_score=720,
            annual_income_usd=80000.0,
            debt_to_income_ratio=0.25,
            loan_amount_usd=15000.0,
            num_open_accounts=3,
            fraud_probability=0.02,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True


# ---------------------------------------------------------------------------
# Prompt 9 — SMB Secured Loan hardening
# ---------------------------------------------------------------------------


class TestSMBSecuredLoanHardening:
    def _inp(self, **kwargs) -> ProductPolicyEvaluationInput:
        base = dict(
            application_id="smb-sec-test",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=1_000_000.0,
            years_in_business=4,
            debt_service_coverage_ratio=1.50,
            business_type="llc",
            collateral_type="real_estate",
            collateral_value=500_000.0,
            collateral_ltv=0.60,
            loan_amount_usd=300_000.0,
            debt_to_income_ratio=0.40,
            fraud_probability=0.05,
        )
        base.update(kwargs)
        return ProductPolicyEvaluationInput(**base)

    def test_valid_secured_smb_passes(self):
        result = evaluate_product_policy(self._inp())
        assert result.pre_qualification_passed is True

    def test_low_dscr_fails(self):
        result = evaluate_product_policy(self._inp(debt_service_coverage_ratio=1.10))
        assert result.extra_rule_results.get("dscr_min_1_25") is False
        assert result.pre_qualification_passed is False

    def test_dscr_at_threshold_passes(self):
        result = evaluate_product_policy(self._inp(debt_service_coverage_ratio=1.25))
        assert result.extra_rule_results.get("dscr_min_1_25") is True

    def test_collateral_ltv_over_80pct_fails(self):
        result = evaluate_product_policy(self._inp(collateral_ltv=0.85))
        assert result.extra_rule_results.get("collateral_ltv_max_80pct") is False
        assert result.pre_qualification_passed is False

    def test_collateral_ltv_at_80pct_passes(self):
        result = evaluate_product_policy(self._inp(collateral_ltv=0.80))
        assert result.extra_rule_results.get("collateral_ltv_max_80pct") is True

    def test_insufficient_collateral_fails(self):
        # Loan $400k but collateral only $300k — collateral < loan
        result = evaluate_product_policy(self._inp(
            loan_amount_usd=400_000.0,
            collateral_value=300_000.0,
        ))
        assert result.extra_rule_results.get("collateral_adequacy_check") is False
        assert result.pre_qualification_passed is False

    def test_collateral_exactly_equal_to_loan_passes(self):
        result = evaluate_product_policy(self._inp(
            loan_amount_usd=300_000.0,
            collateral_value=300_000.0,
        ))
        assert result.extra_rule_results.get("collateral_adequacy_check") is True

    def test_missing_collateral_fields_fail_prequal(self):
        inp = ProductPolicyEvaluationInput(
            application_id="smb-no-collateral",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=500_000.0,
            years_in_business=3,
            debt_service_coverage_ratio=1.4,
            business_type="llc",
            loan_amount_usd=200_000.0,
            # collateral_type / collateral_value / collateral_ltv intentionally omitted
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is False
        missing_flags = [f for f in result.pre_qualification_flags if "MISSING_REQUIRED_FIELD" in f]
        assert len(missing_flags) >= 3

    def test_new_business_under_1_year_fails(self):
        result = evaluate_product_policy(self._inp(years_in_business=0))
        assert result.extra_rule_results.get("years_in_business_min_1") is False
        assert result.pre_qualification_passed is False

    def test_seasonal_revenue_stress_high_dti_fails(self):
        """Seasonal/stressed business with high DTI must fail."""
        result = evaluate_product_policy(self._inp(debt_to_income_ratio=0.60))
        assert result.dti_passed is False
        assert result.pre_qualification_passed is False

    def test_regression_personal_loan_unaffected_by_smb_rules(self):
        inp = ProductPolicyEvaluationInput(
            application_id="pl-regression-2",
            product_type="PERSONAL_LOAN",
            credit_score=740,
            annual_income_usd=90000.0,
            debt_to_income_ratio=0.20,
            loan_amount_usd=20000.0,
            num_open_accounts=4,
            fraud_probability=0.02,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_regression_bnpl_unaffected_by_smb_rules(self):
        inp = ProductPolicyEvaluationInput(
            application_id="bnpl-regression-2",
            product_type="BNPL",
            credit_score=630,
            payment_history="good",
            debt_to_income_ratio=0.35,
            loan_amount_usd=200.0,
            num_open_accounts=1,
            fraud_probability=0.03,
            concurrent_bnpl_plans=2,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True
