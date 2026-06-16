"""
Third-Party & Vendor Compliance Registry — Section 23.9
========================================================
Per SR 11-7, all third-party vendor models undergo the same internal MRM
validation lifecycle as internally-developed models before use in credit
decisions.

This module:
1. Declares all third-party models used by the platform (THIRD_PARTY_MODELS).
2. Provides check_third_party_validation_due() to detect overdue MRM
   validations — runs monthly via Cloud Scheduler.
3. Exposes check_fcra_aa_fields() to verify adverse action notices include
   all four FCRA-required fields when a bureau pull contributed to the
   decision outcome.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BigQuery optional import
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq_lib = None  # type: ignore
    _BQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Third-party model registry
# ---------------------------------------------------------------------------

THIRD_PARTY_MODELS: dict[str, dict[str, Any]] = {
    "bureau_vantagescore_4": {
        "vendor": "TransUnion / VantageScore Solutions",
        "version": "4.0",
        "use_case": "supplemental_score_for_thin_file",
        "validation_required": True,
        "validation_cycle_months": 12,
        "contract_review_cycle_months": 24,
        "fair_lending_assessment_required": True,
        "sr11_7_compliant": False,    # Updated by ml_validator after annual assessment
        "owner_email": "mrm@credit-risk-platform.internal",
    },
    "bureau_fico_score_9": {
        "vendor": "Fair Isaac Corporation",
        "version": "9",
        "use_case": "primary_credit_score",
        "validation_required": True,
        "validation_cycle_months": 12,
        "contract_review_cycle_months": 24,
        "fair_lending_assessment_required": True,
        "sr11_7_compliant": False,
        "owner_email": "mrm@credit-risk-platform.internal",
    },
    "lexisnexis_fraud_score": {
        "vendor": "LexisNexis Risk Solutions",
        "version": "3.1",
        "use_case": "identity_fraud_screening",
        "validation_required": True,
        "validation_cycle_months": 12,
        "contract_review_cycle_months": 12,
        "fair_lending_assessment_required": True,
        "sr11_7_compliant": False,
        "owner_email": "mrm@credit-risk-platform.internal",
    },
}

# ---------------------------------------------------------------------------
# FCRA-required adverse action notice fields
# ---------------------------------------------------------------------------

FCRA_AA_REQUIRED_FIELDS: list[str] = [
    "consumer_reporting_agency_name",
    "consumer_reporting_agency_address",
    "consumer_report_right_to_dispute_url",
    "free_disclosure_phone",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_third_party_validation_due() -> list[dict[str, Any]]:
    """
    Return a list of third-party models whose MRM validation is overdue.

    Checks the audit.model_validation_log in BigQuery.  Falls back to
    returning all models with validation_required=True if BigQuery is
    unavailable (safe-to-escalate default).

    Used by the monthly Cloud Scheduler job
    ``scripts/check_third_party_validation_due.py``.
    """
    overdue: list[dict[str, Any]] = []

    for model_id, meta in THIRD_PARTY_MODELS.items():
        if not meta["validation_required"]:
            continue

        last_validated: Optional[date] = _get_last_validated(model_id)
        cycle_days = meta["validation_cycle_months"] * 30
        is_overdue = (
            last_validated is None
            or (date.today() - last_validated).days > cycle_days
        )

        if is_overdue:
            overdue.append(
                {
                    "model_id": model_id,
                    "last_validated": str(last_validated) if last_validated else None,
                    "cycle_days": cycle_days,
                    "days_overdue": (
                        (date.today() - last_validated).days - cycle_days
                        if last_validated
                        else None
                    ),
                    **meta,
                }
            )
            logger.warning(
                "[THIRD_PARTY_COMPLIANCE] %s validation overdue — last_validated=%s "
                "cycle=%d days",
                model_id,
                last_validated,
                cycle_days,
            )

    return overdue


def check_contract_review_due() -> list[dict[str, Any]]:
    """
    Return third-party models whose vendor contract review is overdue.
    """
    overdue: list[dict[str, Any]] = []

    for model_id, meta in THIRD_PARTY_MODELS.items():
        last_reviewed: Optional[date] = _get_last_contract_review(model_id)
        cycle_days = meta["contract_review_cycle_months"] * 30
        is_overdue = (
            last_reviewed is None
            or (date.today() - last_reviewed).days > cycle_days
        )
        if is_overdue:
            overdue.append(
                {
                    "model_id": model_id,
                    "last_contract_reviewed": str(last_reviewed) if last_reviewed else None,
                    "cycle_days": cycle_days,
                    **meta,
                }
            )

    return overdue


def check_fcra_aa_fields(notice: dict[str, Any]) -> list[str]:
    """
    Validate that an adverse action notice dict contains all four FCRA-required
    fields when a bureau pull contributed to the decision.

    Returns
    -------
    list[str]
        List of missing required fields.  Empty list = PASS.
    """
    missing = [f for f in FCRA_AA_REQUIRED_FIELDS if not notice.get(f)]
    if missing:
        logger.error(
            "[FCRA_AA] Notice missing required fields: %s.  "
            "15 U.S.C. § 1681m requires all four fields when bureau pull contributed.",
            missing,
        )
    return missing


def get_third_party_summary() -> list[dict[str, Any]]:
    """
    Return summary of all third-party models with validation & contract status.
    Used by the /analytics/compliance dashboard endpoint.
    """
    summary = []
    for model_id, meta in THIRD_PARTY_MODELS.items():
        last_validated = _get_last_validated(model_id)
        cycle_days = meta["validation_cycle_months"] * 30
        days_since = (date.today() - last_validated).days if last_validated else None
        validation_status = (
            "CURRENT"
            if (days_since is not None and days_since <= cycle_days)
            else "OVERDUE"
        )
        summary.append(
            {
                "model_id": model_id,
                "vendor": meta["vendor"],
                "version": meta["version"],
                "use_case": meta["use_case"],
                "validation_status": validation_status,
                "last_validated": str(last_validated) if last_validated else None,
                "days_since_validation": days_since,
                "sr11_7_compliant": meta["sr11_7_compliant"],
                "fair_lending_assessment_required": meta["fair_lending_assessment_required"],
            }
        )
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_last_validated(model_id: str) -> Optional[date]:
    if not _BQ_AVAILABLE or _bq_lib is None:
        return None
    try:
        rows = list(
            _bq_lib.Client()
            .query(
                "SELECT MAX(validated_at) AS last_validated "
                "FROM audit.model_validation_log "
                "WHERE model_name = @mid",
                job_config=_bq_lib.QueryJobConfig(
                    query_parameters=[
                        _bq_lib.ScalarQueryParameter("mid", "STRING", model_id)
                    ]
                ),
            )
            .result()
        )
        val = rows[0].last_validated if rows else None
        return val.date() if hasattr(val, "date") else val
    except Exception:  # pragma: no cover
        return None


def _get_last_contract_review(model_id: str) -> Optional[date]:
    if not _BQ_AVAILABLE or _bq_lib is None:
        return None
    try:
        rows = list(
            _bq_lib.Client()
            .query(
                "SELECT MAX(reviewed_at) AS last_reviewed "
                "FROM audit.vendor_contract_review_log "
                "WHERE model_id = @mid",
                job_config=_bq_lib.QueryJobConfig(
                    query_parameters=[
                        _bq_lib.ScalarQueryParameter("mid", "STRING", model_id)
                    ]
                ),
            )
            .result()
        )
        val = rows[0].last_reviewed if rows else None
        return val.date() if hasattr(val, "date") else val
    except Exception:  # pragma: no cover
        return None
