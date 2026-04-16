"""
compliance/committee_approval_store.py
=======================================
Lightweight SQLite/PostgreSQL store for Model Risk Committee approvals.

These records become part of the exam packet under the
"committee_approvals" component.

Public API
----------
>>> from compliance.committee_approval_store import (
...     CommitteeApproval,
...     save_approval,
...     list_approvals,
... )
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Engine cache (shared with audit.logger pattern)
# ---------------------------------------------------------------------------
try:
    from audit.logger import _ENGINE_CACHE, _get_engine  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _ENGINE_CACHE: dict = {}  # type: ignore[assignment]

    def _get_engine(db_url: str):  # type: ignore[return]
        if db_url not in _ENGINE_CACHE:
            _ENGINE_CACHE[db_url] = create_async_engine(db_url, echo=False)
        return _ENGINE_CACHE[db_url]


# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS committee_approvals (
    approval_id   TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    subject       TEXT NOT NULL,
    approval_type TEXT NOT NULL,
    submitted_by  TEXT NOT NULL,
    approved_by   TEXT NOT NULL,
    approved_at   TEXT NOT NULL,
    notes         TEXT NOT NULL DEFAULT '',
    effective_date TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ca_tenant_date
    ON committee_approvals (tenant_id, approved_at);
"""

_INSERT = """
INSERT INTO committee_approvals (
    approval_id, tenant_id, subject, approval_type,
    submitted_by, approved_by, approved_at, notes, effective_date, created_at
) VALUES (
    :approval_id, :tenant_id, :subject, :approval_type,
    :submitted_by, :approved_by, :approved_at, :notes, :effective_date, :created_at
)
"""

_SELECT = """
SELECT approval_id, tenant_id, subject, approval_type,
       submitted_by, approved_by, approved_at, notes, effective_date, created_at
FROM committee_approvals
WHERE tenant_id = :tenant_id
  AND approved_at BETWEEN :from_date AND :to_date_end
ORDER BY approved_at DESC
"""


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class CommitteeApproval:
    """A Model Risk Committee approval record."""

    approval_id: str
    tenant_id: str
    subject: str
    approval_type: str          # "POLICY_CHANGE" | "MODEL_APPROVAL" | "LIMIT_INCREASE"
    submitted_by: str
    approved_by: str
    approved_at: str            # ISO-8601 UTC
    notes: str
    effective_date: str         # YYYY-MM-DD


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def save_approval(approval: CommitteeApproval, db_url: str) -> str:
    """Persist *approval* and return its ``approval_id``."""
    engine = _get_engine(db_url)
    now = datetime.now(timezone.utc).isoformat()
    params = {
        "approval_id":   approval.approval_id,
        "tenant_id":     approval.tenant_id,
        "subject":       approval.subject,
        "approval_type": approval.approval_type,
        "submitted_by":  approval.submitted_by,
        "approved_by":   approval.approved_by,
        "approved_at":   approval.approved_at,
        "notes":         approval.notes or "",
        "effective_date": approval.effective_date,
        "created_at":    now,
    }
    async with engine.begin() as conn:
        for stmt in _CREATE_TABLE.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
        await conn.execute(text(_INSERT), params)
    return approval.approval_id


async def list_approvals(
    tenant_id: str,
    from_date: str,
    to_date: str,
    db_url: str,
) -> List[CommitteeApproval]:
    """Return committee approvals for *tenant_id* in [from_date, to_date]."""
    engine = _get_engine(db_url)
    to_date_end = to_date + "T23:59:59"
    async with engine.begin() as conn:
        for stmt in _CREATE_TABLE.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                await conn.execute(text(stmt))
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT),
                {"tenant_id": tenant_id, "from_date": from_date, "to_date_end": to_date_end},
            )
        except Exception:
            return []
        rows = result.mappings().fetchall()

    return [
        CommitteeApproval(
            approval_id=r["approval_id"],
            tenant_id=r["tenant_id"],
            subject=r["subject"],
            approval_type=r["approval_type"],
            submitted_by=r["submitted_by"],
            approved_by=r["approved_by"],
            approved_at=r["approved_at"],
            notes=r["notes"],
            effective_date=r["effective_date"],
        )
        for r in rows
    ]
