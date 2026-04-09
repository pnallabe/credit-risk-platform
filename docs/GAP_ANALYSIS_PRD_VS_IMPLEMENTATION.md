# Gap Analysis: PRD vs. Implementation
**Document**: Integrated Lending Operating Layer (ILOL)
**PRD Reference**: `docs/PRD_INTEGRATED_LENDING_OPERATING_LAYER.md`
**Analysis Date**: 2026-04-07
**Analyst**: GitHub Copilot
**Status**: 18 gaps identified across 5 priority tiers

---

## Executive Summary

A systematic comparison of the ILOL PRD requirements against the current `credit-risk-platform` codebase identified **18 gaps**. Two are **Priority 1 (Critical)** — blocking regulatory compliance and auditability. Five are **Priority 2 (High)** — required for go-live readiness. The remaining gaps are Priority 3–5, addressed in subsequent development phases.

---

## Methodology

Each PRD section was mapped to concrete codebase artifacts via:
1. Full directory listing of all modules
2. Source-level examination of `audit/`, `compliance/`, `decision-api/`, `monitoring/`, `reporting/`, `orchestration/`, and `feature_pipeline/`
3. Cross-referencing PRD functional requirements (§4), system architecture (§6), data architecture (§7), compliance framework (§8), and API design (§9)

---

## Gap Inventory

### Priority 1 — Critical (Regulatory / Audit Integrity)

---

#### GAP-01: Cryptographic Hash Chain Missing from Audit Log
**PRD Reference**: §8.3 Audit Trail Requirements, §6.4 Immutable Audit Infrastructure
**Severity**: P1 — Critical
**Regulatory Driver**: 12 CFR Part 1002 (ECOA/Reg B), OCC 2021-25 model risk, FFIEC IT audit standards

**PRD Requirement**:
> "Every audit record shall be cryptographically chained to its predecessor using SHA-256. Any tampering shall be detectable via offline chain verification. The audit log must be append-only and tamper-evident."

**Current State**:
- `audit/logger.py` implements `log_decision()`, `log_portfolio_action()`, `get_audit_record()` and PII masking
- `_sha256()` helper exists but is only used for PII field masking (SSNs, account numbers)
- `_CREATE_AUDIT_TABLE` DDL has no `record_hash`, `previous_hash`, or `hash_algorithm` columns
- No `chain_verifier.py` module exists
- No migration path to add hash columns to existing tables

**Impact**:
- Audit records can be silently tampered with (UPDATE/DELETE in SQLite/PostgreSQL) with no detection
- OCC examination would find no tamper-evidence control — potential MRA finding
- Chain-of-custody cannot be established for ECOA adverse action disputes

**Remediation**:
See `docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md` — Prompts P1-A through P1-E

---

#### GAP-02: Adverse Action Notices Not Generated
**PRD Reference**: §4.5 Adverse Action Management, §8.1 ECOA / Reg B Compliance
**Severity**: P1 — Critical
**Regulatory Driver**: 12 CFR §1002.9 (notice timing), Reg B model notices C-1/C-2

**PRD Requirement**:
> "The system shall auto-generate Reg B–compliant adverse action notices within 30 days of a credit decision. Notices shall include the specific ECOA reason codes, creditor contact information, and CFPB disclosure language. PDF rendering and delivery tracking are required."

**Current State**:
- No `compliance/adverse_action*.py` files exist
- `compliance/engine.py` runs a compliance gate but returns a pass/fail, no notice object
- `decision-api/src/main.py` `_run_pipeline()` calls `log_decision()` at the end — no adverse action branch
- `decision_engine/engine.py` has `DECISION_REJECT = "REJECT"` but no post-reject notice hook
- `explainability/shap_explainer.py` returns `top_negative_factors` — not mapped to ECOA codes
- No `adverse_action_log` table in database schema
- `monitoring/alert_router.py` has no deadline-overdue alert

**Impact**:
- Consumer harm: applicants denied credit receive no legally required explanation
- Reg B enforcement exposure: CFPB can assess civil money penalties up to $10,000/violation (15 U.S.C. §1691e)
- No delivery tracking = no proof of compliance in examination

**Remediation**:
See `docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md` — Prompts P2-A through P2-G

---

### Priority 2 — High (Go-Live Readiness)

---

#### GAP-03: No Multi-Tenant Data Isolation at Query Layer
**PRD Reference**: §6.5 Multi-Tenant Architecture, §7.4 Data Isolation Controls
**Severity**: P2 — High
**Regulatory Driver**: GLBA §501(b), SOC 2 Type II CC6.3

**PRD Requirement**:
> "All data access must enforce tenant_id row-level scoping in every query. Cross-tenant data leakage must be architecturally impossible, not policy-dependent."

**Current State**:
- `orchestration/pipeline.py` accepts optional `tenant_id` but does not enforce it in all code paths
- `audit/logger.py` inserts `tenant_id` but `get_audit_record()` does not validate caller's tenant matches record tenant
- `db/bigquery_schema.py` defines `tenant_id` column in schemas but BigQuery row-level access policies not provisioned
- `decision-api/src/main.py` `verify_bearer()` extracts `tenant_id` from JWT but several internal helper functions bypass this, accepting `db_url` directly without tenant context

**Impact**:
- Latent cross-tenant data leak in edge cases (admin tokens, direct DB calls from analytics scripts)
- SOC 2 audit finding risk

---

#### GAP-04: Champion/Challenger Only at Model Level — No Policy-Level A/B
**PRD Reference**: §4.3 Policy Management, §6.3 Champion/Challenger Framework
**Severity**: P2 — High

**PRD Requirement**:
> "Champion/challenger routing shall operate at both the ML model layer and the underwriting policy rule layer independently, with per-tenant traffic split configuration."

**Current State**:
- `decisioning/champion_challenger.py` implements model-level champion/challenger with traffic splitting
- `decision_engine/policy_version_store.py` tracks policy versions (SQLite-backed) but has no traffic-split or challenger routing
- No policy-level A/B framework exists; policy versions are pinned per tenant, not split

**Impact**:
- Cannot safely test new policy rule sets in production without a full cutover
- Policy rollback is manual (`policy_version_store.rollback()`) with no automatic revert on metric regression

---

#### GAP-05: HMDA LAR Export Only — No CRA, FCRA, or UDAAP Reporting
**PRD Reference**: §8.4 Regulatory Reporting, §4.7 Compliance Reporting Suite
**Severity**: P2 — High
**Regulatory Driver**: 12 CFR Part 203 (HMDA), 12 U.S.C. §2901 (CRA), 15 U.S.C. §1681 (FCRA)

**PRD Requirement**:
> "The platform shall generate HMDA LAR, CRA activity reports, FCRA Metro 2 tradeline exports, and UDAAP monitoring summaries on configurable schedules."

**Current State**:
- `reporting/hmda_lar.py` — HMDA LAR export implemented
- No CRA reporting module
- No FCRA / Metro 2 export
- No UDAAP monitoring summary generator
- `monitoring/fair_lending.py` computes AIR and chi-squared stats but does not produce a report artifact

**Impact**:
- CRA exam preparedness gap — institutions subject to CRA cannot produce required activity reports
- FCRA compliance gap for any credit reporting to bureaus

---

#### GAP-06: No NLG Decision Summaries
**PRD Reference**: §4.6 Explainability & Customer Communication, §5.2 Loan Officer Workflow
**Severity**: P2 — High

**PRD Requirement**:
> "For each underwriting decision, the system shall produce a plain-language NLG summary suitable for (a) the loan officer dashboard, (b) the applicant-facing portal, and (c) the adverse action notice body."

**Current State**:
- `explainability/shap_explainer.py` returns structured `ExplanationResult` with `top_negative_factors`
- `ai-agent/src/main.py` runs a LangChain + GPT-4o agent for general Q&A — not wired to decision pipeline
- No `generate_decision_summary()` function exists
- No prompt templates for decision narration
- SHAP factors are not piped to any language model for narration

**Impact**:
- Loan officers receive raw SHAP codes with no human-readable interpretation layer
- Adverse action notices fall back to boilerplate reason codes — potential Reg B clarity issue

---

#### GAP-07: Model Drift Alerts Not Wired to Alert Router
**PRD Reference**: §4.8 Model Monitoring, §6.6 Alerting Infrastructure
**Severity**: P2 — High

**PRD Requirement**:
> "PSI > 0.20, KS drop > 0.05, or AUROC drop > 0.03 shall trigger a P1 alert to the model risk officer within 5 minutes via the configured alert channel."

**Current State**:
- `monitoring/cc_pd_monitor.py` computes PSI, KS, AUROC and detects thresholds
- `monitoring/alert_router.py` has `SlackWebhookChannel` and `EmailChannel` classes
- The two modules are **not connected** — `cc_pd_monitor.py` logs warnings to Python `logging` but never calls `alert_router.py`
- `AlertRouter` has no `send_alert()` public method (channels are instantiated but not exposed)

**Impact**:
- Model degradation can go undetected until next scheduled manual review
- SLA for drift notification (PRD: 5 minutes) cannot be met

---

### Priority 3 — Medium (Operational Completeness)

---

#### GAP-08: Feature Lineage Emitted but Not Queryable
**PRD Reference**: §7.3 Data Lineage, §6.7 Observability
**Severity**: P3 — Medium

**PRD Requirement**:
> "Feature lineage shall be queryable via API — each feature's upstream source, transformation, and version must be retrievable on demand."

**Current State**:
- `feature_pipeline/lineage.py` emits OpenLineage events to a configurable backend
- No query API exists to retrieve lineage for a given feature or run ID
- Lineage events are fire-and-forget; no local index

---

#### GAP-09: No SR 11-7 Model Documentation Auto-Generation for Champion Challenger
**PRD Reference**: §8.5 Model Governance, §4.9 Model Risk Management
**Severity**: P3 — Medium

**PRD Requirement**:
> "When a challenger model is promoted to champion, the system shall automatically generate an SR 11-7–compliant model card and attach it to the promotion audit record."

**Current State**:
- `compliance/generate_model_doc.py` generates SR 11-7 documents manually
- `decisioning/champion_challenger.py` `promote_champion()` does not call `generate_model_doc.py`
- No promotion-event hook exists in the champion/challenger framework

---

#### GAP-10: Explainability API Not Exposed in Decision API
**PRD Reference**: §9.3 Explainability Endpoints, §4.6 Explainability
**Severity**: P3 — Medium

**PRD Requirement**:
> "GET /v1/decisions/{id}/explanation shall return SHAP values, counterfactuals, and a narrative summary in a single response."

**Current State**:
- `explainability/shap_explainer.py` is called internally during `_run_pipeline()`
- SHAP values are stored in `audit_log.top_shap_factors` as JSON
- No dedicated `/v1/decisions/{id}/explanation` endpoint exists in `decision-api/src/main.py`
- `GET /v1/decisions/{id}/audit` returns the full audit record (including SHAP) but is not a focused explainability endpoint; no counterfactual generation

---

#### GAP-11: Policy Configuration API is Read-Only
**PRD Reference**: §9.2 Policy Management API, §4.3 Policy Management
**Severity**: P3 — Medium

**PRD Requirement**:
> "The Policy Management API shall support CRUD operations with four-eyes approval workflow before any policy rule takes effect in production."

**Current State**:
- `decision-api/src/main.py` has `GET /v1/config/{tenant_id}` and `PUT /v1/config/{tenant_id}` endpoints
- `compliance/rbac.py` has a four-eyes checker but it is only enforced for model promotion events
- Policy updates via `PUT /v1/config/{tenant_id}` bypass the four-eyes gate entirely — a single authorized user can push policy changes live
- No `POST /v1/config/{tenant_id}/approve` staging endpoint

---

#### GAP-12: No Canary Deployment for Decision Service
**PRD Reference**: §6.8 Deployment Architecture, §4.10 Rollout Controls
**Severity**: P3 — Medium

**PRD Requirement**:
> "The decision service shall support canary deployments with automatic rollback when error rate or latency p99 exceeds defined thresholds."

**Current State**:
- `scripts/canary_status.py` and `scripts/full_cutover.py` exist — canary concept understood
- These scripts target ML model canary deployments, not the decision-api service itself
- No traffic-weighting layer (Istio, Cloud Run traffic splits, NGINX upstream weighting) configured
- No automated rollback trigger on latency/error thresholds for the API service

---

### Priority 4 — Low (Enhancement)

---

#### GAP-13: No Borrower-Facing Portal API
**PRD Reference**: §5.3 Borrower Workflow, §9.5 Borrower Portal API
**Severity**: P4 — Low

**Current State**:
- All endpoints in `decision-api/src/main.py` require a JWT with `tenant_id` — no public-facing borrower authentication scheme
- No `/v1/applications/{id}/status` endpoint for borrower self-service
- `ui/` directory exists but is a stub

---

#### GAP-14: Batch Underwriting Pipeline Not Exposed via API
**PRD Reference**: §4.2 Batch Processing, §9.4 Batch API
**Severity**: P4 — Low

**Current State**:
- `scripts/run_cc_pd_pipeline.py` runs batch training/monitoring pipelines via CLI
- No `POST /v1/batch/underwrite` endpoint to submit a CSV of applications
- No job-status polling endpoint

---

#### GAP-15: No Stochastic Stress Testing
**PRD Reference**: §4.11 Risk Stress Testing, §6.9 Scenario Analysis
**Severity**: P4 — Low

**Current State**:
- `monitoring/cc_pd_monitor.py` performs historical backtesting
- No Monte Carlo or macro-scenario stress testing module
- PRD §4.11 requires 1,000-scenario stress tests on the active portfolio with results stored and comparable across quarters

---

#### GAP-16: Webhook Delivery for Decision Events Not Implemented
**PRD Reference**: §9.6 Webhook API
**Severity**: P4 — Low

**Current State**:
- No outbound webhook framework exists
- `monitoring/alert_router.py` handles internal alerts only
- No `/v1/webhooks` CRUD endpoints or delivery retry queue

---

### Priority 5 — Backlog

---

#### GAP-17: No Document Ingestion / OCR Pipeline
**PRD Reference**: §4.1 Document Processing, §6.2 Ingestion Layer
**Severity**: P5 — Backlog

**Current State**:
- `ingestion-api/` directory is a stub with no implementation
- No OCR, document classification, or bank statement parsing
- PRD requires Tesseract-based OCR + LayoutLM for structured extraction from uploaded PDFs

---

#### GAP-18: No Real-Time Bureau Data Integration
**PRD Reference**: §4.4 Bureau Integration, §7.2 External Data Sources
**Severity**: P5 — Backlog

**Current State**:
- `REAL_DATA_SOURCES.md` documents intended bureau connections (Experian, TransUnion, Equifax)
- No actual API client code for any bureau
- All scoring uses pre-fetched feature sets — no live bureau pull at decisioning time

---

## Summary Matrix

| Gap ID | Description | Priority | Regulatory Driver | Est. Effort |
|--------|-------------|----------|-------------------|-------------|
| GAP-01 | Cryptographic hash chain on audit log | P1 | ECOA, OCC 2021-25 | 3 days |
| GAP-02 | Adverse action notice generation | P1 | Reg B §1002.9 | 5 days |
| GAP-03 | Multi-tenant query isolation enforcement | P2 | GLBA, SOC 2 | 2 days |
| GAP-04 | Policy-level champion/challenger A/B | P2 | Internal | 3 days |
| GAP-05 | CRA / FCRA / UDAAP reporting | P2 | CRA, FCRA | 4 days |
| GAP-06 | NLG decision summaries | P2 | Reg B clarity | 2 days |
| GAP-07 | Model drift alerts wired to AlertRouter | P2 | SR 11-7 | 1 day |
| GAP-08 | Feature lineage queryable via API | P3 | Internal | 2 days |
| GAP-09 | SR 11-7 doc on champion promotion | P3 | SR 11-7 | 1 day |
| GAP-10 | Dedicated explainability endpoint | P3 | Internal | 1 day |
| GAP-11 | Policy API four-eyes enforcement | P3 | SOC 2, FFIEC | 2 days |
| GAP-12 | Canary deployment for decision service | P3 | Internal | 3 days |
| GAP-13 | Borrower-facing portal API | P4 | Internal | 4 days |
| GAP-14 | Batch underwriting API | P4 | Internal | 2 days |
| GAP-15 | Stochastic stress testing | P4 | SR 11-7 | 5 days |
| GAP-16 | Webhook delivery framework | P4 | Internal | 3 days |
| GAP-17 | Document ingestion / OCR pipeline | P5 | Internal | 10 days |
| GAP-18 | Real-time bureau data integration | P5 | FCRA | 15 days |

**Total P1+P2 effort estimate**: ~20 engineering days
**Total P1–P4 effort estimate**: ~49 engineering days

---

## Recommended Immediate Actions

1. **Freeze production deploys** until GAP-01 hash chain migration is live — current audit logs have no tamper evidence
2. **Assign a compliance engineer** to GAP-02 immediately — Reg B 30-day clock starts at origination; any live decisions today have no notice path
3. **Schedule SOC 2 pre-audit** only after GAP-03 and GAP-11 are closed
4. **Wire GAP-07** (alert router) in a single sprint — lowest effort, highest monitoring ROI

---

*For implementation details on P1 and P2 gaps, see [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md)*
