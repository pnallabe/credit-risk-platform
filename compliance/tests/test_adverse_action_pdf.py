"""Tests for compliance/adverse_action_pdf.py (P2-C)"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest


TENANT_CFG = {
    "creditor_name": "Acme Bank",
    "applicant_name": "Jane Doe",
    "bureau_config": {
        "bureau_name": "Experian",
        "credit_score_model_name": "FICO Score 8",
        "credit_score_range_low": 300,
        "credit_score_range_high": 850,
    },
}
REJECT_RESULT = {"decision": "REJECT", "reason_codes": ["AA01"], "credit_score_used": 610}


def _make_notice():
    from compliance.adverse_action_generator import generate_notice
    return generate_notice("app-pdf-001", "t-001", REJECT_RESULT, None, TENANT_CFG)


# Skip PDF tests if reportlab is not installed
reportlab_available = pytest.importorskip("reportlab", reason="reportlab not installed")


def test_render_returns_pdf_bytes():
    from compliance.adverse_action_pdf import render_notice_pdf

    notice = _make_notice()
    pdf_bytes = render_notice_pdf(notice)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes.startswith(b"%PDF-"), "Output must start with %PDF-"


def test_pdf_contains_notice_id():
    from compliance.adverse_action_pdf import render_notice_pdf

    notice = _make_notice()
    pdf_bytes = render_notice_pdf(notice)

    # The notice_id should appear somewhere in the raw PDF bytes
    assert notice.notice_id.encode() in pdf_bytes or b"Notice ID" in pdf_bytes


def test_watermark_increases_pdf_size(tmp_path):
    from compliance.adverse_action_pdf import render_notice_pdf

    notice = _make_notice()

    pdf_no_wm = render_notice_pdf(notice)

    os.environ["AA_NOTICE_WATERMARK"] = "1"
    try:
        pdf_with_wm = render_notice_pdf(notice)
    finally:
        os.environ.pop("AA_NOTICE_WATERMARK", None)

    assert len(pdf_with_wm) > len(pdf_no_wm), "Watermark should increase PDF size"


def test_import_error_when_reportlab_missing():
    """render_notice_pdf must raise ImportError with helpful message if reportlab absent."""
    from compliance.adverse_action_pdf import render_notice_pdf

    notice = _make_notice()

    # Mock reportlab as unimportable
    with mock.patch.dict(sys.modules, {
        "reportlab": None,
        "reportlab.lib": None,
        "reportlab.lib.colors": None,
        "reportlab.lib.pagesizes": None,
        "reportlab.lib.styles": None,
        "reportlab.lib.units": None,
        "reportlab.platypus": None,
        "reportlab.platypus.flowables": None,
    }):
        with pytest.raises(ImportError, match="reportlab"):
            render_notice_pdf(notice)


def test_output_path_writes_file(tmp_path):
    from compliance.adverse_action_pdf import render_notice_pdf

    notice = _make_notice()
    out = tmp_path / "notice.pdf"
    pdf_bytes = render_notice_pdf(notice, output_path=out)

    assert out.exists()
    assert out.read_bytes() == pdf_bytes
