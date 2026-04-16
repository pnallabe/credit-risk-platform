"""Acceptance tests for field_normalizer.py (GAP-17, prompt G17-D)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import date

import pytest

from document_models import DocumentType, ExtractedField
from field_normalizer import (
    fields_to_feature_dict,
    normalize_currency,
    normalize_date,
    normalize_fields,
)


class TestNormalizeCurrency:
    def test_dollar_amount(self):
        assert normalize_currency("$5,230.00") == 5230.0

    def test_plain_number(self):
        assert normalize_currency("5230") == 5230.0

    def test_number_with_commas(self):
        assert normalize_currency("5,230.00") == 5230.0

    def test_not_a_number(self):
        assert normalize_currency("not a number") is None

    def test_empty_string(self):
        assert normalize_currency("") is None

    def test_euro_symbol(self):
        assert normalize_currency("€1,500.50") == 1500.5

    def test_pound_symbol(self):
        assert normalize_currency("£999.99") == 999.99

    def test_zero(self):
        assert normalize_currency("0") == 0.0


class TestNormalizeDate:
    def test_mm_dd_yyyy(self):
        assert normalize_date("01/15/2026") == date(2026, 1, 15)

    def test_month_name(self):
        result = normalize_date("JAN 15 2026")
        assert result == date(2026, 1, 15)

    def test_iso_format(self):
        assert normalize_date("2026-01-15") == date(2026, 1, 15)

    def test_garbage_returns_none(self):
        assert normalize_date("garbage") is None

    def test_empty_returns_none(self):
        assert normalize_date("") is None

    def test_dd_mmm_yyyy(self):
        result = normalize_date("15 Jan 2026")
        assert result == date(2026, 1, 15)


class TestNormalizeFields:
    def _make_field(self, name, raw) -> ExtractedField:
        return ExtractedField(
            field_name=name,
            raw_value=raw,
            confidence=1.0,
            page_number=1,
        )

    def test_currency_suffix_normalizes_to_float(self):
        fields = [self._make_field("gross_pay", "$5,230.00")]
        result = normalize_fields(fields)
        assert result[0].normalized_value == 5230.0

    def test_date_suffix_normalizes_to_date(self):
        fields = [self._make_field("pay_period_start", "01/15/2026")]
        result = normalize_fields(fields)
        assert result[0].normalized_value == date(2026, 1, 15)

    def test_other_suffix_stays_string(self):
        fields = [self._make_field("employer_name", "Acme Corp")]
        result = normalize_fields(fields)
        assert result[0].normalized_value == "Acme Corp"

    def test_balance_suffix_normalizes(self):
        fields = [self._make_field("ending_balance", "3,100.00")]
        result = normalize_fields(fields)
        assert result[0].normalized_value == 3100.0

    def test_income_suffix_normalizes(self):
        fields = [self._make_field("adjusted_gross_income", "75000")]
        result = normalize_fields(fields)
        assert result[0].normalized_value == 75000.0


class TestFieldsToFeatureDict:
    def _make_field(self, name, raw, normalized=None) -> ExtractedField:
        return ExtractedField(
            field_name=name,
            raw_value=raw,
            normalized_value=normalized,
            confidence=1.0,
            page_number=1,
        )

    def test_prefix_applied(self):
        fields = [
            self._make_field("gross_pay", "5000.00", normalized=5000.0),
            self._make_field("net_pay", "4000.00", normalized=4000.0),
        ]
        result = fields_to_feature_dict(DocumentType.PAY_STUB, fields, "app-1")
        assert "pay_stub__gross_pay" in result
        assert "pay_stub__net_pay" in result

    def test_required_meta_keys(self):
        fields = [self._make_field("gross_pay", "5000", normalized=5000.0)]
        result = fields_to_feature_dict(DocumentType.PAY_STUB, fields, "app-1")
        assert result["application_id"] == "app-1"
        assert result["doc_type"] == "pay_stub"
        assert "extraction_field_count" in result
        assert "extraction_confidence_avg" in result

    def test_empty_fields(self):
        result = fields_to_feature_dict(DocumentType.UNKNOWN, [], "app-2")
        assert result["extraction_field_count"] == 0
        assert result["extraction_confidence_avg"] == 0.0

    def test_bank_statement_prefix(self):
        fields = [self._make_field("ending_balance", "3100", normalized=3100.0)]
        result = fields_to_feature_dict(DocumentType.BANK_STATEMENT, fields, "app-3")
        assert "bank_statement__ending_balance" in result
        assert result["bank_statement__ending_balance"] == 3100.0
