# Financial Regulation & Examination Mastery Roadmap

---

## SECTION 1: Regulatory Landscape Deep Dive

### 1.1 Key Regulators & Their Roles

#### United States

| Regulator | Jurisdiction | Primary Focus |
|---|---|---|
| **OCC** (Office of the Comptroller of the Currency) | National banks, federal thrifts | Safety & soundness, credit risk, fair lending |
| **Federal Reserve (FRB)** | BHCs, FHCs, state member banks, systemically important firms | Monetary policy, systemic risk, stress testing (CCAR) |
| **FDIC** | State non-member banks, deposit insurance | Resolution planning, deposit insurance assessments |
| **CFPB** | Consumer financial products | UDAAP, fair lending, HMDA, TILA, RESPA |
| **SEC** | Securities firms, broker-dealers | Market integrity, disclosure |
| **FINRA** | Broker-dealers | Self-regulatory, sales practices |
| **State Regulators** | State-chartered banks, licensed lenders, credit unions | Varies — often mirror federal but add state-specific consumer protections |
| **NCUA** | Federal credit unions | Safety & soundness, field-of-membership |

#### Canada

| Regulator | Jurisdiction |
|---|---|
| **OSFI** (Office of the Superintendent of Financial Institutions) | Federally regulated banks, insurers, pension plans |
| **FINTRAC** (Financial Transactions and Reports Analysis Centre) | AML/ATF compliance, suspicious transaction reporting |
| **FCAC** (Financial Consumer Agency of Canada) | Consumer protection at federally regulated FIs |
| **AMF** (Autorité des marchés financiers) | Quebec provincial regulator |
| **Bank of Canada** | Systemic risk, payment systems oversight |

#### Global

| Body | Role |
|---|---|
| **BIS** (Bank for International Settlements) | Research, standard-setting infrastructure |
| **Basel Committee on Banking Supervision (BCBS)** | Basel I/II/III/IV capital & liquidity standards |
| **IMF** | Financial Sector Assessment Program (FSAP), Article IV consultations |
| **World Bank** | Development finance, regulatory capacity building |
| **FATF** | Global AML/CFT standards |
| **FSB** (Financial Stability Board) | Macroprudential oversight, G-SIB/G-SII designation |

---

### 1.2 Regulatory Philosophy: Rules-Based vs. Principles-Based

| Dimension | Rules-Based (US dominant) | Principles-Based (Canada/UK/Australia) |
|---|---|---|
| **Specificity** | Bright-line thresholds (e.g., exact capital ratios, exact LTV caps) | Outcome-focused; institution defines "how" |
| **Flexibility** | Low — limited interpretation | High — but more examiner judgment |
| **Burden** | Compliance as checklist | Compliance as ongoing risk management |
| **Failure mode** | Technical violations despite sound risk management | Vague expectations lead to inconsistent supervision |
| **Examples** | Reg B, HMDA, Dodd-Frank 1071 | OSFI B-20 (mortgage underwriting), OSFI E-23 |

**Practical implication:** In the US, document that you met the rule. In Canada, document *why* your approach achieves the principle's objective.

---

### 1.3 Supervisory Models

#### Risk-Based Supervision (RBS)
The dominant global model. Examiners allocate resources proportionate to:
- **Probability of failure** (quality of risk management, capital, earnings)
- **Impact of failure** (size, interconnectedness, complexity)

Under RBS, a well-capitalized $500M community bank gets lighter-touch supervision than a $10B specialty lender in subprime auto — regardless of absolute size.

**The supervisory cycle under RBS:**
```
Risk Assessment → Supervisory Strategy → Examination Planning
       ↑                                           ↓
  Update Assessment ← Findings & Ratings ← Fieldwork
```

#### CAMELS Framework (US)
Used by OCC, Fed, and FDIC to rate every regulated institution 1–5 (1 = strongest):

| Component | What Examiners Evaluate |
|---|---|
| **C** — Capital Adequacy | Tier 1/Total capital ratios, RWA calculations, capital planning quality |
| **A** — Asset Quality | NPL ratios, criticized/classified loan trends, ALLL/ACL adequacy, concentration risk |
| **M** — Management | Board governance, risk appetite framework, audit function independence |
| **E** — Earnings | ROA/ROE trends, earnings sustainability, dependency on non-recurring items |
| **L** — Liquidity | LCR/NSFR compliance, contingency funding plans, deposit concentration |
| **S** — Sensitivity to Market Risk | IRR (interest rate risk), duration gaps, stress scenario performance |

A composite rating of 3+ triggers increased supervisory attention. A 4 or 5 triggers formal enforcement action consideration.

**OSFI equivalent:** BCAR (Business and Capital Adequacy Rating) for Canadian federally regulated institutions.

#### Stress Testing Regimes

| Program | Regulator | Applicability | Cadence |
|---|---|---|---|
| **CCAR** (Comprehensive Capital Analysis & Review) | Federal Reserve | BHCs with $100B+ assets | Annual |
| **DFAST** (Dodd-Frank Act Stress Test) | Fed/OCC/FDIC | $10B+ banks | Annual (supervisory), semi-annual phased out for smaller |
| **OSFI ICAAP** | OSFI | All D-SIBs and large FIs | Annual self-assessment |
| **EBA Stress Tests** | EBA/ECB | EU banks | Biennial |
| **IMF FSAP** | IMF | Member countries (voluntary) | ~5 years |

---

## SECTION 2: Core Knowledge Areas — Module-by-Module Breakdown

---

### MODULE 1: Credit Risk

**Depth Level Required:** Expert (this is the highest-scrutiny area for most lenders)

**Key Regulations/Documents:**
- OCC Comptroller's Handbook: *Loan Portfolio Management* (LPM), *Credit Risk Management*
- OCC Banking Bulletin 2020-62: *Sound Practices for Model Risk Management in Retail Credit*
- FDIC FIL-13-2015: *Prudent Risk Management for Commercial Real Estate Lending*
- SR 11-7 (Federal Reserve): Model Risk Management guidance
- CECL (ASC 326): Current Expected Credit Loss — effective for most institutions
- IFRS 9: International equivalent (3-stage ECL model)
- OSFI B-20: Residential Mortgage Underwriting Practices
- OSFI B-21: Residential Mortgage Insurance (mortgage insurers)

**Real-World Exam Application:**
Examiners will:
1. Pull a random loan sample (typically 10–30% of portfolio by dollar, 100% of criticized/classified)
2. Re-underwrite each loan to verify policy compliance
3. Test risk rating accuracy — do internal ratings match examiner assessment?
4. Assess concentration limits — are you monitoring and reporting on them?
5. Evaluate the ALLL/ACL: Is it methodologically sound? Are qualitative adjustments documented?

**Common Failure Points:**
- Risk ratings that are stale (not updated as conditions deteriorated)
- Exceptions to policy undocumented or uncollateralized
- Exception tracking not reported to board
- ACL that is systemically under-reserved (will result in MRA and potential restatement)
- Concentration limits set but never enforced or reported

---

### MODULE 2: Model Risk Management (SR 11-7)

**This is often the #1 source of MRAs at fintechs and mid-market lenders.**

**Key Documents:**
- SR 11-7 / OCC 2011-12: *Supervisory Guidance on Model Risk Management*
- OSFI E-23: *Model Risk Management*
- SR 15-18: Vendor/third-party model risk

**The Model Risk Lifecycle (what examiners audit):**

```
Development → Validation → Approval → Implementation →
    Monitoring → Change Management → Retirement
```

**What "good" looks like:**
- Independent validation (not the developer)
- Documented conceptual soundness
- Outcome analysis (backtesting, benchmarking)
- Monitoring reports with pre-defined triggers for review/revalidation
- Inventory of all models with risk tiering
- Third-party model reliance documented (vendor models are NOT exempt)

**What "bad" looks like:**
- "The vendor validates it" → NOT acceptable
- Model has been live 3 years without revalidation
- No monitoring reports
- Conceptual soundness section is one paragraph
- No documented approval by MRM committee

**CECL-specific model exam focus:**
- Segmentation rationale documented
- Macroeconomic scenario selection methodology
- Qualitative factor overlays: are they disciplined or just management judgment with no framework?

---

### MODULE 3: Compliance (KYC/AML, Fair Lending, UDAAP)

**Key Regulations:**
- Bank Secrecy Act (BSA) + FinCEN rules
- PATRIOT Act Section 326 (CIP)
- FFIEC BSA/AML Examination Manual (THE primary reference)
- ECOA (Reg B) + Fair Housing Act → Fair Lending
- HMDA (Reg C) → Mortgage data reporting
- UDAAP (Dodd-Frank Section 1031) + UDAP (FTC Act Section 5)
- FINTRAC Proceeds of Crime Act (Canada)

**BSA/AML Exam — What They Actually Test:**
1. Customer Identification Program (CIP) completeness
2. Customer Due Diligence (CDD) and Beneficial Ownership (BO) documentation
3. Enhanced Due Diligence (EDD) for high-risk customers
4. Transaction monitoring: Are SAR/CTR filings timely and complete?
5. Training program effectiveness
6. Independent BSA audit function

**Fair Lending — Statistical Red Flags Examiners Look For:**
- Disparate impact in approval rates (HMDA analysis)
- Pricing disparities by protected class even after controlling for risk
- Redlining patterns in marketing or branching
- "BISG" proxy analysis when race/ethnicity not self-reported

**UDAAP Exam Focus:**
- Are disclosures clear, conspicuous, and non-misleading?
- Do actual product terms match marketing?
- Complaint management: Is there a root cause analysis process?
- For fintechs: Are your algorithms creating disparate outcomes even without intent?

---

### MODULE 4: Capital Adequacy (Basel I/II/III/IV)

| Framework | Core Innovation | Key Ratios |
|---|---|---|
| **Basel I** | Standardized RWA buckets | 8% total capital to RWA |
| **Basel II** | Internal ratings-based (IRB) approaches; operational risk capital | Tier 1 + Tier 2 ratios |
| **Basel III** | CET1 requirement; LCR/NSFR liquidity standards; leverage ratio; G-SIB surcharge | CET1 ≥ 4.5%; Tier 1 ≥ 6%; Total ≥ 8%; Leverage ≥ 3% |
| **Basel IV / CRR3** | Output floor (72.5% of standardized); revised operational risk; revised credit risk SA | Full implementation 2025–2028 |

**US Implementation Note:** The US has NEVER fully adopted Basel II IRB for community/mid-size banks. US modified Basel III (Collins Amendment) floors capital at standardized approaches. The "Basel III Endgame" NPR (2023) proposed significant changes for $100B+ banks.

**What Examiners Check:**
- RWA calculation accuracy (is the bank correctly risk-weighting assets?)
- Capital planning: Does it reflect stress scenarios, not just base case?
- Dividend/distribution policies aligned with capital buffers
- Capital Conservation Buffer (CCB) of 2.5% above minimum — if breached, distributions restricted

---

### MODULE 5: Liquidity Risk (LCR / NSFR)

**Key Documents:**
- 12 CFR Parts 249 (LCR) and 252 (NSFR) — US rules
- OSFI LAR Guideline (Liquidity Adequacy Requirements)
- Basel III: *Basel III: The Liquidity Coverage Ratio and Liquidity Risk Monitoring Tools* (2013)

**LCR:** High-quality liquid assets (HQLA) ÷ Net cash outflows over 30-day stress scenario ≥ 100%

**NSFR:** Available stable funding (ASF) ÷ Required stable funding (RSF) ≥ 100%

**What Examiners Look For Beyond Ratios:**
- Intraday liquidity monitoring
- Contingency Funding Plan (CFP): Is it actionable? Has it been tested?
- Concentration of funding sources (e.g., 60% brokered deposits is a red flag)
- Interconnectedness with parent/subsidiary liquidity

---

### MODULE 6: Operational Risk & Governance

**Key Frameworks:**
- Basel II/III: Basic Indicator, Standardized, Advanced Measurement Approaches
- Basel IV: Standardized Measurement Approach (replaces AMA)
- OCC: *Corporate and Risk Governance* booklet
- OSFI E-21: *Operational Risk Management*

**Governance Artifacts Examiners Review:**
- Board Risk Committee charter and minutes
- Risk Appetite Statement (RAS) — must be quantified, not aspirational
- Three Lines of Defense model documentation
- Internal Audit independence and scope
- Concentration risk limits and escalation protocols

---

## SECTION 3: Study Plan — Beginner to Expert

### Phase 1: Foundation (Days 1–30)

| Priority | Resource | Focus |
|---|---|---|
| 1 | OCC Comptroller's Handbook — *Introduction* | Supervisory philosophy, examination process |
| 2 | FFIEC BSA/AML Exam Manual (Chapters 1-5) | Compliance fundamentals |
| 3 | Federal Reserve SR letters index | Understand the SR letter system |
| 4 | Basel III Summary Document (BIS website) | Capital/liquidity basics |
| 5 | FDIC: *FDIC Law, Regulations, Related Acts* | Regulatory authority understanding |
| 6 | OSFI Supervisory Framework | Canadian approach |

**Exercises:**
- Download 5 recent OCC enforcement actions (consent orders) and map each finding to a specific regulatory requirement
- Read CFPB supervisory highlights (published quarterly)

### Phase 2: Depth (Days 31–90)

| Module | Resource | Output |
|---|---|---|
| Credit Risk | OCC LPM Handbook + CECL ASU 2016-13 | Write a sample ACL methodology memo |
| Model Risk | SR 11-7 full text + OCC 2011-12 | Build a model inventory template |
| Fair Lending | CFPB Fair Lending Guide + Reg B text | Conduct a mock HMDA analysis |
| Capital | BIS Basel III text (Chapters 1-4) | Map your institution's RWA calculation |
| Liquidity | 12 CFR 249 + OSFI LAR | Draft a 1-page CFP summary |

### Phase 3: Expert (Months 3–6)

- Read 20+ enforcement actions end-to-end (OCC, CFPB, FDIC enforcement databases are public)
- Study CCAR/DFAST public results and stress test disclosures
- Obtain one certification (ranked by ROI for this path):
  1. **CAMS** (Certified Anti-Money Laundering Specialist) — immediate credibility for BSA/AML
  2. **FRM** (Financial Risk Manager) — quantitative risk credibility
  3. **CRC** (Certified Regulatory Compliance Manager) — ABA-offered, US-focused
  4. **CFA** — relevant for market/credit risk depth, not exam-specific

**Case Studies to Prioritize:**
- Wells Fargo cross-selling consent order (2016/2018) — governance failure
- Capital One cybersecurity enforcement (2020) — operational risk, third-party
- Citibank model risk MRA disclosures — model governance
- TD Bank BSA enforcement action (2024) — largest BSA penalty in US history
- Silvergate/SVB failures (2023) — liquidity risk and IRR blind spots

---

## SECTION 4: The Real Examination Process (Regulator POV)

### Step 1: Pre-Exam Planning (3–6 weeks before arrival)

**What the examiner team does:**
- Review prior exam report and any open MRAs/MRIAs
- Analyze Call Report (FFIEC 031/041) trends — looking for anomalies
- Review HMDA LAR, CRA data, complaint data
- Identify areas of elevated risk based on peer analytics
- Assign examiner team by specialty (credit, compliance, IT, capital)

**Internal examiner discussion:**
> "Their classified loan ratio jumped 40bps QoQ, but their ACL coverage ratio stayed flat. We're going to focus the credit module on reserve adequacy."

### Step 2: Information Request (Pre-Exam Data Call)

Issued 2–4 weeks before exam start. A typical data call requests:

```
☐ Loan trial balance, segmented by type, risk rating, accrual status
☐ Criticized/classified loan detail (loan-level)
☐ ALLL/ACL methodology documentation
☐ Credit policy (current, board-approved version)
☐ Exception tracking reports (last 4 quarters)
☐ Large loan listing ($1M+)
☐ Concentration reports (current + 4 quarters)
☐ Organizational chart and management bios
☐ Board and committee minutes (12 months)
☐ Internal audit reports (credit, compliance, IT)
☐ Capital adequacy analysis / ICAAP
☐ Liquidity stress test and CFP
☐ Model inventory and last validation reports
```

**Examiner mindset on the data call:**
> "If they respond late, incomplete, or with documents that look created for the exam — we start flagging governance issues immediately."

### Step 3: Onsite / Remote Examination

**Modern reality:** Since 2020, much supervision is hybrid. Fully remote exams are now common for community FIs.

**Day 1 — Entrance Meeting:**
- Examiner presents scope and schedule
- Management presents the institution's current risk profile
- Examiner is already forming impressions of management competence

**Examiner Sampling Approach — Credit:**
- Pull entire criticized/classified population (100%)
- Random sample of pass-rated loans (risk-stratified by size and type)
- Targeted sample in identified risk areas (e.g., CRE if concentration is >300% of capital)

**What examiners actually read in a loan file:**
1. Credit memo — who approved it and when
2. Financial analysis — were spreading templates used consistently?
3. Collateral documentation — current appraisal, lien position confirmed
4. Covenant compliance — are covenants being monitored and documented?
5. Risk grade assignment — does it match the facts in the file?
6. Exception log — are waivers formally documented and approved?

### Step 4: Issue Identification & Escalation

**Internal examiner hierarchy:**
```
Finding (minor, process)
   → Recommendation (no rating impact)
   → Matter Requiring Attention (MRA) — must be formally addressed
   → Matters Requiring Immediate Attention (MRIA) — urgent safety/soundness
   → Formal Action (Consent Order, MOU, Cease & Desist)
```

**Examiner escalation trigger examples:**
- ACL appears understated by >10% of pre-tax income → MRIA
- BSA program has no independent testing → MRA
- Model in production, no validation in 3+ years → MRA
- Board not receiving risk concentration reports → MRA

### Step 5: Examiner Write-Up — Anatomy of an MRA

A well-crafted MRA contains exactly:

1. **Condition:** What did we find? (factual, specific, quantified)
2. **Criteria:** What rule/guidance/best practice was violated?
3. **Cause:** Why did this happen? (root cause, not symptom)
4. **Effect:** What is the risk impact?
5. **Recommendation:** What must management do?

**Example MRA — Model Risk:**
> *Condition:* The institution's CECL PD model (Model ID: CECL-01) was implemented in Q1 2022; no independent validation has been conducted as of the examination date. The model produces the institution's allowance for credit losses, which was $4.2M as of 12/31/2023.
>
> *Criteria:* SR 11-7 and OCC 2011-12 require that new models be subject to independent validation prior to first use and periodically thereafter.
>
> *Cause:* Management stated that internal validation resources were insufficient and the project was deprioritized following implementation.
>
> *Effect:* The institution cannot demonstrate the model is fit-for-purpose, creating reputational, financial, and regulatory risk. ACL accuracy is unverifiable.
>
> *Recommendation:* Complete an independent validation by [date 90 days out]. Establish a formal model validation policy with defined revalidation triggers and timelines.

### Step 6: Final Report & CAMELS Ratings

- Draft report shared with management (typically 45–90 days post-exam)
- Management has opportunity to respond to findings
- Composite CAMELS rating assigned
- Rating is CONFIDENTIAL — the institution cannot publish it

**Rating consequences:**

| Rating | Supervisory Response |
|---|---|
| 1-2 | Normal supervision cycle |
| 3 | Increased monitoring, possible informal action (Commitment Letter, Board Resolution) |
| 4 | Formal action likely (Consent Order, MOU), restricted activities |
| 5 | Imminent failure — FDIC receivership planning, capital injection required |

### Step 7: Enforcement Actions

Public enforcement actions (OCC, FDIC, CFPB databases) include:
- **Formal Agreement** — binding, public, requires corrective action
- **Consent Order** — most common formal action; enforceable in federal court
- **Cease and Desist** — severe; can restrict all activities
- **Civil Money Penalty (CMP)** — financial penalty, often combined with above
- **Individual MMA** — action against specific officers/directors

---

## SECTION 5: Data & Documentation Expectations

### 5.1 Loan-Level Data Schema (Examiner Minimum Expectations)

```
LOAN DETAIL FILE — REQUIRED FIELDS

Identification:
  - loan_id (unique, stable)
  - origination_date
  - maturity_date
  - loan_type (commercial, consumer, CRE, C&I, etc.)
  - product_code

Borrower:
  - borrower_id
  - borrower_name (or encrypted token for privacy)
  - geography (MSA, state)
  - industry_code (NAICS)

Financials:
  - original_balance
  - current_outstanding_balance
  - committed_amount (lines of credit)
  - unfunded_commitment

Risk:
  - internal_risk_rating (1-10 or equivalent)
  - regulatory_classification (Pass, Special Mention, Substandard, Doubtful, Loss)
  - days_past_due
  - accrual_status (accruing / nonaccrual)
  - TDR_flag (or Modification per ASC 326)

Collateral:
  - collateral_type
  - appraised_value
  - appraisal_date
  - LTV
  - lien_position

Origination:
  - originating_officer_id
  - approval_level (committee, officer, automated)
  - exception_flags (policy exceptions at origination)
  - DTI_at_origination
  - DSCR_at_origination (commercial)

Performance:
  - specific_reserve_amount
  - charge_off_amount
  - recovery_amount
  - last_financial_review_date
  - covenant_compliance_flag
```

**"Good" vs "Bad" Data Quality:**

| Dimension | Good | Bad |
|---|---|---|
| Completeness | <1% null on required fields | >5% null on risk rating field |
| Timeliness | Risk ratings updated within policy cycle | Ratings unchanged for 18 months |
| Consistency | Risk rating definition matches policy | 20 different interpretations across officers |
| Lineage | Can trace each record to source system | No documentation of transformation logic |

---

### 5.2 Model Documentation — Regulator-Grade Structure

A complete model documentation package contains:

```
1. EXECUTIVE SUMMARY (1-2 pages)
   - Model purpose, scope, and regulatory applicability
   - Key findings from last validation
   - Current rating (High/Medium/Low risk)

2. MODEL DESCRIPTION
   - Business context and use case
   - Input variables (with data dictionary)
   - Mathematical specification (full equations)
   - Output interpretation
   - Known limitations

3. DEVELOPMENT
   - Dataset description (sample period, exclusions, rationale)
   - Variable selection methodology (statistical + judgmental)
   - Model architecture and estimation methodology
   - Benchmarking against alternative models
   - Performance metrics (Gini, AUC, KS, PSI)

4. VALIDATION (independent)
   - Conceptual soundness review
   - Data quality assessment
   - Replication of developer results
   - Out-of-time / out-of-sample testing
   - Benchmarking results
   - Outcome analysis (if sufficient performance history)
   - Findings and recommendations
   - Validator conclusion and rating

5. MODEL RISK RATING & APPROVAL
   - Risk tier assigned
   - MRM committee approval (signed minutes or memo)
   - Conditions of approval

6. IMPLEMENTATION NOTES
   - Champion/challenger setup (if applicable)
   - IT implementation sign-off
   - User access controls

7. MONITORING
   - Monitoring schedule
   - Metrics and thresholds
   - Last monitoring report date and findings
   - Revalidation triggers

8. CHANGE LOG
   - All changes since initial approval
   - Materiality assessment for each change
   - Re-validation triggered? Y/N
```

---

## SECTION 6: Structuring & Presenting for Regulators

### 6.1 The Four Pillars of Regulator-Grade Documentation

**1. Traceability** — Every decision must be traceable to data, policy, and approver
> "We can trace every credit decision to: (a) the input data used, (b) the model version that processed it, (c) the policy rule applied, (d) the human reviewer if applicable, and (e) the approval authority."

**2. Explainability** — A non-technical examiner must be able to follow the logic
> Avoid: "The model assigned a score of 742."
> Use: "The model assigned a score of 742, primarily driven by [top 3 factors with directional attribution], consistent with the borrower's [specific financial characteristics]."

**3. Reproducibility** — Results can be replicated
> Version-control everything: data snapshots, model versions, parameter files, code

**4. Auditability** — Independent verification is possible without interviewing staff
> The documentation should stand alone. If the person who built the system left tomorrow, could an examiner — or a new employee — audit it completely?

---

### 6.2 Template: Credit Decision Documentation

```
CREDIT DECISION MEMORANDUM

Institution: [Name]                    Date: [Date]
Loan ID: [ID]                          Officer: [Name/ID]
Approval Authority: [Committee/Level]  Risk Rating: [X]

─────────────────────────────────────────────────────────
CREDIT REQUEST SUMMARY
Purpose: [e.g., commercial real estate acquisition]
Amount Requested: $[X]
Term: [X months/years]
Collateral: [Type, value, LTV]
Guaranty: [Personal/corporate, guarantor financials summary]

─────────────────────────────────────────────────────────
BORROWER FINANCIAL ANALYSIS
                      Year 1    Year 2    Year 3    YTD
Revenue               $X        $X        $X        $X
EBITDA                $X        $X        $X        $X
DSCR                  X.Xx      X.Xx      X.Xx      X.Xx
Leverage (D/EBITDA)   X.Xx      X.Xx      X.Xx      X.Xx
Current Ratio         X.Xx      X.Xx      X.Xx      X.Xx

Policy minimums: DSCR ≥ 1.20x; Leverage ≤ 4.0x ✓/✗

─────────────────────────────────────────────────────────
RISK FACTORS
Strengths:
  1. [Specific, evidenced]
  2. [Specific, evidenced]
Weaknesses/Mitigants:
  1. [Risk]: [Mitigant]
  2. [Risk]: [Mitigant]

─────────────────────────────────────────────────────────
POLICY EXCEPTIONS (if any)
Exception #1: [Policy requirement] / [Actual metric] / [Mitigant] / [Approved by]

─────────────────────────────────────────────────────────
COLLATERAL ANALYSIS
Type: [Commercial RE / Equipment / A/R]
Appraised Value: $X (Appraisal date: [Date], FIRREA-compliant: Y/N)
LTV: X% (Policy max: X%) ✓/✗
Lien Position: First / Second

─────────────────────────────────────────────────────────
RISK RATING ASSIGNMENT
Assigned Rating: [X] — [Pass / Special Mention / Substandard]
Rationale: [3-5 sentences specifically referencing the rating definition
            in the Credit Policy, pages X-Y]

─────────────────────────────────────────────────────────
RECOMMENDATION
☐ Approve   ☐ Approve with Conditions   ☐ Decline
Conditions: [List any requirements prior to/after funding]
Approving Authority Signature: _____________ Date: _______
```

---

### 6.3 Template: Model Validation Report Executive Summary

```
MODEL VALIDATION REPORT — EXECUTIVE SUMMARY

Model Name:        [Name]
Model ID:          [ID]
Model Owner:       [Business line / team]
Model Use:         [Specific decision use case]
Validation Date:   [Date]
Validator:         [Name, independent of development team]
Prior Validation:  [Date or "First validation"]

VALIDATION SCOPE
☐ Conceptual Soundness
☐ Data Quality & Representativeness
☐ Replication of Developer Testing
☐ Out-of-Time/Out-of-Sample Testing
☐ Benchmarking
☐ Sensitivity Analysis
☐ Outcome Analysis (backtesting)

FINDINGS SUMMARY
Critical Findings (must be remediated before continued use): [#]
High Findings (remediated within 60 days): [#]
Medium Findings (remediated within 90 days): [#]
Low Findings (noted, remediate in next model update): [#]

MODEL RISK RATING: [High / Medium / Low]

VALIDATOR CONCLUSION:
☐ Approved for use without restrictions
☐ Approved for use with the following conditions: [list]
☐ Conditional approval — approve pending remediation of Critical findings
☐ Not approved for use until critical findings remediated

MONITORING REQUIREMENTS:
- Quarterly: PSI report, performance stability
- Annual: Full revalidation
- Triggers: PSI > 0.25, Gini decline > 5 points, portfolio composition shift > 15%
```

---

## SECTION 7: Common Pitfalls — Why Firms Fail Exams

### 7.1 The Gap Between Policy and Practice

**The most common finding at mid-market lenders:**
> The written credit policy says risk ratings must be updated annually. The actual practice is "when the loan is renewed." The loan renewed 2 years ago. The rating is 2 years stale.

**Real enforcement example:** A bank's written AML policy required EDD for all MSBs. Examiners found 47 MSB relationships with no EDD documentation. The written policy was excellent. The execution was absent.

**Fix:** Conduct semi-annual policy vs. practice gap assessments with audit trails.

---

### 7.2 "We Have a Model" ≠ "SR 11-7 Compliance"

Fintechs frequently assume that having a sophisticated model means they're in compliance with SR 11-7. Common specific failures:

- Using a vendor scorecard (e.g., FICO, VantageScore) without validating it on your own portfolio
- "The vendor provides documentation" — vendor documentation covers the model generally; you must validate it for YOUR specific use case
- Building a challenger model internally and deploying it without formal approval through MRM committee
- Using ML/AI models with no feature attribution or explainability layer

---

### 7.3 Governance Theater

**Signs of governance theater (examiners know this immediately):**
- Board Risk Committee minutes that are identical across 4 quarters (copy-paste with dates changed)
- Risk Appetite Statement with only qualitative language ("we avoid excessive risk") — no quantified limits
- Risk limits that have been in breach for 6+ months with no board action documented
- Three Lines of Defense documented on paper, but the second line reports to the same business head they're supposed to be overseeing

---

### 7.4 Data Lineage Failures

Examiners now routinely ask: *"Show me how this number in your ALLL methodology gets from your origination system to this reserve amount."*

If the answer involves a manual Excel workbook maintained by one person — that is both an operational risk finding and a data governance finding.

---

### 7.5 Black Box Decisioning

**CFPB and OCC are actively examining this:**
- If your credit decisioning model cannot produce adverse action reason codes that are specific and accurate to the actual model output — you have a UDAAP/ECOA exposure
- "Algorithm said no" is not a permissible adverse action reason under Reg B
- Explainability is no longer a best practice; it is a regulatory expectation

**Real case:** In 2023, a CFPB supervisory examination found that a fintech's adverse action reason codes were drawn from a generic lookup table, not from the actual model explanations. The actual model drivers were different from what was disclosed to applicants. Result: ECOA violation.

---

## SECTION 8: Building a Regulator-Ready System

### 8.1 The Regulatory Acceptance Checklist

```
CREDIT PLATFORM — REGULATORY ACCEPTANCE CHECKLIST

╔══════════════════════════════════════════════════════╗
║  MODEL RISK MANAGEMENT                               ║
╠══════════════════════════════════════════════════════╣
║ ☐ Model inventory maintained with risk tiers        ║
║ ☐ All models independently validated at launch      ║
║ ☐ Validation reports stored and retrievable         ║
║ ☐ Monitoring reports automated, not manual          ║
║ ☐ Revalidation triggers defined and enforced        ║
║ ☐ Vendor models validated for YOUR portfolio        ║
║ ☐ Model change management process documented        ║
╠══════════════════════════════════════════════════════╣
║  AUDIT TRAIL & DATA GOVERNANCE                       ║
╠══════════════════════════════════════════════════════╣
║ ☐ Every decision logged with timestamp              ║
║ ☐ Input data snapshot stored per decision           ║
║ ☐ Model version at time of decision recorded        ║
║ ☐ Policy version at time of decision recorded       ║
║ ☐ Human override capability with required reason    ║
║ ☐ Override tracking and reporting                   ║
║ ☐ Data lineage documented from source to output     ║
╠══════════════════════════════════════════════════════╣
║  EXPLAINABILITY & ADVERSE ACTION                     ║
╠══════════════════════════════════════════════════════╣
║ ☐ Model produces feature attribution per decision   ║
║ ☐ Adverse action codes derived from actual model    ║
║ ☐ Reason code accuracy backtested                   ║
║ ☐ SHAP/LIME or equivalent framework implemented     ║
╠══════════════════════════════════════════════════════╣
║  FAIR LENDING & COMPLIANCE                           ║
╠══════════════════════════════════════════════════════╣
║ ☐ Disparate impact testing automated and logged     ║
║ ☐ BISG proxy analysis for monitoring                ║
║ ☐ HMDA-reportable field population complete         ║
║ ☐ Denial reason compliance with Reg B               ║
╠══════════════════════════════════════════════════════╣
║  GOVERNANCE INFRASTRUCTURE                           ║
╠══════════════════════════════════════════════════════╣
║ ☐ Risk appetite limits defined and monitored        ║
║ ☐ Concentration reports generated and distributed   ║
║ ☐ Exception tracking with escalation workflow       ║
║ ☐ Board-level reporting automated                   ║
║ ☐ Three-lines-of-defense roles enforced in system   ║
╠══════════════════════════════════════════════════════╣
║  VERSION CONTROL & REPRODUCIBILITY                   ║
╠══════════════════════════════════════════════════════╣
║ ☐ All model artifacts version-controlled (git)      ║
║ ☐ Policy rules version-controlled in system         ║
║ ☐ Historical decisions reproducible from logs       ║
║ ☐ Environment reproducibility (containers/IaC)      ║
╠══════════════════════════════════════════════════════╣
║  VENDOR / THIRD-PARTY RISK                          ║
╠══════════════════════════════════════════════════════╣
║ ☐ Third-party risk assessment on all critical       ║
║   technology vendors                                ║
║ ☐ Contracts include audit rights                    ║
║ ☐ SLAs documented and monitored                     ║
║ ☐ Exit plans documented for critical vendors        ║
╚══════════════════════════════════════════════════════╝
```

### 8.2 Mapping to a Governance-Native Credit Platform

| Regulatory Expectation | Platform Feature |
|---|---|
| SR 11-7: Model inventory with risk tiers | `ModelRegistry` with `risk_tier` field, validation status, last validation date, revalidation trigger |
| CECL monitoring | Automated PSI/CSI reports; threshold breach alerts; drift detection |
| Adverse action Reg B compliance | Decision explanation engine generating regulatory-defensible reason codes from SHAP values |
| Fair lending monitoring | Post-decision disparate impact analysis pipeline with demographic proxy variables |
| Data lineage | Immutable decision log: input snapshot + model version + policy version per decision |
| Audit trail | Append-only log store (no deletes), role-based access, exportable for examiner data calls |
| Board reporting | Automated risk dashboards with period-over-period comparison and limit breach alerting |
| Override governance | Override requires coded reason + supervisor approval + documented in log |

---

## SECTION 9: Simulation & Practice

### 9.1 Mock Audit Scenario #1 — Community Bank Credit Exam

**Scenario:** You are the Chief Credit Officer of a $750M community bank. An OCC examination has begun. The examiner has requested your classified loan list and has selected 12 loans for review, including 3 classified loans and 9 pass-rated loans.

**Examiner Questions — Prepare Answers For:**
1. *"Walk me through how this loan received a Pass rating when DSCR is 0.98x and has been below 1.0x for six consecutive quarters."*
2. *"Your policy requires annual financial spreading. This credit has no updated financials since origination in 2022. Who is responsible for monitoring this?"*
3. *"I see this credit was approved with an LTV of 85% versus your 75% policy maximum. Where's the documented exception approval, and has it been tracked in your exception log?"*
4. *"Your ALLL methodology shows a general reserve factor of 1.2% for CRE. How was that factor derived, and when was it last recalibrated?"*

**Self-score:** Can you answer each question with documented evidence, not just verbal explanation?

---

### 9.2 Mock Audit Scenario #2 — Fintech Model Risk Exam

**Scenario:** A fintech lender's first OCC supervisory examination. You built a proprietary ML-based credit scoring model 18 months ago with a third-party vendor.

**Examiner Questions:**
1. *"Where is your model validation report for this model?"*
2. *"You're using the vendor's model — did you validate it on your own origination data?"*
3. *"Show me a sample adverse action notice and explain how the reason codes were generated from the model's actual output."*
4. *"What's your current PSI? What would trigger a revalidation?"*
5. *"Who approved this model for production use? Can you show me the committee minutes?"*

---

### 9.3 "Think Like a Regulator" Exercises

**Exercise 1 — Red Flag Identification:**
Review your own portfolio data. Flag any:
- Loans with ratings unchanged for >12 months
- Loans with DSCR <1.0x rated Pass
- Loans 30+ DPD rated Pass or Special Mention only

**Exercise 2 — Policy-Practice Gap Assessment:**
Take your top 5 credit policy requirements. Pull a sample of 20 loans. Test each loan for compliance with each requirement. Calculate compliance rate. If <95% on any requirement — that is an exam finding.

**Exercise 3 — Regulator's First 30 Minutes:**
Imagine a regulator gets your entire data package. Without talking to anyone, what would they flag as concerning in the first 30 minutes? Do that analysis on yourself quarterly.

---

## SECTION 10: Securing Regulatory Approval

### 10.1 Model Risk Approval Process

```
STAGE 1: Pre-Development
  ☐ Define material use cases and user populations
  ☐ Identify applicable regulations (ECOA, CRA, BSA, etc.)
  ☐ Document intended model scope and limitations
  ↓
STAGE 2: Development
  ☐ Document development decisions (variable selection, data exclusions)
  ☐ Benchmark against alternatives
  ☐ Performance testing in-sample and out-of-sample
  ↓
STAGE 3: Independent Validation
  ☐ Assign validator with no development involvement
  ☐ Complete validation report with all findings
  ☐ Critical findings remediated before proceeding
  ↓
STAGE 4: MRM Committee Approval
  ☐ Validation report presented to committee
  ☐ Approval documented in signed minutes
  ☐ Conditions of approval recorded
  ↓
STAGE 5: Implementation
  ☐ IT sign-off on implementation fidelity
  ☐ Champion/challenger setup if required
  ☐ Monitoring framework activated
  ↓
STAGE 6: Ongoing
  ☐ Quarterly monitoring reports distributed
  ☐ Annual revalidation scheduled
  ☐ Change management process for any adjustments
```

### 10.2 Regulatory Sandboxes

| Jurisdiction | Program | What It Offers |
|---|---|---|
| **US — OCC** | Innovation Pilot Program | Engagement with OCC innovation staff; no formal approval but informal feedback |
| **US — CFPB** | No-Action Letter (NAL) | CFPB commits not to bring supervisory action on specific product feature while data is collected |
| **US — CFPB** | Trial Disclosure Program | Test alternative disclosures in live market |
| **Canada — FCAC** | Financial Innovation Hub | Dialogue forum; not a formal sandbox |
| **Canada — OSFI** | Innovation Engagement | In-writing consultation on novel approaches |
| **UK — FCA** | Regulatory Sandbox | Full live testing with regulatory waivers |
| **Singapore — MAS** | FinTech Regulatory Sandbox | Live testing with legal relaxation |
| **EU — EBA** | Innovation Hubs Network | Cross-border coordination |

**Practical US Sandbox Strategy for a Credit Platform:**

1. **Engage OCC Innovation Office early** — before building, not after. Document the conversation.
2. **Apply for a CFPB No-Action Letter** if your model uses alternative data — this provides temporary protection while you establish a track record
3. **Partner with a regulated bank** — operate under their charter (BaaS model) and absorb their regulatory infrastructure initially
4. **Pursue pre-submission meetings** with state regulators before launching in new states (especially California DBO, New York DFS, and Texas DOB which have the most active fintech supervision)

### 10.3 Proactive Regulator Engagement — Best Practices

**What works:**
- **Transparency over perfection.** Regulators respect institutions that identify problems themselves before being told. Self-identification of issues and credible remediation plans are viewed far more favorably than issues the examiner discovers.
- **Pre-examination briefings.** Offer the examiner team a voluntary briefing on material changes since the last exam — new products, new models, new leadership. This sets your narrative.
- **Written commitments with milestones.** When you have an open MRA, don't wait for the exam to show progress. Send quarterly status updates proactively.
- **Hire exam-experienced staff.** Nothing signals institutional seriousness like hiring former examiners or regulatory staff. They know the language, the expectations, and what "good" actually looks like.

**What doesn't work:**
- Legalistic responses to MRAs ("We believe we are in compliance because...") — regulators view this as combative
- Sweeping documentation creation after the data call arrives (examiners date-check document metadata)
- Over-lawyering the entrance meeting
- Blaming prior management for findings — own it, remediate it, prevent recurrence

---

## Quick Reference: Regulator-Grade Language Glossary

| Term | Definition |
|---|---|
| **MRA** | Matter Requiring Attention — examiner finding requiring corrective action |
| **MRIA** | Matter Requiring Immediate Attention — urgent safety/soundness concern |
| **Criticized assets** | Special Mention + Substandard + Doubtful + Loss loans |
| **Classified assets** | Substandard + Doubtful + Loss (subset of criticized) |
| **ALLL / ACL** | Allowance for Loan and Lease Losses / Allowance for Credit Losses (CECL-era term) |
| **RWA** | Risk-Weighted Assets — denominator of capital ratios |
| **CET1** | Common Equity Tier 1 capital — highest quality capital |
| **LCR** | Liquidity Coverage Ratio — 30-day stress liquidity buffer |
| **HQLA** | High-Quality Liquid Assets — LCR numerator |
| **DSCR** | Debt Service Coverage Ratio — key commercial underwriting metric |
| **IRR** | Interest Rate Risk — sensitivity of earnings/capital to rate changes |
| **PSI** | Population Stability Index — measures input distribution shift in models |
| **BISG** | Bayesian Improved Surname Geocoding — proxy for race/ethnicity in fair lending |
| **TDR** | Troubled Debt Restructuring (replaced under ASC 326 by "modified loan") |
| **MRM** | Model Risk Management |
| **Three Lines** | 1st: business (owns risk), 2nd: risk/compliance (oversees), 3rd: audit (assures) |
| **CAMELS** | Capital, Assets, Management, Earnings, Liquidity, Sensitivity |
| **BHC** | Bank Holding Company |
| **D-SIB** | Domestic Systemically Important Bank |
| **G-SIB** | Global Systemically Important Bank |
