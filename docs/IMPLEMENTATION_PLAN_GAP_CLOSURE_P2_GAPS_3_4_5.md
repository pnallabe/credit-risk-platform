# Implementation Plan: Gap Closure — Priority 2 (GAPs 3, 4, 5)
## Integrated Lending Operating Layer (ILOL) — credit-risk-platform

**Version:** 1.0.0
**Date:** April 7, 2026
**Scope:** GAP-03 (Multi-Tenant Query Isolation), GAP-04 (Policy-Level Champion/Challenger A/B), GAP-05 (CRA / FCRA / UDAAP Reporting)
**Reference:** PRD v1.0.0 §6.5, §4.3, §8.4
**Predecessor:** `docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md` (P1 hash chain + adverse action)

---

## Overview

This document provides a sequential series of coding prompts, each self-contained and implementation-ready. Each prompt specifies:
- The **exact files** to create or modify
- The **interfaces** to implement against existing code
- The **acceptance tests** that determine "done"
- All **constraints** from the PRD and existing architecture

Work the prompts in order within each gap section. Gaps may be worked in parallel by separate engineers once their shared-file dependencies are understood. Dependencies between gaps are called out explicitly.

---

## GAP-03: Multi-Tenant Query Layer Isolation

### Background

The PRD (§6.5, §7.4) requires that every data access operation enforces `tenant_id` row-level scoping such that cross-tenant data leakage is architecturally impossible. The current codebase has partial protection:

- `audit/logger.py` — `log_decision()` and `get_audit_record()` both require `tenant_id` and scope SQL queries with it; this is correct.
- `decision-api/src/main.py` — `verify_bearer()` extracts `tenant_id` from the JWT and propagates it to `_run_pipeline()` correctly for the main decision path.
- **Gap 1**: `orchestration/pipeline.py` accepts `tenant_id: Optional[str] = None` in `CreditRiskPipeline.run()` — callers that omit `tenant_id` get an unscoped pipeline run with no tenant enforcement.
- **Gap 2**: `decision-api/src/main.py` — `GET /v1/decisions/{id}/audit` calls `get_audit_record(application_id, DB_URL, tenant_id)` which enforces tenant scoping in the SQL `WHERE` clause, but the endpoint does not re-verify that the returned record's `tenant_id` field matches the JWT `tenant_id` in the application layer (relies solely on the DB predicate).
- **Gap 3**: Internal analytics scripts and batch scoring paths (e.g., `scripts/batch_score.py`) accept a `--db-url` flag and query without a `tenant_id` bound, creating an admin-level bypass.
- **Gap 4**: `db/bigquery_schema.py` defines `tenant_id` in BigQuery table schemas but no row-level access policy (IAM condition policy) is provisioned.

---

### Prompt G3-A: Make `tenant_id` Mandatory in the Orchestration Pipeline

**File to modify:** `orchestration/pipeline.py`

**Context:** `CreditRiskPipeline.run()` currently takes `tenant_id: Optional[str] = None`. When `None` is passed, the pipeline resolves an empty `tenant_cfg` and proceeds without any tenant-scoped audit writes. All `log_decision()` calls downstream require `tenant_id` — but callers can silently pass `None` at the pipeline level, allowing an unscoped run.

**Task:**

1. Change the signature of `CreditRiskPipeline.run()` to make `tenant_id` a **required positional keyword argument** with type `str` (no default):
   ```python
   def run(
       self,
       applicant_dicts: List[Dict[str, Any]],
       tenant_id: str,                          # ← now required, no default
       experiment_id: Optional[str] = None,
       use_challenger: bool = False,
       source: str = "pipeline",
   ) -> PipelineRun:
   ```

2. At the top of `run()`, **before** any config resolution, add a guard:
   ```python
   if not tenant_id or not tenant_id.strip():
       raise ValueError(
           "tenant_id is required for all pipeline runs. "
           "Pass the tenant_id extracted from the request JWT."
       )
   ```

3. Add `tenant_id` to the `PipelineRun` dataclass as a field:
   ```python
   tenant_id: str = ""
   ```
   Assign it in `run()` immediately after the guard check:
   ```python
   pipeline_run = PipelineRun(
       run_id=run_id,
       tenant_id=tenant_id,
       started_at=...,
       ...
   )
   ```
   Include `tenant_id` in `PipelineRun.to_dict()`.

4. Thread `tenant_id` into the payload passed to the `DecisionEngineAgent` stage so it reaches `log_decision()`:
   - Add `"tenant_id": tenant_id` to the payload dict that is passed to `self._decision_engine.execute(...)`.
   - Also add it to the `MonitoringAgent` and `BQWriterAgent` stage payloads if those agents accept a `tenant_id` key.

5. Update `CreditRiskPipeline.from_config()` — if a `default_tenant_id` key is present in the YAML config, store it on the pipeline instance as `self._default_tenant_id` so that batch callers passing no explicit `tenant_id` can fall through to a platform-level default. This must **not** silently suppress the guard — callers must still explicitly pass `tenant_id=pipeline._default_tenant_id` if they want to use the default.

**Constraints:**
- Do **not** break the `from_config()` class method — it must still work with the existing `config/agent_config.yaml`
- Do **not** change any agent `execute()` signatures — thread `tenant_id` through the payload dict only
- The guard must raise `ValueError`, not `HTTPException` — the API layer handles HTTP error codes

**Acceptance test file:** `orchestration/tests/test_pipeline_tenant_guard.py`

Write tests that:
1. Calling `pipeline.run(applicant_dicts=[...], tenant_id="")` raises `ValueError` with a message containing `"tenant_id is required"`
2. Calling `pipeline.run(applicant_dicts=[...])` (omitting `tenant_id` entirely) raises `TypeError` from Python's argument binding
3. `pipeline.run(..., tenant_id="tenant-abc")` returns a `PipelineRun` whose `.to_dict()["tenant_id"]` equals `"tenant-abc"`
4. The returned `PipelineRun.tenant_id` is `"tenant-abc"` (field access, not just dict serialization)

---

### Prompt G3-B: Application-Layer Tenant Re-Verification on Audit Record Reads

**File to modify:** `decision-api/src/main.py`

**Context:** `GET /v1/decisions/{id}/audit` calls `get_audit_record(application_id, DB_URL, tenant_id)`. The SQL query already includes `WHERE tenant_id = :tenant_id`, so a cross-tenant row will not be returned. The implicit assumption is correct — but it is "security by DB predicate" only. If the DB predicate is ever removed, refactored, or the function is called via a different path, the application layer has no explicit check. The PRD (§7.4) requires cross-tenant leakage to be "architecturally impossible, not policy-dependent" — meaning defence in depth at both layers.

**Task:**

1. After the `get_audit_record()` call in the `GET /v1/decisions/{id}/audit` endpoint handler, add an explicit assertion:

   ```python
   if record is None:
       raise HTTPException(status_code=404, detail="Audit record not found")

   # Defence-in-depth: re-verify tenant_id at application layer
   record_tenant = record.get("tenant_id")
   if record_tenant != tenant_id:
       logger.warning(
           "SECURITY: Audit record tenant_id %s does not match JWT tenant_id %s "
           "for application_id=%s — possible mis-routed query",
           record_tenant,
           tenant_id,
           application_id,
       )
       raise HTTPException(
           status_code=403,
           detail="Forbidden: audit record does not belong to this tenant",
       )
   ```

2. Apply the **same pattern** to every other endpoint in `decision-api/src/main.py` that retrieves a record by ID from the database:
   - Any `GET /v1/decisions/{id}/...` variants
   - Any `POST /v1/decisions/{id}/...` mutation endpoints
   - The batch audit endpoint if it exists

3. Add a private helper function near `verify_bearer()`:
   ```python
   def _assert_tenant_owns_record(
       record: Dict[str, Any] | None,
       expected_tenant_id: str,
       resource_type: str,
       resource_id: str,
   ) -> None:
       """Raise HTTP 403 if the record's tenant_id does not match the JWT tenant.
       Raise HTTP 404 if the record is None.
       """
   ```
   Replace the inline assertion added in step 1 with a call to `_assert_tenant_owns_record()`.

**Constraints:**
- The helper must log a `WARNING` (not raise silently) before raising `HTTPException(403)` so SOC monitoring can detect anomalous access patterns
- Do **not** modify `get_audit_record()` in `audit/logger.py` — the defence is applied in the API layer, not the data layer
- All existing endpoint tests must continue to pass

**Acceptance test file:** `decision-api/tests/test_tenant_isolation.py`

Write tests that:
1. A request with JWT `tenant_id="tenant-a"` for an audit record owned by `"tenant-a"` returns `200`
2. A request with JWT `tenant_id="tenant-a"` for an audit record owned by `"tenant-b"` returns `403` even if the DB query "mistakenly" returned the record (simulate by monkeypatching `get_audit_record` to return a record with `tenant_id="tenant-b"`)
3. A request for a non-existent record returns `404`
4. The `403` path emits a `WARNING` log line containing the string `"SECURITY"`

---

### Prompt G3-C: Tenant-Scoped Analytics Script Guard

**Files to create:** `audit/tenant_guard.py`
**Files to modify:** Any existing script that takes `--db-url` and queries without `tenant_id`

**Context:** Scripts in `scripts/` (e.g., `batch_score.py`, `check_audit_completeness.py`) directly construct DB connections using `--db-url` CLI arguments without binding a `tenant_id`, creating an admin-level bypass path. While admin-level access is sometimes necessary, it must be explicit and audited.

**Task:**

Create `audit/tenant_guard.py` with the following:

1. A `TenantContext` dataclass:
   ```python
   @dataclass(frozen=True)
   class TenantContext:
       tenant_id: str
       source: str              # e.g. "jwt", "admin_override", "batch_job"
       authorized_by: str       # e.g. caller identity / service account name
   ```

2. A context variable for the current tenant:
   ```python
   import contextvars
   _CURRENT_TENANT: contextvars.ContextVar[Optional[TenantContext]] = \
       contextvars.ContextVar("current_tenant", default=None)
   ```

3. A context manager `scoped_tenant(ctx: TenantContext)` that sets `_CURRENT_TENANT` for the duration of a `with` block and resets it on exit.

4. A function `require_tenant_context() -> TenantContext` that:
   - Gets `_CURRENT_TENANT.get()`
   - Raises `RuntimeError("No tenant context — call scoped_tenant() before executing tenant-scoped queries")` if `None`
   - Returns the `TenantContext` if set

5. A decorator `@tenant_scoped` that can be applied to any function. It calls `require_tenant_context()` at the start of the function and injects the `tenant_id` into the kwargs if the function signature accepts a `tenant_id` parameter.

6. A module-level function `admin_override(tenant_id: str, authorized_by: str)` that returns a `scoped_tenant()` context manager pre-filled with `source="admin_override"`. This makes admin bypasses explicit and grep-able:
   ```python
   with admin_override("tenant-abc", authorized_by="data-eng-team"):
       # access is scoped but admin-elevated
       ...
   ```

**Modify** `scripts/batch_score.py` (if it exists) to:
- Accept `--tenant-id` as a required CLI argument
- Wrap the main body in `with scoped_tenant(TenantContext(tenant_id=args.tenant_id, source="batch_job", authorized_by="cli")):`

**Acceptance test file:** `audit/tests/test_tenant_guard.py`

Write tests that:
1. Calling `require_tenant_context()` outside a `scoped_tenant()` block raises `RuntimeError` containing `"No tenant context"`
2. Inside `scoped_tenant(TenantContext("t1", "jwt", "user@example.com"))`, `require_tenant_context().tenant_id == "t1"`
3. After the `with scoped_tenant(...)` block exits, `require_tenant_context()` raises `RuntimeError` again (reset verified)
4. `admin_override()` returns a context manager that sets `source="admin_override"` on the `TenantContext`
5. `@tenant_scoped` on a function that accepts `tenant_id` injects the correct `tenant_id` from context into the kwargs

---

### Prompt G3-D: BigQuery Row-Level Access Policy Provisioning Script

**File to create:** `scripts/provision_bq_tenant_policies.py`

**Context:** `db/bigquery_schema.py` defines BigQuery table schemas with a `tenant_id` column, but IAM row-level access policies (BigQuery `ROW ACCESS POLICIES`) are not provisioned. Without them, any service account with `bigquery.dataViewer` on the dataset can read all tenants' data.

**Task:**

Create `scripts/provision_bq_tenant_policies.py` that:

1. Accepts CLI arguments:
   ```
   --project       GCP project ID
   --dataset       BigQuery dataset ID
   --tenant-id     Tenant ID to provision policy for
   --service-account  Service account email to grant row-level access to
   --dry-run       Print DDL without executing
   ```

2. Creates a BigQuery row-level access policy using the `google-cloud-bigquery` SDK:
   ```python
   from google.cloud import bigquery

   policy_name = f"tenant_{tenant_id.replace('-', '_')}_policy"
   ddl = f"""
   CREATE ROW ACCESS POLICY {policy_name}
   ON `{project}.{dataset}.audit_log`
   GRANT TO ("serviceAccount:{service_account}")
   FILTER USING (tenant_id = '{tenant_id}');
   """
   ```

3. Applies the DDL to **all** tenant-bearing tables in the dataset:
   - `audit_log`
   - `portfolio_audit_log`
   - Any table whose schema (from `db/bigquery_schema.py`) includes a `tenant_id` field

4. Implements an idempotency check: before creating a policy, query `INFORMATION_SCHEMA.ROW_ACCESS_POLICIES` and skip creation if a policy with the same name already exists.

5. In `--dry-run` mode, prints each DDL statement to stdout without executing.

6. Logs every provisioned / skipped policy to stdout in JSON format for audit trail ingestion.

**Constraints:**
- Must use `google-cloud-bigquery>=3.0.0` (already in `requirements.txt`)
- Must not break if `--dry-run` is passed and no GCP credentials are available (the DDL generation must not require a live connection)
- The BigQuery `ROW ACCESS POLICY` syntax requires `FILTER USING (...)` not `WHERE` — use correct syntax

**Acceptance test file:** `scripts/tests/test_provision_bq_tenant_policies.py`

Write tests that (using mocked BigQuery client):
1. `--dry-run` mode generates the expected DDL for a given `--tenant-id` without calling any BigQuery API methods
2. When a policy with the same name already exists in mocked `INFORMATION_SCHEMA`, the CREATE is skipped and a "skipped" log entry is emitted
3. When the policy does not exist, a `client.query(ddl)` call is made with the correct DDL string

---

## GAP-04: Policy-Level Champion/Challenger A/B Framework

### Background

The PRD (§4.3, §6.3) requires champion/challenger routing at **both** the ML model layer and the policy rule layer, with per-tenant traffic split configuration. Currently:

- `decisioning/champion_challenger.py` — `ChampionChallengerRouter` provides deterministic, hash-based traffic splitting at the **ML model** level (`champion: ModelConfig`, `challenger: Optional[ModelConfig]`). This is complete.
- `decision_engine/policy_version_store.py` — `PolicyVersionStore` tracks policy versions as an append-only ledger and supports point-in-time replay. It does **not** support traffic splitting — a tenant always uses the single `is_active=1` version. `rollback()` exists but is manual with no automatic metric-based revert.

The fix requires a new **policy-level A/B framework** modelled after the existing model-level framework, but operating on `PolicyVersion` objects rather than `ModelConfig` objects.

---

### Prompt G4-A: Add `PolicyChallengerConfig` and `PolicySplitStore` to `decision_engine/`

**Files to create:** `decision_engine/policy_challenger.py`

**Context:** The existing `PolicyVersionStore` in `policy_version_store.py` is a ledger. We need a parallel lightweight store that tracks which two policy versions are currently in a champion/challenger split, records per-application routing decisions, and accumulates comparison metrics. This must not modify the existing `PolicyVersionStore` interface.

**Task:**

Create `decision_engine/policy_challenger.py` with:

1. A `PolicyChallengerConfig` dataclass:
   ```python
   @dataclass(frozen=True)
   class PolicyChallengerConfig:
       role: Literal["CHAMPION", "CHALLENGER"]
       version_id: int              # PolicyVersion.id from policy_version_store
       version_tag: str             # e.g. "v1.0", "v2.0-challenger"
       traffic_pct: float           # 0.0–1.0 of traffic sent to this policy
       tenant_id: str               # tenant this split applies to
       active: bool = True
   ```

2. A `PolicyDecisionRecord` dataclass:
   ```python
   @dataclass(frozen=True)
   class PolicyDecisionRecord:
       application_id: str
       timestamp: datetime
       tenant_id: str
       role: str                    # "CHAMPION" or "CHALLENGER"
       version_id: int
       version_tag: str
       decision: str                # "APPROVE" / "APPROVE_WITH_CONDITIONS" / "REJECT"
       apr: Optional[float]
       credit_limit: Optional[float]
       is_shadow: bool              # True = shadow mode (no live authority)
   ```

3. A `PolicyComparisonReport` dataclass with the same shape as `ChallengerComparisonReport` in `champion_challenger.py`, but with `champion_version_tag` and `challenger_version_tag` fields instead of model version fields.

4. A DDL constant `_CREATE_POLICY_DECISIONS_TABLE`:
   ```sql
   CREATE TABLE IF NOT EXISTS policy_decisions (
       id              INTEGER PRIMARY KEY AUTOINCREMENT,
       application_id  TEXT NOT NULL,
       timestamp       TEXT NOT NULL,
       tenant_id       TEXT NOT NULL,
       role            TEXT NOT NULL,
       version_id      INTEGER NOT NULL,
       version_tag     TEXT NOT NULL,
       decision        TEXT NOT NULL,
       apr             REAL,
       credit_limit    REAL,
       is_shadow       INTEGER NOT NULL
   );
   CREATE INDEX IF NOT EXISTS idx_pd_tenant_ts ON policy_decisions(tenant_id, timestamp);
   ```

5. A `PolicySplitStore` class (synchronous SQLAlchemy, same pattern as `CCDecisionStore`):
   - `__init__(self, db_url: str = "sqlite:///./policy_challenger.db")`
   - `add(self, record: PolicyDecisionRecord) -> None`
   - `generate_comparison_report(self, tenant_id: str, lookback_days: int = 7) -> PolicyComparisonReport` — scoped by `tenant_id`
   - `get_active_split(self, tenant_id: str) -> Optional[tuple[PolicyChallengerConfig, PolicyChallengerConfig]]` — returns `(champion_cfg, challenger_cfg)` or `None` if no active split for this tenant. Reads from a `policy_splits` table defined as:
     ```sql
     CREATE TABLE IF NOT EXISTS policy_splits (
         id          INTEGER PRIMARY KEY AUTOINCREMENT,
         tenant_id   TEXT NOT NULL,
         role        TEXT NOT NULL,
         version_id  INTEGER NOT NULL,
         version_tag TEXT NOT NULL,
         traffic_pct REAL NOT NULL,
         active      INTEGER NOT NULL DEFAULT 1,
         created_at  TEXT NOT NULL
     );
     ```
   - `set_split(self, champion: PolicyChallengerConfig, challenger: PolicyChallengerConfig) -> None` — deactivates any existing split for the tenant then inserts the new champion/challenger pair

**Constraints:**
- `PolicySplitStore.generate_comparison_report()` must always filter by `tenant_id` — no cross-tenant query path
- `set_split()` must validate that `champion.tenant_id == challenger.tenant_id` and both configs are for the same tenant
- All datetimes must be stored as ISO-8601 UTC strings (same convention as `CCDecisionStore`)
- Must work with both `sqlite://` and `postgresql://` connection strings

**Acceptance test file:** `decision_engine/tests/test_policy_challenger.py`

Write tests that:
1. `PolicySplitStore.set_split()` inserts a champion and challenger row with `active=1`
2. Calling `set_split()` again for the same tenant deactivates the previous split before inserting the new one
3. `get_active_split("tenant-a")` returns the correct `(champion, challenger)` tuple
4. `get_active_split("tenant-b")` when no split has been configured for `tenant-b` returns `None`
5. `PolicySplitStore.add()` + `generate_comparison_report()` correctly computes approval rates and returns a `PolicyComparisonReport` with the correct `recommendation`
6. `generate_comparison_report("tenant-a")` does not include records for `"tenant-b"` even when both tenants have records in the same DB

---

### Prompt G4-B: Implement `PolicyChallengerRouter`

**File to modify:** `decision_engine/policy_challenger.py`

**Context:** The data layer from G4-A now exists. This prompt adds the routing logic — the equivalent of `ChampionChallengerRouter` but for policy versions.

**Task:**

Add a `PolicyChallengerRouter` class to `decision_engine/policy_challenger.py`:

1. Constructor:
   ```python
   class PolicyChallengerRouter:
       def __init__(
           self,
           champion: PolicyChallengerConfig,
           challenger: Optional[PolicyChallengerConfig],
           store: PolicySplitStore,
           policy_store: "PolicyVersionStore",    # from policy_version_store
           random_seed: Optional[int] = None,
       ):
   ```
   - Validate `champion.role == "CHAMPION"` and `challenger.role == "CHALLENGER"` (if not None)
   - Validate `champion.tenant_id == challenger.tenant_id` (if challenger is not None)

2. A `route(self, application_id: str) -> Literal["CHAMPION", "CHALLENGER"]` method using the **same deterministic SHA-256 hash-bucket algorithm** as `ChampionChallengerRouter.route()` — use `f"{application_id}:policy:{self.salt}"` as the pre-image (different salt namespace from model routing to ensure decorrelated routing when both are active simultaneously).

3. A `get_policy_params(self, application_id: str) -> tuple[Literal["CHAMPION", "CHALLENGER"], Dict[str, Any]]` method that:
   - Calls `route(application_id)` to determine which policy version to use
   - Retrieves the `PolicyVersion` from `self.policy_store.get_by_id(version_id)` for the routed config
   - Returns `(role, policy_version.parameters)`

4. A `record_outcome(self, application_id: str, role: str, version_id: int, version_tag: str, decision: str, apr: Optional[float], credit_limit: Optional[float], is_shadow: bool) -> None` method that creates and persists a `PolicyDecisionRecord`.

5. A `promote_challenger(self, promoted_by: str, note: str, policy_version_store: "PolicyVersionStore") -> int`:
   - Asserts `self.challenger is not None`
   - Calls `policy_version_store.publish()` to create a new version that copies the challenger's parameters, with `author=promoted_by` and `note=f"promoted from challenger {self.challenger.version_tag}: {note}"`
   - Returns the new version's `id`
   - Does **not** call `policy_version_store.set_active()` — the caller is responsible for activating the new version after four-eyes approval (see GAP-11)

6. A `auto_rollback_if_regressed(self, lookback_days: int = 7, max_approval_rate_delta: float = 0.05, max_pd_increase_pct: float = 0.10) -> bool`:
   - Calls `self.store.generate_comparison_report()` for `self.champion.tenant_id`
   - If `report.recommendation == "REJECT"` (challenger approval rate delta > threshold and challenger PD significantly higher), deactivates the split by calling `self.store.set_split()` with the champion in both slots (traffic_pct=1.0 for champion, 0.0 for challenger)
   - Logs a `WARNING` with the report metrics and rollback action
   - Returns `True` if rollback was triggered, `False` otherwise

**Constraints:**
- `get_policy_params()` must raise `ValueError` if `policy_version_store.get_by_id()` returns `None` (version was deleted from the store)
- `promote_challenger()` must assert that the comparison report `recommendation != "REJECT"` before promoting — raise `RuntimeError("Cannot promote challenger: current comparison report recommends REJECT")` if the check fails
- The routing salt must use a different namespace from the model-level router to prevent accidental correlation

**Acceptance test file:** Add to `decision_engine/tests/test_policy_challenger.py`:
1. `route()` is deterministic: calling it twice with the same `application_id` returns the same role
2. An `application_id` hash-bucketed to 30% traffic should route to CHALLENGER when challenger has `traffic_pct=0.50` and to CHAMPION when `traffic_pct=0.20`
3. `get_policy_params()` raises `ValueError` when the `PolicyVersionStore` has no version matching the config's `version_id`
4. `auto_rollback_if_regressed()` returns `True` and updates the split when the report recommendation is `"REJECT"`
5. `promote_challenger()` raises `RuntimeError` when the current report recommends `"REJECT"`

---

### Prompt G4-C: Wire Policy-Level Routing into the Decision API

**Files to modify:** `decision-api/src/main.py`, `orchestration/pipeline.py`

**Context:** The model-level champion/challenger router is instantiated in `decision-api/src/main.py`'s startup in `_run_pipeline()`. The new policy-level router needs to be instantiated and wired in alongside it. The decision flow is: `route_policy() → get_policy_params() → evaluate_policy(params) → route_model() → predict_pd() → make_decision()`.

**Task:**

**In `decision-api/src/main.py`:**

1. At module startup (inside `startup_event()` or at module level), instantiate a `PolicySplitStore`:
   ```python
   _POLICY_SPLIT_STORE = PolicySplitStore(
       db_url=os.getenv("POLICY_SPLIT_DB_URL", "sqlite:///./policy_challenger.db")
   )
   ```

2. Modify `_run_pipeline()` to accept and use policy-level routing:
   - After extracting `tenant_id` from the request, call `_POLICY_SPLIT_STORE.get_active_split(tenant_id)`.
   - If a split is active, instantiate `PolicyChallengerRouter` and call `get_policy_params(application_id)` to get `(policy_role, policy_params)`.
   - Pass `policy_params` to `evaluate_policy()` instead of the default config-registry params.
   - After the decision is computed, call `router.record_outcome(...)`.
   - If no split is active, use existing logic unchanged.

3. Add two new admin endpoints (require JWT with `role=platform_admin` claim in addition to `tenant_id`):

   **`POST /v1/admin/policy-split/{tenant_id}`**
   - Request body: `{ "champion_version_id": int, "challenger_version_id": int, "challenger_traffic_pct": float }`
   - Validates both version IDs exist in `PolicyVersionStore`
   - Calls `_POLICY_SPLIT_STORE.set_split(champion, challenger)`
   - Returns `{ "status": "ok", "tenant_id": ..., "challenger_traffic_pct": ... }`

   **`DELETE /v1/admin/policy-split/{tenant_id}`**
   - Deactivates the challenger by setting `traffic_pct=0.0` for that tenant
   - Returns `{ "status": "deactivated", "tenant_id": ... }`

4. Add a read endpoint (accessible to any authenticated tenant user):

   **`GET /v1/admin/policy-split/{tenant_id}/report`**
   - Returns `PolicyComparisonReport.to_dict()` for the given tenant's active split lookback
   - Returns `404` if no split is configured for this tenant

**Constraints:**
- The `POST /v1/admin/policy-split/{tenant_id}` endpoint must enforce `tenant_id` in the JWT matches the path parameter (a tenant cannot configure splits for other tenants)
- `challenger_traffic_pct` must be validated `> 0.0` and `<= 0.50` (no challenger gets more than half the traffic)
- `evaluate_policy()` must receive the full `policy_params` dict — do not hard-code individual thresholds from the params dict in the route handler

**Acceptance test file:** `decision-api/tests/test_policy_split_endpoints.py`

Write tests that:
1. `POST /v1/admin/policy-split/tenant-a` with valid version IDs returns `200`
2. `POST /v1/admin/policy-split/tenant-a` with `challenger_traffic_pct=0.60` returns `422`
3. `POST /v1/admin/policy-split/tenant-b` with JWT `tenant_id="tenant-a"` returns `403`
4. `GET /v1/admin/policy-split/tenant-a/report` with no active split returns `404`
5. `DELETE /v1/admin/policy-split/tenant-a` with an active split deactivates it and returns `200`
6. A decision request for a tenant with an active split calls `evaluate_policy()` with the policy params from the routed version (verify via mock)

---

### Prompt G4-D: Auto-Rollback Scheduler and Promotion Workflow

**File to create:** `scripts/policy_split_manager.py`

**Context:** The `PolicyChallengerRouter.auto_rollback_if_regressed()` method from G4-B handles the revert logic, but it needs to be called on a schedule. This prompt creates the scheduler script and the promotion CLI command.

**Task:**

Create `scripts/policy_split_manager.py` with a CLI interface:

```
python scripts/policy_split_manager.py check-rollback \
    --tenant-id <id> \
    --lookback-days 7 \
    --max-approval-delta 0.05

python scripts/policy_split_manager.py promote-challenger \
    --tenant-id <id> \
    --promoted-by "alice@example.com" \
    --note "Q2 2026 policy refresh — passed merchant risk gate"

python scripts/policy_split_manager.py status \
    --tenant-id <id>
```

Implement three subcommands:

1. **`check-rollback`** — Instantiates a `PolicyChallengerRouter` for the given tenant (loading the active split from `PolicySplitStore`), calls `auto_rollback_if_regressed()`, and prints a JSON result:
   ```json
   { "tenant_id": "...", "rolled_back": true|false, "report": { ... } }
   ```

2. **`promote-challenger`** — Calls `promote_challenger(promoted_by, note, policy_version_store)` on the active split's router. Prints the new version ID on success. This command is designed to be the second step in a four-eyes approval workflow (the policy change was staged and reviewed; this command executes the promotion).

3. **`status`** — Prints the current active split and the latest `PolicyComparisonReport` as JSON. If no split is active, prints `{ "active_split": null }`.

Additionally, add a `check-rollback` invocation to `scripts/run_cc_pd_pipeline.py` at the `--stage monitor` step: after running `cc_pd_monitor.py`, if a `POLICY_SPLIT_DB_URL` env var is set, run `check-rollback` for each tenant returned by `_CONFIG_REGISTRY.list_tenants()`.

**Constraints:**
- The script must exit with code `0` if `rolled_back=False`, code `2` if `rolled_back=True` (allows CI/shell scripts to detect automatic rollbacks and send an alert)
- The script must read `POLICY_SPLIT_DB_URL` and `DATABASE_URL` from environment variables — no hardcoded DB paths
- `promote-challenger` must print a confirmation prompt `"Promote challenger [version_tag]? (yes/no): "` and abort if anything other than `"yes"` is typed (safety guard for CLI use)

**Acceptance test file:** `scripts/tests/test_policy_split_manager.py`

Write tests that (using mocked `PolicySplitStore` and `PolicyChallengerRouter`):
1. `check-rollback` with a `"REJECT"` recommendation exits with code `2` and prints `"rolled_back": true`
2. `check-rollback` with a `"HOLD"` recommendation exits with code `0` and prints `"rolled_back": false`
3. `promote-challenger` prompts for confirmation and aborts when `"no"` is entered
4. `status` with no active split prints `{ "active_split": null }` and exits with code `0`

---

## GAP-05: CRA / FCRA / UDAAP Reporting Suite

### Background

The PRD (§8.4, §4.7) requires four regulatory report types on configurable schedules. Currently only the HMDA LAR is implemented in `reporting/hmda_lar.py`. This gap closes three missing report modules:

1. **CRA Activity Report** — Community Reinvestment Act (12 U.S.C. §2901) — documents lending activity in low/moderate-income census tracts for covered institutions. Required format: tabular summary by assessment area, activity type, and income category.

2. **FCRA Metro 2 Tradeline Export** — Fair Credit Reporting Act (15 U.S.C. §1681 et seq.) — fixed-width file format used when reporting credit account information to the credit bureaus. Metro 2 is the CDIA standard format.

3. **UDAAP Monitoring Summary** — Consumer Financial Protection Act §1031 (Unfair, Deceptive, or Abusive Acts or Practices) — a structured report of complaint volume, complaint type distribution, and resolution metrics for supervisory examination.

The `monitoring/fair_lending.py` module computes AIR and chi-squared statistics but produces only an in-memory object — no report artifact is persisted or scheduled. A unified report dispatcher is also needed to schedule and persist all four report types.

---

### Prompt G5-A: CRA Activity Report Generator

**File to create:** `reporting/cra_activity.py`

**Context:** CRA reporting aggregates lending activity by assessment area (geography) and demographic income category (low/moderate/middle/upper, based on census tract median family income). The report is a tabular summary — not a per-loan record file like HMDA LAR.

**Task:**

Create `reporting/cra_activity.py` with the following:

1. Constants for CRA income categories (per OCC/FDIC/Fed CRA examination rules):
   ```python
   CRA_INCOME_LOW = "low"           # < 50% of area median family income (AMFI)
   CRA_INCOME_MODERATE = "moderate" # 50–79.99% of AMFI
   CRA_INCOME_MIDDLE = "middle"     # 80–119.99% of AMFI
   CRA_INCOME_UPPER = "upper"       # >= 120% of AMFI
   ```

2. A `CRALoanRecord` dataclass for a single input record:
   ```python
   @dataclass
   class CRALoanRecord:
       application_id: str
       census_tract: str        # 11-digit FIPS census tract code
       state_code: str
       county_code: str
       action_taken: int        # 1=originated, 2=approved not accepted, 3=denied, 6=purchased
       loan_amount: float
       applicant_income: Optional[int]  # gross annual income in thousands
       loan_purpose: int        # 1=home purchase, 2=home improvement, 3=refinance
       tract_median_family_income_pct: Optional[float]  # tract MFI as % of area MFI
   ```

3. A `CRAActivitySummary` dataclass for the output:
   ```python
   @dataclass
   class CRAActivitySummary:
       institution_name: str
       reporting_period_start: str   # ISO-8601 date
       reporting_period_end: str
       assessment_area_id: str       # state+county FIPS code (5 digits)
       income_category: str          # CRA_INCOME_* constant
       loan_purpose_label: str       # "home_purchase" / "home_improvement" / "refinance"
       originated_count: int
       originated_amount: float
       approved_not_accepted_count: int
       denied_count: int
       total_applications: int
       origination_rate: float       # originated_count / total_applications
   ```

4. A function `classify_income_category(tract_mfi_pct: Optional[float]) -> str` that maps a tract MFI percentage to a CRA income category string. Returns `"unknown"` when `tract_mfi_pct` is `None`.

5. A function `generate_cra_activity_report(records: List[CRALoanRecord], institution_name: str, period_start: str, period_end: str) -> List[CRAActivitySummary]` that:
   - Groups records by `(state_code + county_code, income_category, loan_purpose)`
   - Computes aggregate counts and amounts for each group
   - Returns a list of `CRAActivitySummary` objects (one per group)

6. A function `to_csv(summaries: List[CRAActivitySummary], output_path: Path) -> Path` that writes the summaries to a pipe-delimited CSV file and returns the path.

7. A function `from_audit_log_records(audit_records: List[Dict[str, Any]]) -> List[CRALoanRecord]` that constructs `CRALoanRecord` objects from the audit log dict structure returned by `get_audit_record()`. Map fields as follows:
   - `audit_record["application_id"]` → `application_id`
   - `audit_record.get("input_features", {}).get("census_tract")` → `census_tract`
   - `audit_record.get("decision_output")` mapped to HMDA `action_taken` codes (APPROVE→1, REJECT→3)
   - Use `HMDA_EXEMPT_NUMERIC = 1111` for fields not present in the audit record

**Constraints:**
- `generate_cra_activity_report()` must be a pure function (no I/O, no DB calls)
- `classify_income_category()` must handle `None` gracefully — do not raise on missing data
- The pipe-delimited output must include a header row with column names matching the `CRAActivitySummary` field names

**Acceptance test file:** `reporting/tests/test_cra_activity.py`

Write tests that:
1. `classify_income_category(45.0)` returns `"low"`, `classify_income_category(75.0)` returns `"moderate"`, etc.
2. A list of 10 records with `state_code="CA"`, `county_code="001"` and mixed income categories produces summaries grouped correctly
3. `origination_rate` equals `originated_count / total_applications` for each summary row
4. `to_csv()` produces a file whose first line is the header and whose row count equals `total_applications` counted across all summaries
5. `from_audit_log_records()` handles missing `census_tract` in `input_features` without raising

---

### Prompt G5-B: FCRA Metro 2 Tradeline Export

**File to create:** `reporting/fcra_metro2.py`

**Context:** Metro 2 is the CDIA (Consumer Data Industry Association) standard fixed-width file format for reporting credit account information to Equifax, Experian, and TransUnion. Each tradeline record is a 426-character fixed-width line (base segment). This module enables the platform to generate Metro 2 header, trailer, and base segment records from audit log data.

**Task:**

Create `reporting/fcra_metro2.py` with the following:

1. Constants for Metro 2 field positions (partial — implement only the fields required for a minimal valid base segment):
   ```python
   # Field lengths (characters) — Metro 2 Base Segment v1.0 subset
   SEGMENT_IDENTIFIER_LEN = 2         # "J1" or "J2" for base; "BS" for standard
   CUSTOMER_ACCOUNT_NUMBER_LEN = 30
   DATE_OF_ACCOUNT_INFORMATION_LEN = 8  # MMDDYYYY
   SCHEDULED_MONTHLY_PAYMENT_AMOUNT_LEN = 9
   ACCOUNT_RATING_CODE_LEN = 1        # 0=too new, 1=current, 2–5=delinquency days
   CREDIT_LIMIT_LEN = 9
   CURRENT_BALANCE_LEN = 9
   PORTFOLIO_TYPE_LEN = 1             # I=installment, O=open, R=revolving, M=mortgage
   CONSUMER_NAME_LEN = 30             # LAST_FIRST_MI
   ```

2. A `Metro2BaseSegment` dataclass with one field per Metro 2 base segment column. Include at minimum:
   - `customer_account_number: str`
   - `date_of_account_information: str`  (MMDDYYYY)
   - `account_rating_code: str`
   - `credit_limit: Optional[int]`        (in dollars)
   - `current_balance: Optional[int]`     (in dollars)
   - `portfolio_type: str`
   - `consumer_name: str`
   - `date_opened: str`                   (MMDDYYYY)
   - `account_status: str`                (11=open/current, 13=closed/paid, 61=paid/closed/was 30)
   - `compliance_condition_code: Optional[str]`  (XB for disputed accounts)

3. A function `format_base_segment(record: Metro2BaseSegment) -> str` that:
   - Right/left justifies each field to its fixed width
   - Returns a 426-character string
   - Fills numeric fields with zero-padding on the left, string fields with space-padding on the right
   - Raises `ValueError` if the final string is not exactly 426 characters

4. A `Metro2HeaderRecord` dataclass and `format_header(header: Metro2HeaderRecord) -> str` (produce a 426-character header segment in Metro 2 format).

5. A `Metro2TrailerRecord` dataclass and `format_trailer(trailer: Metro2TrailerRecord, total_base_segments: int, total_credit_amount: int) -> str`.

6. A function `build_metro2_file(base_segments: List[Metro2BaseSegment], reporter_name: str, reporter_address: str, reporting_period: str) -> str` that assembles the header + base segments + trailer as a newline-delimited string.

7. A function `from_audit_log_records(audit_records: List[Dict[str, Any]]) -> List[Metro2BaseSegment]` that maps audit log records to `Metro2BaseSegment` objects, using appropriate defaults for fields not in the audit log.

**Constraints:**
- Each fixed-width line must be exactly 426 characters — enforce this with `assert len(line) == 426` in `format_base_segment()`
- All date fields must be formatted as `MMDDYYYY` — use `datetime.strptime` / `strftime`
- Numeric amounts must be zero-padded (not space-padded)
- Do not include any real consumer PII in test fixtures — use anonymized test data

**Acceptance test file:** `reporting/tests/test_fcra_metro2.py`

Write tests that:
1. `format_base_segment()` returns a string of exactly 426 characters
2. `format_base_segment()` raises `ValueError` if a field value is longer than its allocated width
3. `build_metro2_file()` returns a string whose lines are: header, N base segments, trailer (N+2 lines)
4. Numeric fields in `format_base_segment()` are zero-padded to their declared width
5. `from_audit_log_records()` produces one `Metro2BaseSegment` per input audit record

---

### Prompt G5-C: UDAAP Monitoring Summary Generator

**File to create:** `reporting/udaap_summary.py`

**Context:** UDAAP (Unfair, Deceptive, or Abusive Acts or Practices) monitoring requires institutions to track consumer complaints, flag complaint patterns, and demonstrate timely resolution. The summary report is used in supervisory examinations to demonstrate the institution has an active UDAAP monitoring program. The `monitoring/fair_lending.py` module already computes AIR and chi-squared stats; this module adds a structured complaint-centric UDAAP summary alongside it.

**Task:**

Create `reporting/udaap_summary.py` with the following:

1. A `ComplaintRecord` dataclass representing a single consumer complaint:
   ```python
   @dataclass
   class ComplaintRecord:
       complaint_id: str
       received_date: str        # ISO-8601
       resolved_date: Optional[str]
       complaint_type: str       # e.g. "adverse_action_notice", "billing_error", "servicing"
       product: str              # e.g. "credit_card", "installment_loan"
       resolution: Optional[str] # "resolved", "pending", "escalated"
       resolution_days: Optional[int]
       is_cfpb_forwarded: bool   # complaint forwarded to CFPB complaint portal
   ```

2. A `UDAAPMonitoringSummary` dataclass:
   ```python
   @dataclass
   class UDAAPMonitoringSummary:
       reporting_period_start: str
       reporting_period_end: str
       tenant_id: str
       total_complaints: int
       complaints_by_type: Dict[str, int]       # type → count
       complaints_by_product: Dict[str, int]    # product → count
       median_resolution_days: Optional[float]
       pct_resolved_within_30_days: float
       pct_resolved_within_60_days: float
       cfpb_forwarded_count: int
       cfpb_forwarded_pct: float
       escalated_count: int
       top_complaint_type: Optional[str]        # most frequent type
       udaap_risk_flag: bool                    # True if CFPB-forwarded rate > 5% or resolution > 60 days
       risk_flag_reasons: List[str]
       fair_lending_air_score: Optional[float]  # pulled from FairLendingReport if available
       generated_at: str                        # ISO-8601 UTC
   ```

3. A function `generate_udaap_summary(complaints: List[ComplaintRecord], tenant_id: str, period_start: str, period_end: str, fair_lending_report: Optional["FairLendingReport"] = None) -> UDAAPMonitoringSummary` that:
   - Computes all fields in `UDAAPMonitoringSummary`
   - Sets `udaap_risk_flag=True` and populates `risk_flag_reasons` when:
     - CFPB-forwarded rate > 5%
     - Median resolution days > 60
     - A specific complaint type exceeds 30% of total complaints
   - Pulls `fair_lending_report.dir_score` into `fair_lending_air_score` if the report is provided

4. A function `to_json(summary: UDAAPMonitoringSummary, output_path: Path) -> Path` that serializes the summary to a formatted JSON file and returns the path.

5. A function `to_html(summary: UDAAPMonitoringSummary, output_path: Path) -> Path` that renders a minimal HTML report (no external CSS framework — inline styles only) with a summary table suitable for examiner review.

6. A function `from_adverse_action_store(adverse_action_records: List[Dict[str, Any]]) -> List[ComplaintRecord]` that constructs `ComplaintRecord` objects from `adverse_action_log` records, treating each undelivered adverse action notice as a prospective complaint source (not a confirmed complaint — set `complaint_type="adverse_action_notice"`, `resolution=None` if the notice was not delivered).

**Constraints:**
- `generate_udaap_summary()` must be a pure function (no I/O, no DB calls)
- `to_html()` must not require any third-party template engine — use stdlib `string.Template` or plain f-strings
- The UDAAP risk flag threshold values (5%, 60 days, 30%) must be module-level constants so they are easy to tune

**Acceptance test file:** `reporting/tests/test_udaap_summary.py`

Write tests that:
1. With 3 CFPB-forwarded complaints out of 20 total (15%), `udaap_risk_flag=True` and `"cfpb_forwarded_pct"` appears in `risk_flag_reasons`
2. With median resolution of 70 days, `udaap_risk_flag=True` and `"median_resolution_days"` appears in `risk_flag_reasons`
3. With all complaints resolved in less than 30 days and no CFPB-forwards, `udaap_risk_flag=False`
4. `pct_resolved_within_30_days` is computed correctly when some records have `resolution_days=None`
5. `to_json()` produces a file that is valid JSON (use `json.loads()` to verify)
6. `to_html()` produces a string containing `"<table"` and the `tenant_id` value

---

### Prompt G5-D: Unified Report Dispatcher and CLI

**File to create:** `reporting/dispatcher.py`
**File to modify:** `reporting/__init__.py`

**Context:** The four reporting modules (HMDA LAR, CRA Activity, FCRA Metro 2, UDAAP Summary) are now all implemented but run independently. Production compliance requires them to run on a configurable schedule — typically quarterly for CRA and FCRA, and monthly for UDAAP. This prompt creates a unified dispatcher used both by the scheduled monitor script and as a standalone CLI.

**Task:**

Create `reporting/dispatcher.py` with:

1. A `ReportSpec` dataclass:
   ```python
   @dataclass
   class ReportSpec:
       tenant_id: str
       report_type: Literal["hmda_lar", "cra_activity", "fcra_metro2", "udaap_summary"]
       period_start: str   # ISO-8601 date
       period_end: str     # ISO-8601 date
       output_dir: Path
       institution_name: str = "Unknown Institution"
       extra_params: Dict[str, Any] = field(default_factory=dict)
   ```

2. A `ReportResult` dataclass:
   ```python
   @dataclass
   class ReportResult:
       spec: ReportSpec
       status: Literal["success", "failure", "skipped"]
       output_path: Optional[Path]
       error: Optional[str]
       generated_at: str
       record_count: int
   ```

3. An async function `dispatch_report(spec: ReportSpec, db_url: str) -> ReportResult` that:
   - Fetches audit records for the tenant/period from `get_audit_record()` (multiple calls) or a bulk query function (add `async def get_audit_records_by_period(tenant_id, start, end, db_url) -> List[Dict]` to `audit/logger.py` — see constraint note)
   - Calls the appropriate module's generator function based on `spec.report_type`
   - Writes the output to `spec.output_dir / f"{spec.tenant_id}_{spec.report_type}_{spec.period_start}_{spec.period_end}.{ext}"`
   - Returns a `ReportResult` with `status="success"` and the output path
   - On exception, returns `ReportResult(status="failure", error=str(exc), ...)`

4. An async function `dispatch_all(specs: List[ReportSpec], db_url: str) -> List[ReportResult]` that runs all specs concurrently using `asyncio.gather()` and returns results in input order.

5. A CLI entry point:
   ```
   python -m reporting.dispatcher \
       --tenant-id <id> \
       --report-type hmda_lar|cra_activity|fcra_metro2|udaap_summary|all \
       --period-start 2026-01-01 \
       --period-end 2026-03-31 \
       --output-dir ./reports/q1_2026 \
       --institution-name "First National Bank"
   ```
   When `--report-type all` is passed, dispatch all four report types for the given tenant and period.

6. **Add to `audit/logger.py`**: An async bulk-fetch function:
   ```python
   async def get_audit_records_by_period(
       tenant_id: str,
       period_start: str,
       period_end: str,
       db_url: str,
   ) -> List[Dict[str, Any]]:
   ```
   That queries `audit_log` for all records in `[period_start, period_end]` for the given `tenant_id`, ordered by `logged_at ASC`. The function must enforce `tenant_id` in the `WHERE` clause.

**Constraints:**
- `dispatch_all()` must not raise even if individual `dispatch_report()` calls fail — failures are captured in `ReportResult.error`
- The CLI `--report-type all` must write one output file per report type (4 files total) — not a combined file
- `get_audit_records_by_period()` must validate `tenant_id` is non-empty (same pattern as `get_audit_record()`)
- Output filenames must be filesystem-safe — replace any `/` or spaces in `tenant_id` with `_`

**Acceptance test file:** `reporting/tests/test_dispatcher.py`

Write tests that:
1. `dispatch_report()` with `report_type="hmda_lar"` creates a file at the expected output path
2. When the underlying generator raises an exception, `dispatch_report()` returns `status="failure"` (does not re-raise)
3. `dispatch_all()` with 4 specs returns 4 `ReportResult` objects in the same order as the input specs
4. `dispatch_all()` still returns results for successful specs when one spec fails
5. `get_audit_records_by_period()` with an empty `tenant_id` raises `ValueError`
6. The CLI with `--report-type all` creates 4 separate output files

---

---

## Integration Checklist

After all prompts are completed, run the following end-to-end validation:

```bash
# From project root
cd /Users/swarnabale/Documents/My Projects/credit-risk-platform

# GAP-03 — Tenant isolation
python -m pytest orchestration/tests/test_pipeline_tenant_guard.py -v
python -m pytest decision-api/tests/test_tenant_isolation.py -v
python -m pytest audit/tests/test_tenant_guard.py -v
python -m pytest scripts/tests/test_provision_bq_tenant_policies.py -v

# GAP-04 — Policy champion/challenger
python -m pytest decision_engine/tests/test_policy_challenger.py -v
python -m pytest decision-api/tests/test_policy_split_endpoints.py -v
python -m pytest scripts/tests/test_policy_split_manager.py -v

# GAP-05 — Regulatory reporting
python -m pytest reporting/tests/test_cra_activity.py -v
python -m pytest reporting/tests/test_fcra_metro2.py -v
python -m pytest reporting/tests/test_udaap_summary.py -v
python -m pytest reporting/tests/test_dispatcher.py -v

# Regression — ensure nothing from P1/P2 is broken
python -m pytest audit/ decision-api/ compliance/ monitoring/ decisioning/ decision_engine/ reporting/ orchestration/ -v
```

---

## File Creation Summary

| Prompt | Action | File |
|--------|--------|------|
| G3-A | Modify | `orchestration/pipeline.py` — make `tenant_id` required + add to `PipelineRun` |
| G3-A | Create | `orchestration/tests/test_pipeline_tenant_guard.py` |
| G3-B | Modify | `decision-api/src/main.py` — add `_assert_tenant_owns_record()` + wire to audit endpoint |
| G3-B | Create | `decision-api/tests/test_tenant_isolation.py` |
| G3-C | Create | `audit/tenant_guard.py` |
| G3-C | Create | `audit/tests/test_tenant_guard.py` |
| G3-D | Create | `scripts/provision_bq_tenant_policies.py` |
| G3-D | Create | `scripts/tests/test_provision_bq_tenant_policies.py` |
| G4-A | Create | `decision_engine/policy_challenger.py` (data layer: dataclasses + `PolicySplitStore`) |
| G4-A | Create | `decision_engine/tests/test_policy_challenger.py` |
| G4-B | Modify | `decision_engine/policy_challenger.py` (add `PolicyChallengerRouter`) |
| G4-C | Modify | `decision-api/src/main.py` — instantiate policy split store + new admin endpoints |
| G4-C | Create | `decision-api/tests/test_policy_split_endpoints.py` |
| G4-D | Create | `scripts/policy_split_manager.py` |
| G4-D | Create | `scripts/tests/test_policy_split_manager.py` |
| G5-A | Create | `reporting/cra_activity.py` |
| G5-A | Create | `reporting/tests/test_cra_activity.py` |
| G5-B | Create | `reporting/fcra_metro2.py` |
| G5-B | Create | `reporting/tests/test_fcra_metro2.py` |
| G5-C | Create | `reporting/udaap_summary.py` |
| G5-C | Create | `reporting/tests/test_udaap_summary.py` |
| G5-D | Modify | `audit/logger.py` — add `get_audit_records_by_period()` |
| G5-D | Create | `reporting/dispatcher.py` |
| G5-D | Modify | `reporting/__init__.py` — export new report generators |
| G5-D | Create | `reporting/tests/test_dispatcher.py` |

**Total: 7 files modified, 18 files created**

---

## Dependencies to Add to `requirements.txt`

```
# GAP-03 — Tenant isolation (no new deps; uses stdlib contextvars)

# GAP-04 — Policy champion/challenger (no new deps; extends existing SQLAlchemy usage)

# GAP-05 — FCRA Metro 2 and UDAAP HTML report
# (no new deps; uses stdlib string.Template for HTML, stdlib fixed-width formatting)
# If CFPB complaint data is sourced from external API:
# httpx>=0.24.0   # already likely present for AI-agent module
```

---

## Sequencing Notes

- **G3-A must precede G3-C** (tenant guard module depends on the concept of tenant_id being required across all callers)
- **G4-A must precede G4-B** (store/dataclass layer must exist before router is added to same file)
- **G4-B must precede G4-C** (router must exist before API wiring)
- **G5-D depends on G5-A, G5-B, G5-C** (dispatcher calls all three generators) and also on the `audit/logger.py` bulk-fetch function added in G5-D — add `get_audit_records_by_period()` first before writing dispatcher tests
- **G3 and G4 are independent** of each other and of G5 — they can be worked in parallel by separate engineers
- **GAP-11** (four-eyes for policy API) is a dependency for `promote_challenger()` in G4-B to be fully compliant — G4 implements the technical routing; GAP-11 adds the approval gate. GAP-11 should be worked immediately after GAP-04.

---

*Document Control: Implementation plan for Priority 2 gaps GAP-03, GAP-04, GAP-05. Reviewed against PRD v1.0.0 §6.5, §4.3, §8.4. For Priority 1 and the adverse action gaps, see [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md).*
