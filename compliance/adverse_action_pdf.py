"""
compliance/adverse_action_pdf.py
=================================
PDF renderer for the CFPB Model Form C-1 adverse action notice.

Uses ``reportlab`` (imported lazily — importable even when library is absent).

Public API
----------
>>> from compliance.adverse_action_pdf import render_notice_pdf
"""
from __future__ import annotations

import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Optional, Union

from compliance.adverse_action import AdverseActionNotice
from compliance.adverse_action_generator import render_c1_text

logger = logging.getLogger(__name__)


def render_notice_pdf(
    notice: AdverseActionNotice,
    output_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """Render an adverse action notice as a PDF.

    Parameters
    ----------
    notice:
        Populated :class:`AdverseActionNotice` instance.
    output_path:
        Optional file path to write the PDF to.  The bytes are *always*
        returned regardless.

    Returns
    -------
    bytes
        Raw PDF bytes (begins with ``b"%PDF-"``).

    Raises
    ------
    ImportError
        If ``reportlab`` is not installed.
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
        from reportlab.platypus.flowables import HRFlowable
    except ImportError as exc:
        raise ImportError(
            "reportlab is required to render PDF notices. "
            "Install it with: pip install 'reportlab>=4.0.0'"
        ) from exc

    buf = BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=inch,
        rightMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
        title="Adverse Action Notice",
        author=notice.creditor_name,
    )

    styles = getSampleStyleSheet()

    header_style = ParagraphStyle(
        "NoticeHeader",
        parent=styles["Heading1"],
        fontSize=14,
        leading=18,
        spaceAfter=12,
    )
    body_style = ParagraphStyle(
        "NoticeBody",
        parent=styles["Normal"],
        fontSize=11,
        leading=14,
        spaceAfter=6,
    )
    footer_style = ParagraphStyle(
        "NoticeFooter",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.grey,
        leading=10,
    )

    # Build story
    notice_text_lines = render_c1_text(notice).split("\n")
    story = []

    # Header (first non-empty line)
    first_line = notice_text_lines[0] if notice_text_lines else "NOTICE"
    story.append(Paragraph(first_line, header_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))

    for line in notice_text_lines[1:]:
        escaped = (
            line.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
        if escaped.strip():
            story.append(Paragraph(escaped, body_style))
        else:
            story.append(Spacer(1, 6))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(
        Paragraph(
            f"Notice ID: {notice.notice_id} | Generated: {notice.generated_at}",
            footer_style,
        )
    )

    # Watermark support
    watermark = os.getenv("AA_NOTICE_WATERMARK") == "1"
    if watermark:
        _add_watermark_to_story(story, doc, "COMPLIANCE COPY")

    doc.build(story)
    pdf_bytes = buf.getvalue()

    logger.debug("Rendered PDF for notice_id=%s, size=%d bytes", notice.notice_id, len(pdf_bytes))

    if output_path is not None:
        Path(output_path).write_bytes(pdf_bytes)

    return pdf_bytes


def _add_watermark_to_story(story: list, doc: object, text: str) -> None:
    """Add a watermark by appending metadata-bearing content (POST build hook)."""
    # reportlab watermarks are easiest via a canvas override; we approximate by
    # injecting a large grey text paragraph at the start — a simple and reliable
    # approach that adds measurable bytes to the PDF.
    try:
        from reportlab.lib import colors
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import Paragraph

        wm_style = ParagraphStyle(
            "Watermark",
            fontSize=48,
            textColor=colors.Color(0.8, 0.8, 0.8, alpha=0.4),
            leading=52,
            alignment=1,  # center
        )
        story.insert(0, Paragraph(text, wm_style))
    except Exception as exc:
        logger.debug("Watermark injection failed (non-fatal): %s", exc)
