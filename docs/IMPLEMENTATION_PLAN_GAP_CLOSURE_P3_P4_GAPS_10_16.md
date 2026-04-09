# Implementation Plan: Gap Closure — GAP-10 through GAP-16
**Document**: Integrated Lending Operating Layer (ILOL)
**Gaps Addressed**: GAP-10 (Explainability Endpoint · P3), GAP-11 (Policy Four-Eyes · P3), GAP-12 (Canary Deployment · P3), GAP-13 (Borrower Portal API · P4), GAP-14 (Batch Underwriting API · P4), GAP-15 (Stochastic Stress Testing · P4), GAP-16 (Webhook Delivery Framework · P4)
**Date**: 2026-04-07
**Estimated Total Effort**: ~20 engineering days
**Dependencies**: Python 3.11+, FastAPI, SQLAlchemy, `shap`, `openai>=1.0`, `numpy`, `scipy`, existing `explainability/`, `compliance/`, `config_registry/`, `monitoring/`, `decision-api/`, `audit/` modules

---

## Prerequisite Reading

Before starting, read the following files end-to-end:

- `explainability/shap_explainer.py` — `ExplanationResult` dataclass, `explain_prediction()` signature
- `explainability/nlg_summarizer.py` — `NLGSummary`, `generate_decision_summary()` (produced in GAP-06)
- `compliance/rbac.py` — `FOUR_EYES_RULES`, `enforce_four_eyes()`, `SeparationOfDutiesViolation`, `RBAC_MATRIX`
- `config_registry/service.py` — `ConfigRegistryService.publish()`, `get_active()`, `get_version()`, `rollback()`, `.as_dict()`
- `audit/logger.py` — `log_decision()`, `log_portfolio_action()`, `get_audit_record()`
- `decision-api/src/main.py` — all existing routes, `verify_bearer()`, `_assert_tenant_owns_record()`, `_run_pipeline()`, `LoanApplicationRequest`
- `monitoring/cc_pd_monitor.py` — `run_monitoring()`, threshold constants (added in G7-B)
- `monitoring/alert_router.py` — `AlertRouter`, `AlertRouter.send_alert()`, `DEFAULT_ALERT_ROUTER`
- `decision_engine/policy_version_store.py` — `PolicyVersionStore`, `publish()`, `rollback()`

---

## GAP-10 — Dedicated Explainability Endpoint

**Goal**: Expose `GET /v1/decisions/{id}/explanation` returning SHAP values, counterfactuals, and an NLG narrative in a single focused response.

**Effort**: ~1 day

---

### Prompt G10-A — Create `explainability/counterfactual.py`

```
Create a new file `explainability/counterfactual.py`.

This module generates the minimum feature perturbation required to flip a
REJECT decision to APPROVE (a "nearest counterfactual").  It avoids any
external dependency beyond numpy and pandas.

Requirements:

1. Define a Pydantic dataclass (or standard dataclass) `CounterfactualResult`:
   ```python
   @dataclass
   class CounterfactualResult:
       application_id: str
       original_decision: str            # "APPROVE" | "REJECT" | "MANUAL_REVIEW"
       counterfactual_decision: str      # decision under the proposed change
       feature_changes: list[dict]       # list of {feature, original_value, suggested_value, delta}
       feasibility_note: str             # plain-language description of changes required
       generated_at: str                 # ISO-8601 UTC
   ```

2. Define the main public function:
   ```python
   def generate_counterfactual(
       features_df: pd.DataFrame,           # single-row DataFrame with model features
       model: Any,                          # fitted scikit-learn / LightGBM model
       decision_threshold: float = 0.5,     # PD cutoff above which decision == REJECT
       max_features_to_change: int = 3,     # limit perturbations to the top-N features
       step_pct: float = 0.05,              # step size as % of feature range
       max_iterations: int = 200,           # guard against infinite loops
       application_id: str = "",
       original_decision: str = "REJECT",
   ) -> CounterfactualResult:
   ```

   Algorithm (greedy single-feature descent):
   a. Compute `base_prob = model.predict_proba(features_df)[0, 1]`.
   b. Use SHAP `TreeExplainer` (or fall back to model `feature_importances_` when
      SHAP is unavailable) to rank features by |SHAP value| descending.
   c. For each of the top `max_features_to_change` features (negative-direction only):
      - Determine the natural range of the feature from `features_df` column statistics
        if available, else use [0, feature_value * 2].
      - On each iteration, nudge the feature value by `step_pct * range` in the direction
        that reduces predicted probability.
      - Stop nudging this feature when `predict_proba` drops below `decision_threshold`.
   d. If the flip succeeds within `max_iterations`, set `counterfactual_decision = "APPROVE"`.
      Otherwise set it to the original decision and add a `feasibility_note` explaining
      that no feasible single-feature flip was found within the search budget.
   e. Build `feature_changes` only for features actually modified.
   f. Build `feasibility_note` as a plain-language sentence, e.g.:
      "Reducing debt_to_income_ratio from 0.52 to 0.38 and improving fico_score
       from 620 to 680 would be sufficient to obtain approval under current policy."

3. If `shap` is not installed, catch `ImportError` and fall back to using
   `model.feature_importances_` if available, or rank features alphabetically.
   Never raise — return a `CounterfactualResult` with `feature_changes=[]` and
   an explanatory `feasibility_note` if the model is not introspectable.

4. All numeric operations must be guarded for edge cases:
   - Single-feature DataFrames must not crash.
   - Models without `predict_proba` (regressors) must be handled gracefully —
     treat the raw prediction as the "probability".

5. Write unit tests in `tests/test_counterfactual.py`:
   - Train a tiny `LogisticRegression` on 50 rows of synthetic data.
   - Call `generate_counterfactual()` with a high-PD row and assert
     `counterfactual_decision == "APPROVE"` or `feature_changes != []`.
   - Call with SHAP not installed (mock `import shap` to raise `ImportError`) —
     assert no exception raised and `CounterfactualResult` is returned.
   - Call for an already-approved row (`base_prob < decision_threshold`) —
     assert `counterfactual_decision == "APPROVE"` and `feature_changes == []`.
```

---

### Prompt G10-B — Expose `GET /v1/decisions/{id}/explanation` in the Decision API

```
In `decision-api/src/main.py`, add a new read-only endpoint after the
existing `GET /v1/decisions/{application_id}/audit` route:

```python
@app.get(
    "/v1/decisions/{application_id}/explanation",
    summary="Full explainability record: SHAP + counterfactual + NLG narrative",
    tags=["Decisions"],
)
async def get_decision_explanation(
    application_id: str,
    _user: Dict = Depends(verify_bearer),
) -> JSONResponse:
    """Return a structured explanation for a previously made decision.

    Response schema
    ---------------
    {
      "application_id": "...",
      "tenant_id":       "...",
      "decision":        "REJECT",
      "shap": {
        "base_value":           0.12,
        "predicted_value":      0.67,
        "top_positive_factors": [...],
        "top_negative_factors": [...],
        "explanation_text":     "..."
      },
      "counterfactual": {
        "original_decision":       "REJECT",
        "counterfactual_decision": "APPROVE",
        "feature_changes":         [...],
        "feasibility_note":        "..."
      },
      "narrative": {
        "loan_officer_narrative": "...",
        "applicant_narrative":    "...",
        "adverse_action_body":    "...",
        "top_reasons":            [...]
      },
      "generated_at": "2026-04-07T..."
    }

    Implementation notes
    --------------------
    1. Call `get_audit_record(application_id, db_url=DB_URL, tenant_id=tenant_id)`.
       Use `_assert_tenant_owns_record()` to enforce tenant isolation.
    2. Extract `top_shap_factors` from the audit record's JSON field (stored
       by `log_decision()` as `top_shap_factors`).  If absent, fall back to
       an empty dict for the `shap` block with a `"warning"` key.
    3. Re-run `generate_counterfactual()` from `explainability.counterfactual`
       using `_risk_model` and a reconstructed feature DataFrame built from
       `input_features_json` stored in the audit record.
       - If `input_features_json` is not stored, return `"counterfactual": null`
         with a `"warning"` key rather than raising.
    4. Re-run `generate_decision_summary()` from `explainability.nlg_summarizer`
       using the stored SHAP factors.
       - If the NLG summarizer or openai is unavailable, return the template
         fallback (the module handles this internally — never raise here).
    5. All three blocks (shap, counterfactual, narrative) must degrade gracefully:
       if any one block fails, include it as `null` with a `"warning"` field
       rather than returning a 500.
    6. Return HTTP 404 when `application_id` is not found.
    7. Return HTTP 403 when the audit record's `tenant_id` does not match JWT.
    """
```

Add an integration test `tests/test_explanation_endpoint.py`:
- POST to `POST /v1/decisions` to create a real decision, capture `application_id`.
- GET `GET /v1/decisions/{application_id}/explanation`.
- Assert HTTP 200, response contains keys `shap`, `counterfactual`, `narrative`.
- Assert 404 for an unknown `application_id`.
- Assert 403 when the JWT's `tenant_id` does not match the record.
- Assert no 500 when SHAP or counterfactual generation fails (mock
  `explainability.counterfactual.generate_counterfactual` to raise `RuntimeError`).
```

---

## GAP-11 — Policy API Four-Eyes Enforcement

**Goal**: Gate all policy config changes through a staging + approval workflow using `compliance/rbac.py`'s four-eyes enforcement before any config takes effect in production.

**Effort**: ~2 days

---

### Prompt G11-A — Add Staging State to `ConfigRegistryService`

```
Modify `config_registry/service.py` to add a "staged" (pending-approval) state
for config changes.

1. Add a new column `status` to the config versions table DDL:
   ```sql
   status  TEXT NOT NULL DEFAULT 'active'
   -- Valid values: 'staged' | 'active' | 'superseded' | 'rejected'
   ```
   Add a migration path identical to the pattern from `audit/logger.py`'s
   `migrate_audit_schema()` — an idempotent `ALTER TABLE ... ADD COLUMN`
   function called `migrate_config_schema(db_url: str) -> None`.

2. Add two new methods to `ConfigRegistryService`:

   ```python
   def stage_config(
       self,
       tenant_id: str,
       config_json: dict,
       authored_by: str,
       note: str,
   ) -> ConfigVersion:
       """Insert a new config row with status='staged'.  Does NOT activate it.
       Returns the staged ConfigVersion (including its generated version_tag).
       Raises ValueError if a staged version already exists for this tenant.
       """

   def approve_staged_config(
       self,
       tenant_id: str,
       staged_version_tag: str,
       approver_email: str,
       actor_email: str,
   ) -> ConfigVersion:
       """Promote a staged version to active.

       Steps:
       1. Load the staged ConfigVersion; raise ValueError if not found or status != 'staged'.
       2. Call `compliance.rbac.enforce_four_eyes(
              action='policy_stage_6_committee_approval',
              actor_email=actor_email,
              approver_email=approver_email,
          )` — this raises SeparationOfDutiesViolation if actor == approver.
       3. Mark all existing 'active' versions for this tenant as 'superseded'.
       4. Set staged row's status = 'active', effective_from = utcnow().isoformat().
       5. Write an audit event row to config_audit_events with event_type='APPROVED'.
       6. Return the now-active ConfigVersion.
       """

   def reject_staged_config(
       self,
       tenant_id: str,
       staged_version_tag: str,
       rejected_by: str,
       reason: str,
   ) -> None:
       """Set a staged version's status = 'rejected'.
       Does not raise if version is not found — logs a warning instead.
       Writes an audit event with event_type='REJECTED'.
       """
   ```

3. Ensure `get_active()` only returns rows where `status = 'active'`.  Add
   `get_staged()` which returns the pending staged version or `None`.

4. Ensure the existing `publish()` method is NOT removed — it remains as a
   `stage_config() → approve_staged_config()` shortcut for backward-compatible
   callers that pass a trusted `approved_by` param.  Document this clearly.

5. Write unit tests in `tests/test_config_staging.py`:
   - Stage a config, assert `get_staged()` returns it and `get_active()` returns old.
   - Approve it with a different `approver_email` — assert `get_active()` is updated.
   - Attempt approval with `actor_email == approver_email` — assert
     `SeparationOfDutiesViolation` is raised and old config is still active.
   - Reject a staged config — assert `get_active()` is unchanged.
   - Calling `stage_config()` when a staged version already exists — assert ValueError.
```

---

### Prompt G11-B — Wire Four-Eyes Gates into the Decision API Config Endpoints

```
In `decision-api/src/main.py`, make the following changes to implement the
four-eyes enforcement workflow for policy config changes.

1. Add two new Pydantic request models:

   ```python
   class StageConfigRequest(BaseModel):
       config_json: Dict[str, Any] = Field(
           ..., description="Policy config dict to stage for approval"
       )
       note: str = Field(..., min_length=1, description="Mandatory change rationale")

   class ApproveConfigRequest(BaseModel):
       staged_version_tag: str = Field(
           ..., description="Version tag of the staged config to approve"
       )
       actor_email: str = Field(
           ..., description="Email of the approver (must differ from the author's email)"
       )
       note: str = Field(default="", description="Optional approval note")
   ```

2. Add `POST /v1/config/stage` endpoint:
   ```python
   @app.post("/v1/config/stage", status_code=202, tags=["Config Registry"])
   async def stage_tenant_config(
       body: StageConfigRequest,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Submit a policy config change for four-eyes approval.
       Returns the staged version object with status='staged'.
       The config is NOT live until approved via POST /v1/config/approve.
       """
   ```
   Calls `_CONFIG_REGISTRY.stage_config(tenant_id, body.config_json, authored_by=_user["email"], note=body.note)`.

3. Add `POST /v1/config/approve` endpoint:
   ```python
   @app.post("/v1/config/approve", status_code=200, tags=["Config Registry"])
   async def approve_staged_config(
       body: ApproveConfigRequest,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Approve a staged policy config change and activate it immediately.

       Four-eyes check: the approver (body.actor_email from JWT) must be a
       different individual than the author who called POST /v1/config/stage.
       Enforced via compliance.rbac.enforce_four_eyes().

       Required JWT claim: role must be 'cro' or 'compliance_officer'.
       """
   ```
   - Validate `_user.get("role") in {"cro", "compliance_officer"}` — raise HTTP 403 otherwise.
   - Call `_CONFIG_REGISTRY.approve_staged_config(...)`.
   - Catch `SeparationOfDutiesViolation` → raise HTTPException(status_code=409,
     detail="Four-eyes violation: approver cannot be the same individual as the author.").
   - On success, return the active ConfigVersion dict.

4. Add `POST /v1/config/reject` endpoint:
   ```python
   @app.post("/v1/config/reject", status_code=200, tags=["Config Registry"])
   async def reject_staged_config(
       body: dict,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Reject a staged config change. Requires staged_version_tag and reason in body.
       Permitted roles: 'cro', 'compliance_officer', 'ml_validator'.
       """
   ```

5. Modify the existing `POST /v1/config` endpoint:
   - Add a warning in the docstring: "Deprecated — prefer POST /v1/config/stage +
     POST /v1/config/approve for production environments. This endpoint bypasses the
     four-eyes gate and is retained for development convenience only."
   - Add a header check: if `X-Allow-Bypass-Four-Eyes: true` is NOT present in the
     request, return HTTP 428 (Precondition Required) with body:
     `{"error": "Direct config publish requires X-Allow-Bypass-Four-Eyes: true header.
       Use POST /v1/config/stage + POST /v1/config/approve in production."}`
   - This makes the bypass explicit and auditable without removing backward compat.

6. Write integration tests `tests/test_policy_four_eyes.py`:
   - Stage a config with user A's JWT, approve with user B's JWT (different email) — assert 200.
   - Stage a config with user A, attempt to approve with user A's email in body — assert 409.
   - Attempt approval with wrong role JWT — assert 403.
   - Reject a staged config — assert 200 and old active config unchanged.
   - POST to `/v1/config` without bypass header — assert 428.
   - POST to `/v1/config` WITH bypass header — assert 201 (original behavior).
```

---

## GAP-12 — Canary Deployment for Decision Service

**Goal**: Enable safe canary releases of the decision service API with automated rollback triggered by error rate or p99 latency thresholds.

**Effort**: ~3 days

---

### Prompt G12-A — Add Service-Level Metrics Endpoint and In-Process Prometheus Counters

```
In `decision-api/src/main.py`, add lightweight in-process metrics collection
without introducing a full Prometheus push gateway dependency (optional integration).

1. At module level, add a `_ServiceMetrics` dataclass:
   ```python
   from dataclasses import dataclass, field
   from collections import deque
   import threading

   @dataclass
   class _ServiceMetrics:
       """Rolling window counters for canary health checks."""
       _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
       # Rolling 60-second latency window (deque of (timestamp_float, latency_ms) pairs)
       _latency_window: deque = field(default_factory=lambda: deque(maxlen=10_000), init=False)
       request_count: int = 0
       error_count_5xx: int = 0
       error_count_4xx: int = 0

       def record(self, latency_ms: int, status_code: int) -> None:
           import time
           with self._lock:
               self._latency_window.append((time.monotonic(), latency_ms))
               self.request_count += 1
               if status_code >= 500:
                   self.error_count_5xx += 1
               elif status_code >= 400:
                   self.error_count_4xx += 1

       def p99_latency_ms(self, window_seconds: float = 60.0) -> float | None:
           import time, numpy as np
           now = time.monotonic()
           with self._lock:
               recent = [ms for ts, ms in self._latency_window
                         if now - ts <= window_seconds]
           if not recent:
               return None
           return float(np.percentile(recent, 99))

       def error_rate(self, window_requests: int = 100) -> float:
           with self._lock:
               total = max(self.request_count, 1)
               return self.error_count_5xx / total

   _METRICS = _ServiceMetrics()
   ```

2. Add a FastAPI middleware that records every request into `_METRICS`:
   ```python
   @app.middleware("http")
   async def _metrics_middleware(request, call_next):
       import time
       start = time.perf_counter()
       response = await call_next(request)
       latency_ms = int((time.perf_counter() - start) * 1000)
       _METRICS.record(latency_ms=latency_ms, status_code=response.status_code)
       return response
   ```
   Place this middleware AFTER the existing CORS / rate-limit middleware registrations.

3. Add a `GET /v1/metrics` endpoint (internal — protected by JWT):
   ```python
   @app.get("/v1/metrics", summary="Service health metrics for canary evaluation", tags=["Ops"])
   async def get_metrics(_user: Dict = Depends(verify_bearer)) -> Dict[str, Any]:
       """Return rolling p99 latency, error rate, and request counters.

       This endpoint is consumed by the canary controller script to decide
       whether to continue ramping traffic or trigger an automatic rollback.

       Response schema
       ---------------
       {
         "p99_latency_ms":   142.3,    # last-60s rolling p99; null if no traffic yet
         "error_rate_5xx":   0.003,    # fraction of all requests returning 5xx
         "total_requests":   12453,
         "error_count_5xx":  37,
         "thresholds": {
           "p99_latency_ms_max": 500,  # from env CANARY_P99_THRESHOLD_MS (default 500)
           "error_rate_5xx_max": 0.01  # from env CANARY_ERROR_RATE_THRESHOLD (default 0.01)
         },
         "canary_healthy":   true      # computed: both thresholds within limits
       }
       """
       p99 = _METRICS.p99_latency_ms()
       err_rate = _METRICS.error_rate()
       p99_limit = float(os.getenv("CANARY_P99_THRESHOLD_MS", "500"))
       err_limit = float(os.getenv("CANARY_ERROR_RATE_THRESHOLD", "0.01"))
       healthy = (p99 is None or p99 <= p99_limit) and err_rate <= err_limit
       return {
           "p99_latency_ms":   p99,
           "error_rate_5xx":   round(err_rate, 5),
           "total_requests":   _METRICS.request_count,
           "error_count_5xx":  _METRICS.error_count_5xx,
           "thresholds": {"p99_latency_ms_max": p99_limit, "error_rate_5xx_max": err_limit},
           "canary_healthy":   healthy,
       }
   ```

4. Write unit tests `tests/test_service_metrics.py`:
   - Record 100 synthetic latency + status entries, assert `p99_latency_ms()` is within ±5%.
   - Record 10/100 5xx responses, assert `error_rate() ≈ 0.10`.
   - Call `GET /v1/metrics` via TestClient — assert `canary_healthy` key present.
   - Assert `canary_healthy == False` when injected p99 > threshold.
```

---

### Prompt G12-B — Create Canary Controller Script and Cloud Run Traffic Split Config

```
Create two new files: `scripts/canary_decision_api.py` and
`deploy/cloud_run_traffic.yaml`.

--- File 1: `scripts/canary_decision_api.py` ---

This script drives a progressive canary rollout for the decision service.
It polls `GET /v1/metrics` on both the canary (new) and stable (old) service
revisions and automatically triggers rollback when health degrades.

```python
#!/usr/bin/env python3
"""
Canary Controller — Decision API Service
========================================
Drives a progressive traffic ramp:
  0% → 5% → 10% → 25% → 50% → 100%

Rolls back automatically when:
  - Canary error_rate_5xx > CANARY_ERROR_RATE_THRESHOLD
  - Canary p99_latency_ms > CANARY_P99_THRESHOLD_MS
  - Stable revision health degrades (defensive check)

Usage
-----
    python scripts/canary_decision_api.py \\
        --service decision-api \\
        --region us-central1 \\
        --project my-gcp-project \\
        --canary-revision decision-api-00042-xyz \\
        --stable-revision decision-api-00041-abc \\
        --metrics-url-canary https://canary-decision-api.run.app/v1/metrics \\
        --metrics-url-stable https://decision-api.run.app/v1/metrics \\
        --auth-token $METRICS_AUTH_TOKEN

Environment variables (all overridden by CLI flags)
----------------------------------------------------
CANARY_SERVICE              Cloud Run service name
CANARY_REGION               GCP region
CANARY_PROJECT              GCP project ID
CANARY_REVISION             New revision tag being ramped
STABLE_REVISION             Current stable revision tag
CANARY_METRICS_URL          URL of /v1/metrics on canary
STABLE_METRICS_URL          URL of /v1/metrics on stable
CANARY_P99_THRESHOLD_MS     Max acceptable p99 latency (default: 500)
CANARY_ERROR_RATE_THRESHOLD Max acceptable 5xx rate (default: 0.01)
CANARY_POLL_INTERVAL_SEC    Seconds between polls (default: 30)
CANARY_RAMP_STEPS           Comma-separated % steps (default: 5,10,25,50,100)
CANARY_RAMP_STEP_WAIT_SEC   Seconds to hold at each step before ramping (default: 300)
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Optional


RAMP_STEPS_DEFAULT = [5, 10, 25, 50, 100]


def fetch_metrics(url: str, auth_token: str) -> Optional[dict]:
    """GET /v1/metrics from *url*.  Returns parsed JSON or None on error."""
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {auth_token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"[WARN] metrics fetch failed from {url}: {exc}", file=sys.stderr)
        return None


def set_cloud_run_traffic(
    project: str, region: str, service: str,
    canary_rev: str, stable_rev: str, canary_pct: int,
) -> bool:
    """Invoke `gcloud run services update-traffic` to set traffic split.
    Returns True on success, False on error.
    """
    stable_pct = 100 - canary_pct
    cmd = [
        "gcloud", "run", "services", "update-traffic", service,
        f"--to-revisions={canary_rev}={canary_pct},{stable_rev}={stable_pct}",
        f"--region={region}", f"--project={project}", "--quiet"
    ]
    print(f"[TRAFFIC] {canary_rev}={canary_pct}%  {stable_rev}={stable_pct}%")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] gcloud failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def rollback(project: str, region: str, service: str, stable_rev: str) -> None:
    """Route 100% traffic to stable revision."""
    print("[ROLLBACK] Routing all traffic to stable revision.", file=sys.stderr)
    cmd = [
        "gcloud", "run", "services", "update-traffic", service,
        f"--to-revisions={stable_rev}=100",
        f"--region={region}", f"--project={project}", "--quiet"
    ]
    subprocess.run(cmd)


def run_canary(args: argparse.Namespace) -> int:
    p99_limit  = float(os.getenv("CANARY_P99_THRESHOLD_MS",     str(args.p99_threshold)))
    err_limit  = float(os.getenv("CANARY_ERROR_RATE_THRESHOLD",  str(args.error_threshold)))
    poll_sec   = int(os.getenv("CANARY_POLL_INTERVAL_SEC",       str(args.poll_interval)))
    hold_sec   = int(os.getenv("CANARY_RAMP_STEP_WAIT_SEC",      str(args.step_wait)))
    steps_raw  = os.getenv("CANARY_RAMP_STEPS", "")
    steps      = [int(x) for x in steps_raw.split(",") if x.strip()] or RAMP_STEPS_DEFAULT

    for pct in steps:
        print(f"\n[RAMP] Setting canary traffic to {pct}%...")
        if not set_cloud_run_traffic(
            args.project, args.region, args.service,
            args.canary_revision, args.stable_revision, pct,
        ):
            rollback(args.project, args.region, args.service, args.stable_revision)
            return 1

        deadline = time.monotonic() + hold_sec
        while time.monotonic() < deadline:
            time.sleep(poll_sec)
            m = fetch_metrics(args.metrics_url_canary, args.auth_token)
            if m is None:
                print("[WARN] Canary metrics unavailable — holding position.", file=sys.stderr)
                continue
            p99    = m.get("p99_latency_ms") or 0.0
            err    = m.get("error_rate_5xx") or 0.0
            print(f"[HEALTH] p99={p99:.0f}ms  error_rate={err:.4f}")
            if p99 > p99_limit or err > err_limit:
                print(f"[ALERT] Threshold breach: p99={p99}>{p99_limit} or err={err}>{err_limit}",
                      file=sys.stderr)
                rollback(args.project, args.region, args.service, args.stable_revision)
                return 2   # exit code 2 = rollback triggered

    print("[DONE] Canary promotion complete — 100% traffic on new revision.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Canary controller for decision-api on Cloud Run")
    ap.add_argument("--service",         default=os.getenv("CANARY_SERVICE", "decision-api"))
    ap.add_argument("--region",          default=os.getenv("CANARY_REGION", "us-central1"))
    ap.add_argument("--project",         default=os.getenv("CANARY_PROJECT", ""))
    ap.add_argument("--canary-revision", default=os.getenv("CANARY_REVISION", ""))
    ap.add_argument("--stable-revision", default=os.getenv("STABLE_REVISION", ""))
    ap.add_argument("--metrics-url-canary", default=os.getenv("CANARY_METRICS_URL", ""))
    ap.add_argument("--metrics-url-stable", default=os.getenv("STABLE_METRICS_URL", ""))
    ap.add_argument("--auth-token",      default=os.getenv("METRICS_AUTH_TOKEN", ""))
    ap.add_argument("--p99-threshold",   type=float, default=500.0)
    ap.add_argument("--error-threshold", type=float, default=0.01)
    ap.add_argument("--poll-interval",   type=int,   default=30)
    ap.add_argument("--step-wait",       type=int,   default=300)
    args = ap.parse_args()

    missing = [f for f in ("project", "canary_revision", "stable_revision",
                            "metrics_url_canary", "auth_token")
               if not getattr(args, f.replace("-", "_"), "")]
    if missing:
        ap.error(f"Missing required arguments: {missing}")

    sys.exit(run_canary(args))


if __name__ == "__main__":
    main()
```

--- File 2: `deploy/cloud_run_traffic.yaml` ---

Create `deploy/cloud_run_traffic.yaml` as a reusable manifest template for
manual Cloud Run traffic splits (complement to the automated script above):

```yaml
# Cloud Run Traffic Split Manifest
# Usage: gcloud run services replace deploy/cloud_run_traffic.yaml
# Substitute {{CANARY_REVISION}}, {{STABLE_REVISION}}, {{CANARY_PCT}} before applying.
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: decision-api
  annotations:
    run.googleapis.com/ingress: all
spec:
  traffic:
    - revisionName: "{{STABLE_REVISION}}"
      percent: "{{STABLE_PCT}}"
    - revisionName: "{{CANARY_REVISION}}"
      percent: "{{CANARY_PCT}}"
      tag: canary
```

Also create `deploy/nginx_canary.conf.template` for teams using NGINX instead
of Cloud Run:

```nginx
# NGINX upstream weighting for decision-api canary
# Set CANARY_WEIGHT (0–100) and redeploy to ramp traffic.
upstream decision_api {
    server decision-api-stable:8080 weight={{STABLE_WEIGHT}};
    server decision-api-canary:8080 weight={{CANARY_WEIGHT}};
    keepalive 32;
}

server {
    listen 80;
    location /v1/ {
        proxy_pass         http://decision_api;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }

    # Dedicated path for health probes — always hits stable
    location /v1/health {
        proxy_pass http://decision-api-stable:8080/v1/health;
    }
}
```

Write unit tests `tests/test_canary_script.py`:
- Mock `fetch_metrics()` to return healthy metrics — assert `run_canary()` returns 0.
- Mock `fetch_metrics()` to return p99 > threshold on second poll — assert returns 2
  (rollback triggered) and `rollback()` was called.
- Mock `set_cloud_run_traffic()` to return False — assert returns 1 immediately.
```

---

## GAP-13 — Borrower-Facing Portal API

**Goal**: Expose a public-facing API for borrowers to check application status, view a plain-language decision explanation, and submit applications — authenticated via a separate borrower JWT scheme.

**Effort**: ~4 days

---

### Prompt G13-A — Borrower Auth Module

```
Create a new file `decision-api/src/borrower_auth.py`.

This module manages borrower-scoped JWTs that are distinct from the
`tenant_id`-scoped internal JWTs used by `verify_bearer()` in `main.py`.

Requirements:

1. Define a `BorrowerTokenPayload` dataclass:
   ```python
   @dataclass
   class BorrowerTokenPayload:
       borrower_id: str          # UUID; opaque per-borrower identifier
       tenant_id: str            # which lender's portal issued this token
       application_ids: list[str]  # list of application IDs this borrower may access
       issued_at: str            # ISO-8601 UTC
       expires_at: str           # ISO-8601 UTC
   ```

2. Implement `issue_borrower_token(borrower_id, tenant_id, application_ids, ttl_hours) -> str`
   using `PyJWT` (HS256) with a separate secret from `BORROWER_JWT_SECRET` env var
   (default fallback raises RuntimeError if unset, same pattern as JWT_SECRET in main.py).
   The JWT must include claim `"token_type": "borrower"`.

3. Implement `verify_borrower_token(token: str) -> BorrowerTokenPayload`
   - Decodes and validates the JWT.
   - Raises `HTTPException(401)` if invalid / expired.
   - Raises `HTTPException(403)` if `token_type != "borrower"` (prevents tenant JWTs
     from being used as borrower tokens).

4. Implement a FastAPI dependency `get_borrower` (equivalent of `verify_bearer`):
   ```python
   async def get_borrower(
       credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
   ) -> BorrowerTokenPayload:
   ```

5. Write unit tests `tests/test_borrower_auth.py`:
   - Issue a token, decode it, assert fields match.
   - Pass an expired token — assert HTTP 401.
   - Pass a tenant JWT (no `token_type: borrower` claim) — assert HTTP 403.
   - Verify token grants access only to `application_ids` in payload.
```

---

### Prompt G13-B — Borrower Portal Endpoints

```
In `decision-api/src/main.py`, add a borrower-facing portal section using
`get_borrower` from `borrower_auth` (created in G13-A).

All portal endpoints are prefixed `/v1/portal/` and use a separate router tag
"Borrower Portal".

1. `POST /v1/portal/token`
   ```python
   class BorrowerTokenRequest(BaseModel):
       borrower_id: str
       application_ids: list[str]
       ttl_hours: int = Field(default=72, ge=1, le=720)

   @app.post("/v1/portal/token", tags=["Borrower Portal"])
   async def issue_portal_token(
       body: BorrowerTokenRequest,
       _user: Dict = Depends(verify_bearer),   # lender/tenant auth required to issue
   ) -> Dict[str, str]:
       """Issued by the lender's backend to give a specific borrower a scoped token.
       The returned token grants the borrower access ONLY to `application_ids`.
       """
   ```

2. `GET /v1/portal/applications/{application_id}/status`
   ```python
   @app.get("/v1/portal/applications/{application_id}/status", tags=["Borrower Portal"])
   async def get_portal_application_status(
       application_id: str,
       borrower: BorrowerTokenPayload = Depends(get_borrower),
   ) -> Dict[str, Any]:
       """Return the decision status for the application.
       Enforces: application_id must be in borrower.application_ids.
       Returns: {application_id, decision, decision_date, notice_id, status_label}.
       Does not expose raw PD score, fraud probability, or SHAP values.
       """
   ```
   - Fetch the audit record via `get_audit_record()`.
   - Guard: raise HTTP 403 if `application_id not in borrower.application_ids`.
   - Guard: raise HTTP 403 if `audit_record["tenant_id"] != borrower.tenant_id`.
   - Return a filtered dict — no model internals exposed to borrower.

3. `GET /v1/portal/applications/{application_id}/explanation`
   ```python
   @app.get(
       "/v1/portal/applications/{application_id}/explanation",
       tags=["Borrower Portal"],
   )
   async def get_portal_explanation(
       application_id: str,
       borrower: BorrowerTokenPayload = Depends(get_borrower),
   ) -> Dict[str, Any]:
       """Return ONLY the applicant_narrative and top_reasons (no SHAP, no PD score).
       Uses NLG summary stored in audit log or regenerates with template fallback.
       """
   ```
   - Returns: `{application_id, decision, applicant_narrative, top_reasons, adverse_action_body}`.
   - Must NOT include: `pd_score`, `fraud_probability`, SHAP values, internal model details.

4. Write integration tests `tests/test_portal_api.py`:
   - Issue a borrower token for application_id "A1", attempt GET status for "A2" — assert 403.
   - Use a tenant JWT directly against `/v1/portal/` endpoint — assert 403.
   - Assert `pd_score` and `fraud_probability` are NOT in the status or explanation response.
   - GET status for a valid application — assert 200 and `decision` key present.
```

---

## GAP-14 — Batch Underwriting API (CSV Upload + Job Polling)

**Goal**: Accept a CSV batch upload of applications, process asynchronously, and expose job-status polling and results download endpoints.

**Effort**: ~2 days

---

### Prompt G14-A — Create `BatchJobStore`

```
Create a new file `decision-api/src/batch_job_store.py`.

This module manages the lifecycle of batch underwriting jobs using a
SQLite-backed store.

```python
"""
Batch Job Store
===============
Tracks the state of CSV batch underwriting jobs submitted via
POST /v1/batch/underwrite.

Job lifecycle
-------------
  PENDING  → RUNNING  → COMPLETE
                       → FAILED
                       → CANCELLED (future)

Schema: batch_jobs table
  job_id          TEXT PRIMARY KEY    -- UUID
  tenant_id       TEXT NOT NULL
  status          TEXT NOT NULL       -- PENDING | RUNNING | COMPLETE | FAILED
  submitted_at    TEXT NOT NULL       -- ISO-8601 UTC
  started_at      TEXT                -- ISO-8601 UTC; NULL until processing begins
  completed_at    TEXT                -- ISO-8601 UTC; NULL until done
  total_rows      INTEGER NOT NULL DEFAULT 0
  processed_rows  INTEGER NOT NULL DEFAULT 0
  approved_count  INTEGER NOT NULL DEFAULT 0
  rejected_count  INTEGER NOT NULL DEFAULT 0
  review_count    INTEGER NOT NULL DEFAULT 0
  error_message   TEXT                -- populated for FAILED jobs
  results_path    TEXT                -- path to JSONL results file when COMPLETE
"""
```

Implement the following methods:

```python
class BatchJobStore:
    def create_job(self, job_id: str, tenant_id: str, total_rows: int) -> dict: ...
    def mark_running(self, job_id: str) -> None: ...
    def update_progress(self, job_id: str, processed: int, approved: int,
                        rejected: int, review: int) -> None: ...
    def mark_complete(self, job_id: str, results_path: str) -> None: ...
    def mark_failed(self, job_id: str, error_message: str) -> None: ...
    def get_job(self, job_id: str) -> dict | None: ...
    def list_jobs(self, tenant_id: str, limit: int = 20) -> list[dict]: ...
```

Write unit tests `tests/test_batch_job_store.py`:
- Create a job, assert status == "PENDING".
- Mark running, update progress, mark complete — assert status sequence.
- Create two jobs for different tenants, assert `list_jobs()` only returns own tenant's jobs.
```

---

### Prompt G14-B — Add Batch Upload and Polling Endpoints

```
In `decision-api/src/main.py`, add the batch underwriting CSV endpoints.

Import `BatchJobStore` from `batch_job_store` (created in G14-A).
Add a module-level singleton: `_BATCH_JOB_STORE = BatchJobStore()`.

1. `POST /v1/batch/underwrite` (CSV upload):
   ```python
   from fastapi import UploadFile, File, BackgroundTasks

   @app.post("/v1/batch/underwrite", status_code=202, tags=["Batch"])
   async def submit_batch_job(
       background_tasks: BackgroundTasks,
       file: UploadFile = File(..., description="CSV file of loan applications"),
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Accept a CSV file of applications and process asynchronously.

       CSV columns required (same as LoanApplicationRequest fields):
         application_id, customer_id, credit_score, annual_income,
         employment_status, employer_tenure_months, debt_to_income_ratio,
         existing_debt_amount, loan_amount, loan_purpose, loan_term_months,
         num_open_accounts, num_derogatory_marks, months_since_last_delinquency,
         borrower_state

       Returns
       -------
       {
         "job_id":        "uuid...",
         "status":        "PENDING",
         "submitted_at":  "2026-04-07T...",
         "total_rows":    500,
         "poll_url":      "/v1/batch/{job_id}/status"
       }
       """
   ```
   Implementation:
   a. Read and parse the CSV into `pd.DataFrame` (validate columns present,
      raise HTTP 422 if mandatory columns missing).
   b. Cap batch size at 10,000 rows; raise HTTP 413 if exceeded.
   c. Generate `job_id = str(uuid.uuid4())`.
   d. Call `_BATCH_JOB_STORE.create_job(job_id, tenant_id, total_rows=len(df))`.
   e. Add background task `_process_batch_job(job_id, tenant_id, df.to_dict("records"))`.
   f. Return `{"job_id": job_id, "status": "PENDING", "poll_url": f"/v1/batch/{job_id}/status", ...}`.

2. Define `async def _process_batch_job(job_id, tenant_id, rows)`:
   - Mark job RUNNING.
   - For each row, build a `LoanApplicationRequest` (skip row on validation error,
     count as rejected with error reason).
   - Await `_run_pipeline(app_req, tenant_id)` for each row (respect `_batch_semaphore`).
   - Write results as JSONL to `data/batch_results/{job_id}.jsonl`.
   - Update progress every 50 rows.
   - Mark COMPLETE on success, FAILED with error_message on exception.

3. `GET /v1/batch/{job_id}/status`:
   ```python
   @app.get("/v1/batch/{job_id}/status", tags=["Batch"])
   async def get_batch_job_status(
       job_id: str,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Poll the status of a submitted batch job.
       Enforces: job must belong to calling tenant.
       """
   ```
   Return full job dict from `_BATCH_JOB_STORE.get_job(job_id)`.
   Raise 404 if not found; 403 if tenant_id mismatch.

4. `GET /v1/batch/{job_id}/results`:
   ```python
   from fastapi.responses import FileResponse

   @app.get("/v1/batch/{job_id}/results", tags=["Batch"])
   async def get_batch_job_results(
       job_id: str,
       _user: Dict = Depends(verify_bearer),
   ) -> FileResponse:
       """Download the JSONL results for a completed batch job.
       Returns 404 if job not found or still running.
       Returns 409 if job is FAILED.
       """
   ```

5. Write integration tests `tests/test_batch_api.py`:
   - POST a valid CSV of 3 rows — assert 202, `job_id` returned.
   - Poll `/status` — assert `status` eventually becomes "COMPLETE".
   - GET `/results` — assert JSONL with 3 lines.
   - POST CSV with invalid/missing column — assert 422.
   - POST CSV with 10,001 rows — assert 413.
   - GET status for job belonging to another tenant — assert 403.
```

---

## GAP-15 — Stochastic Stress Testing

**Goal**: Implement Monte Carlo portfolio stress testing that runs 1,000+ macro scenarios against the live portfolio, stores results, and allows quarter-over-quarter comparison.

**Effort**: ~5 days

---

### Prompt G15-A — Create `risk_models/stress_test.py`

```
Create a new file `risk_models/stress_test.py`.

This module implements a Monte Carlo stress testing engine against the active
loan portfolio using macroeconomic shock scenarios.

```python
"""
Stochastic Portfolio Stress Test
=================================
Implements the Monte Carlo stress testing engine required by PRD §4.11.

Each scenario applies correlated macroeconomic shocks (GDP shock,
unemployment delta, credit spread delta) to the portfolio's PD model inputs,
re-scores every account, and measures portfolio-level expected loss (EL)
and stressed default rate (SDR).

1,000 scenarios are run per stress test run.  Results are stored in a
SQLite table and can be compared across quarters.
"""
```

Implement these components:

1. `StressScenario` dataclass:
   ```python
   @dataclass
   class StressScenario:
       scenario_id: int
       gdp_shock_pct: float          # e.g. -0.05 means -5% GDP growth
       unemployment_delta_ppt: float  # e.g. +3.0 means +3 percentage points
       credit_spread_delta_bps: float  # e.g. +200 bps
       house_price_delta_pct: float    # e.g. -0.15 means -15%
   ```

2. `ScenarioGenerator` class:
   ```python
   class ScenarioGenerator:
       def generate(
           self,
           n_scenarios: int = 1000,
           seed: int = 42,
           severity: str = "moderate",  # "mild" | "moderate" | "severe" | "tail"
       ) -> list[StressScenario]:
           """Generate correlated macro shock scenarios using a multivariate
           normal distribution with historically calibrated correlation matrix.

           Severity levels map to shock distribution parameters:
             mild:     GDP ∈ N(-0.01, 0.01), UE ∈ N(+1.0, 0.5)
             moderate: GDP ∈ N(-0.03, 0.02), UE ∈ N(+2.5, 1.0)
             severe:   GDP ∈ N(-0.06, 0.03), UE ∈ N(+5.0, 1.5)
             tail:     GDP ∈ N(-0.12, 0.04), UE ∈ N(+8.0, 2.0)

           Correlation matrix (GDP × UE × credit_spread × house_price):
             GDP ↔ UE:            -0.75 (recession drives unemployment)
             GDP ↔ credit_spread: -0.60
             GDP ↔ house_price:   +0.50
           """
   ```

3. `PortfolioStressor` class:
   ```python
   class PortfolioStressor:
       def __init__(self, model: Any, feature_names: list[str]) -> None:
           """
           model: fitted scikit-learn or LightGBM credit risk model
           feature_names: list of input feature columns
           """

       def apply_macro_shocks(
           self,
           portfolio_df: pd.DataFrame,
           scenario: StressScenario,
       ) -> pd.DataFrame:
           """Apply macro shock adjustments to portfolio features.

           Shock mappings (can be overridden via STRESS_SHOCK_CONFIG env var
           pointing to a JSON file):
             gdp_shock_pct        → credit_score * (1 + 0.3 * gdp_shock_pct)
             unemployment_delta   → debt_to_income_ratio * (1 + 0.2 * ue_delta)
             credit_spread_delta  → (no direct feature mapping; scales PD multiplicatively post-score)
             house_price_delta    → credit_score * (1 + 0.1 * house_price_delta)
           Returns a new DataFrame of shocked features without mutating the input.
           """

       def score_scenario(
           self,
           portfolio_df: pd.DataFrame,
           scenario: StressScenario,
       ) -> dict:
           """Apply shocks and re-score.  Returns:
           {
             scenario_id:       int,
             mean_pd:           float,
             stressed_dr:       float,  # accounts with shocked PD > 0.5
             expected_loss:     float,  # sum(shocked_pd * EAD)
             pct_pd_increase:   float,  # mean PD vs baseline
           }
           """
   ```

4. `StressTestRunner` class:
   ```python
   class StressTestRunner:
       def __init__(
           self,
           model: Any,
           feature_names: list[str],
           store_path: str = "./stress_test_results.db",
       ) -> None: ...

       def run(
           self,
           portfolio_df: pd.DataFrame,
           n_scenarios: int = 1000,
           severity: str = "moderate",
           run_label: str = "",
           quarter: str = "",           # e.g. "2026-Q1"
           seed: int = 42,
       ) -> "StressTestSummary": ...

       def get_results(
           self,
           quarter: str | None = None,
           limit: int = 10,
       ) -> list[dict]: ...          # most recent runs, newest first

       def compare_quarters(
           self,
           quarter_a: str,
           quarter_b: str,
       ) -> dict: ...                # delta summary between Q runs
   ```

5. `StressTestSummary` dataclass:
   ```python
   @dataclass
   class StressTestSummary:
       run_id: str
       quarter: str
       severity: str
       n_scenarios: int
       baseline_mean_pd: float
       p50_stressed_dr: float       # median across 1000 scenarios
       p95_stressed_dr: float       # 95th-percentile "stress" outcome
       p99_stressed_dr: float       # 99th-percentile "tail" outcome
       max_expected_loss: float
       scenarios_above_10pct_dr: int  # number of scenarios with DR > 10%
       run_at: str                  # ISO-8601 UTC
   ```

6. Persist results in SQLite with the schema:
   ```sql
   CREATE TABLE IF NOT EXISTS stress_test_runs (
       run_id           TEXT PRIMARY KEY,
       quarter          TEXT NOT NULL,
       severity         TEXT NOT NULL,
       n_scenarios      INTEGER NOT NULL,
       baseline_mean_pd REAL,
       p50_stressed_dr  REAL,
       p95_stressed_dr  REAL,
       p99_stressed_dr  REAL,
       max_expected_loss REAL,
       scenarios_above_10pct_dr INTEGER,
       run_at           TEXT NOT NULL,
       scenario_results_json TEXT    -- full JSON blob of all 1000 scenario dicts
   );
   ```

7. Write unit tests `tests/test_stress_test.py`:
   - Generate 100 scenarios with severity="moderate", assert len == 100.
   - Run `StressTestRunner.run()` on a 200-row synthetic portfolio with a toy LR model,
     assert `p95_stressed_dr > baseline_mean_pd`.
   - Call `compare_quarters()` with two stored runs, assert delta keys present.
   - Assert `get_results(quarter="2026-Q1")` returns only Q1 results.
```

---

### Prompt G15-B — Expose Stress Test API Endpoints

```
In `decision-api/src/main.py`, add stress test management endpoints under
the "Stress Testing" tag.

Add a module-level singleton (lazy-initialized at first use to avoid
model-load overhead at startup):
```python
_STRESS_RUNNER: Optional[Any] = None  # StressTestRunner, initialized on first call

def _get_stress_runner() -> Any:
    global _STRESS_RUNNER
    if _STRESS_RUNNER is None:
        from risk_models.stress_test import StressTestRunner
        store_path = os.getenv("STRESS_TEST_DB_PATH", "./stress_test_results.db")
        _STRESS_RUNNER = StressTestRunner(
            model=_risk_model,
            feature_names=FEATURE_CONFIG.feature_list,
            store_path=store_path,
        )
    return _STRESS_RUNNER
```

1. `POST /v1/stress-test/run`:
   ```python
   class StressTestRequest(BaseModel):
       n_scenarios: int = Field(default=1000, ge=100, le=10000)
       severity: str = Field(default="moderate",
                             pattern="^(mild|moderate|severe|tail)$")
       quarter: str = Field(default="", description="e.g. '2026-Q2'")
       run_label: str = Field(default="")

   @app.post("/v1/stress-test/run", status_code=202, tags=["Stress Testing"])
   async def run_stress_test(
       body: StressTestRequest,
       background_tasks: BackgroundTasks,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Dispatch a background stress test run.
       Returns run_id and a poll URL immediately; the run completes asynchronously.
       Requires role 'cro' or 'model_risk_officer'.
       """
   ```
   - RBAC: require `role in {"cro", "model_risk_officer"}`.
   - Load portfolio from the training data parquet
     (`DATA_DIR / "pd_training_5m.parquet"`, 50k row sample by default).
   - Background task: call `_STRESS_RUNNER.run(portfolio_df, ...)`.
   - Return `{"run_id": "...", "status": "DISPATCHED", "poll_url": "/v1/stress-test/results/..."}`.

2. `GET /v1/stress-test/results`:
   ```python
   @app.get("/v1/stress-test/results", tags=["Stress Testing"])
   async def list_stress_test_results(
       quarter: Optional[str] = None,
       limit: int = 10,
       _user: Dict = Depends(verify_bearer),
   ) -> List[Dict[str, Any]]:
       """List recent stress test runs, optionally filtered by quarter."""
   ```

3. `GET /v1/stress-test/compare`:
   ```python
   @app.get("/v1/stress-test/compare", tags=["Stress Testing"])
   async def compare_stress_quarters(
       quarter_a: str,
       quarter_b: str,
       _user: Dict = Depends(verify_bearer),
   ) -> Dict[str, Any]:
       """Return delta metrics between two quarter stress test runs."""
   ```

Write integration tests `tests/test_stress_api.py`:
- Mock `StressTestRunner.run()` to return a stub summary.
- POST to `/v1/stress-test/run` with CRO JWT — assert 202.
- POST with non-CRO JWT — assert 403.
- GET `/v1/stress-test/results` — assert list returned.
- GET `/v1/stress-test/compare?quarter_a=...&quarter_b=...` — assert delta keys present.
```

---

## GAP-16 — Webhook Delivery Framework

**Goal**: Implement an outbound webhook framework with CRUD endpoint management, signed delivery, exponential-backoff retry, and delivery log.

**Effort**: ~3 days

---

### Prompt G16-A — Create the `webhooks/` Package

```
Create the following files:

--- `webhooks/__init__.py` ---
Empty; marks the directory as a Python package.

--- `webhooks/models.py` ---
Define data models for webhooks:

```python
from __future__ import annotations
import hashlib, hmac, json, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

EventType = Literal[
    "decision.approved",
    "decision.rejected",
    "decision.manual_review",
    "batch.complete",
    "batch.failed",
    "adverse_action.generated",
    "model.drift_alert",
]

@dataclass
class WebhookRegistration:
    webhook_id: str
    tenant_id: str
    target_url: str
    secret: str          # HMAC signing secret (stored hashed in DB; value returned once at creation)
    events: list[str]    # list of EventType values to subscribe to; ["*"] means all
    is_active: bool
    created_at: str
    description: str = ""

@dataclass
class WebhookDeliveryAttempt:
    attempt_id: str
    webhook_id: str
    tenant_id: str
    event_type: str
    payload_json: str
    response_status: int | None    # HTTP status from target; None if connection failed
    response_body: str | None
    delivered_at: str
    duration_ms: int
    success: bool
    error_message: str | None = None
    attempt_number: int = 1

def sign_payload(secret: str, payload_bytes: bytes) -> str:
    """Return HMAC-SHA256 hex digest: 'sha256=<hex>'."""
    sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"
```

--- `webhooks/store.py` ---
Define `WebhookStore` using a SQLite backend:

```python
class WebhookStore:
    """SQLite-backed store for webhook registrations and delivery logs."""

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS webhook_registrations (
        webhook_id    TEXT PRIMARY KEY,
        tenant_id     TEXT NOT NULL,
        target_url    TEXT NOT NULL,
        secret_hash   TEXT NOT NULL,   -- SHA-256 of the secret; original not stored
        events_json   TEXT NOT NULL,   -- JSON array of subscribed event types
        is_active     INTEGER NOT NULL DEFAULT 1,
        description   TEXT NOT NULL DEFAULT '',
        created_at    TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS ix_wh_tenant ON webhook_registrations (tenant_id);

    CREATE TABLE IF NOT EXISTS webhook_delivery_log (
        attempt_id      TEXT PRIMARY KEY,
        webhook_id      TEXT NOT NULL,
        tenant_id       TEXT NOT NULL,
        event_type      TEXT NOT NULL,
        payload_json    TEXT NOT NULL,
        response_status INTEGER,
        response_body   TEXT,
        delivered_at    TEXT NOT NULL,
        duration_ms     INTEGER NOT NULL DEFAULT 0,
        success         INTEGER NOT NULL DEFAULT 0,
        error_message   TEXT,
        attempt_number  INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS ix_wdl_webhook ON webhook_delivery_log (webhook_id);
    CREATE INDEX IF NOT EXISTS ix_wdl_event   ON webhook_delivery_log (event_type);
    """

    def __init__(self, db_path: str = "./webhooks.db") -> None: ...
    def register(self, tenant_id, target_url, secret, events, description) -> WebhookRegistration: ...
    def get(self, webhook_id: str) -> WebhookRegistration | None: ...
    def list_for_tenant(self, tenant_id: str) -> list[WebhookRegistration]: ...
    def list_for_event(self, tenant_id: str, event_type: str) -> list[WebhookRegistration]: ...
    def deactivate(self, webhook_id: str, tenant_id: str) -> bool: ...
    def log_attempt(self, attempt: WebhookDeliveryAttempt) -> None: ...
    def get_delivery_log(self, webhook_id: str, limit: int = 50) -> list[WebhookDeliveryAttempt]: ...
```

--- `webhooks/dispatcher.py` ---
Define `WebhookDispatcher`:

```python
class WebhookDispatcher:
    """Delivers webhook events with exponential-backoff retry.

    Retry policy (PRD §9.6):
      Attempt 1: immediate
      Attempt 2: 30 seconds
      Attempt 3: 5 minutes
      Attempt 4: 30 minutes
      Attempt 5: 2 hours
      After 5 failures: mark delivery as permanently failed; log WARN.

    Signing: every POST includes header `X-ILOL-Signature: sha256=<hmac>`
    computed over the raw JSON body using the registration secret.
    Receiving systems verify this header to authenticate the delivery.

    Timeout: 10 seconds per attempt.
    """

    def __init__(self, store: WebhookStore) -> None: ...

    def dispatch(
        self,
        tenant_id: str,
        event_type: EventType,
        payload: dict,
    ) -> int:
        """Deliver *payload* to all active webhooks subscribed to *event_type*
        for *tenant_id*.  Returns count of successful deliveries.

        This method is synchronous and handles retries inline.
        For production use, wire to a background task via FastAPI BackgroundTasks
        (see G16-B).
        """

    def _deliver_once(
        self,
        registration: WebhookRegistration,
        event_type: str,
        payload_bytes: bytes,
        attempt_number: int,
    ) -> WebhookDeliveryAttempt:
        """Make one HTTP POST attempt and return a DeliveryAttempt record."""
```

Write unit tests `tests/test_webhooks.py`:
- Register a webhook, assert `list_for_tenant()` returns it.
- Deactivate a webhook, assert `list_for_event()` does not return it.
- `sign_payload()` — assert signature verifiable with `hmac.compare_digest`.
- Mock an HTTP target returning 200 — assert `dispatch()` returns 1 and
  delivery log entry has `success=True`.
- Mock target returning 500 then 200 on retry — assert `attempt_number=2`
  in the success log entry.
- Mock target always returning 500 — assert after 5 attempts the attempt is
  logged as permanently failed.
```

---

### Prompt G16-B — Webhook CRUD Endpoints and Decision Event Wiring

```
In `decision-api/src/main.py`, add webhook management endpoints and wire
decision events to the dispatcher.

Add module-level singletons:
```python
from webhooks.store import WebhookStore
from webhooks.dispatcher import WebhookDispatcher

_WEBHOOK_STORE    = WebhookStore(db_path=os.getenv("WEBHOOK_DB_PATH", "./webhooks.db"))
_WEBHOOK_DISPATCH = WebhookDispatcher(store=_WEBHOOK_STORE)
```

1. Webhook CRUD endpoints (tag: "Webhooks"):

   ```python
   class WebhookCreateRequest(BaseModel):
       target_url: str = Field(..., description="HTTPS URL to POST events to")
       events: list[str] = Field(default=["*"], description="Event types or ['*'] for all")
       description: str = Field(default="")

   @app.post("/v1/webhooks", status_code=201, tags=["Webhooks"])
   async def create_webhook(body: WebhookCreateRequest, _user=Depends(verify_bearer)):
       """Register a new webhook endpoint. Returns the registration including the
       one-time plaintext secret (not stored; client must save it)."""

   @app.get("/v1/webhooks", tags=["Webhooks"])
   async def list_webhooks(_user=Depends(verify_bearer)):
       """List all webhook registrations for the calling tenant."""

   @app.get("/v1/webhooks/{webhook_id}/deliveries", tags=["Webhooks"])
   async def get_webhook_deliveries(webhook_id: str, limit: int = 50, _user=Depends(verify_bearer)):
       """Return delivery log for a specific webhook (last 50 attempts)."""

   @app.delete("/v1/webhooks/{webhook_id}", status_code=204, tags=["Webhooks"])
   async def delete_webhook(webhook_id: str, _user=Depends(verify_bearer)):
       """Deactivate (soft-delete) a webhook registration."""
   ```

   Enforce tenant isolation: all operations must filter by `tenant_id` from JWT.

2. Wire decision events into the dispatcher.

   In `_run_pipeline()`, after the final `return DecisionResponse(...)` is built
   (before returning), add a fire-and-forget background dispatch call:

   ```python
   # G16: Dispatch webhook event for this decision (best-effort; never blocks response)
   try:
       _event_type = {
           "APPROVE":       "decision.approved",
           "REJECT":        "decision.rejected",
           "MANUAL_REVIEW": "decision.manual_review",
       }.get(decision_result.decision, "decision.manual_review")

       _webhook_payload = {
           "application_id":   app_req.application_id,
           "decision":         decision_result.decision,
           "pd_score":         pd_score,
           "notice_id":        notice_id,
           "audit_log_id":     audit_log_id,
           "tenant_id":        tenant_id,
           "event_type":       _event_type,
           "occurred_at":      datetime.utcnow().isoformat() + "Z",
       }
       # Run in thread to avoid blocking the async event loop
       import asyncio
       loop = asyncio.get_event_loop()
       loop.run_in_executor(
           None,
           lambda: _WEBHOOK_DISPATCH.dispatch(tenant_id, _event_type, _webhook_payload)
       )
   except Exception as _wh_exc:
       logger.warning("Webhook dispatch failed (non-fatal): %s", _wh_exc)
   ```

   Similarly, wire `batch.complete` and `batch.failed` events in `_process_batch_job()`.

3. Write integration tests `tests/test_webhook_endpoints.py`:
   - POST `/v1/webhooks` with a valid HTTPS URL — assert 201 and `secret` field present.
   - GET `/v1/webhooks` — assert list contains the new registration.
   - DELETE `/v1/webhooks/{id}` — assert 204 and subsequent GET does not return it.
   - Assert listing another tenant's webhooks returns empty list (tenant isolation).
   - POST a decision via `/v1/decisions` with a registered webhook — assert
     `dispatcher.dispatch()` was called (use `unittest.mock.patch`).
```

---

## Execution Order & Dependencies

```
G10-A ──────────────────────────► G10-B
G11-A ──────────────────────────► G11-B
G12-A ──────────────────────────► G12-B
G13-A ──────────────────────────► G13-B
G14-A ──────────────────────────► G14-B
G15-A ──────────────────────────► G15-B
G16-A ──────────────────────────► G16-B
```

All `-A` prompts are independent of each other and safe to implement in parallel.
Each `-B` depends only on its corresponding `-A` being complete.

**Recommended sprint order** (by priority × effort × dependency risk):

| Sprint | Prompts | Rationale |
|--------|---------|-----------|
| Sprint 1 | G10-A, G10-B | 1-day close; highest-value P3; needed by loan officers now |
| Sprint 2 | G11-A, G11-B | 2-day close; SOC 2 gate; blocks production policy changes |
| Sprint 3 | G16-A, G16-B | 3-day close; enables partner integrations; isolated new module |
| Sprint 4 | G12-A, G12-B | 3-day close; de-risks next deployment; no functional dependencies |
| Sprint 5 | G14-A, G14-B | 2-day close; unblocks analytics/bulk origination use cases |
| Sprint 6 | G13-A, G13-B | 4-day close; new auth surface; do last to minimise attack surface review scope |
| Sprint 7 | G15-A | 4-day core engine; CCAR/stress testing cycle |
| Sprint 8 | G15-B | 1-day API wrapper; complete after G15-A is validated |

---

## Acceptance Criteria

| Gap | Criterion | Test |
|-----|-----------|------|
| G10 | `GET /v1/decisions/{id}/explanation` returns 200 with `shap`, `counterfactual`, `narrative` keys | `tests/test_explanation_endpoint.py` |
| G10 | Returns 404 for unknown decision ID | `tests/test_explanation_endpoint.py` |
| G10 | Returns 403 for cross-tenant access | `tests/test_explanation_endpoint.py` |
| G10 | Does not return 500 when counterfactual generation fails | `tests/test_explanation_endpoint.py` |
| G11 | Staging a config does NOT activate it | `tests/test_config_staging.py` |
| G11 | Approving a staged config activates it | `tests/test_config_staging.py` |
| G11 | `actor_email == approver_email` → HTTP 409 | `tests/test_policy_four_eyes.py` |
| G11 | Non-CRO/compliance_officer role → HTTP 403 on `/v1/config/approve` | `tests/test_policy_four_eyes.py` |
| G11 | `POST /v1/config` without bypass header → HTTP 428 | `tests/test_policy_four_eyes.py` |
| G12 | `GET /v1/metrics` returns `canary_healthy` key | `tests/test_service_metrics.py` |
| G12 | `canary_decision_api.py` returns exit code 2 when threshold breached | `tests/test_canary_script.py` |
| G12 | Rollback function called when health check fails | `tests/test_canary_script.py` |
| G13 | Borrower token cannot access another tenant's applications | `tests/test_portal_api.py` |
| G13 | Tenant JWT cannot access `/v1/portal/` endpoints | `tests/test_portal_api.py` |
| G13 | `pd_score` and `fraud_probability` absent from portal responses | `tests/test_portal_api.py` |
| G14 | CSV upload returns `job_id` immediately (202) | `tests/test_batch_api.py` |
| G14 | `/v1/batch/{id}/status` transitions PENDING → RUNNING → COMPLETE | `tests/test_batch_api.py` |
| G14 | CSV with missing columns → HTTP 422 | `tests/test_batch_api.py` |
| G14 | CSV with > 10,000 rows → HTTP 413 | `tests/test_batch_api.py` |
| G15 | `p95_stressed_dr > baseline_mean_pd` for any severity | `tests/test_stress_test.py` |
| G15 | Results persisted and queryable by quarter | `tests/test_stress_test.py` |
| G15 | Non-CRO role → HTTP 403 on `/v1/stress-test/run` | `tests/test_stress_api.py` |
| G16 | Webhook CRUD creates/lists/deletes registrations | `tests/test_webhook_endpoints.py` |
| G16 | Decision events trigger dispatcher calls | `tests/test_webhook_endpoints.py` |
| G16 | 5 consecutive 5xx responses → permanent failure logged | `tests/test_webhooks.py` |
| G16 | Tenant isolation: cannot list another tenant's webhooks | `tests/test_webhook_endpoints.py` |

---

## New Files Summary

| File | Gap | Description |
|------|-----|-------------|
| `explainability/counterfactual.py` | G10 | Greedy counterfactual generator |
| `decision-api/src/borrower_auth.py` | G13 | Borrower JWT issuance and verification |
| `decision-api/src/batch_job_store.py` | G14 | SQLite job lifecycle tracker |
| `risk_models/stress_test.py` | G15 | Monte Carlo stress engine |
| `webhooks/__init__.py` | G16 | Package marker |
| `webhooks/models.py` | G16 | WebhookRegistration, DeliveryAttempt, sign_payload |
| `webhooks/store.py` | G16 | SQLite-backed webhook registry and delivery log |
| `webhooks/dispatcher.py` | G16 | Delivery engine with exponential-backoff retry |
| `scripts/canary_decision_api.py` | G12 | Canary progressive ramp controller |
| `deploy/cloud_run_traffic.yaml` | G12 | Cloud Run traffic split manifest template |
| `deploy/nginx_canary.conf.template` | G12 | NGINX upstream weighting template |

## Modified Files Summary

| File | Gap | Changes |
|------|-----|---------|
| `decision-api/src/main.py` | G10, G11, G12, G13, G14, G15, G16 | New endpoints, metrics middleware, webhook singletons, portal endpoints |
| `config_registry/service.py` | G11 | `stage_config()`, `approve_staged_config()`, `reject_staged_config()`, `get_staged()` |

---

## Environment Variables Required

| Variable | Gap | Purpose |
|----------|-----|---------|
| `BORROWER_JWT_SECRET` | G13 | Separate HMAC secret for borrower-scoped portal tokens |
| `CANARY_P99_THRESHOLD_MS` | G12 | Max acceptable p99 latency during canary (default: 500) |
| `CANARY_ERROR_RATE_THRESHOLD` | G12 | Max acceptable 5xx error rate during canary (default: 0.01) |
| `METRICS_AUTH_TOKEN` | G12 | Bearer token used by canary script to poll `/v1/metrics` |
| `STRESS_TEST_DB_PATH` | G15 | Path to stress test results SQLite DB |
| `STRESS_SHOCK_CONFIG` | G15 | Optional JSON file overriding default macro shock mappings |
| `WEBHOOK_DB_PATH` | G16 | Path to webhook registry SQLite DB (default: `./webhooks.db`) |
| `LINEAGE_STORE_PATH` | G10 (indirect) | Required if lineage context embedded in explanation endpoint |

---

*For P1 and P2 (GAP-01 through GAP-05) gap closure, see [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md) and [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_GAPS_3_4_5.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_GAPS_3_4_5.md)*
*For P3 GAP-06 through GAP-09 gap closure, see [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_P3_GAPS_6_7_8_9.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_P3_GAPS_6_7_8_9.md)*
