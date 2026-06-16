"""
etl/transformer.py
==================
Transforms raw Pub/Sub message payloads into bronze, silver, and gold BigQuery rows.

Layer definitions
-----------------
* **Bronze** — raw JSON flattened to columns; no cleaning.  Every inbound
  message produces exactly one bronze row.  Schema matches
  ``db.bigquery_schema.LOAN_APPLICATIONS_SCHEMA``.

* **Silver** — bronze + type coercion, null handling, and deduplication on
  ``(application_id, tenant_id)``.  Rows that fail validation are written to
  a ``_rejected`` side table with a ``rejection_reason`` column.

* **Gold** — placeholder level.  Denormalised decision outcome is joined from
  the audit log in a separate scheduled job.
  TODO(G3-gold): implement gold-layer join once audit log BQ sink exists.

``tenant_id`` is ALWAYS sourced from the Pub/Sub message ``attributes`` dict,
never from the payload body, to prevent spoofing.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Required fields for a valid silver row
# ---------------------------------------------------------------------------

_REQUIRED_SILVER_FIELDS = {
    "application_id",
    "tenant_id",
    "submitted_at",
    "loan_amount",
    "annual_income",
    "loan_purpose",
    "loan_term_months",
    "employment_status",
}

# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------


def _to_float(val: Any) -> float | None:
    """Coerce *val* to float; return None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_int(val: Any) -> int | None:
    """Coerce *val* to int; return None on failure."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _to_bool(val: Any) -> bool | None:
    """Coerce *val* to bool."""
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _to_str(val: Any) -> str | None:
    return str(val) if val is not None else None


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _flatten_payload(payload: Dict[str, Any], attributes: Dict[str, str]) -> Dict[str, Any]:
    """Flatten a Pub/Sub message into a bronze row dict.

    ``tenant_id`` is always taken from *attributes*, never from *payload*.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    return {
        "tenant_id":                    attributes.get("tenant_id", ""),
        "application_id":               _to_str(payload.get("application_id")),
        "submitted_at":                 _to_str(payload.get("submitted_at") or now_iso),
        "loan_amount":                  payload.get("loan_amount"),
        "loan_purpose":                 _to_str(payload.get("loan_purpose")),
        "loan_term_months":             payload.get("loan_term_months"),
        "annual_income":                payload.get("annual_income"),
        "employment_status":            _to_str(payload.get("employment_status")),
        "employer_tenure_months":       payload.get("employer_tenure_months"),
        "dti":                          payload.get("dti"),
        "existing_debt":                payload.get("existing_debt"),
        "credit_score":                 payload.get("credit_score"),
        "num_open_accounts":            payload.get("num_open_accounts"),
        "num_derogatory_marks":         payload.get("num_derogatory_marks"),
        "months_since_last_delinquency": payload.get("months_since_last_delinquency"),
        "borrower_state":               _to_str(payload.get("borrower_state")),
        "channel":                      _to_str(payload.get("channel")),
        # Alt-data / thin-file signals
        "rent_payment_months":          payload.get("rent_payment_months"),
        "utility_payment_months":       payload.get("utility_payment_months"),
        "mobile_data_score":            payload.get("mobile_data_score"),
        "bank_account_age_months":      payload.get("bank_account_age_months"),
        "avg_monthly_cash_inflow":      payload.get("avg_monthly_cash_inflow"),
        "avg_monthly_cash_outflow":     payload.get("avg_monthly_cash_outflow"),
        "is_thin_file":                 payload.get("is_thin_file"),
        "data_split":                   _to_str(payload.get("data_split")),
        "schema_version":               _to_str(payload.get("schema_version", "1.0")),
        "inserted_at":                  now_iso,
        # Carry forwarded metadata
        "_source_event_type":           _to_str(payload.get("event_type")),
        "_batch_id":                    _to_str(payload.get("batch_id")),
        "_gcs_uri":                     _to_str(payload.get("gcs_uri")),
    }


def _coerce_silver(bronze: Dict[str, Any]) -> Dict[str, Any]:
    """Apply type coercions and null handling to produce a silver row."""
    row = dict(bronze)
    row["loan_amount"] = _to_float(bronze.get("loan_amount"))
    row["loan_term_months"] = _to_int(bronze.get("loan_term_months"))
    row["annual_income"] = _to_float(bronze.get("annual_income"))
    row["employer_tenure_months"] = _to_float(bronze.get("employer_tenure_months"))
    row["dti"] = _to_float(bronze.get("dti"))
    row["existing_debt"] = _to_float(bronze.get("existing_debt"))
    row["credit_score"] = _to_float(bronze.get("credit_score"))
    row["num_open_accounts"] = _to_int(bronze.get("num_open_accounts"))
    row["num_derogatory_marks"] = _to_int(bronze.get("num_derogatory_marks"))
    row["months_since_last_delinquency"] = _to_float(bronze.get("months_since_last_delinquency"))
    row["rent_payment_months"] = _to_int(bronze.get("rent_payment_months"))
    row["utility_payment_months"] = _to_int(bronze.get("utility_payment_months"))
    row["mobile_data_score"] = _to_float(bronze.get("mobile_data_score"))
    row["bank_account_age_months"] = _to_int(bronze.get("bank_account_age_months"))
    row["avg_monthly_cash_inflow"] = _to_float(bronze.get("avg_monthly_cash_inflow"))
    row["avg_monthly_cash_outflow"] = _to_float(bronze.get("avg_monthly_cash_outflow"))
    row["is_thin_file"] = _to_bool(bronze.get("is_thin_file"))
    return row


def _validate_silver(row: Dict[str, Any]) -> str | None:
    """Return a rejection reason string if validation fails, else None."""
    for field in _REQUIRED_SILVER_FIELDS:
        if not row.get(field):
            return f"missing_required_field:{field}"

    if row.get("loan_amount") is not None and row["loan_amount"] <= 0:
        return "invalid_loan_amount:must_be_positive"
    if row.get("annual_income") is not None and row["annual_income"] < 0:
        return "invalid_annual_income:negative"
    if row.get("dti") is not None and not (0.0 <= row["dti"] <= 10.0):
        return f"invalid_dti:{row['dti']}"

    return None  # valid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def transform_batch(
    messages: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Transform a batch of raw Pub/Sub messages into bronze, silver, and gold rows.

    Each element of *messages* must have the shape::

        {
            "data": {...},        # JSON-decoded message body (the ingestion envelope)
            "attributes": {       # Pub/Sub message attributes
                "tenant_id": "...",
                "source": "...",
                "data_type": "...",
            },
            "message_id": "...",
        }

    Parameters
    ----------
    messages:
        Decoded Pub/Sub messages as dicts (``data`` already JSON-decoded).

    Returns
    -------
    tuple[bronze_rows, silver_rows, gold_rows]
        ``bronze_rows`` — all rows (one per message, no cleaning).
        ``silver_rows`` — validated and coerced rows; invalid rows go into
        ``rejected_rows`` (accessible via ``transform_batch_with_rejects``).
        ``gold_rows`` — empty list (stub for future join-from-audit-log).

    Note
    ----
    ``tenant_id`` is ALWAYS sourced from ``message["attributes"]["tenant_id"]``.
    """
    bronze_rows: List[Dict[str, Any]] = []
    silver_rows: List[Dict[str, Any]] = []

    for msg in messages:
        attributes: Dict[str, str] = msg.get("attributes") or {}
        payload: Dict[str, Any] = msg.get("data") or {}
        # Flatten to bronze — always succeeds (one bronze row per message)
        bronze = _flatten_payload(payload, attributes)
        bronze_rows.append(bronze)

        # Coerce + validate for silver
        silver = _coerce_silver(bronze)
        rejection_reason = _validate_silver(silver)
        if rejection_reason is None:
            silver_rows.append(silver)
        else:
            # Rejected rows are returned separately; callers write to _rejected BQ table
            silver["rejection_reason"] = rejection_reason
            silver_rows.append(silver)  # keep in list with reason; caller filters on key

    # Gold: TODO(G3-gold) — join with audit log decision outcomes in a scheduled job
    gold_rows: List[Dict[str, Any]] = []

    return bronze_rows, silver_rows, gold_rows


def transform_batch_with_rejects(
    messages: List[Dict[str, Any]],
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Like ``transform_batch`` but splits silver into valid and rejected.

    Returns
    -------
    tuple[bronze_rows, valid_silver_rows, rejected_silver_rows, gold_rows]
    """
    bronze_rows, silver_rows_mixed, gold_rows = transform_batch(messages)
    valid_silver: List[Dict[str, Any]] = []
    rejected_silver: List[Dict[str, Any]] = []
    for row in silver_rows_mixed:
        if "rejection_reason" in row:
            rejected_silver.append(row)
        else:
            valid_silver.append(row)
    return bronze_rows, valid_silver, rejected_silver, gold_rows
