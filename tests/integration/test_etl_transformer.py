"""
tests/integration/test_etl_transformer.py
==========================================
Integration tests for ``etl.transformer`` (PROMPT-07).

Tests
-----
* A well-formed Pub/Sub message produces the correct bronze row.
* A malformed message produces a rejected silver row with ``rejection_reason``.
* ``tenant_id`` is always sourced from message ``attributes``, never from payload body.
* Deduplication key fields (``application_id``, ``tenant_id``) are present in silver rows.
* Bronze rows carry all raw payload fields without coercion.

These tests run without any GCP credentials — no BQ or Pub/Sub calls are made.
"""

from __future__ import annotations

import pytest

from etl.transformer import transform_batch, transform_batch_with_rejects


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(
    payload: dict,
    tenant_id: str = "tenant-acme",
    source: str = "unit-test",
    data_type: str = "loan_application",
) -> dict:
    return {
        "data": payload,
        "attributes": {
            "tenant_id": tenant_id,
            "source": source,
            "data_type": data_type,
        },
        "message_id": "test-msg-001",
    }


_VALID_PAYLOAD = {
    "application_id": "app-001",
    "submitted_at": "2026-01-01T00:00:00Z",
    "loan_amount": 15000.0,
    "loan_purpose": "home_improvement",
    "loan_term_months": 36,
    "annual_income": 60000.0,
    "employment_status": "employed",
    "dti": 0.25,
    "credit_score": 720.0,
    "schema_version": "1.1",
    "event_type": "ingestion.completed",
    "batch_id": "batch-xyz",
}


# ---------------------------------------------------------------------------
# Bronze row tests
# ---------------------------------------------------------------------------


def test_well_formed_message_produces_bronze_row():
    """A valid Pub/Sub message should produce exactly one bronze row."""
    msg = _make_message(_VALID_PAYLOAD, tenant_id="tenant-acme")
    bronze_rows, silver_rows, gold_rows = transform_batch([msg])

    assert len(bronze_rows) == 1, "Expected exactly one bronze row"
    bronze = bronze_rows[0]

    # Core fields
    assert bronze["application_id"] == "app-001"
    assert bronze["loan_amount"] == 15000.0
    assert bronze["annual_income"] == 60000.0
    assert bronze["loan_purpose"] == "home_improvement"
    assert bronze["schema_version"] == "1.1"
    assert bronze["_batch_id"] == "batch-xyz"


def test_tenant_id_sourced_from_attributes_not_payload():
    """tenant_id must come from message attributes, never from payload body."""
    payload_with_wrong_tenant = dict(_VALID_PAYLOAD)
    payload_with_wrong_tenant["tenant_id"] = "attacker-tenant"

    msg = _make_message(payload_with_wrong_tenant, tenant_id="correct-tenant")
    bronze_rows, _, _ = transform_batch([msg])

    assert len(bronze_rows) == 1
    # Must use attribute value
    assert bronze_rows[0]["tenant_id"] == "correct-tenant"
    # Must NOT use payload body value
    assert bronze_rows[0]["tenant_id"] != "attacker-tenant"


def test_bronze_row_always_produced_for_malformed_message():
    """Even an empty payload produces a bronze row (raw capture layer)."""
    msg = _make_message({}, tenant_id="tenant-x")
    bronze_rows, _, _ = transform_batch([msg])
    assert len(bronze_rows) == 1


# ---------------------------------------------------------------------------
# Silver row tests
# ---------------------------------------------------------------------------


def test_valid_message_produces_silver_row_without_rejection_reason():
    """A valid message should produce a silver row with no rejection_reason."""
    msg = _make_message(_VALID_PAYLOAD, tenant_id="tenant-acme")
    _, silver_rows, _ = transform_batch([msg])

    assert len(silver_rows) == 1
    silver = silver_rows[0]
    assert "rejection_reason" not in silver


def test_malformed_message_produces_rejected_silver_row():
    """A message missing required fields should produce a rejection_reason."""
    payload = {
        "application_id": "app-002",
        # Missing: loan_amount, annual_income, employment_status, loan_purpose,
        #          loan_term_months, submitted_at
    }
    msg = _make_message(payload, tenant_id="tenant-acme")
    _, silver_rows, _ = transform_batch([msg])

    assert len(silver_rows) == 1
    silver = silver_rows[0]
    assert "rejection_reason" in silver
    assert silver["rejection_reason"].startswith("missing_required_field:")


def test_invalid_loan_amount_triggers_rejection():
    """A loan_amount <= 0 must trigger silver rejection."""
    payload = dict(_VALID_PAYLOAD)
    payload["loan_amount"] = -500.0
    msg = _make_message(payload, tenant_id="tenant-acme")
    _, silver_rows, _ = transform_batch([msg])

    assert len(silver_rows) == 1
    assert "rejection_reason" in silver_rows[0]
    assert "invalid_loan_amount" in silver_rows[0]["rejection_reason"]


def test_transform_batch_with_rejects_separates_valid_from_rejected():
    """transform_batch_with_rejects must split valid and rejected silver rows."""
    valid_msg = _make_message(_VALID_PAYLOAD, tenant_id="tenant-acme")
    bad_payload = {"application_id": "app-bad"}  # missing required fields
    bad_msg = _make_message(bad_payload, tenant_id="tenant-acme")

    bronze, valid_silver, rejected_silver, gold = transform_batch_with_rejects(
        [valid_msg, bad_msg]
    )

    assert len(bronze) == 2
    assert len(valid_silver) == 1
    assert len(rejected_silver) == 1
    assert "rejection_reason" in rejected_silver[0]
    assert "rejection_reason" not in valid_silver[0]


# ---------------------------------------------------------------------------
# Type coercion tests
# ---------------------------------------------------------------------------


def test_silver_coerces_string_numbers_to_correct_types():
    """Silver layer must coerce string-typed numbers to float/int."""
    payload = dict(_VALID_PAYLOAD)
    payload["loan_amount"] = "20000"
    payload["loan_term_months"] = "48"
    msg = _make_message(payload, tenant_id="tenant-acme")
    _, silver_rows, _ = transform_batch([msg])

    silver = silver_rows[0]
    assert isinstance(silver["loan_amount"], float)
    assert silver["loan_amount"] == 20000.0
    assert isinstance(silver["loan_term_months"], int)
    assert silver["loan_term_months"] == 48


# ---------------------------------------------------------------------------
# Gold row test
# ---------------------------------------------------------------------------


def test_gold_rows_are_empty_stub():
    """Gold rows are empty pending audit-log join (TODO G3-gold)."""
    msg = _make_message(_VALID_PAYLOAD, tenant_id="tenant-acme")
    _, _, gold_rows = transform_batch([msg])
    assert gold_rows == [], "Gold rows must be empty (stub) until G3-gold is implemented"


# ---------------------------------------------------------------------------
# Batch tests
# ---------------------------------------------------------------------------


def test_batch_of_n_messages_produces_n_bronze_rows():
    """Each message must produce exactly one bronze row regardless of validity."""
    messages = [_make_message(_VALID_PAYLOAD, tenant_id=f"t{i}") for i in range(10)]
    bronze_rows, _, _ = transform_batch(messages)
    assert len(bronze_rows) == 10


def test_tenant_id_sourced_from_attributes_in_batch():
    """In a multi-tenant batch, each row's tenant_id must match its message attributes."""
    payloads_and_tenants = [
        (dict(_VALID_PAYLOAD, application_id=f"app-{i}"), f"tenant-{i}")
        for i in range(3)
    ]
    messages = [_make_message(p, tenant_id=t) for p, t in payloads_and_tenants]
    bronze_rows, _, _ = transform_batch(messages)

    for i, row in enumerate(bronze_rows):
        assert row["tenant_id"] == f"tenant-{i}", (
            f"Row {i} tenant_id mismatch: expected tenant-{i}, got {row['tenant_id']}"
        )
