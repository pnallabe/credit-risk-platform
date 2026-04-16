"""
Field Normalizer for the Document Ingestion Pipeline (GAP-17).

Converts raw regex-extracted strings to typed Python values before they
enter the feature pipeline.
"""

from __future__ import annotations

import re
from datetime import date
from statistics import mean
from typing import List, Optional

try:
    from dateutil import parser as dateutil_parser
    _DATEUTIL_AVAILABLE = True
except ImportError:
    _DATEUTIL_AVAILABLE = False

try:
    from document_models import DocumentType, ExtractedField
except ImportError:
    from src.document_models import DocumentType, ExtractedField


# ---------------------------------------------------------------------------
# Primitive normalizers
# ---------------------------------------------------------------------------

def normalize_currency(raw: str) -> Optional[float]:
    """Convert "$5,230.00", "5230", "5,230.00" → 5230.0.

    Returns None if the value cannot be parsed.
    """
    if not raw:
        return None
    cleaned = re.sub(r'[$£€\s,]', '', raw.strip())
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def normalize_date(raw: str) -> Optional[date]:
    """Convert common date strings to a Python ``date`` object.

    Handles: MM/DD/YYYY, DD-MM-YYYY, Month DD YYYY, YYYY-MM-DD, DD MMM YYYY.
    Returns None if unparseable.
    """
    if not raw:
        return None
    if not _DATEUTIL_AVAILABLE:
        # Fallback: try ISO format only
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            return None
    try:
        return dateutil_parser.parse(raw.strip(), ignoretz=True).date()
    except (ValueError, OverflowError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Suffix-based dispatch
# ---------------------------------------------------------------------------

_CURRENCY_SUFFIXES = ("_pay", "_income", "_balance", "_tax", "_debt", "_amount")
_DATE_SUFFIXES = ("_date", "_start", "_end", "_period")


def _normalize_single(field: ExtractedField) -> ExtractedField:
    """Return a copy of *field* with ``normalized_value`` populated."""
    name = field.field_name
    if any(name.endswith(s) for s in _CURRENCY_SUFFIXES):
        nv = normalize_currency(field.raw_value)
    elif any(name.endswith(s) for s in _DATE_SUFFIXES):
        nv = normalize_date(field.raw_value)
    else:
        nv = str(field.raw_value)

    return field.model_copy(update={"normalized_value": nv})


def normalize_fields(fields: List[ExtractedField]) -> List[ExtractedField]:
    """Return a new list with ``normalized_value`` populated on each field."""
    return [_normalize_single(f) for f in fields]


# ---------------------------------------------------------------------------
# Feature dict builder
# ---------------------------------------------------------------------------

def fields_to_feature_dict(
    doc_type: DocumentType,
    fields: List[ExtractedField],
    application_id: str,
) -> dict:
    """Convert a list of ExtractedField objects to a flat dict for the feature pipeline.

    Keys are prefixed by doc_type value, e.g. ``pay_stub__gross_pay``.

    Always includes:
        "application_id"           → application_id
        "doc_type"                 → doc_type.value
        "extraction_field_count"   → len(fields)
        "extraction_confidence_avg"→ mean of field.confidence values
    """
    prefix = doc_type.value
    feature: dict = {
        "application_id": application_id,
        "doc_type": doc_type.value,
        "extraction_field_count": len(fields),
        "extraction_confidence_avg": mean(f.confidence for f in fields) if fields else 0.0,
    }
    for f in fields:
        key = f"{prefix}__{f.field_name}"
        feature[key] = f.normalized_value if f.normalized_value is not None else f.raw_value

    return feature
