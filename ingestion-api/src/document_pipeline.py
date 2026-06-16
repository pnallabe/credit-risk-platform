"""
Document Pipeline Orchestrator for the Document Ingestion Pipeline (GAP-17).

Chains: ocr_engine → document_classifier → field extraction → field_normalizer
and produces a final DocumentExtractionResult.  Never raises — all errors are
collected and returned in the ``errors`` list.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

try:
    from document_models import DocumentExtractionResult, DocumentType, ExtractedField
    from ocr_engine import TesseractNotAvailableError, pdf_to_text
    from document_classifier import (
        classify_document,
        extract_bank_statement_fields,
        extract_pay_stub_fields,
        extract_tax_return_fields,
    )
    from field_normalizer import fields_to_feature_dict, normalize_fields
except ImportError:
    from src.document_models import DocumentExtractionResult, DocumentType, ExtractedField
    from src.ocr_engine import TesseractNotAvailableError, pdf_to_text
    from src.document_classifier import (
        classify_document,
        extract_bank_statement_fields,
        extract_pay_stub_fields,
        extract_tax_return_fields,
    )
    from src.field_normalizer import fields_to_feature_dict, normalize_fields

logger = logging.getLogger(__name__)


async def process_document(
    pdf_bytes: bytes,
    *,
    application_id: str,
    filename: str,
    client_document_type_hint: Optional[DocumentType] = None,
    dpi: int = 300,
    lang: str = "eng",
) -> DocumentExtractionResult:
    """Full document processing pipeline.

    Steps:
    1. Record start time.
    2. OCR / text extraction via ocr_engine.pdf_to_text().
    3. Document type classification.
    4. Dispatch to the appropriate extract_*_fields function.
    5. Normalise extracted fields.
    6. Build feature dict.
    7. Return DocumentExtractionResult.

    Never raises — all errors are recorded in the ``errors`` list.
    """
    start_ms = time.monotonic() * 1000
    errors: list[str] = []
    raw_text = ""
    page_count = 0
    doc_type = DocumentType.UNKNOWN
    classification_confidence = 0.0
    extracted_fields: list[ExtractedField] = []
    feature_dict: dict = {}

    # ------------------------------------------------------------------
    # Step 1-2: OCR / text extraction
    # ------------------------------------------------------------------
    try:
        raw_text, page_count = await pdf_to_text(pdf_bytes, dpi=dpi, lang=lang)
    except TesseractNotAvailableError as exc:
        logger.warning(
            "Tesseract not available for application_id=%s: %s", application_id, exc
        )
        errors.append(f"TesseractNotAvailableError: {exc}")
        raw_text = ""
        page_count = 0
    except Exception as exc:
        logger.error(
            "OCR/text extraction failed for application_id=%s: %s", application_id, exc,
            exc_info=True,
        )
        errors.append(f"OCR extraction error: {exc}")
        raw_text = ""
        page_count = 0

    # ------------------------------------------------------------------
    # Step 3: Classification
    # ------------------------------------------------------------------
    try:
        doc_type, classification_confidence = classify_document(
            raw_text,
            filename_hint=filename,
            client_hint=client_document_type_hint,
        )
    except Exception as exc:
        logger.error(
            "Document classification failed for application_id=%s: %s", application_id, exc,
        )
        errors.append(f"Classification error: {exc}")
        doc_type = DocumentType.UNKNOWN
        classification_confidence = 0.0

    # ------------------------------------------------------------------
    # Step 4: Field extraction dispatch
    # ------------------------------------------------------------------
    try:
        if doc_type == DocumentType.PAY_STUB:
            extracted_fields = extract_pay_stub_fields(raw_text)
        elif doc_type == DocumentType.BANK_STATEMENT:
            extracted_fields = extract_bank_statement_fields(raw_text)
        elif doc_type == DocumentType.TAX_RETURN:
            extracted_fields = extract_tax_return_fields(raw_text)
        else:
            extracted_fields = []
            if doc_type not in (DocumentType.UNKNOWN,):
                errors.append(
                    f"No field extractor implemented for doc_type={doc_type.value}; "
                    "fields will be empty."
                )
    except Exception as exc:
        logger.error(
            "Field extraction failed for application_id=%s doc_type=%s: %s",
            application_id, doc_type.value, exc,
        )
        errors.append(f"Field extraction error for {doc_type.value}: {exc}")
        extracted_fields = []

    # ------------------------------------------------------------------
    # Step 5-6: Normalization + feature dict
    # ------------------------------------------------------------------
    normalized_fields: list[ExtractedField] = extracted_fields  # default fallback
    try:
        normalized_fields = normalize_fields(extracted_fields)
        feature_dict = fields_to_feature_dict(doc_type, normalized_fields, application_id)
    except Exception as exc:
        logger.error(
            "Normalization failed for application_id=%s: %s", application_id, exc,
        )
        errors.append(f"Normalization error: {exc}")
        feature_dict = {
            "application_id": application_id,
            "doc_type": doc_type.value,
            "extraction_field_count": 0,
            "extraction_confidence_avg": 0.0,
        }

    # ------------------------------------------------------------------
    # Step 7: Assemble result
    # ------------------------------------------------------------------
    processing_time_ms = time.monotonic() * 1000 - start_ms

    return DocumentExtractionResult(
        application_id=application_id,
        document_type=doc_type,
        filename=filename,
        page_count=page_count,
        extracted_fields=normalized_fields,
        raw_text=raw_text,
        classification_confidence=classification_confidence,
        processing_time_ms=processing_time_ms,
        errors=errors,
        gcs_uri=None,
        feature_dict=feature_dict,
    )
