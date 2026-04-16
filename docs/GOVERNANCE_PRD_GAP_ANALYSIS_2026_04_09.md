# Gap Analysis: Governance-Native Credit Decisioning Audit Platform
**PRD Reference**: `docs/Governance_native_LOS_PRD.md`
**Analysis Date**: 2026-04-09
**Analyst**: GitHub Copilot
**Platform**: `credit-risk-platform`
**Status**: 16 gaps identified across 3 criticality tiers

---

## Executive Summary

A systematic comparison of the *Governance-Native Credit Decisioning Audit Platform* PRD against the `credit-risk-platform` codebase identified **16 gaps**. Three are **Critical (P1)** — blocking a regulator-ready posture. Seven are **High (P2)** — required for go-live readiness. Six are **Medium/Low (P3–P4)** — aligned with Phase 2/3 roadmap items or quality improvements.

| Criticality | Count | Description |
|---|---|---|
| P1 — Critical | 3 | Missing MVP deliverables; regulator exam risk |
| P2 — High | 7 | Required for feature completeness and go-live |
| P3 — Medium | 4 | Phase 2 roadmap; operational limitations |
| P4 — Low | 2 | Phase 3 roadmap; future differentiation |
| **Total** | **16** | |

---

## Methodology

Each PRD section was mapped to concrete codebase artifacts via:
1. Full directory listing of all modules
2. Source-level examination of `audit/`, `compliance/`, `decision_engine/`, `monitoring/`, `reporting/`, `explainability/`, and `ui/analytics-dashboard/`
3. Cross-referencing PRD modules §3.1–3.5, core workflows §4, audit package structure §5, compliance rules engine §6, data model §8, integration §9, UX requirements §11, and security §12

---

## Module-Level Coverage Matrix

| PRD Module | Section | Status | Notes |
|---|---|---|---|
| Decisioning Audit Engine | §3.1 | ⚠️ Partial | Hash chain ✅; override detection ❌; consistency score ❌ |
| Governance Document Generator | §3.2 | ⚠️ Partial | MDD generation ✅; exam packet stubs ❌; UI action ❌ |
| Fair Lending Monitor | §3.3 | ✅ Implemented | DIR, chi-sq, BISG proxy, alerts present |
| Model Risk Dashboard | §3.4 | ⚠️ Partial | KPIs ✅; live data feed ❌; independent validation workflow ❌ |
| Portfolio Monitoring Engine | §3.5 | ⚠️ Partial | Delinquency ✅; vintage curves ❌; historical trend ⚠️ |
| Command Center UX | §4, §11 | ⚠️ Partial | Role-based views ✅; unified command center ❌; "Generate" button ❌ |
| Compliance Rules Engine | §6 | ⚠️ Partial | Gate + adverse action ✅; prohibited variables ❌; override enforcement ❌ |
| Data Model & Audit Package | §5, §8 | ⚠️ Partial | Core entities ✅; data lineage ❌; policy snapshots ❌ |
| Integration | §9 | ⚠️ Partial | Decision-API ✅; LOS/bureau stubs; regulator portal ❌ |
| Security & Governance | §12 | ✅ Implemented | RBAC ✅; hash-chain ✅; PII masking ✅ |
| MVP Scope (Phase 1) | §13 | ⚠️ Partial | Audit logs ✅; rules engine ✅; audit package stubs ⚠️; model monitoring ✅ |

---

## Gap Inventory

---

### P1 — Critical (MVP Blocking / Regulatory Risk)

---

#### GAP-01: Exam Packet Builder — Non-Adverse-Action Components are Stubs
**PRD Reference**: §3.2 Governance Document Generator, §5 Audit Package Structure, §13 MVP Scope
**Severity**: P1 — Critical

**PRD Requirement**:
> "Generate audit-ready PDF / export package. One-click 'Generate Audit Package'. Pre-mapped regulatory templates. Outputs: credit policy documents, change logs, committee approvals, model documentation (MDD, validation summary), decision evidence samples, fair lending analysis, data lineage."

**Current State**:
- `compliance/exam_packet_builder.py` — `ExamPacketComponent` objects for all components exist, but only `adverse_actions` is marked `"complete"`. All other components (`model_documentation`, `policy_snapshots`, `decision_samples`, `fair_lending_analysis`, `data_lineage`, `committee_approvals`) return `status="stub"`.
- `format="pdf_zip"` is accepted as a CLI argument but no PDF rendering is wired up for the full package (only adverse action notices use `adverse_action_pdf.py` via reportlab).
- There is no UI button to trigger package generation; the builder is CLI-only.
- No `committee_approvals` data model or collection path exists anywhere in the codebase.

**Impact**:
- One-click audit package generation — a core PRD §3.2 / §11 feature — cannot be demonstrated to a regulator.
- OCC/CFPB exam prep remains manual; PRD success criterion of "reduce audit prep time by 70%+" is unmet.

**Remediation**:
1. Implement each stub component in `exam_packet_builder.py` by wiring to existing live data sources (`compliance/generate_model_doc.py` → `model_documentation`, `decision_engine/policy_version_store.py` → `policy_snapshots`, `audit/logger.py` → `decision_samples`, `monitoring/fair_lending.py` → `fair_lending_analysis`).
2. Add PDF rendering for the full package using reportlab or WeasyPrint (extend `adverse_action_pdf.py` pattern).
3. Add `CommitteeApproval` to the data model and a CRUD API endpoint.
4. Expose a `/api/v1/audit/generate-package` POST endpoint and wire a "Generate Audit Package" button in the compliance UI.

---

#### GAP-02: Override Detection Engine Missing
**PRD Reference**: §3.1 Decisioning Audit Engine — "Override detection engine", §6.2 Example Rules — "Overrides must include justification + approval"
**Severity**: P1 — Critical

**PRD Requirement**:
> "Detect overrides and deviations. Every override must include a justification and approval. Override rate is a key audit metric."

**Current State**:
- `decision_engine/engine.py` accepts a `policy_overrides: Optional[Dict[str, Any]]` parameter that silently overrides PD thresholds with no justification, approver, or audit log entry.
- `audit/logger.py`'s `_CREATE_AUDIT_TABLE` DDL has no `override_flag`, `override_justification`, or `override_approver` columns.
- `compliance/engine.py`'s compliance gate has no override detection path; it only gates APR/MLA violations.
- `decision_engine/portfolio_review.py` tracks `guardrail_override_count` at the batch level, but individual decision-level override capture does not flow to the audit log.
- `compliance/rbac.py` defines four-eyes enforcement but it is not coupled to override submission.

**Impact**:
- Override rate metric (PRD §7.1) cannot be computed accurately from audit data.
- SR 11-7 model risk management and OCC 2021-25 require every model override to be logged, justified, and approved — this is unmet.
- Shadow-floor or policy manipulation by a single actor is undetected.

**Remediation**:
1. Add `PolicyOverrideRecord` dataclass: `decision_id`, `override_type`, `original_value`, `override_value`, `justification`, `submitted_by`, `approved_by`, `approved_at`.
2. Persist to a new `policy_overrides_log` table (append-only); include `record_hash` per the existing chain-verifier schema.
3. Enforce via `compliance/rbac.py` four-eyes before accepting `policy_overrides` in `engine.py`.
4. Surface override rate on the compliance dashboard.

---

#### GAP-03: No Data Lineage Module
**PRD Reference**: §5.5 Data & System Documentation — "Data lineage, architecture diagrams, data dictionary"
**Severity**: P1 — Critical

**PRD Requirement**:
> "Audit package must include: data lineage, architecture diagrams, and a data dictionary."

**Current State**:
- No `data_lineage/` module, no `data_dictionary.py`, and no architecture diagram generation exists anywhere in the codebase.
- `feature_pipeline/` implements feature extraction; `ingestion-api/` handles data ingestion — but neither records provenance metadata (source system, transformation step, schema version) to a queryable store.
- `compliance/exam_packet_builder.py` has a `data_lineage` slot that always returns `status="stub"`.
- `compliance/generate_model_doc.py` includes a `training_data_description` field, but it relies on manually typed strings and MLflow tags, not a live lineage graph.

**Impact**:
- FFIEC IT audit standards and OCC supervisory guidance expect a documented chain of data custody from ingestion to model prediction. Absence creates a documentation gap that regulators flag as a management control weakness.

**Remediation**:
1. Create `data_lineage/lineage_tracker.py` that captures source → transform → feature → model provenance as a DAG stored in the audit database.
2. Auto-populate from `feature_pipeline/` hooks.
3. Export a `DataLineageReport` from `exam_packet_builder.py`.

---

### P2 — High (Go-Live Readiness)

---

#### GAP-04: Decision Consistency Score Not Implemented
**PRD Reference**: §3.1 Decisioning Audit Engine — "Decision consistency score", §7.1 Audit Metrics
**Severity**: P2 — High

**PRD Requirement**:
> "Output: decision consistency score."

**Current State**:
- No module computes a consistency score for a credit decision (e.g., probability that the same inputs would produce the same output under policy re-run, or consistency relative to peer decisions in the same risk tier).
- The `explainability/counterfactual.py` module exists but produces a counterfactual explanation, not a consistency metric.

**Remediation**:
Implement `audit/consistency_scorer.py`: deterministic re-run of a stored decision through the current policy + model, compare output delta; flag inconsistencies above a threshold as a compliance item.

---

#### GAP-05: Model Governance UI Uses Mock Data
**PRD Reference**: §3.4 Model Risk Dashboard — "Model inventory management, real-time model monitoring"
**Severity**: P2 — High

**Current State**:
- `ui/analytics-dashboard/app/compliance/model-governance/page.tsx` renders `MOCK_MODELS` (a hardcoded TypeScript array).
- No API endpoint (`/api/v1/models` or similar) is wired to the MLflow model registry or any live model inventory store.
- Promote/archive actions call `setTimeout` stubs instead of a real API.

**Remediation**:
1. Add `GET /api/v1/models` → query MLflow `MlflowClient.search_model_versions()`.
2. Add `POST /api/v1/models/{model_id}/promote` → call `mlflow.transition_model_version_stage()` with RBAC enforcement.
3. Replace `MOCK_MODELS` with a `useSWR` data-fetching hook.

---

#### GAP-06: Command Center Homepage Does Not Exist
**PRD Reference**: §4 Core Workflows, §11 UX Requirements — "Dashboard Elements: Audit Readiness Score, Active Compliance Flags, Model Health Indicators, Fair Lending Alerts; Key Actions: Generate Audit Package, View Decision Trace, Run Fair Lending Analysis"
**Severity**: P2 — High

**Current State**:
- `ui/analytics-dashboard/app/page.tsx` is a server-side redirect router that sends each user role to a siloed page.
- The `compliance/` UI role lands on `/compliance/fair-lending` by default — not a unified command center.
- No single dashboard page aggregates: Audit Readiness Score (0–100), Active Compliance Flags count, Model Health status, Fair Lending alert counts, and quick-action buttons ("Generate Audit Package", "View Decision Trace", "Run Fair Lending Analysis").
- `compliance/health_score.py` (backend) computes all necessary dimensions but has no REST endpoint exposing its output.

**Remediation**:
1. Add `GET /api/v1/compliance/health` endpoint wrapping `compute_health_score()`.
2. Create `ui/analytics-dashboard/app/compliance/command-center/page.tsx` with the full KPI grid and action launchers.
3. Update `ROLE_HOME` to route `compliance` role to `/compliance/command-center`.

---

#### GAP-07: NLG Summarizer Not Integrated into Audit Package
**PRD Reference**: §10 Automation Opportunities — "Auto-generation of audit narratives"
**Severity**: P2 — High

**Current State**:
- `explainability/nlg_summarizer.py` generates natural-language summaries of individual decisions.
- `compliance/exam_packet_builder.py` does not call the summarizer; narrative sections are either empty or static.
- No audit narrative template system exists.

**Remediation**:
Wire `nlg_summarizer.generate_narrative()` into each `ExamPacketComponent` to produce executive-audit-ready prose summaries alongside the structured data output.

---

#### GAP-08: Prohibited Variables Registry Missing
**PRD Reference**: §6.2 Example Rules — "No prohibited variables used in decisioning"
**Severity**: P2 — High

**Current State**:
- `compliance/engine.py` checks MLA, state usury caps, and fraud score thresholds but contains no explicit protected-class / prohibited-variable registry.
- `decision_engine/engine.py` does not validate that input feature keys are free of proxies for race, gender, religion, national origin, marital status, or age.
- ECOA / FCRA / Fair Housing Act all require that no prohibited basis variables (or their close proxies) enter the decisioning pipeline.

**Remediation**:
1. Create `compliance/prohibited_variables.py` with a `PROHIBITED_VARIABLES` registry and a `PROXY_VARIABLE_MAP`.
2. Add a pre-decision gate in `decision_engine/engine.py` that raises `ProhibitedVariableViolation` if any input feature matches the registry.
3. Log violations to `compliance_events` and surface in the compliance dashboard.

---

#### GAP-09: Independent Model Validation Workflow Not Formalized
**PRD Reference**: §3.4 Model Risk Dashboard — "Independent validation tracking", §6.2 — "Model must have validation within last X months"
**Severity**: P2 — High

**Current State**:
- `compliance/generate_model_doc.py` accepts `reviewer` and `approver` string fields in `ModelDocumentationConfig` but does not enforce that they are distinct individuals (four-eyes) or that their review was recorded at a specific point in the model lifecycle.
- `compliance/health_score.py` tracks a `model_governance` dimension score but the underlying data query references MLflow tags which can be self-populated by the model developer.
- No `ModelValidationRecord` entity exists; there is no state machine (e.g., `PENDING_VALIDATION → UNDER_REVIEW → VALIDATED → APPROVED`).
- The compliance rules engine has no hard enforcement that a deployed model has a validation within a configurable SLA window.

**Remediation**:
1. Add `ModelValidationRecord` to the data model with lifecycle states and timestamps.
2. Enforce that `reviewer != submitter` via `compliance/rbac.py` four-eyes check.
3. Add a nightly job that flags models with `last_validated_at > VALIDATION_SLA_DAYS` and creates a compliance event.

---

#### GAP-10: Vintage Curves Not Implemented
**PRD Reference**: §3.5 Portfolio Monitoring Engine — "Vintage curves"
**Severity**: P2 — High

**Current State**:
- `monitoring/cc_portfolio_monitor.py` tracks monthly action-rate drift, feature PSI, guardrail overrides, and adverse action SLA — but does not compute vintage curves (delinquency-by-origination-cohort over time).
- No `VintageCurveReport` dataclass or plotting utility exists.

**Remediation**:
Add `monitor_vintage_curves(decisions_df, performance_df)` to `cc_portfolio_monitor.py`, bucketing decisions by origination quarter and computing delinquency rates at 3, 6, 12, 18, and 24 months post-origination.

---

### P3 — Medium (Phase 2 Roadmap)

---

#### GAP-11: Scenario Simulation for Fair Lending Not Implemented
**PRD Reference**: §3.3 Fair Lending Monitor — "Scenario simulation (policy/model changes)", Phase 2 Roadmap
**Severity**: P3 — Medium

**Current State**:
- `monitoring/fair_lending.py` computes current-state metrics but has no simulation capability.
- `decision_engine/policy_challenger.py` exists for champion/challenger policy testing but is not integrated with the fair lending monitor to project DIR impact of a proposed policy change.

**Remediation**:
Add `simulate_fair_lending_impact(new_policy_config, historical_applications_df)` that re-runs the decisioning engine with the proposed policy and computes the delta DIR/approval-rate disparity.

---

#### GAP-12: Historical Fair Lending Trend Tracking Absent
**PRD Reference**: §3.3 Fair Lending Monitor — "Historical trend tracking"
**Severity**: P3 — Medium

**Current State**:
- `monitoring/fair_lending.py` produces a point-in-time `FairLendingReport`; reports are saved as JSON files in `monitoring/` but are not stored in a time-series table.
- The fair-lending UI page has a date-range picker but it is non-functional (no historical API endpoint).

**Remediation**:
1. Persist `FairLendingReport` to a `fair_lending_history` table after each run.
2. Add `GET /api/v1/fair-lending/history?from=&to=` endpoint.
3. Add a trend-line chart to the fair-lending UI page.

---

#### GAP-13: LOS / Credit Bureau Integration Still Stub
**PRD Reference**: §9 Integration Requirements — "Loan origination system (LOS), Credit bureau APIs"
**Severity**: P3 — Medium

**Current State**:
- `decision-api/src/main.py` accepts application payloads directly over REST but has no native integration with a LOS webhook or bureau pull orchestration.
- `ingestion-api/` exists but the bureau-pull workflow (`experian/`, `equifax/`, `transunion/`) is not implemented beyond schema definitions.

**Remediation**:
Implement LOS webhook receiver (`POST /webhook/los`) and bureau data enrichment middleware as part of the ingestion-API pipeline.

---

#### GAP-14: Regulator Read-Only Portal Not Implemented
**PRD Reference**: §9.2 Downstream Outputs, Phase 2 Roadmap — "Regulator portal access"
**Severity**: P3 — Medium

**Current State**:
- `compliance/rbac.py` defines an `auditor` role with read-only access semantics, but no isolated regulator-facing portal or view exists in the UI.
- Regulators currently have no authenticated, scoped access path to exam packets or audit records.

**Remediation**:
Add a `regulator` role to `auth.ts` and create a `/regulator/` route group in the analytics dashboard limited to read-only exam packet download and audit record search, gated by the `auditor` RBAC role.

---

### P4 — Low (Phase 3 / Future Differentiation)

---

#### GAP-15: AI-Powered Anomaly Detection Not Implemented
**PRD Reference**: §10 Automation Opportunities — "AI-powered anomaly detection"
**Severity**: P4 — Low

**Current State**:
- `monitoring/drift_monitor.py` uses PSI + KS tests (statistical methods) but no ML-based anomaly detection (isolation forest, autoencoder, or LLM-based narrative anomaly detection) exists.

**Remediation**:
Integrate an anomaly detection layer (e.g., `sklearn.ensemble.IsolationForest`) in `monitoring/drift_monitor.py` as a supplementary signal to statistical methods; route anomaly events through `monitoring/alert_router.py`.

---

#### GAP-16: Automated Remediation Recommendations Missing
**PRD Reference**: Phase 3 Roadmap — "Automated remediation recommendations"
**Severity**: P4 — Low

**Current State**:
- `compliance/regulatory_horizon.py` tracks upcoming regulatory changes; `compliance/engine.py` emits compliance events — but neither produces a recommended remediation action.
- `explainability/nlg_summarizer.py` generates decision explanations but not compliance remediation guidance.

**Remediation**:
Build a `compliance/remediation_advisor.py` that maps each compliance event `rule_code` to a structured `RemediationRecommendation` (action, owner, SLA, regulatory citation), and surface these in the command center dashboard.

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
| RBAC + four-eyes enforcement | `compliance/rbac.py` |
| Compliance health score (0–100, 8 dimensions) | `compliance/health_score.py` |
| Disparate Impact Ratio + chi-sq fair lending | `monitoring/fair_lending.py` |
| BISG proxy methodology for fair lending | `monitoring/bisg.py` |
| PSI + KS drift detection | `monitoring/drift_monitor.py` |
| Portfolio delinquency + guardrail tracking | `monitoring/cc_portfolio_monitor.py` |
| Model KS / AUC performance tracking | `monitoring/cc_pd_monitor.py` |
| Alert routing | `monitoring/alert_router.py` |
| Decision audit explorer UI | `ui/.../compliance/audit-explorer/page.tsx` |
| Fair lending dashboard UI | `ui/.../compliance/fair-lending/page.tsx` |
| Model governance registry UI (mock data) | `ui/.../compliance/model-governance/page.tsx` |
| SHAP explainability with ECOA code mapping | `explainability/shap_explainer.py` + `compliance/adverse_action.py` |
| HMDA LAR + FCRA Metro 2 reporting | `reporting/hmda_lar.py`, `reporting/fcra_metro2.py` |
| Tenant isolation guard | `compliance/tenant_guard.py` |
| Regulatory horizon tracking | `compliance/regulatory_horizon.py` |

### ❌ Not Implemented (Gaps)

| Capability | Missing Artifact | PRD Section | Criticality |
|---|---|---|---|
| Exam packet — all components except adverse actions | `exam_packet_builder.py` stubs | §3.2, §5, §13 | P1 |
| Override detection engine with mandatory justification | `audit/override_log.py` | §3.1, §6.2 | P1 |
| Data lineage module | `data_lineage/` | §5.5 | P1 |
| Decision consistency score | `audit/consistency_scorer.py` | §3.1, §7.1 | P2 |
| Model governance UI — live data | API + hook wiring | §3.4 | P2 |
| Unified command center homepage | `/compliance/command-center/page.tsx` | §4, §11 | P2 |
| NLG narratives in audit package | Wire `nlg_summarizer.py` | §10 | P2 |
| Prohibited variables registry | `compliance/prohibited_variables.py` | §6.2 | P2 |
| Independent validation workflow | `ModelValidationRecord` state machine | §3.4, §6.2 | P2 |
| Vintage curves | `monitor_vintage_curves()` | §3.5 | P2 |
| Fair lending scenario simulation | `simulate_fair_lending_impact()` | §3.3 | P3 |
| Historical fair lending trend API | `fair_lending_history` table + endpoint | §3.3 | P3 |
| LOS / credit bureau integration | Ingestion webhook + bureau pull | §9.1 | P3 |
| Regulator read-only portal | `/regulator/` route group | §9.2, Phase 2 | P3 |
| AI anomaly detection | `IsolationForest` in drift monitor | §10 | P4 |
| Automated remediation recommendations | `compliance/remediation_advisor.py` | Phase 3 | P4 |

---

## PRD Success Criteria Assessment

| PRD Success Criterion | Status | Evidence |
|---|---|---|
| Reduce audit prep time by 70%+ | ❌ Not Yet | Exam packet builder is majority stubs; manual assembly still required |
| 100% decision traceability | ✅ Met | Hash-chain audit log covers all decision types |
| Near-zero audit findings from documentation gaps | ❌ Not Yet | Data lineage, committee approvals, override logs, policy snapshots are missing |
| Increased regulator confidence / faster approvals | ❌ Not Yet | No regulator portal; unified command center absent |

---

## Recommended Prioritisation

| Sprint | Gaps | Effort |
|---|---|---|
| Sprint 1 | GAP-02 (Override detection), GAP-08 (Prohibited variables) | 3–5 days |
| Sprint 2 | GAP-01 (Exam packet stubs + PDF export), GAP-06 (Command center homepage) | 5–7 days |
| Sprint 3 | GAP-03 (Data lineage), GAP-05 (Model governance live data), GAP-09 (Validation workflow) | 5–7 days |
| Sprint 4 | GAP-04 (Consistency score), GAP-07 (NLG in packet), GAP-10 (Vintage curves) | 3–5 days |
| Sprint 5 | GAP-11 (Fair lending simulation), GAP-12 (Historical trends), GAP-14 (Regulator portal) | 5–7 days |
| Backlog | GAP-13 (LOS integration), GAP-15 (AI anomaly), GAP-16 (Remediation advisor) | 10–15 days |
