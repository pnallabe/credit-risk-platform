"""
Decision Engine
===============
Combines fraud detection, credit risk, and pricing model outputs into a
single, FCRA-compliant loan decision.

Decision Logic (from PRD)
--------------------------
  fraud_flag == "reject"         → REJECT         (AA02)
  fraud_flag == "manual_review"  → MANUAL_REVIEW  (AA05)
  pd_score < 0.05                → APPROVE        (standard / base rate)
  0.05 ≤ pd_score ≤ 0.10        → APPROVE        (risk-priced rate)
  pd_score > 0.10                → REJECT         (AA01)

FCRA Adverse Action Codes
--------------------------
  AA01 — High probability of default
  AA02 — Fraud indicators detected
  AA03 — Insufficient credit history
  AA04 — Debt-to-income ratio too high
  AA05 — Application requires manual review

Public API
----------
>>> from decision_engine.engine import (
...     DecisionRequest, DecisionResult, make_decision, REASON_CODE_DESCRIPTIONS
... )
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Make project root importable when run as a script
sys.path.insert(0, str(Path(__file__).parents[1]))

from models.pricing.engine import PricingResult  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECISION_APPROVE = "APPROVE"
DECISION_REJECT = "REJECT"
DECISION_MANUAL_REVIEW = "MANUAL_REVIEW"

#: Mapping of FCRA adverse action codes to their human-readable descriptions.
REASON_CODE_DESCRIPTIONS: Dict[str, str] = {
    "AA01": "High probability of default",
    "AA02": "Fraud indicators detected",
    "AA03": "Insufficient credit history",
    "AA04": "Debt-to-income ratio too high",
    "AA05": "Application requires manual review",
}

# Risk thresholds (mirror models/credit_risk/predict.py)
PD_THRESHOLD_LOW = 0.05    # below → low risk → APPROVE at base rate
PD_THRESHOLD_MEDIUM = 0.10  # 0.05–0.10 → medium risk → APPROVE at priced rate

# Heuristic thresholds for supplemental reason codes
DTI_HIGH_THRESHOLD = 0.43       # DTI above this → AA04
OPEN_ACCOUNTS_MIN = 1           # fewer than this → AA03


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FraudResult:
    """Fraud model output for a single application.

    Can be constructed directly from a row of the DataFrame returned by
    ``models.fraud_detection.predict.predict_fraud()``.
    """

    fraud_probability: float
    fraud_flag: str  # "continue" | "manual_review" | "reject"


@dataclass
class CreditResult:
    """Credit risk model output for a single application.

    Can be constructed directly from a row of the DataFrame returned by
    ``models.credit_risk.predict.predict_pd()``.
    """

    pd_score: float
    pd_band: str  # "low" | "medium" | "high"


@dataclass
class DecisionRequest:
    """Full input bundle for the decision engine.

    Parameters
    ----------
    application_id:
        UUID string identifying the loan application.
    fraud_result:
        Output from the fraud detection model.
    credit_result:
        Output from the credit risk model.
    pricing_result:
        Output from the pricing engine.
    loan_amount:
        Requested loan amount in USD.
    loan_term_months:
        Requested loan term (12 / 24 / 36 / 48 / 60 months).
    debt_to_income_ratio:
        Applicant's debt-to-income ratio (0.0 – 0.65).
    num_open_accounts:
        Number of open credit accounts.
    annual_income:
        Gross annual income in USD (optional; used only for loan_terms metadata).
    """

    application_id: str
    fraud_result: FraudResult
    credit_result: CreditResult
    pricing_result: PricingResult
    loan_amount: float
    loan_term_months: int
    debt_to_income_ratio: float
    num_open_accounts: int
    annual_income: Optional[float] = None


@dataclass
class DecisionResult:
    """Full output from the decision engine for a single application.

    Parameters
    ----------
    application_id:
        Echoed from the request for traceability.
    decision:
        Final lending decision: ``"APPROVE"``, ``"REJECT"``, or
        ``"MANUAL_REVIEW"``.
    recommended_rate:
        Annual interest rate (%) to offer; ``None`` for rejections.
    loan_terms:
        Dictionary with structured loan offer details (amount, term,
        rate, estimated monthly payment, expected loss, expected profit).
        Empty dict for rejections.
    reason_codes:
        List of FCRA adverse action codes explaining the decision.
    decision_timestamp:
        UTC timestamp of when the decision was made.
    decision_latency_ms:
        Wall-clock time (ms) from request receipt to decision completion.
    """

    application_id: str
    decision: str
    recommended_rate: Optional[float]
    loan_terms: Dict
    reason_codes: List[str]
    decision_timestamp: datetime
    decision_latency_ms: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    """Calculate the fixed monthly instalment using the annuity formula.

    Parameters
    ----------
    principal:
        Loan principal in USD.
    annual_rate:
        Annual interest rate as a percentage (e.g., ``7.5`` for 7.5%).
    term_months:
        Loan term in months.

    Returns
    -------
    float
        Monthly payment in USD, rounded to 2 decimal places.
    """
    monthly_rate = annual_rate / 100 / 12
    if monthly_rate == 0:
        return round(principal / term_months, 2)
    payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -term_months)
    return round(payment, 2)


def _collect_reason_codes(
    decision: str,
    fraud_result: FraudResult,
    credit_result: CreditResult,
    debt_to_income_ratio: float,
    num_open_accounts: int,
) -> List[str]:
    """Collect applicable FCRA adverse action codes.

    Reason codes are always included for ``REJECT`` and
    ``MANUAL_REVIEW`` decisions. For ``APPROVE`` decisions an empty
    list is returned (no adverse action notice required).

    Parameters
    ----------
    decision:
        The tentative decision string.
    fraud_result, credit_result:
        Model outputs.
    debt_to_income_ratio, num_open_accounts:
        Raw application fields used for supplemental codes.

    Returns
    -------
    List[str]
        Ordered list of applicable adverse action codes.
    """
    if decision == DECISION_APPROVE:
        return []

    codes: List[str] = []

    # Primary reason from the decision path
    if fraud_result.fraud_flag == "reject":
        codes.append("AA02")
    elif fraud_result.fraud_flag == "manual_review":
        codes.append("AA05")
    elif credit_result.pd_score > PD_THRESHOLD_MEDIUM:
        codes.append("AA01")

    # Supplemental reason codes (provide additional context)
    if num_open_accounts < OPEN_ACCOUNTS_MIN:
        codes.append("AA03")
    if debt_to_income_ratio > DTI_HIGH_THRESHOLD:
        codes.append("AA04")

    # De-duplicate whilst preserving order (Python 3.7+ dict trick)
    return list(dict.fromkeys(codes))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_decision(
    request: DecisionRequest,
    *,
    policy_overrides: Optional[Dict[str, Any]] = None,
) -> DecisionResult:
    """Apply the decision policy and return a ``DecisionResult``.

    Decision tree
    ~~~~~~~~~~~~~
    1. **Fraud reject**      → ``REJECT``        (AA02)
    2. **Fraud review**      → ``MANUAL_REVIEW`` (AA05)
    3. **pd_score < 0.05**   → ``APPROVE``       at base rate
    4. **pd_score ≤ 0.10**   → ``APPROVE``       at risk-priced rate
    5. **pd_score > 0.10**   → ``REJECT``        (AA01)

    Parameters
    ----------
    request:
        Populated :class:`DecisionRequest` instance.
    policy_overrides : dict, optional
        Per-tenant policy cutoff overrides resolved from the Config Registry
        (P2.1).  Supported keys::

            pd_threshold      float  — replaces PD_THRESHOLD_MEDIUM
            pd_threshold_low  float  — replaces PD_THRESHOLD_LOW
            dti_high          float  — replaces DTI_HIGH_THRESHOLD

        Unknown keys are silently ignored so future cutoff additions are
        backwards-compatible.

    Returns
    -------
    DecisionResult
        Complete decision with audit fields.
    """
    start_ns = time.perf_counter_ns()

    # P2.1 — Apply per-tenant policy cutoffs when provided
    overrides = policy_overrides or {}
    _pd_low    = float(overrides.get("pd_threshold_low", PD_THRESHOLD_LOW))
    _pd_medium = float(overrides.get("pd_threshold",     PD_THRESHOLD_MEDIUM))

    fraud = request.fraud_result
    credit = request.credit_result
    pricing = request.pricing_result

    # ------------------------------------------------------------------
    # Step 1 — Apply decision tree
    # ------------------------------------------------------------------
    if fraud.fraud_flag == "reject":
        decision = DECISION_REJECT

    elif fraud.fraud_flag == "manual_review":
        decision = DECISION_MANUAL_REVIEW

    elif credit.pd_score < _pd_low:
        decision = DECISION_APPROVE

    elif credit.pd_score <= _pd_medium:
        decision = DECISION_APPROVE

    else:
        decision = DECISION_REJECT

    # ------------------------------------------------------------------
    # Step 2 — Build loan terms (only meaningful for APPROVE)
    # ------------------------------------------------------------------
    if decision == DECISION_APPROVE:
        rate = pricing.recommended_rate
        monthly = _monthly_payment(request.loan_amount, rate, request.loan_term_months)
        loan_terms: Dict = {
            "loan_amount": request.loan_amount,
            "loan_term_months": request.loan_term_months,
            "annual_rate_pct": rate,
            "monthly_payment": monthly,
            "expected_loss": pricing.expected_loss,
            "expected_profit": pricing.expected_profit,
            "profitability_flag": pricing.profitability_flag,
        }
        recommended_rate: Optional[float] = rate
    else:
        loan_terms = {}
        recommended_rate = None

    # ------------------------------------------------------------------
    # Step 3 — Collect reason codes
    # ------------------------------------------------------------------
    reason_codes = _collect_reason_codes(
        decision=decision,
        fraud_result=fraud,
        credit_result=credit,
        debt_to_income_ratio=request.debt_to_income_ratio,
        num_open_accounts=request.num_open_accounts,
    )

    # ------------------------------------------------------------------
    # Step 4 — Compute latency and timestamp
    # ------------------------------------------------------------------
    elapsed_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
    decision_timestamp = datetime.now(tz=timezone.utc)

    return DecisionResult(
        application_id=request.application_id,
        decision=decision,
        recommended_rate=recommended_rate,
        loan_terms=loan_terms,
        reason_codes=reason_codes,
        decision_timestamp=decision_timestamp,
        decision_latency_ms=elapsed_ms,
    )


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import uuid

    from models.pricing.engine import PricingConfig, calculate_pricing

    _pricing_cfg = PricingConfig()
    _pricing = calculate_pricing(pd_score=0.03, fraud_flag="continue",
                                 loan_amount=20_000.0, config=_pricing_cfg)

    _req = DecisionRequest(
        application_id=str(uuid.uuid4()),
        fraud_result=FraudResult(fraud_probability=0.1, fraud_flag="continue"),
        credit_result=CreditResult(pd_score=0.03, pd_band="low"),
        pricing_result=_pricing,
        loan_amount=20_000.0,
        loan_term_months=36,
        debt_to_income_ratio=0.25,
        num_open_accounts=5,
        annual_income=75_000.0,
    )

    _result = make_decision(_req)
    print(json.dumps(
        {
            "application_id": _result.application_id,
            "decision": _result.decision,
            "recommended_rate": _result.recommended_rate,
            "loan_terms": _result.loan_terms,
            "reason_codes": _result.reason_codes,
            "decision_timestamp": _result.decision_timestamp.isoformat(),
            "decision_latency_ms": _result.decision_latency_ms,
        },
        indent=2,
    ))
