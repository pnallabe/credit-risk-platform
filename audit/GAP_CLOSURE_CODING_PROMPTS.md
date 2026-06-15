# Gap Closure Coding Prompts
## Helix Decisions — Investor Readiness Sprint

**Source:** `audit/HELIX_DECISIONS_PLATFORM_AUDIT_2026.md`
**Date:** June 12, 2026
**Execution order:** Run prompts sequentially. Do not skip guard-rail prompts.
**Scope:** 14 prompts covering P0 → P2 gaps. P3 items are excluded.

---

## Global Guard-Rail Prompt (Prepend to Every Prompt Below)

```text
You are implementing changes in a regulated credit-risk platform (Helix Decisions).
Guard rails are mandatory for every task:

1. Preserve backward compatibility unless explicitly instructed otherwise.
2. Do not remove existing tests. Add or update tests for every behavior change.
3. Keep one canonical feature path; do not duplicate feature logic.
4. Add structured logging (logger.info / logger.warning / logger.error) for all
   failures and non-trivial paths.
5. Validate inputs at system boundaries and return explicit, typed errors (never
   bare exceptions to callers).
6. Avoid broad refactors unrelated to this task.
7. Update docstrings and inline comments for any interface or schema change.
8. After implementation, provide:
   (a) files changed
   (b) tests added or updated
   (c) risk notes (what could break, what is deferred)
```

---

## P0 — Critical (Do First)

---

### Prompt 1 — AI Agent Chain Verification Endpoint (GAP-20 Closure)

```text
Task:
Implement a verify_ai_agent_chain() function in ai-agent/src/ai_audit_log.py
and expose it via a new GET /api/v1/agent/audit/verify-chain API endpoint
in ai-agent/src/main.py.

Context:
The ai_agent_audit_log table already has record_hash and previous_hash columns
populated by log_ai_turn(). The hash-chain computation pattern in
ai-agent/src/ai_audit_log.py mirrors audit/logger.py. However, no verification
function exists — there is no way to confirm the chain has not been tampered with.
The audit/logger.py module has a compute_chain_hash() function at line 275 that
serves as the reference pattern.

Requirements:
- Add async def verify_ai_agent_chain(session_id: str | None, db_url: str)
  in ai-agent/src/ai_audit_log.py.
  - If session_id is provided: verify the chain only for that session.
  - If session_id is None: verify the entire table (all sessions, all tenants).
  - Walk rows in (session_id, logged_at) order.
  - For each row, recompute the expected record_hash using _compute_chain_hash()
    with the stored previous_hash and canonical payload.
  - Return a ChainVerificationResult dataclass:
      - total_records: int
      - verified_records: int
      - broken_at: list[str]  # log_id values where chain breaks
      - is_intact: bool       # True if broken_at is empty
- Add GET /api/v1/agent/audit/verify-chain to ai-agent/src/main.py.
  - Query params: session_id (optional str).
  - Requires valid JWT (same auth as other protected endpoints).
  - Returns ChainVerificationResult as JSON.
  - Log the result at INFO level with tenant_id context.
- Register the verify-chain route in the exam packet AI appendix component in
  compliance/exam_packet_builder.py: call verify_ai_agent_chain() during
  build_ai_agent_audit_component() and include is_intact in the packet output.

Testing:
- Unit test: insert 5 rows with correct chain → verify_ai_agent_chain returns
  is_intact=True, verified_records=5.
- Unit test: insert 5 rows, manually corrupt row 3's record_hash → returns
  is_intact=False, broken_at contains row 3's log_id.
- Unit test: session_id filter — only verifies rows for the given session.
- Integration test: call GET /api/v1/agent/audit/verify-chain via TestClient,
  assert 200 and is_intact field present.

Deliverables:
- verify_ai_agent_chain() in ai_audit_log.py
- GET /api/v1/agent/audit/verify-chain endpoint
- ChainVerificationResult dataclass
- Tests in ai-agent/tests/
- Risk note: chain verification is read-only; it does not repair broken chains.
  Broken chains require a forensic investigation workflow (out of scope here).
```

---

### Prompt 2 — Per-Tenant Configurable Confidence Threshold (GAP-19 Closure)

```text
Task:
Make the AI agent's refusal confidence threshold configurable per tenant instead
of hardcoded, and add an explicit grounding gate that refuses when the query
result set is empty and no SQL artifact was produced.

Context:
ai-agent/src/confidence_scorer.py has should_refuse() at line 130. It currently
refuses only when label == "none" OR (empty_result AND score < 0.10). The
threshold (0.10) is hardcoded and cannot be tuned per tenant. Some tenants with
sensitive portfolios need a stricter gate (e.g., 0.30); others may accept lower
confidence for exploratory queries.

The config_registry/service.py (ConfigRegistryService) already supports
per-tenant config key/value storage. Use it as the backing store.

Requirements:
- Add a new config key "ai_agent.refusal_threshold" to the config registry
  (default value: 0.10, valid range: 0.05–0.60).
- Modify should_refuse() to accept an optional threshold: float = 0.10 parameter
  instead of hardcoding. Do not change the function signature in a
  backward-incompatible way — make threshold keyword-only with a default.
- In ai-agent/src/main.py, at the point where should_refuse() is called (around
  the /api/v1/agent/query handler), fetch "ai_agent.refusal_threshold" from the
  config registry for the current tenant_id. Fall back to 0.10 if the key is
  absent or the value is out of range.
- Add a strict grounding gate: if factors.row_count == 0 AND
  factors.has_sql_artifact is False AND factors.query_error is False
  (meaning the query ran but returned nothing AND produced no SQL), refuse
  unconditionally regardless of threshold. This prevents the agent from
  confabulating answers when the data plane returned nothing.
- Add GET /api/v1/agent/config to ai-agent/src/main.py:
  Returns the active ai_agent.* config keys for the current tenant:
  { "refusal_threshold": float, "source": "tenant_override" | "default" }

Testing:
- Unit test: should_refuse() with threshold=0.05 passes a score of 0.08.
- Unit test: should_refuse() with threshold=0.30 refuses a score of 0.25.
- Unit test: strict grounding gate fires when row_count=0, has_sql_artifact=False,
  query_error=False even if score=0.50.
- Unit test: config registry returns override when key exists; falls back to 0.10
  when absent.
- Integration test: set "ai_agent.refusal_threshold" = 0.40 for test tenant →
  a query with score 0.35 returns a structured refusal response body.

Deliverables:
- Modified confidence_scorer.py (threshold param + strict grounding gate)
- Config registry key registration
- GET /api/v1/agent/config endpoint
- Updated query handler in main.py
- Tests
- Risk note: tenants setting threshold > 0.50 will see high refusal rates on
  data-sparse portfolios. Document this in the API reference.
```

---

### Prompt 3 — Code Artifact Re-Execution Endpoint (GAP-19 Closure)

```text
Task:
Add a POST /api/v1/agent/artifacts/{artifact_id}/execute endpoint to
ai-agent/src/main.py that re-executes a stored SQL code artifact against the
tenant's data plane and returns the result, proving reproducibility.

Context:
ai-agent/src/code_artifact_store.py stores SQL artifacts in agent_code_artifacts
(artifact_id, turn_id, language, code, result_hash, tenant_id). The code is
stored but there is no way to re-run it. This is the key "show me the code"
differentiator — investors and OCC examiners need to verify that re-running the
stored SQL produces the same answer.

Requirements:
- Add POST /api/v1/agent/artifacts/{artifact_id}/execute.
  - Lookup artifact by artifact_id and verify it belongs to the calling tenant
    (tenant_id from JWT must match artifact's tenant_id — hard requirement,
    never allow cross-tenant execution).
  - Only execute artifacts where language == "sql". Return 422 for Python
    artifacts (Python execution sandbox is out of scope; note this in the response).
  - Run the stored SQL via the existing BigQuery client or the analytics DB
    connection (whichever is configured for the tenant).
  - Compute SHA-256 of the result rows (same hashing approach as result_hash
    stored at creation time).
  - Return:
      {
        "artifact_id": str,
        "original_result_hash": str,    # stored at creation time
        "reexecution_result_hash": str,  # just computed
        "hashes_match": bool,
        "row_count": int,
        "executed_at": ISO8601 timestamp,
        "rows_preview": list[dict]       # first 10 rows only
      }
  - Write a re-execution event to ai_agent_audit_log (use log_ai_turn with a
    synthetic turn marking type="artifact_reexecution").
  - Rate-limit: max 20 re-executions per tenant per hour (use existing
    RateLimitMiddleware pattern).

Security:
- Validate the SQL artifact against compliance/prohibited_variables.py before
  re-executing. Reject with 422 if prohibited variables are present.
- Never allow the caller to modify the SQL — execute exactly what was stored.

Testing:
- Unit test: artifact belongs to wrong tenant → 403.
- Unit test: Python artifact → 422 with clear message.
- Unit test: SQL artifact re-executes and hashes_match=True when data is
  unchanged.
- Unit test: prohibited variable in stored SQL → 422 (should never happen but
  must be verified).
- Integration test: store an artifact, re-execute, verify audit log entry.

Deliverables:
- POST /api/v1/agent/artifacts/{artifact_id}/execute endpoint
- Audit log write for re-execution events
- Rate limiting
- Tests
- Risk note: BigQuery re-execution costs real money. Consider adding a "dry run"
  flag that validates the SQL without executing (future work).
```

---

### Prompt 4 — Run and Register SMB PD Model Artifact

```text
Task:
Run the existing SMB PD model training script, validate the output artifact,
and wire the trained model into the decision routing logic so that SMB loan
applications are scored by the SMB model instead of the CC model.

Context:
models/credit_risk/train_smb_pd_model.py (501 lines) is fully written but has
never been executed — no artifact file exists. The model_loader.py at line 2372
already references "smb_pd_v1" → "models/credit_risk/smb_pd_scorecard_woe.json"
but this file does not exist. decision-api/src/main.py uses predict_pd() from
models/credit_risk/predict.py which loads the CC model by default.

Requirements:
Step 1 — Training (run in terminal, not code change):
  cd credit-risk-platform
  python models/credit_risk/train_smb_pd_model.py --sample 5000

  Validate outputs:
  - smb_pd_model_v1.pkl exists under models/credit_risk/
  - smb_pd_scorecard_woe.json exists under models/credit_risk/
  - smb_pd_model_card.json exists under models/credit_risk/
  - MLflow run registered under experiment "smb_pd_v1"
  - Gini coefficient on holdout >= 0.30 (check printed output)

Step 2 — Model loader routing (code change in models/credit_risk/predict.py):
  - Add a product_type: str = "credit_card" parameter to predict_pd().
  - If product_type == "smb_loan": load smb_pd_model_v1.pkl and apply the SMB
    feature set. If product_type is anything else: keep existing CC model path.
  - Keep backward compatibility — callers that omit product_type get CC behavior.
  - Add load_smb_model() to models/model_loader.py following the same
    cache_info() / load_model() pattern.

Step 3 — Decision API routing (code change in decision-api/src/main.py):
  - In the POST /v1/decisions handler, extract product_type from the request.
  - Pass product_type to predict_pd() so SMB applications use the SMB model.
  - Update GET /v1/health to report smb_pd_v1 model version alongside cc_pd_v1.
  - Update GET /v1/models to list smb_pd_v1 in the model registry response.

Step 4 — Scorecard endpoint:
  - GET /v1/models/smb_pd_v1/scorecard must return the WoE scorecard JSON from
    smb_pd_scorecard_woe.json. Verify this works with the existing scorecard
    endpoint handler at line 2377.

Testing:
  - Unit test: predict_pd(features, product_type="smb_loan") returns a float
    in [0.0, 1.0] using the SMB model.
  - Unit test: predict_pd(features) (no product_type) still uses CC model.
  - Unit test: POST /v1/decisions with product_type="smb_loan" → decision
    response includes model_version="smb_pd_v1".
  - Unit test: GET /v1/models/smb_pd_v1/scorecard returns 200 with non-empty
    score_bands.
  - Regression test: existing CC decision tests still pass unchanged.

Deliverables:
  - Trained smb_pd_model_v1.pkl + smb_pd_scorecard_woe.json + smb_pd_model_card.json
  - Updated predict.py and model_loader.py
  - Updated decision-api routing
  - Tests
  - Risk note: SMB model is trained on synthetic data. Before any live pilot,
    replace with real SBA 7(a) or institution-supplied SMB loan data and retrain.
    Document this in smb_pd_model_card.json under "training_data_limitations".
```

---

### Prompt 5 — Self-Service Tenant Provisioning Flow

```text
Task:
Implement end-to-end self-service tenant onboarding in ui/tenant-portal/ so a
new tenant can sign up, receive an API key, and make their first /v1/decisions
call without any ops team involvement.

Context:
- ui/tenant-portal/ scaffolding exists (src/app/, src/components/, src/lib/).
- Backend: GET /api/v1/tenants/me and POST /api/v1/tenant-inquiries are
  implemented.
- Missing: API key generation, tenant record creation, and a guided activation
  flow in the portal UI.
- db/migrations/005_tenant_portal.sql has tenants, tenant_members, and
  tenant_inquiries tables.

Requirements:

Backend (decision-api/src/main.py):
  - Add POST /api/v1/tenants/provision:
    - Input: { "company_name": str, "contact_email": str, "firebase_uid": str }
    - Create a row in tenants table (tenant_id = UUID4, status = "active").
    - Create a row in tenant_members (firebase_uid linked to tenant_id, role = "admin").
    - Generate a secure API key: 32-byte secrets.token_urlsafe(), prefix "hx_".
      Store SHA-256 hash in a new tenant_api_keys table (never store plaintext).
    - Return: { "tenant_id": str, "api_key": str } — this is the ONLY time the
      plaintext key is returned. Log a provisioning audit event.
    - Idempotent: if firebase_uid already has a tenant, return existing
      tenant_id and a message "already_provisioned" (do not re-issue key).

  - Add POST /api/v1/tenants/rotate-key:
    - Requires valid JWT (existing key or Firebase token).
    - Invalidates the current API key hash, generates and stores a new one.
    - Returns the new plaintext key once.

  - Update existing API key authentication middleware to check tenant_api_keys
    table (SHA-256 hash comparison) in addition to the current JWT path.

Backend (db/migrations/):
  - Add 006_tenant_api_keys.sql:
    CREATE TABLE tenant_api_keys (
      key_id        TEXT PRIMARY KEY,
      tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
      key_hash      TEXT NOT NULL UNIQUE,   -- SHA-256 of "hx_" + random
      created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
      revoked_at    TIMESTAMP,
      created_by    TEXT NOT NULL           -- firebase_uid
    );

Frontend (ui/tenant-portal/src/):
  - Add /onboarding page with a 3-step wizard:
    Step 1 "Create Account": email + company name form → calls POST /provision.
    Step 2 "Your API Key": displays the key with a copy button and a warning
      ("Save this now — it will not be shown again"). Shows a masked preview
      after dismissal.
    Step 3 "First Call": shows a pre-filled curl snippet:
      curl -X POST https://api.helixdecisions.ai/v1/decisions \
           -H "X-API-Key: hx_..." \
           -H "Content-Type: application/json" \
           -d @sample_applicant.json
      Includes a "Test Connection" button that POSTs to /v1/health and shows
      the response (green checkmark or error).
  - Navigation guard: redirect unauthenticated users to /auth/signin.

Security (mandatory):
  - Never log the plaintext API key. Log only the first 8 characters for
    debugging (prefix + 5 chars of the random portion).
  - Key comparison must be constant-time (use hmac.compare_digest on the hash).
  - Rate-limit POST /api/v1/tenants/provision to 3 requests per IP per hour
    (use existing RateLimitMiddleware).

Testing:
  - Unit test: POST /provision creates tenant + member + key_hash row; returns
    plaintext key with "hx_" prefix.
  - Unit test: Second POST /provision with same firebase_uid returns
    "already_provisioned" and same tenant_id; does NOT create duplicate rows.
  - Unit test: API key auth middleware accepts "hx_..." key via X-API-Key header.
  - Unit test: Revoked key (revoked_at IS NOT NULL) → 401.
  - Unit test: POST /rotate-key generates a new hash and invalidates old one.
  - Component test (Playwright or vitest): onboarding wizard Step 2 shows key,
    copy button writes to clipboard, dismissal masks the key.

Deliverables:
  - POST /api/v1/tenants/provision and /rotate-key in decision-api
  - 006_tenant_api_keys.sql migration
  - tenant_api_keys auth middleware update
  - Onboarding wizard in ui/tenant-portal/src/app/onboarding/
  - Tests
  - Risk note: plaintext key is returned exactly once. If the user loses it,
    they must rotate. Document this prominently in the UI and in the API reference.
```

---

## P1 — High Priority (Next 4 Weeks)

---

### Prompt 6 — Performance Load Test and Benchmark Report

```text
Task:
Write a k6 load test for POST /v1/decisions and produce a benchmark report
that validates (or refutes) the "<200ms p99" latency claim in the investor deck.

Context:
The investor pitch deck (docs/pitch/INVESTOR_PITCH_DECK.md, Slide 6) states
"Decision API < 200ms p99". No benchmark evidence exists in the repo.
This must be verified before investor technical diligence.

Requirements:
  - Create scripts/benchmark_decision_api.js as a k6 script:
    - Stage 1 (ramp up): 0 → 20 VUs over 30s
    - Stage 2 (sustained): 20 VUs for 2 minutes
    - Stage 3 (peak): 50 VUs for 1 minute
    - Stage 4 (ramp down): 50 → 0 VUs over 30s
    - Target: POST /v1/decisions with data/sample_applicant.json payload.
    - Thresholds (fail the run if breached):
        http_req_duration['p(95)'] < 500ms
        http_req_duration['p(99)'] < 1000ms
        http_req_failed < 1%
    - Output JSON summary to reports/benchmarks/decision_api_benchmark.json.

  - Create scripts/run_benchmark.sh:
    - Starts the decision-api in a subprocess if not already running.
    - Runs k6 with the above script.
    - Extracts p50, p95, p99 from the JSON output.
    - Appends a one-line result (timestamp, p50, p95, p99, vus_peak) to
      reports/benchmarks/benchmark_history.csv.
    - Prints a PASS / FAIL verdict against the <200ms p99 target.

  - Create reports/benchmarks/BENCHMARK_README.md explaining:
    - How to run the benchmark.
    - What the thresholds mean.
    - What infrastructure the benchmark was run against (local SQLite vs.
      Cloud SQL PostgreSQL will have very different results — document this).
    - The current measured p99 and whether the <200ms claim is validated.

  - If p99 exceeds 200ms on local SQLite, add a clearly labeled note in
    reports/benchmarks/BENCHMARK_README.md:
    "Local SQLite baseline: Xms p99. Production Cloud SQL target: <200ms p99.
    Full production benchmark pending PostgreSQL migration."
    Do NOT falsify or suppress results.

Testing:
  - Add tests/test_decision_latency.py: uses TestClient to make 10 sequential
    /v1/decisions calls and asserts mean latency < 2s (a loose sanity check,
    not the real benchmark — the real benchmark requires k6 and a running server).

Deliverables:
  - scripts/benchmark_decision_api.js
  - scripts/run_benchmark.sh
  - reports/benchmarks/decision_api_benchmark.json (first run result)
  - reports/benchmarks/benchmark_history.csv (first entry)
  - reports/benchmarks/BENCHMARK_README.md
  - tests/test_decision_latency.py
  - Risk note: benchmark results on SQLite in-process DB will not reflect
    production performance. This is a known limitation — document it.
```

---

### Prompt 7 — SHAP Waterfall Chart Component in Dashboard

```text
Task:
Add a SHAP waterfall chart to the underwriter decision detail view in
ui/analytics-dashboard so that feature contributions are visualized, not just
returned as JSON.

Context:
GET /v1/decisions/{id}/explanation returns a JSON response with a shap_values
object (feature → float contribution map). The analytics dashboard has an
underwriter queue at /underwriter/queue and history at /underwriter/history.
No chart component renders these values. The DESIGN.md analytics dashboard
palette should be used (brand-blue #1d4ed8 for positive contributions,
status-red #dc2626 for negative, border-default #e2e8f0 for zero-crossing line).

Requirements:
  - Create ui/analytics-dashboard/components/charts/ShapWaterfallChart.tsx:
    - Props: { shapValues: Record<string, number>; baseValue: number;
               finalScore: number; maxFeatures?: number }
    - Renders a horizontal bar chart (Recharts BarChart or plain SVG):
        * Bars sorted by absolute contribution (largest first).
        * Positive contributions = brand-blue fill.
        * Negative contributions = status-red fill.
        * Truncate to maxFeatures (default 10) most impactful features.
        * Show feature name + formatted contribution value (e.g., "+4.2 pts")
          as bar labels.
        * Footer row: base value + contributions = final score (sanity check).
    - Accessible: bars have aria-label; color is NOT the only encoding
      (use + / - prefix on values per DESIGN.md rule "always paired with text
      labels, never color-only").
    - Loading skeleton state for when explanation fetch is in-flight.

  - Add ExplanationPanel component to ui/analytics-dashboard/components/:
    - Fetches GET /v1/decisions/{id}/explanation on mount.
    - Renders: ShapWaterfallChart + counterfactual text + NLG summary paragraph.
    - Error state if explanation unavailable.

  - Wire ExplanationPanel into:
    - /underwriter/queue — clicking a queue item opens a side sheet with
      ExplanationPanel.
    - /underwriter/history — same side sheet on row click.

  - Add a "Download Adverse Action Notice" button in ExplanationPanel that
    calls GET /v1/adverse-actions/{notice_id} or generates one via the adverse
    action API.

Testing (vitest):
  - Unit test ShapWaterfallChart: renders correct number of bars from mock data.
  - Unit test: positive values get blue bars; negative values get red bars.
  - Unit test: maxFeatures=5 truncates to 5 bars even with 12 features in input.
  - Unit test: accessible aria-label present on each bar.
  - Unit test ExplanationPanel: shows loading skeleton before fetch resolves;
    shows chart after.

Deliverables:
  - components/charts/ShapWaterfallChart.tsx
  - components/ExplanationPanel.tsx
  - Updated /underwriter/queue/page.tsx and /underwriter/history/page.tsx
  - vitest tests
  - Risk note: if shap_values is empty or null (e.g., rule-based fallback
    decision), ExplanationPanel should show a "No model explanation available
    for this decision" message instead of a broken chart.
```

---

### Prompt 8 — Real Data Pipeline for Portfolio Concentration

```text
Task:
Replace the synthetic random data generator in _load_decisions_df() in
decision-api/src/main.py with a real query against the decision_audit_log table,
so that /v1/portfolio/concentration, /snapshot, /rebalancing, and /heatmap
return actual portfolio data.

Context:
_load_decisions_df() at line 2557 in decision-api/src/main.py currently generates
fake data using numpy random (rng.choice for states, NAICS codes, exposures).
The audit log table (decision_audit.db) stores real decisions with application_id,
decision, risk_score, pd_score, product_type, tenant_id, and logged_at. However,
naics_2d, state, and exposure (loan amount) are not currently stored in the audit
log row. The DecisionRequest schema (line ~650) does have borrower_state and
loan_amount fields available.

Requirements:
  Step 1 — Schema extension (audit/logger.py):
    - Add naics_2d TEXT, borrower_state TEXT, loan_amount REAL to the
      decision_audit_log table schema in audit/logger.py.
    - Add these fields to log_decision() — extract from the DecisionRequest
      payload and pass through. If not present, default to NULL.
    - Create db/migrations/007_audit_log_portfolio_fields.sql with the ALTER TABLE
      statements (SQLite: add columns, no data migration needed).

  Step 2 — Write real fields at decision time (decision-api/src/main.py):
    - In the POST /v1/decisions handler, pass naics_2d, borrower_state, and
      loan_amount to log_decision() so live decisions populate these fields.
    - Add naics_2d: Optional[str] = None to the DecisionRequest schema
      (SIC/NAICS 2-digit code for the borrower's industry). Document it.

  Step 3 — Replace _load_decisions_df() with real query:
    - Query decision_audit_log for the last `days` days, filtering by tenant_id.
    - Map columns: exposure = loan_amount (fallback to 25000.0 if NULL),
      naics_2d = naics_2d (fallback to "99" if NULL),
      state = borrower_state (fallback to "XX" if NULL),
      risk_grade = score band from risk_score (e.g., 80-100="A", 60-79="B",
      40-59="C", 20-39="D", 0-19="F").
    - If the query returns 0 rows (empty portfolio), return an empty
      ConcentrationReport with a is_empty=True flag instead of fake data.
    - Remove all numpy random generation from _load_decisions_df().
      Add a comment: "# Synthetic fallback removed 2026-06-12. Real data only."

  Step 4 — Update concentration_monitor.py fallback columns:
    - The ConcentrationMonitor.compute_report() requires naics_2d, state,
      exposure, risk_grade, product_type, account_id in the DataFrame.
    - Add a _validate_and_fill_defaults() method that fills NULL/missing
      dimension values with an "Unknown" sentinel rather than crashing.

Testing:
  - Unit test: log_decision() with naics_2d and borrower_state → row has these
    fields in DB.
  - Unit test: _load_decisions_df() with 10 seeded audit rows → DataFrame has
    correct shape and column types; no numpy random usage.
  - Unit test: _load_decisions_df() with 0 rows → empty DataFrame with
    correct columns (not crash).
  - Unit test: ConcentrationMonitor handles "Unknown" naics_2d sentinel
    (includes it in breakdown, does not crash).
  - Regression test: GET /v1/portfolio/concentration with seeded data returns
    a report with sector and state dimensions populated from real data.

Deliverables:
  - Updated audit/logger.py schema + log_decision() signature
  - db/migrations/007_audit_log_portfolio_fields.sql
  - Updated _load_decisions_df() (real query, no fake data)
  - Updated concentration_monitor.py _validate_and_fill_defaults()
  - Tests
  - Risk note: existing portfolio endpoints that used synthetic data will return
    empty or sparse results for tenants with no historical decisions. This is
    correct behavior — document it in the endpoint docstring.
```

---

### Prompt 9 — Risk Score Confidence Interval

```text
Task:
Add a calibrated confidence interval to the risk score returned by
POST /v1/decisions so that the response includes a lower/upper bound
alongside the point estimate.

Context:
POST /v1/decisions returns risk_score (int 0-100) and pd_score (float) but no
uncertainty estimate. For credit decisions, reporting a point estimate without
a confidence band understates model uncertainty and is a model governance gap
(SR 11-7 requires uncertainty quantification for IRB models).

The CC LightGBM model (cc_pd_model_v1.pkl) supports predict_proba() which
returns raw probabilities. Platt scaling calibration is already applied
(cc_pd_calibration.png exists, calibration was run during training).

Requirements:
  - In models/credit_risk/predict.py, add a predict_pd_with_interval() function:
    - Use bootstrap confidence interval: run predict_proba() with LightGBM's
      built-in num_iteration variants OR use a stored set of 100 bootstrap
      model replicas.
    - Pragmatic approach (preferred for now): use the LightGBM model's leaf
      prediction variance as a proxy for uncertainty. Specifically:
        * Get predict_proba() → point estimate pd_point.
        * Estimate sigma as: sigma = sqrt(pd_point * (1 - pd_point) / n_trees)
          where n_trees is the number of boosting rounds.
        * 90% CI: lower = max(0, pd_point - 1.645 * sigma),
                  upper = min(1, pd_point + 1.645 * sigma)
        * Convert to risk score space: score_lower = 100 * (1 - upper),
          score_upper = 100 * (1 - lower).
    - Returns: PdPrediction(pd_score=float, pd_lower=float, pd_upper=float,
               risk_score=int, risk_score_lower=int, risk_score_upper=int,
               ci_level=0.90)

  - Update DecisionResponse schema in decision-api/src/main.py to include:
      pd_lower: float
      pd_upper: float
      risk_score_lower: int
      risk_score_upper: int
      ci_level: float  # always 0.90 for now
    Keep existing pd_score and risk_score fields unchanged (backward compatible).

  - Update GET /v1/decisions/{id}/explanation to include the interval in its
    response (fetch from audit log or recompute).

  - Apply the same logic to the SMB model (Prompt 4) — predict_pd_with_interval()
    must work for both product types.

Testing:
  - Unit test: predict_pd_with_interval() returns pd_lower <= pd_score <= pd_upper.
  - Unit test: pd_lower >= 0.0, pd_upper <= 1.0.
  - Unit test: risk_score_lower <= risk_score <= risk_score_upper.
  - Unit test: POST /v1/decisions response body includes all 5 new fields.
  - Regression test: existing tests that check pd_score and risk_score still pass
    (new fields are additive).

Deliverables:
  - Updated predict.py with predict_pd_with_interval()
  - Updated DecisionResponse schema
  - Tests
  - Risk note: the sigma approximation is a heuristic, not a true bootstrap CI.
    Document this limitation in the model card and in the API reference. A proper
    bootstrap CI requires storing 50-100 submodels which increases artifact size
    and inference latency — defer to roadmap.
```

---

### Prompt 10 — Credit Analyst Agent

```text
Task:
Implement agents/credit_analyst_agent.py as a new BaseAgent subclass that performs
qualitative per-account credit assessment and generates a structured risk narrative.

Context:
docs/AICS_GAP_IMPLEMENTATION_PLAN.md Sprint 1 defines the full design for this
agent. agents/base.py defines the BaseAgent interface. The orchestration pipeline
in orchestration/pipeline.py wires agents together — wire CreditAnalystAgent
after ExplainabilityAgent.

Requirements:

1. agents/credit_analyst_agent.py — Three sub-components:

  1a. QualitativeAssessmentEngine:
    Input: FeatureVector (from FeatureEngineeringAgent) + ModelScores (from
    RiskModelingAgent)
    Logic:
      - creditworthiness_score (1–5): derived from employment_status + emp_years
        + income stability (inflow_volatility_12m feature if available).
      - collateral_coverage: collateral_value / loan_amount ratio.
        < 0.8 = "Insufficient", 0.8-1.2 = "Marginal", > 1.2 = "Adequate".
        For unsecured loans: "N/A".
      - industry_risk_tier: Look up borrower's naics_2d in a seeded static
        dict (data/industry_risk_tiers.json) → Low | Medium | High | Elevated.
        Default "Medium" if naics_2d is absent.
      - red_flags: List of RedFlag(code, description, severity, feature_value,
        threshold). Codes to detect:
          RF-01: fraud_flag == "review"
          RF-02: num_missed_pmts_12m > 2
          RF-03: recent_bankruptcy == True
          RF-04: debt_to_income > 0.55
          RF-05: thin_file == True AND alt_data_score < 40
    Output: QualitativeAssessment dataclass

  1b. RiskNarrativeGenerator (extend explainability/nlg_summarizer.py):
    Input: QualitativeAssessment + ModelScores + SHAP values
    Output: RiskNarrativeDocument with sections:
      - borrower_profile (income, employment, credit history summary)
      - financial_strength (DTI, cash flow adequacy, income stability)
      - collateral_analysis (only for secured loans)
      - industry_macro (industry tier + 1-sentence macro context)
      - red_flags (only if red_flags list is non-empty)
      - credit_opinion (Acceptable | Marginal | Unacceptable + one-sentence rationale)
    Implementation: Jinja2 templates per section. Data-grounded only — no LLM
    calls. Every sentence references a specific feature value.

  1c. RedFlagReport:
    Standalone JSON artifact: list of flagged conditions with severity (P1/P2/P3),
    supporting evidence, and recommended_action ("Manual Review" | "Decline" |
    "Request Documentation").

2. Data file — create data/industry_risk_tiers.json:
   Seed with NAICS 2-digit codes and risk tier assignments. Include at minimum:
   11 (Agriculture) = Medium, 22 (Utilities) = Low, 23 (Construction) = High,
   31-33 (Manufacturing) = Medium, 44-45 (Retail) = Medium, 48-49 (Transport) = Medium,
   51 (Information) = Low, 52 (Finance/Insurance) = Low, 53 (Real Estate) = Medium,
   54 (Professional Services) = Low, 56 (Admin/Support) = Medium,
   61 (Education) = Low, 62 (Healthcare) = Low, 71 (Arts/Entertainment) = High,
   72 (Accommodation/Food) = High, 81 (Other Services) = Medium, 99 (Unknown) = Medium.

3. orchestration/pipeline.py wiring:
   - Add CreditAnalystAgent to the pipeline DAG after ExplainabilityAgent.
   - Pass feature_vector, model_scores, shap_values to run().
   - Add credit_analyst_output to the pipeline result object.

4. decision-api/src/main.py:
   - Include credit_opinion and red_flags in the DecisionResponse (as optional
     fields — null if CreditAnalystAgent is not in the pipeline).
   - Add the RiskNarrativeDocument to GET /v1/decisions/{id}/explanation response.

Testing:
  - Unit test QualitativeAssessmentEngine: fraud_flag="review" → RF-01 in flags.
  - Unit test: debt_to_income=0.60 → RF-04 in flags.
  - Unit test: secured loan with collateral_value=80000, loan_amount=100000
    → collateral_coverage="Insufficient".
  - Unit test: naics_2d="72" → industry_risk_tier="High".
  - Unit test: missing naics_2d → defaults to "Medium" without crash.
  - Unit test RiskNarrativeGenerator: all sections present in output when full
    input provided; collateral_analysis absent for unsecured loan.
  - Unit test: narrative contains no hallucinated values — every number in the
    text appears in the input FeatureVector.
  - Integration test: POST /v1/decisions with full payload → response includes
    credit_opinion field.

Deliverables:
  - agents/credit_analyst_agent.py (3 sub-components)
  - data/industry_risk_tiers.json
  - Updated orchestration/pipeline.py
  - Updated DecisionResponse schema (additive)
  - Updated /v1/decisions/{id}/explanation
  - Jinja2 narrative templates in explainability/templates/
  - Tests
  - Risk note: credit_opinion is non-binding. Document clearly that it is an
    AI-generated assessment and that final underwriting decisions require human
    review for flagged applications.
```

---

## P2 — Medium Priority (Weeks 6–12)

---

### Prompt 11 — Conditional Approval Decision State

```text
Task:
Add CONDITIONAL_APPROVE as a distinct decision outcome to the decision engine,
with an attached conditions list, so that borderline approvals with attached
requirements are returned as a first-class state instead of being routed to REFER.

Context:
decision_engine/engine.py produces APPROVE | DECLINE | REFER. There is no
CONDITIONAL_APPROVE state. Lenders frequently want to approve subject to
conditions (income verification, reduced limit, co-borrower requirement).
Currently these cases either go to REFER (requiring a human to note the
conditions manually) or are returned as APPROVE without the condition context.

Requirements:
  - In decision_engine/engine.py:
    - Add DecisionOutcome.CONDITIONAL_APPROVE = "conditional_approve" to the enum.
    - Add ConditionalApproval dataclass:
        conditions: List[Condition]
        condition_deadline_days: int = 30

    - Condition dataclass:
        code: str            # e.g., "INCOME_VERIFY", "REDUCED_LIMIT", "COBORROWER"
        description: str
        required_by_days: int

    - Update make_decision() to return CONDITIONAL_APPROVE when:
        * PD is in the borderline band (configurable: default 0.05–0.12).
        * AND at least one of: DTI > 0.45, thin_file=True, employment_status
          != "employed", collateral_ltv > 0.85.
        * Generate appropriate Condition codes automatically based on which
          triggers fired.

  - Update DecisionResponse in decision-api/src/main.py:
    - Add conditional_approval: Optional[ConditionalApproval] = None.
    - Populated only when decision == "conditional_approve".
    - Existing APPROVE / DECLINE / REFER responses are unaffected.

  - Update the adverse action module (compliance/adverse_action.py):
    - CONDITIONAL_APPROVE does NOT generate an adverse action notice.
    - Add a conditional_approval_notice generator that produces a Reg B-compliant
      conditional commitment letter (template in compliance/templates/).

  - Update the underwriter queue (decision-api/src/rules/ or main.py):
    - CONDITIONAL_APPROVE cases appear in the review queue with a "Conditions
      Pending" badge, NOT in the standard referral queue.

Testing:
  - Unit test: PD=0.08, DTI=0.48 → CONDITIONAL_APPROVE with "INCOME_VERIFY"
    condition.
  - Unit test: PD=0.04 → APPROVE (not conditional, below borderline band).
  - Unit test: PD=0.15 → DECLINE (above borderline band).
  - Unit test: conditional_approval field present in DecisionResponse when
    outcome is CONDITIONAL_APPROVE.
  - Unit test: adverse action NOT generated for CONDITIONAL_APPROVE.
  - Regression test: existing APPROVE and DECLINE unit tests unchanged.

Deliverables:
  - Updated engine.py (new outcome + dataclasses)
  - Updated DecisionResponse schema
  - Updated adverse_action.py
  - Conditional commitment letter template
  - Tests
```

---

### Prompt 12 — Alternative Structure Recommendations on Decline

```text
Task:
When a loan application is declined, compute and return alternative deal
structures that would have resulted in an approval, surfacing them in the
DecisionResponse as an alternatives list.

Context:
decision_engine/alternative_structures.py exists but is not wired into the
decision pipeline. Currently, DECLINE responses contain reason codes but no
"what would it take to approve" guidance.

Requirements:
  - In decision_engine/alternative_structures.py:
    - Implement compute_alternatives(request, decision_result, policy_config)
      that returns List[AlternativeStructure]:

      AlternativeStructure:
        structure_type: str  # "reduced_amount", "higher_down_payment",
                             # "co_borrower", "income_documentation",
                             # "reduced_term"
        description: str     # human-readable: "Approval likely at $18,000
                               (vs. requested $25,000)"
        adjusted_pd: float   # estimated PD under the alternative
        adjusted_dti: float  # estimated DTI under the alternative
        feasibility: str     # "High" | "Medium" | "Low"

    - Logic for each alternative:
        reduced_amount: Binary search for the largest loan_amount at which
          PD < approval_threshold AND DTI < dti_limit. Step = 5% reductions.
          Max 10 steps. Return if found within 40% of requested amount.
        higher_down_payment: For secured loans — compute the collateral_value
          needed to bring LTV below 0.80. Return the dollar uplift required.
        income_documentation: If employment_status != "employed" or
          income_verification_score < 60 — flag that verified income docs
          could improve the decision.
        reduced_term: For DTI-constrained declines — show DTI impact of
          a shorter term (higher monthly payment, faster payoff).

  - Wire into POST /v1/decisions in decision-api/src/main.py:
    - Call compute_alternatives() only on DECLINE outcomes.
    - Add alternatives: List[AlternativeStructure] = [] to DecisionResponse.
    - Limit to 3 alternatives (highest feasibility first).

  - Include alternatives in GET /v1/decisions/{id}/explanation.

  - Surface alternatives in the applicant portal (ui/applicant-portal/app/decision/):
    - If decision == "decline" and alternatives is non-empty, show an
      "Explore Options" section with the alternative structures in plain language.

Testing:
  - Unit test: DECLINE with DTI=0.52, loan_amount=25000 → reduced_amount
    alternative found at ≤ $20,000.
  - Unit test: APPROVE → alternatives list is empty.
  - Unit test: DECLINE with no feasible alternatives within 40% reduction →
    empty alternatives list (not an error).
  - Unit test: alternatives sorted by feasibility (High before Medium before Low).
  - Integration test: POST /v1/decisions DECLINE → response includes alternatives.

Deliverables:
  - Updated alternative_structures.py
  - Updated DecisionResponse
  - Updated applicant portal /decision page
  - Tests
```

---

### Prompt 13 — LGD Trained Model

```text
Task:
Replace the config-constant LGD rate in risk_models/ecl_engine.py with a trained
LGD regression model, registered in MLflow and integrated into the ECL calculation.

Context:
risk_models/ecl_engine.py uses a hardcoded lgd_rate config constant for all
Expected Credit Loss (ECL = PD × LGD × EAD) calculations. models/credit_risk/lgd_model.py
has an LGDModel class with a fit() method at line 150 and a predict() method —
the model exists architecturally but has never been trained or registered.
models/credit_risk/lgd_model_card.json exists. train_ead_model.py serves as
a structural reference for the training pipeline pattern.

Requirements:
  Step 1 — Training script (models/credit_risk/train_lgd_model.py):
    - Load synthetic recovery data (generate if real data unavailable):
        Fields: loan_amount, recovery_amount, collateral_type, collateral_ltv,
        time_in_default_months, product_type, borrower_state.
        LGD = 1 - (recovery_amount / loan_amount), clipped to [0.0, 1.0].
    - Feature engineering: collateral_coverage_ratio, secured flag,
      log_loan_amount, product_type_encoded.
    - Train LGDModel (LightGBM regressor or XGBoost with monotonicity constraints:
      LGD must be non-decreasing as collateral_ltv increases).
    - Calibration: enforce LGD ∈ [0.05, 0.95] (physical floor/ceiling).
    - MLflow logging: register as "lgd_v1" with RMSE, MAE metrics.
    - Save artifact: models/credit_risk/lgd_model_v1.pkl
    - Update lgd_model_card.json with training metadata.

  Step 2 — Model loader:
    - Add "lgd_v1" to models/model_loader.py model registry.
    - Add load_lgd_model() following the existing cache pattern.

  Step 3 — ECL engine integration (risk_models/ecl_engine.py):
    - Add predict_lgd(features: dict, product_type: str) function that loads
      lgd_model_v1.pkl and returns a float LGD estimate.
    - Update calculate_ecl() to call predict_lgd() instead of reading lgd_rate
      from config. Make it configurable: use the model if available, fall back
      to config constant if the model artifact is absent.
    - Keep the config-constant lgd_rate as the fallback — do not break existing
      behavior when the model is not present.

  Step 4 — POST /v1/stress-test/run:
    - Stress test scenarios should now use the LGD model per loan rather than
      a portfolio-level constant. Pass collateral metadata through the scenario
      object if available.

Testing:
  - Unit test: train_lgd_model.py runs to completion on 500 synthetic rows
    without error. RMSE < 0.25 (sanity check).
  - Unit test: predict_lgd() returns float in [0.05, 0.95].
  - Unit test: secured loan with low LTV → lower LGD than unsecured loan
    (monotonicity test).
  - Unit test: ECL = PD × predict_lgd() × EAD for a sample application.
  - Unit test: if lgd_model_v1.pkl absent → calculate_ecl() falls back to
    config constant lgd_rate without crash.
  - Regression test: existing ECL tests still pass (fallback path unchanged).

Deliverables:
  - models/credit_risk/train_lgd_model.py
  - models/credit_risk/lgd_model_v1.pkl (trained artifact)
  - Updated lgd_model_card.json
  - Updated model_loader.py
  - Updated risk_models/ecl_engine.py
  - Tests
```

---

### Prompt 14 — Applicant Portal Mobile Responsiveness Validation

```text
Task:
Add Playwright end-to-end tests that validate the applicant portal's responsive
layout at three breakpoints and verify WCAG AA color contrast for key UI elements.

Context:
ui/applicant-portal/ uses Tailwind CSS (likely responsive), but no automated
tests verify the responsive layout or accessibility. The DESIGN.md palette defines
text-muted as #6b7280 on white — this is exactly 4.5:1 contrast ratio (WCAG AA
minimum). Any deviation in practice needs to be caught. An investor-facing
borrower portal that fails basic accessibility is a compliance risk under ADA
and CFPB fair access requirements.

Requirements:
  - Create ui/applicant-portal/tests/e2e/responsive.spec.ts with Playwright tests:

    Test 1 — Mobile (375px iPhone SE):
      - Navigate to / (landing page).
      - Assert the header logo is visible.
      - Assert the primary CTA button ("Apply Now" or equivalent) is visible and
        not clipped.
      - Assert no horizontal scroll (document.body.scrollWidth == window.innerWidth).
      - Screenshot to tests/e2e/screenshots/mobile_home.png.

    Test 2 — Tablet (768px iPad):
      - Navigate to /apply.
      - Assert the multi-step form renders all visible fields without overflow.
      - Screenshot to tests/e2e/screenshots/tablet_apply.png.

    Test 3 — Desktop (1280px):
      - Navigate to /apply.
      - Complete the form with synthetic applicant data (name, income, loan amount).
      - Assert the submit button is enabled.
      - Screenshot to tests/e2e/screenshots/desktop_apply.png.

    Test 4 — Contrast check (desktop):
      - For each of these selectors, compute the computed color and background-color
        via page.evaluate() and assert contrast ratio >= 4.5 (WCAG AA):
          * "h1" (primary heading — should be --text-primary #0f172a on white)
          * ".cta-button" or the primary submit button
          * ".text-muted" or helper text elements

    Test 5 — Adverse action page:
      - Navigate to /decision with a mock "declined" state param.
      - Assert the decline notice section is visible.
      - Assert adverse action reason text is present.
      - Assert at minimum one "Contact Us" or appeal link is visible (Reg B
        requirement: notice must include a contact for reconsideration).

  - Add playwright.config.ts to ui/applicant-portal/ if not already present.
  - Add "test:e2e" script to package.json: "playwright test tests/e2e/".
  - Screenshots must be committed to the repo for before/after comparison.

Testing:
  - These tests ARE the deliverable. They should all pass on the current portal.
  - If any test fails, fix the underlying layout/accessibility issue and include
    the fix in this PR.
  - Document any failing contrast check in a //TODO comment rather than silently
    ignoring it.

Deliverables:
  - ui/applicant-portal/tests/e2e/responsive.spec.ts
  - ui/applicant-portal/playwright.config.ts
  - Updated package.json scripts
  - Screenshots directory with initial baseline captures
  - Any layout/contrast fixes discovered during testing
  - Risk note: Playwright tests require a running dev server. Add a CI step
    (GitHub Actions) that starts the dev server before running e2e tests.
```

---

## Execution Checklist

Run prompts in this order. Each prompt's tests must pass before moving to the next.

| # | Prompt | Priority | Estimated Days | Blocks |
|---|---|---|---|---|
| 1 | AI Agent Chain Verification | P0 | 2 | Exam packet AI appendix |
| 2 | Per-Tenant Confidence Threshold | P0 | 2 | Investor demo integrity |
| 3 | Artifact Re-Execution Endpoint | P0 | 3 | Core differentiator claim |
| 4 | Run + Wire SMB PD Model | P0 | 3 | Primary ICP pilot readiness |
| 5 | Self-Service Tenant Provisioning | P0 | 5 | 30-day onboarding claim |
| 6 | Performance Benchmark | P1 | 2 | Technical diligence |
| 7 | SHAP Waterfall Chart | P1 | 3 | Underwriter demo quality |
| 8 | Real Portfolio Concentration Data | P1 | 3 | M2 module claim |
| 9 | Risk Score Confidence Interval | P1 | 2 | SR 11-7 governance |
| 10 | Credit Analyst Agent | P1 | 8 | Autonomous underwriting claim |
| 11 | Conditional Approval State | P2 | 3 | Underwriting completeness |
| 12 | Alternative Structure Recommendations | P2 | 4 | Borrower portal value |
| 13 | LGD Trained Model | P2 | 4 | CECL accuracy |
| 14 | Mobile Responsiveness Validation | P2 | 2 | ADA / CFPB compliance |
| | **Total** | | **~46 days** | |

**90-day target:** Complete Prompts 1–9 (all P0 + high P1) within 6 weeks.
Complete Prompts 10–14 (Credit Analyst Agent + P2) in weeks 7–12.

---

*Generated from audit/HELIX_DECISIONS_PLATFORM_AUDIT_2026.md — June 12, 2026*
