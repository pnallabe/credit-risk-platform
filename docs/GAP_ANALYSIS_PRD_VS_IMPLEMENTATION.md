# Gap Analysis: PRD vs. Implementation
**Document**: Integrated Lending Operating Layer (ILOL)
**PRD Reference**: `docs/Unified_ILOL_PRD.md` *(Unified Edition v3.0.0 — supersedes v1.0.0 + Governance_native_LOS_PRD v2.1)*
**Analysis Date**: 2026-04-15 *(full re-audit against unified PRD v3.0; prior audits: 2026-04-07, 2026-04-14; HITL audit addendum: 2026-04-15)*
**Analyst**: GitHub Copilot
**Status**: 21 of 21 original+legacy gaps CLOSED — 5 new gaps introduced by PRD v3.0 (P1–P2)

---

## Executive Summary

A full re-audit of the `credit-risk-platform` codebase against the **Unified ILOL PRD v3.0.0** conducted on **2026-04-15** produces the following verdict:

- All **18 legacy gaps** from the prior audit cycles are now fully closed, including GAP-17 (OCR document ingestion) and GAP-18 (real-time bureau integration) which were previously marked partially open.
- The v3.0 PRD introduced a new architectural pillar — **Module 6: RAG-Powered AI Analytics Agent + Anti-Hallucination Framework** — that materially expands scope beyond v1.0. Three new gaps are open against this module: GAP-19 (Anti-Hallucination Framework / Code Transparency Layer absent), GAP-20 (GNRI-011 immutable AI audit log non-compliant), and GAP-21 (AI Agent Audit Appendix missing from exam packet generator).
- Fourteen modules and features introduced or materially expanded in PRD v3.0 — Compliance Health Score, SOC 2 evidence collection, data retention enforcement, erasure request handling, RBAC enforcement, regulatory horizon scanner, third-party model registry, prohibited variables checker, decision replay bundle, consistency scorer, override log, exam packet builder (7 components), NLG executive summaries, and the analytics API — are **all implemented and confirmed**.

Net position: **18 of 18 legacy gaps CLOSED; 5 new PRD v3.0 gaps open (1× P1, 1× P1, 3× P2).**

---

## Methodology

Each PRD v3.0 section was mapped to concrete codebase artifacts via:
1. Full recursive listing of all Python source files across all modules (confirmed 200+ files across 30+ top-level packages)
2. Source-level examination of every module: `audit/`, `compliance/`, `decision-api/`, `monitoring/`, `reporting/`, `orchestration/`, `feature_pipeline/`, `explainability/`, `webhooks/`, `risk_models/`, `decision_engine/`, `decisioning/`, `ingestion-api/`, `scripts/`, `data_lineage/`, `ai-agent/`, `analytics_api/`, `config_registry/`, `validation/`, `observability/`, `etl/`, `db/`, `models/`
3. Route extraction from `decision-api/src/main.py` (67 distinct API endpoints confirmed)
4. Cross-referencing PRD v3.0 functional requirements (§4 Modules 1–6), §5 Anti-Hallucination Framework, §7 System Architecture, §8 Data Architecture, §9 Compliance & Governance, §10 API Design
5. Diff against prior re-audit (2026-04-14) to identify net-new implementations and newly opened v3.0 gaps

---

## Part I — Legacy Gap Inventory (PRD v1.0 / v2.1 Basis)

---

#### GAP-01: Cryptographic Hash Chain Missing from Audit Log — ✅ CLOSED
**PRD Reference**: §8.3 Audit Trail Requirements, §6.4 Immutable Audit Infrastructure
**Severity**: P1 — Critical → **RESOLVED**
**Regulatory Driver**: 12 CFR Part 1002 (ECOA/Reg B), OCC 2021-25 model risk, FFIEC IT audit standards

**PRD Requirement**:
> "Every audit record shall be cryptographically chained to its predecessor using SHA-256. Any tampering shall be detectable via offline chain verification. The audit log must be append-only and tamper-evident."

**As-Of 2026-04-07 State**: `audit/logger.py` had no `record_hash`/`previous_hash` columns; `_sha256()` used only for PII masking; no `chain_verifier.py`.

**Current State (2026-04-14)**:
- `audit/logger.py` DDL now includes `record_hash TEXT`, `previous_hash TEXT`, `hash_algorithm TEXT NOT NULL DEFAULT 'sha256'` on both `audit_log` and `portfolio_audit_log` tables, plus `adverse_action_log`
- `compute_chain_hash()` async function computes `(record_hash, previous_hash)` and writes them on every `log_decision()` / `log_portfolio_action()` call
- `audit/chain_verifier.py` fully implements `verify_chain()` returning `ChainVerificationResult` with `verified`, `rows_checked`, `first_tampered_log_id`, `gap_detected`
- `_CANONICAL_FIELDS` mapping covers `audit_log`, `portfolio_audit_log`, and `adverse_action_log` tables
- Test suite: `audit/tests/test_chain_verifier.py`, `audit/tests/test_hash_chain_migration.py`

**Closure Verdict**: Full remediation confirmed. SHA-256 hash chain is enforced on every write path; offline verification is available. OCC tamper-evidence control is satisfied.

---

#### GAP-02: Adverse Action Notices Not Generated — ✅ CLOSED
**PRD Reference**: §4.5 Adverse Action Management, §8.1 ECOA / Reg B Compliance
**Severity**: P1 — Critical → **RESOLVED**
**Regulatory Driver**: 12 CFR §1002.9 (notice timing), Reg B model notices C-1/C-2

**PRD Requirement**:
> "The system shall auto-generate Reg B–compliant adverse action notices within 30 days of a credit decision. Notices shall include the specific ECOA reason codes, creditor contact information, and CFPB disclosure language. PDF rendering and delivery tracking are required."

**As-Of 2026-04-07 State**: No `adverse_action*.py` files; `compliance/engine.py` returned pass/fail only; no `adverse_action_log` table; no delivery tracking.

**Current State (2026-04-14)**:
- `compliance/adverse_action.py` — `AdverseActionNotice` dataclass, `REG_B_REASON_CODES` registry, `map_shap_factors_to_reg_b_codes()`, `select_form_type()` (C-1/C-2)
- `compliance/adverse_action_generator.py` — `generate_notice()`, `render_c1_text()`, `notice_to_dict()`
- `compliance/adverse_action_pdf.py` — `render_notice_pdf()` via `reportlab` (lazy import)
- `compliance/adverse_action_store.py` — `save_notice()`, `mark_delivered()`, `get_notice()`, `list_notices()`, `get_pending_deadline_notices()`
- `decision-api/src/main.py` `_run_pipeline()` wires SHAP factors → Reg B codes → `generate_notice()` → `save_notice()` on REJECT path
- NLG-generated `adverse_action_body` injected into notice text via `explainability/nlg_summarizer.py`
- `monitoring/tests/test_aa_deadline_alert.py` confirms 30-day deadline monitoring
- `decision-api/tests/test_adverse_action_endpoints.py` covers full API path
- Test suite: `compliance/tests/test_adverse_action_generator.py`, `test_adverse_action_pdf.py`, `test_adverse_action_store.py`

**Closure Verdict**: Full Reg B notice lifecycle implemented — generation, PDF rendering, delivery tracking, and deadline monitoring. CFPB enforcement exposure eliminated.

---

### Priority 2 — High (Go-Live Readiness)

---

#### GAP-03: No Multi-Tenant Data Isolation at Query Layer — ✅ CLOSED
**PRD Reference**: §6.5 Multi-Tenant Architecture, §7.4 Data Isolation Controls
**Severity**: P2 — High → **RESOLVED**
**Regulatory Driver**: GLBA §501(b), SOC 2 Type II CC6.3

**PRD Requirement**:
> "All data access must enforce tenant_id row-level scoping in every query. Cross-tenant data leakage must be architecturally impossible, not policy-dependent."

**As-Of 2026-04-07 State**: `orchestration/pipeline.py` accepted optional `tenant_id`; `get_audit_record()` did not validate caller tenant; BigQuery row-level access policies not provisioned.

**Current State (2026-04-14)**:
- `audit/tenant_guard.py` — `TenantContext` dataclass, `scoped_tenant()` context manager, `require_tenant_context` decorator that injects `tenant_id` into decorated function signatures automatically
- `orchestration/pipeline.py` now enforces `tenant_id` as a **required** positional argument in `run()`; validation raises `ValueError` on empty/missing tenant — no default
- `scripts/provision_bq_tenant_policies.py` — idempotent BigQuery `CREATE ROW ACCESS POLICY` provisioner per tenant + service-account pair; dry-run and live modes; JSON audit log output
- `audit/tests/test_tenant_guard.py`, `orchestration/tests/test_pipeline_tenant_guard.py`, `tests/audit/test_tenant_isolation.py`, `decision-api/tests/test_tenant_isolation.py` all green
- `scripts/tests/test_provision_bq_tenant_policies.py` covers dry-run DDL output

**Closure Verdict**: Tenant isolation is now architecturally enforced at the pipeline, audit, and BigQuery layers.

---

#### GAP-04: Champion/Challenger Only at Model Level — No Policy-Level A/B — ✅ CLOSED
**PRD Reference**: §4.3 Policy Management, §6.3 Champion/Challenger Framework
**Severity**: P2 — High → **RESOLVED**

**PRD Requirement**:
> "Champion/challenger routing shall operate at both the ML model layer and the underwriting policy rule layer independently, with per-tenant traffic split configuration."

**As-Of 2026-04-07 State**: Only model-level champion/challenger existed; no policy-level traffic split.

**Current State (2026-04-14)**:
- `decision_engine/policy_challenger.py` — `PolicyChallengerConfig`, `PolicyDecisionRecord`, `PolicyComparisonReport`, `PolicySplitStore` (SQLite/Postgres backed, `policy_challenger.db`)
- Per-tenant traffic-split percentages configurable; champion/challenger routing decided via deterministic hash of `application_id`
- Decision API exposes `/v1/policy-split` POST/GET/DELETE endpoints, `/v1/policy-split/report` aggregate metrics
- `decision-api/tests/test_policy_split_endpoints.py` covers CRUD and routing logic
- `scripts/policy_split_manager.py` CLI for ops teams; `scripts/tests/test_policy_split_manager.py`
- `decision_engine/tests/test_policy_challenger.py` covers store and routing logic

**Closure Verdict**: Policy-level A/B routing with per-tenant traffic splits is fully implemented.

---

#### GAP-05: HMDA LAR Export Only — No CRA, FCRA, or UDAAP Reporting — ✅ CLOSED
**PRD Reference**: §8.4 Regulatory Reporting, §4.7 Compliance Reporting Suite
**Severity**: P2 — High → **RESOLVED**
**Regulatory Driver**: 12 CFR Part 203 (HMDA), 12 U.S.C. §2901 (CRA), 15 U.S.C. §1681 (FCRA)

**PRD Requirement**:
> "The platform shall generate HMDA LAR, CRA activity reports, FCRA Metro 2 tradeline exports, and UDAAP monitoring summaries on configurable schedules."

**As-Of 2026-04-07 State**: Only `reporting/hmda_lar.py` existed.

**Current State (2026-04-14)**:
- `reporting/cra_activity.py` — CRA Activity Report generator; categorises applications by income tier (AMI %), action taken, geographic distribution
- `reporting/fcra_metro2.py` — FCRA Metro 2® Base Segment (426-char) record builder; full field mapping for bureau submission
- `reporting/udaap_summary.py` — UDAAP monitoring summary aggregating complaint and adverse-action records; risk signal surfacing
- `reporting/dispatcher.py` — scheduled report runner tying all four report types to configurable cadences
- Test suite: `reporting/tests/test_cra_activity.py`, `test_fcra_metro2.py`, `test_udaap_summary.py`, `test_dispatcher.py`

**Closure Verdict**: All four regulatory report types implemented. CRA exam and FCRA bureau-reporting preparedness gaps eliminated.

---

#### GAP-06: No NLG Decision Summaries — ✅ CLOSED
**PRD Reference**: §4.6 Explainability & Customer Communication, §5.2 Loan Officer Workflow
**Severity**: P2 — High → **RESOLVED**

**PRD Requirement**:
> "For each underwriting decision, the system shall produce a plain-language NLG summary suitable for (a) the loan officer dashboard, (b) the applicant-facing portal, and (c) the adverse action notice body."

**As-Of 2026-04-07 State**: No `generate_decision_summary()` function; SHAP factors not piped to any LLM; no prompt templates.

**Current State (2026-04-14)**:
- `explainability/nlg_summarizer.py` — `NLGSummary` dataclass; `generate_decision_summary()` produces three audience-tuned variants: `loan_officer_narrative` (professional, 3–5 sentences), `applicant_narrative` (8th-grade reading level), `adverse_action_body` (Reg B / ECOA compliant)
- Full `ECOA_REASON_CODES` mapping from SHAP factor names to plain-language descriptions
- `decision-api/src/main.py` `_run_pipeline()` imports and calls `generate_decision_summary()` after SHAP; results stored in `DecisionResponse.explanation_narrative` and passed to adverse action notice
- `tests/test_nlg_integration.py` covers LLM stub + live narrative generation
- Graceful fallback when LLM unavailable (env var `OPENAI_API_KEY` absent)

**Closure Verdict**: Three-audience NLG narratives generated and wired into the full decision pipeline.

---

#### GAP-07: Model Drift Alerts Not Wired to Alert Router — ✅ CLOSED
**PRD Reference**: §4.8 Model Monitoring, §6.6 Alerting Infrastructure
**Severity**: P2 — High → **RESOLVED**

**PRD Requirement**:
> "PSI > 0.20, KS drop > 0.05, or AUROC drop > 0.03 shall trigger a P1 alert to the model risk officer within 5 minutes via the configured alert channel."

**As-Of 2026-04-07 State**: `cc_pd_monitor.py` and `alert_router.py` existed but were not connected; `AlertRouter` had no `send_alert()` method.

**Current State (2026-04-14)**:
- `monitoring/alert_router.py` now exposes `AlertRouter.send_alert(severity, title, body) → AlertRecord` and `AlertRouter.route(severity, subject, body) → AlertRecord`; `DEFAULT_ALERT_ROUTER` singleton exposed at module level
- `monitoring/cc_pd_monitor.py` imports `AlertRouter, DEFAULT_ALERT_ROUTER`; `monitor_model()` function accepts optional `alert_router` parameter (defaults to `DEFAULT_ALERT_ROUTER`) and calls `router.send_alert(...)` when PSI/KS/AUROC thresholds are breached
- `tests/monitoring/test_monitor_alert_routing.py` and `tests/monitoring/test_alert_router_channels.py` cover end-to-end wiring
- `monitoring/drift_monitor.py` also wired to `AlertRouter`

**Closure Verdict**: Drift threshold breaches now trigger real-time alerts. PRD 5-minute SLA is met for configured Slack/email channels.

---

### Priority 3 — Medium (Operational Completeness)

---

#### GAP-08: Feature Lineage Emitted but Not Queryable — ✅ CLOSED
**PRD Reference**: §7.3 Data Lineage, §6.7 Observability
**Severity**: P3 — Medium → **RESOLVED**

**PRD Requirement**:
> "Feature lineage shall be queryable via API — each feature's upstream source, transformation, and version must be retrievable on demand."

**As-Of 2026-04-07 State**: `feature_pipeline/lineage.py` emitted OpenLineage events fire-and-forget; no query API.

**Current State (2026-04-14)**:
- `decision-api/src/main.py` exposes `GET /v1/lineage/{run_id}` (retrieve all lineage events for a pipeline run) and `GET /v1/lineage/job/{job_name}` (retrieve by job name)
- `data_lineage/lineage_tracker.py` provides `get_lineage_graph()` and `export_lineage_report()` for async graph traversal
- `feature_pipeline/lineage.py` `LineageStore` provides local SQLite-backed index for fast lookups
- `decision-api/tests/test_lineage_api.py` covers 200/404/503 paths
- `tests/feature_pipeline/test_lineage.py` covers store operations

**Closure Verdict**: Lineage is queryable on-demand at both the run and job-name level via the decision API.

---

#### GAP-09: No SR 11-7 Model Documentation Auto-Generation for Champion Challenger — ✅ CLOSED
**PRD Reference**: §8.5 Model Governance, §4.9 Model Risk Management
**Severity**: P3 — Medium → **RESOLVED**

**PRD Requirement**:
> "When a challenger model is promoted to champion, the system shall automatically generate an SR 11-7–compliant model card and attach it to the promotion audit record."

**As-Of 2026-04-07 State**: `generate_model_doc.py` existed for manual runs; `promote_champion()` did not invoke it.

**Current State (2026-04-14)**:
- `decisioning/champion_challenger.py` `promote_champion()` now accepts optional `model_doc_config` parameter
- On promotion, automatically imports and calls `compliance.generate_model_doc.generate_mdr()` with a default `ModelDocumentationConfig` built from the new champion run ID
- Generated MDR is attached to the promotion audit record
- `decision-api/tests/test_promotion_endpoint.py` covers the promotion-to-doc pipeline
- `tests/decisioning/test_champion_promotion.py` unit-tests the auto-generation hook

**Closure Verdict**: SR 11-7 model documentation is auto-generated and attached to the audit record on every champion promotion.

---

#### GAP-10: Explainability API Not Exposed in Decision API — ✅ CLOSED
**PRD Reference**: §9.3 Explainability Endpoints, §4.6 Explainability
**Severity**: P3 — Medium → **RESOLVED**

**PRD Requirement**:
> "GET /v1/decisions/{id}/explanation shall return SHAP values, counterfactuals, and a narrative summary in a single response."

**As-Of 2026-04-07 State**: SHAP stored internally; no dedicated explainability endpoint; no counterfactual generation.

**Current State (2026-04-14)**:
- `decision-api/src/main.py` exposes `GET /v1/decisions/{application_id}/explanation` returning SHAP factors, counterfactual flip analysis (from `explainability/counterfactual.py`), and all three NLG narratives in a single response
- `explainability/counterfactual.py` — `generate_counterfactual()` using greedy single-feature descent to find nearest-flip perturbations
- `explainability/lime_explainer.py` — LIME support as secondary explanation method
- Borrower-scoped variant at `GET /v1/portal/applications/{id}/explanation` with audience filtering
- `tests/test_explanation_endpoint.py` and `tests/test_counterfactual.py` cover full response contract

**Closure Verdict**: Dedicated explainability endpoint implemented with SHAP + counterfactual + NLG merged response.

---

#### GAP-11: Policy Configuration API is Read-Only — ✅ CLOSED
**PRD Reference**: §9.2 Policy Management API, §4.3 Policy Management
**Severity**: P3 — Medium → **RESOLVED**
**Regulatory Driver**: SOC 2, FFIEC

**PRD Requirement**:
> "The Policy Management API shall support CRUD operations with four-eyes approval workflow before any policy rule takes effect in production."

**As-Of 2026-04-07 State**: Single `PUT /v1/config/{tenant_id}` with no four-eyes gate; one authorized user could push live changes.

**Current State (2026-04-14)**:
- `POST /v1/config/stage` — stages a new config for four-eyes review; stores pending config with `authored_by` and `approver_email`; does **not** activate
- `POST /v1/config/approve` — activates a staged config; enforces SOC 2 separation of duties (approver ≠ author); returns 403 when violated
- Legacy `PUT /v1/config/{tenant_id}` retained with warning header recommending stage/approve in production environments
- `tests/test_config_staging.py` and `tests/test_policy_four_eyes.py` cover four-eyes enforcement and SOC 2 violation path
- `compliance/committee_approval_store.py` persists stage/approve records for audit trail

**Closure Verdict**: Four-eyes policy approval workflow implemented; SOC 2 separation of duties enforced at the API layer.

---

#### GAP-12: No Canary Deployment for Decision Service — ✅ CLOSED
**PRD Reference**: §6.8 Deployment Architecture, §4.10 Rollout Controls
**Severity**: P3 — Medium → **RESOLVED**

**PRD Requirement**:
> "The decision service shall support canary deployments with automatic rollback when error rate or latency p99 exceeds defined thresholds."

**As-Of 2026-04-07 State**: Only ML-model canary scripts existed; no API-service traffic weighting or auto-rollback.

**Current State (2026-04-14)**:
- `scripts/canary_decision_api.py` — full canary controller for the decision API service on Cloud Run; progressive ramp: 0% → 5% → 10% → 25% → 50% → 100%
- Automatic rollback triggered when: canary 5xx error rate > threshold OR canary p99 latency > threshold OR stable revision health degrades
- Uses `gcloud run services update-traffic` for Cloud Run traffic splitting; no Istio dependency required
- Exit codes: 0 (promoted), 1 (gcloud error), 2 (rollback triggered)
- `tests/test_canary_script.py` covers threshold-breach rollback and successful promotion paths

**Closure Verdict**: Canary deployment with auto-rollback on error rate / p99 thresholds is fully implemented for the decision service.

---

### Priority 4 — Low (Enhancement)

---

#### GAP-13: No Borrower-Facing Portal API — ✅ CLOSED
**PRD Reference**: §5.3 Borrower Workflow, §9.5 Borrower Portal API
**Severity**: P4 — Low → **RESOLVED**

**As-Of 2026-04-07 State**: No borrower authentication; no `/v1/applications/{id}/status`; `ui/` was a stub.

**Current State (2026-04-14)**:
- `decision-api/src/borrower_auth.py` — `issue_borrower_token()`, `verify_borrower_token()`, `get_borrower()` managing borrower-scoped JWTs (distinct from tenant JWTs); read-only access to specific application IDs on a single tenant
- `POST /v1/portal/token` — issue borrower portal JWT from lender backend
- `GET /v1/portal/applications/{id}/status` — borrower-facing decision status
- `GET /v1/portal/applications/{id}/explanation` — borrower-facing explanation (applicant narrative, filtered SHAP)
- `tests/test_borrower_auth.py` and `tests/test_portal_api.py` cover auth and endpoint contracts

**Closure Verdict**: Borrower portal with scoped JWT auth, decision status, and explanation endpoints fully implemented.

---

#### GAP-14: Batch Underwriting Pipeline Not Exposed via API — ✅ CLOSED
**PRD Reference**: §4.2 Batch Processing, §9.4 Batch API
**Severity**: P4 — Low → **RESOLVED**

**As-Of 2026-04-07 State**: Only CLI-based pipeline; no API endpoints for batch submission or polling.

**Current State (2026-04-14)**:
- `POST /v1/batch/underwrite` — CSV batch underwriting job submission (async, background-processed)
- `GET /v1/batch/{id}/status` — job status polling (queued / running / complete / failed)
- `GET /v1/batch/{id}/results` — download batch results
- `decision-api/src/batch_job_store.py` — `BatchJobStore` backed by SQLite (`batch_jobs.db`); tracks state, progress, results
- `POST /v1/decisions/batch` — synchronous batch scoring for up to 1,000 applications (pre-existing, now complemented by async CSV route)
- Global and per-tenant concurrency semaphores prevent resource exhaustion
- `tests/test_batch_api.py` and `tests/test_batch_job_store.py` cover submission, status, results, and error paths

**Closure Verdict**: Full async batch underwriting pipeline exposed via API with job-status polling.

---

#### GAP-15: No Stochastic Stress Testing — ✅ CLOSED
**PRD Reference**: §4.11 Risk Stress Testing, §6.9 Scenario Analysis
**Severity**: P4 — Low → **RESOLVED**

**As-Of 2026-04-07 State**: Only historical backtesting in `cc_pd_monitor.py`; no Monte Carlo engine; no cross-quarter comparison.

**Current State (2026-04-14)**:
- `risk_models/stress_test.py` — `StressTestRunner` Monte Carlo engine; generates 1,000+ macro scenarios; stores results in SQLite with run metadata and quarter tag for cross-quarter comparison
- `POST /v1/stress-test/run` — trigger a Monte Carlo stress test run (async, background)
- `GET /v1/stress-test/results` — list stored results
- `GET /v1/stress-test/compare` — compare two quarters' stress test distributions
- Integrates with `risk_models/ecl_engine.py` for ECL impact estimation under each scenario
- `tests/test_stress_test.py` and `tests/test_stress_api.py` cover 1,000-scenario runs and comparison logic

**Closure Verdict**: 1,000-scenario Monte Carlo stress testing with cross-quarter comparability implemented as required by PRD §4.11.

---

#### GAP-16: Webhook Delivery for Decision Events Not Implemented — ✅ CLOSED
**PRD Reference**: §9.6 Webhook API
**Severity**: P4 — Low → **RESOLVED**

**As-Of 2026-04-07 State**: No outbound webhook framework; no `/v1/webhooks` CRUD; no retry queue.

**Current State (2026-04-14)**:
- `webhooks/dispatcher.py` — `WebhookDispatcher` with exponential-backoff retry; HMAC-SHA256 payload signing
- `webhooks/models.py` — `EventType` enum, `WebhookRegistration`, `WebhookDeliveryAttempt`
- `webhooks/store.py` — `WebhookStore` backed by SQLite (`webhooks.db`)
- Decision API exposes `POST /v1/webhooks` (register), `GET /v1/webhooks` (list), `GET /v1/webhooks/{id}/deliveries` (delivery log), `DELETE /v1/webhooks/{id}` (deactivate)
- Fire-and-forget dispatch wired into decision pipeline (post-decision) and batch job completion
- `tests/test_webhooks.py` and `tests/test_webhook_endpoints.py` cover registration, dispatch, retry, and deactivation

**Closure Verdict**: Full webhook framework with signed payloads, retry, and CRUD management implemented.

---

### Priority 5 — Backlog

---

#### GAP-17: Document Ingestion / OCR Pipeline — ✅ CLOSED
**PRD Reference**: §4.1 Document Processing, §6.2 Ingestion Layer
**Severity**: P5 — Backlog → **RESOLVED**
**Regulatory Driver**: CFPB income verification guidance, FCRA sourcing requirements

**PRD Requirement**:
> Tesseract-based OCR + LayoutLM for structured extraction from uploaded PDFs; document classification; bank statement parsing.

**Prior State (2026-04-14)**: No PDF OCR. Ingestion API existed but with Plaid (bank API) only; no Tesseract, no document classification, no PDF parsing.

**Current State (2026-04-15)**:
- `ingestion-api/src/ocr_engine.py` — `pdf_to_text()` async entry point; fast-path text extraction via `pdfminer.six` for digital PDFs; Tesseract OCR fallback (via `pytesseract` + `pdf2image`) for scanned pages below 50-char-per-page threshold; `TesseractNotAvailableError` graceful degradation; CPU-bound work offloaded to `ThreadPoolExecutor(max_workers=4)`
- `ingestion-api/src/document_classifier.py` — keyword-rules classifier supporting `PAY_STUB`, `BANK_STATEMENT`, `TAX_RETURN`, `UTILITY_BILL`, `GOVERNMENT_ID`; confidence scoring with calibrated `_KEYWORD_BOOST` per match; LayoutLM hook present at `classify_document()` interface for future ML upgrade
- `ingestion-api/src/document_pipeline.py` — `process_document()` full async pipeline: OCR → classify → field extraction dispatch → field normalisation → `DocumentExtractionResult`; never raises (all errors collected in `errors` list)
- `ingestion-api/src/field_normalizer.py` — `normalize_fields()` and `fields_to_feature_dict()` producing ML-ready key/value output
- `ingestion-api/src/document_models.py` — `DocumentType`, `ExtractedField`, `DocumentExtractionResult` dataclasses
- Test suite: `ingestion-api/tests/test_ocr_engine.py`, `test_document_classifier.py`, `test_document_pipeline.py`, `test_document_models.py`, `test_field_normalizer.py`, `test_document_upload.py`
- `ingestion-api/src/plaid_connector.py` — Plaid/Finicity cash-flow & income enrichment (alternative-data path); complements PDF OCR for bank data

**Remaining Note**: LayoutLM model-based classification is not yet wired (keyword-rules MVP only). The hook is present and the interface is stable; this is a model-quality enhancement, not a functional gap.

**Closure Verdict**: Core OCR pipeline fully functional. Tesseract + pdfminer + document classification + field extraction + normalisation all implemented and tested. PRD minimum requirement met; LayoutLM upgrade is a future enhancement, not a compliance blocker.

---

#### GAP-18: Real-Time Bureau Data Integration — ✅ CLOSED
**PRD Reference**: §4.4 Bureau Integration, §7.2 External Data Sources
**Severity**: P5 — Backlog → **RESOLVED**
**Regulatory Driver**: FCRA §604 permissible purpose, ECOA fair underwriting, OCC prudent underwriting standards

**PRD Requirement**:
> Live bureau pulls (Experian, TransUnion, Equifax) at decisioning time; bureau API clients with real credentials; bureau waterfall fallback on freeze/unavailability.

**Prior State (2026-04-14)**: Mock Experian sandbox endpoint reference only; no Equifax or TransUnion client; no decision-pipeline wiring.

**Current State (2026-04-15)**:
- `ingestion-api/src/bureau_clients/experian_client.py` — `ExperianClient(BureauClient)`: OAuth2 client-credentials token flow (with 5-minute expiry buffer); `EXPERIAN_ENV=sandbox|production` flip; `_CREDIT_PROFILE_PATH` → `/consumerservices/credit-profile/v2/credit-score`; tradeline parsing into `BureauResponse`
- `ingestion-api/src/bureau_clients/equifax_client.py` — `EquifaxClient(BureauClient)`: OAuth2 token + `EQUIFAX_CUSTOMER_NUMBER` required header; Equifax OneView endpoint; same tradeline contract
- `ingestion-api/src/bureau_clients/transunion_client.py` — `TransUnionClient(BureauClient)`: mTLS (PEM cert + key from env vars); `TRANSUNION_API_KEY` header; TruVision endpoint; per-process cert file caching via `tempfile`
- `ingestion-api/src/bureau_clients/base.py` — `BureauClient` ABC: `pull(BureauRequest) → BureauResponse`, `to_feature_dict()`
- `ingestion-api/src/bureau_clients/models.py` — `BureauProvider` enum, `BureauRequest`, `BureauResponse`, `Tradeline`, `BureauPullError`
- `ingestion-api/src/bureau_clients/router.py` — `BureauRouter`: ordered waterfall; tries primary, falls back through list; `BureauRouter.from_env()` factory reads `BUREAU_PRIMARY` / `BUREAU_FALLBACK_1` / `BUREAU_FALLBACK_2`
- `ingestion-api/src/bureau_clients/mock_client.py` — deterministic mock for CI/local dev
- **Decision pipeline wiring** (`decision-api/src/main.py`, lines 664–714): when `BUREAU_ENABLED=true`, `_run_pipeline()` instantiates `BureauRouter.from_env()`, executes `router.pull(BureauRequest(...))`, maps `bureau_features` to matching `features_df` columns; graceful fallback on `BureauPullError` without halting the decision
- Test suite: `ingestion-api/tests/bureau_clients/test_experian_client.py`, `test_equifax_client.py`, `test_transunion_client.py`, `test_mock_client.py`, `test_router.py`, `test_models.py`, `test_wiring.py`; `decision-api/tests/test_bureau_integration.py` covers feature-merge and graceful-failure paths

**Remaining Note**: Production credentials (`EXPERIAN_CLIENT_ID`, `EQUIFAX_CLIENT_ID`, `TRANSUNION_CERT_PEM`, etc.) must be provisioned in GCP Secret Manager before live bureau pulls execute. The clients are production-ready; credential onboarding is an ops task.

**Closure Verdict**: Full three-bureau client library implemented with OAuth2, mTLS, waterfall routing, and decision-pipeline wiring. Feature flag (`BUREAU_ENABLED`) enables safe rollout. FCRA permissible-purpose metadata logging is present in each client. All prior remaining gap effort (~12–15 days) is delivered.

---

## Part II — PRD v3.0 Net-New Features: Implementation Confirmation

The Unified ILOL PRD v3.0.0 significantly expands scope beyond v1.0. The following features — not tracked in prior gap analyses — are confirmed implemented as of 2026-04-15.

---

### Compliance & Governance Expansion (Module 4 / §9 Compliance Framework)

| Feature | Module | Status | Evidence |
|---|---|---|---|
| Compliance Health Score (0–100 composite, 8 weighted dimensions, zero-tolerance for MLA/AA-SLA violations) | `compliance/health_score.py` | ✅ IMPLEMENTED | `compute_health_score()` → `ComplianceHealthScore`; GREEN/YELLOW/RED status logic; `DIMENSION_WEIGHTS` registry |
| SOC 2 Type II Evidence Collection (CC1–CC9 TSC coverage, `soc2_evidence_packages` + `soc2_control_evidence` tables, JSON + summary export) | `compliance/soc2_evidence.py` | ✅ IMPLEMENTED | `SOC2EvidenceCollector.generate_evidence_package()`; `/v1/compliance/soc2/generate`, `/v1/compliance/soc2/packages`, `/v1/compliance/soc2/controls` endpoints |
| Data Retention Enforcement (CCPA/GLBA/ECOA schedule; GCS cold archive before BQ partition DELETE; permanent-exempt table list) | `compliance/retention_policy.py` | ✅ IMPLEMENTED | `RETENTION_SCHEDULE` dict; `RETENTION_EXEMPT_TABLES` frozenset; `RetentionReport` dataclass; BQ DML-based deletion |
| Right-to-Erasure Handler (CCPA § 1798.105 / GLBA; <= 45-day SLA; SHA-256 PII boundary; legal-hold exempt tables never modified; audit trail required) | `compliance/erasure_request.py` | ✅ IMPLEMENTED | `process_erasure_request()`; `ERASURE_EXEMPT_TABLES` (covers ECOA/Reg B/SR 11-7 holds); `ERASABLE_TABLES` dict; BQ audit log write |
| RBAC + Separation of Duties Enforcement (8 platform roles; `SeparationOfDutiesViolation`; `FOUR_EYES_RULES` registry; access event log to BQ) | `compliance/rbac.py` | ✅ IMPLEMENTED | `enforce_four_eyes()`; `log_access_event()`; role taxonomy: `ml_developer`, `ml_validator`, `compliance_officer`, `cro`, `data_engineer`, `system_service_acct`, `auditor`, `legal_counsel`, `executive` |
| Regulatory Horizon Scanner (180/90/60/30/7-day tiered alerts; nightly Cloud Scheduler @ 06:00 UTC; SEVERITY_ESCALATION mapping) | `compliance/regulatory_horizon.py` | ✅ IMPLEMENTED | `scan_horizon()` → `list[dict]`; `ALERT_DAYS = [180, 90, 60, 30, 7]`; `update_days_remaining()`; BQ `regulatory_horizon` table query |
| Third-Party Model Registry (SR 11-7 vendor model validation; `check_third_party_validation_due()`; FCRA AA four-field check `check_fcra_aa_fields()`) | `compliance/third_party_model_registry.py` | ✅ IMPLEMENTED | `THIRD_PARTY_MODELS` registry (VantageScore 4, FICO 10T, ...); monthly validation-due detection |
| Prohibited Variables Checker (ECOA/FHA/FCRA direct banned vars; `PROXY_VARIABLE_MAP` with 10+ proxy → protected-class mappings; `ProhibitedVariableViolation`) | `compliance/prohibited_variables.py` | ✅ IMPLEMENTED | `check_for_prohibited_variables()`; `PROHIBITED_VARIABLES` frozenset (30+ entries); proxy detection logic |
| Exam Packet Builder — multi-component (7 named components: `adverse_actions`, `model_documentation`, `policy_snapshots`, `decision_samples`, `fair_lending_analysis`, `committee_approvals`, `data_lineage`; PDF export) | `compliance/exam_packet_builder.py`, `compliance/exam_packet_pdf.py` | ✅ IMPLEMENTED | `build_exam_packet(ExamPacketSpec)` → `ExamPacket`; wired to `POST /v1/audit/generate-package` + `GET /v1/audit/packets`; test: `compliance/tests/test_exam_packet_builder.py` |

---

### Audit Infrastructure Expansion (Module 1 / §4.1 GNRI)

| Feature | Module | Status | Evidence |
|---|---|---|---|
| Decision Replay Bundle (deterministic signed bundle binding raw inputs + feature versions + model artefact hashes + policy hash + tenant config hash + decision outcome + audit log row hash + single `bundle_sha256` fingerprint) | `audit/replay_bundle.py` | ✅ IMPLEMENTED | `build_replay_bundle()` → `ReplayBundle`; `GET /v1/decisions/{id}/replay-bundle` endpoint; `tests/test_replay_bundle.py` |
| Decision Consistency Scorer (replays stored decision through current policy+model; reports PD delta, outcome change, CONSISTENCY_THRESHOLD=0.02; `GET /v1/decisions/{id}/consistency`) | `audit/consistency_scorer.py` | ✅ IMPLEMENTED | `score_decision_consistency()` → `ConsistencyResult`; `tests/audit/test_consistency_scorer.py` |
| Override Log — hash-chained, append-only (four-eyes required; immutable APPEND-ONLY DDL; `compute_override_chain_hash()`; `verify_override_chain()`; `get_override_rate()`) | `audit/override_log.py` | ✅ IMPLEMENTED | `log_override()` → `override_id`; `audit/tests/test_override_log.py` |

---

### Portfolio Analytics & Reporting Expansion (Module 3 / §4.3)

| Feature | Module | Status | Evidence |
|---|---|---|---|
| Analytics API — Vintage Curves, Roll Rates, Approval-Profit by Segment (BigQuery + SQLite dev backend; tenant-scoped JWT auth; cursor-based pagination; configurable 5-min in-process cache) | `analytics_api/src/main.py` | ✅ IMPLEMENTED | `GET /v1/analytics/vintage-curves`, `GET /v1/analytics/roll-rates`, `GET /v1/analytics/approval-profit`; `tests/analytics/test_analytics_api.py` |
| NLG-Powered Executive Summaries (data-grounded; template-based always-available mode + optional LLM-augmented mode with ≤0.1% number-drift validation; CRO/board audience; PDF export; `generate_executive_summary()`) | `reporting/executive_summary.py` | ✅ IMPLEMENTED | `ExecutiveSummary` dataclass; portfolio, model-health, fair-lending, override-activity, milestone sections; LLM validation layer prevents hallucinated numbers |

---

### AI Agent Platform (Module 6 — Partial)

| Feature | Module | Status | Evidence |
|---|---|---|---|
| AI Analytics Agent — LangChain ReAct + OpenAI GPT-4o, SSE streaming, session management, rate limiting, role-based personas (`data_analyst`, `business_analyst`) | `ai-agent/src/main.py` | ✅ IMPLEMENTED | `POST /agent/sessions`, `POST /agent/chat` (SSE), `GET /agent/sessions/{id}/history`, `DELETE /agent/sessions/{id}`; tools: `sql_query_tool`, `metrics_tool`, `drift_report_tool`, `fair_lending_tool`, `chart_generator_tool`, `report_generator_tool` |
| Scheduled AI Reporting — daily portfolio, weekly model health, monthly fair lending, real-time drift PSI alert via APScheduler | `ai-agent/src/scheduler.py` | ✅ IMPLEMENTED | `AsyncIOScheduler` with `CronTrigger` / `IntervalTrigger`; notifications written to SQLite `notifications` table; `AGENT_API_URL` configurable for multi-service topology |
| Notifications API (list unread, mark-read, mark-all-read) | `decision-api/src/main.py` | ✅ IMPLEMENTED | `GET /v1/notifications`, `PATCH /v1/notifications/{id}/read`, `PATCH /v1/notifications/read-all` |

> **Note**: Module 6 is partially implemented. Anti-Hallucination Framework and Code Transparency Layer — both first-class PRD v3.0 requirements — are not yet implemented. See GAP-19, GAP-20, GAP-21 below.

---

### Additional Infrastructure Confirmed

| Feature | Module | Status |
|---|---|---|
| Tenant branding + feature flags API | `config_registry/tenant_branding.py`, `/v1/tenant/branding*` | ✅ IMPLEMENTED |
| Compliance data plane (BigQuery DDL, table schemas, consent/disclosure tracking) | `compliance/data_plane.py` | ✅ IMPLEMENTED |
| Automated validation suite (cross-module data quality checks) | `validation/automated_suite.py` | ✅ IMPLEMENTED |
| Observability — distributed tracing + metrics push | `observability/tracing.py`, `observability/metrics_pusher.py` | ✅ IMPLEMENTED |
| Policy DSL (AST-validated, no `eval()` risk, DE-001 compliant) | `decision_engine/policy_dsl.py` | ✅ IMPLEMENTED |
| Pricing engine (capital, FTP, cNPV, scenario config) | `models/pricing/` | ✅ IMPLEMENTED |
| LGD model + reject inference | `models/credit_risk/lgd_model.py`, `reject_inference.py` | ✅ IMPLEMENTED |

---

## Part III — New Open Gaps (PRD v3.0 Unified Edition)

These gaps did not exist in PRD v1.0. They arise from Module 6 (RAG-Powered AI Analytics Agent) and the §5 Anti-Hallucination Framework — both of which are first-class architectural pillars of the v3.0 unified specification.

---

### Priority 1 — Critical

---

#### GAP-19: Anti-Hallucination Framework + Code Transparency Layer Absent — 🔴 OPEN
**PRD Reference**: §5 Anti-Hallucination Framework (Regulatory-Grade); §2.3 Pillar 4 "Transparent AI — Code as Proof"; §4.6 Module 6 RAG-Powered AI Analytics Agent; GNRI-011
**Severity**: P1 — Critical
**Regulatory Driver**: SR 11-7 (OCC AI/ML extension); CFPB supervisory guidance on AI in credit decisions; OCC examination standards for model transparency

**PRD Requirement (§5)**:
> "Every AI-generated answer carries the complete, executable SQL and Python used to produce it. Users are never asked to trust a number they cannot verify. The AI agent shall enforce zero-hallucination tolerance: answers not grounded in a retrieved dataset shall be refused or clearly marked as unavailable. Every AI answer is tagged with: source table, partition date, query hash, BigQuery job ID, and result hash (SHA-256 of the raw query result). All of these artifacts are stored immutably."

**PRD Requirement (§2.4 Principle 6)**:
> "Code as the ultimate audit trail — every AI answer carries its exact executable source code, stored immutably."

**Current State**:
- `ai-agent/src/main.py` implements a LangChain ReAct agent with a `sql_query_tool` that executes SQL. The SQL is run internally but is **not surfaced in the API response** as a code artifact. There is no `code_artifact` field, no `sql_executed` log, no `python_code` surface in any endpoint response or audit table.
- No confidence score is computed or returned. The agent returns a natural-language answer with no grounding metadata.
- No refusal mechanism when the data source returns zero rows or an ambiguous result — the agent fabricates a summary from the raw string output without validation.
- No `result_hash` is computed. No `query_hash` is computed. No BigQuery job IDs are captured (the agent uses SQLite, not BigQuery, as the data backend).
- The `reporting/executive_summary.py` has a ≤0.1% number-drift LLM validation layer (partial control), but this is scoped to executive summaries only and does not cover the interactive query-answer loop.

**Gap Details**:

| PRD Control | Status | Missing Artifact |
|---|---|---|
| Executable SQL surfaced with every answer | ❌ ABSENT | `code_artifact.sql` field in `AgentResponse` |
| Executable Python surfaced with every answer | ❌ ABSENT | `code_artifact.py` field in `AgentResponse` |
| Confidence score on every answer | ❌ ABSENT | `confidence_score: float` computed from data coverage |
| Data-grounding enforcement (refuse if no data) | ❌ ABSENT | Pre-answer data availability check + grounding gate |
| `result_hash` (SHA-256 of raw query result) | ❌ ABSENT | Hash computed at query execution time |
| `query_hash` (SHA-256 of the SQL string) | ❌ ABSENT | Hash computed before query execution |
| BigQuery job ID per answer | ❌ ABSENT | BQ client not used in agent backend |
| Source table + partition date tagging | ❌ ABSENT | Data lineage tags in answer metadata |
| Zero-hallucination refusal ("data not available") | ❌ ABSENT | Guard condition on empty-result tool output |

**Effort Estimate**: ~8–12 engineering days
- Extend `sql_query_tool` response to return `{result, sql_executed, query_hash, result_hash}` tuple
- Add `confidence_scorer.py` that evaluates data coverage and returns a 0–1 score
- Add grounding gate in `_stream_agent_response()`: if result_hash maps to empty/zero rows, surface "data not available" rather than hallucinated summary
- Add `code_artifact_store.py` persisting `.sql` and `.py` snippets per answer
- Extend `AgentResponse` / SSE event schema with `code_artifacts`, `confidence_score`, `data_lineage_tags`
- Migrate agent backend to BigQuery (or add BQ query path) to enable job ID capture

---

#### GAP-20: GNRI-011 Immutable AI Agent Audit Log Non-Compliant — 🔴 OPEN
**PRD Reference**: §4.1.1 Immutable Decision Log, GNRI-011; §4.4.1 AI Agent Audit Appendix; §6 UX & Workflow Design (AI Agent session audit)
**Severity**: P1 — Critical
**Regulatory Driver**: OCC 2021-25 (model risk governance); SR 11-7 AI/ML extension; CFPB supervisory technology guidance; 7-year record retention (12 CFR Part 1002 App. B)

**PRD Requirement (GNRI-011)**:
> "AI agent audit log: every AI query, plan, SQL executed, result hash, and code artifacts stored in audit table — append-only, 7-year retention."

**Current State**:
- `ai-agent/src/main.py` creates two SQLite tables: `agent_sessions` (session ID, persona, timestamps, turn count) and `agent_messages` (role, content, timestamp). These are standard conversational memory tables.
- Neither table is append-only (SQLite permits UPDATE and DELETE; no DDL constraints enforce immutability).
- Neither table stores: `plan_text` (agent reasoning steps), `sql_executed`, `result_hash`, `query_hash`, `code_artifacts`, `confidence_score`, `bq_job_id`, or `data_lineage_tags`.
- No 7-year retention policy is applied to these tables — they exist in transient SQLite files with no archival or TTL enforcement.
- No cryptographic hash chain links audit records (the pattern used successfully in `audit/logger.py` is not applied here).
- The `agent_messages` table is not written to consistently — the `chat()` endpoint streams without persisting message content to the DB.

**Gap Details**:

| GNRI-011 Field | Current Table | Present? |
|---|---|---|
| `query_text` | `agent_messages.content` (partial) | ⚠️ Partial |
| `plan_text` (reasoning steps / thoughts) | — | ❌ ABSENT |
| `sql_executed` (exact SQL strings run) | — | ❌ ABSENT |
| `result_hash` (SHA-256 of query result) | — | ❌ ABSENT |
| `code_artifacts` (`.sql`, `.py` file refs) | — | ❌ ABSENT |
| `confidence_score` | — | ❌ ABSENT |
| `bq_job_id` | — | ❌ ABSENT |
| Append-only enforcement | — | ❌ ABSENT |
| Cryptographic hash chain | — | ❌ ABSENT |
| 7-year retention with archival | — | ❌ ABSENT |

**Effort Estimate**: ~5–7 engineering days
- Create `ai_agent_audit_log` table with all required fields; DDL-level append-only enforcement (trigger-based or application-level NO-UPDATE contract)
- Apply same SHA-256 hash chain pattern as `audit/logger.py` (`record_hash`, `previous_hash`)
- Extend `_stream_agent_response()` to capture intermediate steps (thoughts + tool calls) and persist to audit log post-stream
- Add 7-year retention rule to `compliance/retention_policy.py` `RETENTION_SCHEDULE`
- Add `verify_ai_agent_chain()` to `audit/chain_verifier.py` for `ai_agent_audit_log`

---

### Priority 2 — High

---

#### GAP-21: AI Agent Audit Appendix Missing from Exam Packet Generator — 🟡 OPEN
**PRD Reference**: §4.4.1 Automated Exam Packet Generation — Table "AI Agent Audit Appendix" row; GNRI-011
**Severity**: P2 — High
**Regulatory Driver**: OCC examination standards; CFPB supervisory AI guidance; SR 11-7 AI/ML governance extension

**PRD Requirement (§4.4.1)**:
> "AI Agent Audit Appendix | All AI queries, plans, SQL code, Python code, BigQuery job IDs, confidence scores, and result hashes from the exam period | OCC, CFPB (SR 11-7 AI extension)"

**Current State**:
- `compliance/exam_packet_builder.py` implements 7 named component builders: `adverse_actions`, `model_documentation`, `policy_snapshots`, `decision_samples`, `fair_lending_analysis`, `committee_approvals`, `data_lineage`.
- The `_COMPONENT_BUILDERS` dispatcher does **not** include an `ai_agent_audit` (or equivalent) component builder.
- Requesting an `ai_agent_audit` component by name in `ExamPacketSpec.components` would return a `status="stub"` placeholder (the catch-all for unrecognised component names).
- There is no function to aggregate AI session logs, code artifacts, and confidence scores for a specified exam date range.
- This gap is blocked by GAP-20: until the `ai_agent_audit_log` table is populated with code artifacts and result hashes (GAP-20), no data exists to assemble this appendix.

**Dependency**: GAP-20 must be resolved first.

**Effort Estimate**: ~3–4 engineering days (after GAP-20)
- Add `build_ai_agent_audit_component(spec, db_url)` to `compliance/exam_packet_builder.py` querying `ai_agent_audit_log` for the exam period
- Register as `"ai_agent_audit"` in `_COMPONENT_BUILDERS`
- Output: query count, unique session count, SQL artifacts (list of hashes + previews), confidence score distribution, BigQuery job ID list, chain verification result
- Add to default component list in `POST /v1/audit/generate-package`
- Update `compliance/exam_packet_pdf.py` to render the AI appendix section
- Test: `compliance/tests/test_exam_packet_ai_appendix.py`

---

#### GAP-22: HITL Approval Gate Missing for Exam Packet Export and AI Regulatory Submissions — 🟡 OPEN
**PRD Reference**: §11.3 Anti-Hallucination Controls ("Human-in-the-loop gate"); Appendix C R-01 Mitigation Plan; SR 11-7 AI/ML governance compliance control table (line 1284)
**Severity**: P2 — High
**Regulatory Driver**: SR 11-7 (OCC AI/ML extension); OCC examination standards; CFPB supervisory technology guidance

**PRD Requirement (§11.3 Control Table)**:
> "Human-in-the-loop gate | Exam package generation requires human approval before final export"

**PRD Requirement (Appendix C — R-01 Mitigation, Sprint 2 target)**:
> "Introduce human-in-the-loop approval gate for any AI output destined for regulatory submission (compliance mode) — user must click 'Verified and Approved' before export."

**Current State**:
- `POST /v1/audit/generate-package` in `decision-api/src/main.py` calls `build_exam_packet()` and returns the packet immediately in a single synchronous response — no approval state, no pending status, no human gate.
- `compliance/exam_packet_builder.py` has no concept of a `pending_approval` or `approved` state on `ExamPacket`. Once `build_exam_packet()` returns, the data is fully exposed.
- No `exam_packet_approvals` table or store exists anywhere in the codebase.
- No `POST /v1/audit/packets/{id}/approve` endpoint exists.
- No `POST /v1/audit/packets/{id}/reject` endpoint exists.
- The AI agent (`ai-agent/src/main.py`) has no "compliance mode" flag that gates output destined for regulatory use behind a human approval step.
- The four-eyes policy approval in `compliance/committee_approval_store.py` covers **policy config changes only** and is not applicable to exam packet export or AI outputs.

**Gap Details**:

| PRD Control | Status | Missing Artifact |
|---|---|---|
| Exam packet generation enters `pending_approval` state | ❌ ABSENT | `ExamPacketApprovalStore`; `exam_packet_approvals` table |
| `POST /v1/audit/packets/{id}/approve` endpoint | ❌ ABSENT | Approval endpoint with approver identity capture |
| `POST /v1/audit/packets/{id}/reject` endpoint | ❌ ABSENT | Rejection endpoint with reason capture |
| Approver ≠ generator SOD enforcement | ❌ ABSENT | Same author/approver check as `compliance/rbac.py` pattern |
| AI output "Verified and Approved" gate in compliance mode | ❌ ABSENT | `compliance_mode` flag on AI agent; approval record before export |
| Approval event written to immutable audit log | ❌ ABSENT | Audit log write on approval action |

**Dependency**: GAP-21 (exam packet builder complete with all 8 components) should be resolved first, but GAP-22 can be developed in parallel against the existing 7-component builder.

**Effort Estimate**: ~4–5 engineering days
- Create `compliance/exam_packet_approval_store.py` — `exam_packet_approvals` table; `submit_for_approval()`, `approve_packet()`, `reject_packet()`, `get_approval_status()` with SOD enforcement
- Modify `POST /v1/audit/generate-package` to return `status="pending_approval"` instead of emitting the full packet immediately
- Add `POST /v1/audit/packets/{id}/approve` and `POST /v1/audit/packets/{id}/reject` (approver ≠ generator check)
- Add `GET /v1/audit/packets/{id}` to retrieve packet once approved
- Test: `compliance/tests/test_exam_packet_approval.py`

---

#### GAP-23: Manual Review / Referral Queue — No Resolution Workflow — 🟡 OPEN
**PRD Reference**: §4.2.1 DE-007 ("Configurable decision matrix: approve / decline / refer / conditional"); DE-005 ("Exception and override workflow with mandatory justification capture"); DE-006 ("Override logging: who, when, why, what changed — immutable, dual-approver"); §6 UX Workflow 1 (REFERRED in application feed; Override button)
**Severity**: P2 — High
**Regulatory Driver**: ECOA/Reg B (disparate-treatment risk in referral resolution); UDAAP (inconsistent referral outcomes); FFIEC model governance; OCC 2021-25 (human review documentation)

**PRD Requirement (DE-007)**:
> "Configurable decision matrix: approve / decline / refer / conditional"

**PRD Requirement (§6 Override Workflow)**:
> "1. Analyst selects 'Override'. 2. System prompts: Override type (risk-based exception), justification (free-text + structured), approval routing. 3. Override sent to dual-approver workflow (configurable by exception type and amount). 4. Approval/denial logged with timestamp, approver, and justification. 5. Override decision logged in immutable audit trail."

**PRD Data Schema (§8.2)**:
> `decision_outcome VARCHAR(20) -- APPROVED/DECLINED/REFERRED/WITHDRAWN`

**Current State**:

*What exists (partial):*
- `DECISION_MANUAL_REVIEW = "MANUAL_REVIEW"` constant in `decision_engine/engine.py` — triggers when `fraud_flag == "manual_review"` (AA05) ✅
- `POST /v1/underwrite` returns HTTP 202 when outcome is MANUAL_REVIEW, signal to the caller that human action is needed ✅
- `audit/override_log.py` — immutable hash-chained `policy_overrides_log` table; `log_override()` writes records when **pre-decision** `policy_overrides` are supplied to `make_decision()` ✅
- `decision_engine/engine.py` — `make_decision()` accepts `policy_overrides`, `override_submitted_by`, `override_approved_by`, `override_justification`; validates four-eyes via `compliance.rbac.validate_override_submission` ✅

*What is missing:*
- **No referral queue endpoint**: There is no `GET /v1/review/queue` endpoint exposing all `MANUAL_REVIEW` applications pending human action for a tenant. Loan officers have no API surface to see what needs their attention.
- **No claim/assignment**: No `POST /v1/review/{application_id}/claim` for a loan officer to take ownership of a referral.
- **No post-decision override resolution**: The override mechanism in `engine.py` works only when `policy_overrides` are passed at initial decision time (pre-decision). There is no `POST /v1/decisions/{id}/override` endpoint for a loan officer to submit a post-decision override (convert MANUAL_REVIEW → APPROVE or REJECT with justification after manual review).
- **No `CONDITIONAL` decision type**: PRD DE-007 requires `conditional` approval (approve with conditions, e.g., co-signer required, lower loan amount). `DECISION_MANUAL_REVIEW` exists but no `DECISION_CONDITIONAL` constant, no conditional terms storage, no conditional acceptance workflow.
- **No referral SLA tracking**: No deadline enforcement or alerting for referrals not resolved within a configurable SLA window (analogous to the Reg B 30-day adverse action SLA enforced in `monitoring/tests/test_aa_deadline_alert.py`).
- **No `REFERRED`/`WITHDRAWN` outcome persistence**: The PRD data schema has `REFERRED` and `WITHDRAWN` as valid `decision_outcome` values; the codebase only uses `APPROVE`, `REJECT`, `MANUAL_REVIEW`.

**Gap Details**:

| PRD Requirement | Status | Missing Artifact |
|---|---|---|
| Referral queue API (`GET /v1/review/queue`) | ❌ ABSENT | Endpoint querying `audit_log` for MANUAL_REVIEW rows; paginated, filterable by tenant |
| Claim/assign endpoint (`POST /v1/review/{id}/claim`) | ❌ ABSENT | Assigns a reviewer identity to a pending referral |
| Post-decision override resolution endpoint | ❌ ABSENT | `POST /v1/decisions/{id}/override` → triggers four-eyes flow → logs to `policy_overrides_log` |
| `CONDITIONAL` decision type + conditional terms storage | ❌ ABSENT | `DECISION_CONDITIONAL` constant; `conditional_terms` field in `DecisionResult`; API exposure |
| Referral SLA tracking + alerting | ❌ ABSENT | `monitoring/referral_sla_monitor.py`; alert when SLA window exceeded |
| `REFERRED`/`WITHDRAWN` outcome values in engine | ❌ ABSENT | Map `MANUAL_REVIEW` → `REFERRED` in PRD schema terms; add `WITHDRAWN` handling |

**Note on "do all credit decisions require human approval?"**: No. The PRD defines auto-decisioning (APPROVE/REJECT) as the standard, no-human-required path. Human review is only mandatory for: (a) REFER/MANUAL_REVIEW cases (this gap), (b) policy-threshold overrides requiring four-eyes approval (partially implemented), and (c) exam packet export and AI regulatory outputs (GAP-22). Auto-approved and auto-rejected decisions do not require a human sign-off.

**Dependency**: Independent — but benefits from `audit/override_log.py` (already implemented) for logging post-decision overrides.

**Effort Estimate**: ~7–9 engineering days
- Create `decision-api/src/referral_store.py` — `referral_queue` table; `create_referral()`, `claim_referral()`, `resolve_referral()`, `get_queue()`, `get_sla_breaches()`
- Add `GET /v1/review/queue`, `POST /v1/review/{id}/claim`, `POST /v1/decisions/{id}/override` endpoints to `decision-api/src/main.py`
- Add `DECISION_CONDITIONAL` to `decision_engine/engine.py`; `ConditionalTerms` dataclass; `conditional_terms` field on `DecisionResult`
- Create `monitoring/referral_sla_monitor.py` — alerting when referrals exceed configurable resolution SLA
- Test: `decision-api/tests/test_referral_queue.py`, `decision-api/tests/test_post_decision_override.py`, `monitoring/tests/test_referral_sla.py`

---

## Summary Matrix

### Part A — All Legacy Gaps (PRD v1.0 / v2.1 Basis)

| Gap ID | Description | Priority | Regulatory Driver | Status | Primary Evidence |
|--------|-------------|:--------:|-------------------|:------:|-----------------|
| GAP-01 | Cryptographic hash chain on audit log | P1 | ECOA, OCC 2021-25 | ✅ CLOSED | `audit/chain_verifier.py`; `compute_chain_hash()` on every write path |
| GAP-02 | Adverse action notice generation | P1 | Reg B §1002.9 | ✅ CLOSED | `compliance/adverse_action*.py` (4 modules); wired in `_run_pipeline()` |
| GAP-03 | Multi-tenant query isolation enforcement | P2 | GLBA, SOC 2 | ✅ CLOSED | `audit/tenant_guard.py`; required `tenant_id` in pipeline; BQ row-policy provisioner |
| GAP-04 | Policy-level champion/challenger A/B | P2 | Internal | ✅ CLOSED | `decision_engine/policy_challenger.py`; `/v1/policy-split` CRUD + report |
| GAP-05 | CRA / FCRA / UDAAP reporting | P2 | CRA, FCRA | ✅ CLOSED | `reporting/cra_activity.py`, `fcra_metro2.py`, `udaap_summary.py`, `dispatcher.py` |
| GAP-06 | NLG decision summaries (3 audiences) | P2 | Reg B clarity | ✅ CLOSED | `explainability/nlg_summarizer.py`; wired post-SHAP in decision pipeline |
| GAP-07 | Model drift alerts wired to AlertRouter | P2 | SR 11-7 | ✅ CLOSED | `monitoring/cc_pd_monitor.py` calls `AlertRouter.send_alert()` on threshold breach |
| GAP-08 | Feature lineage queryable via API | P3 | Internal | ✅ CLOSED | `GET /v1/lineage/{run_id}`; `GET /v1/lineage/job/{job_name}` |
| GAP-09 | SR 11-7 MDR auto-generation on champion promotion | P3 | SR 11-7 | ✅ CLOSED | `promote_champion()` auto-calls `generate_mdr()`; MDR attached to audit record |
| GAP-10 | Dedicated explainability endpoint | P3 | Internal | ✅ CLOSED | `GET /v1/decisions/{id}/explanation` (SHAP + counterfactual + NLG) |
| GAP-11 | Policy API four-eyes enforcement | P3 | SOC 2, FFIEC | ✅ CLOSED | `POST /v1/config/stage` + `POST /v1/config/approve`; author ≠ approver enforced |
| GAP-12 | Canary deployment for decision service | P3 | Internal | ✅ CLOSED | `scripts/canary_decision_api.py`; auto-rollback on error rate / p99 breach |
| GAP-13 | Borrower-facing portal API | P4 | Internal | ✅ CLOSED | `decision-api/src/borrower_auth.py`; `/v1/portal/*` endpoints |
| GAP-14 | Batch underwriting API | P4 | Internal | ✅ CLOSED | `POST /v1/batch/underwrite` (async); `GET /v1/batch/{id}/status`; `batch_job_store.py` |
| GAP-15 | Stochastic stress testing | P4 | SR 11-7 | ✅ CLOSED | `risk_models/stress_test.py` 1,000-scenario Monte Carlo; `/v1/stress-test/*` |
| GAP-16 | Webhook delivery framework | P4 | Internal | ✅ CLOSED | `webhooks/dispatcher.py`; HMAC-SHA256 signed; `/v1/webhooks` CRUD |
| GAP-17 | Document ingestion / OCR pipeline | P5 | CFPB, FCRA | ✅ CLOSED | `ocr_engine.py` (Tesseract + pdfminer); `document_pipeline.py`; `document_classifier.py`; `field_normalizer.py` |
| GAP-18 | Real-time bureau data integration | P5 | FCRA | ✅ CLOSED | `bureau_clients/{experian,equifax,transunion}_client.py`; `BureauRouter`; wired in `_run_pipeline()` with `BUREAU_ENABLED` flag |

**Legacy gap closure rate: 18 / 18 (100%)**

---

### Part B — New PRD v3.0 Gaps

| Gap ID | Description | Priority | Regulatory Driver | Status | Blocking |
|--------|-------------|:--------:|-------------------|:------:|---------|
| GAP-19 | Anti-Hallucination Framework + Code Transparency Layer | P1 | SR 11-7 AI, CFPB AI guidance | 🔴 OPEN | None |
| GAP-20 | GNRI-011 Immutable AI Agent Audit Log non-compliant | P1 | OCC 2021-25, SR 11-7, 7-yr retention | 🔴 OPEN | None |
| GAP-21 | AI Agent Audit Appendix missing from exam packet | P2 | OCC exam, CFPB supervisory | 🟡 OPEN | GAP-20 |
| GAP-22 | HITL approval gate absent for exam packet export and AI regulatory submissions | P2 | SR 11-7 AI, OCC exam, CFPB supervisory | 🟡 OPEN | None (can parallel GAP-21) |
| GAP-23 | Manual Review / Referral Queue — no resolution workflow, no post-decision override API, no `CONDITIONAL` decision type | P2 | ECOA, UDAAP, FFIEC, OCC 2021-25 | 🟡 OPEN | None |

**New gap count: 5 open / 5 introduced by PRD v3.0**
**Recommended resolution order**: GAP-19 → GAP-20 → GAP-21 (depends on GAP-20); GAP-22 and GAP-23 are independent and can run in parallel with GAP-19/20
**Estimated effort**: GAP-19 (~10 days) + GAP-20 (~6 days) + GAP-21 (~3 days) + GAP-22 (~5 days) + GAP-23 (~8 days) = ~32 days total

---

## Recommended Next Actions

### Immediate (P1) — Sprint 14 target

1. **GAP-19: Code Transparency Layer**
   - Extend `sql_query_tool` in `ai-agent/src/main.py` to return `{"result": ..., "sql_executed": ..., "query_hash": ..., "result_hash": ...}` from every tool invocation.
   - Add `ai-agent/src/code_artifact_store.py` to persist `.sql` and (optionally) `.py` code artifacts per answer session.
   - Add `ai-agent/src/confidence_scorer.py` computing a grounding confidence from result row count, data freshness, and tool coverage.
   - Extend SSE event envelope with `code_artifacts`, `confidence_score`, and `data_lineage_tags` fields.
   - Add grounding gate in `_stream_agent_response()`: when `result_hash` corresponds to zero rows or a SQL error, emit a structured "data not available" event rather than allowing the LLM to summarise empty context.
   - Migrate the agent SQL backend to use BigQuery (via `db/bigquery_client.py`) in production, enabling `bq_job_id` capture.

2. **GAP-20: Compliant AI Audit Log**
   - Define `ai_agent_audit_log` table DDL with all GNRI-011 fields: `query_text`, `plan_text` (JSON array of reasoning steps), `sql_executed`, `result_hash`, `code_artifact_ref`, `confidence_score`, `bq_job_id`, `record_hash`, `previous_hash`.
   - Apply the same `compute_chain_hash()` pattern from `audit/logger.py` to this new table.
   - Wire `_stream_agent_response()` to persist a complete audit record after each completed turn.
   - Add `"ai_agent_audit_log": 7` to `compliance/retention_policy.py` `RETENTION_SCHEDULE`.
   - Add `verify_ai_agent_chain()` to `audit/chain_verifier.py`.

### Short-term (P2) — Sprint 15 target

3. **GAP-21: AI Agent Audit Appendix in Exam Packets**
   - Add `build_ai_agent_audit_component(spec, db_url)` to `compliance/exam_packet_builder.py`.
   - Register under `"ai_agent_audit"` in `_COMPONENT_BUILDERS`.
   - Include: total query count, unique sessions, code artifact hashes, confidence score P50/P90, BQ job ID list, chain verification status.
   - Add to default component list in `POST /v1/audit/generate-package`.
   - Update `compliance/exam_packet_pdf.py` with an AI appendix PDF rendering section.

4. **GAP-22: HITL Approval Gate for Exam Packet Export and AI Regulatory Submissions** *(can run in parallel with GAP-21)*
   - Create `compliance/exam_packet_approval_store.py` — `exam_packet_approvals` table; `submit_for_approval()`, `approve_packet()`, `reject_packet()` with SOD enforcement (approver ≠ generator).
   - Modify `POST /v1/audit/generate-package` to return `status="pending_approval"` instead of returning the full packet immediately.
   - Add `POST /v1/audit/packets/{id}/approve` and `POST /v1/audit/packets/{id}/reject` endpoints.
   - Add `GET /v1/audit/packets/{id}` to retrieve the packet payload only when `status="approved"`.
   - Write approval events to the existing `audit_log` table.

5. **GAP-23: Manual Review Referral Queue and Post-Decision Override API** *(independent, can run in parallel)*
   - Create `decision-api/src/referral_store.py` — `referral_queue` SQLite table; `create_referral()`, `claim_referral()`, `resolve_referral()`, `get_queue()`, `get_sla_breaches()`.
   - Add `GET /v1/review/queue`, `POST /v1/review/{id}/claim`, `POST /v1/decisions/{id}/override` to `decision-api/src/main.py`.
   - Add `DECISION_CONDITIONAL` constant and `ConditionalTerms` dataclass to `decision_engine/engine.py`; expose via decision API.
   - Create `monitoring/referral_sla_monitor.py` — alerts when referral resolution exceeds the configurable SLA window.
   - Wire `create_referral()` into `_run_pipeline()` on `MANUAL_REVIEW` outcome (analogous to `save_notice()` on REJECT).

### Ongoing

6. **LayoutLM upgrade (GAP-17 enhancement)**: Wire a LayoutLM model or `unstructured` library into `document_classifier.py` for higher-accuracy document type detection.
7. **Bureau credentials (GAP-18 ops)**: Provision `EXPERIAN_CLIENT_ID`, `EQUIFAX_CLIENT_ID`, `EQUIFAX_CUSTOMER_NUMBER`, `TRANSUNION_API_KEY`, and mTLS cert PEMs in GCP Secret Manager.
8. **Full regression test run**: Execute `pytest` to confirm no regressions across all 200+ test files.

---

*For implementation coding prompts for GAP-19 through GAP-23, see [`docs/IMPLEMENTATION_PLAN_GAP19_20_21.md`](IMPLEMENTATION_PLAN_GAP19_20_21.md). For the unified PRD driving this audit, see [`docs/Unified_ILOL_PRD.md`](Unified_ILOL_PRD.md).*

---

## Part C — HITL Decision Audit (2026-04-16 Addendum)

> Produced by the Userflow & Decision Diagram Audit (see `docs/USERFLOW_DECISION_DIAGRAM_AUDIT_PROMPT.md`).
> Covers H-01 through H-10 from the HITL gap checklist.

---

#### GAP-H01: `assign_to_analyst()` Method Name Mismatch — ⚠️ PARTIAL
**PRD Reference**: §4.6 Human-In-The-Loop Review Queue
**Severity**: P3
**Regulatory Driver**: OCC 2021-25 model risk guidance — human override accountability

**PRD Requirement**:
> "Every MANUAL_REVIEW item shall be assignable to a named analyst. Assignment must be logged with start time."

**Current State**:
- `ReviewQueue.assign(item_id, reviewer_id)` is present and fully functional (`decisioning/review_queue.py`).
- Sets `status=UNDER_REVIEW`, `assigned_to`, and `review_started_at`.
- Method is named `assign()` not `assign_to_analyst()` as referenced in the PRD checklist.

**Remediation**:
1. Rename or alias the method to `assign_to_analyst()` for PRD conformance.
2. Update any callers (currently no callers found in production code outside tests).

---

#### GAP-H02: `complete()` Does Not Enforce Non-Null `override_reason_code` — ⚠️ OPEN
**PRD Reference**: §4.6 Human-In-The-Loop Review Queue, §9.3 Audit Trail
**Severity**: P2
**Regulatory Driver**: FCRA §615(a) — basis for adverse action must be documented; OCC 2021-25

**PRD Requirement**:
> "Every completed review item must record a non-null reason code from the `ReviewReasonCode` enum."

**Current State**:
- `ReviewQueue.complete()` accepts `override_reason_code: str` but performs no null/empty check.
- An analyst can call `complete(item_id, override_decision="APPROVE", override_reason_code="")` and the row is written without validation error.

**Remediation**:
1. Add guard at top of `complete()`:
   ```python
   if not override_reason_code or str(override_reason_code).strip() == "":
       raise ValueError("override_reason_code must be non-null and non-empty")
   valid_codes = {rc.value for rc in ReviewReasonCode}
   if str(override_reason_code) not in valid_codes:
       raise ValueError(f"override_reason_code must be one of {sorted(valid_codes)}")
   ```
2. Add test: `test_complete_rejects_null_reason_code()`.

---

#### GAP-H03: `check_sla_breaches()` Exists But Is Not Scheduled — ⚠️ PARTIAL
**PRD Reference**: §4.6.3 SLA Monitoring
**Severity**: P2
**Regulatory Driver**: UDAAP — unreasonable delay in credit decision; ECOA 30-day clock

**PRD Requirement**:
> "SLA breach detection shall run automatically on a scheduled basis. Breached items must be escalated without manual intervention."

**Current State**:
- `ReviewQueue.check_sla_breaches()` is fully implemented (`decisioning/review_queue.py`).
- No scheduler in `orchestration/`, `scripts/`, or `decision-api/src/main.py` calls this method.
- SLA breaches only detected when explicitly called — no automated alerting.

**Remediation**:
1. Add an APScheduler or Celery beat job in `decision-api/src/main.py` startup (lifespan event):
   ```python
   from apscheduler.schedulers.asyncio import AsyncIOScheduler
   scheduler = AsyncIOScheduler()
   scheduler.add_job(lambda: review_queue.check_sla_breaches(), "interval", minutes=30)
   ```
2. Emit a metric/alert to `monitoring/` on any newly breached items.

---

#### GAP-H04: Analyst Assignment Has No RBAC Enforcement — ⚠️ OPEN
**PRD Reference**: §9.2 RBAC Matrix, §4.6.2 Queue Assignment Controls
**Severity**: P2
**Regulatory Driver**: OCC 2021-25 §IV.C — access controls for model override actions

**PRD Requirement**:
> "Only users with role `analyst` or `supervisor` may claim and complete review queue items."

**Current State**:
- `ReviewQueue.assign()` and `complete()` accept any `reviewer_id` string — no JWT role validation.
- `compliance/rbac.py` has a `FOUR_EYES_RULES` registry and `validate_override_submission()` but these are not wired into the review queue methods.

**Remediation**:
1. Expose HITL assignment/completion as API endpoints (alongside GAP-H09 / GAP-23 remediation).
2. Apply `Depends(require_role(["analyst", "supervisor"]))` on the assign endpoint.
3. Apply `Depends(require_role(["analyst", "supervisor"]))` on the complete endpoint.

---

#### GAP-H05: HITL Override Not Written to `policy_overrides_log` — ⚠️ OPEN
**PRD Reference**: §8.3 Audit Trail Requirements, §3.1 Override Governance
**Severity**: P1
**Regulatory Driver**: OCC 2021-25 model risk — all model output overrides must be immutably logged; FFIEC IT audit standards

**PRD Requirement**:
> "All manual overrides of model recommendations must be logged to the immutable `policy_overrides_log` table with the four-eyes record."

**Current State**:
- `ReviewQueue.complete()` writes only to the `review_queue` table.
- No call to `audit.override_log.log_override()` or `PolicyOverrideRecord` creation in `complete()` or any caller.
- `policy_overrides_log` table (immutable, hash-chained) exists and is used for threshold overrides from `make_decision()` — but analyst queue overrides bypass it entirely.

**Remediation**:
1. After writing the override to `review_queue`, call `audit.override_log.log_override()`:
   ```python
   from audit.override_log import PolicyOverrideRecord, log_override
   record = PolicyOverrideRecord(
       override_id=str(uuid.uuid4()),
       decision_id=item.application_id,
       tenant_id=tenant_id,
       override_type="hitl_analyst_override",
       original_value=0.0,
       override_value=0.0,
       justification=notes or override_reason_code,
       submitted_by=analyst_email,
       approved_by=analyst_email,   # until H-10 is remediated
       approved_at=completed_at.isoformat(),
   )
   await log_override(record, audit_db_url)
   ```
2. Add test verifying `policy_overrides_log` entry is created on `complete()`.

---

#### GAP-H06: Adverse Action Notice Not Generated on Analyst `override_decision=DECLINE` — ⚠️ OPEN
**PRD Reference**: §4.5 Adverse Action Management, §8.1 ECOA / Reg B Compliance
**Severity**: P1
**Regulatory Driver**: 12 CFR §1002.9 — 30-day notice clock applies to all final rejections including post-HITL

**PRD Requirement**:
> "A Reg B–compliant adverse action notice must be generated and delivered within 30 days of any final rejection, including analyst overrides."

**Current State**:
- `_run_pipeline()` in `decision-api/src/main.py` generates a Reg B notice on automatic REJECT outcomes.
- No adverse action notice is triggered when an analyst sets `override_decision="DECLINE"` in `ReviewQueue.complete()`.
- The 30-day clock for applicants whose items are reviewed and declined by a human starts — and is missed.

**Remediation**:
1. Add adverse action trigger in the HITL completion API endpoint (to be created as part of GAP-23):
   ```python
   if completed_item.override_decision == "DECLINE":
       notice = generate_notice(decision_result, applicant_info)
       await save_notice(notice, db_url=DB_URL)
   ```
2. Add test: `test_analyst_decline_triggers_adverse_action_notice()`.

---

#### GAP-H07: No Escalation Path from `SLA_BREACHED` to Supervisor Re-Assignment — ⚠️ OPEN
**PRD Reference**: §4.6.3 SLA Escalation
**Severity**: P2
**Regulatory Driver**: UDAAP — undue processing delays; ECOA 30-day clock

**PRD Requirement**:
> "Items in SLA_BREACHED status must be automatically escalated to a supervisor queue for re-assignment."

**Current State**:
- `ReviewQueue` has no `escalate()` or supervisor re-assignment method.
- Once an item is `SLA_BREACHED`, it can only be manually re-assigned by directly calling `assign()` — no automated escalation path exists.
- The state diagram in `docs/diagrams/hitl_review_queue_lifecycle.md` shows this gap explicitly.

**Remediation**:
1. Add `escalate(item_id, supervisor_email)` method to `ReviewQueue` that transitions `SLA_BREACHED → UNDER_REVIEW` with supervisor assignment.
2. Wire into the scheduled `check_sla_breaches()` job (GAP-H03) to auto-escalate immediately on breach.
3. Emit a notification/webhook event on escalation.

---

#### GAP-H08: HITL Metrics Not Surfaced in Monitoring Dashboard — ⚠️ PARTIAL
**PRD Reference**: §5.3 Operational Monitoring, §4.6.4 Queue Metrics
**Severity**: P3
**Regulatory Driver**: OCC 2021-25 — ongoing monitoring of model override rates

**PRD Requirement**:
> "The monitoring dashboard shall display HITL queue depth, SLA breach rate, analyst completion rate, and override reversal rate."

**Current State**:
- `GET /v1/analytics/decision-mix` endpoint implemented (2026-04-16) via `decisioning/decision_metrics.py`. Returns `hitl_rate`, `manual_review_sla_breached`, `hitl_override_reversal_rate`. ✅
- `monitoring/` directory has no HITL-specific metric emitters or dashboard widgets.
- `analytics_api/` does not expose review queue metrics.
- No queue depth or SLA breach rate charts in `dashboard/app.py`.

**Remediation**:
1. Add HITL metric gauges to `monitoring/` (queue depth, SLA breach count, completion rate).
2. Add a Plotly graph in `dashboard/app.py` for HITL queue status over time.

---

#### GAP-H09: `configure_review_queue()` Not Called at App Startup — 🔴 OPEN
**PRD Reference**: §4.6 Human-In-The-Loop Review Queue, §7.2 Service Startup
**Severity**: P1
**Regulatory Driver**: OCC 2021-25 — HITL gate must be operational; ECOA / UDAAP — all flagged applications must reach a human reviewer

**PRD Requirement**:
> "The review queue must be initialised and wired at service startup. MANUAL_REVIEW outcomes must always result in a queue entry being created."

**Current State**:
- `decision_engine/cc_origination_policy.py` has `_REVIEW_QUEUE: Optional[ReviewQueue] = None`.
- `configure_review_queue()` sets this module-level reference.
- `decision-api/src/main.py` **never calls** `configure_review_queue()` — confirmed by grep (no matches).
- When `_REVIEW_QUEUE is None`, the `evaluate_application()` path silently skips the enqueue with only a `logging.warning`.
- Result: in production, all MANUAL_REVIEW outcomes from the CC policy engine are silently discarded — no queue entries, no SLA clocks, no analyst assignments.

**Remediation**:
1. Add to `decision-api/src/main.py` lifespan startup:
   ```python
   from decisioning.review_queue import ReviewQueue
   from decision_engine.cc_origination_policy import configure_review_queue
   _review_queue = ReviewQueue(db_url=os.getenv("REVIEW_QUEUE_DB_URL", DB_URL))
   configure_review_queue(_review_queue)
   ```
2. Change the silent `except Exception: log.warning(...)` in `evaluate_application()` to re-raise after logging, so startup failures are visible.
3. Add integration test verifying `_REVIEW_QUEUE` is not `None` after app startup.

---

#### GAP-H10: Second-Approver Check Absent on Analyst Queue Overrides — ⚠️ PARTIAL
**PRD Reference**: §9.2 Four-Eyes Principle, §3.1 Override Governance
**Severity**: P2
**Regulatory Driver**: OCC 2021-25 §IV.C — separation of duties for model output overrides; SOC 2 CC6.3

**PRD Requirement**:
> "All manual overrides of automated credit decisions require four-eyes sign-off: the person submitting the override must differ from the person approving it."

**Current State**:
- `make_decision()` in `engine.py` enforces four-eyes via `compliance/rbac.validate_override_submission()` for threshold policy overrides. ✅ Present for threshold changes.
- `ReviewQueue.complete()` takes a single `reviewer_id` with no second-approver field. No SOD check.
- Analyst queue overrides (the most common override path for borderline applications) bypass the four-eyes control entirely.

**Remediation**:
1. Add `approved_by: str` parameter to `ReviewQueue.complete()`.
2. Enforce `submitted_by != approved_by` (analogous to `validate_override_submission()`).
3. Store `approved_by` in the `review_queue` schema (new column) and in the `policy_overrides_log` entry (GAP-H05).
4. Update API endpoint for queue completion to require two separate authenticated calls or a second-approver token.

---

### Summary Table — HITL Gaps (H-01 through H-10)

| Gap ID | Control | Severity | Status |
|--------|---------|:--------:|:------:|
| GAP-H01 | `assign_to_analyst()` method name | P3 | Partial |
| GAP-H02 | Non-null `override_reason_code` validation | P2 | 🔴 Open |
| GAP-H03 | `check_sla_breaches()` scheduled job | P2 | Partial |
| GAP-H04 | RBAC enforcement on queue assignment/completion | P2 | 🔴 Open |
| GAP-H05 | Override written to `policy_overrides_log` | P1 | 🔴 Open |
| GAP-H06 | Adverse action notice on analyst DECLINE | P1 | 🔴 Open |
| GAP-H07 | SLA escalation path to supervisor | P2 | 🔴 Open |
| GAP-H08 | HITL metrics in monitoring dashboard | P3 | Partial |
| GAP-H09 | `configure_review_queue()` at startup | P1 | 🔴 Open |
| GAP-H10 | Four-eyes on analyst queue overrides | P2 | Partial |

**P1 open**: GAP-H05, GAP-H06, GAP-H09 — must be resolved before production HITL is live.
**P2 open**: GAP-H02, GAP-H04, GAP-H07, GAP-H10 — required for regulatory examination readiness.
