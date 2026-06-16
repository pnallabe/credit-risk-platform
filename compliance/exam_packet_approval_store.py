"""
compliance/exam_packet_approval_store.py
=========================================
Approval state machine for generated regulatory exam packets.

PRD §11.3 / Appendix C R-01 — Human-in-the-loop approval gate.

State machine:
  pending_approval  →  approved | rejected

No packet payload is accessible via the public API until status = "approved".
SOD rule: reviewed_by MUST NOT equal generated_by.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Schema init (once per process)
# ---------------------------------------------------------------------------

_SCHEMA_INIT_LOCK = threading.Lock()
_SCHEMA_INITIALISED: set[str] = set()

_DDL = """
CREATE TABLE IF NOT EXISTS exam_packet_approvals (
    packet_id        TEXT    PRIMARY KEY,
    tenant_id        TEXT    NOT NULL,
    generated_by     TEXT    NOT NULL,
    generated_at     TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending_approval',
    reviewed_by      TEXT,
    reviewed_at      TEXT,
    review_notes     TEXT,
    packet_json      TEXT    NOT NULL,
    created_at       TEXT    NOT NULL
);
"""


def _strip_url(db_url: str) -> str:
    """Strip sqlite:/// prefix if present."""
    for prefix in ("sqlite:///", "sqlite+aiosqlite:///"):
        if db_url.startswith(prefix):
            return db_url[len(prefix):]
    return db_url


def _ensure_schema(db_url: str) -> None:
    path = _strip_url(db_url)
    with _SCHEMA_INIT_LOCK:
        if path in _SCHEMA_INITIALISED:
            return
        conn = sqlite3.connect(path)
        try:
            conn.executescript(_DDL)
            conn.commit()
        finally:
            conn.close()
        _SCHEMA_INITIALISED.add(path)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExamPacketApprovalRecord:
    packet_id: str
    tenant_id: str
    generated_by: str
    generated_at: str
    status: str  # 'pending_approval' | 'approved' | 'rejected'
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    review_notes: Optional[str]
    created_at: str


def _row_to_record(row: dict) -> ExamPacketApprovalRecord:
    return ExamPacketApprovalRecord(
        packet_id=row["packet_id"],
        tenant_id=row["tenant_id"],
        generated_by=row["generated_by"],
        generated_at=row["generated_at"],
        status=row["status"],
        reviewed_by=row.get("reviewed_by"),
        reviewed_at=row.get("reviewed_at"),
        review_notes=row.get("review_notes"),
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Sync implementations (run via asyncio.to_thread)
# ---------------------------------------------------------------------------


def _sync_submit_packet(
    db_url: str,
    packet_id: str,
    tenant_id: str,
    generated_by: str,
    packet_json: str,
) -> ExamPacketApprovalRecord:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        # Check for duplicate
        existing = conn.execute(
            "SELECT packet_id FROM exam_packet_approvals WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
        if existing:
            raise ValueError(f"Packet {packet_id!r} already exists in the approval store.")

        conn.execute(
            """
            INSERT INTO exam_packet_approvals
                (packet_id, tenant_id, generated_by, generated_at, status,
                 reviewed_by, reviewed_at, review_notes, packet_json, created_at)
            VALUES (?, ?, ?, ?, 'pending_approval', NULL, NULL, NULL, ?, ?)
            """,
            (packet_id, tenant_id, generated_by, now, packet_json, now),
        )
        conn.commit()
        row = dict(
            conn.execute(
                "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
                (packet_id,),
            ).fetchone()
        )
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_approve_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: Optional[str],
) -> ExamPacketApprovalRecord:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row_raw = conn.execute(
            "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
        if row_raw is None:
            raise ValueError(f"Packet {packet_id!r} not found.")
        row = dict(row_raw)

        if row["status"] != "pending_approval":
            raise ValueError(
                f"Packet {packet_id!r} cannot be approved: current status is {row['status']!r}."
            )
        if reviewed_by == row["generated_by"]:
            raise PermissionError(
                "Approver and generator must be different users (SOD violation)."
            )

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE exam_packet_approvals
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?, review_notes = ?
             WHERE packet_id = ?
            """,
            (reviewed_by, now, review_notes, packet_id),
        )
        conn.commit()
        row = dict(
            conn.execute(
                "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
                (packet_id,),
            ).fetchone()
        )
        # Write to audit_log if possible
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO audit_log
                    (log_id, tenant_id, action, decision_output, logged_at,
                     previous_hash, record_hash, hash_algorithm)
                VALUES (?, ?, 'EXAM_PACKET_APPROVED', ?, ?, 'GENESIS', 'N/A', 'sha256')
                """,
                (str(uuid.uuid4()), row["tenant_id"], packet_id, now),
            )
            conn.commit()
        except Exception:
            pass
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_reject_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: str,
) -> ExamPacketApprovalRecord:
    _ensure_schema(db_url)
    if not review_notes or len(review_notes.strip()) < 10:
        raise ValueError("review_notes must be at least 10 characters when rejecting a packet.")
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row_raw = conn.execute(
            "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
        if row_raw is None:
            raise ValueError(f"Packet {packet_id!r} not found.")
        row = dict(row_raw)

        if row["status"] != "pending_approval":
            raise ValueError(
                f"Packet {packet_id!r} cannot be rejected: current status is {row['status']!r}."
            )
        if reviewed_by == row["generated_by"]:
            raise PermissionError(
                "Approver and generator must be different users (SOD violation)."
            )

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE exam_packet_approvals
               SET status = 'rejected', reviewed_by = ?, reviewed_at = ?, review_notes = ?
             WHERE packet_id = ?
            """,
            (reviewed_by, now, review_notes, packet_id),
        )
        conn.commit()
        row = dict(
            conn.execute(
                "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
                (packet_id,),
            ).fetchone()
        )
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO audit_log
                    (log_id, tenant_id, action, decision_output, logged_at,
                     previous_hash, record_hash, hash_algorithm)
                VALUES (?, ?, 'EXAM_PACKET_REJECTED', ?, ?, 'GENESIS', 'N/A', 'sha256')
                """,
                (str(uuid.uuid4()), row["tenant_id"], packet_id, now),
            )
            conn.commit()
        except Exception:
            pass
        return _row_to_record(row)
    finally:
        conn.close()


def _sync_get_approval_record(db_url: str, packet_id: str) -> Optional[ExamPacketApprovalRecord]:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row_raw = conn.execute(
            "SELECT * FROM exam_packet_approvals WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
        if row_raw is None:
            return None
        return _row_to_record(dict(row_raw))
    finally:
        conn.close()


def _sync_get_approved_packet_json(db_url: str, packet_id: str) -> Optional[str]:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        row_raw = conn.execute(
            "SELECT status, packet_json FROM exam_packet_approvals WHERE packet_id = ?",
            (packet_id,),
        ).fetchone()
        if row_raw is None:
            return None
        row = dict(row_raw)
        if row["status"] == "approved":
            return row["packet_json"]
        raise PermissionError(
            f"Packet {packet_id!r} is not approved (status={row['status']!r}). "
            "Packet payload is only available after approval."
        )
    finally:
        conn.close()


def _sync_list_pending_packets(db_url: str, tenant_id: str) -> list:
    _ensure_schema(db_url)
    path = _strip_url(db_url)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM exam_packet_approvals WHERE tenant_id = ? AND status = 'pending_approval' ORDER BY created_at ASC",
            (tenant_id,),
        ).fetchall()
        return [_row_to_record(dict(r)) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def submit_packet_for_approval(
    db_url: str,
    packet_id: str,
    tenant_id: str,
    generated_by: str,
    packet_json: str,
) -> ExamPacketApprovalRecord:
    """Store the generated packet in pending_approval state.
    Raises ValueError if packet_id already exists.
    """
    return await asyncio.to_thread(
        _sync_submit_packet, db_url, packet_id, tenant_id, generated_by, packet_json
    )


async def approve_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: Optional[str] = None,
) -> ExamPacketApprovalRecord:
    """Approve the packet. Raises PermissionError for SOD violation, ValueError if not pending."""
    return await asyncio.to_thread(
        _sync_approve_packet, db_url, packet_id, reviewed_by, review_notes
    )


async def reject_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: str,
) -> ExamPacketApprovalRecord:
    """Reject the packet. review_notes required (min 10 chars). Raises PermissionError for SOD."""
    return await asyncio.to_thread(
        _sync_reject_packet, db_url, packet_id, reviewed_by, review_notes
    )


async def get_approval_record(
    db_url: str,
    packet_id: str,
) -> Optional[ExamPacketApprovalRecord]:
    """Return the approval record or None if not found."""
    return await asyncio.to_thread(_sync_get_approval_record, db_url, packet_id)


async def get_approved_packet_json(
    db_url: str,
    packet_id: str,
) -> Optional[str]:
    """Return packet JSON only if status == 'approved'. Raises PermissionError otherwise."""
    return await asyncio.to_thread(_sync_get_approved_packet_json, db_url, packet_id)


async def list_pending_packets(
    db_url: str,
    tenant_id: str,
) -> list[ExamPacketApprovalRecord]:
    """Return all packets with status='pending_approval' for a tenant."""
    return await asyncio.to_thread(_sync_list_pending_packets, db_url, tenant_id)
