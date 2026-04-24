---
doc_type: fair_lending
report_year: 2023
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2023

**Report Period:** January 1, 2023 – December 31, 2023
**Report Date:** April 30, 2024
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2023)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 7,560 | 70.0% |
| Approved, Not Accepted | 432 | 4.0% |
| Application Denied | 4,644 | 43.0% |
| Application Withdrawn | 864 | 8.0% |
| File Closed Incomplete | 216 | 2.0% |
| **Total Applications** | **10,800** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 7,776 | 5,443 |
| Multifamily (5+ units) | 1,080 | 604 |
| Manufactured Home | 864 | 453 |
| Condominium | 1,080 | 1,058 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 6,264 | 58% |
| Refinance | 3,240 | 30% |
| Cash-Out Refinance | 1,296 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 6,696 | 4,007 | 59.9% | 1.000 | ✓ Control |
| Hispanic | 1,620 | 824 | 50.9% | 0.850 | ✓ |
| Black / African-American | 1,296 | 636 | 49.1% | 0.820 | ✓ |
| Asian | 864 | 501 | 58.1% | 0.970 | ✓ |
| Female Applicant | 4,860 | 2,705 | 55.7% | 0.930 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +13 bps | +9 bps | p = 0.36 | ✓ Not significant |
| Black / African-American | +14 bps | +11 bps | p = 0.29 | ✓ Within threshold |
| Female | +8 bps | +6 bps | p = 0.46 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2023 Status:** No investigation threshold exceeded.

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

**2023 Overall Assessment:** High-rate environment continues. No disparities. CRA assessment: satisfactory.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2024
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
