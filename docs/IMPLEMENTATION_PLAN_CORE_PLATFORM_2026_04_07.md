# CORE PLATFORM — IMPLEMENTATION PLAN (CODING PROMPTS)
## Credit Risk Platform — 2026-04-07

> Purpose: Convert the deep technical audit into a dependency-ordered series of self-contained coding prompts.
>
> Guiding principle: **one canonical “credit brain”** (contracts + features + policy) used by all entry points (Decision API, agent orchestrator, batch jobs).

---

## Phase 0 — Stop-the-bleed (1–2 weeks)

### PROMPT P0.1 — Introduce Tenant Context (Mandatory)

**Severity:** CRITICAL — multi-tenant correctness + security boundary

**Files:**
- `schemas/contracts.py`
- `decision-api/src/main.py`
- `audit/logger.py`
- `agents/*` (pipeline propagation)

**Context**
The platform has no tenant identifier in its canonical schemas, audit events, or warehouse writes. Without tenant scoping, you cannot safely operate as a SaaS platform.

**Task**
1. Add a new Pydantic model `TenantContext` in `schemas/contracts.py`:
   - `tenant_id: str` (required)
   - `environment: Literal["dev","staging","prod"]` (optional)
   - `request_id: str` (required)
2. Add `tenant_id` to all agent-level output contracts where persistence occurs:
   - `ValidatedRecord`, `FeatureVector`, `ModelScores`, `CreditDecision`, `ExplanationRecord`, `PipelineOutput`.
3. In Decision API (`decision-api/src/main.py`):
   - Require JWT claims include `tenant_id`.
   - Do **not** accept tenant_id from request body.
   - Thread tenant_id into the audit log write.
4. In `audit/logger.py`:
   - Add a `tenant_id` column to the audit tables (SQLite + Postgres DDL strings).
   - Update `log_decision()` signature to require `tenant_id`.
   - Update `get_audit_record()` to require `tenant_id` and enforce tenant scoping in SQL.

**Acceptance Criteria**
- Any audit read/write without tenant_id fails safely.
- A tenant cannot read another tenant’s audit record.

**Tests**
- Add `tests/audit/test_tenant_isolation.py`:
  - write two audit records with same application_id but different tenant_id; verify tenant-scoped read returns only its own.

---

### PROMPT P0.2 — Create Canonical Domain Package (“credit_core”) and Delete Duplication

**Severity:** CRITICAL — inconsistent decisions by channel

**Files:**
- NEW: `credit_core/__init__.py`
- NEW: `credit_core/features.py`
- NEW: `credit_core/policy.py`
- Update: `decision-api/src/main.py`, `orchestration/pipeline.py`, `agents/feature_engineering_agent.py`, `agents/decision_engine_agent.py`

**Context**
There are two feature pipelines and two decision engines. This will produce divergent outcomes. In regulated environments, that is an existential issue.

**Task**
1. Create `credit_core/features.py` that exposes one entry point:
   - `compute_feature_matrix(applications_df: pd.DataFrame, *, version: str) -> pd.DataFrame`
   - Internally delegate to `feature_pipeline/features.py` (canonical) and optionally apply thin-file enrichment hooks.
2. Create `credit_core/policy.py` that exposes one entry point:
   - `evaluate_policy(scores_df: pd.DataFrame, context_df: pd.DataFrame, *, policy_version: str, config: dict) -> pd.DataFrame`
   - Internally delegate to `decision_engine/engine.py` OR consolidate decision logic here.
3. Update Decision API to call `credit_core` (not `feature_pipeline` directly).
4. Update FeatureEngineeringAgent to call `credit_core/features.py` (remove its duplicated computations).
5. Update DecisionEngineAgent to call `credit_core/policy.py` (remove duplicated cutoff logic).

**Acceptance Criteria**
- For a fixed input, Decision API and agent pipeline return identical decisions + reason codes.

**Tests**
- Add golden test `tests/test_decision_parity.py`:
  - run N sample applicants through both paths; assert stable equality for key outputs.

---

### PROMPT P0.3 — Remove `eval()` Policy Rules and Replace with a Safe DSL

**Severity:** CRITICAL — security + governance

**Files:**
- `agents/decision_engine_agent.py`
- NEW: `decision_engine/policy_dsl.py`
- `config/agent_config.yaml` (rule format migration)

**Context**
Agent decisioning currently evaluates YAML conditions using Python `eval`. This is not acceptable in any multi-tenant financial system.

**Task**
1. Implement a restricted expression evaluator using `ast.parse` with whitelisted nodes:
   - comparisons, boolean ops, names, constants
   - explicitly reject function calls, attribute access, subscripts, comprehensions
2. Define a rule schema: `{field, op, value}` or JSONLogic-style rules.
3. Migrate existing hard rules in `config/agent_config.yaml` to the safe schema.
4. Ensure rule evaluation is deterministic and logged (rule_id, inputs used, outcome).

**Acceptance Criteria**
- No call sites contain `eval(` for policy.

**Tests**
- Add tests that prove:
  - allowed operators work
  - disallowed syntax is rejected

---

## Phase 1 — Production-grade decision plane (0–3 months)

### PROMPT P1.1 — Redis-backed Rate Limiting + Idempotency for Decision API

**Severity:** HIGH — enterprise traffic control

**Files:**
- `decision-api/src/main.py`
- NEW: `decision-api/src/middleware/rate_limit.py`
- NEW: `decision-api/src/middleware/idempotency.py`
- `docker-compose.yml` (ensure redis wired in env)

**Task**
1. Implement a Redis token bucket limiter scoped by `(tenant_id, route)`.
2. Add idempotency support:
   - accept `Idempotency-Key` header
   - store response blob keyed by `(tenant_id, key)` with TTL
   - on replay, return the stored response without re-executing pipeline
3. Add metrics logs: rejected requests, cache hits.

**Acceptance Criteria**
- Same request with same Idempotency-Key does not double-write audit logs.

**Tests**
- Integration test using a test Redis container OR mocked redis client.

---

### PROMPT P1.2 — Make Ingestion API Async-Safe + Durable Publish

**Severity:** HIGH — ingestion throughput + reliability

**Files:**
- `ingestion-api/src/main.py`

**Task**
1. Move GCS uploads and Pub/Sub publish to:
   - background tasks, or
   - threadpool offload, so async endpoints do not block.
2. Add retries with exponential backoff for transient GCP errors.
3. Add request dedupe using content hash:
   - compute sha256 of batch payload
   - store “seen hashes” in Redis with TTL
4. Emit structured event envelopes including `tenant_id`.

**Acceptance Criteria**
- Under concurrent load, ingestion endpoints keep stable latency and do not block the event loop.

---

### PROMPT P1.3 — Tenant-Aware BigQuery Writes (Schema + Writer)

**Severity:** HIGH — analytics correctness

**Files:**
- `db/bigquery_schema.py`
- `agents/bq_writer_agent.py`
- `db/bigquery_client.py`

**Task**
1. Add `tenant_id` (STRING, REQUIRED) to all scoring/audit related tables.
2. Update row builders in `BQWriterAgent` to populate tenant_id.
3. Partition/clustering:
   - cluster on `tenant_id` + `application_id` for per-tenant lookups.

**Acceptance Criteria**
- All BQ writes are tenant-scoped.

---

### PROMPT P1.4 — Model Loading: Eliminate Per-Request Disk I/O

**Severity:** HIGH — p95 latency

**Files:**
- `models/credit_risk/predict.py`
- `models/fraud_detection/predict.py`
- `agents/risk_modeling_agent.py`
- NEW: `models/model_loader.py`

**Task**
1. Implement process-level cached model loading with explicit version tags.
2. Ensure agent scoring loads models once at init (similar to Decision API startup).
3. Remove “stub scoring succeeds” behavior from production entry points.

**Acceptance Criteria**
- No joblib load calls in per-request hot path.

---

## Phase 2 — Warehouse-first analytics + customization (3–6 months)

### PROMPT P2.1 — Tenant Config Registry (Versioned, Audited, Rollback)

**Severity:** CRITICAL — customization + governance

**Files:**
- NEW: `config_registry/models.py`
- NEW: `config_registry/service.py`
- NEW: `db/migrations/004_config_registry.sql`
- Update: `decision-api/src/main.py`, `orchestration/pipeline.py`

**Related (existing):**
- `decision_engine/policy_version_store.py` (prefer extending this instead of inventing a second version-store pattern)

**Task**
1. Create tables:
   - `tenants`
   - `tenant_configs` (tenant_id, config_version, sha256, approved_by, approved_at, config_json)
2. Implement resolution logic:
   - Decision API resolves active config version per tenant.
3. Implement rollback:
   - set active version pointer, write audit event.

**Acceptance Criteria**
- A tenant can run custom policy cutoffs and feature toggles without code changes.

---

### PROMPT P2.2 — Portfolio Analytics Service (Warehouse-backed)

**Severity:** HIGH — real workload enablement

**Files:**
- NEW: `analytics_api/src/main.py`
- NEW: `analytics_api/src/queries/*.sql`

**Task**
1. Implement endpoints returning:
   - cohort/vintage curves
   - roll rates and delinquency buckets
   - approval rate + expected profit by segment
2. Enforce tenant scoping in BQ SQL (`WHERE tenant_id = :tenant_id`).
3. Implement pagination and caching for expensive queries.

---

## Phase 3 — Streaming, distributed compute, and regulator-grade replay (6–12 months)

### PROMPT P3.1 — Deterministic Decision Replay Bundle

**Severity:** CRITICAL — regulator defensibility

**Files:**
- `audit/logger.py`
- `credit_core/*`

**Task**
1. Persist for every decision:
   - policy artifact hash
   - config version
   - model artifact hash + MLflow run id
   - feature set version + PIT pointers
2. Implement `replay_decision(log_id)` that rebuilds the decision deterministically.

---

# Notes on sequencing

- Do **P0.1 (tenant context)** before any warehouse/analytics work.
- Do **P0.2 (canonical engine)** before optimizing performance; otherwise you will optimize the wrong code path.
- Do **P0.3 (remove eval)** before any enterprise customer pilots.
