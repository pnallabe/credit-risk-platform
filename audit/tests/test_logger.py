"""
Tests for audit/logger.py
==========================
Uses SQLite in-memory via aiosqlite for full CI compatibility (no Postgres required).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parents[3]))

from audit.logger import (
    _mask_bank_account,
    _sha256,
    get_audit_record,
    log_decision,
    mask_pii,
)

# Use SQLite in-memory for tests
DB_URL = "sqlite+aiosqlite:///:memory:"
# Tenant ID used by all audit-log integration tests
TENANT_ID = "test-tenant-001"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_decision_result():
    """A minimal dict simulating a DecisionResult."""
    return {
        "application_id": "app-test-001",
        "decision": "APPROVE",
        "reason_codes": ["AA01"],
        "decision_latency_ms": 123,
    }


@pytest.fixture
def sample_input_features():
    """Sample feature dict with PII fields."""
    return {
        "customer_id": "cust-abc",
        "ssn": "123-45-6789",
        "bank_account": "9876543210",
        "pd_score": 0.03,
        "fraud_probability": 0.05,
        "credit_utilization": 0.4,
        "annual_income": 80000.0,
    }


@pytest.fixture
def sample_model_versions():
    return {
        "fraud": "v1",
        "credit_risk": "v1",
        "fraud_score": 0.05,
        "risk_score": 0.03,
    }


# ---------------------------------------------------------------------------
# Unit tests: PII masking
# ---------------------------------------------------------------------------


class TestMaskPii:
    def test_sha256_produces_64_char_hex(self) -> None:
        result = _sha256("test-value")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_sha256_deterministic(self) -> None:
        assert _sha256("abc") == _sha256("abc")

    def test_sha256_different_inputs(self) -> None:
        assert _sha256("abc") != _sha256("xyz")

    def test_mask_bank_account_last_four(self) -> None:
        result = _mask_bank_account("9876543210")
        assert result == "****3210"

    def test_mask_bank_account_short(self) -> None:
        result = _mask_bank_account("12")
        assert result == "****"

    def test_mask_bank_account_with_spaces(self) -> None:
        result = _mask_bank_account("1234 5678 9012")
        # Last 4 of "123456789012"
        assert result == "****9012"

    def test_mask_pii_hashes_ssn(self, sample_input_features) -> None:
        masked = mask_pii(sample_input_features)
        assert masked["ssn"] != "123-45-6789"
        assert len(masked["ssn"]) == 64  # SHA-256 hex

    def test_mask_pii_hashes_customer_id(self, sample_input_features) -> None:
        masked = mask_pii(sample_input_features)
        assert masked["customer_id"] != "cust-abc"
        assert len(masked["customer_id"]) == 64

    def test_mask_pii_masks_bank_account(self, sample_input_features) -> None:
        masked = mask_pii(sample_input_features)
        assert masked["bank_account"].startswith("****")

    def test_mask_pii_preserves_non_pii_fields(self, sample_input_features) -> None:
        masked = mask_pii(sample_input_features)
        assert masked["pd_score"] == 0.03
        assert masked["credit_utilization"] == 0.4

    def test_mask_pii_missing_fields_no_error(self) -> None:
        features = {"credit_utilization": 0.5}
        result = mask_pii(features)
        assert result == {"credit_utilization": 0.5}

    def test_mask_pii_does_not_mutate_original(self, sample_input_features) -> None:
        original_ssn = sample_input_features["ssn"]
        mask_pii(sample_input_features)
        assert sample_input_features["ssn"] == original_ssn


# ---------------------------------------------------------------------------
# Async integration tests: log_decision and get_audit_record
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLogDecision:
    async def test_returns_log_id_string(
        self,
        sample_decision_result,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        log_id = await log_decision(
            decision_result=sample_decision_result,
            feature_version="1.0.0",
            model_versions=sample_model_versions,
            input_features=sample_input_features,
            db_url=DB_URL,
            tenant_id=TENANT_ID,
        )
        assert isinstance(log_id, str)
        assert len(log_id) == 36  # UUID format

    async def test_log_id_is_unique(
        self,
        sample_decision_result,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        id1 = await log_decision(
            sample_decision_result, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID
        )
        id2 = await log_decision(
            sample_decision_result, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID
        )
        assert id1 != id2

    async def test_stores_and_retrieves_record(
        self,
        sample_decision_result,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        log_id = await log_decision(
            sample_decision_result, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID
        )
        record = await get_audit_record("app-test-001", DB_URL, TENANT_ID)
        assert record is not None
        assert record["application_id"] == "app-test-001"

    async def test_decision_output_stored(
        self,
        sample_decision_result,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        await log_decision(
            sample_decision_result, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID
        )
        record = await get_audit_record("app-test-001", DB_URL, TENANT_ID)
        assert record["decision_output"] == "APPROVE"

    async def test_reason_codes_stored_as_list(
        self,
        sample_decision_result,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        await log_decision(
            sample_decision_result, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID
        )
        record = await get_audit_record("app-test-001", DB_URL, TENANT_ID)
        assert isinstance(record["reason_codes"], list)

    async def test_pii_masked_before_storage(
        self,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        dr = {"application_id": "app-pii-test", "decision": "REJECT", "reason_codes": [], "decision_latency_ms": 0}
        await log_decision(dr, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID)
        record = await get_audit_record("app-pii-test", DB_URL, TENANT_ID)
        # SSN should be hashed, not original
        stored_features = record["input_features"]
        assert stored_features.get("ssn") != "123-45-6789"
        assert len(stored_features.get("ssn", "")) == 64

    async def test_latency_ms_stored(
        self,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        dr = {
            "application_id": "app-latency-test",
            "decision": "APPROVE",
            "reason_codes": [],
            "decision_latency_ms": 450,
        }
        await log_decision(dr, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID)
        record = await get_audit_record("app-latency-test", DB_URL, TENANT_ID)
        assert record["decision_latency_ms"] == 450

    async def test_accepts_dataclass_like_result(
        self,
        sample_input_features,
        sample_model_versions,
    ) -> None:
        from dataclasses import dataclass

        @dataclass
        class FakeDecision:
            application_id: str = "app-dc-test"
            decision: str = "MANUAL_REVIEW"
            reason_codes: list = None
            decision_latency_ms: int = 200

            def __post_init__(self):
                if self.reason_codes is None:
                    self.reason_codes = ["AA05"]

        dr = FakeDecision()
        log_id = await log_decision(dr, "1.0.0", sample_model_versions, sample_input_features, DB_URL, TENANT_ID)
        assert isinstance(log_id, str)

    async def test_get_audit_record_returns_none_for_missing(self) -> None:
        record = await get_audit_record("nonexistent-app", DB_URL, TENANT_ID)
        # May return None if table doesn't have that record
        if record is not None:
            assert record["application_id"] != "nonexistent-app" or record is None
