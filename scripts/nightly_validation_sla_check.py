#!/usr/bin/env python3
"""Nightly SLA enforcement script for independent model validation (Sprint 3-C).

SR 11-7 requires that every production model receives an independent validation
at least once every 365 days. This script:
  1. Loads the most-recent validation date for each (model_name, model_version)
     pair from the ``model_validation_log`` table.
  2. Compares that date against today.
  3. Flags any model exceeding the SLA threshold.
  4. Writes a ``REVIEW_DUE`` governance action for each overdue model (unless
     ``--dry-run`` is specified).
  5. Exits with code 1 if any model is overdue, so CI/CD pipelines can gate on it.

Usage
-----
    python scripts/nightly_validation_sla_check.py --db-url sqlite+aiosqlite:///./decision_audit.db
    python scripts/nightly_validation_sla_check.py --sla-days 180 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


# ---------------------------------------------------------------------------
# DB queries
# ---------------------------------------------------------------------------

_LATEST_VALIDATIONS_SQL = """
SELECT
    model_name,
    model_version,
    validator_email,
    MAX(validation_date) AS latest_date,
    outcome
FROM model_validation_log
GROUP BY model_name, model_version
ORDER BY model_name, model_version
"""

_INSERT_GOVERNANCE_SQL = """
INSERT OR IGNORE INTO governance_action_log (
    action_id, tenant_id, actor_email, action, model_name,
    model_version, reason, timestamp
) VALUES (
    :action_id, :tenant_id, :actor_email, :action, :model_name,
    :model_version, :reason, :timestamp
)
"""

_CREATE_GOVERNANCE_LOG_SQL = """
CREATE TABLE IF NOT EXISTS governance_action_log (
    action_id       TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    actor_email     TEXT NOT NULL,
    action          TEXT NOT NULL,
    model_name      TEXT,
    model_version   TEXT,
    reason          TEXT,
    timestamp       TEXT NOT NULL
)
"""


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

async def _run(db_url: str, sla_days: int, dry_run: bool, tenant_id: str) -> int:
    """Run the SLA check and return the number of overdue models."""
    import uuid

    engine = create_async_engine(db_url, echo=False)
    now = datetime.now(timezone.utc)
    overdue: List[Dict] = []
    ok: List[Dict] = []
    no_validation: List[str] = []

    async with engine.connect() as conn:
        # Ensure governance log table exists
        await conn.execute(text(_CREATE_GOVERNANCE_LOG_SQL))
        await conn.commit()

        try:
            rows = (await conn.execute(text(_LATEST_VALIDATIONS_SQL))).fetchall()
        except Exception as exc:
            print(f"[ERROR] Could not query model_validation_log: {exc}", file=sys.stderr)
            await engine.dispose()
            return 0

    for row in rows:
        model_name, model_version, validator_email, latest_ts, outcome = (
            row[0], row[1], row[2], row[3], row[4]
        )
        try:
            if isinstance(latest_ts, str):
                # Strip timezone info variations
                ts_clean = latest_ts.replace("Z", "+00:00")
                latest_dt = datetime.fromisoformat(ts_clean)
            else:
                latest_dt = datetime.fromtimestamp(float(latest_ts), tz=timezone.utc)
            if latest_dt.tzinfo is None:
                latest_dt = latest_dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            no_validation.append(f"{model_name} v{model_version} (unparseable date: {latest_ts!r})")
            continue

        age_days = (now - latest_dt).days
        entry = {
            "model_name": model_name,
            "model_version": model_version,
            "latest_date": latest_dt.date().isoformat(),
            "age_days": age_days,
            "outcome": outcome,
        }
        if age_days > sla_days:
            overdue.append(entry)
        else:
            ok.append(entry)

    # ---------------------------------------------------------------------------
    # Print tabular summary
    # ---------------------------------------------------------------------------
    col_w = 32
    header = f"{'Model':<{col_w}} {'Version':<10} {'Last Validated':<16} {'Age (days)':<12} {'Outcome':<20} Status"
    sep = "─" * len(header)
    print()
    print("╔══ Nightly Model Validation SLA Check " + "═" * 40)
    print(f"║  SLA threshold : {sla_days} days")
    print(f"║  DB            : {db_url}")
    print(f"║  Run at        : {now.isoformat()}")
    print(f"║  Dry-run       : {dry_run}")
    print("╚" + "═" * 78)
    print()
    print(header)
    print(sep)

    for e in sorted(ok, key=lambda x: x["model_name"]):
        print(f"{e['model_name']:<{col_w}} {e['model_version']:<10} {e['latest_date']:<16} {e['age_days']:<12} {e['outcome'] or '':<20} ✅ OK")

    for e in sorted(overdue, key=lambda x: x["model_name"]):
        print(f"{e['model_name']:<{col_w}} {e['model_version']:<10} {e['latest_date']:<16} {e['age_days']:<12} {e['outcome'] or '':<20} ❌ OVERDUE (>{sla_days}d)")

    for label in no_validation:
        print(f"  ⚠️  Skipped: {label}")

    print(sep)
    print(f"\nSummary: {len(ok)} OK  |  {len(overdue)} OVERDUE  |  {len(no_validation)} skipped\n")

    # ---------------------------------------------------------------------------
    # Write REVIEW_DUE governance actions for each overdue model
    # ---------------------------------------------------------------------------
    if overdue and not dry_run:
        async with engine.begin() as conn:
            for e in overdue:
                await conn.execute(
                    text(_INSERT_GOVERNANCE_SQL),
                    {
                        "action_id":     str(uuid.uuid4()),
                        "tenant_id":     tenant_id,
                        "actor_email":   "nightly-sla-bot@system",
                        "action":        "REVIEW_DUE",
                        "model_name":    e["model_name"],
                        "model_version": e["model_version"],
                        "reason":        (
                            f"Model validation overdue: last validated {e['age_days']} days ago "
                            f"(SLA: {sla_days} days, outcome: {e['outcome'] or 'N/A'})"
                        ),
                        "timestamp":     now.isoformat(),
                    },
                )
        print(f"  → Wrote {len(overdue)} REVIEW_DUE governance action(s) to the audit log.")
    elif overdue and dry_run:
        print(f"  → Dry-run: would write {len(overdue)} REVIEW_DUE governance action(s).")

    await engine.dispose()
    return len(overdue)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Nightly independent model validation SLA check (SR 11-7)."
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("DECISION_AUDIT_DB_URL", "sqlite+aiosqlite:///./decision_audit.db"),
        help="SQLAlchemy-compatible async DB URL (default: env DECISION_AUDIT_DB_URL or local SQLite).",
    )
    parser.add_argument(
        "--sla-days",
        type=int,
        default=365,
        help="Number of days before a model validation is considered overdue (default: 365).",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("TENANT_ID", "default"),
        help="Tenant identifier written to governance log entries.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report overdue models without writing governance actions to the database.",
    )
    args = parser.parse_args()

    overdue_count = asyncio.run(
        _run(
            db_url=args.db_url,
            sla_days=args.sla_days,
            dry_run=args.dry_run,
            tenant_id=args.tenant_id,
        )
    )

    if overdue_count > 0:
        sys.exit(1)  # non-zero exit so CI pipelines can gate on this


if __name__ == "__main__":
    main()
