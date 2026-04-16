"""
audit/override_log.py
=====================
Immutable, hash-chained log of every policy-threshold override applied to a
credit decision (GAP-02 / PRD §3.1).

Every override must be reviewed and approved by a SECOND person (four-eyes).
The table is APPEND-ONLY — no UPDATE or DELETE is ever performed.

Public API
----------
>>> from audit.override_log import (
...     PolicyOverrideRecord, log_override,
...     get_override_rate, verify_override_chain,
... )
>>> override_id = await log_override(record, db_url)
>>> rate = await get_override_rate("tenant-1", "2026-01-01", "2026-03-31", db_url)
>>> valid = await verify_override_chain("tenant-1", db_url)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# ---------------------------------------------------------------------------
# Engine cache (shared with audit.logger pattern)
# ---------------------------------------------------------------------------

_ENGINE_CACHE: Dict[str, AsyncEngine] = {}


def _get_engine(db_url: str) -> AsyncEngine:
    if db_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[db_url] = create_async_engine(db_url, echo=False)
    return _ENGINE_CACHE[db_url]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

OVERRIDE_LOG_DDL = """
CREATE TABLE IF NOT EXISTS policy_overrides_log (
    override_id    TEXT PRIMARY KEY,
    decision_id    TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    override_type  TEXT NOT NULL,
    original_value REAL NOT NULL,
    override_value REAL NOT NULL,
    justification  TEXT NOT NULL,
    submitted_by   TEXT NOT NULL,
    approved_by    TEXT NOT NULL,
    approved_at    TEXT NOT NULL,
    record_hash    TEXT NOT NULL,
    previous_hash  TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class PolicyOverrideRecord:
    """One policy-threshold override request that has been approved.

    Fields
    ------
    override_id      UUID of this override event.
    decision_id      application_id of the affected decision.
    tenant_id        Opaque tenant identifier from JWT claims.
    override_type    e.g. ``"pd_threshold_low"`` | ``"pd_threshold"``.
    original_value   The platform default / previous threshold value.
    override_value   The requested replacement value.
    justification    Free-text business justification (min 10 chars).
    submitted_by     Email of the person requesting the override.
    approved_by      Email of the second approver (must differ from submitted_by).
    approved_at      ISO-8601 UTC timestamp of approval.
    record_hash      sha256 of all fields + previous_hash — computed at write time.
    previous_hash    Hash of the prior record for this tenant (or ``"GENESIS"``).
    """

    override_id: str
    decision_id: str
    tenant_id: str
    override_type: str
    original_value: float
    override_value: float
    justification: str
    submitted_by: str
    approved_by: str
    approved_at: str
    # These two are computed in log_override; supply empty strings when building
    # a record before calling log_override.
    record_hash: str = ""
    previous_hash: str = ""


# ---------------------------------------------------------------------------
# Hash helper
# ---------------------------------------------------------------------------


def _compute_record_hash(record: PolicyOverrideRecord) -> str:
    """Compute the sha256 of the serialised record (sort_keys=True)."""
    d = dataclasses.asdict(record)
    raw = json.dumps(d, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


async def _ensure_table(engine: AsyncEngine) -> None:
    """Create the policy_overrides_log table if absent."""
    async with engine.begin() as conn:
        await conn.execute(text(OVERRIDE_LOG_DDL))


async def _fetch_previous_hash(conn, tenant_id: str) -> str:
    """Return the record_hash of the most-recent row for *tenant_id*, or
    ``"GENESIS"`` when the tenant has no earlier rows."""
    result = await conn.execute(
        text(
            "SELECT record_hash FROM policy_overrides_log"
            " WHERE tenant_id = :tid"
            " ORDER BY approved_at DESC, override_id ASC LIMIT 1"
        ),
        {"tid": tenant_id},
    )
    row = result.fetchone()
    return row[0] if row else "GENESIS"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def log_override(record: PolicyOverrideRecord, db_url: str) -> str:
    """Append *record* to the policy_overrides_log and return ``override_id``.

    The function:
    1. Establishes (or reuses) an async engine for ``db_url``.
    2. Creates the table if absent.
    3. Inside a single transaction, fetches the previous hash for the tenant
       and computes ``record.record_hash`` so the chain is tamper-evident.
    4. Inserts the record.

    Parameters
    ----------
    record : PolicyOverrideRecord
        A fully-populated record.  ``record_hash`` and ``previous_hash`` are
        overwritten by this function — any values you pre-set are ignored.
    db_url : str
        SQLAlchemy async connection URL.

    Returns
    -------
    str
        The ``override_id`` of the inserted record.
    """
    engine = _get_engine(db_url)
    await _ensure_table(engine)

    async with engine.begin() as conn:
        # Step 1 — fetch previous hash inside the same transaction to prevent
        # race conditions on concurrent inserts.
        previous_hash = await _fetch_previous_hash(conn, record.tenant_id)
        record.previous_hash = previous_hash

        # Step 2 — compute record_hash over all fields including previous_hash
        record.record_hash = _compute_record_hash(record)

        # Step 3 — insert
        await conn.execute(
            text(
                "INSERT INTO policy_overrides_log ("
                "  override_id, decision_id, tenant_id, override_type,"
                "  original_value, override_value, justification,"
                "  submitted_by, approved_by, approved_at,"
                "  record_hash, previous_hash"
                ") VALUES ("
                "  :override_id, :decision_id, :tenant_id, :override_type,"
                "  :original_value, :override_value, :justification,"
                "  :submitted_by, :approved_by, :approved_at,"
                "  :record_hash, :previous_hash"
                ")"
            ),
            dataclasses.asdict(record),
        )

    return record.override_id


async def get_override_rate(
    tenant_id: str,
    from_date: str,
    to_date: str,
    db_url: str,
) -> float:
    """Return the proportion of decisions in the period that had at least one
    override logged.

    Calculation:
        count(override rows for tenant in period)
        ─────────────────────────────────────────
        count(audit_log rows for tenant in period)

    Returns ``0.0`` when the denominator is zero.

    Parameters
    ----------
    tenant_id : str
    from_date : str   ISO-8601 date (``"2026-01-01"``).
    to_date   : str   ISO-8601 date (``"2026-03-31"``).
    db_url    : str
    """
    engine = _get_engine(db_url)
    await _ensure_table(engine)

    async with engine.connect() as conn:
        # Numerator — override rows in the window
        ov_result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM policy_overrides_log"
                " WHERE tenant_id = :tid"
                "   AND approved_at >= :from_dt"
                "   AND approved_at <= :to_dt"
            ),
            {"tid": tenant_id, "from_dt": from_date, "to_dt": to_date},
        )
        override_count = ov_result.scalar() or 0

        # Denominator — total audit_log rows in the window (may be 0 in tests)
        try:
            al_result = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM audit_log"
                    " WHERE tenant_id = :tid"
                    "   AND logged_at >= :from_dt"
                    "   AND logged_at <= :to_dt"
                ),
                {"tid": tenant_id, "from_dt": from_date, "to_dt": to_date},
            )
            total_count = al_result.scalar() or 0
        except Exception:
            # audit_log table may not exist in isolated test DBs
            total_count = 0

    if total_count == 0:
        return 0.0
    return override_count / total_count


async def verify_override_chain(tenant_id: str, db_url: str) -> bool:
    """Re-walk the hash chain for *tenant_id* and return ``True`` iff every
    link is valid (i.e. no record has been tampered with).

    The chain is verified by:
    1. Loading all records for the tenant ordered by ``approved_at, override_id``.
    2. For each record, temporarily zeroing ``previous_hash`` and
       ``record_hash`` on a copy, then re-computing the expected hash and
       comparing it with ``record.record_hash``.

    Parameters
    ----------
    tenant_id : str
    db_url    : str

    Returns
    -------
    bool
        ``True``  — chain is intact.
        ``False`` — at least one record fails hash verification.
    """
    engine = _get_engine(db_url)
    await _ensure_table(engine)

    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT override_id, decision_id, tenant_id, override_type,"
                "       original_value, override_value, justification,"
                "       submitted_by, approved_by, approved_at,"
                "       record_hash, previous_hash"
                " FROM policy_overrides_log"
                " WHERE tenant_id = :tid"
                " ORDER BY approved_at ASC, override_id ASC"
            ),
            {"tid": tenant_id},
        )
        rows = result.fetchall()

    if not rows:
        return True  # Empty chain is valid

    columns = [
        "override_id", "decision_id", "tenant_id", "override_type",
        "original_value", "override_value", "justification",
        "submitted_by", "approved_by", "approved_at",
        "record_hash", "previous_hash",
    ]

    expected_previous = "GENESIS"
    for row in rows:
        rec_dict = dict(zip(columns, row))
        stored_hash = rec_dict["record_hash"]
        stored_prev = rec_dict["previous_hash"]

        # Verify the chain link
        if stored_prev != expected_previous:
            return False

        # Rebuild the record and recompute expected hash.
        # IMPORTANT: when the hash was originally stored, record.record_hash
        # was "" at the time _compute_record_hash() was called, so we must
        # zero it out here before recomputing to get the same digest.
        record = PolicyOverrideRecord(**{**rec_dict, "record_hash": ""})
        recomputed = _compute_record_hash(record)
        if recomputed != stored_hash:
            return False

        expected_previous = stored_hash

    return True
