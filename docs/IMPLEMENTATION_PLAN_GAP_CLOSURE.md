# Implementation Plan: Gap Closure
**Document**: Integrated Lending Operating Layer (ILOL)
**Gaps Addressed**: GAP-19 through GAP-25 (identified in `docs/GAP_ANALYSIS_PRD_VS_IMPLEMENTATION.md`, 2026-04-26 audit)
**Author**: GitHub Copilot
**Created**: 2026-04-26

---

## Execution Order

Work the gaps in priority order. Each gap section contains one or more self-contained coding prompts. A prompt can be handed directly to an AI coding agent or a developer. Each prompt specifies exact file paths, function/class contracts, external dependencies, and acceptance criteria.

| Phase | Gap | Severity | Prompts |
|---|---|---|---|
| 1 | GAP-22: AI Audit Log BQ Array Fields | P1 | Prompt 22-A |
| 2 | GAP-23: Missing Webhook Events | P1 | Prompt 23-A |
| 3 | GAP-19: Tenant-Scoped Semantic Layer | P0 | Prompts 19-A, 19-B, 19-C |
| 4 | GAP-20: Multi-Agent Architecture | P0 | Prompts 20-A, 20-B, 20-C, 20-D |
| 5 | GAP-21: API Contract Compliance | P0 | Prompts 21-A, 21-B |
| 6 | GAP-25: Policy Version RSA Signing | P2 | Prompt 25-A |
| 7 | GAP-24: GraphQL Analytics API | P2 | Prompt 24-A |

> **Why P1 gaps before P0?** GAP-22 and GAP-23 are small, isolated changes. Completing them first gives GAP-20 (`ValidatorAgent`) and GAP-21 correct schema fields and webhook hooks to emit, preventing rework.

---

## Phase 1 — Prompt 22-A: AI Audit Log BigQuery Array Fields

**File**: `ai-agent/src/ai_audit_log.py`
**Depends on**: nothing
**PRD Reference**: §4.1.1 GNRI-011, §8.3

### Coding Prompt

```
Modify the file `ai-agent/src/ai_audit_log.py`.

CONTEXT
The file implements an append-only AI analytics agent audit log table `ai_agent_audit_log` backed
by SQLite (dev) / BigQuery (prod). It stores one row per AI turn with fields including
`session_id`, `query_text`, `plan_json`, `answer_text`, `confidence_score`,
`code_artifact_ref` (singular TEXT), `bq_job_id` (singular TEXT), and a SHA-256 hash chain.

PRD §8.3 mandates the BigQuery schema uses arrays for these fields because a single AI turn may
execute multiple SQL statements and produce multiple code artifacts.

CHANGES REQUIRED

1. In the DDL string (the SQL CREATE TABLE statement inside the module), replace:
     `code_artifact_ref TEXT`  →  `code_artifact_uris TEXT`     -- JSON-serialized array, e.g. '["gs://...a.sql","gs://...b.py"]'
     `bq_job_id TEXT`          →  `bq_job_ids TEXT`              -- JSON-serialized array
   Add two new columns:
     `code_zip_uri TEXT`        -- URI of the .zip archive for this turn's code artifacts
     `code_sha256_hashes TEXT`  -- JSON-serialized array of hex SHA-256 digests, one per artifact in code_artifact_uris

2. Update the `log_ai_turn()` async function signature from:
     log_ai_turn(..., code_artifact_ref: str | None = None, bq_job_id: str | None = None)
   to:
     log_ai_turn(...,
                 code_artifact_uris: list[str] | None = None,
                 bq_job_ids: list[str] | None = None,
                 code_zip_uri: str | None = None,
                 code_sha256_hashes: list[str] | None = None)
   Inside the function, serialize lists to JSON strings before INSERT:
     json.dumps(code_artifact_uris or [])

3. Add a new async function `get_ai_audit_records(session_id: str, db_session) -> list[dict]`
   that queries the table for all rows matching session_id, orders by `created_at` ASC,
   deserializes JSON array columns back to Python lists, and returns a list of dicts.
   This function is consumed by `compliance/exam_packet_builder.py`
   `build_ai_agent_audit_component()`.

4. Add an Alembic-style migration guard: if the table already exists (detect via
   `SELECT name FROM sqlite_master WHERE type='table' AND name='ai_agent_audit_log'`),
   use `ALTER TABLE ... ADD COLUMN` statements inside a try/except to add the new columns
   when they are absent, so existing databases are upgraded without data loss.

5. Update the `_compute_chain_hash()` helper to include `code_artifact_uris`,
   `bq_job_ids`, `code_zip_uri`, and `code_sha256_hashes` in the concatenated hash input
   string (order: append them after the existing fields, sorted for determinism).

CONSTRAINTS
- Do not change any function that is not mentioned above.
- Do not add new dependencies; `json` is stdlib.
- All async functions must use `await` properly with the existing async SQLAlchemy session pattern.
- Preserve the existing hash-chain logic exactly; only extend the hash input string.

ACCEPTANCE CRITERIA
1. `log_ai_turn()` accepts lists for the four array fields and stores them as JSON strings.
2. `get_ai_audit_records()` returns deserialized dicts with lists (not JSON strings) for array fields.
3. Running the module startup migration on an empty SQLite DB creates the table with all 6 columns (4 original + 4 new - 2 renamed = columns are: `code_artifact_uris`, `bq_job_ids`, `code_zip_uri`, `code_sha256_hashes`).
4. Running the migration on an existing DB that has the old singular columns adds the new columns without error.
5. The hash chain still verifies end-to-end after the change.
```

**Test file to create**: `ai-agent/tests/test_ai_audit_log.py`

```
Write pytest tests for the updated `ai-agent/src/ai_audit_log.py` covering:

1. test_log_ai_turn_array_fields — call log_ai_turn() with lists for code_artifact_uris,
   bq_job_ids, code_sha256_hashes, and a code_zip_uri string; assert the row stored in SQLite
   has the values JSON-deserialized correctly by get_ai_audit_records().

2. test_hash_chain_integrity — log 3 turns; call the existing chain verification function;
   assert it returns verified=True with rows_checked=3.

3. test_migration_idempotent — create the table with the OLD schema (using the original DDL
   without the array columns), then call the module startup; assert all four new columns
   are present in the schema afterward and no exception was raised.

Use pytest-asyncio and an in-memory SQLite database. Do not use mocks for the database layer.
```

---

## Phase 2 — Prompt 23-A: Webhook Events for AI Agent and Semantic Layer

**File**: `webhooks/models.py`
**Depends on**: nothing (Prompt 23-A is a pure enum addition; emission wiring comes in Prompts 20-C and 19-C)
**PRD Reference**: §10.3

### Coding Prompt

```
Modify the file `webhooks/models.py`.

CONTEXT
The file defines an `EventType` enum (or equivalent) listing all webhook event types emitted
by the platform. The current set includes: decision.created, decision.override, policy.changed,
model.deployed, alert.triggered, exam_packet.ready.

CHANGES REQUIRED
Add the following four members to the EventType enum in alphabetical position relative to
existing members:

    AGENT_ANSWER_READY   = "agent.answer.ready"
    HALLUCINATION_DETECTED = "hallucination.detected"
    SEMANTIC_SCHEMA_DRIFT  = "semantic.schema_drift"
    SEMANTIC_TERM_PROPOSED = "semantic.term_proposed"

If the file also contains a Pydantic model (e.g., `WebhookPayload`) with a `data` field that
is typed as a discriminated union by event_type, add minimal data schema classes:

    class AgentAnswerReadyData(BaseModel):
        session_id: str
        query_id: str
        confidence: str        # HIGH | MEDIUM | LOW
        code_artifact_count: int

    class HallucinationDetectedData(BaseModel):
        session_id: str
        query_id: str
        suppressed_sentence_count: int
        hallucination_count: int

    class SemanticSchemaDriftData(BaseModel):
        tenant_id: str
        table_name: str
        registered_hash: str
        live_hash: str

    class SemanticTermProposedData(BaseModel):
        tenant_id: str
        term: str
        proposed_by: str

CONSTRAINTS
- Match the coding style of the existing enum and model definitions exactly.
- Do not remove or rename any existing members.
- Do not add new imports beyond what is already imported.

ACCEPTANCE CRITERIA
1. `EventType.AGENT_ANSWER_READY.value == "agent.answer.ready"` is True.
2. `EventType.HALLUCINATION_DETECTED.value == "hallucination.detected"` is True.
3. `EventType.SEMANTIC_SCHEMA_DRIFT.value == "semantic.schema_drift"` is True.
4. `EventType.SEMANTIC_TERM_PROPOSED.value == "semantic.term_proposed"` is True.
5. All existing event type values are unchanged.
```

---

## Phase 3 — Prompt 19-A: Semantic Layer Core (AnalyticsScope, SemanticRegistry, Platform Metrics)

**File to create**: `analytics_api/src/semantic_layer.py`
**Depends on**: `data_contracts/` (enum harvesting), nothing else
**PRD Reference**: §4.7, §5.1–5.2 (Layer 1)

### Coding Prompt

```
Create the file `analytics_api/src/semantic_layer.py`.

PURPOSE
This module implements the Tenant-Scoped Semantic Layer (PRD Module 7). It provides:
  - Platform-level metric definitions (9 named metrics)
  - Automatic harvesting of enum values from data_contracts/ as platform glossary terms
  - Per-tenant custom glossary entries and table schema registrations
  - Two-tier resolution: tenant entries win over platform defaults
  - SHA-256 tamper detection per entry (deterministic hash of entry fields)
  - Schema drift detection on registered tenant table schemas

DATA MODELS (Pydantic v2)

    class EntryKind(str, Enum):
        METRIC = "metric"
        TERM = "term"
        TABLE_SCHEMA = "table_schema"

    class GlossaryEntry(BaseModel):
        entry_id: str                  # UUID
        kind: EntryKind
        name: str                      # Unique within tenant + kind
        tenant_id: str | None          # None = platform-level entry
        definition: str
        sql_expression: str | None     # For metrics: SELECT expression
        columns: list[str] | None      # For table_schema entries
        sha256: str                    # Deterministic hash of (kind, name, tenant_id, definition, sql_expression, columns)
        version: int
        created_at: datetime
        approved: bool                 # Four-eyes required for table_schema entries

    class PlatformMetric(BaseModel):
        name: str
        definition: str
        sql_expression: str

    class TwoTierResolutionResult(BaseModel):
        resolved_entry: GlossaryEntry
        source: Literal["tenant", "platform"]
        tenant_id: str | None

PLATFORM METRICS
Define exactly these 9 platform metrics as module-level constants in a dict
`PLATFORM_METRICS: dict[str, PlatformMetric]`:

    approval_rate:     "Percentage of loan applications approved in the period"
                       SQL: "COUNTIF(decision='APPROVED') / COUNT(*)"
    charge_off_rate:   "Percentage of outstanding balances charged off in the period"
                       SQL: "SUM(charge_off_amount) / SUM(outstanding_balance)"
    expected_loss:     "Probability of default multiplied by loss given default multiplied by exposure at default"
                       SQL: "SUM(pd * lgd * ead)"
    dir_score:         "Disparity Impact Ratio — approval rate for protected class divided by approval rate for control class"
                       SQL: "SAFE_DIVIDE(COUNTIF(decision='APPROVED' AND protected_class=1) / COUNTIF(protected_class=1), COUNTIF(decision='APPROVED' AND protected_class=0) / COUNTIF(protected_class=0))"
    model_gini:        "Gini coefficient of the credit scoring model on the evaluation window"
                       SQL: "2 * AUC - 1"
    portfolio_yield:   "Interest income divided by average outstanding balance"
                       SQL: "SUM(interest_income) / AVG(outstanding_balance)"
    vintage_dpd30:     "Percentage of loans in a vintage cohort that have gone 30+ DPD"
                       SQL: "COUNTIF(dpd >= 30) / COUNT(*)"
    concentration_hhi: "Herfindahl-Hirschman Index of industry segment concentration"
                       SQL: "SUM(POWER(segment_share, 2))"
    roll_rate:         "Percentage of current accounts that roll into the next delinquency bucket in the next period"
                       SQL: "COUNTIF(next_bucket > current_bucket) / COUNTIF(current_bucket < 5)"

PLATFORM GLOSSARY HARVESTING
Write a function `harvest_platform_glossary() -> list[GlossaryEntry]` that:
  1. Attempts to import every module under `data_contracts/` using `importlib`.
  2. Iterates module attributes; for any attribute that is a subclass of `enum.Enum`,
     iterates enum members and creates a `GlossaryEntry` with:
       kind = EntryKind.TERM
       name = f"{enum_class_name}.{member.name}"
       tenant_id = None
       definition = f"{member.value}" (the string value of the enum member)
       sql_expression = None
       approved = True   (platform entries are pre-approved)
  3. Returns the full list. If `data_contracts/` does not exist or no enums are found,
     returns an empty list without raising an exception.

SEMANTIC REGISTRY CLASS
Write a class `SemanticRegistry`:

    class SemanticRegistry:
        def __init__(self, tenant_id: str):
            self.tenant_id = tenant_id
            self._platform_entries: dict[str, GlossaryEntry]  # keyed by name
            self._tenant_entries: dict[str, GlossaryEntry]    # keyed by name

        @classmethod
        async def load(cls, tenant_id: str, db_session) -> "SemanticRegistry":
            """Load platform glossary + tenant entries from DB (via semantic_store)."""

        def resolve(self, name: str) -> TwoTierResolutionResult:
            """Tenant entry wins over platform if both exist. Raises KeyError if neither found."""

        def resolve_all(self) -> list[TwoTierResolutionResult]:
            """Return merged view: all platform entries + all tenant entries (tenant wins on conflict)."""

        @staticmethod
        def compute_entry_hash(entry: GlossaryEntry) -> str:
            """SHA-256 of json.dumps({kind, name, tenant_id, definition, sql_expression, columns}, sort_keys=True)"""

SCHEMA DRIFT DETECTION
Write an async function:

    async def check_schema_drift(
        registered_entry: GlossaryEntry,
        live_columns: list[str]
    ) -> tuple[bool, str, str]:
        """
        Compare the SHA-256 of the sorted registered columns list against
        the SHA-256 of the sorted live_columns list.
        Returns (drift_detected: bool, registered_hash: str, live_hash: str).
        """

CONSTRAINTS
- Pure Python; no DB calls in this file (DB is in semantic_store.py).
- Pydantic v2 (`model_config`, `model_validator` as needed).
- `compute_entry_hash` must be deterministic: sort keys, sort list fields before hashing.
- All `datetime` fields must be timezone-aware UTC.
- Do not raise exceptions for missing `data_contracts/` — degrade gracefully.

ACCEPTANCE CRITERIA
1. `PLATFORM_METRICS` contains exactly 9 entries with the names listed above.
2. `SemanticRegistry.compute_entry_hash()` returns the same value for two identical entries.
3. `check_schema_drift(entry, same_columns)` returns `(False, hash, hash)`.
4. `check_schema_drift(entry, different_columns)` returns `(True, registered_hash, live_hash)`.
5. `harvest_platform_glossary()` does not raise if `data_contracts/` is absent.
```

---

## Phase 3 — Prompt 19-B: Semantic Store (Append-Only DB + Four-Eyes Approval)

**File to create**: `analytics_api/src/semantic_store.py`
**Depends on**: `analytics_api/src/semantic_layer.py` (Prompt 19-A)
**PRD Reference**: §4.7.3 (SEM-003, SEM-006)

### Coding Prompt

```
Create the file `analytics_api/src/semantic_store.py`.

PURPOSE
Provides append-only persistence for the `tenant_semantic_registry` table. Supports:
  - Insert of new glossary entries (TERM and METRIC kinds are auto-approved)
  - Four-eyes approval workflow for TABLE_SCHEMA entries (create → pending → approved)
  - Read queries filtered by tenant_id (no cross-tenant leakage)
  - SHA-256 tamper verification on read

TABLE DDL (SQLite-compatible; also valid for PostgreSQL/BigQuery)

    CREATE TABLE IF NOT EXISTS tenant_semantic_registry (
        entry_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,                -- "metric" | "term" | "table_schema"
        name TEXT NOT NULL,
        tenant_id TEXT,                    -- NULL = platform entry
        definition TEXT NOT NULL,
        sql_expression TEXT,
        columns TEXT,                      -- JSON array of column names
        sha256 TEXT NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,          -- ISO-8601 UTC
        approved INTEGER NOT NULL DEFAULT 0,   -- 0 = pending, 1 = approved
        approved_by TEXT,
        approved_at TEXT,
        second_approver TEXT,
        second_approved_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_semantic_name_tenant
        ON tenant_semantic_registry (name, tenant_id);

FUNCTIONS TO IMPLEMENT

All functions are async and take a `db_session` as the last parameter (async SQLAlchemy
`AsyncSession` or a raw `aiosqlite` connection — match the pattern used in
`ai-agent/src/ai_audit_log.py`).

    async def insert_entry(entry: GlossaryEntry, db_session) -> GlossaryEntry:
        """
        Insert a new entry. Auto-generates entry_id (uuid4) and created_at if absent.
        Sets approved=True automatically for kind TERM and METRIC.
        Sets approved=False for kind TABLE_SCHEMA (requires four-eyes).
        Computes and stores sha256 using SemanticRegistry.compute_entry_hash().
        Raises ValueError if name+tenant_id already exists (unique constraint violation
        should be caught and re-raised as ValueError with a clear message).
        Returns the inserted entry with all fields populated.
        """

    async def get_entries(tenant_id: str, db_session, kind: EntryKind | None = None) -> list[GlossaryEntry]:
        """
        Return all APPROVED entries for tenant_id, plus all APPROVED platform entries
        (tenant_id IS NULL). Never return entries for other tenants.
        Optionally filter by kind. Deserializes columns JSON array.
        Verifies sha256 of each row; raises IntegrityError if mismatch detected.
        """

    async def approve_entry(
        entry_id: str,
        approver: str,
        second_approver: str,
        db_session
    ) -> GlossaryEntry:
        """
        Four-eyes approval: sets approved=1, approved_by, approved_at, second_approver,
        second_approved_at. Raises ValueError if approver == second_approver.
        Raises LookupError if entry_id not found.
        Only valid for TABLE_SCHEMA entries; raises ValueError for other kinds.
        """

    async def get_pending_approvals(tenant_id: str, db_session) -> list[GlossaryEntry]:
        """Return TABLE_SCHEMA entries with approved=0 for the given tenant."""

CONSTRAINTS
- Match the async DB pattern used in `ai-agent/src/ai_audit_log.py` exactly.
- sha256 verification on read: re-compute hash from row data and compare; if mismatch,
  raise `IntegrityError` with the entry_id.
- No cross-tenant data leakage: all queries must filter WHERE tenant_id = ? OR tenant_id IS NULL.
- Do not add new library dependencies beyond what the project already uses.

ACCEPTANCE CRITERIA
1. `insert_entry()` with kind=TABLE_SCHEMA stores approved=False.
2. `insert_entry()` with kind=TERM stores approved=True immediately.
3. `get_entries()` returns only approved entries; pending TABLE_SCHEMA entries are excluded.
4. `approve_entry()` raises ValueError when approver == second_approver.
5. `get_entries()` raises IntegrityError when stored sha256 does not match recomputed sha256.
6. `get_entries(tenant_id="a")` never returns rows with tenant_id="b".
```

---

## Phase 3 — Prompt 19-C: Semantic API Router

**File to create**: `analytics_api/src/semantic_api.py`
**Depends on**: Prompts 19-A, 19-B
**PRD Reference**: §10.2 SEM-007 through SEM-011

### Coding Prompt

```
Create the file `analytics_api/src/semantic_api.py`.

PURPOSE
FastAPI router exposing the Tenant-Scoped Semantic Layer as HTTP endpoints, per PRD §10.2.

ROUTER SETUP
    from fastapi import APIRouter
    router = APIRouter(prefix="/v1/analytics", tags=["semantic-layer"])

ENDPOINTS TO IMPLEMENT

--- GET /v1/analytics/glossary ---
Response: GlossaryResponse
    class GlossaryResponse(BaseModel):
        tenant_id: str
        platform_terms: list[GlossaryEntry]
        tenant_terms: list[GlossaryEntry]
        platform_metrics: list[PlatformMetric]
        total_count: int

Logic:
  1. Extract tenant_id from JWT claims (use the existing `get_current_tenant_id()` dependency
     from `analytics_api/src/main.py` or equivalent).
  2. Load SemanticRegistry for tenant via `SemanticRegistry.load(tenant_id, db)`.
  3. Call `registry.resolve_all()` to build merged view.
  4. Return platform terms, tenant terms, and all platform metrics separately.
  5. Never include entries from other tenants.


--- POST /v1/analytics/tenant/glossary ---
Request body:
    class GlossaryTermRequest(BaseModel):
        name: str
        kind: EntryKind          # TERM or METRIC only; TABLE_SCHEMA rejected here
        definition: str
        sql_expression: str | None = None

Response: GlossaryEntry (the inserted entry)

Logic:
  1. Validate kind != TABLE_SCHEMA (return HTTP 422 if so, with message
     "Use /tenant/schema/register for table schema entries").
  2. Build GlossaryEntry and call `insert_entry()`.
  3. Emit webhook event SEMANTIC_TERM_PROPOSED via `webhooks/dispatcher.py`
     `emit_webhook()` (async, fire-and-forget — do not await or block response).
  4. Return 201 Created with the inserted entry.


--- POST /v1/analytics/tenant/schema/register ---
Request body:
    class SchemaRegisterRequest(BaseModel):
        table_name: str
        columns: list[str]       # Column names only; no PII type info required
        definition: str          # Human-readable description of the table

Response:
    class SchemaRegisterResponse(BaseModel):
        entry_id: str
        status: Literal["pending_approval"]
        message: str

Logic:
  1. Build GlossaryEntry with kind=TABLE_SCHEMA, name=table_name, columns=columns.
  2. Call `insert_entry()` (will store approved=False).
  3. Return 202 Accepted with status="pending_approval" and a message explaining
     that four-eyes approval is required before the schema is active.


--- GET /v1/analytics/tenant/schema/{table_name}/status ---
Response:
    class SchemaStatusResponse(BaseModel):
        table_name: str
        status: Literal["approved", "pending_approval", "not_found"]
        entry: GlossaryEntry | None

Logic:
  1. Query `get_pending_approvals()` and `get_entries()` for the tenant.
  2. Search for an entry with name == table_name and kind == TABLE_SCHEMA.
  3. Return appropriate status.


--- POST /v1/analytics/admin/tenant/{tenant_id}/schema/{entry_id}/approve  (admin role only) ---
Request body:
    class SchemaApproveRequest(BaseModel):
        approver: str
        second_approver: str

Response: GlossaryEntry

Logic:
  1. Require role "platform_admin" in JWT claims (return HTTP 403 if not present).
  2. Call `approve_entry(entry_id, approver, second_approver, db)`.
  3. Emit webhook event SEMANTIC_TERM_PROPOSED (reuse for approvals; a separate event
     type will be added in a future iteration).
  4. Return 200 with the updated entry.


WIRE INTO APP
In `analytics_api/src/main.py`, import the router and include it:
    from analytics_api.src.semantic_api import router as semantic_router
    app.include_router(semantic_router)

CONSTRAINTS
- Use the same JWT auth dependency pattern as the existing analytics_api endpoints.
- All DB calls must be async.
- Webhook emission must be fire-and-forget (asyncio.create_task or BackgroundTask).
- Return RFC 7807 Problem Details JSON for error responses (use the existing error handler
  pattern in the analytics_api app if one exists, otherwise return
  {"detail": "...", "type": "...", "status": <code>}).

ACCEPTANCE CRITERIA
1. `GET /v1/analytics/glossary` returns platform metrics and merged glossary without cross-tenant entries.
2. `POST /v1/analytics/tenant/glossary` with kind=TABLE_SCHEMA returns HTTP 422.
3. `POST /v1/analytics/tenant/schema/register` returns HTTP 202 with status="pending_approval".
4. `GET /v1/analytics/tenant/schema/{name}/status` returns "not_found" for unknown table name.
5. `POST /v1/analytics/admin/tenant/{id}/schema/{entry_id}/approve` returns HTTP 403 without platform_admin role.
```

---

## Phase 4 — Prompt 20-A: ComplianceGateAgent

**File to create**: `ai-agent/src/compliance_gate_agent.py`
**Depends on**: `compliance/prohibited_variables.py` (existing)
**PRD Reference**: §4.6.6, §5.2 (Enforcement Layer 2)

### Coding Prompt

```
Create the file `ai-agent/src/compliance_gate_agent.py`.

PURPOSE
The ComplianceGateAgent is the first pre-planning enforcement layer in the multi-agent query
pipeline. It screens the raw user query for ECOA-prohibited variables and other PII signals
before the PlannerAgent receives the query. If prohibited content is detected, the query is
blocked entirely and a structured refusal is returned without touching the planner or SQL layer.

IMPORTS
Import `detect_prohibited_variables(query: str) -> list[str]` from
`compliance/prohibited_variables.py`. If the import path differs, locate the function
using the file search and use the correct import path.

DATA MODELS

    class GateDecision(BaseModel):
        allowed: bool
        blocked_terms: list[str]          # Empty if allowed
        refusal_message: str | None       # Human-readable reason if not allowed
        gate_id: str                      # UUID for audit cross-reference

AGENT CLASS

    class ComplianceGateAgent:
        """
        Pre-planning compliance gate. Blocks ECOA-prohibited variables and PII
        indicators from entering the query pipeline.
        """

        def evaluate(self, query_text: str, tenant_id: str) -> GateDecision:
            """
            1. Call detect_prohibited_variables(query_text) to get a list of detected terms.
            2. Additionally, apply a lightweight regex scan for direct PII indicators:
               - SSN patterns: r'\b\d{3}-\d{2}-\d{4}\b'
               - Credit card patterns: r'\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b'
               If any PII pattern is found, add "direct_pii" to blocked_terms.
            3. If blocked_terms is non-empty:
               - allowed = False
               - refusal_message = (
                   f"Query blocked: contains ECOA-prohibited or PII content: "
                   f"{', '.join(blocked_terms)}. "
                   "Please rephrase using aggregate metrics only."
                 )
            4. If blocked_terms is empty:
               - allowed = True
               - refusal_message = None
            5. Always generate a unique gate_id = str(uuid.uuid4()).
            6. Return GateDecision.
            """

        def log_gate_decision(self, decision: GateDecision, session_id: str) -> None:
            """
            Write a single-line JSON log entry to stderr (not stdout) using Python's
            logging module at WARNING level if not allowed, INFO level if allowed.
            Format: {"gate_id": ..., "session_id": ..., "allowed": ..., "blocked_terms": ...}
            """

CONSTRAINTS
- `evaluate()` must be synchronous (not async) — it performs no I/O.
- Do not raise exceptions for prohibited content; return GateDecision with allowed=False.
- Do not import any LangChain or OpenAI libraries.
- The regex patterns must be compiled at class instantiation (not per-call) for performance.

ACCEPTANCE CRITERIA
1. `evaluate("approve loans by race")` returns `allowed=False` with "race" in blocked_terms.
2. `evaluate("what is the approval rate by state?")` returns `allowed=True`.
3. `evaluate("customer SSN is 123-45-6789")` returns `allowed=False` with "direct_pii" in blocked_terms.
4. `gate_id` is a valid UUID string on every call.
5. `log_gate_decision()` does not raise.
```

---

## Phase 4 — Prompt 20-B: QueryBuilderAgent (Schema Injection + DB Dry-Run)

**File to create**: `ai-agent/src/query_builder_agent.py`
**Depends on**: `analytics_api/src/semantic_layer.py` (Prompt 19-A), existing DB session
**PRD Reference**: §4.6.4 (mandatory schema injection + dry-run)

### Coding Prompt

```
Create the file `ai-agent/src/query_builder_agent.py`.

PURPOSE
The QueryBuilderAgent wraps LLM-generated SQL with:
  1. Schema context injection into the prompt before generation
  2. Tenant-id injection into the WHERE clause of every generated query
  3. PII column masking (NULL replacement for columns flagged in SemanticRegistry)
  4. DB dry-run validation (EXPLAIN or LIMIT 0) before a query is returned as valid

DATA MODELS

    class QueryCandidate(BaseModel):
        sql: str
        injected_tenant_id: str
        schema_context_used: list[str]    # names of GlossaryEntries used in prompt
        dry_run_passed: bool
        dry_run_error: str | None

    class QueryBuildError(Exception):
        def __init__(self, message: str, dry_run_output: str):
            super().__init__(message)
            self.dry_run_output = dry_run_output

AGENT CLASS

    class QueryBuilderAgent:
        def __init__(self, db_url: str, tenant_id: str):
            """Store db_url and tenant_id. Create a SQLAlchemy engine (sync, for dry-run)."""

        def inject_schema_context(
            self,
            base_prompt: str,
            registry_entries: list[GlossaryEntry]
        ) -> str:
            """
            Append a schema context block to base_prompt:

            --- SCHEMA CONTEXT ---
            Available metrics and terms:
            {for each entry: "  - {entry.name}: {entry.definition}" + sql_expression if metric}
            Tenant ID filter: All queries MUST include WHERE tenant_id = '{self.tenant_id}'
            ----------------------

            Returns the augmented prompt string.
            """

        def inject_tenant_id(self, sql: str) -> str:
            """
            Parse the SQL string. If it contains a WHERE clause, append
            `AND tenant_id = '{self.tenant_id}'`. If it has no WHERE clause but has
            a FROM clause, append `WHERE tenant_id = '{self.tenant_id}'`.
            Uses simple string manipulation (no full SQL parser required).
            If 'tenant_id' already appears in the SQL, return sql unchanged.
            """

        async def dry_run(self, sql: str) -> tuple[bool, str | None]:
            """
            Execute 'EXPLAIN ' + sql using the async SQLAlchemy engine.
            For SQLite, EXPLAIN is available. For BigQuery, use 'SELECT ... LIMIT 0'.
            If the engine dialect is 'bigquery', wrap sql as:
                SELECT * FROM ({sql}) AS _dry_run LIMIT 0
            Catch all exceptions and return (False, str(exception)).
            On success return (True, None).
            """

        async def build(
            self,
            raw_sql: str,
            registry_entries: list[GlossaryEntry]
        ) -> QueryCandidate:
            """
            1. Inject tenant_id into raw_sql.
            2. Run dry_run on the tenant-injected sql.
            3. If dry_run fails, raise QueryBuildError with the dry_run error output.
            4. Return QueryCandidate with dry_run_passed=True and schema_context_used
               populated from registry_entries names.
            """

CONSTRAINTS
- dry_run must use a separate read-only connection (do not use the session passed
  to other agent methods — create a dedicated engine in __init__).
- Do not modify the SQL parser for complex queries; simple string injection is acceptable
  for the v1 implementation as noted above. Add a TODO comment for future sqlglot integration.
- All async methods must properly await async SQLAlchemy operations.

ACCEPTANCE CRITERIA
1. `inject_tenant_id("SELECT * FROM loans WHERE state = 'CA'")` returns SQL containing
   `AND tenant_id = '<tenant_id>'`.
2. `inject_tenant_id("SELECT * FROM loans WHERE tenant_id = 'x'")` returns SQL unchanged.
3. `dry_run(valid_sql)` returns `(True, None)` on a live SQLite in-memory DB.
4. `dry_run("SELECT * FROM nonexistent_table_xyz")` returns `(False, <error_string>)`.
5. `build()` raises `QueryBuildError` when dry_run fails.
```

---

## Phase 4 — Prompt 20-C: ValidatorAgent (Narrative ↔ Data Reconciliation)

**File to create**: `ai-agent/src/validator_agent.py`
**Depends on**: `webhooks/models.py` (Prompt 23-A for HALLUCINATION_DETECTED event)
**PRD Reference**: §5.2 (Enforcement Layer 4), §4.6.6

### Coding Prompt

```
Create the file `ai-agent/src/validator_agent.py`.

PURPOSE
The ValidatorAgent reconciles every number cited in the AI-generated narrative against the
actual rows returned by the executed SQL queries. This is the primary anti-hallucination
enforcement layer.

DATA MODELS

    class HallucinationAttempt(BaseModel):
        suppressed_sentence: str
        claimed_value: str        # The number as it appeared in the narrative
        nearest_result_value: str | None   # Closest value found in result_rows, or None
        delta_pct: float | None           # Absolute % difference, or None if no match found

    class ValidationResult(BaseModel):
        passed: bool
        validated_narrative: str          # Narrative with hallucinated sentences removed/flagged
        hallucination_count: int
        suppressed_sentences: list[str]
        attempts: list[HallucinationAttempt]

AGENT CLASS

    class ValidatorAgent:
        TOLERANCE_PCT = 1.0    # Numbers within 1% are considered matching

        def reconcile(
            self,
            narrative: str,
            result_rows: list[dict]
        ) -> ValidationResult:
            """
            Algorithm:
            1. Flatten all numeric values from result_rows into a single list of floats.
               For each dict in result_rows, recursively collect all values that can be
               cast to float.

            2. Tokenize narrative into sentences using '. ' as the delimiter.

            3. For each sentence:
               a. Extract all numeric tokens using regex: r'\b\d+(?:[.,]\d+)?%?\b'
               b. For each numeric token, strip '%', replace ',' with '', cast to float.
               c. For each float value, check if any value in the flattened result set
                  is within TOLERANCE_PCT percent:
                    abs(claimed - result) / max(abs(result), 1e-9) * 100 <= TOLERANCE_PCT
               d. If the sentence contains at least one numeric token that is NOT found
                  in the result set, mark the sentence as hallucinated.

            4. Build validated_narrative by:
               - Keeping non-hallucinated sentences unchanged.
               - Replacing hallucinated sentences with:
                 "[REDACTED: value not found in query results]"

            5. Return ValidationResult with:
               - passed = (hallucination_count == 0)
               - validated_narrative = rejoined sentences
               - hallucination_count = number of suppressed sentences
               - suppressed_sentences = list of original hallucinated sentences
               - attempts = list of HallucinationAttempt for each suppressed sentence

            IMPORTANT: If the narrative contains NO numeric tokens at all, return
            ValidationResult(passed=True, validated_narrative=narrative,
            hallucination_count=0, suppressed_sentences=[], attempts=[]).
            """

        def emit_hallucination_webhook(
            self,
            result: ValidationResult,
            session_id: str,
            query_id: str
        ) -> None:
            """
            If result.hallucination_count > 0, emit a HALLUCINATION_DETECTED webhook
            event using `webhooks/dispatcher.py` `emit_webhook()` (fire-and-forget via
            asyncio.create_task if in async context, else threading.Thread).
            Payload should be HallucinationDetectedData(
                session_id=session_id,
                query_id=query_id,
                suppressed_sentence_count=result.hallucination_count,
                hallucination_count=result.hallucination_count
            ).
            Log the emission at WARNING level.
            """

CONSTRAINTS
- `reconcile()` must be synchronous (no I/O).
- Sentence splitting by '. ' is acceptable for v1; add a TODO for spaCy sentence tokenization.
- Do not import LangChain or OpenAI; this agent must be fully deterministic.
- TOLERANCE_PCT is a class-level constant; do not make it a constructor parameter.

ACCEPTANCE CRITERIA
1. narrative = "The approval rate was 42.5%." with result_rows = [{"approval_rate": 0.425}]
   → passed=True (0.425 rounds to 42.5% within tolerance with scaling logic).

   NOTE: The implementation must handle the common case where the narrative expresses a
   value as a percentage (42.5%) but the DB returns a decimal (0.425). Handle this by
   also checking claimed_value * 100 against result values and claimed_value / 100.

2. narrative = "The approval rate was 42.5%." with result_rows = [{"approval_rate": 0.99}]
   → passed=False, hallucination_count=1.

3. narrative = "Performance improved significantly." (no numbers) → passed=True.

4. `emit_hallucination_webhook()` does not raise even if webhooks/dispatcher is unavailable
   (catch ImportError and log at WARNING).
```

---

## Phase 4 — Prompt 20-D: FormatterAgent, SessionStore, RegulatoryKB

**Files to create**: `ai-agent/src/formatter_agent.py`, `ai-agent/src/session_store.py`, `ai-agent/src/regulatory_kb.py`
**Depends on**: Prompts 20-A, 20-C, Prompt 22-A (for code_artifact_uris)
**PRD Reference**: §4.6.5 (Code Transparency Layer, non-negotiable), §4.6.6 (RegulatoryInterpreterAgent), §7.2 (Redis)

### Coding Prompt

```
Create three files: `ai-agent/src/formatter_agent.py`, `ai-agent/src/session_store.py`,
and `ai-agent/src/regulatory_kb.py`.

=== FILE 1: ai-agent/src/formatter_agent.py ===

PURPOSE
The FormatterAgent is the final gate before any AI answer is delivered to the caller.
PRD §4.6.5 Rule 6 (non-negotiable): "FormatterAgent blocks output delivery if
code_artifacts array is empty."

DATA MODELS

    class CodeArtifactsMissingError(Exception):
        """Raised when FormatterAgent blocks delivery due to missing code artifacts."""

    class FormattedOutput(BaseModel):
        answer_text: str                  # Validated narrative from ValidatorAgent
        code_artifacts: list[str]         # URIs from code_artifact_store
        code_zip_uri: str | None          # ZIP URI if already assembled
        confidence: str                   # HIGH | MEDIUM | LOW
        metadata: dict                    # session_id, query_id, tenant_id, timestamp

AGENT CLASS

    class FormatterAgent:
        def format(
            self,
            validated_narrative: str,
            code_artifact_uris: list[str],
            confidence: str,
            metadata: dict,
            code_zip_uri: str | None = None
        ) -> FormattedOutput:
            """
            1. If code_artifact_uris is empty, raise CodeArtifactsMissingError with message:
               "Output delivery blocked: no code artifacts recorded for this query.
                All AI answers must be backed by verifiable SQL or Python code."

            2. If code_artifact_uris is non-empty, return FormattedOutput with all fields.
            """


=== FILE 2: ai-agent/src/session_store.py ===

PURPOSE
Redis-backed (with SQLite fallback for dev/test) session memory store for the multi-agent
pipeline. Stores the last N turns of a session as a list of dicts.

    class SessionStore:
        MAX_TURNS = 20   # Sliding window

        def __init__(self, redis_url: str | None = None, sqlite_path: str = ":memory:"):
            """
            If redis_url is provided AND the `redis` package is importable, use Redis.
            Otherwise, fall back to an in-process dict (for dev/test) keyed by session_id.
            Log which backend is active at INFO level on startup.
            """

        def append_turn(self, session_id: str, turn: dict) -> None:
            """
            Append turn dict to session history. Trim to MAX_TURNS (oldest removed).
            Serializes to JSON for Redis (RPUSH + LTRIM) or stores in-process dict.
            """

        def get_history(self, session_id: str) -> list[dict]:
            """Return list of turn dicts for session_id. Returns [] if not found."""

        def clear_session(self, session_id: str) -> None:
            """Delete session history."""

CONSTRAINTS for SessionStore:
- Redis import must be wrapped in try/except ImportError.
- The fallback dict store is process-local; document that it is not suitable for
  multi-instance deployments.
- Do not raise if Redis is unavailable; silently fall back.


=== FILE 3: ai-agent/src/regulatory_kb.py ===

PURPOSE
Provides a `RegulatoryKB` class that retrieves relevant regulatory guidance chunks for
a query, and a `RegulatoryInterpreterAgent` that formats those chunks for LLM context.

    class RegulatoryChunk(BaseModel):
        source: str         # e.g. "SR_11-7_Section_4.2"
        text: str
        relevance_score: float

    class RegulatoryKB:
        """
        Production: connects to Pinecone index "regulatory-kb".
        Development fallback: uses a local FAISS index if pinecone is not available,
        or returns a static set of hardcoded chunks for known regulatory topics.
        """

        def __init__(self, pinecone_api_key: str | None = None, index_name: str = "regulatory-kb"):
            """
            Attempt to import `pinecone` and connect to the index.
            If import fails or api_key is None, set self._backend = "local".
            Otherwise set self._backend = "pinecone".
            Log backend selection at INFO level.
            """

        def query(self, query_text: str, top_k: int = 5) -> list[RegulatoryChunk]:
            """
            If backend = "pinecone": embed query_text and query the Pinecone index.
            If backend = "local": return the TOP_K most relevant entries from
            STATIC_REGULATORY_CHUNKS (defined below) using simple keyword matching
            (count overlapping words between query_text.lower() and chunk.text.lower()).
            Always return a list of RegulatoryChunk sorted by relevance_score DESC.
            """

        STATIC_REGULATORY_CHUNKS = [
            RegulatoryChunk(
                source="SR_11-7_Section_2",
                text="Model risk management encompasses all activities associated with developing, "
                     "validating, implementing, and using models. SR 11-7 requires banks to "
                     "maintain a comprehensive model inventory with version history.",
                relevance_score=0.9
            ),
            RegulatoryChunk(
                source="ECOA_Reg_B_202.6",
                text="A creditor shall not consider race, color, religion, national origin, sex, "
                     "marital status, or age in any aspect of a credit transaction. "
                     "Disparate impact analysis must be performed for any neutral policy.",
                relevance_score=0.9
            ),
            RegulatoryChunk(
                source="CFPB_UDAAP_Exam_Procedures",
                text="Unfair, deceptive, or abusive acts or practices (UDAAP) include making "
                     "material misrepresentations about credit products. AI-generated summaries "
                     "containing incorrect numerical claims may constitute a deceptive practice.",
                relevance_score=0.85
            ),
            RegulatoryChunk(
                source="FFIEC_IT_Exam_Handbook_Audit",
                text="Audit trails must be complete, accurate, and tamper-evident. "
                     "AI systems that generate analytical outputs must maintain logs of "
                     "every query, response, and code artifact for examiner review.",
                relevance_score=0.85
            ),
            RegulatoryChunk(
                source="OCC_2021-25_Model_Risk",
                text="Model outputs used for credit decisions must be validated against "
                     "empirical data. Model documentation must include limitations, assumptions, "
                     "and conceptual soundness assessments updated at least annually.",
                relevance_score=0.8
            ),
        ]

    class RegulatoryInterpreterAgent:
        def __init__(self, kb: RegulatoryKB):
            self.kb = kb

        def build_context(self, query_text: str, top_k: int = 3) -> str:
            """
            Query the KB and format the top-k chunks as a context block:

            --- REGULATORY CONTEXT ---
            The following regulatory guidance is relevant to this query:
            [1] {source}: {text}
            [2] {source}: {text}
            ...
            --------------------------

            Returns the formatted string. If kb.query() returns empty list,
            return an empty string (do not include the header block).
            """

CONSTRAINTS
- All three files must be importable independently.
- No LangChain imports in formatter_agent.py or session_store.py.
- regulatory_kb.py may import langchain_openai only for embedding if pinecone backend is active;
  wrap in try/except.

ACCEPTANCE CRITERIA (FormatterAgent)
1. `format(narrative, [], "HIGH", {})` raises CodeArtifactsMissingError.
2. `format(narrative, ["gs://bucket/query.sql"], "HIGH", {"session_id": "x"})` returns FormattedOutput.

ACCEPTANCE CRITERIA (SessionStore)
1. `append_turn(sid, {"q": "test"})` followed by `get_history(sid)` returns [{"q": "test"}].
2. After 21 appends, `get_history(sid)` returns exactly 20 items.
3. `clear_session(sid)` results in `get_history(sid)` returning [].

ACCEPTANCE CRITERIA (RegulatoryKB)
1. `kb.query("ECOA disparate impact")` returns at least 1 RegulatoryChunk with "ECOA" in source.
2. `RegulatoryInterpreterAgent.build_context("model risk")` returns a non-empty string.
3. `RegulatoryInterpreterAgent.build_context("xyzzy no match abc")` does not raise (may return empty string).
```

---

## Phase 5 — Prompt 21-A: AI Agent API Contract Compliance

**File to modify**: `ai-agent/src/main.py`
**Depends on**: Prompts 20-A, 20-B, 20-C, 20-D, 22-A
**PRD Reference**: §10.2 Appendix B, GNRI-011

### Coding Prompt

```
Modify the file `ai-agent/src/main.py`.

CONTEXT
The current file has these endpoints:
  POST /agent/sessions           (create session)
  POST /agent/chat               (streaming chat, returns SSE)
  GET  /agent/sessions/{id}/history
  DELETE /agent/sessions/{id}

These must be KEPT intact (backward compatibility). Add the following PRD-compliant
endpoints as a versioned prefix group under /api/v1.

NEW ENDPOINTS TO ADD

--- POST /api/v1/agent/query ---
Request body (AgentQueryRequest):
    class AgentQueryRequest(BaseModel):
        session_id: str
        query: str
        tenant_id: str
        output_format: Literal["json", "pdf", "excel", "both"] = "json"

Response body (AgentQueryResponse):
    class AgentQueryResponse(BaseModel):
        query_id: str          # UUID for this query turn
        session_id: str
        answer: str            # Validated narrative from ValidatorAgent
        confidence: str        # HIGH | MEDIUM | LOW
        code_artifacts: list[CodeArtifactItem]
        plan: dict | None      # PlannerAgent output
        hallucination_count: int
        status: Literal["success", "blocked", "error"]
        blocked_reason: str | None

    class CodeArtifactItem(BaseModel):
        artifact_id: str
        kind: str              # "sql" | "python"
        uri: str               # gs:// or local path
        sha256: str

Pipeline logic (in order):
  1. ComplianceGateAgent.evaluate(query, tenant_id) → if not allowed, return
     AgentQueryResponse with status="blocked", blocked_reason=gate.refusal_message,
     code_artifacts=[], hallucination_count=0.
  2. PlannerAgent.plan(query) → store plan.
  3. Route to the appropriate specialist agent (use existing OrchestratorAgent logic).
  4. Collect code artifacts from code_artifact_store for this query_id.
  5. QueryBuilderAgent.build(raw_sql, registry_entries) for any SQL produced — replace
     raw SQL with the dry-run-validated, tenant-id-injected SQL.
  6. Execute validated SQL via the existing DB connection.
  7. ValidatorAgent.reconcile(narrative, result_rows) → get validated_narrative.
  8. FormatterAgent.format(validated_narrative, artifact_uris, confidence, metadata)
     → if CodeArtifactsMissingError raised, return status="error" with the error message.
  9. Log the full turn to ai_audit_log via log_ai_turn() with the new array fields.
  10. Emit AGENT_ANSWER_READY webhook event (fire-and-forget).
  11. Return AgentQueryResponse.


--- GET /api/v1/agent/sessions/{session_id} ---
Response: SessionSummary
    class SessionSummary(BaseModel):
        session_id: str
        tenant_id: str
        turn_count: int
        created_at: datetime
        last_activity: datetime
        history: list[dict]   # From SessionStore.get_history()


--- POST /api/v1/agent/audit-package ---
Request body:
    class AuditPackageRequest(BaseModel):
        session_id: str
        tenant_id: str

Response: dict with keys: session_id, tenant_id, audit_records (list of dicts from
get_ai_audit_records()), generated_at (ISO-8601 UTC string).

Logic: call `get_ai_audit_records(session_id, db)` from ai_audit_log.py and return as JSON.


--- GET /api/v1/agent/query/{query_id}/code-artifacts ---
Response: list[CodeArtifactItem]
Logic: query `agent_code_artifacts` table for all rows matching query_id; return as list.


--- GET /api/v1/agent/query/{query_id}/code-archive.zip ---
Response: StreamingResponse with media_type="application/zip"
Logic:
  1. Fetch all code artifact records for query_id from code_artifact_store.
  2. Create an in-memory zip file (io.BytesIO + zipfile.ZipFile) containing each artifact
     as a file named `{artifact_id}_{kind}.{ext}` where ext is "sql" for SQL artifacts
     and "py" for Python artifacts.
  3. Add a manifest.json to the zip: {"query_id": ..., "artifacts": [{"id":..., "kind":..., "sha256":...}]}
  4. Return StreamingResponse of the zip bytes.

CONSTRAINTS
- Keep ALL existing endpoints unchanged.
- New endpoints must be additive only — do not modify existing route handlers.
- Use the existing DB session dependency injection pattern.
- For endpoints that call ComplianceGateAgent, the agent must be instantiated per-request
  (stateless).
- The ZIP endpoint must not write to disk; use in-memory io.BytesIO only.

ACCEPTANCE CRITERIA
1. POST /api/v1/agent/query with a prohibited variable returns status="blocked".
2. POST /api/v1/agent/query with a valid query returns code_artifacts as a non-empty list.
3. GET /api/v1/agent/query/{id}/code-archive.zip returns Content-Type: application/zip.
4. POST /api/v1/agent/audit-package returns a list of audit records with code_artifact_uris as lists.
5. All existing /agent/* endpoints still return HTTP 200 for their current test payloads.
```

---

## Phase 5 — Prompt 21-B: Analytics API Query + Evidence Endpoints

**File to modify**: `analytics_api/src/main.py`
**Depends on**: Prompts 19-A, 19-B, 19-C
**PRD Reference**: §10.2

### Coding Prompt

```
Modify the file `analytics_api/src/main.py`.

Add the following endpoint groups. Keep all existing endpoints (/v1/analytics/vintage-curves,
/v1/analytics/roll-rates, /v1/analytics/approval-profit) unchanged.

--- POST /v1/analytics/query/sql ---
Request body:
    class SqlQueryRequest(BaseModel):
        sql: str
        tenant_id: str
        description: str | None = None  # Optional human-readable label

Response:
    class SqlQueryResponse(BaseModel):
        query_id: str
        rows: list[dict]
        row_count: int
        code_artifact_id: str | None   # ID stored in code_artifact_store if available
        executed_at: str               # ISO-8601 UTC

Logic:
  1. Validate that sql.upper().strip().startswith("SELECT") — reject INSERT/UPDATE/DELETE/DROP
     with HTTP 422 and message "Only SELECT statements are permitted."
  2. Inject tenant_id into WHERE clause using QueryBuilderAgent.inject_tenant_id() if
     query_builder_agent.py is available; otherwise append manually.
  3. Execute the SQL against the configured database.
  4. Store the SQL as a code artifact via code_artifact_store if available.
  5. Return response with rows and code_artifact_id.


--- POST /v1/analytics/query/nl ---
Request body:
    class NlQueryRequest(BaseModel):
        query: str
        tenant_id: str

Response: Same as SqlQueryResponse plus:
        generated_sql: str              # The SQL actually executed
        semantic_terms_resolved: list[str]  # Names of GlossaryEntries used

Logic:
  1. Load SemanticRegistry for tenant_id.
  2. Use registry to resolve all terms in the query text.
  3. Build schema-injected prompt using QueryBuilderAgent.inject_schema_context() if available.
  4. NOTE: The actual LLM SQL generation is out of scope for this prompt — add a TODO comment
     stating "TODO: route through OrchestratorAgent for LLM SQL generation" and for now
     return HTTP 501 with body {"detail": "NL query endpoint not yet implemented; use /query/sql"}.
     This stub ensures the endpoint exists and is routed correctly.


--- GET /v1/analytics/queries/saved ---
Response: list[SavedQueryRecord]
    class SavedQueryRecord(BaseModel):
        query_id: str
        tenant_id: str
        sql: str
        description: str | None
        created_at: str

Logic: Query a `saved_queries` table (create DDL inline in this function if not already present):
    CREATE TABLE IF NOT EXISTS saved_queries (
        query_id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        sql TEXT NOT NULL,
        description TEXT,
        created_at TEXT NOT NULL
    )
Filter by tenant_id from JWT claims. Return list.


--- POST /v1/analytics/queries/save ---
Request: SqlQueryRequest (reuse)
Response: SavedQueryRecord

Logic: Insert into saved_queries; generate query_id = uuid4().


--- POST /v1/analytics/evidence/exam-packet ---
Request body:
    class EvidencePacketRequest(BaseModel):
        tenant_id: str
        session_id: str | None = None    # If provided, include AI audit records
        date_range_start: str | None = None  # ISO-8601 date
        date_range_end: str | None = None

Response:
    class EvidencePacketResponse(BaseModel):
        packet_id: str
        tenant_id: str
        status: Literal["building", "ready"]
        components: list[str]
        download_url: str | None    # Populated when status=ready

Logic:
  1. Generate packet_id = uuid4().
  2. Store a record in a `evidence_packets` table with status="building".
  3. Return immediately with status="building" and the packet_id.
  4. Use BackgroundTasks to build the packet asynchronously:
     a. Call compliance/exam_packet_builder.build_exam_packet() if importable.
     b. Update status to "ready" in the table.
     (If exam_packet_builder is not importable, log warning and set status="ready" with no components.)


--- GET /v1/analytics/evidence/exam-packet/{packet_id} ---
Response: EvidencePacketResponse
Logic: Query `evidence_packets` table by packet_id and tenant_id (from JWT). Return 404 if not found.

CONSTRAINTS
- All new endpoints must use the existing JWT auth dependency.
- All DB operations must be async.
- The /query/nl endpoint MUST return HTTP 501 with the stub message as described — do not
  attempt LLM integration in this prompt.
- The evidence packet background task must not block the HTTP response.

ACCEPTANCE CRITERIA
1. POST /v1/analytics/query/sql with "DELETE FROM loans" returns HTTP 422.
2. POST /v1/analytics/query/sql with "SELECT COUNT(*) FROM loans" returns rows with row_count.
3. POST /v1/analytics/query/nl returns HTTP 501.
4. GET /v1/analytics/queries/saved returns [] for a tenant with no saved queries.
5. POST /v1/analytics/evidence/exam-packet returns status="building" immediately.
6. GET /v1/analytics/evidence/exam-packet/{id} returns the packet record.
```

---

## Phase 6 — Prompt 25-A: Policy Version RSA Signing (PV-007)

**File to modify**: `decision_engine/policy_version_store.py`
**Depends on**: `cryptography` library (already in requirements.txt — verify before coding)
**PRD Reference**: §4.1.2 PV-007

### Coding Prompt

```
Modify the file `decision_engine/policy_version_store.py`.

CONTEXT
The file stores policy versions in a DB table with SHA-256 content hashes and a hash chain.
PV-007 requires an additional RSA-2048 digital signature on each policy version payload.

CHANGES REQUIRED

1. Add two new columns to the policy_versions table DDL:
     `rsa_signature TEXT`      -- Base64-encoded RSA-PSS signature of the version payload
     `signing_key_id TEXT`     -- Identifier of the key used (e.g. "policy-signing-key-v1")

2. Add a migration guard (same pattern as audit log): use ALTER TABLE ADD COLUMN in a
   try/except to add the two columns when they are absent in existing databases.

3. Add a module-level function:
    def sign_version(version_payload: dict, private_key_pem: bytes) -> str:
        """
        Sign the canonical JSON representation of version_payload using RSA-2048 PSS.

        Implementation:
          1. Serialize version_payload to canonical JSON:
             json.dumps(version_payload, sort_keys=True, separators=(',', ':'))
             and encode to UTF-8 bytes.
          2. Load the private key:
             from cryptography.hazmat.primitives.serialization import load_pem_private_key
             private_key = load_pem_private_key(private_key_pem, password=None)
          3. Sign using RSA-PSS with SHA-256:
             from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
             from cryptography.hazmat.primitives import hashes as crypto_hashes
             signature = private_key.sign(
                 canonical_bytes,
                 asym_padding.PSS(
                     mgf=asym_padding.MGF1(crypto_hashes.SHA256()),
                     salt_length=asym_padding.PSS.MAX_LENGTH
                 ),
                 crypto_hashes.SHA256()
             )
          4. Return base64.b64encode(signature).decode('utf-8').
        """

4. Add a module-level function:
    def verify_version_signature(
        version_payload: dict,
        signature_b64: str,
        public_key_pem: bytes
    ) -> bool:
        """
        Verify the RSA-PSS signature of version_payload.

        Implementation:
          1. Serialize version_payload to canonical JSON (same as sign_version).
          2. Load the public key:
             from cryptography.hazmat.primitives.serialization import load_pem_public_key
             public_key = load_pem_public_key(public_key_pem)
          3. Decode signature_b64 from base64.
          4. Call public_key.verify(...) with the same PSS parameters.
          5. Return True if verification succeeds, False if cryptography.exceptions.InvalidSignature.
        """

5. In the existing function that creates a new policy version (identify it by reading the file):
   a. If the env var `POLICY_SIGNING_KEY_PEM` is set, load its value as bytes and call
      `sign_version(version_dict, private_key_pem)`.
   b. Store the result in `rsa_signature` column.
   c. Store `signing_key_id = os.environ.get("POLICY_SIGNING_KEY_ID", "default")`.
   d. If `POLICY_SIGNING_KEY_PEM` is not set, store NULL in both columns (signing is optional
      for dev environments).

CONSTRAINTS
- Use only `cryptography` library (already in requirements.txt).
- Do not generate or hard-code any RSA keys in the source file.
- `verify_version_signature()` must catch `cryptography.exceptions.InvalidSignature` and
  return False (do not re-raise).
- All changes must be backward-compatible: existing version records with NULL rsa_signature
  are valid.

ACCEPTANCE CRITERIA
1. `sign_version({"id": "v1", "rules": []}, private_key_pem)` returns a non-empty base64 string.
2. `verify_version_signature(payload, sig, public_key_pem)` returns True for a valid pair.
3. `verify_version_signature(payload, sig, wrong_public_key_pem)` returns False.
4. `verify_version_signature(payload, "badsig==", public_key_pem)` returns False without raising.
5. Creating a new policy version with POLICY_SIGNING_KEY_PEM unset does not raise.
6. Creating a new policy version with POLICY_SIGNING_KEY_PEM set stores a non-NULL rsa_signature.
```

---

## Phase 7 — Prompt 24-A: GraphQL Analytics API

**File to create**: `analytics_api/src/graphql_schema.py`
**Depends on**: `strawberry-graphql` (add to requirements.txt if not present)
**PRD Reference**: §10.1

### Coding Prompt

```
Create the file `analytics_api/src/graphql_schema.py`.
Also: if `strawberry-graphql` is not in `analytics_api/requirements.txt` (or the top-level
`requirements.txt`), add `strawberry-graphql[fastapi]>=0.220.0` to requirements.txt.

PURPOSE
Expose a GraphQL endpoint at /graphql on the analytics_api FastAPI app. The schema covers
the four major analytics domains: portfolio summary, vintage curves, roll rates, and semantic
glossary.

STRAWBERRY TYPES

    @strawberry.type
    class PortfolioSummary:
        total_applications: int
        approval_rate: float
        average_credit_score: float
        charge_off_rate: float
        tenant_id: str

    @strawberry.type
    class VintageCurvePoint:
        cohort_month: str
        dpd30_rate: float
        dpd60_rate: float
        dpd90_rate: float
        loan_count: int

    @strawberry.type
    class RollRateCell:
        from_bucket: str
        to_bucket: str
        rate: float

    @strawberry.type
    class GlossaryTermGQL:
        name: str
        definition: str
        kind: str
        tenant_id: str | None
        approved: bool

    @strawberry.type
    class AgentInsight:
        query_id: str
        session_id: str
        answer_text: str
        confidence: str
        created_at: str

QUERY TYPE

    @strawberry.type
    class Query:
        @strawberry.field
        async def portfolio_summary(self, tenant_id: str, info: strawberry.types.Info) -> PortfolioSummary:
            """
            Return aggregate stats for the tenant. Query the database using the existing
            analytics DB session from FastAPI context (info.context["db"]).
            Return zeroed-out values if no data found (do not raise).
            """

        @strawberry.field
        async def vintage_curves(
            self, tenant_id: str, cohort_start: str | None = None, info: strawberry.types.Info = strawberry.UNSET
        ) -> list[VintageCurvePoint]:
            """Reuse the same query logic as GET /v1/analytics/vintage-curves."""

        @strawberry.field
        async def roll_rates(self, tenant_id: str, info: strawberry.types.Info) -> list[RollRateCell]:
            """Reuse the same query logic as GET /v1/analytics/roll-rates."""

        @strawberry.field
        async def semantic_glossary(self, tenant_id: str, info: strawberry.types.Info) -> list[GlossaryTermGQL]:
            """
            Load SemanticRegistry for tenant_id, call resolve_all(), return as GlossaryTermGQL list.
            If SemanticRegistry is not available (import error), return [].
            """

        @strawberry.field
        async def agent_insights(
            self, session_id: str, tenant_id: str, info: strawberry.types.Info
        ) -> list[AgentInsight]:
            """
            Call get_ai_audit_records(session_id, db) from ai_audit_log.py.
            Map records to AgentInsight objects. Return [] on import error.
            """

SCHEMA AND ROUTER
    schema = strawberry.Schema(query=Query)

    graphql_app = GraphQLRouter(schema)

WIRE INTO APP
In `analytics_api/src/main.py`:
    from analytics_api.src.graphql_schema import graphql_app
    app.include_router(graphql_app, prefix="/graphql")

CONTEXT INJECTION
Configure the GraphQL router to inject the FastAPI DB session into `info.context`:
    async def get_context(db=Depends(get_db_session)) -> dict:
        return {"db": db}
    graphql_app = GraphQLRouter(schema, context_getter=get_context)

CONSTRAINTS
- Use `strawberry-graphql[fastapi]`.
- All resolvers must be async.
- If a resolver's data dependency (e.g. ai_audit_log, semantic_layer) is unavailable,
  return empty list / zeroed values — do not propagate import errors to the client.
- Do not add authentication to the GraphQL endpoint in v1; add a TODO comment for
  JWT middleware in v2.

ACCEPTANCE CRITERIA
1. `GET /graphql` returns the GraphQL playground/schema introspection UI (HTTP 200).
2. `POST /graphql` with `{"query": "{ portfolioSummary(tenantId: \"t1\") { approvalRate } }"}` returns JSON.
3. `POST /graphql` with invalid query returns GraphQL error response (not HTTP 500).
4. `POST /graphql` semantic_glossary query returns [] without raising when semantic layer is not seeded.
5. The strawberry schema is importable without a running DB.
```

---

## Verification Checklist

After all prompts are implemented, run the following to confirm closure:

```bash
# GAP-22
pytest ai-agent/tests/test_ai_audit_log.py -v

# GAP-23
python -c "from webhooks.models import EventType; print(EventType.AGENT_ANSWER_READY.value)"

# GAP-19
pytest analytics_api/tests/test_semantic_layer.py analytics_api/tests/test_semantic_api.py -v

# GAP-20
pytest ai-agent/tests/test_validator_agent.py ai-agent/tests/test_compliance_gate_agent.py ai-agent/tests/test_formatter_agent.py ai-agent/tests/test_query_builder_agent.py -v

# GAP-21
pytest ai-agent/tests/test_agent_api_contract.py analytics_api/tests/test_analytics_query_api.py -v

# GAP-25
pytest decision_engine/tests/test_policy_version_store.py -v

# GAP-24
pytest analytics_api/tests/test_graphql_api.py -v

# Full regression (ensure no regressions in closed gaps)
pytest --tb=short -q
```

---

*End of Implementation Plan — 2026-04-26*
