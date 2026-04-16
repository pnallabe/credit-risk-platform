# IMPLEMENTATION PLAN — GAP CLOSURE
## Credit Risk Platform — 2026-04-09

> **Source**: Gaps identified in `CORE_PLATFORM_TECH_AUDIT_2026_04_09.md`.
>
> **Structure**: Each item is a self-contained coding prompt. Execute prompts in the order listed.
> Each prompt states the exact files to modify, the acceptance criteria, and the required tests.

---

## Priority Legend

| Label | Meaning |
|-------|---------|
| `P1` | This sprint — blocks production readiness |
| `P2` | Next 4–8 weeks — blocks enterprise scale |
| `P3` | 6–12 weeks — infrastructure completeness |

---

## P1 — Immediate (this sprint)

---

### PROMPT-01 · Fix `iterrows()` in bulk feature store writes

**Priority**: P1
**Files to modify**: `feature_pipeline/feature_store.py`
**Test file**: `feature_pipeline/tests/` (add new test)

**Context**

`feature_pipeline/feature_store.py` contains the following function at line ~174:

```python
def _df_to_rows(df: pd.DataFrame, version: str, event_timestamp: datetime, as_of_date: date) -> List[Dict[str, Any]]:
    """Convert a DataFrame to a list of insert dicts."""
    return [_build_row(row, version, event_timestamp, as_of_date) for _, row in df.iterrows()]
```

`DataFrame.iterrows()` creates a Python object per row with full dtype boxing and is 10–50× slower than vectorised alternatives for large DataFrames. At 1 M+ rows this dominates write latency and blocks the async event loop if awaited from a sync thread.

**Task**

Replace `_df_to_rows` with a fully vectorised implementation that:

1. Uses `df.to_dict("records")` to convert the DataFrame to a list of raw Python dicts in one pass (O(n) with no per-row object creation overhead).
2. Passes each raw dict directly to `_build_row` — which already expects a dict-like — instead of a `pd.Series`.
3. Verifies that `_build_row` works correctly with a plain `dict` argument (it uses `.get()` so it is already compatible).
4. Adds a `benchmark_df_to_rows` test that creates a 100 000-row DataFrame, runs the old and new implementation, and asserts the new version is at least 2× faster (using `time.perf_counter`).
5. Adds a correctness test that asserts the old and new implementations produce identical output for a 10-row sample.

**Acceptance criteria**

- `_df_to_rows` no longer contains `iterrows`.
- `grep -r "iterrows" feature_pipeline/` returns no matches.
- The benchmark passes (new ≥ 2× faster than old on 100 k rows).
- All existing `feature_pipeline` tests pass.

---

### PROMPT-02 · Redis PROD health check at startup

**Priority**: P1
**Files to modify**: `decision-api/src/main.py`, `ingestion-api/src/main.py`
**New file**: `decision-api/src/health.py`
**Test file**: `tests/test_service_health.py`

**Context**

Both `RateLimitMiddleware` (`decision-api/src/middleware/rate_limit.py`) and `IdempotencyMiddleware` (`decision-api/src/middleware/idempotency.py`) degrade gracefully when Redis is unreachable — they log a warning and pass the request through. In development this is correct. In production (`ENVIRONMENT=prod`) this silently disables rate limiting and idempotency, allowing:

- Duplicate decisions to double-write audit records.
- A single tenant to exhaust compute under high traffic.

The ingestion API (`ingestion-api/src/main.py`) has the same issue for its Redis-backed batch deduplication.

**Task**

1. Create `decision-api/src/health.py` with an async `check_redis(url: str, timeout: float = 2.0) -> bool` function that attempts a `PING` command and returns `True` on success or `False` on failure/timeout. Use `redis.asyncio` (already a dependency).

2. In `decision-api/src/main.py`, inside the `startup_event` async function (around line 322), add the following logic **after** model loading:

```python
_ENVIRONMENT = os.getenv("ENVIRONMENT", "dev")
if _ENVIRONMENT == "prod":
    from health import check_redis
    _redis_ok = await check_redis(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    if not _redis_ok:
        raise RuntimeError(
            "[CRIT-05] ENVIRONMENT=prod but Redis is unreachable at REDIS_URL. "
            "Rate-limiting and idempotency are non-functional. "
            "Fix Redis connectivity or set ENVIRONMENT=dev to suppress this check."
        )
    logger.info("Redis connectivity verified at startup.")
```

3. Apply the same Redis health check pattern to `ingestion-api/src/main.py` inside its startup/lifespan block — when `ENVIRONMENT=prod`, assert Redis before accepting traffic.

4. Add a `GET /v1/health/dependencies` endpoint to `decision-api/src/main.py` that returns the live status of Redis, the audit DB, and the model cache. Schema:

```json
{
  "redis": "ok" | "degraded",
  "audit_db": "ok" | "degraded",
  "models": {"fraud": "loaded", "credit_risk": "loaded"},
  "environment": "prod" | "dev"
}
```

5. Write tests in `tests/test_service_health.py` that:
   - Mock `check_redis` returning `False` with `ENVIRONMENT=prod` and assert startup raises `RuntimeError`.
   - Mock `check_redis` returning `True` and assert startup succeeds.
   - Call `GET /v1/health/dependencies` with a mock Redis client and assert the response schema.

**Acceptance criteria**

- `uvicorn` refuses to start in `ENVIRONMENT=prod` with Redis down.
- `GET /v1/health/dependencies` returns `200` with the correct JSON schema.
- All test cases pass.

---

## P2 — Next 4–8 Weeks

---

### PROMPT-03 · Per-tenant batch concurrency semaphore

**Priority**: P2
**Files to modify**: `decision-api/src/main.py`
**Test file**: `tests/test_batch_api.py`

**Context**

`decision-api/src/main.py` uses a single global `asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)` for the batch endpoint:

```python
BATCH_CONCURRENCY_LIMIT: int = int(os.getenv("BATCH_CONCURRENCY_LIMIT", "50"))
_batch_semaphore: Optional[asyncio.Semaphore] = None
# ...
_batch_semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)
```

A single large tenant batch (e.g. 1 000 rows at 50 concurrency) can hold all 50 semaphore slots simultaneously, starving real-time single-decision requests from other tenants until the batch drains.

**Task**

1. Replace the single global semaphore with a `_TenantSemaphoreRegistry` class that maintains a `Dict[str, asyncio.Semaphore]` keyed by `tenant_id`. Acquire the tenant's semaphore for each batch item.

2. Semaphore limits per tenant must be resolved from `ConfigRegistryService` at request time via a new config key `batch_concurrency_limit` (integer). Fall back to a new env var `TENANT_BATCH_CONCURRENCY_DEFAULT` (default `10`) when the config key is absent.

3. A global hard cap `BATCH_CONCURRENCY_GLOBAL_LIMIT` (env var, default `50`) must remain. The sum of all in-flight batch items across all tenants must never exceed this cap. Implement this as a second semaphore that wraps the per-tenant semaphore: always acquire the global semaphore first, then the per-tenant semaphore.

4. The `_TenantSemaphoreRegistry` must be thread-safe and lazily create semaphores for new tenants.

5. Update `startup_event` to initialise only the global semaphore (per-tenant semaphores are created lazily).

6. Update the existing batch endpoint handler to acquire `(global_semaphore, tenant_semaphore)` using an `asyncio.gather`-compatible context manager pattern.

7. Write tests in `tests/test_batch_api.py` that:
   - Assert a large burst from tenant A does not prevent tenant B from acquiring slots.
   - Assert the global cap is enforced when multiple tenants submit concurrently.
   - Assert per-tenant limit from `ConfigRegistryService` is respected.

**Acceptance criteria**

- Semaphore is per-tenant with a global cap.
- No breaking change to the batch endpoint's external API contract.
- Tests pass.

---

### PROMPT-04 · Per-tenant model bindings in config registry

**Priority**: P2
**Files to modify**: `config_registry/models.py`, `config_registry/service.py`, `agents/risk_modeling_agent.py`, `orchestration/pipeline.py`
**Test file**: `tests/config_registry/` (add new test)

**Context**

`ConfigRegistryService.get_active(tenant_id)` returns a `TenantConfigVersion` whose `config_json` currently carries policy cutoffs, feature set parameters, and pricing config. There is no mechanism to bind a specific model artefact version to a tenant. All tenants share the single model paths set by environment variables.

**Task**

1. In `config_registry/models.py`, extend `TenantConfigVersion` with a helper method:

```python
def get_model_bindings(self) -> Dict[str, str]:
    """Return per-tenant model artefact URI overrides.

    Dict keys are model roles:
      "pd_champion", "pd_challenger",
      "fraud_champion",
      "cc_val_champion", "cc_val_challenger",
      "cc_port_champion", "cc_port_challenger",
      "mort_champion", "mort_challenger"

    Values are fully-qualified artefact URIs:
      "models:/credit_risk/Production"   (MLflow registry URI)
      "gs://my-bucket/models/credit_risk_v2.pkl"  (GCS path)
      "/app/models/credit_risk_v2.pkl"            (local path)

    Returns an empty dict if no model bindings are configured.
    """
    return self.config_json.get("model_bindings", {})
```

2. In `agents/risk_modeling_agent.py`, modify `__init__` to accept an optional `tenant_model_bindings: Dict[str, str]` argument. When bindings are provided, override the corresponding `self._champion_pd_path`, `self._fraud_model_path`, etc. fields **before** calling `_preload_agent_models()`.

3. In `orchestration/pipeline.py`, resolve model bindings from `_CONFIG_REGISTRY.get_active(tenant_id)` during pipeline construction and pass them to `RiskModelingAgent.__init__`. If no tenant config exists, use environment variable defaults (existing behaviour).

4. Write tests that:
   - Assert that when a tenant config contains `"model_bindings": {"pd_champion": "/tmp/test_model.pkl"}`, the agent uses that path (mock `preload`).
   - Assert that when no binding exists, the env-var default is used.
   - Assert that a binding with an invalid/missing artefact raises an error at pipeline construction (not at request time).

**Acceptance criteria**

- `RiskModelingAgent` reads model paths from tenant config when present.
- Env-var paths remain the fallback.
- No existing tests broken.

---

### PROMPT-05 · OpenTelemetry distributed tracing

**Priority**: P2
**New files**: `observability/tracing.py`, `observability/__init__.py`
**Files to modify**: `credit_core/features.py`, `credit_core/policy.py`, `audit/logger.py`, `decision-api/src/main.py`, `requirements.txt`
**Test file**: `tests/test_tracing.py`

**Context**

No distributed tracing instrumentation exists in any Python service. Cross-service latency — e.g. how long `compute_feature_matrix` vs `evaluate_policy` vs the audit write takes within a single decision — is invisible. This is a hard requirement for SRE triage and SR 11-7 audit trail completeness.

**Task**

1. Add to `requirements.txt`:
   ```
   opentelemetry-sdk>=1.24.0
   opentelemetry-api>=1.24.0
   opentelemetry-exporter-otlp-proto-http>=1.24.0
   opentelemetry-instrumentation-fastapi>=0.45b0
   ```

2. Create `observability/tracing.py` with:
   - A `configure_tracer(service_name: str) -> opentelemetry.trace.Tracer` function that initialises the SDK with OTLP HTTP export when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and falls back to a `ConsoleSpanExporter` otherwise.
   - A `span(name: str, tracer: Tracer, **attributes)` context manager (wraps `tracer.start_as_current_span`) that adds standard attributes: `service.name`, `tenant_id` (read from `audit.tenant_guard.TenantContext` if active), `environment`.
   - Export `TRACER: Tracer` as a module-level singleton initialised at import time using `service_name = os.getenv("OTEL_SERVICE_NAME", "credit-risk-platform")`.

3. In `credit_core/features.py`, wrap `compute_feature_matrix` with a span:
   ```python
   with span("credit_core.compute_feature_matrix", TRACER, feature_version=version, rows=len(df)):
       ...
   ```

4. In `credit_core/policy.py`, wrap `evaluate_policy` with a span:
   ```python
   with span("credit_core.evaluate_policy", TRACER, policy_version=policy_version, batch_size=len(scores_df)):
       ...
   ```

5. In `audit/logger.py`, wrap `log_decision` (the async function) with a span:
   ```python
   with span("audit.log_decision", TRACER):
       ...
   ```

6. In `decision-api/src/main.py`, add `FastAPIInstrumentor().instrument_app(app)` immediately after `app = FastAPI(...)`.

7. Write tests in `tests/test_tracing.py` using `opentelemetry.sdk.trace.export.InMemorySpanExporter`:
   - Assert `compute_feature_matrix` emits a span named `"credit_core.compute_feature_matrix"`.
   - Assert `evaluate_policy` emits a span named `"credit_core.evaluate_policy"`.
   - Assert both spans carry the `tenant_id` attribute when a `TenantContext` is active.
   - Assert that when `OTEL_EXPORTER_OTLP_ENDPOINT` is not set, initialisation succeeds (console fallback).

**Acceptance criteria**

- Spans are emitted for `compute_feature_matrix`, `evaluate_policy`, and `log_decision`.
- All spans carry `tenant_id` when a tenant context is present.
- Tracer initialisation is a no-op when the OTLP endpoint is not configured — no import errors.
- Tests pass with `InMemorySpanExporter`.

---

### PROMPT-06 · CI eval() grep gate + cross-service OpenAPI contract tests

**Priority**: P2
**New files**: `.github/workflows/contract_tests.yml`, `tests/integration/test_api_contracts.py`, `scripts/check_no_eval.sh`
**Files to modify**: `Makefile`, `pytest.ini`

**Context**

Two CI safety gates are missing:

1. **`eval()` in policy paths**: `decision_engine/policy_dsl.py` eliminated `eval()` from rule evaluation, but there is no automated check that prevents it from being re-introduced. A future contributor could add `eval(condition)` in any agent or engine file and CI would not catch it.

2. **Cross-service API contracts**: `tests/test_decision_parity.py` verifies Decision API vs agent pipeline parity at the Python function level, but there are no HTTP-level contract tests asserting that the Decision API and Analytics API JSON response schemas match their OpenAPI specs. A schema drift (e.g. a renamed field in `DecisionResponse`) would be discovered only at integration testing.

**Task — Part A: eval() grep gate**

1. Create `scripts/check_no_eval.sh`:
   ```bash
   #!/usr/bin/env bash
   # Fail if eval() or exec() appears in any production policy/agent/engine path.
   # Test files and this script itself are excluded.
   set -euo pipefail
   FORBIDDEN=$(grep -rn --include="*.py" \
       --exclude-dir=".venv" --exclude-dir="tests" \
       -E '\beval\s*\(' \
       agents/ decision_engine/ credit_core/ feature_pipeline/ orchestration/ \
       | grep -v "# noqa: eval-allowed" || true)
   if [[ -n "$FORBIDDEN" ]]; then
       echo "ERROR: eval() found in production policy paths:"
       echo "$FORBIDDEN"
       exit 1
   fi
   echo "eval() check passed."
   ```

2. Add a `make check-no-eval` target to `Makefile` that runs `scripts/check_no_eval.sh`.

3. Create `.github/workflows/contract_tests.yml` that runs `make check-no-eval` on every pull request to `main`.

**Task — Part B: OpenAPI contract tests**

4. Add to `requirements.txt`:
   ```
   jsonschema>=4.21.0
   ```

5. Create `tests/integration/test_api_contracts.py` using `fastapi.testclient.TestClient`:
   - Import `decision-api` `app` and `analytics_api` `app`.
   - Call `GET /openapi.json` on each.
   - For the Decision API, assert the `POST /v1/decisions` request schema matches a committed golden snapshot (`tests/integration/snapshots/decision_request.json`).
   - For the Decision API, assert the `POST /v1/decisions` response schema matches `tests/integration/snapshots/decision_response.json`.
   - For the Analytics API, assert `GET /v1/analytics/vintage-curves` response schema matches `tests/integration/snapshots/vintage_curves_response.json`.
   - On the first run (when no snapshot exists), generate the snapshot files and fail with a message that says "Snapshots created — commit them and rerun". Subsequent runs compare against committed snapshots.

6. Wire `tests/integration/test_api_contracts.py` into `pytest.ini` with marker `integration`.

7. Add `make contract-tests` to `Makefile`.

**Acceptance criteria**

- `make check-no-eval` exits non-zero if `eval(` is found in any production Python file under the listed directories.
- `make contract-tests` exits non-zero if any OpenAPI schema shape changes without updating the snapshots.
- GHA workflow runs both on every PR to `main`.

---

## P3 — 6–12 Weeks

---

### PROMPT-07 · Streaming ETL: Pub/Sub → BigQuery bronze/silver/gold

**Priority**: P3
**New files**: `etl/pubsub_consumer.py`, `etl/transformer.py`, `etl/bq_writer.py`, `etl/Dockerfile`, `etl/requirements.txt`, `deploy/cloud_run_etl.yaml`
**Files to modify**: `db/bigquery_schema.py`

**Context**

`ingestion-api/src/main.py` publishes structured event envelopes to Pub/Sub topic `ingestion.completed`. No downstream consumer exists — those events are never written to BigQuery. The warehouse bronze/silver/gold layer is schema-correct (tenant-partitioned, clustering defined) but permanently empty in production.

**Task**

1. Create `etl/pubsub_consumer.py` — a long-running Cloud Run service that:
   - Subscribes to the Pub/Sub subscription `PUBSUB_SUBSCRIPTION` (env var).
   - Pulls messages in batches of up to `PULL_BATCH_SIZE` (env var, default 100).
   - Passes each batch to `etl.transformer.transform_batch(messages)`.
   - Writes the result to BigQuery via `etl.bq_writer.write_batch(rows, table)`.
   - Acknowledges only after a successful BigQuery write (at-least-once delivery).
   - Implements exponential backoff on transient BQ errors.

2. Create `etl/transformer.py` with:
   - `transform_batch(messages: List[dict]) -> Tuple[List[dict], List[dict], List[dict]]` returning `(bronze_rows, silver_rows, gold_rows)`.
   - **Bronze**: raw JSON flattened to columns, no cleaning. Schema matches `db/bigquery_schema.py` `LOAN_APPLICATIONS_SCHEMA`.
   - **Silver**: bronze + type coercion, null handling, and deduplication on `(application_id, tenant_id)`. Any row that fails validation is written to a `_rejected` side table.
   - **Gold**: silver + denormalised decision outcome joined from the audit log (written in a separate scheduled job, not inline here — leave a `TODO(G3-gold)` comment).
   - All row types carry `tenant_id` (extracted from the Pub/Sub message `attributes` dict, not the payload body).

3. Create `etl/bq_writer.py` with:
   - `write_batch(rows: List[dict], project: str, dataset: str, table: str) -> int` — returns number of rows written.
   - Uses the BigQuery Storage Write API (`google.cloud.bigquery_storage`) for streaming rather than the legacy streaming insert to reduce costs and improve settlement time.
   - On partial failure (some rows rejected by BQ), writes rejected rows to `<table>_rejected` and returns the count of successful rows.

4. In `db/bigquery_schema.py`, add `bronze_*_rejected` schemas for each fact table (same columns as the main table plus `rejection_reason: STRING NULLABLE`).

5. Create `etl/Dockerfile` and `etl/requirements.txt` targeting Python 3.12 / Cloud Run.

6. Create `deploy/cloud_run_etl.yaml` (Cloud Run service definition) with:
   - `min-instances: 1`, `max-instances: 10`
   - `PUBSUB_SUBSCRIPTION`, `BQ_PROJECT`, `BQ_DATASET` as environment variable references to Secret Manager / substitution variables.
   - Memory: `1Gi`, CPU: `1`.

7. Write tests in `tests/integration/test_etl_transformer.py`:
   - Assert a well-formed Pub/Sub message produces the correct bronze row.
   - Assert a malformed message produces a rejected row with `rejection_reason` populated.
   - Assert `tenant_id` is always sourced from message `attributes`, never from payload body.

**Acceptance criteria**

- `etl/pubsub_consumer.py` runs as a standalone Cloud Run service.
- Bronze and silver rows are idempotent (re-processing the same Pub/Sub message produces no duplicate rows).
- `tenant_id` is always sourced from message attributes.
- `_rejected` side tables capture all invalid rows.

---

### PROMPT-08 · Deterministic replay bundle endpoint

**Priority**: P3
**Files to modify**: `decision-api/src/main.py`, `audit/logger.py`
**New file**: `audit/replay_bundle.py`
**Test file**: `tests/test_replay_bundle.py`

**Context**

A regulator-grade replay requires producing, for any historical decision, a single signed document that binds:
- The exact raw input fields received.
- The feature set version and the feature values computed.
- The model artefact hash (SHA-256 of the pickle file).
- The policy version hash and the exact policy parameter snapshot.
- The tenant config version and its SHA-256.
- The decision outcome and reason codes.
- The audit log row hash to prove the record was not tampered with.

None of these are assembled into a single retrievable artefact. `audit/logger.py` stores individual fields, and `chain_verifier.py` can verify the hash chain independently, but there is no "replay bundle" endpoint.

**Task**

1. Create `audit/replay_bundle.py` with:

```python
@dataclass(frozen=True)
class ReplayBundle:
    decision_id: str
    tenant_id: str
    decided_at: str                # ISO-8601 UTC
    raw_inputs: Dict[str, Any]     # exactly what was received in the request
    feature_version: str
    feature_values: Dict[str, Any]
    model_artifact_hashes: Dict[str, str]   # {"fraud_v1": "sha256:<hex>", "pd_v1": "sha256:<hex>"}
    policy_version: str
    policy_params_snapshot: Dict[str, Any]
    tenant_config_version: str
    tenant_config_sha256: str
    decision: str
    reason_codes: List[str]
    audit_log_row_hash: str        # from audit_log.current_hash
    bundle_sha256: str             # SHA-256 of the canonical JSON of all the above fields
```

`bundle_sha256` is computed over a deterministic JSON serialisation of all fields except `bundle_sha256` itself, using `json.dumps(payload, sort_keys=True, separators=(",", ":"))`.

2. Add `async def build_replay_bundle(decision_id: str, db_url: str, config_registry: ConfigRegistryService, policy_store: PolicyVersionStore) -> ReplayBundle` to `audit/replay_bundle.py`. It must:
   - Query the audit log for the row matching `decision_id`.
   - Query the feature store for features keyed to that decision's `as_of_date` and `feature_version`.
   - Query `PolicyVersionStore.get_as_of(decided_at)` for the exact policy params active at decision time.
   - Query `ConfigRegistryService.get_version(tenant_id, config_version)` for the tenant config snapshot.
   - Compute `model_artifact_hashes` by reading the artefact paths recorded in the audit row and computing `sha256(open(path, "rb").read())`.
   - Compute and attach `bundle_sha256`.

3. Add endpoint `GET /v1/decisions/{id}/replay-bundle` to `decision-api/src/main.py`:
   - Requires Bearer JWT; tenant scoping enforced (can only fetch own tenant's decisions).
   - Returns `ReplayBundle` as JSON.
   - Returns `404` if `decision_id` not found.
   - Returns `403` if `tenant_id` in audit row != `tenant_id` from JWT.

4. Write tests in `tests/test_replay_bundle.py`:
   - Assert `bundle_sha256` changes when any field of the bundle changes.
   - Assert `bundle_sha256` is deterministic (same inputs → same hash on repeated calls).
   - Assert tenant isolation: a request with `tenant_id=A` cannot retrieve `tenant_id=B`'s bundle.
   - Assert `404` when `decision_id` does not exist.

**Acceptance criteria**

- `GET /v1/decisions/{id}/replay-bundle` returns a complete `ReplayBundle` in < 500 ms for a local SQLite audit DB.
- `bundle_sha256` is cryptographically deterministic.
- Tenant isolation is enforced at the endpoint level.
- Tests pass.

---

### PROMPT-09 · External metrics sink (Prometheus + Cloud Monitoring)

**Priority**: P3
**New files**: `observability/metrics_pusher.py`
**Files to modify**: `decision-api/src/main.py`, `requirements.txt`
**Test file**: `tests/test_metrics_pusher.py`

**Context**

`decision-api/src/main.py` maintains a `_ServiceMetrics` object (rolling deque, in-process, thread-safe) that provides p50/p95/p99 latency and error rate. This is ephemeral — it resets on every restart and is not scraped by any external system. There is no Prometheus endpoint and no push to Cloud Monitoring.

For production SRE:
- p95/p99 alerts require persistent time-series data.
- The Canary deploy logic checks `_METRICS.snapshot()["canary_healthy"]` — this will never catch latency regressions after a restart.

**Task**

1. Add to `requirements.txt`:
   ```
   prometheus-client>=0.20.0
   ```

2. Create `observability/metrics_pusher.py` with:
   - A `MetricsCollector` class that exposes the following Prometheus metrics:
     - `credit_decision_latency_seconds` — `Histogram` with buckets `[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]`, labels `["tenant_id", "route", "environment"]`.
     - `credit_decision_errors_total` — `Counter`, labels `["tenant_id", "route", "status_code"]`.
     - `credit_decision_requests_total` — `Counter`, labels `["tenant_id", "route"]`.
   - A `record(latency_s: float, tenant_id: str, route: str, status_code: int)` method that increments all three metrics.
   - A `make_asgi_app()` method that returns a Prometheus ASGI `/metrics` endpoint using `prometheus_client.make_asgi_app()`.

3. In `decision-api/src/main.py`:
   - Instantiate `MetricsCollector` at module level.
   - Mount the Prometheus ASGI app at `/metrics` using `app.mount("/metrics", collector.make_asgi_app())`.
   - Update `_metrics_middleware` to call `MetricsCollector.record(...)` in addition to the existing `_METRICS.record(...)` call. Extract `tenant_id` from the request state (set by `RateLimitMiddleware`) and `route` from `request.url.path`.
   - Retain the existing `_ServiceMetrics` rolling deque for the `/v1/metrics` JSON endpoint (backward-compatible).

4. **Cloud Monitoring push (optional, guarded by env var)**:
   In `observability/metrics_pusher.py`, add a `push_to_cloud_monitoring(project_id: str, metrics_snapshot: Dict) -> None` function that uses `google.cloud.monitoring_v3` to write a `custom.googleapis.com/credit_risk/p99_latency_ms` time series. Guard this behind `ENABLE_CLOUD_MONITORING=true` (env var). Add `google-cloud-monitoring>=2.20.0` to `requirements.txt` only as a conditional extras requirement so it does not break installs without GCP credentials.

5. Write tests in `tests/test_metrics_pusher.py`:
   - Assert `GET /metrics` returns `200` and contains `credit_decision_latency_seconds_bucket`.
   - Assert that recording a latency sample increments the histogram.
   - Assert that a `5xx` response increments `credit_decision_errors_total`.

**Acceptance criteria**

- `GET /metrics` on the Decision API returns Prometheus-compatible text format.
- Latency histogram and error counter are populated after requests.
- Existing `/v1/metrics` JSON endpoint is unaffected.
- Tests pass without GCP credentials.

---

## Execution Summary

| # | Prompt | Priority | Files | Tests |
|---|--------|---------|-------|-------|
| 01 | Fix `iterrows()` in feature store | P1 | `feature_pipeline/feature_store.py` | `feature_pipeline/tests/` |
| 02 | Redis PROD health check at startup | P1 | `decision-api/src/main.py`, `ingestion-api/src/main.py` | `tests/test_service_health.py` |
| 03 | Per-tenant batch concurrency semaphore | P2 | `decision-api/src/main.py` | `tests/test_batch_api.py` |
| 04 | Per-tenant model bindings in config registry | P2 | `config_registry/models.py`, `config_registry/service.py`, `agents/risk_modeling_agent.py` | `tests/config_registry/` |
| 05 | OpenTelemetry distributed tracing | P2 | `observability/tracing.py`, `credit_core/*.py`, `audit/logger.py` | `tests/test_tracing.py` |
| 06 | CI eval() gate + OpenAPI contract tests | P2 | `.github/workflows/`, `tests/integration/` | `tests/integration/test_api_contracts.py` |
| 07 | Streaming ETL Pub/Sub → BQ | P3 | `etl/`, `db/bigquery_schema.py` | `tests/integration/test_etl_transformer.py` |
| 08 | Deterministic replay bundle endpoint | P3 | `audit/replay_bundle.py`, `decision-api/src/main.py` | `tests/test_replay_bundle.py` |
| 09 | External metrics sink (Prometheus) | P3 | `observability/metrics_pusher.py`, `decision-api/src/main.py` | `tests/test_metrics_pusher.py` |
