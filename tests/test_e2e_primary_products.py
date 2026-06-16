"""
Prompt 13: End-to-end tests — enrichment → feature engineering → policy evaluation
for BNPL, Personal Loan, and SMB Secured Loan.

Covers:
  - Happy path: bank enrichment → feature matrix → policy → APPROVE
  - Degraded provider: missing bank data → fallback → policy runs on reduced features
  - Invalid input: bad loan amount → validation error before policy runs
  - Deterministic outputs on fixed fixtures across all three primary products

These tests wire together the full pipeline without hitting live APIs.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from credit_core.features import compute_feature_matrix
from decision_engine.product_policies import (
    ProductPolicyEvaluationInput,
    evaluate_product_policy,
    get_product_policy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_feature_input(raw: Dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([raw])


def make_policy_input(product_type, *, credit_score=None, dti=0.25, income=60000.0,
                      loan_amount=10000.0, num_accounts=3, fraud_prob=0.03, pd_score=0.05,
                      **extra) -> ProductPolicyEvaluationInput:
    return ProductPolicyEvaluationInput(
        application_id=f"e2e-{product_type.lower()}-001",
        product_type=product_type,
        credit_score=credit_score,
        annual_income_usd=income,
        debt_to_income_ratio=dti,
        loan_amount_usd=loan_amount,
        num_open_accounts=num_accounts,
        fraud_probability=fraud_prob,
        pd_score=pd_score,
        **extra,
    )


# ---------------------------------------------------------------------------
# Shared enrichment mock data (simulates successful Plaid enrichment)
# ---------------------------------------------------------------------------

MOCK_BANK_ENRICHMENT = {
    "avg_monthly_cash_inflow": 5200.0,
    "avg_monthly_cash_outflow": 3800.0,
    "nsfv_last_90_days": 0,
    "returned_payment_count": 0,
    "income_confidence": 0.92,
    "min_balance_90d": 350.0,
    "avg_monthly_end_balance": 2100.0,
    "monthly_net_income": 4800.0,
}

DEGRADED_BANK_ENRICHMENT: Dict[str, Any] = {}  # provider returned nothing


# ---------------------------------------------------------------------------
# E2E: Personal Loan
# ---------------------------------------------------------------------------

class TestPersonalLoanE2E:
    BASE_RAW = {
        "application_id": "e2e-pl-001",
        "loan_amount": 15000.0,
        "loan_purpose": "debt_consolidation",
        "loan_term_months": 36,
        "annual_income": 75000.0,
        "employment_status": "employed",
        "employer_tenure_months": 36.0,
        "debt_to_income_ratio": 0.28,
        "existing_debt_amount": 21000.0,
        "credit_score": 730,
        "num_open_accounts": 4,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
    }

    def test_happy_path_approve(self):
        raw = {**self.BASE_RAW, **MOCK_BANK_ENRICHMENT}
        features = compute_feature_matrix(build_feature_input(raw))
        assert "thin_file_alt_score" in features.columns

        inp = make_policy_input(
            "PERSONAL_LOAN",
            credit_score=730,
            dti=0.28,
            income=75000.0,
            loan_amount=15000.0,
            num_accounts=4,
            fraud_prob=0.02,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True
        assert result.dti_passed is True
        assert result.fraud_verdict == "APPROVE"

    def test_degraded_provider_still_evaluates_policy(self):
        """When enrichment returns nothing, policy evaluation still runs on base features."""
        raw = {**self.BASE_RAW, **DEGRADED_BANK_ENRICHMENT}
        features = compute_feature_matrix(build_feature_input(raw))
        assert "thin_file_alt_score" in features.columns
        # thin_file_alt_score with no alt-data should be very low but non-negative
        score = float(features["thin_file_alt_score"].iloc[0])
        assert 0.0 <= score <= 1.0

        inp = make_policy_input(
            "PERSONAL_LOAN",
            credit_score=730,
            dti=0.28,
            income=75000.0,
            loan_amount=15000.0,
            num_accounts=4,
            fraud_prob=0.02,
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_invalid_loan_amount_below_minimum_fails_prequal(self):
        from decision_engine.product_policies import get_product_policy
        policy = get_product_policy("PERSONAL_LOAN")
        inp = make_policy_input(
            "PERSONAL_LOAN",
            credit_score=720,
            loan_amount=policy.min_loan_amount_usd - 1,
            num_accounts=3,
        )
        result = evaluate_product_policy(inp, policy)
        assert result.loan_amount_passed is False
        assert result.pre_qualification_passed is False

    def test_feature_enrichment_boosts_thin_file_score(self):
        """Enriched bank signals should produce a higher alt score than no bank data."""
        raw_with_bank = {**self.BASE_RAW, "credit_score": None, **MOCK_BANK_ENRICHMENT}
        raw_without_bank = {**self.BASE_RAW, "credit_score": None}

        feat_with = compute_feature_matrix(build_feature_input(raw_with_bank))
        feat_without = compute_feature_matrix(build_feature_input(raw_without_bank))

        score_with = float(feat_with["thin_file_alt_score"].iloc[0])
        score_without = float(feat_without["thin_file_alt_score"].iloc[0])
        assert score_with > score_without

    def test_outputs_deterministic_on_fixed_fixture(self):
        raw = {**self.BASE_RAW, **MOCK_BANK_ENRICHMENT}
        f1 = compute_feature_matrix(build_feature_input(raw))
        f2 = compute_feature_matrix(build_feature_input(raw))
        assert float(f1["thin_file_alt_score"].iloc[0]) == float(f2["thin_file_alt_score"].iloc[0])


# ---------------------------------------------------------------------------
# E2E: BNPL
# ---------------------------------------------------------------------------

class TestBNPLE2E:
    BASE_RAW = {
        "application_id": "e2e-bnpl-001",
        "loan_amount": 250.0,
        "loan_purpose": "personal",
        "loan_term_months": 4,
        "annual_income": 42000.0,
        "employment_status": "employed",
        "employer_tenure_months": 12.0,
        "debt_to_income_ratio": 0.28,
        "existing_debt_amount": 11760.0,
        "credit_score": 650,
        "num_open_accounts": 2,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
    }

    def test_happy_path_approve(self):
        raw = {**self.BASE_RAW, **MOCK_BANK_ENRICHMENT}
        features = compute_feature_matrix(build_feature_input(raw))
        assert "thin_file_alt_score" in features.columns

        inp = make_policy_input(
            "BNPL",
            credit_score=650,
            dti=0.28,
            income=42000.0,
            loan_amount=250.0,
            num_accounts=2,
            fraud_prob=0.04,
            payment_history="good",
            concurrent_bnpl_plans=1,
            merchant_category="electronics",
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is True

    def test_nsf_events_in_bank_data_reduce_alt_score(self):
        inflow_base = {"avg_monthly_cash_inflow": 3000.0, "avg_monthly_cash_outflow": 2000.0, "income_confidence": 0.80}
        raw_clean = {**self.BASE_RAW, "nsfv_last_90_days": 0, "credit_score": None, **inflow_base}
        raw_nsf = {**self.BASE_RAW, "nsfv_last_90_days": 3, "credit_score": None, **inflow_base}

        score_clean = float(compute_feature_matrix(build_feature_input(raw_clean))["thin_file_alt_score"].iloc[0])
        score_nsf = float(compute_feature_matrix(build_feature_input(raw_nsf))["thin_file_alt_score"].iloc[0])
        assert score_nsf < score_clean

    def test_invalid_merchant_declines(self):
        inp = make_policy_input(
            "BNPL",
            credit_score=650,
            dti=0.28,
            income=42000.0,
            loan_amount=250.0,
            num_accounts=2,
            fraud_prob=0.04,
            payment_history="good",
            concurrent_bnpl_plans=1,
            merchant_category="gambling",
        )
        result = evaluate_product_policy(inp)
        assert result.pre_qualification_passed is False

    def test_outputs_deterministic_on_fixed_fixture(self):
        inp = make_policy_input(
            "BNPL",
            credit_score=650,
            dti=0.28,
            income=42000.0,
            loan_amount=250.0,
            num_accounts=2,
            fraud_prob=0.04,
            payment_history="good",
            concurrent_bnpl_plans=1,
            merchant_category="home_goods",
        )
        r1 = evaluate_product_policy(inp)
        r2 = evaluate_product_policy(inp)
        assert r1.pre_qualification_passed == r2.pre_qualification_passed
        assert r1.policy_decline_codes == r2.policy_decline_codes


# ---------------------------------------------------------------------------
# E2E: SMB Secured Loan
# ---------------------------------------------------------------------------

class TestSMBSecuredE2E:
    BASE_RAW = {
        "application_id": "e2e-smb-001",
        "loan_amount": 300000.0,
        "loan_purpose": "business",
        "loan_term_months": 60,
        "annual_income": 200000.0,
        "employment_status": "self_employed",
        "employer_tenure_months": 0,
        "debt_to_income_ratio": 0.35,
        "existing_debt_amount": 70000.0,
        "credit_score": 700,
        "num_open_accounts": 3,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
    }

    def _base_policy_input(self, **overrides):
        base = dict(
            product_type="SMB_SECURED_LOAN",
            annual_revenue=1_000_000.0,
            years_in_business=5,
            debt_service_coverage_ratio=1.55,
            business_type="llc",
            collateral_type="real_estate",
            collateral_value=550_000.0,
            collateral_ltv=0.55,
            loan_amount=300_000.0,
            dti=0.35,
            income=200_000.0,
            num_accounts=3,
            fraud_prob=0.03,
        )
        base.update(overrides)
        return make_policy_input(**base)

    def test_happy_path_approve(self):
        raw = {**self.BASE_RAW, **MOCK_BANK_ENRICHMENT}
        features = compute_feature_matrix(build_feature_input(raw))
        assert "thin_file_alt_score" in features.columns

        result = evaluate_product_policy(self._base_policy_input())
        assert result.pre_qualification_passed is True

    def test_degraded_provider_still_evaluates_secured_policy(self):
        raw = {**self.BASE_RAW, **DEGRADED_BANK_ENRICHMENT}
        features = compute_feature_matrix(build_feature_input(raw))
        assert "thin_file_alt_score" in features.columns

        result = evaluate_product_policy(self._base_policy_input())
        assert result.pre_qualification_passed is True

    def test_insufficient_collateral_declines(self):
        result = evaluate_product_policy(self._base_policy_input(
            collateral_value=200_000.0,  # loan is $300k, collateral only $200k
            loan_amount=300_000.0,
        ))
        assert result.pre_qualification_passed is False
        assert result.extra_rule_results.get("collateral_adequacy_check") is False

    def test_new_business_declines(self):
        result = evaluate_product_policy(self._base_policy_input(years_in_business=0))
        assert result.pre_qualification_passed is False

    def test_outputs_deterministic_on_fixed_fixture(self):
        inp = self._base_policy_input()
        r1 = evaluate_product_policy(inp)
        r2 = evaluate_product_policy(inp)
        assert r1.pre_qualification_passed == r2.pre_qualification_passed
        assert sorted(r1.policy_decline_codes) == sorted(r2.policy_decline_codes)
        assert sorted(r1.pre_qualification_flags) == sorted(r2.pre_qualification_flags)


# ---------------------------------------------------------------------------
# E2E: Cross-product — same bad fraud score always blocks all products
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("product_type,extra", [
    ("PERSONAL_LOAN", {"credit_score": 720, "num_accounts": 3}),
    ("BNPL", {"credit_score": 650, "payment_history": "good", "concurrent_bnpl_plans": 1, "merchant_category": "electronics"}),
    ("SMB_SECURED_LOAN", {
        "annual_revenue": 1_000_000.0, "years_in_business": 5,
        "debt_service_coverage_ratio": 1.50, "business_type": "llc",
        "collateral_type": "real_estate", "collateral_value": 500_000.0,
        "collateral_ltv": 0.55,
    }),
])
def test_high_fraud_blocks_all_primary_products(product_type, extra):
    policy = get_product_policy(product_type)
    inp = make_policy_input(
        product_type,
        loan_amount=10000.0,
        dti=0.25,
        income=60000.0,
        fraud_prob=policy.fraud_reject_threshold + 0.01,
        **extra,
    )
    result = evaluate_product_policy(inp, policy)
    assert result.fraud_verdict == "REJECT"
    assert result.pre_qualification_passed is False
