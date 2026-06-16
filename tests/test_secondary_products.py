"""
Prompt 14: Credit Builder / Secured Card profile tests.
Prompt 15: Overdraft / Cash Advance profile tests.

Covers:
- No-credit-score applicant routing
- Limit assignment and manual-review routing
- Active bankruptcy hard decline
- Overdraft frequency gate
- Net inflow adequacy gate
- Stable payroll vs volatile inflow cohorts
- Regression: primary products unaffected
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from decision_engine.product_policies import (
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
    validate_required_features,
)


# ---------------------------------------------------------------------------
# Prompt 14 — Credit Builder / Secured Card
# ---------------------------------------------------------------------------

class TestCreditBuilderProfile:
    def _inp(self, **kwargs) -> ProductPolicyEvaluationInput:
        base = dict(
            application_id="cb-test",
            product_type="CREDIT_BUILDER",
            annual_income_usd=28000.0,
            loan_amount_usd=500.0,
            debt_to_income_ratio=0.30,
            fraud_probability=0.04,
            pd_score=0.10,
        )
        base.update(kwargs)
        return ProductPolicyEvaluationInput(**base)

    def test_no_credit_score_applicant_passes_prequal(self):
        """Thin-file with no credit score must be eligible for Credit Builder."""
        inp = self._inp(credit_score=None)
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_active_bankruptcy_hard_declines(self):
        inp = self._inp(has_active_bankruptcy=True)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("no_active_bankruptcy_check") is False
        assert result.pre_qualification_passed is False

    def test_no_bankruptcy_passes_rule(self):
        inp = self._inp(has_active_bankruptcy=False)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("no_active_bankruptcy_check") is True

    def test_deposit_covers_limit_passes(self):
        inp = self._inp(security_deposit_amount=500.0, loan_amount_usd=500.0)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("deposit_secured_limit_check") is True

    def test_deposit_below_limit_fails(self):
        inp = self._inp(security_deposit_amount=400.0, loan_amount_usd=500.0)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("deposit_secured_limit_check") is False
        assert result.pre_qualification_passed is False

    def test_no_bureau_signal_soft_routes_not_hard_decline(self):
        """No bureau signal must not cause a hard decline — only soft review routing."""
        inp = self._inp(has_bureau_signal=False, credit_score=None)
        result = evaluate_product_policy(inp)
        # manual_review_if_no_bureau_signal is a soft rule — always returns True
        assert result.extra_rule_results.get("manual_review_if_no_bureau_signal") is True

    def test_annual_income_required_missing_fails(self):
        inp = ProductPolicyEvaluationInput(
            application_id="cb-missing-income",
            product_type="CREDIT_BUILDER",
            loan_amount_usd=300.0,
            debt_to_income_ratio=0.25,
            # annual_income_usd intentionally omitted
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is False
        assert any("MISSING_REQUIRED_FIELD:annual_income" in f for f in result.pre_qualification_flags)

    def test_loan_above_max_limit_fails(self):
        policy = get_product_policy("CREDIT_BUILDER")
        inp = self._inp(loan_amount_usd=policy.max_loan_amount_usd + 1)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False
        assert result.pre_qualification_passed is False

    def test_loan_at_minimum_passes(self):
        policy = get_product_policy("CREDIT_BUILDER")
        inp = self._inp(loan_amount_usd=policy.min_loan_amount_usd)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is True

    def test_high_pd_but_thin_file_tolerance_approves(self):
        """PD up to pd_threshold_refer should pass prequal (PD gating is separate from policy gate)."""
        inp = self._inp(pd_score=0.14, fraud_probability=0.03)
        result = evaluate_product_policy(inp)
        # Policy gate does not use pd_score — it uses fraud/dti/amount/rules
        assert result.pre_qualification_passed is True

    def test_high_fraud_declines(self):
        policy = get_product_policy("CREDIT_BUILDER")
        inp = self._inp(fraud_probability=policy.fraud_reject_threshold + 0.01)
        result = evaluate_product_policy(inp, policy)
        assert result.fraud_verdict == "REJECT"
        assert result.pre_qualification_passed is False

    def test_high_dti_declines(self):
        policy = get_product_policy("CREDIT_BUILDER")
        inp = self._inp(debt_to_income_ratio=policy.max_dti + 0.05)
        result = evaluate_product_policy(inp, policy)
        assert result.dti_passed is False
        assert result.pre_qualification_passed is False

    def test_regression_personal_loan_unaffected(self):
        inp = ProductPolicyEvaluationInput(
            application_id="pl-regression-cb",
            product_type="PERSONAL_LOAN",
            credit_score=730,
            annual_income_usd=70000.0,
            debt_to_income_ratio=0.25,
            loan_amount_usd=12000.0,
            num_open_accounts=4,
            fraud_probability=0.02,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_regression_bnpl_unaffected(self):
        inp = ProductPolicyEvaluationInput(
            application_id="bnpl-regression-cb",
            product_type="BNPL",
            credit_score=640,
            payment_history="good",
            debt_to_income_ratio=0.28,
            loan_amount_usd=200.0,
            num_open_accounts=1,
            fraud_probability=0.03,
            concurrent_bnpl_plans=1,
            merchant_category="electronics",
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True


# ---------------------------------------------------------------------------
# Prompt 15 — Overdraft / Cash Advance
# ---------------------------------------------------------------------------

class TestOverdraftCashAdvanceProfile:
    def _inp(self, **kwargs) -> ProductPolicyEvaluationInput:
        base = dict(
            application_id="oca-test",
            product_type="OVERDRAFT_CASH_ADVANCE",
            annual_income_usd=36000.0,
            avg_monthly_cash_inflow=3000.0,
            loan_amount_usd=300.0,
            debt_to_income_ratio=0.30,
            overdraft_events_90d=0,
            paycheck_cadence="biweekly",
            fraud_probability=0.04,
            pd_score=0.08,
        )
        base.update(kwargs)
        return ProductPolicyEvaluationInput(**base)

    def test_stable_payroll_applicant_approves(self):
        inp = self._inp(overdraft_events_90d=0, avg_monthly_cash_inflow=3000.0)
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_high_overdraft_frequency_declines(self):
        """More than 3 overdraft events in 90 days must trigger decline."""
        inp = self._inp(overdraft_events_90d=4)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("overdraft_frequency_check") is False
        assert result.pre_qualification_passed is False

    def test_exactly_3_overdraft_events_passes(self):
        inp = self._inp(overdraft_events_90d=3)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("overdraft_frequency_check") is True

    def test_insufficient_net_inflow_declines(self):
        """Inflow must be >= 1.5× advance amount; too low → decline."""
        # Advance $300, inflow $400 (need $450 minimum)
        inp = self._inp(loan_amount_usd=300.0, avg_monthly_cash_inflow=400.0)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("net_inflow_adequacy_check") is False
        assert result.pre_qualification_passed is False

    def test_adequate_net_inflow_passes(self):
        # Advance $300, inflow $600 (>= $450 minimum)
        inp = self._inp(loan_amount_usd=300.0, avg_monthly_cash_inflow=600.0)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("net_inflow_adequacy_check") is True

    def test_net_inflow_at_exact_threshold_passes(self):
        # Advance $200, inflow exactly $300 (= 1.5×)
        inp = self._inp(loan_amount_usd=200.0, avg_monthly_cash_inflow=300.0)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("net_inflow_adequacy_check") is True

    def test_volatile_inflow_no_overdraft_still_passes_policy_gate(self):
        """Irregular paycheck cadence is a soft signal — policy gate does not hard-decline."""
        inp = self._inp(paycheck_cadence="irregular", overdraft_events_90d=1,
                        avg_monthly_cash_inflow=900.0, loan_amount_usd=300.0)
        result = evaluate_product_policy(inp)
        # repayment_cadence_check is soft (always passes rule)
        assert result.extra_rule_results.get("repayment_cadence_check") is True

    def test_active_bankruptcy_hard_declines(self):
        inp = self._inp(has_active_bankruptcy=True)
        result = evaluate_product_policy(inp)
        assert result.extra_rule_results.get("no_active_bankruptcy_check") is False
        assert result.pre_qualification_passed is False

    def test_annual_income_required_missing_fails(self):
        inp = ProductPolicyEvaluationInput(
            application_id="oca-missing-income",
            product_type="OVERDRAFT_CASH_ADVANCE",
            loan_amount_usd=200.0,
            debt_to_income_ratio=0.25,
            # annual_income_usd and avg_monthly_cash_inflow intentionally omitted
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is False
        missing_names = [f.split(":")[1] for f in result.pre_qualification_flags if "MISSING_REQUIRED_FIELD" in f]
        assert "annual_income" in missing_names
        assert "avg_monthly_cash_inflow" in missing_names

    def test_loan_above_max_declines(self):
        policy = get_product_policy("OVERDRAFT_CASH_ADVANCE")
        inp = self._inp(loan_amount_usd=policy.max_loan_amount_usd + 1)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False

    def test_loan_below_min_declines(self):
        policy = get_product_policy("OVERDRAFT_CASH_ADVANCE")
        inp = self._inp(loan_amount_usd=policy.min_loan_amount_usd - 1,
                        avg_monthly_cash_inflow=500.0)
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False

    def test_high_fraud_declines(self):
        policy = get_product_policy("OVERDRAFT_CASH_ADVANCE")
        inp = self._inp(fraud_probability=policy.fraud_reject_threshold + 0.01)
        result = evaluate_product_policy(inp, policy)
        assert result.fraud_verdict == "REJECT"
        assert result.pre_qualification_passed is False

    def test_stable_vs_volatile_inflow_same_policy_gate_outcome(self):
        """Policy gate outcome must depend on overdraft count, not cadence label alone."""
        stable = self._inp(paycheck_cadence="biweekly", overdraft_events_90d=0,
                           avg_monthly_cash_inflow=1000.0)
        volatile = self._inp(paycheck_cadence="irregular", overdraft_events_90d=0,
                              avg_monthly_cash_inflow=1000.0)
        r_stable = evaluate_product_policy(stable)
        r_volatile = evaluate_product_policy(volatile)
        assert r_stable.pre_qualification_passed == r_volatile.pre_qualification_passed

    def test_regression_smb_secured_unaffected(self):
        inp = ProductPolicyEvaluationInput(
            application_id="smb-regression-oca",
            product_type="SMB_SECURED_LOAN",
            annual_revenue=1_000_000.0,
            years_in_business=4,
            debt_service_coverage_ratio=1.55,
            business_type="llc",
            collateral_type="real_estate",
            collateral_value=600_000.0,
            collateral_ltv=0.50,
            loan_amount_usd=300_000.0,
            debt_to_income_ratio=0.38,
            fraud_probability=0.03,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_regression_credit_builder_unaffected_by_oca_rules(self):
        inp = ProductPolicyEvaluationInput(
            application_id="cb-regression-oca",
            product_type="CREDIT_BUILDER",
            annual_income_usd=30000.0,
            loan_amount_usd=400.0,
            debt_to_income_ratio=0.30,
            fraud_probability=0.04,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True


# ---------------------------------------------------------------------------
# Cross-secondary-product sanity checks
# ---------------------------------------------------------------------------

class TestSecondaryProductCatalog:
    def test_credit_builder_policy_exists(self):
        policy = get_product_policy("CREDIT_BUILDER")
        assert policy.product_type == "CREDIT_BUILDER"
        assert policy.min_open_accounts == 0  # must allow zero tradelines
        assert policy.max_loan_amount_usd <= 3000.0

    def test_overdraft_policy_exists(self):
        policy = get_product_policy("OVERDRAFT_CASH_ADVANCE")
        assert policy.product_type == "OVERDRAFT_CASH_ADVANCE"
        assert policy.max_loan_amount_usd <= 1000.0

    def test_credit_builder_apr_cap_reasonable(self):
        policy = get_product_policy("CREDIT_BUILDER")
        assert policy.max_apr <= 36.0  # CFPB / MLA guidance

    def test_overdraft_apr_cap_mla_compliant(self):
        policy = get_product_policy("OVERDRAFT_CASH_ADVANCE")
        assert policy.max_apr <= 36.0

    def test_validate_required_features_credit_builder(self):
        inp = ProductPolicyEvaluationInput(
            application_id="cb-req",
            product_type="CREDIT_BUILDER",
            loan_amount_usd=300.0,
        )
        missing = validate_required_features("CREDIT_BUILDER", inp)
        assert any("annual_income" in f for f in missing)

    def test_validate_required_features_overdraft(self):
        inp = ProductPolicyEvaluationInput(
            application_id="oca-req",
            product_type="OVERDRAFT_CASH_ADVANCE",
            loan_amount_usd=200.0,
        )
        missing = validate_required_features("OVERDRAFT_CASH_ADVANCE", inp)
        assert any("annual_income" in f for f in missing)
        assert any("avg_monthly_cash_inflow" in f for f in missing)
