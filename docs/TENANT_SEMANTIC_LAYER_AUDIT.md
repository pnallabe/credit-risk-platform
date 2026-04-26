# Architectural Audit — Tenant-Scoped Semantic Layer

**Platform:** credit-risk-platform
**Audit date:** 2025
**Scope:** All changes required to implement a tenant-scoped semantic layer that feeds `nl_to_sql`, glossary resolution, custom metric computation, and RBAC-gated analytics.

---

## 1. Executive Summary

The semantic layer sits between raw BigQuery schemas and the NL query agent. It answers the question: *"what does 'approval rate' mean for THIS tenant?"* Today, there is no semantic layer — there are only free-text `description` strings on BigQuery columns and Pydantic enum values in `data_contracts`. Those are partial, implicit semantic anchors that must be formalised.

**Work breakdown:**
| Category | Files to create | Files to modify |
|---|---|---|
| DB schemas | 0 | 1 (`bigquery_schema.py`) |
| RBAC | 0 | 1 (`rbac.py`) |
| Semantic core | 4 | 0 |
| Analytics routers | 7 | 1 (`analytics_api/src/main.py`) |
| Config registry | 0 | 1 (`config_registry/service.py`) |
| Lineage | 0 | 1 (`data_lineage/lineage_tracker.py`) |
| LucidCredit integration | 2 | 1 (`config.py`) |
| **Total** | **13** | **6** |

---

## 2. What Currently Exists (Semantic-Adjacent Assets)

### 2.1 Canonical enum values in `data_contracts/`

These ARE implicit glossary entries today:

| Source | Symbol | Semantic value |
|---|---|---|
| `decisions.py` | `DecisionLabelV1` | `APPROVE`, `REJECT`, `MANUAL_REVIEW` — canonical decision vocabulary |
| `decisions.py` | `PDBandV1` | `low`, `medium`, `high` — risk tier vocabulary |
| `decisions.py` | `LoanProductTypeV1` | `credit_card`, `personal_loan`, etc. |
| `portfolio.py` | `DelinquencyBucketV1` | `current`, `1-29`, `30-59`, `60-89`, `90-119`, `120+`, `charged_off` |
| `portfolio.py` | `FicoBandV1` | `sub_580`, `580-619`, `620-659`, `660-719`, `720+` |
| `portfolio.py` | `DtiBandV1` | `0-20%`, `20-36%`, `36-50%`, `50%+` |
| `compliance.py` | `DenialReasonV1` | HMDA denial reason codes 1–9 |
| `compliance.py` | `ActionTakenV1` | HMDA action-taken codes 1–8 |

**Gap:** These enums live in contracts but are not queryable by the NL agent. They must be harvested into the platform glossary at startup.

### 2.2 Column-level descriptions in `db/bigquery_schema.py`

Every `SchemaField` has a `description` arg (e.g., `"1 if applicant has <5 tradelines"`). These are:
- ✅ Already machine-readable
- ✅ Sufficient for field-level column docs
- ❌ Not surfaced to the query planner
- ❌ No synonym mapping (e.g., "thin file" → `is_thin_file = 1`)
- ❌ No cross-table metric definitions

**Gap:** `bigquery_schema.py` needs 4 new table schemas (see §4.1). The existing field descriptions are the seed data for `glossary.py`.

### 2.3 `TABLE_CATALOGUE` in `db/bigquery_schema.py`

The `TABLE_CATALOGUE` dict at line ~315 maps table name → `{schema, partition_field, clustering_fields, description}`. This is the closest thing to a table registry today.

**Gap:** It has no tenant-scoping, no `allowed_for_roles`, no `requires_tenant_filter` flag. These must be added.

### 2.4 `TenantConfigVersion.config_json` in `config_registry/models.py`

The `config_json: Dict[str, Any]` blob accepts arbitrary keys. Semantic entries *could* be stored under `config_json["semantic_layer"]` today with zero DDL.

**Why this is insufficient long-term:**
- `config_json` is versioned at the *whole-blob* level — there is no per-entry versioning
- No SHA-256 per individual semantic entry (tamper detection operates on the entire config blob)
- No way to query "give me all glossary terms for tenant X" without deserialising the entire config
- No `is_active` flag per entry — can't deprecate a single term without republishing the whole config
- No `approved_by` per entry — compliance trail is coarse

**Decision:** Store semantic entries in a dedicated `tenant_semantic_registry` table, same append-only + SHA-256 pattern as `tenant_configs`. Use `config_json["semantic_layer"]` only as a migration path during the transition period.

### 2.5 `data_lineage/lineage_tracker.py`

Current `node_type` values: `"source"`, `"transform"`, `"feature"`, `"model"` (free strings, no enum enforcement).

**Gap:** No `"external_data_source"` type. When a tenant registers a custom table schema, it must create a lineage node of type `external_data_source`. This enables:
1. Provenance tracking for tenant-sourced data
2. Audit export showing where tenant data entered the query pipeline
3. Drift detection on tenant schema hashes

### 2.6 `analytics_api/src/main.py`

Current endpoints: `GET /v1/analytics/vintage-curves`, `GET /v1/analytics/roll-rates`, `GET /v1/analytics/approval-profit`.

What's missing:
- No SQL query endpoint
- No NL query endpoint
- No exam packet endpoints
- No semantic registry endpoints
- No saved queries
- No dashboard config
- No P&L reports
- `allow_methods=["GET"]` — must add `POST`
- CORS currently GET-only — must expand for POST endpoints

### 2.7 `compliance/rbac.py`

Current `Role` Literal: 9 roles. Missing `credit_analyst` and `external_service`.

`RBAC_MATRIX` covers: `cc_origination_policy`, `mlflow_registry`, `audit_log`, `compliance_events`, `regulatory_thresholds`, `policy_approval_log`, `emergency_override`. Missing: `analytics_queries`, `saved_queries`, `exam_packets`, `tenant_semantic_registry`, `dashboards`, `pl_reports`.

`FOUR_EYES_RULES` missing: `credit_policy_amendment`, `tenant_schema_registration`.

---

## 3. Gap Analysis by Layer

### Layer 1 — Physical Schema

| Table | Status | Action |
|---|---|---|
| `loan_applications` | ✅ | No change |
| `feature_vectors` | ✅ | No change |
| `model_scores` | ✅ | No change |
| `credit_decisions` | ✅ | No change |
| `explanations` | ✅ | No change |
| `fair_lending_reports` | ⚠️ Missing `portfolio_as_of_date`, `cohort_definition` | Add 2 columns |
| `analytics_query_log` | ❌ Does not exist | Add `ANALYTICS_QUERY_LOG_SCHEMA` |
| `saved_queries` | ❌ Does not exist | Add `SAVED_QUERIES_SCHEMA` |
| `exam_packets` | ❌ Does not exist | Add `EXAM_PACKETS_SCHEMA` |
| `tenant_semantic_registry` | ❌ Does not exist | Add `TENANT_SEMANTIC_REGISTRY_SCHEMA` |

### Layer 2 — RBAC

| Item | Status | Action |
|---|---|---|
| `credit_analyst` role | ❌ Missing | Add to `Role` Literal |
| `external_service` role | ❌ Missing | Add to `Role` Literal |
| Analytics permissions matrix | ❌ Missing | Add `analytics_queries`, `exam_packets`, `tenant_semantic_registry` resources |
| `credit_policy_amendment` four-eyes | ❌ Missing | Add to `FOUR_EYES_RULES` |
| `tenant_schema_registration` four-eyes | ❌ Missing | Add to `FOUR_EYES_RULES` |

### Layer 3 — Semantic Core (new files)

| File | Status | Purpose |
|---|---|---|
| `analytics_api/src/glossary.py` | ❌ Missing | Platform-level glossary harvested from `data_contracts` enums and `bigquery_schema.py` field descriptions |
| `analytics_api/src/metric_registry.py` | ❌ Missing | Named metric formulas (e.g., `approval_rate`, `charge_off_rate`, `expected_loss`) |
| `analytics_api/src/tenant_semantic_registry.py` | ❌ Missing | Tenant overrides: custom glossary terms, table schemas, metric formulas |
| `analytics_api/src/analytics_scope.py` | ❌ Missing | FastAPI dependency: resolves JWT → `AnalyticsScope(tenant_id, role, allowed_tables, merged_glossary)` |
| `analytics_api/src/sql_validator.py` | ❌ Missing | sqlglot parse → allowlist check → tenant_id injection → cost guard → PII field strip |

### Layer 4 — Analytics API Routers (new files)

| Router | Status | Endpoints |
|---|---|---|
| `routers/sql_query.py` | ❌ Missing | `POST /v1/analytics/query/sql`, `GET /v1/analytics/queries/saved`, `POST /v1/analytics/queries/save` |
| `routers/nl_query.py` | ❌ Missing | `POST /v1/analytics/query/nl` |
| `routers/exam_packets.py` | ❌ Missing | `POST /v1/analytics/evidence/exam-packet`, `GET /v1/analytics/evidence/exam-packet/{id}` |
| `routers/policies.py` | ❌ Missing | `GET /v1/analytics/policies`, `POST /v1/analytics/policies` |
| `routers/dashboards.py` | ❌ Missing | `POST /v1/analytics/dashboards`, `GET /v1/analytics/dashboards/{id}` |
| `routers/reports.py` | ❌ Missing | `POST /v1/analytics/reports/pl`, `GET /v1/analytics/reports/pl/{id}` |
| `routers/tenant_semantic.py` | ❌ Missing | `POST /v1/analytics/tenant/schema/register`, `GET /v1/analytics/glossary`, `POST /v1/analytics/tenant/glossary` |

### Layer 5 — NL Query Agent

| File | Status | Purpose |
|---|---|---|
| `analytics_api/src/nl_query_agent.py` | ❌ Missing | Orchestrates: intent classify → schema inject → sql generate → validate → execute → synthesize → cite |

### Layer 6 — Config Registry Extension

| Item | Status | Action |
|---|---|---|
| `config_registry/service.py::get_semantic_layer()` | ❌ Missing | Read `config_json["semantic_layer"]` for migration-period fallback |

### Layer 7 — Lineage Extension

| Item | Status | Action |
|---|---|---|
| `external_data_source` lineage node type | ❌ Not enforced | Document in `lineage_tracker.py`; add `register_tenant_source()` helper |

### Layer 8 — LucidCredit Integration

| File | Status | Action |
|---|---|---|
| `app/agent/tools/analytics_tool.py` | ❌ Missing | HTTP client to CRP Analytics API; replaces direct DB connections for CRP tables |
| `app/agent/tools/sql_tool.py` | ⚠️ Has direct CRP DB credentials | Remove CRP-owned tables from `_ALLOWED_TABLES`; route through `analytics_tool.py` |
| `app/config.py` | ⚠️ Missing analytics URL | Add `crp_analytics_base_url`, `crp_analytics_scope` |

---

## 4. Detailed Change Specs

### 4.1 `db/bigquery_schema.py` — 4 new schemas + 2 new columns

#### Fix 1: `FAIR_LENDING_REPORTS_SCHEMA`
```python
# Add after existing fields:
_f("portfolio_as_of_date", "DATE",   "NULLABLE", "Reporting cut-off date for portfolio snapshot"),
_f("cohort_definition",    "STRING", "NULLABLE", "JSON-encoded cohort filter used for fair-lending comparison"),
```

#### New schema: `ANALYTICS_QUERY_LOG_SCHEMA`
```python
ANALYTICS_QUERY_LOG_SCHEMA: List[Any] = [
    _f("query_id",        "STRING",    "REQUIRED", "UUIDv4 unique query identifier"),
    _f("tenant_id",       "STRING",    "REQUIRED", "Tenant scope — required on all rows"),
    _f("user_email",      "STRING",    "REQUIRED", "Submitting user (PII — access-logged)"),
    _f("role",            "STRING",    "REQUIRED", "Submitting user's platform role"),
    _f("query_type",      "STRING",    "REQUIRED", "'sql' | 'nl'"),
    _f("raw_input",       "STRING",    "NULLABLE", "Original NL question or SQL text"),
    _f("generated_sql",   "STRING",    "NULLABLE", "Final executed SQL (post-validation)"),
    _f("sql_hash",        "STRING",    "REQUIRED", "SHA-256 of generated_sql for dedup"),
    _f("row_count",       "INTEGER",   "NULLABLE", "Rows returned"),
    _f("latency_ms",      "INTEGER",   "NULLABLE", "End-to-end latency"),
    _f("status",          "STRING",    "REQUIRED", "'success' | 'blocked' | 'error'"),
    _f("block_reason",    "STRING",    "NULLABLE", "Populated when status='blocked'"),
    _f("submitted_at",    "TIMESTAMP", "REQUIRED", "UTC query submission time"),
]
```

#### New schema: `SAVED_QUERIES_SCHEMA`
```python
SAVED_QUERIES_SCHEMA: List[Any] = [
    _f("query_id",     "STRING",    "REQUIRED", "UUIDv4"),
    _f("tenant_id",    "STRING",    "REQUIRED", "Owning tenant"),
    _f("name",         "STRING",    "REQUIRED", "Human-readable query name"),
    _f("description",  "STRING",    "NULLABLE", "Query purpose for catalogue"),
    _f("sql_text",     "STRING",    "REQUIRED", "Saved SQL (tenant-scoped)"),
    _f("created_by",   "STRING",    "REQUIRED", "Author email"),
    _f("created_at",   "TIMESTAMP", "REQUIRED", "UTC creation time"),
    _f("is_active",    "BOOLEAN",   "REQUIRED", "Soft-delete flag"),
]
```

#### New schema: `EXAM_PACKETS_SCHEMA`
```python
EXAM_PACKETS_SCHEMA: List[Any] = [
    _f("packet_id",        "STRING",    "REQUIRED", "UUIDv4"),
    _f("tenant_id",        "STRING",    "REQUIRED", "Owning tenant"),
    _f("exam_type",        "STRING",    "REQUIRED", "'regulatory' | 'internal_audit' | 'model_validation'"),
    _f("period_start",     "DATE",      "REQUIRED", "Evidence window start"),
    _f("period_end",       "DATE",      "REQUIRED", "Evidence window end"),
    _f("queries_json",     "STRING",    "REQUIRED", "JSON array of {query_id, sql, result_hash, executed_at}"),
    _f("citations_json",   "STRING",    "REQUIRED", "JSON array of {fact, source_table, column, query_id, timestamp}"),
    _f("pdf_gcs_uri",      "STRING",    "NULLABLE", "GCS URI of rendered PDF packet"),
    _f("created_by",       "STRING",    "REQUIRED", "Analyst email"),
    _f("approved_by",      "STRING",    "NULLABLE", "Four-eyes approver email"),
    _f("status",           "STRING",    "REQUIRED", "'draft' | 'pending_approval' | 'approved' | 'submitted'"),
    _f("created_at",       "TIMESTAMP", "REQUIRED", "UTC creation time"),
]
```

#### New schema: `TENANT_SEMANTIC_REGISTRY_SCHEMA`
```python
TENANT_SEMANTIC_REGISTRY_SCHEMA: List[Any] = [
    _f("entry_id",         "STRING",    "REQUIRED", "UUIDv4"),
    _f("tenant_id",        "STRING",    "REQUIRED", "Owning tenant"),
    _f("entry_type",       "STRING",    "REQUIRED", "'glossary_term' | 'table_schema' | 'metric' | 'synonym_override'"),
    _f("name",             "STRING",    "REQUIRED", "Term/table/metric name — unique per (tenant_id, entry_type, version)"),
    _f("version",          "STRING",    "REQUIRED", "Semantic version e.g. '1.0.0'"),
    _f("definition_json",  "STRING",    "REQUIRED", "JSON-encoded entry definition (see §4.3)"),
    _f("definition_sha256","STRING",    "REQUIRED", "SHA-256 of definition_json — tamper detection"),
    _f("approved_by",      "STRING",    "REQUIRED", "Approver email — four-eyes required"),
    _f("is_active",        "BOOLEAN",   "REQUIRED", "False = deprecated/superseded"),
    _f("created_at",       "TIMESTAMP", "REQUIRED", "UTC insert time"),
]
```

Add all 5 to `TABLE_CATALOGUE` in the same file.

---

### 4.2 `compliance/rbac.py` — new roles + analytics permissions

#### Add to `Role` Literal
```python
Role = Literal[
    "ml_developer",
    "ml_validator",
    "compliance_officer",
    "cro",
    "data_engineer",
    "system_service_acct",
    "auditor",
    "legal_counsel",
    "executive",
    "credit_analyst",      # NEW
    "external_service",    # NEW
]
```

#### Add to `FOUR_EYES_RULES`
```python
"credit_policy_amendment": {
    "author_role": "credit_analyst",
    "approver_role": "cro",
    "prohibited_overlap": True,
    "description": "Policy threshold amendment requires CRO sign-off",
},
"tenant_schema_registration": {
    "author_role": "credit_analyst",
    "approver_role": "data_engineer",
    "prohibited_overlap": True,
    "description": "Registering a net-new tenant data source requires data engineering approval",
},
```

#### Add to `RBAC_MATRIX`
```python
"credit_analyst": {
    "cc_origination_policy":     ["READ", "WRITE:draft", "WRITE:propose_amendment"],
    "mlflow_registry":           ["READ"],
    "audit_log":                 ["READ:all"],
    "compliance_events":         ["READ"],
    "regulatory_thresholds":     ["READ"],
    "policy_approval_log":       ["READ:all"],
    "emergency_override":        [],
    # Analytics-specific resources:
    "analytics_queries":         ["READ", "WRITE:own", "EXECUTE"],
    "saved_queries":             ["READ", "WRITE:own"],
    "exam_packets":              ["READ", "WRITE:own", "WRITE:submit"],
    "tenant_semantic_registry":  ["READ", "WRITE:propose"],
    "dashboards":                ["READ", "WRITE:own"],
    "pl_reports":                ["READ", "EXECUTE"],
    "fair_lending_reports":      ["READ"],
},
"external_service": {
    "cc_origination_policy":     ["READ"],
    "mlflow_registry":           [],
    "audit_log":                 [],
    "compliance_events":         [],
    "regulatory_thresholds":     [],
    "policy_approval_log":       [],
    "emergency_override":        [],
    "analytics_queries":         ["READ", "EXECUTE:scoped"],   # tenant-scoped only
    "saved_queries":             ["READ:scoped"],
    "exam_packets":              [],
    "tenant_semantic_registry":  ["READ:scoped"],
    "dashboards":                ["READ:scoped"],
    "pl_reports":                [],
    "fair_lending_reports":      [],
},
```

---

### 4.3 Semantic Entry `definition_json` shapes

Each `entry_type` has a defined JSON shape stored in `definition_json`:

#### `glossary_term`
```json
{
  "display_name": "Thin File",
  "description": "Applicant with fewer than 5 tradelines on file",
  "synonyms": ["thin-file", "thin file applicant", "limited credit history"],
  "sql_predicate": "is_thin_file = 1",
  "applies_to_tables": ["loan_applications"],
  "source_contract": "data_contracts.v1.features.DEFAULT_FEATURE_LIST",
  "canonical": false
}
```
> `canonical: true` is reserved for platform glossary entries from `data_contracts`.

#### `table_schema`
```json
{
  "table_name": "acme_bureau_enrichments",
  "bigquery_table": "acme-tenant.crp_tenant_acme.bureau_enrichments",
  "join_key": "application_id",
  "join_to": "loan_applications",
  "columns": [
    {"name": "bureau_score", "type": "FLOAT64", "description": "Proprietary bureau score"},
    {"name": "tradeline_count", "type": "INTEGER", "description": "Number of open tradelines"}
  ],
  "requires_tenant_filter": true,
  "lineage_node_id": "lineage-uuid-here",
  "schema_hash": "sha256-of-columns-definition"
}
```

#### `metric`
```json
{
  "display_name": "30-Day Approval Rate",
  "description": "Share of applications approved in a rolling 30-day window",
  "formula_sql": "COUNTIF(decision = 'APPROVE') / COUNT(*)",
  "base_table": "credit_decisions",
  "time_filter": "TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), submitted_at, DAY) <= 30",
  "unit": "percentage",
  "source_contract": null
}
```

#### `synonym_override`
```json
{
  "term": "approved",
  "override_value": "APPROVE",
  "platform_default": "APPROVE",
  "context": "decision column in credit_decisions",
  "reason": "Tenant uses 'approved' while platform uses 'APPROVE' enum value"
}
```

---

### 4.4 `analytics_api/src/analytics_scope.py` — new file

**Purpose:** Single FastAPI dependency that resolves JWT → `AnalyticsScope`. All downstream endpoints receive this; they never call `verify_bearer` directly.

```
AnalyticsScope
├── tenant_id: str
├── user_email: str
├── role: Role
├── allowed_tables: FrozenSet[str]    # platform tables + tenant-registered tables
├── merged_glossary: Dict[str, GlossaryEntry]  # platform defaults + tenant overrides
├── metrics: Dict[str, MetricDefinition]       # platform + tenant metrics
└── require_tenant_filter: bool       # always True for external_service
```

Resolution order for glossary merging:
1. Start with `CREDIT_GLOSSARY` from `glossary.py` (platform defaults)
2. Overlay `METRIC_REGISTRY` from `metric_registry.py`
3. Overlay active `glossary_term` entries from `tenant_semantic_registry` for `tenant_id`
4. Overlay active `metric` entries from `tenant_semantic_registry` for `tenant_id`
5. Add tenant-registered `table_schema` entries to `allowed_tables`

---

### 4.5 `analytics_api/src/sql_validator.py` — new file

**Pipeline** (applied in order, fail-fast):
1. **Parse** — sqlglot parse; reject if syntax error
2. **Statement type** — only `SELECT` allowed; block `INSERT`, `UPDATE`, `DELETE`, `DROP`, `EXEC`
3. **Table allowlist** — every referenced table must be in `scope.allowed_tables`
4. **Tenant filter injection** — if `require_tenant_filter=True`, inject `WHERE tenant_id = :tenant_id` on every table reference that lacks it
5. **PII column guard** — block queries projecting PII columns (`ssn`, `date_of_birth`, `street_address`, `applicant_name`) for `external_service` role
6. **Cost guard** — reject queries with no `WHERE` on `submitted_at` partition column (full-table scan prevention)
7. **SQL hash** — compute SHA-256 of normalised SQL for dedup + audit log

---

### 4.6 `analytics_api/src/glossary.py` — new file

Harvests platform glossary from two sources at module load:
1. `data_contracts.v1.*` enum values (auto-discovered, `canonical=True`)
2. `db.bigquery_schema.TABLE_CATALOGUE` field descriptions (column-level docs)

Also defines hand-authored `GlossaryEntry` records for compound business terms:

| Term | Synonyms | SQL predicate / column |
|---|---|---|
| thin file | thin-file, limited credit history | `is_thin_file = 1` → `loan_applications` |
| approved | approve, green | `decision = 'APPROVE'` → `credit_decisions` |
| rejected | declined, denied | `decision = 'REJECT'` → `credit_decisions` |
| manual review | pend, refer, review queue | `decision = 'MANUAL_REVIEW'` → `credit_decisions` |
| charge-off | charged off, write-off | `delinquency_bucket = 'charged_off'` → roll rate tables |
| approval rate | pass rate, acceptance rate | `COUNTIF(decision='APPROVE') / COUNT(*)` → `credit_decisions` |
| PD score | probability of default, default score | `pd_score` → `model_scores` |
| FICO band | credit score tier | `pd_band` → `model_scores` |

---

### 4.7 `analytics_api/src/metric_registry.py` — new file

Platform-level named metrics. Each `MetricDefinition` stores:
- `name`, `display_name`, `description`
- `formula_sql` (with `@dataset` placeholder)
- `base_table`
- `required_filters` (list of column names that must appear in WHERE)
- `unit` (`percentage`, `currency_usd`, `count`, `ratio`)

Initial platform metrics:

| Name | Formula summary |
|---|---|
| `approval_rate` | `COUNTIF(decision='APPROVE') / COUNT(*)` on `credit_decisions` |
| `rejection_rate` | `COUNTIF(decision='REJECT') / COUNT(*)` |
| `manual_review_rate` | `COUNTIF(decision='MANUAL_REVIEW') / COUNT(*)` |
| `charge_off_rate` | `COUNTIF(delinquency_bucket='charged_off') / COUNT(*)` |
| `net_loss_rate` | `SUM(net_loss_amount) / SUM(outstanding_balance)` |
| `expected_loss` | `SUM(pd_score * lgd * ead)` on `model_scores` JOIN `loan_applications` |
| `fico_distribution` | `COUNT(*) GROUP BY pd_band` |
| `vintage_cumulative_default` | `MAX(cumulative_default_rate)` on `vintage_curves` |
| `dir_score` | `approval_rate_protected / approval_rate_control` on `fair_lending_reports` |

---

### 4.8 `analytics_api/src/tenant_semantic_registry.py` — new file

**Key functions:**

```python
async def load_tenant_entries(
    tenant_id: str,
    entry_type: Optional[str],
    db_url: str,
) -> List[TenantSemanticEntry]:
    """Load all active entries for a tenant, optionally filtered by type."""

async def register_entry(
    tenant_id: str,
    entry: TenantSemanticEntry,
    author_email: str,
    approver_email: str,
    db_url: str,
) -> TenantSemanticEntry:
    """
    Append a new entry (never update in place).
    Calls enforce_four_eyes('tenant_schema_registration') for table_schema entries.
    Computes and stores definition_sha256.
    For table_schema entries: calls lineage_tracker.register_tenant_source().
    """

async def verify_schema_hash(
    tenant_id: str,
    table_name: str,
    current_hash: str,
    db_url: str,
) -> bool:
    """
    Compare current_hash against the registered definition_sha256.
    Returns False (blocks NL queries) if drift detected.
    """
```

---

### 4.9 `analytics_api/src/nl_query_agent.py` — new file

**Agent pipeline (sequential, no LangGraph dependency in analytics_api):**

```
1. IntentClassifier    → classify_intent(question) → {intent_type, entities}
2. SchemaInjector      → inject_schema_context(scope, intent) → {tables, columns, glossary_matches}
3. SQLGenerator        → generate_sql(question, schema_context, scope) → raw_sql
4. SQLValidator        → sql_validator.validate(raw_sql, scope) → validated_sql
5. Executor            → backend.run_sql(validated_sql) → rows
6. Synthesizer         → synthesize_answer(question, rows, schema_context) → answer_text
7. CitationEnforcer    → attach_citations(answer_text, rows, validated_sql) → cited_answer
8. Persister           → log_query(scope, question, validated_sql, rows) → query_id
```

**Anti-hallucination:** every numeric claim in `answer_text` must carry a citation:
```
[Source: credit_decisions.decision | Query: {query_id} | Date: {submitted_at}]
```
The `CitationEnforcer` step rejects answers with uncited claims (uses regex pattern matching on numeric tokens).

**Schema injection prompt fragment:**
```
You are a SQL expert. The tenant is {tenant_id}.
Available tables: {allowed_tables}
Glossary: {merged_glossary_json}
Metrics: {metrics_json}
Rules:
- Always include WHERE tenant_id = '{tenant_id}'
- Only use SELECT statements
- Reference only the tables listed above
```

---

### 4.10 `analytics_api/src/main.py` — modifications

1. Add `POST` to `allow_methods` in CORS middleware
2. Mount 7 new routers (see §3, Layer 4)
3. On startup: call `_ensure_schema()` for 4 new BQ tables
4. Replace inline `verify_bearer` calls in new routers with `resolve_analytics_scope` dependency

---

### 4.11 `data_lineage/lineage_tracker.py` — modification

Add helper:
```python
async def register_tenant_source(
    db_url: str,
    tenant_id: str,
    table_name: str,
    schema_hash: str,
    version: str,
) -> LineageNode:
    """
    Register a tenant custom table as an external_data_source lineage node.
    node_type = 'external_data_source'
    name = f"{tenant_id}.{table_name}"
    """
```

Add corresponding edge when tenant table is joined to a platform table in a query:
```python
async def record_tenant_join_edge(
    db_url: str,
    tenant_node_id: str,
    platform_table: str,
    join_key: str,
) -> LineageEdge:
    ...
```

---

### 4.12 `config_registry/service.py` — modification

Add migration-period accessor:
```python
def get_semantic_layer(self, tenant_id: str) -> Dict[str, Any]:
    """
    Return config_json["semantic_layer"] for the active config version.
    Returns {} if not present.
    Used as fallback during migration from config_json to tenant_semantic_registry.
    """
    config = self.get_active(tenant_id)
    if config is None:
        return {}
    return config.config_json.get("semantic_layer", {})
```

---

### 4.13 LucidCredit — 3 file changes

#### `backend/app/config.py`
```python
crp_analytics_base_url: str = Field(default="http://localhost:8082", env="CRP_ANALYTICS_BASE_URL")
crp_analytics_scope: str = Field(default="lucidcredit", env="CRP_ANALYTICS_SCOPE")
```

#### `backend/app/agent/tools/analytics_tool.py` — new file
HTTP client that:
- Calls `POST /v1/analytics/query/sql` with `Authorization: Bearer {crp_api_key}`
- Maps CRP-owned table queries from `sql_tool.py`'s `_ALLOWED_TABLES`
- Returns `AnalyticsResult(rows, query_id, citations, sql_hash)`

#### `backend/app/agent/tools/sql_tool.py` — modification
Remove from `_ALLOWED_TABLES`:
```python
# REMOVED — these are CRP-owned tables; route through analytics_tool.py:
# "loan_applications", "features", "funded_loans", "payment_history",
# "feature_snapshots", "policy_docs"
```
Keep in `_ALLOWED_TABLES` (LucidCredit-owned):
```python
_ALLOWED_TABLES = frozenset({
    "bank_accounts",       # LucidCredit's own
    "audit_logs",          # LucidCredit's own
    "copilot_sessions",    # LucidCredit's own
    "citations",           # LucidCredit's own
})
```

---

## 5. Integration Contract: Tenant Semantic Registry → NL Query Pipeline

```
Request: POST /v1/analytics/query/nl
  Authorization: Bearer <JWT with tenant_id, role>
  Body: { "question": "What was the approval rate for thin-file applicants last quarter?" }

  1. resolve_analytics_scope(JWT)
       → scope.tenant_id = "acme"
       → scope.role = "credit_analyst"
       → scope.merged_glossary includes:
            "thin file" → sql_predicate: "is_thin_file = 1" (from platform glossary)
            "approval rate" → formula: "COUNTIF(decision='APPROVE')/COUNT(*)"
       → scope.allowed_tables = {"loan_applications", "credit_decisions", ...}
             + {"acme_bureau_enrichments"} (from tenant_semantic_registry)

  2. nl_query_agent.run(scope, question)
       → sql: SELECT COUNT(CASE WHEN cd.decision = 'APPROVE' THEN 1 END)::FLOAT /
                     COUNT(*) AS approval_rate
              FROM `@dataset.credit_decisions` cd
              JOIN `@dataset.loan_applications` la USING (application_id)
              WHERE cd.tenant_id = 'acme'
                AND la.is_thin_file = 1
                AND cd.submitted_at >= DATE_TRUNC(CURRENT_DATE(), QUARTER, -1)

  3. sql_validator.validate(sql, scope)
       → ✅ SELECT only
       → ✅ tables in allowlist
       → ✅ tenant_id filter present
       → ✅ partition filter present

  4. backend.run_sql(sql) → rows

  5. synthesize + cite:
       "The approval rate for thin-file applicants last quarter was 18.4%
        [Source: credit_decisions.decision | Query: q-abc123 | Date: 2025-04-01]"

  6. log to analytics_query_log
```

---

## 6. Schema Drift Protection Flow

```
Tenant registers table schema → definition_sha256 stored in tenant_semantic_registry
                                 lineage node created (external_data_source)

NL query references tenant table →
  sql_validator calls verify_schema_hash(tenant_id, table_name, live_hash)
  live_hash = sha256(SELECT column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS WHERE table_name=...)

  If hashes match:    proceed
  If hashes mismatch: block query, return HTTP 422
                      {
                        "error": "schema_drift_detected",
                        "table": "acme_bureau_enrichments",
                        "action": "Re-register table schema at POST /v1/analytics/tenant/schema/register"
                      }
                      flag for re-approval (four-eyes)
```

---

## 7. Implementation Priority Order

| Priority | File | Rationale |
|---|---|---|
| 1 | `db/bigquery_schema.py` | Foundation — everything else depends on these schemas |
| 2 | `compliance/rbac.py` | Needed by `analytics_scope.py` |
| 3 | `analytics_api/src/glossary.py` | No code dependencies; data-only |
| 4 | `analytics_api/src/metric_registry.py` | No code dependencies; data-only |
| 5 | `analytics_api/src/analytics_scope.py` | Needed by all routers |
| 6 | `analytics_api/src/tenant_semantic_registry.py` | Needed by `analytics_scope.py` |
| 7 | `analytics_api/src/sql_validator.py` | Needed by SQL + NL routers |
| 8 | `analytics_api/src/routers/sql_query.py` | Core SQL endpoint |
| 9 | `analytics_api/src/nl_query_agent.py` | Depends on validator + glossary |
| 10 | `analytics_api/src/routers/nl_query.py` | Depends on nl_query_agent |
| 11 | `analytics_api/src/routers/exam_packets.py` | Depends on SQL + NL |
| 12 | `analytics_api/src/routers/policies.py` | Depends on scope |
| 13 | `analytics_api/src/routers/dashboards.py` | Depends on scope |
| 14 | `analytics_api/src/routers/reports.py` | Depends on SQL |
| 15 | `analytics_api/src/routers/tenant_semantic.py` | Depends on tenant_semantic_registry |
| 16 | `analytics_api/src/main.py` (update) | Wire all routers |
| 17 | `data_lineage/lineage_tracker.py` (update) | Add `register_tenant_source()` |
| 18 | `config_registry/service.py` (update) | Migration accessor |
| 19 | `LucidCredit/backend/app/config.py` (update) | Add analytics URL |
| 20 | `LucidCredit/backend/app/agent/tools/analytics_tool.py` | New HTTP client |
| 21 | `LucidCredit/backend/app/agent/tools/sql_tool.py` (update) | Remove CRP table refs |

---

## 8. Testing Requirements

### Unit tests to write:
- `tests/test_glossary.py` — assert platform enum harvest; synonym lookup
- `tests/test_metric_registry.py` — assert formula SQL renders correctly
- `tests/test_sql_validator.py` — assert blocked patterns (INSERT, missing tenant filter, PII columns, full scan)
- `tests/test_tenant_semantic_registry.py` — assert SHA-256 tamper detection; four-eyes enforcement on table_schema registration
- `tests/test_analytics_scope.py` — assert tenant override wins over platform default
- `tests/test_nl_query_agent.py` — assert citation enforcement; assert SQL is valid after generation

### Integration tests:
- `tests/integration/test_analytics_api_sql.py` — end-to-end POST /v1/analytics/query/sql against SQLite
- `tests/integration/test_analytics_api_nl.py` — end-to-end NL question → cited answer against SQLite
- `tests/integration/test_tenant_semantic_endpoints.py` — register term → query → verify override wins

---

## 9. Known Risks

| Risk | Mitigation |
|---|---|
| LLM SQL generation hallucinates table names | `sql_validator.validate()` blocks any table not in `scope.allowed_tables` before execution |
| Tenant registers a schema that drifts silently | `verify_schema_hash()` called on every NL query that touches a tenant table |
| `config_json["semantic_layer"]` and `tenant_semantic_registry` diverge during migration | `analytics_scope.py` reads `tenant_semantic_registry` first; `get_semantic_layer()` fallback only if registry is empty |
| PII exposure through NL queries | `sql_validator` strips PII column projections for `external_service` role |
| SQL injection via NL-generated SQL | sqlglot parse-tree analysis (not regex) + parameterised execution for all scalar values |
| `credit_analyst` bypasses four-eyes on policy changes | `FOUR_EYES_RULES["credit_policy_amendment"]` enforced at the policies router |
