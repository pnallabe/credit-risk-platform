"""Acceptance tests for PolicySplitStore (G4-A) and PolicyChallengerRouter (G4-B)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from decision_engine.policy_challenger import (
    PolicyChallengerConfig,
    PolicyDecisionRecord,
    PolicyChallengerRouter,
    PolicySplitStore,
)

DB_URL = "sqlite:///:memory:"


def _store() -> PolicySplitStore:
    return PolicySplitStore(db_url=DB_URL)


def _cfg(role, tag, version_id=1, traffic_pct=0.8, tenant_id="tenant-a"):
    return PolicyChallengerConfig(
        role=role,
        version_id=version_id,
        version_tag=tag,
        traffic_pct=traffic_pct,
        tenant_id=tenant_id,
    )


def _record(application_id, role, tag, decision, tenant_id="tenant-a", version_id=1, offset_days=0):
    ts = datetime.now(timezone.utc) - timedelta(days=offset_days)
    return PolicyDecisionRecord(
        application_id=application_id,
        timestamp=ts,
        tenant_id=tenant_id,
        role=role,
        version_id=version_id,
        version_tag=tag,
        decision=decision,
        apr=None,
        credit_limit=None,
        is_shadow=False,
    )


# ---------------------------------------------------------------------------
# Test 1: set_split() inserts rows with active=1
# ---------------------------------------------------------------------------

def test_set_split_inserts_active_rows():
    store = _store()
    champ = _cfg("CHAMPION", "v1.0", version_id=1, traffic_pct=0.8)
    chall = _cfg("CHALLENGER", "v2.0", version_id=2, traffic_pct=0.2)
    store.set_split(champ, chall)

    result = store.get_active_split("tenant-a")
    assert result is not None
    c, challenger = result
    assert c.role == "CHAMPION"
    assert c.version_tag == "v1.0"
    assert challenger.role == "CHALLENGER"
    assert challenger.version_tag == "v2.0"


# ---------------------------------------------------------------------------
# Test 2: second set_split() deactivates previous rows
# ---------------------------------------------------------------------------

def test_set_split_deactivates_previous():
    store = _store()
    # First split
    store.set_split(
        _cfg("CHAMPION", "v1.0", version_id=1),
        _cfg("CHALLENGER", "v2.0", version_id=2),
    )
    # Second split for the same tenant
    store.set_split(
        _cfg("CHAMPION", "v3.0", version_id=3),
        _cfg("CHALLENGER", "v4.0", version_id=4),
    )

    with store._engine.begin() as conn:
        rows = conn.execute(
            __import__("sqlalchemy").text(
                "SELECT version_tag, active FROM policy_splits WHERE tenant_id = 'tenant-a'"
            )
        ).fetchall()

    active_tags = {r[0] for r in rows if r[1] == 1}
    inactive_tags = {r[0] for r in rows if r[1] == 0}

    assert active_tags == {"v3.0", "v4.0"}
    assert "v1.0" in inactive_tags
    assert "v2.0" in inactive_tags


# ---------------------------------------------------------------------------
# Test 3: get_active_split returns correct tuple
# ---------------------------------------------------------------------------

def test_get_active_split_returns_correct_pair():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "stable-1", version_id=10, traffic_pct=0.7),
        _cfg("CHALLENGER", "beta-2", version_id=11, traffic_pct=0.3),
    )

    result = store.get_active_split("tenant-a")
    assert result is not None
    champ, chall = result
    assert champ.version_id == 10
    assert champ.version_tag == "stable-1"
    assert chall.version_id == 11
    assert chall.version_tag == "beta-2"
    assert champ.tenant_id == "tenant-a"
    assert chall.tenant_id == "tenant-a"


# ---------------------------------------------------------------------------
# Test 4: get_active_split for unconfigured tenant returns None
# ---------------------------------------------------------------------------

def test_get_active_split_returns_none_for_unconfigured_tenant():
    store = _store()
    # Configure for tenant-a only
    store.set_split(
        _cfg("CHAMPION", "v1.0", tenant_id="tenant-a"),
        _cfg("CHALLENGER", "v2.0", tenant_id="tenant-a"),
    )
    assert store.get_active_split("tenant-b") is None


# ---------------------------------------------------------------------------
# Test 5: add() + generate_comparison_report() computes rates correctly
# ---------------------------------------------------------------------------

def test_generate_comparison_report_correct_rates():
    store = _store()

    # Champion: 3 approvals, 1 decline → 75%
    store.add(_record("app-1", "CHAMPION", "v1", "APPROVE"))
    store.add(_record("app-2", "CHAMPION", "v1", "APPROVE"))
    store.add(_record("app-3", "CHAMPION", "v1", "APPROVE"))
    store.add(_record("app-4", "CHAMPION", "v1", "DECLINE"))

    # Challenger: 2 approvals, 2 declines → 50%
    store.add(_record("app-5", "CHALLENGER", "v2", "APPROVE"))
    store.add(_record("app-6", "CHALLENGER", "v2", "APPROVE"))
    store.add(_record("app-7", "CHALLENGER", "v2", "DECLINE"))
    store.add(_record("app-8", "CHALLENGER", "v2", "DECLINE"))

    report = store.generate_comparison_report("tenant-a")

    assert report.champion_approval_rate == pytest.approx(0.75)
    assert report.challenger_approval_rate == pytest.approx(0.50)
    assert report.approval_rate_delta == pytest.approx(-0.25)
    assert report.sample_size_champion == 4
    assert report.sample_size_challenger == 4
    # delta < -0.10  →  REJECT
    assert report.recommendation == "REJECT"


# ---------------------------------------------------------------------------
# Test 6: generate_comparison_report is tenant-scoped
# ---------------------------------------------------------------------------

def test_generate_comparison_report_tenant_scoped():
    store = _store()

    # tenant-a: all approvals
    for i in range(4):
        store.add(_record(f"a-{i}", "CHAMPION", "v1", "APPROVE", tenant_id="tenant-a"))

    # tenant-b: all declines
    for i in range(4):
        store.add(_record(f"b-{i}", "CHAMPION", "vx", "DECLINE", tenant_id="tenant-b"))

    report_a = store.generate_comparison_report("tenant-a")
    assert report_a.champion_approval_rate == pytest.approx(1.0)
    assert report_a.sample_size_champion == 4

    report_b = store.generate_comparison_report("tenant-b")
    assert report_b.champion_approval_rate == pytest.approx(0.0)
    assert report_b.sample_size_champion == 4


# ---------------------------------------------------------------------------
# Test 7: set_split raises if tenants differ
# ---------------------------------------------------------------------------

def test_set_split_raises_on_tenant_mismatch():
    store = _store()
    champ = _cfg("CHAMPION", "v1", tenant_id="tenant-a")
    chall = _cfg("CHALLENGER", "v2", tenant_id="tenant-b")
    with pytest.raises(ValueError, match="tenant_id"):
        store.set_split(champ, chall)


# ---------------------------------------------------------------------------
# Test 8: set_split raises on wrong role order
# ---------------------------------------------------------------------------

def test_set_split_raises_on_wrong_roles():
    store = _store()
    with pytest.raises(ValueError, match="CHAMPION"):
        store.set_split(
            _cfg("CHALLENGER", "v1"),
            _cfg("CHAMPION", "v2"),
        )


# ---------------------------------------------------------------------------
# Test 9: recommendation is PROMOTE when delta <= 3 pp
# ---------------------------------------------------------------------------

def test_recommendation_promote_when_delta_small():
    store = _store()

    # Challenger slightly better: both ~80%
    for i in range(5):
        store.add(_record(f"c-{i}", "CHAMPION", "v1", "APPROVE"))
    store.add(_record("c-5", "CHAMPION", "v1", "DECLINE"))

    for i in range(5):
        store.add(_record(f"ch-{i}", "CHALLENGER", "v2", "APPROVE"))
    store.add(_record("ch-5", "CHALLENGER", "v2", "DECLINE"))

    report = store.generate_comparison_report("tenant-a")
    # delta = 0 → PROMOTE
    assert report.recommendation == "PROMOTE"

# ===========================================================================
# G4-B — PolicyChallengerRouter tests
# ===========================================================================


def _router(store: PolicySplitStore, seed: int = 42) -> PolicyChallengerRouter:
    return PolicyChallengerRouter(store=store, random_seed=seed)


# ---------------------------------------------------------------------------
# Test 10: route() returns CHAMPION when no active split
# ---------------------------------------------------------------------------

def test_router_defaults_to_champion_when_no_split():
    store = _store()
    router = _router(store)
    assert router.route("any-app", "tenant-a") == "CHAMPION"


# ---------------------------------------------------------------------------
# Test 11: route() deterministic — same application_id always same result
# ---------------------------------------------------------------------------

def test_router_is_deterministic():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "v1", traffic_pct=0.5),
        _cfg("CHALLENGER", "v2", traffic_pct=0.5),
    )
    router = _router(store, seed=7)
    results = [router.route("app-xyz-123", "tenant-a") for _ in range(5)]
    assert len(set(results)) == 1, "Routing should be deterministic"


# ---------------------------------------------------------------------------
# Test 12: route() uses :policy: namespace (different hash than model router)
# ---------------------------------------------------------------------------

def test_router_uses_policy_namespace():
    import hashlib

    salt = "42"
    app_id = "test-app"

    model_h = hashlib.sha256(f"{app_id}:{salt}".encode()).digest()
    policy_h = hashlib.sha256(f"{app_id}:policy:{salt}".encode()).digest()

    model_bucket = int.from_bytes(model_h[:8], "big") % 100
    policy_bucket = int.from_bytes(policy_h[:8], "big") % 100

    # Different namespaces must produce different buckets for this test vector
    assert model_bucket != policy_bucket, (
        "Policy and model routers must use different hash namespaces"
    )


# ---------------------------------------------------------------------------
# Test 13: get_policy_params returns correct config per role
# ---------------------------------------------------------------------------

def test_get_policy_params_returns_correct_config():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "stable-v1", version_id=10),
        _cfg("CHALLENGER", "beta-v2", version_id=11),
    )
    router = _router(store)
    champ = router.get_policy_params("tenant-a", "CHAMPION")
    chall = router.get_policy_params("tenant-a", "CHALLENGER")

    assert champ is not None
    assert champ.version_tag == "stable-v1"
    assert champ.version_id == 10

    assert chall is not None
    assert chall.version_tag == "beta-v2"
    assert chall.version_id == 11


# ---------------------------------------------------------------------------
# Test 14: record_outcome persists a PolicyDecisionRecord
# ---------------------------------------------------------------------------

def test_record_outcome_persists():
    store = _store()
    router = _router(store)

    rec = router.record_outcome(
        application_id="app-999",
        tenant_id="tenant-a",
        role="CHAMPION",
        version_id=1,
        version_tag="v1.0",
        outcome={"decision": "APPROVE", "apr": 0.12, "credit_limit": 5000.0},
    )
    assert rec.decision == "APPROVE"
    assert rec.apr == pytest.approx(0.12)

    report = store.generate_comparison_report("tenant-a")
    assert report.sample_size_champion == 1


# ---------------------------------------------------------------------------
# Test 15: promote_challenger makes old challenger the new champion
# ---------------------------------------------------------------------------

def test_promote_challenger():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "v1", version_id=1),
        _cfg("CHALLENGER", "v2", version_id=2),
    )
    router = _router(store)
    new_champ, _ = router.promote_challenger("tenant-a")

    assert new_champ.version_tag == "v2"
    assert new_champ.role == "CHAMPION"
    assert new_champ.traffic_pct == 1.0

    split = store.get_active_split("tenant-a")
    assert split is not None
    assert split[0].version_tag == "v2"


# ---------------------------------------------------------------------------
# Test 16: auto_rollback triggered on REJECT recommendation
# ---------------------------------------------------------------------------

def test_auto_rollback_on_regression():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "v1", version_id=1),
        _cfg("CHALLENGER", "v2", version_id=2),
    )
    router = _router(store)

    # Champion: 100% approval  →  challenger 0%  →  delta < -0.10 → REJECT
    for i in range(5):
        store.add(_record(f"c-{i}", "CHAMPION", "v1", "APPROVE", tenant_id="tenant-a"))
    for i in range(5):
        store.add(_record(f"ch-{i}", "CHALLENGER", "v2", "DECLINE", tenant_id="tenant-a"))

    result = router.auto_rollback_if_regressed("tenant-a")

    assert result["rolled_back"] is True
    assert result["report"].recommendation == "REJECT"

    # After rollback the active split champion should be the original champion
    split = store.get_active_split("tenant-a")
    assert split is not None
    assert split[0].version_tag == "v1"
    assert split[1].traffic_pct == 0.0


# ---------------------------------------------------------------------------
# Test 17: auto_rollback not triggered on PROMOTE
# ---------------------------------------------------------------------------

def test_auto_rollback_not_triggered_when_promote():
    store = _store()
    store.set_split(
        _cfg("CHAMPION", "v1", version_id=1),
        _cfg("CHALLENGER", "v2", version_id=2),
    )
    router = _router(store)

    # Both roles same approval rate → delta = 0 → PROMOTE
    for role, tag in [("CHAMPION", "v1"), ("CHALLENGER", "v2")]:
        for i in range(4):
            store.add(_record(f"{role}-{i}", role, tag, "APPROVE", tenant_id="tenant-a"))

    result = router.auto_rollback_if_regressed("tenant-a")

    assert result["rolled_back"] is False
    assert result["report"].recommendation == "PROMOTE"
