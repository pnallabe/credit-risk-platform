"""
Compliance Data Plane client — Section 23.2
============================================
All platform components import get_threshold() / log_compliance_event()
from this module — NEVER hardcode regulatory values in the codebase.

Design contract
---------------
- get_threshold() raises ComplianceDataPlaneError if the threshold is absent.
  A missing threshold is a deploy blocker; callers must never silently swallow
  ComplianceDataPlaneError and continue with a hardcoded fallback.
- log_compliance_event() is async; the caller is responsible for awaiting it or
  scheduling it via asyncio.get_event_loop().run_until_complete().
- All regulatory values are cached in an LRU cache with 512 entries. The cache
  is keyed by (threshold_id, jurisdiction). A nightly Cloud Scheduler job calls
  get_threshold.cache_clear() to force a refresh.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Optional

# ---------------------------------------------------------------------------
# Optional BigQuery import — falls back to a stub during unit tests so that
# the module can be imported without live GCP credentials.
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _bq = _bq_lib.Client()
    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq = None  # type: ignore
    _BQ_AVAILABLE = False

BQ_DATASET = "compliance_data_plane"


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegulatoryThreshold:
    """Immutable snapshot of a single regulatory threshold."""

    threshold_id: str
    regulation: str
    jurisdiction: str
    threshold_type: str
    threshold_value: float
    legal_citation: str


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


class ComplianceDataPlaneError(RuntimeError):
    """
    Raised when a required compliance threshold cannot be resolved from the
    compliance data plane.  This error must NEVER be caught-and-continued —
    an unresolvable threshold means the decision cannot be made safely.
    """


@lru_cache(maxsize=512)
def get_threshold(
    threshold_id: str, jurisdiction: str = "FEDERAL"
) -> RegulatoryThreshold:
    """
    Fetch a regulatory threshold from compliance_data_plane.regulatory_thresholds.

    Results are cached in an LRU cache (maxsize=512).  The nightly job
    ``check_regulatory_horizon.py`` calls ``get_threshold.cache_clear()`` to
    force a fresh read from BigQuery.

    Raises
    ------
    ComplianceDataPlaneError
        If no active threshold exists for the given (threshold_id, jurisdiction)
        pair.  Callers must propagate this error; they must not substitute a
        hardcoded default.
    """
    if not _BQ_AVAILABLE or _bq is None:
        raise ComplianceDataPlaneError(
            f"BigQuery client unavailable — cannot resolve threshold "
            f"{threshold_id}/{jurisdiction}."
        )

    rows = list(
        _bq.query(
            f"""
            SELECT *
            FROM `{BQ_DATASET}.regulatory_thresholds`
            WHERE threshold_id = @tid
              AND jurisdiction  = @jur
              AND effective_date <= CURRENT_DATE()
              AND (sunset_date IS NULL OR sunset_date > CURRENT_DATE())
            ORDER BY effective_date DESC
            LIMIT 1
            """,
            job_config=_bq_lib.QueryJobConfig(
                query_parameters=[
                    _bq_lib.ScalarQueryParameter("tid", "STRING", threshold_id),
                    _bq_lib.ScalarQueryParameter("jur", "STRING", jurisdiction),
                ]
            ),
        ).result()
    )

    if not rows:
        raise ComplianceDataPlaneError(
            f"No active threshold for {threshold_id}/{jurisdiction} — "
            "cannot proceed without regulatory reference.  "
            "Add the threshold to compliance_data_plane.regulatory_thresholds "
            "with a valid legal_sign_off_date before deploying."
        )

    r = rows[0]
    return RegulatoryThreshold(
        threshold_id=r.threshold_id,
        regulation=r.regulation,
        jurisdiction=r.jurisdiction,
        threshold_type=r.threshold_type,
        threshold_value=float(r.threshold_value),
        legal_citation=r.legal_citation,
    )


async def log_compliance_event(
    event_type: str,
    source_system: str,
    check_name: str,
    check_result: str,  # "PASS" | "FAIL" | "WARN" | "BLOCKED"
    observed_value: Optional[float] = None,
    threshold_id: Optional[str] = None,
    threshold_value: Optional[float] = None,
    policy_version_id: Optional[str] = None,
    model_name: Optional[str] = None,
    mlflow_run_id: Optional[str] = None,
    applicant_id_hash: Optional[str] = None,
    decision_id: Optional[str] = None,
    run_by: str = "system",
) -> str:
    """
    Append a compliance event to the immutable ledger
    (compliance_data_plane.compliance_events).

    Returns
    -------
    str
        The generated ``event_id`` (UUID4).

    Notes
    -----
    - The compliance_events table is append-only.  No UPDATE or DELETE
      statements are permitted by any application service account.
    - Rows are inserted via the BigQuery streaming insert API which provides
      at-least-once delivery.  Duplicate event_ids are idempotent from an
      audit perspective.
    """
    event_id = str(uuid.uuid4())

    if _BQ_AVAILABLE and _bq is not None:
        _bq.insert_rows_json(
            f"{BQ_DATASET}.compliance_events",
            [
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "source_system": source_system,
                    "policy_version_id": policy_version_id,
                    "model_name": model_name,
                    "mlflow_run_id": mlflow_run_id,
                    "check_name": check_name,
                    "check_result": check_result,
                    "threshold_id": threshold_id,
                    "observed_value": observed_value,
                    "threshold_value": threshold_value,
                    "applicant_id_hash": applicant_id_hash,
                    "decision_id": decision_id,
                    "run_by": run_by,
                    "run_at": datetime.utcnow().isoformat(),
                }
            ],
        )

    return event_id
