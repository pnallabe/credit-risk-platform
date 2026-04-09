"""Tests for compliance/adverse_action.py (P2-A)"""
from __future__ import annotations

from compliance.adverse_action import (
    AdverseActionNotice,
    REG_B_REASON_CODES,
    map_shap_factors_to_reg_b_codes,
    select_form_type,
)


def test_map_shap_factors_dti():
    factors = [
        {"feature": "debt_to_income_ratio", "shap_value": -0.4, "direction": "negative"},
        {"feature": "credit_score", "shap_value": -0.3, "direction": "negative"},
    ]
    codes = map_shap_factors_to_reg_b_codes(factors)
    assert "SHAP_DTI" in codes


def test_map_shap_factors_ordering():
    """Codes must be ordered by |shap_value| descending."""
    factors = [
        {"feature": "annual_income", "shap_value": -0.1, "direction": "negative"},
        {"feature": "credit_score", "shap_value": -0.9, "direction": "negative"},
        {"feature": "debt_to_income_ratio", "shap_value": -0.5, "direction": "negative"},
    ]
    codes = map_shap_factors_to_reg_b_codes(factors)
    assert codes[0] == "SHAP_CREDIT_SCORE"
    assert codes[1] == "SHAP_DTI"


def test_map_shap_factors_max_four():
    factors = [
        {"feature": f"unknown_{i}", "shap_value": -float(i), "direction": "negative"}
        for i in range(1, 10)
    ]
    codes = map_shap_factors_to_reg_b_codes(factors)
    assert len(codes) <= 4


def test_map_shap_factors_fallback():
    """Unknown features fall back to AA01."""
    factors = [{"feature": "totally_unknown_feature", "shap_value": -0.9, "direction": "negative"}]
    codes = map_shap_factors_to_reg_b_codes(factors)
    assert codes == ["AA01"]


def test_adverse_action_notice_constructable():
    notice = AdverseActionNotice(
        notice_id="n-001",
        application_id="app-001",
        tenant_id="t-001",
        applicant_name="Jane Doe",
        creditor_name="Acme Bank",
        action_taken="Application Denied",
        action_date="2026-04-07",
        deadline_date="2026-05-07",
        reason_codes=["AA01"],
        reason_texts=["High probability of default based on credit history"],
        form_type="C-1",
        credit_score_used=620,
        credit_score_range_low=300,
        credit_score_range_high=850,
        credit_score_model_name="FICO Score 8",
        bureau_name="Experian",
        generated_at="2026-04-07T00:00:00Z",
    )
    assert notice.notice_id == "n-001"
    assert notice.form_type == "C-1"
    assert notice.delivery_status == "PENDING"


def test_select_form_type_denial():
    assert select_form_type("denial") == "C-1"


def test_select_form_type_counter_offer():
    assert select_form_type("counter_offer") == "C-2"


def test_select_form_type_incomplete():
    assert select_form_type("incomplete") == "C-3"


def test_reg_b_reason_codes_not_empty():
    assert len(REG_B_REASON_CODES) > 0
    assert "AA01" in REG_B_REASON_CODES
    assert "SHAP_DTI" in REG_B_REASON_CODES
