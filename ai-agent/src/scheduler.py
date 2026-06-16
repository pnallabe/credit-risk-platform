"""
Phase 13 – Scheduled AI Reporting
APScheduler jobs: daily portfolio, weekly model health, monthly fair lending, real-time drift alert
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "decision_audit.db")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:8082")
DRIFT_PSI_THRESHOLD = float(os.getenv("DRIFT_PSI_THRESHOLD", "0.25"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_notification(title: str, body: str, level: str = "info", category: str = "report"):
    try:
        ts = datetime.utcnow().isoformat()
        with _get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    level TEXT NOT NULL DEFAULT 'info',
                    category TEXT NOT NULL DEFAULT 'report',
                    created_at TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0
                )
            """)
            conn.execute(
                "INSERT INTO notifications (title, body, level, category, created_at) VALUES (?,?,?,?,?)",
                (title, body, level, category, ts),
            )
            conn.commit()
        logger.info("Notification saved: %s", title)
    except Exception as exc:
        logger.error("Failed to save notification: %s", exc)


async def _call_report_tool(report_type: str) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Create a session
        sess_res = await client.post(
            f"{AGENT_API_URL}/agent/sessions",
            json={"persona": "business_analyst" if report_type in ("portfolio", "fair_lending") else "data_analyst"},
        )
        session_id = sess_res.json().get("session_id", "fallback")

        # Post the report generation message
        prompt = f"Generate a {report_type} report and summarize key findings."
        lines: list[str] = []
        async with client.stream(
            "POST",
            f"{AGENT_API_URL}/agent/chat",
            json={"session_id": session_id, "message": prompt},
            timeout=60.0,
        ) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        d = json.loads(line[6:])
                        if "token" in d:
                            lines.append(d["token"])
                    except Exception:
                        pass

        return {"summary": "".join(lines), "report_type": report_type}


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------
async def job_daily_portfolio():
    """Daily portfolio health summary."""
    logger.info("[scheduler] Running daily portfolio report…")
    try:
        with _get_conn() as conn:
            total_row = conn.execute("SELECT COUNT(*) as cnt FROM decisions").fetchone()
            approve_row = conn.execute("SELECT COUNT(*) as cnt FROM decisions WHERE decision='APPROVE'").fetchone()
        total = total_row["cnt"] if total_row else 0
        approved = approve_row["cnt"] if approve_row else 0
        rate = f"{approved / total * 100:.1f}%" if total else "N/A"
        body = f"Today: {total} decisions processed, approval rate {rate}."
    except Exception:
        body = "Portfolio report: data unavailable."
    _insert_notification("Daily Portfolio Summary", body, level="info", category="report")


async def job_weekly_model_health():
    """Weekly model health check."""
    logger.info("[scheduler] Running weekly model health report…")
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT auc, ks FROM model_metrics ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
        if row and row["auc"] < 0.80:
            level = "warning"
            body = f"Model AUC={row['auc']:.3f} is BELOW the 0.80 threshold. KS={row['ks']:.3f}. Retraining recommended."
        elif row:
            level = "info"
            body = f"Model health OK — AUC={row['auc']:.3f}, KS={row['ks']:.3f}."
        else:
            level = "info"
            body = "Model health report: no metrics available."
    except Exception:
        level = "info"
        body = "Model health check: database unavailable."
    _insert_notification("Weekly Model Health", body, level=level, category="model")


async def job_monthly_fair_lending():
    """Monthly fair lending compliance report."""
    logger.info("[scheduler] Running monthly fair lending report…")
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT dir_score, summary_text FROM fair_lending_reports ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row and row["dir_score"] < 0.80:
            level = "critical"
            body = f"ECOA compliance risk: DIR score {row['dir_score']:.3f} is below the 0.80 threshold. Immediate review required."
        elif row:
            level = "info"
            body = f"Fair lending compliant — DIR={row['dir_score']:.3f}. {row['summary_text']}"
        else:
            level = "info"
            body = "Fair lending report: no data available."
    except Exception:
        level = "info"
        body = "Fair lending check: database unavailable."
    _insert_notification("Monthly Fair Lending Report", body, level=level, category="compliance")


async def job_realtime_drift_alert():
    """Near real-time drift alerting (runs every 15 minutes)."""
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT feature, psi, status FROM drift_features WHERE status='major' ORDER BY psi DESC LIMIT 5"
            ).fetchall()
        if rows:
            features = ", ".join(r["feature"] for r in rows)
            max_psi = max(r["psi"] for r in rows)
            body = f"Major drift detected on: {features}. Highest PSI={max_psi:.4f} (threshold={DRIFT_PSI_THRESHOLD})."
            _insert_notification("⚠️ Data Drift Alert", body, level="warning", category="drift")
            logger.warning("[scheduler] Drift alert: %s", body)
    except Exception:
        pass  # Silently skip if drift table doesn't exist yet


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------
def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    # 07:00 UTC daily portfolio
    scheduler.add_job(
        job_daily_portfolio,
        CronTrigger(hour=7, minute=0),
        id="daily_portfolio",
        name="Daily Portfolio Summary",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Every Monday 08:00 UTC model health
    scheduler.add_job(
        job_weekly_model_health,
        CronTrigger(day_of_week="mon", hour=8, minute=0),
        id="weekly_model_health",
        name="Weekly Model Health",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # 1st of every month at 09:00 UTC fair lending
    scheduler.add_job(
        job_monthly_fair_lending,
        CronTrigger(day=1, hour=9, minute=0),
        id="monthly_fair_lending",
        name="Monthly Fair Lending",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # Every 15 minutes drift alert
    scheduler.add_job(
        job_realtime_drift_alert,
        IntervalTrigger(minutes=15),
        id="realtime_drift",
        name="Real-time Drift Alert",
        replace_existing=True,
        misfire_grace_time=60,
    )

    return scheduler


if __name__ == "__main__":
    import asyncio

    async def _run():
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))
        try:
            while True:
                await asyncio.sleep(60)
        except asyncio.CancelledError:
            scheduler.shutdown()

    asyncio.run(_run())
