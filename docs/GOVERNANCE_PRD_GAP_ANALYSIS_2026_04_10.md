# Gap Analysis: Governance-Native Credit Decisioning Audit Platform
**PRD Reference**: `docs/Governance_native_LOS_PRD.md`
**Analysis Date**: 2026-04-10
**Prior Analysis**: `docs/GOVERNANCE_PRD_GAP_ANALYSIS_2026_04_09.md`
**Analyst**: GitHub Copilot
**Platform**: `credit-risk-platform`
**Status**: 13 open gaps (3 closed since last audit); 5 new capabilities documented

---

## Executive Summary

A re-audit against the [prior gap analysis (2026-04-09)](GOVERNANCE_PRD_GAP_ANALYSIS_2026_04_09.md) surfaces meaningful progress:

| Change | Detail |
|---|---|
| **GAP-10 CLOSED** | `analytics_api` now exposes `GET /v1/analytics/vintage-curves`, `GET /v1/analytics/roll-rates`, `GET /v1/analytics/approval-profit` (BQ + SQLite backends, TTL cache, JWT auth, tenant scoping) |
| **GAP-09 PARTIAL → P2 stays open** | `model_validation_log` and `governance_approval_log` tables + persistence helpers added to `audit/logger.py`; state machine and RBAC enforcement still absent |
| **GAP-07 PARTIAL → P2 stays open** | NLG narratives are now generated per-decision in the Decision API (G06); `exam_packet_builder.py` still does not pull them into `ExamPacketComponent` |
| **5 major new capabilities** | Webhooks (G16-B), Config Registry four-eyes (G11-B), Borrower Portal (G13-B), CSV Batch Underwriting (G14-B), Monte Carlo Stress Test (G15-B) |

Thirteen of the original sixteen gaps remain open (3 P1 critical, 7 P2 high, 3 P3 medium).

| Criticality | Count | Change vs 04-09 |
|---|---|---|
| P1 — Critical | 3 | ↔ unchanged |
| P2 — High | 7 | ↔ unchanged (two P2s partially progressed) |
| P3 — Medium | 3 | ↓ 1 (GAP-10 closed) |
| P4 — Low | 2 | ↔ unchanged |
| **Total open** | **15** | ↓ 1 |

> **Note**: GAP-10 is closed; GAP-07 and GAP-09 are re-classified as **Partial** with updated current-state descriptions.

---

## Methodology

Each previous gap was re-verified by:
1. Full `list_dir` on `audit/`, `compliance/`, `decision_engine/`, `monitoring/`, `explainability/`, `analytics_api/`, `ui/analytics-dashboard/app/compliance/`
2. `grep_search` and `read_file` across all changed artefacts
3. Cross-referencing every new symbol, table DDL, and API endpoint against PRD sections §3.1–3.5, §4–§13

---

## Module-Level Coverage Matrix (Updated)

| PRD Module | Section | Status | Notes |
|---|---|---|---|
| Decisioning Audit Engine | §3.1 | ⚠️ Partial | Hash chain ✅; override detection ❌; consistency score ❌ |
| Governance Document Generator | §3.2 | ⚠️ Partial | MDD generation ✅; exam packet stubs ❌; UI action ❌ |
| Fair Lending Monitor | §3.3 | ⚠️ Partial | DIR, chi-sq, BISG proxy, alerts ✅; simulation ❌; history ❌ |
| Model Risk Dashboard | §3.4 | ⚠️ Partial | KPIs ✅; validation log tables NEW ✅; live data feed UI ❌ |
| Portfolio Monitoring Engine | §3.5 | ✅ Implemented | Delinquency ✅; vintage-curves API ✅ (analytics_api) |
| Command Center UX | §4, §11 | ⚠️ Partial | Role-based views ✅; unified command center ❌; "Generate" button ❌ |
| Compliance Rules Engine | §6 | ⚠️ Partial | Gate + adverse action ✅; prohibited variables ❌; override enforcement ❌ |
| Data Model & Audit Package | §5, §8 | ⚠️ Partial | Core entities ✅; validation/governance logs NEW ✅; data lineage ❌; policy snapshots ❌ |
| Integration | §9 | ⚠️ Partial | Decision-API + webhooks ✅; LOS/bureau ❌; regulator portal ❌ |
| Security & Governance | §12 | ✅ Implemented | RBAC ✅; hash-chain ✅; PII masking ✅; four-eyes config ✅ |
| MVP Scope (Phase 1) | §13 | ⚠️ Partial | Audit logs ✅; rules engine ✅; audit package stubs ⚠️; model monitoring ✅ |

---

## Gap Inventory (Current State)

---

### P1 — Critical (MVP Blocking / Regulatory Risk)

---

#### GAP-01: Exam Packet Builder — Non-Adverse-Action Components Still Stubs
**PRD Reference**: §3.2 Governance Document Generator, §5 Audit Package Structure, §13 MVP Scope
**Severity**: P1 — Critical
**Status vs 04-09**: ↔ No change

**PRD Requirement**:
> "One-click 'Generate Audit Package'. Pre-mapped regulatory templates. Outputs: credit policy documents, change logs, committee approvals, model documentation (MDD, validation summary), decision evidence samples, fair lending analysis, data lineage."

**Current State**:
- `compliance/exam_packet_builder.py` (282 lines) — `build_exam_packet()` iterates the requested components; only `"adverse_actions"` has a real builder. Every other component name (`model_documentation`, `policy_snapshots`, `decision_samples`, `fair_lending_analysis`, `data_lineage`, `committee_approvals`) falls into an `else` branch that returns `ExamPacketComponent(status="stub", data=None)`.
- `format="pdf_zip"` is accepted as a CLI argument but no PDF rendering other than `adverse_action_pdf.py` is wired.
- No UI trigger exists; `ui/analytics-dashboard/app/compliance/` has no command-center or "Generate Audit Package" button.
- No `CommitteeApproval` entity exists in any data model or API.
- NLG narratives are now generated per-decision in `decision-api` (G06) — **these could be wired to `decision_samples` but are not yet**.

**Impact**:
- PRD success criterion "reduce audit prep time by 70%+" remains unmet.
- OCC/CFPB readiness posture unchanged.

**Remediation** (unchanged from 04-09):
1. Wire each stub component to existing live sources: `generate_model_doc.py` → `model_documentation`; `policy_version_store.py` → `policy_snapshots`; `audit/logger.py` → `decision_samples`; `monitoring/fair_lending.py` → `fair_lending_analysis`.
2. Pull NLG narratives (now available from `nlg_summarizer.generate_decision_summary`) into `decision_samples` summaries.
3. Add PDF export for the full package (extend `adverse_action_pdf.py`).
4. Add `CommitteeApproval` model + CRUD endpoint.
5. Expose `POST /api/v1/audit/generate-package` and wire "Generate Audit Package" button in the compliance UI.

---

#### GAP-02: Override Detection Engine Missing
**PRD Reference**: §3.1 Decisioning Audit Engine, §6.2 Example Rules
**Severity**: P1 — Critical
**Status vs 04-09**: ↔ No change (governance_approval_log is for model lifecycle, not policy-parameter overrides)

**PRD Requirement**:
> "Every override must include a justification and approval. Override rate is a key audit metric."

**Current State**:
- `decision_engine/engine.py` — `policy_overrides: Optional[Dict[str, Any]]` parameter is passed directly into the decision logic (`overrides.get("pd_threshold_low", PD_THRESHOLD_LOW)`) with no justification, approver, or audit trail.
- `audit/logger.py` — primary `audit_log` DDL has no `override_flag`, `override_justification`, or `override_approver` columns.
- `audit/logger.py` — a new `governance_approval_log` table (§21) was added with an `action` column that accepts `GOVERNANCE_OVERRIDE`; **this covers model-lifecycle overrides only**, not per-decision policy-parameter overrides.
- `compliance/engine.py` — compliance gate has no override detection path.
- `compliance/rbac.py` — four-eyes enforcement exists for Config Registry approval (G11-B) but is **not coupled** to `policy_overrides` at the decision engine level.

**Impact**: Override rate metric (PRD §7.1) cannot be accurately computed; SR 11-7 / OCC 2021-25 per-decision override logging is unmet.

**Remediation** (unchanged):
1. Add `PolicyOverrideRecord` dataclass and a `policy_overrides_log` table (append-only, hash-chained).
2. Reject any `policy_overrides` dict in `engine.py` that lacks a `justification` + `approved_by` field.
3. Surface override rate on the compliance dashboard.

---

#### GAP-03: No Data Lineage Module
**PRD Reference**: §5.5 Data & System Documentation
**Severity**: P1 — Critical
**Status vs 04-09**: ↔ No change

**PRD Requirement**:
> "Audit package must include: data lineage, architecture diagrams, and a data dictionary."

**Current State**:
- No `data_lineage/` directory in the workspace.
- `feature_pipeline/` extracts features; `ingestion-api/` ingests data — neither records provenance metadata to a queryable store.
- `compliance/exam_packet_builder.py` `data_lineage` slot returns `status="stub"`.
- `compliance/generate_model_doc.py` has a `training_data_description` free-text field backed by manual strings and MLflow tags — not a live lineage graph.

**Remediation** (unchanged):
1. Create `data_lineage/lineage_tracker.py` with source → transform → feature → model DAG persisted to the audit DB.
2. Auto-populate from `feature_pipeline/` instrumentation hooks.
3. Export `DataLineageReport` from `exam_packet_builder.py`.

---

### P2 — High (Go-Live Readiness)

---

#### GAP-04: Decision Consistency Score Not Implemented
**PRD Reference**: §3.1 Decisioning Audit Engine — "Decision consistency score", §7.1
**Severity**: P2 — High
**Status vs 04-09**: ↔ No change

**Current State**: No `audit/consistency_scorer.py` exists. `explainability/counterfactual.py` computes counterfactual deltas but not a reproducibility/consistency score against a re-run.

**Remediation**: Implement `audit/consistency_scorer.py` — deterministic replay of a stored decision and comparison of the output delta to the original.

---

#### GAP-05: Model Governance UI Uses Mock Data
**PRD Reference**: §3.4 Model Risk Dashboard
**Severity**: P2 — High
**Status vs 04-09**: ⚠️ Backend improved; UI unchanged

**Current State**:
- `ui/analytics-dashboard/app/compliance/model-governance/page.tsx` — `MOCK_MODELS` TypeScript array is still used; `promoteModel()` calls `setTimeout` stub instead of a real API.
- **NEW (backend)**: `audit/logger.py` now has `governance_approval_log` (action: REGISTER / PROMOTE_PRODUCTION / GOVERNANCE_OVERRIDE / REVIEW_DUE) and `model_validation_log` tables, with `log_governance_action()` and `log_model_validation()` async helpers. These provide the persistence layer for live data.
- No `GET /api/v1/models` endpoint exists; no `POST /api/v1/models/{id}/promote` endpoint exists.

**Remediation** (updated steps 1–2):
1. Add `GET /api/v1/models` → query MLflow `search_model_versions()` + join `governance_approval_log` for lifecycle status.
2. Add `POST /api/v1/models/{model_id}/promote` → call `mlflow.transition_model_version_stage()` + `log_governance_action(action="PROMOTE_PRODUCTION")` with RBAC four-eyes enforcement.
3. Replace `MOCK_MODELS` and `setTimeout` stubs with `useSWR` data-fetching hooks.

---

#### GAP-06: Command Center Homepage Does Not Exist
**PRD Reference**: §4 Core Workflows, §11 UX Requirements
**Severity**: P2 — High
**Status vs 04-09**: ↔ No change

**Current State**:
- `ui/analytics-dashboard/app/page.tsx` still routes `compliance` role to `/compliance/fair-lending` (not a unified command center).
- No `ui/analytics-dashboard/app/compliance/command-center/page.tsx` exists.
- `compliance/health_score.py` exposes `compute_health_score()` — but no REST endpoint wraps it (`GET /api/v1/compliance/health` is absent from all service routers).

**Remediation** (unchanged):
1. Add `GET /api/v1/compliance/health` endpoint wrapping `compute_health_score()`.
2. Create `ui/analytics-dashboard/app/compliance/command-center/page.tsx` with Audit Readiness Score KPI grid, Active Compliance Flags, Model Health, Fair Lending Alerts, and "Generate Audit Package" / "View Decision Trace" / "Run Fair Lending Analysis" action launchers.
3. Update `ROLE_HOME` to route `compliance` → `/compliance/command-center`.

---

#### GAP-07: NLG Narratives Not Integrated into Audit Package
**PRD Reference**: §10 Automation Opportunities — "Auto-generation of audit narratives"
**Severity**: P2 — High
**Status vs 04-09**: ⚠️ Partially closed at decision level; exam packet still open

**Current State**:
- **NEW (decision pipeline)**: `decision-api/src/main.py` — G06 block calls `generate_decision_summary()` after every underwriting decision and populates `DecisionResponse.explanation_narrative`, `applicant_narrative`, `adverse_action_body`, and `adverse_action_reasons`. NLG narratives are now surfaced in every API response.
- `compliance/exam_packet_builder.py` — the `decision_samples` and other `ExamPacketComponent` slots still return `status="stub"` with no NLG narrative content.
- No audit narrative template system exists in `exam_packet_builder.py`.

**Remaining Work**:
Wire `nlg_summarizer.generate_decision_summary()` into `ExamPacketComponent` builders inside `exam_packet_builder.py` — specifically to populate the `decision_samples` narrative section for the exam packet.

---

#### GAP-08: Prohibited Variables Registry Missing
**PRD Reference**: §6.2 Example Rules — "No prohibited variables used in decisioning"
**Severity**: P2 — High
**Status vs 04-09**: ↔ No change

**Current State**:
- `compliance/engine.py` — checks MLA, state usury caps, fraud thresholds; no protected-class or prohibited-variable registry.
- `decision_engine/engine.py` — `LoanApplicationRequest` validates field formats but does not check feature names against a prohibited-variable list.
- No `compliance/prohibited_variables.py` exists anywhere in the codebase.

**Remediation** (unchanged):
1. Create `compliance/prohibited_variables.py` with `PROHIBITED_VARIABLES` set and `PROXY_VARIABLE_MAP`.
2. Add a pre-decision gate in `engine.py` raising `ProhibitedVariableViolation` on match.
3. Log violations to `compliance_events` and surface in the compliance dashboard.

---

#### GAP-09: Independent Model Validation Workflow Not Fully Formalized
**PRD Reference**: §3.4 Model Risk Dashboard, §6.2
**Severity**: P2 — High
**Status vs 04-09**: ⚠️ Backend data model added; state machine and enforcement still absent

**Current State**:
- **NEW**: `audit/logger.py` now has:
  - `model_validation_log` table (columns: `validation_id`, `model_name`, `model_version`, `validator_email`, `validation_date`, `validation_type` [INITIAL/ANNUAL/TRIGGERED], `outcome` [PASS/PASS_WITH_CONDITIONS/FAIL], `conditions`, `findings`, `test_scripts_ref`, `approved_for_prod`). Async helper `log_model_validation()` persists records.
  - `governance_approval_log` table with `action` values including `VALIDATION_PASS`, `VALIDATION_FAIL`, `GOVERNANCE_OVERRIDE`, `REVIEW_DUE`. Async helper `log_governance_action()`.
- **Still missing**: No state machine (`PENDING_VALIDATION → UNDER_REVIEW → VALIDATED → APPROVED`). No enforcement that `validator_email != submitter`. No nightly job that flags models with `validation_date > SLA_DAYS`. No compliance engine rule using `model_validation_log`.

**Remaining Work**:
1. Enforce `validator_email != performed_by` in `log_model_validation()` (or in the API layer) using `compliance/rbac.py` four-eyes check.
2. Add a nightly job (or `REVIEW_DUE` log action trigger) checking `validation_date` staleness against a configurable SLA (default 12 months) and creating a `ComplianceEvent`.
3. Add `GET /api/v1/models/{id}/validations` endpoint surfacing `model_validation_log` records.
4. Wire to model governance UI.

---

#### GAP-10: ~~Vintage Curves Not Implemented~~ — **CLOSED**
**PRD Reference**: §3.5 Portfolio Monitoring Engine
**Severity**: P2 → **Resolved**
**Status vs 04-09**: ✅ CLOSED

**Current State (resolved)**:
- `analytics_api/src/main.py` — `GET /v1/analytics/vintage-curves` endpoint is fully implemented (lines 322–365). Returns `List[VintageCurveRow]` with `origination_month`, `months_on_book`, `cohort_size`, `dpd_30_rate`, `dpd_60_rate`, `dpd_90_rate`, `charge_off_rate`, and `loss_rate` fields.
- `analytics_api/src/queries/cohort_vintage_curves.sql` — SQL template compatible with both BigQuery (`@dataset` prefix) and SQLite (dev/test fallback).
- Supports JWT auth, tenant scoping, `months_back` parameter, cursor pagination, and in-process TTL cache.
- `GET /v1/analytics/roll-rates` and `GET /v1/analytics/approval-profit` are also implemented in the same service.

> **Note**: `cc_portfolio_monitor.py` still lacks a `monitor_vintage_curves()` method but the analytics API fulfils the PRD requirement for vintage curve reporting.

---

### P3 — Medium (Phase 2 Roadmap)

---

#### GAP-11: Scenario Simulation for Fair Lending Not Implemented
**PRD Reference**: §3.3 Fair Lending Monitor — "Scenario simulation", Phase 2
**Severity**: P3 — Medium
**Status vs 04-09**: ↔ No change

**Current State**: `monitoring/fair_lending.py` produces point-in-time `FairLendingReport`; `decision_engine/policy_challenger.py` supports champion/challenger policy testing; but the two are not integrated to project DIR impact of a proposed policy change.

**Remediation**: Add `simulate_fair_lending_impact(new_policy_config, historical_applications_df)` in `monitoring/fair_lending.py` that replays decisions under the proposed policy and returns delta DIR/approval-rate disparity.

---

#### GAP-12: Historical Fair Lending Trend Tracking Absent
**PRD Reference**: §3.3 Fair Lending Monitor — "Historical trend tracking"
**Severity**: P3 — Medium
**Status vs 04-09**: ↔ No change

**Current State**: `FairLendingReport` objects are saved as JSON files; no time-series table. The fair-lending UI date-range picker is non-functional (no historical API endpoint).

**Remediation**:
1. Persist `FairLendingReport` to a `fair_lending_history` table after each run.
2. Add `GET /api/v1/fair-lending/history?from=&to=` endpoint.
3. Add a trend-line chart to `ui/analytics-dashboard/app/compliance/fair-lending/page.tsx`.

---

#### GAP-13: LOS / Credit Bureau Integration Still Stub
**PRD Reference**: §9 Integration Requirements
**Severity**: P3 — Medium
**Status vs 04-09**: ↔ No change

**Current State**: `ingestion-api/src/main.py` exposes `POST /transactions` and `POST /applications` for direct REST ingestion. No LOS webhook receiver (`/webhook/los`) and no bureau-pull orchestration (Experian/Equifax/TransUnion). `ingestion-api/src/models.py` has schema definitions but no bureau-pull workflow.

> **Note**: `decision-api` now has a full webhook event dispatch system (G16-B) for outbound events; inbound LOS webhook ingestion is still absent.

**Remediation**: Implement `POST /webhook/los` receiver and bureau data enrichment middleware in `ingestion-api`.

---

#### ~~GAP-14: Regulator Read-Only Portal Not Implemented~~
**PRD Reference**: §9.2, Phase 2
**Severity**: P3 — Medium
**Status vs 04-09**: ↔ No change

**Current State**: `compliance/rbac.py` defines an `auditor` role with read-only semantics; no isolated regulator-facing route group (`/regulator/`) exists in `ui/analytics-dashboard/`.

**Remediation**: Add `regulator` role to `auth.ts` and create `/regulator/` route group limited to read-only exam packet download and audit record search, gated by the `auditor` RBAC role.

---

### P4 — Low (Phase 3 / Future Differentiation)

---

#### GAP-15: AI-Powered Anomaly Detection Not Implemented
**PRD Reference**: §10 Automation Opportunities
**Severity**: P4 — Low
**Status vs 04-09**: ↔ No change

**Current State**: `monitoring/drift_monitor.py` uses PSI + KS statistical tests. No ML-based anomaly layer (e.g., `IsolationForest`, autoencoder).

**Remediation**: Integrate `sklearn.ensemble.IsolationForest` in `monitoring/drift_monitor.py` as a supplementary signal; route anomaly events through `monitoring/alert_router.py`.

---

#### GAP-16: Automated Remediation Recommendations Missing
**PRD Reference**: Phase 3 Roadmap
**Severity**: P4 — Low
**Status vs 04-09**: ↔ No change

**Current State**: `compliance/regulatory_horizon.py` tracks upcoming regulatory changes; `compliance/engine.py` emits compliance events; neither maps events to structured remediation recommendations.

**Remediation**: Build `compliance/remediation_advisor.py` mapping each `rule_code` to a `RemediationRecommendation` (action, owner, SLA, regulatory citation) and surface these in the command center dashboard.

---

## New Capabilities Since 04-09 (Not in Prior Gap Analysis)

The following are **net-new deliverables** that expand the platform beyond the PRD baseline. They are not gaps but are documented here for completeness.

| Capability | Module / Endpoint | Tag |
|---|---|---|
| Outbound webhook event dispatch | `webhooks/store.py`, `webhooks/dispatcher.py`, `POST /v1/webhooks`, `GET /v1/webhooks`, `DELETE /v1/webhooks/{id}` | G16-B |
| Config Registry four-eyes approval | `config_registry/`, `POST /v1/config/stage`, `POST /v1/config/approve`, `POST /v1/config/reject` | G11-B |
| Borrower self-service portal | `decision-api/src/borrower_auth.py`, `POST /v1/portal/token`, `GET /v1/portal/applications/{id}/status` | G13-B |
| CSV batch underwriting job queue | `decision-api/src/batch_job_store.py`, `POST /v1/batch/underwrite`, `GET /v1/batch/{id}/status`, `GET /v1/batch/{id}/results` | G14-B |
| Monte Carlo stress test | `POST /v1/stress-test/run`, `GET /v1/stress-test/results`, `GET /v1/stress-test/compare` | G15-B |
| Prometheus + OpenTelemetry metrics | `observability/metrics_pusher.py`, `/metrics` ASGI endpoint | PROMPT-09 |
| Policy challenger A/B routing | `decision_engine/policy_challenger.py`, `PolicyChallengerRouter` | G4-C |
| Governance + validation audit logs | `governance_approval_log`, `model_validation_log` tables in `audit/logger.py` | §21 |
| Per-decision NLG narratives | `decision-api` G06 block calling `nlg_summarizer.generate_decision_summary()` | G06 |
| Analytics API (vintage, roll-rates) | `analytics_api/src/main.py` — `GET /v1/analytics/vintage-curves`, `GET /v1/analytics/roll-rates`, `GET /v1/analytics/approval-profit` | P2.2 |
| Per-tenant semaphore + rate-limit | `IdempotencyMiddleware`, `RateLimitMiddleware`, `_TenantSemaphoreRegistry` | P1.1, CRIT-04 |
| Security hardening (CRIT-01–05) | JWT_SECRET startup guard; CORS allowlist; model crash-on-fail; state APR cap enforcement; Redis check in prod | CRIT-01 to 05 |

---

## Implemented vs. Not Implemented — Summary

### ✅ Fully Implemented

| Capability | Module |
|---|---|
| Cryptographic hash-chain audit log | `audit/logger.py` + `audit/chain_verifier.py` |
| PII masking (SSN, bank account, customer ID) | `audit/logger.py` — `mask_pii()` |
| Real-time compliance gate (MLA, usury, fraud) | `compliance/engine.py` |
| Adverse action data model + ECOA reason codes | `compliance/adverse_action.py` |
| Adverse action PDF rendering (Reg B Form C-1) | `compliance/adverse_action_pdf.py` |
| Adverse action delivery tracking + SLA | `compliance/adverse_action_store.py` |
| SR 11-7 Model Documentation Record generator | `compliance/generate_model_doc.py` |
| RBAC + four-eyes enforcement (Config Registry) | `compliance/rbac.py`, `config_registry/` |
| Compliance health score (0–100, 8 dimensions) | `compliance/health_score.py` |
| Disparate Impact Ratio + chi-sq fair lending | `monitoring/fair_lending.py` |
| BISG proxy methodology for fair lending | `monitoring/bisg.py` |
| PSI + KS drift detection | `monitoring/drift_monitor.py` |
| Portfolio delinquency + guardrail tracking | `monitoring/cc_portfolio_monitor.py` |
| Model KS / AUC performance tracking | `monitoring/cc_pd_monitor.py` |
| Alert routing | `monitoring/alert_router.py` |
| Decision audit explorer UI | `ui/.../compliance/audit-explorer/page.tsx` |
| Fair lending dashboard UI | `ui/.../compliance/fair-lending/page.tsx` |
| SHAP explainability with ECOA code mapping | `explainability/shap_explainer.py` |
| HMDA LAR + FCRA Metro 2 reporting | `reporting/hmda_lar.py`, `reporting/fcra_metro2.py` |
| Tenant isolation guard | `compliance/tenant_guard.py` |
| Regulatory horizon tracking | `compliance/regulatory_horizon.py` |
| **Vintage curves API** | `analytics_api/src/main.py` `GET /v1/analytics/vintage-curves` |
| **Governance/validation audit tables** | `audit/logger.py` §21 `governance_approval_log`, `model_validation_log` |
| **Per-decision NLG narratives** | `decision-api` G06 `generate_decision_summary()` in every response |
| **Webhook event dispatch** | `webhooks/` + `decision-api` G16-B |

### ❌ Not Implemented (Open Gaps)

| Capability | Missing Artifact | PRD Section | Criticality |
|---|---|---|---|
| Exam packet — all components except adverse actions | `exam_packet_builder.py` stubs | §3.2, §5, §13 | P1 |
| Override detection engine with mandatory justification | `audit/override_log.py`, `policy_overrides_log` table | §3.1, §6.2 | P1 |
| Data lineage module | `data_lineage/` | §5.5 | P1 |
| Decision consistency score | `audit/consistency_scorer.py` | §3.1, §7.1 | P2 |
| Model governance UI — live data | API endpoints + hook wiring | §3.4 | P2 |
| Unified command center homepage | `/compliance/command-center/page.tsx` + health endpoint | §4, §11 | P2 |
| NLG narratives in exam packet | Wire `nlg_summarizer` into `exam_packet_builder.py` | §10 | P2 |
| Prohibited variables registry | `compliance/prohibited_variables.py` | §6.2 | P2 |
| Independent validation state machine + SLA check | Enforcement around `model_validation_log` | §3.4, §6.2 | P2 |
| Fair lending scenario simulation | `simulate_fair_lending_impact()` | §3.3 | P3 |
| Historical fair lending trend API | `fair_lending_history` table + endpoint + chart | §3.3 | P3 |
| LOS / credit bureau integration | Ingestion webhook + bureau pull | §9.1 | P3 |
| Regulator read-only portal | `/regulator/` route group + `regulator` role | §9.2, Phase 2 | P3 |
| AI anomaly detection | `IsolationForest` in drift monitor | §10 | P4 |
| Automated remediation recommendations | `compliance/remediation_advisor.py` | Phase 3 | P4 |

---

## PRD Success Criteria Assessment (Updated)

| PRD Success Criterion | Status | Evidence |
|---|---|---|
| Reduce audit prep time by 70%+ | ❌ Not Yet | Exam packet builder is majority stubs; manual assembly still required |
| 100% decision traceability | ✅ Met | Hash-chain audit log covers all decision types |
| Near-zero audit findings from documentation gaps | ❌ Not Yet | Data lineage, committee approvals, override logs, policy snapshots are missing |
| Increased regulator confidence / faster approvals | ❌ Not Yet | No regulator portal; unified command center absent |

---

## Recommended Prioritisation (Updated)

| Sprint | Gaps | Effort | Priority Change |
|---|---|---|---|
| Sprint 1 | GAP-02 (Override detection), GAP-08 (Prohibited variables) | 3–5 days | ↔ unchanged |
| Sprint 2 | GAP-01 (Exam packet stubs + PDF + NLG wiring), GAP-06 (Command center homepage) | 5–7 days | ↔ unchanged; GAP-07 NLG decision pipeline done, focus on packet wiring |
| Sprint 3 | GAP-03 (Data lineage), GAP-05 (Model governance live data — backend tables now exist), GAP-09 (Validation state machine + RBAC) | 4–6 days | ↓ ~1 day saved (tables exist) |
| Sprint 4 | GAP-04 (Consistency score), GAP-12 (Historical fair lending) | 2–4 days | GAP-10 removed from this sprint (closed) |
| Sprint 5 | GAP-11 (Fair lending simulation), GAP-13 (LOS integration), GAP-14 (Regulator portal) | 5–7 days | ↔ unchanged |
| Backlog | GAP-15 (AI anomaly), GAP-16 (Remediation advisor) | 10–15 days | ↔ unchanged |
