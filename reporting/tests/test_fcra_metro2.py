"""Acceptance tests for reporting/fcra_metro2.py (G5-B)."""

from __future__ import annotations

import io
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.fcra_metro2 import (  # noqa: E402
    CRLF,
    RECORD_LENGTH,
    Metro2Record,
    export_metro2,
    format_record,
    from_audit_log_record,
    validate_record_length,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_record(**kwargs) -> Metro2Record:
    defaults = dict(
        subscriber_id="SUB000001",
        account_number="ACCT-12345-ABC",
        ssn="123456789",
        date_of_birth=date(1980, 5, 15),
        first_name="JANE",
        middle_name="A",
        last_name="DOE",
        generation_code=" ",
        account_type="12",
        portfolio_type="I",
        date_opened=date(2024, 1, 1),
        credit_limit=10000,
        highest_credit_amount=10000,
        terms_duration="036",
        terms_frequency="M",
        scheduled_monthly_payment=300,
        actual_payment=300,
        account_status="11",
        payment_rating="0",
        payment_history_1="C",
        current_balance=8000,
        amount_past_due=0,
        original_charge_off=None,
        date_account_information=date(2025, 1, 1),
        first_delinquency_date=None,
        date_closed=None,
        date_last_payment=date(2024, 12, 1),
        address_1="123 MAIN ST",
        address_2="",
        city="ANYTOWN",
        state="CA",
        zip_code="900001234",
        country_code="  ",
        telephone_number="5551234567",
        ecoa_code="1",
        consumer_info_indicator=" ",
        country_of_citizenship_1="US",
        country_of_citizenship_2="  ",
        removal_indicator=" ",
        residence_code="O",
        mortgage_type="  ",
        interest_type_indicator=" ",
    )
    defaults.update(kwargs)
    return Metro2Record(**defaults)


# ---------------------------------------------------------------------------
# Test 1: format_record returns exactly 426 characters
# ---------------------------------------------------------------------------

def test_record_is_exactly_426_chars():
    rec = _minimal_record()
    formatted = format_record(rec)
    assert len(formatted) == RECORD_LENGTH, (
        f"Expected {RECORD_LENGTH} chars, got {len(formatted)}"
    )


# ---------------------------------------------------------------------------
# Test 2: validate_record_length accepts valid record
# ---------------------------------------------------------------------------

def test_validate_record_length_valid():
    rec = _minimal_record()
    line = format_record(rec)
    assert validate_record_length(line)


# ---------------------------------------------------------------------------
# Test 3: validate_record_length rejects wrong length
# ---------------------------------------------------------------------------

def test_validate_record_length_invalid():
    assert not validate_record_length("A" * 425)
    assert not validate_record_length("A" * 427)
    assert not validate_record_length("")


# ---------------------------------------------------------------------------
# Test 4: export_metro2 adds CRLF after each record
# ---------------------------------------------------------------------------

def test_export_adds_crlf():
    rec = _minimal_record()
    output = export_metro2([rec])
    lines = output.split(CRLF)
    # Last element will be empty string after the final CRLF
    assert lines[0] != ""
    assert lines[-1] == ""


# ---------------------------------------------------------------------------
# Test 5: export_metro2 with multiple records → correct line count
# ---------------------------------------------------------------------------

def test_export_multiple_records():
    records = [_minimal_record(account_number=f"ACCT-{i:04d}") for i in range(3)]
    output = export_metro2(records)
    lines = [l for l in output.split(CRLF) if l]
    assert len(lines) == 3
    for line in lines:
        assert len(line) == RECORD_LENGTH


# ---------------------------------------------------------------------------
# Test 6: None date fields render as 00000000
# ---------------------------------------------------------------------------

def test_none_date_renders_as_zeros():
    rec = _minimal_record(first_delinquency_date=None, date_closed=None)
    formatted = format_record(rec)
    # Verify that "00000000" appears at least twice (for first_delinquency_date and date_closed)
    count = formatted.count("00000000")
    assert count >= 2, (
        f"Expected at least 2 occurrences of '00000000' for None dates, found {count}"
    )


# ---------------------------------------------------------------------------
# Test 7: Numeric fields are zero-padded to correct width
# ---------------------------------------------------------------------------

def test_numeric_zero_padding():
    rec = _minimal_record(current_balance=42)
    formatted = format_record(rec)
    # current_balance is 7 chars wide
    # Find "0000042" in the formatted string
    assert "0000042" in formatted


# ---------------------------------------------------------------------------
# Test 8: SSN with hyphens is normalised
# ---------------------------------------------------------------------------

def test_ssn_normalised():
    rec = _minimal_record(ssn="123-45-6789")
    formatted = format_record(rec)
    assert "123456789" in formatted


# ---------------------------------------------------------------------------
# Test 9: from_audit_log_record builds Metro2Record
# ---------------------------------------------------------------------------

def test_from_audit_log_record_basic():
    audit_rec = {
        "application_id": "APP-XYZ",
        "decision_output": "APPROVE",
        "loan_amount": 5000,
        "borrower_state": "TX",
        "logged_at": "2025-03-15",
    }
    m2 = from_audit_log_record(audit_rec, subscriber_id="SUB000001")
    assert isinstance(m2, Metro2Record)
    assert "APP-XYZ" in m2.account_number
    assert m2.account_status == "11"  # APPROVE → STATUS_CURRENT
    assert m2.state == "TX"


# ---------------------------------------------------------------------------
# Test 10: from_audit_log_record → DECLINE maps to charge-off status
# ---------------------------------------------------------------------------

def test_from_audit_log_record_decline_status():
    audit_rec = {
        "application_id": "APP-DENY",
        "decision_output": "DECLINE",
        "loan_amount": 0,
        "logged_at": "2025-01-01",
    }
    m2 = from_audit_log_record(audit_rec, subscriber_id="SUB000002")
    assert m2.account_status == "97"  # charge-off code
