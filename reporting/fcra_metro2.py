"""FCRA Metro 2® Format credit reporting export.

Implements a Metro 2® Base Segment record builder suitable for submission to
the major Credit Reporting Agencies (CRAs).  This module intentionally covers
only the Base Segment (426 characters per record) as defined by the Consumer
Data Industry Association (CDIA) Metro 2® specification.

Reference:
  CDIA Metro 2® Credit Reporting Resource Guide — Base Segment Layout

Field widths are FIXED.  All alphanumeric fields are left-justified and
space-padded; all numeric fields are right-justified and zero-padded.
Every generated record is exactly 426 characters followed by CRLF.

Disclaimer:
  This implementation is for internal reporting/audit purposes.
  Before production use, validate against the most current CDIA specification
  and your institution's data-furnisher agreement.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RECORD_LENGTH: int = 426          # Base Segment character count (excl. CRLF)
SEGMENT_IDENTIFIER: str = "5"     # Base Segment identifier per Metro 2 spec
CRLF: str = "\r\n"

# Metro 2 status codes (partial)
STATUS_CURRENT: str = "11"           # Account current; no problems
STATUS_30_DAYS: str = "71"           # 30 days past due
STATUS_60_DAYS: str = "78"           # 60 days past due
STATUS_90_DAYS: str = "80"           # 90 days past due
STATUS_120_DAYS: str = "82"          # 120+ days past due
STATUS_CHARGE_OFF: str = "97"        # Charge-off
STATUS_PAID_IN_FULL: str = "13"      # Paid in full / closed
STATUS_TRANSFER: str = "05"          # Transfer

# Account-type codes (partial)
ACCOUNT_TYPE_INSTALLMENT: str = "12"
ACCOUNT_TYPE_REVOLVING: str = "18"
ACCOUNT_TYPE_MORTGAGE: str = "26"

# ECOA codes
ECOA_INDIVIDUAL: str = "1"
ECOA_JOINT: str = "2"

# Compliance condition codes
COMPLIANCE_NA: str = "  "          # Two spaces = not applicable

# Portfolio type
PORTFOLIO_INSTALLMENT: str = "I"
PORTFOLIO_REVOLVING: str = "R"
PORTFOLIO_MORTGAGE: str = "M"
PORTFOLIO_OPEN: str = "O"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Metro2Record:
    """All fields required to build a Metro 2 Base Segment record.

    All date fields are ``date`` objects.  Monetary fields are integers in
    WHOLE dollars (Metro 2 does not support cents in most fields).

    Fields marked Optional default to blanks / zeros when None.
    """

    # Identification
    subscriber_id: str            # Positions 1-9   (9 chars) — assigned by CRA
    account_number: str           # Positions 10-35 (26 chars)
    ssn: str                      # Positions 36-44 (9 digits, no hyphens)
    date_of_birth: date           # Positions 45-52 (MMDDYYYY)
    first_name: str               # Positions 53-67 (15 chars)
    middle_name: str              # Positions 68-75 (8 chars)
    last_name: str                # Positions 76-90 (15 chars)
    generation_code: str          # Positions 91    (1 char: J/S/II/III/IV etc.)

    # Account information
    account_type: str             # Positions 92-93 (2 chars)
    portfolio_type: str           # Positions 94    (1 char)
    date_opened: date             # Positions 95-102 (MMDDYYYY)
    credit_limit: Optional[int]   # Positions 103-109 (7 digits, dollars)
    highest_credit_amount: int    # Positions 110-116 (7 digits)
    terms_duration: str           # Positions 117-119 (3 chars: e.g. "036")
    terms_frequency: str          # Positions 120 (1 char: M=monthly, W=weekly…)
    scheduled_monthly_payment: Optional[int]  # 121-128 (8 digits)
    actual_payment: Optional[int]             # 129-136 (8 digits)

    # Balance and status
    account_status: str           # Positions 137-138 (2 chars)
    payment_rating: str           # Positions 139 (1 char)
    payment_history_1: str        # Positions 140 (1 char)
    current_balance: int          # Positions 141-147 (7 digits)
    amount_past_due: int          # Positions 148-154 (7 digits)
    original_charge_off: Optional[int]        # 155-161 (7 digits)

    # Dates
    date_account_information: date  # Positions 162-169 (MMDDYYYY)
    first_delinquency_date: Optional[date]    # 170-177 (MMDDYYYY, or 00000000)
    date_closed: Optional[date]               # 178-185 (MMDDYYYY, or 00000000)
    date_last_payment: Optional[date]         # 186-193 (MMDDYYYY, or 00000000)

    # Personal — continued
    address_1: str                # Positions 194-217 (24 chars)
    address_2: str                # Positions 218-241 (24 chars)
    city: str                     # Positions 242-253 (12 chars)
    state: str                    # Positions 254-255 (2-char state code)
    zip_code: str                 # Positions 256-264 (9 chars)
    country_code: str             # Positions 265-266 (2-char; blank for USA)
    telephone_number: str         # Positions 267-276 (10 digits)
    ecoa_code: str                # Positions 277 (1 char)
    consumer_info_indicator: str  # Positions 278 (1 char)
    country_of_citizenship_1: str # Positions 279-280 (2 chars)
    country_of_citizenship_2: str # Positions 281-282 (2 chars)
    removal_indicator: str        # Positions 283 (1 char)
    residence_code: str           # Positions 284 (1 char: O=own, R=rent…)
    mortgage_type: str            # Positions 285-286 (2 chars; blank if N/A)
    interest_type_indicator: str  # Positions 287 (1 char)
    # Positions 288-426: reserved / compliance fields — defaulted to spaces
    compliance_condition_code: str = COMPLIANCE_NA   # 288-289
    employment_status_code: str = " "               # 290
    # Remaining positions (291-426) reserved/blank — appended automatically


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _alphanum(value: Optional[str], width: int) -> str:
    """Left-justify, pad with spaces, truncate to *width*."""
    s = str(value or "").upper()
    return s[:width].ljust(width)


def _numeric(value: Optional[int], width: int) -> str:
    """Right-justify, zero-pad, truncate to *width*."""
    n = int(value or 0)
    return str(n)[:width].zfill(width)


def _date_field(d: Optional[date]) -> str:
    """Format a date as MMDDYYYY (8 chars).  Returns '00000000' for None."""
    if d is None:
        return "00000000"
    return f"{d.month:02d}{d.day:02d}{d.year:04d}"


def _ssn(raw: str) -> str:
    """Strip hyphens/spaces and zero-pad to 9 digits."""
    digits = re.sub(r"\D", "", str(raw or ""))
    return digits[:9].zfill(9)


# ---------------------------------------------------------------------------
# Record formatter
# ---------------------------------------------------------------------------


def format_record(rec: Metro2Record) -> str:
    """Return a 426-character Metro 2 Base Segment string (no line terminator).

    The returned string is exactly ``RECORD_LENGTH`` characters.
    """
    # Build each field in order, concatenating into a single string.
    # Field positions per CDIA Metro 2 Base Segment layout:
    segments: List[str] = [
        SEGMENT_IDENTIFIER,                         # pos 1     (1 char)
        _alphanum(rec.subscriber_id, 9),            # pos 2-10  → shift: 1-9 reserved for record length; we use segment ID at pos 1.
        _alphanum(rec.account_number, 26),          # pos 10-35
        _ssn(rec.ssn),                              # pos 36-44
        _date_field(rec.date_of_birth),             # pos 45-52
        _alphanum(rec.first_name, 15),              # pos 53-67
        _alphanum(rec.middle_name, 8),              # pos 68-75
        _alphanum(rec.last_name, 15),               # pos 76-90
        _alphanum(rec.generation_code, 1),          # pos 91
        _alphanum(rec.account_type, 2),             # pos 92-93
        _alphanum(rec.portfolio_type, 1),           # pos 94
        _date_field(rec.date_opened),               # pos 95-102
        _numeric(rec.credit_limit, 7),              # pos 103-109
        _numeric(rec.highest_credit_amount, 7),     # pos 110-116
        _alphanum(rec.terms_duration, 3),           # pos 117-119
        _alphanum(rec.terms_frequency, 1),          # pos 120
        _numeric(rec.scheduled_monthly_payment, 8), # pos 121-128
        _numeric(rec.actual_payment, 8),            # pos 129-136
        _alphanum(rec.account_status, 2),           # pos 137-138
        _alphanum(rec.payment_rating, 1),           # pos 139
        _alphanum(rec.payment_history_1, 1),        # pos 140
        _numeric(rec.current_balance, 7),           # pos 141-147
        _numeric(rec.amount_past_due, 7),           # pos 148-154
        _numeric(rec.original_charge_off, 7),       # pos 155-161
        _date_field(rec.date_account_information),  # pos 162-169
        _date_field(rec.first_delinquency_date),    # pos 170-177
        _date_field(rec.date_closed),               # pos 178-185
        _date_field(rec.date_last_payment),         # pos 186-193
        _alphanum(rec.address_1, 24),               # pos 194-217
        _alphanum(rec.address_2, 24),               # pos 218-241
        _alphanum(rec.city, 12),                    # pos 242-253
        _alphanum(rec.state, 2),                    # pos 254-255
        _alphanum(rec.zip_code, 9),                 # pos 256-264
        _alphanum(rec.country_code, 2),             # pos 265-266
        _alphanum(rec.telephone_number, 10),        # pos 267-276
        _alphanum(rec.ecoa_code, 1),                # pos 277
        _alphanum(rec.consumer_info_indicator, 1),  # pos 278
        _alphanum(rec.country_of_citizenship_1, 2), # pos 279-280
        _alphanum(rec.country_of_citizenship_2, 2), # pos 281-282
        _alphanum(rec.removal_indicator, 1),        # pos 283
        _alphanum(rec.residence_code, 1),           # pos 284
        _alphanum(rec.mortgage_type, 2),            # pos 285-286
        _alphanum(rec.interest_type_indicator, 1),  # pos 287
        _alphanum(rec.compliance_condition_code, 2), # pos 288-289
        _alphanum(rec.employment_status_code, 1),   # pos 290
    ]

    raw = "".join(segments)

    # Pad / truncate to exactly RECORD_LENGTH
    if len(raw) < RECORD_LENGTH:
        raw = raw + " " * (RECORD_LENGTH - len(raw))
    else:
        raw = raw[:RECORD_LENGTH]

    return raw


# ---------------------------------------------------------------------------
# File-level export
# ---------------------------------------------------------------------------


def export_metro2(
    records: Sequence[Metro2Record],
    output: Optional[io.StringIO] = None,
) -> str:
    """Serialise a sequence of ``Metro2Record`` objects into a Metro 2 flat file.

    Each record is a 426-char line terminated by CRLF.
    Returns the complete file as a string.
    """
    buf = output or io.StringIO()
    for rec in records:
        line = format_record(rec)
        buf.write(line + CRLF)
    return buf.getvalue()


def validate_record_length(line: str) -> bool:
    """Return True if *line* (without CRLF) is exactly ``RECORD_LENGTH`` chars."""
    stripped = line.rstrip("\r\n")
    return len(stripped) == RECORD_LENGTH


# ---------------------------------------------------------------------------
# Builder: from audit-log record dict
# ---------------------------------------------------------------------------


def from_audit_log_record(
    audit_rec: Dict[str, Any],
    *,
    subscriber_id: str,
) -> Metro2Record:
    """Build a ``Metro2Record`` from an audit-log record dict.

    This is a best-effort mapping.  Fields not present in the audit log are
    defaulted to Metro 2's "not applicable" blanks/zeros.

    Expected keys (all optional except ``application_id``):
      - ``application_id``   → account_number
      - ``customer_id``      → (used for account_number fallback)
      - ``logged_at``        → date_account_information + date_opened
      - ``decision_output``  → account_status ("APPROVE"→11, else 97)
      - ``loan_amount``      → highest_credit_amount, credit_limit
      - ``annual_income``    → not mapped to Metro 2 standard field
      - ``borrower_state``   → state
    """
    app_id = str(audit_rec.get("application_id") or audit_rec.get("customer_id", ""))
    logged_at_raw = str(audit_rec.get("logged_at") or "")
    try:
        acct_date = date.fromisoformat(logged_at_raw[:10])
    except (ValueError, TypeError):
        acct_date = date.today()

    decision = str(audit_rec.get("decision_output", "")).upper()
    if decision == "APPROVE":
        acct_status = STATUS_CURRENT
    elif decision in ("DECLINE", "REJECT"):
        acct_status = STATUS_CHARGE_OFF
    else:
        acct_status = STATUS_CURRENT

    loan_amt = int(float(audit_rec.get("loan_amount") or 0))
    borrower_state = str(audit_rec.get("borrower_state") or "  ")[:2]
    input_feats: Dict[str, Any] = audit_rec.get("input_features") or {}
    first_name = str(input_feats.get("first_name") or "")
    last_name = str(input_feats.get("last_name") or "")

    return Metro2Record(
        subscriber_id=subscriber_id,
        account_number=app_id,
        ssn="000000000",
        date_of_birth=date(1900, 1, 1),
        first_name=first_name,
        middle_name="",
        last_name=last_name,
        generation_code=" ",
        account_type=ACCOUNT_TYPE_INSTALLMENT,
        portfolio_type=PORTFOLIO_INSTALLMENT,
        date_opened=acct_date,
        credit_limit=loan_amt or None,
        highest_credit_amount=loan_amt,
        terms_duration="000",
        terms_frequency="M",
        scheduled_monthly_payment=None,
        actual_payment=None,
        account_status=acct_status,
        payment_rating="0",
        payment_history_1="C",
        current_balance=loan_amt,
        amount_past_due=0,
        original_charge_off=None,
        date_account_information=acct_date,
        first_delinquency_date=None,
        date_closed=None,
        date_last_payment=None,
        address_1="",
        address_2="",
        city="",
        state=borrower_state,
        zip_code="",
        country_code="  ",
        telephone_number="",
        ecoa_code=ECOA_INDIVIDUAL,
        consumer_info_indicator=" ",
        country_of_citizenship_1="US",
        country_of_citizenship_2="  ",
        removal_indicator=" ",
        residence_code=" ",
        mortgage_type="  ",
        interest_type_indicator=" ",
    )
