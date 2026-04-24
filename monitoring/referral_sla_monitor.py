"""
monitoring/referral_sla_monitor.py
====================================
Detect referral cases that have exceeded the SLA deadline without resolution
and fire an alert via the existing AlertRouter.

Mirrors the pattern in monitoring/cc_pd_monitor.py.

Suggested APScheduler config:
    scheduler.add_job(
        monitor_referral_sla,
        "interval",
        hours=1,
        kwargs={"db_url": REFERRAL_DB_URL, "tenant_id": TENANT_ID},
        id="referral_sla_monitor",
    )
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReferralSLAReport:
    checked_at: str          # ISO-8601 UTC
    tenant_id: str
    breach_count: int
    breach_referral_ids: list
    alert_fired: bool


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------


async def monitor_referral_sla(
    db_url: str,
    tenant_id: str,
    get_breaches_fn: Optional[Callable] = None,
    alert_router=None,
) -> ReferralSLAReport:
    """
    Detect referral SLA breaches and fire an alert if any are found.

    Parameters
    ----------
    db_url:
        SQLite path / URL for the referral_queue DB.
    tenant_id:
        Tenant to check.
    get_breaches_fn:
        Injectable callable for testability; defaults to
        ``referral_store.get_sla_breaches``.
    alert_router:
        AlertRouter instance; defaults to DEFAULT_ALERT_ROUTER.

    Returns
    -------
    ReferralSLAReport
    """
    checked_at = datetime.now(timezone.utc).isoformat()

    # Resolve defaults
    if alert_router is None:
        try:
            from monitoring.alert_router import DEFAULT_ALERT_ROUTER  # noqa: PLC0415
            alert_router = DEFAULT_ALERT_ROUTER
        except Exception:
            alert_router = None

    if get_breaches_fn is None:
        try:
            # Lazy import to avoid circular dependency at module level
            import sys as _sys  # noqa: PLC0415
            import os as _os  # noqa: PLC0415
            _src = _os.path.join(_os.path.dirname(__file__), "..", "decision-api", "src")
            if _src not in _sys.path:
                _sys.path.insert(0, _src)
            from referral_store import get_sla_breaches  # noqa: PLC0415
            get_breaches_fn = get_sla_breaches
        except ImportError:
            logger.warning("referral_store not importable; returning empty report.")
            return ReferralSLAReport(
                checked_at=checked_at,
                tenant_id=tenant_id,
                breach_count=0,
                breach_referral_ids=[],
                alert_fired=False,
            )

    try:
        breaches = await get_breaches_fn(db_url, tenant_id)
    except Exception as exc:
        logger.error("Error fetching SLA breaches for tenant=%s: %s", tenant_id, exc)
        return ReferralSLAReport(
            checked_at=checked_at,
            tenant_id=tenant_id,
            breach_count=0,
            breach_referral_ids=[],
            alert_fired=False,
        )

    breach_ids = [r.referral_id for r in breaches]
    breach_count = len(breach_ids)
    alert_fired = False

    if breach_count > 0 and alert_router is not None:
        try:
            subject = f"[REFERRAL SLA BREACH] {breach_count} case(s) overdue — tenant={tenant_id}"
            body = (
                f"The following referral cases have exceeded their SLA deadline "
                f"without resolution:\n\n"
                + "\n".join(f"  - {rid}" for rid in breach_ids[:25])
                + ("\n  ... (truncated)" if breach_count > 25 else "")
                + f"\n\nChecked at: {checked_at}"
            )
            alert_router.dispatch(subject=subject, body=body, severity="HIGH")
            alert_fired = True
            logger.info("SLA breach alert fired: %d breach(es) for tenant=%s", breach_count, tenant_id)
        except Exception as exc:
            logger.error("Failed to fire SLA breach alert: %s", exc)

    return ReferralSLAReport(
        checked_at=checked_at,
        tenant_id=tenant_id,
        breach_count=breach_count,
        breach_referral_ids=breach_ids,
        alert_fired=alert_fired,
    )
