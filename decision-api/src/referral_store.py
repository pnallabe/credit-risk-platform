"""
decision-api/src/referral_store.py
====================================
Persist and manage credit decision referral cases that require manual human
review. Every MANUAL_REVIEW decision output triggers a referral entry.

PRD §11.3 — HITL referral lifecycle:
  engine flags MANUAL_REVIEW → referral_queue entry created →
  loan officer claims → loan officer resolves (APPROVE/REJECT/CONDITIONAL) →
  four-eyes approval → immutably logged.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

REFERRAL_SLA_HOURS: int = int(os.getenv("REFERRAL_SLA_HOURS", "72"))

# ---------------------------------------------------------------------------
# Schema / init
# ---------------------------------------------------------------------------

_SCHEMA_LOCK = threading.Lock()
_SCHEMA_DONE: set[str] = set()

_DDL = """
CREATE TABLE IF NOT EXISTS referral_queue (
    referral_id        TEXT    PRIMARY KEY,
    application_id     TEXT    NOT NULL,
    tenant_id          TEXT    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    created_at         TEXT    NOT NULL,
    sla_deadline       TEXT    NOT NULL,
    claimed_by         TEXT,
    claimed_at         TEXT,
    resolved_by        TEXT,
    resolved_at        TEXT,
    resolution         TEXT,
    resolution_notes   TEXT,
    approved_by        TEXT,
    override_id        TEXT,
    conditional_terms  TEXT,
    audit_log_id       TEXT,
    pd_score           REAL,
    fraud_probability  REAL
);
"""


def _strip_url(db_url: str) -> str:
    for prefix in ("sqlite:///", "sqlite+aiosqlite:///"):
        if db_url.startswith(prefix):
            return db_url[len(prefix):]
    return db_url


def _ensure_schema(db_url: str) -> None:
    path = _strip_url(db_url)
    with _SCHEMA_LOCK:
        if path in _SCHEMA_DONE:
            return
        conn = sqlite3.connect(path)
        try:
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_DONE.add(path)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReferralRecord:
    referral_id: str
    application_id: str
    tenant_id: str
    status: str  # pending | claimed | resolved | sla_breached
    created_at: str
    sla_deadline: str
    claimed_by: Optional[str]
    claimed_at: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    resolution: Optional[str]  # APPROVE | REJECT | CONDITIONAL
    resolution_notes: Optional[str]
    approved_by: Optional[str]
    override_id: Optional[str]
    conditional_terms: Optional[dict]
    audit_log_id: Optional[str]
    pd_score: Optional[float]
    fraud_probability: Optional[float]


def _row_to_record(row: dict) -> ReferralRecord:
    ct_raw = row.get("conditional_terms")
    ct = None
    if ct_raw:
        try:
            ct = json.loads(ct_raw)
        except Exception:
            ct = None
    return ReferralRecord(
        referral_id=row["referral_id"],
        application_id=row["application_id"],
        tenant_id=row["tenant_id"],
        status=row["status"],
        created_at=row["created_at"],
        sla_deadline=row["sla_deadline"],
        claimed_by=row.get("claimed_by"),
        claimed_at=row.get("claimed_at"),
        resolved_by=row.get("resolved_by"),
        resolved_at=row.get("resolved_at"),
        resolution=row.get("resolution"),
        resolution_notes=row.get("resolution_notes"),
        approved_by=row.get("approved_by"),
        override_id=row.get("override_id"),
        conditional_terms=ct,
        audit_log_id=row.get("audit_log_id"),
        pd_score=row.get("pd_score"),
        fraud_probability=row.get("fraud_probability"),
    )


def _maybe_update_sla_breach(conn: sqlite3.Connection, referral_id: str) -> None:
    """Mark a pending/claimed referral as sla_breached if deadline has passed."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        UPDATE referral_queue SET status = 'sla_breached'
         WHERE referral_id = ?
           AND status IN ('pending', 'claimed')
           AND sla_deadline < ?
        """,
        (referral_id, now),
    )


# ---------------------------------------------------------------------------
# Sync implementations
# ---------------------------------------------------------------------------


def _sync_create_referral(
    db_url: str,
    application_id: str,
    tenant_id: str,
    audit_log_id: Optional[str],
    pd_score: Optional[float],
    fraud_probability: Optional[float],
    sla_hours: int,
) -> ReferralRecord:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    now = datetime.now(timezone.utc)
    deadline = (now + timedelta(hours=sla_hours)).isoformat()
    now_str = now.isoformat()
    referral_id = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            INSERT INTO referral_queue
                (referral_id, application_id, tenant_id, status, created_at,
                 sla_deadline, claimed_by, claimed_at, resolved_by, resolved_at,
                 resolution, resolution_notes, approved_by, override_id,
                 conditional_terms, audit_log_id, pd_score, fraud_probability)
            VALUES (?, ?, ?, 'pending', ?, ?, NULL, NULL, NULL, NULL,
                    NULL, NULL, NULL, NULL, NULL, ?, ?, ?)
            """,
            (
                referral_id, application_id, tenant_id, now_str, deadline,
                audit_log_id, pd_score, fraud_probability,
            ),
        )
        conn.commit()
        row = dict(
            conn.execute(
                "SELECT * FROM referral_queue WHERE referral_id = ?",
                (referral_id,),
            ).fetchone()
        )
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_claim_referral(
    db_url: str,
    referral_id: str,
    claimed_by: str,
) -> ReferralRecord:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        _maybe_update_sla_breach(conn, referral_id)
        conn.commit()
        row_raw = conn.execute(
            "SELECT * FROM referral_queue WHERE referral_id = ?",
            (referral_id,),
        ).fetchone()
        if row_raw is None:
            raise ValueError(f"Referral {referral_id!r} not found.")
        row = dict(row_raw)
        if row["status"] not in ("pending", "sla_breached"):
            raise ValueError(
                f"Referral {referral_id!r} cannot be claimed: status={row['status']!r}."
            )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE referral_queue
               SET status = 'claimed', claimed_by = ?, claimed_at = ?
             WHERE referral_id = ?
            """,
            (claimed_by, now, referral_id),
        )
        conn.commit()
        row = dict(
            conn.execute(
                "SELECT * FROM referral_queue WHERE referral_id = ?",
                (referral_id,),
            ).fetchone()
        )
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_resolve_referral(
    db_url: str,
    override_db_url: Optional[str],
    referral_id: str,
    resolved_by: str,
    resolution: str,
    resolution_notes: str,
    approved_by: str,
    conditional_terms: Optional[dict],
) -> ReferralRecord:
    _ensure_schema(db_url)
    if len(resolution_notes.strip()) < 10:
        raise ValueError("resolution_notes must be at least 10 characters.")
    if resolved_by == approved_by:
        raise PermissionError(
            "Four-eyes violation: resolved_by and approved_by must be different users."
        )
    if resolution not in ("APPROVE", "REJECT", "CONDITIONAL"):
        raise ValueError(f"Invalid resolution {resolution!r}. Must be APPROVE, REJECT, or CONDITIONAL.")

    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row_raw = conn.execute(
            "SELECT * FROM referral_queue WHERE referral_id = ?",
            (referral_id,),
        ).fetchone()
        if row_raw is None:
            raise ValueError(f"Referral {referral_id!r} not found.")
        row = dict(row_raw)
        if row["status"] not in ("claimed", "pending", "sla_breached"):
            raise ValueError(
                f"Referral {referral_id!r} cannot be resolved: status={row['status']!r}."
            )

        now = datetime.now(timezone.utc).isoformat()
        override_id = str(uuid.uuid4())
        ct_json = json.dumps(conditional_terms) if conditional_terms else None

        conn.execute(
            """
            UPDATE referral_queue
               SET status = 'resolved', resolved_by = ?, resolved_at = ?,
                   resolution = ?, resolution_notes = ?, approved_by = ?,
                   override_id = ?, conditional_terms = ?
             WHERE referral_id = ?
            """,
            (resolved_by, now, resolution, resolution_notes, approved_by,
             override_id, ct_json, referral_id),
        )
        conn.commit()

        # Write to override_log (lazy import, best-effort)
        try:
            from audit.override_log import log_override, PolicyOverrideRecord  # noqa: PLC0415
            import asyncio as _asyncio  # noqa: PLC0415
            ov_rec = PolicyOverrideRecord(
                override_id=override_id,
                decision_id=row["application_id"],
                tenant_id=row["tenant_id"],
                override_type="manual_review_resolution",
                original_value=0.0,
                override_value=1.0 if resolution == "APPROVE" else 0.0,
                justification=resolution_notes,
                submitted_by=resolved_by,
                approved_by=approved_by,
                approved_at=now,
            )
            _ov_db = override_db_url or db_url
            loop = _asyncio.new_event_loop()
            loop.run_until_complete(log_override(ov_rec, _ov_db))
            loop.close()
        except Exception:
            pass  # best-effort

        row = dict(
            conn.execute(
                "SELECT * FROM referral_queue WHERE referral_id = ?",
                (referral_id,),
            ).fetchone()
        )
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_get_queue(
    db_url: str,
    tenant_id: str,
    status_filter: Optional[str],
    page: int,
    per_page: int,
) -> tuple[list[ReferralRecord], int]:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # Auto-update SLA breaches
        conn.execute(
            """
            UPDATE referral_queue SET status = 'sla_breached'
             WHERE tenant_id = ?
               AND status IN ('pending', 'claimed')
               AND sla_deadline < ?
            """,
            (tenant_id, now),
        )
        conn.commit()

        where = "WHERE tenant_id = ?"
        params: list = [tenant_id]
        if status_filter:
            where += " AND status = ?"
            params.append(status_filter)

        total = conn.execute(
            f"SELECT COUNT(*) FROM referral_queue {where}",
            params,
        ).fetchone()[0]

        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT * FROM referral_queue {where} ORDER BY created_at ASC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return [_row_to_record(dict(r)) for r in rows], total
    finally:
        conn.close()


def _sync_get_sla_breaches(db_url: str, tenant_id: str) -> list[ReferralRecord]:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # Auto-update
        conn.execute(
            """
            UPDATE referral_queue SET status = 'sla_breached'
             WHERE tenant_id = ?
               AND status IN ('pending', 'claimed')
               AND sla_deadline < ?
            """,
            (tenant_id, now),
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM referral_queue WHERE tenant_id = ? AND status = 'sla_breached' ORDER BY sla_deadline ASC",
            (tenant_id,),
        ).fetchall()
        return [_row_to_record(dict(r)) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def create_referral(
    db_url: str,
    application_id: str,
    tenant_id: str,
    audit_log_id: Optional[str] = None,
    pd_score: Optional[float] = None,
    fraud_probability: Optional[float] = None,
    sla_hours: int = REFERRAL_SLA_HOURS,
) -> ReferralRecord:
    """Create a new referral entry in pending state."""
    return await asyncio.to_thread(
        _sync_create_referral,
        db_url, application_id, tenant_id,
        audit_log_id, pd_score, fraud_probability, sla_hours,
    )


async def claim_referral(
    db_url: str,
    referral_id: str,
    claimed_by: str,
) -> ReferralRecord:
    """Claim a pending referral for manual review."""
    return await asyncio.to_thread(_sync_claim_referral, db_url, referral_id, claimed_by)


async def resolve_referral(
    db_url: str,
    referral_id: str,
    resolved_by: str,
    resolution: str,
    resolution_notes: str,
    approved_by: str,
    override_db_url: Optional[str] = None,
    conditional_terms: Optional[dict] = None,
) -> ReferralRecord:
    """Resolve a referral with four-eyes approval (resolved_by != approved_by)."""
    return await asyncio.to_thread(
        _sync_resolve_referral,
        db_url, override_db_url, referral_id, resolved_by, resolution,
        resolution_notes, approved_by, conditional_terms,
    )


async def get_queue(
    db_url: str,
    tenant_id: str,
    status_filter: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[ReferralRecord], int]:
    """Return paginated referral queue for a tenant. Returns (records, total)."""
    return await asyncio.to_thread(_sync_get_queue, db_url, tenant_id, status_filter, page, per_page)


async def get_sla_breaches(
    db_url: str,
    tenant_id: str,
) -> list[ReferralRecord]:
    """Return all referrals that have exceeded their SLA deadline."""
    return await asyncio.to_thread(_sync_get_sla_breaches, db_url, tenant_id)
