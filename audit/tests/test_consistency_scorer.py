"""
audit/tests/test_consistency_scorer.py
========================================
Tests for the decision consistency scorer (GAP-04).

Markers: gap_closure, p2
"""
from __future__ import annotations

import dataclasses
import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_record(
    application_id: str,
    decision: str = "APPROVE",
    risk_score: float = 0.04,
    fraud_score: float = 0.10,
    features: dict | None = None,
) -> dict:
    """Build a fake audit record dict as returned by get_audit_record."""
    return {
        "log_id": str(uuid.uuid4()),
        "tenant_id": "tenant-test",
        "application_id": application_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "decision_output": decision,
        "risk_score": risk_score,
        "fraud_score": fraud_score,
        "policy_version": "v1",
        "input_features": features or {
            "loan_amount": 5000,
            "loan_term_months": 36,
            "debt_to_income_ratio": 0.25,
            "num_open_accounts": 3,
            "credit_score": 720,
            "annual_income": 60000.0,
        },
    }


def _make_fraud_df(prob: float = 0.10):
    import pandas as pd
    flag = "continue" if prob < 0.30 else ("manual_review" if prob <= 0.60 else "reject")
    return pd.DataFrame([{"fraud_probability": prob, "fraud_flag": flag}])


def _make_credit_df(pd_score: float = 0.04):
    import pandas as pd
    pd_band = "low" if pd_score < 0.05 else ("medium" if pd_score <= 0.10 else "high")
    return pd.DataFrame([{"pd_score": pd_score, "pd_band": pd_band}])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.gap_closure
@pytest.mark.p2
@pytest.mark.asyncio
async def test_identical_replay():
    """Same stored features + same models → consistent=True, score=1.0."""
    app_id = str(uuid.uuid4())
    record = _make_mock_record(app_id, decision="APPROVE", risk_score=0.04)

    with (
        patch("audit.consistency_scorer.get_audit_record", new=AsyncMock(return_value=record)),
        patch("audit.consistency_scorer.predict_fraud", return_value=_make_fraud_df(0.10)),
        patch("audit.consistency_scorer.predict_pd", return_value=_make_credit_df(0.04)),
    ):
        from audit.consistency_scorer import score_decision_consistency

        result = await score_decision_consistency(
            application_id=app_id,
            db_url="sqlite+aiosqlite:///:memory:",
            fraud_model=None,
            risk_model=None,
            tenant_id="tenant-test",
        )

    assert result.consistent is True
    assert result.score == 1.0
    assert not result.flagged
    assert result.original_decision == "APPROVE"
    assert result.replayed_decision == "APPROVE"
    assert abs(result.delta_pd) < 0.001


@pytest.mark.gap_closure
@pytest.mark.p2
@pytest.mark.asyncio
async def test_model_drift_detected():
    """Stored PD = 0.04, replayed PD = 0.09 → |delta| > threshold → flagged=True."""
    app_id = str(uuid.uuid4())
    # Original was APPROVE at PD = 0.04
    record = _make_mock_record(app_id, decision="APPROVE", risk_score=0.04)
    # Replayed PD drifts to 0.09 (still APPROVE but large delta)
    with (
        patch("audit.consistency_scorer.get_audit_record", new=AsyncMock(return_value=record)),
        patch("audit.consistency_scorer.predict_fraud", return_value=_make_fraud_df(0.10)),
        patch("audit.consistency_scorer.predict_pd", return_value=_make_credit_df(0.09)),
    ):
        from audit.consistency_scorer import score_decision_consistency, CONSISTENCY_THRESHOLD

        result = await score_decision_consistency(
            application_id=app_id,
            db_url="sqlite+aiosqlite:///:memory:",
            fraud_model=None,
            risk_model=None,
            tenant_id="tenant-test",
        )

    assert result.flagged is True
    assert abs(result.delta_pd) > CONSISTENCY_THRESHOLD
    assert result.consistent is False


@pytest.mark.gap_closure
@pytest.mark.p2
@pytest.mark.asyncio
async def test_decision_flip_score_zero():
    """Original APPROVE, replayed REJECT → score=0.0, flagged=True."""
    app_id = str(uuid.uuid4())
    # Original approved at low PD
    record = _make_mock_record(app_id, decision="APPROVE", risk_score=0.04)
    # Replay uses high PD → REJECT
    with (
        patch("audit.consistency_scorer.get_audit_record", new=AsyncMock(return_value=record)),
        patch("audit.consistency_scorer.predict_fraud", return_value=_make_fraud_df(0.10)),
        patch("audit.consistency_scorer.predict_pd", return_value=_make_credit_df(0.15)),
    ):
        from audit.consistency_scorer import score_decision_consistency

        result = await score_decision_consistency(
            application_id=app_id,
            db_url="sqlite+aiosqlite:///:memory:",
            fraud_model=None,
            risk_model=None,
            tenant_id="tenant-test",
        )

    assert result.score == 0.0
    assert result.consistent is False
    assert result.flagged is True
    assert result.original_decision.upper() == "APPROVE"
    assert result.replayed_decision.upper() == "REJECT"


@pytest.mark.gap_closure
@pytest.mark.p2
@pytest.mark.asyncio
async def test_not_found_raises_value_error():
    """Missing audit record should raise ValueError."""
    with patch("audit.consistency_scorer.get_audit_record", new=AsyncMock(return_value=None)):
        from audit.consistency_scorer import score_decision_consistency

        with pytest.raises(ValueError, match="No audit record found"):
            await score_decision_consistency(
                application_id="does-not-exist",
                db_url="sqlite+aiosqlite:///:memory:",
                fraud_model=None,
                risk_model=None,
                tenant_id="tenant-test",
            )


@pytest.mark.gap_closure
@pytest.mark.p2
@pytest.mark.asyncio
async def test_consistency_result_fields():
    """ConsistencyResult must contain all expected fields."""
    from audit.consistency_scorer import ConsistencyResult

    result = ConsistencyResult(
        application_id="app-123",
        consistent=True,
        original_decision="APPROVE",
        replayed_decision="APPROVE",
        original_pd=0.03,
        replayed_pd=0.03,
        delta_pd=0.0,
        score=1.0,
        flagged=False,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )
    d = dataclasses.asdict(result)
    for key in (
        "application_id", "consistent", "original_decision", "replayed_decision",
        "original_pd", "replayed_pd", "delta_pd", "score", "flagged", "checked_at",
    ):
        assert key in d, f"Missing field: {key}"
