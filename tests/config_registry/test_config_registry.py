"""
tests/config_registry/test_config_registry.py
=============================================
Tests for the P2.1 Tenant Config Registry (ConfigRegistryService + models).

Coverage:
  * publish creates a new version and auto-activates
  * resolving active config returns correct JSON
  * no-op publish is rejected
  * rollback creates a new version pointing to the target, and activates it
  * rollback event records from/to version correctly
  * diff returns key-level changes
  * tenant isolation: tenant A cannot see tenant B config
  * audit events are recorded for publish and rollback
  * ConfigDiff.is_empty()
"""

from __future__ import annotations

import pytest

from config_registry.models import ConfigDiff, TenantConfigVersion, diff_configs
from config_registry.service import ConfigRegistryService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def svc(tmp_path):
    """Return a ConfigRegistryService backed by a temp SQLite file."""
    db_path = str(tmp_path / "test_config_registry.db")
    return ConfigRegistryService(db_url=db_path)


@pytest.fixture()
def tenant_a(svc):
    return svc.ensure_tenant("tenant_a", name="Tenant A", tier="enterprise")


@pytest.fixture()
def tenant_b(svc):
    return svc.ensure_tenant("tenant_b", name="Tenant B")


# ---------------------------------------------------------------------------
# TenantRecord
# ---------------------------------------------------------------------------


def test_ensure_tenant_creates_record(svc):
    t = svc.ensure_tenant("acme", name="Acme Corp")
    assert t.tenant_id == "acme"
    assert t.status == "active"
    assert t.active_config_version is None


def test_ensure_tenant_idempotent(svc):
    svc.ensure_tenant("acme", name="Acme Corp")
    svc.ensure_tenant("acme", name="Acme Corp Again")  # should not raise
    assert svc.get_tenant("acme").name == "Acme Corp"  # original name preserved


def test_list_tenants(svc, tenant_a, tenant_b):
    tenants = svc.list_tenants()
    ids = {t.tenant_id for t in tenants}
    assert "tenant_a" in ids
    assert "tenant_b" in ids


def test_list_tenants_by_status(svc, tenant_a):
    active = svc.list_tenants(status="active")
    assert any(t.tenant_id == "tenant_a" for t in active)


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


def test_publish_creates_first_version(svc, tenant_a):
    cfg = {"policy_cutoffs": {"pd_threshold": 0.10}}
    cv = svc.publish("tenant_a", cfg, approved_by="alice", note="init")
    assert cv.config_version == "v1"
    assert cv.config_json == cfg
    assert len(cv.config_sha256) == 64


def test_publish_activates_version(svc, tenant_a):
    svc.publish("tenant_a", {"policy_cutoffs": {"pd_threshold": 0.10}},
                approved_by="alice", note="init")
    t = svc.get_tenant("tenant_a")
    assert t.active_config_version == "v1"


def test_publish_sequential_versions(svc, tenant_a):
    svc.publish("tenant_a", {"policy_cutoffs": {"pd_threshold": 0.10}},
                approved_by="alice", note="v1")
    svc.publish("tenant_a", {"policy_cutoffs": {"pd_threshold": 0.12}},
                approved_by="alice", note="v2")
    active = svc.get_active("tenant_a")
    assert active.config_version == "v2"
    assert active.config_json["policy_cutoffs"]["pd_threshold"] == 0.12


def test_publish_requires_existing_tenant(svc):
    with pytest.raises(ValueError, match="not found"):
        svc.publish("nonexistent", {}, approved_by="alice", note="x")


def test_publish_rejects_noop(svc, tenant_a):
    cfg = {"policy_cutoffs": {"pd_threshold": 0.10}}
    svc.publish("tenant_a", cfg, approved_by="alice", note="init")
    with pytest.raises(ValueError, match="identical"):
        svc.publish("tenant_a", cfg, approved_by="alice", note="dup")


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_get_active_returns_none_before_publish(svc, tenant_a):
    assert svc.get_active("tenant_a") is None


def test_resolve_falls_back_to_empty_dict(svc, tenant_a):
    result = svc.resolve("tenant_a", fallback={"default": True})
    assert result == {"default": True}


def test_resolve_returns_active_config(svc, tenant_a):
    cfg = {"policy_cutoffs": {"pd_threshold": 0.08}}
    svc.publish("tenant_a", cfg, approved_by="alice", note="init")
    result = svc.resolve("tenant_a")
    assert result == cfg


def test_get_version_returns_specific_version(svc, tenant_a):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"v": 2}, approved_by="alice", note="v2")
    cv = svc.get_version("tenant_a", "v1")
    assert cv.config_json["v"] == 1


def test_get_version_returns_none_for_missing(svc, tenant_a):
    assert svc.get_version("tenant_a", "v99") is None


def test_list_versions_newest_first(svc, tenant_a):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"v": 2}, approved_by="alice", note="v2")
    versions = svc.list_versions("tenant_a")
    assert versions[0].config_version == "v2"
    assert versions[1].config_version == "v1"


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


def test_rollback_restores_target_config(svc, tenant_a):
    cfg_v1 = {"policy_cutoffs": {"pd_threshold": 0.10}}
    cfg_v2 = {"policy_cutoffs": {"pd_threshold": 0.20}}
    svc.publish("tenant_a", cfg_v1, approved_by="alice", note="v1")
    svc.publish("tenant_a", cfg_v2, approved_by="alice", note="v2")

    event = svc.rollback("tenant_a", "v1", rolled_back_by="bob", note="emergency")

    assert event.from_version == "v2"
    assert event.to_version == "v1"
    assert event.new_version_tag == "v3"

    active = svc.get_active("tenant_a")
    assert active.config_version == "v3"
    assert active.config_json == cfg_v1
    assert active.is_rollback is True
    assert active.rollback_source_version == "v1"


def test_rollback_records_sha256_from_target(svc, tenant_a):
    cfg = {"policy_cutoffs": {"pd_threshold": 0.10}}
    v1 = svc.publish("tenant_a", cfg, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"policy_cutoffs": {"pd_threshold": 0.20}},
                approved_by="alice", note="v2")
    svc.rollback("tenant_a", "v1", rolled_back_by="bob", note="rb")

    active = svc.get_active("tenant_a")
    assert active.config_sha256 == v1.config_sha256


def test_rollback_requires_valid_target(svc, tenant_a):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="v1")
    with pytest.raises(ValueError, match="not found"):
        svc.rollback("tenant_a", "v99", rolled_back_by="bob", note="bad")


def test_rollback_requires_active_config(svc, tenant_a):
    with pytest.raises(ValueError, match="no active config"):
        svc.rollback("tenant_a", "v1", rolled_back_by="bob", note="bad")


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


def test_tenant_isolation_config(svc, tenant_a, tenant_b):
    """Each tenant's config is scoped; tenant B cannot read tenant A's config."""
    svc.publish("tenant_a", {"sensitive": "a_only"}, approved_by="alice", note="a")
    svc.publish("tenant_b", {"sensitive": "b_only"}, approved_by="bob",   note="b")

    a_active = svc.get_active("tenant_a")
    b_active = svc.get_active("tenant_b")

    assert a_active.config_json["sensitive"] == "a_only"
    assert b_active.config_json["sensitive"] == "b_only"
    assert a_active.config_json != b_active.config_json


def test_tenant_isolation_versions(svc, tenant_a, tenant_b):
    """list_versions for tenant_a must not include tenant_b rows."""
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="a")
    svc.publish("tenant_b", {"v": 1}, approved_by="bob",   note="b")

    a_versions = svc.list_versions("tenant_a")
    assert all(v.tenant_id == "tenant_a" for v in a_versions)


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


def test_diff_detects_added_key(svc, tenant_a):
    svc.publish("tenant_a", {"a": 1}, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"a": 1, "b": 2}, approved_by="alice", note="v2")
    d = svc.diff("tenant_a", "v1", "v2")
    assert "b" in d.added
    assert not d.removed


def test_diff_detects_changed_key(svc, tenant_a):
    svc.publish("tenant_a", {"threshold": 0.10}, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"threshold": 0.15}, approved_by="alice", note="v2")
    d = svc.diff("tenant_a", "v1", "v2")
    assert "threshold" in d.changed
    assert d.changed["threshold"] == (0.10, 0.15)


def test_diff_raises_for_missing_version(svc, tenant_a):
    svc.publish("tenant_a", {"a": 1}, approved_by="alice", note="v1")
    with pytest.raises(ValueError):
        svc.diff("tenant_a", "v1", "v99")


def test_config_diff_is_empty():
    d = ConfigDiff()
    assert d.is_empty()
    d.added.append("x")
    assert not d.is_empty()


def test_diff_configs_standalone():
    old = {"a": 1, "b": 2}
    new = {"b": 3, "c": 4}
    d = diff_configs(old, new)
    assert d.added == ["c"]
    assert d.removed == ["a"]
    assert "b" in d.changed


# ---------------------------------------------------------------------------
# Audit events
# ---------------------------------------------------------------------------


def test_audit_events_recorded_on_publish(svc, tenant_a):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="init")
    events = svc.get_audit_events("tenant_a")
    assert any(e["event_type"] == "publish" for e in events)


def test_audit_events_recorded_on_rollback(svc, tenant_a):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="v1")
    svc.publish("tenant_a", {"v": 2}, approved_by="alice", note="v2")
    svc.rollback("tenant_a", "v1", rolled_back_by="bob", note="rb")
    events = svc.get_audit_events("tenant_a")
    assert any(e["event_type"] == "rollback" for e in events)


def test_audit_events_tenant_scoped(svc, tenant_a, tenant_b):
    svc.publish("tenant_a", {"v": 1}, approved_by="alice", note="a")
    svc.publish("tenant_b", {"v": 1}, approved_by="bob",   note="b")
    events_a = svc.get_audit_events("tenant_a")
    assert all(e["tenant_id"] == "tenant_a" for e in events_a)


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------


def test_tenant_config_version_as_dict(svc, tenant_a):
    svc.publish("tenant_a", {"policy_cutoffs": {"pd_threshold": 0.1}},
                approved_by="alice", note="init")
    active = svc.get_active("tenant_a")
    d = active.as_dict()
    assert "config_version" in d
    assert "config_sha256" in d
    assert d["approved_by"] == "alice"


def test_tenant_config_version_helpers(svc, tenant_a):
    cfg = {
        "policy_cutoffs": {"pd_threshold": 0.12},
        "feature_toggles": {"thin_file_enrich": True},
        "pricing_overrides": {"base_rate": 0.07},
        "rate_limits": {"decisions_per_minute": 1000},
    }
    svc.publish("tenant_a", cfg, approved_by="alice", note="full")
    active = svc.get_active("tenant_a")
    assert active.get_policy_cutoffs() == {"pd_threshold": 0.12}
    assert active.get_feature_toggles() == {"thin_file_enrich": True}
    assert active.get_pricing_overrides() == {"base_rate": 0.07}
    assert active.get_rate_limits() == {"decisions_per_minute": 1000}
