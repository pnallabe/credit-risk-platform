"""Tests for WaiverStore (S5-A)."""

from __future__ import annotations

import tempfile
import os
import pytest
from datetime import datetime, timezone, timedelta

from compliance.waiver_store import WaiverStore, Waiver


@pytest.fixture
def store(tmp_path):
    db = str(tmp_path / "test_waivers.db")
    return WaiverStore(db_path=db)


def _req(store: WaiverStore, **kwargs) -> Waiver:
    defaults = dict(
        application_id="APP-001",
        policy_rule_id="RULE_DTI_LIMIT",
        policy_rule_description="DTI must not exceed 0.43",
        waiver_reason="Senior manager override for strategic client",
        requested_by="alice@example.com",
    )
    defaults.update(kwargs)
    return store.request_waiver(**defaults)


class TestWaiverStore:
    def test_request_creates_pending_waiver(self, store):
        w = _req(store)
        assert w.status == "pending"
        assert w.waiver_id
        assert w.policy_rule_id == "RULE_DTI_LIMIT"

    def test_approve_sets_status(self, store):
        w = _req(store)
        approved = store.approve_waiver(w.waiver_id, approved_by="bob@example.com")
        assert approved.status == "approved"
        assert approved.approved_by == "bob@example.com"

    def test_four_eyes_same_user_cannot_approve(self, store):
        w = _req(store, requested_by="alice@example.com")
        with pytest.raises(PermissionError, match="Four-eyes"):
            store.approve_waiver(w.waiver_id, approved_by="alice@example.com")

    def test_deny_sets_status(self, store):
        w = _req(store)
        denied = store.deny_waiver(w.waiver_id, denied_by="carol@example.com", denial_reason="Not justified")
        assert denied.status == "denied"
        assert denied.denial_reason == "Not justified"

    def test_cannot_approve_already_denied(self, store):
        w = _req(store)
        store.deny_waiver(w.waiver_id, "carol", "Nope")
        with pytest.raises(ValueError, match="not pending"):
            store.approve_waiver(w.waiver_id, "bob")

    def test_cannot_deny_already_approved(self, store):
        w = _req(store)
        store.approve_waiver(w.waiver_id, "bob")
        with pytest.raises(ValueError, match="not pending"):
            store.deny_waiver(w.waiver_id, "carol", "Too late")

    def test_get_waiver_returns_correct(self, store):
        w = _req(store)
        fetched = store.get_waiver(w.waiver_id)
        assert fetched.waiver_id == w.waiver_id

    def test_get_waiver_not_found_raises(self, store):
        with pytest.raises(KeyError):
            store.get_waiver("nonexistent-id")

    def test_list_waivers_all(self, store):
        for i in range(5):
            _req(store, application_id=f"APP-{i:03d}")
        waivers = store.list_waivers()
        assert len(waivers) == 5

    def test_list_waivers_filter_by_status(self, store):
        w1 = _req(store, application_id="APP-001")
        w2 = _req(store, application_id="APP-002")
        store.approve_waiver(w1.waiver_id, "bob")
        pending = store.list_waivers(status="pending")
        approved = store.list_waivers(status="approved")
        assert len(pending) == 1
        assert len(approved) == 1
        assert pending[0].waiver_id == w2.waiver_id

    def test_list_waivers_limit_offset(self, store):
        for i in range(10):
            _req(store, application_id=f"APP-{i:03d}")
        page1 = store.list_waivers(limit=5, offset=0)
        page2 = store.list_waivers(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {w.waiver_id for w in page1}
        ids2 = {w.waiver_id for w in page2}
        assert ids1.isdisjoint(ids2)

    def test_expire_stale_waivers(self, store):
        past_ts = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()
        future_ts = (datetime.now(tz=timezone.utc) + timedelta(hours=24)).isoformat()
        w_past = _req(store, application_id="APP-PAST", expires_at=past_ts)
        w_future = _req(store, application_id="APP-FUTURE", expires_at=future_ts)
        w_none = _req(store, application_id="APP-NONE")

        count = store.expire_stale_waivers()
        assert count == 1
        assert store.get_waiver(w_past.waiver_id).status == "expired"
        assert store.get_waiver(w_future.waiver_id).status == "pending"
        assert store.get_waiver(w_none.waiver_id).status == "pending"

    def test_generate_report(self, store):
        w1 = _req(store, application_id="APP-001")
        w2 = _req(store, application_id="APP-002")
        store.approve_waiver(w1.waiver_id, "bob")
        store.deny_waiver(w2.waiver_id, "carol", "Not justified")
        _req(store, application_id="APP-003")

        report = store.generate_report(period_days=30)
        assert report["total_requested"] == 3
        assert report["total_approved"] == 1
        assert report["total_denied"] == 1
        assert 0.0 <= report["approval_rate"] <= 1.0

    def test_report_by_policy_rule(self, store):
        for i in range(3):
            _req(store, application_id=f"APP-{i}", policy_rule_id="RULE_A")
        for i in range(3, 5):
            _req(store, application_id=f"APP-{i}", policy_rule_id="RULE_B")

        report = store.generate_report(period_days=30)
        rule_ids = {r["rule_id"] for r in report["by_policy_rule"]}
        assert "RULE_A" in rule_ids
        assert "RULE_B" in rule_ids
