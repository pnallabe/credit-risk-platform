# Implementation Plan: Gap Closure — Priority 1 & 2
## Integrated Lending Operating Layer (ILOL) — credit-risk-platform

**Version:** 1.0.0
**Date:** April 7, 2026
**Scope:** Priority 1 (Cryptographic Hash Chain on Audit Log) and Priority 2 (Reg B Adverse Action Notice Generation)
**Reference:** PRD v1.0.0 §4.1.1 GNRI-007, §4.4.2, §8.1

---

## Overview

This document provides a sequential series of coding prompts, each self-contained and implementation-ready. Each prompt specifies:
- The **exact files** to create or modify
- The **interfaces** to implement against existing code
- The **acceptance tests** that determine "done"
- All **constraints** from the PRD and existing architecture

Work the prompts in order. Each prompt builds on the previous one. Do not skip ahead.

---

## PRIORITY 1: Cryptographic Hash Chain on Audit Log

### Background

[audit/logger.py](../audit/logger.py) currently writes decision records to a `audit_log` SQLite/PostgreSQL table but has no cryptographic tamper protection. The PRD (GNRI-007) requires an append-only log with a cryptographic hash chain: each record must commit to the `log_id` and `logged_at` of the previous record, making retroactive modification detectable.

The existing `log_decision()` and `log_portfolio_action()` functions and their callers in [decision-api/src/main.py](../decision-api/src/main.py) must not break. The hash chain is additive — extend the schema and the write path without changing any existing function signatures.

---

### Prompt P1-A: Implement the Hash Chain Schema Migration

**File to modify:** `audit/logger.py`

**Context:** The current `_CREATE_AUDIT_TABLE` DDL (lines 75–103 of `audit/logger.py`) defines `audit_log` with no integrity columns. You need to add three new columns and a migration function that can be called at startup to add them to existing tables without data loss.

**Task:**

Add the following three columns to the `audit_log` table DDL in `_CREATE_AUDIT_TABLE`:

```
record_hash       TEXT,   -- SHA-256(canonical_payload) for this row
previous_hash     TEXT,   -- record_hash of the previous row in insertion order (NULL for row 1)
hash_algorithm    TEXT NOT NULL DEFAULT 'sha256'
```

Then implement a function `async def migrate_audit_schema(db_url: str) -> None` that:
1. Uses SQLAlchemy `text()` to check if each column already exists in `audit_log` (query `pragma_table_info` for SQLite, `information_schema.columns` for PostgreSQL, detected by the `db_url` scheme prefix)
2. Issues `ALTER TABLE audit_log ADD COLUMN <name> <type>` for each missing column
3. Is idempotent — calling it twice must not raise

Also add the same three columns and the same `migrate_audit_schema` logic for `portfolio_audit_log`.

**Constraints:**
- Must work for both `sqlite+aiosqlite://` and `postgresql+asyncpg://` connection strings
- Must not alter or rename any existing columns
- Migration must run in a single database transaction per table
- All new columns default to `NULL` for existing rows (backfill is handled in Prompt P1-C)

**Acceptance test file:** `audit/tests/test_hash_chain_migration.py`

Write tests that:
1. Create a fresh in-memory SQLite DB, call `migrate_audit_schema`, and assert all three columns exist
2. Call `migrate_audit_schema` a second time and assert no errors (idempotency)
3. Write one row with the old `log_decision()` call, then run `migrate_audit_schema` on the same DB and assert the existing row is untouched

---

### Prompt P1-B: Implement the Hash Chain Writer

**File to modify:** `audit/logger.py`

**Context:** After the schema migration exists, `log_decision()` must compute and store `record_hash` and `previous_hash` for every new row it inserts.

**Task:**

Add a private async function `_compute_chain_hash(conn, log_id: str, logged_at: str, canonical_payload: str, db_url: str) -> tuple[str, str | None]` that:

1. Queries `audit_log` for the `record_hash` of the most recently inserted row for the same `tenant_id`, ordered by `logged_at DESC, log_id ASC`, returning `None` if this is the first row for that tenant
2. Computes `record_hash = sha256(previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical_payload)` where `canonical_payload` is a deterministic JSON-serialized string of `{decision_output, risk_score, fraud_score, reason_codes}` with keys sorted alphabetically
3. Returns `(record_hash, previous_hash)` as a tuple

Where `previous_hash` is `""` (empty string, not `NULL`) when this is the first row, so the hash chain is fully computable from row 1.

Modify `log_decision()` to:
1. Build `canonical_payload` from the params dict before the INSERT
2. Call `_compute_chain_hash()` inside the same `conn.begin()` block (so no other row can be inserted between the SELECT and INSERT)
3. Add `record_hash` and `previous_hash` to the `_INSERT_AUDIT` params

Make the same change to `log_portfolio_action()` — build `canonical_payload` from `{recommended_action, scenario_weighted_delta, model_version_portfolio, policy_version}`.

**Constraints:**
- The hash chain query and the INSERT must be in the same transaction (no `await conn.commit()` between them)
- `canonical_payload` must be deterministic: use `json.dumps(d, sort_keys=True, separators=(',', ':'))` — no spaces, no newlines
- If the three hash columns do not exist yet (old schema), the function must gracefully skip hash writes rather than raise (to support rolling deploys)
- `_sha256()` already exists in `audit/logger.py` — reuse it

**Acceptance tests:** Add to `audit/tests/test_hash_chain_migration.py`:
1. Insert 3 rows via `log_decision()` and assert `previous_hash` of row N equals `record_hash` of row N-1
2. Assert row 1 has `previous_hash == ""`
3. Assert `record_hash` is a 64-character hex string for every row

---

### Prompt P1-C: Implement the Hash Chain Verifier

**File to create:** `audit/chain_verifier.py`

**Context:** The PRD requires tamper detection. The verifier is used by the compliance export workflow (Prompt P2-D) and by auditors who download a decision log for a given date range.

**Task:**

Create `audit/chain_verifier.py` with a single public async function:

```python
async def verify_chain(
    db_url: str,
    tenant_id: str,
    from_logged_at: str | None = None,    # ISO-8601 UTC; None = beginning of log
    to_logged_at: str | None = None,      # ISO-8601 UTC; None = now
    table: Literal["audit_log", "portfolio_audit_log"] = "audit_log",
) -> ChainVerificationResult:
    ...
```

Where `ChainVerificationResult` is a frozen `dataclass` with fields:
- `verified: bool` — `True` if every row's `record_hash` recomputes correctly and every `previous_hash` matches the prior row's `record_hash`
- `rows_checked: int`
- `first_tampered_log_id: str | None` — log_id of the first row that fails verification
- `first_tampered_at: str | None` — `logged_at` of that row
- `gap_detected: bool` — `True` if any row has a `previous_hash` that does not match any `record_hash` in the result set (indicates a deleted row)

The function must:
1. Query `audit_log` (or `portfolio_audit_log`) for all rows WHERE `tenant_id = :tenant_id` (and optionally within the date window), ordered by `logged_at ASC, log_id ASC`
2. For each row, recompute `record_hash` from `previous_hash`, `log_id`, `logged_at`, and the canonical fields using the exact same algorithm as `_compute_chain_hash()`
3. Compare recomputed hash to the stored `record_hash`
4. Return early on first mismatch, populating `first_tampered_log_id`
5. If any row's `previous_hash` does not equal the prior row's `record_hash`, set `gap_detected = True`
6. Skip verification for rows where `record_hash IS NULL` (pre-migration rows) — count them but do not fail on them

Also implement a CLI entry point:
```
python -m audit.chain_verifier --tenant-id <id> --db-url <url> --from 2026-01-01 --to 2026-03-31
```
that exits with code `0` on success and `1` on failure, printing a human-readable summary.

**Acceptance tests:** `audit/tests/test_chain_verifier.py`
1. Insert 5 rows, verify → `verified=True, rows_checked=5`
2. Insert 5 rows, manually corrupt `record_hash` of row 3, verify → `verified=False, first_tampered_log_id=<row3 id>`
3. Insert 5 rows, DELETE row 3, verify → `gap_detected=True`
4. Rows with `record_hash IS NULL` are skipped without failing

---

### Prompt P1-D: Expose Chain Verification in the Audit API Endpoint

**File to modify:** `decision-api/src/main.py`

**Context:** The audit retrieval endpoint `GET /v1/decisions/{id}/audit` (line ~660 in `main.py`) currently calls `get_audit_record()` and returns the raw row. The PRD (GNRI-008) requires that any audit record returned through the API includes tamper evidence.

**Task:**

Modify `GET /v1/decisions/{id}/audit` to:
1. Call `get_audit_record(application_id, db_url, tenant_id)` as before
2. Also call `verify_chain(db_url, tenant_id, from_logged_at=record["logged_at"], to_logged_at=record["logged_at"])` from `audit.chain_verifier`
3. Add a `chain_integrity` field to the response:

```python
"chain_integrity": {
    "verified": bool,
    "record_hash": str | None,
    "previous_hash": str | None,
    "hash_algorithm": str | None,
}
```

Add a new standalone endpoint:

```
POST /v1/audit/verify-chain
```

Request body:
```json
{
  "from_logged_at": "2026-01-01T00:00:00Z",   // optional
  "to_logged_at": "2026-03-31T23:59:59Z",      // optional
  "table": "audit_log"                          // or "portfolio_audit_log"
}
```

Response:
```json
{
  "tenant_id": "...",
  "verified": true,
  "rows_checked": 47821,
  "first_tampered_log_id": null,
  "gap_detected": false,
  "verified_at": "2026-04-07T10:00:00Z"
}
```

**Constraints:**
- Endpoint requires `Bearer` JWT (use existing `verify_bearer` dependency)
- Chain verification is tenant-scoped — a tenant can only verify their own log
- Verification of large date ranges should be async (respond with `202 Accepted` + a `job_id` if `rows_checked` would exceed 100K — detected by a COUNT query before proceeding)
- Tag the endpoint as `["Audit & Compliance"]` in FastAPI

**Acceptance tests:** `decision-api/tests/test_chain_verification_endpoint.py`
1. `POST /v1/audit/verify-chain` with valid JWT returns `200` and `verified: true` after 3 decisions inserted
2. After manually corrupting a row in test DB, endpoint returns `verified: false`
3. Missing JWT → `401`

---

### Prompt P1-E: Integrate Chain Migration into Application Startup

**File to modify:** `decision-api/src/main.py`

**Context:** The `startup_event()` async function (line ~188) currently calls `_load_models()`. The hash chain migration must run at startup so every deployment automatically upgrades existing databases.

**Task:**

In `startup_event()`, add the following after `_load_models()`:

```python
from audit.logger import migrate_audit_schema
await migrate_audit_schema(DB_URL)
logger.info("Audit schema migration complete (hash chain columns ensured)")
```

Also add a health check field to `GET /v1/health`:

```json
{
  "audit_chain_enabled": true,
  "audit_schema_version": "v2-hash-chain"
}
```

Where `audit_chain_enabled` is `True` when the `record_hash` column exists (detect via a schema introspection query in a new `async def audit_schema_version(db_url: str) -> str` helper in `audit/logger.py`).

**Constraints:**
- If `migrate_audit_schema` fails, log the error but do NOT prevent startup — old schema still works
- `audit_schema_version` must not raise; return `"v1-no-chain"` on any error

---

## PRIORITY 2: Reg B Adverse Action Notice Generation

### Background

The PRD (§4.4.2) requires auto-generation of Reg B-compliant adverse action notices for every declined application. This covers CFPB Model Forms C-1 through C-5, delivery channel tracking, 30-day deadline monitoring, and multi-brand template management.

Currently there is no `adverse_action` module anywhere in `credit-risk-platform`. The `reporting/hmda_lar.py` file maps denial codes for HMDA LAR export but does not generate consumer notices. The `explainability/shap_explainer.py` generates human-readable factor text — that output must feed the notice.

---

### Prompt P2-A: Create the Adverse Action Notice Data Model and FCRA Reason Code Mapping

**File to create:** `compliance/adverse_action.py`

**Context:** Every declined credit application triggers a Reg B obligation. The notice must identify: (1) the creditor, (2) the action taken, (3) the date, (4) the principal reason(s) — up to 4 — using either OCC-approved standard codes or a disclosure that the applicant can request the reasons. The existing `REASON_CODE_DESCRIPTIONS` dict in `decision_engine/engine.py` has 5 codes. You need a complete mapping to Reg B-compliant consumer language and CFPB model form fields.

**Task:**

Create `compliance/adverse_action.py` with:

1. A `REG_B_REASON_CODES` dict mapping every internal reason code to a consumer-facing string:

```python
REG_B_REASON_CODES: dict[str, str] = {
    # existing codes from decision_engine/engine.py
    "AA01": "High probability of default based on credit history",
    "AA02": "Unable to verify information provided",
    "AA03": "Insufficient credit history",
    "AA04": "Debt-to-income ratio too high",
    "AA05": "Application requires additional review",
    # SHAP-derived factor codes (mapped from shap_explainer feature names)
    "SHAP_PAYMENT_HISTORY":   "Delinquent past or present credit obligations with others",
    "SHAP_UTILIZATION":       "Proportion of balances to credit limits too high",
    "SHAP_DTI":               "Amount of monthly debt payments in relation to monthly income",
    "SHAP_ACCOUNT_AGE":       "Length of time accounts have been established",
    "SHAP_NUM_DEROG":         "Number of derogatory public records",
    "SHAP_EMPLOYMENT":        "Unable to verify employment information",
    "SHAP_INCOME":            "Income insufficient for amount of credit requested",
    "SHAP_CREDIT_SCORE":      "Credit score below minimum threshold",
    # Compliance-gate derived codes
    "COMP_MLA":               "Military Lending Act — interest rate cap exceeded",
    "COMP_STATE_APR":         "State usury limit — proposed rate exceeds state maximum",
    "COMP_FRAUD":             "Unable to verify identity",
}
```

2. A frozen `dataclass AdverseActionNotice` with fields:

```python
@dataclass(frozen=True)
class AdverseActionNotice:
    notice_id: str              # UUID
    application_id: str
    tenant_id: str
    applicant_name: str
    creditor_name: str          # from tenant config
    action_taken: str           # "Application Denied" | "Terms Different from Those Applied For"
    action_date: str            # ISO-8601 date
    deadline_date: str          # action_date + 30 calendar days
    reason_codes: list[str]     # 1–4 REG_B_REASON_CODES keys
    reason_texts: list[str]     # consumer-facing strings from REG_B_REASON_CODES
    form_type: str              # "C-1" | "C-2" | "C-3" | "C-4" | "C-5"
    credit_score_used: int | None
    credit_score_range_low: int | None       # e.g. 300
    credit_score_range_high: int | None      # e.g. 850
    credit_score_model_name: str | None      # e.g. "FICO Score 8"
    bureau_name: str | None                  # e.g. "Experian"
    generated_at: str           # UTC ISO-8601 timestamp
    delivery_channel: str | None = None      # "email" | "mail" | "portal" | None
    delivered_at: str | None = None
    delivery_status: str = "PENDING"         # "PENDING" | "SENT" | "DELIVERED" | "FAILED"
```

3. A function `map_shap_factors_to_reg_b_codes(shap_top_negative: list[dict]) -> list[str]` that:
   - Takes the `top_negative_factors` list from `ExplanationResult` (each dict has `feature`, `shap_value`, `direction`)
   - Maps the `feature` name to a `SHAP_*` code using a best-effort mapping dict
   - Falls back to `"AA01"` if no mapping exists
   - Returns at most 4 codes, ordered by `|shap_value|` descending

4. A function `select_form_type(context: str) -> str` that selects the CFPB model form:
   - `"C-1"` — credit denial (most common; use as default)
   - `"C-2"` — credit approval with different terms
   - `"C-3"` — incomplete application
   - `"C-4"` — employment denial (not applicable for credit)
   - `"C-5"` — insurance denial (not applicable)
   - Accept `context: Literal["denial", "counter_offer", "incomplete"]` and return the correct form

**Acceptance tests:** `compliance/tests/test_adverse_action.py`
1. `map_shap_factors_to_reg_b_codes([{"feature": "debt_to_income_ratio", ...}, ...])` returns `["SHAP_DTI", ...]`
2. `AdverseActionNotice` is constructable and all fields are present
3. `select_form_type("denial")` returns `"C-1"`

---

### Prompt P2-B: Create the Notice Generator — Plain Text and JSON

**File to create:** `compliance/adverse_action_generator.py`

**Context:** The `AdverseActionNotice` dataclass defines the data model. This module renders it as (a) the canonical JSON record stored in the audit log, and (b) a plain-text notice body matching CFPB Model Form C-1 language exactly. PDF rendering is handled in Prompt P2-C.

**Task:**

Create `compliance/adverse_action_generator.py` with:

1. A function `generate_notice(application_id: str, tenant_id: str, decision_result: Any, explanation_result: Any, tenant_config: dict) -> AdverseActionNotice` that:
   - Accepts a `DecisionResult` (from `decision_engine/engine.py`) or a plain dict with `decision`, `reason_codes`, `recommended_rate`
   - Accepts an `ExplanationResult` (from `explainability/shap_explainer.py`) or `None`
   - Pulls `creditor_name` from `tenant_config.get("creditor_name", "The Creditor")`
   - Pulls `credit_score_model_name` and `bureau_name` from `tenant_config.get("bureau_config", {})`
   - Only generates a notice if `decision_result.decision == "REJECT"` — raises `ValueError("decision must be REJECT to generate adverse action notice")` otherwise
   - Combines `decision_result.reason_codes` (the FCRA codes already computed) with SHAP-mapped codes if `explanation_result` is provided, deduplicates, and truncates to 4
   - Sets `deadline_date` to `action_date + 30 calendar days` using `datetime.date`
   - Sets `form_type` using `select_form_type("denial")`

2. A function `render_c1_text(notice: AdverseActionNotice) -> str` that returns a plain-text string matching the CFPB Model Form C-1 structure:

```
NOTICE OF ACTION TAKEN AND STATEMENT OF REASONS

Creditor: {creditor_name}
Date: {action_date}
Applicant: {applicant_name}
Application ID: {application_id}

DESCRIPTION OF ACCOUNT, TRANSACTION, OR REQUESTED CREDIT:
{product description from notice metadata}

DESCRIPTION OF ACTION TAKEN:
{action_taken}

STATEMENT OF REASONS:
1. {reason_texts[0]}
2. {reason_texts[1]}   <- included only if present
3. {reason_texts[2]}   <- included only if present
4. {reason_texts[3]}   <- included only if present

DISCLOSURE OF USE OF INFORMATION FROM AN OUTSIDE SOURCE:
{conditional block: if credit_score_used is not None}
Our credit decision was based in whole or in part on information obtained
from a consumer reporting agency. The agency that provided the information
is: {bureau_name}. The credit score used in making this credit decision was
{credit_score_used}. Scores range from a low of {credit_score_range_low} to
a high of {credit_score_range_high} under the scoring model: {credit_score_model_name}.
{end conditional}

You have a right to obtain a free copy of your consumer report from the
consumer reporting agency listed above for a period of 60 days from the date
of this notice. If you find information in your report that you believe is
inaccurate or incomplete, you have the right to dispute the matter with the
reporting agency.

You have a right to know whether information in your file at a consumer
reporting agency was used in connection with any credit transaction initiated
or reviewed by you. You may contact the consumer reporting agency at any time
to see your file and to have any inaccurate information corrected.

Please contact {creditor_name} if you have questions about this notice.
```

3. A function `notice_to_dict(notice: AdverseActionNotice) -> dict` that returns the JSON-serializable representation for audit log storage. Use `dataclasses.asdict()`.

**Constraints:**
- All date arithmetic must use `datetime.date`, not string manipulation
- `render_c1_text()` must produce deterministic output (no timestamps in the body)
- The function must not import `reportlab`, `fpdf`, or any PDF library — PDF rendering is in the next prompt
- `generate_notice()` must import lazily from `explainability.shap_explainer` to avoid circular imports

**Acceptance tests:** `compliance/tests/test_adverse_action_generator.py`
1. `generate_notice()` with a REJECT result and an `ExplanationResult` produces an `AdverseActionNotice` with 1–4 reason codes
2. `generate_notice()` with an APPROVE result raises `ValueError`
3. `render_c1_text()` contains the applicant name, creditor name, and all reason texts
4. `deadline_date` is exactly 30 days after `action_date`
5. When `credit_score_used is None`, the credit score disclosure block is absent from the rendered text

---

### Prompt P2-C: Create the PDF Renderer for CFPB Model Form C-1

**File to create:** `compliance/adverse_action_pdf.py`

**Context:** Reg B requires the notice to be delivered to the applicant. The delivery channel tracking in `AdverseActionNotice` supports email and mail. For mail delivery, a PDF must be generated. For email delivery, the PDF is attached. This prompt uses `reportlab` (already a common dependency in compliance workflows).

**Task:**

Create `compliance/adverse_action_pdf.py` with a single public function:

```python
def render_notice_pdf(
    notice: AdverseActionNotice,
    output_path: str | Path | None = None,
) -> bytes:
    ...
```

That:
1. Imports `reportlab.lib`, `reportlab.platypus`, `reportlab.lib.styles` — all within the function body (lazy import), raising `ImportError` with install instructions if `reportlab` is unavailable
2. Renders the notice as a single-page PDF using the text from `render_c1_text(notice)` with:
   - Header: `"NOTICE OF ACTION TAKEN AND STATEMENT OF REASONS"` in 14pt bold
   - Body: 11pt regular, 1-inch margins, single-spaced
   - Footer: `"Notice ID: {notice.notice_id} | Generated: {notice.generated_at}"` in 8pt gray
3. If `output_path` is provided, writes the PDF bytes to that path
4. Always returns the PDF as `bytes` regardless of `output_path`

Also add the following to `render_notice_pdf`:
- Watermark the PDF `"COMPLIANCE COPY"` in light gray diagonal text if `os.getenv("AA_NOTICE_WATERMARK") == "1"` — used for auditor exports vs. customer copies

**Constraints:**
- Function must be importable even when `reportlab` is not installed (import inside function, return helpful `ImportError`)
- Output must be a valid PDF (starts with `%PDF-`)
- The function must not write to `stdout` or log at `INFO` level — only `DEBUG`

**Acceptance tests:** `compliance/tests/test_adverse_action_pdf.py`
1. `render_notice_pdf(notice)` returns bytes starting with `b"%PDF-"`
2. PDF contains the `notice_id` string (basic content check via byte scan)
3. With `AA_NOTICE_WATERMARK=1`, PDF is larger than without (watermark adds content)
4. `ImportError` is raised with a clear message when `reportlab` is not installed (mock the import)

---

### Prompt P2-D: Persist Notices to the Audit Log and Implement Delivery Tracking

**File to create:** `compliance/adverse_action_store.py`

**Context:** Once a notice is generated, it must be persisted as part of the immutable audit trail and its delivery status must be tracked to satisfy the 30-day Reg B delivery deadline. The existing `audit/logger.py` must gain an `adverse_action_log` table (additive schema change — do not modify existing tables).

**Task:**

1. Add to `audit/logger.py` a new DDL constant `_CREATE_ADVERSE_ACTION_TABLE`:

```sql
CREATE TABLE IF NOT EXISTS adverse_action_log (
    notice_id           TEXT PRIMARY KEY,
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    action_date         TEXT NOT NULL,
    deadline_date       TEXT NOT NULL,
    reason_codes        TEXT NOT NULL,  -- JSON array
    form_type           TEXT NOT NULL,
    credit_score_used   INTEGER,
    bureau_name         TEXT,
    generated_at        TEXT NOT NULL,
    delivery_channel    TEXT,
    delivered_at        TEXT,
    delivery_status     TEXT NOT NULL DEFAULT 'PENDING',
    notice_hash         TEXT,   -- SHA-256 of the rendered notice text (tamper evidence)
    record_hash         TEXT,
    previous_hash       TEXT
);
CREATE INDEX IF NOT EXISTS idx_aa_tenant_app  ON adverse_action_log(tenant_id, application_id);
CREATE INDEX IF NOT EXISTS idx_aa_deadline    ON adverse_action_log(deadline_date);
CREATE INDEX IF NOT EXISTS idx_aa_status      ON adverse_action_log(delivery_status);
```

2. Create `compliance/adverse_action_store.py` with:

```python
async def save_notice(
    notice: AdverseActionNotice,
    notice_text: str,       # from render_c1_text(notice) — hashed for tamper evidence
    db_url: str,
) -> str:                   # returns notice_id
    ...

async def mark_delivered(
    notice_id: str,
    delivery_channel: str,
    delivered_at: str,
    db_url: str,
    tenant_id: str,
) -> None:
    ...

async def get_pending_deadline_notices(
    db_url: str,
    tenant_id: str,
    warn_days_before: int = 5,  # alert if deadline is within N days
) -> list[dict]:
    """Return notices where deadline_date <= today + warn_days_before and delivery_status = 'PENDING'."""
    ...

async def get_notice(
    notice_id: str,
    db_url: str,
    tenant_id: str,
) -> dict | None:
    ...

async def list_notices(
    db_url: str,
    tenant_id: str,
    from_date: str | None = None,
    to_date: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 100,
) -> tuple[list[dict], int]:   # (records, total_count)
    ...
```

3. `save_notice()` must:
   - Compute `notice_hash = sha256(notice_text)` using `audit.logger._sha256()`
   - Write `record_hash` and `previous_hash` for `adverse_action_log` using the same chain logic as `audit/logger.py` (extract the shared `_compute_chain_hash` logic into `audit/logger.py` as a module-level helper, not a private function, so `adverse_action_store.py` can import it)
   - Raise `ValueError` if a notice with the same `notice_id` already exists

4. `mark_delivered()` must:
   - Only update `delivery_channel`, `delivered_at`, `delivery_status = 'DELIVERED'`
   - Raise `ValueError` if the `notice_id` does not belong to `tenant_id`

**Acceptance tests:** `compliance/tests/test_adverse_action_store.py`
1. `save_notice()` inserts a row and returns the `notice_id`
2. `mark_delivered()` updates status; `get_notice()` reflects new status
3. `get_pending_deadline_notices()` returns a notice with a deadline 3 days from now
4. Calling `save_notice()` twice with the same `notice_id` raises `ValueError`
5. Hash chain is intact across 3 saved notices (reuse `chain_verifier.verify_chain`)

---

### Prompt P2-E: Integrate Adverse Action Generation into the Decision Pipeline

**File to modify:** `decision-api/src/main.py`

**Context:** Currently `_run_pipeline()` (line ~395) logs the decision to the audit log and returns a `DecisionResponse`. REJECT decisions must also: generate an adverse action notice, save it to `adverse_action_log`, and include the `notice_id` in the response.

**Task:**

1. In `_run_pipeline()`, after the audit log write (the `audit_log_id = await log_decision(...)` call), add:

```python
notice_id: str | None = None
if decision_result.decision == DECISION_REJECT:
    from compliance.adverse_action_generator import generate_notice, render_c1_text
    from compliance.adverse_action_store import save_notice

    try:
        aa_notice = generate_notice(
            application_id=app_req.application_id,
            tenant_id=tenant_id,
            decision_result=decision_result,
            explanation_result=shap_result if explanation_factors else None,
            tenant_config=tenant_cfg,
        )
        notice_text = render_c1_text(aa_notice)
        notice_id = await save_notice(aa_notice, notice_text, DB_URL)
        logger.info("Adverse action notice generated: notice_id=%s", notice_id)
    except Exception as exc:
        logger.error("Adverse action notice generation failed: %s", exc)
        # Do NOT raise — notice failure must not block the decision response
```

2. Add `notice_id: str | None` to `DecisionResponse` Pydantic model (defaults to `None` for APPROVE/MANUAL_REVIEW).

3. Add a new endpoint `GET /v1/adverse-actions/{notice_id}` that:
   - Calls `get_notice(notice_id, DB_URL, tenant_id)`
   - Returns `404` if not found or wrong tenant
   - Tags: `["Adverse Actions"]`

4. Add a new endpoint `GET /v1/adverse-actions` that:
   - Accepts query params: `from`, `to`, `status`, `page`, `per_page`
   - Calls `list_notices(DB_URL, tenant_id, from_date, to_date, status, page, per_page)`
   - Returns `{"notices": [...], "total": N, "page": N, "per_page": N}`
   - Tags: `["Adverse Actions"]`

5. Add a new endpoint `POST /v1/adverse-actions/{notice_id}/deliver` that:
   - Request body: `{"delivery_channel": "email" | "mail" | "portal", "delivered_at": "ISO-8601"}`
   - Calls `mark_delivered()`
   - Returns `{"notice_id": ..., "delivery_status": "DELIVERED"}`
   - Tags: `["Adverse Actions"]`

6. Add `GET /v1/adverse-actions/pending-deadlines` that:
   - Calls `get_pending_deadline_notices(DB_URL, tenant_id, warn_days_before=5)`
   - Returns the list with a count
   - Tags: `["Adverse Actions"]`

**Constraints:**
- Adverse action generation must NOT be in the synchronous critical path for APPROVE decisions — only trigger for `DECISION_REJECT`
- All endpoints require Bearer JWT
- `notice_id` in `DecisionResponse` is `None` for non-reject decisions — do not break existing API consumers
- Do not change the `DecisionResponse` field ordering (append `notice_id` at end)

**Acceptance tests:** `decision-api/tests/test_adverse_action_endpoints.py`
1. `POST /v1/decisions` with a low credit score → `decision=REJECT`, response includes `notice_id` (not null)
2. `GET /v1/adverse-actions/{notice_id}` returns the notice with correct reason codes
3. `POST /v1/adverse-actions/{notice_id}/deliver` with `delivery_channel=email` → `delivery_status=DELIVERED`
4. `GET /v1/adverse-actions/pending-deadlines` returns notices with `deadline_date` within 5 days
5. `POST /v1/decisions` with high credit score → `decision=APPROVE`, `notice_id=null`
6. REJECT in wrong tenant → `GET /v1/adverse-actions/{notice_id}` returns `404`

---

### Prompt P2-F: Add Deadline Monitoring Alert to the Alert Router

**File to modify:** `monitoring/alert_router.py`

**Context:** `monitoring/alert_router.py` has `SlackWebhookChannel` and `EmailChannel`. The PRD requires a 30-day delivery deadline alert. Any notice that is `PENDING` with fewer than 5 days until `deadline_date` must trigger an alert.

**Task:**

Add a function to `monitoring/alert_router.py`:

```python
async def check_adverse_action_deadlines(
    db_url: str,
    tenant_id: str,
    router: "AlertRouter",
    warn_days_before: int = 5,
) -> int:
    """
    Query adverse_action_log for PENDING notices approaching deadline.
    Fires a CRITICAL alert via router for each.
    Returns the count of notices alerted.
    """
    ...
```

That:
1. Calls `get_pending_deadline_notices(db_url, tenant_id, warn_days_before)` from `compliance.adverse_action_store`
2. For each notice, calls `router.send_alert(severity="CRITICAL", title="Adverse Action Deadline Approaching", body=f"Notice {notice_id} for application {application_id} must be delivered by {deadline_date}. Status: PENDING.")` using the existing `AlertRouter` class
3. Returns the count of alerted notices

Also add an `async def send_alert(self, severity: str, title: str, body: str) -> None` method to the existing `AlertRouter` class that broadcasts to all configured channels.

Finally, create `scripts/check_adverse_action_deadlines.py` as a standalone script:
```python
"""
Run as a scheduled job (cron / Cloud Scheduler) daily.
Usage: python scripts/check_adverse_action_deadlines.py
Reads DB_URL and TENANT_IDS (comma-separated) from env.
"""
```

The script should:
- Load `DB_URL` from environment
- Load `TENANT_IDS` as a comma-separated list from environment
- For each tenant, call `check_adverse_action_deadlines()`
- Exit with code `1` if any alerts were fired (for CI/CD monitoring)

**Constraints:**
- `check_adverse_action_deadlines` must be async — use `asyncio.run()` in the script entry point
- Import from `compliance.adverse_action_store` must be lazy (inside the function) to avoid circular imports
- The function must handle the case where `adverse_action_log` table does not exist (catch `Exception`, log warning, return 0)

**Acceptance tests:** `monitoring/tests/test_aa_deadline_alert.py`
1. Insert a notice with `deadline_date = today + 3, status = PENDING` → `check_adverse_action_deadlines` returns 1 and fires 1 alert
2. Insert a notice with `deadline_date = today + 10, status = PENDING` → returns 0 (not yet in warning window)
3. Insert a notice with `deadline_date = today + 3, status = DELIVERED` → returns 0 (already delivered)
4. Empty `adverse_action_log` table → returns 0

---

### Prompt P2-G: Expose Adverse Action Summary in the Exam Packet Skeleton

**File to create:** `compliance/exam_packet_builder.py`

**Context:** The full Exam Packet Generator is a Phase 1 deliverable tracked in the gap list. This prompt creates the skeleton builder and implements the Adverse Action Summary component specifically (since we now have the data for it). The other components (policy history, decision log summary, etc.) are stubs that will be filled in subsequent sprints.

**Task:**

Create `compliance/exam_packet_builder.py` with:

1. A `dataclass ExamPacketSpec`:
```python
@dataclass
class ExamPacketSpec:
    tenant_id: str
    from_date: str    # ISO-8601 date
    to_date: str      # ISO-8601 date
    components: list[str]  # e.g. ["adverse_actions", "policy_history", "decision_log"]
    format: Literal["json", "pdf_zip"]
    template: str = "OCC_EXAMINATION"
```

2. A `dataclass ExamPacketComponent`:
```python
@dataclass
class ExamPacketComponent:
    name: str
    status: Literal["complete", "stub", "error"]
    data: dict | None
    error_message: str | None = None
```

3. A `dataclass ExamPacket`:
```python
@dataclass
class ExamPacket:
    packet_id: str
    tenant_id: str
    generated_at: str
    from_date: str
    to_date: str
    template: str
    components: list[ExamPacketComponent]

    def to_dict(self) -> dict: ...
    def summary_text(self) -> str: ...  # human-readable summary of what's included
```

4. An async function `build_adverse_action_component(spec: ExamPacketSpec, db_url: str) -> ExamPacketComponent` that:
   - Calls `list_notices(db_url, tenant_id, from_date, to_date, page=1, per_page=100000)` (use total count, paginate internally if > 1000)
   - Computes:
     - `total_notices`: total count
     - `delivered_count`: count where `delivery_status == "DELIVERED"`
     - `pending_count`: count where `delivery_status == "PENDING"`
     - `failed_count`: count where `delivery_status == "FAILED"`
     - `delivery_compliance_rate`: `delivered_count / total_notices * 100` (0 if total=0)
     - `overdue_count`: count where `delivery_status == "PENDING"` and `deadline_date < today`
     - `reason_code_distribution`: dict of `{reason_code: count}` across all notices
   - Returns the component with `status="complete"` and all metrics in `data`

5. An async function `build_exam_packet(spec: ExamPacketSpec, db_url: str) -> ExamPacket` that:
   - Calls `build_adverse_action_component` if `"adverse_actions"` is in `spec.components`
   - For all other components in `spec.components`, returns a stub `ExamPacketComponent(status="stub", data=None)`
   - Assembles and returns an `ExamPacket`

6. A CLI entry point:
```
python -m compliance.exam_packet_builder \
    --tenant-id <id> \
    --from 2026-01-01 \
    --to 2026-03-31 \
    --components adverse_actions \
    --format json
```
That prints the `ExamPacket.to_dict()` as indented JSON.

**Acceptance tests:** `compliance/tests/test_exam_packet_builder.py`
1. With 10 notices (8 DELIVERED, 2 PENDING), `build_adverse_action_component` returns `delivery_compliance_rate=80.0`, `overdue_count=0`
2. With 2 PENDING notices past `deadline_date`, `overdue_count=2`
3. `build_exam_packet` with `components=["adverse_actions", "policy_history"]` returns a packet with 1 `complete` and 1 `stub` component
4. `ExamPacket.summary_text()` includes the component names and statuses

---

## Integration Checklist

After all prompts are completed, run the following end-to-end validation:

```bash
# From project root
cd /Users/swarnabale/Documents/My Projects/credit-risk-platform

# P1 — Hash chain
python -m pytest audit/tests/test_hash_chain_migration.py -v
python -m pytest audit/tests/test_chain_verifier.py -v
python -m pytest decision-api/tests/test_chain_verification_endpoint.py -v

# P2 — Adverse action
python -m pytest compliance/tests/test_adverse_action.py -v
python -m pytest compliance/tests/test_adverse_action_generator.py -v
python -m pytest compliance/tests/test_adverse_action_pdf.py -v
python -m pytest compliance/tests/test_adverse_action_store.py -v
python -m pytest decision-api/tests/test_adverse_action_endpoints.py -v
python -m pytest monitoring/tests/test_aa_deadline_alert.py -v
python -m pytest compliance/tests/test_exam_packet_builder.py -v

# Regression — existing tests must still pass
python -m pytest audit/ decision-api/ compliance/ monitoring/ -v --ignore=audit/tests/test_chain_verifier.py
```

---

## File Creation Summary

| Prompt | Action | File |
|---|---|---|
| P1-A | Modify | `audit/logger.py` — add hash columns to DDL + `migrate_audit_schema()` |
| P1-A | Create | `audit/tests/test_hash_chain_migration.py` |
| P1-B | Modify | `audit/logger.py` — add `_compute_chain_hash()` + wire into `log_decision()` and `log_portfolio_action()` |
| P1-C | Create | `audit/chain_verifier.py` |
| P1-C | Create | `audit/tests/test_chain_verifier.py` |
| P1-D | Modify | `decision-api/src/main.py` — update audit endpoint + add `POST /v1/audit/verify-chain` |
| P1-D | Create | `decision-api/tests/test_chain_verification_endpoint.py` |
| P1-E | Modify | `decision-api/src/main.py` — add migration to `startup_event()` + health check field |
| P2-A | Create | `compliance/adverse_action.py` |
| P2-A | Create | `compliance/tests/test_adverse_action.py` |
| P2-B | Create | `compliance/adverse_action_generator.py` |
| P2-B | Create | `compliance/tests/test_adverse_action_generator.py` |
| P2-C | Create | `compliance/adverse_action_pdf.py` |
| P2-C | Create | `compliance/tests/test_adverse_action_pdf.py` |
| P2-D | Modify | `audit/logger.py` — add `_CREATE_ADVERSE_ACTION_TABLE` DDL |
| P2-D | Create | `compliance/adverse_action_store.py` |
| P2-D | Create | `compliance/tests/test_adverse_action_store.py` |
| P2-E | Modify | `decision-api/src/main.py` — wire notice generation + add 4 endpoints |
| P2-E | Create | `decision-api/tests/test_adverse_action_endpoints.py` |
| P2-F | Modify | `monitoring/alert_router.py` — add `check_adverse_action_deadlines()` + `send_alert()` |
| P2-F | Create | `scripts/check_adverse_action_deadlines.py` |
| P2-F | Create | `monitoring/tests/test_aa_deadline_alert.py` |
| P2-G | Create | `compliance/exam_packet_builder.py` |
| P2-G | Create | `compliance/tests/test_exam_packet_builder.py` |

**Total: 10 files modified, 13 files created**

---

## Dependencies to Add to `requirements.txt`

```
# P1 — Hash chain (no new dependencies; uses stdlib hashlib)

# P2 — Adverse action PDF
reportlab>=4.0.0

# P2 — PDF testing (byte-level validation)
pypdf>=3.0.0  # test-only; move to requirements-dev.txt if desired
```

---

*Document Control: Implementation plan for Priority 1 and Priority 2 gap closure. Reviewed against PRD v1.0.0 §4.1.1 (GNRI-007), §4.4.2, and §8.1. Subsequent priorities (P3–P10) to be documented in a follow-on implementation plan after P1–P2 prompts are executed.*
