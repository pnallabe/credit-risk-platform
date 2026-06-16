"""
OCR Engine for the Document Ingestion Pipeline (GAP-17).

Wraps pdf2image, pytesseract, and pdfminer.six to extract text from PDFs.
Importable even when Tesseract is not installed; gracefully raises
TesseractNotAvailableError if OCR fallback is required but unavailable.
"""

from __future__ import annotations

import asyncio
import shutil
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from typing import Optional

# ---------------------------------------------------------------------------
# Tesseract availability check (cached at module load time)
# ---------------------------------------------------------------------------
_TESSERACT_PATH: Optional[str] = shutil.which("tesseract")
_TESSERACT_AVAILABLE: bool = _TESSERACT_PATH is not None

# Thread-pool for CPU-bound / blocking operations
_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# Minimum characters-per-page threshold — below this we fall back to OCR
_MIN_CHARS_PER_PAGE = 50


class TesseractNotAvailableError(RuntimeError):
    """Raised when the tesseract binary cannot be found but is required."""


def _extract_text_with_pdfminer(pdf_bytes: bytes) -> tuple[str, int]:
    """Fast path: extract text from a digital (text-layer) PDF using pdfminer.

    Returns (text, page_count).
    """
    from pdfminer.high_level import extract_text as pm_extract_text
    from pdfminer.high_level import extract_pages

    text = pm_extract_text(BytesIO(pdf_bytes))
    # Count pages by iterating page layout objects
    page_count = sum(1 for _ in extract_pages(BytesIO(pdf_bytes)))
    return text, max(page_count, 1)


def _ocr_pdf_bytes(pdf_bytes: bytes, dpi: int, lang: str) -> tuple[str, int]:
    """CPU-bound: rasterise each PDF page and run Tesseract OCR.

    Returns (full_text, page_count).
    Raises TesseractNotAvailableError if tesseract binary is absent.
    """
    if not _TESSERACT_AVAILABLE:
        raise TesseractNotAvailableError(
            "Tesseract OCR binary not found. "
            "Install with: apt-get install -y tesseract-ocr  OR  brew install tesseract"
        )

    import pytesseract
    from pdf2image import convert_from_bytes

    images = convert_from_bytes(pdf_bytes, dpi=dpi)
    texts: list[str] = []
    for img in images:
        texts.append(pytesseract.image_to_string(img, lang=lang))

    return "\n".join(texts), len(images)


def _ocr_image_bytes(image_bytes: bytes, lang: str, psm: int) -> str:
    """CPU-bound: run pytesseract on a single image (PNG/JPEG bytes).

    Raises TesseractNotAvailableError if tesseract binary is absent.
    """
    if not _TESSERACT_AVAILABLE:
        raise TesseractNotAvailableError(
            "Tesseract OCR binary not found. "
            "Install with: apt-get install -y tesseract-ocr  OR  brew install tesseract"
        )

    import pytesseract
    from PIL import Image

    image = Image.open(BytesIO(image_bytes))
    return pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}")


async def pdf_to_text(
    pdf_bytes: bytes,
    *,
    dpi: int = 300,
    lang: str = "eng",
    use_pdfminer_fallback: bool = True,
) -> tuple[str, int]:
    """Extract text from a PDF.

    Strategy:
    1. Try pdfminer.six first (fast, zero external binary requirement) for PDFs
       that already have a text layer.
    2. If pdfminer yields fewer than 50 characters per page on average, fall back
       to pdf2image + pytesseract (OCR on rasterised pages).

    Returns:
        (full_text: str, page_count: int)

    Raises:
        TesseractNotAvailableError: if OCR fallback is needed but Tesseract not found.
    """
    loop = asyncio.get_event_loop()

    # -- Fast path: pdfminer --------------------------------------------------
    try:
        pdfminer_text, page_count = await loop.run_in_executor(
            _EXECUTOR, _extract_text_with_pdfminer, pdf_bytes
        )
        avg_chars = len(pdfminer_text.strip()) / max(page_count, 1)
        if avg_chars >= _MIN_CHARS_PER_PAGE:
            return pdfminer_text, page_count
    except Exception:
        # pdfminer failed — proceed to OCR
        page_count = 1

    # -- Slow path: Tesseract OCR ---------------------------------------------
    if not use_pdfminer_fallback:
        raise TesseractNotAvailableError(
            "pdfminer fallback disabled and PDF has insufficient text layer."
        )

    full_text, ocr_page_count = await loop.run_in_executor(
        _EXECUTOR, _ocr_pdf_bytes, pdf_bytes, dpi, lang
    )
    return full_text, ocr_page_count


async def extract_text_from_image(
    image_bytes: bytes,
    *,
    lang: str = "eng",
    psm: int = 6,
) -> str:
    """Run pytesseract on a single PIL Image (PNG/JPEG bytes).

    Returns raw OCR text.

    Raises:
        TesseractNotAvailableError: if the tesseract binary is absent.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        _EXECUTOR, _ocr_image_bytes, image_bytes, lang, psm
    )
