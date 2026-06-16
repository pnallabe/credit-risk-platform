"""
check_model_review_due.py — Section 21.4.2
============================================
Daily cron job (Cloud Scheduler / crontab) that checks whether any Production
model is overdue for its annual/semi-annual review and fires alerts.

Review schedule (from MODEL_GOVERNANCE):
  cc_pd_model                 — every 12 months
  cc_origination_valuation    — every 12 months
  cc_portfolio_action         — every 6 months
  mortgage_valuation_model    — every 12 months

Trigger logic:
  For each Production model in the registry:
    1. Read governance_approval_log → most recent PROMOTE_PRODUCTION date
    2. If (today - last_promoted_date) >= review_cycle_months * 30 days:
       → log WARNING
       → write governance_approval_log with action = "REVIEW_DUE"
       → send alert to model_owner_email (Cloud Monitoring / Slack stub)

Usage
-----
  python scripts/check_model_review_due.py
  python scripts/check_model_review_due.py --dry-run   # no writes, just print
  python scripts/check_model_review_due.py --db-url sqlite+aiosqlite:///./audit/mrm_audit.db

Environment Variables
---------------------
  MLFLOW_TRACKING_URI   — MLflow server URI
  MRM_DB_URL            — Audit SQLAlchemy async URL
  SLACK_WEBHOOK_URL     — Slack incoming webhook (optional)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from audit.logger import log_governance_action, get_governance_audit_log
from mlflow_config.mlflow_config import (
    ALL_REGISTERED_MODELS,
    MODEL_GOVERNANCE,
    configure_mlflow,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("check_model_review_due")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DB_URL = os.getenv(
    "MRM_DB_URL",
    f"sqlite+aiosqlite:///{_ROOT / 'audit' / 'mrm_audit.db'}",
)
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SYSTEM_ACTOR = "review-cron@example.com"


# ---------------------------------------------------------------------------
# Alert sender
# ---------------------------------------------------------------------------


def _send_slack_alert(message: str) -> None:
    """Post a message to Slack via incoming webhook (no-op if URL not configured)."""
    if not SLACK_WEBHOOK_URL:
        log.debug("Slack webhook not configured — skipping alert")
        return
    try:
        import urllib.request

        payload = json.dumps({"text": message}).encode()
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            log.info("Slack alert sent: HTTP %s", resp.status)
    except Exception as exc:  # noqa: BLE001
        log.warning("Slack alert failed: %s", exc)


def _send_email_stub(to_email: str, subject: str, body: str) -> None:
    """Email stub — in production, replace with Cloud Pub/Sub or SendGrid."""
    log.warning(
        "EMAIL ALERT (stub) → %s | Subject: %s | %s",
        to_email, subject, body,
    )


# ---------------------------------------------------------------------------
# Core check logic
# ---------------------------------------------------------------------------


async def _check_model(
    model_name: str,
    db_url: str,
    dry_run: bool,
    now: datetime,
) -> Dict[str, Any]:
    """Check if a single model is due for review.

    Returns a result dict with keys:
      model_name, last_promoted, review_cycle_months, days_since_promotion,
      review_due, overdue_days
    """
    gov = MODEL_GOVERNANCE.get(model_name, {})
    review_cycle_months: int = int(gov.get("review_cycle_months", 12))
    model_owner_email: str = gov.get("model_owner_email", "ds-team@example.com")
    review_threshold_days: int = review_cycle_months * 30

    # Find last PROMOTE_PRODUCTION record
    audit_records = await get_governance_audit_log(model_name, db_url, limit=200)
    production_promotions = [
        r for r in audit_records
        if r.get("action") in ("PROMOTE_PRODUCTION", "PROMOTE_STAGING")
        and r.get("to_stage", "").lower() in ("production", "promote_production")
    ]

    if not production_promotions:
        # Try to get from MLflow directly
        last_promoted_str = _get_mlflow_last_promoted(model_name)
    else:
        last_promoted_str = production_promotions[0].get("performed_at", "")

    if not last_promoted_str:
        log.info("No Production promotion record found for %s — skipping review check", model_name)
        return {
            "model_name": model_name,
            "last_promoted": None,
            "review_cycle_months": review_cycle_months,
            "days_since_promotion": None,
            "review_due": False,
            "overdue_days": 0,
        }

    # Parse timestamp
    try:
        # Handle ISO format with or without timezone info
        ts = last_promoted_str.replace("Z", "+00:00")
        last_promoted = datetime.fromisoformat(ts)
        if last_promoted.tzinfo is None:
            last_promoted = last_promoted.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError) as exc:
        log.warning("Could not parse last_promoted timestamp '%s': %s", last_promoted_str, exc)
        return {
            "model_name": model_name,
            "last_promoted": last_promoted_str,
            "review_cycle_months": review_cycle_months,
            "days_since_promotion": None,
            "review_due": False,
            "overdue_days": 0,
        }

    days_since = (now - last_promoted).days
    review_due = days_since >= review_threshold_days
    overdue_days = max(0, days_since - review_threshold_days)

    result = {
        "model_name": model_name,
        "last_promoted": last_promoted.date().isoformat(),
        "review_cycle_months": review_cycle_months,
        "days_since_promotion": days_since,
        "review_due": review_due,
        "overdue_days": overdue_days,
    }

    if review_due:
        log.warning(
            "REVIEW DUE: %s — last promoted %s (%d days ago, threshold %d days, overdue by %d days)",
            model_name,
            result["last_promoted"],
            days_since,
            review_threshold_days,
            overdue_days,
        )

        if not dry_run:
            # Write REVIEW_DUE record to governance log
            await log_governance_action(
                model_name=model_name,
                model_version="N/A",
                action="REVIEW_DUE",
                from_stage="production",
                to_stage=None,
                performed_by=SYSTEM_ACTOR,
                approved_by=None,
                governance_metrics={
                    "days_since_promotion": days_since,
                    "review_threshold_days": review_threshold_days,
                    "overdue_days": overdue_days,
                },
                notes=(
                    f"Automated review-due alert: {model_name} was last promoted to Production "
                    f"{days_since} days ago (threshold: {review_threshold_days} days). "
                    f"Overdue by {overdue_days} days."
                ),
                mlflow_run_id=None,
                db_url=db_url,
            )

        # Send alerts
        alert_msg = (
            f":red_circle: *MODEL REVIEW DUE* — `{model_name}`\n"
            f"Last promoted to Production: {result['last_promoted']} ({days_since} days ago)\n"
            f"Review cycle: {review_cycle_months} months | Overdue by {overdue_days} days\n"
            f"Action required: Schedule annual model review with MRM team.\n"
            f"cc: {model_owner_email}"
        )
        _send_slack_alert(alert_msg)
        _send_email_stub(
            to_email=model_owner_email,
            subject=f"[MRM ALERT] Model Review Due: {model_name}",
            body=alert_msg,
        )

    return result


def _get_mlflow_last_promoted(model_name: str) -> Optional[str]:
    """Try to get the last Production promotion timestamp from MLflow directly."""
    try:
        configure_mlflow()
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        versions = client.get_latest_versions(model_name, stages=["Production"])
        if versions:
            ts_ms = versions[0].last_updated_timestamp
            if ts_ms:
                return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    except Exception as exc:  # noqa: BLE001
        log.debug("Could not get MLflow Production version for %s: %s", model_name, exc)
    return None


async def run_all_checks(db_url: str, dry_run: bool) -> List[Dict[str, Any]]:
    """Run review-due checks for all registered models."""
    now = datetime.now(timezone.utc)
    results = []
    for model_name in ALL_REGISTERED_MODELS:
        result = await _check_model(model_name, db_url, dry_run, now)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Daily MRM check: find Production models overdue for review",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check only — do not write REVIEW_DUE records or send alerts",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help=f"SQLAlchemy async DB URL (default: {DEFAULT_DB_URL})",
    )
    args = parser.parse_args()

    log.info("Starting model review-due check (dry_run=%s)", args.dry_run)
    results = asyncio.run(run_all_checks(args.db_url, args.dry_run))

    due_count = sum(1 for r in results if r.get("review_due"))
    log.info(
        "Review-due check complete: %d/%d models need attention",
        due_count, len(results),
    )

    # Print summary table
    print("\n{:<35} {:>8} {:>10} {:>12} {:>12}".format(
        "Model", "Cycle(mo)", "LastProm.", "DaysSince", "OverdueDays"
    ))
    print("-" * 85)
    for r in results:
        flag = "⚠ REVIEW DUE" if r.get("review_due") else "✓ OK"
        print("{:<35} {:>9} {:>10} {:>12} {:>8}  {}".format(
            r["model_name"],
            r.get("review_cycle_months", "?"),
            r.get("last_promoted") or "—",
            r.get("days_since_promotion") if r.get("days_since_promotion") is not None else "—",
            r.get("overdue_days", 0),
            flag,
        ))
    print()

    # Exit code 1 if any models are overdue (for CI/CD integration)
    return 1 if due_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
