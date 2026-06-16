"""
Smoke tests for decision_engine/personal_loan_origination_policy.py
"""
from __future__ import annotations

import pytest

from decision_engine.personal_loan_origination_policy import (
    PLDecision,
    PLDecisionResult,
    compute_pl_rate,
    evaluate_personal_loan,
)


def _clean_pl_application() -> dict:
    return {
        "fico_score": 720,
        "annual_income": 100_000.0,
        "monthly_income": 8_333.0,
        "employment_status": "employed",
        "employer_tenure_months": 24,
        "loan_amount": 10_000.0,
        "loan_term_months": 36,
        "dti": 0.25,
        "state": "CA",
    }


# ---------------------------------------------------------------------------
# compute_pl_rate
# ---------------------------------------------------------------------------

def test_compute_pl_rate_returns_float():
    rate = compute_pl_rate(fico=720, dti=0.25, term_months=36, purpose="debt_consolidation")
    assert isinstance(rate, float)
    assert 5.0 <= rate <= 36.0


def test_compute_pl_rate_higher_fico_lower_rate():
    r_low = compute_pl_rate(fico=620, dti=0.30, term_months=36, purpose="debt_consolidation")
    r_high = compute_pl_rate(fico=780, dti=0.20, term_months=36, purpose="debt_consolidation")
    assert r_high < r_low


# ---------------------------------------------------------------------------
# evaluate_personal_loan
# ---------------------------------------------------------------------------

def test_pl_clean_application_approved():
    result = evaluate_personal_loan(
        application=_clean_pl_application(),
        pd_score=0.02,
        fraud_score=0.01,
    )
    assert isinstance(result, PLDecisionResult)
    assert result.decision in (PLDecision.APPROVE, PLDecision.COUNTER_OFFER)


def test_pl_high_fraud_declines():
    result = evaluate_personal_loan(
        application=_clean_pl_application(),
        pd_score=0.02,
        fraud_score=0.95,
    )
    assert result.decision == PLDecision.DECLINE


def test_pl_high_pd_declines():
    result = evaluate_personal_loan(
        application=_clean_pl_application(),
        pd_score=0.90,
        fraud_score=0.01,
    )
    assert result.decision in (PLDecision.DECLINE, PLDecision.MANUAL_REVIEW)


def test_pl_result_approved_has_rate():
    app = _clean_pl_application()
    result = evaluate_personal_loan(app, pd_score=0.02, fraud_score=0.01)
    if result.decision == PLDecision.APPROVE:
        assert result.approved_rate is not None
        assert result.approved_rate > 0


def test_pl_result_has_fcra_codes_on_decline():
    app = _clean_pl_application()
    app["fico_score"] = 400  # very low
    result = evaluate_personal_loan(app, pd_score=0.80, fraud_score=0.01)
    if result.decision == PLDecision.DECLINE:
        assert isinstance(result.fcra_reason_codes, list)


# ---------------------------------------------------------------------------
# evaluate_batch
# ---------------------------------------------------------------------------

def test_pl_evaluate_batch():
    import pandas as pd
    from decision_engine.personal_loan_origination_policy import evaluate_batch

    df = pd.DataFrame([
        {"fico_score": 720, "annual_income": 80_000, "dti": 0.25,
         "num_derog_marks": 0, "employment_status": "employed",
         "requested_amount": 10_000, "term_months": 36,
         "loan_purpose": "debt_consolidation", "pd_score": 0.03, "fraud_score": 0.01},
        {"fico_score": 500, "annual_income": 20_000, "dti": 0.55,
         "num_derog_marks": 0, "employment_status": "employed",
         "requested_amount": 50_000, "term_months": 60,
         "loan_purpose": "other", "pd_score": 0.50, "fraud_score": 0.01},
    ])
    result = evaluate_batch(df)
    assert len(result) == 2
    assert "decision_outcome" in result.columns
    assert result["decision_outcome"].notna().all()


def test_pl_evaluate_batch_empty():
    import pandas as pd
    from decision_engine.personal_loan_origination_policy import evaluate_batch

    df = pd.DataFrame(columns=["fico_score", "annual_income"])
    result = evaluate_batch(df)
    assert len(result) == 0
