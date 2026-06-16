"""
Tests for Multi-Product Policy Engine (decision_engine/product_policies.py)
"""
from __future__ import annotations

import dataclasses
import pytest

from decision_engine.product_policies import (
    ProductPolicy,
    ProductPolicyEvaluationInput,
    ProductPolicyResult,
    evaluate_product_policy,
    get_product_policy,
    list_product_types,
)


# ---------------------------------------------------------------------------
# list_product_types
# ---------------------------------------------------------------------------

def test_list_product_types_returns_all_six():
    products = list_product_types()
    assert len(products) == 6
    assert "CREDIT_CARD" in products
    assert "MORTGAGE" in products
    assert "BNPL" in products
    assert "SMALL_BUSINESS_LOAN" in products


# ---------------------------------------------------------------------------
# get_product_policy
# ---------------------------------------------------------------------------

def test_get_product_policy_credit_card():
    policy = get_product_policy("CREDIT_CARD")
    assert isinstance(policy, ProductPolicy)
    assert policy.product_type == "CREDIT_CARD"
    assert 0 < policy.pd_threshold_approve < 1.0
    assert 0 < policy.fraud_reject_threshold < 1.0


def test_get_product_policy_all_products():
    for pt in list_product_types():
        policy = get_product_policy(pt)
        assert policy.product_type == pt
        assert policy.max_apr > 0


def test_get_product_policy_unknown_raises():
    with pytest.raises((KeyError, ValueError)):
        get_product_policy("FLYING_CARPET")


# ---------------------------------------------------------------------------
# evaluate_product_policy helpers
# ---------------------------------------------------------------------------

def _clean_input(product_type: str) -> ProductPolicyEvaluationInput:
    return ProductPolicyEvaluationInput(
        application_id="app-001",
        product_type=product_type,
        fraud_probability=0.01,
        pd_score=0.01,
        loan_amount_usd=5_000.0,
        annual_income_usd=120_000.0,
        debt_to_income_ratio=0.20,
        num_open_accounts=5,
        credit_score=750,
    )


# ---------------------------------------------------------------------------
# evaluate_product_policy — clean approval
# ---------------------------------------------------------------------------

def test_credit_card_approve():
    inp = _clean_input("CREDIT_CARD")
    result = evaluate_product_policy(inp)
    assert result.pre_qualification_passed
    assert result.fraud_verdict == "APPROVE"


def test_personal_loan_approve():
    inp = _clean_input("PERSONAL_LOAN")
    result = evaluate_product_policy(inp)
    assert result.pre_qualification_passed


def test_bnpl_approve():
    inp = _clean_input("BNPL")
    result = evaluate_product_policy(inp)
    assert result.pre_qualification_passed


# ---------------------------------------------------------------------------
# evaluate_product_policy — rejections
# ---------------------------------------------------------------------------

def test_high_fraud_score_triggers_reject():
    inp = _clean_input("CREDIT_CARD")
    inp.fraud_probability = 0.95
    result = evaluate_product_policy(inp)
    assert result.fraud_verdict == "REJECT"
    assert not result.pre_qualification_passed


def test_moderate_fraud_score_triggers_review():
    inp = _clean_input("PERSONAL_LOAN")
    inp.fraud_probability = 0.50
    result = evaluate_product_policy(inp)
    assert result.fraud_verdict == "MANUAL_REVIEW"


def test_high_dti_fails_dti_check():
    inp = _clean_input("CREDIT_CARD")
    inp.debt_to_income_ratio = 0.90
    result = evaluate_product_policy(inp)
    assert not result.dti_passed


def test_loan_below_minimum_fails():
    inp = _clean_input("PERSONAL_LOAN")
    inp.loan_amount_usd = 1.0  # below $1,000 minimum
    result = evaluate_product_policy(inp)
    assert not result.loan_amount_passed


def test_loan_above_maximum_fails():
    inp = _clean_input("CREDIT_CARD")
    inp.loan_amount_usd = 999_999.0  # above $50,000 maximum
    result = evaluate_product_policy(inp)
    assert not result.loan_amount_passed


# ---------------------------------------------------------------------------
# evaluate_product_policy — custom policy override
# ---------------------------------------------------------------------------

def test_custom_policy_applied():
    base_policy = get_product_policy("CREDIT_CARD")
    tight_policy = dataclasses.replace(base_policy, max_dti=0.01)

    inp = _clean_input("CREDIT_CARD")
    inp.debt_to_income_ratio = 0.20  # would normally pass
    result = evaluate_product_policy(inp, policy=tight_policy)
    assert not result.dti_passed


# ---------------------------------------------------------------------------
# result structure
# ---------------------------------------------------------------------------

def test_result_has_required_fields():
    inp = _clean_input("AUTO_LOAN")
    result = evaluate_product_policy(inp)
    assert isinstance(result, ProductPolicyResult)
    assert isinstance(result.pre_qualification_flags, list)
    assert isinstance(result.policy_decline_codes, list)
    assert result.policy_version_tag  # non-empty string
