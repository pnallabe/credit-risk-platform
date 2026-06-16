"""
credit_core.policy — Canonical Policy Evaluation
=================================================
Single entry point for credit policy evaluation used by ALL channels.

Usage
-----
>>> from credit_core.policy import evaluate_policy, PolicyResult
>>> results = evaluate_policy(scores_df, context_df,
...                           policy_version="v1", config={})

Design
------
This module wraps ``decision_engine.engine.make_decision`` so that:

* The Decision API and the DecisionEngineAgent call identical logic.
* Policy version, cutoffs, and reason codes are not duplicated.
* The DataFrame-oriented interface makes batch scoring straightforward.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from decision_engine.engine import (
    CreditResult,
    DecisionRequest,
    DecisionResult,
    FraudResult,
    make_decision,
)
from models.pricing.engine import PricingConfig, calculate_pricing

logger = logging.getLogger(__name__)

# PROMPT-05: Import tracing — no-op if opentelemetry-sdk is not installed
try:
    from observability.tracing import TRACER, span as _trace_span
except ImportError:  # pragma: no cover
    TRACER = None  # type: ignore[assignment]
    import contextlib as _contextlib
    _trace_span = _contextlib.nullcontext  # type: ignore[assignment]

# Default policy version — overridable via ``policy_version`` parameter.
DEFAULT_POLICY_VERSION = "v1"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class PolicyResult:
    """Decision result for a single application produced by ``evaluate_policy``.

    Attributes mirror ``DecisionResult`` but carry the ``policy_version``
    used so callers can assert consistency.
    """

    application_id: str
    decision: str           # "APPROVE" | "REJECT" | "MANUAL_REVIEW"
    reason_codes: List[str] = field(default_factory=list)
    approved_amount: Optional[float] = None
    approved_rate: Optional[float] = None
    approved_term_months: Optional[int] = None
    policy_version: str = DEFAULT_POLICY_VERSION
    decision_latency_ms: int = 0
    raw: Optional[DecisionResult] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def evaluate_policy(
    scores_df: pd.DataFrame,
    context_df: pd.DataFrame,
    *,
    policy_version: str = DEFAULT_POLICY_VERSION,
    config: Optional[Dict[str, Any]] = None,
) -> List[PolicyResult]:
    """Evaluate credit policy for a batch of scored applications.

    Both DataFrames must be indexed by ``application_id`` or contain an
    ``application_id`` column.  Rows are matched on ``application_id``.

    Parameters
    ----------
    scores_df:
        DataFrame with columns: ``application_id``, ``pd_score``,
        ``pd_band``, ``fraud_probability``, ``fraud_flag``.
        Produced by the risk models (``models.credit_risk.predict``,
        ``models.fraud_detection.predict``).
    context_df:
        DataFrame with the raw application context needed to evaluate
        policy rules: ``application_id``, ``loan_amount``,
        ``loan_term_months``, ``debt_to_income_ratio`` (or ``dti``),
        ``num_open_accounts``, ``annual_income``.
        Produced by the ingestion/validation stage or the Decision API
        request payload.
    policy_version:
        Opaque version string written to every ``PolicyResult`` so
        decisions can be traced back to the active policy snapshot.
    config:
        Optional overrides for ``PricingConfig`` fields.

    Returns
    -------
    List[PolicyResult]
        One ``PolicyResult`` per row in ``scores_df``, in the same order.
    """
    pricing_cfg = PricingConfig(**(config or {})) if config else PricingConfig()

    # Merge scores with context on application_id
    s = scores_df.copy()
    c = context_df.copy()

    # Normalise column alias: dti → debt_to_income_ratio
    if "dti" in c.columns and "debt_to_income_ratio" not in c.columns:
        c = c.rename(columns={"dti": "debt_to_income_ratio"})

    merged = s.merge(c, on="application_id", how="left", suffixes=("", "_ctx"))

    results: List[PolicyResult] = []

    with _trace_span("credit_core.evaluate_policy", TRACER,
                     policy_version=policy_version, batch_size=len(merged)):
        for _, row in merged.iterrows():
            app_id = str(row["application_id"])
            pd_score = float(row.get("pd_score", 0.0))
            pd_band = str(row.get("pd_band", "high"))
            fraud_probability = float(row.get("fraud_probability", 0.0))
            fraud_flag = str(row.get("fraud_flag", "reject"))
            loan_amount = float(row.get("loan_amount", 0.0))
            loan_term_months = int(row.get("loan_term_months", 36))
            dti = float(row.get("debt_to_income_ratio", 0.0))
            num_open = int(row.get("num_open_accounts") or 0)
            annual_income = float(row.get("annual_income", 0.0))
            borrower_state = row.get("borrower_state", None)
            if pd.isna(borrower_state):
                borrower_state = None

            # Compute pricing (needed by make_decision)
            pricing_result = calculate_pricing(
                pd_score=pd_score,
                fraud_flag=fraud_flag,
                loan_amount=loan_amount,
                config=pricing_cfg,
                borrower_state=str(borrower_state) if borrower_state else None,
            )

            decision_req = DecisionRequest(
                application_id=app_id,
                fraud_result=FraudResult(
                    fraud_probability=fraud_probability,
                    fraud_flag=fraud_flag,
                ),
                credit_result=CreditResult(
                    pd_score=pd_score,
                    pd_band=pd_band,
                ),
                pricing_result=pricing_result,
                loan_amount=loan_amount,
                loan_term_months=loan_term_months,
                debt_to_income_ratio=dti,
                num_open_accounts=num_open,
                annual_income=annual_income,
            )

            dr: DecisionResult = make_decision(decision_req)

            approved_amount: Optional[float] = None
            approved_rate: Optional[float] = None
            approved_term: Optional[int] = None
            if dr.decision == "APPROVE":
                approved_amount = loan_amount
                approved_rate = dr.recommended_rate
                approved_term = loan_term_months

            results.append(
                PolicyResult(
                    application_id=app_id,
                    decision=dr.decision,
                    reason_codes=dr.reason_codes,
                    approved_amount=approved_amount,
                    approved_rate=approved_rate,
                    approved_term_months=approved_term,
                    policy_version=policy_version,
                    decision_latency_ms=dr.decision_latency_ms,
                    raw=dr,
                )
            )

    logger.info(
        "credit_core.policy: evaluated %d applications (policy_version=%s)",
        len(results),
        policy_version,
    )
    return results
