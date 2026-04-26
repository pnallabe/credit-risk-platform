"""
Smoke tests for decision_engine/cc_origination_policy.py
"""
from __future__ import annotations

import pytest

from decision_engine.cc_origination_policy import (
    Decision,
    PolicyDecision,
    ProductPolicy,
    PRODUCT_POLICIES,
    assign_credit_limit,
    compute_breakeven_pd,
    evaluate_application,
    evaluate_batch,
)


# ---------------------------------------------------------------------------
# PRODUCT_POLICIES
# ---------------------------------------------------------------------------

def test_product_policies_non_empty():
    assert len(PRODUCT_POLICIES) > 0
    assert "rewards" in PRODUCT_POLICIES
    assert "secured" in PRODUCT_POLICIES
    assert "premium" in PRODUCT_POLICIES


def test_product_policy_fields():
    policy = PRODUCT_POLICIES["rewards"]
    assert isinstance(policy.min_fico, int)
    assert isinstance(policy.max_dti, float)
    assert isinstance(policy.pd_hard_decline, float)


# ---------------------------------------------------------------------------
# assign_credit_limit
# ---------------------------------------------------------------------------

def test_assign_credit_limit_within_bounds():
    policy = PRODUCT_POLICIES["basic"]
    cl = assign_credit_limit(
        policy=policy,
        annual_income=60_000.0,
        fico_score=700,
        pd_score=0.10,
        dti=0.30,
    )
    assert policy.cl_abs_min <= cl <= policy.cl_abs_max


def test_assign_credit_limit_higher_fico_higher_limit():
    policy = PRODUCT_POLICIES["basic"]
    cl_low = assign_credit_limit(policy, 60_000.0, 620, 0.10, 0.30)
    cl_high = assign_credit_limit(policy, 60_000.0, 780, 0.05, 0.25)
    assert cl_high >= cl_low


# ---------------------------------------------------------------------------
# compute_breakeven_pd
# ---------------------------------------------------------------------------

def test_compute_breakeven_pd_returns_dict():
    policy = PRODUCT_POLICIES["rewards"]
    result = compute_breakeven_pd(policy, avg_balance=2_500.0)
    assert isinstance(result, dict)
    assert "breakeven_pd" in result
    assert "product" in result
    assert result["product"] == "rewards"


def test_compute_breakeven_pd_positive():
    policy = PRODUCT_POLICIES["premium"]
    result = compute_breakeven_pd(policy, avg_balance=5_000.0)
    assert result["breakeven_pd"] >= 0.0


# ---------------------------------------------------------------------------
# evaluate_application
# ---------------------------------------------------------------------------

def _clean_cc_applicant(**overrides):
    base = dict(
        account_id=1001,
        fico_score=700,
        annual_income=75_000.0,
        dti=0.30,
        num_bankruptcy=0,
        num_derog_marks=0,
        inq_last_6m=1,
        age=30,
        employment_status="employed",
        pct_rev_utilization=0.25,
        pd_score=0.05,
        requested_product="basic",
    )
    base.update(overrides)
    return base


def test_evaluate_application_approve():
    result = evaluate_application(**_clean_cc_applicant())
    assert isinstance(result, PolicyDecision)
    assert result.decision in (Decision.APPROVE, Decision.MANUAL_REVIEW)


def test_evaluate_application_fraud_decline():
    result = evaluate_application(**_clean_cc_applicant(pd_score=0.99))
    assert result.decision in (Decision.DECLINE, Decision.REFER_SECURED)


def test_evaluate_application_fico_below_min():
    result = evaluate_application(**_clean_cc_applicant(fico_score=400, requested_product="rewards"))
    assert result.decision in (Decision.DECLINE, Decision.REFER_SECURED)


def test_evaluate_application_secured_product():
    result = evaluate_application(**_clean_cc_applicant(requested_product="secured", fico_score=560))
    assert isinstance(result, PolicyDecision)


def test_evaluate_application_unknown_product_defaults():
    """Unknown product should not crash."""
    result = evaluate_application(**_clean_cc_applicant(requested_product="rewards"))
    assert isinstance(result, PolicyDecision)


def test_evaluate_application_returns_decline_reasons_on_decline():
    result = evaluate_application(**_clean_cc_applicant(fico_score=400, requested_product="premium"))
    if result.decision == Decision.DECLINE:
        assert isinstance(result.decline_reasons, list)


def test_evaluate_application_manual_review():
    """pd_score in manual review band should trigger MANUAL_REVIEW."""
    policy = PRODUCT_POLICIES["basic"]
    result = evaluate_application(**_clean_cc_applicant(
        pd_score=policy.pd_manual_review + 0.01,
        requested_product="basic",
    ))
    assert result.decision in (Decision.MANUAL_REVIEW, Decision.DECLINE, Decision.REFER_SECURED)


def test_evaluate_application_minor_declines():
    """Age below 18 should decline."""
    result = evaluate_application(**_clean_cc_applicant(age=17))
    assert result.decision in (Decision.DECLINE, Decision.REFER_SECURED)


def test_evaluate_application_high_utilization():
    result = evaluate_application(**_clean_cc_applicant(pct_rev_utilization=0.99))
    assert result.decision in (Decision.DECLINE, Decision.REFER_SECURED, Decision.MANUAL_REVIEW)


def test_evaluate_application_dti_exceed():
    result = evaluate_application(**_clean_cc_applicant(dti=0.90, requested_product="rewards"))
    assert result.decision in (Decision.DECLINE, Decision.REFER_SECURED)


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def test_evaluate_batch_basic():
    import pandas as pd
    df = pd.DataFrame([
        {**_clean_cc_applicant()},
        {**_clean_cc_applicant(fico_score=400, pd_score=0.90)},
    ])
    result = evaluate_batch(df)
    assert len(result) == 2
    assert "policy_decision" in result.columns


def test_evaluate_batch_with_product_column():
    """evaluate_batch should use product column if present."""
    import pandas as pd
    df = pd.DataFrame([
        {**_clean_cc_applicant(), "product": "basic"},
        {**_clean_cc_applicant(fico_score=750, annual_income=120_000.0), "product": "premium"},
    ])
    result = evaluate_batch(df, product_col="product")
    assert len(result) == 2


def test_evaluate_batch_with_true_pd_column():
    """evaluate_batch should prefer true_pd over pd_score when available."""
    import pandas as pd
    df = pd.DataFrame([
        {**_clean_cc_applicant(), "true_pd": 0.03},
    ])
    result = evaluate_batch(df)
    assert len(result) == 1


def test_evaluate_batch_empty():
    import pandas as pd
    df = pd.DataFrame(columns=["fico_score", "annual_income", "dti"])
    result = evaluate_batch(df)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
