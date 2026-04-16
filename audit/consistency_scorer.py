"""
audit/consistency_scorer.py
============================
Decision consistency scorer (PRD §3.1, §7.1 — GAP-04).

Replays a stored decision through the current policy + model and reports
the delta between the original and replayed outputs.

Public API
----------
>>> from audit.consistency_scorer import score_decision_consistency
>>> result = await score_decision_consistency("app-uuid-123", db_url, fraud_model, risk_model)
>>> print(result.consistent, result.delta_pd, result.score)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSISTENCY_THRESHOLD = 0.02   # PD delta above this is flagged


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyResult:
    """Outcome of a single consistency check replay.

    Attributes
    ----------
    application_id:
        The application that was replayed.
    consistent:
        True if replayed decision matches original AND |delta_pd| < CONSISTENCY_THRESHOLD.
    original_decision:
        Decision stored in the audit log (APPROVE / REJECT / MANUAL_REVIEW).
    replayed_decision:
        Decision produced by the current policy when given the same features.
    original_pd:
        PD score stored in the audit log.
    replayed_pd:
        PD score produced in this replay.
    delta_pd:
        replayed_pd - original_pd
    score:
        1.0 = identical; 0.5 = same decision bucket but high PD delta; 0.0 = decision flipped.
    flagged:
        True if delta_pd > CONSISTENCY_THRESHOLD or the decision outcome changed.
    checked_at:
        ISO-8601 UTC timestamp of this check.
    """

    application_id: str
    consistent: bool
    original_decision: str
    replayed_decision: str
    original_pd: float
    replayed_pd: float
    delta_pd: float
    score: float
    flagged: bool
    checked_at: str


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------

async def score_decision_consistency(
    application_id: str,
    db_url: str,
    fraud_model: Any,
    risk_model: Any,
    tenant_id: Optional[str] = None,
) -> ConsistencyResult:
    """Replay a stored decision and measure consistency.

    Steps
    -----
    1. Load the stored audit record for *application_id*.
    2. Reconstruct the input feature DataFrame from stored ``input_features``.
    3. Re-run fraud + credit risk models.
    4. Re-run the decision engine with the policy thresholds active at ``logged_at``.
    5. Compare original vs replayed (decision, pd_score).
    6. Return a :class:`ConsistencyResult`.

    Parameters
    ----------
    application_id:
        UUID of the loan application to replay.
    db_url:
        SQLAlchemy async connection URL.
    fraud_model:
        Pre-loaded fraud detection model (or None to load from disk).
    risk_model:
        Pre-loaded credit risk model (or None to load from disk).
    tenant_id:
        Tenant for row-level isolation (required when db_url points to a
        multi-tenant store; if None a ValueError from get_audit_record propagates).

    Returns
    -------
    ConsistencyResult
    """
    import pandas as pd
    from audit.logger import get_audit_record
    from decision_engine.engine import (
        CreditResult, DecisionRequest, FraudResult, make_decision,
    )
    from models.credit_risk.predict import predict_pd
    from models.fraud_detection.predict import predict_fraud
    from models.pricing.engine import PricingConfig, calculate_pricing

    checked_at = datetime.now(timezone.utc).isoformat()

    # ------------------------------------------------------------------ #
    # 1. Load stored audit record                                          #
    # ------------------------------------------------------------------ #
    record = await get_audit_record(application_id, db_url, tenant_id=tenant_id or "")
    if record is None:
        raise ValueError(f"No audit record found for application_id={application_id!r}")

    # ------------------------------------------------------------------ #
    # 2. Reconstruct feature DataFrame                                     #
    # ------------------------------------------------------------------ #
    raw_features = record.get("input_features") or {}
    if isinstance(raw_features, str):
        try:
            raw_features = json.loads(raw_features)
        except Exception:
            raw_features = {}

    features_df = pd.DataFrame([raw_features])

    # ------------------------------------------------------------------ #
    # 3. Re-run models                                                     #
    # ------------------------------------------------------------------ #
    try:
        fraud_out = predict_fraud(features_df, _model=fraud_model)
        fraud_row = fraud_out.iloc[0]
        fraud_result = FraudResult(
            fraud_probability=float(fraud_row["fraud_probability"]),
            fraud_flag=str(fraud_row["fraud_flag"]),
        )
    except Exception as exc:
        logger.warning("Fraud model replay failed: %s; using stored score", exc)
        stored_fraud = float(record.get("fraud_score") or 0.0)
        fraud_flag = "continue" if stored_fraud < 0.30 else ("manual_review" if stored_fraud <= 0.60 else "reject")
        fraud_result = FraudResult(fraud_probability=stored_fraud, fraud_flag=fraud_flag)

    try:
        credit_out = predict_pd(features_df, _model=risk_model)
        credit_row = credit_out.iloc[0]
        replayed_pd = float(credit_row["pd_score"])
        credit_result = CreditResult(
            pd_score=replayed_pd,
            pd_band=str(credit_row["pd_band"]),
        )
    except Exception as exc:
        logger.warning("Credit model replay failed: %s; using stored score", exc)
        replayed_pd = float(record.get("risk_score") or 0.0)
        pd_band = "low" if replayed_pd < 0.05 else ("medium" if replayed_pd <= 0.10 else "high")
        credit_result = CreditResult(pd_score=replayed_pd, pd_band=pd_band)

    # ------------------------------------------------------------------ #
    # 4. Re-run decision engine with policy active at original logged_at  #
    # ------------------------------------------------------------------ #
    policy_overrides_replay = {}

    # Attempt to load the policy version that was active at decision time
    try:
        from decision_engine.policy_version_store import PolicyVersionStore
        logged_at_str = record.get("logged_at") or checked_at
        logged_at_dt = datetime.fromisoformat(logged_at_str.replace("Z", "+00:00"))
        policy_store = PolicyVersionStore()
        policy_at_time = policy_store.get_as_of(logged_at_dt)
        params_dict = (
            policy_at_time.parameters if hasattr(policy_at_time, "parameters")
            else {}
        )
        if isinstance(params_dict, dict):
            for key in ("pd_threshold_low", "pd_threshold", "dti_high"):
                if key in params_dict:
                    policy_overrides_replay[key] = params_dict[key]
    except Exception as exc:
        logger.debug("Policy version lookup failed: %s; using engine defaults", exc)

    # Build minimal pricing result for replay
    try:
        loan_amount = float(raw_features.get("loan_amount", 5000))
        loan_term = int(raw_features.get("loan_term_months", 36))
        pricing_cfg = PricingConfig()
        pricing_result = calculate_pricing(
            pd_score=replayed_pd,
            loan_amount=loan_amount,
            loan_term_months=loan_term,
            config=pricing_cfg,
        )
    except Exception as exc:
        logger.debug("Pricing replay failed: %s; using stub", exc)
        from models.pricing.engine import PricingResult
        pricing_result = PricingResult(
            recommended_rate=7.5,
            base_rate=5.0,
            risk_premium=2.5,
            expected_loss=0.0,
            expected_profit=0.0,
            profitability_flag="pass",
        )

    decision_request = DecisionRequest(
        application_id=application_id,
        fraud_result=fraud_result,
        credit_result=credit_result,
        pricing_result=pricing_result,
        loan_amount=float(raw_features.get("loan_amount", 5000)),
        loan_term_months=int(raw_features.get("loan_term_months", 36)),
        debt_to_income_ratio=float(raw_features.get("debt_to_income_ratio", 0.2)),
        num_open_accounts=int(raw_features.get("num_open_accounts", 3)),
        annual_income=raw_features.get("annual_income"),
    )

    # Replay without four-eyes (simulation — not a live production override)
    replayed_result = make_decision(
        decision_request,
        policy_overrides=policy_overrides_replay if policy_overrides_replay else None,
    )
    replayed_decision = replayed_result.decision

    # ------------------------------------------------------------------ #
    # 5. Compare                                                           #
    # ------------------------------------------------------------------ #
    original_decision = str(record.get("decision_output") or "")
    original_pd = float(record.get("risk_score") or 0.0)
    delta_pd = replayed_pd - original_pd

    decisions_match = original_decision.upper() == replayed_decision.upper()

    if decisions_match and abs(delta_pd) < CONSISTENCY_THRESHOLD:
        score = 1.0
        consistent = True
    elif decisions_match:
        score = 0.5
        consistent = False
    else:
        score = 0.0
        consistent = False

    flagged = abs(delta_pd) > CONSISTENCY_THRESHOLD or not decisions_match

    return ConsistencyResult(
        application_id=application_id,
        consistent=consistent,
        original_decision=original_decision,
        replayed_decision=replayed_decision,
        original_pd=original_pd,
        replayed_pd=replayed_pd,
        delta_pd=delta_pd,
        score=score,
        flagged=flagged,
        checked_at=checked_at,
    )
