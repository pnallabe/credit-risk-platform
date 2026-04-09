"""Tests for compliance/adverse_action_store.py (P2-D)"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import date, timedelta
from sqlalchemy.ext.asyncio import create_async_engine


TENANT_CFG = {
    "creditor_name": "Acme Bank",
    "applicant_name": "Test User",
    "bureau_config": {
        "bureau_name": "Equifax",
        "credit_score_model_name": "FICO Score 8",
        "credit_score_range_low": 300,
        "credit_score_range_high": 850,
    },
}
REJECT_RESULT = {"decision": "REJECT", "reason_codes": ["AA01"], "credit_score_used": 580}


async def _make_url():
    import uuid as _uuid
    return f"sqlite+aiosqlite:///:memory:{_uuid.uuid4().hex}"


async def _setup(url: str):
    from audit.logger import _ENGINE_CACHE
    engine = create_async_engine(url, echo=False)
    _ENGINE_CACHE[url] = engine
    return engine


def _make_notice(suffix: str = "001", tenant_id: str = "t-store"):
    from compliance.adverse_action_generator import generate_notice
    return generate_notice(
        application_id=f"app-{suffix}",
        tenant_id=tenant_id,
        decision_result=REJECT_RESULT,
        explanation_result=None,
        tenant_config=TENANT_CFG,
    )


def _render(notice):
    from compliance.adverse_action_generator import render_c1_text
    return render_c1_text(notice)


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_notice_returns_notice_id():
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action_store import save_notice

    notice = _make_notice("s001")
    nid = await save_notice(notice, _render(notice), url)

    assert nid == notice.notice_id

    await engine.dispose()


@pytest.mark.asyncio
async def test_mark_delivered_updates_status():
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action_store import save_notice, mark_delivered, get_notice
    from datetime import datetime, timezone

    notice = _make_notice("s002")
    await save_notice(notice, _render(notice), url)

    now = datetime.now(timezone.utc).isoformat()
    await mark_delivered(notice.notice_id, "email", now, url, "t-store")

    record = await get_notice(notice.notice_id, url, "t-store")
    assert record is not None
    assert record["delivery_status"] == "DELIVERED"

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_deadline_notices():
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action_store import save_notice, get_pending_deadline_notices
    from compliance.adverse_action import AdverseActionNotice
    import uuid
    from datetime import datetime, timezone

    today = date.today()
    deadline_3days = (today + timedelta(days=3)).isoformat()

    notice = AdverseActionNotice(
        notice_id=str(uuid.uuid4()),
        application_id="app-deadline",
        tenant_id="t-store",
        applicant_name="Deadline User",
        creditor_name="Acme Bank",
        action_taken="Application Denied",
        action_date=today.isoformat(),
        deadline_date=deadline_3days,
        reason_codes=["AA01"],
        reason_texts=["High probability of default based on credit history"],
        form_type="C-1",
        credit_score_used=None,
        credit_score_range_low=None,
        credit_score_range_high=None,
        credit_score_model_name=None,
        bureau_name=None,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    await save_notice(notice, "test notice text", url)

    results = await get_pending_deadline_notices(url, "t-store", warn_days_before=5)
    assert len(results) >= 1
    assert any(r["notice_id"] == notice.notice_id for r in results)

    await engine.dispose()


@pytest.mark.asyncio
async def test_save_duplicate_raises_value_error():
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action_store import save_notice

    notice = _make_notice("s003")
    await save_notice(notice, _render(notice), url)

    with pytest.raises(ValueError, match="already exists"):
        await save_notice(notice, _render(notice), url)

    await engine.dispose()


@pytest.mark.asyncio
async def test_hash_chain_intact_across_three_notices():
    url = await _make_url()
    engine = await _setup(url)

    from compliance.adverse_action_store import save_notice
    from audit.chain_verifier import verify_chain

    for i in range(3):
        notice = _make_notice(f"chain-{i:03d}")
        await save_notice(notice, _render(notice), url)

    result = await verify_chain(url, "t-store", table="adverse_action_log")
    assert result.rows_checked == 3
    assert result.verified is True

    await engine.dispose()
