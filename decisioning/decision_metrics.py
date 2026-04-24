"""
decisioning/decision_metrics.py
================================
Runtime statistics: automatic decisions vs. HITL-flagged cases.

Queries the ``audit_log`` table (for APPROVE / REJECT / MANUAL_REVIEW counts)
and the ``review_queue`` table (for HITL queue lifecycle metrics) and returns
a structured :class:`DecisionMixReport`.

Usage
-----
>>> import asyncio
>>> from decisioning.decision_metrics import get_decision_mix
>>> report = asyncio.run(
...     get_decision_mix(
...         tenant_id="tenant-abc",
...         from_date="2026-01-01",
...         to_date="2026-03-31",
...         audit_db_url="postgresql+asyncpg://...",
...         review_db_url="sqlite+aiosqlite:///./audit/review_queue.db",
...     )
... )
>>> print(report.automatic_decision_rate, report.hitl_rate)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class DecisionMixReport:
    """Aggregated automatic-vs-HITL breakdown for a tenant + date window.

    Attributes
    ----------
    tenant_id : str
        Tenant scoped in this report.
    from_date : str
        ISO-8601 inclusive start date.
    to_date : str
        ISO-8601 inclusive end date.
    total_decisions : int
        Total decisions (APPROVE + REJECT + MANUAL_REVIEW) in the window.
    automatic_approve : int
        Count of automatic APPROVE decisions.
    automatic_reject : int
        Count of automatic REJECT decisions.
    manual_review_enqueued : int
        Count of items enqueued to the review queue in the window.
    manual_review_completed : int
        Count of review items in COMPLETED status.
    manual_review_sla_breached : int
        Count of review items in SLA_BREACHED status.
    override_approve : int
        Analyst overrides to APPROVE.
    override_reject : int
        Analyst overrides to DECLINE (maps to REJECT semantics).
    automatic_decision_rate : float
        (automatic_approve + automatic_reject) / total_decisions.
    hitl_rate : float
        manual_review_enqueued / total_decisions (from audit_log).
    hitl_override_reversal_rate : float
        (override_approve + override_reject) / manual_review_enqueued.
        Measures how often analysts change the model's routing decision.
    """

    tenant_id: str
    from_date: str
    to_date: str
    total_decisions: int
    automatic_approve: int
    automatic_reject: int
    manual_review_enqueued: int
    manual_review_completed: int
    manual_review_sla_breached: int
    override_approve: int    # analyst changed MANUAL_REVIEW → APPROVE
    override_reject: int     # analyst changed MANUAL_REVIEW → DECLINE/REJECT
    automatic_decision_rate: float          # (approve+reject) / total
    hitl_rate: float                         # manual_review_enqueued / total
    hitl_override_reversal_rate: float       # cases where analyst changed outcome


# ---------------------------------------------------------------------------
# Engine cache (avoid recreating engines on repeated calls)
# ---------------------------------------------------------------------------

_ENGINE_CACHE: dict = {}


def _get_engine(db_url: str):
    if db_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[db_url] = create_async_engine(db_url, echo=False)
    return _ENGINE_CACHE[db_url]


# ---------------------------------------------------------------------------
# Main query function
# ---------------------------------------------------------------------------


async def get_decision_mix(
    tenant_id: str,
    from_date: str,
    to_date: str,
    audit_db_url: str,
    review_db_url: str,
) -> DecisionMixReport:
    """Query audit_log + review_queue to produce a :class:`DecisionMixReport`.

    Parameters
    ----------
    tenant_id : str
        Tenant to scope the audit_log query.
    from_date : str
        ISO-8601 date string (inclusive lower bound, e.g. ``"2026-01-01"``).
    to_date : str
        ISO-8601 date string (inclusive upper bound, e.g. ``"2026-03-31"``).
    audit_db_url : str
        Async SQLAlchemy URL for the audit database containing ``audit_log``.
        Example: ``"postgresql+asyncpg://user:pass@host/db"``  # pragma: allowlist secret
    review_db_url : str
        Async SQLAlchemy URL for the database containing ``review_queue``.
        Can be the same as ``audit_db_url`` when both tables share a database.

    Returns
    -------
    DecisionMixReport
        Fully populated report with rates rounded to 4 decimal places.

    Notes
    -----
    - The ``audit_log`` schema is defined in ``audit/logger.py``.
      Key columns: ``tenant_id``, ``decision_output``, ``created_at``.
    - The ``review_queue`` schema is defined in ``decisioning/review_queue.py``.
      Key columns: ``status``, ``override_decision``, ``created_at``.
    - For SQLite (development/test), use ``sqlite+aiosqlite:///./path/to/db``.
    """
    audit_engine = _get_engine(audit_db_url)
    review_engine = _get_engine(review_db_url)

    # ------------------------------------------------------------------
    # Query 1: audit_log — count APPROVE / REJECT / MANUAL_REVIEW
    # ------------------------------------------------------------------
    async with audit_engine.begin() as conn:
        totals_row = await conn.execute(
            text("""
                SELECT
                    COUNT(*)                                                          AS total,
                    SUM(CASE WHEN decision_output = 'APPROVE'        THEN 1 ELSE 0 END) AS approves,
                    SUM(CASE WHEN decision_output = 'REJECT'         THEN 1 ELSE 0 END) AS rejects,
                    SUM(CASE WHEN decision_output = 'MANUAL_REVIEW'  THEN 1 ELSE 0 END) AS manual
                FROM audit_log
                WHERE tenant_id  = :tid
                  AND created_at BETWEEN :fd AND :td
            """),
            {"tid": tenant_id, "fd": from_date, "td": to_date},
        )
        row = totals_row.fetchone()
        total    = int(row.total    or 0)
        approves = int(row.approves or 0)
        rejects  = int(row.rejects  or 0)
        manual   = int(row.manual   or 0)

    # ------------------------------------------------------------------
    # Query 2: review_queue — count by status + override outcome
    # ------------------------------------------------------------------
    async with review_engine.begin() as conn:
        rq_row = await conn.execute(
            text("""
                SELECT
                    COUNT(*)                                                               AS enqueued,
                    SUM(CASE WHEN status = 'COMPLETED'    THEN 1 ELSE 0 END)               AS completed,
                    SUM(CASE WHEN status = 'SLA_BREACHED' THEN 1 ELSE 0 END)               AS sla_breach,
                    SUM(CASE WHEN override_decision = 'APPROVE'  THEN 1 ELSE 0 END)        AS ov_approve,
                    SUM(CASE WHEN override_decision IN ('DECLINE','REJECT')
                              THEN 1 ELSE 0 END)                                           AS ov_reject
                FROM review_queue
                WHERE created_at BETWEEN :fd AND :td
            """),
            {"fd": from_date, "td": to_date},
        )
        rrow = rq_row.fetchone()

    enqueued   = int(rrow.enqueued   or 0)
    completed  = int(rrow.completed  or 0)
    sla_breach = int(rrow.sla_breach or 0)
    ov_approve = int(rrow.ov_approve or 0)
    ov_reject  = int(rrow.ov_reject  or 0)

    # ------------------------------------------------------------------
    # Compute rates
    # ------------------------------------------------------------------
    auto_rate = (approves + rejects) / total    if total    else 0.0
    hitl_rate = manual / total                  if total    else 0.0
    reversal  = (ov_approve + ov_reject) / enqueued if enqueued else 0.0

    return DecisionMixReport(
        tenant_id=tenant_id,
        from_date=from_date,
        to_date=to_date,
        total_decisions=total,
        automatic_approve=approves,
        automatic_reject=rejects,
        manual_review_enqueued=enqueued,
        manual_review_completed=completed,
        manual_review_sla_breached=sla_breach,
        override_approve=ov_approve,
        override_reject=ov_reject,
        automatic_decision_rate=round(auto_rate, 4),
        hitl_rate=round(hitl_rate, 4),
        hitl_override_reversal_rate=round(reversal, 4),
    )
