"""Acceptance tests for document_classifier.py (GAP-17, prompt G17-C)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from document_models import DocumentType
from document_classifier import (
    classify_document,
    extract_bank_statement_fields,
    extract_pay_stub_fields,
    extract_tax_return_fields,
)


PAY_STUB_TEXT = """
Acme Corp
Pay Period: 01/01/2026 - 01/15/2026
Gross Pay: $5,230.00
Net Pay: $4,100.00
YTD: $10,460.00
Employer EIN: 12-3456789
"""

BANK_STATEMENT_TEXT = """
First National Bank
Statement Period: 01/01/2026 - 01/31/2026
Beginning Balance: $2,500.00
Ending Balance: $3,100.00
Routing Number: 021000089
Available Balance: $3,100.00
Account: ****1234
"""

TAX_RETURN_TEXT = """
Form 1040
Internal Revenue Service
2025 Tax Return
Adjusted Gross Income: $75,000
Total Tax: $12,500
Taxable Income: $65,000
"""

UNKNOWN_TEXT = "Lorem ipsum dolor sit amet consectetur adipiscing elit."


class TestClassifyDocument:
    def test_pay_stub_classification(self):
        doc_type, confidence = classify_document(PAY_STUB_TEXT)
        assert doc_type == DocumentType.PAY_STUB
        assert confidence >= 0.6

    def test_bank_statement_classification(self):
        doc_type, confidence = classify_document(BANK_STATEMENT_TEXT)
        assert doc_type == DocumentType.BANK_STATEMENT
        assert confidence >= 0.6

    def test_tax_return_classification(self):
        doc_type, confidence = classify_document(TAX_RETURN_TEXT)
        assert doc_type == DocumentType.TAX_RETURN
        assert confidence >= 0.6

    def test_unknown_text_returns_unknown(self):
        doc_type, confidence = classify_document(UNKNOWN_TEXT)
        assert doc_type == DocumentType.UNKNOWN
        assert confidence == 0.0

    def test_empty_string_returns_unknown(self):
        doc_type, confidence = classify_document("")
        assert doc_type == DocumentType.UNKNOWN
        assert confidence == 0.0

    def test_client_hint_applied_when_agreement(self):
        """If client_hint matches the classified type, confidence is capped at 0.9."""
        doc_type, confidence = classify_document(
            PAY_STUB_TEXT,
            client_hint=DocumentType.PAY_STUB,
        )
        assert doc_type == DocumentType.PAY_STUB
        assert confidence <= 0.9


class TestExtractPayStubFields:
    def test_gross_pay_extracted(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        field_names = {f.field_name for f in fields}
        assert "gross_pay" in field_names

    def test_net_pay_extracted(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        field_names = {f.field_name for f in fields}
        assert "net_pay" in field_names

    def test_ytd_gross_extracted(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        field_names = {f.field_name for f in fields}
        assert "ytd_gross" in field_names

    def test_gross_pay_raw_value(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        gross = next(f for f in fields if f.field_name == "gross_pay")
        assert "5" in gross.raw_value  # 5,230.00 or similar

    def test_gross_pay_confidence(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        gross = next(f for f in fields if f.field_name == "gross_pay")
        assert gross.confidence == 1.0

    def test_bounding_box_is_none(self):
        fields = extract_pay_stub_fields(PAY_STUB_TEXT)
        for f in fields:
            assert f.bounding_box is None


class TestExtractBankStatementFields:
    def test_beginning_balance_extracted(self):
        fields = extract_bank_statement_fields(BANK_STATEMENT_TEXT)
        names = {f.field_name for f in fields}
        assert "beginning_balance" in names

    def test_ending_balance_extracted(self):
        fields = extract_bank_statement_fields(BANK_STATEMENT_TEXT)
        names = {f.field_name for f in fields}
        assert "ending_balance" in names

    def test_account_last4_extracted(self):
        fields = extract_bank_statement_fields(BANK_STATEMENT_TEXT)
        names = {f.field_name for f in fields}
        assert "account_last4" in names
        last4 = next(f for f in fields if f.field_name == "account_last4")
        assert last4.raw_value == "1234"


class TestExtractTaxReturnFields:
    def test_agi_extracted(self):
        fields = extract_tax_return_fields(TAX_RETURN_TEXT)
        names = {f.field_name for f in fields}
        assert "adjusted_gross_income" in names

    def test_total_tax_extracted(self):
        fields = extract_tax_return_fields(TAX_RETURN_TEXT)
        names = {f.field_name for f in fields}
        assert "total_tax" in names

    def test_tax_year_extracted(self):
        fields = extract_tax_return_fields(TAX_RETURN_TEXT)
        names = {f.field_name for f in fields}
        assert "tax_year" in names
        year = next(f for f in fields if f.field_name == "tax_year")
        assert year.raw_value == "2025"
