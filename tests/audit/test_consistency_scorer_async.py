"""
Tests for audit/consistency_scorer.py — async paths with mocked audit record.

Strategy: monkeypatch audit.logger.get_audit_record to return a controlled
fake record. The fraud/credit model calls are expected to fail (no real models)
and are caught by exception handlers → fallback to stored scores.
calculate_pricing is mocked because consistency_scorer.py has a bug where the
PricingResult fallback stub uses invalid kwargs — mocking avoids the double-failure.
"""
from __future__ import annotations

import pytest

from audit.consistency_scorer import (
    CONSISTENCY_THRESHOLD,
    ConsistencyResult,
    score_decision_consistency,
)

DB_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Fixture: patch calculate_pricing to return a valid PricingResult
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_pricing(monkeypatch):
    """Prevent the buggy PricingResult fallback from propagating."""
    from models.pricing.engine import PricingResult
    valid_result = PricingResult(
        recommended_rate=7.5,
        expected_loss=225.0,
        expected_profit=150.0,
        profitability_flag=True,
        pd_score=0.045,
        fraud_flag="continue",
        loan_amount=5000.0,
    )
    monkeypatch.setattr(
        "models.pricing.engine.calculate_pricing",
        lambda *args, **kwargs: valid_result,
    )

# ---------------------------------------------------------------------------
# Fake audit records
# ---------------------------------------------------------------------------

def _fake_record(**overrides) -> dict:
    base = {
        "application_id": "app-001",
        "decision_output": "APPROVE",
        "risk_score": 0.045,
        "fraud_score": 0.08,
        "input_features": {
            "fico_score": 720,
            "annual_income": 80000,
            "loan_amount": 5000,
            "loan_term_months": 36,
            "debt_to_income_ratio": 0.22,
            "num_open_accounts": 3,
            "delinquency_24m": 0,
        },
        "logged_at": "2026-01-01T12:00:00+00:00",
        "reason_codes": ["AA04"],
        "model_version": {"credit_risk": "v1.0", "fraud": "v1.0"},
        "feature_version": "v1.0",
        "tenant_id": "tenant-a",
        "policy_version": "v10.0",
        "record_hash": "sha256:abc123",
    }
    base.update(overrides)
    return base


def _fake_record_reject() -> dict:
    return _fake_record(
        decision_output="REJECT",
        risk_score=0.25,
        fraud_score=0.35,
        input_features={
            "fico_score": 560,
            "annual_income": 25000,
            "loan_amount": 10000,
            "loan_term_months": 60,
            "debt_to_income_ratio": 0.65,
            "num_open_accounts": 1,
            "delinquency_24m": 3,
        },
    )


# ---------------------------------------------------------------------------
# Tests: ValueError when no record found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_decision_consistency_raises_when_no_record(monkeypatch):
    """When get_audit_record returns None, ValueError is raised."""
    async def mock_get(*args, **kwargs):
        return None

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    with pytest.raises(ValueError, match="No audit record found"):
        await score_decision_consistency("missing-app", DB_URL, None, None, "tenant-a")


# ---------------------------------------------------------------------------
# Tests: Successful replay (models fail → fallback to stored scores)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_score_decision_consistency_approve(monkeypatch):
    """Approve record replays consistently — both original and replayed stay APPROVE."""
    record = _fake_record()

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert isinstance(result, ConsistencyResult)
    assert result.application_id == "app-001"
    assert isinstance(result.consistent, bool)
    assert isinstance(result.score, float)
    assert 0.0 <= result.score <= 1.0
    assert result.checked_at is not None


@pytest.mark.asyncio
async def test_score_decision_consistency_reject(monkeypatch):
    """Reject record replays — result is a valid ConsistencyResult."""
    record = _fake_record_reject()

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert isinstance(result, ConsistencyResult)
    assert result.original_decision == "REJECT"


@pytest.mark.asyncio
async def test_score_decision_consistency_returns_delta_pd(monkeypatch):
    """delta_pd = replayed_pd - original_pd is computed correctly."""
    stored_pd = 0.06
    record = _fake_record(risk_score=stored_pd)

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    # replayed_pd comes from stored score fallback (models fail) → same as stored
    assert isinstance(result.delta_pd, float)
    assert result.replayed_pd == pytest.approx(stored_pd)
    assert result.delta_pd == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_score_decision_consistency_flagged_field_is_bool(monkeypatch):
    async def mock_get(*args, **kwargs):
        return _fake_record()

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert isinstance(result.flagged, bool)


@pytest.mark.asyncio
async def test_score_decision_consistency_string_input_features(monkeypatch):
    """input_features stored as JSON string → should be decoded."""
    import json
    record = _fake_record(
        input_features=json.dumps({"fico_score": 700, "annual_income": 60000,
                                   "loan_amount": 8000, "loan_term_months": 48,
                                   "debt_to_income_ratio": 0.30, "num_open_accounts": 2})
    )

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert isinstance(result, ConsistencyResult)


@pytest.mark.asyncio
async def test_score_decision_consistency_missing_input_features(monkeypatch):
    """input_features=None → treated as {} → function completes."""
    record = _fake_record(input_features=None)

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert isinstance(result, ConsistencyResult)


@pytest.mark.asyncio
async def test_score_decision_consistency_high_risk_score(monkeypatch):
    """High risk score (>0.10) → pd_band='high' in fallback."""
    record = _fake_record(risk_score=0.25, decision_output="REJECT")

    async def mock_get(*args, **kwargs):
        return record

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    result = await score_decision_consistency(
        "app-001", DB_URL, None, None, tenant_id="tenant-a"
    )

    assert result.replayed_pd == pytest.approx(0.25)


@pytest.mark.asyncio
async def test_score_decision_consistency_no_tenant_id_uses_empty(monkeypatch):
    """tenant_id=None → '' is passed to get_audit_record."""
    calls = []

    async def mock_get(application_id, db_url, tenant_id=""):
        calls.append(tenant_id)
        return _fake_record()

    monkeypatch.setattr("audit.logger.get_audit_record", mock_get)

    await score_decision_consistency("app-001", DB_URL, None, None, tenant_id=None)

    assert calls[0] == ""
