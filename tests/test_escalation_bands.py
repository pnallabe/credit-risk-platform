"""Tests for config-driven escalation bands (S6-A Task 3)."""

from __future__ import annotations

import pytest

from decision_engine.engine import _load_escalation_bands, PD_THRESHOLD_LOW, PD_THRESHOLD_MEDIUM


class TestLoadEscalationBands:
    """Unit tests for _load_escalation_bands()."""

    def test_credit_card_band(self):
        lo, hi = _load_escalation_bands("credit_card")
        assert lo == 0.08
        assert hi == 0.12

    def test_personal_loan_band(self):
        lo, hi = _load_escalation_bands("personal_loan")
        assert lo == 0.07
        assert hi == 0.11

    def test_mortgage_band(self):
        lo, hi = _load_escalation_bands("mortgage")
        assert lo == 0.05
        assert hi == 0.09

    def test_smb_loan_band(self):
        lo, hi = _load_escalation_bands("smb_loan")
        assert lo == 0.10
        assert hi == 0.16

    def test_commercial_loan_band(self):
        lo, hi = _load_escalation_bands("commercial_loan")
        assert lo == 0.06
        assert hi == 0.10

    def test_unknown_product_falls_back_to_global_thresholds(self):
        lo, hi = _load_escalation_bands("unknown_product_xyz")
        assert lo == PD_THRESHOLD_LOW
        assert hi == PD_THRESHOLD_MEDIUM


class TestEscalationBandDecisions:
    """Integration: make_decision() uses per-product escalation bands."""

    def _make_request(self, pd_score: float):
        from decision_engine.engine import DecisionRequest, FraudResult, CreditResult
        from models.pricing.engine import PricingResult

        fraud = FraudResult(fraud_probability=0.0, fraud_flag="pass")
        credit = CreditResult(pd_score=pd_score, pd_band="Medium")
        pricing = PricingResult(recommended_rate=0.05, expected_loss=0.01, expected_profit=0.04,
                                profitability_flag=True, pd_score=pd_score, fraud_flag="pass",
                                loan_amount=10000.0)
        return DecisionRequest(
            application_id="TEST-001",
            fraud_result=fraud,
            credit_result=credit,
            pricing_result=pricing,
            loan_amount=10000.0,
            loan_term_months=36,
            debt_to_income_ratio=0.30,
            num_open_accounts=5,
        )

    def _decide(self, pd_score: float, product_type: str):
        from decision_engine.engine import make_decision
        req = self._make_request(pd_score)
        return make_decision(req, policy_overrides={"product_type": product_type},
                             override_submitted_by="tester", override_approved_by="approver",
                             override_justification="escalation band test", _simulation=True)

    def test_pd_below_band_approves(self):
        from decision_engine.engine import DECISION_APPROVE
        result = self._decide(0.03, "credit_card")
        assert result.decision == DECISION_APPROVE

    def test_pd_within_band_refers(self):
        from decision_engine.engine import DECISION_MANUAL_REVIEW
        # credit_card band: refer [0.08, 0.12]; pd=0.10 should MANUAL_REVIEW
        result = self._decide(0.10, "credit_card")
        assert result.decision == DECISION_MANUAL_REVIEW

    def test_pd_above_band_rejects(self):
        from decision_engine.engine import DECISION_REJECT
        # credit_card band: refer [0.08, 0.12]; pd=0.20 should REJECT
        result = self._decide(0.20, "credit_card")
        assert result.decision == DECISION_REJECT

    def test_smb_loan_wide_band(self):
        from decision_engine.engine import DECISION_MANUAL_REVIEW
        # smb_loan band: refer [0.10, 0.16]; pd=0.13 should MANUAL_REVIEW
        result = self._decide(0.13, "smb_loan")
        assert result.decision == DECISION_MANUAL_REVIEW

    def test_mortgage_low_band(self):
        from decision_engine.engine import DECISION_MANUAL_REVIEW
        # mortgage band: refer [0.05, 0.09]; pd=0.07 should MANUAL_REVIEW
        result = self._decide(0.07, "mortgage")
        assert result.decision == DECISION_MANUAL_REVIEW

    def test_commercial_below_band_approves(self):
        from decision_engine.engine import DECISION_APPROVE
        # commercial_loan band: refer [0.06, 0.10]; pd=0.04 should APPROVE
        result = self._decide(0.04, "commercial_loan")
        assert result.decision == DECISION_APPROVE
