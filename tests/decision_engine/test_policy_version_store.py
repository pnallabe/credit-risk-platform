"""
Tests for the P1.6 Policy Version Store
(decision_engine/policy_version_store.py).
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from decision_engine.policy_version_store import (
    PolicyVersion,
    PolicyVersionNotFoundError,
    PolicyVersionStore,
    extract_current_policy_parameters,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> PolicyVersionStore:
    """Fresh in-memory-like store using a tmp file."""
    return PolicyVersionStore(db_path=tmp_path / "test_policy_versions.db")


def _sample_params(version: int = 1) -> dict:
    return {
        "product_policies": {
            "basic": {
                "name": "basic",
                "min_fico": 620 + version,
                "max_dti": 0.50,
                "pd_hard_decline": 0.25,
            }
        }
    }


# ---------------------------------------------------------------------------
# publish / get_active
# ---------------------------------------------------------------------------


def test_publish_returns_int_id(store: PolicyVersionStore):
    version_id = store.publish(_sample_params(), author="test@example.com", note="init")
    assert isinstance(version_id, int)
    assert version_id > 0


def test_get_active_returns_latest(store: PolicyVersionStore):
    store.publish(_sample_params(1), author="alice", note="v1")
    store.publish(_sample_params(2), author="bob", note="v2")
    active = store.get_active()
    assert active.is_active
    assert active.note == "v2"


def test_only_one_active_version_at_a_time(store: PolicyVersionStore):
    store.publish(_sample_params(1), author="alice")
    store.publish(_sample_params(2), author="bob")
    store.publish(_sample_params(3), author="carol")
    all_versions = store.list_versions()
    active_count = sum(1 for v in all_versions if v.is_active)
    assert active_count == 1


def test_get_active_raises_when_empty(store: PolicyVersionStore):
    with pytest.raises(PolicyVersionNotFoundError):
        store.get_active()


def test_auto_version_tag(store: PolicyVersionStore):
    vid = store.publish(_sample_params(), author="alice")
    version = store.get_by_id(vid)
    assert version.version_tag.startswith("v")


def test_explicit_version_tag(store: PolicyVersionStore):
    vid = store.publish(_sample_params(), author="alice", version_tag="q1-2025")
    version = store.get_by_id(vid)
    assert version.version_tag == "q1-2025"


# ---------------------------------------------------------------------------
# get_as_of — point-in-time replay
# ---------------------------------------------------------------------------


def test_get_as_of_returns_correct_version(store: PolicyVersionStore):
    """Policy active before the second publish should be returned for past queries."""
    from datetime import timedelta

    t1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    store.publish(_sample_params(1), author="alice", note="jan", effective_from=t1)
    store.publish(_sample_params(2), author="bob", note="jun", effective_from=t2)

    # Query before t2: should get v1
    query_time = datetime(2024, 3, 15, tzinfo=timezone.utc)
    version = store.get_as_of(query_time)
    assert version.note == "jan"

    # Query after t2: should get v2
    version_after = store.get_as_of(datetime(2024, 9, 1, tzinfo=timezone.utc))
    assert version_after.note == "jun"


def test_get_as_of_raises_when_no_version_before_date(store: PolicyVersionStore):
    t_future = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store.publish(_sample_params(), author="alice", effective_from=t_future)

    # Query before any version was active
    t_past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(PolicyVersionNotFoundError):
        store.get_as_of(t_past)


def test_get_as_of_at_exact_effective_from(store: PolicyVersionStore):
    t = datetime(2024, 6, 1, tzinfo=timezone.utc)
    store.publish(_sample_params(1), author="alice", effective_from=t)
    version = store.get_as_of(t)
    assert version.is_active or version.effective_from <= t


# ---------------------------------------------------------------------------
# get_by_id
# ---------------------------------------------------------------------------


def test_get_by_id_retrieves_correct_row(store: PolicyVersionStore):
    id1 = store.publish(_sample_params(1), author="alice")
    id2 = store.publish(_sample_params(2), author="bob")

    v1 = store.get_by_id(id1)
    v2 = store.get_by_id(id2)

    assert v1.parameters["product_policies"]["basic"]["min_fico"] == 621
    assert v2.parameters["product_policies"]["basic"]["min_fico"] == 622


def test_get_by_id_raises_for_unknown(store: PolicyVersionStore):
    with pytest.raises(PolicyVersionNotFoundError):
        store.get_by_id(9999)


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------


def test_rollback_creates_new_version(store: PolicyVersionStore):
    id1 = store.publish(_sample_params(1), author="alice", note="v1")
    store.publish(_sample_params(2), author="bob", note="v2")

    rollback_id = store.rollback(target_version_id=id1, author="carol", note="emergency")

    # New version should exist
    rollback_v = store.get_by_id(rollback_id)
    assert rollback_v.is_active
    assert "rollback" in rollback_v.version_tag
    # Parameters should match v1
    assert (
        rollback_v.parameters["product_policies"]["basic"]["min_fico"]
        == _sample_params(1)["product_policies"]["basic"]["min_fico"]
    )


def test_rollback_does_not_delete_history(store: PolicyVersionStore):
    id1 = store.publish(_sample_params(1), author="alice")
    store.publish(_sample_params(2), author="bob")
    store.rollback(target_version_id=id1, author="carol")
    all_versions = store.list_versions(limit=100)
    assert len(all_versions) == 3  # v1, v2, rollback


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


def test_list_versions_ordered_newest_first(store: PolicyVersionStore):
    from datetime import timedelta

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(5):
        store.publish(_sample_params(i), author="a", effective_from=base + timedelta(days=i))
    versions = store.list_versions()
    dts = [v.effective_from for v in versions]
    assert dts == sorted(dts, reverse=True)


def test_list_versions_respects_limit(store: PolicyVersionStore):
    for i in range(10):
        store.publish(_sample_params(i), author="a")
    versions = store.list_versions(limit=3)
    assert len(versions) == 3


# ---------------------------------------------------------------------------
# export_audit_trail
# ---------------------------------------------------------------------------


def test_export_audit_trail_is_json_list(store: PolicyVersionStore):
    import json
    store.publish(_sample_params(1), author="alice")
    store.publish(_sample_params(2), author="bob")
    trail_json = store.export_audit_trail()
    trail = json.loads(trail_json)
    assert isinstance(trail, list)
    assert len(trail) == 2
    assert "version_tag" in trail[0]
    assert "parameters" in trail[0]


# ---------------------------------------------------------------------------
# extract_current_policy_parameters
# ---------------------------------------------------------------------------


def test_extract_current_policy_parameters_has_product_policies():
    params = extract_current_policy_parameters()
    assert "product_policies" in params
    assert "basic" in params["product_policies"]
    assert "min_fico" in params["product_policies"]["basic"]


def test_extracted_params_can_be_published(store: PolicyVersionStore):
    params = extract_current_policy_parameters()
    vid = store.publish(params, author="ci-system", note="initial snapshot")
    version = store.get_by_id(vid)
    assert "product_policies" in version.parameters
