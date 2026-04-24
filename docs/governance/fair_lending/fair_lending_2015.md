---
doc_type: fair_lending
report_year: 2015
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2015

**Report Period:** January 1, 2015 – December 31, 2015
**Report Date:** April 30, 2016
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2015)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 8,960 | 70.0% |
| Approved, Not Accepted | 512 | 4.0% |
| Application Denied | 3,840 | 30.0% |
| Application Withdrawn | 1,024 | 8.0% |
| File Closed Incomplete | 256 | 2.0% |
| **Total Applications** | **12,800** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 9,216 | 6,451 |
| Multifamily (5+ units) | 1,280 | 716 |
| Manufactured Home | 1,024 | 537 |
| Condominium | 1,280 | 1,254 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 7,423 | 58% |
| Refinance | 3,840 | 30% |
| Cash-Out Refinance | 1,536 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 7,936 | 5,832 | 73.5% | 1.000 | ✓ Control |
| Hispanic | 1,920 | 1,241 | 64.7% | 0.880 | ✓ |
| Black / African-American | 1,536 | 937 | 61.0% | 0.830 | ✓ |
| Asian | 1,024 | 730 | 71.3% | 0.970 | ✓ |
| Female Applicant | 5,760 | 3,979 | 69.1% | 0.940 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +10 bps | +6 bps | p = 0.28 | ✓ Not significant |
| Black / African-American | +11 bps | +8 bps | p = 0.21 | ✓ Within threshold |
| Female | +5 bps | +3 bps | p = 0.38 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2015 Status:** No investigation threshold exceeded.

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

**2015 Overall Assessment:** No disparities. All AIR ≥0.80. APR difference within acceptable range.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2016
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
