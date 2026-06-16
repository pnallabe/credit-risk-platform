# Ideal Customer Profile
## Credit Risk Platform — B2B SaaS

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: Sales, Marketing, Customer Success
> Cross-references: `docs/BUSINESS_ASSETS_2026.md`, `docs/go_to_market/GTM_STRATEGY.md`

---

## 1. ICP Summary Card

**Platform one-line positioning**: A governance-first, multi-agent credit risk platform that gives mid-market lenders automated underwriting, explainable AI, and audit-ready compliance documentation — live in under 30 days.

| Dimension | Detail |
|---|---|
| **Target buyer** | Head of Credit Risk / VP Decision Science / CRO; Risk Technology function; reports to CRO or CFO |
| **Target user** | Risk Analyst, Model Risk Manager, Credit Analyst; builds scorecards, monitors portfolio, prepares board reporting |
| **Deal size range** | $60K – $500K ARR |
| **Sales cycle estimate** | 30–90 days (fintech); 90–150 days (regional bank / credit union) |
| **They are ready to buy if...** | (1) They have an OCC/CFPB exam, CECL implementation, or model validation finding scheduled in the next 90 days. (2) Their current model governance process is manual, Excel-based, or lives in SharePoint. (3) A new CRO or Head of Credit Risk has been hired in the past 6 months and is signaling a platform refresh. |

---

## 2. Primary ICP Segment — Fintech Lender ($100M–$2B AUM)

### Firmographic Signals

| Dimension | Target Profile |
|---|---|
| **AUM range** | $100M–$2B in active loan book |
| **Product types** | Consumer credit card, personal loans, BNPL, SMB working capital |
| **Regulatory status** | Licensed lender, CFPB-supervised, state chartered |
| **Headcount** | 50–500 employees |
| **Tech maturity** | Modern data stack (Snowflake/BigQuery/dbt) **or** legacy (Excel/SAS) — both are buyers, different entry points |
| **Geography** | US-domiciled; expanding to UK / Canada in Phase 3 |

### Technographic Signals

| Signal | What It Indicates |
|---|---|
| Uses nCino, Blend, or custom-built LOS | Standard decisioning integration exists |
| Has existing MLflow or SageMaker model registry | Sophisticated analytics team → governance is the gap, not the model |
| Still scores applicants using a vendor scorecard they can't explain | Immediate governance + explainability pain → fastest sales cycle |
| Pub/Sub or Kafka in place | Ready for event-driven decisioning integration |
| Excel-based model monitoring spreadsheets | Explicit pain point → quantifiable time savings |

### Psychographic Signals (Actual Buyer Pain)

> "Our model monitoring is a spreadsheet that someone updates on Fridays — and we all know it gets skipped when things are busy."

> "We had an OCC exam and it took 6 weeks of analyst time just to assemble the model documentation. We can't do that again."

> "We're doing champion/challenger but there's no formal approval record. If we get examined, we can't prove we followed our own policy."

> "We have SHAP outputs in a notebook. They're not in a workflow, not attached to any decision, and the compliance team can't look at them."

> "Our approval rate dropped 4% last quarter and we don't know if it's the model, the policy, or the data quality."

### Anti-ICP Signals (Disqualify)

| Anti-Signal | Why to Disqualify |
|---|---|
| < $50M AUM | ROI math doesn't work; implementation cost relative to portfolio size is too high |
| No dedicated risk analytics team | No champion; no internal advocate; 12-month sales cycle minimum |
| Full Moody's or FICO Enterprise contract signed in last 12 months | Budget locked in; not in market for 18 months |
| CRO reports to CFO with no engineering relationship | Procurement will block; champion can't get budget |
| Start-up with < 10 employees in risk | Not operationally ready to integrate |

### Champion Profile

| Dimension | Profile |
|---|---|
| **Title** | Head of Credit Risk, VP Decision Science, Director of Risk Analytics, Chief Model Risk Officer |
| **Day-to-day** | Builds scorecard models, monitors portfolio KPIs, prepares board reporting, manages MRM findings |
| **KPIs they own** | Approval rates, bad rate, model AUC/KS/Gini, fair lending metrics, audit findings count |
| **Their CEO/CRO is saying** | "We need to be audit-ready by Q3" / "The MRM team needs documentation that holds up to examination" |
| **What they're frustrated by** | Manual model monitoring; stitching together 5 tools; having to explain model decisions in plain English for compliance |

### Economic Buyer

| Dimension | Profile |
|---|---|
| **Title** | CRO, Chief Credit Officer, VP Risk |
| **Contract size** | $80K–$350K ARR |
| **Budget source** | Risk technology, compliance, or data platform line items |
| **Signs contract** | After champion demonstrates ROI (analyst time savings + exam readiness) |

---

## 3. Secondary ICP Segment — Regional Bank / Credit Union ($1B–$15B AUM)

### Firmographic Signals

| Dimension | Target Profile |
|---|---|
| **AUM range** | $1B–$15B total assets |
| **Institution type** | State-chartered bank, federally chartered credit union, thrift |
| **Regulatory supervisors** | OCC / FRB / FDIC (banks); NCUA (credit unions) |
| **Product types** | Consumer mortgage, auto, personal loans, HELOCs, SMB SBA loans |
| **Headcount** | 200–2,000 employees |
| **Tech maturity** | Often legacy (Jack Henry, FiServ, Temenos core banking) with limited modern data stack |

### Psychographic Signals (Buyer Pain)

> "The OCC examiner asked us for a model validation report and we hadn't done one in 18 months."

> "SR 11-7 says we need to have ongoing monitoring. Right now that's a quarterly meeting where someone reads a PowerPoint."

> "We're implementing CECL and we don't have a proper loss curve model. We're doing it in Excel."

> "Our CRO is new. She came from a Tier 1 bank and she's asking questions we can't answer about model governance."

### Sales Dynamics

| Factor | Impact |
|---|---|
| **Sales cycle** | 90–120 days; IT procurement involved from Day 30 |
| **Entry point** | Governance / compliance urgency is primary driver, not analytics sophistication |
| **Champions** | CRO + Chief Compliance Officer together; both need to be won |
| **Deal blockers** | IT security review, vendor management, data classification questionnaire |
| **Budgets** | Q4 for following year; pilot in Q3 to land in Q4 budget |

### Differentiated Value Proposition for This Segment

- **SR 11-7 alignment**: automated model documentation generation (`compliance/generate_model_doc.py`) reduces exam prep from 6 weeks to days
- **CECL / IFRS 9 readiness**: vintage curves and cohort loss projections (Portfolio Analytics module) accelerate reserve model development
- **Audit package export**: one-click regulatory examination package reduces per-exam cost by $50K–$200K in analyst time
- **No rip-and-replace**: the platform wraps existing LOS (nCino, Jack Henry) via Decision API — no core system change required

---

## 4. Tertiary ICP Segment — NBFC / International Lender (India, UK, Southeast Asia)

| Dimension | Profile |
|---|---|
| **India NBFC** | RBI model governance guidelines; digital lending lenders; fast-growing portfolios; need regulatory-grade documentation for RBI inspection |
| **UK digital bank** | FCA SREP requirements; SR 11-7 analog in PS7/17 model risk; IFRS 9 mandatory |
| **Southeast Asia fintech** | MAS TRM framework (Singapore); Bank Negara Malaysia; BNM JSPKD model risk guidelines |
| **Why they're easier** | Less legacy baggage → faster implementation; often cloud-native already; shorter sales cycles |
| **Entry product** | Portfolio Analytics + Governance Layer — compliance documentation is universal pain |

---

## 5. Negative ICP — Account Disqualification Criteria

| Disqualification Criterion | Reason |
|---|---|
| Tier 1 banks ($100B+ AUM) | 18–24 month procurement cycles; require on-prem deployment; SOC2 Type II + FedRAMP review; out of scope at Seed stage |
| Pure insurance or wealth management | No credit decision flow; zero addressable use case |
| No risk analytics function at all | No champion exists; will not complete integration; 0% conversion probability |
| Already 12+ months into a competitor implementation (Moody's, FICO, Provenir) | Budget locked; switching cost too high; wait 18 months |
| Consumer-only micro-lender < $20M portfolio | Too small; ROI is negative at current pricing |

---

## 6. ICP-to-Platform Capability Mapping

| ICP Pain | Platform Capability | Source Module | Time-to-Demonstrate |
|---|---|---|---|
| Model governance docs take 6 weeks per exam cycle | `compliance/generate_model_doc.py` — automated SR 11-7 model cards | `compliance/` | Live demo (Day 0) |
| Can't explain credit decisions to applicants / regulators | `agents/explainability_agent.py` — SHAP reason codes in every decision | `agents/`, `models/` | Live demo (Day 0) |
| Two different teams produce different credit decisions for the same application | `credit_core` canonical feature + policy package (P0.2) | `feature_pipeline/`, `decision_engine/` | POC (Day 30) |
| No audit trail for model version changes | Model registry + `policy_version` in every audit record | `audit/logger.py`, `decision_engine/policy_version_store.py` | Live demo (Day 0) |
| CECL implementation requires cohort loss projections | Portfolio Analytics module — vintage curves, cohort loss | `db/bigquery_schema.py`, warehouse | POC (Day 14) |
| Fair lending disparate impact not monitored | `scripts/run_fairness_check.py` (planned), `compliance/engine.py` | `compliance/` | POC (Day 30) |
| Champion/challenger has no formal approval record | Policy version store + MRM review queue | `decision_engine/policy_version_store.py`, `scripts/review_queue_cli.py` | Live demo (Day 0) |
| Approval rate dropped, don't know why | Originations Intelligence — approval funnel drill-down, feature attribution | `dashboard/`, BigQuery analytics layer | POC (Day 14) |
| Audit prep is a fire drill every exam | One-click audit package export | `scripts/check_audit_completeness.py` | POC (Day 14) |
| No per-application adverse action reason codes | SHAP → reason code mapping in every decision response | `agents/explainability_agent.py`, `schemas/contracts.py` | Live demo (Day 0) |

---

## 7. Buying Triggers (External Events That Accelerate Purchase)

| Trigger | Signal Strength | How to Detect |
|---|---|---|
| OCC/CFPB exam scheduled in next 90 days | 🔴 Highest | Direct conversation; news/press release |
| Basel IV or CECL implementation underway | 🔴 Highest | CECL deadline pressure (US banks); LinkedIn posts about "CECL readiness" |
| Recent model failure, MRM finding, or enforcement action | 🔴 Highest | Public enforcement action databases (CFPB Consumer Financial Protection Bureau enforcement page) |
| New CRO or Head of Credit hired in past 6 months | 🟠 High | LinkedIn job postings; leadership page changes |
| Series B/C fundraise — investors asking for institutional-grade risk infrastructure | 🟠 High | Crunchbase funding announcements |
| Expansion into new product type (launching BNPL, entering SMB lending) | 🟠 High | Product launch press releases; LinkedIn announcements |
| "Model documentation" in LinkedIn posts or job postings | 🟡 Medium | LinkedIn Sales Navigator keyword search |
| New Head of Data / Chief Data Officer hired | 🟡 Medium | LinkedIn alerts on target accounts |
| New compliance / model risk job posting | 🟡 Medium | Signals a gap being felt |
