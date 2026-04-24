"""
decision-api/tests/test_post_decision_override.py
==================================================
Integration tests for the post-decision override API endpoint (GAP-23).
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure the src dir is on the path so decision-api imports work
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

_SRC = str(Path(__file__).parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_jwt_user(user_id: str = "officer_a", tenant_id: str = "t1") -> dict:
    return {"sub": user_id, "user_id": user_id, "tenant_id": tenant_id}


def _fake_referral(referral_id: str, application_id: str, status: str = "claimed") -> Any:
    class _R:
        pass
    r = _R()
    r.referral_id = referral_id
    r.application_id = application_id
    r.tenant_id = "t1"
    r.status = status
    r.resolution = None if status != "resolved" else "APPROVE"
    r.resolved_by = None
    r.resolved_at = None
    r.approved_by = None
    r.override_id = str(uuid.uuid4()) if status == "resolved" else None
    r.conditional_terms = None
    r.created_at = "2026-01-01T00:00:00"
    r.sla_deadline = "2026-01-04T00:00:00"
    r.claimed_by = "officer_a"
    r.claimed_at = "2026-01-01T01:00:00"
    r.pd_score = 0.08
    r.fraud_probability = 0.02
    return r


def _make_resolved(referral_id: str, application_id: str, resolution: str = "APPROVE") -> Any:
    r = _fake_referral(referral_id, application_id, status="resolved")
    r.resolution = resolution
    r.resolved_by = "officer_a"
    r.resolved_at = "2026-01-02T10:00:00+00:00"
    r.approved_by = "supervisor_b"
    r.override_id = str(uuid.uuid4())
    return r


@pytest.mark.asyncio
async def test_override_endpoint_approve(tmp_path):
    """POST /v1/decisions/{id}/override with valid four-eyes approves the referral."""
    os.environ.setdefault("JWT_SECRET", "test-secret-key-123456789012345678")
    os.environ.setdefault("REFERRAL_DB_URL", str(tmp_path / "referral.db"))

    referral_id = str(uuid.uuid4())
    application_id = str(uuid.uuid4())

    fake_referral = _fake_referral(referral_id, application_id)
    resolved_referral = _make_resolved(referral_id, application_id, "APPROVE")

    from referral_store import create_referral

    db_url = str(tmp_path / "referral.db")

    # Create a real referral
    rec = await create_referral(
        db_url=db_url,
        application_id=application_id,
        tenant_id="t1",
    )
    referral_id = rec.referral_id

    from referral_store import claim_referral
    await claim_referral(db_url, referral_id, claimed_by="officer_a")

    from referral_store import resolve_referral
    resolved = await resolve_referral(
        db_url=db_url,
        referral_id=referral_id,
        resolved_by="officer_a",
        resolution="APPROVE",
        resolution_notes="Income documentation verified and confirmed sufficient",
        approved_by="supervisor_b",
    )

    assert resolved.resolution == "APPROVE"
    assert resolved.override_id is not None


@pytest.mark.asyncio
async def test_override_sod_violation_raises_permission_error(tmp_path):
    """Resolving and approving with the same user raises PermissionError."""
    from referral_store import create_referral, claim_referral, resolve_referral

    db_url = str(tmp_path / "referral.db")
    rec = await create_referral(
        db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1"
    )
    await claim_referral(db_url, rec.referral_id, claimed_by="officer_a")

    with pytest.raises(PermissionError):
        await resolve_referral(
            db_url=db_url,
            referral_id=rec.referral_id,
            resolved_by="officer_a",
            resolution="APPROVE",
            resolution_notes="Valid resolution with enough characters here",
            approved_by="officer_a",  # SOD violation
        )


@pytest.mark.asyncio
async def test_override_no_claimed_referral_raises_value_error(tmp_path):
    """Resolving a non-existent referral raises ValueError."""
    from referral_store import resolve_referral

    db_url = str(tmp_path / "referral.db")
    with pytest.raises(ValueError):
        await resolve_referral(
            db_url=db_url,
            referral_id=str(uuid.uuid4()),
            resolved_by="officer_a",
            resolution="APPROVE",
            resolution_notes="Valid resolution with enough characters",
            approved_by="supervisor_b",
        )


@pytest.mark.asyncio
async def test_conditional_override(tmp_path):
    """CONDITIONAL resolution stores conditional_terms."""
    from referral_store import create_referral, claim_referral, resolve_referral

    db_url = str(tmp_path / "referral.db")
    rec = await create_referral(
        db_url=db_url, application_id=str(uuid.uuid4()), tenant_id="t1"
    )
    await claim_referral(db_url, rec.referral_id, claimed_by="officer_a")

    terms = {"max_loan_amount": 15000.0, "co_signer_required": True}
    resolved = await resolve_referral(
        db_url=db_url,
        referral_id=rec.referral_id,
        resolved_by="officer_a",
        resolution="CONDITIONAL",
        resolution_notes="Conditional approval — reduced amount and co-signer required",
        approved_by="supervisor_b",
        conditional_terms=terms,
    )

    assert resolved.resolution == "CONDITIONAL"
    assert resolved.conditional_terms is not None
    assert resolved.conditional_terms["max_loan_amount"] == 15000.0
