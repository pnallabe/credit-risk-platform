"""
scripts/check_adverse_action_deadlines.py
==========================================
Run as a scheduled job (cron / Cloud Scheduler) daily.

Usage:
    python scripts/check_adverse_action_deadlines.py

Environment variables:
    DB_URL        SQLAlchemy async DB URL (default: sqlite+aiosqlite:///./decision_audit.db)
    TENANT_IDS    Comma-separated list of tenant IDs to check

Exit codes:
    0  — No alerts fired
    1  — One or more deadline alerts fired (use in CI/CD monitoring)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Make project root importable when run directly
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("check_adverse_action_deadlines")


async def _main() -> int:
    db_url = os.getenv("DB_URL", "sqlite+aiosqlite:///./decision_audit.db")
    tenant_ids_raw = os.getenv("TENANT_IDS", "")
    tenant_ids = [t.strip() for t in tenant_ids_raw.split(",") if t.strip()]

    if not tenant_ids:
        logger.warning("TENANT_IDS is not set — no tenants to check.")
        return 0

    from monitoring.alert_router import AlertRouter, build_channels_from_env
    from monitoring.alert_router import check_adverse_action_deadlines

    router = AlertRouter(channels=build_channels_from_env())
    total_alerted = 0

    for tid in tenant_ids:
        try:
            count = await check_adverse_action_deadlines(
                db_url=db_url,
                tenant_id=tid,
                router=router,
            )
            total_alerted += count
            if count:
                logger.warning(
                    "Tenant %s: %d adverse action notice(s) approaching deadline", tid, count
                )
            else:
                logger.info("Tenant %s: no upcoming adverse action deadlines", tid)
        except Exception as exc:
            logger.error("Error checking tenant %s: %s", tid, exc)

    if total_alerted > 0:
        logger.warning("Total: %d adverse action alerts fired", total_alerted)
        return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
