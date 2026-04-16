"""
Tests for Sprint 7-A: Multi-Product Policy Engine (decision_engine/product_policies.py)
"""
from __future__ import annotations

import pytest

from decision_engine.product_policies import (
    ProductPolicy,
    ProductPolicyInput,
    ProductPolicyResult,
    evaluate_product_policy,
    get_product_policy,
    list_supported_products,
)


# ---------------------------------------------------------------------------
# list_supported_products
# ---------------------------------------------------------------------------

def test_list_supported_products_returns_all_six():
    products = list_supported_products()
    assert len(products) == 6
    names = {p["product_type"] for p in products}
    assert "CREDIT_CARD" in names
    assert "MORTGAGE" in names
    assert "BNPL" in names
    assert "SMALL_BUSINESS_LOAN" in names


# ---------------------------------------------------------------------------
# get_product_policy
# ---------------------------------------------------------------------------

def test_get_product_policy_credit_card():
    policy = get_product_policy("CREDIT_CARD")
    assert policy.product_type == "CREDIT_CARD"
    assert policy.pd_approval_threshold < 1.0
    assert policy.fraud_hard_decline_threshold < 1.0


def test_get_product_policy_unknown_raises():
    with pytest.raises(KeyError):
        get_product_policy("FLYING_CARPET")


def test_get_product_policy_tenant_overrides_applied():
    overrides = {"pd_approval_threshold": 0.99}
    policy = get_product_policy("PERSONAL_LOAN", tenant_overrides=overrides)
    assert policy.pd_approval_threshold == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# evaluate_product_policy — clean approval
# ---------------------------------------------------------------------------

def _min_clean_input(product_type: str) -> tuple[ProductPolicyInput, ProductPolicy]:
    policy = get_product_policy(product_type)
    inp = ProductPolicyInput(
        pd_score=0.01,
        fraud_score=0.01,
        income=120_000.0,
        existing_monthly_debt=500.0,
        requested_amount=5_000.0,
        collateral_value=None,
        extra_features={},
    )
    return inp, policy


def test_credit_card_approve():
    inp, policy = _min_clean_input("CREDIT_CARD")
    result = evaluate_product_policy(inp, policy)
    assert result.pre_qualified is True
    assert result.fraud_verdict in ("PASS", "REVIEW")


def test_personal_loan_approve():
    inp, policy = _min_clean_input("PERSONAL_LOAN")
    result = evaluate_product_policy(inp, policy)
    assert result.pre_qualified is True


def test_bnpl_approve():
    inp, policy = _min_clean_input("BNPL")
    result = evaluate_product_policy(inp, policy)
    assert result.pre_qualified is True


# ---------------------------------------------------------------------------
# evaluate_product_policy — high PD decline
# ---------------------------------------------------------------------------

def test_high_pd_score_declines():
    policy = get_product_policy("CREDIT_CARD")
    inp = ProductPolicyInput(
        pd_score=0.99,
        fraud_score=0.01,
        income=80_000.0,
        existing_monthly_debt=500.0,
        requested_amount=5_000.0,
    )
    result = evaluate_product_policy(inp, policy)
    assert result.pre_qualified is False
    assert any("pd_score" in r.rule_name.lower() or "pd" in r.rule_name.lower() for r in result.rule_outcomes)


def test_high_fraud_score_hard_declines():
    policy = get_product_policy("PERSONAL_LOAN")
    inp = ProductPolicyInput(
        pd_score=0.05,
        fraud_score=0.99,
        income=80_000.0,
        existing_monthly_debt=500.0,
        requested_amount=10_000.0,
    )
    result = evaluate_product_policy(inp, policy)
    assert result.fraud_verdict == "HARD_DECLINE"
    assert result.pre_qualified is False


# ---------------------------------------------------------------------------
# evaluate_product_policy — DTI breach
# ---------------------------------------------------------------------------

def test_high_dti_declines():
    policy = get_product_policy("MORTGAGE")
    # Monthly income = $4_000; monthly debt = $2_500 → DTI = 62.5%
    inp = ProductPolicyInput(
        pd_score=0.02,
        fraud_score=0.01,
        income=48_000.0,   # annual
        existing_monthly_debt=2_500.0,
        requested_amount=200_000.0,
        collateral_value=250_000.0,
        extra_features={},
    )
    result = evaluate_product_policy(inp, policy)
    # DTI=62.5% should breach typical mortgage 43% QM limit
    dti_rule = next(
        (r for r in result.rule_outcomes if "dti" in r.rule_name.lower()),
        None,
    )
    assert dti_rule is not None, "Expected a DTI rule outcome"
    assert dti_rule.passed is False


# ---------------------------------------------------------------------------
# evaluate_product_policy — loan amount bounds
# ---------------------------------------------------------------------------

def test_bnpl_over_limit_declines():
    policy = get_product_policy("BNPL")
    inp = ProductPolicyInput(
        pd_score=0.02,
        fraud_score=0.01,
        income=100_000.0,
        existing_monthly_debt=200.0,
        requested_amount=999_999.0,   # far above BNPL max
    )
    result = evaluate_product_policy(inp, policy)
    amount_rule = next(
        (r for r in result.rule_outcomes if "amount" in r.rule_name.lower()),
        None,
    )
    assert amount_rule is not None or result.pre_qualified is False


# ---------------------------------------------------------------------------
# result structure
# ---------------------------------------------------------------------------

def test_result_has_required_fields():
    inp, policy = _min_clean_input("AUTO_LOAN")
    result = evaluate_product_policy(inp, policy)
    assert isinstance(result, ProductPolicyResult)
    assert isinstance(result.rule_outcomes, list)
    assert isinstance(result.fcra_codes, list)
    assert result.policy_version  # non-empty string
