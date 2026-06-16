"""
compliance/adverse_action_store.py
====================================
Persistence layer for Reg B adverse action notices.

Uses the ``adverse_action_log`` table defined in ``audit.logger``.

Public API
----------
>>> from compliance.adverse_action_store import (
...     save_notice,
...     mark_delivered,
...     get_notice,
...     list_notices,
...     get_pending_deadline_notices,
... )
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text

from audit.logger import (
    _CREATE_ADVERSE_ACTION_TABLE,
    _get_engine,
    _sha256,
    compute_chain_hash,
)
from compliance.adverse_action import AdverseActionNotice

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DDL helper
# ---------------------------------------------------------------------------

async def _ensure_table(conn: Any) -> None:
    """Create the adverse_action_log table (and indices) if absent."""
    for stmt in _CREATE_ADVERSE_ACTION_TABLE.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# INSERT / UPDATE helpers
# ---------------------------------------------------------------------------

_INSERT_AA = """
INSERT INTO adverse_action_log (
    notice_id, application_id, tenant_id,
    action_date, deadline_date,
    reason_codes, form_type,
    credit_score_used, bureau_name,
    generated_at,
    delivery_channel, delivered_at, delivery_status,
    notice_hash,
    record_hash, previous_hash
) VALUES (
    :notice_id, :application_id, :tenant_id,
    :action_date, :deadline_date,
    :reason_codes, :form_type,
    :credit_score_used, :bureau_name,
    :generated_at,
    :delivery_channel, :delivered_at, :delivery_status,
    :notice_hash,
    :record_hash, :previous_hash
)
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def save_notice(
    notice: AdverseActionNotice,
    notice_text: str,
    db_url: str,
) -> str:
    """Persist a new adverse action notice and return its ``notice_id``.

    Parameters
    ----------
    notice:
        Populated :class:`AdverseActionNotice` instance.
    notice_text:
        Plain-text rendering from ``render_c1_text(notice)`` — hashed
        for tamper evidence.
    db_url:
        SQLAlchemy async DB URL.

    Returns
    -------
    str — ``notice_id``

    Raises
    ------
    ValueError
        If a notice with the same ``notice_id`` already exists.
    """
    notice_hash = _sha256(notice_text)

    canonical_payload = json.dumps(
        {
            "action_date":    notice.action_date,
            "deadline_date":  notice.deadline_date,
            "form_type":      notice.form_type,
            "reason_codes":   json.dumps(sorted(notice.reason_codes)),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        await _ensure_table(conn)

        # Duplicate check
        existing = await conn.execute(
            text("SELECT notice_id FROM adverse_action_log WHERE notice_id = :nid"),
            {"nid": notice.notice_id},
        )
        if existing.fetchone() is not None:
            raise ValueError(
                f"Notice with notice_id={notice.notice_id!r} already exists"
            )

        # Compute hash chain
        record_hash, previous_hash = await compute_chain_hash(
            conn,
            notice.notice_id,
            notice.generated_at,
            canonical_payload,
            notice.tenant_id,
            table="adverse_action_log",
            partition_field="tenant_id",
            timestamp_field="generated_at",
            id_field="notice_id",
        )

        params: Dict[str, Any] = {
            "notice_id":        notice.notice_id,
            "application_id":   notice.application_id,
            "tenant_id":        notice.tenant_id,
            "action_date":      notice.action_date,
            "deadline_date":    notice.deadline_date,
            "reason_codes":     json.dumps(notice.reason_codes),
            "form_type":        notice.form_type,
            "credit_score_used": notice.credit_score_used,
            "bureau_name":      notice.bureau_name,
            "generated_at":     notice.generated_at,
            "delivery_channel": notice.delivery_channel,
            "delivered_at":     notice.delivered_at,
            "delivery_status":  notice.delivery_status,
            "notice_hash":      notice_hash,
            "record_hash":      record_hash,
            "previous_hash":    previous_hash,
        }
        await conn.execute(text(_INSERT_AA), params)

    logger.info(
        "Adverse action notice saved: notice_id=%s application_id=%s tenant_id=%s",
        notice.notice_id,
        notice.application_id,
        notice.tenant_id,
    )
    return notice.notice_id


async def mark_delivered(
    notice_id: str,
    delivery_channel: str,
    delivered_at: str,
    db_url: str,
    tenant_id: str,
) -> None:
    """Mark a notice as DELIVERED.

    Raises
    ------
    ValueError
        If *notice_id* does not belong to *tenant_id*.
    """
    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        await _ensure_table(conn)

        row = await conn.execute(
            text(
                "SELECT tenant_id FROM adverse_action_log WHERE notice_id = :nid"
            ),
            {"nid": notice_id},
        )
        existing = row.fetchone()
        if existing is None or existing[0] != tenant_id:
            raise ValueError(
                f"notice_id={notice_id!r} not found or does not belong to tenant {tenant_id!r}"
            )

        await conn.execute(
            text(
                "UPDATE adverse_action_log"
                " SET delivery_channel = :ch, delivered_at = :dat,"
                "     delivery_status = 'DELIVERED'"
                " WHERE notice_id = :nid AND tenant_id = :tid"
            ),
            {
                "ch":  delivery_channel,
                "dat": delivered_at,
                "nid": notice_id,
                "tid": tenant_id,
            },
        )


async def get_notice(
    notice_id: str,
    db_url: str,
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Return a notice by ID scoped to *tenant_id*, or ``None``."""
    engine = _get_engine(db_url)

    try:
        async with engine.connect() as conn:
            await _ensure_table(conn)
            result = await conn.execute(
                text(
                    "SELECT * FROM adverse_action_log"
                    " WHERE notice_id = :nid AND tenant_id = :tid"
                ),
                {"nid": notice_id, "tid": tenant_id},
            )
            row = result.mappings().fetchone()
    except Exception:
        return None

    if row is None:
        return None

    record = dict(row)
    if record.get("reason_codes"):
        try:
            record["reason_codes"] = json.loads(record["reason_codes"])
        except (json.JSONDecodeError, TypeError):
            pass
    return record


async def list_notices(
    db_url: str,
    tenant_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 100,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return a paginated list of notices for *tenant_id*.

    Returns
    -------
    tuple[list[dict], int]
        ``(records, total_count)``
    """
    engine = _get_engine(db_url)

    where = ["tenant_id = :tid"]
    params: Dict[str, Any] = {"tid": tenant_id}

    if from_date:
        where.append("action_date >= :from_date")
        params["from_date"] = from_date
    if to_date:
        where.append("action_date <= :to_date")
        params["to_date"] = to_date
    if status:
        where.append("delivery_status = :status")
        params["status"] = status

    where_sql = " AND ".join(where)
    offset = (max(page, 1) - 1) * per_page

    try:
        async with engine.connect() as conn:
            await _ensure_table(conn)

            count_result = await conn.execute(
                text(f"SELECT COUNT(*) FROM adverse_action_log WHERE {where_sql}"),
                params,
            )
            total = count_result.scalar() or 0

            params["limit"] = per_page
            params["offset"] = offset
            rows_result = await conn.execute(
                text(
                    f"SELECT * FROM adverse_action_log WHERE {where_sql}"
                    " ORDER BY action_date DESC"
                    " LIMIT :limit OFFSET :offset"
                ),
                params,
            )
            rows = [dict(r) for r in rows_result.mappings().fetchall()]
    except Exception as exc:
        logger.error("list_notices failed: %s", exc)
        return [], 0

    for rec in rows:
        if rec.get("reason_codes"):
            try:
                rec["reason_codes"] = json.loads(rec["reason_codes"])
            except (json.JSONDecodeError, TypeError):
                pass

    return rows, int(total)


async def get_pending_deadline_notices(
    db_url: str,
    tenant_id: str,
    warn_days_before: int = 5,
) -> List[Dict[str, Any]]:
    """Return PENDING notices with deadline within *warn_days_before* days.

    Parameters
    ----------
    warn_days_before:
        Alert if ``deadline_date <= today + warn_days_before``.
    """
    today = date.today()
    cutoff = (today + timedelta(days=warn_days_before)).isoformat()

    engine = _get_engine(db_url)

    try:
        async with engine.connect() as conn:
            await _ensure_table(conn)
            result = await conn.execute(
                text(
                    "SELECT * FROM adverse_action_log"
                    " WHERE tenant_id = :tid"
                    "   AND delivery_status = 'PENDING'"
                    "   AND deadline_date <= :cutoff"
                    " ORDER BY deadline_date ASC"
                ),
                {"tid": tenant_id, "cutoff": cutoff},
            )
            rows = [dict(r) for r in result.mappings().fetchall()]
    except Exception as exc:
        logger.error("get_pending_deadline_notices failed: %s", exc)
        return []

    for rec in rows:
        if rec.get("reason_codes"):
            try:
                rec["reason_codes"] = json.loads(rec["reason_codes"])
            except (json.JSONDecodeError, TypeError):
                pass

    return rows
