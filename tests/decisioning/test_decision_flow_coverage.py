"""
tests/decisioning/test_decision_flow_coverage.py
==================================================
End-to-end decision path coverage validating automatic vs. HITL routing.
Each test documents the exact condition and expected outcome.

Decision tree under test (decision_engine/engine.py):
  1. fraud_flag == "reject"         → REJECT        (AA02)
  2. fraud_flag == "manual_review"  → MANUAL_REVIEW (AA05)
  3. pd_score < 0.05                → APPROVE        (base rate)
  4. 0.05 ≤ pd_score ≤ 0.10        → APPROVE        (risk-priced rate)
  5. pd_score > 0.10                → REJECT         (AA01)

Fraud probability thresholds (models/fraud_detection/predict.py):
  THRESHOLD_REJECT = 0.60   → fraud_flag = "reject"
  THRESHOLD_REVIEW = 0.30   → fraud_flag = "manual_review"
  < 0.30                    → fraud_flag = "continue"

PD thresholds (decision_engine/engine.py):
  PD_THRESHOLD_LOW    = 0.05
  PD_THRESHOLD_MEDIUM = 0.10
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from models.pricing.engine import PricingConfig, calculate_pricing
from decision_engine.engine import (
    DECISION_APPROVE,
    DECISION_REJECT,
    DECISION_MANUAL_REVIEW,
    CreditResult,
    DecisionRequest,
    FraudResult,
    make_decision,
    PD_THRESHOLD_LOW,
    PD_THRESHOLD_MEDIUM,
)
from decisioning.review_queue import ReviewQueue

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_CFG = PricingConfig()


def _pricing(pd_score: float, fraud_flag: str = "continue"):
    return calculate_pricing(
        pd_score=pd_score, fraud_flag=fraud_flag, loan_amount=15_000.0, config=_CFG
    )


def _make_request(
    fraud_flag: str,
    pd_score: float,
    dti: float = 0.30,
    open_accounts: int = 3,
) -> DecisionRequest:
    return DecisionRequest(
        application_id="test-flow-001",
        fraud_result=FraudResult(fraud_probability=0.0, fraud_flag=fraud_flag),
        credit_result=CreditResult(pd_score=pd_score, pd_band="low"),
        pricing_result=_pricing(pd_score=pd_score, fraud_flag=fraud_flag),
        loan_amount=15_000.0,
        loan_term_months=36,
        debt_to_income_ratio=dti,
        num_open_accounts=open_accounts,
        annual_income=60_000.0,
    )


# ---------------------------------------------------------------------------
# TestAutomaticDecisions — every branch that never touches the review queue
# ---------------------------------------------------------------------------

class TestAutomaticDecisions:
    """All automatic (no-human) decision paths."""

    def test_fraud_reject_is_automatic(self):
        """fraud_flag='reject' → DECISION_REJECT + AA02.
        Source: engine.py line 370 (fraud_flag == 'reject' → DECISION_REJECT).
        Fraud model threshold: fraud_probability > THRESHOLD_REJECT (0.60).
        """
        req = _make_request(fraud_flag="reject", pd_score=0.03)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA02" in result.reason_codes
        assert result.loan_terms == {}
        assert result.recommended_rate is None

    def test_fraud_reject_has_no_loan_terms(self):
        """Rejected decisions never expose offer terms."""
        req = _make_request(fraud_flag="reject", pd_score=0.03)
        result = make_decision(req)
        assert result.loan_terms == {}

    def test_low_pd_approve_is_automatic(self):
        """pd_score < PD_THRESHOLD_LOW (0.05) + continue → APPROVE at base rate.
        Source: engine.py lines 376-379 (pd_score < _pd_low → DECISION_APPROVE).
        """
        req = _make_request(fraud_flag="continue", pd_score=0.03)
        result = make_decision(req)
        assert result.decision == DECISION_APPROVE
        assert result.reason_codes == []
        assert result.recommended_rate is not None

    def test_medium_pd_approve_is_automatic(self):
        """0.05 ≤ pd_score ≤ 0.10 + continue → APPROVE at risk-priced rate.
        Source: engine.py lines 379-382 (pd_score ≤ _pd_medium → DECISION_APPROVE).
        """
        req = _make_request(fraud_flag="continue", pd_score=0.07)
        result = make_decision(req)
        assert result.decision == DECISION_APPROVE
        assert result.reason_codes == []

    def test_medium_pd_boundary_upper_approves(self):
        """pd_score == PD_THRESHOLD_MEDIUM (0.10) exactly → APPROVE (≤, inclusive).
        Boundary condition test.
        """
        req = _make_request(fraud_flag="continue", pd_score=PD_THRESHOLD_MEDIUM)
        result = make_decision(req)
        assert result.decision == DECISION_APPROVE

    def test_high_pd_reject_is_automatic(self):
        """pd_score > PD_THRESHOLD_MEDIUM (0.10) + continue → REJECT (AA01).
        Source: engine.py line 382 (else → DECISION_REJECT).
        """
        req = _make_request(fraud_flag="continue", pd_score=0.15)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA01" in result.reason_codes

    def test_high_pd_reject_boundary(self):
        """pd_score just above 0.10 (0.1001) → REJECT.
        Boundary condition test.
        """
        req = _make_request(fraud_flag="continue", pd_score=0.1001)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA01" in result.reason_codes

    def test_fraud_reject_overrides_low_pd(self):
        """fraud_flag='reject' takes precedence over even a very low pd_score.
        Decision tree checks fraud gate first (engine.py line 370).
        """
        req = _make_request(fraud_flag="reject", pd_score=0.001)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA02" in result.reason_codes

    def test_supplemental_aa03_insufficient_history(self):
        """REJECT + open_accounts < 1 → AA01 + AA03.
        Source: engine.py _collect_reason_codes(), OPEN_ACCOUNTS_MIN = 1.
        """
        req = _make_request(fraud_flag="continue", pd_score=0.15, open_accounts=0)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA01" in result.reason_codes
        assert "AA03" in result.reason_codes

    def test_supplemental_aa04_high_dti(self):
        """REJECT + DTI > 0.43 → AA01 + AA04.
        Source: engine.py _collect_reason_codes(), DTI_HIGH_THRESHOLD = 0.43.
        """
        req = _make_request(fraud_flag="continue", pd_score=0.15, dti=0.50)
        result = make_decision(req)
        assert result.decision == DECISION_REJECT
        assert "AA01" in result.reason_codes
        assert "AA04" in result.reason_codes

    def test_approve_has_no_supplemental_codes(self):
        """APPROVE never emits reason codes (no adverse action needed)."""
        req = _make_request(fraud_flag="continue", pd_score=0.03, dti=0.50, open_accounts=0)
        result = make_decision(req)
        assert result.decision == DECISION_APPROVE
        assert result.reason_codes == []  # adverse action exempt


# ---------------------------------------------------------------------------
# TestHITLRouting — every path that triggers the review queue
# ---------------------------------------------------------------------------

class TestHITLRouting:
    """MANUAL_REVIEW routing: queue is populated, SLA clock starts."""

    def test_fraud_manual_review_is_non_automatic(self):
        """fraud_flag='manual_review' → DECISION_MANUAL_REVIEW + AA05.
        Source: engine.py line 373 (fraud_flag == 'manual_review' → DECISION_MANUAL_REVIEW).
        Fraud model threshold: 0.30 ≤ fraud_probability ≤ 0.60.
        """
        req = _make_request(fraud_flag="manual_review", pd_score=0.06)
        result = make_decision(req)
        assert result.decision == DECISION_MANUAL_REVIEW
        assert "AA05" in result.reason_codes
        assert result.loan_terms == {}

    def test_fraud_manual_review_routes_to_queue(self):
        """MANUAL_REVIEW outcome → ReviewQueue.enqueue() is called exactly once.
        Verifies the wiring between engine outcome and HITL queue (H-09 control).
        """
        from decision_engine.cc_origination_policy import configure_review_queue

        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        configure_review_queue(queue)

        # Use cc_origination_policy to trigger queue enqueue path
        from decision_engine.cc_origination_policy import evaluate_application, PRODUCT_POLICIES

        policy = PRODUCT_POLICIES["rewards"]
        # pd_score between pd_manual_review (0.10) and pd_hard_decline (0.18)
        result = evaluate_application(
            account_id=999,
            fico_score=700,
            annual_income=50_000,
            dti=0.35,
            num_bankruptcy=0,
            num_derog_marks=1,
            inq_last_6m=2,
            age=30,
            employment_status="employed",
            pct_rev_utilization=0.40,
            pd_score=0.12,
            requested_product="rewards",
        )

        from decision_engine.cc_origination_policy import Decision
        assert result.decision == Decision.MANUAL_REVIEW

        pending = queue.get_pending()
        assert len(pending) == 1
        assert pending[0].application_id == "999"

        # Reset queue to avoid test pollution
        configure_review_queue(None)  # type: ignore[arg-type]

    def test_queue_enqueue_creates_pending_item(self):
        """Direct ReviewQueue.enqueue() creates item with PENDING status and SLA clock."""
        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        item = queue.enqueue(
            application_id="app-queue-test",
            pd_score=0.08,
            features={"dti": 0.35, "open_accounts": 3},
            sla_hours=24,
        )
        assert item.status == "PENDING"
        assert item.application_id == "app-queue-test"
        assert item.override_decision is None
        assert item.assigned_to is None
        # SLA deadline should be ~24 h from now
        delta = item.sla_deadline - item.created_at
        assert 23 * 3600 < delta.total_seconds() < 25 * 3600

    def test_queue_assign_transitions_to_under_review(self):
        """assign() transitions PENDING → UNDER_REVIEW and records analyst email."""
        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        item = queue.enqueue("app-assign", pd_score=0.09, features={})
        updated = queue.assign(item.item_id, "analyst@example.com")
        assert updated.status == "UNDER_REVIEW"
        assert updated.assigned_to == "analyst@example.com"
        assert updated.review_started_at is not None

    def test_queue_complete_transitions_to_completed(self):
        """complete() transitions UNDER_REVIEW → COMPLETED and records override."""
        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        item = queue.enqueue("app-complete", pd_score=0.09, features={})
        queue.assign(item.item_id, "analyst@example.com")
        finished = queue.complete(
            item.item_id,
            override_decision="APPROVE",
            override_reason_code="POLICY_EXCEPTION",
            notes="Income verified via payslip",
        )
        assert finished.status == "COMPLETED"
        assert finished.override_decision == "APPROVE"
        assert finished.override_reason_code == "POLICY_EXCEPTION"
        assert finished.completed_at is not None

    def test_sla_breach_detected(self):
        """Items with expired sla_deadline are detected by check_sla_breaches().
        Uses sla_hours=0 to guarantee immediate breach.
        Source: decisioning/review_queue.py ReviewQueue.check_sla_breaches().
        """
        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        item = queue.enqueue("app-sla", pd_score=0.08, features={}, sla_hours=0)
        # Sleep briefly to ensure clock advances past deadline
        time.sleep(0.05)
        breached = queue.check_sla_breaches()
        assert any(i.item_id == item.item_id for i in breached)
        # Verify status persisted
        pending = queue.get_pending()
        assert all(i.item_id != item.item_id for i in pending)

    def test_complete_rejects_invalid_override_decision(self):
        """complete() rejects override_decision values not in {APPROVE, DECLINE, REFER_TO_SENIOR}.
        Source: review_queue.py line 184.
        """
        queue = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
        item = queue.enqueue("app-invalid", pd_score=0.09, features={})
        queue.assign(item.item_id, "analyst@example.com")
        with pytest.raises(ValueError, match="override_decision must be one of"):
            queue.complete(item.item_id, override_decision="REJECT", override_reason_code="OTHER")


# ---------------------------------------------------------------------------
# TestFraudThresholds — document exact threshold values from predict.py
# ---------------------------------------------------------------------------

class TestFraudThresholds:
    """Verify fraud threshold constants align with documented values."""

    def test_fraud_thresholds_documented_values(self):
        """Verify THRESHOLD_REJECT=0.60 and THRESHOLD_REVIEW=0.30 (predict.py lines 32-33)."""
        from models.fraud_detection.predict import THRESHOLD_REJECT, THRESHOLD_REVIEW
        assert THRESHOLD_REJECT == 0.60, (
            f"Expected THRESHOLD_REJECT=0.60, got {THRESHOLD_REJECT}. "
            "Update docs/DECISION_ROUTING_SUMMARY.md if changed."
        )
        assert THRESHOLD_REVIEW == 0.30, (
            f"Expected THRESHOLD_REVIEW=0.30, got {THRESHOLD_REVIEW}. "
            "Update docs/DECISION_ROUTING_SUMMARY.md if changed."
        )

    def test_pd_thresholds_documented_values(self):
        """Verify PD_THRESHOLD_LOW=0.05 and PD_THRESHOLD_MEDIUM=0.10 (engine.py lines 60-61)."""
        assert PD_THRESHOLD_LOW == 0.05
        assert PD_THRESHOLD_MEDIUM == 0.10
