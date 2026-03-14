"""Decision Engine — unit tests.

Covers all decision branches:
  - Fraud reject → REJECT + AA02
  - Fraud manual_review → MANUAL_REVIEW + AA05
  - Low PD score (<0.05) → APPROVE (base rate)
  - Medium PD score (0.05–0.10) → APPROVE (priced rate)
  - High PD score (>0.10) → REJECT + AA01
  - Supplemental codes: AA03 (no open accounts), AA04 (high DTI)
  - Utility: monthly payment calculation
  - Latency: decision_latency_ms is a non-negative integer
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))

from models.pricing.engine import PricingConfig, PricingResult, calculate_pricing
from decision_engine.engine import (
    DECISION_APPROVE,
    DECISION_MANUAL_REVIEW,
    DECISION_REJECT,
    CreditResult,
    DecisionRequest,
    DecisionResult,
    FraudResult,
    make_decision,
    _monthly_payment,
    REASON_CODE_DESCRIPTIONS,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CFG = PricingConfig()


def _pricing(pd_score: float, fraud_flag: str = "continue", loan_amount: float = 20_000.0) -> PricingResult:
    """Helper to generate a PricingResult for a given pd_score."""
    return calculate_pricing(pd_score=pd_score, fraud_flag=fraud_flag,
                             loan_amount=loan_amount, config=_CFG)


def _make_request(
    fraud_flag: str = "continue",
    fraud_prob: float = 0.1,
    pd_score: float = 0.03,
    pd_band: str = "low",
    loan_amount: float = 20_000.0,
    loan_term_months: int = 36,
    dti: float = 0.25,
    open_accounts: int = 5,
    annual_income: float = 60_000.0,
) -> DecisionRequest:
    """Factory that builds a DecisionRequest with sensible defaults."""
    pricing = _pricing(pd_score=pd_score, fraud_flag=fraud_flag, loan_amount=loan_amount)
    return DecisionRequest(
        application_id="test-app-001",
        fraud_result=FraudResult(fraud_probability=fraud_prob, fraud_flag=fraud_flag),
        credit_result=CreditResult(pd_score=pd_score, pd_band=pd_band),
        pricing_result=pricing,
        loan_amount=loan_amount,
        loan_term_months=loan_term_months,
        debt_to_income_ratio=dti,
        num_open_accounts=open_accounts,
        annual_income=annual_income,
    )


# ---------------------------------------------------------------------------
# Branch: fraud reject
# ---------------------------------------------------------------------------


def test_fraud_reject_decision():
    """Fraud rejection should produce REJECT with AA02."""
    result = make_decision(_make_request(fraud_flag="reject", fraud_prob=0.75))
    assert result.decision == DECISION_REJECT
    assert "AA02" in result.reason_codes


def test_fraud_reject_no_loan_terms():
    """A rejected application must not carry any loan terms."""
    result = make_decision(_make_request(fraud_flag="reject", fraud_prob=0.75))
    assert result.loan_terms == {}
    assert result.recommended_rate is None


# ---------------------------------------------------------------------------
# Branch: fraud manual_review
# ---------------------------------------------------------------------------


def test_fraud_manual_review_decision():
    """Manual review flag should yield MANUAL_REVIEW with AA05."""
    result = make_decision(_make_request(fraud_flag="manual_review", fraud_prob=0.45))
    assert result.decision == DECISION_MANUAL_REVIEW
    assert "AA05" in result.reason_codes


def test_fraud_manual_review_no_loan_terms():
    """Manual review must not carry loan terms."""
    result = make_decision(_make_request(fraud_flag="manual_review", fraud_prob=0.45))
    assert result.loan_terms == {}
    assert result.recommended_rate is None


# ---------------------------------------------------------------------------
# Branch: low PD → APPROVE
# ---------------------------------------------------------------------------


def test_low_pd_approve():
    """pd_score < 0.05 and clean fraud → APPROVE."""
    result = make_decision(_make_request(pd_score=0.02, pd_band="low"))
    assert result.decision == DECISION_APPROVE


def test_low_pd_approve_no_reason_codes():
    """Approved applications must return an empty reason_codes list."""
    result = make_decision(_make_request(pd_score=0.02, pd_band="low"))
    assert result.reason_codes == []


def test_low_pd_approve_has_loan_terms():
    """Approved applications must contain all expected loan_terms keys."""
    result = make_decision(_make_request(pd_score=0.02, pd_band="low"))
    expected_keys = {
        "loan_amount", "loan_term_months", "annual_rate_pct",
        "monthly_payment", "expected_loss", "expected_profit",
        "profitability_flag",
    }
    assert expected_keys.issubset(result.loan_terms.keys())


def test_low_pd_approve_rate_in_range():
    """Recommended rate should be within [5.0, 36.0]%."""
    result = make_decision(_make_request(pd_score=0.02, pd_band="low"))
    assert 5.0 <= result.recommended_rate <= 36.0


# ---------------------------------------------------------------------------
# Branch: medium PD → APPROVE
# ---------------------------------------------------------------------------


def test_medium_pd_approve():
    """pd_score == 0.05 (boundary) should be APPROVE."""
    result = make_decision(_make_request(pd_score=0.05, pd_band="medium"))
    assert result.decision == DECISION_APPROVE


def test_medium_pd_approve_boundary_upper():
    """pd_score == 0.10 (upper boundary) should still be APPROVE."""
    result = make_decision(_make_request(pd_score=0.10, pd_band="medium"))
    assert result.decision == DECISION_APPROVE


def test_medium_pd_rate_higher_than_low_pd_rate():
    """A medium-risk applicant should receive a higher rate than a low-risk one."""
    low_risk = make_decision(_make_request(pd_score=0.02, pd_band="low"))
    medium_risk = make_decision(_make_request(pd_score=0.08, pd_band="medium"))
    assert medium_risk.recommended_rate >= low_risk.recommended_rate


# ---------------------------------------------------------------------------
# Branch: high PD → REJECT
# ---------------------------------------------------------------------------


def test_high_pd_reject():
    """pd_score > 0.10 with clean fraud flag → REJECT."""
    result = make_decision(_make_request(pd_score=0.15, pd_band="high"))
    assert result.decision == DECISION_REJECT
    assert "AA01" in result.reason_codes


def test_high_pd_reject_no_loan_terms():
    """High-PD reject must not carry any loan terms."""
    result = make_decision(_make_request(pd_score=0.20, pd_band="high"))
    assert result.loan_terms == {}
    assert result.recommended_rate is None


# ---------------------------------------------------------------------------
# Supplemental reason codes
# ---------------------------------------------------------------------------


def test_aa03_insufficient_credit_history():
    """num_open_accounts == 0 triggers AA03 on rejection."""
    result = make_decision(_make_request(pd_score=0.20, pd_band="high", open_accounts=0))
    assert "AA03" in result.reason_codes


def test_aa04_high_dti():
    """DTI > 0.43 triggers AA04 on rejection."""
    result = make_decision(_make_request(pd_score=0.20, pd_band="high", dti=0.50))
    assert "AA04" in result.reason_codes


def test_aa03_and_aa04_combined():
    """Both AA03 and AA04 may appear together on a rejection."""
    result = make_decision(_make_request(pd_score=0.20, pd_band="high", open_accounts=0, dti=0.55))
    assert "AA03" in result.reason_codes
    assert "AA04" in result.reason_codes


def test_no_supplemental_codes_on_approve():
    """Even with high DTI, a low-risk APPROVE never has reason codes."""
    result = make_decision(_make_request(pd_score=0.02, pd_band="low", dti=0.50, open_accounts=0))
    assert result.reason_codes == []


# ---------------------------------------------------------------------------
# Fraud priority over credit risk
# ---------------------------------------------------------------------------


def test_fraud_reject_overrides_low_pd():
    """Fraud reject takes priority even if pd_score is very low."""
    result = make_decision(_make_request(fraud_flag="reject", fraud_prob=0.9, pd_score=0.01))
    assert result.decision == DECISION_REJECT
    assert "AA02" in result.reason_codes


def test_fraud_review_overrides_low_pd():
    """Manual review takes priority even if pd_score is very low."""
    result = make_decision(_make_request(fraud_flag="manual_review", fraud_prob=0.4, pd_score=0.01))
    assert result.decision == DECISION_MANUAL_REVIEW


# ---------------------------------------------------------------------------
# Output shape & metadata
# ---------------------------------------------------------------------------


def test_result_has_application_id():
    result = make_decision(_make_request())
    assert result.application_id == "test-app-001"


def test_result_latency_non_negative():
    result = make_decision(_make_request())
    assert result.decision_latency_ms >= 0
    assert isinstance(result.decision_latency_ms, int)


def test_result_timestamp_utc():
    from datetime import timezone
    result = make_decision(_make_request())
    assert result.decision_timestamp.tzinfo == timezone.utc


def test_result_is_dataclass():
    result = make_decision(_make_request())
    assert isinstance(result, DecisionResult)


# ---------------------------------------------------------------------------
# Utility: monthly payment
# ---------------------------------------------------------------------------


def test_monthly_payment_zero_rate():
    """Zero interest rate should return principal / term."""
    payment = _monthly_payment(12_000.0, 0.0, 12)
    assert payment == pytest.approx(1_000.0, rel=1e-4)


def test_monthly_payment_positive_rate():
    """With a positive rate the monthly payment is higher than principal / term."""
    simple = 12_000.0 / 12
    payment = _monthly_payment(12_000.0, 6.0, 12)
    assert payment > simple


def test_monthly_payment_longer_term_lower_payment():
    """Longer term should reduce the monthly payment."""
    short = _monthly_payment(20_000.0, 10.0, 24)
    long_ = _monthly_payment(20_000.0, 10.0, 60)
    assert long_ < short


# ---------------------------------------------------------------------------
# Reason code dictionary completeness
# ---------------------------------------------------------------------------


def test_reason_code_descriptions_complete():
    """All five AAxx codes must be present in the descriptions dict."""
    for code in ("AA01", "AA02", "AA03", "AA04", "AA05"):
        assert code in REASON_CODE_DESCRIPTIONS
        assert len(REASON_CODE_DESCRIPTIONS[code]) > 0
