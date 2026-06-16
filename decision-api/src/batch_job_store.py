"""
Batch Job Store
===============
Tracks the state of CSV batch underwriting jobs submitted via
POST /v1/batch/underwrite.

Job lifecycle
-------------
  PENDING  → RUNNING  → COMPLETE
                       → FAILED
                       → CANCELLED (future)

Schema: batch_jobs table
  job_id          TEXT PRIMARY KEY    -- UUID
  tenant_id       TEXT NOT NULL
  status          TEXT NOT NULL       -- PENDING | RUNNING | COMPLETE | FAILED
  submitted_at    TEXT NOT NULL       -- ISO-8601 UTC
  started_at      TEXT                -- ISO-8601 UTC; NULL until processing begins
  completed_at    TEXT                -- ISO-8601 UTC; NULL until done
  total_rows      INTEGER NOT NULL DEFAULT 0
  processed_rows  INTEGER NOT NULL DEFAULT 0
  approved_count  INTEGER NOT NULL DEFAULT 0
  rejected_count  INTEGER NOT NULL DEFAULT 0
  review_count    INTEGER NOT NULL DEFAULT 0
  error_message   TEXT                -- populated for FAILED jobs
  results_path    TEXT                -- path to JSONL results file when COMPLETE
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS batch_jobs (
    job_id          TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    submitted_at    TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    total_rows      INTEGER NOT NULL DEFAULT 0,
    processed_rows  INTEGER NOT NULL DEFAULT 0,
    approved_count  INTEGER NOT NULL DEFAULT 0,
    rejected_count  INTEGER NOT NULL DEFAULT 0,
    review_count    INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    results_path    TEXT
);
CREATE INDEX IF NOT EXISTS ix_bj_tenant ON batch_jobs (tenant_id);
"""

_DEFAULT_DB_PATH = os.getenv("BATCH_JOB_DB_PATH", "./batch_jobs.db")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BatchJobStore:
    """SQLite-backed store for batch underwriting job lifecycle.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file.  Defaults to ``./batch_jobs.db``
        (or ``BATCH_JOB_DB_PATH`` env var).
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_DDL)
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def create_job(self, job_id: str, tenant_id: str, total_rows: int) -> dict:
        """Insert a new job row with status=PENDING.

        Returns the job dict.
        """
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO batch_jobs
                        (job_id, tenant_id, status, submitted_at, total_rows)
                    VALUES (?, ?, 'PENDING', ?, ?)
                    """,
                    (job_id, tenant_id, now, total_rows),
                )
                conn.commit()
            finally:
                conn.close()
        return self.get_job(job_id) or {}  # type: ignore[return-value]

    def mark_running(self, job_id: str) -> None:
        """Transition a PENDING job to RUNNING."""
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE batch_jobs SET status = 'RUNNING', started_at = ? "
                    "WHERE job_id = ?",
                    (now, job_id),
                )
                conn.commit()
            finally:
                conn.close()

    def update_progress(
        self,
        job_id: str,
        processed: int,
        approved: int,
        rejected: int,
        review: int,
    ) -> None:
        """Update progress counters for a running job."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    UPDATE batch_jobs
                    SET processed_rows = ?,
                        approved_count = ?,
                        rejected_count = ?,
                        review_count   = ?
                    WHERE job_id = ?
                    """,
                    (processed, approved, rejected, review, job_id),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_complete(self, job_id: str, results_path: str) -> None:
        """Transition job to COMPLETE and record the results file path."""
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE batch_jobs SET status = 'COMPLETE', completed_at = ?, "
                    "results_path = ? WHERE job_id = ?",
                    (now, results_path, job_id),
                )
                conn.commit()
            finally:
                conn.close()

    def mark_failed(self, job_id: str, error_message: str) -> None:
        """Transition job to FAILED and store the error message."""
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "UPDATE batch_jobs SET status = 'FAILED', completed_at = ?, "
                    "error_message = ? WHERE job_id = ?",
                    (now, error_message[:2000], job_id),
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_job(self, job_id: str) -> Optional[dict]:
        """Return the job dict or None if not found."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM batch_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.close()
        return dict(row) if row else None

    def list_jobs(self, tenant_id: str, limit: int = 20) -> list[dict]:
        """Return the most-recent jobs for a tenant, newest first."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM batch_jobs WHERE tenant_id = ? "
                "ORDER BY submitted_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]
