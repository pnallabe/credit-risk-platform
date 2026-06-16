"""
compliance/tests/test_exam_packet_ai_appendix.py
==================================================
Tests for the AI Agent Audit Appendix exam packet component (GAP-21).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure ai-agent/src is importable so patch targets can be resolved
_AI_SRC = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "ai-agent", "src")
)
if _AI_SRC not in sys.path:
    sys.path.insert(0, _AI_SRC)


# ---------------------------------------------------------------------------
# Minimal stubs for AIAgentAuditRecord and ChainVerificationResult
# ---------------------------------------------------------------------------


def _make_record(
    session_id: str = "ses1",
    confidence_score: float = 0.8,
    grounded: bool = True,
    tools_called: Optional[str] = None,
) -> Any:
    class _Rec:
        pass
    r = _Rec()
    r.session_id = session_id
    r.confidence_score = confidence_score
    r.confidence_label = "high" if confidence_score >= 0.75 else ("medium" if confidence_score >= 0.5 else "low")
    r.grounded = grounded
    r.tools_called = tools_called or json.dumps(["sql_query_tool"])
    r.query_hash = "a" * 64
    r.result_hash = "b" * 64
    return r


def _make_chain_result(verified: bool = True, rows_checked: int = 5) -> Any:
    class _CR:
        pass
    c = _CR()
    c.verified = verified
    c.rows_checked = rows_checked
    c.gap_detected = False
    c.first_tampered_log_id = None
    c.first_tampered_at = None
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_ai_agent_audit_component_complete():
    """Component is complete when records are present and chain is verified."""
    from compliance.exam_packet_builder import ExamPacketSpec, build_ai_agent_audit_component

    records = [
        _make_record("ses1", 0.2, False),
        _make_record("ses2", 0.5, True),
        _make_record("ses3", 0.7, True),
        _make_record("ses1", 0.8, True),
        _make_record("ses2", 0.9, True),
    ]
    chain_result = _make_chain_result(verified=True, rows_checked=5)

    spec = ExamPacketSpec(
        tenant_id="test",
        from_date="2026-01-01",
        to_date="2026-03-31",
        components=["ai_agent_audit"],
        format="json",
    )

    with patch("ai_audit_log.get_ai_audit_records", new_callable=AsyncMock) as mock_records, \
         patch("audit.chain_verifier.verify_ai_agent_chain", new_callable=AsyncMock) as mock_chain:
        mock_records.return_value = records
        mock_chain.return_value = chain_result

        comp = await build_ai_agent_audit_component(spec, "test.db")

    assert comp.status == "complete"
    assert comp.data["total_queries"] == 5
    assert comp.data["unique_sessions"] >= 1
    assert comp.data["grounding_rate_pct"] == 80.0
    assert comp.data["chain_verification"]["status"] == "verified"


@pytest.mark.asyncio
async def test_build_ai_agent_audit_component_stub_when_empty():
    """Returns stub status when no records found."""
    from compliance.exam_packet_builder import ExamPacketSpec, build_ai_agent_audit_component

    spec = ExamPacketSpec(
        tenant_id="test", from_date="2026-01-01", to_date="2026-03-31",
        components=["ai_agent_audit"], format="json",
    )

    with patch("ai_audit_log.get_ai_audit_records", new_callable=AsyncMock) as mock_records, \
         patch("audit.chain_verifier.verify_ai_agent_chain", new_callable=AsyncMock) as mock_chain:
        mock_records.return_value = []
        mock_chain.return_value = _make_chain_result()

        comp = await build_ai_agent_audit_component(spec, "test.db")

    assert comp.status == "stub"
    assert "No AI agent audit records" in comp.data["note"]


@pytest.mark.asyncio
async def test_build_ai_agent_audit_component_error_on_exception():
    """Returns error status when an exception is raised."""
    from compliance.exam_packet_builder import ExamPacketSpec, build_ai_agent_audit_component

    spec = ExamPacketSpec(
        tenant_id="test", from_date="2026-01-01", to_date="2026-03-31",
        components=["ai_agent_audit"], format="json",
    )

    with patch("ai_audit_log.get_ai_audit_records", new_callable=AsyncMock) as mock_records:
        mock_records.side_effect = RuntimeError("DB unavailable")
        comp = await build_ai_agent_audit_component(spec, "test.db")

    assert comp.status == "error"
    assert "DB unavailable" in comp.error_message


def test_ai_agent_audit_in_component_builders():
    """_COMPONENT_BUILDERS must contain 'ai_agent_audit'."""
    from compliance.exam_packet_builder import _COMPONENT_BUILDERS

    assert "ai_agent_audit" in _COMPONENT_BUILDERS
    assert callable(_COMPONENT_BUILDERS["ai_agent_audit"])


@pytest.mark.asyncio
async def test_full_exam_packet_includes_ai_agent_audit():
    """build_exam_packet returns a packet with ai_agent_audit component."""
    from compliance.exam_packet_builder import ExamPacketSpec, build_exam_packet, _COMPONENT_BUILDERS

    spec = ExamPacketSpec(
        tenant_id="test", from_date="2026-01-01", to_date="2026-03-31",
        components=["ai_agent_audit"], format="json",
    )

    fake_comp = {"name": "ai_agent_audit", "status": "stub", "data": None, "error_message": None}

    async def _mock_builder(s, d):
        from compliance.exam_packet_builder import ExamPacketComponent
        return ExamPacketComponent(name="ai_agent_audit", status="stub", data=None)

    with patch.dict(_COMPONENT_BUILDERS, {"ai_agent_audit": _mock_builder}):
        packet = await build_exam_packet(spec, "test.db")

    ai_comps = [c for c in packet.components if c.name == "ai_agent_audit"]
    assert len(ai_comps) == 1


@pytest.mark.asyncio
async def test_pdf_renders_ai_appendix_section():
    """PDF renderer returns valid PDF bytes for ai_agent_audit component."""
    from compliance.exam_packet_builder import ExamPacket, ExamPacketComponent
    from compliance.exam_packet_pdf import render_exam_packet_pdf
    from datetime import datetime, timezone

    comp = ExamPacketComponent(
        name="ai_agent_audit",
        status="complete",
        data={
            "total_queries": 10,
            "unique_sessions": 3,
            "grounded_count": 9,
            "grounding_rate_pct": 90.0,
            "avg_confidence_score": 0.82,
            "min_confidence_score": 0.55,
            "confidence_label_distribution": {"high": 7, "medium": 2, "low": 1},
            "tools_called_distribution": {"sql_query_tool": 10},
            "chain_verification": {
                "status": "verified",
                "rows_checked": 10,
                "gap_detected": False,
                "first_tampered_log_id": None,
            },
            "from_date": "2026-01-01",
            "to_date": "2026-03-31",
        },
    )
    packet = ExamPacket(
        packet_id=str(uuid.uuid4()),
        tenant_id="test",
        generated_at=datetime.now(timezone.utc).isoformat(),
        from_date="2026-01-01",
        to_date="2026-03-31",
        template="OCC_EXAMINATION",
        components=[comp],
    )

    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100
