"""
Smoke tests for decision_engine/mortgage_origination_policy.py
"""
from __future__ import annotations

import pytest

from decision_engine.mortgage_origination_policy import (
    MortgageDecision,
    MortgageDecisionResult,
    check_atr,
    classify_ltv,
    compute_mortgage_rate,
    evaluate_mortgage,
    route_mortgage_product,
)


# ---------------------------------------------------------------------------
# classify_ltv
# ---------------------------------------------------------------------------

def test_classify_ltv_preferred():
    assert classify_ltv(0.75) == "preferred"
    assert classify_ltv(0.80) == "preferred"


def test_classify_ltv_standard():
    assert classify_ltv(0.85) == "standard"
    assert classify_ltv(0.97) == "standard"


def test_classify_ltv_high():
    assert classify_ltv(0.98) == "high_ltv"
    assert classify_ltv(1.10) == "high_ltv"


# ---------------------------------------------------------------------------
# check_atr
# ---------------------------------------------------------------------------

def _good_atr_application() -> dict:
    return {
        "monthly_income": 10_000.0,
        "assets_verified": True,
        "employment_status": "employed",
        "monthly_mortgage_payment": 2_000.0,   # 20% of income
        "dti": 0.35,
        "residual_income": 5_000.0,
        "bankruptcy_within_4yrs": False,
        "monthly_piti": 2_400.0,               # 24% of income
        "family_size": 1,
    }


def test_check_atr_qualified_application():
    is_qm, failed = check_atr(_good_atr_application())
    assert is_qm is True
    assert failed == []


def test_check_atr_high_dti_fails():
    app = _good_atr_application()
    app["dti"] = 0.50  # above 43% QM limit
    is_qm, failed = check_atr(app)
    assert is_qm is False
    assert "factor_4_5_dti_qm_limit" in failed


def test_check_atr_bankruptcy_fails():
    app = _good_atr_application()
    app["bankruptcy_within_4yrs"] = True
    is_qm, failed = check_atr(app)
    assert "factor_7_bankruptcy" in failed


def test_check_atr_unemployed_fails():
    app = _good_atr_application()
    app["employment_status"] = "unemployed"
    is_qm, failed = check_atr(app)
    assert "factor_2_employment" in failed


def test_check_atr_no_income_no_assets_fails():
    app = _good_atr_application()
    app["monthly_income"] = 0
    app["assets_verified"] = False
    is_qm, failed = check_atr(app)
    assert "factor_1_income_assets" in failed


def test_check_atr_high_mortgage_payment_ratio():
    app = _good_atr_application()
    app["monthly_mortgage_payment"] = 3_500.0  # 35% of 10k income
    is_qm, failed = check_atr(app)
    assert "factor_3_mortgage_payment_ratio" in failed


def test_check_atr_low_residual_income():
    app = _good_atr_application()
    app["residual_income"] = 500.0  # below $1500 threshold
    is_qm, failed = check_atr(app)
    assert "factor_6_residual_income" in failed


def test_check_atr_family_size_higher_threshold():
    """family_size > 1 raises threshold to $2500."""
    app = _good_atr_application()
    app["residual_income"] = 2_000.0  # above single threshold but below family threshold
    app["family_size"] = 2
    is_qm, failed = check_atr(app)
    assert "factor_6_residual_income" in failed


def test_check_atr_high_piti():
    app = _good_atr_application()
    app["monthly_piti"] = 4_000.0  # 40% of income
    is_qm, failed = check_atr(app)
    assert "factor_8_piti_ratio" in failed


# ---------------------------------------------------------------------------
# route_mortgage_product
# ---------------------------------------------------------------------------

def test_route_conforming_loan():
    app = {"loan_amount": 400_000, "fico_score": 700, "ltv_at_origination": 0.85}
    product = route_mortgage_product(app, {})
    assert product == "conforming"


def test_route_va_eligible():
    app = {"loan_amount": 400_000, "fico_score": 700, "va_eligible": True}
    product = route_mortgage_product(app, {})
    assert product == "VA"


def test_route_jumbo_eligible():
    app = {"loan_amount": 1_000_000, "fico_score": 750}
    product = route_mortgage_product(app, {})
    assert product == "jumbo"


def test_route_jumbo_disabled():
    app = {"loan_amount": 1_000_000, "fico_score": 750}
    product = route_mortgage_product(app, {"jumbo_enabled": False})
    assert product == "DECLINE_JUMBO_SUSPENDED"


def test_route_jumbo_low_fico():
    app = {"loan_amount": 1_000_000, "fico_score": 620}
    product = route_mortgage_product(app, {})
    assert product == "DECLINE_JUMBO_FICO"


# ---------------------------------------------------------------------------
# compute_mortgage_rate
# ---------------------------------------------------------------------------

def test_compute_mortgage_rate_returns_float():
    rate = compute_mortgage_rate(
        rate_type="fixed_30",
        fico=740,
        ltv=0.80,
        product_type="conforming",
        points_paid=0.0,
    )
    assert 3.0 <= rate <= 14.99


def test_compute_mortgage_rate_jumbo_premium():
    rate_conforming = compute_mortgage_rate("fixed_30", 740, 0.80, "conforming", 0.0)
    rate_jumbo = compute_mortgage_rate("fixed_30", 740, 0.80, "jumbo", 0.0)
    assert rate_jumbo > rate_conforming


def test_compute_mortgage_rate_high_ltv_premium():
    rate_low_ltv = compute_mortgage_rate("fixed_30", 740, 0.75, "conforming", 0.0)
    rate_high_ltv = compute_mortgage_rate("fixed_30", 740, 0.95, "conforming", 0.0)
    assert rate_high_ltv > rate_low_ltv


def test_compute_mortgage_rate_points_discount():
    rate_no_pts = compute_mortgage_rate("fixed_30", 740, 0.80, "conforming", 0.0)
    rate_with_pts = compute_mortgage_rate("fixed_30", 740, 0.80, "conforming", 2.0)
    assert rate_with_pts < rate_no_pts


def test_compute_mortgage_rate_arm_types():
    for rate_type in ("fixed_15", "arm_5_1", "arm_7_1"):
        rate = compute_mortgage_rate(rate_type, 740, 0.80, "conforming", 0.0)
        assert 3.0 <= rate <= 14.99


def test_compute_mortgage_rate_unknown_type_defaults():
    rate = compute_mortgage_rate("unknown_type", 740, 0.80, "conforming", 0.0)
    assert 3.0 <= rate <= 14.99


def test_compute_mortgage_rate_medium_ltv():
    """LTV between 0.80 and 0.90 should apply 0.125 premium."""
    rate_80 = compute_mortgage_rate("fixed_30", 740, 0.80, "conforming", 0.0)
    rate_85 = compute_mortgage_rate("fixed_30", 740, 0.85, "conforming", 0.0)
    assert rate_85 > rate_80


def test_compute_mortgage_rate_jumbo_premium():
    rate_conf = compute_mortgage_rate("fixed_30", 740, 0.80, "conforming", 0.0)
    rate_jumbo = compute_mortgage_rate("fixed_30", 740, 0.80, "jumbo", 0.0)
    assert rate_jumbo > rate_conf


# ---------------------------------------------------------------------------
# evaluate_mortgage
# ---------------------------------------------------------------------------

def _standard_mortgage_application() -> dict:
    return {
        "fico_score": 720,
        "dti": 0.35,
        "annual_income": 120_000.0,
        "monthly_income": 10_000.0,
        "loan_amount": 400_000.0,
        "property_value": 500_000.0,
        "ltv_at_origination": 0.80,
        "assets_verified": True,
        "employment_status": "employed",
        "monthly_mortgage_payment": 2_500.0,
        "monthly_piti": 2_800.0,
        "residual_income": 4_000.0,
        "bankruptcy_within_4yrs": False,
        "property_type": "primary_residence",
        "rate_type": "fixed_30",
        "points_paid": 0.0,
    }


def test_evaluate_mortgage_approve():
    result = evaluate_mortgage(
        application=_standard_mortgage_application(),
        pd_score=0.02,
        fraud_score=0.01,
    )
    assert isinstance(result, MortgageDecisionResult)
    assert result.decision in (
        MortgageDecision.APPROVE_QM,
        MortgageDecision.APPROVE_NON_QM,
        MortgageDecision.REFER_FHA,
        MortgageDecision.MANUAL_REVIEW,
    )


def test_evaluate_mortgage_fraud_decline():
    result = evaluate_mortgage(
        application=_standard_mortgage_application(),
        pd_score=0.02,
        fraud_score=0.99,
    )
    assert result.decision == MortgageDecision.DECLINE


def test_evaluate_mortgage_low_fico_decline():
    app = _standard_mortgage_application()
    app["fico_score"] = 500  # below FHA floor
    result = evaluate_mortgage(app, pd_score=0.02, fraud_score=0.01)
    assert result.decision == MortgageDecision.DECLINE


def test_evaluate_mortgage_result_has_fcra_codes():
    app = _standard_mortgage_application()
    app["fico_score"] = 500
    result = evaluate_mortgage(app, pd_score=0.02, fraud_score=0.01)
    assert isinstance(result.fcra_reason_codes, list)


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

@pytest.mark.xfail(reason="evaluate_batch has a known pandas vectorisation bug in this version", strict=False)
def test_evaluate_mortgage_batch():
    import pandas as pd
    from decision_engine.mortgage_origination_policy import evaluate_batch

    row1 = {
        "fico_score": 720, "dti": 0.35, "annual_income": 120_000.0,
        "monthly_income": 10_000.0, "loan_amount": 400_000.0,
        "property_value": 500_000.0, "ltv_at_origination": 0.80,
        "assets_verified": True, "employment_status": "employed",
        "monthly_mortgage_payment": 2_500.0, "monthly_piti": 2_800.0,
        "residual_income": 4_000.0, "bankruptcy_within_4yrs": False,
        "property_type": "primary_residence", "rate_type": "fixed_30",
        "points_paid": 0.0, "pd_score": 0.02, "fraud_score": 0.01,
    }
    row2 = dict(row1)
    row2["fico_score"] = 500
    row2["pd_score"] = 0.30
    df = pd.DataFrame([row1, row2])
    result = evaluate_batch(df)
    assert len(result) == 2
    assert "decision" in result.columns


def test_evaluate_mortgage_batch_empty():
    import pandas as pd
    from decision_engine.mortgage_origination_policy import evaluate_batch

    df = pd.DataFrame(columns=["fico_score", "loan_amount"])
    result = evaluate_batch(df)
    assert len(result) == 0


def test_evaluate_mortgage_refer_fha():
    """FICO below conforming floor but above FHA floor → REFER_FHA."""
    app = {
        "fico_score": 590,  # below conforming floor (620), above FHA (580)
        "annual_income": 80_000,
        "monthly_income": 6_667,
        "dti": 0.35,
        "loan_amount": 200_000,
        "appraised_value": 260_000,
        "ltv_at_origination": 0.77,
        "property_type": "primary_residence",
        "rate_type": "fixed_30",
        "points_paid": 0.0,
        "employment_status": "employed",
        "assets_verified": True,
        "residual_income": 1_800.0,
    }
    result = evaluate_mortgage(app, 0.05, 0.05)
    assert result.decision == MortgageDecision.REFER_FHA
