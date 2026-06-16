"""Integration tests for GET /v1/lineage/{run_id} and related endpoints
(GAP-08 acceptance criteria)."""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("JWT_SECRET", "test-secret-pytest")  # nosec B105

import jwt as _jwt  # noqa: E402


def _make_token(tenant_id: str = "tenant-lineage") -> str:
    return _jwt.encode(
        {"sub": "user", "tenant_id": tenant_id, "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


AUTH_HEADERS = {"Authorization": f"Bearer {_make_token()}"}


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    import numpy as np
    import src.main as api_module
    from fastapi.testclient import TestClient

    mock_model = MagicMock()
    mock_model.predict_proba = MagicMock(return_value=np.array([[0.95, 0.05]]))
    mock_model.predict = MagicMock(return_value=np.array([0]))
    api_module._fraud_model = mock_model
    api_module._risk_model  = mock_model

    from src.main import app
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper to create a temp store with synthetic events
# ---------------------------------------------------------------------------

def _populate_store(db_path: str, run_id: str, n_events: int = 2) -> None:
    from feature_pipeline.lineage import LineageStore
    store = LineageStore(db_path)
    for i in range(n_events):
        store.record(
            run_id=run_id,
            job_namespace="test-ns",
            job_name="test_job",
            event_type="COMPLETE" if i > 0 else "START",
            event_time=datetime.now(timezone.utc).isoformat(),
            inputs=[{"namespace": "raw", "name": f"input_{i}"}],
            outputs=[{"namespace": "features", "name": f"output_{i}"}],
            run_facets={"source": "pytest"},
        )
    store.close()


# ---------------------------------------------------------------------------
# Test 1: GET /v1/lineage/{run_id} returns 200 with events
# ---------------------------------------------------------------------------

def test_get_lineage_returns_200_with_events(client, tmp_path) -> None:
    """GAP-08: GET /v1/lineage/{run_id} must return 200 with events when store has data."""
    db_path = str(tmp_path / "lineage.db")
    _populate_store(db_path, run_id="run-001", n_events=2)

    with (
        pytest.MonkeyPatch().context() as mp,
    ):
        mp.setenv("LINEAGE_STORE_PATH", db_path)
        resp = client.get("/v1/lineage/run-001", headers=AUTH_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"] == "run-001"
    assert data["event_count"] == 2
    assert len(data["events"]) == 2
    assert data["events"][0]["run_id"] == "run-001"


# ---------------------------------------------------------------------------
# Test 2: Returns 404 for unknown run_id
# ---------------------------------------------------------------------------

def test_get_lineage_404_for_unknown_run_id(client, tmp_path) -> None:
    """GAP-08: Returns 404 for run_id not in the store."""
    db_path = str(tmp_path / "lineage_404.db")
    _populate_store(db_path, run_id="run-exists", n_events=1)

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("LINEAGE_STORE_PATH", db_path)
        resp = client.get("/v1/lineage/nonexistent-run", headers=AUTH_HEADERS)

    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Test 3: Returns 503 when LINEAGE_STORE_PATH unset
# ---------------------------------------------------------------------------

def test_get_lineage_503_when_store_path_unset(client) -> None:
    """GAP-08: Returns 503 when LINEAGE_STORE_PATH env var is not set."""
    with pytest.MonkeyPatch().context() as mp:
        mp.delenv("LINEAGE_STORE_PATH", raising=False)
        resp = client.get("/v1/lineage/any-run-id", headers=AUTH_HEADERS)

    assert resp.status_code == 503, resp.text
    assert "LINEAGE_STORE_PATH" in resp.json().get("error", "")


# ---------------------------------------------------------------------------
# Test 4: GET /v1/lineage/job/{job_name} returns events by job
# ---------------------------------------------------------------------------

def test_get_lineage_by_job_returns_events(client, tmp_path) -> None:
    db_path = str(tmp_path / "lineage_job.db")
    # Insert events for two different runs of the same job
    from feature_pipeline.lineage import LineageStore
    store = LineageStore(db_path)
    for run_id in ("run-A", "run-B"):
        store.record(
            run_id=run_id,
            job_namespace="test-ns",
            job_name="my_etl_job",
            event_type="COMPLETE",
            event_time=datetime.now(timezone.utc).isoformat(),
            inputs=[],
            outputs=[],
        )
    store.close()

    with pytest.MonkeyPatch().context() as mp:
        mp.setenv("LINEAGE_STORE_PATH", db_path)
        resp = client.get("/v1/lineage/job/my_etl_job", headers=AUTH_HEADERS)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["event_count"] == 2
    assert data["job_name"] == "my_etl_job"


# ---------------------------------------------------------------------------
# Test 5: Unauthenticated request returns 401
# ---------------------------------------------------------------------------

def test_get_lineage_requires_auth(client) -> None:
    resp = client.get("/v1/lineage/run-001")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Unit tests for LineageStore independently (no API layer)
# ---------------------------------------------------------------------------

def test_lineage_store_record_and_query(tmp_path) -> None:
    """LineageStore.record() then get_by_run_id() returns the persisted events."""
    from feature_pipeline.lineage import LineageStore

    db_path = str(tmp_path / "unit_lineage.db")
    store = LineageStore(db_path)

    store.record(
        run_id="unit-run-001",
        job_namespace="test",
        job_name="unit_job",
        event_type="START",
        event_time=datetime.now(timezone.utc).isoformat(),
        inputs=[{"namespace": "raw", "name": "dataset_a"}],
        outputs=[],
    )
    store.record(
        run_id="unit-run-001",
        job_namespace="test",
        job_name="unit_job",
        event_type="COMPLETE",
        event_time=datetime.now(timezone.utc).isoformat(),
        inputs=[],
        outputs=[{"namespace": "features", "name": "dataset_b"}],
        run_facets={"schema_version": "1.0"},
    )

    events = store.get_by_run_id("unit-run-001")
    store.close()

    assert len(events) == 2
    assert events[0]["event_type"] == "START"
    assert events[1]["event_type"] == "COMPLETE"
    assert events[1]["run_facets"] == {"schema_version": "1.0"}
    assert events[0]["inputs"][0]["name"] == "dataset_a"
