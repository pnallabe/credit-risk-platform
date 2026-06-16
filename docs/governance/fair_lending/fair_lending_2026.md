---
doc_type: fair_lending
report_year: 2026
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2026

**Report Period:** January 1, 2026 – December 31, 2026
**Report Date:** April 30, 2027
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2026)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 12,600 | 70.0% |
| Approved, Not Accepted | 720 | 4.0% |
| Application Denied | 6,300 | 35.0% |
| Application Withdrawn | 1,440 | 8.0% |
| File Closed Incomplete | 360 | 2.0% |
| **Total Applications** | **18,000** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 12,960 | 9,072 |
| Multifamily (5+ units) | 1,800 | 1,008 |
| Manufactured Home | 1,440 | 756 |
| Condominium | 1,800 | 1,764 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 10,440 | 58% |
| Refinance | 5,400 | 30% |
| Cash-Out Refinance | 2,160 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 11,160 | 7,616 | 68.3% | 1.000 | ✓ Control |
| Hispanic | 2,700 | 1,621 | 60.1% | 0.880 | ✓ |
| Black / African-American | 2,160 | 1,253 | 58.0% | 0.850 | ✓ |
| Asian | 1,440 | 953 | 66.2% | 0.970 | ✓ |
| Female Applicant | 8,100 | 5,251 | 64.8% | 0.950 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +10 bps | +6 bps | p = 0.39 | ✓ Not significant |
| Black / African-American | +11 bps | +8 bps | p = 0.32 | ✓ Within threshold |
| Female | +5 bps | +3 bps | p = 0.49 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2026 Status:** No investigation threshold exceeded.

---

## 4. Statistical Methodology

### Regression Model

**Dependent variable:** Note rate (APR) at origination
**Independent variables:**
- FICO score (continuous + squared term)
- DTI ratio (continuous)
- LTV at origination (continuous + interaction with loan purpose)
- Loan amount (log-transformed)
- Loan purpose (purchase / refi / cash-out — fixed effects)
- Property type (fixed effects)
- Channel (online / branch / partner / mobile — fixed effects)
- State (fixed effects)
- Origination month (year-quarter fixed effects)
- Demographic group (indicator variables — coefficients of interest)

**Redlining Analysis:** Geographic concentration analysis performed at census tract level.
Proportion of applications in majority-minority tracts compared to market benchmarks
using HMDA peer data. No redlining concerns identified.

**Intersectional Analysis:** Interaction terms tested for gender × race × income level.
No significant intersectional disparities identified.

---

## 5. Disparate Impact Findings

**2026 Overall Assessment:** No disparities. Expansion cycle. AIR metrics at multi-year highs.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2027
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
