"""Acceptance tests for document_models.py (GAP-17, prompt G17-A)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from pydantic import ValidationError

from document_models import (
    DocumentExtractionResult,
    DocumentType,
    DocumentUploadRequest,
    ExtractedField,
)


class TestDocumentType:
    def test_valid_values(self):
        assert DocumentType.PAY_STUB == "pay_stub"
        assert DocumentType.BANK_STATEMENT == "bank_statement"
        assert DocumentType.TAX_RETURN == "tax_return"
        assert DocumentType.UTILITY_BILL == "utility_bill"
        assert DocumentType.GOVERNMENT_ID == "government_id"
        assert DocumentType.UNKNOWN == "unknown"

    def test_rejects_unknown_string(self):
        with pytest.raises(ValidationError):
            DocumentUploadRequest(
                application_id="app-1",
                document_type="not_a_real_type",  # invalid
                filename="test.pdf",
            )


class TestDocumentUploadRequest:
    def test_valid_instantiation(self):
        req = DocumentUploadRequest(
            application_id="app-123",
            document_type=DocumentType.PAY_STUB,
            page_count_hint=3,
            filename="paystub.pdf",
        )
        assert req.application_id == "app-123"
        assert req.document_type == DocumentType.PAY_STUB
        assert req.page_count_hint == 3

    def test_defaults(self):
        req = DocumentUploadRequest(
            application_id="app-1",
            document_type=DocumentType.UNKNOWN,
            filename="doc.pdf",
        )
        assert req.page_count_hint == 0


class TestExtractedField:
    def test_valid_instantiation(self):
        field = ExtractedField(
            field_name="gross_pay",
            raw_value="5230.00",
            normalized_value=5230.0,
            confidence=1.0,
            page_number=1,
            bounding_box={"x": 10, "y": 20, "w": 100, "h": 20},
        )
        assert field.field_name == "gross_pay"
        assert field.confidence == 1.0

    def test_optional_fields_default_none(self):
        field = ExtractedField(
            field_name="net_pay",
            raw_value="4000.00",
            confidence=0.9,
            page_number=1,
        )
        assert field.normalized_value is None
        assert field.bounding_box is None


class TestDocumentExtractionResult:
    def test_feature_dict_is_plain_dict(self):
        result = DocumentExtractionResult(
            application_id="app-1",
            document_type=DocumentType.PAY_STUB,
            filename="stub.pdf",
            page_count=1,
            extracted_fields=[],
            raw_text="",
            classification_confidence=0.9,
            processing_time_ms=123.4,
            errors=[],
            gcs_uri=None,
            feature_dict={"application_id": "app-1"},
        )
        assert isinstance(result.feature_dict, dict)
        assert result.feature_dict is not None

    def test_full_instantiation(self):
        field = ExtractedField(
            field_name="gross_pay",
            raw_value="5000",
            confidence=1.0,
            page_number=1,
        )
        result = DocumentExtractionResult(
            application_id="app-2",
            document_type=DocumentType.PAY_STUB,
            filename="pay.pdf",
            page_count=2,
            extracted_fields=[field],
            raw_text="gross pay 5000",
            classification_confidence=0.95,
            processing_time_ms=45.6,
            errors=["minor warning"],
            gcs_uri="gs://bucket/file.pdf",
            feature_dict={"pay_stub__gross_pay": 5000.0},
        )
        assert result.page_count == 2
        assert len(result.extracted_fields) == 1
        assert result.gcs_uri == "gs://bucket/file.pdf"
