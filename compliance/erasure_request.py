"""
CCPA / GLBA Right-to-Erasure Handler — Section 23.7
=====================================================
Implements the right-to-erasure workflow mandated by:
  - CCPA § 1798.105 (California Consumer Privacy Act)
  - GLBA Privacy Rule (16 CFR Part 313)

Processing SLA: <= 45 days from request receipt (CCPA § 1798.105(d)).

Design rules
------------
1. Erasure-exempt tables (ECOA, FCRA, Reg B, SR 11-7 legal holds) are
   NEVER modified regardless of the erasure request.
2. Every erasure request, whether it results in deletions or not, is
   recorded to audit.erasure_request_log (legally required audit trail).
3. The applicant identifier is SHA-256 hashed at the boundary of this
   function; plaintext PII never enters any BQ table.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Optional

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
# Erasure policy tables
# ---------------------------------------------------------------------------

ERASURE_EXEMPT_TABLES: frozenset[str] = frozenset(
    {
        "audit.audit_log",                       # ECOA Reg B — 25-month mandatory hold
        "audit.governance_approval_log",          # SR 11-7 — permanent retention
        "audit.model_validation_log",             # SR 11-7 — permanent retention
        "audit.policy_version_log",               # SR 11-7 — permanent retention
        "audit.policy_approval_log",              # SR 11-7 — permanent retention
        "compliance_data_plane.compliance_events",# SR 11-7 — 5-year minimum retention
        "audit.access_event_log",                 # SOX / internal policy — 7 years
    }
)

# table -> PII column name used for matching
ERASABLE_TABLES: dict[str, str] = {
    "compliance_data_plane.consent_and_disclosures": "applicant_id_hash",
    "audit.adverse_action_notice_queue": "applicant_id_hash",
    "features.cc_customer_features": "customer_id_hash",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_erasure_request(
    applicant_id: str,
    requested_by: str,
    legal_basis: str = "CCPA § 1798.105",
    request_id: Optional[str] = None,
) -> dict:
    """
    Execute a right-to-erasure request for the given applicant.

    Parameters
    ----------
    applicant_id : str
        Plaintext applicant identifier (e.g. customer UUID).  Hashed before
        any BQ interaction.
    requested_by : str
        Email or system identifier of the party initiating the request.
    legal_basis : str
        Regulatory basis for the erasure (default: CCPA § 1798.105).
    request_id : str, optional
        Pre-assigned request identifier; auto-generated if omitted.

    Returns
    -------
    dict
        {table_name: rows_deleted, ...} for all erasable tables.

    Raises
    ------
    RuntimeError
        If BigQuery is unavailable.
    """
    if not _BQ_AVAILABLE or _bq_lib is None:
        raise RuntimeError("BigQuery unavailable — cannot process erasure request.")

    id_hash = _sha256(applicant_id)
    req_id = request_id or str(uuid.uuid4())
    bq = _bq_lib.Client()

    results: dict[str, int] = {}
    for table, id_col in ERASABLE_TABLES.items():
        try:
            job = bq.query(
                f"DELETE FROM `{table}` WHERE `{id_col}` = @hash",
                job_config=_bq_lib.QueryJobConfig(
                    query_parameters=[
                        _bq_lib.ScalarQueryParameter("hash", "STRING", id_hash)
                    ]
                ),
            )
            result = job.result()
            rows_deleted = getattr(result, "num_dml_affected_rows", 0) or 0
            results[table] = rows_deleted
            logger.info(
                "[ERASURE] req=%s table=%s rows_deleted=%d",
                req_id,
                table,
                rows_deleted,
            )
        except Exception as exc:  # pragma: no cover
            logger.error("[ERASURE] req=%s table=%s error: %s", req_id, table, exc)
            results[table] = -1  # sentinel: error

    # ------------------------------------------------------------------
    # Audit log entry (mandatory — erasure_request_log is exempt-exempt,
    # i.e. we never erase the erasure log itself)
    # ------------------------------------------------------------------
    _log_erasure_request(
        bq=bq,
        request_id=req_id,
        applicant_id_hash=id_hash,
        requested_by=requested_by,
        legal_basis=legal_basis,
        tables_erased=list(ERASABLE_TABLES.keys()),
        exempt_tables=list(ERASURE_EXEMPT_TABLES),
        rows_deleted=results,
    )

    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _log_erasure_request(
    bq: "bigquery.Client",  # type: ignore[name-defined]
    request_id: str,
    applicant_id_hash: str,
    requested_by: str,
    legal_basis: str,
    tables_erased: list[str],
    exempt_tables: list[str],
    rows_deleted: dict[str, int],
) -> None:
    bq.insert_rows_json(
        "audit.erasure_request_log",
        [
            {
                "request_id": request_id,
                "applicant_id_hash": applicant_id_hash,
                "requested_by": requested_by,
                "legal_basis": legal_basis,
                "tables_erased": tables_erased,
                "exempt_tables": exempt_tables,
                "rows_deleted": str(rows_deleted),
                "processed_at": datetime.utcnow().isoformat(),
            }
        ],
    )
