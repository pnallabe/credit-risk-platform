# Platform Requirements Document (PRD)
# Integrated Lending Operating Layer (ILOL)

**Version:** 1.0.0
**Status:** Draft — Pending Stakeholder Review
**Date:** April 7, 2026
**Owner:** Product Management
**Classification:** Internal — Confidential

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision & Strategy](#2-product-vision--strategy)
3. [User Personas](#3-user-personas)
4. [Detailed Feature Requirements](#4-detailed-feature-requirements)
5. [UX / Workflow Design](#5-ux--workflow-design)
6. [System Architecture](#6-system-architecture)
7. [Data Architecture](#7-data-architecture)
8. [Compliance & Governance Framework](#8-compliance--governance-framework)
9. [API Design](#9-api-design)
10. [Metrics & Success Criteria](#10-metrics--success-criteria)
11. [Implementation Roadmap](#11-implementation-roadmap)

---

## 1. Executive Summary

### 1.1 Product Overview

The **Integrated Lending Operating Layer (ILOL)** is a production-grade, governance-native credit risk platform purpose-built for mid-market lenders — credit unions, community banks, and fintech lenders managing loan portfolios between $100M and $10B. It serves as the single operating layer across originations, underwriting, risk management, compliance, and portfolio analytics.

ILOL is not a point solution. It is the connective tissue between every system and decision a lender makes — from the moment an application arrives to the moment a regulatory examiner requests documentation.

### 1.2 Problem Statement

Mid-market lenders face a structural crisis across three dimensions:

| Dimension | Current Pain | Cost |
|---|---|---|
| **Decisioning** | Disconnected policy engines, manual score overrides, no audit trail | High error rate, fair lending exposure |
| **Monitoring** | Lagged reporting (30–90 days), no real-time portfolio visibility | Slow response to credit deterioration |
| **Compliance** | Manual exam prep, inconsistent documentation, long audit cycles | $500K–$5M in exam response costs annually |

Existing solutions address one or two of these pain points in isolation. ILOL addresses all three in a unified, integrated platform.

### 1.3 Solution Summary

ILOL delivers:

- **A Decisioning Engine** that orchestrates credit policies and ML models with full traceability
- **A Governance-Native Infrastructure** that auto-generates regulator-ready audit evidence
- **A Portfolio Monitoring Layer** with real-time dashboards down to individual loan decisions
- **A Compliance Automation Suite** that converts regulatory scrutiny from a crisis into a routine
- **A Model Lifecycle Management System** aligned with SR 11-7

### 1.4 Business Case

| Metric | Target |
|---|---|
| Initial target market | Credit unions ($100M–$2B AUM) and fintech lenders |
| Addressable market (TAM) | ~4,700 institutions in the US meeting profile criteria |
| ARR per customer | $150K–$600K depending on tier |
| Target Year 1 customers | 15–25 |
| Target Year 2 ARR | $5M–$8M |
| Differentiation | Only platform with governance-native architecture + exam automation |

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

> *"Every credit decision made on ILOL is explainable, auditable, and defensible — today, tomorrow, and on the day a regulator walks in."*

### 2.2 Strategic Positioning

ILOL occupies a distinct position in the market:

```
                    HIGH GOVERNANCE
                          │
        [ILOL]            │
                          │
                          │
LOW AUTOMATION ───────────┼─────────────── HIGH AUTOMATION
                          │
                          │             [ML-Only Vendors]
                          │
                    LOW GOVERNANCE
```

Competitors either optimize for speed (without governance) or compliance (without intelligence). ILOL is the only platform that treats governance as a **first-class engineering primitive** — not an afterthought.

### 2.3 Strategic Pillars

#### Pillar 1: Governance-First Architecture
Every component in ILOL is built with auditability as a default, not an add-on. Decision logs, policy versions, and model outputs are immutable by design.

#### Pillar 2: Regulatory Immunity
One-click exam packet generation eliminates the multi-month manual process of preparing for OCC, CFPB, or Federal Reserve examinations. Customers using ILOL should never be surprised by an examiner.

#### Pillar 3: Unified Intelligence Layer
Risk analysts, data scientists, and compliance officers share the same data layer, eliminating reconciliation overhead and providing a single source of truth.

#### Pillar 4: Extensible by Design
ILOL is modular. Customers can adopt individual modules (e.g., decisioning only, or compliance only) and expand. The API-first design enables integration into any existing tech stack.

### 2.4 Product Principles

1. **Explainability over opacity** — every output must have a traceable reason
2. **Immutability over editability** — logs are append-only; no soft deletes on compliance-critical data
3. **Modularity over monolith** — each module deploys independently
4. **Latency as a feature** — real-time decisioning is not optional; sub-200ms for synchronous decisions
5. **Regulatory alignment as product design** — OCC/CFPB guidance shapes UX, not just backend behavior

### 2.5 Competitive Landscape

| Competitor | Strength | Gap vs ILOL |
|---|---|---|
| Zest AI | ML model quality | No governance layer, no exam automation |
| Provenir | LOS integration depth | No model risk management, no fairness monitoring |
| Experian Ascend | Data access | Platform lock-in, no policy versioning |
| Sageworks/Abrigo | Community bank brand | Legacy architecture, no real-time decisioning |
| Moody's Analytics (RiskCalc) | Credit analytics depth | No decisioning engine, no compliance automation |
| In-house builds | Customization | High cost, no regulatory templates, talent risk |

---

## 3. User Personas

### 3.1 Persona 1: Risk Analyst (Maya)

**Title:** Senior Credit Risk Analyst
**Organization:** Credit Union, $800M AUM
**Team size:** 3–5 analysts

**Goals:**
- Monitor approval rates, delinquency trends, and policy performance daily
- Identify emerging portfolio stress early
- Run policy simulations before changes go live
- Defend policy decisions to internal audit with documentation ready

**Frustrations:**
- Pulling data from 4+ systems into Excel every morning
- No way to know what changed in scoring between months
- Model reason codes are unexplainable to loan officers
- Fair lending reports require 2 weeks of manual work

**ILOL Value Delivered:**
- Single dashboard with live portfolio metrics
- Policy change history with visual diff
- Reason code explainability in plain English
- Automated disparate impact analysis on demand

**Key Workflows:** Portfolio monitoring, policy simulation, fairness reporting

---

### 3.2 Persona 2: Chief Risk Officer (David)

**Title:** Chief Risk Officer
**Organization:** Fintech Lender, $2B+ AUM
**Team size:** Executive, oversees 15–30 FTEs

**Goals:**
- Maintain regulatory posture across OCC, CFPB, and Fair Lending
- Understand portfolio health at the aggregate and segment level
- Receive early warning for risk deterioration
- Brief board quarterly with reliable, consistent data

**Frustrations:**
- Board packages require 2–3 days of manual assembly per quarter
- Regulatory examinations feel like crises, not routine reviews
- No single view of model performance across vintages
- Can't simulate the impact of a policy change before it goes live

**ILOL Value Delivered:**
- Auto-generated CRO executive summaries (NLG-powered)
- Real-time alert system with configurable thresholds
- Exam packet auto-generation: policy history + model docs + fair lending reports
- Policy rollback with impact preview

**Key Workflows:** Executive reporting, alert management, regulatory preparation

---

### 3.3 Persona 3: Compliance Officer (Sandra)

**Title:** VP of Compliance
**Organization:** Community Bank, $1.5B AUM
**Reports to:** General Counsel / CEO

**Goals:**
- Ensure ECOA / Reg B compliance for every adverse action
- Maintain a defensible audit trail for all underwriting decisions
- Prepare for OCC examinations with minimal disruption
- Monitor for disparate impact across protected classes continuously

**Frustrations:**
- Adverse action notices are inconsistent across channels
- No centralized audit trail — decisions are spread across LOS, core banking, and spreadsheets
- Fair lending analysis requires external consultant ($30K–$100K per engagement)
- Policy documentation is out of date within 60 days of changes

**ILOL Value Delivered:**
- Immutable decision log with complete input-output traceability
- Automated disparate impact monitoring with threshold alerts
- Regulator-ready adverse action notice templates aligned to Reg B
- One-click exam packet with OCC and CFPB pre-built templates

**Key Workflows:** Adverse action management, fair lending monitoring, exam preparation

---

### 3.4 Persona 4: Data Scientist / Model Developer (Priya)

**Title:** Lead Data Scientist
**Organization:** Fintech Lender, internal model team
**Team:** 2–6 data scientists

**Goals:**
- Deploy, version, and monitor ML models with minimal friction
- Ensure model behavior is stable post-deployment
- Satisfy model validation requirements from model risk management
- Respond to model risk governance inquiries with structured documentation

**Frustrations:**
- No standardized model registry — models live in S3 buckets with no metadata
- Re-training cycles take 2–3 weeks due to manual data pipeline processes
- No alerting when model PSI or AUC degrades post-deployment
- Model documentation is written manually after the fact

**ILOL Value Delivered:**
- Integrated model registry with version control, lineage, and metadata
- Auto-generated model cards aligned to SR 11-7 requirements
- Real-time PSI / AUC / KS monitoring with configurable alert thresholds
- A/B testing framework for policy and model experimentation

**Key Workflows:** Model deployment, model monitoring, A/B testing, model documentation

---

## 4. Detailed Feature Requirements

### 4.1 Module 1: Governance-Native Risk Infrastructure (GNRI)

This is the foundational module. All other modules build on top of GNRI primitives.

#### 4.1.1 Immutable Decision Log

**Description:** Every underwriting decision — approved, declined, referred, or withdrawn — is logged as an immutable event with full context.

**Functional Requirements:**

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

**Non-Functional Requirements:**
- Write latency: < 50ms (async write, not in critical path)
- Storage: tiered — hot (90 days), warm (2 years), cold (7 years)
- Audit log tamper detection: cryptographic hash chain on append-only log

---

#### 4.1.2 Policy Versioning System

**Description:** Complete version control for credit policies, scorecards, and decision trees with visual diff, rollback, and impact preview.

**Functional Requirements:**

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
| PV-010 | Active version clearly displayed on all decision outputs | P0 |

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
  "policy_definition": { ... },
  "signature": "sha256_hash",
  "parent_version": "2.4.0"
}
```

---

#### 4.1.3 Model Explainability Layer

**Description:** Generates human-readable explanations for every model-driven decision, aligned with Reg B adverse action notice requirements and SR 11-7 model transparency standards.

**Functional Requirements:**

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
| EXP-010 | Batch explainability for population-level analysis | P2 |

---

#### 4.1.4 Fairness Monitoring System

**Description:** Continuous monitoring of lending decisions for disparate impact and disparate treatment across ECOA-protected classes.

**Functional Requirements:**

| ID | Requirement | Priority |
|---|---|---|
| FM-001 | Monitor approval rates by protected class (race, sex, age, national origin, marital status) | P0 |
| FM-002 | Calculate adverse impact ratio (AIR) for each protected class vs. control group | P0 |
| FM-003 | Threshold alert: trigger when AIR falls below 0.80 (4/5ths rule) | P0 |
| FM-004 | Regression-based disparate impact analysis controlling for creditworthiness proxies | P1 |
| FM-005 | Geographic fair lending analysis (HMDA-style heat maps) | P1 |
| FM-006 | Configurable comparison groups (peer institution benchmarks) | P2 |
| FM-007 | Trend monitoring: AIR changes over rolling 30/60/90-day windows | P1 |
| FM-008 | Auto-generate disparate impact report in CFPB-ready format | P0 |
| FM-009 | Flag proxy variable risks (zip code, last name proxies) | P1 |
| FM-010 | Log all fairness calculations with methodology metadata for audit defense | P0 |

**Fair Lending Metrics Computed:**
- Adverse Impact Ratio (AIR) — by product, channel, segment, and overall
- Marginal Effect Analysis — logistic regression controlling for legitimate risk factors
- Concentration Analysis — lending geography vs. demographic composition
- Comparative File Review — statistical matching of declined applicants to approved applicants

---

#### 4.1.5 Data Lineage Tracking

**Description:** End-to-end tracking of every data element from source ingestion to decision output.

**Functional Requirements:**

| ID | Requirement | Priority |
|---|---|---|
| DL-001 | Track every feature value from source system to decision with provenance metadata | P0 |
| DL-002 | Record source system, ingestion timestamp, transformation applied, and version | P0 |
| DL-003 | Visualize lineage DAG (directed acyclic graph) for any decision | P1 |
| DL-004 | Alert on source data staleness or missing data elements | P1 |
| DL-005 | Support retroactive lineage querying (what data was used on date X for application Y?) | P0 |
| DL-006 | Export lineage as model documentation evidence for SR 11-7 | P1 |

---

#### 4.1.6 Role-Based Access Control (RBAC)

| Role | Permissions |
|---|---|
| **Platform Admin** | Full access: configure, deploy, manage users |
| **CRO / Executive** | Read-all: all dashboards, reports, alerts; no edit |
| **Risk Analyst** | Read/write: policy simulation, monitoring dashboards; no production deploy |
| **Compliance Officer** | Read-all: audit logs, fair lending, export; no model edit |
| **Data Scientist** | Read/write: model registry, feature store; no policy deploy |
| **Loan Officer** | Read-limited: own decisions only; reason codes only |
| **Auditor (External)** | Read-only: scoped to defined review period; watermarked exports |

---

### 4.2 Module 2: Decisioning Engine

#### 4.2.1 Policy Orchestration

**Functional Requirements:**

| ID | Requirement | Priority |
|---|---|---|
| DE-001 | Support rule-based policy (if/then/else decision trees) | P0 |
| DE-002 | Support scorecard-based decisioning (logistic regression scorecards) | P0 |
| DE-003 | Support ML model scoring (gradient boosting, neural nets via REST) | P0 |
| DE-004 | Support waterfall policy logic (pre-screen → score → policy overlay → final decision) | P0 |
| DE-005 | Support exception and override workflow with mandatory justification capture | P0 |
| DE-006 | Override logging: who, when, why, what changed | P0 |
| DE-007 | Configurable decision matrix: approve / decline / refer / conditional | P0 |
| DE-008 | Real-time decisioning API: 95th percentile latency < 200ms end-to-end | P0 |
| DE-009 | Batch decisioning: process 100K+ applications per hour | P1 |
| DE-010 | Shadow mode: run new policy/model alongside production without affecting decisions | P1 |

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

#### 4.2.3 A/B Testing Framework

**Functional Requirements:**

| ID | Requirement | Priority |
|---|---|---|
| AB-001 | Split traffic by configurable percentage across policy/model variants | P1 |
| AB-002 | Statistical significance calculator built into experiment results view | P1 |
| AB-003 | Guard rails: automatically halt experiment if approval rate or AIR diverges beyond threshold | P1 |
| AB-004 | Experiment results exportable as model validation evidence | P2 |
| AB-005 | Support multiple concurrent experiments with conflict detection | P2 |

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

**Tier 2 — Segment-Level Drill Down:**
- Vintage analysis: origination cohort performance by month, score band, geography
- Segment P&L contribution estimate
- Behavioral score migration (score changes post-booking)
- Policy rule hit rates (what % of applicants hit each decline rule)

**Tier 3 — Loan-Level Drill Down:**
- Individual application decision replay (full audit trail)
- Current loan status, payment history
- Reason code display at origination

#### 4.3.2 Alerting on Portfolio Metrics

| Metric | Alert Trigger | Default Threshold |
|---|---|---|
| 30+ DPD Rate | Exceeds rolling 90-day high | +50 bps |
| Approval Rate | Drops materially in rolling 7-day window | -500 bps |
| Charge-off Rate | Exceeds budget trajectory | +25 bps |
| Bureau Pull Error Rate | Service degradation | > 2% |
| Score Distribution Shift | PSI > 0.10 | 0.10 |
| AIR (Fair Lending) | Falls below 4/5ths rule | < 0.80 |

---

### 4.4 Module 4: Compliance & Audit Layer

#### 4.4.1 Automated Exam Packet Generation

**Description:** On-demand or scheduled generation of complete, regulator-ready exam packets.

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

**Format Options:** PDF (regulator-facing), Excel (analyst working papers), ZIP archive (all files)

**Generation Time SLA:** < 5 minutes for full exam packet covering any configurable date range

#### 4.4.2 Adverse Action Notice Management

**Functional Requirements:**
- Auto-generate Reg B-compliant adverse action notice for every decline
- Support all required forms: CFPB Model Form C-1 through C-5
- Delivery channel tracking: mail, email, in-app — with timestamp proof
- 30-day notice delivery deadline monitoring with alert if approaching
- Multi-lender template management (for servicers handling multiple brands)

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

#### 4.5.2 Model Performance Monitoring

**Metrics Tracked (Production Models, Daily Refresh):**

| Metric | Description | Alert Threshold |
|---|---|---|
| AUC-ROC | Discrimination ability | Drop > 0.02 vs. validation |
| KS Statistic | Separation between good/bad | Drop > 5 pp |
| PSI | Population stability (feature/score drift) | PSI > 0.10 minor; > 0.25 major |
| Gini Coefficient | Predictive power | Drop > 3 pp |
| Calibration Error | Score → probability accuracy | Brier score shift > 0.01 |
| Approval Rate by Score Band | Score band decision consistency | ±10% vs. 90-day baseline |

#### 4.5.3 Model Card Auto-Generation (SR 11-7 Aligned)

Auto-generated model card includes:
- Model overview and intended use
- Training data description and date range
- Out-of-time validation results (AUC, KS, Gini, PSI)
- Known limitations and edge cases
- Monitoring plan and recertification schedule
- Developer and validator signatures (digital approval workflow)
- Approval status and governance committee sign-off

---

## 5. UX / Workflow Design

### 5.1 Design Philosophy

ILOL's UI is a **Credit Command Center** — designed for power users who need to move between data, decisions, and documentation without context switching. The UX is:

- **Information-dense but not cluttered** — financial professionals want data, not marketing
- **Action-oriented** — every view has a clear call-to-action (simulate, export, alert, investigate)
- **Progressive disclosure** — summary → segment → loan → decision in consistent drill-down pattern
- **Accessibility-first** — WCAG 2.1 AA compliance minimum

### 5.2 Primary Workflows

#### Workflow 1: Decisioning Command Center

```
┌─────────────────────────────────────────────────────────────────┐
│  ILOL  │ Portfolio  │ Decisioning  │ Compliance  │ Models  │ ⚙️ │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  REAL-TIME DECISIONING VIEW                                      │
│                                                                  │
│  Today: 1,247 applications │ 72% Approved │ 21% Declined         │
│                                                                  │
│  ┌──────────────────────┐  ┌──────────────────────────────────┐ │
│  │ APPLICATION FEED     │  │ DECISION DETAIL                  │ │
│  │ APP-20260407-8821    │  │ APP-20260407-8821                │ │
│  │ ● APPROVED  $12,500  │  │ Score: 742 │ Policy: v2.4.1      │ │
│  │ APP-20260407-8820    │  │ Decision: APPROVED               │ │
│  │ ○ DECLINED           │  │                                  │ │
│  │ APP-20260407-8819    │  │ TOP FACTORS (SHAP)               │ │
│  │ ● APPROVED  $8,000   │  │ + Payment history   +0.18        │ │
│  │ APP-20260407-8818    │  │ + Utilization       +0.12        │ │
│  │ ○ REFERRED           │  │ - DTI ratio         -0.08        │ │
│  └──────────────────────┘  │ - Account age       -0.04        │ │
│                             │                                  │ │
│                             │ POLICY RULES EVALUATED           │ │
│                             │ ✓ Min score 620     PASS         │ │
│                             │ ✓ Max DTI 45%       PASS         │ │
│                             │ ✓ BK last 7 yrs     PASS         │ │
│                             │                                  │ │
│                             │ [Override]  [Export]  [History]  │ │
│                             └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
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
┌─────────────────────────────────────────────────────────────────┐
│  COMPLIANCE  │  Exam Packets  │  Reports  │  Audit Logs          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  EXAM PACKET GENERATOR                                           │
│                                                                  │
│  Date Range: [01/01/2026] → [03/31/2026]   Product: [All ▼]     │
│                                                                  │
│  ─────────────────────────────────────────────                  │
│  INCLUDE IN PACKET:                                              │
│  ☑ Policy Version History (v2.2.0 – v2.4.1, 3 versions)        │
│  ☑ Decision Log Summary (47,821 decisions)                      │
│  ☑ Override Log (142 overrides, 98% approved)                   │
│  ☑ Fair Lending Analysis (AIR: 0.87 Race/Ethnicity)             │
│  ☑ Adverse Action Summary (11,203 declines, 100% AA issued)     │
│  ☑ Model Validation Summary (AUC: 0.742, last validated 2/2026) │
│  ☑ Data Lineage Evidence                                         │
│  ─────────────────────────────────────────────                  │
│                                                                  │
│  Format: ● PDF  ○ Excel  ○ Both                                  │
│  Template: [OCC Examination ▼]                                   │
│                                                                  │
│  Estimated generation time: ~2.3 minutes                         │
│                                                                  │
│  [Generate Packet]          Last generated: 2026-03-01 by Sandra │
└─────────────────────────────────────────────────────────────────┘
```

---

#### Workflow 3: Portfolio Monitoring Command Center

```
┌─────────────────────────────────────────────────────────────────┐
│  PORTFOLIO MONITORING                                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ● 3 Active Alerts   ▲ 30+ DPD at 4.2% (+67bps MoM)            │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ ORIGS    │ │ APPROVAL │ │ 30+ DPD  │ │ NET C/O  │          │
│  │ $12.4M   │ │ RATE     │ │ 4.2%     │ │ 1.8%     │          │
│  │ MTD      │ │ 71.3%    │ │ ▲ +67bps │ │ ▼ -12bps │          │
│  │ ▲ +8%    │ │ ▼ -220bp │ │          │ │          │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│                                                                  │
│  VINTAGE ANALYSIS                    SEGMENT PERFORMANCE         │
│  ┌─────────────────────────────┐    ┌─────────────────────────┐ │
│  │ [chart: 12-month cohort     │    │ Score Band  Vol   DPD30 │ │
│  │  performance by vintage]    │    │ 780+        22%   0.8%  │ │
│  │                             │    │ 720-779     31%   1.9%  │ │
│  │                             │    │ 660-719     28%   4.1%  │ │
│  └─────────────────────────────┘    │ 620-659     19%   8.7%  │ │
│                                     └─────────────────────────┘ │
│  [Drill down: Segment → Loan → Decision]                         │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 Intelligent Alerting UI

- Alert inbox with severity (Critical / Warning / Informational)
- Alert detail: metric name, current value, threshold, trend chart, recommended action
- One-click: acknowledge, investigate, escalate, or suppress
- Alert history with resolution log

### 5.4 Executive Summary View (NLG-Powered)

Auto-generated weekly/monthly summary for CRO / Board use. Example output:

> *"For the quarter ending March 31, 2026, the portfolio originated $37.2M across 3,821 accounts, with an average credit score of 714. The 30+ DPD rate is 4.2%, up 67 basis points from the prior month, driven primarily by the 620-659 score band (8.7% DPD). The approval rate declined 220 basis points following the January policy tightening. Fair lending indicators remain within acceptable bounds: Adverse Impact Ratio by race/ethnicity is 0.87, above the 0.80 regulatory threshold. No regulatory examinations are pending. Next model recertification is due June 2026."*

---

## 6. System Architecture

### 6.1 Architecture Overview

ILOL follows a **modular microservices architecture** with a shared event bus, common data primitives, and API-first design. Each module is independently deployable but tightly integrated through well-defined contracts.

```
                        ┌─────────────────────────────────┐
                        │         ILOL API GATEWAY         │
                        │   (Kong / AWS API Gateway)       │
                        └───────────────┬─────────────────┘
                                        │
          ┌─────────────────────────────┼──────────────────────────────┐
          │                             │                              │
          ▼                             ▼                              ▼
┌──────────────────┐        ┌───────────────────┐        ┌─────────────────────┐
│  DECISIONING      │        │  GOVERNANCE /     │        │  PORTFOLIO          │
│  ENGINE SERVICE   │        │  AUDIT SERVICE    │        │  ANALYTICS SERVICE  │
│                   │        │                   │        │                     │
│ - Policy eval     │        │ - Audit log store │        │ - Metrics engine    │
│ - Model scoring   │        │ - Policy versions │        │ - Vintage analysis  │
│ - Rule engine     │        │ - Lineage tracker │        │ - Cohort tracker    │
│ - Explainability  │        │ - Exam packet gen │        │ - KPI aggregation   │
└────────┬─────────┘        └────────┬──────────┘        └──────────┬──────────┘
         │                           │                               │
         └───────────────────────────┼───────────────────────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │     EVENT BUS (Kafka)    │
                        │  decision.created        │
                        │  policy.changed          │
                        │  model.deployed          │
                        │  alert.triggered         │
                        └────────────┬─────────────┘
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
          ▼                          ▼                          ▼
┌─────────────────┐       ┌──────────────────┐      ┌──────────────────────┐
│  COMPLIANCE     │       │  MODEL LIFECYCLE  │      │  NOTIFICATION        │
│  SERVICE        │       │  SERVICE          │      │  SERVICE             │
│                 │       │                   │      │                      │
│ - Fair lending  │       │ - Model registry  │      │ - Alert routing      │
│ - AA notices    │       │ - Performance mon │      │ - Email/webhook      │
│ - Exam reports  │       │ - A/B framework   │      │ - Digest generation  │
└─────────────────┘       └───────────────────┘      └──────────────────────┘
```

### 6.2 Technology Stack

| Layer | Technology | Rationale |
|---|---|---|
| **API Gateway** | AWS API Gateway + Kong | Rate limiting, auth, routing |
| **Service runtime** | Python (FastAPI) + Go (high-throughput services) | FastAPI for data-heavy; Go for latency-critical decisioning |
| **Event bus** | Apache Kafka (MSK on AWS) | High-throughput, durable, replay support |
| **Decision store** | PostgreSQL (RDS) + S3 (cold archive) | ACID compliance for hot layer; cost-efficient cold archive |
| **Feature store** | Feast (self-hosted) or Tecton | Consistent feature serving for training and inference |
| **Audit log store** | Amazon QLDB or custom append-only PostgreSQL | Cryptographically verifiable immutability |
| **Analytics store** | Snowflake or BigQuery | Portfolio analytics, SQL-first exploration |
| **Model serving** | BentoML or SageMaker endpoints | Versioned model serving with rollback |
| **Cache** | Redis (ElastiCache) | Bureau response caching, session state |
| **Search** | OpenSearch | Audit log search, decision lookup |
| **Frontend** | Next.js + TypeScript | SSR for initial load, client-side for interactivity |
| **Auth** | Auth0 / AWS Cognito + RBAC | OIDC + JWT, role-based permissions |
| **NLG (Summaries)** | OpenAI GPT-4o (API) with deterministic templates | Executive summaries; template fallback for regulatory outputs |
| **Infrastructure** | AWS (EKS for containers, RDS, MSK, S3, CloudWatch) | Multi-region support; SOC 2 infrastructure |
| **IaC** | Terraform + Helm | Reproducible, auditable infrastructure |
| **CI/CD** | GitHub Actions + ArgoCD | GitOps model deployment |
| **Observability** | Datadog (APM, logging, metrics) | Unified observability; supports SLA alerting |

### 6.3 Decisioning Engine — Latency Architecture

Real-time decisioning must complete < 200ms (p95). Sequence:

```
Applicant Request
    │
    ▼ (< 5ms)
API Gateway → Auth + Rate Limit
    │
    ▼ (< 10ms)
Feature Resolution Service → Redis cache check → Feature store lookup
    │
    ▼ (< 30ms)
Bureau Pull (if not cached) → Experian/Equifax/TU connector
    │
    ▼ (< 20ms)
Model Scoring Service → SageMaker endpoint or embedded model
    │
    ▼ (< 15ms)
Policy Rule Engine → Rule evaluation against active policy version
    │
    ▼ (< 10ms)
Explainability Service → SHAP values + reason code generation
    │
    ▼ (async, < 50ms, non-blocking)
Audit Log Write → Kafka → QLDB
    │
    ▼ (< 5ms)
Decision Response → Return to LOS / origination channel

Total synchronous path: ≈ 90–140ms (well within 200ms SLA)
```

### 6.4 Multi-Tenant Architecture

- **Tenant isolation model:** Shared infrastructure, isolated data (database-per-tenant on RDS)
- **Tenant configuration:** Per-tenant policy engine config, branding, and integration settings
- **Data isolation enforcement:** Row-level security (RLS) in PostgreSQL + tenant context passed in JWT
- **Tenant onboarding:** Self-service provisioning via admin API, completed in < 4 hours
- **Cross-tenant leakage prevention:** Automated test suite validates tenant data isolation on every deployment

### 6.5 Deployment Model

```
┌──────────────────────────────────────────────────────────┐
│  AWS us-east-1 (Primary)                                 │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐ │
│  │ EKS Cluster │ │ RDS Multi-AZ│ │ MSK Kafka Cluster   │ │
│  │ (services)  │ │ (per tenant)│ │ (event bus)         │ │
│  └─────────────┘ └─────────────┘ └─────────────────────┘ │
└──────────────────────────────────────────────────────────┘
               │  Active-Passive Failover
┌──────────────────────────────────────────────────────────┐
│  AWS us-west-2 (DR / HA)                                 │
│  ┌─────────────┐ ┌─────────────┐                         │
│  │ EKS Cluster │ │ RDS Replica │                         │
│  │ (standby)   │ │ (read only) │                         │
│  └─────────────┘ └─────────────┘                         │
└──────────────────────────────────────────────────────────┘
```

- **RTO (Recovery Time Objective):** < 1 hour
- **RPO (Recovery Point Objective):** < 15 minutes

---

## 7. Data Architecture

### 7.1 Data Layer Overview

ILOL maintains four distinct logical data stores, each with a defined purpose and access pattern:

| Store | Purpose | Technology | Retention |
|---|---|---|---|
| **Decision Store** | Per-application decision record (hot data) | PostgreSQL (RDS) | 7 years |
| **Feature Store** | Feature values at decision time + current feature values | Feast + Redis + S3 | 7 years |
| **Audit Store** | Immutable append-only log of all system events | Amazon QLDB | 10 years |
| **Analytics Store** | Aggregated metrics, portfolio analytics, cohort analysis | Snowflake / BigQuery | 10 years |
| **Model Store** | Model artifacts, versions, validation reports | S3 + MLflow | Indefinite |

### 7.2 Decision Store Schema (Core)

```sql
-- applications table
CREATE TABLE applications (
    application_id      UUID PRIMARY KEY,
    tenant_id           UUID NOT NULL,
    external_ref        VARCHAR(100),            -- LOS application ID
    applicant_id        UUID,                    -- anonymized
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

-- decision_features table (point-in-time feature snapshot)
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
    rules_evaluated     JSONB,                   -- rule name, input, outcome
    waterfall_stage     VARCHAR(50),
    final_policy_outcome VARCHAR(20)
);
```

### 7.3 Data Ingestion Architecture

#### Batch Ingestion (Nightly)
- Core banking system feeds via SFTP / S3 drop zone
- Performance data (delinquency, payoff, charge-off) loaded nightly
- Bureau data enrichment for existing portfolio
- ETL pipeline: AWS Glue + dbt for transformation

#### Real-Time Ingestion (Per Application)
- Bureau API calls (synchronous, inline to decision path)
- LOS webhook (POST to ILOL API on application creation)
- Behavioral data streaming (payment events via Kafka)

#### Data Quality Checks (Automated, per batch)
- Null rate validation per field (configurable threshold)
- Distribution shift detection (PSI vs. prior 30-day baseline)
- Referential integrity checks (application ↔ decision ↔ feature)
- Completeness checks against expected record counts
- Failed checks → alert to data engineering + notification in dashboard

### 7.4 Integration Architecture

#### Loan Origination Systems (LOS)

| Integration Method | Supported LOS |
|---|---|
| REST API (webhook + pull) | Encompass, Byte, MeridianLink, LendingPad |
| SFTP batch | Legacy LOS (configurable field mapping) |
| Native connector (certified) | MeridianLink (primary target for Year 1) |

#### Core Banking Platforms

| Integration Method | Supported Platforms |
|---|---|
| REST API | Symitar, Jack Henry, Finxact, Temenos |
| Database connector (read-only) | SQL Server, Oracle (with VPN tunnel) |
| SFTP batch | All platforms (fallback) |

#### Data Warehouses
- Snowflake: native connector, push-model (ILOL writes to customer Snowflake)
- BigQuery: service account-based write access, partitioned tables
- Redshift: JDBC connector (P2 roadmap)

#### Alternative Data Providers
- Plaid (bank statement / cash flow data)
- Finicity (income + asset verification)
- Nova Credit (newcomer credit file translation)
- Experian Lift (alternative credit scoring)

---

## 8. Compliance & Governance Framework

### 8.1 Regulatory Alignment Matrix

| Regulation | Requirement | ILOL Implementation |
|---|---|---|
| **ECOA / Reg B** | Adverse action notice, non-discrimination | Auto-generated AA notices; fairness monitoring; reason codes |
| **FCRA** | Permissible purpose, accuracy, dispute resolution | Bureau pull logging with permissible purpose; dispute flag in decision log |
| **OCC Model Risk Guidance** | Model validation, documentation, governance | SR 11-7 aligned model cards; validation workflow; performance monitoring |
| **Fed SR 11-7** | Model risk management framework | Model registry, validation status, tiering, ongoing monitoring |
| **CFPB UDAAP** | Unfair, deceptive, abusive acts/practices | Decision consistency monitoring; override audit trail; fairness guardrails |
| **CRA** | Community Reinvestment Act (banks) | Geographic origination mapping; LMI lending metrics |
| **HMDA** | Home Mortgage Disclosure Act (if applicable) | HMDA LAR export with field mapping |
| **SOC 2 Type II** | Security, availability, confidentiality | Encryption, RBAC, audit logging, availability SLAs |
| **GLBA** | Financial data privacy | PII encryption, access controls, data minimization |

### 8.2 SR 11-7 Model Risk Management Compliance

ILOL implements SR 11-7's three-pillar framework:

**Pillar 1: Model Development**
- Model card auto-generation documents intent, training data, assumptions, and limitations
- Model tier assignment (Tier 1: high risk / high volume, Tier 2: moderate, Tier 3: low/simple)
- Documented validation plan required before production deployment

**Pillar 2: Model Validation**
- Independent validation workflow with conflict-of-interest controls (validator ≠ developer)
- Out-of-time and out-of-sample testing required for Tier 1 models
- Validation results stored in audit-immutable record
- Re-validation triggered automatically by: performance degradation (PSI > 0.25, AUC drop > 0.03), data source change, or policy change affecting >30% of applications

**Pillar 3: Ongoing Monitoring**
- Daily metric refresh: AUC, KS, PSI, Gini, calibration
- Automated alerts at configurable thresholds
- Annual recertification schedule managed in model registry
- Model retirement workflow with impact assessment

### 8.3 PII Handling

| Data Category | Handling Approach |
|---|---|
| SSN / Tax ID | AES-256 encrypted at rest; never logged in plain text; tokenized for analytics use |
| Name / Address | Encrypted at rest; masked in non-production environments |
| Protected class attributes | Stored only in compliance-scoped data store; RBAC-restricted to compliance role |
| Credit bureau data | Per FCRA: retained for permissible purpose period; access logged; no resale |
| Bank account data | Plaid access tokens rotated per NACHA guidance; account numbers never stored |

### 8.4 Security Architecture

- **Encryption at rest:** AES-256 (AWS KMS managed keys, per-tenant key rotation)
- **Encryption in transit:** TLS 1.2 minimum, TLS 1.3 preferred; mutual TLS for service-to-service
- **Key management:** AWS KMS + annual key rotation; customer-managed keys available (Enterprise tier)
- **Network isolation:** VPC per environment; private subnets for data services; WAF on public endpoints
- **Penetration testing:** Annual third-party pen test; results logged and remediated under SLA
- **Vulnerability management:** Automated CVE scanning (Snyk / AWS Inspector) on every container build
- **Secret management:** AWS Secrets Manager; no hardcoded credentials in codebase (enforced by pre-commit hooks)
- **Access logs:** All API calls logged to CloudTrail and forwarded to SIEM (Datadog / Splunk)

### 8.5 SOC 2 Type II Controls

| Trust Service Criteria | ILOL Control |
|---|---|
| Security (CC6–CC9) | RBAC, MFA enforcement, WAF, VPC, pen testing |
| Availability (A1) | Multi-AZ deployment, DR plan, RTO/RPO commitments |
| Confidentiality (C1) | PII encryption, data classification, access controls |
| Processing Integrity (PI1) | Decision log hash chain, validation checks, reconciliation |
| Privacy (P1–P8) | GLBA controls, data minimization, subject rights workflow |

---

## 9. API Design

### 9.1 API Design Principles

- **RESTful** (primary) with **GraphQL** available for analytics queries
- API versioning via URL path: `/api/v1/`, `/api/v2/`
- JSON request/response with consistent envelope structure
- All responses include `request_id` for tracing
- OpenAPI 3.0 specification auto-generated from code
- Rate limiting: configurable per tenant, per endpoint tier
- Authentication: Bearer JWT (OAuth 2.0 client credentials for service-to-service)

### 9.2 Core API Endpoints

#### Decisioning API

```
POST   /api/v1/decisions
       Submit application for real-time credit decision
       Request: { application_id, product_type, applicant_data, features }
       Response: { decision_id, outcome, score, reason_codes, policy_version, model_version }

GET    /api/v1/decisions/{decision_id}
       Retrieve full decision record with audit trail
       Response: { decision, features, scores, policy_evaluation, explainability, audit_log }

GET    /api/v1/decisions?from=&to=&outcome=&product=&page=&per_page=
       Query decision log with filters and pagination

POST   /api/v1/decisions/{decision_id}/override
       Submit a manual override (requires dual approval if configured)
       Request: { override_type, justification, requested_outcome, approver_id }
       Response: { override_id, status, routing }
```

#### Policy API

```
GET    /api/v1/policies
       List all policy versions (active + historical)
       Response: [{ policy_id, version, effective_date, status, author, change_reason }]

GET    /api/v1/policies/{policy_id}/versions
       Full version history for a policy
       Response: [{ version, effective_date, author, change_reason, diff_from_prior }]

GET    /api/v1/policies/{policy_id}/versions/{version}/diff
       Visual diff between two versions
       Query params: compare_to=version_string
       Response: { added_rules, removed_rules, modified_rules, impact_summary }

POST   /api/v1/policies/{policy_id}/simulate
       Simulate impact of a proposed policy change on historical decisions
       Request: { proposed_policy_definition, lookback_days }
       Response: { approval_rate_delta, decline_rate_delta, air_delta, affected_application_count }

POST   /api/v1/policies/{policy_id}/rollback
       Roll back to a prior version (requires dual authorization)
       Request: { target_version, justification, secondary_approver_id }
       Response: { rollback_id, status, effective_immediately }
```

#### Governance & Audit API

```
POST   /api/v1/audit/exam-packets
       Generate exam packet for specified date range and scope
       Request: { date_from, date_to, components: [], format, template }
       Response: { job_id, estimated_minutes, status_url }

GET    /api/v1/audit/exam-packets/{job_id}
       Check exam packet generation status and retrieve download URL
       Response: { status, download_url, expires_at }

GET    /api/v1/audit/decisions/{decision_id}/lineage
       Full data lineage for a specific decision
       Response: { features: [{ name, value, source, transform, ingested_at }] }

GET    /api/v1/audit/decisions/{decision_id}/log
       Immutable event log for a decision
       Response: { events: [{ event_type, timestamp, actor, data, hash }] }
```

#### Compliance API

```
GET    /api/v1/compliance/fair-lending/report
       Generate fair lending analysis report
       Query params: from, to, product, comparison_group
       Response: { air_by_protected_class, regression_results, geographic_analysis }

GET    /api/v1/compliance/adverse-actions
       List adverse action notices with delivery status
       Query params: from, to, status, product
       Response: [{ application_id, notice_type, issued_at, delivered_at, delivery_channel }]

GET    /api/v1/compliance/overrides
       Override log with justification and approval chain
       Response: [{ override_id, application_id, operator, justification, approver, outcome }]
```

#### Portfolio Analytics API

```
GET    /api/v1/analytics/portfolio/summary
       Portfolio-level KPI summary
       Query params: as_of_date, segment (optional)
       Response: { originations, approval_rate, dpd_30, dpd_60, dpd_90, net_chargeoff }

GET    /api/v1/analytics/portfolio/vintage
       Vintage analysis by origination cohort
       Query params: from, to, segment
       Response: { vintages: [{ month, volume, dpd_at_3m, dpd_at_6m, dpd_at_12m }] }

GET    /api/v1/analytics/portfolio/segments
       Segment-level performance breakdown
       Query params: segment_dimension (score_band | product | channel | geography)
       Response: { segments: [{ label, volume_pct, dpd_30, approval_rate }] }
```

#### Model Lifecycle API

```
GET    /api/v1/models
       List all models in registry
       Response: [{ model_id, name, version, type, status, champion, last_evaluated }]

POST   /api/v1/models/{model_id}/deployments
       Deploy a model version to champion, challenger, or shadow
       Request: { target_role, traffic_pct, effective_date }
       Response: { deployment_id, status }

GET    /api/v1/models/{model_id}/performance
       Current and historical performance metrics
       Response: { auc, ks, gini, psi, calibration_error, trend_30d }

GET    /api/v1/models/{model_id}/card
       Retrieve SR 11-7 aligned model card
       Response: { model_card_json } or PDF download
```

### 9.3 Webhook Events

| Event | Trigger | Payload |
|---|---|---|
| `decision.created` | New decision returned | decision_id, outcome, score |
| `decision.override` | Override submitted/approved | override_id, decision_id, outcome |
| `policy.changed` | Policy version promoted | policy_id, new_version, old_version |
| `model.deployed` | Model version goes live | model_id, version, role |
| `alert.triggered` | Threshold breach detected | alert_id, metric, value, threshold |
| `exam_packet.ready` | Packet generation complete | job_id, download_url |

---

## 10. Metrics & Success Criteria

### 10.1 Platform Health Metrics (Internal)

| Metric | Target | Measurement |
|---|---|---|
| Decisioning API p50 latency | < 100ms | Datadog APM |
| Decisioning API p95 latency | < 200ms | Datadog APM |
| Decisioning API p99 latency | < 500ms | Datadog APM |
| Platform availability | > 99.9% | Monthly uptime report |
| Audit log write success rate | 100% | Kafka consumer lag + DLQ |
| Exam packet generation success | > 99.5% | Job queue metrics |
| PII exposure events | 0 | Security audit |
| Failed bureau pulls (unresolved) | < 0.1% | Connector health dashboard |

### 10.2 Customer Success Metrics

| Metric | Baseline (pre-ILOL) | Target (12 months post) |
|---|---|---|
| Time to generate exam packet | 4–8 weeks | < 5 minutes |
| Compliance team exam prep hours | 400+ hrs / exam | < 20 hrs / exam |
| Days to identify model degradation | 30–90 days | < 3 days |
| Adverse action notice error rate | 2–5% | < 0.1% |
| Policy change cycle time | 2–4 weeks | < 3 days (including testing) |
| Fair lending report generation | 2–4 weeks (external consultant) | On-demand, in-house |

### 10.3 Business Success Metrics

| Metric | Year 1 Target | Year 2 Target |
|---|---|---|
| Paying customers | 15–25 | 50–75 |
| ARR | $2.5M–$4M | $8M–$12M |
| Net Revenue Retention | > 110% | > 120% |
| Time to first value (exam packet) | < 30 days from contract | < 14 days |
| Customer NPS | > 50 | > 60 |
| Churn rate | < 5% annually | < 5% annually |

### 10.4 Regulatory Outcome Metrics (Customer-Measured)

| Metric | Description |
|---|---|
| Exam findings attributable to documentation gaps | Target: 0 per customer using ILOL |
| Fair lending enforcement actions | Target: 0 per customer (proactive monitoring) |
| Adverse action notice violations | Target: 0 (auto-generation + compliance check) |
| Model risk management MRAs | Target: reduction in Matters Requiring Attention related to model governance |

---

## 11. Implementation Roadmap

### 11.1 Phasing Philosophy

Each phase delivers a complete, shippable product — not a partial system. Customers can purchase Phase 1 alone and receive immediate value. Phase 2 builds on Phase 1 capabilities. Phase 3 is an enterprise expansion layer.

```
Phase 1 (MVP)           Phase 2 (Growth)         Phase 3 (Enterprise)
Months 1–6              Months 7–12              Months 13–18
─────────────────        ─────────────────        ─────────────────
Governance Core          Portfolio Analytics      Model Lifecycle Mgmt
Decision Logger          Fairness Monitoring      A/B Testing Framework
Policy Versioning        Executive Summaries      Advanced NLG Engine
Exam Packet (basic)      Intelligent Alerting     White-label / OEM
2–3 LOS integrations     Full bureau integration  Multi-tenant SaaS
```

---

### Phase 1: Governance Foundation (Months 1–6)

**Theme:** "Be audit-ready in 30 days"
**Target buyer:** Compliance officer at credit union or fintech lender facing imminent examination or regulatory review

#### Phase 1 Deliverables:

| Feature | Description | Month |
|---|---|---|
| Immutable decision log | Append-only log with cryptographic hash chain | M2 |
| Policy versioning v1 | Create, version, and activate credit policies | M2 |
| Basic decisioning API | REST endpoint: submit → score → return decision | M3 |
| Experian integration | Real-time bureau pull + data mapping | M3 |
| RBAC + Auth | Auth0 integration, 6 roles defined | M3 |
| Reason code generation | SHAP-based top-4 adverse factors | M4 |
| Exam packet v1 | Policy history + decision log export (PDF) | M4 |
| Adverse action module | Reg B notice templates + generation | M4 |
| Admin dashboard | Tenant setup, user management | M5 |
| MeridianLink integration | Bi-directional LOS connector | M5 |
| Policy rollback | One-click rollback with dual approval | M6 |
| Data lineage v1 | Feature provenance for each decision | M6 |
| Audit log search | OpenSearch indexing + query UI | M6 |

**Phase 1 Success Criteria:**
- <= 200ms p95 decisioning latency
- Exam packet generated in < 15 minutes
- 3 paying pilot customers live
- Zero data integrity issues in audit log

---

### Phase 2: Intelligence & Monitoring (Months 7–12)

**Theme:** "See your portfolio in real time, and never be surprised"
**Target expansion:** Risk analysts and CROs who want proactive portfolio intelligence

#### Phase 2 Deliverables:

| Feature | Description | Month |
|---|---|---|
| Portfolio dashboard v1 | Originations, approval rate, DPD metrics | M7 |
| Vintage analysis | Cohort performance by origination month | M8 |
| Fairness monitoring | Daily AIR calculation + alert | M8 |
| Intelligent alerting | Configurable thresholds, UI + email | M9 |
| Equifax + TransUnion | Full tri-bureau integration | M9 |
| Policy simulation | Impact preview before deployment | M9 |
| Visual policy diff | Side-by-side version comparison | M10 |
| Executive summaries v1 | NLG-powered weekly/monthly CRO digest | M10 |
| Exam packet v2 | Fair lending + override log included | M11 |
| Drill-down: portfolio → loan | Linked portfolio-to-decision navigation | M11 |
| Webhook event system | decision.created, alert.triggered events | M11 |
| GraphQL analytics API | Flexible portfolio query API | M12 |

**Phase 2 Success Criteria:**
- 15+ paying customers
- Alert-to-investigation workflow in < 5 minutes
- NLG summaries rated accurate by CRO users (> 4.0/5.0)
- Zero missed AIR threshold violations

---

### Phase 3: Model Lifecycle & Enterprise Scale (Months 13–18)

**Theme:** "Own your model risk governance"
**Target expansion:** Data science teams and model risk management functions

#### Phase 3 Deliverables:

| Feature | Description | Month |
|---|---|---|
| Model registry | Full model versioning, metadata, status | M13 |
| Model performance monitoring | Daily AUC/KS/PSI with alerts | M14 |
| SR 11-7 model card generation | Auto-generated documentation | M14 |
| Champion/challenger framework | Traffic splitting with guardrails | M15 |
| A/B testing framework | Policy/model experimentation engine | M15 |
| Advanced NLG | Configurable tone, audience, depth | M15 |
| Snowflake/BigQuery push | Native write connector for analytics | M16 |
| Multi-product policy engine | Card, auto, personal loan, BNPL | M16 |
| Plaid / Finicity integration | Cash flow + income data enrichment | M17 |
| White-label / OEM API | Branded API for lender-as-a-platform | M17 |
| Compliance dashboard v2 | Full regulatory posture view | M18 |
| SOC 2 Type II audit | Third-party certification | M18 |

**Phase 3 Success Criteria:**
- 50+ paying customers
- SOC 2 Type II certified
- Model risk management workflow handles full SR 11-7 lifecycle
- NPS > 55

---

### 11.2 Team Structure Required

| Role | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|
| Backend Engineers (Python/Go) | 3 | 5 | 6 |
| Frontend Engineers (Next.js) | 1 | 2 | 3 |
| Data Engineer | 1 | 2 | 2 |
| ML / AI Engineer | 1 | 1 | 2 |
| DevOps / Platform Engineer | 1 | 1 | 2 |
| Product Manager | 1 | 1 | 2 |
| Compliance Advisor (part-time) | 1 | 1 | 1 |
| Total | **9** | **13** | **18** |

### 11.3 Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Bureau API latency exceeds SLA | Medium | High | Multi-bureau caching + fallback rules |
| Regulatory guidance changes (CFPB) | Medium | High | Modular compliance templates; advisory board review quarterly |
| Multi-tenant data isolation failure | Low | Critical | Automated isolation tests on every deploy; pen test annually |
| NLG generates inaccurate regulatory summaries | Medium | High | Template-constrained generation; human review workflow for exam packets |
| Model explainability challenged in litigation | Low | High | Log all SHAP values; methodology documented; expert witness protocol |
| LOS integration complexity exceeds timeline | High | Medium | Prioritize MeridianLink; SFTP fallback for all others in Phase 1 |
| Exam packet generation latency > 5 minutes | Low | Medium | Pre-computation of common report components; async generation with email delivery |

---

## Appendix A: Glossary

| Term | Definition |
|---|---|
| **AIR** | Adverse Impact Ratio — ratio of approval rates between protected and control groups |
| **AUC** | Area Under the ROC Curve — model discrimination metric |
| **KS** | Kolmogorov-Smirnov statistic — separation between good/bad score distributions |
| **PSI** | Population Stability Index — measures distribution shift over time |
| **SHAP** | SHapley Additive exPlanations — model explainability method |
| **SR 11-7** | Federal Reserve Supervisory Guidance on Model Risk Management |
| **ECOA** | Equal Credit Opportunity Act |
| **Reg B** | Regulation B — implements ECOA |
| **FCRA** | Fair Credit Reporting Act |
| **UDAAP** | Unfair, Deceptive, or Abusive Acts or Practices |
| **LOS** | Loan Origination System |
| **DPD** | Days Past Due |
| **MRA** | Matter Requiring Attention (regulatory finding category) |
| **NLG** | Natural Language Generation |
| **QLDB** | Amazon Quantum Ledger Database — immutable, cryptographically verifiable ledger |
| **RBAC** | Role-Based Access Control |
| **RTO / RPO** | Recovery Time Objective / Recovery Point Objective |
| **HMDA** | Home Mortgage Disclosure Act |
| **CRA** | Community Reinvestment Act |

---

## Appendix B: Integration Checklist (Go-Live Requirements)

For each new customer deployment, the following must be completed before Go-Live:

- [ ] LOS integration configured and tested (round-trip decision test with >100 applications)
- [ ] Core banking feed established (nightly performance data flowing)
- [ ] Bureau integration live (test pulls via Experian sandbox, then production)
- [ ] RBAC configured (all user roles assigned, dual-approver designees named)
- [ ] Policy uploaded and versioned (initial production policy in ILOL registry)
- [ ] Exam packet test run completed (full packet generated for sample date range)
- [ ] Alert thresholds configured (AIR, DPD, approval rate — reviewed with risk team)
- [ ] Adverse action notice templates reviewed and approved by compliance officer
- [ ] Data retention policy confirmed (7-year minimum)
- [ ] Disaster recovery test completed

---

*Document Control: This PRD is version-controlled in the project repository. Changes require product manager approval and stakeholder review before merging. All prior versions are retained.*

*Classification: Internal — Confidential. Not for external distribution without redaction review.*
