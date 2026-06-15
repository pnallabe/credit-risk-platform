import pytest
from datetime import datetime, timezone

from decision_engine.engine import (
    make_decision,
    DecisionRequest,
    FraudResult,
    CreditResult,
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_CONDITIONAL_APPROVE,
)
from models.pricing.engine import PricingResult

def get_base_request(pd_score: float, dti: float = 0.3) -> DecisionRequest:
    return DecisionRequest(
        application_id="TEST-11",
        fraud_result=FraudResult(fraud_probability=0.01, fraud_flag="continue"),
        credit_result=CreditResult(pd_score=pd_score, pd_band="low"),
        pricing_result=PricingResult(
            recommended_rate=5.5,
            expected_loss=100.0,
            expected_profit=500.0,
            profitability_flag="PROFITABLE",
        ),
        loan_amount=10000.0,
        loan_term_months=36,
        debt_to_income_ratio=dti,
        num_open_accounts=5,
        annual_income=100000.0,
    )

def test_conditional_approval():
    # PD = 0.08, DTI = 0.48 -> CONDITIONAL_APPROVE
    req = get_base_request(pd_score=0.08, dti=0.48)
    res = make_decision(req)
    assert res.decision == DECISION_CONDITIONAL_APPROVE
    assert res.conditional_approval is not None
    assert len(res.conditional_approval.conditions) == 1
    assert res.conditional_approval.conditions[0].code == "INCOME_VERIFY"

def test_approve_low_pd():
    # PD = 0.04 -> APPROVE
    req = get_base_request(pd_score=0.04, dti=0.48)
    res = make_decision(req)
    assert res.decision == DECISION_APPROVE
    assert res.conditional_approval is None

def test_reject_high_pd():
    # PD = 0.15 -> DECLINE
    req = get_base_request(pd_score=0.15, dti=0.48)
    res = make_decision(req)
    assert res.decision == DECISION_REJECT
    assert res.conditional_approval is None

def test_adverse_action_not_generated_for_conditional_approve():
    req = get_base_request(pd_score=0.08, dti=0.48)
    res = make_decision(req)

    from compliance.adverse_action_generator import generate_notice
    with pytest.raises(ValueError, match="decision must be REJECT"):
        generate_notice(
            application_id="TEST-11",
            tenant_id="tenant_1",
            decision_result=res,
            explanation_result=None,
            tenant_config={}
        )
