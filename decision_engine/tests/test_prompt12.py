import pytest
from decision_engine.alternative_structures import compute_alternatives, AlternativeStructure
from decision_engine.engine import DecisionResult

class MockRequest:
    def __init__(self, loan_amount, dti, annual_income, loan_term_months=36, employment_status="employed", features=None):
        self.loan_amount = loan_amount
        self.debt_to_income_ratio = dti
        self.annual_income = annual_income
        self.loan_term_months = loan_term_months
        self.employment_status = employment_status
        self.features = features or {}

def test_approve_no_alternatives():
    req = MockRequest(loan_amount=25000, dti=0.30, annual_income=100000)
    decision = DecisionResult(
        application_id="123",
        decision="APPROVE",
        recommended_rate=5.0,
        loan_terms={},
        reason_codes=[],
        decision_timestamp=None,
        decision_latency_ms=0,
        override_records=[],
    )
    alts = compute_alternatives(req, decision, {"pd_threshold": 0.10, "dti_limit": 0.43})
    assert len(alts) == 0

def test_decline_reduced_amount():
    req = MockRequest(loan_amount=25000, dti=0.52, annual_income=100000)
    decision = DecisionResult(
        application_id="123",
        decision="REJECT",
        recommended_rate=None,
        loan_terms={},
        reason_codes=[],
        decision_timestamp=None,
        decision_latency_ms=0,
        override_records=[],
    )
    # Give a pd_score just under threshold so it passes PD check easily when reduced
    decision.pd_score = 0.09

    alts = compute_alternatives(req, decision, {"pd_threshold": 0.10, "dti_limit": 0.43})

    reduced_alt = next((a for a in alts if a.structure_type == "reduced_amount"), None)
    assert reduced_alt is not None
    # Verify we extract a number roughly <= 20000
    assert "Approval likely at $" in reduced_alt.description
    assert reduced_alt.adjusted_dti < 0.43

def test_decline_no_feasible_alternatives():
    # Very high DTI so even 40% reduction won't get it under 0.43
    req = MockRequest(loan_amount=25000, dti=0.95, annual_income=100000)
    decision = DecisionResult(
        application_id="123",
        decision="REJECT",
        recommended_rate=None,
        loan_terms={},
        reason_codes=[],
        decision_timestamp=None,
        decision_latency_ms=0,
        override_records=[],
    )
    decision.pd_score = 0.09

    alts = compute_alternatives(req, decision, {"pd_threshold": 0.10, "dti_limit": 0.43})
    reduced_alt = next((a for a in alts if a.structure_type == "reduced_amount"), None)
    assert reduced_alt is None

def test_alternatives_sorted_by_feasibility():
    req = MockRequest(loan_amount=25000, dti=0.52, annual_income=100000, employment_status="unemployed")
    decision = DecisionResult(
        application_id="123",
        decision="REJECT",
        recommended_rate=None,
        loan_terms={},
        reason_codes=[],
        decision_timestamp=None,
        decision_latency_ms=0,
        override_records=[],
    )
    decision.pd_score = 0.09
    alts = compute_alternatives(req, decision, {"pd_threshold": 0.10, "dti_limit": 0.43})

    # Check order: High -> Medium -> Low
    order = {"High": 0, "Medium": 1, "Low": 2}
    for i in range(len(alts) - 1):
        assert order[alts[i].feasibility] <= order[alts[i+1].feasibility]
