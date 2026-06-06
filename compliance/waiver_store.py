"""
Waiver Store — S5-A
====================
SQLite-backed waiver management with four-eyes enforcement.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "waivers.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS waivers (
    waiver_id            TEXT PRIMARY KEY,
    application_id       TEXT NOT NULL,
    policy_rule_id       TEXT NOT NULL,
    policy_rule_description TEXT NOT NULL,
    waiver_reason        TEXT NOT NULL,
    requested_by         TEXT NOT NULL,
    requested_at         TEXT NOT NULL,
    approved_by          TEXT,
    approved_at          TEXT,
    denied_by            TEXT,
    denied_at            TEXT,
    denial_reason        TEXT,
    expires_at           TEXT,
    scope                TEXT NOT NULL DEFAULT 'single',
    status               TEXT NOT NULL DEFAULT 'pending',
    notes                TEXT
);
CREATE INDEX IF NOT EXISTS idx_waivers_status ON waivers(status);
CREATE INDEX IF NOT EXISTS idx_waivers_rule   ON waivers(policy_rule_id);
"""


@dataclass(frozen=True)
class Waiver:
    waiver_id: str
    application_id: str
    policy_rule_id: str
    policy_rule_description: str
    waiver_reason: str
    requested_by: str
    requested_at: str
    approved_by: Optional[str]
    approved_at: Optional[str]
    denied_by: Optional[str]
    denied_at: Optional[str]
    denial_reason: Optional[str]
    expires_at: Optional[str]
    scope: Literal["single", "portfolio"]
    status: Literal["pending", "approved", "denied", "expired"]
    notes: Optional[str]


def _row_to_waiver(row: dict) -> Waiver:
    return Waiver(
        waiver_id=row["waiver_id"],
        application_id=row["application_id"],
        policy_rule_id=row["policy_rule_id"],
        policy_rule_description=row["policy_rule_description"],
        waiver_reason=row["waiver_reason"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        approved_by=row.get("approved_by"),
        approved_at=row.get("approved_at"),
        denied_by=row.get("denied_by"),
        denied_at=row.get("denied_at"),
        denial_reason=row.get("denial_reason"),
        expires_at=row.get("expires_at"),
        scope=row.get("scope", "single"),
        status=row.get("status", "pending"),
        notes=row.get("notes"),
    )


class WaiverStore:
    """SQLite-backed waiver store with four-eyes enforcement."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = str(db_path or _DEFAULT_DB_PATH)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE_SQL)

    def _audit(self, event_type: str, waiver_id: str, actor: str, details: str = "") -> None:
        try:
            log.info("[WAIVER_%s] waiver_id=%s actor=%s %s", event_type, waiver_id, actor, details)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def request_waiver(
        self,
        application_id: str,
        policy_rule_id: str,
        policy_rule_description: str,
        waiver_reason: str,
        requested_by: str,
        scope: Literal["single", "portfolio"] = "single",
        expires_at: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Waiver:
        waiver_id = str(uuid.uuid4())
        requested_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO waivers (
                    waiver_id, application_id, policy_rule_id, policy_rule_description,
                    waiver_reason, requested_by, requested_at, scope, expires_at,
                    status, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    waiver_id, application_id, policy_rule_id, policy_rule_description,
                    waiver_reason, requested_by, requested_at, scope, expires_at,
                    "pending", notes,
                ),
            )
        waiver = self.get_waiver(waiver_id)
        self._audit("REQUESTED", waiver_id, requested_by)
        return waiver

    def approve_waiver(self, waiver_id: str, approved_by: str) -> Waiver:
        current = self.get_waiver(waiver_id)
        if current.status != "pending":
            raise ValueError(f"Waiver {waiver_id} is not pending (status={current.status})")
        if current.requested_by == approved_by:
            raise PermissionError(
                f"Four-eyes violation: approver '{approved_by}' cannot approve "
                f"their own waiver request."
            )
        approved_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE waivers SET status='approved', approved_by=?, approved_at=? WHERE waiver_id=?",
                (approved_by, approved_at, waiver_id),
            )
        self._audit("APPROVED", waiver_id, approved_by)
        return self.get_waiver(waiver_id)

    def deny_waiver(self, waiver_id: str, denied_by: str, denial_reason: str) -> Waiver:
        current = self.get_waiver(waiver_id)
        if current.status != "pending":
            raise ValueError(f"Waiver {waiver_id} is not pending (status={current.status})")
        denied_at = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE waivers SET status='denied', denied_by=?, denied_at=?, denial_reason=? WHERE waiver_id=?",
                (denied_by, denied_at, denial_reason, waiver_id),
            )
        self._audit("DENIED", waiver_id, denied_by, f"reason={denial_reason}")
        return self.get_waiver(waiver_id)

    def get_waiver(self, waiver_id: str) -> Waiver:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM waivers WHERE waiver_id=?", (waiver_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Waiver {waiver_id} not found")
        return _row_to_waiver(dict(row))

    def list_waivers(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Waiver]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM waivers WHERE status=? ORDER BY requested_at DESC LIMIT ? OFFSET ?",
                    (status, limit, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM waivers ORDER BY requested_at DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
        return [_row_to_waiver(dict(r)) for r in rows]

    def expire_stale_waivers(self) -> int:
        """Mark all pending waivers whose expires_at is in the past as 'expired'.

        Returns the number of waivers expired.
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE waivers
                SET status='expired'
                WHERE status='pending'
                  AND expires_at IS NOT NULL
                  AND expires_at < ?
                """,
                (now,),
            )
            count = cur.rowcount
        if count > 0:
            log.info("Expired %d stale waiver(s).", count)
        return count

    def generate_report(self, period_days: int = 30) -> dict:
        """Generate a summary report for the given period in days."""
        from datetime import timedelta
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=period_days)).isoformat()
        period_label = f"{period_days}d"

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM waivers WHERE requested_at >= ?", (cutoff,)
            ).fetchall()

        waivers = [_row_to_waiver(dict(r)) for r in rows]
        total = len(waivers)
        approved = sum(1 for w in waivers if w.status == "approved")
        denied = sum(1 for w in waivers if w.status == "denied")

        by_rule: dict[str, dict] = {}
        for w in waivers:
            if w.policy_rule_id not in by_rule:
                by_rule[w.policy_rule_id] = {"rule_id": w.policy_rule_id, "count": 0, "approved": 0}
            by_rule[w.policy_rule_id]["count"] += 1
            if w.status == "approved":
                by_rule[w.policy_rule_id]["approved"] += 1

        return {
            "period": period_label,
            "total_requested": total,
            "total_approved": approved,
            "total_denied": denied,
            "approval_rate": round(approved / total, 4) if total > 0 else 0.0,
            "by_policy_rule": list(by_rule.values()),
        }
