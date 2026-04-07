# Customer Demo Deck
## Credit Risk Platform — Your Credit Risk Control Tower

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: Head of Credit Risk, VP Decision Science, CRO — at a fintech lender or regional bank evaluating a pilot
> Usage: Personalize Slides 2, 3, 9, 10, 11 with discovery call insights before each presentation
> Cross-references: `docs/go_to_market/IDEAL_CUSTOMER_PROFILE.md`, `docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md`

---

## SLIDE 1 — Cover

### Credit Risk Platform
**Your Credit Risk Control Tower**

*Prepared for: [Customer Organization Name]*
*Date: [Presentation Date]*
*Presented by: [Presenter Name] | [Title]*

> **"From data to audit-ready decision — in one governed workflow."**

---

## SLIDE 2 — What We Heard (Discovery Recap)

*[PERSONALIZE: Replace these three bullets with exact language from your discovery call. Use the customer's words, not your words.]*

**You told us that...**

- **"[Pain Point 1]"** — e.g., *"Our model monitoring is a manual process that takes two full weeks per reporting cycle — and we know it gets skipped when the team is under pressure."*

- **"[Pain Point 2]"** — e.g., *"Our last OCC exam prep took 6 weeks of analyst time just to assemble the model documentation we needed. We can't go through that again in Q3."*

- **"[Pain Point 3]"** — e.g., *"We can't attribute our P&L movements to specific risk cohorts without significant data wrangling that takes 3 weeks and involves half the analytics team."*

---

**Here is how Credit Risk Platform solves each one of these — in the next 20 minutes.**

*[PRESENTER NOTE: Reference each pain back to its specific platform demo during Slides 5–7. This creates a closed-loop problem → solution narrative.]*

---

## SLIDE 3 — Your Current State (The Pain Map)

*[PERSONALIZE: Adapt names of tools your prospect is currently using based on discovery.]*

### "Every Team Has a Version. No One Has the Truth."

```
┌─────────────────────────────────────────────────────────────────────┐
│                     YOUR CURRENT RISK STACK                         │
│                                                                     │
│  [Excel]        [SAS / R / Python    [Tableau / Power BI]           │
│  Policy rules   Notebooks]           "Monitoring dashboards"        │
│  (who's is      (models that live    (disconnected from actual      │
│   current?)     on someone's laptop) decision data)                 │
│                                                                     │
│  [SharePoint]   [LOS (nCino/         [Email threads]                │
│  "Model docs"   Blend/custom)]       "Approval for                  │
│  (last updated  originates loans     champion/challenger"           │
│  14 months ago) but can't explain    (no formal record)             │
│                 its decisions                                       │
└─────────────────────────────────────────────────────────────────────┘
```

**The result:**
- Every team has a version of the truth — no single authoritative source
- Audit prep is a fire drill every single time a regulator arrives
- Model changes happen without a formal approval record
- Credit decisions are made but can't be explained in plain language to applicants or examiners

**"The platform you're about to see collapses all of this into one governed workflow — and goes live in 30 days."**

---

## SLIDE 4 — Platform Overview

### What Credit Risk Platform Replaces — For You

**Six integrated modules. All connected. All auditable. All live in 30 days.**

| Module | What It Does | What It Replaces for You |
|---|---|---|
| **Originations Intelligence** | Real-time approval funnel, risk-tier segmentation, feature attribution per decision | [Customer's existing originations dashboard or Excel model] |
| **Portfolio Analytics** | Delinquency roll rates, vintage curves, cohort loss projections | [Customer's Tableau/Power BI portfolio reports] |
| **P&L & Profitability Engine** | Risk-adjusted return by segment, cost of credit vs yield | [Customer's Finance spreadsheets] |
| **Governance & Audit Layer** | Automated SR 11-7 model docs, one-click audit export, decision lineage | [Customer's SharePoint + manual analyst prep] |
| **Policy & Strategy Workbench** | Version-controlled credit policy, champion/challenger with formal approval | [Customer's email approval threads + jira tickets] |
| **Decision API** | < 200ms real-time underwriting with SHAP reason codes and Reg B adverse action codes | [Customer's existing LOS black-box decisioning] |

**Integration architecture**: the platform connects to your existing LOS via a standard REST API integration — no core system replacement required.

---

## SLIDE 5 — Live Demo: Originations Intelligence

*[PRESENTER: Open the Originations Intelligence dashboard. Walk through the following story.]*

### What You Can See in 30 Seconds That Took 3 Weeks Before

**Step 1 — Approval funnel drill-down**:
- "Here is your approval rate by risk tier this quarter."
- "This drop in Prime approvals — let's click into it."
- Watch: drill down to the feature that's driving it (e.g., DTI thresholds shifted after Q4 policy update)

**Step 2 — Single application trace**:
- "Let's pull up a declined application."
- "Here are the exact feature inputs: DTI: 0.52, credit score: 618, existing debt: $28K."
- "Here is the model output: PD score 0.34 = Deep Sub-Prime."
- "Here are the reason codes the platform generated: R01 (DTI too high), R05 (derogatory history)."
- "This is a Reg B adverse action reason code set — legally compliant, auto-generated, no analyst involvement."

**The aha moment:**
> *"You can now see exactly which risk tier is driving approval rate drops — and you can trace every decline back to the exact features and model output that caused it. No more guessing."*

---

## SLIDE 6 — Live Demo: Governance & Audit Layer

*[PRESENTER: This is the primary emotional close for compliance-motivated buyers. Take your time here.]*

### The Exam Prep That Took 6 Weeks. Now Takes 6 Minutes.

**Step 1 — Model registry with version history**:
- "Here is your `credit_risk_pd` model. Version 3 is in production."
- "Here is the full audit trail: who trained it, what data, what performance metrics, who approved it for production, and exactly when it was bound."

**Step 2 — Policy change log**:
- "Three weeks ago, your team updated the DTI hard cutoff from 0.45 to 0.40."
- "Here is who proposed the change, who approved it, what the expected impact was, and the A/B test results that justified it."
- "This is the formal change control record SR 11-7 requires."

**Step 3 — One-click audit package export**:
- Click: "Generate Exam Package — Q1 2026"
- Watch: 47 artifacts generated in < 2 minutes
  - Model card for each active model
  - Policy version history
  - Decision lineage for sample applications
  - Fairness assessment
  - Monitoring performance report

**The aha moment:**
> *"What just took your team 6 weeks to assemble takes 6 minutes here — and every document is SR 11-7 ready, every record is immutable, every approval is traceable. The next time an examiner walks in, you hand them this package."*

---

## SLIDE 7 — Live Demo: Portfolio Analytics

*[PRESENTER: Tailor this to the customer's active pain — if they mentioned CECL, focus on cohort loss projections. If they mentioned monitoring, focus on roll rate trends.]*

### Portfolio Intelligence That Replaces 4 Separate Dashboards

**Delinquency roll rates**:
- "Here are your 30/60/90 day roll rate trends by origination month."
- "This cohort from Q3 2025 is rolling faster than prior vintages. Here is the feature explanation — higher DTI concentration in this batch."

**Vintage curves with loss projection**:
- "Here is the projected loss curve for this vintage — this is your CECL input."
- "The platform generates this from your actual decision data and model outputs — not from a spreadsheet."

**Concentration risk**:
- "You have 34% of your book in the Mid-West, 28% in Sub-Prime tier, and 19% in auto loans."
- "Here is the stress scenario: if Sub-Prime bad rates increase 150bps, here is the impact on reserves."

**The aha moment:**
> *"This replaces 4 separate Tableau dashboards — each one maintained by a different analyst, each one updated on a different schedule. And it's connected to your real decision data, updated in real time."*

---

## SLIDE 8 — Integration & Onboarding

### 30 Days to Live. Here Is Exactly How It Works.

**Week-by-week onboarding plan:**

| Week | Milestone | Your Team's Input |
|---|---|---|
| **Week 1** | API credentials provisioned; sandbox environment configured | Provide LOS API key + sandbox endpoint |
| **Week 1–2** | Decision API integration live with your LOS data in sandbox | LOS engineering (4 hours typical) |
| **Week 2–3** | Originations and Portfolio dashboards populated with your data | Provide BigQuery / Snowflake read access |
| **Week 3** | First governance audit package generated | Review model documentation together |
| **Week 4** | Production cutover; first live decision logged to audit trail | Final UAT sign-off from your team |

**What your team provides**: LOS API key; data warehouse read access; model artifacts (if you have existing models to register)

**What we handle**: schema mapping (`schemas/contracts.py` has 180+ pre-mapped credit risk fields), feature engineering, governance layer setup, model registration in MLflow, monitoring configuration

**Pre-built connectors available**: [nCino / Blend / Salesforce / custom — confirm from customer's tech stack]

---

## SLIDE 9 — Pilot Proposal

*[PERSONALIZE: Insert the specific pilot fee and success criteria derived from the discovery call.]*

### 30-Day Paid Pilot — Structured for Your Specific Outcome

**Structure:**

| Element | Detail |
|---|---|
| **Duration** | 30 calendar days from kick-off |
| **Pilot fee** | $[X]K — applied in full to your Year 1 contract upon conversion |
| **What you need to provide** | LOS API access (sandbox) + data warehouse read credentials |
| **What we deliver** | Full platform setup, schema mapping, first audit package, onboarding support |

**Success criteria — jointly agreed before kick-off:**

- [ ] Governance layer live and generating audit artifacts within 21 days
- [ ] Originations dashboard connected to your production LOS data
- [ ] First SR 11-7-ready model monitoring report generated and reviewed together
- [ ] Decision API tested successfully against your sandbox LOS with all three decision outcomes (APPROVE, DECLINE, REFER)

**Risk-free commitment**:
If we do not meet all four success criteria by Day 30, you have zero obligation to a Year 1 contract. We carry the implementation risk — not you.

---

## SLIDE 10 — Investment & ROI

*[PERSONALIZE: Fill in the customer's specific numbers from discovery — loan volume, analyst team size, exam frequency.]*

### For Every $1 You Invest, Here Is What You Get Back

**Time savings — Exam prep:**
- Current: [X] weeks × [Y] analysts × [$Z analyst cost/week] = **$[Total] per exam cycle**
- With platform: < 1 day for audit package generation = **$[Savings] saved per exam**
- Payback on exam prep alone: **[Months] months**

**Approval rate recovery:**
- Opaque decisioning creates 3–8% approval rate leakage on eligible applicants
- At [$X average loan value] × [Y annual applications] × [3–5% recovery]:
- **$[Revenue recovered] / year** from reducing incorrect declines alone

**Regulatory risk reduction:**
- Average OCC model risk finding remediation: $2–15M
- With automated SR 11-7 documentation and ongoing monitoring: reduced finding probability
- Value: not easily quantified, but the CRO who explains this to the board will fund this platform

**Platform cost**: $[ARR] per year

**ROI summary:**
> *"On analyst time savings and approval rate recovery alone — before you count regulatory risk reduction — the payback is under 12 months. Every month you wait is a month of exam prep cost and approval leakage you're absorbing."*

---

## SLIDE 11 — Why Now

### The Window to Get Ahead of This Is Closing

*[PERSONALIZE: Use the specific regulatory driver that resonated in discovery.]*

**Regulatory pressure is compressing the decision window:**

- **Basel IV**: US banks are actively reviewing model governance frameworks in anticipation of adoption
- **CFPB 2026 AI/ML enforcement signals**: the agency has signaled increased scrutiny of automated credit decisioning that can't be explained
- **Your [next OCC exam / board presentation / CECL deadline]** is [X months] away

**Your three options:**
1. **Assemble manually** — another 6-week fire drill for your team, every exam, forever
2. **Build it internally** — 12–18 months of engineering; $1–3M; no guarantee it holds up to SR 11-7 scrutiny
3. **Credit Risk Platform** — **30 days to live governance; audit-ready from Day 1**

**"The window to get ahead of your next exam is now. You can spend 30 days and $[pilot fee] to know for certain this works — or you can spend 6 weeks of your team's time to assemble the documentation package manually next quarter."**

---

## SLIDE 12 — Next Steps

### From This Conversation to Live Governance in 30 Days

| Day | Action | Who |
|---|---|---|
| **Day 1** | Confirm pilot agreement; sign engagement letter | You + Us |
| **Day 3** | Kick-off call: schema mapping review, LOS API access provisioned | Technical teams both sides |
| **Day 7** | First Decision API call live against your LOS sandbox data | Joint |
| **Day 14** | Originations dashboard live; first data review | Your CRO + us |
| **Day 21** | Governance layer producing audit artifacts | Joint review |
| **Day 28** | Full audit package generated; review SR 11-7 coverage together | Your team + us |
| **Day 30** | Pilot review call; pivot to Year 1 contract discussion | CRO + us |

**Who else should be in the kick-off call?**
Typically: you (credit/risk lead) + one LOS engineer (for API access) + one data/analytics resource (for warehouse access). Total: 3–4 people. Total time commitment from your team in the first week: approximately 6 hours.

---

**[Calendar link: schedule the pilot kick-off call]**
**[One-page pilot agreement: ready to sign today]**

---

*For technical integration details, see `docs/manuals/CUSTOMER_INTEGRATION_GUIDE.md`.
For compliance and governance detail, see `docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md`.*
