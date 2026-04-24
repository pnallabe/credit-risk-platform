---
doc_type: fair_lending
report_year: 2025
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2025

**Report Period:** January 1, 2025 – December 31, 2025
**Report Date:** April 30, 2026
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2025)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 11,340 | 70.0% |
| Approved, Not Accepted | 648 | 4.0% |
| Application Denied | 6,156 | 38.0% |
| Application Withdrawn | 1,296 | 8.0% |
| File Closed Incomplete | 324 | 2.0% |
| **Total Applications** | **16,200** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 11,664 | 8,164 |
| Multifamily (5+ units) | 1,620 | 907 |
| Manufactured Home | 1,296 | 680 |
| Condominium | 1,620 | 1,587 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 9,396 | 58% |
| Refinance | 4,860 | 30% |
| Cash-Out Refinance | 1,944 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 10,044 | 6,538 | 65.1% | 1.000 | ✓ Control |
| Hispanic | 2,430 | 1,376 | 56.6% | 0.870 | ✓ |
| Black / African-American | 1,944 | 1,063 | 54.7% | 0.840 | ✓ |
| Asian | 1,296 | 818 | 63.1% | 0.970 | ✓ |
| Female Applicant | 7,290 | 4,461 | 61.2% | 0.940 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +11 bps | +7 bps | p = 0.38 | ✓ Not significant |
| Black / African-American | +12 bps | +9 bps | p = 0.31 | ✓ Within threshold |
| Female | +6 bps | +4 bps | p = 0.48 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2025 Status:** No investigation threshold exceeded.

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

**2025 Overall Assessment:** No disparities. Easing cycle improving affordability across all groups.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2026
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
