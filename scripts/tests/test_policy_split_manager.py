"""Acceptance tests for scripts/policy_split_manager.py (G4-D)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decision_engine.policy_challenger import PolicyChallengerConfig, PolicySplitStore  # noqa: E402
from scripts.policy_split_manager import main  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def in_memory_db(tmp_path) -> str:
    """Return a unique in-memory SQLite URL (different connection per fixture call)."""
    # Use a named file URL so the store can be recreated with the same data
    db_file = tmp_path / "policy_split_test.db"
    return f"sqlite:///{db_file}"


def _cfg(role, tag, version_id=1, traffic_pct=0.5, tenant_id="tenant-a"):
    return PolicyChallengerConfig(
        role=role,
        version_id=version_id,
        version_tag=tag,
        traffic_pct=traffic_pct,
        tenant_id=tenant_id,
    )


def _set_split(db_url: str, champ_tag="v1", chall_tag="v2") -> PolicySplitStore:
    store = PolicySplitStore(db_url=db_url)
    store.set_split(
        _cfg("CHAMPION", champ_tag, version_id=1),
        _cfg("CHALLENGER", chall_tag, version_id=2),
    )
    return store


# ---------------------------------------------------------------------------
# Tests: status subcommand
# ---------------------------------------------------------------------------


def test_status_no_split_configured(in_memory_db, capsys):
    exit_code = main(["status", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert exit_code == 0
    assert body["status"] == "no split configured"


def test_status_active_split(in_memory_db, capsys):
    _set_split(in_memory_db)
    exit_code = main(["status", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert exit_code == 0
    assert body["status"] == "active"
    assert body["champion"]["version_tag"] == "v1"
    assert body["challenger"]["version_tag"] == "v2"


# ---------------------------------------------------------------------------
# Tests: promote-challenger subcommand
# ---------------------------------------------------------------------------


def test_promote_challenger_succeeds(in_memory_db, capsys):
    _set_split(in_memory_db)
    exit_code = main(["promote-challenger", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert exit_code == 0
    assert body["status"] == "promoted"
    assert body["new_champion_version_tag"] == "v2"


def test_promote_challenger_fails_when_no_split(in_memory_db, capsys):
    exit_code = main(["promote-challenger", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    assert exit_code == 1


def test_new_champion_is_stored_after_promote(in_memory_db, capsys):
    _set_split(in_memory_db)
    main(["promote-challenger", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    capsys.readouterr()  # clear output

    # Now check status
    main(["status", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert body["champion"]["version_tag"] == "v2"


# ---------------------------------------------------------------------------
# Tests: check-rollback subcommand
# ---------------------------------------------------------------------------


def test_check_rollback_no_regression_exit0(in_memory_db, capsys):
    """With equal approval rates delta = 0 → PROMOTE → exit 0."""
    from datetime import datetime, timezone

    from decision_engine.policy_challenger import PolicyDecisionRecord

    store = _set_split(in_memory_db)
    now = datetime.now(timezone.utc)
    for i in range(4):
        store.add(
            PolicyDecisionRecord(
                application_id=f"c-{i}",
                timestamp=now,
                tenant_id="tenant-a",
                role="CHAMPION",
                version_id=1,
                version_tag="v1",
                decision="APPROVE",
                apr=0.1,
                credit_limit=5000.0,
                is_shadow=False,
            )
        )
    for i in range(4):
        store.add(
            PolicyDecisionRecord(
                application_id=f"ch-{i}",
                timestamp=now,
                tenant_id="tenant-a",
                role="CHALLENGER",
                version_id=2,
                version_tag="v2",
                decision="APPROVE",
                apr=0.1,
                credit_limit=5000.0,
                is_shadow=False,
            )
        )

    exit_code = main(["check-rollback", "--tenant-id", "tenant-a", "--db-url", in_memory_db])
    out = capsys.readouterr().out
    body = json.loads(out)
    assert exit_code == 0
    assert body["rolled_back"] is False


def test_check_rollback_regression_exit2(in_memory_db, capsys):
    """Challenger 0% approval vs champion 100% → REJECT → exit 2."""
    from datetime import datetime, timezone

    from decision_engine.policy_challenger import PolicyDecisionRecord

    store = _set_split(in_memory_db)
    now = datetime.now(timezone.utc)
    for i in range(5):
        store.add(
            PolicyDecisionRecord(
                application_id=f"c-{i}",
                timestamp=now,
                tenant_id="tenant-a",
                role="CHAMPION",
                version_id=1,
                version_tag="v1",
                decision="APPROVE",
                apr=0.1,
                credit_limit=5000.0,
                is_shadow=False,
            )
        )
    for i in range(5):
        store.add(
            PolicyDecisionRecord(
                application_id=f"ch-{i}",
                timestamp=now,
                tenant_id="tenant-a",
                role="CHALLENGER",
                version_id=2,
                version_tag="v2",
                decision="DECLINE",
                apr=None,
                credit_limit=None,
                is_shadow=False,
            )
        )

    exit_code = main(
        ["check-rollback", "--tenant-id", "tenant-a", "--db-url", in_memory_db, "--lookback-days", "14"]
    )
    out = capsys.readouterr().out
    body = json.loads(out)
    assert exit_code == 2
    assert body["rolled_back"] is True
    assert body["recommendation"] == "REJECT"
