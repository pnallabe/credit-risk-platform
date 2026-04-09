"""Tests for GAP-14A: batch_job_store.py – SQLite-backed batch job tracker."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest

from decision_api.src.batch_job_store import BatchJobStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> BatchJobStore:
    db = str(tmp_path / "batch_test.db")
    return BatchJobStore(db_path=db)


@pytest.fixture()
def mem_store() -> BatchJobStore:
    """In-memory SQLite store for faster tests."""
    return BatchJobStore(db_path=":memory:")


# ---------------------------------------------------------------------------
# create_job
# ---------------------------------------------------------------------------


class TestCreateJob:
    def test_returns_dict_with_job_id(self, store: BatchJobStore) -> None:
        job = store.create_job("job-001", "tenant-a", total_rows=100)
        assert job["job_id"] == "job-001"
        assert job["status"] == "PENDING"

    def test_creates_job_with_correct_tenant(self, store: BatchJobStore) -> None:
        store.create_job("job-002", "tenant-b", 50)
        fetched = store.get_job("job-002")
        assert fetched is not None
        assert fetched["tenant_id"] == "tenant-b"

    def test_initial_counts_are_zero(self, store: BatchJobStore) -> None:
        store.create_job("job-003", "tenant-c", 100)
        job = store.get_job("job-003")
        assert job["processed_rows"] == 0
        assert job["approved_count"] == 0
        assert job["rejected_count"] == 0
        assert job["review_count"] == 0

    def test_total_rows_stored(self, store: BatchJobStore) -> None:
        store.create_job("job-004", "tenant-a", 500)
        job = store.get_job("job-004")
        assert job["total_rows"] == 500


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------


class TestJobLifecycle:
    def test_pending_to_running(self, mem_store: BatchJobStore) -> None:
        mem_store.create_job("j1", "t1", 10)
        mem_store.mark_running("j1")
        job = mem_store.get_job("j1")
        assert job["status"] == "RUNNING"
        assert job["started_at"] is not None

    def test_update_progress(self, mem_store: BatchJobStore) -> None:
        mem_store.create_job("j2", "t1", 100)
        mem_store.mark_running("j2")
        mem_store.update_progress("j2", processed=40, approved=25, rejected=10, review=5)
        job = mem_store.get_job("j2")
        assert job["processed_rows"] == 40
        assert job["approved_count"] == 25
        assert job["rejected_count"] == 10
        assert job["review_count"] == 5

    def test_running_to_complete(self, mem_store: BatchJobStore) -> None:
        mem_store.create_job("j3", "t1", 20)
        mem_store.mark_running("j3")
        mem_store.mark_complete("j3", results_path="/tmp/results_j3.csv")
        job = mem_store.get_job("j3")
        assert job["status"] == "COMPLETE"
        assert job["completed_at"] is not None
        assert job["results_path"] == "/tmp/results_j3.csv"

    def test_running_to_failed(self, mem_store: BatchJobStore) -> None:
        mem_store.create_job("j4", "t1", 20)
        mem_store.mark_running("j4")
        mem_store.mark_failed("j4", error_message="CSV parse error on row 5")
        job = mem_store.get_job("j4")
        assert job["status"] == "FAILED"
        assert "row 5" in job["error_message"]
        assert job["completed_at"] is not None

    def test_get_nonexistent_job_returns_none(self, mem_store: BatchJobStore) -> None:
        result = mem_store.get_job("no-such-id")
        assert result is None


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------


class TestListJobs:
    def test_list_jobs_for_tenant(self, mem_store: BatchJobStore) -> None:
        mem_store.create_job("j-a1", "tenant-alpha", 100)
        mem_store.create_job("j-a2", "tenant-alpha", 200)
        mem_store.create_job("j-b1", "tenant-beta", 50)

        alpha = mem_store.list_jobs("tenant-alpha")
        beta = mem_store.list_jobs("tenant-beta")

        assert len(alpha) == 2
        assert len(beta) == 1
        assert all(j["tenant_id"] == "tenant-alpha" for j in alpha)

    def test_list_jobs_respects_limit(self, mem_store: BatchJobStore) -> None:
        for i in range(15):
            mem_store.create_job(f"j-{i}", "tenant-x", 10)
        jobs = mem_store.list_jobs("tenant-x", limit=5)
        assert len(jobs) <= 5

    def test_list_jobs_empty_for_unknown_tenant(self, mem_store: BatchJobStore) -> None:
        jobs = mem_store.list_jobs("no-such-tenant")
        assert jobs == []

    def test_list_jobs_default_limit(self, mem_store: BatchJobStore) -> None:
        for i in range(25):
            mem_store.create_job(f"jl-{i}", "tenant-def", 5)
        jobs = mem_store.list_jobs("tenant-def")
        assert len(jobs) <= 20  # default limit is 20


# ---------------------------------------------------------------------------
# Thread safety (basic smoke test)
# ---------------------------------------------------------------------------


def test_concurrent_updates_safe(mem_store: BatchJobStore) -> None:
    import threading

    mem_store.create_job("concurrent-job", "t1", 1000)
    mem_store.mark_running("concurrent-job")

    errors = []

    def _update(n):
        try:
            mem_store.update_progress("concurrent-job", n, n // 2, n // 4, 0)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_update, args=(i * 10,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"Concurrent errors: {errors}"
