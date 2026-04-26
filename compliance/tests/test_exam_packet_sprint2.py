"""Sprint 2-A tests: verify all exam packet components return live data (not stubs).

Covers GAP-01 + GAP-07 from the Sprint 2-A coding prompt:
  - build_model_documentation_component     → status == "complete"
  - build_policy_snapshots_component        → status == "complete"
  - build_committee_approvals_component     → empty period → count == 0 but status == "complete"
  - build_exam_packet (all components)      → no component has status == "stub"
  - POST /v1/audit/generate-package         → HTTP 200, packet_id in response
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from compliance.exam_packet_builder import (
    ExamPacket,
    ExamPacketComponent,
    ExamPacketSpec,
    build_exam_packet,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(components: list[str], tenant_id: str = "t-sprint2") -> ExamPacketSpec:
    return ExamPacketSpec(
        tenant_id=tenant_id,
        from_date="2025-01-01",
        to_date="2025-03-31",
        components=components,
        format="json",
        template="OCC_EXAMINATION",
    )


DB_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Model documentation component
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_model_documentation_component_complete():
    """build_model_documentation_component returns status='complete' and includes model_name."""
    from compliance.exam_packet_builder import build_model_documentation_component

    mock_mdr = {
        "model_name": "credit_risk_v1",
        "model_version": "1.0",
        "intended_use": "Credit decisioning",
        "training_data_summary": "12 months originations",
        "performance_metrics": {"auc": 0.83},
        "validation_status": "PASS",
    }

    with patch("compliance.generate_model_doc.generate_mdr", return_value=mock_mdr):
        spec = _make_spec(["model_documentation"])
        comp = await build_model_documentation_component(spec, DB_URL)

    assert comp.status == "complete", f"Expected status='complete', got '{comp.status}'"
    assert comp.data is not None
    assert "model_name" in comp.data, "data dict must contain 'model_name'"
    assert comp.data["model_name"] == "credit_risk_v1"


# ---------------------------------------------------------------------------
# Policy snapshots component
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_snapshots_component_complete():
    """build_policy_snapshots_component returns status='complete' and includes version_id."""
    from compliance.exam_packet_builder import build_policy_snapshots_component

    mock_snapshot = {
        "version_id": "v-2025-01-15",
        "content_hash": "abc123",
        "effective_date": "2025-01-15",
        "author": "policy-team",
    }
    mock_history = [
        {"version_id": "v-2024-12-01", "effective_date": "2024-12-01"},
        {"version_id": "v-2025-01-15", "effective_date": "2025-01-15"},
    ]

    mock_store = MagicMock()
    mock_store.get_as_of.return_value = mock_snapshot
    mock_store.list_versions.return_value = mock_history

    with patch(
        "decision_engine.policy_version_store.PolicyVersionStore",
        return_value=mock_store,
    ):
        spec = _make_spec(["policy_snapshots"])
        comp = await build_policy_snapshots_component(spec, DB_URL)

    assert comp.status == "complete", f"Expected status='complete', got '{comp.status}'"
    assert comp.data is not None
    assert "version_id" in comp.data, "data dict must contain 'version_id'"


# ---------------------------------------------------------------------------
# Committee approvals component — empty period
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_committee_approvals_no_data():
    """Empty approval period → status='complete', count=0."""
    from compliance.exam_packet_builder import build_committee_approvals_component

    with patch(
        "compliance.committee_approval_store.list_approvals",
        new_callable=AsyncMock,
        return_value=[],
    ):
        spec = _make_spec(["committee_approvals"])
        comp = await build_committee_approvals_component(spec, DB_URL)

    assert comp.status == "complete"
    assert comp.data is not None
    assert comp.data.get("count", -1) == 0, f"Expected count=0, got {comp.data}"


# ---------------------------------------------------------------------------
# Full packet build — no stubs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_packet_json_no_stubs():
    """build_exam_packet with all known components produces no stub components."""
    all_known_components = [
        "model_documentation",
        "policy_snapshots",
        "adverse_actions",
        "fair_lending_analysis",
        "committee_approvals",
        "data_lineage",
    ]
    spec = _make_spec(all_known_components)

    # Patch all external dependencies so the test is fully hermetic
    mock_mdr = {"model_name": "test_model", "model_version": "1.0"}
    mock_snapshot = {"version_id": "v-mock", "effective_date": "2025-01-01"}
    mock_store = MagicMock()
    mock_store.get_as_of.return_value = mock_snapshot
    mock_store.list_versions.return_value = [mock_snapshot]

    with (
        patch("compliance.generate_model_doc.generate_mdr", return_value=mock_mdr),
        patch("decision_engine.policy_version_store.PolicyVersionStore", return_value=mock_store),
        patch("compliance.committee_approval_store.list_approvals", new_callable=AsyncMock, return_value=[]),
        patch("audit.logger.get_audit_records_by_period", new_callable=AsyncMock, return_value=[]),
        patch("monitoring.fair_lending.analyze_fair_lending", return_value={"disparate_impact_ratio": 0.82}),
        patch("data_lineage.lineage_tracker.export_lineage_report", new_callable=AsyncMock, return_value=MagicMock(
            tenant_id="t-sprint2",
            generated_at=datetime.now(timezone.utc).isoformat(),
            nodes=[],
            edges=[],
        )),
    ):
        packet = await build_exam_packet(spec, DB_URL)

    assert isinstance(packet, ExamPacket)
    for comp in packet.components:
        assert comp.status != "stub", (
            f"Component '{comp.name}' still has status='stub' — not wired yet."
        )


# ---------------------------------------------------------------------------
# FastAPI endpoint smoke test
# ---------------------------------------------------------------------------

def test_generate_package_endpoint_returns_200():
    """POST /v1/audit/generate-package should return HTTP 200 with packet_id in body."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # Import with minimal env setup
    import importlib
    import sys
    import os

    os.environ.setdefault("DECISION_AUDIT_DB_URL", "sqlite+aiosqlite:///:memory:")

    # Dynamically import the app to avoid top-level import costs in unit tests
    try:
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[3] / "decision-api" / "src"))
        app_mod = importlib.import_module("main")
        app = app_mod.app
    except Exception as exc:
        pytest.skip(f"Could not import decision-api app: {exc}")

    mock_mdr = {"model_name": "test", "model_version": "1.0"}
    mock_snapshot = {"version_id": "v-test", "effective_date": "2025-01-01"}
    mock_store = MagicMock()
    mock_store.get_as_of.return_value = mock_snapshot
    mock_store.list_versions.return_value = []

    with (
        patch("compliance.generate_model_doc.generate_mdr", new_callable=AsyncMock, return_value=mock_mdr),
        patch("compliance.exam_packet_builder.PolicyVersionStore", return_value=mock_store),
        patch("compliance.committee_approval_store.list_approvals", new_callable=AsyncMock, return_value=[]),
        patch("audit.logger.get_audit_records_by_period", new_callable=AsyncMock, return_value=[]),
        patch("monitoring.fair_lending.analyze_fair_lending", return_value={"disparate_impact_ratio": 0.82}),
    ):
        client = TestClient(app)
        response = client.post(
            "/v1/audit/generate-package",
            json={
                "tenant_id": "t-test",
                "from_date": "2025-01-01",
                "to_date": "2025-03-31",
                "components": ["model_documentation", "committee_approvals"],
                "format": "json",
                "template": "OCC_EXAMINATION",
            },
            headers={"Authorization": "Bearer test-token"},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    body = response.json()
    assert "packet_id" in body, f"'packet_id' not found in response: {body}"
