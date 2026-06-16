"""Tests for conditional approval and engine conditions (S4-A)."""

from __future__ import annotations

import pytest

from decision_engine.engine import (
    DECISION_APPROVE,
    DECISION_CONDITIONAL,
    DECISION_REJECT,
    DecisionRequest,
    DecisionResult,
    make_decision,
    FraudResult,
    CreditResult,
)
from decision_engine.conditions import Condition


def _make_pricing():
    """Return a minimal PricingResult stub."""
    class _P:
        recommended_rate = 18.0
        expected_loss = 0.0
        expected_profit = 0.0
        profitability_flag = "profitable"
    return _P()


def _make_request(
    pd_score: float = 0.07,
    dti: float = 0.30,
    num_open: int = 5,
    income: float = 80_000.0,
    loan_amount: float = 10_000.0,
    income_verified: bool = True,
    collateral_value: float = 0.0,
    collateral_coverage_ratio: float = 0.0,
) -> DecisionRequest:
    req = DecisionRequest(
        application_id="TEST-001",
        fraud_result=FraudResult(fraud_probability=0.01, fraud_flag="continue"),
        credit_result=CreditResult(pd_score=pd_score, pd_band="medium"),
        pricing_result=_make_pricing(),
        loan_amount=loan_amount,
        loan_term_months=36,
        debt_to_income_ratio=dti,
        num_open_accounts=num_open,
        annual_income=income,
    )
    req.features = {
        "income_verified": income_verified,
        "collateral_value": collateral_value,
        "collateral_coverage_ratio": collateral_coverage_ratio,
    }
    return req


class TestConditionalApproval:
    def test_clean_application_is_approved(self):
        req = _make_request(pd_score=0.06)
        result = make_decision(req)
        assert result.decision == DECISION_APPROVE

    def test_income_unverified_triggers_conditional(self):
        req = _make_request(pd_score=0.08, income_verified=False)
        result = make_decision(req)
        assert result.decision == DECISION_CONDITIONAL
        cond_types = [c.condition_type for c in result.conditions]
        assert "INCOME_VERIFICATION_REQUIRED" in cond_types

    def test_elevated_dti_triggers_conditional(self):
        req = _make_request(pd_score=0.09, dti=0.46)
        result = make_decision(req)
        assert result.decision == DECISION_CONDITIONAL
        cond_types = [c.condition_type for c in result.conditions]
        assert "REDUCED_LIMIT" in cond_types

    def test_thin_file_triggers_conditional(self):
        req = _make_request(pd_score=0.08, num_open=2)
        result = make_decision(req)
        assert result.decision == DECISION_CONDITIONAL
        cond_types = [c.condition_type for c in result.conditions]
        assert "ADDITIONAL_DOCUMENTATION" in cond_types

    def test_collateral_shortfall_triggers_conditional(self):
        req = _make_request(
            pd_score=0.09,
            collateral_value=5000.0,
            collateral_coverage_ratio=0.5,
        )
        result = make_decision(req)
        assert result.decision == DECISION_CONDITIONAL
        cond_types = [c.condition_type for c in result.conditions]
        assert "COLLATERAL_REQUIRED" in cond_types

    def test_high_pd_still_rejects(self):
        req = _make_request(pd_score=0.25)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT

    def test_fraud_reject_overrides_conditional(self):
        req = _make_request(pd_score=0.08, income_verified=False)
        req.fraud_result = FraudResult(fraud_probability=0.9, fraud_flag="reject")
        result = make_decision(req)
        assert result.decision == DECISION_REJECT

    def test_multiple_conditions_collected(self):
        req = _make_request(
            pd_score=0.09,
            dti=0.46,
            num_open=2,
            income_verified=False,
        )
        result = make_decision(req)
        assert result.decision == DECISION_CONDITIONAL
        assert len(result.conditions) >= 2

    def test_conditions_are_condition_objects(self):
        req = _make_request(pd_score=0.08, income_verified=False)
        result = make_decision(req)
        for cond in result.conditions:
            assert isinstance(cond, Condition)
