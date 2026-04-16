# Governance-Native Credit Decisioning Audit Platform
### with RAG-Powered AI Analytics Agent Layer

> **Product Name:** Governance-Native Credit Decisioning Audit Platform (GNCDA)
> **Version:** v2.1 | **Date:** April 15, 2026 | **Status:** ACTIVE
> **Owner:** Product / Risk / Compliance / AI Engineering
> **Previous Version:** v2.0 (AI agent layer — pre-code transparency)
> **Change Summary (v2.1):** Added Code Transparency Layer — every AI-generated analysis answer must surface the full executable code (SQL + Python) used to produce it, enabling users to independently validate, reproduce, and audit the answer.

---

## 1. 🎯 Product Overview

### 1.1 Vision

Build a **governance-first operating layer** for credit card and installment lenders that combines:

- **Regulator-ready auditability** of every credit decision end-to-end
- **Continuous compliance monitoring** against ECOA/Reg B, UDAAP, and SR 11-7
- **One-click generation** of examiner-ready audit evidence packages
- **RAG-powered AI Analytics Agent** that answers complex risk, compliance, and portfolio questions in natural language — with zero hallucination tolerance and full auditability of every answer produced

The platform behaves like a **Chief Risk Officer's analytical right hand**: a Capital One-grade analytics consultant embedded directly into compliance and risk workflows, with every answer traceable to a dataset, query, and timestamp.

---

### 1.2 Problem Statement

Mid-market credit lenders face compounding pressures:

| Problem Dimension | Current Pain |
|---|---|
| Fragmented audit systems | Decisioning, data, models, and compliance live in separate silos |
| Manual, reactive audit prep | Exam preparation takes 4–6 weeks of analyst time per cycle |
| Lack of decision explainability | SHAP scores exist but aren't surfaced to compliance teams in accessible language |
| Blind-spot analytics | Portfolio questions requiring cross-system joins take days via data teams |
| Model risk exposure | SR 11-7 validation cycles are tracked in spreadsheets |
| Fair lending risk | Automated disparate impact analysis is absent or inconsistent |
| AI hallucination risk | Generic LLMs cannot be trusted to answer regulatory questions without grounding |

---

### 1.3 Solution

A modular SaaS platform — deployed on **Google Cloud Run** with **BigQuery** as the analytical backbone — that:

1. Captures every credit decision with full input-model-rule-output traceability (existing `audit/logger.py` layer)
2. Continuously audits decisions against regulatory expectations via a real-time compliance engine (`compliance/engine.py`)
3. Produces regulator-ready audit packages on demand with version-controlled governance artifacts
4. Answers any natural-language risk or portfolio question via a **RAG-grounded multi-agent system** backed by BigQuery, decision logs, model documentation, and regulatory knowledge bases — with every answer linked to a source query, confidence score, **and full executable code**
5. Generates polished outputs (PDF, Excel, structured JSON) that can be attached directly to exam responses
6. **Surfaces every SQL query and Python analysis script** used to produce an AI answer — giving users a first-class mechanism to independently validate, reproduce, and challenge any insight before acting on it

---

### 1.4 Strategic Differentiation

| Capability | Generic BI Tool | Generic LLM Chatbot | GNCDA v2 |
|---|---|---|---|
| Decision-level audit trace | ❌ | ❌ | ✅ Real-time, per-decision |
| Regulatory template mapping | ❌ | ❌ | ✅ ECOA / SR 11-7 / UDAAP |
| AI analytics on portfolio data | Limited | Hallucination risk | ✅ RAG-grounded, BigQuery-backed |
| Anti-hallucination enforcement | N/A | None | ✅ Schema-grounded + confidence scoring |
| Audit trail on AI answers | ❌ | ❌ | ✅ Every AI answer is itself auditable |
| **Code transparency on every answer** | ❌ | ❌ | ✅ Full SQL + Python shown, copyable, re-runnable |
| SHAP reason code integration | ❌ | ❌ | ✅ Via `agents/explainability_agent.py` |
| Fair lending automation | ❌ | ❌ | ✅ Built-in disparate impact engine |

---

## 2. 👤 Target Users

### Primary Users

| Role | Primary Use Case | Key AI Agent Interaction |
|---|---|---|
| Head of Credit Risk | Portfolio oversight, policy decisions | "What drove the 15% decline rate increase in Q1 among thin-file applicants?" |
| Compliance Officer | Exam prep, adverse action review | "Generate a Reg B adverse action reason code summary for the past 90 days" |
| Model Risk Manager | SR 11-7 compliance, drift monitoring | "Show me all models that have not had an independent validation in 12 months" |
| Internal Audit | Controls testing, decision sampling | "Pull a stratified random sample of 200 decline decisions for manual review" |

### Secondary Users

| Role | Access Level |
|---|---|
| Regulators (CFPB, OCC, Federal Reserve) | Read-only audit view — pre-generated packages |
| Data Science / Underwriting Teams | Model monitoring dashboards, SQL query review |
| Executive Leadership | AI-generated portfolio summary briefs |

---

## 3. 🧱 Core Product Modules

### 3.1 Decisioning Audit Engine

**Objective:** Continuously audit every credit decision for compliance, consistency, and explainability.

**Inputs**
- Application data (customer attributes, bureau data — `schemas/contracts.py`)
- Decision outputs (APPROVE / DECLINE / REFER, credit limit, APR — `decision-api/src/main.py`)
- Model scores (PD, fraud score — `models/credit_risk/predict.py`, `models/fraud_detection/predict.py`)
- SHAP reason codes (`agents/explainability_agent.py`)
- Policy rule configurations (`decision_engine/policy_dsl.py`)

**Processing**
- Validate decision against policy rules (AST-validated DSL — no `eval()` risk)
- Trace input → feature engineering → model → rule application → output path
- Check for missing or inconsistent Reg B reason codes
- Detect overrides and deviations with mandatory justification requirements
- Cross-validate SHAP importance against adverse action reason codes

**Outputs**
- Decision audit logs (fully traceable, append-only — `audit/logger.py`)
- Compliance flags (e.g., missing adverse action reason, prohibited variable exposure)
- Decision consistency score (policy-model alignment metric)

**Key Features**
- Real-time decision tracing (< 200ms p99 on Cloud Run)
- SHAP-powered explainability layer with Reg B reason code mapping
- Override detection engine with approver chain tracking
- Immutable audit log (append-only BigQuery partitioned table)

---

### 3.2 Governance Document Generator

**Objective:** Automatically generate examiner-ready documentation — eliminating 4–6 weeks of manual exam prep.

**Inputs**
- Decision logs (BigQuery — `db/bigquery_schema.py`)
- Model documentation (MLflow registry — version, training date, performance metrics)
- Policy configurations and change logs (`decision_engine/policy_dsl.py` version history)
- Validation reports and committee approval records

**Processing**
- Assemble structured audit packages mapped to regulatory templates (ECOA, SR 11-7, UDAAP)
- AI-assisted narrative generation using the Governance AI Agent (grounded in logged data only)
- Version-controlled artifact assembly with diff tracking across policy changes
- One-click packaging with digital signature metadata

**Outputs**
- Audit-ready PDF with indexed table of contents
- Model Development Document (MDD) populated from MLflow artifact store
- Policy documentation snapshots with effective date history
- Adverse action notice compliance summary (Reg B)

**Key Features**
- One-click "Generate Audit Package" via REST API and UI
- Pre-mapped templates for CFPB, OCC, and Federal Reserve examinations
- Version-controlled documentation with change delta highlighting
- AI narrative summaries grounded strictly in logged data (not generated from LLM memory)

---

### 3.3 Fair Lending Monitor

**Objective:** Continuously detect and flag potential fair lending violations with statistical rigor.

**Inputs**
- Decision data from BigQuery audit tables (approvals, declines, pricing, limits)
- Protected class proxies (Bayesian Improved Surname Geocoding — BISG, where applicable)
- APR assignments and credit limit decisions by segment
- Application attributes (state, application channel, product type)

**Processing**
- Disparate impact analysis (4/5ths rule, regression-based approach)
- Segment-level approval rate comparison across protected class proxies
- Statistical significance testing (z-test, chi-square) with configurable confidence thresholds
- SHAP-based feature attribution to detect proxy variable use in model decisions
- MLA compliance checks via `compliance/engine.py`

**Outputs**
- Fair lending risk dashboard with drill-down by segment and time period
- Disparate impact ratios with statistical confidence intervals
- Threshold breach alerts routed to Compliance Officer queue
- AI-generated plain-language fair lending summary for exam response

**Key Features**
- Automated BISG-proxy testing
- Scenario simulation (policy/model change impact on approval rate disparity)
- Historical trend tracking with configurable lookback windows
- AI agent integration: "Run a fair lending analysis on last quarter's auto-decline population"

---

### 3.4 Model Risk Dashboard

**Objective:** Monitor model performance, drift, and compliance with SR 11-7 model risk guidelines across the full model inventory.

**Inputs**
- Live model predictions (XGBoost PD model, fraud detection model — `models/` directory)
- Actual performance data (loan performance from BigQuery — `agents/bq_writer_agent.py`)
- MLflow experiment tracking: version, training date, test set metrics
- Independent validation reports (uploaded, linked to model version)

**Processing**
- Performance tracking (KS statistic, AUC-ROC, Gini coefficient, PSI) via Scikit-learn/MLflow
- Input drift detection (PSI on feature distributions vs. training baseline)
- Output drift detection (score distribution shift)
- Benchmark comparisons against challenger models
- Validation status tracking (validated / overdue / approaching due date)

**Outputs**
- Model health score (0–100, composite of performance + stability + governance)
- Population Stability Index (PSI) alerts with feature-level decomposition
- Independent validation status per model (SR 11-7 compliance calendar)
- Drift alerts routed to Model Risk Manager queue

**Key Features**
- Real-time model monitoring via BigQuery materialized views
- Model inventory management linked to MLflow registry
- Automated SR 11-7 documentation gap detection
- AI agent query: "Which models are at risk of failing the next validation cycle?"

---

### 3.5 Portfolio Monitoring Engine

**Objective:** Track portfolio-level outcomes, policy effectiveness, and early warning signals in real time.

**Inputs**
- Loan performance data (BigQuery — monthly roll-up from `agents/bq_writer_agent.py`)
- Decision cohorts (application vintage, decision month, product type)
- Risk segmentation (risk tier, bureau score band, product)
- External macro data (optional: delinquency benchmarks)

**Processing**
- Delinquency roll rate matrix (current → 30 → 60 → 90 → charge-off)
- Vintage curve generation and projection (logistic curve fitting)
- Policy impact evaluation (champion/challenger A/B cohort comparison)
- Concentration risk analysis (geographic, employer, channel)
- Early warning signal detection (anomaly detection on roll rate acceleration)

**Outputs**
- Portfolio dashboards with drill-down to decision cohort level
- Vintage curve visualizations with forward projection bands
- Early warning signal alerts (configurable thresholds)
- AI-generated portfolio commentary for risk committee reporting

**Key Features**
- Cohort-based vintage tracking from origination through charge-off
- Policy A/B performance comparison (champion/challenger)
- AI agent: "Summarize Q1 vintage performance vs. Q1 last year with root cause hypothesis"
- Export to Excel (multi-tab: raw data, roll rates, vintage curves, AI narrative)

---

## 4. 🤖 RAG-Powered AI Analytics Agent Platform

This is the net-new capability layer introduced in v2.0. The AI Agent Platform operates with **zero hallucination tolerance** — every answer is grounded in retrieved data from BigQuery, audit logs, model documentation, and the compliance knowledge base.

### 4.1 Product Vision for the AI Agent Layer

Users across risk, compliance, audit, and executive functions can:

- Ask natural-language analytics questions via the **Command Center UI** or **REST API**
- Receive structured analysis plans before execution (with optional approval gate)
- Get verified, data-backed answers with source citations and confidence scores
- Receive professional outputs: PDF summaries, Excel workbooks, or structured JSON for downstream systems

The system behaves like a **top-tier credit risk analytics consultant** (Capital One / McKinsey-level rigor) embedded into daily workflows — but with the audit trail of a regulated financial institution.

---

### 4.2 Core AI Agent Capabilities

#### 4.2.1 Context Understanding Engine

- Interpret ambiguous credit risk and compliance questions using domain-tuned prompt templates
- Identify **business intent**, **risk metrics / KPIs**, **time horizons**, and **required data sources**
- Classify question type: descriptive, diagnostic, predictive, prescriptive, or compliance-specific
- Maintain **session memory** across multi-turn conversations (Redis-backed context store)
- Detect when a question requires regulatory interpretation vs. data retrieval, and route accordingly

**Example intent classifications:**

| User Question | Detected Intent | Required Agent |
|---|---|---|
| "Why did approvals drop last month?" | Diagnostic / Portfolio | Data Retrieval + Insight Generator |
| "Are we at fair lending risk?" | Compliance / Fair Lending | Fair Lending Agent + Regulatory KB |
| "Generate the Q2 audit package" | Governance / Document | Governance Document Agent |
| "Show model drift for the PD model" | Model Risk / Performance | Model Risk Agent |

---

#### 4.2.2 Retrieval-Augmented Generation (RAG) Layer

The RAG layer grounds every AI response in verified enterprise data — preventing hallucination at the architectural level.

**Retrieval Sources:**

| Source | Content | Technology |
|---|---|---|
| BigQuery audit tables | Decision logs, performance data, fair lending metrics | BigQuery Python client (`db/bigquery_client.py`) |
| BigQuery analytics | Portfolio KPIs, vintage curves, roll rates | Materialized views + Pandas |
| MLflow artifact store | Model versions, training metrics, validation status | MLflow Python API |
| Policy DSL repository | Credit policy rules, change history | Git-backed, parsed AST |
| Regulatory knowledge base | SR 11-7, ECOA/Reg B, UDAAP rules text | Vertex AI Matching Engine |
| Governance document store | MDD templates, exam packages, committee minutes | GCS + metadata index |
| Compliance engine rules | Configured compliance rules (`compliance/engine.py`) | In-memory + structured extraction |

**Retrieval Architecture:**
- **Schema-aware SQL generation**: Query Builder Agent generates BigQuery SQL validated against registered schemas — never raw LLM SQL executed blindly
- **Hybrid search**: semantic (Vertex AI embeddings) + keyword (BigQuery SEARCH) for documentation retrieval
- **Data lineage awareness**: every retrieved data point carries its lineage tag (source table, partition date, query hash)
- **Vector DB**: Vertex AI Matching Engine for regulatory KB and document embeddings
- **Embedding model**: `text-embedding-004` (Google) — consistent with existing GCP stack

---

#### 4.2.3 Analysis Planning Engine

Before any data query is executed, the Planning Agent generates a transparent, user-reviewable plan:

```
Analysis Plan: "What drove the approval rate decline in March?"
─────────────────────────────────────────────────────────────
Step 1: Query decision_logs table for March vs. February approval rates
        → Tables: audit.decision_log | Partition: 2026-02-01 to 2026-03-31
        → Grouping: decision_month, risk_tier, product_type

Step 2: Decompose decline reasons by reason_code
        → Tables: audit.adverse_action_reasons | Join: decision_id

Step 3: Cross-reference model score distribution changes (PSI)
        → Tables: model_monitoring.score_distribution | Metric: PSI > 0.1

Step 4: Investigate policy rule change log for the period
        → Source: policy_dsl version history (Git)

Assumptions: Approval rate = approved / total applications (excluding withdrawn)
Confidence: HIGH (all required data partitions present and complete)
Estimated execution time: ~8 seconds
```

- **Ambiguity detection**: if underspecified, Planner Agent asks targeted clarifying questions before proceeding
- **Optional approval gate** (strict mode): user must confirm the plan — required for compliance-sensitive queries
- **Assumptions documented**: every plan explicitly states what is assumed and what is excluded

---

#### 4.2.4 Query Generation & Execution Engine

- **SQL Generation**: Query Builder Agent generates BigQuery SQL via structured prompting with schema injection
- **Validation before execution** (mandatory):
  - Syntax validation (BigQuery dry-run API — zero bytes processed)
  - Schema alignment check (column names and types verified against registered schema)
  - Data access permission check (row-level security, RBAC via GCP IAM)
  - Prohibited column filter (PII masked; ECOA-prohibited variables flagged)
- **Execution**: secure sandbox — queries executed via service account with read-only BigQuery permissions
- **Auditable compute**: every query and its hash logged to `audit.agent_query_log` before execution
- **Python analysis**: Pandas / Scikit-learn for statistical analysis on query results (not raw LLM computation)
- **Code capture (mandatory)**: every SQL query and every Python analysis snippet is captured verbatim at execution time and attached to the answer as a `code_artifact` — this is the source-of-truth code that produced the result, not a reconstruction
- **Code serialization**: code artifacts are stored as versioned, immutable objects in GCS alongside the answer JSON; they are never re-generated post-execution

---

#### 4.2.5 Result Interpretation & Insight Generation

- **Statistical analysis**: trend detection, segmentation, correlation analysis, hypothesis testing
- **Root cause analysis**: multi-factor decomposition using SHAP-style attribution on aggregated metrics
- **Business narrative**: Insight Generator Agent translates statistical findings into plain-language summaries
- **Regulatory framing**: Regulatory Interpreter Agent maps findings to specific requirements (e.g., "This adverse impact ratio of 0.78 falls below the 0.80 threshold under the 4/5ths rule — ECOA/Reg B review required")
- **Confidence labeling**: every insight carries a confidence tier (HIGH / MEDIUM / LOW) based on data completeness and statistical significance

---

#### 4.2.6 Output Generation — Multi-Format

| Output Type | Use Case | Contents |
|---|---|---|
| **Executive Brief (PDF)** | Risk committee, Board reporting | AI narrative + charts + data citations + confidence scores + **appendix: full code** |
| **Exam Response Package (PDF)** | Regulatory examination | Mapped to examiner request items, version-stamped + **appendix: full code** |
| **Excel Workbook** | Analyst review | Tab 1: Raw data \| Tab 2: Aggregations \| Tab 3: Pivot tables \| Tab 4: AI narrative \| **Tab 5: SQL + Python code** |
| **PowerPoint** | Management presentation | Chart-first slides with AI-generated commentary |
| **JSON / API Response** | Downstream system integration | Structured insight object with lineage metadata + **`code_artifacts` array** |
| **Audit Log Entry** | Immutable record | Query, plan, result hash, confidence score, timestamp, **code artifact GCS URI** |
| **Standalone Code Export** | Independent validation / reproduction | Raw `.sql` and `.py` files downloadable as a `.zip` archive |

Every output is **self-documenting**: includes source queries, SQL executed, Python analysis code, time range, and confidence score — submittable directly as audit evidence.

---

#### 4.2.7 Code Transparency Layer *(Key Differentiator — New in v2.1)*

**Principle:** Every AI-generated analysis answer MUST be accompanied by the complete, executable code that produced it. The user is never asked to trust a number they cannot verify.

This is the single most powerful trust-building mechanism in the platform. A compliance officer, internal auditor, or regulator can take the surfaced code, run it independently against BigQuery, and get the same result — or flag a discrepancy. This transforms the AI from a black box into a **transparent analytical collaborator**.

**What is surfaced per answer:**

| Code Artifact | Content | Format |
|---|---|---|
| **BigQuery SQL** | Exact query executed (not a reconstruction) — including all WHERE clauses, JOINs, GROUP BYs, and LIMIT/PARTITION filters | `.sql` file or inline code block |
| **Python Analysis Script** | Pandas / Scikit-learn code for all post-query computation (roll rates, PSI, t-tests, Gini) — annotated with inline comments | `.py` file or inline code block |
| **Execution Metadata** | BigQuery job ID, bytes processed, execution timestamp, row count returned | JSON metadata block |
| **Reproducibility Instructions** | Step-by-step: authenticate → connect → run SQL → run Python → compare output | Plain-text block in output |

**Code Display — UX Rules:**

```
AI Answer:
  ┌────────────────────────────────────────────────────┐
  │ Approval rates for thin-file applicants declined   │
  │ 8.2 pp in Q1 2026 vs Q1 2025 [HIGH confidence]    │
  │                                                    │
  │  📊 Source: audit.decision_log | n=4,200           │
  └────────────────────────────────────────────────────┘

  [👁️ Show Code ▾]  ← collapsed by default; expanded on click

  └─ SQL Query (Step 1 of 3):
     ┌────────────────────────────────────────────────────┐
     │ SELECT                                             │
     │   DATE_TRUNC(decision_timestamp, QUARTER) AS qtr, │
     │   bureau_score_band,                               │
     │   COUNTIF(outcome = 'APPROVE') / COUNT(*) AS rate  │
     │ FROM `project.audit.decision_log`                  │
     │ WHERE product_type = 'credit_card'                 │
     │   AND bureau_score_band = 'thin_file'              │
     │   AND decision_timestamp                           │
     │       BETWEEN '2025-01-01' AND '2026-03-31'        │
     │ GROUP BY 1, 2                                      │
     └────────────────────────────────────────────────────┘
     [Copy SQL] [Run in BQ Console] [Download .sql]

  └─ Python Analysis (Step 2 of 3):
     ┌────────────────────────────────────────────────────┐
     │ # Q1 YoY approval rate comparison                  │
     │ q1_2025 = df[df['qtr'] == '2025-01-01']['rate']   │
     │ q1_2026 = df[df['qtr'] == '2026-01-01']['rate']   │
     │ delta_pp = (q1_2026 - q1_2025).mean() * 100       │
     │ # Result: delta_pp = -8.2                          │
     └────────────────────────────────────────────────────┘
     [Copy Python] [Download .py] [Export as Notebook (.ipynb)]

  Execution: BQ Job ID bqjob_r75a... | 2.1 MB processed | 4,200 rows
```

**Code Transparency Rules (Non-Negotiable):**
1. Code is captured at execution time and stored immutably — never regenerated from LLM after the fact
2. Code is displayed inline in the chat UI in a syntax-highlighted, copyable code block
3. Code is included in every PDF appendix and every Excel `Code` tab with no exceptions
4. The "Copy SQL" / "Run in BQ Console" / "Download .py" / "Export as Notebook" actions are always available
5. If any computation step has no associated code (e.g., retrieval from a document store), this is explicitly stated: *"Step 3: Retrieved from GCS document `sr_11_7_guidance_v4.pdf` — no SQL generated"*
6. The `FormatterAgent` is responsible for assembling `code_artifacts` into every output format; failure to include code artifacts causes the output to be flagged as incomplete and withheld

**User Value Proposition:**
- **Validate**: "The AI says approvals dropped 8.2 pp — let me run this SQL myself to confirm"
- **Reproduce**: paste the SQL into BigQuery Console or the Python into a Jupyter notebook and get identical results
- **Audit**: regulators and internal auditors can verify the exact computation methodology, not just the output number
- **Trust**: "I don't have to take the AI's word for it — I can see exactly how it got there"

---

### 4.3 Multi-Agent Architecture

Implemented in Python using the existing `orchestration/pipeline.py` framework.

```
┌──────────────────────────────────────────────────────────┐
│               GNCDA AI Agent Platform                    │
├──────────────────────────────────────────────────────────┤
│  User Query (UI / REST API)                              │
│      │                                                   │
│      ▼                                                   │
│  CoordinatorAgent ← Session memory (Redis) + RBAC       │
│      │                                                   │
│  ┌───┴────────────────────┐                              │
│  ▼                        ▼                              │
│  IntentClassifierAgent    ComplianceGateAgent            │
│      │                    (compliance/engine.py)         │
│      ▼                                                   │
│  PlannerAgent ← Schema registry + ambiguity detection   │
│      │  (plan shown to user; approval gate if strict)   │
│      ▼                                                   │
│  ┌──────────────────────────────────┐                   │
│  │   Specialist Agent Routing       │                   │
│  │  Portfolio | FairLending |       │                   │
│  │  ModelRisk | AuditGovernance     │                   │
│  └──────────────┬───────────────────┘                   │
│                 ▼                                        │
│  DataRetrievalAgent (BigQuery | MLflow | GCS | RAG)     │
│                 ▼                                        │
│  QueryBuilderAgent (BQ dry-run | schema | PII mask)     │
│                 ▼                                        │
│  ExecutionAgent (read-only BigQuery SA)                 │
│                 ▼                                        │
│  InsightGeneratorAgent + RegulatoryInterpreterAgent     │
│                 ▼                                        │
│  ValidatorAgent (reconciliation + confidence scoring)   │
│                 ▼                                        │
│  FormatterAgent (PDF | Excel | PPT | JSON | AuditLog)   │
└──────────────────────────────────────────────────────────┘
```

**Specialist Agent Responsibilities:**

| Agent | Responsibility | Key Data Sources |
|---|---|---|
| `CoordinatorAgent` | Session management, routing, RBAC enforcement | Redis, IAM |
| `IntentClassifierAgent` | Classify query type and extract entities | Prompt template + LLM |
| `ComplianceGateAgent` | Block queries exposing prohibited data | `compliance/engine.py` |
| `PlannerAgent` | Generate step-by-step analysis plan | Schema registry, BQ metadata |
| `PortfolioAnalyticsAgent` | Portfolio, vintage, roll rate, delinquency | BigQuery portfolio tables |
| `FairLendingAgent` | Disparate impact, approval rate disparity | BigQuery decision tables + BISG |
| `ModelRiskAgent` | PSI, AUC drift, validation status | MLflow + BigQuery monitoring |
| `AuditGovernanceAgent` | Audit package assembly, policy doc generation | GCS + BQ audit logs |
| `DataRetrievalAgent` | RAG retrieval from all sources | BigQuery + GCS + Vertex AI |
| `QueryBuilderAgent` | BQ SQL generation and validation | Schema registry + BQ dry-run |
| `ExecutionAgent` | Execute validated queries (read-only SA) | BigQuery |
| `InsightGeneratorAgent` | Statistical analysis + narrative | Pandas + LLM (grounded) |
| `RegulatoryInterpreterAgent` | Map findings to regulatory requirements | Regulatory KB (Vertex AI RAG) |
| `ValidatorAgent` | Anti-hallucination checks + confidence scoring | Query results + schema |
| `FormatterAgent` | Multi-format output generation | ReportLab, openpyxl, python-pptx |

---

### 4.4 Tech Stack (AI Agent Layer)

| Component | Technology | Rationale |
|---|---|---|
| **LLM** | Google Gemini 1.5 Pro (Vertex AI) | GCP-native; tool use support |
| **Fallback LLM** | GPT-4o (OpenAI API) | Redundancy for critical exam prep queries |
| **Embedding Model** | `text-embedding-004` (Vertex AI) | GCP-native; consistent dimensions |
| **Vector Store** | Vertex AI Matching Engine | Managed, scalable, no ops overhead |
| **Orchestration** | Custom agent framework (extending `orchestration/pipeline.py`) | Audit-friendly; avoids LangChain version drift |
| **Query Execution** | BigQuery Python client v3 | Existing `db/bigquery_client.py` |
| **Analytical Compute** | Pandas + Scikit-learn + NumPy | Existing dependency tree |
| **Session Memory** | Redis (GCP Memorystore) | Provisioned but unused in v1 — activated in v2 |
| **Audit Log** | Append-only BigQuery table (`audit.agent_query_log`) | Immutable, queryable, partitioned |
| **API Layer** | FastAPI (extending `decision-api/src/main.py`) | Consistent with platform |
| **Output: PDF** | ReportLab | Python-native |
| **Output: Excel** | openpyxl | Python-native |
| **Output: PPT** | python-pptx | Python-native |
| **Observability** | Google Cloud Logging + custom metrics | GCP-native |

---

## 5. 🚫 Anti-Hallucination Framework (REGULATORY-GRADE — NON-NEGOTIABLE)

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

| Layer | Enforcement Mechanism | Location |
|---|---|---|
| **Schema Grounding** | SQL generated only against registered schemas; schema injected at generation time | `QueryBuilderAgent` |
| **BQ Dry-Run Validation** | Every SQL query validated (zero bytes) before execution | `QueryBuilderAgent` |
| **Result Reconciliation** | AI narrative numbers must match query result set (deterministic check) | `ValidatorAgent` |
| **Source Citation Enforcement** | Every stated fact must carry `[Source: table.column \| Query: hash \| Date: timestamp]` | `ValidatorAgent` |
| **Confidence Scoring** | THREE tiers: HIGH / MEDIUM / LOW based on data completeness and statistical significance | `ValidatorAgent` |
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
| LLM response cannot be reconciled with data | Return data only; suppress narrative; log hallucination attempt to monitoring |
| Regulatory KB retrieval fails | Return data answer only; flag that regulatory framing is unavailable |

---

## 6. 🧭 Core Workflows

### 6.1 Workflow 1: AI-Assisted Decision Audit Review

```
User: "Show me decision #DEC-2026-00341 with full trace and compliance status"
  ↓ CoordinatorAgent → AuditGovernanceAgent
  ↓ DataRetrievalAgent: SELECT * FROM audit.decision_log WHERE decision_id = 'DEC-2026-00341'
    → Retrieves: application inputs, feature values, PD score, SHAP reason codes, override flag
  ↓ ValidatorAgent: verify all required fields present, flag missing reason codes
  ↓ ComplianceGateAgent: check Reg B reason code completeness, override justification
  ↓ FormatterAgent: structured decision trace + compliance flag summary (JSON + PDF)
  Output: Complete decision trace with compliance status — exportable as audit evidence
```

### 6.2 Workflow 2: Automated Audit Package Generation

```
User: "Generate the Q1 2026 regulatory audit package for CFPB examination"
  ↓ PlannerAgent: enumerate required artifacts per CFPB exam scope
  ↓ AuditGovernanceAgent:
    Step 1: Retrieve credit policy documents + change log (GCS)
    Step 2: Pull model inventory + validation status (MLflow)
    Step 3: Sample decision logs with input-output traceability (BigQuery)
    Step 4: Generate adverse action reason code compliance summary
    Step 5: Run fair lending analysis for examination period
    Step 6: Assemble data lineage documentation
  ↓ InsightGeneratorAgent: AI narrative for each section — grounded in retrieved data
  ↓ ValidatorAgent: every numerical claim reconciled to source query
  ↓ FormatterAgent: indexed PDF + Excel appendices
  Output: Examiner-ready package — self-documenting, version-stamped, ready for submission
```

### 6.3 Workflow 3: Natural Language Portfolio Question

```
User: "Why did our Q1 approval rate drop 8 points vs Q1 last year among thin-file applicants?"
  ↓ IntentClassifierAgent: Diagnostic | segment=thin-file | metric=approval_rate | Q1 YoY
  ↓ PlannerAgent: 4-step plan shown to user → user approves
  ↓ PortfolioAnalyticsAgent:
    Step 1: Approval rate by bureau_score_band — BigQuery YoY comparison
    Step 2: Reason code distribution — what drove additional declines?
    Step 3: Policy change log — were thin-file cutoffs changed?
    Step 4: Model score PSI — did score distribution shift?
  ↓ InsightGeneratorAgent: root cause decomposition
    → Policy change (cutoff adjustment) = 60% | Score drift = 30% | Bureau coverage = 10%
  ↓ RegulatoryInterpreterAgent: assess fair lending implications
  ↓ ValidatorAgent: confidence=HIGH (n=4,200 applications; all partitions present)
  ↓ FormatterAgent: Executive PDF + Excel workbook with raw data + charts
```

### 6.4 Workflow 4: Real-Time Compliance Alert Response

```
Trigger: Fair lending alert — approval rate disparity ratio drops below 0.80
  ↓ ComplianceGateAgent → FairLendingAgent
  ↓ DataRetrievalAgent: full disparate impact analysis for trigger segment
  ↓ InsightGeneratorAgent: AI summary — magnitude, affected segment, trend
  ↓ RegulatoryInterpreterAgent: cite ECOA/Reg B provision; generate response timeline
  Output: Alert to Compliance Officer queue with statistical summary, regulatory citation,
          recommended action checklist, and pre-populated corrective action memo template
```

---

## 7. 📦 Audit Package Structure (Output)

### 7.1 Governance Artifacts
- Credit policy documents with effective date history (Git-versioned DSL)
- Policy change logs with committee approval chain
- Model risk inventory (MLflow-sourced: version, training date, champion/challenger status)
- SR 11-7 validation calendar with overdue flag indicators

### 7.2 Model Documentation
- Model Development Document (MDD) — auto-populated from MLflow metadata + training artifacts
- Independent validation summary (uploaded reports linked to model version)
- Model performance trend (AUC, KS, Gini, PSI over trailing 12 months)
- SHAP importance charts by decision outcomes

### 7.3 Decision Evidence
- Stratified random sample of decision logs (configurable sample size, risk tier distribution)
- Input-output traceability per sampled decision (feature vector → model → rules → output)
- SHAP reason codes mapped to Reg B adverse action notices
- Override register (decision ID, original recommendation, justification, approver, date)

### 7.4 Fair Lending Analysis
- Disparate impact testing across protected class proxies (BISG methodology)
- Segment-level approval rate comparison (risk tier, geography, product, channel)
- Pricing disparity analysis (APR and limit assignments)
- AI-generated plain-language fair lending narrative suitable for exam response

### 7.5 AI Agent Audit Appendix *(New in v2.0)*
- Complete log of AI queries submitted during the audit period
- SQL queries executed, row counts returned, confidence scores
- **Full code artifacts per answer**: exact `.sql` and `.py` files executed — independently runnable against BigQuery to reproduce every stated metric
- **BigQuery job IDs** for every executed query (verifiable in GCP audit log)
- Narrative-to-data reconciliation table (every AI-stated number linked to source query and the specific code line that computed it)
- Agent session logs (user ID, timestamp, query, plan, output hash)
- Code artifact GCS URIs with SHA-256 content hashes for tamper detection

### 7.6 Data & System Documentation
- Data lineage diagrams (ingestion → feature engineering → decisioning → BigQuery)
- Architecture reference with version tag
- Data dictionary (BigQuery schema with column descriptions and PII classification)

---

## 8. ⚠️ Compliance Rules Engine

### 8.1 Rule Categories

| Category | Regulatory Authority | Example Rules |
|---|---|---|
| Fair lending | ECOA / Reg B | Approval rate disparity ratio ≥ 0.80; no prohibited bases in decisioning |
| Adverse action | ECOA / Reg B | Every decline/counter-offer must have valid principal reason codes (max 4) |
| UDAAP | CFPB | No deceptive practices in pricing or limit assignment |
| Model risk | SR 11-7 / OCC 2011-12 | Models must have independent validation within 12 months of champion deployment |
| Data integrity | Internal / FFIEC | All input fields must have documented provenance; no post-hoc data modification |
| Override governance | Internal | All overrides require documented justification + second-level approver |
| MLA | Military Lending Act | MAPR ≤ 36% for covered borrowers; MLA status verified at origination |
| AI agent outputs | SR 11-7 (AI/ML extension) | Every AI-generated insight must be auditable and linked to source data |

### 8.2 Rule Enforcement Points

| Rule | Enforcement Point | System Component |
|---|---|---|
| Reason code completeness | Decision creation + batch audit | `audit/logger.py` + nightly compliance scan |
| Override justification | Override API endpoint | `decision-api/src/main.py` — mandatory field validation |
| Model validation currency | Daily model health check | `ModelRiskAgent` + MLflow query |
| Prohibited variable use | Pre-query PII/ECOA guard | `ComplianceGateAgent` |
| AI output auditability | Every agent session | `ValidatorAgent` + `audit.agent_query_log` |
| Fair lending threshold | Nightly batch + real-time | `FairLendingAgent` + alert queue |

---

## 9. 📊 Metrics & KPIs

### 9.1 Platform Audit Metrics

| Metric | Definition | Target |
|---|---|---|
| Decision traceability rate | % decisions with complete input-model-rule-output trace | 100% |
| Reason code completeness | % decline decisions with valid Reg B reason codes | ≥ 99.5% |
| Override documentation rate | % overrides with justification + approver chain | 100% |
| Audit readiness score | Composite 0–100 (traceability + reason codes + model validation + fair lending) | ≥ 90 |
| Exam prep time reduction | Hours saved vs. manual preparation benchmark | ≥ 70% reduction |

### 9.2 Model Risk Metrics

| Metric | Definition | Alert Threshold |
|---|---|---|
| AUC performance | Area under ROC curve vs. validation baseline | < 0.05 absolute decline |
| Gini coefficient | Gini = 2 × AUC − 1 | < 0.05 absolute decline |
| KS statistic | Maximum separation between score distributions | < 0.05 absolute decline |
| PSI (score output) | Population stability index on score distribution | > 0.20 = high instability |
| PSI (features) | PSI per input feature vs. training distribution | > 0.25 per feature |
| Validation overdue | Days since last independent validation | > 375 days = non-compliant |

### 9.3 Fair Lending Metrics

| Metric | Definition | Threshold |
|---|---|---|
| Adverse impact ratio | Minority approval rate ÷ majority approval rate | < 0.80 = potential disparate impact |
| Pricing disparity | Mean APR difference between matched pairs by protected class proxy | > 25 bps = investigation |
| Limit disparity | Mean credit limit difference, controlled for risk tier | > 5% = investigation |

### 9.4 AI Agent Performance Metrics *(New in v2.0)*

| Metric | Definition | Target |
|---|---|---|
| Hallucination rate | % of AI outputs where a stated fact cannot be reconciled to source data | 0% |
| Query success rate | % of user queries producing a validated, data-backed answer | ≥ 95% |
| Plan approval rate | % of AI plans approved without modification | ≥ 80% |
| Time to insight | Median: query submission → validated output delivery | < 30 seconds |
| HIGH confidence rate | % of outputs at HIGH confidence tier | ≥ 70% |
| **Code artifact coverage** | **% of AI analysis answers that include at least one surfaced SQL or Python artifact** | **100%** |
| **Code reproduction rate** | **% of surfaced code that, when independently executed, produces the same result as the AI answer (sampled monthly)** | **≥ 99%** |
| User adoption | % of target roles using AI agent weekly (3 months post-launch) | ≥ 70% |

---

## 10. 🧱 Data Model (High-Level)

### 10.1 Core Entities

| Entity | Storage | Key Fields |
|---|---|---|
| `Application` | BigQuery: `originations.applications` | application_id, applicant_id_hash, bureau_score_band, product_type, channel, application_date |
| `Decision` | BigQuery: `audit.decision_log` | decision_id, application_id, outcome, credit_limit, apr, pd_score, fraud_score, policy_version, decision_timestamp |
| `ReasonCode` | BigQuery: `audit.adverse_action_reasons` | decision_id, reason_code, reason_text, rank, is_reg_b_compliant |
| `FeatureVector` | BigQuery: `audit.feature_snapshots` | decision_id, feature_name, feature_value, feature_source, shap_value |
| `Model` | MLflow registry | model_id, version, algorithm, training_date, champion_flag, validation_date, auc, gini, ks |
| `Policy` | GCS + Git: `policy_dsl/versions/` | policy_id, version, effective_date, rules_ast, approver_id, change_summary |
| `Override` | BigQuery: `audit.override_log` | override_id, decision_id, original_outcome, override_outcome, justification, approver_id, timestamp |
| `ComplianceEvent` | BigQuery: `compliance.events` | event_id, source_system, rule_id, result, applicant_id_hash, decision_id, timestamp |
| `AuditPackage` | GCS: `audit-packages/` | package_id, period, scope, generation_timestamp, contents_manifest |
| `AgentSession` | BigQuery: `audit.agent_query_log` | session_id, user_id, query_text, plan, sql_hash, result_row_count, confidence_score, output_type, timestamp, **code_artifact_uris (ARRAY<STRING>)**, **bq_job_ids (ARRAY<STRING>)**, **code_zip_uri** |

### 10.2 Key Relationships

```
Application ──→ Decision
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
  ReasonCode  FeatureVector  Override
                   │
        ┌──────────┼──────────┐
        ▼          ▼          ▼
  Model(version) Policy(version) ComplianceEvent
        │
        ▼
  ValidationReport (MLflow artifact)

AgentSession ──→ Decision (queried)
AgentSession ──→ AuditPackage (generated)
AuditPackage ──→ [all entities] (referenced)
```

---

## 11. 🔌 Integration Requirements

### 11.1 Upstream Systems

| System | Integration Type | Data Provided |
|---|---|---|
| Loan Origination System (LOS) | REST API `POST /v1/decisions/single` | Application data → decision + reason codes |
| Credit Bureau APIs | Existing integration via LOS | Bureau tradeline data, scores |
| Decision Engine (`decision-api/`) | Internal service — existing | Real-time decisioning with SHAP output |
| MLflow artifact store | Python API | Model versions, metrics, validation artifacts |
| Google Cloud Storage | GCS Python client | Policy documents, audit packages |
| BigQuery | BigQuery Python client v3 | All analytical data, audit logs, monitoring |

### 11.2 Downstream Outputs

| Output | Consumer | Format |
|---|---|---|
| Regulatory audit packages | CFPB / OCC / Federal Reserve examiners | PDF (indexed, version-stamped) |
| Adverse action data | Internal audit, compliance | Excel / JSON |
| Fair lending reports | Compliance officer, legal | PDF + Excel |
| Model risk reports | Model risk managers, validators | PDF + JSON |
| AI insight briefs | Risk committee, executive leadership | PDF / PowerPoint |
| API responses | LOS, downstream BI tools | JSON (structured insight objects) |

---

## 12. 🔐 Security & Governance

### 12.1 Authentication & Authorization
- **RBAC**: Four roles: `compliance_officer`, `model_risk_manager`, `internal_audit`, `executive_read_only` — enforced via GCP IAM + JWT claims
- **AI Agent RBAC**: Role-specific query permissions (`internal_audit` cannot query raw PII; `executive_read_only` receives summary outputs only)
- **Service Account Isolation**: AI agent execution uses dedicated read-only BigQuery SA — no write access to production tables

### 12.2 Data Protection
- **PII masking**: `applicant_id_hash` used throughout (SHA-256 salted); raw PII never in audit logs or AI agent logs
- **Data encryption**: At rest (GCP CMEK) and in transit (TLS 1.3)
- **Prohibited variable guard**: ECOA-prohibited variables blocked at AI agent query layer via `ComplianceGateAgent`
- **Data residency**: All data remains in designated GCP region (us-central1)

### 12.3 AI Governance
- **LLM version pinning**: Gemini model version pinned per deployment; version change requires change management approval
- **Prompt versioning**: All system prompts version-controlled in Git with approver chain
- **Hallucination monitoring**: ValidatorAgent logs every reconciliation check; hallucination rate dashboarded and alerted
- **Human-in-the-loop gate**: Exam package generation requires human approval before final export

### 12.4 Immutability & Non-Repudiation
- Decision logs and compliance events: append-only BigQuery tables (no UPDATE/DELETE)
- Audit packages carry SHA-256 content hash at generation — tampering detectable
- Agent session logs are append-only — AI answers cannot be retroactively modified

---

## 13. 🖥️ UX Requirements (Command Center)

### 13.1 Dashboard — Primary View

| Element | Description |
|---|---|
| **Audit Readiness Score** | 0–100 composite gauge — prominent above the fold |
| **Active Compliance Flags** | Count + severity (Critical / High / Medium) with one-click drill-down |
| **Model Health Indicators** | Per-model: health score + drift status + validation currency |
| **Fair Lending Alerts** | Active threshold breaches with regulatory citation |
| **AI Agent Query Bar** | Natural language input — "Ask anything about your portfolio" |
| **Recent AI Insights** | Last 5 outputs with confidence score and one-click re-run |

### 13.2 AI Agent Chat Interface
- Enterprise chat aesthetic (not consumer chatbot)
- Plan display: step-by-step analysis plan shown before execution (expandable)
- Source citation panel: data source citations collapsed by default (expandable)
- Confidence badge: HIGH / MEDIUM / LOW on every response
- **"Show Code" panel (collapsed by default, always present):**
  - Syntax-highlighted SQL code block(s) — one per query step
  - Syntax-highlighted Python code block for all post-query computation
  - **[Copy SQL]** button — one-click to clipboard
  - **[Run in BQ Console]** button — opens BigQuery Console pre-populated with the query
  - **[Copy Python]** button
  - **[Export as Notebook (.ipynb)]** button — wraps SQL + Python into a Jupyter notebook
  - **[Download All Code (.zip)]** — `.sql` + `.py` + metadata JSON in a single archive
  - BigQuery Job ID displayed for every executed query (links to GCP console entry)
- Export bar: one-click export of any response to PDF / Excel / PPT (code always included)
- "Why did you say that?" — expandable audit trail showing data AND code behind any stated fact

### 13.3 Key Action Buttons
- **"Generate Audit Package"** — period/scope selector → triggers Workflow 2
- **"View Decision Trace"** — decision ID lookup with full trace visualization
- **"Run Fair Lending Analysis"** — launches FairLendingAgent with period selector
- **"Check Model Health"** — triggers ModelRiskAgent dashboard refresh
- **"Ask the AI"** — opens AI agent query interface

---

## 14. 🚀 MVP Scope (Phase 1)

### Platform Must Have
- Decision audit logs (complete trace via `audit/logger.py`)
- Basic compliance rules engine (Reg B reason codes, override documentation — `compliance/engine.py`)
- Audit package generator v1 (PDF with governance artifacts, decision samples, model docs)
- Model monitoring dashboard (AUC, KS, PSI from MLflow + BigQuery)

### AI Agent MVP (Phase 1 — Constrained Scope)
- Single-turn natural language queries on BigQuery portfolio data
- SQL generation + validation against registered schemas
- Basic confidence scoring (HIGH / LOW)
- Append-only audit log for all AI queries and outputs
- Anti-hallucination enforcement: schema grounding + result reconciliation
- **Code Transparency (Phase 1, non-negotiable)**: every answer surfaces the exact SQL executed and the Python computation — with [Copy] and [Download .zip] actions

### Out of Scope for Phase 1
- Multi-turn session memory (Phase 2)
- Excel / PPT output generation (Phase 2)
- Fair lending AI automation (Phase 2)
- Regulatory KB RAG (Phase 2)
- PowerPoint output (Phase 3)

---

## 15. 📈 Phased Roadmap

### Phase 1 — Foundation (Q2 2026)
- Decision audit engine + compliance rules engine (existing codebase hardened)
- Audit package generator v1 (PDF)
- Model monitoring dashboard (MLflow + BigQuery)
- AI Agent v1: single-turn SQL queries + schema-grounded answers + audit log

### Phase 2 — Intelligence Layer (Q3 2026)
- Multi-agent orchestration (full specialist agent routing)
- Multi-turn session memory (Redis — activate existing provisioned instance)
- Fair lending automation (FairLendingAgent + BISG proxy testing)
- Regulatory KB (Vertex AI RAG over SR 11-7, ECOA, UDAAP text)
- Excel + PDF output generation
- Scenario simulation (policy/model change impact modeling)

### Phase 3 — Advanced Governance (Q4 2026)
- Real-time decision interception with compliance gate
- Regulator portal (read-only access with pre-packaged views)
- Advanced AI analytics (ML-powered portfolio insights, anomaly detection)
- PowerPoint generation
- AI agent governance artifacts (model card per SR 11-7 AI/ML extension)

### Phase 4 — Autonomous Decision Support (Q1 2027)
- Cross-client benchmarking (anonymized peer comparison)
- AI audit assistant (interactive exam prep Q&A)
- Automated remediation recommendations with approval workflow
- Proactive compliance monitoring (predict regulatory findings before exam)

---

## 16. ✅ Success Criteria

| Criteria | Measurement | Target |
|---|---|---|
| Audit prep time reduction | Hours: manual benchmark vs. platform-generated package | ≥ 70% reduction |
| Decision traceability | % decisions with complete audit trail | 100% |
| Documentation gap findings | Regulatory findings related to documentation at first examination | Near zero |
| AI hallucination rate | % of AI outputs with unreconciled stated facts | 0% |
| Time to insight | Median: query submission → validated AI output | < 30 seconds |
| User adoption | % of target roles actively using AI agent weekly (3 months post-launch) | ≥ 70% |
| Query success rate | % of AI queries returning validated, data-backed answers | ≥ 95% |
| Override documentation compliance | % of overrides meeting full documentation requirements | 100% |
| Model validation currency | % of production models with current independent validation | 100% |
| Regulator confidence | Exam outcome: no MRAs related to data or documentation | Achieved at first examination |
| **Code artifact coverage** | **% of AI analysis answers with at least one surfaced, independently executable code artifact** | **100%** |
| **Code reproduction accuracy** | **% of code artifacts that reproduce the stated answer when independently executed (sampled monthly)** | **≥ 99%** |

---

## Appendix A — API Specifications (AI Agent Layer)

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
    "narrative": "Approval rates for thin-file applicants declined 8.2 percentage points...",
    "root_causes": [
      {"factor": "Policy cutoff change", "contribution_pct": 60, "evidence_query_id": "sql_001"},
      {"factor": "Score distribution shift (PSI=0.23)", "contribution_pct": 30, "evidence_query_id": "sql_002"}
    ],
    "confidence": "HIGH",
    "data_citations": [
      {"claim": "8.2 pp decline", "source_table": "audit.decision_log", "query_hash": "sha256:abc...", "row_count": 4200}
    ]
  },
  "code_artifacts": [
    {
      "step": 1,
      "type": "sql",
      "label": "Q1 YoY approval rate by bureau_score_band",
      "code": "SELECT DATE_TRUNC(decision_timestamp, QUARTER) AS qtr, bureau_score_band, COUNTIF(outcome = 'APPROVE') / COUNT(*) AS approval_rate FROM `project.audit.decision_log` WHERE product_type = 'credit_card' AND bureau_score_band = 'thin_file' AND decision_timestamp BETWEEN '2025-01-01' AND '2026-03-31' GROUP BY 1, 2",
      "bq_job_id": "bqjob_r75a4c9f2_00018e3b4e7b_1",
      "bytes_processed": 2189440,
      "row_count": 4200,
      "executed_at": "2026-04-15T09:32:11Z",
      "gcs_uri": "gs://gncda-code-artifacts/qry_20260415_001/step1.sql",
      "sha256": "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069"
    },
    {
      "step": 2,
      "type": "python",
      "label": "YoY delta computation and PSI calculation",
      "code": "import pandas as pd\nfrom scipy.stats import chi2_contingency\n# Q1 YoY approval rate comparison\nq1_2025 = df[df['qtr'] == '2025-01-01']['approval_rate'].iloc[0]\nq1_2026 = df[df['qtr'] == '2026-01-01']['approval_rate'].iloc[0]\ndelta_pp = (q1_2026 - q1_2025) * 100  # Result: -8.2",
      "gcs_uri": "gs://gncda-code-artifacts/qry_20260415_001/step2.py",
      "sha256": "3d7e9f2a1b4c8e5f6d0a2c9b7e4f1d3a8c5b2e9f7d4a1c6b3e8f5d2a9c7b4e"
    }
  ],
  "code_export_url": "gs://gncda-code-artifacts/qry_20260415_001/code_archive.zip",
  "outputs": {
    "pdf_url": "gs://gncda-outputs/qry_20260415_001.pdf",
    "excel_url": "gs://gncda-outputs/qry_20260415_001.xlsx"
  },
  "audit_log_id": "agent_log_20260415_001"
}
```

### `POST /api/v1/agent/audit-package`
```json
{
  "period_start": "2026-01-01",
  "period_end": "2026-03-31",
  "scope": ["governance_artifacts", "model_documentation", "decision_evidence", "fair_lending"],
  "exam_type": "CFPB_SUPERVISION",
  "require_approval": true
}
```

### `GET /api/v1/agent/sessions/{session_id}`
Full audit trail for an agent session — supports regulatory examination.

### `GET /api/v1/compliance/flags`
Active compliance flags with severity ranking.

### `GET /api/v1/models/health`
Model health scores and drift metrics for all production models.

---

## Appendix B — Risk & Mitigation Register

| Risk | Severity | Mitigation |
|---|---|---|
| AI generates hallucinated metric cited in exam response | Critical | ValidatorAgent reconciliation mandatory before output; LOW confidence outputs labeled "ESTIMATE ONLY — do not use in regulatory submissions" |
| Prohibited ECOA variable exposed in AI query | Critical | ComplianceGateAgent blocks prohibited columns at schema level |
| BigQuery data lag causes stale AI answer | High | Every output carries last-updated timestamp; staleness warning if data > 24h old |
| LLM model version change introduces regression | High | Model version pinned per deployment; regression test suite on LLM behavior required |
| Agent session logs insufficient for exam | High | Append-only `audit.agent_query_log`; 7-year retention |
| AI answer contradicts audit log | High | Deterministic reconciliation — AI numbers must match query results, not LLM memory |
| PII exposure in AI output | High | `applicant_id_hash` enforced; raw PII never in AI query scope |
| Redis session store failure | Medium | Stateless fallback (single-turn mode); session loss surfaced to user |
| Vertex AI RAG retrieves incorrect regulatory text | Medium | Regulatory KB versioned and compliance-reviewed before deployment |
| Fair lending AI analysis used as sole regulatory basis | Medium | Outputs labeled "analytical support only — compliance officer review required before regulatory submission" |
| Code artifact missing or inconsistent with AI answer | High | `FormatterAgent` blocks output delivery if `code_artifacts` array is empty; immutable capture at execution time prevents post-hoc reconstruction |
| User overwhelmed by technical code output | Low | Code panel collapsed by default; plain-language execution summary ("Queried 4,200 decisions over 2 quarters") shown first; full code available on demand |

---

*Document Owners: Product Engineering / Risk Technology / Compliance*
*Review Cadence: Quarterly or upon material regulatory change*
*Next Review: July 15, 2026*
