---
doc_type: fair_lending
report_year: 2022
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---

# Fair Lending Annual Report — 2022

**Report Period:** January 1, 2022 – December 31, 2022
**Report Date:** April 30, 2023
**Prepared By:** Fair Lending Officer
**Reviewed By:** Compliance Officer, Chief Risk Officer
**Classification:** Internal — Restricted; Regulator-ready upon request

---

## 1. HMDA LAR Summary (Mortgage — 2022)



### Application Volume by Action Taken

| Action Taken | Count | Percentage |
|---|---|---|
| Loan Originated | 8,540 | 70.0% |
| Approved, Not Accepted | 488 | 4.0% |
| Application Denied | 5,002 | 41.0% |
| Application Withdrawn | 976 | 8.0% |
| File Closed Incomplete | 244 | 2.0% |
| **Total Applications** | **12,200** | **100%** |

### Application Volume by Property Type

| Property Type | Applications | Originated |
|---|---|---|
| Single-Family (1-4 unit) | 8,784 | 6,148 |
| Multifamily (5+ units) | 1,220 | 683 |
| Manufactured Home | 976 | 512 |
| Condominium | 1,220 | 1,195 |

### Application Volume by Loan Purpose

| Purpose | Applications | % |
|---|---|---|
| Home Purchase | 7,075 | 58% |
| Refinance | 3,660 | 30% |
| Cash-Out Refinance | 1,464 | 12% |

---

## 2. Approval Rate Disparity Analysis

**Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
= minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

| Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
|---|---|---|---|---|---|
| White Non-Hispanic (control) | 7,564 | 4,685 | 62.0% | 1.000 | ✓ Control |
| Hispanic | 1,830 | 974 | 53.3% | 0.860 | ✓ |
| Black / African-American | 1,464 | 752 | 51.4% | 0.830 | ✓ |
| Asian | 976 | 586 | 60.1% | 0.970 | ✓ |
| Female Applicant | 5,490 | 3,162 | 57.6% | 0.930 | ✓ |

**Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

---

## 3. APR Pricing Disparity Analysis

**Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
effects), and origination channel.

### Mortgage APR Disparity — Regression-Adjusted Results

| Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
|---|---|---|---|---|
| Hispanic | +12 bps | +8 bps | p = 0.35 | ✓ Not significant |
| Black / African-American | +13 bps | +10 bps | p = 0.28 | ✓ Within threshold |
| Female | +7 bps | +5 bps | p = 0.45 | ✓ Not significant |

**Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
**2022 Status:** No investigation threshold exceeded.

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

**2022 Overall Assessment:** Elevated denial rates across all demographic groups due to policy tightening (rate hike cycle). No demographic-specific disparities. AIR stable vs. prior year. Rate hike cycle creates affordability challenges equally across groups.

---

## 6. Corrective Actions

No corrective actions required. No disparities identified.



---

## 7. Fair Lending Officer Sign-off

I certify that this Fair Lending Annual Report has been prepared in accordance with
ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
Examination Manual for Fair Lending.

**Fair Lending Officer:** Patricia K. Owens
**Date:** April 30, 2023
**CRO Review:** Dr. Priya Nambiar — Approved

---

*This report is prepared for internal compliance purposes and is available to regulatory
examiners upon request. Retention: 25 years (ECOA record retention requirement).*
