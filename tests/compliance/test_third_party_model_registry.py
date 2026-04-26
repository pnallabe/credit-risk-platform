"""
Smoke tests for compliance/third_party_model_registry.py
"""
from __future__ import annotations

from compliance.third_party_model_registry import (
    FCRA_AA_REQUIRED_FIELDS,
    THIRD_PARTY_MODELS,
    check_fcra_aa_fields,
    check_third_party_validation_due,
    get_third_party_summary,
)


# ---------------------------------------------------------------------------
# Registry constants
# ---------------------------------------------------------------------------

def test_third_party_models_non_empty():
    assert len(THIRD_PARTY_MODELS) >= 2


def test_known_models_present():
    assert "bureau_fico_score_9" in THIRD_PARTY_MODELS
    assert "bureau_vantagescore_4" in THIRD_PARTY_MODELS


def test_model_entries_have_required_keys():
    required = {"vendor", "version", "use_case", "validation_required", "validation_cycle_months"}
    for model_id, meta in THIRD_PARTY_MODELS.items():
        missing = required - meta.keys()
        assert not missing, f"Model '{model_id}' missing keys: {missing}"


def test_fcra_required_fields_four_fields():
    assert len(FCRA_AA_REQUIRED_FIELDS) == 4


# ---------------------------------------------------------------------------
# check_fcra_aa_fields
# ---------------------------------------------------------------------------

def test_check_fcra_aa_fields_pass_with_all_fields():
    notice = {
        "consumer_reporting_agency_name": "Equifax",
        "consumer_reporting_agency_address": "123 Main St",
        "consumer_report_right_to_dispute_url": "https://equifax.com/dispute",
        "free_disclosure_phone": "1-800-555-0000",
    }
    missing = check_fcra_aa_fields(notice)
    assert missing == []


def test_check_fcra_aa_fields_returns_missing_fields():
    notice = {
        "consumer_reporting_agency_name": "Experian",
        # missing: address, url, phone
    }
    missing = check_fcra_aa_fields(notice)
    assert "consumer_reporting_agency_address" in missing
    assert "consumer_report_right_to_dispute_url" in missing
    assert "free_disclosure_phone" in missing


def test_check_fcra_aa_fields_empty_notice_misses_all():
    missing = check_fcra_aa_fields({})
    assert len(missing) == 4


# ---------------------------------------------------------------------------
# get_third_party_summary
# ---------------------------------------------------------------------------

def test_get_third_party_summary_returns_all_models():
    summary = get_third_party_summary()
    assert isinstance(summary, list)
    assert len(summary) == len(THIRD_PARTY_MODELS)


def test_third_party_summary_has_required_keys():
    summary = get_third_party_summary()
    for entry in summary:
        for key in ("model_id", "vendor", "version", "use_case", "validation_status"):
            assert key in entry, f"Missing key '{key}' in summary entry for {entry.get('model_id')}"


def test_third_party_validation_due_no_bq_returns_list():
    """Without BigQuery, falls back to returning models requiring validation."""
    result = check_third_party_validation_due()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# check_contract_review_due
# ---------------------------------------------------------------------------

def test_check_contract_review_due_returns_list():
    from compliance.third_party_model_registry import check_contract_review_due
    result = check_contract_review_due()
    assert isinstance(result, list)
    # All entries should be dicts
    for entry in result:
        assert isinstance(entry, dict)
        assert "model_id" in entry
