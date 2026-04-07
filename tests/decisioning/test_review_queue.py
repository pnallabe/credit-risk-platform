from __future__ import annotations

import pandas as pd

from decisioning.review_queue import ReviewQueue


def test_enqueue_and_get_pending() -> None:
    q = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
    q.enqueue("app_1", pd_score=0.12, features={"x": 1})
    pending = q.get_pending(limit=10)
    assert len(pending) == 1
    assert pending[0].application_id == "app_1"


def test_sla_breach_detection() -> None:
    q = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
    it = q.enqueue("app_1", pd_score=0.12, features={"x": 1}, sla_hours=0)
    breached = q.check_sla_breaches()
    assert any(b.item_id == it.item_id for b in breached)


def test_complete_sets_status() -> None:
    q = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")
    it = q.enqueue("app_1", pd_score=0.12, features={"x": 1})
    it2 = q.complete(it.item_id, override_decision="APPROVE", override_reason_code="POLICY_EXCEPTION")
    assert it2.status == "COMPLETED"
    assert q.get_pending(limit=10) == []


def test_feedback_export_only_includes_overrides(tmp_path) -> None:
    q = ReviewQueue(db_url="sqlite+pysqlite:///:memory:")

    it1 = q.enqueue("app_1", pd_score=0.12, features={"x": 1})
    it2 = q.enqueue("app_2", pd_score=0.20, features={"x": 2})

    # Not a final decision → excluded from training feedback export
    q.complete(it1.item_id, override_decision="REFER_TO_SENIOR", override_reason_code="MANUAL_ESCALATION")

    # Final override → included
    q.complete(it2.item_id, override_decision="DECLINE", override_reason_code="POLICY_EXCEPTION")

    out = tmp_path / "feedback.parquet"
    n = q.export_feedback(out)
    assert n == 1

    df = pd.read_parquet(out)
    assert len(df) == 1
    assert set(df.columns) == {"application_id", "original_features", "override_decision", "completed_at"}
    assert df.iloc[0]["application_id"] == "app_2"
