# Implementation Plan: Gap Closure — Priority 5 (GAP-17 & GAP-18)
## Integrated Lending Operating Layer (ILOL) — credit-risk-platform

**Version:** 1.0.0
**Date:** April 14, 2026
**Scope:** GAP-17 (Document Ingestion / OCR Pipeline) and GAP-18 (Real-Time Credit Bureau Integration)
**Reference:** PRD §4.1 Document Processing, §4.4 Bureau Integration, §6.2 Ingestion Layer, §7.2 External Data Sources
**Prerequisites:** All P1–P4 gaps closed (confirmed 2026-04-14)

---

## Overview

This document provides a sequential series of self-contained, implementation-ready coding prompts to close the two remaining P5 backlog gaps.

Each prompt specifies:
- The **exact files** to create or modify
- **Interfaces** to implement against the existing architecture
- **Acceptance tests** that define "done"
- All **constraints** from the PRD and current codebase

Work the prompts in order within each gap. GAP-17 and GAP-18 are independent — they may be worked in parallel by different engineers.

---

## Estimated Effort

| Gap | Prompts | Est. Days |
|-----|---------|-----------|
| GAP-17: OCR Pipeline | G17-A → G17-F | 6–8 days |
| GAP-18: Bureau Integration | G18-A → G18-G | 12–15 days |
| **Total** | **13 prompts** | **18–23 days** |

---
---

# GAP-17: Document Ingestion / OCR Pipeline

## Background

The PRD (§4.1) requires Tesseract-based OCR with LayoutLM-style structured extraction for uploaded PDFs (pay stubs, bank statements, tax returns). The `ingestion-api/` service handles GCS upload, Pub/Sub emission, and Plaid-based bank-data enrichment, but has no ability to parse scanned or digital PDF documents. This gap closes the loop: uploaded documents must be processed into structured feature-pipeline-compatible records.

Existing integration points:
- `ingestion-api/src/main.py` — GCS upload, auth, deduplication all in place; new PDF upload endpoint will use the same patterns
- `ingestion-api/src/models.py` — Pydantic models follow the same pattern; extend here
- `feature_pipeline/features.py` — output of OCR must map to feature names consumed here
- `decision-api/src/main.py` `_run_pipeline()` — expects an `ApplicationRequest`; OCR output must be convertible to the same schema

---

### Prompt G17-A: Add Dependencies and Document Model

**Files to create/modify:**
- `ingestion-api/requirements.txt` (modify)
- `ingestion-api/src/document_models.py` (create)

**Task:**

**1. Update `ingestion-api/requirements.txt`:**

Add the following packages (pin to the versions shown):

```
pytesseract>=0.3.10
Pillow>=10.3.0
pdf2image>=1.17.0
python-multipart>=0.0.9
pdfminer.six>=20221105
unstructured[pdf]>=0.13.0
```

> Note: `tesseract-ocr` system binary must be installed separately (document in README). `pdf2image` requires `poppler` system binary. Add a note in `ingestion-api/README.md` (or create it) with: `apt-get install -y tesseract-ocr poppler-utils` or `brew install tesseract poppler`.

**2. Create `ingestion-api/src/document_models.py`:**

Define the following Pydantic models (use the same `ConfigDict(str_strip_whitespace=True)` pattern as `ingestion-api/src/models.py`):

```python
class DocumentType(str, Enum):
    PAY_STUB         = "pay_stub"
    BANK_STATEMENT   = "bank_statement"
    TAX_RETURN       = "tax_return"
    UTILITY_BILL     = "utility_bill"
    GOVERNMENT_ID    = "government_id"
    UNKNOWN          = "unknown"

class DocumentUploadRequest(BaseModel):
    application_id: str
    document_type: DocumentType          # hint from client; OCR validates
    page_count_hint: Optional[int]       # 0 means unknown
    filename: str

class ExtractedField(BaseModel):
    field_name: str
    raw_value: str
    normalized_value: Optional[Any]      # typed value after normalization
    confidence: float                    # 0.0–1.0
    page_number: int
    bounding_box: Optional[dict]         # {"x": int, "y": int, "w": int, "h": int}

class DocumentExtractionResult(BaseModel):
    application_id: str
    document_type: DocumentType          # confirmed type after classification
    filename: str
    page_count: int
    extracted_fields: List[ExtractedField]
    raw_text: str                         # full concatenated OCR text
    classification_confidence: float      # overall doc-type confidence
    processing_time_ms: float
    errors: List[str]                     # non-fatal extraction warnings
    gcs_uri: Optional[str]               # where the original PDF is stored
    feature_dict: dict                   # ready for feature_pipeline ingestion
```

**Acceptance tests:** `ingestion-api/tests/test_document_models.py`
- Instantiate each model with valid data and assert field values
- Assert `DocumentType` enum rejects unknown strings via Pydantic validation
- Assert `feature_dict` is a plain `dict` (not None) on a minimal valid `DocumentExtractionResult`

---

### Prompt G17-B: Implement the OCR Engine

**File to create:** `ingestion-api/src/ocr_engine.py`

**Context:** This module wraps `pdf2image`, `pytesseract`, and `pdfminer.six`. It must be importable even when Tesseract is not installed (graceful degradation with a `TesseractNotAvailableError`).

**Task:**

Implement the following public API:

```python
class TesseractNotAvailableError(RuntimeError):
    """Raised when the tesseract binary cannot be found."""

async def pdf_to_text(
    pdf_bytes: bytes,
    *,
    dpi: int = 300,
    lang: str = "eng",
    use_pdfminer_fallback: bool = True,
) -> tuple[str, int]:
    """
    Extract text from a PDF.

    Strategy:
    1. Try pdfminer.six first (fast, zero external binary requirement) for
       PDFs that are already text-layer PDFs.
    2. If pdfminer yields fewer than 50 characters per page on average,
       fall back to pdf2image + pytesseract (OCR on rasterised pages).

    Returns:
        (full_text: str, page_count: int)

    Raises:
        TesseractNotAvailableError if OCR fallback needed but tesseract not found
    """

async def extract_text_from_image(
    image_bytes: bytes,
    *,
    lang: str = "eng",
    psm: int = 6,
) -> str:
    """Run pytesseract on a single PIL Image (PNG/JPEG bytes). Returns raw OCR text."""
```

**Implementation notes:**
- Run `pdf2image.convert_from_bytes` and `pytesseract.image_to_string` in a `ThreadPoolExecutor` via `asyncio.get_event_loop().run_in_executor()` — they are synchronous and CPU-bound
- Use `pdfminer.six`'s `extract_text(BytesIO(pdf_bytes))` for the fast path
- Detect Tesseract availability at the top of the module with a `shutil.which("tesseract")` check; cache the result

**Acceptance tests:** `ingestion-api/tests/test_ocr_engine.py`
- Mock `shutil.which` returning `None` → assert `TesseractNotAvailableError` is raised when OCR fallback is triggered
- Create a minimal in-memory text-layer PDF using `reportlab` (already a dependency from `compliance/`) → assert `pdf_to_text` returns the expected string without needing Tesseract
- Mock `pytesseract.image_to_string` to return a known string → assert the async wrapper returns it

---

### Prompt G17-C: Implement the Document Classifier

**File to create:** `ingestion-api/src/document_classifier.py`

**Context:** After OCR extracts raw text, a lightweight rules-based classifier determines the `DocumentType`. No ML model is required at this stage — keyword + pattern matching is sufficient for the MVP, with a hook for a future LayoutLM model.

**Task:**

Implement:

```python
def classify_document(
    raw_text: str,
    *,
    filename_hint: str = "",
    client_hint: Optional[DocumentType] = None,
) -> tuple[DocumentType, float]:
    """
    Classify a document from its raw OCR/text content.

    Returns:
        (DocumentType, confidence: float 0.0–1.0)

    Rules (ordered by specificity; first match wins):
    1. If client_hint provided and confidence rules agree (>= 0.5), return client_hint at min(0.9, computed_confidence)
    2. Pay stub: keywords ["gross pay", "net pay", "ytd", "pay period", "employer ein", "pay stub", "earnings statement"]
    3. Bank statement: keywords ["account summary", "beginning balance", "ending balance", "statement period", "routing number", "available balance"]
    4. Tax return: keywords ["form 1040", "adjusted gross income", "schedule", "internal revenue service", "irs", "taxable income"]
    5. Utility bill: keywords ["account number", "due date", "kwh", "service address", "amount due", "utility", "electric", "gas"]
    6. Government ID: keywords ["date of birth", "expiration date", "license number", "state of", "driver", "passport"]
    7. Fallback: DocumentType.UNKNOWN at confidence 0.0
    """

def extract_pay_stub_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a pay stub using regex patterns."""

def extract_bank_statement_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a bank statement using regex patterns."""

def extract_tax_return_fields(raw_text: str) -> List[ExtractedField]:
    """Extract structured fields from a 1040 using regex patterns."""
```

**Field extraction details for each document type:**

*Pay stub fields* (use `re.search` with named groups):
- `gross_pay`: pattern `r'gross\s*pay[\s:$]*([0-9,]+\.?[0-9]*)` (case-insensitive)
- `net_pay`: pattern `r'net\s*pay[\s:$]*([0-9,]+\.?[0-9]*)`
- `pay_period_start` / `pay_period_end`: ISO date patterns near "pay period"
- `employer_name`: first line of the document (heuristic)
- `ytd_gross`: pattern `r'ytd[\s:$]*([0-9,]+\.?[0-9]*)`

*Bank statement fields:*
- `beginning_balance`: pattern `r'beginning\s*balance[\s:$]*([0-9,]+\.?[0-9]*)`
- `ending_balance`: pattern `r'ending\s*balance[\s:$]*([0-9,]+\.?[0-9]*)`
- `statement_period_start` / `_end`: date patterns near "statement period"
- `account_last4`: pattern `r'(?:account|acct)[\s#:]*\*{0,4}(\d{4})\b`

*Tax return fields:*
- `adjusted_gross_income`: pattern `r'adjusted\s*gross\s*income[\s:$]*([0-9,]+\.?[0-9]*)`
- `total_tax`: pattern `r'total\s*tax[\s:$]*([0-9,]+\.?[0-9]*)`
- `tax_year`: pattern `r'(20\d{2})\s*(?:tax|form\s*1040)`

**All `ExtractedField` instances** must set:
- `confidence` to `1.0` for an exact regex match with a plausible value, `0.5` for a fuzzy match
- `page_number` to `1` (single-page extraction at this stage; multi-page in G17-E)
- `bounding_box` to `None` at this stage

**Acceptance tests:** `ingestion-api/tests/test_document_classifier.py`
- Assert `classify_document("gross pay ... net pay ... ytd")` returns `(DocumentType.PAY_STUB, confidence >= 0.8)`
- Assert `classify_document("beginning balance ... ending balance ... routing number")` returns `(DocumentType.BANK_STATEMENT, confidence >= 0.8)`
- Assert unknown text returns `(DocumentType.UNKNOWN, 0.0)`
- Assert `extract_pay_stub_fields` returns an `ExtractedField` for `gross_pay` with correct `normalized_value` (float) from known test text

---

### Prompt G17-D: Implement the Field Normalizer

**File to create:** `ingestion-api/src/field_normalizer.py`

**Context:** Raw regex-extracted values (strings like `"$5,230.00"`, `"01/15/2026"`, `"JAN 15 2026"`) must be normalised to Python-typed values before entering the feature pipeline. This module provides the normalization layer.

**Task:**

Implement:

```python
def normalize_currency(raw: str) -> Optional[float]:
    """
    Convert "$5,230.00", "5230", "5,230.00" → 5230.0
    Returns None if the raw value cannot be parsed.
    Strip currency symbols ($, £, €), commas, and whitespace before converting.
    """

def normalize_date(raw: str) -> Optional[date]:
    """
    Convert common date strings to Python date.
    Handle formats: MM/DD/YYYY, DD-MM-YYYY, Month DD YYYY, YYYY-MM-DD, DD MMM YYYY.
    Return None if unparseable rather than raising.
    Use dateutil.parser.parse() as the primary strategy with ignoretz=True.
    """

def normalize_fields(fields: List[ExtractedField]) -> List[ExtractedField]:
    """
    Return a new list with normalized_value populated on each field.

    Field name suffix rules:
    - ends with _pay, _income, _balance, _tax, _debt, _amount → normalize_currency
    - ends with _date, _start, _end, _period → normalize_date
    - everything else → raw_value cast to str
    """

def fields_to_feature_dict(
    doc_type: DocumentType,
    fields: List[ExtractedField],
    application_id: str,
) -> dict:
    """
    Convert a list of ExtractedField objects to a flat dict
    suitable for feature_pipeline ingestion.

    Keys are prefixed by doc_type value:
        e.g. pay_stub__gross_pay, bank_statement__ending_balance

    Always include:
        "application_id": application_id
        "doc_type": doc_type.value
        "extraction_field_count": len(fields)
        "extraction_confidence_avg": mean of field.confidence values
    """
```

**Dependencies:** `python-dateutil` (already in `requirements.txt` via other modules; if not, add it)

**Acceptance tests:** `ingestion-api/tests/test_field_normalizer.py`
- `normalize_currency("$5,230.00")` → `5230.0`
- `normalize_currency("not a number")` → `None`
- `normalize_date("01/15/2026")` → `date(2026, 1, 15)`
- `normalize_date("JAN 15 2026")` → `date(2026, 1, 15)`
- `normalize_date("garbage")` → `None`
- `fields_to_feature_dict(DocumentType.PAY_STUB, [...], "app-1")` → dict with keys prefixed `pay_stub__` and required meta keys

---

### Prompt G17-E: Implement the Document Pipeline Orchestrator

**File to create:** `ingestion-api/src/document_pipeline.py`

**Context:** This is the top-level orchestrator that chains: `ocr_engine.pdf_to_text` → `document_classifier.classify_document` → `extract_*_fields` → `field_normalizer.normalize_fields` → `fields_to_feature_dict`. It produces the final `DocumentExtractionResult`.

**Task:**

Implement:

```python
async def process_document(
    pdf_bytes: bytes,
    *,
    application_id: str,
    filename: str,
    client_document_type_hint: Optional[DocumentType] = None,
    dpi: int = 300,
    lang: str = "eng",
) -> DocumentExtractionResult:
    """
    Full document processing pipeline.

    Steps:
    1. Record start time (for processing_time_ms)
    2. Call ocr_engine.pdf_to_text(pdf_bytes, dpi=dpi, lang=lang) → (raw_text, page_count)
    3. Call document_classifier.classify_document(raw_text, filename_hint=filename, client_hint=client_document_type_hint)
    4. Dispatch to the appropriate extract_*_fields function based on confirmed doc_type
       (pay_stub → extract_pay_stub_fields, bank_statement → extract_bank_statement_fields,
        tax_return → extract_tax_return_fields, others → empty list + error note)
    5. Call field_normalizer.normalize_fields(extracted_fields)
    6. Call field_normalizer.fields_to_feature_dict(doc_type, normalized_fields, application_id)
    7. Return DocumentExtractionResult with all populated fields

    Error handling:
    - TesseractNotAvailableError → append to errors list, set raw_text = "", page_count = 0, continue
    - Any classification error → doc_type = UNKNOWN, classification_confidence = 0.0
    - Any field extraction error → append error message to errors list, return empty extracted_fields
    - Never raise — always return a DocumentExtractionResult (with errors list populated)
    """
```

**Acceptance tests:** `ingestion-api/tests/test_document_pipeline.py`
- Mock `pdf_to_text` to return a known pay-stub text → assert result is `DocumentType.PAY_STUB`
- Mock `pdf_to_text` to raise `TesseractNotAvailableError` → assert result has `errors` list non-empty and `raw_text == ""`
- Assert `feature_dict` keys are prefixed correctly and `application_id` is in feature_dict
- Assert `processing_time_ms` is a positive float

---

### Prompt G17-F: Expose the Document Upload API Endpoint

**File to modify:** `ingestion-api/src/main.py`

**Context:** The ingestion API already handles `POST /transactions` and `POST /applications` with GCS upload + Pub/Sub. Add a `POST /documents/{application_id}` endpoint that accepts a multipart file upload, runs the document pipeline, stores the raw PDF in GCS, emits an extraction-result event to Pub/Sub, and returns the `DocumentExtractionResult`.

**Task:**

Add the following to `ingestion-api/src/main.py`:

1. **Import** `UploadFile`, `File` from `fastapi` (already importable if `python-multipart` is installed)
2. **Import** `process_document` from `ingestion-api/src/document_pipeline.py`
3. **Add endpoint:**

```python
@app.post(
    "/documents/{application_id}",
    response_model=DocumentExtractionResult,
    status_code=202,
    summary="Upload and OCR-process a document for a given application",
)
async def upload_document(
    application_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type_hint: str = "unknown",
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> DocumentExtractionResult:
    """
    Accept a PDF document upload. Steps:
    1. Authenticate via verify_and_get_tenant (existing pattern)
    2. Read file bytes; enforce max size 20 MB (raise 413 if exceeded)
    3. Validate MIME type is application/pdf or application/octet-stream
    4. SHA-256 deduplicate (use existing _is_duplicate / _record_hash pattern with prefix "doc:")
    5. Call process_document(file_bytes, application_id=application_id, filename=file.filename, ...)
    6. Background task: upload raw PDF to GCS at path
       f"documents/{tenant_id}/{application_id}/{file.filename}" using existing _write_to_gcs
    7. Background task: emit Pub/Sub extraction-result event with topic
       os.getenv("DOCUMENT_EVENTS_TOPIC", "document-extraction-results")
       payload = {"application_id": ..., "doc_type": ..., "feature_dict": ..., "tenant_id": ...}
    8. Set result.gcs_uri before returning
    9. Return the DocumentExtractionResult immediately (don't wait for background tasks)
    """
```

**Constraints:**
- Max upload size: 20 MB (return HTTP 413 if exceeded)
- Only accept `application/pdf` content type (return HTTP 415 otherwise)
- Deduplication key: `f"doc:{tenant_id}:{sha256_of_raw_bytes}"`
- Background tasks must never block the response (follow the existing `_background_upload_and_publish` pattern)
- If `process_document` raises unexpectedly, catch all exceptions, log them, and return a `DocumentExtractionResult` with the error in `errors` and `doc_type = UNKNOWN`

**Acceptance tests:** `ingestion-api/tests/test_document_upload.py`
- Mock `process_document` → assert endpoint returns 202 with valid `DocumentExtractionResult`
- Assert 413 on file > 20 MB
- Assert 415 on non-PDF content type
- Assert duplicate upload returns 200 (not 202) with cached result identifier
- Assert background tasks are enqueued (use `unittest.mock.patch` on `_write_to_gcs` and `_emit_pubsub`)

---

## Summary: GAP-17 File Manifest

| Action | File |
|--------|------|
| Modify | `ingestion-api/requirements.txt` |
| Create | `ingestion-api/src/document_models.py` |
| Create | `ingestion-api/src/ocr_engine.py` |
| Create | `ingestion-api/src/document_classifier.py` |
| Create | `ingestion-api/src/field_normalizer.py` |
| Create | `ingestion-api/src/document_pipeline.py` |
| Modify | `ingestion-api/src/main.py` |
| Create | `ingestion-api/tests/test_document_models.py` |
| Create | `ingestion-api/tests/test_ocr_engine.py` |
| Create | `ingestion-api/tests/test_document_classifier.py` |
| Create | `ingestion-api/tests/test_field_normalizer.py` |
| Create | `ingestion-api/tests/test_document_pipeline.py` |
| Create | `ingestion-api/tests/test_document_upload.py` |

---
---

# GAP-18: Real-Time Credit Bureau Integration

## Background

The PRD (§4.4) requires live bureau pulls from Experian, TransUnion, and Equifax at decisioning time. Currently:
- `ingestion-api/src/main.py` contains a single `enrich_with_bureau_data()` function backed by a mock Experian sandbox response when `BUREAU_API_KEY` is absent
- `decision-api/src/main.py` `_run_pipeline()` does **not** call the bureau at origination time — all features are pre-fetched from the feature store
- No multi-bureau fallback, credential management, or tradeline field mapping exists

The goal is a pluggable, multi-bureau client architecture that can be: (1) called live from the decision pipeline, (2) mocked end-to-end in tests, and (3) extended to new bureau providers without changing calling code.

Existing integration points:
- `decision-api/src/main.py` `_run_pipeline()` — insert live bureau fetch before feature assembly
- `feature_pipeline/features.py` — bureau fields must map to feature names expected here
- `schemas/contracts.py` — `LoanApplicationRequest` schema; bureau pull uses `application_id` + `applicant` fields
- `ingestion-api/src/main.py` `enrich_with_bureau_data()` — **replace** this with a call to the new bureau client library

---

### Prompt G18-A: Define the Bureau Client Interface and Data Models

**File to create:** `ingestion-api/src/bureau_clients/__init__.py`
**File to create:** `ingestion-api/src/bureau_clients/base.py`
**File to create:** `ingestion-api/src/bureau_clients/models.py`

**Task:**

**1. Create `ingestion-api/src/bureau_clients/models.py`:**

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

class BureauProvider(str, Enum):
    EXPERIAN    = "experian"
    TRANSUNION  = "transunion"
    EQUIFAX     = "equifax"
    MOCK        = "mock"

@dataclass(frozen=True)
class BureauRequest:
    application_id: str
    first_name: str
    last_name: str
    date_of_birth: str          # ISO-8601 YYYY-MM-DD
    ssn_last4: str              # last 4 digits only (never log full SSN)
    address_line1: str
    city: str
    state: str                  # 2-letter US state code
    zip_code: str
    requested_amount: float
    loan_purpose: str

@dataclass(frozen=True)
class Tradeline:
    creditor_name: str
    account_type: str           # "revolving" | "installment" | "mortgage" | "other"
    balance: float
    credit_limit: Optional[float]
    payment_status: str         # "current" | "30_dpd" | "60_dpd" | "90_dpd" | "chargeoff"
    opened_date: Optional[str]  # ISO-8601
    months_on_file: Optional[int]

@dataclass(frozen=True)
class BureauResponse:
    provider: BureauProvider
    application_id: str
    credit_score: int                   # FICO 8 or provider equivalent
    score_model: str                    # e.g. "FICO_8", "VantageScore_4"
    open_accounts: int
    delinquencies_last_24m: int
    total_debt: float
    utilisation_rate: float             # 0.0–1.0
    inquiries_last_6m: int
    months_since_oldest_account: int
    public_records: int
    tradelines: List[Tradeline] = field(default_factory=list)
    raw_response: dict = field(default_factory=dict)  # vendor-original payload
    pulled_at: str = ""                 # ISO-8601 UTC timestamp

    def to_feature_dict(self) -> dict:
        """Return a flat dict suitable for feature_pipeline ingestion."""
        return {
            "bureau_provider":              self.provider.value,
            "credit_score":                 self.credit_score,
            "open_accounts":                self.open_accounts,
            "delinquencies_last_24m":       self.delinquencies_last_24m,
            "total_debt":                   self.total_debt,
            "utilisation_rate":             self.utilisation_rate,
            "inquiries_last_6m":            self.inquiries_last_6m,
            "months_since_oldest_account":  self.months_since_oldest_account,
            "public_records":               self.public_records,
            # Derived tradeline aggregates
            "tradeline_count":              len(self.tradelines),
            "derogatory_tradeline_count":   sum(
                1 for t in self.tradelines
                if t.payment_status not in ("current",)
            ),
            "revolving_utilisation_avg":    self._revolving_util_avg(),
        }

    def _revolving_util_avg(self) -> float:
        revolving = [
            t for t in self.tradelines
            if t.account_type == "revolving" and t.credit_limit and t.credit_limit > 0
        ]
        if not revolving:
            return 0.0
        return sum(t.balance / t.credit_limit for t in revolving) / len(revolving)

class BureauPullError(Exception):
    """Raised when all bureau providers fail or are misconfigured."""
    def __init__(self, message: str, provider: Optional[BureauProvider] = None):
        super().__init__(message)
        self.provider = provider
```

**2. Create `ingestion-api/src/bureau_clients/base.py`:**

Define the abstract base class:

```python
from abc import ABC, abstractmethod
from .models import BureauRequest, BureauResponse

class BureauClient(ABC):
    """Abstract base for all bureau provider clients."""

    @property
    @abstractmethod
    def provider(self) -> BureauProvider:
        """The bureau provider this client talks to."""

    @abstractmethod
    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        Perform a live credit pull.

        Raises:
            BureauPullError: if the request fails (network, auth, throttle).
                             Caller is responsible for fallback logic.
        """

    async def health_check(self) -> bool:
        """
        Ping the bureau's health endpoint.
        Default implementation returns True (override in concrete clients).
        """
        return True
```

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_models.py`
- Instantiate `BureauResponse` with two tradelines (one revolving, one installment) → assert `to_feature_dict()` keys include all listed fields
- Assert `_revolving_util_avg()` computes correctly
- Assert `BureauProvider` enum values are the strings "experian", "transunion", "equifax", "mock"

---

### Prompt G18-B: Implement the Mock Bureau Client

**File to create:** `ingestion-api/src/bureau_clients/mock_client.py`

**Context:** The mock client replaces the existing `_MOCK_BUREAU_RESPONSE` dict in `ingestion-api/src/main.py`. It is deterministic (seeded by `application_id` hash) so the same application always receives the same score in tests.

**Task:**

```python
import hashlib
from .base import BureauClient
from .models import BureauProvider, BureauRequest, BureauResponse, Tradeline

class MockBureauClient(BureauClient):
    """
    Deterministic mock bureau client for local development and testing.

    Score and field values are derived from SHA-256(application_id) so
    the same application ID always receives the same mock response.
    """

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.MOCK

    async def pull(self, request: BureauRequest) -> BureauResponse:
        seed = int(hashlib.sha256(request.application_id.encode()).hexdigest(), 16)

        # Deterministic values seeded from application_id hash
        credit_score          = 580 + (seed % 270)       # 580–849
        open_accounts         = 2 + (seed % 10)
        delinquencies         = 0 if (seed % 5) != 0 else (seed % 3)
        total_debt            = round(5000 + (seed % 45000), 2)
        utilisation           = round((seed % 60) / 100, 2)   # 0.00–0.59
        inquiries             = seed % 5
        months_oldest         = 24 + (seed % 120)
        public_records        = 0 if (seed % 8) != 0 else 1

        tradelines = [
            Tradeline(
                creditor_name="Mock Bank NA",
                account_type="revolving",
                balance=round(total_debt * 0.4, 2),
                credit_limit=round(total_debt * 0.8, 2),
                payment_status="current",
                opened_date=None,
                months_on_file=months_oldest // 2,
            ),
            Tradeline(
                creditor_name="Mock Auto Finance",
                account_type="installment",
                balance=round(total_debt * 0.6, 2),
                credit_limit=None,
                payment_status="current" if delinquencies == 0 else "30_dpd",
                opened_date=None,
                months_on_file=months_oldest,
            ),
        ]

        from datetime import datetime, timezone
        return BureauResponse(
            provider=BureauProvider.MOCK,
            application_id=request.application_id,
            credit_score=credit_score,
            score_model="MOCK_FICO_8",
            open_accounts=open_accounts,
            delinquencies_last_24m=delinquencies,
            total_debt=total_debt,
            utilisation_rate=utilisation,
            inquiries_last_6m=inquiries,
            months_since_oldest_account=months_oldest,
            public_records=public_records,
            tradelines=tradelines,
            raw_response={"mock": True, "seed": seed % 99999},
            pulled_at=datetime.now(timezone.utc).isoformat(),
        )
```

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_mock_client.py`
- Assert same `application_id` always produces the same `credit_score`
- Assert `credit_score` is always in range 580–849
- Assert `tradeline_count` is 2
- Assert `to_feature_dict()` returns correct computed values

---

### Prompt G18-C: Implement the Experian Client

**File to create:** `ingestion-api/src/bureau_clients/experian_client.py`

**Context:** Experian's ConnectPlus API uses OAuth2 client-credentials flow. The existing `enrich_with_bureau_data()` in `main.py` makes a single call to `sandbox.experian.com/consumerservices/credit-profile/v2/credit-score`. The production endpoint is `us.api.experian.com/consumerservices/credit-profile/v2/credit-score`. Credentials are managed via GCP Secret Manager (or env vars for development).

**Task:**

Implement `ExperianClient(BureauClient)` with:

```python
class ExperianClient(BureauClient):
    """
    Experian ConnectPlus credit pull client.

    Required environment variables (or GCP Secret Manager secrets):
        EXPERIAN_CLIENT_ID       — OAuth2 client ID
        EXPERIAN_CLIENT_SECRET   — OAuth2 client secret
        EXPERIAN_SUBSCRIBER_CODE — Experian subscriber/member code
        EXPERIAN_ENV             — "sandbox" | "production" (default: "sandbox")

    Token refresh: OAuth2 client-credentials token is cached in-memory
    with a 5-minute buffer before expiry.
    """

    _BASE_URL_SANDBOX    = "https://sandbox.experian.com"
    _BASE_URL_PRODUCTION = "https://us.api.experian.com"
    _TOKEN_PATH          = "/oauth2/v1/token"
    _CREDIT_PROFILE_PATH = "/consumerservices/credit-profile/v2/credit-score"

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.EXPERIAN

    async def _get_token(self) -> str:
        """
        Return a valid bearer token. Refresh if expired or within 5 minutes of expiry.
        Uses httpx.AsyncClient with a 10-second timeout.
        POST to {base_url}/oauth2/v1/token with grant_type=client_credentials.
        Cache token in self._token / self._token_expires_at.
        Raise BureauPullError on failure.
        """

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        POST to {base_url}/consumerservices/credit-profile/v2/credit-score.

        Request body (JSON):
        {
          "appReference": request.application_id,
          "primaryConsumer": {
            "name": {"firstName": ..., "lastName": ...},
            "dob": {"dob": "MMDDYYYY"},
            "ssn": {"last4": request.ssn_last4},
            "currentAddress": {
              "line1": ..., "city": ..., "state": ..., "zipCode": ...
            }
          },
          "requestedAttributes": ["scores", "trades", "inquiries", "publicRecords"]
        }

        Map response fields to BureauResponse:
        - scores[0].scoreValue → credit_score (int)
        - scores[0].scoreModel → score_model
        - trades (array) → tradelines
        - inquiries filtered to last 6 months → inquiries_last_6m
        - publicRecords array length → public_records

        On HTTP 4xx/5xx: raise BureauPullError(f"Experian {status}: {body[:200]}")
        On timeout: raise BureauPullError("Experian request timed out")
        """

    def _map_experian_trade(self, trade: dict) -> Tradeline:
        """Map a single Experian trades[] element to a Tradeline."""

    async def health_check(self) -> bool:
        """GET {base_url}/oauth2/v1/token (token refresh) → True if successful."""
```

**Constraints:**
- `httpx` must be used (already in requirements)
- Never log `ssn_last4` or full SSN values — mask in all log messages as `"****"`
- Timeout: 10 seconds for token fetch, 15 seconds for credit pull
- On sandbox, `EXPERIAN_CLIENT_ID` / `EXPERIAN_CLIENT_SECRET` may be stubbed values
- Wrap all HTTP calls in try/except; translate `httpx.TimeoutException` → `BureauPullError`

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_experian_client.py`
- Mock `httpx.AsyncClient.post` for token endpoint → assert token is cached after first call
- Mock `httpx.AsyncClient.post` for credit profile endpoint → assert `BureauResponse.credit_score` maps correctly
- Mock HTTP 429 response → assert `BureauPullError` is raised
- Assert SSN is never present in any log output (mock logging and inspect records)

---

### Prompt G18-D: Implement the TransUnion Client

**File to create:** `ingestion-api/src/bureau_clients/transunion_client.py`

**Context:** TransUnion TruVision uses certificate-based mutual TLS (mTLS) + API key authentication. The REST endpoint is `https://prod.api.transunion.com/credit-report`. Unlike Experian's OAuth2 flow, TransUnion requires a client certificate (`.pem`) provided via environment variables or GCP Secret Manager.

**Task:**

Implement `TransUnionClient(BureauClient)` with:

```python
class TransUnionClient(BureauClient):
    """
    TransUnion TruVision credit pull client.

    Required environment variables:
        TRANSUNION_API_KEY           — API key header value
        TRANSUNION_SUBSCRIBER_CODE   — Subscriber code
        TRANSUNION_CERT_PEM          — PEM-encoded client certificate (string)
        TRANSUNION_KEY_PEM           — PEM-encoded private key (string)
        TRANSUNION_ENV               — "sandbox" | "production" (default: "sandbox")

    mTLS: The client cert/key are written to a NamedTemporaryFile at first use
    and the path is passed to httpx.AsyncClient(cert=...).
    """

    _BASE_URL_SANDBOX    = "https://sandbox.api.transunion.com"
    _BASE_URL_PRODUCTION = "https://prod.api.transunion.com"
    _CREDIT_REPORT_PATH  = "/credit-report/v2/consumer"

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.TRANSUNION

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        POST to {base_url}/credit-report/v2/consumer.

        Headers:
            X-API-Key: {TRANSUNION_API_KEY}
            X-Subscriber-Code: {TRANSUNION_SUBSCRIBER_CODE}
            Content-Type: application/json

        Request body:
        {
          "requestReference": request.application_id,
          "subject": {
            "name": {"firstName": ..., "lastName": ...},
            "dateOfBirth": "YYYY-MM-DD",
            "ssnLast4": request.ssn_last4,
            "address": {"addressLine1": ..., "city": ..., "state": ..., "zipCode": ...}
          },
          "includeProducts": ["CreditScore", "TradeLines", "Inquiries", "PublicRecords"]
        }

        Map response to BureauResponse using the same pattern as ExperianClient.pull().
        TransUnion score field path: response["creditScore"]["score"]
        Tradelines path: response["tradeLines"]
        """

    def _map_transunion_trade(self, trade: dict) -> Tradeline:
        """Map a single TransUnion tradeLines[] element to a Tradeline."""

    def _get_cert_paths(self) -> tuple[str, str]:
        """
        Write TRANSUNION_CERT_PEM and TRANSUNION_KEY_PEM env vars to
        NamedTemporaryFiles if not already written. Return (cert_path, key_path).
        Use a module-level cache so the files are only written once per process.
        """
```

**Constraints:** Same as ExperianClient — 15-second timeout, mTLS via `httpx.AsyncClient(cert=(cert_path, key_path))`, mask SSN in logs, raise `BureauPullError` on all failures.

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_transunion_client.py`
- Mock httpx post → assert `BureauResponse.provider == BureauProvider.TRANSUNION`
- Mock missing `TRANSUNION_CERT_PEM` env var → assert `BureauPullError` raised with meaningful message
- Assert mTLS cert temp files are written only once (module-level cache)

---

### Prompt G18-E: Implement the Equifax Client

**File to create:** `ingestion-api/src/bureau_clients/equifax_client.py`

**Context:** Equifax uses OAuth2 PKCE + API key (`X-Equifax-Customer-Number`). REST endpoint is `https://api.equifax.com/business/creditreports/v1/basic`. Like Experian, token is obtained via client-credentials flow but Equifax also requires a `X-Equifax-Customer-Number` header on every request.

**Task:**

Implement `EquifaxClient(BureauClient)` following the same pattern as `ExperianClient`:

```python
class EquifaxClient(BureauClient):
    """
    Equifax OneView credit pull client.

    Required environment variables:
        EQUIFAX_CLIENT_ID         — OAuth2 client ID
        EQUIFAX_CLIENT_SECRET     — OAuth2 client secret
        EQUIFAX_CUSTOMER_NUMBER   — Required header value
        EQUIFAX_ENV               — "sandbox" | "production" (default: "sandbox")
    """

    _BASE_URL_SANDBOX    = "https://api.sandbox.equifax.com"
    _BASE_URL_PRODUCTION = "https://api.equifax.com"
    _TOKEN_PATH          = "/v1/oauth/token"
    _CREDIT_REPORT_PATH  = "/business/creditreports/v1/basic"

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.EQUIFAX

    async def _get_token(self) -> str: ...   # same pattern as ExperianClient

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        POST to {base_url}/business/creditreports/v1/basic.

        Headers:
            Authorization: Bearer {token}
            X-Equifax-Customer-Number: {EQUIFAX_CUSTOMER_NUMBER}

        Request body:
        {
          "consumers": {
            "name": [{"firstName": ..., "lastName": ...}],
            "socialNum": [{"ssnLast4": request.ssn_last4}],
            "addresses": [{"addressLine1": ..., "city": ..., "state": ..., "zip": ...}]
          }
        }

        Map response: score from response["score"]["value"],
        tradelines from response["tradelines"], etc.
        """

    def _map_equifax_trade(self, trade: dict) -> Tradeline: ...
```

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_equifax_client.py` — same pattern as Experian tests.

---

### Prompt G18-F: Implement the Bureau Router with Waterfall Fallback

**File to create:** `ingestion-api/src/bureau_clients/router.py`

**Context:** In production, a primary bureau is configured per tenant. If the primary fails (network error, throttle, outage), the router falls through to secondary and tertiary bureaus. If all fail, raise `BureauPullError`. This logic must be transparent to the calling code.

**Task:**

```python
from typing import List, Optional
import logging
from .base import BureauClient
from .models import BureauProvider, BureauRequest, BureauResponse, BureauPullError

logger = logging.getLogger(__name__)

class BureauRouter:
    """
    Waterfall bureau router with configurable primary/fallback order.

    Usage:
        router = BureauRouter.from_env()
        response = await router.pull(request)
    """

    def __init__(self, clients: List[BureauClient]):
        """
        clients: ordered list; first is primary, remainder are fallbacks.
        Must contain at least one client.
        """
        if not clients:
            raise ValueError("BureauRouter requires at least one client")
        self._clients = clients

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        Try each client in order. On BureauPullError, log a warning and
        try the next client. If all fail, raise BureauPullError with a
        summary of all failures.

        Successful pulls are logged at INFO level with provider name and
        application_id (no PII beyond application_id in log lines).
        """
        errors: list[str] = []
        for client in self._clients:
            try:
                response = await client.pull(request)
                logger.info(
                    "Bureau pull succeeded: provider=%s application_id=%s",
                    client.provider.value, request.application_id,
                )
                return response
            except BureauPullError as exc:
                logger.warning(
                    "Bureau pull failed: provider=%s application_id=%s error=%s — trying next",
                    client.provider.value, request.application_id, exc,
                )
                errors.append(f"{client.provider.value}: {exc}")

        raise BureauPullError(
            f"All bureau providers failed for application_id={request.application_id}: "
            + "; ".join(errors)
        )

    @classmethod
    def from_env(cls) -> "BureauRouter":
        """
        Construct a BureauRouter from environment variables.

        BUREAU_PRIMARY   — "experian" | "transunion" | "equifax" | "mock" (default: "mock")
        BUREAU_FALLBACK  — comma-separated list of fallback providers (default: "mock")

        Examples:
            BUREAU_PRIMARY=experian BUREAU_FALLBACK=transunion,mock
            → ExperianClient → TransUnionClient → MockBureauClient

        Always append MockBureauClient as the last resort if no other client succeeds
        and BUREAU_ALLOW_MOCK_FALLBACK=true (default: true in non-production).
        """
        from .experian_client import ExperianClient
        from .transunion_client import TransUnionClient
        from .equifax_client import EquifaxClient
        from .mock_client import MockBureauClient
        import os

        _CLIENT_MAP = {
            "experian":  ExperianClient,
            "transunion": TransUnionClient,
            "equifax":   EquifaxClient,
            "mock":      MockBureauClient,
        }

        primary = os.getenv("BUREAU_PRIMARY", "mock").lower()
        fallback_str = os.getenv("BUREAU_FALLBACK", "mock")
        fallbacks = [f.strip().lower() for f in fallback_str.split(",") if f.strip()]
        allow_mock_fallback = os.getenv("BUREAU_ALLOW_MOCK_FALLBACK", "true").lower() == "true"

        providers = [primary] + fallbacks
        if allow_mock_fallback and "mock" not in providers:
            providers.append("mock")

        # Deduplicate preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for p in providers:
            if p not in seen:
                seen.add(p)
                ordered.append(p)

        clients = [_CLIENT_MAP[p]() for p in ordered if p in _CLIENT_MAP]
        return cls(clients)
```

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_router.py`
- Two clients: first raises `BureauPullError`, second returns valid response → assert second response returned
- All clients raise → assert `BureauPullError` raised with summary
- `from_env()` with `BUREAU_PRIMARY=mock` → assert single `MockBureauClient` in router
- `from_env()` with `BUREAU_PRIMARY=experian BUREAU_FALLBACK=transunion` + `BUREAU_ALLOW_MOCK_FALLBACK=true` → assert 3 clients (Experian, TransUnion, Mock)

---

### Prompt G18-G: Wire Bureau Router into Decision Pipeline

**Files to modify:**
- `ingestion-api/src/main.py`
- `decision-api/src/main.py`

**Part 1 — Replace `enrich_with_bureau_data()` in `ingestion-api/src/main.py`:**

Replace the existing `enrich_with_bureau_data()` function (lines ~666–712) and `_MOCK_BUREAU_RESPONSE` dict with:

```python
from ingestion_api.src.bureau_clients.router import BureauRouter   # or relative import
from ingestion_api.src.bureau_clients.models import BureauRequest

_BUREAU_ROUTER: Optional[BureauRouter] = None

def _get_bureau_router() -> BureauRouter:
    global _BUREAU_ROUTER
    if _BUREAU_ROUTER is None:
        _BUREAU_ROUTER = BureauRouter.from_env()
    return _BUREAU_ROUTER

async def enrich_with_bureau_data(
    application_id: str,
    applicant: dict,
) -> dict:
    """
    Enrich applicant with live bureau data via BureauRouter.
    Falls back to MockBureauClient if no production credentials are configured.
    Returns merged dict of applicant + bureau feature fields.
    """
    router = _get_bureau_router()
    req = BureauRequest(
        application_id=application_id,
        first_name=applicant.get("first_name", ""),
        last_name=applicant.get("last_name", ""),
        date_of_birth=applicant.get("date_of_birth", "1970-01-01"),
        ssn_last4=applicant.get("ssn_last4", "0000"),
        address_line1=applicant.get("address_line1", ""),
        city=applicant.get("city", ""),
        state=applicant.get("state", "CA"),
        zip_code=applicant.get("zip_code", "00000"),
        requested_amount=float(applicant.get("loan_amount", 0)),
        loan_purpose=applicant.get("loan_purpose", "personal"),
    )
    response = await router.pull(req)
    return {**applicant, **response.to_feature_dict(), "application_id": application_id}
```

**Part 2 — Wire bureau pull into `decision-api/src/main.py` `_run_pipeline()`:**

Locate `_run_pipeline()` in `decision-api/src/main.py`. Before the feature assembly step (where `features.py` features are gathered), add a live bureau pull:

```python
# GAP-18: Live bureau pull at origination time
bureau_features: dict = {}
if os.getenv("BUREAU_ENABLED", "false").lower() == "true":
    try:
        from ingestion_api.src.bureau_clients.router import BureauRouter   # noqa
        from ingestion_api.src.bureau_clients.models import BureauRequest  # noqa
        _router = BureauRouter.from_env()
        _bureau_req = BureauRequest(
            application_id=app_req.application_id,
            first_name=getattr(app_req, "first_name", ""),
            last_name=getattr(app_req, "last_name", ""),
            date_of_birth=getattr(app_req, "date_of_birth", "1970-01-01"),
            ssn_last4=getattr(app_req, "ssn_last4", "0000"),
            address_line1=getattr(app_req, "address_line1", ""),
            city=getattr(app_req, "city", ""),
            state=getattr(app_req, "borrower_state", "CA"),
            zip_code=getattr(app_req, "zip_code", "00000"),
            requested_amount=float(getattr(app_req, "loan_amount", 0)),
            loan_purpose=getattr(app_req, "loan_purpose", "personal"),
        )
        _bureau_response = await _router.pull(_bureau_req)
        bureau_features = _bureau_response.to_feature_dict()
        logger.info(
            "Bureau pull completed: provider=%s application_id=%s score=%s",
            _bureau_response.provider.value,
            app_req.application_id,
            _bureau_response.credit_score,
        )
    except Exception as _bureau_exc:
        logger.warning(
            "Bureau pull failed for application_id=%s — proceeding without live bureau data: %s",
            app_req.application_id, _bureau_exc,
        )

# Merge bureau_features into the feature dict (overrides pre-fetched values when present)
# This happens just before the model predict call — find the dict passed to model.predict()
# and spread bureau_features into it.
```

**Important constraints for Part 2:**
- `BUREAU_ENABLED=false` by default — no live bureau calls in CI/CD without explicit opt-in
- Bureau pull failure must **never** block the decision — log warning and continue with pre-fetched features
- `bureau_features` keys from `to_feature_dict()` override pre-fetched values of the same name (bureau data is authoritative)
- Log the bureau provider and score at INFO but **never** log SSN, DOB, or full name

**Acceptance tests:** `ingestion-api/tests/bureau_clients/test_wiring.py`
- Mock `BureauRouter.pull` to return a valid `BureauResponse` → assert `enrich_with_bureau_data()` returns merged dict with `credit_score` key
- Mock `BureauRouter.pull` to raise `BureauPullError` → assert `enrich_with_bureau_data()` returns original applicant dict unchanged (graceful fallback)

`decision-api/tests/test_bureau_integration.py` (create):
- With `BUREAU_ENABLED=false` (default): mock no bureau module import → assert `_run_pipeline()` completes without bureau call
- With `BUREAU_ENABLED=true`: mock `BureauRouter.pull` → assert `bureau_features` merged into model input features
- With `BUREAU_ENABLED=true` + `BureauRouter.pull` raising: assert decision is returned (no exception propagation)

---

## Summary: GAP-18 File Manifest

| Action | File |
|--------|------|
| Create | `ingestion-api/src/bureau_clients/__init__.py` |
| Create | `ingestion-api/src/bureau_clients/models.py` |
| Create | `ingestion-api/src/bureau_clients/base.py` |
| Create | `ingestion-api/src/bureau_clients/mock_client.py` |
| Create | `ingestion-api/src/bureau_clients/experian_client.py` |
| Create | `ingestion-api/src/bureau_clients/transunion_client.py` |
| Create | `ingestion-api/src/bureau_clients/equifax_client.py` |
| Create | `ingestion-api/src/bureau_clients/router.py` |
| Modify | `ingestion-api/src/main.py` |
| Modify | `decision-api/src/main.py` |
| Create | `ingestion-api/tests/bureau_clients/__init__.py` |
| Create | `ingestion-api/tests/bureau_clients/test_models.py` |
| Create | `ingestion-api/tests/bureau_clients/test_mock_client.py` |
| Create | `ingestion-api/tests/bureau_clients/test_experian_client.py` |
| Create | `ingestion-api/tests/bureau_clients/test_transunion_client.py` |
| Create | `ingestion-api/tests/bureau_clients/test_equifax_client.py` |
| Create | `ingestion-api/tests/bureau_clients/test_router.py` |
| Create | `ingestion-api/tests/bureau_clients/test_wiring.py` |
| Create | `decision-api/tests/test_bureau_integration.py` |

---
---

## Combined Sprint Plan

| Sprint | Prompts | Owner | Days |
|--------|---------|-------|------|
| Sprint 1 | G17-A, G17-B | Platform Eng | 2 |
| Sprint 1 | G18-A, G18-B | Platform Eng | 2 |
| Sprint 2 | G17-C, G17-D | Platform Eng | 2 |
| Sprint 2 | G18-C | Integrations Eng | 3 |
| Sprint 3 | G17-E, G17-F | Platform Eng | 2 |
| Sprint 3 | G18-D, G18-E | Integrations Eng | 3 |
| Sprint 4 | G18-F, G18-G | Integrations Eng | 3 |
| **Buffer / Review** | — | — | 2 |
| **Total** | **13 prompts** | | **~19 days** |

## Environment Variables Reference

### GAP-17 (OCR)
| Variable | Default | Description |
|----------|---------|-------------|
| `DOCUMENT_EVENTS_TOPIC` | `document-extraction-results` | Pub/Sub topic for extraction results |
| `OCR_DPI` | `300` | Rasterisation DPI for pdf2image |
| `OCR_LANG` | `eng` | Tesseract language pack |
| `MAX_UPLOAD_SIZE_MB` | `20` | Maximum PDF upload size |

### GAP-18 (Bureau)
| Variable | Default | Description |
|----------|---------|-------------|
| `BUREAU_ENABLED` | `false` | Master switch for live bureau pulls |
| `BUREAU_PRIMARY` | `mock` | Primary bureau provider |
| `BUREAU_FALLBACK` | `mock` | Comma-separated fallback providers |
| `BUREAU_ALLOW_MOCK_FALLBACK` | `true` | Append mock as last-resort fallback |
| `EXPERIAN_CLIENT_ID` | — | Experian OAuth2 client ID |
| `EXPERIAN_CLIENT_SECRET` | — | Experian OAuth2 client secret |
| `EXPERIAN_SUBSCRIBER_CODE` | — | Experian subscriber code |
| `EXPERIAN_ENV` | `sandbox` | `sandbox` or `production` |
| `TRANSUNION_API_KEY` | — | TransUnion API key |
| `TRANSUNION_SUBSCRIBER_CODE` | — | TransUnion subscriber code |
| `TRANSUNION_CERT_PEM` | — | PEM cert string (or Secret Manager ref) |
| `TRANSUNION_KEY_PEM` | — | PEM private key string |
| `TRANSUNION_ENV` | `sandbox` | `sandbox` or `production` |
| `EQUIFAX_CLIENT_ID` | — | Equifax OAuth2 client ID |
| `EQUIFAX_CLIENT_SECRET` | — | Equifax OAuth2 client secret |
| `EQUIFAX_CUSTOMER_NUMBER` | — | Equifax customer number header |
| `EQUIFAX_ENV` | `sandbox` | `sandbox` or `production` |

## Definition of Done

GAP-17 is **closed** when:
- [ ] `POST /documents/{application_id}` endpoint is live and returns `DocumentExtractionResult`
- [ ] Pay stub, bank statement, and tax return fields are correctly extracted from sample PDFs
- [ ] All 6 new test files pass (`pytest ingestion-api/tests/`)
- [ ] Feature dict from OCR output is consumable by `feature_pipeline/features.py`

GAP-18 is **closed** when:
- [ ] `BureauRouter.from_env()` returns a working router with mock fallback in all environments
- [ ] With `BUREAU_ENABLED=true` and `BUREAU_PRIMARY=experian`, live Experian sandbox calls succeed in a staging environment
- [ ] Bureau pull failure never blocks a credit decision
- [ ] All 8 new test files pass (`pytest ingestion-api/tests/bureau_clients/ decision-api/tests/test_bureau_integration.py`)
- [ ] `credit_score` from the live bureau pull overrides the pre-fetched value in `_run_pipeline()`
