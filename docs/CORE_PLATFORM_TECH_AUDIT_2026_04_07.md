# CORE PLATFORM — DEEP TECHNICAL AUDIT (GOVERNANCE-FIRST)
## Credit Risk Platform — 2026-04-07

> Scope: `credit-risk-platform` (core runtime + APIs + pipelines + storage + UI)
>
> Focus: performance, modularity, multi-tenant scalability, client customizability, robustness.

---

## 1. Current System Inference (Baseline Architecture)

### What is likely implemented (from repo evidence)

**APIs**
- **Ingestion API (FastAPI)**: accepts transaction/application batches, writes raw JSON to **GCS**, publishes an event to **Pub/Sub** (`ingestion.completed`).
- **Decision API (FastAPI)**: executes an underwriting pipeline for single + batch requests: feature engineering → fraud inference → PD inference → pricing → decision → audit logging.

**Two parallel “core decisioning” implementations exist**
1) **Decision API path**: request DTOs + `feature_pipeline` + `decision_engine` + `audit/logger.py`.
2) **Agent-orchestrated path**: `CreditRiskPipeline` runs `DataIngestionAgent → FeatureEngineeringAgent → RiskModelingAgent → DecisionEngineAgent → ExplainabilityAgent → (optional) BQWriterAgent`.

**Storage / persistence**
- **Audit log**: async SQLAlchemy, supports SQLite and Postgres.
- **Feature store**: async SQLAlchemy, implements point-in-time columns + read-audit table.
- **BigQuery (optional)**: schema catalogue + writer agent; intended as analytics / scoring sink.

**UI**
- Two Next.js apps (applicant portal, analytics dashboard).
- Streamlit dashboard (currently mock-data heavy; not production analytics).

### Assumptions (explicit)
- Intended production target is GCP (Cloud Run + GCS + Pub/Sub + BigQuery), but the “Pub/Sub → streaming ETL → curated warehouse” path is not a deployable end-to-end pipeline in this repo.
- Portfolio analytics should be warehouse-first; the Python services should not attempt large cohort/vintage computation in-process.

### Data flow (as implemented)

**Online decisioning (Decision API)**
- Request → `compute_features()` → preloaded joblib models for fraud + PD → pricing engine → decision engine → async append-only audit row.

**Online/Batch pipeline (Agent orchestrator)**
- Raw dicts → Pydantic validation + rule checks → pandas feature calc (alternate implementation) → scoring (may load artifacts per call / may stub) → config-driven rules (currently using `eval`) → explanations → optional BigQuery write.

### Decisioning flow
- Decision API uses fixed policy thresholds and reason-code logic.
- Agent pipeline uses YAML-defined hard rules + cutoffs (but executes conditions via `eval`).

---

## 2. Performance Audit

### A. Data Processing
- **Batch vs real-time**: real-time is supported. “Batch” is implemented as concurrent fan-out with a semaphore in Decision API; agent orchestrator has chunked batch mode.
- **Large portfolio analytics**: not implemented as a warehouse-backed semantic layer. Streamlit uses mock data and does not reflect production constraints.
- **Pipeline bottlenecks**:
  - Feature store write converts DataFrame → rows via `iterrows()` (CPU-heavy for 1M+ rows) and performs chunked executes.
  - Dual feature pipelines cause duplicated optimization effort and inconsistent performance behavior.

### B. Compute Layer
- **Model execution latency**:
  - Decision API loads models at startup and passes `_model` for inference (good).
  - Agent path uses inference helpers that load from disk unless a model object is injected—risking “load model per request” latency spikes.
- **Parallelization**: batch uses asyncio concurrency; CPU-heavy steps (pandas, SHAP) will dominate p95/p99.
- **Load behavior**: ingestion API performs GCS/PubSub client calls from within async endpoints (event-loop blocking risk).

### C. Storage
- **OLTP vs warehouse**:
  - Audit default is SQLite in Decision API env var default; Postgres schemas exist for domain DBs.
  - BigQuery exists as a sink but not as the authoritative analytics layer.
- **Partitioning/indexing**:
  - BQ tables have partition/clustering definitions but lack tenant keys.
  - Audit retrieval paths will need indexes tuned for regulator queries (application_id + time + versions).

### D. API Layer
- **Latency**: mostly in feature compute + model inference; SHAP is a p99 killer if enabled broadly.
- **Throughput**: no distributed rate limiting; Redis provisioned but unused.

### E. UI/UX Performance
- Streamlit is demo-grade. Next.js UIs will require paginated + aggregated backend endpoints for large datasets.

---

## 3. Modularity Assessment (CRITICAL)

### Current module boundaries
- Data ingestion: ingestion API + agent ingestion gate.
- Feature engineering: `feature_pipeline/features.py` (Decision API) and `agents/feature_engineering_agent.py` (agent path).
- Modeling: joblib inference modules; some agent scoring paths degrade to stubs.
- Decision engine: `decision_engine/engine.py` (Decision API) and `agents/decision_engine_agent.py` (agent path).
- Governance: audit logger; compliance engine + RBAC exist but are not wired consistently into all execution paths.
- Reporting: HMDA-related utilities exist.

### Key modularity failures
- **Severe duplication of the “credit brain”** (features + policy implemented twice). This guarantees divergent decisions by channel—unacceptable in regulated decisioning.
- **Contract drift**: multiple incompatible request schemas / field names (`existing_debt` vs `existing_debt_amount`, `dti` vs `debt_to_income_ratio`, UUID vs freeform ids).
- **Unsafe rules execution**: agent decision engine evaluates YAML conditions using `eval` (even restricted builtins is not governance-grade).

---

## 4. Multi-Tenant Architecture Audit

### A. Tenant isolation
- No tenant identifier exists in canonical schemas, audit log, or BigQuery schemas.
- No tenant claims enforcement on reads/writes.

### B. Customization layer
- Global YAML config exists; no per-tenant config registry with version pinning + approval + audit.

### C. Resource allocation
- No tenant quotas, priority, or compute isolation.

### D. Scaling strategy
- No tenant onboarding automation or metadata layer.

---

## 5. Custom Ecosystem Capability

- Custom dashboards exist, but there is no tenant-scoped “metrics API” backed by warehouse aggregates.
- Model overrides are technically possible via MLflow/artifact paths, but there is no per-tenant binding, compatibility gate, or rollback.
- Policy customization exists only as YAML + `eval`, which is neither safe nor auditable.

---

## 6. Synthetic Data Limitation Analysis

- Synthetic data likely lacks path-dependent delinquency dynamics, edge-case null patterns, and cardinality explosions.
- Performance assumptions derived from synthetic data will be optimistic.
- Model validation risks: high AUC/KS on synthetic can fail stability once real distribution shift appears.

---

## 7. Missing Components (MOST IMPORTANT)

### A. Performance infrastructure
- Redis-backed rate limiting, idempotency, and request dedupe.
- Async-safe ingestion I/O and retries.
- Separation of CPU-heavy steps from API request threads.

### B. Platform modularity
- A canonical shared domain package used by BOTH Decision API and agent orchestrator.
- Stable API contracts and versioned schema management.
- A safe policy DSL and policy artifact lifecycle (approve, sign, rollback).

### C. Multi-tenant readiness
- Tenant context propagation (JWT → request context → storage partitions).
- Tenant config management + metadata service.

### D. Governance tech
- Consistent PIT feature usage across production scoring paths.
- Deterministic replay bundles: policy hash, model artifact hash, feature set version, config snapshot.

---

## 8. Target Architecture (Future-State Design)

### Recommendation: modular monolith for “credit-core” + “governance-core”, separate data plane services
- Regulated decisioning benefits from a single canonical engine + strict change control.
- Microservices are appropriate for ingestion/warehouse pipelines and non-critical analytics.

### Component diagram (textual)

**Control Plane**
- Tenant service (metadata, keys, quotas)
- Config registry (versioned, approved policy + feature set configs)
- Model registry (MLflow + signed artifacts + compatibility checks)

**Data Plane**
- Ingestion service → Event bus (Pub/Sub)
- Warehouse (BigQuery) bronze/silver/gold
- Offline PIT feature views in warehouse
- Online feature store (Redis) for low-latency decisions

**Decision Plane**
- Decision API (stateless) calling a shared `credit_core` library
- Audit/event store (append-only) with tenant partitioning

**Monitoring Plane**
- Drift + fair lending jobs reading warehouse + audit store
- Alerts router

### Interaction flows
- Online underwriting: JWT tenant_id → resolve tenant config → fetch/compute features → infer → policy → append-only audit event with full version pointers.
- Offline: ingestion → curated warehouse → PIT training sets → train/validate/promote → bind model to tenant(s) with rollback.

---

## 9. Performance Optimization Roadmap

### Phase 1 (0–3 months)
- Unify features + policy into one canonical engine used by all paths.
- Add tenant_id propagation end-to-end.
- Add Redis rate limiting + idempotency keys.
- Remove “stub mode succeeds” in any production path.
- Make ingestion API async-safe (no blocking I/O in event loop).

### Phase 2 (3–6 months)
- Warehouse-backed analytics semantic layer (pre-aggregated cohort/vintage tables).
- Policy registry with versioned, hashed, approved artifacts; remove `eval`.
- Bulk feature store write optimization.

### Phase 3 (6–12 months)
- Deployable streaming ETL pipeline; align monitoring to warehouse.
- Dedicated model serving if needed; regulator-grade deterministic replay.

---

## 10. Engineering Best Practices

- Enforce a single canonical DTO layer and contract tests across services.
- OpenTelemetry tracing across decision pipeline segments.
- CI gates: “Decision API output equals canonical engine output” golden tests.
- Data tests for PIT correctness, drift, and fairness metrics.

---

## Appendix — Core repo evidence consulted
- Orchestration: `orchestration/pipeline.py`
- Agents: `agents/*`
- Feature pipeline + store: `feature_pipeline/*`
- Decision engine: `decision_engine/engine.py`
- Audit: `audit/logger.py`
- Decision API: `decision-api/src/main.py`
- Ingestion API: `ingestion-api/src/main.py`
- BigQuery: `db/bigquery_client.py`, `db/bigquery_schema.py`, `agents/bq_writer_agent.py`
- UIs: `ui/*`, `dashboard/app.py`
