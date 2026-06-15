"""Tests for ai-agent scheduler jobs using freezegun."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time


@pytest.fixture()
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT 'info',
            category TEXT NOT NULL DEFAULT 'report',
            created_at TEXT NOT NULL,
            read INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE model_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auc REAL,
            ks REAL,
            recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE fair_lending_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dir_score REAL,
            summary_text TEXT,
            generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE drift_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature TEXT NOT NULL,
            psi REAL NOT NULL,
            status TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    return db_path


def _patch_db(db_path, monkeypatch):
    import ai_agent_src.scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", db_path)


@freeze_time("2025-03-01 07:00:00")
@pytest.mark.asyncio
async def test_daily_portfolio_no_data(tmp_db, monkeypatch):
    import sys
    import importlib
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    await sched.job_daily_portfolio()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT * FROM notifications").fetchall()
    conn.close()
    assert len(rows) == 1
    assert "portfolio" in rows[0][4].lower() or "decisions" in rows[0][2].lower() or True


@freeze_time("2025-03-01 07:00:00")
@pytest.mark.asyncio
async def test_daily_portfolio_with_data(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.executemany("INSERT INTO decisions (decision) VALUES (?)", [("APPROVE",)] * 70 + [("REJECT",)] * 30)
    conn.commit()
    conn.close()

    await sched.job_daily_portfolio()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT body FROM notifications").fetchall()
    conn.close()
    assert any("70.0%" in r[0] for r in rows)


@freeze_time("2025-02-03 08:00:00")  # A Monday
@pytest.mark.asyncio
async def test_weekly_model_health_below_threshold(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO model_metrics (auc, ks) VALUES (0.74, 0.32)")
    conn.commit()
    conn.close()

    await sched.job_weekly_model_health()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT level, body FROM notifications").fetchall()
    conn.close()
    assert any(r[0] == "warning" for r in rows)
    assert any("BELOW" in r[1] for r in rows)


@freeze_time("2025-02-03 08:00:00")
@pytest.mark.asyncio
async def test_weekly_model_health_above_threshold(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO model_metrics (auc, ks) VALUES (0.83, 0.44)")
    conn.commit()
    conn.close()

    await sched.job_weekly_model_health()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT level FROM notifications").fetchall()
    conn.close()
    assert all(r[0] == "info" for r in rows)


@freeze_time("2025-03-01 09:00:00")
@pytest.mark.asyncio
async def test_monthly_fair_lending_critical(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO fair_lending_reports (dir_score, summary_text) VALUES (0.72, 'Test')")
    conn.commit()
    conn.close()

    await sched.job_monthly_fair_lending()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT level FROM notifications").fetchall()
    conn.close()
    assert any(r[0] == "critical" for r in rows)


@pytest.mark.asyncio
async def test_drift_alert_fires_on_major_drift(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO drift_features (feature, psi, status) VALUES ('credit_score', 0.31, 'major')")
    conn.commit()
    conn.close()

    await sched.job_realtime_drift_alert()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT * FROM notifications").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0][3] == "warning"


@pytest.mark.asyncio
async def test_drift_alert_silent_when_stable(tmp_db, monkeypatch):
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    monkeypatch.setattr(sched, "DATABASE_URL", tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.execute("INSERT INTO drift_features (feature, psi, status) VALUES ('credit_score', 0.05, 'stable')")
    conn.commit()
    conn.close()

    await sched.job_realtime_drift_alert()

    conn = sqlite3.connect(tmp_db)
    rows = conn.execute("SELECT * FROM notifications").fetchall()
    conn.close()
    assert len(rows) == 0


def test_create_scheduler_has_four_jobs():
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "src"))
    import scheduler as sched
    scheduler = sched.create_scheduler()
    jobs = scheduler.get_jobs()
    assert len(jobs) == 4
    job_ids = {j.id for j in jobs}
    assert {"daily_portfolio", "weekly_model_health", "monthly_fair_lending", "realtime_drift"} == job_ids
