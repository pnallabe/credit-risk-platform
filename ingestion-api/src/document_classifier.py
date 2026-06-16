"""
Document Classifier for the Document Ingestion Pipeline (GAP-17).

Lightweight keyword + pattern rules-based classifier.  No ML model is required
at MVP stage; a hook for a future LayoutLM model is provided via the
module-level classify_document() interface.
"""

from __future__ import annotations

import re
from typing import List, Optional

try:
    from document_models import DocumentType, ExtractedField
except ImportError:
    from src.document_models import DocumentType, ExtractedField


# ---------------------------------------------------------------------------
# Keyword rule sets (ordered by specificity; first-match wins)
# ---------------------------------------------------------------------------

_RULES: list[tuple[DocumentType, list[str]]] = [
    (
        DocumentType.PAY_STUB,
        ["gross pay", "net pay", "ytd", "pay period", "employer ein",
         "pay stub", "earnings statement"],
    ),
    (
        DocumentType.BANK_STATEMENT,
        ["account summary", "beginning balance", "ending balance",
         "statement period", "routing number", "available balance"],
    ),
    (
        DocumentType.TAX_RETURN,
        ["form 1040", "adjusted gross income", "schedule",
         "internal revenue service", "irs", "taxable income"],
    ),
    (
        DocumentType.UTILITY_BILL,
        ["account number", "due date", "kwh", "service address",
         "amount due", "utility", "electric", "gas"],
    ),
    (
        DocumentType.GOVERNMENT_ID,
        ["date of birth", "expiration date", "license number",
         "state of", "driver", "passport"],
    ),
]

_KEYWORD_BOOST = 0.15   # confidence added per keyword match


def _count_matches(text_lower: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text_lower)


def classify_document(
    raw_text: str,
    *,
    filename_hint: str = "",
    client_hint: Optional[DocumentType] = None,
) -> tuple[DocumentType, float]:
    """Classify a document from its raw OCR / text content.

    Returns:
        (DocumentType, confidence: float 0.0–1.0)

    Rules (ordered by specificity; first match wins):
    1. If client_hint provided and confidence rules agree (>= 0.5), return
       client_hint at min(0.9, computed_confidence).
    2-6. Keyword matching per document type (see _RULES above).
    7.  Fallback: DocumentType.UNKNOWN at confidence 0.0.
    """
    text_lower = raw_text.lower()
    filename_lower = filename_hint.lower()

    best_type: DocumentType = DocumentType.UNKNOWN
    best_confidence: float = 0.0

    for doc_type, keywords in _RULES:
        hits = _count_matches(text_lower, keywords)
        if hits == 0:
            # Also check filename hint
            fn_hits = _count_matches(filename_lower, keywords)
            if fn_hits == 0:
                continue
            hits = fn_hits

        raw_confidence = min(1.0, _KEYWORD_BOOST * hits)
        # Normalise: a doc with ≥5 keyword hits gets full 1.0 confidence
        normalised = min(1.0, raw_confidence * (len(keywords) / max(hits, 1)) * 0.15)
        confidence = min(1.0, _KEYWORD_BOOST * hits + 0.3)  # base 0.3 + 0.15 per hit

        if confidence > best_confidence:
            best_confidence = confidence
            best_type = doc_type

    # Client-hint override: if the hint agrees with what we found (>= 0.5), apply boost
    if client_hint is not None and best_confidence >= 0.5 and best_type == client_hint:
        best_confidence = min(0.9, best_confidence)
        return best_type, best_confidence

    return best_type, best_confidence


# ---------------------------------------------------------------------------
# Field extraction helpers (regex-based)
# ---------------------------------------------------------------------------

def _make_field(
    field_name: str,
    raw_value: str,
    confidence: float = 1.0,
    page_number: int = 1,
) -> ExtractedField:
    return ExtractedField(
        field_name=field_name,
        raw_value=raw_value,
        normalized_value=None,  # filled by field_normalizer
        confidence=confidence,
        page_number=page_number,
        bounding_box=None,
    )


def extract_pay_stub_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a pay stub using regex patterns."""
    fields: list[ExtractedField] = []
    text = raw_text

    # Gross pay
    m = re.search(r'gross\s*pay[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("gross_pay", m.group(1).strip()))

    # Net pay
    m = re.search(r'net\s*pay[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("net_pay", m.group(1).strip()))

    # YTD gross
    m = re.search(r'ytd[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("ytd_gross", m.group(1).strip()))

    # Pay period dates — look for two ISO-like dates near "pay period"
    period_match = re.search(
        r'pay\s*period[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\s*[-–to]+\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        text, re.IGNORECASE,
    )
    if period_match:
        fields.append(_make_field("pay_period_start", period_match.group(1)))
        fields.append(_make_field("pay_period_end", period_match.group(2)))

    # Employer name heuristic: first non-blank line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        fields.append(_make_field("employer_name", lines[0], confidence=0.5))

    return fields


def extract_bank_statement_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a bank statement using regex patterns."""
    fields: list[ExtractedField] = []
    text = raw_text

    # Beginning balance
    m = re.search(r'beginning\s*balance[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("beginning_balance", m.group(1).strip()))

    # Ending balance
    m = re.search(r'ending\s*balance[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("ending_balance", m.group(1).strip()))

    # Statement period dates
    period_match = re.search(
        r'statement\s*period[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})\s*[-–to]+\s*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})',
        text, re.IGNORECASE,
    )
    if period_match:
        fields.append(_make_field("statement_period_start", period_match.group(1)))
        fields.append(_make_field("statement_period_end", period_match.group(2)))

    # Account last 4 digits
    m = re.search(r'(?:account|acct)[\s#:]*\*{0,4}(\d{4})\b', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("account_last4", m.group(1)))

    return fields


def extract_tax_return_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a 1040 tax return using regex patterns."""
    fields: list[ExtractedField] = []
    text = raw_text

    # Adjusted gross income
    m = re.search(r'adjusted\s*gross\s*income[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("adjusted_gross_income", m.group(1).strip()))

    # Total tax
    m = re.search(r'total\s*tax[\s:$]*([0-9,]+\.?[0-9]*)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("total_tax", m.group(1).strip()))

    # Tax year
    m = re.search(r'(20\d{2})\s*(?:tax|form\s*1040)', text, re.IGNORECASE)
    if m:
        fields.append(_make_field("tax_year", m.group(1)))

    return fields
