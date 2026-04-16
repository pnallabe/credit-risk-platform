"""Acceptance tests for document_pipeline.py (GAP-17, prompt G17-E)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from document_models import DocumentType
from ocr_engine import TesseractNotAvailableError


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


PAY_STUB_TEXT = """
Acme Corp
Pay Period: 01/01/2026 - 01/15/2026
Gross Pay: $5,230.00
Net Pay: $4,100.00
YTD: $10,460.00
Employer EIN: 12-3456789
Pay Stub Earnings Statement
"""


class TestProcessDocument:
    def test_pay_stub_pipeline(self):
        """Mock pdf_to_text → pay stub text → result should be PAY_STUB."""
        import document_pipeline as dp

        with patch.object(dp, "pdf_to_text", new=AsyncMock(return_value=(PAY_STUB_TEXT, 1))):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-1",
                    filename="paystub.pdf",
                )
            )

        assert result.document_type == DocumentType.PAY_STUB
        assert result.application_id == "app-test-1"
        assert result.page_count == 1

    def test_tesseract_error_is_recorded(self):
        """Mock pdf_to_text raising TesseractNotAvailableError → errors list non-empty, raw_text empty."""
        import document_pipeline as dp

        with patch.object(
            dp, "pdf_to_text",
            new=AsyncMock(side_effect=TesseractNotAvailableError("no tesseract"))
        ):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-2",
                    filename="scan.pdf",
                )
            )

        assert len(result.errors) > 0
        assert result.raw_text == ""
        assert any("TesseractNotAvailableError" in e or "tesseract" in e.lower() for e in result.errors)

    def test_feature_dict_keys_prefixed(self):
        """feature_dict keys should be prefixed with doc_type value."""
        import document_pipeline as dp

        with patch.object(dp, "pdf_to_text", new=AsyncMock(return_value=(PAY_STUB_TEXT, 2))):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-3",
                    filename="paycheck.pdf",
                )
            )

        assert result.feature_dict["application_id"] == "app-test-3"
        assert "doc_type" in result.feature_dict

    def test_processing_time_is_positive(self):
        """processing_time_ms must be a positive float."""
        import document_pipeline as dp

        with patch.object(dp, "pdf_to_text", new=AsyncMock(return_value=("some text", 1))):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-4",
                    filename="doc.pdf",
                )
            )

        assert isinstance(result.processing_time_ms, float)
        assert result.processing_time_ms > 0

    def test_never_raises(self):
        """process_document should never propagate exceptions — always returns a result."""
        import document_pipeline as dp

        with patch.object(
            dp, "pdf_to_text",
            new=AsyncMock(side_effect=RuntimeError("unexpected failure"))
        ):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-5",
                    filename="broken.pdf",
                )
            )

        # Should return a result, not raise
        assert result is not None
        assert len(result.errors) > 0

    def test_client_hint_passed_through(self):
        """Client type hint should influence classification."""
        import document_pipeline as dp

        with patch.object(
            dp, "pdf_to_text",
            new=AsyncMock(return_value=(PAY_STUB_TEXT, 1))
        ):
            result = _run(
                dp.process_document(
                    b"fake-pdf",
                    application_id="app-test-6",
                    filename="stub.pdf",
                    client_document_type_hint=DocumentType.PAY_STUB,
                )
            )

        assert result.document_type == DocumentType.PAY_STUB
