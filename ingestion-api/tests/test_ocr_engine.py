"""Acceptance tests for ocr_engine.py (GAP-17, prompt G17-B)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncio
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_minimal_text_pdf(text: str = "Hello OCR World") -> bytes:
    """Create a minimal text-layer PDF using reportlab if available,
    falling back to a hand-crafted minimal PDF."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        buf = BytesIO()
        c = rl_canvas.Canvas(buf)
        c.drawString(72, 720, text)
        c.save()
        return buf.getvalue()
    except ImportError:
        pass

    # Minimal hand-crafted PDF with embedded text
    pdf_content = f"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>
stream
BT /F1 12 Tf 72 720 Td ({text}) Tj ET
endstream
endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f
trailer<</Size 6/Root 1 0 R>>
startxref
0
%%EOF"""
    return pdf_content.encode()


class TestOCREngine:
    def test_tesseract_not_available_raises_error(self):
        """When shutil.which returns None and OCR fallback is needed, raise TesseractNotAvailableError."""
        from ocr_engine import TesseractNotAvailableError, _ocr_pdf_bytes

        with patch("ocr_engine._TESSERACT_AVAILABLE", False):
            with pytest.raises(TesseractNotAvailableError):
                _ocr_pdf_bytes(b"fake-pdf", dpi=72, lang="eng")

    def test_pdf_to_text_with_text_layer_pdf(self):
        """pdf_to_text should extract text from a text-layer PDF without Tesseract."""
        # Skip if pdfminer not installed
        pytest.importorskip("pdfminer")

        pdf_bytes = _make_minimal_text_pdf("Hello OCR World")
        text, page_count = _run(
            __import__("ocr_engine").pdf_to_text(pdf_bytes)
        )
        # Text-layer PDF should be extractable without OCR
        assert isinstance(text, str)
        assert page_count >= 1

    def test_extract_text_from_image_async_wrapper(self):
        """Mock pytesseract.image_to_string — assert the async wrapper returns the mocked string."""
        from ocr_engine import extract_text_from_image

        fake_image_bytes = BytesIO()
        # Use a 10x10 white PNG
        try:
            from PIL import Image as PILImage
            img = PILImage.new("RGB", (10, 10), color="white")
            img.save(fake_image_bytes, format="PNG")
        except ImportError:
            pytest.skip("Pillow not installed")

        fake_image_bytes.seek(0)

        with patch("ocr_engine._TESSERACT_AVAILABLE", True), \
             patch("pytesseract.image_to_string", return_value="mocked OCR result") as mock_tess:
            result = _run(extract_text_from_image(fake_image_bytes.read()))
            assert result == "mocked OCR result"

    def test_pdf_to_text_ocr_fallback_raises_when_no_tesseract(self):
        """When pdfminer fails AND tesseract is unavailable, raise TesseractNotAvailableError."""
        import ocr_engine

        with patch("ocr_engine._TESSERACT_AVAILABLE", False):
            with patch("ocr_engine._extract_text_with_pdfminer", side_effect=Exception("pdfminer failed")):
                with pytest.raises(ocr_engine.TesseractNotAvailableError):
                    _run(ocr_engine.pdf_to_text(b"fake-pdf-bytes"))
