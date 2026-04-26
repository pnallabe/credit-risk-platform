# Tenant-Scoped Semantic Layer — Implementation Plan

**Platform:** credit-risk-platform
**PRD Reference:** Unified ILOL PRD v3.0.0 § 4.7 (Module 7)
**Architectural Audit:** `docs/TENANT_SEMANTIC_LAYER_AUDIT.md`
**Status:** Ready for implementation

---

## Overview

This plan implements Module 7 of the ILOL PRD: the Tenant-Scoped Semantic Layer. Each coding prompt below is self-contained, references the exact file(s) to modify or create, and is sequenced so that each prompt depends only on work completed in prior steps. Execute prompts in order. Do not skip steps.

**Total work items:** 21 prompts across 8 phases.

---

## Phase A — Physical Schema Foundation
*Goal: Lay the BigQuery table schemas and RBAC definitions that every other layer depends on. No agent or API code yet.*

---

### Prompt 1 — Fix `fair_lending_reports` schema and add 4 new BigQuery table schemas

**File:** `db/bigquery_schema.py`

```
You are modifying credit-risk-platform/db/bigquery_schema.py.

TASK 1: Fix a known schema gap.
In FAIR_LENDING_REPORTS_SCHEMA, add two new nullable columns immediately after the last existing field:
  - Field name: "portfolio_as_of_date", type: DATE, mode: NULLABLE,
    description: "Reporting cut-off date for the portfolio snapshot used in this fair-lending analysis"
  - Field name: "cohort_definition", type: STRING, mode: NULLABLE,
    description: "JSON-encoded filter definition used to select the comparison cohort (e.g., product, channel, date range)"

TASK 2: Add four new schema constants at the end of the file, before TABLE_CATALOGUE.

Add ANALYTICS_QUERY_LOG_SCHEMA with these fields (all REQUIRED unless noted):
  - query_id: STRING REQUIRED — "UUIDv4 unique identifier for this analytics query"
  - tenant_id: STRING REQUIRED — "Tenant scope — required on all rows; matches JWT tenant_id claim"
  - user_email: STRING REQUIRED — "Email of the submitting user (PII — access is audit-logged)"
  - role: STRING REQUIRED — "Platform RBAC role of the submitting user at query time"
  - query_type: STRING REQUIRED — "'sql' | 'nl' — whether the query was SQL-direct or natural language"
  - raw_input: STRING NULLABLE — "Original NL question text or raw SQL as submitted"
  - generated_sql: STRING NULLABLE — "Final executed SQL after validation and tenant_id injection"
  - sql_hash: STRING REQUIRED — "SHA-256 of normalized generated_sql for deduplication and audit"
  - row_count: INTEGER NULLABLE — "Number of rows returned by the query"
  - latency_ms: INTEGER NULLABLE — "End-to-end request latency in milliseconds"
  - status: STRING REQUIRED — "'success' | 'blocked' | 'error'"
  - block_reason: STRING NULLABLE — "Populated when status='blocked'; describes which validation step blocked the query"
  - submitted_at: TIMESTAMP REQUIRED — "UTC timestamp when the query was submitted"

Add SAVED_QUERIES_SCHEMA:
  - query_id: STRING REQUIRED — "UUIDv4"
  - tenant_id: STRING REQUIRED — "Owning tenant"
  - name: STRING REQUIRED — "Human-readable name for the saved query"
  - description: STRING NULLABLE — "Optional description for the query catalogue"
  - sql_text: STRING REQUIRED — "Saved SQL (always tenant-scoped; tenant_id filter verified at save time)"
  - created_by: STRING REQUIRED — "Email of the user who saved the query"
  - created_at: TIMESTAMP REQUIRED — "UTC timestamp of creation"
  - is_active: BOOLEAN REQUIRED — "False = soft-deleted"

Add EXAM_PACKETS_SCHEMA:
  - packet_id: STRING REQUIRED — "UUIDv4"
  - tenant_id: STRING REQUIRED — "Owning tenant"
  - exam_type: STRING REQUIRED — "'regulatory' | 'internal_audit' | 'model_validation'"
  - period_start: DATE REQUIRED — "First day of the evidence window"
  - period_end: DATE REQUIRED — "Last day of the evidence window"
  - queries_json: STRING REQUIRED — "JSON array of {query_id, sql, result_hash, executed_at} — all SQL evidence"
  - citations_json: STRING REQUIRED — "JSON array of {fact, source_table, column, query_id, timestamp}"
  - semantic_registry_snapshot_json: STRING NULLABLE — "JSON snapshot of all active tenant semantic entries at packet generation time"
  - pdf_gcs_uri: STRING NULLABLE — "GCS URI of the rendered PDF exam packet"
  - created_by: STRING REQUIRED — "Analyst email"
  - approved_by: STRING NULLABLE — "Four-eyes approver email"
  - status: STRING REQUIRED — "'draft' | 'pending_approval' | 'approved' | 'submitted'"
  - created_at: TIMESTAMP REQUIRED — "UTC creation time"

Add TENANT_SEMANTIC_REGISTRY_SCHEMA:
  - entry_id: STRING REQUIRED — "UUIDv4 unique identifier for this semantic entry"
  - tenant_id: STRING REQUIRED — "Owning tenant"
  - entry_type: STRING REQUIRED — "'glossary_term' | 'table_schema' | 'metric' | 'synonym_override'"
  - name: STRING REQUIRED — "Term, table, or metric name — unique per (tenant_id, entry_type, version)"
  - version: STRING REQUIRED — "Semantic version e.g. '1.0.0'"
  - definition_json: STRING REQUIRED — "JSON-encoded entry definition (shape varies by entry_type; see PRD §4.7.3)"
  - definition_sha256: STRING REQUIRED — "SHA-256 hex digest of definition_json — used for tamper detection at query time"
  - approved_by: STRING REQUIRED — "Email of the approving user — four-eyes required for table_schema entries"
  - is_active: BOOLEAN REQUIRED — "False = deprecated or superseded by a newer version"
  - created_at: TIMESTAMP REQUIRED — "UTC timestamp of insert"

TASK 3: Add all four new schemas to TABLE_CATALOGUE with appropriate descriptions.

CONSTRAINTS:
- Use the existing _f() helper for all field definitions — do not change _f().
- Follow the exact same pattern as existing schemas in the file.
- Do not change any existing schema constants.
- Do not add any new imports.
```

---

### Prompt 2 — Add `credit_analyst` and `external_service` roles to RBAC

**File:** `compliance/rbac.py`

```
You are modifying credit-risk-platform/compliance/rbac.py.

TASK 1: Add two new role literals to the Role type.
In the Role Literal type definition, add after "executive":
  "credit_analyst"
  "external_service"

TASK 2: Add two new four-eyes rules to FOUR_EYES_RULES.
Add after the existing "policy_override" entry:

"credit_policy_amendment": {
    "author_role": "credit_analyst",
    "approver_role": "cro",
    "prohibited_overlap": True,
    "description": "A credit analyst's proposed policy threshold amendment requires CRO sign-off before activation",
},
"tenant_schema_registration": {
    "author_role": "credit_analyst",
    "approver_role": "data_engineer",
    "prohibited_overlap": True,
    "description": "Registering a net-new tenant data source in the semantic registry requires data engineering approval",
},

TASK 3: Add two new entries to RBAC_MATRIX.

For "credit_analyst":
  cc_origination_policy:    ["READ", "WRITE:draft", "WRITE:propose_amendment"]
  mlflow_registry:          ["READ"]
  audit_log:                ["READ:all"]
  compliance_events:        ["READ"]
  regulatory_thresholds:    ["READ"]
  policy_approval_log:      ["READ:all"]
  emergency_override:       []
  analytics_queries:        ["READ", "WRITE:own", "EXECUTE"]
  saved_queries:            ["READ", "WRITE:own"]
  exam_packets:             ["READ", "WRITE:own", "WRITE:submit"]
  tenant_semantic_registry: ["READ", "WRITE:propose"]
  dashboards:               ["READ", "WRITE:own"]
  pl_reports:               ["READ", "EXECUTE"]
  fair_lending_reports:     ["READ"]

For "external_service":
  cc_origination_policy:    ["READ"]
  mlflow_registry:          []
  audit_log:                []
  compliance_events:        []
  regulatory_thresholds:    []
  policy_approval_log:      []
  emergency_override:       []
  analytics_queries:        ["READ", "EXECUTE:scoped"]
  saved_queries:            ["READ:scoped"]
  exam_packets:             []
  tenant_semantic_registry: ["READ:scoped"]
  dashboards:               ["READ:scoped"]
  pl_reports:               []
  fair_lending_reports:     []

CONSTRAINTS:
- Only add to Role Literal, FOUR_EYES_RULES, and RBAC_MATRIX. Do not change any other code.
- The new RBAC_MATRIX entries must be inside the existing RBAC_MATRIX dict, not outside it.
- Do not add imports.
```

---

## Phase B — Platform Semantic Core
*Goal: Build the platform-level glossary and metric registry. These are pure data files with no external dependencies.*

---

### Prompt 3 — Create the platform glossary

**File:** `analytics_api/src/glossary.py` *(new file)*

```
Create analytics_api/src/glossary.py.

This module defines the platform-level semantic glossary — the canonical vocabulary that
the NL query agent uses to translate business terms into SQL predicates and column references.

Define a Pydantic BaseModel called GlossaryEntry with these fields:
  - name: str — canonical lookup key (lowercase, hyphenated)
  - display_name: str — human-readable label
  - description: str — plain-English definition
  - synonyms: list[str] — alternative terms that resolve to this entry
  - sql_predicate: Optional[str] = None — SQL WHERE predicate fragment (e.g., "is_thin_file = 1")
  - column_ref: Optional[str] = None — simple column reference (e.g., "pd_score")
  - applies_to_tables: list[str] = [] — tables where this predicate/column is valid
  - source_contract: Optional[str] = None — data_contracts module path this was harvested from
  - canonical: bool = True — True for platform entries; False for tenant overrides

Create a module-level dict CREDIT_GLOSSARY: dict[str, GlossaryEntry] with at minimum these entries:

  "thin-file":
    display_name: "Thin File Applicant"
    description: "Applicant with fewer than 5 tradelines on file — flagged for alternative data consideration"
    synonyms: ["thin file", "thin-file applicant", "limited credit history", "sparse credit"]
    sql_predicate: "is_thin_file = 1"
    applies_to_tables: ["loan_applications"]
    source_contract: "data_contracts.v1.features.DEFAULT_FEATURE_LIST"

  "approved":
    display_name: "Approved Decision"
    synonyms: ["approve", "green", "accepted", "originated"]
    sql_predicate: "decision = 'APPROVE'"
    applies_to_tables: ["credit_decisions"]
    source_contract: "data_contracts.v1.decisions.DecisionLabelV1"

  "rejected":
    display_name: "Rejected Decision"
    synonyms: ["declined", "denied", "rejected", "red", "adverse"]
    sql_predicate: "decision = 'REJECT'"
    applies_to_tables: ["credit_decisions"]
    source_contract: "data_contracts.v1.decisions.DecisionLabelV1"

  "manual-review":
    display_name: "Manual Review"
    synonyms: ["pend", "refer", "referred", "review queue", "manual", "exception queue"]
    sql_predicate: "decision = 'MANUAL_REVIEW'"
    applies_to_tables: ["credit_decisions"]
    source_contract: "data_contracts.v1.decisions.DecisionLabelV1"

  "charged-off":
    display_name: "Charged Off"
    synonyms: ["charge-off", "charged off", "write-off", "written off", "CO"]
    sql_predicate: "delinquency_bucket = 'charged_off'"
    applies_to_tables: ["roll_rates"]
    source_contract: "data_contracts.v1.portfolio.DelinquencyBucketV1"

  "approval-rate":
    display_name: "Approval Rate"
    description: "Share of applications that received an APPROVE decision"
    synonyms: ["pass rate", "acceptance rate", "origination rate", "approval %"]
    sql_predicate: "COUNTIF(decision = 'APPROVE') / COUNT(*)"
    applies_to_tables: ["credit_decisions"]
    source_contract: None

  "pd-score":
    display_name: "Probability of Default Score"
    synonyms: ["PD score", "default score", "probability of default", "risk score"]
    column_ref: "pd_score"
    applies_to_tables: ["model_scores"]
    source_contract: "data_contracts.v1.decisions.DecisionExplanationV1"

  "high-risk":
    display_name: "High Risk Band"
    synonyms: ["high risk", "high band", "high PD"]
    sql_predicate: "pd_band = 'high'"
    applies_to_tables: ["model_scores"]
    source_contract: "data_contracts.v1.decisions.PDBandV1"

  "medium-risk":
    display_name: "Medium Risk Band"
    synonyms: ["medium risk", "medium band", "moderate risk"]
    sql_predicate: "pd_band = 'medium'"
    applies_to_tables: ["model_scores"]
    source_contract: "data_contracts.v1.decisions.PDBandV1"

  "low-risk":
    display_name: "Low Risk Band"
    synonyms: ["low risk", "low band", "prime"]
    sql_predicate: "pd_band = 'low'"
    applies_to_tables: ["model_scores"]
    source_contract: "data_contracts.v1.decisions.PDBandV1"

Add a module-level helper function:
  def lookup(term: str) -> Optional[GlossaryEntry]

  Looks up term by checking:
  1. Exact key match in CREDIT_GLOSSARY
  2. Case-insensitive key match
  3. Synonym match across all entries
  Returns None if not found.

CONSTRAINTS:
- Use Pydantic v2 (model_config = ConfigDict(frozen=True)).
- Do not import from analytics_api internals — this is a pure data module.
- No database calls. All data is in-memory constants.
```

---

### Prompt 4 — Create the platform metric registry

**File:** `analytics_api/src/metric_registry.py` *(new file)*

```
Create analytics_api/src/metric_registry.py.

This module defines the platform-level named metric registry. Each metric has a name,
description, formula SQL (with @dataset placeholder), and metadata.

Define a Pydantic BaseModel called MetricDefinition with these fields:
  - name: str — machine-readable key (snake_case)
  - display_name: str
  - description: str
  - formula_sql: str — SQL expression using @dataset placeholder; must be a complete
    aggregation expression that can be embedded in a SELECT clause
  - base_table: str — primary table this metric queries
  - required_time_filter_column: Optional[str] = None — if set, queries must include
    a WHERE filter on this column (prevents full-table scans)
  - unit: Literal["percentage", "currency_usd", "count", "ratio", "score", "basis_points"]
  - source_contract: Optional[str] = None

Create METRIC_REGISTRY: dict[str, MetricDefinition] with these entries:

  "approval_rate":
    display_name: "Approval Rate"
    description: "Share of applications that received an APPROVE decision in the period"
    formula_sql: "COUNTIF(decision = 'APPROVE') / NULLIF(COUNT(*), 0)"
    base_table: "credit_decisions"
    required_time_filter_column: "submitted_at"
    unit: "percentage"
    source_contract: "data_contracts.v1.decisions.DecisionLabelV1"

  "rejection_rate":
    display_name: "Rejection Rate"
    formula_sql: "COUNTIF(decision = 'REJECT') / NULLIF(COUNT(*), 0)"
    base_table: "credit_decisions"
    required_time_filter_column: "submitted_at"
    unit: "percentage"

  "manual_review_rate":
    display_name: "Manual Review Rate"
    formula_sql: "COUNTIF(decision = 'MANUAL_REVIEW') / NULLIF(COUNT(*), 0)"
    base_table: "credit_decisions"
    required_time_filter_column: "submitted_at"
    unit: "percentage"

  "charge_off_rate":
    display_name: "Charge-Off Rate"
    description: "Share of accounts that have been charged off (120+ DPD)"
    formula_sql: "COUNTIF(delinquency_bucket = 'charged_off') / NULLIF(COUNT(*), 0)"
    base_table: "roll_rates"
    required_time_filter_column: "cohort_month"
    unit: "percentage"
    source_contract: "data_contracts.v1.portfolio.DelinquencyBucketV1"

  "net_loss_rate":
    display_name: "Net Loss Rate"
    description: "Net credit losses as a fraction of outstanding balance"
    formula_sql: "SUM(net_loss_amount) / NULLIF(SUM(outstanding_balance), 0)"
    base_table: "loan_applications"
    required_time_filter_column: "submitted_at"
    unit: "percentage"

  "expected_loss":
    display_name: "Expected Loss"
    description: "PD × LGD × EAD — model-predicted credit loss amount"
    formula_sql: "SUM(pd_score * lgd_estimate * loan_amount)"
    base_table: "model_scores"
    required_time_filter_column: "submitted_at"
    unit: "currency_usd"

  "fico_distribution":
    display_name: "FICO Score Band Distribution"
    description: "Count of applications by FICO band"
    formula_sql: "COUNT(*)"
    base_table: "loan_applications"
    required_time_filter_column: "submitted_at"
    unit: "count"

  "vintage_cumulative_default":
    display_name: "Vintage Cumulative Default Rate"
    formula_sql: "MAX(cumulative_default_rate)"
    base_table: "vintage_curves"
    required_time_filter_column: "cohort_month"
    unit: "percentage"
    source_contract: "data_contracts.v1.portfolio.VintageCohortV1"

  "dir_score":
    display_name: "Disparate Impact Ratio (DIR)"
    description: "Approval rate for protected class divided by approval rate for control group. Values below 0.80 trigger the 4/5ths rule threshold."
    formula_sql: "protected_approval_rate / NULLIF(control_approval_rate, 0)"
    base_table: "fair_lending_reports"
    required_time_filter_column: "report_timestamp"
    unit: "ratio"

Add a helper function:
  def get(name: str) -> Optional[MetricDefinition]
  Returns the metric by exact name or None.

CONSTRAINTS:
- Pydantic v2, frozen=True.
- No imports from analytics_api internals.
- No database calls. All data is in-memory.
```

---

## Phase C — Tenant Registry and Analytics Scope
*Goal: Build the core runtime components that all endpoints depend on.*

---

### Prompt 5 — Create the analytics scope dependency

**File:** `analytics_api/src/analytics_scope.py` *(new file)*

```
Create analytics_api/src/analytics_scope.py.

This module provides the AnalyticsScope Pydantic model and the resolve_analytics_scope
FastAPI dependency. Every analytics endpoint uses this dependency instead of calling
verify_bearer directly.

Import from:
  - analytics_api.src.glossary: GlossaryEntry, CREDIT_GLOSSARY, lookup as glossary_lookup
  - analytics_api.src.metric_registry: MetricDefinition, METRIC_REGISTRY

Define AnalyticsScope(BaseModel) with fields:
  - tenant_id: str
  - user_email: str
  - role: str
  - allowed_tables: frozenset[str]
  - merged_glossary: dict[str, GlossaryEntry]  — platform defaults + tenant overrides
  - metrics: dict[str, MetricDefinition]        — platform + tenant metrics
  - require_tenant_filter: bool = True

The list of PLATFORM_TABLES must be a module-level constant (frozenset) containing all table
names from db.bigquery_schema.TABLE_CATALOGUE. Hard-code the initial list:
  {"loan_applications", "feature_vectors", "model_scores", "credit_decisions",
   "explanations", "fair_lending_reports", "drift_reports", "experiment_results",
   "model_registry", "analytics_query_log", "saved_queries", "exam_packets"}

Define an async function resolve_analytics_scope that:
  1. Calls verify_bearer (imported from analytics_api.src.main) to get JWT payload
  2. Extracts tenant_id, user_email (from "sub" claim), role (from "role" claim, default "credit_analyst")
  3. Starts with merged_glossary = dict(CREDIT_GLOSSARY)  (shallow copy)
  4. Starts with metrics = dict(METRIC_REGISTRY)           (shallow copy)
  5. Starts with allowed_tables = set(PLATFORM_TABLES)
  6. Attempts to load tenant semantic entries by calling load_tenant_entries() from
     analytics_api.src.tenant_semantic_registry (import lazily inside try/except to avoid
     circular import — if the module is not yet available, skip gracefully)
  7. For each active tenant entry:
     - entry_type "glossary_term" or "synonym_override": parse definition_json and add/override
       the corresponding GlossaryEntry in merged_glossary
     - entry_type "metric": parse definition_json and add/override the MetricDefinition in metrics
     - entry_type "table_schema": add the table name to allowed_tables
  8. Sets require_tenant_filter = True always (never False — even for internal roles)
  9. Returns AnalyticsScope(...)

For the import of verify_bearer: use a lazy import inside the function to avoid circular
dependency with main.py.

CONSTRAINTS:
- This must be usable as a FastAPI Depends() dependency.
- The function signature for FastAPI injection must accept credentials via Security(bearer_scheme).
- If tenant semantic registry load fails (e.g., DB unavailable), log a warning and continue
  with platform-only scope (do not raise).
- Use Pydantic v2.
```

---

### Prompt 6 — Create the tenant semantic registry service

**File:** `analytics_api/src/tenant_semantic_registry.py` *(new file)*

```
Create analytics_api/src/tenant_semantic_registry.py.

This module manages CRUD for tenant semantic registry entries in the
tenant_semantic_registry BigQuery/SQLite table.

Define a Pydantic model TenantSemanticEntry with fields:
  - entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
  - tenant_id: str
  - entry_type: Literal["glossary_term", "table_schema", "metric", "synonym_override"]
  - name: str
  - version: str = "1.0.0"
  - definition_json: dict[str, Any]
  - definition_sha256: str = ""  — computed at registration, not supplied by caller
  - approved_by: str
  - is_active: bool = True
  - created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

The definition_sha256 must always be computed server-side:
  import hashlib, json
  definition_sha256 = hashlib.sha256(
      json.dumps(definition_json, sort_keys=True).encode()
  ).hexdigest()

Implement these async functions. All use the DATABASE_URL env var for SQLite in dev,
BigQuery in prod (follow the exact same _QueryBackend pattern from analytics_api/src/main.py):

async def load_tenant_entries(
    tenant_id: str,
    entry_type: Optional[str] = None,
    db_url: str = DATABASE_URL,
) -> list[TenantSemanticEntry]:
  """Load all is_active=True entries for a tenant, optionally filtered by entry_type."""
  -- SELECT from tenant_semantic_registry WHERE tenant_id = :tenant_id AND is_active = 1
  -- optionally AND entry_type = :entry_type

async def register_entry(
    entry: TenantSemanticEntry,
    author_email: str,
    approver_email: str,
    db_url: str = DATABASE_URL,
) -> TenantSemanticEntry:
  """
  Append a new entry (never update in place — append-only pattern).
  Steps:
  1. Compute definition_sha256 from entry.definition_json
  2. For entry_type = "table_schema": call enforce_four_eyes("tenant_schema_registration",
     author_email, approver_email) from compliance.rbac — raises SeparationOfDutiesViolation
     if author == approver
  3. Set entry.created_at to UTC now
  4. INSERT into tenant_semantic_registry
  5. For entry_type = "table_schema": call register_tenant_source() from
     data_lineage.lineage_tracker (see Prompt 8)
  6. Return the saved entry
  """

async def verify_schema_hash(
    tenant_id: str,
    table_name: str,
    registered_sha256: str,
    current_columns: list[dict],
) -> bool:
  """
  Compare the SHA-256 of current_columns (sorted by name) against registered_sha256.
  current_columns is a list of {"name": str, "type": str} dicts — caller is responsible
  for fetching these from INFORMATION_SCHEMA.COLUMNS.
  Returns True if hashes match (no drift), False if drift detected.
  """

async def deactivate_entry(
    entry_id: str,
    tenant_id: str,
    db_url: str = DATABASE_URL,
) -> None:
  """Set is_active = False for the specified entry. Does not delete."""

CONSTRAINTS:
- Append-only: register_entry must never UPDATE an existing row. If a name+version already
  exists for this tenant, raise ValueError("Entry already exists. Increment the version.").
- Use the same SQLite-compatible SQL that main.py uses for the dev path.
- Import DATABASE_URL from the same env var pattern as main.py (os.getenv).
- Do not import from analytics_api.src.analytics_scope (avoid circular import).
```

---

## Phase D — SQL Validation Pipeline
*Goal: The safety layer that validates all SQL before execution.*

---

### Prompt 7 — Create the SQL validator

**File:** `analytics_api/src/sql_validator.py` *(new file)*

```
Create analytics_api/src/sql_validator.py.

This module validates SQL queries before execution. It uses sqlglot for AST-level
analysis (not regex). Install sqlglot if not present.

Define a Pydantic model ValidationResult with fields:
  - is_valid: bool
  - validated_sql: Optional[str] = None  — post-injection SQL if valid
  - sql_hash: Optional[str] = None       — SHA-256 of validated_sql
  - block_reason: Optional[str] = None   — populated when is_valid=False
  - pii_columns_stripped: list[str] = []

Define these module-level constants:
  BLOCKED_STATEMENT_TYPES = {"insert", "update", "delete", "drop", "create", "alter",
                              "truncate", "exec", "execute", "merge", "call"}

  PII_COLUMNS = frozenset({
      "ssn", "tax_id", "date_of_birth", "street_address", "city", "zip_code",
      "applicant_name", "first_name", "last_name", "phone_number", "email_address",
      "ip_address", "device_id"
  })

  PARTITION_COLUMNS = frozenset({
      "submitted_at", "created_at", "decision_at", "report_timestamp",
      "cohort_month", "ingested_at"
  })

Implement the main function:
  def validate(
      sql: str,
      scope: "AnalyticsScope",   — use TYPE_CHECKING import to avoid circular dep
      dialect: str = "bigquery",
  ) -> ValidationResult:

Pipeline (in order, fail-fast — return ValidationResult(is_valid=False) on first failure):

  Step 1 — Parse
    Use sqlglot.parse(sql, dialect=dialect). If parse raises an exception or returns
    an empty list, return block_reason="SQL syntax error: {exception message}"

  Step 2 — Statement type check
    Get the first statement. Convert to lowercase class name.
    If any part of BLOCKED_STATEMENT_TYPES appears, return block_reason indicating
    the blocked statement type.
    Only SELECT (and WITH...SELECT) statements are allowed.

  Step 3 — Table allowlist
    Extract all table names from the AST (use sqlglot.exp.Table nodes).
    For each table name: if it is not in scope.allowed_tables, return
    block_reason="Table '{table_name}' is not in your analytics scope.
    Register it via POST /v1/analytics/tenant/schema/register."

  Step 4 — Tenant filter injection
    For each table reference in the AST that lacks a WHERE clause filtering on tenant_id:
    Inject AND tenant_id = '{scope.tenant_id}' into the WHERE clause.
    Use sqlglot AST manipulation (not string replacement).

  Step 5 — PII column guard (for external_service role only)
    If scope.role == "external_service":
      Scan SELECT expressions for any column name in PII_COLUMNS.
      If found: remove the column from the SELECT list (strip silently) and add its
      name to pii_columns_stripped list.
      If stripping would leave an empty SELECT, return block_reason="Query selects only
      PII columns which are not available to external_service role."

  Step 6 — Partition filter guard
    Check that at least one table reference in the WHERE clause filters on a column
    in PARTITION_COLUMNS. If no partition filter is present on any table,
    return block_reason="Query has no partition filter (e.g., WHERE submitted_at >= ...).
    Add a time-bounded filter to prevent full-table scans."

  Step 7 — Compute hash and return
    Generate the final SQL string from the modified AST.
    Compute sql_hash = hashlib.sha256(validated_sql.encode()).hexdigest()
    Return ValidationResult(is_valid=True, validated_sql=..., sql_hash=...,
                            pii_columns_stripped=...)

CONSTRAINTS:
- Use sqlglot AST manipulation throughout — never string concatenation on SQL.
- The validate() function must be synchronous (not async) — it does no I/O.
- Import AnalyticsScope with TYPE_CHECKING guard to avoid circular imports.
```

---

## Phase E — Analytics API Routers
*Goal: Build the HTTP layer. Each router imports from the modules built in phases B–D.*

---

### Prompt 8 — Create the SQL query router

**File:** `analytics_api/src/routers/sql_query.py` *(new file)*

```
Create analytics_api/src/routers/sql_query.py.

This module implements the SQL query endpoints. Create an APIRouter with prefix="/v1/analytics".

Import and use AnalyticsScope from analytics_api.src.analytics_scope.
Import ValidationResult and validate from analytics_api.src.sql_validator.
Use the _QueryBackend and _db instances from analytics_api.src.main (export these
from main.py so routers can import them — add __all__ or direct import in main.py).

Define Pydantic request/response models:

  SqlQueryRequest:
    - sql: str = Field(..., max_length=50_000)
    - dry_run: bool = False  — if True, validate but do not execute

  QueryResultRow = dict[str, Any]

  SqlQueryResponse:
    - query_id: str
    - status: Literal["success", "blocked", "dry_run_ok"]
    - rows: list[QueryResultRow] = []
    - row_count: int = 0
    - sql_hash: Optional[str]
    - validated_sql: Optional[str]
    - block_reason: Optional[str]
    - pii_columns_stripped: list[str] = []
    - latency_ms: int

  SaveQueryRequest:
    - sql: str
    - name: str = Field(..., max_length=200)
    - description: Optional[str] = None

Implement these endpoints:

  POST /v1/analytics/query/sql
    - Requires role in {"credit_analyst", "external_service", "auditor", "cro", "executive"}
    - Calls validate(request.sql, scope)
    - If not valid: log to analytics_query_log with status="blocked", return 422 with block_reason
    - If dry_run=True: return SqlQueryResponse(status="dry_run_ok", ...)
    - Execute using _db.run_sql(result.validated_sql, {})
    - Log to analytics_query_log with status="success"
    - Return SqlQueryResponse with rows and metadata
    - On any execution error: log status="error", return 500

  GET /v1/analytics/queries/saved
    - Returns saved queries for the authenticated tenant (filtered by tenant_id from scope)
    - Cursor pagination: accepts ?limit=50&cursor=<last_query_id>
    - Only returns is_active=True queries

  POST /v1/analytics/queries/save
    - Validates the SQL using validate() before saving
    - If invalid, return 422 with block_reason
    - Inserts into saved_queries table via _db
    - Returns the saved query record

Logging to analytics_query_log: write a helper function _log_query(scope, query_id, query_type,
raw_input, generated_sql, sql_hash, row_count, latency_ms, status, block_reason) that calls
_db.run_sql with an INSERT into analytics_query_log.

CONSTRAINTS:
- query_id must be generated with uuid.uuid4() at the start of each request.
- latency_ms must be measured from request receipt to response generation.
- Never log the raw JWT in any log statement.
- Return 401 if scope resolution fails, 403 if role is not permitted.
```

---

### Prompt 9 — Create the NL query agent

**File:** `analytics_api/src/nl_query_agent.py` *(new file)*

```
Create analytics_api/src/nl_query_agent.py.

This module implements the NL-to-SQL pipeline. It does not use LangGraph or LangChain.
It uses the configured LLM provider (OpenAI or Google Gemini) via direct API calls.

Import LLM client from the existing llm/ module if one exists; otherwise use openai.OpenAI
with the OPENAI_API_KEY env var. Detect provider from the env var LLM_PROVIDER
("openai" | "gemini", default "openai").

Define a Pydantic model NlQueryResult with fields:
  - query_id: str
  - question: str
  - answer: str
  - citations: list[dict]     — each: {claim, source_table, column, query_id, timestamp}
  - generated_sql: str
  - sql_hash: str
  - rows: list[dict]
  - row_count: int
  - confidence: Literal["HIGH", "MEDIUM", "LOW"]
  - latency_ms: int
  - pii_columns_stripped: list[str] = []

Implement the pipeline as a single async function:
  async def run(
      question: str,
      scope: AnalyticsScope,
      query_id: str,
  ) -> NlQueryResult:

Pipeline steps (sequential, fail-fast with meaningful error messages):

  STEP 1 — Schema context injection
    Build a schema_context string containing:
    - Allowed tables with column names (use TABLE_CATALOGUE from db.bigquery_schema)
    - scope.merged_glossary as JSON (name → {description, sql_predicate, synonyms})
    - scope.metrics as JSON (name → {description, formula_sql, base_table})
    - tenant_id value for injection

  STEP 2 — SQL generation (LLM call)
    Call LLM with this system prompt (verbatim, do not paraphrase):
    ---
    You are a BigQuery SQL expert generating queries for a credit risk analytics platform.
    Tenant ID: {scope.tenant_id}
    Role: {scope.role}

    Rules (MANDATORY — violation causes query rejection):
    1. Generate only SELECT statements. No INSERT, UPDATE, DELETE, DROP, CREATE.
    2. Always include WHERE tenant_id = '{scope.tenant_id}' for every table that has a tenant_id column.
    3. Only reference tables listed in AVAILABLE_TABLES below.
    4. Use ONLY column names that appear in the schema below. Never invent column names.
    5. Always include a time-bounded WHERE filter on a partition column (submitted_at, created_at, etc.).
    6. Use @dataset placeholder for table references: `@dataset.table_name`.
    7. When a glossary term maps to a sql_predicate, use that predicate exactly.
    8. When a metric name maps to formula_sql, use that formula exactly.
    9. Output only raw SQL. No markdown, no explanation, no comments.

    AVAILABLE_TABLES:
    {schema_context}
    ---
    User question: {question}

  STEP 3 — SQL validation
    Call validate(raw_sql, scope) from sql_validator.
    If not valid: raise ValueError(f"Generated SQL blocked: {result.block_reason}")
    This is a hard failure — do not retry with a different SQL.

  STEP 4 — Execution
    Call _db.run_sql(result.validated_sql, {"tenant_id": scope.tenant_id})
    If rows is empty: set confidence=LOW, answer= "No data found for this query in the
    requested period. [Source: {table_name} | Query: {query_id} | Date: {now}]"
    Return early with this answer — do not proceed to Step 5.

  STEP 5 — Answer synthesis (LLM call)
    Call LLM with instruction to synthesize a 2–4 sentence answer from the rows.
    System prompt must include: "Every numeric claim in your answer MUST end with
    [Source: {table_name}.{column} | Query: {query_id} | Date: {today}].
    If you cannot cite a number, do not state it."

  STEP 6 — Citation enforcement
    Parse the answer text. Find all numeric tokens (integers, floats, percentages).
    For each numeric token: verify it has an adjacent [Source: ...] citation.
    If any uncited numeric is found: strip the sentence containing it and append:
    "[Note: {count} uncited numeric(s) removed to comply with anti-hallucination policy]"

  STEP 7 — Confidence scoring
    HIGH: row_count > 30 and no pii_columns_stripped
    MEDIUM: 5 <= row_count <= 30
    LOW: row_count < 5

  STEP 8 — Return NlQueryResult

CONSTRAINTS:
- LLM temperature MUST be 0.0 for SQL generation (Step 2). No randomness.
- LLM temperature MUST be 0.1 for answer synthesis (Step 5).
- If any LLM call fails: raise immediately — do not return a partial answer.
- The function is async — use await for all LLM calls (use asyncio.to_thread for sync clients).
```

---

### Prompt 10 — Create the NL query router

**File:** `analytics_api/src/routers/nl_query.py` *(new file)*

```
Create analytics_api/src/routers/nl_query.py.

Import run from analytics_api.src.nl_query_agent.
Import AnalyticsScope from analytics_api.src.analytics_scope.
Use _log_query from analytics_api.src.routers.sql_query.

Define request/response models:

  NlQueryRequest:
    - question: str = Field(..., min_length=5, max_length=2000)
    - strict_mode: bool = True  — if True, plan is shown but auto-executed (future: user approval)

  NlQueryResponse:
    - query_id: str
    - question: str
    - answer: str
    - citations: list[dict]
    - sql_hash: str
    - row_count: int
    - confidence: str
    - latency_ms: int
    - code_artifact: dict  — {"sql": validated_sql, "query_id": query_id, "executed_at": now}
    - pii_columns_stripped: list[str] = []

Implement:

  POST /v1/analytics/query/nl
    Allowed roles: credit_analyst, auditor, cro, executive (not external_service)

    1. Generate query_id = str(uuid.uuid4())
    2. Record start_time
    3. Call await nl_query_agent.run(request.question, scope, query_id)
    4. Log to analytics_query_log via _log_query (query_type="nl")
    5. Return NlQueryResponse with code_artifact containing the exact SQL

    On ValueError (SQL blocked): return HTTP 422 with detail containing the block_reason
    On any other exception: log error, return HTTP 500

CONSTRAINTS:
- external_service role is explicitly excluded — NL queries require credit_analyst or higher.
- The code_artifact field in the response is non-optional — NlQueryResponse must always
  include the SQL. If nl_query_agent.run() returns no generated_sql, return HTTP 500.
```

---

### Prompt 11 — Create the tenant semantic registry router

**File:** `analytics_api/src/routers/tenant_semantic.py` *(new file)*

```
Create analytics_api/src/routers/tenant_semantic.py.

Import TenantSemanticEntry, register_entry, load_tenant_entries, verify_schema_hash,
deactivate_entry from analytics_api.src.tenant_semantic_registry.
Import AnalyticsScope from analytics_api.src.analytics_scope.
Import CREDIT_GLOSSARY from analytics_api.src.glossary.
Import METRIC_REGISTRY from analytics_api.src.metric_registry.

Define request/response models:

  RegisterSchemaRequest:
    - name: str — table name
    - bigquery_table: str — fully qualified BQ table ID
    - join_key: str
    - join_to: str — platform table this joins to
    - columns: list[dict]  — each: {"name": str, "type": str, "description": str}
    - approver_email: str  — second approver (four-eyes)

  ProposeGlossaryTermRequest:
    - entry_type: Literal["glossary_term", "metric", "synonym_override"]
    - name: str
    - definition: dict  — the entry definition (shape per PRD §4.7.3)
    - version: str = "1.0.0"
    - approver_email: str

  GlossaryResponse:
    - platform_terms: list[dict]  — from CREDIT_GLOSSARY
    - platform_metrics: list[dict]  — from METRIC_REGISTRY
    - tenant_terms: list[dict]    — active glossary_term + synonym_override entries
    - tenant_metrics: list[dict]  — active metric entries
    - tenant_tables: list[dict]   — active table_schema entries

Implement these endpoints:

  GET /v1/analytics/glossary
    Allowed roles: all authenticated roles
    1. Load platform entries from CREDIT_GLOSSARY and METRIC_REGISTRY (serialize to dicts)
    2. Load tenant entries via load_tenant_entries(scope.tenant_id)
    3. Return GlossaryResponse
    No cross-tenant data leakage: tenant entries filtered strictly by scope.tenant_id

  POST /v1/analytics/tenant/schema/register
    Allowed roles: credit_analyst only
    1. Build TenantSemanticEntry with entry_type="table_schema"
    2. Set definition_json to include all fields from RegisterSchemaRequest
    3. Call register_entry(entry, author_email=scope.user_email, approver_email=request.approver_email)
    4. If SeparationOfDutiesViolation is raised: return HTTP 403 with detail
    5. Return the registered entry

  POST /v1/analytics/tenant/glossary
    Allowed roles: credit_analyst only
    1. Build TenantSemanticEntry from ProposeGlossaryTermRequest
    2. Call register_entry(entry, author_email=scope.user_email, approver_email=request.approver_email)
    3. Return the registered entry

  GET /v1/analytics/tenant/schema/{name}/status
    Allowed roles: credit_analyst, data_engineer, auditor
    1. Load the active table_schema entry for scope.tenant_id and name
    2. If not found: return HTTP 404
    3. Return the entry with a schema_drift_status field:
       - For dev/SQLite: "drift_check_not_supported" (INFORMATION_SCHEMA not available)
       - For BigQuery: query INFORMATION_SCHEMA.COLUMNS, compute current hash, call verify_schema_hash
       - Return "ok" | "drift_detected"

CONSTRAINTS:
- Never return entries from a different tenant_id than scope.tenant_id.
- SeparationOfDutiesViolation from compliance.rbac must be caught and returned as HTTP 403.
- All endpoints must log to access_event_log via compliance.rbac.log_access_event if that
  function exists; skip gracefully if not.
```

---

### Prompt 12 — Create the exam packets router

**File:** `analytics_api/src/routers/exam_packets.py` *(new file)*

```
Create analytics_api/src/routers/exam_packets.py.

Import AnalyticsScope from analytics_api.src.analytics_scope.
Import load_tenant_entries from analytics_api.src.tenant_semantic_registry.
Use _db from analytics_api.src.main.

Define models:

  CreateExamPacketRequest:
    - exam_type: Literal["regulatory", "internal_audit", "model_validation"]
    - period_start: date
    - period_end: date
    - include_semantic_registry: bool = True

  ExamPacketSummary:
    - packet_id: str
    - exam_type: str
    - period_start: date
    - period_end: date
    - status: str
    - created_at: str
    - created_by: str
    - approved_by: Optional[str]

Implement:

  POST /v1/analytics/evidence/exam-packet
    Allowed roles: credit_analyst, compliance_officer, auditor, cro
    1. Generate packet_id
    2. Query analytics_query_log for all queries by this tenant in the period
       (period_start <= submitted_at <= period_end AND status = 'success')
    3. Build queries_json: list of {query_id, sql_hash, row_count, submitted_at}
    4. If include_semantic_registry=True: call load_tenant_entries(scope.tenant_id)
       and serialize to semantic_registry_snapshot_json
    5. Insert into exam_packets table with status='draft'
    6. Return ExamPacketSummary

  GET /v1/analytics/evidence/exam-packet/{packet_id}
    Allowed roles: credit_analyst, compliance_officer, auditor, cro
    1. Query exam_packets WHERE packet_id = :packet_id AND tenant_id = scope.tenant_id
    2. If not found or different tenant: return 404
    3. Return full packet including queries_json and semantic_registry_snapshot_json

CONSTRAINTS:
- Never return a packet belonging to a different tenant_id.
- The packet's semantic_registry_snapshot_json must be a point-in-time snapshot of
  the registry at the time the packet was generated, not a live query on read.
```

---

### Prompt 13 — Create the policies and reports routers

**Files:** `analytics_api/src/routers/policies.py`, `analytics_api/src/routers/reports.py` *(new files)*

```
Create analytics_api/src/routers/policies.py.

This router provides read/write access to the tenant's credit policy configuration
stored in config_registry.

Import ConfigRegistryService from config_registry.service.
Import enforce_four_eyes from compliance.rbac.
Import AnalyticsScope from analytics_api.src.analytics_scope.

Implement:

  GET /v1/analytics/policies
    Allowed roles: credit_analyst, compliance_officer, cro, auditor
    Returns the active config for scope.tenant_id via ConfigRegistryService.get_active().
    Include policy_cutoffs, feature_toggles, model_bindings from config_json.

  POST /v1/analytics/policies
    Allowed roles: credit_analyst only (proposes; CRO must approve via four-eyes)
    Accepts a partial config_json dict with proposed changes.
    Call enforce_four_eyes("credit_policy_amendment", scope.user_email, request.approver_email).
    If passes: call ConfigRegistryService.publish() with the updated config.
    Return the new TenantConfigVersion.

---

Create analytics_api/src/routers/reports.py.

This router provides P&L report generation using named platform metrics.

Import METRIC_REGISTRY from analytics_api.src.metric_registry.
Import validate from analytics_api.src.sql_validator.
Use _db from analytics_api.src.main.

Define:

  PlReportRequest:
    - period_start: date
    - period_end: date
    - product_type: Optional[str] = None
    - segment_by: Optional[Literal["fico_band", "dti_band", "channel", "product_type"]] = None

  PlReportResponse:
    - report_id: str
    - period_start: date
    - period_end: date
    - metrics: dict[str, Any]   — metric_name → computed value
    - sql_artifacts: list[dict] — one per metric: {metric_name, sql, sql_hash}
    - generated_at: str

Implement:

  POST /v1/analytics/reports/pl
    Allowed roles: credit_analyst, cro, executive
    1. For each metric in [approval_rate, rejection_rate, manual_review_rate,
       charge_off_rate, net_loss_rate]: build SQL from MetricDefinition.formula_sql
       wrapped in SELECT ... FROM @dataset.{base_table} WHERE tenant_id = '{tenant_id}'
       AND submitted_at BETWEEN '{period_start}' AND '{period_end}'
    2. Validate each SQL via validate()
    3. Execute each SQL via _db.run_sql()
    4. Return PlReportResponse with all computed values and SQL artifacts

CONSTRAINTS:
- Each metric SQL is individually validated and logged.
- If any metric SQL is blocked by the validator, return 422 with which metric was blocked.
```

---

### Prompt 14 — Create the dashboards router

**File:** `analytics_api/src/routers/dashboards.py` *(new file)*

```
Create analytics_api/src/routers/dashboards.py.

Import AnalyticsScope from analytics_api.src.analytics_scope.
Use _db from analytics_api.src.main.

Define a DashboardConfig Pydantic model:
  - dashboard_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
  - tenant_id: str
  - name: str
  - description: Optional[str]
  - widget_configs: list[dict]  — each: {widget_type, metric_name, filters, title}
  - created_by: str
  - created_at: str
  - is_active: bool = True

Store dashboard configs in a simple SQLite/BQ table called "dashboard_configs" with:
  dashboard_id, tenant_id, name, description, config_json (serialized widget_configs),
  created_by, created_at, is_active.

Implement:

  POST /v1/analytics/dashboards
    Allowed roles: credit_analyst, cro, executive
    Validates that all metric_name values in widget_configs exist in scope.metrics.
    If any metric_name is unknown: return 422 with the unknown name.
    Saves dashboard config. Returns DashboardConfig.

  GET /v1/analytics/dashboards/{dashboard_id}
    Allowed roles: all authenticated roles
    Returns the dashboard config if tenant_id matches scope.tenant_id.
    Returns 404 if not found or different tenant.

  GET /v1/analytics/dashboards
    Returns all active dashboards for scope.tenant_id. Cursor-paginated.

CONSTRAINTS:
- Tenant isolation: never return dashboards from another tenant.
```

---

## Phase F — Wire Everything into main.py
*Goal: Mount all routers and update startup logic.*

---

### Prompt 15 — Update analytics_api/src/main.py

**File:** `analytics_api/src/main.py`

```
Modify analytics_api/src/main.py.

TASK 1: Export the _db instance and verify_bearer function so routers can import them.
After the line where _db is instantiated (e.g., _db = _QueryBackend()), add:
  __all__ = ["_db", "verify_bearer", "bearer_scheme"]

TASK 2: Update CORS middleware.
Change allow_methods=["GET"] to allow_methods=["GET", "POST", "DELETE"].

TASK 3: Import and mount all 7 new routers.
Add these imports at the top of the file (below existing imports):
  from analytics_api.src.routers import (
      sql_query,
      nl_query,
      exam_packets,
      policies,
      reports,
      dashboards,
      tenant_semantic,
  )

Mount each router:
  app.include_router(sql_query.router)
  app.include_router(nl_query.router)
  app.include_router(exam_packets.router)
  app.include_router(policies.router)
  app.include_router(reports.router)
  app.include_router(dashboards.router)
  app.include_router(tenant_semantic.router)

TASK 4: Register new BigQuery tables on startup.
In the startup lifespan event (or @app.on_event("startup") if no lifespan exists),
call the BigQuery table creation logic for the 4 new schemas:
  ANALYTICS_QUERY_LOG_SCHEMA, SAVED_QUERIES_SCHEMA,
  EXAM_PACKETS_SCHEMA, TENANT_SEMANTIC_REGISTRY_SCHEMA
Follow the exact same pattern already used for existing table creation on startup.

TASK 5: Create an `__init__.py` for the routers package.
Create analytics_api/src/routers/__init__.py as an empty file so the package is importable.

CONSTRAINTS:
- Do not change any existing endpoint code.
- Do not change the existing BigQuery table creation logic for existing tables.
- The new routers must be imported lazily (inside try/except ImportError) if they are
  not yet created — this allows incremental deployment without breaking the service.
```

---

## Phase G — Platform Integrations
*Goal: Wire lineage tracking and config registry into the semantic layer.*

---

### Prompt 16 — Add `register_tenant_source` to data lineage tracker

**File:** `data_lineage/lineage_tracker.py`

```
Modify data_lineage/lineage_tracker.py.

TASK 1: Add a new SQL constant for inserting an external_data_source lineage node.
Add _INSERT_EXTERNAL_SOURCE alongside the existing INSERT constants:
  INSERT INTO lineage_nodes (node_id, node_type, name, version, schema_hash, created_at)
  VALUES (:node_id, 'external_data_source', :name, :version, :schema_hash, :created_at)

TASK 2: Add a helper to record a join edge between a tenant table and a platform table.
Add this SQL constant:
  INSERT INTO lineage_edges (edge_id, from_node_id, to_node_id, transform_description, created_at)
  VALUES (:edge_id, :from_node_id, :to_node_id, :transform_description, :created_at)
(This may already exist — if so, reuse the existing INSERT statement.)

TASK 3: Add the following async functions to lineage_tracker.py.

async def register_tenant_source(
    db_url: str,
    tenant_id: str,
    table_name: str,
    schema_hash: str,
    version: str = "1.0.0",
) -> LineageNode:
    """
    Register a tenant-owned external data source as a lineage node.
    node_type is always 'external_data_source'.
    name is formatted as "{tenant_id}.{table_name}" to namespace tenant tables.
    Idempotent: if a node with this name already exists, return the existing node.
    """

async def record_tenant_join_edge(
    db_url: str,
    tenant_node_id: str,
    platform_table_name: str,
    join_key: str,
) -> LineageEdge:
    """
    Record a directed lineage edge from a tenant external_data_source node to
    a platform table node. The platform table node must already exist.
    transform_description is formatted as "JOIN ON {join_key}".
    """

CONSTRAINTS:
- Follow the exact same async/await pattern as existing functions in the file.
- Use the existing _get_engine and _ensure_schema helpers.
- The register_tenant_source function must be idempotent — check for existence before inserting.
- Do not change any existing function signatures.
```

---

### Prompt 17 — Add semantic layer accessor to config_registry service

**File:** `config_registry/service.py`

```
Modify config_registry/service.py.

Add a new method get_semantic_layer to ConfigRegistryService:

  def get_semantic_layer(self, tenant_id: str) -> dict[str, Any]:
      """
      Return the semantic_layer sub-dict from the active config_json for this tenant.
      This is the migration-period fallback: if entries exist in config_json["semantic_layer"]
      but the tenant has not yet migrated to the dedicated tenant_semantic_registry table,
      analytics_scope.py will merge these entries as well.

      Returns {} (empty dict) if:
        - No active config exists for this tenant
        - config_json has no "semantic_layer" key
      Never raises — callers treat {} as "no legacy semantic entries".
      """
      config = self.get_active(tenant_id)
      if config is None:
          return {}
      return config.config_json.get("semantic_layer", {})

CONSTRAINTS:
- This is a read-only method. Do not modify any config version records.
- Do not change any existing method signatures.
- Follow the existing code style in the file exactly.
```

---

## Phase H — LucidCredit Integration
*Goal: Remove direct DB connections to CRP tables and route through the analytics API.*

---

### Prompt 18 — Create analytics_tool.py in LucidCredit

**File:** `LucidCredit/backend/app/agent/tools/analytics_tool.py` *(new file)*

```
Create LucidCredit/backend/app/agent/tools/analytics_tool.py.

This tool replaces direct DB connections to CRP-owned tables.
It routes all CRP analytics queries through the CRP Analytics API
(analytics_api, port 8082) instead of connecting to CRP databases directly.

Import Settings from app.config.
Use httpx.AsyncClient for HTTP calls.

Define a Pydantic model AnalyticsResult:
  - rows: list[dict]
  - query_id: str
  - row_count: int
  - sql_hash: str
  - citations: list[dict] = []
  - confidence: Optional[str] = None
  - code_artifact: Optional[dict] = None  — present on NL query results

Implement two async functions:

async def run_sql_query(
    sql: str,
    settings: Settings,
    dry_run: bool = False,
) -> AnalyticsResult:
    """
    POST sql to /v1/analytics/query/sql on the CRP Analytics API.
    Authentication: Bearer {settings.crp_api_key}
    Timeout: 30 seconds.
    On HTTP 422: raise ValueError(f"SQL blocked: {response.json()['detail']}")
    On HTTP 4xx/5xx: raise RuntimeError(f"Analytics API error: {status} {body}")
    """

async def run_nl_query(
    question: str,
    settings: Settings,
) -> AnalyticsResult:
    """
    POST question to /v1/analytics/query/nl on the CRP Analytics API.
    Authentication: Bearer {settings.crp_api_key}
    Returns the full NlQueryResponse including citations and code_artifact.
    On HTTP 422: raise ValueError(f"NL query blocked: {response.json()['detail']}")
    """

The CRP Analytics API base URL comes from settings.crp_analytics_base_url.
The tenant scope is set by the JWT issued for the external_service role.

CONSTRAINTS:
- Never store or log the API key in plain text.
- Use httpx.AsyncClient with explicit timeout (not the default no-timeout).
- The tool must work without any direct DB credentials or DB drivers.
```

---

### Prompt 19 — Update sql_tool.py to remove CRP table access

**File:** `LucidCredit/backend/app/agent/tools/sql_tool.py`

```
Modify LucidCredit/backend/app/agent/tools/sql_tool.py.

TASK 1: Remove CRP-owned tables from _ALLOWED_TABLES.
The following tables are CRP-owned and must no longer be accessed via direct DB connection.
Remove them from _ALLOWED_TABLES:
  - "loan_applications"
  - "features"
  - "funded_loans"
  - "payment_history"
  - "feature_snapshots"
  - "policy_docs"

Keep these LucidCredit-owned tables (they remain in _ALLOWED_TABLES):
  - "bank_accounts"
  - "audit_logs"
  - "copilot_sessions"
  - "citations"

TASK 2: Add a comment block above _ALLOWED_TABLES explaining the table ownership model:
  # LucidCredit-owned tables: safe for direct DB access via this tool.
  # CRP-owned tables (loan_applications, features, funded_loans, payment_history,
  # feature_snapshots, policy_docs) must be queried via analytics_tool.py
  # which routes through the CRP Analytics API — no direct DB credentials required.

TASK 3: If any query routing logic in this file checks for CRP table names to route
to the analytics API, update it to use analytics_tool.run_sql_query() instead.

CONSTRAINTS:
- Do not change any other logic in sql_tool.py.
- Do not change the schema of _ALLOWED_TABLES (keep as frozenset).
- Do not change any existing function signatures.
```

---

### Prompt 20 — Update LucidCredit config.py

**File:** `LucidCredit/backend/app/config.py`

```
Modify LucidCredit/backend/app/config.py.

Add two new configuration fields to the Settings class (or equivalent config model):

  crp_analytics_base_url: str = Field(
      default="http://localhost:8082",
      env="CRP_ANALYTICS_BASE_URL",
      description="Base URL for the CRP Analytics API (analytics_api service)"
  )

  crp_analytics_scope: str = Field(
      default="lucidcredit",
      env="CRP_ANALYTICS_SCOPE",
      description="Tenant scope identifier sent in the JWT when calling the CRP Analytics API"
  )

Follow the exact same Field() pattern as existing config fields in the file.

CONSTRAINTS:
- Do not remove or rename any existing config fields.
- Do not change any existing default values.
```

---

## Phase I — Tests
*Goal: Unit and integration tests for all new modules.*

---

### Prompt 21 — Write unit and integration tests

**Files:** `analytics_api/tests/test_glossary.py`, `analytics_api/tests/test_metric_registry.py`, `analytics_api/tests/test_sql_validator.py`, `analytics_api/tests/test_tenant_semantic_registry.py`, `analytics_api/tests/test_analytics_scope.py`

```
Create unit tests for the tenant-scoped semantic layer. Use pytest and pytest-asyncio.
All tests use SQLite in-memory (DATABASE_URL = "sqlite+aiosqlite:///:memory:").

FILE: analytics_api/tests/test_glossary.py
Tests:
  - test_lookup_by_exact_key: glossary.lookup("thin-file") returns GlossaryEntry
  - test_lookup_by_synonym: glossary.lookup("declined") returns the "rejected" entry
  - test_lookup_case_insensitive: glossary.lookup("APPROVED") returns the "approved" entry
  - test_lookup_unknown_term: glossary.lookup("xyzzy") returns None
  - test_all_entries_have_applies_to_tables: every entry has at least one applies_to_tables value

FILE: analytics_api/tests/test_metric_registry.py
Tests:
  - test_get_known_metric: metric_registry.get("approval_rate") returns MetricDefinition
  - test_get_unknown_metric: metric_registry.get("unknown_metric") returns None
  - test_all_metrics_have_formula_sql: every MetricDefinition has non-empty formula_sql
  - test_all_metrics_have_required_time_filter: every MetricDefinition has
    required_time_filter_column set (not None) — prevents full-table scans

FILE: analytics_api/tests/test_sql_validator.py
Tests:
  - test_valid_select_passes: a valid SELECT with tenant_id filter and partition filter
    returns ValidationResult(is_valid=True)
  - test_insert_blocked: INSERT statement returns is_valid=False with block_reason
    containing "blocked"
  - test_update_blocked: UPDATE statement is blocked
  - test_drop_blocked: DROP TABLE is blocked
  - test_missing_tenant_filter_injected: a SELECT without WHERE tenant_id is auto-injected
    with the tenant's tenant_id value, is_valid=True
  - test_unknown_table_blocked: SELECT from a table not in scope.allowed_tables returns
    is_valid=False with block_reason containing the table name
  - test_missing_partition_filter_blocked: SELECT without any partition column filter
    returns is_valid=False
  - test_pii_column_stripped_for_external_service: SELECT ssn FROM loan_applications with
    external_service role returns is_valid=True but pii_columns_stripped=["ssn"]

FILE: analytics_api/tests/test_tenant_semantic_registry.py
Tests:
  - test_register_glossary_term: registers a glossary_term entry and loads it back
  - test_register_computes_sha256: registered entry has correct definition_sha256
  - test_duplicate_version_raises: registering the same name+version twice raises ValueError
  - test_deactivate_entry: deactivated entry no longer returned by load_tenant_entries
  - test_four_eyes_same_person_raises: registering a table_schema with
    author_email == approver_email raises SeparationOfDutiesViolation
  - test_verify_schema_hash_match: verify_schema_hash returns True when columns match
  - test_verify_schema_hash_mismatch: verify_schema_hash returns False when columns differ

FILE: analytics_api/tests/test_analytics_scope.py
Tests:
  - test_platform_glossary_present: resolved scope includes "thin-file" from CREDIT_GLOSSARY
  - test_tenant_override_wins: when tenant registers a synonym override for "approved",
    scope.merged_glossary["approved"].sql_predicate reflects the tenant's value
  - test_tenant_table_in_allowed_tables: after registering a table_schema, that table
    appears in scope.allowed_tables
  - test_cross_tenant_isolation: loading tenant A scope does not include tenant B's entries

For all tests requiring AnalyticsScope: build a minimal scope fixture using:
  AnalyticsScope(
      tenant_id="test-tenant",
      user_email="analyst@test.com",
      role="credit_analyst",
      allowed_tables=frozenset({"loan_applications", "credit_decisions", "model_scores",
                                "feature_vectors", "roll_rates"}),
      merged_glossary=dict(CREDIT_GLOSSARY),
      metrics=dict(METRIC_REGISTRY),
      require_tenant_filter=True,
  )

CONSTRAINTS:
- Use pytest fixtures, not setUp/tearDown.
- All async tests use @pytest.mark.asyncio.
- No mocking of the SQL validator's sqlglot calls — test against the real parser.
- Tests must pass with DATABASE_URL pointing to SQLite in-memory.
```

---

## Dependency Graph Summary

```
Prompt 1  (bigquery_schema.py)
Prompt 2  (rbac.py)
    │
    └──► Prompt 3  (glossary.py)          ──────────────────────────┐
    └──► Prompt 4  (metric_registry.py)   ────────────────────────┐  │
                                                                   │  │
Prompt 5  (analytics_scope.py) ◄─── Prompts 3, 4, 6             │  │
Prompt 6  (tenant_semantic_registry.py) ◄─── Prompts 1, 2, 16   │  │
Prompt 7  (sql_validator.py) ◄─── Prompt 5                       │  │
                                                                   │  │
Prompt 8  (routers/sql_query.py)     ◄─── Prompts 5, 7          │  │
Prompt 9  (nl_query_agent.py)        ◄─── Prompts 5, 7, 3, 4   ◄┘  │
Prompt 10 (routers/nl_query.py)      ◄─── Prompts 9, 8         ◄───┘
Prompt 11 (routers/tenant_semantic.py) ◄─── Prompts 3, 4, 5, 6
Prompt 12 (routers/exam_packets.py)  ◄─── Prompts 5, 6
Prompt 13 (routers/policies.py, reports.py) ◄─── Prompts 4, 5, 7
Prompt 14 (routers/dashboards.py)    ◄─── Prompts 4, 5
Prompt 15 (main.py update)           ◄─── Prompts 1, 8–14
Prompt 16 (lineage_tracker.py)       — independent
Prompt 17 (config_registry/service.py) — independent
Prompt 18 (LucidCredit/analytics_tool.py) ◄─── Prompt 20
Prompt 19 (LucidCredit/sql_tool.py) — independent (removal only)
Prompt 20 (LucidCredit/config.py)   — independent
Prompt 21 (tests) ◄─── all above
```

---

## Acceptance Criteria

After all 21 prompts are complete, the following must hold:

| Test | Expected Result |
|---|---|
| `pytest analytics_api/tests/` | All tests pass |
| `POST /v1/analytics/query/nl` with "What was thin-file approval rate last quarter?" | Returns cited answer with SQL in `code_artifact` |
| `POST /v1/analytics/tenant/schema/register` with same author and approver | Returns HTTP 403 |
| NL query referencing an unregistered table | Returns HTTP 422 with `block_reason` naming the table |
| NL query after tenant registers a glossary term | SQL uses the tenant's custom predicate |
| `GET /v1/analytics/glossary` for tenant A | Returns no entries from tenant B |
| Schema drift: tenant table columns changed | NL query returns HTTP 422 with `schema_drift_detected` |
| `POST /v1/analytics/evidence/exam-packet` | Returns packet with `semantic_registry_snapshot_json` populated |
| LucidCredit `sql_tool.py` | `loan_applications` not in `_ALLOWED_TABLES` |
