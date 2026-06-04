"""Prompt 3: Contract hardening tests for enriched cash-flow fields in ApplicantInput."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.contracts import ApplicantInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = dict(
    application_id="test-app",
    loan_amount=5000.0,
    loan_purpose="personal",
    loan_term_months=24,
    annual_income=50000.0,
    employment_status="employed",
)


def make_input(**kwargs) -> dict:
    return {**BASE, **kwargs}


# ---------------------------------------------------------------------------
# Backward compatibility — old payload without enriched fields still works
# ---------------------------------------------------------------------------

def test_old_payload_without_enriched_fields_valid():
    inp = ApplicantInput(**BASE)
    assert inp.monthly_net_income is None
    assert inp.nsfv_last_90_days is None
    assert inp.income_confidence is None


# ---------------------------------------------------------------------------
# Valid enriched fields
# ---------------------------------------------------------------------------

def test_valid_enriched_fields_accepted():
    inp = ApplicantInput(**make_input(
        monthly_net_income=4000.0,
        avg_monthly_end_balance=2500.0,
        min_balance_90d=-100.0,   # can be negative (overdraft)
        nsfv_last_90_days=0,
        returned_payment_count=1,
        gambling_transaction_count=0,
        payday_loan_detected=False,
        large_unusual_deposit_count=0,
        income_confidence=0.90,
        bank_enrichment_provider="plaid",
    ))
    assert inp.monthly_net_income == 4000.0
    assert inp.income_confidence == 0.90
    assert inp.payday_loan_detected is False


# ---------------------------------------------------------------------------
# Bounds validation
# ---------------------------------------------------------------------------

def test_monthly_net_income_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(monthly_net_income=-1.0))


def test_avg_monthly_end_balance_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(avg_monthly_end_balance=-0.01))


def test_nsfv_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(nsfv_last_90_days=-1))


def test_returned_payment_count_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(returned_payment_count=-1))


def test_gambling_count_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(gambling_transaction_count=-1))


def test_large_deposit_count_must_be_non_negative():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(large_unusual_deposit_count=-1))


def test_income_confidence_lower_bound():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(income_confidence=-0.1))


def test_income_confidence_upper_bound():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(income_confidence=1.1))


def test_income_confidence_boundary_zero_valid():
    inp = ApplicantInput(**make_input(income_confidence=0.0))
    assert inp.income_confidence == 0.0


def test_income_confidence_boundary_one_valid():
    inp = ApplicantInput(**make_input(income_confidence=1.0))
    assert inp.income_confidence == 1.0


# ---------------------------------------------------------------------------
# Null handling
# ---------------------------------------------------------------------------

def test_all_enriched_fields_nullable():
    inp = ApplicantInput(**make_input(
        monthly_net_income=None,
        nsfv_last_90_days=None,
        payday_loan_detected=None,
        income_confidence=None,
        bank_enrichment_provider=None,
    ))
    assert inp.monthly_net_income is None
    assert inp.nsfv_last_90_days is None


# ---------------------------------------------------------------------------
# min_balance_90d can be negative (overdraft scenario)
# ---------------------------------------------------------------------------

def test_min_balance_90d_accepts_negative():
    inp = ApplicantInput(**make_input(min_balance_90d=-500.0))
    assert inp.min_balance_90d == -500.0


def test_provider_string_length_capped():
    with pytest.raises(ValidationError):
        ApplicantInput(**make_input(bank_enrichment_provider="x" * 65))
