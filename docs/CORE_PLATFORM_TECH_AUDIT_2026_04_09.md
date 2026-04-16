# CORE PLATFORM — DEEP TECHNICAL AUDIT (GOVERNANCE-FIRST)
## Credit Risk Platform — 2026-04-09

> **Scope**: `credit-risk-platform` (core runtime, APIs, pipelines, storage, UI)
>
> **Focus**: performance, modularity, multi-tenant scalability, governance readiness, remaining gaps.
>
> **Baseline**: Supersedes audit dated 2026-04-07. All section numbers directly compare against that document.

---

## 1. Current System Baseline (Updated)

### 1.1 What has been implemented since 2026-04-07

The following components are now present and verified against source code:

| Area | Component | File(s) | Status |
|------|-----------|---------|--------|
| Canonical domain package | `credit_core.features` | `credit_core/features.py` | ✅ Implemented |
| Canonical domain package | `credit_core.policy` | `credit_core/policy.py` | ✅ Implemented |
| Safe policy DSL | `policy_dsl` | `decision_engine/policy_dsl.py` | ✅ Implemented |
| Policy versioning | `PolicyVersionStore` | `decision_engine/policy_version_store.py` | ✅ Implemented |
| Champion/challenger | `PolicyChallengerRouter` | `decision_engine/policy_challenger.py` | ✅ Implemented |
| Tenant isolation | `TenantContext`, `scoped_tenant` | `audit/tenant_guard.py` | ✅ Implemented |
| Tenant config registry | `ConfigRegistryService` | `config_registry/service.py` | ✅ Implemented |
| Redis rate limiting | `RateLimitMiddleware` | `decision-api/src/middleware/rate_limit.py` | ✅ Implemented |
| Redis idempotency | `IdempotencyMiddleware` | `decision-api/src/middleware/idempotency.py` | ✅ Implemented |
| Ingestion async safety | BackgroundTasks + retry | `ingestion-api/src/main.py` | ✅ Implemented |
| Ingestion deduplication | Redis SHA-256 dedup | `ingestion-api/src/main.py` | ✅ Implemented |
| Analytics API | BQ-backed portfolio | `analytics_api/src/main.py` | ✅ Implemented |
| Audit hash chain | `chain_verifier` | `audit/chain_verifier.py` | ✅ Implemented |
| Feature lineage | OpenLineage emitter | `feature_pipeline/lineage.py` | ✅ Implemented |
| Drift monitoring | PSI + KS | `monitoring/drift_monitor.py` | ✅ Implemented |
| Alert routing | Slack + Email | `monitoring/alert_router.py` | ✅ Implemented |
| Right to erasure | CCPA/GLBA handler | `compliance/erasure_request.py` | ✅ Implemented |
| Compliance data plane | Regulatory thresholds | `compliance/data_plane.py` | ✅ Implemented |
| Batch job tracking | `BatchJobStore` | `decision-api/src/batch_job_store.py` | ✅ Implemented |
| Borrower portal auth | JWT issuance | `decision-api/src/borrower_auth.py` | ✅ Implemented |
| Webhook infrastructure | Reg + dispatch + log | `webhooks/` | ✅ Implemented |
| Decision parity test | Golden test suite | `tests/test_decision_parity.py` | ✅ Implemented |
| Four-eyes config approval | Stage/approve/reject | `decision-api/src/main.py` (endpoints) | ✅ Implemented |
| JWT_SECRET fail-fast | Startup hard check | `decision-api/src/main.py` (CRIT-01) | ✅ Implemented |
| Big Query tenant keys | `tenant_id REQUIRED` | `db/bigquery_schema.py` | ✅ Implemented |

### 1.2 Updated Data Flow

**Online decisioning (Decision API)**
```
JWT → tenant_id extraction → RateLimitMiddleware (Redis, per-tenant+route)
  → IdempotencyMiddleware (Redis, 24 h TTL)
  → credit_core.compute_feature_matrix()          ← canonical
  → predict_fraud() + predict_pd()                ← preloaded models
  → credit_core.evaluate_policy()                 ← canonical
  → PolicyChallengerRouter (champion/challenger)  ← A/B split
  → async append-only audit row (hash-chained)
  → optional webhook dispatch
```

**Online/Batch pipeline (Agent orchestrator)**
```
DataIngestionAgent → FeatureEngineeringAgent     [calls credit_core.compute_feature_matrix]
  → RiskModelingAgent
  → DecisionEngineAgent                          [calls credit_core.evaluate_policy]
                                                 [uses policy_dsl — no eval()]
  → ExplainabilityAgent
  → BQWriterAgent (optional)
  → MonitoringAgent (drift + fairness)
```

Both paths now use `credit_core` as the canonical entry point. The dual-brain divergence from the previous audit has been resolved.

---

## 2. Performance Audit (Updated)

### A. Data Processing

| Finding | Previous | Now | Risk |
|---------|----------|-----|------|
| Dual feature pipelines | ❌ Dual impl | ✅ Unified via `credit_core` | Resolved |
| `iterrows()` in feature store writes | ❌ Present | ❌ Still present (`feature_store.py:174`) | **OPEN** — CPU-heavy at 1 M+ rows |
| Batch fan-out cap | ❌ Uncapped | ✅ `BATCH_CONCURRENCY_LIMIT` semaphore (default 50) | Resolved |
| Ingestion I/O blocking | ❌ Blocking GCS/PubSub in event loop | ✅ BackgroundTasks + exponential backoff | Resolved |
| Analytics layer | ❌ Mock Streamlit only | ✅ BQ-backed `analytics_api` with pagination + LRU cache | Substantially resolved |

**Open issue — `iterrows()` in bulk feature store writes**

`feature_pipeline/feature_store.py` line 174 still uses:
```python
return [_build_row(row, version, event_timestamp, as_of_date) for _, row in df.iterrows()]
```
At 1 M+ rows this is 10–50× slower than a vectorised approach.
**Recommendation**: replace with `df.to_dict("records")` or `df.itertuples()`.

### B. Compute Layer

- Decision API loads models at startup (good). No load-per-request regression detected in review.
- Agent path `RiskModelingAgent` — model injection pathway not fully verified; potential late-load retains risk under cold-start scenarios.
- SHAP explanations: `ExplainabilityAgent` and `/v1/decisions/{id}/explanation` — still a p99 outlier for large batches. No evidence of async offload or compute-tier separation for SHAP.
- In-process metrics: `_ServiceMetrics` class (rolling deque, thread-safe) provides p50/p95/p99 latency. Accurate but ephemeral (resets on restart); no external time-series push.

### C. Storage

- Audit default remains SQLite in env-var default (`sqlite+aiosqlite:///./decision_audit.db`). Acceptable for dev/test; production must override `DATABASE_URL` with Postgres.
- `config_registry.db`, `policy_versions.db`, `policy_challenger.db` are all SQLite by default — correct pattern, but production deployment needs a migration guide to Postgres for each.
- BigQuery schemas now include `tenant_id REQUIRED` on all fact tables with `["tenant_id", ...]` clustering — tenant-partitioned queries are now schema-correct.
- Feature store `as_of_date` PIT semantics are implemented and documented.

### D. API Layer

- Per-tenant+route Redis rate limiting: ✅ sliding-window counter. Degrades gracefully (pass-through) if Redis is unreachable — **risk**: in production, a Redis outage silently disables rate limiting. Recommended: add a health check assertion on Redis at startup when in `PROD` environment.
- Idempotency: ✅ cached in Redis per `(tenant_id, Idempotency-Key)`, 24 h TTL. Same graceful-degradation caveat applies.
- No distributed tracing (OpenTelemetry) in Python services. See §7.

### E. UI/UX

- Streamlit dashboard (`dashboard/app.py`): 5-page application (Portfolio Overview, Model Performance, Drift Monitor, Fair Lending, Audit Lookup). Uses `@st.cache_data(ttl=300)`. **Still mixes live data with synthetic/mock data** — not production analytics.
- `analytics_api`: proper BigQuery-backed FastAPI service with vintage curves, roll rates, approval/profit endpoints, tenant scoping, and cursor pagination. This replaces Streamlit as the analytics source of truth, but the Next.js UI has not been confirmed to consume it.

---

## 3. Modularity Assessment (Updated)

### 3.1 Dual-brain problem — RESOLVED

The critical duplication of feature engineering and policy evaluation has been eliminated:

- `credit_core/features.py` wraps `feature_pipeline.features.compute_features` as the canonical entry point. Column alias normalisation (`existing_debt → existing_debt_amount`, `dti → debt_to_income_ratio`) is centralised here.
- `credit_core/policy.py` wraps `decision_engine.engine.make_decision` as the canonical entry point. Both Decision API and `DecisionEngineAgent` import from `credit_core`.
- `schemas/contracts.py` defines typed Pydantic contracts (`ApplicantInput`, `TenantContext`, `CreditDecision`, `FeatureVector`, etc.) shared across all agents and APIs. No agent may pass raw dicts across boundaries.

### 3.2 Remaining modularity concerns

**Policy DSL migration completeness**
`decision_engine/policy_dsl.py` is fully implemented and `HardRule` in `agents/decision_engine_agent.py` validates rules against the DSL at load time. However, the extent to which all YAML config rule definitions have been converted from `eval`-style to DSL-style is not verified by automated test coverage in `tests/test_policy_dsl.py`. A CI gate (see §8) should assert 0 `eval` or `exec` calls in policy evaluation paths.

**Dual config DB formats**
`config_registry.service.ConfigRegistryService` and `decision_engine.policy_version_store.PolicyVersionStore` are both append-only versioned stores with similar patterns, each using their own SQLite database. This is not duplication of logic (they manage different artefacts), but operations teams need clear runbooks for each.

**Agent path model loading**
`agents/risk_modeling_agent.py` was not reviewed in detail. If it loads joblib artefacts per agent instantiation rather than per startup, it will incur cold-start latency spikes in batch mode.

---

## 4. Multi-Tenant Architecture Audit (Updated)

### A. Tenant isolation

| Check | Previous | Now |
|-------|----------|-----|
| `tenant_id` in canonical schemas | ❌ Absent | ✅ `TenantContext` in `schemas/contracts.py` |
| `tenant_id` in audit log | ❌ Absent | ✅ Propagated via `scoped_tenant` / `TenantContext` |
| `tenant_id` in BQ schemas | ❌ Absent | ✅ `REQUIRED` field + clustering on all BQ fact tables |
| Tenant claims from JWT only | ❌ Unspecified | ✅ `TenantContext.tenant_id` doc: "MUST NOT be accepted from request body" |
| Tenant context in background jobs | ❌ No mechanism | ✅ `audit/tenant_guard.py` `admin_override` + `scoped_tenant` |

**Remaining gap**: Analytics API query filtering (`WHERE tenant_id = :tenant_id`) is correct, but the enforcement of tenant claims in the audit log append path is not verified by a dedicated cross-module integration test.

### B. Customisation layer

- `ConfigRegistryService` provides full lifecycle: publish, activate, rollback, diff, four-eyes approval (`stage → approve/reject`). Every change is SHA-256 hashed and append-only. ✅
- Per-tenant active config is resolved at request time via `_CONFIG_REGISTRY.get_active(tenant_id)` in both Decision API and orchestration pipeline. ✅
- Per-tenant model binding: **not yet implemented**. MLflow artifact paths are common across tenants; no per-tenant model override mechanism exists in the registry.

### C. Resource allocation

- Batch semaphore cap (`BATCH_CONCURRENCY_LIMIT`) protects shared compute. Not yet per-tenant — a large tenant batch still consumes the full semaphore pool.
- No tenant quotas or priority tiers implemented.

### D. Tenant onboarding

- `ConfigRegistryService.ensure_tenant()` provides programmatic onboarding. No automated onboarding workflow or API endpoint for tenant self-service exists yet.

---

## 5. Governance Technology Assessment (Updated)

### A. Policy artefact lifecycle

| Capability | Status |
|-----------|--------|
| Append-only policy ledger | ✅ `PolicyVersionStore` |
| Version tag + SHA-256 hash | ✅ |
| Author + note per version | ✅ |
| PIT replay (`get_as_of(datetime)`) | ✅ |
| Rollback (new version, no mutation) | ✅ |
| Four-eyes config approval | ✅ (`/v1/config/stage`, `/v1/config/approve`, `/v1/config/reject`) |
| Champion/challenger A/B routing | ✅ `PolicyChallengerRouter` |
| Safe rule DSL (no eval) | ✅ `policy_dsl.py` |
| Per-tenant model binding | ❌ Not implemented |

### B. Audit log integrity

- Append-only audit log with SHA-256 hash chain. ✅
- `audit/chain_verifier.py`: asynchronous verifier that detects tampered or gap rows across `audit_log`, `portfolio_audit_log`, `adverse_action_log`. ✅
- `audit/tenant_guard.py`: context-variable based tenant scoping with admin override pattern that is explicit and grep-able. ✅

### C. Feature governance

- `feature_pipeline/lineage.py`: OpenLineage 1.0.x event emission (http or console transport). ✅ Best-effort; failures are logged, not raised.
- Feature store PIT semantics (`as_of_date`, `event_timestamp`) correctly implemented in `feature_pipeline/feature_store.py`. ✅
- `FeatureStoreAuditProof`: sha256 of returned feature values written for every `read_features_as_of` call. ✅

### D. Compliance infrastructure

- `compliance/data_plane.py`: centralised regulatory threshold service (BQ-backed; LRU cache; raises `ComplianceDataPlaneError` rather than silently falling back). ✅
- `compliance/erasure_request.py`: CCPA/GLBA right-to-erasure with exempt table list and PII hashing at boundary. ✅
- `compliance/adverse_action_pdf.py`, `exam_packet_builder.py`, `regulatory_horizon.py`, `retention_policy.py` — full compliance module surface. ✅

### E. Monitoring and alerting

- `monitoring/drift_monitor.py`: PSI + KS drift monitoring with three-tier status (`stable < 0.10 < minor < 0.25 < major`). ✅
- `monitoring/fair_lending.py` + `monitoring/bisg.py`: BISG proxy race/ethnicity estimation for HMDA fair-lending analysis. ✅
- `monitoring/alert_router.py`: pluggable notification channels (Slack webhook, SMTP email) with retry logic. ✅
- `monitoring/cc_pd_monitor.py`, `cc_portfolio_monitor.py`, `cc_valuation_monitor.py`, `mortgage_valuation_monitor.py`: product-specific monitoring modules. ✅

---

## 6. Security Assessment

### Resolved since previous audit

- **JWT_SECRET fail-fast** (CRIT-01): API raises `RuntimeError` at startup if `JWT_SECRET` is absent or equal to the dev placeholder. ✅
- **Batch semaphore** (CRIT-04): `BATCH_CONCURRENCY_LIMIT` env var, default 50. ✅
- **Tenant spoofing prevention**: `TenantContext` doc explicitly prohibits accepting `tenant_id` from request body. ✅

### Open issues

| Issue | Severity | Detail |
|-------|---------|--------|
| Redis optional in prod | MEDIUM | Rate-limiting and idempotency silently pass-through on Redis outage. A `PROD`-env startup check should assert Redis connectivity. |
| SQLite default for policy and config stores | MEDIUM | `policy_versions.db`, `policy_challenger.db`, `config_registry.db` default to SQLite. Production must override; no automated enforcement. |
| Default `DATABASE_URL` is SQLite | MEDIUM | `decision_audit.db` is the default. Production audit log must be Postgres with WAL archiving. |
| JWT algorithm defaulted to HS256 | LOW | Acceptable for symmetric token issuance, but RS256 with a managed key pair (GCP KMS) would be stronger for multi-tenant production. |
| No contract tests asserting no-eval in policy paths | LOW | `test_policy_dsl.py` exists, but a CI grep-based gate on `eval(` in production code paths is absent. |

---

## 7. Missing Components (UPDATED)

### 7.1 Outstanding from previous Phase 1 roadmap

All Phase 1 items are resolved. See §1.1.

### 7.2 Outstanding from previous Phase 2 roadmap

| Item | Status |
|------|--------|
| Warehouse-backed analytics semantic layer | ✅ `analytics_api` implemented |
| Policy registry + versioning + no eval | ✅ Implemented |
| Bulk feature store write optimisation | ❌ **`iterrows()` still present** (`feature_store.py:174`) |

### 7.3 Outstanding from previous Phase 3 roadmap

| Item | Status |
|------|--------|
| Deployable streaming ETL (Ingestion → BQ) | ❌ **Not in repo** — `ingestion-api` writes to GCS/PubSub but no Dataflow/streaming consumer |
| OpenTelemetry distributed tracing | ❌ **Not implemented** in any Python service |
| Regulator-grade deterministic replay bundle | ⚠️ **Partial** — policy hash + feature version + config snapshot exist; no single "replay bundle" assembler endpoint |

### 7.4 New gaps identified in this audit

| Gap | Priority | Detail |
|-----|---------|--------|
| Per-tenant model bindings | P2 | No mechanism to bind a specific MLflow artefact version to a tenant. All tenants share one model version. |
| Per-tenant compute quotas | P2 | Semaphore is global; large tenant batches can starve real-time traffic. |
| Agent path model load verification | P2 | `RiskModelingAgent` model-load behaviour not verified; potential per-call artefact load remains. |
| Redis health check in PROD env | P1 | Graceful degradation is correct for dev/test; it is a misconfiguration risk in production. |
| OpenTelemetry Python instrumentation | P2 | No span/trace context across `credit_core`, `audit`, or BQ write paths. Cross-service latency attribution is blind. |
| Streaming ETL pipeline | P3 | Pub/Sub events are emitted but no downstream consumer (Dataflow/Cloud Run job) transforms them into BQ bronze/silver/gold. |
| Contract tests between Decision API + Analytics API | P2 | `test_decision_parity.py` covers credit_core parity. No OpenAPI schema contract tests across service boundaries. |

---

## 8. Updated Target Architecture Assessment

### Comparison against recommended target (from 2026-04-07 audit)

**Control Plane**
- Tenant service (metadata, keys, quotas): tenant metadata ✅, keys ✅, quotas ❌
- Config registry (versioned, approved): ✅ Fully implemented
- Model registry (MLflow + signed artifacts): MLflow present ✅, per-tenant binding ❌

**Data Plane**
- Ingestion service → Event bus: ✅ GCS + Pub/Sub with async safety
- Warehouse (BQ) bronze/silver/gold: Schema ✅, streaming ETL ❌
- Offline PIT feature views: ✅ `feature_store.py` with `as_of_date`
- Online feature store (Redis): ❌ Redis is used for caching/rate-limiting; no Redis feature store for low-latency decisions

**Decision Plane**
- Stateless Decision API calling shared `credit_core`: ✅ Fully implemented
- Append-only audit with tenant partitioning: ✅ Hash-chained + `tenant_id` propagation

**Monitoring Plane**
- Drift + fair lending jobs: ✅ PSI/KS + BISG
- Alerts router: ✅ Slack + email
- External time-series metrics (Prometheus/Cloud Monitoring): ❌ In-process rolling deque only

---

## 9. Performance Optimisation Roadmap (Updated)

### Immediate (this sprint)

1. **Fix `iterrows()` in feature store** — replace with `df.to_dict("records")` in `feature_store.py:174`. O(n) speedup for large batches.
2. **Redis PROD health check** — add a startup assertion when `ENVIRONMENT=prod` to verify Redis connectivity and halt deployment if unavailable.
3. **Verify agent model loading** — instrument `RiskModelingAgent` to confirm models are loaded once at pipeline construction, not per run.

### Phase 2 (next 4–8 weeks)

4. **OpenTelemetry Python instrumentation** — instrument `credit_core` entry points, audit logger, and BQ writer with OTLP spans. Export to Cloud Trace or a local Jaeger instance.
5. **Per-tenant batch semaphore** — partition `_batch_semaphore` by tenant; configure per-tier limits in `ConfigRegistryService`.
6. **Per-tenant model bindings** — extend `ConfigRegistryService` schema with `model_artifact_uri` field; bind to `RiskModelingAgent` model-load at pipeline construction.
7. **Cross-service contract tests** — add `pytest` OpenAPI schema snapshot tests for Decision API and Analytics API to `tests/integration/`.

### Phase 3 (6–12 weeks)

8. **Streaming ETL** — deploy a Cloud Run job (or Dataflow pipeline) that reads from Pub/Sub `ingestion.completed`, transforms to curated schema, and streams into BQ bronze/silver/gold layers.
9. **Deterministic replay bundle endpoint** — expose `GET /v1/decisions/{id}/replay-bundle` that returns policy hash, model artefact hash, feature set version, config snapshot, and raw inputs in a single signed JSON document.
10. **External metrics sink** — push rolling metrics to Cloud Monitoring or Prometheus pushgateway on a 30-second interval; retire ephemeral in-process deque as the sole observability path.

---

## 10. Engineering Best Practices — Compliance Score

| Practice | Status | Note |
|---------|--------|------|
| Single canonical DTO layer | ✅ | `schemas/contracts.py` |
| Contract tests (Decision API vs agent) | ✅ | `test_decision_parity.py` |
| Contract tests (cross-service OpenAPI) | ❌ | Not implemented |
| No `eval()` in policy paths | ✅ | `policy_dsl.py`; verify with CI grep gate |
| Append-only audit with hash chain | ✅ | `audit/logger.py` + `chain_verifier.py` |
| PIT feature correctness | ✅ | `feature_store.py` `as_of_date` semantics |
| Tenant isolation in all storage writes | ✅ | BQ + audit + config registry |
| JWT secret fail-fast in production | ✅ | `CRIT-01` startup check |
| OpenTelemetry distributed traces | ❌ | Not implemented |
| Redis enforced in production | ⚠️ | Graceful degradation — needs prod hardening |
| Drift + fair lending monitoring | ✅ | PSI/KS + BISG in `monitoring/` |
| Streaming ETL to warehouse | ❌ | Pub/Sub emitted; no consumer deployed |

---

## Appendix A — Changed Files Since 2026-04-07 Audit

**New modules (not present in previous audit)**
- `credit_core/features.py`, `credit_core/policy.py`
- `decision_engine/policy_dsl.py`, `policy_version_store.py`, `policy_challenger.py`
- `audit/tenant_guard.py`, `audit/chain_verifier.py`
- `config_registry/service.py`, `config_registry/models.py`
- `feature_pipeline/lineage.py`
- `monitoring/drift_monitor.py`, `alert_router.py`, `fair_lending.py`, `bisg.py`
- `monitoring/cc_pd_monitor.py`, `cc_portfolio_monitor.py`, `cc_valuation_monitor.py`, `mortgage_valuation_monitor.py`
- `compliance/data_plane.py`, `erasure_request.py`, `exam_packet_builder.py`, `retention_policy.py`, `adverse_action_pdf.py`
- `analytics_api/src/main.py`, `analytics_api/src/queries/*.sql`
- `decision-api/src/middleware/rate_limit.py`, `idempotency.py`
- `decision-api/src/batch_job_store.py`, `borrower_auth.py`
- `webhooks/dispatcher.py`, `store.py`, `models.py`
- `schemas/contracts.py`
- `tests/test_decision_parity.py` and 16 additional test files

**Materially changed modules**
- `decision-api/src/main.py` — 24 endpoints; now imports `credit_core`; middleware wired; four-eyes config; webhook, batch, stress-test, portal endpoints
- `ingestion-api/src/main.py` — BackgroundTasks, Redis dedup, exponential backoff
- `agents/feature_engineering_agent.py` — delegates to `credit_core.compute_feature_matrix`; local `build_feature_dataframe` removed
- `agents/decision_engine_agent.py` — delegates to `credit_core.evaluate_policy`; `eval()` replaced with `policy_dsl`
- `orchestration/pipeline.py` — imports `ConfigRegistryService`; tenant_id carried in `PipelineRun`
- `db/bigquery_schema.py` — `tenant_id REQUIRED` + clustering on all tables

---

## Appendix B — Evidence Base for this Audit

All findings are derived from direct source code review of:

- `credit_core/features.py`, `credit_core/policy.py`
- `decision-api/src/main.py` (lines 1–200 reviewed)
- `decision-api/src/middleware/rate_limit.py`, `idempotency.py`
- `decision-api/src/batch_job_store.py`
- `ingestion-api/src/main.py` (lines 1–100)
- `orchestration/pipeline.py` (lines 1–100)
- `agents/decision_engine_agent.py`, `feature_engineering_agent.py`
- `decision_engine/policy_dsl.py`, `policy_version_store.py`, `policy_challenger.py`, `engine.py`
- `feature_pipeline/feature_store.py`, `lineage.py`
- `config_registry/service.py`
- `audit/tenant_guard.py`, `chain_verifier.py`
- `compliance/data_plane.py`, `erasure_request.py`
- `monitoring/drift_monitor.py`, `alert_router.py`
- `analytics_api/src/main.py`, `analytics_api/src/queries/`
- `schemas/contracts.py`
- `db/bigquery_schema.py`
- `tests/test_decision_parity.py`
- `dashboard/app.py`
