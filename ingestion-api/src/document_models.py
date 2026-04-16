"""
Pydantic models for the Document Ingestion / OCR Pipeline (GAP-17).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict


class DocumentType(str, Enum):
    PAY_STUB = "pay_stub"
    BANK_STATEMENT = "bank_statement"
    TAX_RETURN = "tax_return"
    UTILITY_BILL = "utility_bill"
    GOVERNMENT_ID = "government_id"
    UNKNOWN = "unknown"


class DocumentUploadRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    application_id: str
    document_type: DocumentType          # hint from client; OCR validates
    page_count_hint: Optional[int] = 0   # 0 means unknown
    filename: str


class ExtractedField(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    field_name: str
    raw_value: str
    normalized_value: Optional[Any] = None   # typed value after normalization
    confidence: float                         # 0.0–1.0
    page_number: int
    bounding_box: Optional[dict] = None       # {"x": int, "y": int, "w": int, "h": int}


class DocumentExtractionResult(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    application_id: str
    document_type: DocumentType               # confirmed type after classification
    filename: str
    page_count: int
    extracted_fields: List[ExtractedField]
    raw_text: str                             # full concatenated OCR text
    classification_confidence: float          # overall doc-type confidence
    processing_time_ms: float
    errors: List[str]                         # non-fatal extraction warnings
    gcs_uri: Optional[str] = None            # where the original PDF is stored
    feature_dict: dict                        # ready for feature_pipeline ingestion
