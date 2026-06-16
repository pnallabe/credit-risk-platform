---
doc_type: fair_lending
report_year: 2017
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2017

**Report Period:** January 1, 2017 – December 31, 2017
**Report Date:** April 30, 2018
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2017)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 13,020 | 70.0% |
| Approved, Not Accepted | 744 | 4.0% |
| Application Denied | 5,580 | 30.0% |
| Application Withdrawn | 1,488 | 8.0% |
| File Closed Incomplete | 372 | 2.0% |
| **Total Applications** | **18,600** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 13,392 | 9,374 |
| Multifamily (5+ units) | 1,860 | 1,041 |
| Manufactured Home | 1,488 | 781 |
| Condominium | 1,860 | 1,822 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 10,788 | 58% |
| Refinance | 5,580 | 30% |
| Cash-Out Refinance | 2,232 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 11,532 | 8,476 | 73.5% | 1.000 | ✓ Control |
| Hispanic | 2,790 | 1,763 | 63.2% | 0.860 | ✓ |
| Black / African-American | 2,232 | 1,328 | 59.5% | 0.810 | ⚠ Monitor |
| Asian | 1,488 | 1,060 | 71.3% | 0.970 | ✓ |
| Female Applicant | 8,370 | 5,721 | 68.4% | 0.930 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +13 bps | +9 bps | p = 0.30 | ✓ Not significant |
| Black / African-American | +14 bps | +11 bps | p = 0.23 | ✓ Within threshold |
| Female | +8 bps | +6 bps | p = 0.40 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2017 Status:** No investigation threshold exceeded.

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

**2017 Overall Assessment:** No disparities. Minor APR variance on Hispanic segment — investigated, explained by FICO/LTV mix.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2018
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
