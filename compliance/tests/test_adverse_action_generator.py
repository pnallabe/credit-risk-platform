"""Tests for compliance/adverse_action_generator.py (P2-B)"""
from __future__ import annotations

import pytest
from datetime import date, timedelta

from compliance.adverse_action_generator import (
    generate_notice,
    notice_to_dict,
    render_c1_text,
)


TENANT_CFG = {
    "creditor_name": "Acme Bank",
    "applicant_name": "John Smith",
    "bureau_config": {
        "bureau_name": "Experian",
        "credit_score_model_name": "FICO Score 8",
        "credit_score_range_low": 300,
        "credit_score_range_high": 850,
    },
}

REJECT_RESULT = {
    "decision": "REJECT",
    "reason_codes": ["AA01", "AA04"],
    "credit_score_used": 580,
}

APPROVE_RESULT = {
    "decision": "APPROVE",
    "reason_codes": [],
}


class FakeExplanation:
    top_negative_factors = [
        {"feature": "debt_to_income_ratio", "shap_value": -0.5, "direction": "negative"},
        {"feature": "credit_score", "shap_value": -0.4, "direction": "negative"},
    ]
    top_positive_factors = []


def test_generate_notice_reject_with_explanation():
    notice = generate_notice(
        application_id="app-001",
        tenant_id="t-001",
        decision_result=REJECT_RESULT,
        explanation_result=FakeExplanation(),
        tenant_config=TENANT_CFG,
    )
    assert 1 <= len(notice.reason_codes) <= 4
    assert len(notice.reason_texts) == len(notice.reason_codes)
    assert notice.application_id == "app-001"
    assert notice.creditor_name == "Acme Bank"
    assert notice.form_type == "C-1"


def test_generate_notice_approve_raises():
    with pytest.raises(ValueError, match="REJECT"):
        generate_notice(
            application_id="app-002",
            tenant_id="t-001",
            decision_result=APPROVE_RESULT,
            explanation_result=None,
            tenant_config=TENANT_CFG,
        )


def test_render_c1_text_contains_required_fields():
    notice = generate_notice("app-003", "t-001", REJECT_RESULT, None, TENANT_CFG)
    text = render_c1_text(notice)

    assert notice.applicant_name in text
    assert notice.creditor_name in text
    for rt in notice.reason_texts:
        assert rt in text


def test_render_c1_text_no_credit_score_block_when_none():
    cfg_no_score = dict(TENANT_CFG)
    reject_no_score = {"decision": "REJECT", "reason_codes": ["AA01"], "credit_score_used": None}
    notice = generate_notice("app-004", "t-001", reject_no_score, None, cfg_no_score)
    text = render_c1_text(notice)
    assert "Scores range" not in text


def test_render_c1_text_includes_credit_score_block():
    notice = generate_notice("app-005", "t-001", REJECT_RESULT, None, TENANT_CFG)
    text = render_c1_text(notice)
    assert str(REJECT_RESULT["credit_score_used"]) in text


def test_deadline_date_is_30_days_after_action_date():
    notice = generate_notice("app-006", "t-001", REJECT_RESULT, None, TENANT_CFG)
    action = date.fromisoformat(notice.action_date)
    deadline = date.fromisoformat(notice.deadline_date)
    assert (deadline - action).days == 30


def test_notice_to_dict_serialisable():
    import json
    notice = generate_notice("app-007", "t-001", REJECT_RESULT, None, TENANT_CFG)
    d = notice_to_dict(notice)
    # Must be JSON-serialisable
    serialised = json.dumps(d)
    assert "app-007" in serialised
