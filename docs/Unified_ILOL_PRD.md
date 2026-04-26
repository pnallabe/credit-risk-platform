# Integrated Lending Operating Layer (ILOL)
### Platform Requirements Document — Unified Edition

> **Product Name:** Integrated Lending Operating Layer (ILOL)
> **Version:** 3.0.0 | **Date:** April 15, 2026 | **Status:** ACTIVE — Unified Edition
> **Owner:** Product / Risk / Compliance / AI Engineering
> **Supersedes:** PRD_INTEGRATED_LENDING_OPERATING_LAYER v1.0.0 + Governance_native_LOS_PRD v2.1
> **Change Summary (v3.0):** Unified merger of ILOL platform PRD (v1.0.0) and GNCDA AI Analytics Platform PRD (v2.1). Incorporates the full decisioning engine, bureau integrations, policy versioning, model lifecycle management, multi-tenant SaaS architecture, and RAG-powered AI Analytics Agent with zero-hallucination enforcement and Code Transparency Layer into a single authoritative product specification.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision & Strategy](#2-product-vision--strategy)
3. [User Personas](#3-user-personas)
4. [Core Platform Modules](#4-core-platform-modules)
   - [Module 1: Governance-Native Risk Infrastructure](#41-module-1-governance-native-risk-infrastructure-gnri)
   - [Module 2: Decisioning Engine](#42-module-2-decisioning-engine)
   - [Module 3: Portfolio Monitoring & Analytics](#43-module-3-portfolio-monitoring--analytics)
   - [Module 4: Compliance & Audit Layer](#44-module-4-compliance--audit-layer)
   - [Module 5: Model Lifecycle Management](#45-module-5-model-lifecycle-management)
   - [Module 6: RAG-Powered AI Analytics Agent Platform](#46-module-6-rag-powered-ai-analytics-agent-platform)
   - [Module 7: Tenant-Scoped Semantic Layer](#47-module-7-tenant-scoped-semantic-layer)
5. [Anti-Hallucination Framework](#5-anti-hallucination-framework-regulatory-grade)
6. [UX & Workflow Design](#6-ux--workflow-design)
7. [System Architecture](#7-system-architecture)
8. [Data Architecture](#8-data-architecture)
9. [Compliance & Governance Framework](#9-compliance--governance-framework)
10. [API Design](#10-api-design)
11. [Security & Governance](#11-security--governance)
12. [Metrics & Success Criteria](#12-metrics--success-criteria)
13. [Implementation Roadmap](#13-implementation-roadmap)
14. [Appendix A — Glossary](#appendix-a--glossary)
15. [Appendix B — API Specifications (AI Agent Layer)](#appendix-b--api-specifications-ai-agent-layer)
16. [Appendix C — Risk & Mitigation Register](#appendix-c--risk--mitigation-register)
17. [Appendix D — Go-Live Integration Checklist](#appendix-d--go-live-integration-checklist)

---

## 1. Executive Summary

### 1.1 Product Overview

The **Integrated Lending Operating Layer (ILOL)** is a production-grade, governance-native credit risk platform purpose-built for mid-market lenders — credit unions, community banks, and fintech lenders managing loan portfolios between $100M and $10B. It serves as the single operating layer across originations, underwriting, risk management, compliance, portfolio analytics, and AI-assisted decisioning intelligence.

ILOL is not a point solution. It is the connective tissue between every system and decision a lender makes — from the moment an application arrives to the moment a regulatory examiner requests documentation — with an embedded AI analytics layer that behaves like a **Capital One-grade credit risk consultant**: every answer traceable to a dataset, query, and timestamp, with the full executable code surfaced for independent validation.

### 1.2 Problem Statement

Mid-market lenders face a structural crisis across four dimensions:

| Dimension | Current Pain | Cost |
|---|---|---|
| **Decisioning** | Disconnected policy engines, manual score overrides, no audit trail | High error rate, fair lending exposure |
| **Monitoring** | Lagged reporting (30–90 days), no real-time portfolio visibility | Slow response to credit deterioration |
| **Compliance** | Manual exam prep, inconsistent documentation, long audit cycles | $500K–$5M in exam response costs annually |
| **Analytics** | Portfolio questions requiring cross-system joins take days; generic LLMs hallucinate on regulatory data | Slow insight delivery; AI trust risk |

Existing solutions address one or two of these pain points in isolation. ILOL addresses all four in a unified, integrated platform.

### 1.3 Solution Summary

ILOL delivers:

- **A Governance-Native Risk Infrastructure** — immutable decision logs, policy versioning, fairness monitoring, and data lineage as first-class platform primitives
- **A Decisioning Engine** — orchestrates credit policies and ML models with full traceability and sub-200ms latency
- **A Portfolio Monitoring Layer** — real-time dashboards from portfolio-level to individual loan decisions, with vintage analysis and early warning signals
- **A Compliance Automation Suite** — one-click regulator-ready exam packets that convert regulatory scrutiny from a crisis into a routine
- **A Model Lifecycle Management System** — aligned with SR 11-7, with auto-generated model cards, validation workflows, and performance monitoring
- **A RAG-Powered AI Analytics Agent** — answers complex risk, compliance, and portfolio questions in natural language with zero hallucination tolerance, full code transparency, and regulator-submittable audit trails

### 1.4 Business Case

| Metric | Target |
|---|---|
| Initial target market | Credit unions ($100M–$2B AUM) and fintech lenders |
| Addressable market (TAM) | ~4,700 institutions in the US meeting profile criteria |
| ARR per customer | $150K–$600K depending on tier |
| Target Year 1 customers | 15–25 |
| Target Year 2 ARR | $5M–$8M |
| Differentiation | Only platform with governance-native architecture + exam automation + AI analytics with code transparency |

### 1.5 Key Stakeholders

| Role | Organization | Responsibility |
|---|---|---|
| Chief Product Officer | ILOL | Product direction |
| Head of Engineering | ILOL | Architecture, delivery |
| Head of Compliance | ILOL | Regulatory alignment |
| Advisory — Model Risk | External | SR 11-7 alignment review |
| Advisory — Fair Lending | External | CFPB, ECOA alignment review |

---

## 2. Product Vision & Strategy

### 2.1 Vision Statement

> *"Every credit decision made on ILOL is explainable, auditable, and defensible — today, tomorrow, and on the day a regulator walks in. Every portfolio question answered by ILOL is grounded in real data, independently reproducible, and submittable as audit evidence."*

### 2.2 Strategic Positioning

ILOL occupies a distinct position in the market:

```
                    HIGH GOVERNANCE
                          │
        [ILOL]            │
   (decisioning +         │
    AI + compliance)      │
                          │
LOW AUTOMATION ───────────┼─────────────── HIGH AUTOMATION
                          │
                          │             [ML-Only Vendors]
                          │
                    LOW GOVERNANCE
```

Competitors either optimize for speed (without governance) or compliance (without intelligence). ILOL is the only platform that treats governance as a **first-class engineering primitive** — not an afterthought — while simultaneously delivering an AI analytics layer with zero hallucination tolerance as a core trust mechanism.

### 2.3 Strategic Pillars

#### Pillar 1: Governance-First Architecture
Every component is built with auditability as a default. Decision logs, policy versions, and model outputs are immutable by design. AI-generated answers are equally immutable and auditable.

#### Pillar 2: Regulatory Immunity
One-click exam packet generation eliminates the multi-month manual process of preparing for OCC, CFPB, or Federal Reserve examinations. AI agent outputs include appended executable code that regulators can independently verify.

#### Pillar 3: Unified Intelligence Layer
Risk analysts, data scientists, compliance officers, and AI agents share the same data layer — eliminating reconciliation overhead and providing a single source of truth.

#### Pillar 4: Transparent AI — Code as Proof
Every AI-generated analysis surfaces the complete, executable SQL and Python used to produce it. Users are never asked to trust a number they cannot verify. This transforms the AI from a black box into a **transparent analytical collaborator**.

#### Pillar 5: Extensible by Design
ILOL is modular. Customers can adopt individual modules (e.g., decisioning only, compliance only, AI agent only) and expand. The API-first design enables integration into any existing tech stack.

#### Pillar 6: Tenant-Scoped Intelligence
No two lenders use the same vocabulary for risk. A credit union calls it "charged off"; a fintech calls it "written off." A community bank tracks a proprietary bureau score under a name no platform glossary anticipates. The Tenant-Scoped Semantic Layer means the AI agent understands each tenant's language natively — not through brittle string matching, but through a governed, versioned, tamper-detected registry of business terms, metric formulas, and custom data sources that each tenant owns and maintains.

### 2.4 Product Principles

1. **Explainability over opacity** — every output must have a traceable reason
2. **Immutability over editability** — logs are append-only; no soft deletes on compliance-critical data
3. **Modularity over monolith** — each module deploys independently
4. **Latency as a feature** — real-time decisioning is not optional; sub-200ms for synchronous decisions
5. **Regulatory alignment as product design** — OCC/CFPB guidance shapes UX, not just backend behavior
6. **Code as the ultimate audit trail** — every AI answer carries its exact executable source code, stored immutably

### 2.5 Competitive Landscape

| Competitor | Strength | Gap vs ILOL |
|---|---|---|
| Zest AI | ML model quality | No governance layer, no exam automation, no AI analytics agent |
| Provenir | LOS integration depth | No model risk management, no fairness monitoring, no AI insight layer |
| Experian Ascend | Data access | Platform lock-in, no policy versioning, no AI agent |
| Sageworks/Abrigo | Community bank brand | Legacy architecture, no real-time decisioning, no AI analytics |
| Moody's Analytics (RiskCalc) | Credit analytics depth | No decisioning engine, no compliance automation, no AI agent |
| Generic LLM chatbots | Natural language interface | Hallucination on regulatory data; no audit trail; no code transparency |
| In-house builds | Customization | High cost, no regulatory templates, talent risk, no AI layer |

---

## 3. User Personas

### 3.1 Persona 1: Risk Analyst (Maya)

**Title:** Senior Credit Risk Analyst | **Organization:** Credit Union, $800M AUM | **Team size:** 3–5 analysts

**Goals:**
- Monitor approval rates, delinquency trends, and policy performance daily
- Identify emerging portfolio stress early
- Run policy simulations before changes go live
- Defend policy decisions to internal audit with documentation ready
- Get fast, accurate answers to portfolio questions without waiting for data engineering

**Frustrations:**
- Pulling data from 4+ systems into Excel every morning
- No way to know what changed in scoring between months
- Model reason codes are unexplainable to loan officers
- Fair lending reports require 2 weeks of manual work
- Can't trust AI-generated numbers without seeing the underlying query

**ILOL Value Delivered:**
- Single dashboard with live portfolio metrics
- Policy change history with visual diff
- Reason code explainability in plain English
- Automated disparate impact analysis on demand
- AI agent answers with SQL + Python shown for immediate validation

**Key Workflows:** Portfolio monitoring, policy simulation, fairness reporting, natural language portfolio Q&A

---

### 3.2 Persona 2: Chief Risk Officer (David)

**Title:** CRO | **Organization:** Fintech Lender, $2B+ AUM | **Team size:** Executive, oversees 15–30 FTEs

**Goals:**
- Maintain regulatory posture across OCC, CFPB, and Fair Lending
- Understand portfolio health at aggregate and segment level
- Receive early warning for risk deterioration
- Brief the board quarterly with reliable, consistent, explainable data

**Frustrations:**
- Board packages require 2–3 days of manual assembly per quarter
- Regulatory examinations feel like crises, not routine reviews
- No single view of model performance across vintages
- Can't simulate the impact of a policy change before it goes live

**ILOL Value Delivered:**
- Auto-generated CRO executive summaries (NLG-powered, data-grounded)
- Real-time alert system with configurable thresholds
- Exam packet auto-generation: policy history + model docs + fair lending reports
- Policy rollback with impact preview
- AI-generated portfolio commentary for board packages, with source code attached

**Key Workflows:** Executive reporting, alert management, regulatory preparation, board reporting

---

### 3.3 Persona 3: Compliance Officer (Sandra)

**Title:** VP of Compliance | **Organization:** Community Bank, $1.5B AUM | **Reports to:** General Counsel / CEO

**Goals:**
- Ensure ECOA / Reg B compliance for every adverse action
- Maintain a defensible audit trail for all underwriting decisions
- Prepare for OCC examinations with minimal disruption
- Monitor for disparate impact across protected classes continuously

**Frustrations:**
- Adverse action notices are inconsistent across channels
- No centralized audit trail — decisions spread across LOS, core banking, and spreadsheets
- Fair lending analysis requires external consultant ($30K–$100K per engagement)
- Policy documentation is out of date within 60 days of changes
- Can't verify AI-generated compliance summaries before submitting to regulators

**ILOL Value Delivered:**
- Immutable decision log with complete input-output traceability
- Automated disparate impact monitoring with threshold alerts
- Regulator-ready adverse action notice templates aligned to Reg B
- One-click exam packet with OCC and CFPB pre-built templates
- AI compliance analysis with full SQL code shown — independently verifiable before regulatory submission

**Key Workflows:** Adverse action management, fair lending monitoring, exam preparation, AI-assisted compliance Q&A

---

### 3.4 Persona 4: Data Scientist / Model Developer (Priya)

**Title:** Lead Data Scientist | **Organization:** Fintech Lender, internal model team | **Team:** 2–6 data scientists

**Goals:**
- Deploy, version, and monitor ML models with minimal friction
- Ensure model behavior is stable post-deployment
- Satisfy model validation requirements from model risk management
- Respond to model risk governance inquiries with structured documentation

**Frustrations:**
- No standardized model registry — models live in S3 buckets / GCS with no metadata
- Re-training cycles take 2–3 weeks due to manual data pipeline processes
- No alerting when model PSI or AUC degrades post-deployment
- Model documentation is written manually after the fact

**ILOL Value Delivered:**
- Integrated model registry with version control, lineage, and metadata
- Auto-generated model cards aligned to SR 11-7 requirements
- Real-time PSI / AUC / KS monitoring with configurable alert thresholds
- A/B testing framework for policy and model experimentation
- AI agent queries: "Which models are at risk of failing the next validation cycle?"

**Key Workflows:** Model deployment, model monitoring, A/B testing, model documentation, AI model risk Q&A

---

### 3.5 Persona 5: Internal Auditor / Model Risk Manager

**Title:** Model Risk Manager or VP Internal Audit | **Organization:** Credit Union or Fintech | **Reports to:** CRO / CAO

**Goals:**
- Independently validate AI-generated analytics before using in regulatory responses
- Test controls on a sample of credit decisions
- Confirm SR 11-7 model governance is complete and current
- Produce evidence of controls testing for exam files

**ILOL Value Delivered:**
- Code Transparency Layer: every AI answer comes with runnable SQL + Python for independent verification
- Stratified random decision sampling with one click
- Agent session logs (full audit trail: query → plan → code → result) available for exam evidence
- Model validation status, overdue flags, and governance calendar in one view

**Key Workflows:** Decision sampling, AI output validation, model governance review, exam evidence assembly

---

## 4. Core Platform Modules

---

### 4.1 Module 1: Governance-Native Risk Infrastructure (GNRI)

This is the foundational module. All other modules build on top of GNRI primitives.

#### 4.1.1 Immutable Decision Log

**Description:** Every underwriting decision — approved, declined, referred, or withdrawn — is logged as an immutable event with full context.

| ID | Requirement | Priority |
|---|---|---|
| GNRI-001 | Log every decision event with timestamp, application ID, and decision outcome | P0 |
| GNRI-002 | Capture all input features used at decision time (bureau, alternative data, calculated) | P0 |
| GNRI-003 | Capture all transformed features (normalized values, encoded variables) | P0 |
| GNRI-004 | Capture model score, scorecard output, and policy rule evaluations | P0 |
| GNRI-005 | Capture reason codes (top 4 adverse factors, in Reg B-compliant format) | P0 |
| GNRI-006 | Capture the version of policy, model, and scorecard active at the time of decision | P0 |
| GNRI-007 | Prevent modification or deletion of any decision log record (append-only log store) | P0 |
| GNRI-008 | Support decision log query by: application ID, date range, decision outcome, channel, segment | P1 |
| GNRI-009 | Export decision logs to PDF, Excel, and JSON formats | P1 |
| GNRI-010 | Decision log retention minimum: 7 years (configurable to 10 years) | P0 |
| GNRI-011 | AI agent audit log: every AI query, plan, SQL executed, result hash, and code artifacts stored in audit table — append-only, 7-year retention | P0 |

**Non-Functional Requirements:**
- Write latency: < 50ms (async write, not in critical path)
- Storage: tiered — hot (90 days), warm (2 years), cold (7 years)
- Audit log tamper detection: cryptographic hash chain on append-only log
- Analytics store: BigQuery partitioned tables for high-throughput analytical queries

---

#### 4.1.2 Policy Versioning System

**Description:** Complete version control for credit policies, scorecards, and decision trees with visual diff, rollback, and impact preview.

| ID | Requirement | Priority |
|---|---|---|
| PV-001 | Every policy change is versioned with timestamp, author, and change reason | P0 |
| PV-002 | Support full policy version history with searchable changelog | P0 |
| PV-003 | Visual diff view: side-by-side comparison of any two versions | P1 |
| PV-004 | Impact preview: simulate the effect of a version change on last 30/90/180 days of decisions | P1 |
| PV-005 | Rollback to any prior version with a single action | P0 |
| PV-006 | Rollback requires dual-control authorization (two approvers) | P0 |
| PV-007 | Policy versions are cryptographically signed (RSA-256) | P1 |
| PV-008 | Support branch/staging environment: test policy changes before promotion to production | P1 |
| PV-009 | Export any version as structured JSON and human-readable PDF | P1 |
| PV-010 | Active version clearly displayed on all decision outputs and AI agent answers | P0 |

**Policy Versioning Data Schema:**
```json
{
  "policy_id": "uuid",
  "version": "2.4.1",
  "effective_date": "2026-04-01T00:00:00Z",
  "deprecated_date": null,
  "author": "user_id",
  "approver": "user_id",
  "change_reason": "string",
  "change_category": "risk_expansion | risk_tightening | scorecard_update | regulatory",
  "policy_definition": { },
  "signature": "sha256_hash",
  "parent_version": "2.4.0"
}
```

---

#### 4.1.3 Model Explainability Layer

**Description:** Generates human-readable explanations for every model-driven decision, aligned with Reg B adverse action notice requirements and SR 11-7 model transparency standards.

| ID | Requirement | Priority |
|---|---|---|
| EXP-001 | Generate top-4 adverse action reason codes for every declined application | P0 |
| EXP-002 | Reason codes must map to Reg B-compliant consumer-facing language | P0 |
| EXP-003 | Support SHAP (SHapley Additive exPlanations) for tree-based and linear models | P0 |
| EXP-004 | Support LIME for neural network and black-box models | P1 |
| EXP-005 | Display feature contribution direction (positive/negative impact on score) | P1 |
| EXP-006 | Counterfactual generation: "What would change this decision?" | P2 |
| EXP-007 | Explainability output stored in decision log as structured JSON | P0 |
| EXP-008 | Loan officer-facing reason code display (human-readable, non-technical) | P1 |
| EXP-009 | Regulator-facing detailed explanation (feature values, weights, contributions) | P1 |
| EXP-010 | SHAP-based feature attribution available to AI Analytics Agent for population-level analysis | P1 |

---

#### 4.1.4 Fairness Monitoring System

**Description:** Continuous monitoring of lending decisions for disparate impact and disparate treatment across ECOA-protected classes.

| ID | Requirement | Priority |
|---|---|---|
| FM-001 | Monitor approval rates by protected class (race, sex, age, national origin, marital status) | P0 |
| FM-002 | Calculate adverse impact ratio (AIR) for each protected class vs. control group | P0 |
| FM-003 | Threshold alert: trigger when AIR falls below 0.80 (4/5ths rule) | P0 |
| FM-004 | Regression-based disparate impact analysis controlling for creditworthiness proxies | P1 |
| FM-005 | Geographic fair lending analysis (HMDA-style heat maps) | P1 |
| FM-006 | Automated BISG (Bayesian Improved Surname Geocoding) proxy testing | P1 |
| FM-007 | Trend monitoring: AIR changes over rolling 30/60/90-day windows | P1 |
| FM-008 | Auto-generate disparate impact report in CFPB-ready format | P0 |
| FM-009 | Flag proxy variable risks (zip code, last name proxies) | P1 |
| FM-010 | Log all fairness calculations with methodology metadata for audit defense | P0 |
| FM-011 | AI agent integration: "Run a fair lending analysis on last quarter's auto-decline population" — with full SQL + Python code transparency | P1 |

**Fair Lending Metrics Computed:**
- Adverse Impact Ratio (AIR) — by product, channel, segment, overall
- Marginal Effect Analysis — logistic regression controlling for legitimate risk factors
- Concentration Analysis — lending geography vs. demographic composition
- Comparative File Review — statistical matching of declined to approved applicants
- Pricing Disparity — mean APR and limit differences by protected class proxy (controlled)

---

#### 4.1.5 Data Lineage Tracking

**Description:** End-to-end tracking of every data element from source ingestion to decision output, and from source table to AI agent answer.

| ID | Requirement | Priority |
|---|---|---|
| DL-001 | Track every feature value from source system to decision with provenance metadata | P0 |
| DL-002 | Record source system, ingestion timestamp, transformation applied, and version | P0 |
| DL-003 | Visualize lineage DAG (directed acyclic graph) for any decision | P1 |
| DL-004 | Alert on source data staleness or missing data elements | P1 |
| DL-005 | Support retroactive lineage querying (what data was used on date X for application Y?) | P0 |
| DL-006 | Export lineage as model documentation evidence for SR 11-7 | P1 |
| DL-007 | AI agent answers carry data lineage tags (source table, partition date, query hash) on every retrieved data point | P0 |

---

#### 4.1.6 Role-Based Access Control (RBAC)

| Role | Permissions |
|---|---|
| **Platform Admin** | Full access: configure, deploy, manage users, AI agent configuration |
| **CRO / Executive** | Read-all: all dashboards, reports, alerts, AI agent summaries; no edit |
| **Risk Analyst** | Read/write: policy simulation, monitoring dashboards, AI agent queries; no production deploy |
| **Compliance Officer** | Read-all: audit logs, fair lending, export, AI agent compliance queries; no model edit |
| **Data Scientist** | Read/write: model registry, feature store, AI model risk queries; no policy deploy |
| **Loan Officer** | Read-limited: own decisions only; reason codes only; no AI agent access |
| **Internal Auditor** | Read-all (+code export): AI session logs, decision sampling, code artifacts; no write |
| **Auditor (External)** | Read-only: scoped to defined review period; watermarked exports, no AI agent |

---

### 4.2 Module 2: Decisioning Engine

#### 4.2.1 Policy Orchestration

| ID | Requirement | Priority |
|---|---|---|
| DE-001 | Support rule-based policy (if/then/else decision trees) via AST-validated DSL — no `eval()` risk | P0 |
| DE-002 | Support scorecard-based decisioning (logistic regression scorecards) | P0 |
| DE-003 | Support ML model scoring (gradient boosting, neural nets via REST) | P0 |
| DE-004 | Support waterfall policy logic (pre-screen → score → policy overlay → final decision) | P0 |
| DE-005 | Support exception and override workflow with mandatory justification capture | P0 |
| DE-006 | Override logging: who, when, why, what changed — immutable, dual-approver | P0 |
| DE-007 | Configurable decision matrix: approve / decline / refer / conditional | P0 |
| DE-008 | Real-time decisioning API: 95th percentile latency < 200ms end-to-end | P0 |
| DE-009 | Batch decisioning: process 100K+ applications per hour | P1 |
| DE-010 | Shadow mode: run new policy/model alongside production without affecting decisions | P1 |
| DE-011 | Decision consistency score: policy-model alignment metric logged per decision | P1 |

**Decisioning Latency Budget (p95 < 200ms):**
```
API Gateway → Auth + Rate Limit                 < 5ms
Feature Resolution → Redis cache → Feature store < 10ms
Bureau Pull (if not cached)                     < 30ms
Model Scoring (SageMaker / embedded)            < 20ms
Policy Rule Engine                              < 15ms
Explainability (SHAP reason codes)              < 10ms
Audit Log Write (async, non-blocking via Kafka) < 50ms (async)
Decision Response                               < 5ms
──────────────────────────────────────────────────────
Total synchronous path: ≈ 90–140ms (well within 200ms SLA)
```

#### 4.2.2 Credit Bureau Integration

| Bureau | Data Type | Refresh Rate |
|---|---|---|
| Experian | Full credit file, FICO | Per application |
| Equifax | Full credit file, FICO | Per application |
| TransUnion | Full credit file, VantageScore | Per application |
| All three | Soft pull (pre-screen) | Per pre-qualification |

**Functional Requirements:**
- Automated bureau waterfall (primary to secondary on freeze/freeze-not-found)
- Bureau response caching: configurable 0–90 days per product type
- Bureau error handling: failover rules when bureau is unavailable
- All bureau pulls logged with permissible purpose metadata (FCRA compliance)

#### 4.2.3 Alternative Data Integrations

| Provider | Data Type | Priority |
|---|---|---|
| Plaid | Bank statement / cash flow data | P2 |
| Finicity | Income + asset verification | P2 |
| Nova Credit | Newcomer credit file translation | P3 |
| Experian Lift | Alternative credit scoring | P3 |

#### 4.2.4 A/B Testing Framework

| ID | Requirement | Priority |
|---|---|---|
| AB-001 | Split traffic by configurable percentage across policy/model variants | P1 |
| AB-002 | Statistical significance calculator built into experiment results view | P1 |
| AB-003 | Guard rails: automatically halt experiment if approval rate or AIR diverges beyond threshold | P1 |
| AB-004 | Experiment results exportable as model validation evidence | P2 |
| AB-005 | Support multiple concurrent experiments with conflict detection | P2 |
| AB-006 | Champion/challenger framework: traffic splitting with configurable guardrails | P2 |

---

### 4.3 Module 3: Portfolio Monitoring & Analytics

#### 4.3.1 Real-Time Dashboard Requirements

**Tier 1 — Portfolio-Level Metrics (home screen):**
- Total originations (MTD, QTD, YTD) by count and dollar volume
- Approval rate (overall and by channel, segment, product)
- Average loan amount, average credit score at origination
- Delinquency rate (30/60/90+ DPD) — real-time, updated daily
- Charge-off rate (MTD, trailing 12 months)
- Portfolio yield
- **Audit Readiness Score** (0–100 composite: traceability + reason codes + model validation + fair lending)
- **Active AI Agent Insights** (last 3 AI-generated insights with confidence scores)

**Tier 2 — Segment-Level Drill Down:**
- Vintage analysis: origination cohort performance by month, score band, geography
- Segment P&L contribution estimate
- Behavioral score migration (score changes post-booking)
- Policy rule hit rates (what % of applicants hit each decline rule)
- Delinquency roll rate matrix (current → 30 → 60 → 90 → charge-off)

**Tier 3 — Loan-Level Drill Down:**
- Individual application decision replay (full audit trail)
- Current loan status, payment history
- Reason code display at origination
- SHAP feature attribution view

#### 4.3.2 Alerting on Portfolio Metrics

| Metric | Alert Trigger | Default Threshold |
|---|---|---|
| 30+ DPD Rate | Exceeds rolling 90-day high | +50 bps |
| Approval Rate | Drops materially in rolling 7-day window | -500 bps |
| Charge-off Rate | Exceeds budget trajectory | +25 bps |
| Bureau Pull Error Rate | Service degradation | > 2% |
| Score Distribution Shift | PSI > 0.10 | 0.10 |
| AIR (Fair Lending) | Falls below 4/5ths rule | < 0.80 |
| Pricing Disparity (APR) | Controlled mean difference by protected class proxy | > 25 bps |
| Model AUC | Drop vs. validation baseline | > 0.02 absolute |
| Model Validation Overdue | Days since last independent validation | > 375 days |

#### 4.3.3 NLG-Powered Executive Summaries

Auto-generated weekly/monthly summary for CRO / Board use. All narratives are data-grounded: numbers cited in summaries reconcile to source queries in the AI audit log.

Example output:
> *"For the quarter ending March 31, 2026, the portfolio originated $37.2M across 3,821 accounts, with an average credit score of 714. The 30+ DPD rate is 4.2%, up 67 basis points from the prior month, driven primarily by the 620-659 score band (8.7% DPD). The approval rate declined 220 basis points following the January policy tightening. Fair lending indicators remain within acceptable bounds: Adverse Impact Ratio by race/ethnicity is 0.87, above the 0.80 regulatory threshold. No regulatory examinations are pending. Next model recertification is due June 2026."*

---

### 4.4 Module 4: Compliance & Audit Layer

#### 4.4.1 Automated Exam Packet Generation

**Description:** On-demand or scheduled generation of complete, regulator-ready exam packets. Generation time SLA: < 5 minutes for any configurable date range.

**Exam Packet Components:**

| Component | Content | Regulator |
|---|---|---|
| Policy History | All policy versions, effective dates, change justifications | OCC, CFPB |
| Decision Log Summary | Volume, outcomes, overrides by period | OCC |
| Model Validation Summary | Current model, last validation date, performance metrics | Fed SR 11-7 |
| Fair Lending Analysis | AIR by protected class, methodology, remediation actions | CFPB, DOJ |
| Adverse Action Summary | Volume, reason code distribution, notice compliance check | CFPB, ECOA |
| Data Governance Evidence | Data lineage, source documentation, quality checks | OCC |
| Override Log | All manual overrides with justification and approval | OCC, CFPB |
| **AI Agent Audit Appendix** | All AI queries, plans, SQL code, Python code, BigQuery job IDs, confidence scores, and result hashes from the exam period | OCC, CFPB (SR 11-7 AI extension) |

**Format Options:** PDF (regulator-facing), Excel (analyst working papers), ZIP archive (all files, including `.sql` and `.py` code artifacts from AI answers)

#### 4.4.2 Adverse Action Notice Management

**Functional Requirements:**
- Auto-generate Reg B-compliant adverse action notice for every decline
- Support all required forms: CFPB Model Form C-1 through C-5
- Delivery channel tracking: mail, email, in-app — with timestamp proof
- 30-day notice delivery deadline monitoring with alert if approaching
- Multi-lender template management (for servicers handling multiple brands)

#### 4.4.3 Compliance Rules Engine

| Category | Regulatory Authority | Example Rules |
|---|---|---|
| Fair lending | ECOA / Reg B | Approval rate disparity ratio ≥ 0.80; no prohibited bases in decisioning |
| Adverse action | ECOA / Reg B | Every decline/counter-offer must have valid principal reason codes (max 4) |
| UDAAP | CFPB | No deceptive practices in pricing or limit assignment |
| Model risk | SR 11-7 / OCC 2011-12 | Models must have independent validation within 12 months of champion deployment |
| Data integrity | Internal / FFIEC | All input fields must have documented provenance; no post-hoc data modification |
| Override governance | Internal | All overrides require documented justification + second-level approver |
| MLA | Military Lending Act | MAPR ≤ 36% for covered borrowers; MLA status verified at origination |
| AI agent outputs | SR 11-7 (AI/ML extension) | Every AI-generated insight must be auditable, linked to source data, and code-transparent |

---

### 4.5 Module 5: Model Lifecycle Management

#### 4.5.1 Model Registry

| Field | Description |
|---|---|
| Model ID | UUID |
| Model Name | Human-readable name |
| Version | Semantic versioning (major.minor.patch) |
| Model Type | Logistic regression, XGBoost, LightGBM, neural net, scorecard |
| Training Date | UTC timestamp |
| Training Data Period | Start and end date of training data |
| Champion/Challenger | Status in production |
| Validation Status | Pending / Passed / Failed / Conditionally Approved |
| Last Performance Evaluation | Date + metrics snapshot |
| SR 11-7 Documentation | Linked model card |
| Registry Backend | MLflow (primary) with metadata indexed in platform DB |

#### 4.5.2 Model Performance Monitoring

**Metrics Tracked (Production Models, Daily Refresh):**

| Metric | Description | Alert Threshold |
|---|---|---|
| AUC-ROC | Discrimination ability | Drop > 0.02 vs. validation |
| KS Statistic | Separation between good/bad | Drop > 5 pp |
| PSI (score output) | Population stability — score distribution | PSI > 0.10 minor; > 0.25 major |
| PSI (features) | Input feature distribution shift | PSI > 0.25 per feature |
| Gini Coefficient | Predictive power | Drop > 3 pp |
| Calibration Error | Score → probability accuracy | Brier score shift > 0.01 |
| Approval Rate by Score Band | Decision consistency | ±10% vs. 90-day baseline |
| Validation Overdue | Days since last independent review | > 375 days = non-compliant |

#### 4.5.3 Model Card Auto-Generation (SR 11-7 Aligned)

Auto-generated model card includes:
- Model overview and intended use
- Training data description, date range, and feature dictionary
- Out-of-time validation results (AUC, KS, Gini, PSI)
- Known limitations and edge cases
- Monitoring plan and recertification schedule
- Developer and validator signatures (digital approval workflow)
- Approval status and governance committee sign-off
- Champion/challenger deployment history

---

### 4.6 Module 6: RAG-Powered AI Analytics Agent Platform

This module delivers the net-new AI intelligence layer. The AI Agent Platform operates with **zero hallucination tolerance** — every answer is grounded in retrieved data from the decision store, audit logs, model documentation, and the compliance knowledge base. Every answer surfaces the full executable code used to produce it.

#### 4.6.1 AI Agent Capabilities

**Context Understanding Engine:**
- Interpret ambiguous credit risk and compliance questions using domain-tuned prompt templates
- Identify business intent, risk metrics / KPIs, time horizons, and required data sources
- Classify question type: descriptive, diagnostic, predictive, prescriptive, or compliance-specific
- Maintain **session memory** across multi-turn conversations (Redis-backed context store)
- Detect when a question requires regulatory interpretation vs. data retrieval, and route accordingly

**Example intent classifications:**

| User Question | Detected Intent | Routed To |
|---|---|---|
| "Why did approvals drop last month?" | Diagnostic / Portfolio | PortfolioAnalyticsAgent |
| "Are we at fair lending risk?" | Compliance / Fair Lending | FairLendingAgent + Regulatory KB |
| "Generate the Q2 audit package" | Governance / Document | AuditGovernanceAgent |
| "Show model drift for the PD model" | Model Risk / Performance | ModelRiskAgent |
| "What models are overdue for validation?" | SR 11-7 / Governance | ModelRiskAgent + MLflow |

#### 4.6.2 RAG (Retrieval-Augmented Generation) Layer

The RAG layer grounds every AI response in verified enterprise data — preventing hallucination at the architectural level.

**Retrieval Sources:**

| Source | Content | Technology |
|---|---|---|
| Decision store audit tables | Decision logs, performance data, fair lending metrics | PostgreSQL (hot) + BigQuery (analytics) |
| Analytics store | Portfolio KPIs, vintage curves, roll rates | BigQuery / Snowflake materialized views + Pandas |
| MLflow / Model registry | Model versions, training metrics, validation status | MLflow Python API |
| Policy DSL repository | Credit policy rules, change history | Git-backed, parsed AST |
| Regulatory knowledge base | SR 11-7, ECOA/Reg B, UDAAP rules text | Vector DB (Vertex AI Matching Engine or Pinecone) |
| Governance document store | MDD templates, exam packages, committee minutes | GCS / S3 + metadata index |
| Compliance engine rules | Configured compliance rules | In-memory + structured extraction |

**Retrieval Architecture:**
- **Schema-aware SQL generation**: Query Builder Agent generates SQL validated against registered schemas — never raw LLM SQL executed blindly
- **Hybrid search**: semantic (embedding-based) + keyword for documentation retrieval
- **Data lineage awareness**: every retrieved data point carries its lineage tag (source table, partition date, query hash)
- **Vector DB**: Vertex AI Matching Engine or Pinecone for regulatory KB and document embeddings

#### 4.6.3 Analysis Planning Engine

Before any data query is executed, the Planning Agent generates a transparent, user-reviewable plan. Users may approve, edit, or cancel the plan before execution (configurable; required in strict/compliance mode).

```
Analysis Plan: "What drove the approval rate decline in March?"
─────────────────────────────────────────────────────────────
Step 1: Query decision_logs for March vs. February approval rates
        → Tables: audit.decision_log | Partition: 2026-02-01 to 2026-03-31
        → Grouping: decision_month, risk_tier, product_type

Step 2: Decompose decline reasons by reason_code
        → Tables: audit.adverse_action_reasons | Join: decision_id

Step 3: Cross-reference model score distribution changes (PSI)
        → Tables: model_monitoring.score_distribution | Metric: PSI > 0.1

Step 4: Investigate policy rule change log for the period
        → Source: policy_dsl version history (Git)

Assumptions: Approval rate = approved / total (excluding withdrawn)
Confidence: HIGH (all required data partitions present and complete)
Estimated execution time: ~8 seconds
```

#### 4.6.4 Query Generation & Execution Engine

- **SQL Generation**: Query Builder Agent generates BigQuery / PostgreSQL SQL via structured prompting with schema injection
- **Validation before execution (mandatory)**:
  - Syntax validation (DB dry-run — zero data processed)
  - Schema alignment check (column names and types verified against registered schema)
  - Data access permission check (row-level security, RBAC)
  - Prohibited column filter (PII masked; ECOA-prohibited variables flagged)
- **Execution**: secure sandbox — queries executed via service account with read-only permissions
- **Auditable compute**: every query and its hash logged to `audit.agent_query_log` before execution
- **Python analysis**: Pandas / Scikit-learn for statistical analysis on query results (not raw LLM computation)
- **Code capture (mandatory)**: every SQL query and Python analysis snippet is captured verbatim at execution time and attached to the answer as a `code_artifact` — never reconstructed after the fact
- **Code serialization**: code artifacts stored as versioned, immutable objects in S3 / GCS alongside the answer JSON

#### 4.6.5 Code Transparency Layer *(Key Differentiator)*

**Principle:** Every AI-generated analysis answer MUST be accompanied by the complete, executable code that produced it. The user is never asked to trust a number they cannot verify.

**What is surfaced per answer:**

| Code Artifact | Content | Format |
|---|---|---|
| **SQL Query** | Exact query executed — including all WHERE clauses, JOINs, GROUP BYs, filters | `.sql` file or inline code block |
| **Python Analysis Script** | Pandas / Scikit-learn for all post-query computation (roll rates, PSI, t-tests, Gini) | `.py` file or inline code block |
| **Execution Metadata** | DB Job ID, bytes processed, execution timestamp, row count returned | JSON metadata block |
| **Reproducibility Instructions** | Step-by-step: authenticate → connect → run SQL → run Python → compare output | Plain-text block in output |

**Code Transparency Rules (Non-Negotiable):**
1. Code is captured at execution time and stored immutably — never regenerated from LLM after the fact
2. Code is displayed inline in the chat UI in a syntax-highlighted, copyable code block
3. Code is included in every PDF appendix and every Excel `Code` tab — no exceptions
4. `[Copy SQL]` / `[Run in Console]` / `[Download .py]` / `[Export as Notebook]` actions always available
5. If any step has no code (e.g., retrieval from a document store), this is explicitly stated
6. `FormatterAgent` blocks output delivery if `code_artifacts` array is empty

#### 4.6.6 Multi-Agent Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  ILOL AI Agent Platform                      │
├──────────────────────────────────────────────────────────────┤
│  User Query (Command Center UI / REST API)                   │
│      │                                                       │
│      ▼                                                       │
│  CoordinatorAgent ← Session memory (Redis) + RBAC           │
│      │                                                       │
│  ┌───┴────────────────────┐                                  │
│  ▼                        ▼                                  │
│  IntentClassifierAgent    ComplianceGateAgent                │
│      │                    (blocks PII / prohibited vars)     │
│      ▼                                                       │
│  PlannerAgent ← Schema registry + ambiguity detection       │
│      │  (plan shown to user; approval gate if strict mode)  │
│      ▼                                                       │
│  ┌──────────────────────────────────────────┐               │
│  │       Specialist Agent Routing           │               │
│  │  PortfolioAnalytics | FairLending |      │               │
│  │  ModelRisk | AuditGovernance             │               │
│  └──────────────────┬───────────────────────┘               │
│                     ▼                                        │
│  DataRetrievalAgent (DB | MLflow | GCS/S3 | RAG)            │
│                     ▼                                        │
│  QueryBuilderAgent (dry-run | schema | PII mask)            │
│                     ▼                                        │
│  ExecutionAgent (read-only service account)                 │
│                     ▼                                        │
│  InsightGeneratorAgent + RegulatoryInterpreterAgent         │
│                     ▼                                        │
│  ValidatorAgent (reconciliation + confidence scoring)       │
│                     ▼                                        │
│  FormatterAgent (PDF | Excel | PPT | JSON | AuditLog)       │
│         ↑ blocks output if code_artifacts missing           │
└──────────────────────────────────────────────────────────────┘
```

**Specialist Agent Responsibilities:**

| Agent | Responsibility |
|---|---|
| `CoordinatorAgent` | Session management, routing, RBAC enforcement |
| `IntentClassifierAgent` | Classify query type, extract entities |
| `ComplianceGateAgent` | Block queries exposing prohibited/PII data |
| `PlannerAgent` | Generate step-by-step analysis plan |
| `PortfolioAnalyticsAgent` | Portfolio, vintage, roll rate, delinquency analysis |
| `FairLendingAgent` | Disparate impact, approval rate disparity, BISG testing |
| `ModelRiskAgent` | PSI, AUC drift, SR 11-7 validation status |
| `AuditGovernanceAgent` | Audit package assembly, policy documentation |
| `DataRetrievalAgent` | RAG retrieval from all sources |
| `QueryBuilderAgent` | SQL generation + validation + dry-run |
| `ExecutionAgent` | Execute validated queries (read-only) |
| `InsightGeneratorAgent` | Statistical analysis + narrative generation |
| `RegulatoryInterpreterAgent` | Map findings to regulatory requirements (KB-grounded) |
| `ValidatorAgent` | Anti-hallucination reconciliation + confidence scoring |
| `FormatterAgent` | Multi-format output + code artifact injection |

#### 4.6.7 AI Agent Output Formats

| Output Type | Contents |
|---|---|
| **Executive Brief (PDF)** | AI narrative + charts + data citations + confidence scores + **appendix: full code** |
| **Exam Response Package (PDF)** | Mapped to examiner request items, version-stamped + **appendix: full code** |
| **Excel Workbook** | Raw data \| Aggregations \| Pivot tables \| AI narrative \| **SQL + Python code tab** |
| **PowerPoint** | Chart-first slides with AI-generated commentary |
| **JSON / API Response** | Structured insight object with lineage metadata + **`code_artifacts` array** |
| **Audit Log Entry** | Query, plan, result hash, confidence score, timestamp, **code artifact storage URIs** |
| **Standalone Code Export (.zip)** | Raw `.sql` and `.py` files downloadable as a single archive |

---

### 4.7 Module 7: Tenant-Scoped Semantic Layer

The Tenant-Scoped Semantic Layer is the vocabulary and schema intelligence layer that sits between raw BigQuery tables and the AI Analytics Agent. It answers the foundational question that no generic NL-to-SQL system can answer alone: **"What does *this term* mean for *this tenant*?"**

#### 4.7.1 Rationale

**Problem: Natural language queries break at tenant vocabulary boundaries.**

The ILOL platform serves lenders with genuinely different vocabularies, product configurations, and data sources. When a risk analyst at Tenant A asks "show me thin-file approval rates," the AI agent must know:
- That "thin file" maps to the SQL predicate `is_thin_file = 1` on `loan_applications` — not to `tradeline_count < 5` on a bureau enrichment table that Tenant B has registered
- That "approval rate" means `COUNTIF(decision='APPROVE') / COUNT(*)` for Tenant A, but Tenant B has redefined it to exclude manual reviews from the denominator
- That Tenant C's question "show me gold-band performance" refers to their internal segmentation scheme stored in a custom bureau enrichment table not present on any other tenant's schema

Without a semantic layer, the AI agent faces three failure modes:
1. **Silent mistranslation** — maps a tenant-specific term to the wrong platform column and returns a plausible but incorrect number
2. **Hard failure** — cannot resolve the term at all; returns an unhelpful error
3. **Hallucination** — LLM parametric memory fills the gap with a fabricated definition

All three failure modes are unacceptable in a regulated lending environment. The Tenant-Scoped Semantic Layer eliminates them architecturally.

**Problem: Tenants bring data that the platform schema does not anticipate.**

Mid-market lenders increasingly combine platform data with proprietary enrichment sources: third-party bureau scores, internal behavioral scores, fintech data partnerships, or legacy core banking extracts. Any AI analytics capability that cannot query across these custom sources is immediately limited in value for the most analytically sophisticated tenants.

The Tenant-Scoped Semantic Layer enables tenants to register custom data sources — with full governance, lineage tracking, and schema drift protection — so the AI agent can join across them as naturally as it queries native platform tables.

#### 4.7.2 Architecture Overview

The semantic layer operates as a **two-tier resolution system** evaluated on every NL query before SQL generation:

```
┌──────────────────────────────────────────────────────────────────┐
│  NL QUERY: "What was the charge-off rate for gold-band           │
│  members last quarter?"   (Tenant: acme_cu)                      │
└─────────────────────────────────┬────────────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     AnalyticsScope         │
                    │  resolve(JWT → tenant_id)  │
                    └─────────────┬─────────────┘
                                  │
          ┌───────────────────────▼────────────────────────┐
          │           SEMANTIC RESOLUTION (two tiers)       │
          │                                                  │
          │  Tier 2: Tenant Registry (acme_cu)              │
          │    "gold-band" → score_band = 'GOLD'            │
          │    (table: acme_custom_segments, join: app_id)  │
          │                                                  │
          │  Tier 1: Platform Glossary (fallback)           │
          │    "charge-off rate" → delinquency_bucket =     │
          │    'charged_off' / COUNT(*)                     │
          └───────────────────────┬────────────────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     SQL GENERATOR          │
                    │  (schema-injected context) │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     SQL VALIDATOR          │
                    │  allowlist · tenant_id     │
                    │  inject · PII strip        │
                    └─────────────┬─────────────┘
                                  │
                    ┌─────────────▼─────────────┐
                    │     EXECUTION + CITE       │
                    └────────────────────────────┘
```

Tenant-level entries always win over platform defaults. Platform glossary entries are `canonical=true` and cannot be overridden in ways that would introduce PII or ECOA-prohibited variable usage.

#### 4.7.3 Entry Types

The semantic registry supports four entry types, each versioned, SHA-256 hashed for tamper detection, and append-only:

| Entry Type | What It Defines | Example |
|---|---|---|
| `glossary_term` | Maps a business term (+ synonyms) to a SQL predicate or column | `"thin file" → is_thin_file = 1 ON loan_applications` |
| `synonym_override` | Tenant-specific label for a platform canonical value | `"approved" → decision = 'APPROVE'` (tenant uses lowercase) |
| `metric` | Named computed metric with formula SQL and base table | `"30-day approval rate" → COUNTIF(decision='APPROVE'...` |
| `table_schema` | Registers a net-new tenant data source for AI query scope | `acme_bureau_enrichments (join: application_id)` |

**Glossary term example (JSON):**
```json
{
  "entry_type": "glossary_term",
  "name": "gold-band",
  "display_name": "Gold Band Member",
  "description": "Internal segmentation tier for members with score 720-779",
  "synonyms": ["gold band", "gold tier", "gold segment"],
  "sql_predicate": "score_band = 'GOLD'",
  "applies_to_tables": ["acme_custom_segments"],
  "canonical": false
}
```

**Custom table schema example (JSON):**
```json
{
  "entry_type": "table_schema",
  "name": "acme_bureau_enrichments",
  "bigquery_table": "acme-tenant.crp_tenant_acme.bureau_enrichments",
  "join_key": "application_id",
  "join_to": "loan_applications",
  "columns": [
    {"name": "bureau_score", "type": "FLOAT64", "description": "Proprietary bureau score"},
    {"name": "tradeline_count", "type": "INTEGER", "description": "Number of open tradelines"}
  ],
  "requires_tenant_filter": true,
  "schema_hash": "sha256-of-column-definition"
}
```

#### 4.7.4 Governance Model

All semantic registry entries follow the same governance discipline as credit policy versions:

| Property | Specification |
|---|---||
| **Append-only** | Entries are never updated in place; new versions are appended; `is_active` flag controls which version is live |
| **SHA-256 tamper detection** | `definition_sha256` computed at registration; mismatch at query time blocks the query and triggers an alert |
| **Four-eyes control** | `table_schema` entries require a second approver (typically a `data_engineer`) via the four-eyes rule `tenant_schema_registration` |
| **Credit analyst authority** | `credit_analyst` role can propose glossary terms and metrics; proposals activate only after approval |
| **Schema drift protection** | If a registered table's live schema diverges from the registered `schema_hash`, NL queries referencing that table are blocked until re-approval |
| **Audit trail** | Every registration event logged with `approved_by`, `created_at`, and entry hash — included in exam packets |

**Schema drift protection flow:**
```
Tenant registers table → schema_hash stored → lineage node created

Every NL query referencing the tenant table:
  → compute live schema hash (INFORMATION_SCHEMA.COLUMNS)
  → compare to registered hash
  → MATCH:    proceed with query
  → MISMATCH: block query, return HTTP 422
               "Schema drift detected on table acme_bureau_enrichments.
                Re-register at POST /v1/analytics/tenant/schema/register."
               → flag for four-eyes re-approval
```

#### 4.7.5 Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| SEM-001 | Platform glossary harvested automatically from `data_contracts` enum values at service startup | P0 |
| SEM-002 | Platform metric registry includes 9 named metrics (`approval_rate`, `charge_off_rate`, `expected_loss`, `dir_score`, etc.) resolvable by name in NL queries | P0 |
| SEM-003 | Tenant glossary terms, synonym overrides, and custom metrics stored in append-only `tenant_semantic_registry` BigQuery table with SHA-256 per entry | P0 |
| SEM-004 | Tenant-registered custom data source (`table_schema`) enrolled in data lineage as `external_data_source` node — visible in lineage DAG and exam packets | P0 |
| SEM-005 | Two-tier resolution: tenant entries win over platform defaults at query time; resolution logged per NL query | P0 |
| SEM-006 | `POST /v1/analytics/tenant/schema/register` — registers a new tenant table schema; requires four-eyes approval for `table_schema` entry type | P0 |
| SEM-007 | `GET /v1/analytics/glossary` — returns merged platform + tenant glossary for the authenticated tenant (no cross-tenant leakage) | P0 |
| SEM-008 | `POST /v1/analytics/tenant/glossary` — proposes a new glossary term or metric; credit_analyst role required | P1 |
| SEM-009 | Schema drift detection on every NL query that references a tenant-registered table; block + alert on mismatch | P0 |
| SEM-010 | Semantic registry entries included in exam packet `Data Governance Evidence` section — version, approver, hash | P1 |
| SEM-011 | Platform admin can inspect all active semantic entries for a tenant via admin API | P1 |
| SEM-012 | Tenant semantic entries carry version history; roll back to any prior entry version with single action | P2 |
| SEM-013 | `external_service` role (e.g., LucidCredit) receives merged glossary in analytics API responses — no direct DB access | P1 |

#### 4.7.6 Integration with the AI Agent Pipeline

The semantic layer is injected into the AI agent pipeline at the `PlannerAgent` step. This is the only point where tenant-specific vocabulary is resolved — ensuring the SQL generator always receives schema-accurate, tenant-correct context.

```
CoordinatorAgent → IntentClassifierAgent
                           │
                  PlannerAgent  ← AnalyticsScope.merged_glossary
                           │     ← AnalyticsScope.metrics
                           │     ← AnalyticsScope.allowed_tables
                  QueryBuilderAgent  (schema injection complete)
                           │
                  SQLValidator  (tenant_id injection, allowlist)
                           │
                  ExecutionAgent
                           │
                  ValidatorAgent  ← citations carry semantic entry version
                           │
                  FormatterAgent
```

Every AI answer whose SQL used a tenant-defined term includes the semantic entry version in its citation:
```
[Source: acme_custom_segments.score_band | Term: "gold-band" v1.0.0 | Query: q-abc123 | Date: 2026-04-01]
```

This citation is included in exam packet appendices, making tenant vocabulary choices auditable alongside the data queries themselves.

#### 4.7.7 Semantic Layer in Exam Packets

The `Data Governance Evidence` section of every exam packet includes a **Tenant Semantic Registry Appendix** containing:
- All active glossary terms and their definitions (version, approved_by, SHA-256)
- All registered custom table schemas with schema hashes and lineage node IDs
- All custom metric formulas with formula SQL
- Any schema drift events detected during the exam period (including which queries were blocked)

This gives examiners full visibility into what vocabulary the AI agent was operating with — eliminating a key source of AI explainability risk in regulatory submissions.

---

## 5. Anti-Hallucination Framework (Regulatory-Grade)

In a regulated lending environment, a single hallucinated metric or fabricated reason code can constitute a regulatory violation. This framework is **architecturally enforced** — not advisory.

### 5.1 Zero Hallucination Principle

**If data is unavailable or insufficient, the system MUST return:**
```
"Insufficient data to answer this question. The required table [table_name]
does not contain data for the requested time period [period]. Please verify
that data ingestion has completed or narrow the query scope."
```

**The system MUST NEVER:**
- Fabricate any metric, ratio, percentage, or count
- Infer a value not present in retrieved data
- Use LLM parametric knowledge to answer questions about the institution's portfolio
- Generate a reason code, policy rule, or regulatory citation not retrieved from the knowledge base
- Round numbers without explicit disclosure of rounding methodology

### 5.2 Architectural Enforcement Layers

| Layer | Enforcement Mechanism | Component |
|---|---|---|
| **Semantic Layer Grounding** | Platform glossary + tenant glossary resolved before schema injection; SQL never generated against undefined terms | `AnalyticsScope` + `PlannerAgent` |
| **Schema Grounding** | SQL generated only against registered schemas; schema injected at generation time | `QueryBuilderAgent` |
| **DB Dry-Run Validation** | Every SQL query validated (zero bytes) before execution | `QueryBuilderAgent` |
| **Result Reconciliation** | AI narrative numbers must match query result set (deterministic check) | `ValidatorAgent` |
| **Source Citation Enforcement** | Every stated fact must carry `[Source: table.column \| Query: hash \| Date: timestamp]` | `ValidatorAgent` |
| **Confidence Scoring** | HIGH / MEDIUM / LOW based on data completeness and statistical significance | `ValidatorAgent` |
| **Prohibited Variable Guard** | PII and ECOA-prohibited variables masked at query time | `ComplianceGateAgent` |
| **Regulatory Citation Grounding** | Regulatory references retrieved from vector KB — not from LLM memory | `RegulatoryInterpreterAgent` |
| **Output Audit Trail** | Every output includes: source queries, row counts, computation steps, LLM prompt hash | `FormatterAgent` |

### 5.3 Confidence Score Definition

| Tier | Definition | Required Disclosure |
|---|---|---|
| **HIGH** | Query returned results; n > 30; no data gaps | None — stated as verified fact |
| **MEDIUM** | Data partially available; time period incomplete; proxies used (e.g., BISG) | "Note: result based on [n] records covering [x]% of requested period" |
| **LOW** | Extrapolated from limited data; benchmark estimate; required data absent | "ESTIMATE ONLY — insufficient data. Do not use in regulatory submissions." |

### 5.4 Failure Handling

| Failure Mode | System Response |
|---|---|
| Query returns zero rows | Explicitly state no data found; do not interpret silence as zero |
| Schema mismatch detected | Abort; surface error to user with table name and column |
| Data ingestion lag | Flag staleness with last-updated timestamp before returning results |
| Ambiguous metric definition | Ask clarifying question: "Do you mean 30-day or any delinquency?" |
| Tenant term not in glossary | Ask clarifying question: "I don't have a definition for 'gold-band'. Do you mean score_band = 'GOLD'? If so, register this term at Settings → Glossary." |
| Schema drift on tenant table | Block query; return `schema_drift_detected` error with re-registration link; log to governance incident queue |
| LLM response cannot be reconciled with data | Return data only; suppress narrative; log hallucination attempt to monitoring |
| Regulatory KB retrieval fails | Return data answer only; flag that regulatory framing is unavailable |
| Code artifact missing | `FormatterAgent` blocks output delivery; logs error to incident queue |

---

## 6. UX & Workflow Design

### 6.1 Design Philosophy

ILOL's UI is a **Credit Command Center** — designed for power users who need to move between data, decisions, documentation, and AI-assisted analytics without context switching. The UX is:

- **Information-dense but not cluttered** — financial professionals want data, not marketing
- **Action-oriented** — every view has a clear call-to-action (simulate, export, alert, investigate, ask AI)
- **Progressive disclosure** — summary → segment → loan → decision in consistent drill-down pattern
- **Code-transparent** — AI answers default to collapsed code panels; always expandable and downloadable
- **Accessibility-first** — WCAG 2.1 AA compliance minimum

### 6.2 Primary Workflows

#### Workflow 1: Decisioning Command Center

```
┌──────────────────────────────────────────────────────────────────┐
│  ILOL  │ Portfolio  │ Decisioning  │ Compliance  │ Models  │ AI  │
├──────────────────────────────────────────────────────────────────┤
│  REAL-TIME DECISIONING VIEW                                       │
│  Today: 1,247 applications │ 72% Approved │ 21% Declined          │
│                                                                   │
│  ┌──────────────────────┐  ┌────────────────────────────────────┐ │
│  │ APPLICATION FEED     │  │ DECISION DETAIL                    │ │
│  │ APP-20260407-8821    │  │ APP-20260407-8821                  │ │
│  │ ● APPROVED  $12,500  │  │ Score: 742 │ Policy: v2.4.1        │ │
│  │ APP-20260407-8820    │  │ Decision: APPROVED                 │ │
│  │ ○ DECLINED           │  │                                    │ │
│  │ APP-20260407-8819    │  │ TOP FACTORS (SHAP)                 │ │
│  │ ● APPROVED  $8,000   │  │ + Payment history   +0.18          │ │
│  │ APP-20260407-8818    │  │ + Utilization       +0.12          │ │
│  │ ○ REFERRED           │  │ - DTI ratio         -0.08          │ │
│  └──────────────────────┘  │ - Account age       -0.04          │ │
│                             │                                    │ │
│                             │ POLICY RULES EVALUATED             │ │
│                             │ ✓ Min score 620     PASS           │ │
│                             │ ✓ Max DTI 45%       PASS           │ │
│                             │ ✓ BK last 7 yrs     PASS           │ │
│                             │                                    │ │
│                             │ [Override] [Export] [History] [AI] │ │
│                             └────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

**Override Workflow:**
1. Analyst selects "Override"
2. System prompts: Override type (risk-based exception), justification (free-text + structured), approval routing
3. Override sent to dual-approver workflow (configurable by exception type and amount)
4. Approval/denial logged with timestamp, approver, and justification
5. Override decision logged in immutable audit trail

---

#### Workflow 2: Governance Export Center

```
┌──────────────────────────────────────────────────────────────────┐
│  COMPLIANCE  │  Exam Packets  │  Reports  │  Audit Logs           │
├──────────────────────────────────────────────────────────────────┤
│  EXAM PACKET GENERATOR                                            │
│  Date Range: [01/01/2026] → [03/31/2026]   Product: [All ▼]      │
│  ───────────────────────────────────────────────────────         │
│  INCLUDE IN PACKET:                                               │
│  ☑ Policy Version History (v2.2.0 – v2.4.1, 3 versions)         │
│  ☑ Decision Log Summary (47,821 decisions)                       │
│  ☑ Override Log (142 overrides, 98% approved)                    │
│  ☑ Fair Lending Analysis (AIR: 0.87 Race/Ethnicity)              │
│  ☑ Adverse Action Summary (11,203 declines, 100% AA issued)      │
│  ☑ Model Validation Summary (AUC: 0.742, last validated 2/2026)  │
│  ☑ Data Lineage Evidence                                          │
│  ☑ AI Agent Audit Appendix (SQL + Python code per AI answer)     │
│  ───────────────────────────────────────────────────────         │
│  Format: ● PDF  ○ Excel  ○ Both + Code Archive (.zip)            │
│  Template: [OCC Examination ▼]                                    │
│  Estimated generation time: ~2.3 minutes                          │
│  [Generate Packet]       Last generated: 2026-03-01 by Sandra     │
└──────────────────────────────────────────────────────────────────┘
```

---

#### Workflow 3: AI Agent Command Center

```
┌──────────────────────────────────────────────────────────────────┐
│  AI ANALYTICS AGENT                                               │
├──────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Ask anything about your portfolio...                 [Ask] │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  AI Answer [HIGH confidence]:                                     │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │ Approval rates for thin-file applicants declined 8.2 pp  │    │
│  │ in Q1 2026 vs Q1 2025.  Source: audit.decision_log       │    │
│  │ n=4,200 decisions │ Policy change: 60% │ Score drift:     │    │
│  │ 30% │ Bureau coverage: 10%              [HIGH confidence] │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  [👁 Show Code ▾] [Export PDF] [Export Excel] [Export .zip]       │
│                                                                   │
│  └─ SQL Query (Step 1 of 3):                                      │
│     SELECT DATE_TRUNC(decision_timestamp, QUARTER) AS qtr,       │
│       bureau_score_band,                                          │
│       COUNTIF(outcome='APPROVE') / COUNT(*) AS rate              │
│     FROM `project.audit.decision_log`                            │
│     WHERE bureau_score_band = 'thin_file'                        │
│       AND decision_timestamp BETWEEN '2025-01-01' AND '2026-03-31'│
│     GROUP BY 1, 2                                                 │
│     [Copy SQL] [Run in Console] [Download .sql]                   │
│                                                                   │
│  └─ Python (Step 2): [Copy Python] [Download .py] [→ Notebook]   │
│     Job ID: bqjob_r75a... │ 2.1 MB │ 4,200 rows │ 09:32:11Z      │
└──────────────────────────────────────────────────────────────────┘
```

---

#### Workflow 4: Portfolio Monitoring Command Center

```
┌──────────────────────────────────────────────────────────────────┐
│  PORTFOLIO MONITORING                                             │
├──────────────────────────────────────────────────────────────────┤
│  ● 3 Active Alerts   ▲ 30+ DPD at 4.2% (+67bps MoM)             │
│                                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ ORIGS    │ │ APPROVAL │ │ 30+ DPD  │ │ NET C/O  │           │
│  │ $12.4M   │ │ RATE     │ │ 4.2%     │ │ 1.8%     │           │
│  │ MTD      │ │ 71.3%    │ │ ▲ +67bps │ │ ▼ -12bps │           │
│  │ ▲ +8%    │ │ ▼ -220bp │ │          │ │          │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                                                                   │
│  VINTAGE ANALYSIS                   SEGMENT PERFORMANCE           │
│  [chart: 12-month cohort            Score Band  Vol   DPD30      │
│   performance by vintage]           780+        22%   0.8%       │
│                                     720-779     31%   1.9%       │
│                                     660-719     28%   4.1%       │
│                                     620-659     19%   8.7%       │
│                                                                   │
│  [Drill down: Segment → Loan → Decision]  [Ask AI about this ▸]  │
└──────────────────────────────────────────────────────────────────┘
```

### 6.3 Intelligent Alerting UI

- Alert inbox with severity (Critical / Warning / Informational)
- Alert detail: metric name, current value, threshold, trend chart, recommended action, regulatory citation
- One-click: acknowledge, investigate, escalate, suppress, or **ask AI to explain**
- Alert history with resolution log

---

## 7. System Architecture

### 7.1 Architecture Overview

ILOL follows a **modular microservices architecture** with a shared event bus, common data primitives, and API-first design. Each module is independently deployable but tightly integrated through well-defined contracts.

```
                      ┌──────────────────────────────────────┐
                      │          ILOL API GATEWAY             │
                      │   (AWS API Gateway + Kong)            │
                      └─────────────────┬────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
┌──────────────────┐       ┌─────────────────────┐       ┌──────────────────────┐
│  DECISIONING      │       │  GOVERNANCE /        │       │  PORTFOLIO           │
│  ENGINE SERVICE   │       │  AUDIT SERVICE       │       │  ANALYTICS SERVICE   │
│                   │       │                      │       │                      │
│ - Policy eval     │       │ - Audit log store    │       │ - Metrics engine     │
│ - Model scoring   │       │ - Policy versions    │       │ - Vintage analysis   │
│ - Rule engine     │       │ - Lineage tracker    │       │ - Cohort tracker     │
│ - Explainability  │       │ - Exam packet gen    │       │ - KPI aggregation    │
└────────┬──────────┘       └──────────┬───────────┘       └──────────┬───────────┘
         │                             │                               │
         └─────────────────────────────┼───────────────────────────────┘
                                       │
                          ┌────────────▼────────────────┐
                          │      EVENT BUS (Kafka)       │
                          └────────┬──────────┬──────────┘
                    ┌──────────────┘          └────────────────┐
                    ▼                                          ▼
        ┌─────────────────┐   ┌───────────────────┐   ┌──────────────────────┐
        │  COMPLIANCE      │   │  MODEL LIFECYCLE   │   │  AI ANALYTICS         │
        │  SERVICE         │   │  SERVICE           │   │  AGENT SERVICE        │
        │                  │   │                    │   │                       │
        │ - Fair lending   │   │ - Model registry   │   │ - Multi-agent orch.   │
        │ - AA notices     │   │ - Performance mon  │   │ - RAG / retrieval     │
        │ - Exam reports   │   │ - A/B framework    │   │ - Code transparency   │
        └──────────────────┘   └────────────────────┘   │ - Anti-hallucination  │
                                                         └──────────────────────┘
```

### 7.2 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **API Gateway** | AWS API Gateway + Kong | Rate limiting, auth, routing |
| **Service runtime** | Python (FastAPI) + Go (high-throughput services) | FastAPI for data-heavy; Go for latency-critical decisioning |
| **Event bus** | Apache Kafka (AWS MSK) | High-throughput, durable, replay support |
| **Decision store (hot)** | PostgreSQL (AWS RDS) | ACID compliance for decisioning hot layer |
| **Analytics store** | BigQuery (GCP) or Snowflake | SQL-first portfolio analytics; BigQuery preferred for AI agent integration |
| **Audit log store** | Amazon QLDB or append-only PostgreSQL | Cryptographically verifiable immutability |
| **Cold archive** | Amazon S3 | Cost-efficient long-term retention |
| **Feature store** | Feast (self-hosted) or Tecton | Consistent feature serving for training + inference |
| **Model serving** | MLflow + SageMaker endpoints | Versioned model serving with rollback |
| **Model registry** | MLflow | Metadata, lineage, validation status |
| **Cache** | Redis (AWS ElastiCache) | Bureau response caching, AI session memory |
| **Vector DB** | Vertex AI Matching Engine or Pinecone | Regulatory KB and document embeddings for AI RAG |
| **LLM (Primary)** | Google Gemini 1.5 Pro (Vertex AI) | GCP-native; tool use support; strong at structured data tasks |
| **LLM (Fallback)** | GPT-4o (OpenAI API) | Redundancy for critical compliance queries |
| **Embedding Model** | `text-embedding-004` (Vertex AI) | Consistent dimensions; GCP-native |
| **AI Orchestration** | Custom agent framework (`orchestration/pipeline.py`) | Audit-friendly; avoids LangChain version drift |
| **Code artifact store** | S3 / GCS | Immutable `.sql` + `.py` files per AI answer, SHA-256 hashed |
| **Search** | OpenSearch (AWS) | Audit log search, decision lookup |
| **Frontend** | Next.js + TypeScript | SSR for initial load, client-side for interactivity |
| **Auth** | Auth0 / AWS Cognito + RBAC | OIDC + JWT, role-based permissions |
| **NLG (Summaries)** | Gemini / GPT-4o with deterministic templates | Executive summaries; template fallback for regulatory outputs |
| **Infrastructure** | AWS (EKS for containers, RDS, MSK, S3); GCP (BigQuery, Vertex AI) | Multi-cloud for best-in-class at each layer |
| **IaC** | Terraform + Helm | Reproducible, auditable infrastructure |
| **CI/CD** | GitHub Actions + ArgoCD | GitOps deployment |
| **Observability** | Datadog (APM, logging, metrics) + Google Cloud Logging (AI layer) | Unified observability; SLA alerting |

### 7.3 Multi-Tenant Architecture

- **Tenant isolation model:** Shared infrastructure, isolated data (database-per-tenant on RDS)
- **Tenant configuration:** Per-tenant policy engine config, branding, and integration settings
- **Data isolation enforcement:** Row-level security (RLS) in PostgreSQL + tenant context in JWT
- **Tenant onboarding:** Self-service provisioning via admin API, completed in < 4 hours
- **Cross-tenant leakage prevention:** Automated test suite validates tenant data isolation on every deployment

### 7.4 Deployment Model

```
┌─────────────────────────────────────────────────────────────┐
│  AWS us-east-1 (Primary) + GCP us-central1 (Analytics/AI)   │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐  │
│  │ EKS Cluster │ │ RDS Multi-AZ│ │ BigQuery + Vertex AI  │  │
│  │ (services)  │ │ (per tenant)│ │ (analytics + AI agent)│  │
│  └─────────────┘ └─────────────┘ └───────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
               │  Active-Passive Failover
┌─────────────────────────────────────────────────────────────┐
│  AWS us-west-2 (DR / HA)                                     │
│  ┌─────────────┐ ┌─────────────┐                             │
│  │ EKS Cluster │ │ RDS Replica │                             │
│  │ (standby)   │ │ (read only) │                             │
│  └─────────────┘ └─────────────┘                             │
└─────────────────────────────────────────────────────────────┘
```

- **RTO:** < 1 hour | **RPO:** < 15 minutes

---

## 8. Data Architecture

### 8.1 Data Layer Overview

| Store | Purpose | Technology | Retention |
|---|---|---|---|
| **Decision Store** | Per-application decision record (hot) | PostgreSQL (RDS) | 7 years |
| **Feature Store** | Feature values at decision time + current values | Feast + Redis + S3 | 7 years |
| **Audit Store** | Immutable append-only log of all system + AI agent events | Amazon QLDB | 10 years |
| **Analytics Store** | Aggregated metrics, portfolio analytics, cohort analysis, AI agent queries | BigQuery / Snowflake | 10 years |
| **Model Store** | Model artifacts, versions, validation reports | S3 + MLflow | Indefinite |
| **AI Code Artifact Store** | Immutable SQL + Python per AI answer | S3 / GCS (versioned) | 10 years |
| **Tenant Semantic Registry** | Versioned glossary terms, metric formulas, and custom table schemas per tenant | BigQuery (append-only, SHA-256) | 7 years |

### 8.2 Decision Store Schema (Core)

```sql
-- applications table
CREATE TABLE applications (
    application_id      UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    external_ref        VARCHAR(100),
    applicant_id        UUID,                    -- anonymized / hashed
    product_type        VARCHAR(50),
    requested_amount    DECIMAL(12,2),
    channel             VARCHAR(50),
    submitted_at        TIMESTAMPTZ NOT NULL,
    decision_at         TIMESTAMPTZ,
    decision_outcome    VARCHAR(20),             -- APPROVED/DECLINED/REFERRED/WITHDRAWN
    approved_amount     DECIMAL(12,2),
    policy_version      VARCHAR(20),
    model_version       VARCHAR(20),
    override_flag       BOOLEAN DEFAULT FALSE,
    override_user_id    UUID,
    override_reason     TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- decision_features table
CREATE TABLE decision_features (
    id                  UUID PRIMARY KEY,
    application_id      UUID REFERENCES applications(application_id),
    feature_name        VARCHAR(100),
    feature_value       JSONB,
    source_system       VARCHAR(50),
    ingested_at         TIMESTAMPTZ,
    transformation      VARCHAR(100)
);

-- decision_scores table
CREATE TABLE decision_scores (
    id                  UUID PRIMARY KEY,
    application_id      UUID REFERENCES applications(application_id),
    model_id            UUID,
    model_version       VARCHAR(20),
    raw_score           DECIMAL(10,4),
    scaled_score        INTEGER,
    probability_of_default DECIMAL(8,6),
    reason_codes        JSONB,                   -- top 4 SHAP-based reason codes
    shap_values         JSONB                    -- full SHAP breakdown
);

-- policy_evaluations table
CREATE TABLE policy_evaluations (
    id                  UUID PRIMARY KEY,
    application_id      UUID REFERENCES applications(application_id),
    policy_version      VARCHAR(20),
    rules_evaluated     JSONB,
    waterfall_stage     VARCHAR(50),
    final_policy_outcome VARCHAR(20)
);
```

### 8.3 AI Agent Audit Log Schema (BigQuery)

```sql
-- audit.agent_query_log (append-only, BigQuery)
-- Partitioned by date; clustered by session_id
CREATE TABLE audit.agent_query_log (
    session_id          STRING,
    query_id            STRING,
    user_id             STRING,
    query_text          STRING,
    plan_json           JSON,
    sql_hash            STRING,
    result_row_count    INT64,
    confidence_score    STRING,       -- HIGH / MEDIUM / LOW
    output_type         STRING,
    timestamp           TIMESTAMP,
    code_artifact_uris  ARRAY<STRING>,   -- GCS/S3 URIs for .sql and .py files
    bq_job_ids          ARRAY<STRING>,   -- BigQuery job IDs for every executed query
    code_zip_uri        STRING,          -- pre-packaged .zip archive
    code_sha256_hashes  ARRAY<STRING>    -- tamper detection
);
```

### 8.4 Data Ingestion Architecture

**Batch (Nightly):**
- Core banking feeds via SFTP / S3 drop zone
- Performance data (delinquency, payoff, charge-off) loaded nightly
- ETL pipeline: AWS Glue + dbt for transformation

**Real-Time (Per Application):**
- Bureau API calls (synchronous, inline to decision path)
- LOS webhook (POST to ILOL API on application creation)
- Behavioral data streaming (payment events via Kafka)

**Data Quality Checks (Automated, per batch):**
- Null rate validation per field (configurable threshold)
- Distribution shift detection (PSI vs. prior 30-day baseline)
- Referential integrity checks (application ↔ decision ↔ feature)
- Completeness checks against expected record counts

### 8.5 LOS & Core Banking Integrations

| Integration | Supported Systems |
|---|---|
| LOS — REST API (certified) | MeridianLink (Year 1 priority), Encompass, Byte, LendingPad |
| LOS — SFTP batch | Legacy LOS (configurable field mapping) |
| Core Banking — REST API | Symitar, Jack Henry, Finxact, Temenos |
| Core Banking — DB read | SQL Server, Oracle (with VPN tunnel) |
| Data Warehouse push | Snowflake (native connector), BigQuery (service account), Redshift (P2) |

---

## 9. Compliance & Governance Framework

### 9.1 Regulatory Alignment Matrix

| Regulation | Requirement | ILOL Implementation |
|---|---|---|
| **ECOA / Reg B** | Adverse action notice, non-discrimination | Auto-generated AA notices; fairness monitoring; SHAP reason codes |
| **FCRA** | Permissible purpose, accuracy, dispute resolution | Bureau pull logging with permissible purpose; dispute flag in decision log |
| **SR 11-7** | Model risk management framework | Model registry, validation status, tiering, performance monitoring, auto-generated model cards |
| **CFPB UDAAP** | Unfair, deceptive, abusive acts | Decision consistency monitoring; override audit trail; fairness guardrails |
| **CRA** | Community Reinvestment Act | Geographic origination mapping; LMI lending metrics |
| **HMDA** | Home Mortgage Disclosure Act | HMDA LAR export with field mapping |
| **MLA** | Military Lending Act | MAPR ≤ 36% for covered borrowers; MLA status verified at origination |
| **SOC 2 Type II** | Security, availability, confidentiality | Encryption, RBAC, audit logging, availability SLAs |
| **GLBA** | Financial data privacy | PII encryption, access controls, data minimization |
| **SR 11-7 (AI/ML extension)** | AI model governance | AI agent audit log; code transparency; hallucination monitoring; human-in-the-loop for exam exports |

### 9.2 SR 11-7 Model Risk Management Compliance

**Pillar 1: Model Development**
- Auto-generated model cards document intent, training data, assumptions, limitations
- Model tier assignment (Tier 1: high risk/volume, Tier 2: moderate, Tier 3: low/simple)
- Documented validation plan required before production deployment

**Pillar 2: Model Validation**
- Independent validation workflow with conflict-of-interest controls (validator ≠ developer)
- Out-of-time and out-of-sample testing required for Tier 1 models
- Re-validation triggered by: PSI > 0.25, AUC drop > 0.03, data source change, or policy change affecting > 30% of decisions

**Pillar 3: Ongoing Monitoring**
- Daily refresh: AUC, KS, PSI, Gini, calibration
- Automated alerts at configurable thresholds
- Annual recertification schedule managed in model registry
- AI model risk agent: natural language queries on governance status with code transparency

### 9.3 PII Handling

| Data Category | Handling |
|---|---|
| SSN / Tax ID | AES-256 encrypted at rest; never logged in plain text; tokenized for analytics |
| Name / Address | Encrypted at rest; masked in non-production environments; `applicant_id_hash` (SHA-256 salted) used throughout |
| Protected class attributes | RBAC-restricted to compliance role; never in AI agent query scope (ComplianceGateAgent enforced) |
| Credit bureau data | Per FCRA: retained for permissible purpose period; access logged; no resale |
| Bank account data | Plaid access tokens rotated per NACHA; account numbers never stored |

---

## 10. API Design

### 10.1 API Design Principles

- **RESTful** (primary) with **GraphQL** available for analytics queries
- API versioning via URL path: `/api/v1/`, `/api/v2/`
- JSON request/response with consistent envelope structure
- All responses include `request_id` for tracing
- OpenAPI 3.0 specification auto-generated from code
- Authentication: Bearer JWT (OAuth 2.0 client credentials for service-to-service)

### 10.2 Core Endpoints

#### Decisioning API
```
POST   /api/v1/decisions
GET    /api/v1/decisions/{decision_id}
GET    /api/v1/decisions?from=&to=&outcome=&product=&page=&per_page=
POST   /api/v1/decisions/{decision_id}/override
```

#### Policy API
```
GET    /api/v1/policies
GET    /api/v1/policies/{policy_id}/versions
GET    /api/v1/policies/{policy_id}/versions/{version}/diff
POST   /api/v1/policies/{policy_id}/simulate
POST   /api/v1/policies/{policy_id}/rollback
```

#### Governance & Audit API
```
POST   /api/v1/audit/exam-packets
GET    /api/v1/audit/exam-packets/{job_id}
GET    /api/v1/audit/decisions/{decision_id}/lineage
GET    /api/v1/audit/decisions/{decision_id}/log
```

#### Compliance API
```
GET    /api/v1/compliance/fair-lending/report
GET    /api/v1/compliance/adverse-actions
GET    /api/v1/compliance/overrides
```

#### Portfolio Analytics API
```
GET    /api/v1/analytics/portfolio/summary
GET    /api/v1/analytics/portfolio/vintage
GET    /api/v1/analytics/portfolio/segments
```

#### Model Lifecycle API
```
GET    /api/v1/models
POST   /api/v1/models/{model_id}/deployments
GET    /api/v1/models/{model_id}/performance
GET    /api/v1/models/{model_id}/card
```

#### AI Agent API
```
POST   /api/v1/agent/query
GET    /api/v1/agent/sessions/{session_id}
POST   /api/v1/agent/audit-package
GET    /api/v1/agent/query/{query_id}/code-artifacts
GET    /api/v1/agent/query/{query_id}/code-archive.zip
```

#### Analytics Query API (SQL + NL + Saved Queries)
```
POST   /v1/analytics/query/sql
POST   /v1/analytics/query/nl
GET    /v1/analytics/queries/saved
POST   /v1/analytics/queries/save
```

#### Tenant Semantic Registry API
```
GET    /v1/analytics/glossary                         # Merged platform + tenant glossary
POST   /v1/analytics/tenant/glossary                  # Propose glossary term or metric
POST   /v1/analytics/tenant/schema/register           # Register custom table schema (four-eyes)
GET    /v1/analytics/tenant/schema/{name}/status      # Schema drift status for a registered table
```

#### Evidence & Reporting API
```
POST   /v1/analytics/evidence/exam-packet
GET    /v1/analytics/evidence/exam-packet/{id}
POST   /v1/analytics/reports/pl
GET    /v1/analytics/reports/pl/{id}
```

### 10.3 Webhook Events

| Event | Trigger |
|---|---|
| `decision.created` | New decision returned |
| `decision.override` | Override submitted/approved |
| `policy.changed` | Policy version promoted |
| `model.deployed` | Model version goes live |
| `alert.triggered` | Threshold breach detected |
| `exam_packet.ready` | Packet generation complete |
| `agent.answer.ready` | AI agent answer with code artifacts delivered |
| `hallucination.detected` | ValidatorAgent reconciliation failure — suppressed output |
| `semantic.schema_drift` | Tenant table schema hash mismatch detected — queries blocked |
| `semantic.term_proposed` | New tenant glossary term or metric awaiting approval |

---

## 11. Security & Governance

### 11.1 Authentication & Authorization
- **RBAC**: Roles enforced via GCP IAM + AWS Cognito + JWT claims
- **AI Agent RBAC**: Role-specific query permissions; `internal_audit` cannot query raw PII; `executive_read_only` receives summary-only AI outputs
- **Service Account Isolation**: AI agent execution uses dedicated read-only DB service account — no write access to production tables
- **MFA enforcement**: Required for all roles except `loan_officer` (configurable)

### 11.2 Data Protection
- **Encryption at rest**: AES-256 (AWS KMS + GCP CMEK per-tenant key rotation)
- **Encryption in transit**: TLS 1.3 preferred; mutual TLS for service-to-service
- **Secret management**: AWS Secrets Manager; no hardcoded credentials (enforced by pre-commit hooks)
- **Network isolation**: VPC per environment; private subnets for data services; WAF on public endpoints

### 11.3 AI Governance Controls

| Control | Implementation |
|---|---|
| LLM version pinning | Gemini model version pinned per deployment; version change requires change management |
| Prompt versioning | All system prompts version-controlled in Git with approver chain |
| Hallucination monitoring | ValidatorAgent logs every reconciliation check; hallucination rate dashboarded and alerted |
| Human-in-the-loop gate | Exam package generation requires human approval before final export |
| Code artifact immutability | AI code artifacts stored append-only in S3/GCS with SHA-256 content hash; tampering detectable |

### 11.4 Immutability & Non-Repudiation
- Decision logs and compliance events: append-only (no UPDATE/DELETE)
- Audit packages carry SHA-256 content hash at generation
- Agent session logs are append-only
- AI code artifacts stored immutably — cannot be retroactively modified after answer delivery

### 11.5 SOC 2 Type II Controls

| Trust Service Criteria | ILOL Control |
|---|---|
| Security (CC6–CC9) | RBAC, MFA, WAF, VPC, annual pen test |
| Availability (A1) | Multi-AZ, DR plan, RTO/RPO commitments |
| Confidentiality (C1) | PII encryption, data classification, access controls |
| Processing Integrity (PI1) | Decision log hash chain, validation checks, AI reconciliation |
| Privacy (P1–P8) | GLBA controls, data minimization, subject rights workflow |

---

## 12. Metrics & Success Criteria

### 12.1 Platform Health SLAs

| Metric | Target |
|---|---|
| Decisioning API p50 latency | < 100ms |
| Decisioning API p95 latency | < 200ms |
| Decisioning API p99 latency | < 500ms |
| Platform availability | > 99.9% (monthly) |
| Audit log write success rate | 100% |
| Exam packet generation success | > 99.5% |
| PII exposure events | 0 |
| AI agent response time (median) | < 30 seconds |

### 12.2 AI Agent Quality Metrics

| Metric | Target |
|---|---|
| Hallucination rate | 0% |
| Query success rate | ≥ 95% |
| HIGH confidence rate | ≥ 70% |
| Code artifact coverage | **100%** (every AI analysis answer includes at least one code artifact) |
| Code reproduction accuracy | **≥ 99%** (independently executed code produces the same result — sampled monthly) |
| Plan approval rate | ≥ 80% without modification |
| User adoption (weekly AI usage, 3mo) | ≥ 70% of target roles |

### 12.3 Customer Success Metrics

| Metric | Baseline (pre-ILOL) | Target (12 months post) |
|---|---|---|
| Time to generate exam packet | 4–8 weeks | < 5 minutes |
| Compliance exam prep hours | 400+ hrs / exam | < 20 hrs / exam |
| Days to identify model degradation | 30–90 days | < 3 days |
| Adverse action notice error rate | 2–5% | < 0.1% |
| Policy change cycle time | 2–4 weeks | < 3 days (including testing) |
| Fair lending report generation | 2–4 weeks (consultant) | On-demand, in-house |
| Time to portfolio insight (AI) | Days (data team) | < 30 seconds |

### 12.4 Business Success Metrics

| Metric | Year 1 Target | Year 2 Target |
|---|---|---|
| Paying customers | 15–25 | 50–75 |
| ARR | $2.5M–$4M | $8M–$12M |
| Net Revenue Retention | > 110% | > 120% |
| Customer NPS | > 50 | > 60 |
| Churn rate | < 5% annually | < 5% annually |

---

## 13. Implementation Roadmap

### 13.1 Phasing Philosophy

Each phase delivers a complete, shippable product. Phase 1 delivers immediate compliance value. Phase 2 adds intelligence and monitoring. Phase 3 delivers the full AI analytics layer and enterprise model governance. Phase 4 enables autonomous decision support.

### Phase 1 — Governance Foundation (Months 1–6)

**Theme:** "Be audit-ready in 30 days"

| Feature | Month |
|---|---|
| Immutable decision log (append-only, hash chain) | M2 |
| Policy versioning v1 (create, version, activate) | M2 |
| Basic decisioning API (< 200ms p95) | M3 |
| Experian bureau integration | M3 |
| RBAC + Auth (6 roles) | M3 |
| SHAP reason code generation (top-4, Reg B) | M4 |
| Exam packet v1 (policy history + decision log, PDF) | M4 |
| Adverse action module (Reg B notice templates) | M4 |
| Compliance rules engine v1 (Reg B + override governance) | M4 |
| Admin dashboard (tenant setup, user management) | M5 |
| MeridianLink LOS integration | M5 |
| Policy rollback (dual approval) | M6 |
| Data lineage v1 (feature provenance per decision) | M6 |
| Audit log search (OpenSearch indexing + query UI) | M6 |
| **AI Agent v1 (non-negotiable)**: single-turn SQL queries + schema-grounded answers + code transparency (exact SQL shown, [Copy] + [Download .zip] actions) | M5–M6 |

**Phase 1 Success Criteria:**
- ≤ 200ms p95 decisioning latency
- Exam packet generated in < 15 minutes
- 3 paying pilot customers live
- Zero data integrity issues in audit log
- 100% AI answers include surfaced SQL code artifact

---

### Phase 2 — Intelligence & Monitoring (Months 7–12)

**Theme:** "See your portfolio in real time, and never be surprised"

| Feature | Month |
|---|---|
| Portfolio dashboard v1 (originations, approval rate, DPD) | M7 |
| Vintage analysis (cohort performance by origination month) | M8 |
| Fairness monitoring (daily AIR calculation + alert) | M8 |
| Equifax + TransUnion (full tri-bureau integration) | M9 |
| Intelligent alerting (configurable thresholds, UI + email + AI explanation) | M9 |
| Policy simulation (impact preview before deployment) | M9 |
| Visual policy diff (side-by-side version comparison) | M10 |
| NLG executive summaries v1 (weekly/monthly CRO digest) | M10 |
| AI Agent v2: multi-agent routing, FairLendingAgent, session memory (Redis) | M10 |
| **Tenant-Scoped Semantic Layer v1**: platform glossary (harvested from data contracts), 9 named platform metrics, `AnalyticsScope` dependency, `POST /v1/analytics/query/sql` endpoint | M10 |
| **Tenant-Scoped Semantic Layer v2**: `tenant_semantic_registry` table, glossary/metric registration endpoints, two-tier resolution, schema drift detection | M11 |
| Exam packet v2 (fair lending + override log + AI audit appendix + **Semantic Registry Appendix**) | M11 |
| Drill-down: portfolio → segment → loan → decision | M11 |
| Webhook event system | M11 |
| GraphQL analytics API | M12 |
| Excel + PDF output generation for AI agent answers | M12 |

**Phase 2 Success Criteria:**
- 15+ paying customers
- Alert-to-AI-investigation workflow in < 5 minutes
- NLG summaries rated accurate by CROs (> 4.0/5.0)
- Zero missed AIR threshold violations
- AI agent code reproduction accuracy ≥ 99%

---

### Phase 3 — Model Lifecycle & Advanced AI (Months 13–18)

**Theme:** "Own your model risk governance"

| Feature | Month |
|---|---|
| Model registry (full versioning, metadata, MLflow integration) | M13 |
| Model performance monitoring (daily AUC/KS/PSI + alerts) | M14 |
| SR 11-7 model card auto-generation | M14 |
| AI Agent v3: ModelRiskAgent, RegulatoryInterpreterAgent (Vertex AI RAG over SR 11-7/ECOA KB) | M14 |
| Champion/challenger framework (traffic splitting with guardrails) | M15 |
| A/B testing framework (policy + model experimentation engine) | M15 |
| Advanced NLG (configurable tone, audience, depth) | M15 |
| Snowflake / BigQuery native push connector | M16 |
| Multi-product policy engine (card, auto, personal loan, BNPL) | M16 |
| Plaid / Finicity integration (cash flow + income enrichment) | M17 |
| White-label / OEM API | M17 |
| Compliance dashboard v2 + regulator portal (read-only, pre-packaged) | M18 |
| SOC 2 Type II certification | M18 |
| PowerPoint output for AI agent answers | M18 |

**Phase 3 Success Criteria:**
- 50+ paying customers
- SOC 2 Type II certified
- Full SR 11-7 model lifecycle managed within platform
- AI agent hallucination rate = 0% sustained over 90 days
- NPS > 55

---

### Phase 4 — Autonomous Decision Support (Q1 2027+)

- Cross-client benchmarking (anonymized peer comparison via AI)
- AI audit assistant (interactive exam prep Q&A with regulators)
- Proactive compliance monitoring (predict regulatory findings before exam)
- Automated remediation recommendations with approval workflow

---

### 13.2 Team Structure

| Role | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Backend Engineers (Python/Go) | 3 | 5 | 6 |
| Frontend Engineers (Next.js) | 1 | 2 | 3 |
| Data Engineer | 1 | 2 | 2 |
| ML / AI Engineer | 1 | 2 | 3 |
| DevOps / Platform Engineer | 1 | 1 | 2 |
| Product Manager | 1 | 1 | 2 |
| Compliance Advisor (part-time) | 1 | 1 | 1 |
| **Total** | **9** | **14** | **19** |

---

## Appendix A — Glossary

| Term | Definition |
|---|---|
| **AIR** | Adverse Impact Ratio — ratio of approval rates between protected and control groups |
| **AUC** | Area Under the ROC Curve — model discrimination metric |
| **BISG** | Bayesian Improved Surname Geocoding — proxy methodology for protected class estimation |
| **KS** | Kolmogorov-Smirnov statistic — separation between good/bad score distributions |
| **PSI** | Population Stability Index — measures distribution shift over time |
| **SHAP** | SHapley Additive exPlanations — model explainability method |
| **RAG** | Retrieval-Augmented Generation — grounds AI answers in retrieved data to prevent hallucination |
| **SR 11-7** | Federal Reserve Supervisory Guidance on Model Risk Management |
| **ECOA** | Equal Credit Opportunity Act |
| **Reg B** | Regulation B — implements ECOA |
| **FCRA** | Fair Credit Reporting Act |
| **UDAAP** | Unfair, Deceptive, or Abusive Acts or Practices |
| **MLA** | Military Lending Act |
| **LOS** | Loan Origination System |
| **DPD** | Days Past Due |
| **MRA** | Matter Requiring Attention (regulatory finding category) |
| **NLG** | Natural Language Generation |
| **QLDB** | Amazon Quantum Ledger Database — immutable, cryptographically verifiable ledger |
| **RBAC** | Role-Based Access Control |
| **RTO / RPO** | Recovery Time Objective / Recovery Point Objective |
| **HMDA** | Home Mortgage Disclosure Act |
| **CRA** | Community Reinvestment Act |
| **Code Artifact** | The exact, immutably stored SQL + Python files used to produce an AI answer — independently executable for validation |
| **Champion/Challenger** | A/B deployment pattern where a new model version operates alongside the current production model |

---

## Appendix B — API Specifications (AI Agent Layer)

### `POST /api/v1/agent/query`
```json
// Request
{
  "query": "What drove the approval rate decline in Q1 2026 among thin-file applicants?",
  "session_id": "sess_abc123",
  "strict_mode": true,
  "output_format": ["json", "pdf"],
  "confidence_minimum": "MEDIUM"
}

// Response
{
  "query_id": "qry_20260415_001",
  "answer": {
    "narrative": "Approval rates for thin-file applicants declined 8.2 percentage points in Q1 2026 vs Q1 2025.",
    "root_causes": [
      {"factor": "Policy cutoff change", "contribution_pct": 60, "evidence_query_id": "sql_001"},
      {"factor": "Score distribution shift (PSI=0.23)", "contribution_pct": 30, "evidence_query_id": "sql_002"},
      {"factor": "Bureau coverage gap", "contribution_pct": 10, "evidence_query_id": "sql_003"}
    ],
    "confidence": "HIGH",
    "data_citations": [
      {
        "claim": "8.2 pp decline",
        "source_table": "audit.decision_log",
        "query_hash": "sha256:abc...",
        "row_count": 4200
      }
    ]
  },
  "code_artifacts": [
    {
      "step": 1,
      "type": "sql",
      "label": "Q1 YoY approval rate by bureau_score_band",
      "code": "SELECT DATE_TRUNC(decision_timestamp, QUARTER) AS qtr, bureau_score_band, COUNTIF(outcome = 'APPROVE') / COUNT(*) AS approval_rate FROM `project.audit.decision_log` WHERE bureau_score_band = 'thin_file' AND decision_timestamp BETWEEN '2025-01-01' AND '2026-03-31' GROUP BY 1, 2",
      "bq_job_id": "bqjob_r75a4c9f2_00018e3b4e7b_1",
      "bytes_processed": 2189440,
      "row_count": 4200,
      "executed_at": "2026-04-15T09:32:11Z",
      "storage_uri": "s3://ilol-code-artifacts/qry_20260415_001/step1.sql",
      "sha256": "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"  # pragma: allowlist secret
    },
    {
      "step": 2,
      "type": "python",
      "label": "YoY delta computation and PSI calculation",
      "code": "import pandas as pd\nq1_2025 = df[df['qtr']=='2025-01-01']['approval_rate'].iloc[0]\nq1_2026 = df[df['qtr']=='2026-01-01']['approval_rate'].iloc[0]\ndelta_pp = (q1_2026 - q1_2025) * 100  # Result: -8.2",
      "storage_uri": "s3://ilol-code-artifacts/qry_20260415_001/step2.py",
      "sha256": "3d7e9f2a1b4c8e5f6d0a2c9b7e4f1d3a8c5b2e9f7d4a1c6b3e8f5d2a9c7b4e"  # pragma: allowlist secret
    }
  ],
  "code_export_url": "s3://ilol-code-artifacts/qry_20260415_001/code_archive.zip",
  "outputs": {
    "pdf_url": "s3://ilol-outputs/qry_20260415_001.pdf",
    "excel_url": "s3://ilol-outputs/qry_20260415_001.xlsx"
  },
  "audit_log_id": "agent_log_20260415_001"
}
```

### `POST /api/v1/agent/audit-package`
```json
{
  "period_start": "2026-01-01",
  "period_end": "2026-03-31",
  "scope": ["governance_artifacts", "model_documentation", "decision_evidence", "fair_lending", "ai_agent_audit_appendix"],
  "exam_type": "CFPB_SUPERVISION",
  "require_approval": true,
  "include_code_archive": true
}
```

---

## Appendix C — Risk & Mitigation Register

### C.1 Risk Summary Table

| # | Risk | Likelihood | Impact | Severity | Sprint Target |
|---|---|---|---|---|---|
| R-01 | LLM hallucination breach in regulatory output | Medium | Critical | **Critical** | Sprint 1 |
| R-02 | Multi-cloud complexity (AWS + GCP) causing operational failure | Medium | High | **High** | Sprint 1 |
| R-03 | Sub-200ms latency SLA breach (bureau degradation) | Medium | High | **High** | Sprint 1 |
| R-04 | Regulatory knowledge base staleness | Medium | High | **High** | Sprint 1–2 |
| R-05 | Tenant data isolation failure | Low | Critical | **High** | Sprint 1 |
| R-06 | SR 11-7 / AI regulatory gap (unfinalized guidance) | Medium | Medium | **Medium** | Sprint 2 |
| R-07 | Vendor concentration — Gemini / OpenAI | Medium | Medium | **Medium** | Sprint 2 |
| R-08 | Immutable log storage cost scaling | High | Medium | **Medium** | Sprint 2 |
| R-09 | Analyst non-adoption of code transparency | Medium | Medium | **Medium** | Sprint 3 |
| R-10 | Model validation backlog / governance breach | Medium | Medium | **Medium** | Sprint 3 |
| R-11 | Bureau API latency exceeds SLA | Medium | High | **High** | Sprint 1 |
| R-12 | LOS integration complexity exceeds timeline | High | Medium | **Medium** | Phase 1 |
| R-13 | Prohibited ECOA variable exposed in AI query | Low | Critical | **High** | Sprint 1 |
| R-14 | Exam packet generation latency > 5 minutes | Low | Medium | **Low** | Sprint 2 |

---

### C.2 Detailed Mitigation Plans

---

#### R-01 — LLM Hallucination Breach
**Severity: Critical** | **Owner: AI Engineering + Model Risk Manager**

| Action | Owner | Timeline |
|---|---|---|
| Implement automated red-team test suite: 200+ adversarial queries executed on every deployment | AI Engineering | Sprint 1 |
| Add `ReconciliationAuditAgent` logging every `ValidatorAgent` pass/fail to a monitoring dashboard — alert on failure rate > 0.1% | AI Engineering | Sprint 1 |
| Introduce human-in-the-loop approval gate for any AI output destined for regulatory submission (compliance mode) — user must click "Verified and Approved" before export | Product + Engineering | Sprint 2 |
| Monthly "hallucination hunt" reviews: sample 50 random AI answers, manually verify SQL output matches narrative | Model Risk Manager | Ongoing |
| Publish public **AI Answer Trust Score** SLA — commit to < 0.01% reconciliation failures; measure and report quarterly | CPO | Q3 2026 |

---

#### R-02 — Multi-Cloud Complexity (AWS + GCP)
**Severity: High** | **Owner: Architecture + DevOps**

| Action | Owner | Timeline |
|---|---|---|
| Define data plane separation contract: AWS = decisioning + audit (latency-critical); GCP = analytics + AI (throughput-critical) — no cross-cloud hot-path dependencies | Architecture | Now |
| Build BigQuery abstraction layer (`analytics_store/`) so analytics store is swappable to Snowflake via config change, not re-engineering | Engineering | Sprint 2 |
| Add cross-cloud circuit breakers: if GCP Vertex AI is unavailable, AI agent degrades gracefully (returns "AI unavailable, here is raw data") without failing the decisioning path | Engineering | Sprint 1 |
| Unified observability: route all AWS + GCP logs to single Datadog workspace; set SLA alerts for cross-cloud latency on any path > 50ms | DevOps | Sprint 1 |
| Quarterly cloud cost review with auto-scaling caps to prevent runaway BigQuery query costs from AI agent | Finance + DevOps | Ongoing |

---

#### R-03 — Sub-200ms Latency SLA Breach
**Severity: High** | **Owner: Engineering**

| Action | Owner | Timeline |
|---|---|---|
| Define bureau degradation policy: if bureau response > 30ms p95, serve cached bureau file (configurable 0–90 days per product); log cache hit in decision audit | Engineering | Sprint 1 |
| Add bureau circuit breaker: if error rate > 2% in a 5-minute window, auto-failover to secondary bureau waterfall without human intervention | Engineering | Sprint 1 |
| Establish latency budget enforcement test in CI/CD — P95 load test must pass < 200ms on every merge to main | QA / DevOps | Sprint 2 |
| Introduce "fast-path" decisioning mode for pre-screened applicants where bureau is already cached — target p95 < 80ms | Engineering | Sprint 3 |
| Publish latency SLA in customer contracts with defined remedies — creates internal accountability | Product + Legal | Q3 2026 |

---

#### R-04 — Regulatory Knowledge Base Staleness
**Severity: High** | **Owner: Compliance + Engineering**

| Action | Owner | Timeline |
|---|---|---|
| Assign Regulatory Content Owner (Compliance Officer role) responsible for quarterly KB review and re-embedding | Compliance | Now |
| Build KB freshness monitor: every regulatory document in vector DB has `effective_date` and `review_due_date`; flag documents > 90 days since last review | Engineering | Sprint 2 |
| Subscribe to OCC, CFPB, Federal Reserve RSS/email feeds; auto-create a Jira ticket when new guidance is published | Compliance + Engineering | Sprint 1 |
| `RegulatoryInterpreterAgent` must surface source document title, version, and publication date alongside every regulatory citation — never cite without provenance | Engineering | Sprint 1 |
| For any regulatory citation with `review_due_date` past, agent must prepend: *"Note: This guidance reference was last reviewed on [date]. Verify currency before regulatory submission."* | Engineering | Sprint 2 |

---

#### R-05 — Tenant Data Isolation Failure
**Severity: High (Critical if triggered)** | **Owner: Security + Engineering**

| Action | Owner | Timeline |
|---|---|---|
| Add automated cross-tenant data isolation test to every deployment pipeline: attempt to query Tenant B data using Tenant A credentials — must always return 0 rows | QA / Security | Sprint 1 |
| Implement tenant context enforcement at the ORM layer — every database query automatically injects `tenant_id` filter via middleware, not developer discretion | Engineering | Sprint 1 |
| Quarterly third-party penetration test scoped specifically to tenant isolation (not just general pen test) | Security | Quarterly |
| Row-level security (RLS) policies reviewed and cryptographically signed on every schema migration — any RLS change requires dual-approval PR | Engineering | Sprint 2 |
| Add tenant-scoped API key rotation (90-day max lifetime); alert on any cross-tenant JWT claim anomaly | Security | Sprint 2 |

---

#### R-06 — SR 11-7 / AI Regulatory Gap
**Severity: Medium** | **Owner: Compliance + Model Risk**

| Action | Owner | Timeline |
|---|---|---|
| Map every AI agent feature to the closest existing SR 11-7 requirement today — document gaps explicitly in a "Regulatory Readiness Matrix" | Compliance + Model Risk | Sprint 2 |
| Design all AI agent audit artifacts (query log, code artifacts, confidence scores) to be over-inclusive — capture more than required now so retrofitting is additive, not structural | Engineering | Sprint 1 |
| Engage external model risk advisory firm to review AI agent governance against pending OCC/Fed AI guidance drafts — semi-annually | Compliance | Q3 2026 |
| Build "regulatory update mode": when new AI governance rules are finalized, the compliance rules engine can be updated via config (not code redeployment) | Engineering | Sprint 3 |

---

#### R-07 — Vendor Concentration (Gemini / OpenAI)
**Severity: Medium** | **Owner: Engineering + Legal**

| Action | Owner | Timeline |
|---|---|---|
| Implement LLM abstraction layer (`llm_client/`) with a common interface — swap between Gemini, GPT-4o, and Claude via config, not code changes | Engineering | Sprint 2 |
| Run GPT-4o fallback in active-active (not passive) for compliance queries — if either model fails, the other handles the request with no degradation | Engineering | Sprint 2 |
| Evaluate Anthropic Claude 3.5 Sonnet as a third provider for critical compliance paths — reduces single-vendor leverage | Engineering | Q3 2026 |
| Negotiate contractual SLAs with Google Vertex AI and OpenAI for uptime and pricing stability; include escape clause if pricing increases > 25% | Legal + Finance | Q3 2026 |

---

#### R-08 — Immutable Log Storage Cost Scaling
**Severity: Medium** | **Owner: DevOps + Finance**

| Action | Owner | Timeline |
|---|---|---|
| Implement tiered storage lifecycle strictly: 0–90 days hot (RDS/QLDB), 91 days–2 years warm (S3 Standard-IA), 2–10 years cold (S3 Glacier Deep Archive) | Engineering | Sprint 2 |
| For AI code artifacts: compress + deduplicate SQL/Python files before storage (many queries will be near-identical); store hash pointer, not duplicate file | Engineering | Sprint 2 |
| Add storage cost dashboard with per-tenant, per-module breakdowns and a 90-day cost projection — reviewed monthly by Finance | DevOps | Sprint 3 |
| Define code artifact pruning policy exception process: low-value AI queries (e.g., simple lookups) retain only hash + result, not full code artifacts, after 2 years | Compliance + Engineering | Q4 2026 |

---

#### R-09 — Analyst Non-Adoption of Code Transparency
**Severity: Medium** | **Owner: Product**

| Action | Owner | Timeline |
|---|---|---|
| Default code panel to collapsed in the UI — power users expand; casual users are not overwhelmed | Product | Sprint 1 |
| Add "Validate This Answer" one-click flow: pre-populates SQL in a read-only query console that users can run themselves — reduces trust friction | Engineering | Sprint 2 |
| Build 3 interactive onboarding walkthroughs (Risk Analyst, Compliance Officer, CRO persona) specifically demonstrating code transparency and its regulatory value | Product | Q3 2026 |
| Track code expand rate and code copy rate as product metrics — low adoption triggers UX iteration, not removal of the feature | Product Analytics | Ongoing |

---

#### R-10 — Model Validation Backlog / Governance Breach
**Severity: Medium** | **Owner: Model Risk Manager + Engineering**

| Action | Owner | Timeline |
|---|---|---|
| Change validation overdue alert from 375 days (non-compliant) to 60-day advance warning at 315 days — giving teams time to schedule validation before breach | Engineering | Sprint 1 |
| Add model governance calendar view: shows every model's next validation due date, assigned validator, and days remaining — visible to CRO and Model Risk Manager | Engineering | Sprint 2 |
| For models that breach 375 days: automatically demote to "challenger" status and require CRO override to keep in production — enforces governance, not just monitors it | Engineering | Sprint 3 |
| Provide model validation workflow module: standardized templates, automated PSI/AUC pre-work, and digital approval signatures reduce validation cycle from weeks to days | Product | Q4 2026 |

---

#### R-11 — Bureau API Latency / Availability
**Severity: High** | **Owner: Engineering** *(see also R-03)*

| Action | Owner | Timeline |
|---|---|---|
| Multi-bureau caching with configurable TTL (0–90 days per product type) | Engineering | Sprint 1 |
| Automated bureau waterfall: primary → secondary → tertiary on freeze / error / timeout | Engineering | Sprint 1 |
| Bureau error rate alert: > 2% in rolling 5-minute window triggers on-call alert | Engineering | Sprint 1 |
| All bureau pulls logged with permissible purpose metadata (FCRA compliance) — no silent failovers | Engineering | Sprint 1 |

---

#### R-12 — LOS Integration Complexity
**Severity: Medium** | **Owner: Engineering + Implementations**

| Action | Owner | Timeline |
|---|---|---|
| Prioritize MeridianLink as first LOS integration — covers the largest segment of credit union target market | Engineering | Phase 1 |
| SFTP-based flat-file fallback available for all LOS integrations in Phase 1 — no customer is blocked pending native API | Engineering | Phase 1 |
| Publish LOS integration guide and sandbox environment for customer technical teams | Implementations | Q3 2026 |

---

#### R-13 — Prohibited ECOA Variable Exposure in AI Query
**Severity: High (Critical if triggered)** | **Owner: Engineering + Compliance**

| Action | Owner | Timeline |
|---|---|---|
| `ComplianceGateAgent` blocks prohibited columns at schema registration level — blocklist includes race, sex, age, national origin, marital status, and known proxies | Engineering | Sprint 1 |
| Query dry-run validation includes prohibited column scan — any query touching blocked columns is aborted before execution | Engineering | Sprint 1 |
| Quarterly review of blocklist with Compliance Officer — update for newly identified proxies (zip code, surname vectors) | Compliance | Quarterly |

---

#### R-14 — Exam Packet Generation Latency > 5 Minutes
**Severity: Low** | **Owner: Engineering**

| Action | Owner | Timeline |
|---|---|---|
| Pre-compute common report components (fair lending summary, model validation snapshot) on a nightly schedule — packet assembly pulls from cache | Engineering | Sprint 2 |
| Async generation with progress indicator + email/in-app delivery when complete — user is not blocked waiting | Engineering | Sprint 2 |
| SLA monitoring: alert engineering if any packet generation exceeds 5-minute threshold | Engineering | Sprint 3 |

---

### C.3 Prioritized Execution Roadmap

```
Sprint 1 (Weeks 1–4):
  R-01 red-team test suite + ReconciliationAuditAgent
  R-02 cross-cloud circuit breakers + unified observability
  R-03 bureau circuit breaker + degradation policy
  R-04 regulatory KB provenance enforcement + RSS monitoring
  R-05 cross-tenant isolation tests + ORM-layer tenant enforcement
  R-11 bureau caching + waterfall
  R-13 ComplianceGateAgent blocklist hardening

Sprint 2 (Weeks 5–8):
  R-01 human-in-the-loop regulatory submission gate
  R-02 BigQuery abstraction layer
  R-03 CI/CD latency enforcement test
  R-04 KB freshness monitor
  R-05 RLS signing on schema migrations + API key rotation
  R-06 Regulatory Readiness Matrix
  R-07 LLM abstraction layer + active-active fallback
  R-08 tiered storage lifecycle + artifact deduplication
  R-09 "Validate This Answer" flow
  R-14 async exam packet generation

Sprint 3 (Weeks 9–12):
  R-03 fast-path decisioning mode
  R-06 regulatory update mode (config-driven compliance rules)
  R-08 storage cost dashboard
  R-09 onboarding walkthroughs
  R-10 model governance calendar + auto-demotion at 375 days
  R-12 LOS SFTP fallback hardening

Q3–Q4 2026:
  R-01 public AI Answer Trust Score SLA
  R-06 external model risk advisory engagement
  R-07 third-provider LLM evaluation + vendor SLA negotiation
  R-08 code artifact pruning policy
  R-10 model validation workflow module
  R-12 MeridianLink native integration GA
```

---

## Appendix D — Go-Live Integration Checklist

For each new customer deployment, the following must be completed before Go-Live:

- [ ] LOS integration configured and tested (round-trip decision test with > 100 applications)
- [ ] Core banking feed established (nightly performance data flowing)
- [ ] Bureau integration live (test pulls via Experian sandbox, then production)
- [ ] RBAC configured (all user roles assigned, dual-approver designees named)
- [ ] Policy uploaded and versioned (initial production policy in ILOL registry)
- [ ] Exam packet test run completed (full packet generated for sample date range)
- [ ] Alert thresholds configured (AIR, DPD, approval rate — reviewed with risk team)
- [ ] Adverse action notice templates reviewed and approved by compliance officer
- [ ] Data retention policy confirmed (7-year minimum)
- [ ] AI agent schema registration complete (all decision and analytics tables registered)
- [ ] AI agent test queries validated (5 representative queries executed; code artifacts verified independently)
- [ ] ComplianceGateAgent PII/ECOA column blocklist configured and tested
- [ ] AI agent RBAC roles confirmed and tested per role
- [ ] Disaster recovery test completed

---

*Document Control: This unified PRD supersedes PRD_INTEGRATED_LENDING_OPERATING_LAYER v1.0.0 and Governance_native_LOS_PRD v2.1. Changes require product manager approval and stakeholder review before merging. All prior versions are retained.*

*Classification: Internal — Confidential. Not for external distribution without redaction review.*

*Next Review: July 15, 2026*
