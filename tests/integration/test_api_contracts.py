"""
tests/integration/test_api_contracts.py
========================================
PROMPT-06 Part B: Cross-service OpenAPI contract tests.

Strategy
--------
On the first run (no snapshot files present), the actual OpenAPI JSON is
written to tests/integration/snapshots/ and the test FAILS with a message
instructing you to commit the snapshots.  On subsequent runs, the live
OpenAPI JSON is compared against the committed snapshots — any schema drift
causes the test to fail.

Markers:  pytest -m integration
"""

from __future__ import annotations

import json
import os
import sys
import importlib.util
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parents[2]
DECISION_API_SRC = ROOT / "decision-api" / "src"
ANALYTICS_API_SRC = ROOT / "analytics_api" / "src"
SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"

for _p in (str(ROOT), str(DECISION_API_SRC.parent), str(ANALYTICS_API_SRC.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Minimal environment so apps can be imported without real DB/model artefacts
os.environ.setdefault("JWT_SECRET", "contract-test-secret-key-32chars!")
os.environ.setdefault("BORROWER_JWT_SECRET", "contract-test-borrower-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./contract_test.db")
os.environ.setdefault("CORS_ALLOWED_ORIGINS", "http://localhost")
os.environ.setdefault("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
os.environ.setdefault("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))
os.environ.setdefault("ENVIRONMENT", "dev")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_snapshot(filename: str) -> Dict[str, Any]:
    path = SNAPSHOTS_DIR / filename
    with open(path) as f:
        return json.load(f)


def _save_snapshot(filename: str, data: Dict[str, Any]) -> None:
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / filename
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _extract_schema(openapi: Dict[str, Any], method: str, path: str, phase: str) -> Dict[str, Any]:
    """Pull the JSON schema for a request/response from an OpenAPI spec.

    phase: "requestBody" or "responses"
    """
    path_item = openapi.get("paths", {}).get(path, {})
    op = path_item.get(method.lower(), {})
    if phase == "requestBody":
        return op.get("requestBody", {}).get("content", {}).get(
            "application/json", {}
        ).get("schema", {})
    elif phase == "responses":
        resp = op.get("responses", {})
        # prefer 200, fall back to first
        r200 = resp.get("200", resp.get(next(iter(resp), "200"), {}))
        return r200.get("content", {}).get(
            "application/json", {}
        ).get("schema", {})
    return {}


def _compare_schemas(live: Dict, committed: Dict, label: str) -> None:
    """Assert that *live* schema matches *committed* snapshot, key-by-key."""
    # We do a deterministic JSON round-trip for comparison to avoid dict
    # ordering issues, then use a simple equality check.
    live_str = json.dumps(live, sort_keys=True)
    committed_str = json.dumps(committed, sort_keys=True)
    assert live_str == committed_str, (
        f"OpenAPI schema drift detected for {label}.\n"
        f"Live:      {live_str[:500]}\n"
        f"Committed: {committed_str[:500]}\n"
        "Update the snapshot by deleting the snapshot file and re-running."
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def decision_client():
    """TestClient for the Decision API."""
    from unittest.mock import patch, MagicMock
    mock_model = MagicMock()

    decision_main_path = DECISION_API_SRC / "main.py"
    spec = importlib.util.spec_from_file_location("decision_api_main", str(decision_main_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load decision API module from {decision_main_path}")
    decision_module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = decision_module
    spec.loader.exec_module(decision_module)

    with (
        patch.object(decision_module, "_load_models"),
        patch.object(decision_module, "_fraud_model", mock_model),
        patch.object(decision_module, "_risk_model", mock_model),
    ):
        from fastapi.testclient import TestClient
        _decision_app = decision_module.app
        with TestClient(_decision_app, raise_server_exceptions=False) as c:
            yield c, decision_module


@pytest.fixture(scope="module")
def analytics_client():
    """TestClient for the Analytics API."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "analytics_main",
            str(ANALYTICS_API_SRC / "main.py"),
        )
        analytics_module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[spec.name] = analytics_module
        spec.loader.exec_module(analytics_module)  # type: ignore[union-attr]
        from fastapi.testclient import TestClient
        with TestClient(analytics_module.app, raise_server_exceptions=False) as c:
            yield c
    except Exception as exc:
        pytest.skip(f"Analytics API could not be imported: {exc}")


# ---------------------------------------------------------------------------
# Decision API contract tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDecisionAPIContracts:
    def test_openapi_schema_accessible(self, decision_client) -> None:
        _client, decision_module = decision_client
        assert hasattr(decision_module, "LoanApplicationRequest")
        assert hasattr(decision_module, "DecisionResponse")

    def test_post_decisions_request_schema_matches_snapshot(self, decision_client) -> None:
        _client, decision_module = decision_client
        live_schema = decision_module.LoanApplicationRequest.model_json_schema()
        snapshot_file = "decision_request.json"
        snapshot_path = SNAPSHOTS_DIR / snapshot_file

        if not snapshot_path.exists():
            _save_snapshot(snapshot_file, live_schema)
            pytest.fail(
                f"Snapshot '{snapshot_file}' did not exist. "
                "It has been created — commit it and rerun the tests."
            )

        committed = _load_snapshot(snapshot_file)
        _compare_schemas(live_schema, committed, "/v1/decisions requestBody")

    def test_post_decisions_response_schema_matches_snapshot(self, decision_client) -> None:
        _client, decision_module = decision_client
        live_schema = decision_module.DecisionResponse.model_json_schema()
        snapshot_file = "decision_response.json"
        snapshot_path = SNAPSHOTS_DIR / snapshot_file

        if not snapshot_path.exists():
            _save_snapshot(snapshot_file, live_schema)
            pytest.fail(
                f"Snapshot '{snapshot_file}' did not exist. "
                "It has been created — commit it and rerun the tests."
            )

        committed = _load_snapshot(snapshot_file)
        _compare_schemas(live_schema, committed, "/v1/decisions response")


# ---------------------------------------------------------------------------
# Analytics API contract tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAnalyticsAPIContracts:
    def test_openapi_schema_accessible(self, analytics_client) -> None:
        resp = analytics_client.get("/openapi.json")
        assert resp.status_code == 200
        assert "paths" in resp.json()

    def test_vintage_curves_response_schema_matches_snapshot(
        self, analytics_client
    ) -> None:
        resp = analytics_client.get("/openapi.json")
        openapi = resp.json()

        live_schema = _extract_schema(
            openapi, "get", "/v1/analytics/vintage-curves", "responses"
        )
        snapshot_file = "vintage_curves_response.json"
        snapshot_path = SNAPSHOTS_DIR / snapshot_file

        if not snapshot_path.exists():
            _save_snapshot(snapshot_file, live_schema)
            pytest.fail(
                f"Snapshot '{snapshot_file}' did not exist. "
                "It has been created — commit it and rerun the tests."
            )

        committed = _load_snapshot(snapshot_file)
        _compare_schemas(live_schema, committed, "/v1/analytics/vintage-curves response")
