# Gap Analysis: PRD vs. Implementation
**Document**: Integrated Lending Operating Layer (ILOL)
**PRD Reference**: `docs/Unified_ILOL_PRD.md` *(Unified Edition v3.0.0)*
**Analysis Date**: 2026-04-26 *(full re-audit — supersedes all prior versions: 2026-04-15, 2026-04-14, 2026-04-07)*
**Analyst**: GitHub Copilot
**Status**: 18 legacy gaps CLOSED — **7 active gaps OPEN** (3× P0, 2× P1, 2× P2)

---

## Executive Summary

A full source-level re-audit of the `credit-risk-platform` codebase against **Unified ILOL PRD v3.0.0** conducted on **2026-04-26** produces the following verdict:

All **18 legacy gaps** (GAP-01 through GAP-18) from prior audit cycles remain fully closed. The v3.0 PRD introduced the **Tenant-Scoped Semantic Layer (Module 7)** and the **complete multi-agent AI Analytics Agent architecture (Module 6, §4.6.6)** as the two largest net-new engineering deliverables. Both are substantially unimplemented. Seven discrete gaps have been identified spanning these two modules plus the Analytics API, the AI audit log schema, and the webhook event registry.

**Net position: 18 legacy gaps CLOSED — 7 new gaps OPEN (3× P0, 2× P1, 2× P2).**

> **Note:** Prior audit entries (2026-04-15) marked GAP-19/20/21 as "Anti-Hallucination Framework," "GNRI-011 AI audit log," and "AI Agent Audit Appendix." This re-audit supersedes those designations. All three prior gaps were either partially closed (exam packet AI appendix ✅) or have been more precisely reframed based on deeper source analysis. The current 7-gap register below is the authoritative state.

---

## Audit Methodology

Each PRD v3.0 section was mapped to concrete source artifacts via:
1. Full recursive listing and reading of all 200+ Python source files across all 30+ top-level packages
2. Source-level function-by-function examination of: `ai-agent/src/`, `analytics_api/src/`, `compliance/exam_packet_builder.py`, `decision-api/src/main.py`, `audit/`, `webhooks/models.py`
3. Targeted `grep` search for all PRD-specific symbols: `AnalyticsScope`, `ValidatorAgent`, `FormatterAgent`, `ComplianceGateAgent`, `RegulatoryInterpreterAgent`, `tenant_semantic_registry`, `glossary`, `SEM-`, `query/nl`, `query/sql`, `pinecone`, `vector_db`, `bq_job_ids`, `code_zip_uri`, `code_sha256_hashes`, `AGENT_ANSWER_READY`, `SEMANTIC_SCHEMA_DRIFT`
4. Cross-referencing PRD §4.6, §4.7, §5, §8.3, §10.2, §10.3 requirements against actual endpoint routers, data models, and class definitions found in source

---

## Part I — Legacy Gap Inventory (GAP-01 through GAP-18): All Closed

All 18 legacy gaps are confirmed **CLOSED**. A consolidated summary:

| Gap | Title | Status |
|---|---|---|
| GAP-01 | Cryptographic Hash Chain on Audit Log | ✅ CLOSED — `audit/logger.py` + `chain_verifier.py` |
| GAP-02 | Adverse Action Notices Not Generated | ✅ CLOSED — `compliance/adverse_action_*.py` full lifecycle |
| GAP-03 | No Multi-Tenant Data Isolation | ✅ CLOSED — `audit/tenant_guard.py` + BigQuery RLS provisioner |
| GAP-04 | No Policy-Level A/B Testing | ✅ CLOSED — `decision_engine/policy_challenger.py` |
| GAP-05 | HMDA Only — No CRA/FCRA/UDAAP Reporting | ✅ CLOSED — `reporting/cra_activity.py`, `fcra_metro2.py`, `udaap_summary.py` |
| GAP-06 | No NLG Decision Summaries | ✅ CLOSED — `explainability/nlg_summarizer.py` |
| GAP-07 | Model Drift Alerts Not Wired | ✅ CLOSED — `monitoring/alert_router.py` + `cc_pd_monitor.py` wired |
| GAP-08 | Feature Lineage Not Queryable | ✅ CLOSED — `GET /v1/lineage/{run_id}` + `GET /v1/lineage/job/{job_name}` |
| GAP-09 | SR 11-7 Model Doc Not Auto-Generated on Promotion | ✅ CLOSED — `decisioning/champion_challenger.py` wired |
| GAP-10 | Explainability API Not Exposed | ✅ CLOSED — `GET /v1/decisions/{id}/explanation` + counterfactuals |
| GAP-11 | Policy Config API Read-Only | ✅ CLOSED — `POST /v1/config/stage` + `POST /v1/config/approve` (four-eyes) |
| GAP-12 | No Canary Deployment for Decision Service | ✅ CLOSED — `scripts/canary_decision_api.py` |
| GAP-13 | No Borrower-Facing Portal API | ✅ CLOSED — `decision-api/src/borrower_auth.py` + portal endpoints |
| GAP-14 | Batch Underwriting Not Exposed via API | ✅ CLOSED — `POST /v1/batch/underwrite` + status polling |
| GAP-15 | No Stochastic Stress Testing | ✅ CLOSED — `risk_models/stress_test.py` Monte Carlo + API |
| GAP-16 | No Webhook Delivery for Decision Events | ✅ CLOSED — `webhooks/dispatcher.py` + CRUD endpoints |
| GAP-17 | Document Ingestion / OCR Pipeline | ✅ CLOSED — `ingestion-api/src/ocr_engine.py` + classifier |
| GAP-18 | Real-Time Bureau Data Integration | ✅ CLOSED — tri-bureau client library + decision-pipeline wiring |

---

## Part II — Active Gap Register

---

### GAP-19 — Module 7: Tenant-Scoped Semantic Layer Completely Absent

**PRD Reference**: §4.7 (Module 7 in full), §5.1–5.2 Anti-Hallucination Framework Layer 1 (Semantic Layer Grounding), §10.2 Tenant Semantic Registry API, §13.1 Phase 2 M10–M11
**Severity**: **P0 — Critical** (blocks AI Agent from operating correctly at tenant level; named as mandatory enforcement component in §5.2)
**Regulatory Driver**: SR 11-7 (AI/ML extension) — AI outputs must be traceable to governed, versioned vocabulary; silent term mistranslation constitutes a model risk defect

**PRD Requirements:**

| ID | Requirement | Priority |
|---|---|---|
| SEM-001 | Platform glossary harvested automatically from `data_contracts` enum values at service startup | P0 |
| SEM-002 | Platform metric registry — 9 named metrics (`approval_rate`, `charge_off_rate`, `expected_loss`, `dir_score`, etc.) resolvable by name in NL queries | P0 |
| SEM-003 | `tenant_semantic_registry` append-only table with SHA-256 tamper detection per entry | P0 |
| SEM-004 | Tenant-registered custom table schemas enrolled in data lineage as `external_data_source` node | P0 |
| SEM-005 | Two-tier resolution: tenant entries win over platform defaults; resolution logged per NL query | P0 |
| SEM-006 | `POST /v1/analytics/tenant/schema/register` with four-eyes approval for `table_schema` entries | P0 |
| SEM-007 | `GET /v1/analytics/glossary` — merged platform + tenant glossary (no cross-tenant leakage) | P0 |
| SEM-008 | `POST /v1/analytics/tenant/glossary` — propose glossary term or metric | P1 |
| SEM-009 | Schema drift detection on every NL query referencing tenant-registered tables; block + alert on mismatch | P0 |
| SEM-010 | Semantic registry entries included in exam packet `Data Governance Evidence` section | P1 |
| SEM-011 | Platform admin API to inspect all active semantic entries for a tenant | P1 |
| SEM-012 | Tenant semantic entries carry version history with rollback | P2 |
| SEM-013 | `external_service` role receives merged glossary in analytics API responses | P1 |

**Current State**: Zero implementation. `grep` across all 200+ Python source files returns no matches for `AnalyticsScope`, `tenant_semantic_registry`, `two_tier_resolution`, or any SEM-* symbol. The `data_contracts/` module exists but no code harvests enum values into a platform glossary. `analytics_api/src/main.py` has no glossary, schema-registration, or semantic endpoints. Without the Semantic Layer, the anti-hallucination architecture described in §5.2 is architecturally incomplete at its first enforcement layer.

**Files Required:**
- `analytics_api/src/semantic_layer.py` — `AnalyticsScope`, `SemanticRegistry`, `TenantGlossaryEntry`, `PlatformMetric`, two-tier resolver, SHA-256 tamper detection, schema drift checker
- `analytics_api/src/semantic_store.py` — Append-only `tenant_semantic_registry` table DDL + CRUD; four-eyes approval for `table_schema` entries
- `analytics_api/src/semantic_api.py` — FastAPI router: `GET /v1/analytics/glossary`, `POST /v1/analytics/tenant/glossary`, `POST /v1/analytics/tenant/schema/register`, `GET /v1/analytics/tenant/schema/{name}/status`
- `analytics_api/tests/test_semantic_layer.py`
- `analytics_api/tests/test_semantic_api.py`

---

### GAP-20 — Module 6: Multi-Agent Architecture Incomplete (ValidatorAgent, FormatterAgent, ComplianceGateAgent, RegulatoryInterpreterAgent, Redis Session Memory, Vector KB)

**PRD Reference**: §4.6.4 Query Generation & Execution, §4.6.5 Code Transparency Layer (Non-Negotiable), §4.6.6 Multi-Agent Architecture, §5.2 Architectural Enforcement Layers, §7.2 Technology Stack (Redis + Vector DB), §11.3 AI Governance Controls
**Severity**: **P0 — Critical**
**Regulatory Driver**: SR 11-7 (AI/ML extension) — every AI answer must be grounded, reconciled, and code-transparent; CFPB UDAAP — hallucinated compliance numbers are a potential deceptive practice

**Agent Architecture: Implemented vs. Missing:**

| Agent / Component | PRD §4.6.6 | Status | Evidence |
|---|---|---|---|
| `CoordinatorAgent` (RBAC-aware routing) | Required | ⚠️ PARTIAL | Session management present in `ai-agent/src/main.py`; no RBAC role enforcement on query routing |
| `IntentClassifierAgent` | Required | ⚠️ PARTIAL | Embedded in ReAct prompt; no discrete agent class with structured output |
| `ComplianceGateAgent` (PII / ECOA-prohibited var block) | Required | ❌ ABSENT | `compliance/prohibited_variables.py` exists but is not wired as a pre-execution gate in the query pipeline |
| `PlannerAgent` | Required | ✅ PRESENT | `ai-agent/src/planner_agent.py` |
| `PortfolioAnalyticsAgent` | Required | ✅ PRESENT | `SQLAnalystAgent` in `specialist_agents.py` |
| `FairLendingAgent` | Required | ✅ PRESENT | `FairLendingAnalystAgent` in `specialist_agents.py` |
| `ModelRiskAgent` | Required | ✅ PRESENT | `MetricsAnalystAgent` + `DriftAnalystAgent` in `specialist_agents.py` |
| `AuditGovernanceAgent` | Required | ⚠️ PARTIAL | `ReportGeneratorAgent` covers some governance; no dedicated audit package assembly agent |
| `DataRetrievalAgent` (RAG from vector DB, GCS, MLflow) | Required | ❌ ABSENT | No RAG retrieval from vector DB, GCS document store, or MLflow |
| `QueryBuilderAgent` (schema injection + dry-run) | Required | ❌ ABSENT | SQL generated inline by ReAct; no schema injection; no DB dry-run before execution |
| `ExecutionAgent` (read-only service account sandbox) | Required | ❌ ABSENT | SQL runs as the application's DB user; no isolated read-only execution sandbox |
| `InsightGeneratorAgent` | Required | ✅ PRESENT | `SynthesizerAgent` in `specialist_agents.py` |
| `RegulatoryInterpreterAgent` (vector KB — SR 11-7, ECOA) | Required | ❌ ABSENT | No vector database, no regulatory KB embeddings, no `RegulatoryInterpreterAgent` class |
| `ValidatorAgent` (narrative ↔ data reconciliation) | Required | ❌ ABSENT | `confidence_scorer.py` scores but does not reconcile narrative numbers against returned query rows |
| `FormatterAgent` (blocks output if `code_artifacts` empty) | Required | ❌ ABSENT | Code artifacts stored in DB but no delivery gate blocks answers missing artifacts |
| Redis session memory | Required (§7.2) | ❌ ABSENT | Session history in SQLite; no Redis-backed multi-service context store |
| Vector DB (Pinecone / Vertex AI Matching Engine) | Required (§7.2) | ❌ ABSENT | Not provisioned; no embedding pipeline for regulatory documents |

**Key Functional Gaps:**

1. **No schema injection (§4.6.4 mandatory)**: SQL generated by the ReAct loop receives no schema context; hallucinated column names are not caught pre-execution.
2. **No DB dry-run validation (§4.6.4 mandatory)**: PRD requires every SQL query validated (zero bytes) before execution. Current code executes directly.
3. **No `ValidatorAgent` reconciliation (§5.2 enforcement layer 4)**: Every number in the AI narrative must be deterministically checked against the query result set. This is the primary hallucination attack surface.
4. **`FormatterAgent` blocking not implemented (§4.6.5 rule 6, non-negotiable)**: PRD: "FormatterAgent blocks output delivery if `code_artifacts` array is empty." Code artifact capture exists; the delivery gate does not.
5. **No `ComplianceGateAgent`**: ECOA-prohibited variables are not architecturally blocked at query intake.
6. **No Regulatory KB / RAG**: `RegulatoryInterpreterAgent` has no backing vector store. Regulatory citations currently generated from LLM parametric memory — the exact hallucination risk targeted by §5.

**Files Required:**
- `ai-agent/src/validator_agent.py` — `ValidatorAgent.reconcile()` checking narrative numbers against query result rows; `HallucinationAttemptLog`
- `ai-agent/src/compliance_gate_agent.py` — `ComplianceGateAgent` wrapping `compliance/prohibited_variables.py`; pre-planning gate
- `ai-agent/src/formatter_agent.py` — `FormatterAgent` enforcing `code_artifacts` presence; multi-format output assembly
- `ai-agent/src/regulatory_kb.py` — `RegulatoryKB` abstraction (Pinecone / local FAISS fallback for dev); `RegulatoryInterpreterAgent`
- `ai-agent/src/query_builder_agent.py` — schema injection, DB dry-run, tenant_id injection, PII masking
- `ai-agent/src/session_store.py` — Redis-backed session store with SQLite fallback for dev/test
- `ai-agent/src/main.py` — Modify to wire: `ComplianceGateAgent` → `PlannerAgent` → `QueryBuilderAgent` → specialist → `ValidatorAgent` → `FormatterAgent`
- `ai-agent/tests/test_validator_agent.py`
- `ai-agent/tests/test_compliance_gate_agent.py`
- `ai-agent/tests/test_formatter_agent.py`
- `ai-agent/tests/test_query_builder_agent.py`

---

### GAP-21 — AI Agent + Analytics API Endpoints Non-Compliant with PRD §10.2

**PRD Reference**: §10.2 API Design, Appendix B API Specifications
**Severity**: **P0 — Critical** (external integrations including LucidCredit depend on `code_artifacts` in response; exam packet assembly uses agent API)
**Regulatory Driver**: GNRI-011 — AI audit log must be queryable via defined API; code artifacts must be downloadable for regulatory submission

**AI Agent — PRD-Required Endpoints vs. Current State:**

| PRD Endpoint | Status | Current Reality |
|---|---|---|
| `POST /api/v1/agent/query` | ❌ ABSENT | Has `POST /agent/chat` — different contract: SSE streaming, no `code_artifacts` array in response body |
| `GET /api/v1/agent/sessions/{session_id}` | ❌ ABSENT | Has `GET /agent/sessions/{id}/history` — different path and schema |
| `POST /api/v1/agent/audit-package` | ❌ ABSENT | Not implemented |
| `GET /api/v1/agent/query/{query_id}/code-artifacts` | ❌ ABSENT | Artifacts stored in DB but not exposed via API |
| `GET /api/v1/agent/query/{query_id}/code-archive.zip` | ❌ ABSENT | Not implemented |

**Analytics API — Missing Endpoints:**

| PRD Endpoint | Status |
|---|---|
| `POST /v1/analytics/query/sql` | ❌ ABSENT |
| `POST /v1/analytics/query/nl` | ❌ ABSENT |
| `GET /v1/analytics/queries/saved` | ❌ ABSENT |
| `POST /v1/analytics/queries/save` | ❌ ABSENT |
| `GET /v1/analytics/glossary` | ❌ ABSENT (blocked by GAP-19) |
| `POST /v1/analytics/tenant/glossary` | ❌ ABSENT (blocked by GAP-19) |
| `POST /v1/analytics/tenant/schema/register` | ❌ ABSENT (blocked by GAP-19) |
| `GET /v1/analytics/tenant/schema/{name}/status` | ❌ ABSENT (blocked by GAP-19) |
| `POST /v1/analytics/evidence/exam-packet` | ❌ ABSENT |
| `GET /v1/analytics/evidence/exam-packet/{id}` | ❌ ABSENT |

**Current analytics_api endpoints** (the only 3 present): `GET /v1/analytics/vintage-curves`, `GET /v1/analytics/roll-rates`, `GET /v1/analytics/approval-profit`.

**Files to Modify:**
- `ai-agent/src/main.py` — Add `POST /api/v1/agent/query` with Appendix B response schema (`code_artifacts` array); `GET /api/v1/agent/sessions/{id}`; `POST /api/v1/agent/audit-package`; `GET /api/v1/agent/query/{id}/code-artifacts`; `GET /api/v1/agent/query/{id}/code-archive.zip`
- `analytics_api/src/main.py` — Add SQL query, NL query, saved queries, evidence/exam-packet endpoints
- `ai-agent/tests/test_agent_api_contract.py`
- `analytics_api/tests/test_analytics_query_api.py`

---

### GAP-22 — GNRI-011: AI Audit Log Schema Missing BigQuery Array Fields

**PRD Reference**: §4.1.1 GNRI-011, §8.3 AI Agent Audit Log Schema (BigQuery)
**Severity**: **P1 — High**
**Regulatory Driver**: OCC / CFPB (SR 11-7 AI extension) — exam packets must surface per-step BigQuery job IDs and code archive URIs for independent verification

**PRD BigQuery Schema (§8.3) vs. Current `ai_agent_audit_log` DDL:**

| PRD Field | Type | Current State |
|---|---|---|
| `code_artifact_uris` | `ARRAY<STRING>` | ❌ Missing — only a singular `code_artifact_ref TEXT` |
| `bq_job_ids` | `ARRAY<STRING>` | ❌ Missing — only a singular `bq_job_id TEXT` |
| `code_zip_uri` | `STRING` | ❌ Missing — not present |
| `code_sha256_hashes` | `ARRAY<STRING>` | ❌ Missing — content hash only stored on `agent_code_artifacts` table |

**Impact:** The `build_ai_agent_audit_component()` in `exam_packet_builder.py` cannot surface per-step BigQuery job IDs or a code ZIP URI, making the AI Agent Audit Appendix incomplete for regulatory examination.

**Files to Modify:**
- `ai-agent/src/ai_audit_log.py` — Add four fields to DDL; add JSON-array serialization to `log_ai_turn()`; add Alembic-compatible migration for existing databases
- `ai-agent/tests/test_ai_audit_log.py` — Update for new schema fields

---

### GAP-23 — Webhook Events Missing for AI Agent and Semantic Layer

**PRD Reference**: §10.3 Webhook Events
**Severity**: **P1 — High**

**Missing Events vs. PRD §10.3:**

| PRD Event | Status | Note |
|---|---|---|
| `agent.answer.ready` | ❌ ABSENT | Not in `webhooks/models.py` `EventType` enum |
| `hallucination.detected` | ❌ ABSENT | Depends on GAP-20 `ValidatorAgent` |
| `semantic.schema_drift` | ❌ ABSENT | Depends on GAP-19 Semantic Layer |
| `semantic.term_proposed` | ❌ ABSENT | Depends on GAP-19 Semantic Layer |

**Confirmed present:** `decision.created`, `decision.override`, `policy.changed`, `model.deployed`, `alert.triggered`, `exam_packet.ready`

**Files to Modify:**
- `webhooks/models.py` — Add `AGENT_ANSWER_READY`, `HALLUCINATION_DETECTED`, `SEMANTIC_SCHEMA_DRIFT`, `SEMANTIC_TERM_PROPOSED` to `EventType` enum
- `webhooks/tests/test_webhooks.py` — Add tests for new event types

---

### GAP-24 — GraphQL Analytics API Absent

**PRD Reference**: §10.1 ("GraphQL available for analytics queries"), §13.1 Phase 2 M12
**Severity**: **P2 — Medium**

**Current State:** `analytics_api/src/main.py` is REST-only. No GraphQL schema, resolver, or endpoint exists anywhere in the codebase.

**Files to Create:**
- `analytics_api/src/graphql_schema.py` — Strawberry or Ariadne schema covering portfolio summary, vintage curves, roll rates, agent insights, and semantic glossary queries
- `analytics_api/src/graphql_resolvers.py`
- `analytics_api/tests/test_graphql_api.py`

---

### GAP-25 — Policy Version RSA Signing (PV-007) Not Implemented

**PRD Reference**: §4.1.2 Policy Versioning System, PV-007
**Severity**: **P2 — Medium**
**Regulatory Driver**: OCC IT audit standards — policy versions must support offline, third-party tamper verification

**PRD Requirement (PV-007):** "Policy versions are cryptographically signed (RSA-256)"

**Current State:** `decision_engine/policy_version_store.py` stores policy versions with SHA-256 content hashes at the audit log row level (GAP-01 closure). PV-007 requires a distinct **RSA public-key signature** on the policy version *payload* itself — enabling offline verification without DB access.

**Files to Modify:**
- `decision_engine/policy_version_store.py` — Add `sign_version()` and `verify_version_signature()` using RSA-2048 (`cryptography` library); store `rsa_signature` and `signing_key_id` in version record
- `decision_engine/tests/test_policy_version_store.py` — Add signing and verification tests

---

## Part III — Confirmed Implementations (PRD v3.0 Net-New, All Verified)

| Feature | Module | Evidence |
|---|---|---|
| Compliance Health Score (8-dimension, zero-tolerance) | `compliance/health_score.py` | `compute_health_score()` → GREEN/YELLOW/RED |
| SOC 2 evidence collection | `compliance/soc2_evidence.py` | Event-driven evidence collector |
| Data retention enforcement + erasure | `compliance/retention_policy.py` + `erasure_request.py` | GLBA/CCPA lifecycle |
| RBAC enforcement (8 roles) | `compliance/rbac.py` | Role registry + permission matrix |
| Regulatory horizon scanner | `compliance/regulatory_horizon.py` | OCC/CFPB/Fed rule tracking |
| Third-party model registry | `compliance/third_party_model_registry.py` | SR 11-7 third-party governance |
| Prohibited variables checker | `compliance/prohibited_variables.py` | ECOA-prohibited detection |
| Decision replay bundle | `audit/replay_bundle.py` | Full audit replay |
| Decision consistency scorer | `audit/consistency_scorer.py` | Policy-model alignment metric |
| Override log (immutable, dual-approver) | `audit/override_log.py` | Dual-control audit trail |
| Exam packet builder (8 components incl. AI audit appendix) | `compliance/exam_packet_builder.py` | `build_exam_packet()` wired to all 8 components incl. `build_ai_agent_audit_component()` |
| NLG executive summaries (3 audiences) | `explainability/nlg_summarizer.py` | Three-audience narrative generation |
| Portfolio analytics API (vintage, roll rates, approval/profit) | `analytics_api/src/main.py` | 3 endpoints live |
| Policy versioning (diff + rollback + four-eyes) | `decision_engine/policy_version_store.py` | Full versioning lifecycle |
| AI agent audit log (append-only, hash-chained, GNRI-011 partial) | `ai-agent/src/ai_audit_log.py` | SHA-256 chain; missing 4 BQ array fields (GAP-22) |
| Code artifact store (per-turn SQL/Python capture) | `ai-agent/src/code_artifact_store.py` | Append-only, SHA-256 per artifact |
| PlannerAgent (step-by-step plan SSE emission) | `ai-agent/src/planner_agent.py` | Fully implemented |
| Specialist agents (6: Portfolio, FairLending, ModelRisk, Drift, Chart, Report) | `ai-agent/src/specialist_agents.py` | OrchestratorAgent + SynthesizerAgent |
| Confidence scorer (HIGH/MEDIUM/LOW + refusal threshold) | `ai-agent/src/confidence_scorer.py` | Refusal enforced |
| BISG proxy testing | `monitoring/` | `tests/monitoring/test_bisg.py` green |
| Tri-bureau integration (Experian, Equifax, TransUnion) | `ingestion-api/src/bureau_clients/` | OAuth2 + mTLS + waterfall router + decision-pipeline wiring |

---

## Gap Priority Summary

| Gap | Title | Severity | Blocks |
|---|---|---|---|
| GAP-19 | Tenant-Scoped Semantic Layer Absent | **P0** | Anti-hallucination §5 Layer 1; NL query correctness; exam Data Governance Evidence |
| GAP-20 | Multi-Agent Architecture: ValidatorAgent, FormatterAgent, ComplianceGateAgent, RegulatoryInterpreterAgent, Redis, Vector KB | **P0** | Anti-hallucination enforcement; ECOA compliance gate; regulatory KB citations |
| GAP-21 | AI Agent + Analytics API Endpoints Non-Compliant with PRD §10.2 | **P0** | External integrations; `code_artifacts` in response; audit package API |
| GAP-22 | AI Audit Log Schema Missing BigQuery Array Fields | **P1** | Complete exam packet AI appendix; multi-step BQ job tracing |
| GAP-23 | Webhook Events Missing (AI agent + Semantic Layer) | **P1** | Downstream consumer notifications; hallucination monitoring pipeline |
| GAP-24 | GraphQL Analytics API Absent | **P2** | Phase 2 M12 deliverable; advanced analytics clients |
| GAP-25 | Policy Version RSA Signing (PV-007) | **P2** | OCC offline verification control |

---
