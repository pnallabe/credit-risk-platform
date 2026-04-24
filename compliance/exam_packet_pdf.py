"""
compliance/exam_packet_pdf.py
==============================
PDF renderer for regulatory exam packets.

Uses ``reportlab`` when available; falls back to a plain-text placeholder
when reportlab is not installed (useful for CI environments).

Public API
----------
>>> from compliance.exam_packet_pdf import render_exam_packet_pdf
>>> pdf_bytes = render_exam_packet_pdf(packet)
"""
from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from compliance.exam_packet_builder import ExamPacket

# ---------------------------------------------------------------------------
# ReportLab availability guard
# ---------------------------------------------------------------------------
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from reportlab.platypus import HRFlowable
    import io as _io

    _REPORTLAB = True
except ImportError:  # pragma: no cover
    _REPORTLAB = False


# ---------------------------------------------------------------------------
# Public renderer
# ---------------------------------------------------------------------------


def render_exam_packet_pdf(packet: "ExamPacket") -> bytes:
    """Render *packet* as a PDF and return the raw bytes.

    If ``reportlab`` is not installed, returns a UTF-8-encoded plain-text
    representation (useful in testing environments).

    Parameters
    ----------
    packet : ExamPacket
        The exam packet to render.

    Returns
    -------
    bytes
        Raw PDF bytes (or UTF-8 plain-text bytes as a fallback).
    """
    if _REPORTLAB:
        return _render_with_reportlab(packet)
    return _render_plain_text(packet)


# ---------------------------------------------------------------------------
# ReportLab renderer
# ---------------------------------------------------------------------------


def _render_with_reportlab(packet: "ExamPacket") -> bytes:
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Exam Packet {packet.packet_id}",
    )
    styles = getSampleStyleSheet()
    story = []

    # ── Cover sheet ──────────────────────────────────────────────────────────
    title_style = ParagraphStyle(
        "CoverTitle",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=12,
        textColor=colors.HexColor("#1e3a5f"),
    )
    subtitle_style = ParagraphStyle(
        "CoverSubtitle",
        parent=styles["Normal"],
        fontSize=11,
        spaceAfter=6,
        textColor=colors.HexColor("#4a5568"),
    )
    story.append(Paragraph("Regulatory Examination Packet", title_style))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(f"<b>Packet ID:</b> {packet.packet_id}", subtitle_style))
    story.append(Paragraph(f"<b>Tenant:</b> {packet.tenant_id}", subtitle_style))
    story.append(Paragraph(f"<b>Template:</b> {packet.template}", subtitle_style))
    story.append(Paragraph(f"<b>Period:</b> {packet.from_date} – {packet.to_date}", subtitle_style))
    story.append(Paragraph(f"<b>Generated:</b> {packet.generated_at}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#cbd5e0"), spaceAfter=12))

    # ── Component summary table ───────────────────────────────────────────────
    story.append(Paragraph("Component Summary", styles["Heading2"]))
    table_data = [["Component", "Status"]]
    for comp in packet.components:
        status_color = {
            "complete": colors.HexColor("#c6f6d5"),
            "pending":  colors.HexColor("#fefcbf"),
            "error":    colors.HexColor("#fed7d7"),
            "stub":     colors.HexColor("#e2e8f0"),
        }.get(comp.status, colors.white)
        table_data.append([comp.name, comp.status.upper()])

    t = Table(table_data, colWidths=[12 * cm, 4 * cm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING",   (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(t)
    story.append(Spacer(1, 0.8 * cm))

    # ── Per-component sections ────────────────────────────────────────────────
    heading_style = ParagraphStyle(
        "CompHeading",
        parent=styles["Heading2"],
        textColor=colors.HexColor("#2d3748"),
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "CompBody",
        parent=styles["Normal"],
        fontSize=8,
        fontName="Courier",
        leading=10,
        spaceAfter=4,
    )
    pending_style = ParagraphStyle(
        "Pending",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#744210"),
        backColor=colors.HexColor("#fefcbf"),
        borderPad=6,
        spaceAfter=8,
    )
    error_style = ParagraphStyle(
        "Error",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#742a2a"),
        backColor=colors.HexColor("#fff5f5"),
        borderPad=6,
        borderColor=colors.HexColor("#fc8181"),
        borderWidth=1,
        spaceAfter=8,
    )

    for comp in packet.components:
        story.append(Paragraph(f"§ {comp.name.replace('_', ' ').title()}", heading_style))

        if comp.status == "complete" and comp.data:
            json_str = json.dumps(comp.data, indent=2, default=str)
            # Wrap long lines for readability
            wrapped_lines = []
            for line in json_str.splitlines():
                wrapped_lines.extend(textwrap.wrap(line, width=100) or [line])
            wrapped_text = "\n".join(wrapped_lines)
            # Escape for XML/HTML rendering inside ReportLab
            escaped = wrapped_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(f"<para fontName='Courier' fontSize='8'>{escaped}</para>", body_style))

        elif comp.status == "pending":
            story.append(
                Paragraph(
                    f"⚠ Component pending: {comp.data.get('message', 'Not yet implemented') if comp.data else 'Pending'}",
                    pending_style,
                )
            )

        elif comp.status == "error":
            story.append(
                Paragraph(
                    f"✗ Error generating component: {comp.error_message or 'Unknown error'}",
                    error_style,
                )
            )

        elif comp.name == "ai_agent_audit" and comp.status == "complete" and comp.data:
            d = comp.data
            # Summary statistics table
            story.append(Paragraph("AI Agent Audit Summary (GNRI-011)", styles["Heading3"]))
            summary_data = [
                ["Metric", "Value"],
                ["Total Queries", str(d.get("total_queries", 0))],
                ["Unique Sessions", str(d.get("unique_sessions", 0))],
                ["Grounded Answers", str(d.get("grounded_count", 0))],
                ["Grounding Rate", f"{d.get('grounding_rate_pct', 0.0):.2f}%"],
                ["Avg Confidence Score", str(d.get("avg_confidence_score", "N/A"))],
                ["Min Confidence Score", str(d.get("min_confidence_score", "N/A"))],
                ["Period", f"{d.get('from_date', '')} – {d.get('to_date', '')}"],
            ]
            chain_info = d.get("chain_verification", {})
            summary_data.append(["Chain Integrity", chain_info.get("status", "unknown").upper()])
            summary_data.append(["Chain Rows Checked", str(chain_info.get("rows_checked", 0))])
            if chain_info.get("first_tampered_log_id"):
                summary_data.append(["First Tampered Log ID", str(chain_info["first_tampered_log_id"])])

            ai_table = Table(summary_data, colWidths=[8 * cm, 8 * cm])
            ai_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(ai_table)
            story.append(Spacer(1, 0.2 * cm))

            # Confidence label distribution
            label_dist = d.get("confidence_label_distribution", {})
            if label_dist:
                story.append(Paragraph("Confidence Label Distribution", styles["Heading3"]))
                label_data = [["Label", "Count"]] + [
                    [lbl, str(cnt)] for lbl, cnt in sorted(label_dist.items())
                ]
                lt = Table(label_data, colWidths=[8 * cm, 8 * cm])
                lt.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4a5568")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(lt)
            story.append(Spacer(1, 0.3 * cm))

        else:  # stub
            story.append(
                Paragraph(
                    f"[STUB] Component '{comp.name}' is not yet implemented.",
                    pending_style,
                )
            )

        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0"), spaceAfter=10))

    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Plain-text fallback
# ---------------------------------------------------------------------------


def _render_plain_text(packet: "ExamPacket") -> bytes:
    """Fallback renderer when reportlab is not available."""
    lines = [
        "=" * 70,
        "REGULATORY EXAMINATION PACKET (plain-text fallback)",
        "=" * 70,
        f"Packet ID:  {packet.packet_id}",
        f"Tenant:     {packet.tenant_id}",
        f"Template:   {packet.template}",
        f"Period:     {packet.from_date} – {packet.to_date}",
        f"Generated:  {packet.generated_at}",
        "",
        "COMPONENTS",
        "-" * 70,
    ]
    for comp in packet.components:
        lines.append(f"[{comp.status.upper():8s}] {comp.name}")
        if comp.status == "complete" and comp.data:
            lines.append(json.dumps(comp.data, indent=2, default=str))
        elif comp.status == "error":
            lines.append(f"  Error: {comp.error_message}")
        elif comp.status == "pending" and comp.data:
            lines.append(f"  {comp.data.get('message', 'Pending')}")
        lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines).encode("utf-8")
