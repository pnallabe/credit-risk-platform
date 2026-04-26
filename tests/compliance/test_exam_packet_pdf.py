"""
Tests to boost coverage of compliance/exam_packet_pdf.py
"""
from __future__ import annotations

from compliance.exam_packet_builder import ExamPacket, ExamPacketComponent
from compliance.exam_packet_pdf import render_exam_packet_pdf


def _make_packet(components=None) -> ExamPacket:
    return ExamPacket(
        packet_id="pkt-test-001",
        tenant_id="tenant-a",
        generated_at="2026-01-01T00:00:00+00:00",
        from_date="2026-01-01",
        to_date="2026-03-31",
        template="standard",
        components=components or [],
    )


def test_render_plain_text_fallback(monkeypatch):
    """Force plain-text renderer by setting _REPORTLAB=False."""
    import compliance.exam_packet_pdf as m
    monkeypatch.setattr(m, "_REPORTLAB", False)

    packet = _make_packet([
        ExamPacketComponent(name="test_comp", status="complete", data={"key": "value"}),
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert b"REGULATORY EXAMINATION PACKET" in result
    assert b"test_comp" in result


def test_render_plain_text_pending_component(monkeypatch):
    import compliance.exam_packet_pdf as m
    monkeypatch.setattr(m, "_REPORTLAB", False)

    packet = _make_packet([
        ExamPacketComponent(name="pending_comp", status="pending", data={"message": "Not ready"}),
    ])
    result = render_exam_packet_pdf(packet)
    assert b"pending_comp" in result
    assert b"Not ready" in result


def test_render_plain_text_error_component(monkeypatch):
    import compliance.exam_packet_pdf as m
    monkeypatch.setattr(m, "_REPORTLAB", False)

    packet = _make_packet([
        ExamPacketComponent(name="broken_comp", status="error", data=None, error_message="DB connection failed"),
    ])
    result = render_exam_packet_pdf(packet)
    assert b"broken_comp" in result
    assert b"DB connection failed" in result


def test_render_pdf_with_pending_component():
    """ReportLab path: pending component renders without crash."""
    packet = _make_packet([
        ExamPacketComponent(name="pending_feature", status="pending", data={"message": "Coming soon"}),
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100  # non-empty PDF


def test_render_pdf_with_error_component():
    """ReportLab path: error component renders without crash."""
    packet = _make_packet([
        ExamPacketComponent(name="error_feature", status="error", data=None, error_message="Timeout"),
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100


def test_render_pdf_with_stub_component():
    """ReportLab path: stub status renders without crash."""
    packet = _make_packet([
        ExamPacketComponent(name="stub_feature", status="stub", data=None),
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100


def test_render_pdf_with_ai_agent_audit_component():
    """ReportLab path: ai_agent_audit component renders summary table."""
    packet = _make_packet([
        ExamPacketComponent(
            name="ai_agent_audit",
            status="complete",
            data={
                "total_queries": 100,
                "unique_sessions": 20,
                "grounded_count": 90,
                "grounding_rate_pct": 90.0,
                "avg_confidence_score": 0.88,
                "min_confidence_score": 0.50,
                "from_date": "2026-01-01",
                "to_date": "2026-03-31",
                "chain_verification": {
                    "status": "verified",
                    "rows_checked": 100,
                    "first_tampered_log_id": None,
                },
                "confidence_label_distribution": {"high": 80, "medium": 15, "low": 5},
            },
        )
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100


def test_render_pdf_with_ai_agent_audit_tampered():
    """ReportLab path: ai_agent_audit with tampered chain info."""
    packet = _make_packet([
        ExamPacketComponent(
            name="ai_agent_audit",
            status="complete",
            data={
                "total_queries": 50,
                "unique_sessions": 10,
                "grounded_count": 40,
                "grounding_rate_pct": 80.0,
                "chain_verification": {
                    "status": "tampered",
                    "rows_checked": 50,
                    "first_tampered_log_id": "log-007",
                },
                "confidence_label_distribution": {},
            },
        )
    ])
    result = render_exam_packet_pdf(packet)
    assert isinstance(result, bytes)
    assert len(result) > 100
