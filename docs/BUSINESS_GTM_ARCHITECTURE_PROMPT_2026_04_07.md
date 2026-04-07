# ENHANCED AI AGENT PROMPT — FULL BUSINESS & ARCHITECTURE DOCUMENTATION
## Credit Risk Platform ("`credit-risk-platform`") — B2B SaaS
> Generated: April 7, 2026 | Role: Senior Technical + Business Strategist AI Agent
>
> **Purpose:** Audit the `credit-risk-platform` codebase and produce five deliverables in one structured pass:
> 1. Technical Architecture Document
> 2. How-To-Do Manuals (three audiences)
> 3. Ideal Customer Profile (ICP)
> 4. Go-To-Market Strategy
> 5. Dual-Audience Pitch Deck (Users + Investors)

---

## MASTER CONTEXT YOU MUST ABSORB BEFORE GENERATING ANY OUTPUT

### What This System Is
A **governance-first, multi-agent credit risk platform** built on GCP for B2B deployment to banks, fintechs, and SMB lenders. It is being positioned as a SaaS product (see `docs/BUSINESS_ASSETS_2026.md` and `docs/CORE_PLATFORM_TECH_AUDIT_2026_04_07.md`).

### Runtime Architecture (as built, not aspirational)
- **Two decisioning paths exist in parallel** — this is a critical technical debt issue, not a feature:
  - Path A: `decision-api/src/main.py` → `feature_pipeline/features.py` → `decision_engine/engine.py` → `audit/logger.py`
  - Path B: `orchestration/pipeline.py` → `agents/feature_engineering_agent.py` → `agents/risk_modeling_agent.py` → `agents/decision_engine_agent.py` → `agents/bq_writer_agent.py`
- **Data stores**: SQLite/Postgres (audit), BigQuery (analytics sink), GCS (raw), Redis (provisioned but unused)
- **APIs**: FastAPI (Decision API on Cloud Run), FastAPI (Ingestion API on Cloud Run)
- **UIs**: Two Next.js apps + Streamlit dashboard (currently mock-data)
- **Models**: XGBoost (credit scoring), Isolation Forest (fraud), joblib serialization, MLflow registry
- **Key missing production capabilities**: tenant isolation, safe policy DSL, model artifact versioning per-tenant, PIT replay, rate limiting

### Tech Stack (confirmed from repo)
`Python 3.11+ / FastAPI / SQLAlchemy async / Pydantic v2 / pandas / XGBoost / SHAP / MLflow / Google Cloud (Run, GCS, Pub/Sub, BigQuery, Vertex AI) / Redis / Docker / Alembic / Next.js / Streamlit / dbt`

### Active Technical Debt to Reference in Architecture Docs
1. `eval()` used in `agents/decision_engine_agent.py` for YAML policy rules — security risk
2. No `tenant_id` in any schema, audit log, or BQ table — multi-tenancy is absent
3. Duplicate feature + policy engines — will produce divergent decisions by channel
4. Models loaded per-request in agent path — p99 latency spike risk
5. Ingestion API performs GCS + Pub/Sub I/O synchronously in async event loop — blocking
6. Redis provisioned but unused — rate limiting + idempotency missing
7. Streamlit dashboard uses mock data — not connected to production stores

---

## DELIVERABLE 1 — TECHNICAL ARCHITECTURE DOCUMENT

**Output file**: `docs/TECHNICAL_ARCHITECTURE.md`

### Instructions for the Agent

Produce a structured **Technical Architecture Reference** that a new engineering hire or a technical due-diligence reviewer can read to fully understand the system. It must reflect reality (what `exists`) and flag delta to the target state (what `must become`).

#### Section structure you must output:

```
1. Executive Summary (2 paragraphs: what this system does, who it serves)
2. System Topology Diagram (Mermaid C4 context + container diagram)
3. Component Inventory (table: component, language/framework, entry point file, role, production-ready Y/N)
4. Data Flow Diagrams
   4a. Online Decisioning Flow (request → response with every hop named)
   4b. Batch/Offline Pipeline Flow
   4c. Audit & Replay Flow
5. API Surface Inventory (table: API, method, path, auth mechanism, tenant scoped Y/N, idempotent Y/N)
6. Storage Architecture (table: store, technology, role, partitioned Y/N, tenant-isolated Y/N, PIT-correct Y/N)
7. Security Architecture (auth, JWT claims, secret management, eval() risk, multi-tenant boundary gaps)
8. Critical Technical Debt Register (severity, location, business risk, remediation prompt reference)
9. Future-State Target Architecture
   9a. Canonical Domain Package (`credit_core`) — single brain for all decisioning
   9b. Tenant Control Plane (metadata, JWT, config registry, quotas)
   9c. Decision Plane (stateless API + shared credit_core + append-only audit)
   9d. Data Plane (ingestion → event bus → warehouse → PIT feature views → online store)
   9e. Monitoring Plane (drift, fairness, alerts)
10. Engineering Standards & CI Gates Required
    - Golden test: Decision API == agent pipeline output for identical input
    - OpenTelemetry trace coverage
    - Contract tests across service boundaries
    - Alembic migration gate in CI
    - PIT correctness assertion in test suite
```

#### Technical depth requirements:
- Generate Mermaid diagrams for sections 2, 4a, 4b, 4c, and 9
- For every component marked "production-ready: NO", write a one-line remediation note
- Include the exact file paths from the repo for every claim made (no invented paths)
- The Critical Technical Debt Register must cross-reference `docs/IMPLEMENTATION_PLAN_CORE_PLATFORM_2026_04_07.md` prompt IDs (P0.1, P0.2, P0.3, P1.x, P2.x, P3.x)

---

## DELIVERABLE 2 — HOW-TO-DO MANUALS (THREE AUDIENCES)

### 2A — Developer Onboarding Manual

**Output file**: `docs/manuals/DEVELOPER_ONBOARDING.md`

Audience: A new backend engineer joining the platform team. Zero prior knowledge of the codebase.

#### Sections required:

```
1. Local Development Setup
   - Prerequisites (Python 3.11+, Docker, gcloud CLI, make)
   - Clone, virtualenv, pip install -r requirements.txt
   - Docker Compose up (which services start, what ports)
   - Environment variables required (table: var name, purpose, where to get it, safe default for local)
   - Running the Decision API locally (exact curl example with payload)
   - Running the agent pipeline locally (exact Python command)
   - Running tests (pytest commands, expected output)
2. Codebase Navigation Guide
   - Directory map with one-line purpose per top-level folder
   - "Start here for X" quick-reference table (e.g., "add a new feature" → start at credit_core/features.py)
   - Where NOT to add code (dual-engine duplication anti-pattern — explain why)
3. Making Your First Contribution
   - How to add a new credit feature (step-by-step: feature function → contract → test → golden test update)
   - How to add a new policy rule (safe DSL only — reference P0.3)
   - How to add a new API endpoint (Decision API pattern: route → schema → service → audit)
4. Testing Philosophy
   - Unit test locations and conventions
   - Golden test: `tests/test_decision_parity.py` (what it asserts and why it must not be bypassed)
   - Tenant isolation test: `tests/audit/test_tenant_isolation.py`
5. Common Pitfalls
   - Do NOT use eval() for any conditional logic
   - Do NOT call joblib.load() inside a request handler
   - Do NOT write to audit log without tenant_id after P0.1 is merged
   - Do NOT add logic to agents/*_agent.py that duplicates credit_core
6. Deployment
   - Cloud Run deployment commands
   - Environment vars in Secret Manager
   - BigQuery table creation (from db/bigquery_schema.py)
   - MLflow model registration workflow
```

---

### 2B — Compliance Officer / Model Risk Manager Manual

**Output file**: `docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md`

Audience: A non-engineering compliance officer, model risk manager, or OCC/CFPB examiner reviewing the platform for SR 11-7, ECOA/Reg B, HMDA, and CECL/IFRS 9 compliance.

#### Sections required:

```
1. Platform Governance Overview
   - What decisions are made by the platform vs. human override
   - Where human-in-the-loop override is logged and traceable
   - Audit log schema (fields, immutability guarantees, retention)
2. Model Inventory
   - Table: model name, purpose, algorithm, training data type, version, monitoring status
   - Where model artifacts are stored and versioned (MLflow)
   - Model validation workflow: train → validate → approve → production bind → monitor → retrain trigger
3. SR 11-7 Compliance Checklist
   - Model risk management governance: policy owner, change control, documentation
   - Validation independence: how the platform separates development vs. validation artifacts
   - Ongoing monitoring: drift detection triggers, fair lending checks, performance thresholds
   - Audit artifact auto-generation: what gets produced, when, and where it is stored
4. CFPB Reg B (Adverse Action) Compliance
   - How the platform generates adverse action reason codes
   - SHAP explainability layer: what it produces, how to interpret outputs
   - Adverse action notice requirements: what the platform generates vs. what must be added downstream
5. Fair Lending (ECOA / HMDA)
   - Fairness check scripts: `scripts/run_fairness_check.py` (what it tests, interpretation guide)
   - Disparate impact detection: what metrics are tracked, what thresholds trigger alerts
   - HMDA field mapping: `compliance/` module — what fields are extracted and in what format
6. Audit Workflow
   - How to retrieve a complete audit record for a single application
   - How to generate a model monitoring report (command, output format, interpretation)
   - How to export a full audit package for regulatory examination
   - One-click audit package generation: what files are included, how to validate completeness
7. Policy Change Governance
   - How credit policy changes are proposed, versioned, approved, and documented
   - Champion/challenger test framework: how A/B tests are set up, measured, and concluded
   - Rollback procedure: how to revert to a previous policy version with audit trail
8. Known Gaps and Remediation Timeline
   - eval()-based rules (being replaced by safe DSL — reference P0.3)
   - Tenant isolation not yet enforced in audit log (reference P0.1, target date)
   - Deterministic replay not yet implemented (reference P3.1, target date)
```

---

### 2C — Customer Integration Manual (External API User)

**Output file**: `docs/manuals/CUSTOMER_INTEGRATION_GUIDE.md`

Audience: A fintech or bank engineering team integrating the platform's Decision API into their loan origination system.

#### Sections required:

```
1. Integration Overview
   - Architecture: how the Decision API sits in a lending origination flow
   - Authentication: JWT token acquisition, tenant_id claim requirement, token refresh
   - Rate limits and idempotency: limits by tier, Idempotency-Key header usage
2. API Reference
   - POST /v1/decisions/single: full request schema (all fields with type, required/optional, description), response schema, error codes
   - POST /v1/decisions/batch: same treatment
   - GET /v1/audit/{application_id}: what is returned, access control rules
   - POST /v1/ingestion/batch: ingestion API reference
3. Request / Response Examples
   - Curl examples for each endpoint
   - Python SDK example (using httpx/requests)
   - Webhook notification format (if applicable)
4. Field Mapping Guide
   - Table: platform field name → description → accepted values → validation rule
   - Common field name mismatches to avoid (existing_debt vs existing_debt_amount, dti vs debt_to_income_ratio)
5. Decision Output Interpretation
   - Decision codes: APPROVE, DECLINE, REFER — meaning and recommended downstream action
   - Reason codes: list, numeric codes, plain-language descriptions, Reg B adverse action mapping
   - Confidence scores: how to interpret PD (probability of default), fraud score, risk tier
   - SHAP explanation output: how to surface to human reviewers
6. Error Handling
   - HTTP error codes and retry guidance (table: code, meaning, safe to retry?, backoff recommendation)
   - Validation error format (Pydantic error structure)
7. Sandbox Environment
   - Sandbox base URL
   - Pre-loaded test tenant credentials
   - Synthetic applicant payloads for each decision outcome (APPROVE, DECLINE, REFER)
8. Production Checklist
   - Confirm tenant_id in all JWT tokens
   - Idempotency-Key required for all decision requests
   - mTLS or VPN tunnel for on-prem customers
   - Audit record retention SLA agreement
   - Adverse action notice generation agreement confirmed
```

---

## DELIVERABLE 3 — IDEAL CUSTOMER PROFILE (ICP)

**Output file**: `docs/go_to_market/IDEAL_CUSTOMER_PROFILE.md`

### Instructions for the Agent

Produce a detailed B2B ICP document using the following dimensions. Ground every claim in the platform's real capabilities as documented in the codebase and existing business assets. Do not fabricate capabilities the platform does not have.

#### Section structure you must output:

```
1. ICP Summary Card
   - One sentence company description
   - Target buyer: title, function, reporting line
   - Target user: title, function, day-to-day workflow
   - Deal size range: $ARR low / high
   - Sales cycle estimate: days
   - "They are ready to buy if..." (3 sentences max)

2. Primary ICP Segment — Fintech Lender ($100M–$2B AUM)
   Firmographic signals:
   - AUM range: $100M–$2B in active loan book
   - Product types: consumer credit card, personal loans, BNPL, SMB working capital
   - Regulatory status: licensed lender, CFPB-supervised, state chartered
   - Headcount: 50–500 employees
   - Technology maturity: modern data stack (Snowflake/BigQuery/dbt) OR legacy (Excel/SAS) — both are buyers

   Technographic signals:
   - Uses nCino, Blend, or custom-built LOS
   - Has an existing MLflow or SageMaker model registry (signal: sophisticated team)
   - OR: still scores applicants using a vendor scorecard they can't explain (signal: immediate governance pain)
   - Pub/Sub or Kafka event bus in place

   Psychographic signals (buyer motivations):
   - "Our model monitoring is a spreadsheet that someone updates on Fridays"
   - "We had an OCC exam and the model documentation took 6 weeks to assemble"
   - "We're doing champion/challenger but there's no structured approval record"
   - "We have SHAP outputs but they're in a notebook, not a workflow"

   Anti-ICP signals (disqualify):
   - <$50M AUM (ROI math doesn't work)
   - No dedicated risk analytics team (no champion)
   - Already deployed a full Moody's or FICO Enterprise contract in the last 12 months
   - CRO reports to CFO and has no engineering relationship (procurement will block)

   Champion profile:
   - Title: Head of Credit Risk, VP Decision Science, Director of Risk Analytics
   - Day-to-day: builds scorecard models, monitors portfolio, prepares board reporting
   - KPIs they own: approval rates, bad rate, model AUC/KS, fair lending metrics, audit findings
   - Their CEO/CRO says: "we need to be audit-ready by Q3"

   Economic buyer:
   - Title: CRO, Chief Credit Officer, VP Risk
   - Signs: $120K–$350K ARR contracts
   - Budget source: risk technology, compliance, or data platform line items

3. Secondary ICP Segment — Regional Bank / Credit Union ($1B–$15B AUM)
   [Repeat same dimension structure as Segment 1 but adjusted for regulated institution dynamics]
   - Longer sales cycles (90–120 days)
   - Governance/compliance urgency is primary entry point, not analytics
   - Champion: CRO + Chief Compliance Officer together
   - IT procurement involved earlier
   - Key differentiator for this segment: regulatory exam readiness, SR 11-7 alignment

4. Tertiary ICP Segment — NBFC / International Lender (India, UK, Southeast Asia)
   [Brief segment treatment]
   - Regulatory analog: RBI model governance guidelines, FCA SREP, MAS TRM
   - Typically less legacy baggage → faster implementation
   - Entry product: portfolio analytics + governance layer

5. Negative ICP (Account Disqualification Criteria)
   - Tier 1 banks ($100B+ AUM): procurement cycles 18–24 months, require on-prem, out of scope for Seed stage
   - Pure insurance or wealth management (no credit decision flow)
   - Organizations with no risk analytics function at all (no champion)
   - Organizations already in an 18-month implementation with a competitor

6. ICP-to-Platform Capability Mapping (table)
   - Column 1: ICP Pain
   - Column 2: Platform capability that solves it (with file/module reference)
   - Column 3: Time-to-demonstrate value (live demo, POC, or production)

7. Buying Triggers (External Events That Accelerate Purchase)
   - OCC / CFPB exam scheduled in next 90 days
   - Basel IV or CECL implementation underway
   - Recent model failure, MRM finding, or enforcement action
   - New CRO or Head of Credit hired in past 6 months
   - Series B/C fundraise requiring institutional-grade risk infrastructure
   - Expansion into new product type (e.g., launching BNPL, entering SMB lending)
```

---

## DELIVERABLE 4 — GO-TO-MARKET STRATEGY

**Output file**: `docs/go_to_market/GTM_STRATEGY.md`

### Instructions for the Agent

Produce a concrete, phased GTM playbook. Every recommendation must be grounded in the platform's actual capabilities and current stage (pre-revenue / early Seed). Do not recommend tactics that require sales infrastructure that doesn't yet exist.

#### Section structure you must output:

```
1. GTM Philosophy
   - Land on a specific critical pain → prove ROI fast → expand modules
   - Beachhead: governance audit pain (SR 11-7, CECL, Reg B) → Originations Intelligence → Portfolio Analytics → P&L Engine
   - "Don't try to replace everything. Be the governance layer that sits between what they have and what regulators want."

2. Phase 1 — Beachhead (Months 0–12)
   Target segment: Fintech lenders + forward-thinking credit unions

   Go-to-market motion:
   - Founder-led sales (CEO/CTO as primary AEs — know the buyer's language)
   - Outbound: LinkedIn + conference
   - Entry product: Core Platform (Decision API + Governance Layer)
   - Target: 6–10 paying customers, $0.8M ARR

   Channel 1: Direct Outbound
   - Target list: 200 fintech lenders from CFPB supervised list + FDIC call reports
   - Personas: Head of Credit Risk, VP Decision Science (not IT)
   - Message: governance + explainability pain (reference LinkedIn sequences in BUSINESS_ASSETS_2026.md)
   - Sequence: 3-touch LinkedIn → demo → pilot agreement → paid contract

   Channel 2: Conference Presence
   - GARP (Global Association of Risk Professionals) conferences
   - RMA (Risk Management Association) annual conference
   - LendIt / Fintech Nexus: fintech lender buyer concentration
   - American Bankers Association risk management events
   - Tactic: attend, present a 20-min session on "AI governance in credit decisioning", collect leads

   Channel 3: Content / Thought Leadership
   - Publish: "Model Governance Benchmark Report" (use platform's synthetic data runs + industry stats)
   - Publish: "SR 11-7 Compliance Readiness Diagnostic" (downloadable self-assessment)
   - Distribute via LinkedIn newsletter, GARP/RMA member groups, direct email
   - Goal: 500 email subscribers by Month 6 who are in the ICP

   Pilot Playbook:
   - 30-day paid or co-investment pilot: $5K–$15K pilot fee applied to Year 1 contract
   - Pilot success criteria: governance layer live, first audit package generated, decision API integrated with sandbox LOS
   - Convert to annual contract at $120K–$350K ARR

3. Phase 2 — Expansion (Months 12–30)
   Target segment: Regional banks ($1B–$10B AUM) + enterprise credit unions

   Sales motion shift:
   - Hire 2 enterprise AEs with bank risk technology backgrounds
   - Add Customer Success to drive module expansion in existing accounts
   - Entry product: Governance Layer (direct compliance pain → fastest time-to-value)
   - Secondary upsell: Portfolio Analytics + P&L Engine

   Channel additions:
   - Core banking / LOS partnerships (nCino, Temenos, Jack Henry referral)
   - Big 4 consulting firm partnerships (model validation teams recommend platform to clients)
   - Regulatory consultant channel: ex-OCC/CFPB consultants who work with mid-market banks

   Pricing for this segment: $180K–$500K ARR (larger orgs, more modules)

   Net Revenue Retention target: 115%+ via module expansion

4. Phase 3 — Scale (Months 30–60)
   - Series A-funded growth; dedicated sales team
   - International expansion: UK (FCA), India (RBI), Southeast Asia (MAS)
   - Add integration marketplace: build connectors for top 5 core banking systems
   - Product-led growth layer: freemium model risk self-assessment tool driving inbound

5. Competitive Moats to Build Now
   - Data network effect: governance artifacts + anonymized performance benchmarks → industry benchmarking product
   - Domain data model lock-in: 180+ pre-mapped credit risk fields → switching cost after integration
   - Regulatory artifact IP: patent-pending automated governance documentation generation
   - Advisor moat: ex-OCC examiner advising → credibility with bank compliance buyers

6. Pricing & Packaging Strategy
   Tiers (reference BUSINESS_ASSETS_2026.md Slide 7 and extend):

   | Tier | Entry Price/Year | Modules Included | Target Segment |
   |---|---|---|---|
   | **Starter** | $60K | Decision API + Governance Layer | Early fintech (<$200M AUM) |
   | **Growth** | $150K | + Portfolio Analytics + Originations Intelligence | Fintech $200M–$2B |
   | **Enterprise** | $300K–$600K | Full platform + custom integrations + dedicated CSM | Regional banks, large credit unions |
   | **Platform API** | Usage-based | Decision API only, per-call pricing | LOS vendors integrating as white-label |

   Usage overages: $0.05/decision above plan limit; $500/audit package export above plan limit
   Professional services: $2,500/day for custom integration, model validation support, onboarding

7. Partnership Strategy
   Core banking referral partners:
   - nCino: LOS for bank and credit union segment; API integration → co-sell from nCino marketplace
   - Temenos: Global core banking; connector enables EU/Asia expansion
   - Jack Henry: Community bank / credit union core banking; referral channel

   Data enrichment partners:
   - Plaid / MX / Finicity: open banking transaction data → enriches feature pipeline
   - Experian / Equifax / TransUnion API integration: traditional bureau data connector

   Compliance/advisory partners:
   - Big 4 model validation teams (Deloitte, PwC, EY, KPMG): refer platform to clients who need governance tooling
   - Ex-regulatory consultant networks: RMA, GARP certified member firms

8. Sales Funnel Metrics & Targets (Year 1)
   | Stage | Target | Conversion |
   |---|---|---|
   | Outbound contacts | 200/month | — |
   | Demo requests | 20/month | 10% |
   | Active pilots | 8 | 40% of demos |
   | Closed contracts | 6 | 75% of pilots |
   | Average ARR | $130K | — |
   | Year 1 ARR | $780K | — |

9. Key Metrics to Track (GTM KPIs)
   - Time-to-first-demo (from outbound contact)
   - Time-to-pilot (from demo)
   - Pilot conversion rate
   - Time-to-value in pilot (days to first audit package generated)
   - Net Revenue Retention at 12 months
   - CAC by channel
   - Payback period
```

---

## DELIVERABLE 5 — PITCH DECK (DUAL AUDIENCE)

### 5A — Investor Pitch Deck

**Output file**: `docs/pitch/INVESTOR_PITCH_DECK.md`

### Instructions for the Agent

Produce a complete investor pitch deck in markdown format. This extends and deepens `docs/BUSINESS_ASSETS_2026.md` Slides 1–13 using the current technical audit and GTM strategy. Every slide must be production-quality — ready for a VC partner meeting.

#### Slide-by-slide requirements:

```
SLIDE 1 — Cover
- Platform name + positioning tagline
- Round details: Seed, raising $3.5M
- Contact

SLIDE 2 — The Problem (ENHANCED)
- Lead with regulatory cost data (Basel IV, SR 11-7, CFPB Reg B, CECL/IFRS 9)
- Quantify: average remediation cost per OCC finding, manual audit hours, approval rate leakage %
- Visual: "Timeline of the compliance burden explosion 2010–2026 (+340%)"
- Include the operational reality: tool sprawl (Excel, SAS, Tableau, SharePoint = no single source of truth)
- Close with: "The tooling hasn't caught up. We're changing that."

SLIDE 3 — Current Solutions and Why They Fail
- Table: Legacy SAS/FICO | Build-in-house | BI tools | LOS platforms | Boutique point tools
- Columns: what they do, time to value, average cost, governance coverage, verdict
- Punchline: "No one has built a governed, full-stack layer for the mid-market. We did."

SLIDE 4 — Our Solution
- Platform name + one-line positioning
- 6 modules: Originations Intelligence | Portfolio Analytics | P&L Engine | Stress Testing | Policy Workbench | Governance & Audit Layer
- Key proof point: "Every action in the platform is a governance artifact"
- Architecture advantage: multi-tenant SaaS, GCP-native, Decision API (< 200ms p99), SHAP explainability built-in

SLIDE 5 — Product Walkthrough
- 3-step onboarding: Data Connect (Week 1–2) → Platform Activation (Week 2–3) → Governance Live (Week 3–4)
- Demo narrative: "On day 30, a credit union CRO ran our pre-exam diagnostic and exported 47 governance artifacts that would have taken 8 weeks manually."
- Screenshots placeholder: [Decision API response with reason codes] [Governance audit export] [Portfolio vintage curve]

SLIDE 6 — Technical Moat (NEW SLIDE — not in original)
- Multi-agent decisioning architecture (diagram: agents → credit_core → audit)
- Governance-by-default: every agent action → append-only audit event → timestamped artifact
- Tenant isolation: JWT → tenant context → scoped storage + config → zero cross-tenant leakage
- Safe policy DSL: AST-validated rules → no eval(), traceable, auditable
- Deterministic replay: policy hash + model artifact hash + feature set version → regulators can replay any decision
- Patent-pending: automated governance artifact generation from runtime decision events

SLIDE 7 — Market Size
- TAM: $18.4B (credit risk technology, IDC 2025) → $35B by 2030 (14% CAGR)
- SAM: $2.1B (US mid-market: 2,800 institutions × $80K–$500K/yr)
- SOM: $22M ARR by Year 5 (120 customers @ avg $180K)
- Wedge logic: "We are capturing the $2–3B governance-analytics gap that legacy platforms leave behind"

SLIDE 8 — Business Model
- SaaS + usage + services (65% / 20% / 15% at Year 3)
- Tier pricing: Starter $60K | Growth $150K | Enterprise $300K–$600K
- Unit economics: CAC $35–55K | LTV $420K | LTV/CAC 7–10× | Payback 14–18 months
- NRR target: 115%+ (module expansion + usage growth)

SLIDE 9 — Traction
- Platform: 6 functional modules, synthetic validation complete, Decision API live with SHAP
- Pipeline: X design partners, Y LOIs at $120K–$350K ARR
- Pricing validated: no pushback at target range
- Technical credibility: governance artifact generation working end-to-end, fairness checks running
- Advisory: ex-OCC examiner + former Head of Model Risk at Tier 1 bank

SLIDE 10 — Go-To-Market
- Phase 1 beachhead: fintech lenders, founder-led, $0.8M ARR
- Phase 2 expansion: regional banks + credit unions, enterprise AEs, $7M ARR
- Phase 3 scale: Series A, international, $26M ARR
- Channel wedge: direct outbound → conference thought leadership → core banking partnerships → Big 4 referral
- 30-day time-to-value → converts faster than any alternative

SLIDE 11 — Competition
- Positioning 2×2: governance depth (y-axis) vs. speed-to-value (x-axis)
- [Our Platform] top-left: high governance, fast TTv
- [Legacy SAS/FICO/Moody's] top-right: high governance, slow TTv, $5M+ contracts
- [Tableau/Looker/dbt] bottom-left: fast, but zero governance, zero domain logic
- [Internal builds] bottom-right: aspirationally full-stack, 12–18 month build times, no commercial roadmap
- Win statement: "We are the only governance-native, full-stack credit risk platform built for speed"

SLIDE 12 — Financial Projections
- 5-year table: Customers | ARR | Gross Margin | EBITDA | Headcount
- EBITDA positive Year 4, 78% gross margin Year 5
- Cash-efficient model: $3.5M Seed → $3M ARR milestone → Series A ready

SLIDE 13 — Team
- CEO: ex-CRO experience, credit risk domain depth
- CTO: risk engineering at scale, built real-time decisioning
- Head of Product: model risk + RegTech background
- Advisors: ex-OCC examiner | former Tier 1 bank Head of Model Risk | SaaS GTM operator
- "Why us": rare combination of domain expertise + engineering + operator experience

SLIDE 14 — The Ask
- Raising $3.5M Seed
- Use of funds: 45% product/engineering | 25% sales/GTM | 15% customer success | 15% G&A
- 18-month milestones: 20 paying customers, $3M ARR, 3 signed partnerships, Series A path visible
- Why now: Basel IV + CECL + AI governance mandates = simultaneous regulatory tailwinds
```

---

### 5B — User / Customer Demo Deck

**Output file**: `docs/pitch/CUSTOMER_DEMO_DECK.md`

Audience: Head of Credit Risk, VP Decision Science, CRO — at a fintech lender or regional bank, evaluating the platform for a pilot.

#### Slide-by-slide requirements:

```
SLIDE 1 — Cover
- "[Platform Name]: Your Credit Risk Control Tower"
- "Prepared for: [Customer Name] | [Date]"
- Sub-headline: "From data to audit-ready decision — in one governed workflow"

SLIDE 2 — What We Heard (Discovery Recap — personalize per customer)
- 3 bullet points from discovery call (template: "You told us that...")
  - "Your model monitoring is manual and takes 2 weeks per cycle"
  - "Your last exam prep took 6 weeks of analyst time"
  - "You can't attribute P&L to risk cohorts without significant data work"
- "Here's how [Platform Name] solves each one — in 20 minutes."

SLIDE 3 — Your Current State (The Pain Map)
- Diagram: show tool sprawl (Excel / SAS / Tableau / SharePoint / LOS)
- "Every team has a version. No one has the truth."
- "Audit prep is a fire drill every time."
- "Model changes happen — no one tracks the approval record."

SLIDE 4 — Platform Overview (Our Solution)
- 6 modules and what they replace for this customer
- "All connected. All auditable. All yours in 30 days."
- Integration architecture: how it connects to their LOS and data warehouse

SLIDE 5 — Live Demo: Originations Intelligence
- Show: approval funnel, risk tier segmentation, adverse action breakdown
- Key aha moment: "You can now see exactly which risk tier is driving approval rate drops"
- Drill-down: single application trace from feature inputs → score → decision → reason codes

SLIDE 6 — Live Demo: Governance & Audit Layer
- Show: model registry with version history
- Show: policy change log (who proposed, who approved, what changed)
- Show: one-click audit package export
- Key aha moment: "What took your team 6 weeks takes 6 minutes. And it's SR 11-7 ready."

SLIDE 7 — Live Demo: Portfolio Analytics
- Show: delinquency roll rates, vintage curves, cohort loss projections
- Show: concentration risk by segment
- Key aha moment: "This replaces 4 separate Tableau dashboards — and it's updated in real time."

SLIDE 8 — Integration & Onboarding
- 30-day onboarding plan (week-by-week milestones)
- Pre-built connectors: [relevant ones for this customer's stack]
- What your team needs to provide: data access, LOS API key, model artifacts
- What we handle: schema mapping, feature engineering, governance layer setup

SLIDE 9 — Pilot Proposal
- 30-day paid pilot: $[X] pilot fee applied to Year 1 contract
- Success criteria (personalized to discovery):
  - Governance layer live and generating audit artifacts
  - Originations dashboard connected to their production LOS data
  - First audit-ready model monitoring report generated
  - Decision API tested against their sandbox LOS
- Risk-free: if we don't hit success criteria, no Year 1 contract obligation

SLIDE 10 — Investment & ROI
- Time saved: [X] weeks of analyst time per exam cycle × $[Y] hourly rate = $[Z] savings
- Approval rate recovery: [3–5%] leakage from opaque decisioning × [loan volume] = $[revenue]
- Regulatory risk reduction: average OCC finding remediation $2–15M
- Platform cost: $[ARR]
- ROI summary: "For every $1 spent, you recover $[X] in analyst time + [Z]% in regulatory risk reduction"

SLIDE 11 — Why Now
- "Basel IV effective EU Jan 2025 — US banks are watching and preparing"
- "CFPB has signaled increased Reg B enforcement on automated decisioning in 2026"
- "Your [next exam / board presentation / product launch] is [X] months away"
- "30 days to live governance. The window to get ahead of it is now."

SLIDE 12 — Next Steps
- [Day 1]: Confirm pilot agreement and sign
- [Day 3]: Data access provisioned and connector configured
- [Day 7]: First dashboard live in your environment
- [Day 30]: Audit package generated and reviewed together
- [Day 35]: Pivot to Year 1 contract discussion
- "Here's our calendar link. Who else should be in the kickoff call?"
```

---

## EXECUTION RULES FOR THE AI AGENT

1. **Ground every claim in the repo.** If a capability is cited, link to the exact file path. If a capability does not yet exist, mark it as "(planned — <prompt_id>)" referencing the implementation plan.

2. **No hallucination of technical stack.** The tech stack is defined in the Master Context section above. Do not invent capabilities, databases, or services not present.

3. **Maintain tonal consistency across deliverables:**
   - Technical Architecture: precise, direct, engineering-grade
   - Developer Manual: conversational, practical, "here's exactly what to do"
   - Compliance Manual: formal, regulatory-aware, defensible
   - Customer Integration Guide: practical, trust-building, error-tolerant
   - ICP Document: data-driven, sales-grade, persona-rich
   - GTM Strategy: action-oriented, phased, realistic to current stage
   - Investor Pitch: confident, market-validated, capital-efficient narrative
   - Customer Deck: consultative, discovery-grounded, value-outcome focused

4. **File output structure.** Create the output files in these exact paths:
   ```
   docs/TECHNICAL_ARCHITECTURE.md
   docs/manuals/DEVELOPER_ONBOARDING.md
   docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md
   docs/manuals/CUSTOMER_INTEGRATION_GUIDE.md
   docs/go_to_market/IDEAL_CUSTOMER_PROFILE.md
   docs/go_to_market/GTM_STRATEGY.md
   docs/pitch/INVESTOR_PITCH_DECK.md
   docs/pitch/CUSTOMER_DEMO_DECK.md
   ```

5. **Cross-reference existing docs.** All business claims should be consistent with `docs/BUSINESS_ASSETS_2026.md`. All technical claims must be consistent with `docs/CORE_PLATFORM_TECH_AUDIT_2026_04_07.md` and `docs/IMPLEMENTATION_PLAN_CORE_PLATFORM_2026_04_07.md`.

6. **Prioritize**: if you must choose between depth and coverage, prioritize Deliverables 1, 3, and 5A (Technical Architecture, ICP, Investor Pitch) as they are most immediately business-critical.

7. **Mermaid diagrams**: use `mermaid` code blocks for all architecture diagrams. C4, sequence, and flowchart styles are all acceptable. Do not use ASCII art for architecture diagrams.

8. **Do not repeat the same data in multiple documents.** Instead, cross-link: e.g., the Customer Demo Deck references the ICP, not repeating it.

9. **Versioning**: all output documents must carry `> Version: 1.0 | Date: [current date] | Status: DRAFT` in the header.

---

## APPENDIX — REPO QUICK REFERENCE

| Area | Key Files |
|---|---|
| Decision API | `decision-api/src/main.py` |
| Ingestion API | `ingestion-api/src/main.py` |
| Agent pipeline | `orchestration/pipeline.py`, `agents/*.py` |
| Feature engineering | `feature_pipeline/features.py`, `agents/feature_engineering_agent.py` |
| Decision engine | `decision_engine/engine.py`, `agents/decision_engine_agent.py` |
| Audit log | `audit/logger.py` |
| Schemas / contracts | `schemas/contracts.py` |
| Models | `models/credit_risk/predict.py`, `models/fraud_detection/predict.py` |
| BQ schema + writer | `db/bigquery_schema.py`, `agents/bq_writer_agent.py` |
| Config | `config/agent_config.yaml` |
| Compliance | `compliance/` |
| Fairness | `scripts/run_fairness_check.py` |
| Existing business assets | `docs/BUSINESS_ASSETS_2026.md` |
| Technical audit | `docs/CORE_PLATFORM_TECH_AUDIT_2026_04_07.md` |
| Implementation plan | `docs/IMPLEMENTATION_PLAN_CORE_PLATFORM_2026_04_07.md` |
| Governance audit | `docs/GOVERNANCE_AUDIT_2026_04_06.md` |
| UI | `ui/`, `dashboard/app.py` |
| Tests | `tests/` |
