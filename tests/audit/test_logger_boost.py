"""
Targeted tests for audit/logger.py to boost coverage above 70%.
Focuses on log_portfolio_action, get_portfolio_audit_records,
and other functions not covered by existing audit/tests/ files.
"""
from __future__ import annotations

import pytest

from audit.logger import (
    _sha256,
    _mask_bank_account,
    mask_pii,
    log_portfolio_action,
    get_portfolio_audit_records,
)

DB_URL = "sqlite+aiosqlite://"


# ---------------------------------------------------------------------------
# Pure utility functions (always fast, no I/O)
# ---------------------------------------------------------------------------

def test_sha256_produces_hex_digest():
    h = _sha256("test-value")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_sha256_is_deterministic():
    assert _sha256("abc") == _sha256("abc")


def test_sha256_different_inputs_differ():
    assert _sha256("abc") != _sha256("def")


def test_mask_bank_account_short():
    result = _mask_bank_account("123")
    assert result == "****"


def test_mask_bank_account_long():
    result = _mask_bank_account("9876543210")
    assert result == "****3210"


def test_mask_bank_account_with_dashes():
    result = _mask_bank_account("1234-5678-9012")
    assert result.endswith("9012")
    assert result.startswith("****")


def test_mask_pii_ssn_is_hashed():
    features = {"ssn": "123-45-6789", "other": "unchanged"}
    masked = mask_pii(features)
    assert masked["ssn"] != "123-45-6789"
    assert len(masked["ssn"]) == 64  # SHA-256 hex
    assert masked["other"] == "unchanged"


def test_mask_pii_bank_account_is_masked():
    features = {"bank_account": "9876543210"}
    masked = mask_pii(features)
    assert masked["bank_account"] == "****3210"


def test_mask_pii_returns_copy():
    features = {"ssn": "123-45-6789"}
    masked = mask_pii(features)
    assert features["ssn"] == "123-45-6789"  # original unchanged


def test_mask_pii_empty_ssn_not_masked():
    features = {"ssn": ""}
    masked = mask_pii(features)
    assert masked["ssn"] == ""


# ---------------------------------------------------------------------------
# log_portfolio_action + get_portfolio_audit_records
# ---------------------------------------------------------------------------

def _portfolio_action_result(**kwargs):
    defaults = {
        "final_action": "INCREASE",
        "action_confidence": 0.85,
        "guardrail_reason": "",
        "current_credit_limit": 5000,
        "new_credit_limit": 7500,
        "current_apr": 19.99,
        "new_apr": 17.99,
        "cnpv_delta_base": 120.0,
        "cnpv_delta_worsening": 90.0,
        "cnpv_delta_recession": 50.0,
        "cnpv_delta_scenario_weighted": 95.0,
        "incremental_rwa_usd": 800.0,
    }
    defaults.update(kwargs)
    return defaults


@pytest.mark.asyncio
async def test_log_portfolio_action_returns_uuid():
    log_id = await log_portfolio_action(
        account_id="acct-001",
        review_month="2026-01",
        action_result=_portfolio_action_result(),
        feature_version="v1.0.0",
        model_version_portfolio="mlflow:v3",
        policy_version="v10.0",
        db_url=DB_URL,
    )
    assert isinstance(log_id, str)
    assert len(log_id) > 0


@pytest.mark.asyncio
async def test_log_portfolio_action_with_guardrail():
    log_id = await log_portfolio_action(
        account_id="acct-002",
        review_month="2026-01",
        action_result=_portfolio_action_result(
            guardrail_reason="PD too high for limit increase"
        ),
        feature_version="v1.0.0",
        model_version_portfolio="mlflow:v3",
        policy_version="v10.0",
        db_url=DB_URL,
    )
    assert isinstance(log_id, str)


@pytest.mark.asyncio
async def test_get_portfolio_audit_records_returns_list():
    results = await get_portfolio_audit_records("acct-unknown", DB_URL)
    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_log_then_get_portfolio_audit_records():
    acct = "acct-get-test"
    await log_portfolio_action(
        account_id=acct,
        review_month="2026-02",
        action_result=_portfolio_action_result(final_action="HOLD"),
        feature_version="v1.0.0",
        model_version_portfolio="mlflow:v4",
        policy_version="v10.1",
        db_url=DB_URL,
    )
    records = await get_portfolio_audit_records(acct, DB_URL)
    assert len(records) >= 1
    assert records[0]["recommended_action"] == "HOLD"
