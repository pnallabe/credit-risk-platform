"""
Tests for config_registry staging workflow (G11-A).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from compliance.rbac import SeparationOfDutiesViolation
from config_registry.service import ConfigRegistryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc():
    """Return a ConfigRegistryService backed by a temp SQLite DB."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    service = ConfigRegistryService(db_url=db_path)
    service.ensure_tenant("t1", name="Tenant One")
    yield service


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stage_config_does_not_activate(svc):
    """Stage a config — get_staged() returns it, get_active() returns old."""
    # Publish an active config first
    svc.publish("t1", {"policy": "v1"}, approved_by="alice@co.com", note="initial")
    active_before = svc.get_active("t1")

    # Stage a new config
    staged = svc.stage_config("t1", {"policy": "staged"}, authored_by="bob@co.com", note="staged change")
    assert staged is not None
    assert getattr(staged, "status", None) == "staged"

    # get_staged() should return it
    pending = svc.get_staged("t1")
    assert pending is not None
    assert pending.config_version == staged.config_version

    # get_active() should still return the old active
    active_after = svc.get_active("t1")
    assert active_after is not None
    assert active_after.config_version == active_before.config_version  # type: ignore[union-attr]


def test_approve_staged_config_activates(svc):
    """Approve a staged config with different approver — get_active() is updated."""
    svc.publish("t1", {"policy": "v1"}, approved_by="alice@co.com", note="initial")
    staged = svc.stage_config("t1", {"policy": "v2"}, authored_by="bob@co.com", note="new policy")

    approved = svc.approve_staged_config(
        tenant_id="t1",
        staged_version_tag=staged.config_version,
        approver_email="carol@co.com",
        actor_email="bob@co.com",
    )
    assert getattr(approved, "status", None) == "active"

    active = svc.get_active("t1")
    assert active is not None
    assert active.config_version == staged.config_version
    assert active.config_json == {"policy": "v2"}


def test_approve_same_actor_raises_separation_of_duties(svc):
    """actor_email == approver_email → SeparationOfDutiesViolation, old config unchanged."""
    svc.publish("t1", {"policy": "v1"}, approved_by="alice@co.com", note="initial")
    active_before = svc.get_active("t1")

    staged = svc.stage_config("t1", {"policy": "v2"}, authored_by="alice@co.com", note="change")
    with pytest.raises(SeparationOfDutiesViolation):
        svc.approve_staged_config(
            tenant_id="t1",
            staged_version_tag=staged.config_version,
            approver_email="alice@co.com",
            actor_email="alice@co.com",
        )

    # Active config should be unchanged
    active_after = svc.get_active("t1")
    assert active_after is not None
    assert active_after.config_version == active_before.config_version  # type: ignore[union-attr]


def test_reject_staged_config(svc):
    """Reject a staged config — get_active() is unchanged."""
    svc.publish("t1", {"policy": "v1"}, approved_by="alice@co.com", note="initial")
    active_before = svc.get_active("t1")

    staged = svc.stage_config("t1", {"policy": "v2"}, authored_by="bob@co.com", note="change")
    svc.reject_staged_config(
        tenant_id="t1",
        staged_version_tag=staged.config_version,
        rejected_by="carol@co.com",
        reason="Not ready",
    )

    # Active config should be unchanged
    active_after = svc.get_active("t1")
    assert active_after is not None
    assert active_after.config_version == active_before.config_version  # type: ignore[union-attr]

    # get_staged() should return None
    assert svc.get_staged("t1") is None


def test_stage_when_existing_staged_raises(svc):
    """Calling stage_config() when a staged version already exists raises ValueError."""
    svc.publish("t1", {"policy": "v1"}, approved_by="alice@co.com", note="initial")
    svc.stage_config("t1", {"policy": "v2"}, authored_by="bob@co.com", note="first stage")

    with pytest.raises(ValueError, match="staged version"):
        svc.stage_config("t1", {"policy": "v3"}, authored_by="carol@co.com", note="second stage")


def test_publish_backward_compat(svc):
    """publish() still works as before — no four-eyes required."""
    cv = svc.publish("t1", {"policy": "direct"}, approved_by="dev@co.com", note="dev bypass")
    assert svc.get_active("t1") is not None
    assert svc.get_active("t1").config_json == {"policy": "direct"}  # type: ignore[union-attr]
