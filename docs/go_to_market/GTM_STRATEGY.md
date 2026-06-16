# Go-To-Market Strategy
## Credit Risk Platform — B2B SaaS

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: CEO, CRO, Head of Sales, Marketing
> Current stage: Pre-revenue / early Seed
> Cross-references: `docs/go_to_market/IDEAL_CUSTOMER_PROFILE.md`, `docs/BUSINESS_ASSETS_2026.md`

---

## 1. GTM Philosophy

**Land on a specific critical pain → prove ROI fast → expand modules.**

Our beachhead is not "credit risk analytics" (too broad). It is the **governance audit pain** that every mid-market lender faces in the next 12 months: SR 11-7 compliance, CECL reserve modeling, and CFPB Reg B adverse action explainability. These are regulatory mandates, not nice-to-haves. They create urgency that closes deals.

**The GTM motion in one sentence**: "Don't try to replace everything. Be the governance layer that sits between what they have and what regulators want."

**Wedge → Expand path**:
```
Governance Audit Pain (beachhead entry)
    → Originations Intelligence (module expansion, Month 3–6)
    → Portfolio Analytics (Month 6–12)
    → P&L Engine + Stress Testing (Month 12–24)
```

**Why this works**: the governance layer requires only a Decision API integration (30 days). Generating the first audit package is the "aha moment" that converts pilots to annual contracts. Module expansion follows because the data is already flowing.

---

## 2. Phase 1 — Beachhead (Months 0–12)

### Target Segment
- Fintech lenders ($100M–$2B AUM) — see `docs/go_to_market/IDEAL_CUSTOMER_PROFILE.md` Segment 1
- Forward-thinking credit unions seeking SR 11-7 alignment

### GTM Motion
- **Founder-led sales**: CEO and CTO serve as primary account executives — they know the buyer's language (MRM, SHAP, PSI, SR 11-7)
- **Entry product**: Core Platform (Decision API + Governance Layer)
- **Target**: 6–10 paying customers, $0.8M ARR by end of Month 12

---

### Channel 1 — Direct Outbound

**Target list construction**:
- 200 fintech lenders from CFPB supervised entity list
- FDIC call reports: institutions with $100M–$2B in consumer loans outstanding
- LinkedIn Sales Navigator: "Head of Credit Risk", "VP Decision Science", "Model Risk Manager" at target AUM companies

**Target personas** (contact in this order):
1. Head of Credit Risk, VP Decision Science (technical champion)
2. CRO, Chief Credit Officer (economic buyer — after champion is warm)

> **Do NOT target CIOs or IT departments first.** The platform solves a risk + compliance pain, not an IT infrastructure pain.

**Outreach sequence** (adapt from `docs/BUSINESS_ASSETS_2026.md` LinkedIn sequences):
1. **LinkedIn connection request** with personalized note referencing their company's regulatory context
2. **Follow-up message (Day 3)**: share relevant content (SR 11-7 benchmark article, CECL readiness guide)
3. **Direct message (Day 7)**: 2-sentence pitch + calendar link ("We help lenders like [Company] auto-generate SR 11-7 model documentation in under 30 days. Worth 20 minutes?")
4. **Demo → pilot proposal → paid contract**

**Messaging pillars**:
- Governance: "From 6 weeks of manual audit prep to 6 minutes of automated documentation"
- Explainability: "Every credit decision comes with a Reg B-ready adverse action reason code — automatically"
- Speed: "Live governance layer in 30 days. Not 18 months."
- Risk reduction: "Average OCC model risk finding costs $2–15M in remediation. We make that finding go away."

---

### Channel 2 — Conference Presence

**Target conferences (Year 1)**:

| Conference | Audience Concentration | Tactic |
|---|---|---|
| GARP Global Risk Forum | Risk managers, model validators, CROs | 20-min breakout session: "AI Governance in Credit Decisioning: What SR 11-7 Actually Requires" |
| RMA Annual Risk Management Conference | Risk Management Association members — bank and fintech CROs | Table sponsor + speaking slot |
| LendIt / Fintech Nexus | Fintech lender leadership concentration | Demo booth + hosted dinner for 10 target accounts |
| American Bankers Association Risk Management Summit | Community bank and credit union risk leaders | Session on CECL compliance + live platform demo |

**Conference playbook**:
1. Identify 10 target accounts attending each event before the conference
2. Schedule 15-min coffee meetings in advance via LinkedIn
3. Present 20-minute session (establishes credibility — not a vendor pitch)
4. Collect business cards / LinkedIn connections → follow up within 48 hours with a pilot proposal
5. Measure: inbound demo requests from conference vs. outbound follow-ups

---

### Channel 3 — Content / Thought Leadership

**Content calendar (Year 1)**:

| Asset | Format | Launch Timing | Primary Distribution |
|---|---|---|---|
| "Model Governance Benchmark Report" | 12-page PDF | Month 2 | LinkedIn newsletter, GARP/RMA member groups, direct email |
| "SR 11-7 Compliance Readiness Diagnostic" | Downloadable self-assessment (Google Form + PDF result) | Month 1 | LinkedIn ads targeting VP Risk + Director Model Risk |
| "The True Cost of a Manual Audit Prep" | LinkedIn article (900 words) | Month 1 | LinkedIn + email list |
| "CECL in 90 Days: What Lenders Miss" | Webinar (40 min + Q&A) | Month 3 | Registration page → email capture → demo follow-up |
| Monthly "Credit Risk Platform Insights" newsletter | Email | Monthly | Target list + inbound subscribers |

**Content goal**: 500 email subscribers by Month 6 who match the ICP (Head of Credit Risk, VP Decision Science, Model Risk Manager).

**Content → demo funnel**: every content piece ends with "See how long it takes your team to generate your first audit package — schedule a 20-minute demo."

---

### Pilot Playbook

**Structure**: 30-day paid or co-investment pilot

| Stage | Detail |
|---|---|
| **Pilot fee** | $5K–$15K (applied to Year 1 contract upon conversion) |
| **Success criterion 1** | Governance layer live and generating audit artifacts from the Decision API |
| **Success criterion 2** | Decision API integrated into customer's sandbox LOS with a working request/response |
| **Success criterion 3** | First audit package exported and reviewed together with the customer team |
| **Risk-free clause** | If success criteria are not met by Day 30, no Year 1 contract obligation |
| **Conversion target** | 75% pilot-to-paid conversion; Year 1 contract at $120K–$350K ARR |

**Day-by-day pilot milestone template**:
- Day 1–3: API credentials provisioned; sandbox environment set up
- Day 7: First Decision API call live with customer data
- Day 14: Originations dashboard connected to customer LOS data
- Day 21: Model monitoring report generated
- Day 28: Full audit package exported and reviewed
- Day 30: Pilot review call; pivot to Year 1 contract discussion

---

## 3. Phase 2 — Expansion (Months 12–30)

### Target Segment
- Regional banks ($1B–$10B AUM)
- Enterprise credit unions ($500M–$5B assets)

### Sales Motion Shift

| Change | Detail |
|---|---|
| **Hire 2 enterprise AEs** | Background: bank risk technology sales (nCino, FiServ, S&P Global market); understand 90-day institutional sales cycles |
| **Add Customer Success Manager** | Drives module expansion in existing accounts; tracks usage and surfaces upsell signals |
| **Entry product shift** | Governance Layer is now the primary entry point — compliance pain is universal in this segment |
| **Secondary upsell** | Portfolio Analytics → P&L Engine → Stress Testing |

### New Channels in Phase 2

**Core banking / LOS partnerships**:
- **nCino**: LOS for bank and credit union segment; co-market via nCino App Exchange; joint webinar with nCino customer success team
- **Jack Henry**: Community bank / credit union core banking; referral model — Jack Henry AEs identify governance pain in their base, refer to platform
- **Temenos**: Global core banking — enables EU/Asia expansion in Phase 3

**Big 4 consulting partnerships**:
- Deloitte, PwC, EY, KPMG model validation teams conduct SR 11-7 model validations for clients and identify governance tooling gaps → recommend platform
- Partnership structure: referral fee + co-branded model validation report template

**Regulatory consultant channel**:
- Network of ex-OCC, ex-CFPB consultants who advise mid-market banks on exam preparation
- These consultants recommend tooling to clients in the 6 months before an exam — highest-intent buyer moment

### Pricing for Phase 2 Segment

| Tier | AUM Segment | ARR |
|---|---|---|
| Growth | Fintech $200M–$2B | $150K |
| Enterprise | Regional bank / CU $1B–$10B | $180K–$500K |
| Enterprise+ | > $10B AUM | $400K–$600K + custom |

**Net Revenue Retention target**: 115%+ via module expansion (each new module adds $30–$120K ARR to existing accounts).

---

## 4. Phase 3 — Scale (Months 30–60)

- **Series A-funded growth**: dedicated 6-person sales team + 3 Customer Success
- **International expansion**: UK (FCA), India (RBI), Southeast Asia (MAS) — see ICP Segment 3
- **Integration marketplace**: pre-built connectors for top 5 core banking systems (nCino, Jack Henry, Temenos, FiServ, Salesforce Financial Services Cloud)
- **Product-led growth layer**: freemium "Model Risk Self-Assessment" tool generates inbound leads at scale

---

## 5. Competitive Moats to Build Now

| Moat | Description | Timeline |
|---|---|---|
| **Data network effect** | Governance artifacts + anonymized performance benchmarks → industry benchmarking product ("Your approval rate vs. peer cohort") | Phase 2 (Month 12+) |
| **Domain data model lock-in** | 180+ pre-mapped credit risk fields in `schemas/contracts.py` → switching cost after integration; no other platform speaks this schema natively | Exists today |
| **Regulatory artifact IP** | Automated governance documentation generation (`compliance/generate_model_doc.py`) → patent-pending process | File now |
| **Advisor moat** | Ex-OCC examiner advising → credibility with bank compliance buyers; ex-Tier 1 Head of Model Risk → product credibility with MRM teams | Seed round close |
| **Certified MLflow model governance workflow** | Codified train → validate → approve → bind → monitor workflow; becomes an industry standard reference implementation | Phase 1 content |

---

## 6. Pricing & Packaging Strategy

| Tier | Entry Price / Year | Modules Included | Target Segment |
|---|---|---|---|
| **Starter** | $60K | Decision API + Governance Layer | Early fintech (< $200M AUM) |
| **Growth** | $150K | + Portfolio Analytics + Originations Intelligence | Fintech $200M–$2B |
| **Enterprise** | $300K–$600K | Full platform + custom integrations + dedicated CSM | Regional banks, large credit unions |
| **Platform API** | Usage-based ($0.05 / decision) | Decision API only, per-call pricing | LOS vendors integrating as white-label |

**Usage overages:**
- $0.05 per decision above plan limit
- $500 per audit package export above plan limit

**Professional services:**
- $2,500 / day for custom integration, model validation support, onboarding acceleration

---

## 7. Partnership Strategy

### Core Banking / LOS Referral Partners

| Partner | Why | Co-sell Model |
|---|---|---|
| nCino | LOS for bank + credit union segment; customer base = our ICP | API integration → co-sell via nCino App Exchange; joint customer webinars |
| Jack Henry | Community bank / credit union core banking (3,500+ institutions) | Referral model — Jack Henry AEs flag governance pain; we pay 10% referral fee |
| Temenos | Global core banking; connector enables EU/Asia market access | Technology partner program; connector listed in Temenos Marketplace |

### Data Enrichment Partners

| Partner | Purpose |
|---|---|
| Plaid / MX / Finicity | Open banking transaction data → enriches feature pipeline for thin-file applicants |
| Experian / Equifax / TransUnion API | Traditional bureau data connector for feature enrichment (P2.x) |

### Compliance / Advisory Partners

| Partner | Role |
|---|---|
| Big 4 model validation teams | Refer platform to clients needing governance tooling; co-branded validation report format |
| Ex-regulatory consultant networks (RMA, GARP certified firms) | Recommend platform to mid-market banks in exam prep cycles |
| Law firms with financial services practices | Compliance tool referral when advising on CFPB / OCC regulatory matters |

---

## 8. Sales Funnel Metrics & Targets (Year 1)

| Funnel Stage | Target | Conversion Rate |
|---|---|---|
| Outbound contacts (LinkedIn + email) | 200 / month | — |
| Demo requests | 20 / month | 10% |
| Active pilots initiated | 8 total | 40% of demos |
| Contracts closed | 6 total | 75% of pilots |
| Average ARR per contract | $130K | — |
| **Year 1 ARR** | **$780K** | — |

---

## 9. Key GTM Metrics to Track

| Metric | Definition | Target |
|---|---|---|
| Time-to-first-demo | Days from outbound contact to scheduled demo | < 14 days |
| Time-to-pilot | Days from demo to signed pilot agreement | < 21 days |
| Pilot conversion rate | Pilots → paid contracts | > 70% |
| Time-to-value in pilot | Days to first audit package generated in customer environment | < 21 days |
| Net Revenue Retention | ARR from existing customers at 12 months / ARR at start | > 115% |
| CAC by channel | Total sales + marketing cost / new customers (by channel) | < $45K |
| Payback period | CAC / (ARR × gross margin) | < 18 months |
| Demo → pilot conversion | Demos that convert to a signed pilot | > 40% |
