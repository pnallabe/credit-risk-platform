            ---
            doc_type: fair_lending
            report_year: 2019
            products_covered: [credit_card, personal_loan, mortgage]
            hmda_reporting: true
            ---

            # Fair Lending Annual Report — 2019

            **Report Period:** January 1, 2019 – December 31, 2019
            **Report Date:** April 30, 2020
            **Prepared By:** Fair Lending Officer
            **Reviewed By:** Compliance Officer, Chief Risk Officer
            **Classification:** Internal — Restricted; Regulator-ready upon request

            ---

            ## 1. HMDA LAR Summary (Mortgage — 2019)



            ### Application Volume by Action Taken

            | Action Taken | Count | Percentage |
            |---|---|---|
            | Loan Originated | 15,400 | 70.0% |
            | Approved, Not Accepted | 880 | 4.0% |
            | Application Denied | 6,600 | 30.0% |
            | Application Withdrawn | 1,760 | 8.0% |
            | File Closed Incomplete | 440 | 2.0% |
            | **Total Applications** | **22,000** | **100%** |

            ### Application Volume by Property Type

            | Property Type | Applications | Originated |
            |---|---|---|
            | Single-Family (1-4 unit) | 15,840 | 11,088 |
            | Multifamily (5+ units) | 2,200 | 1,232 |
            | Manufactured Home | 1,760 | 924 |
            | Condominium | 2,200 | 2,156 |

            ### Application Volume by Loan Purpose

            | Purpose | Applications | % |
            |---|---|---|
            | Home Purchase | 12,760 | 58% |
            | Refinance | 6,600 | 30% |
            | Cash-Out Refinance | 2,640 | 12% |

            ---

            ## 2. Approval Rate Disparity Analysis

            **Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
            = minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

            | Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
            |---|---|---|---|---|---|
            | White Non-Hispanic (control) | 13,640 | 10,025 | 73.5% | 1.000 | ✓ Control |
            | Hispanic | 3,300 | 2,037 | 61.7% | 0.840 | ⚠ Monitor |
            | Black / African-American | 2,640 | 1,571 | 59.5% | 0.810 | ⚠ Monitor |
            | Asian | 1,760 | 1,254 | 71.3% | 0.970 | ✓ |
            | Female Applicant | 9,900 | 6,767 | 68.4% | 0.930 | ✓ |

            **Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

            ---

            ## 3. APR Pricing Disparity Analysis

            **Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
            LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
            effects), and origination channel.

            ### Mortgage APR Disparity — Regression-Adjusted Results

            | Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
            |---|---|---|---|---|
            | Hispanic | +18 bps | +14 bps | p = 0.32 | ⚠ **MARGINAL FLAG — Under Investigation** |
            | Black / African-American | +19 bps | +16 bps | p = 0.25 | ⚠ **MARGINAL FLAG — Under Investigation** |
            | Female | +13 bps | +11 bps | p = 0.42 | ✓ Not significant |

            **Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
            **2019 Status:** INVESTIGATION TRIGGERED — see Section 5.

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
            using HMDA peer data. Tract-level analysis shows proportional coverage — no redlining concerns.

            **Intersectional Analysis:** Interaction terms tested for gender × race × income level.
            No significant intersectional disparities identified.

            ---

            ## 5. Disparate Impact Findings

            ### APR Disparity Investigation — 2019

**Trigger:** Regression-adjusted APR difference of 16 bps for Black/African-American
borrowers exceeded the 15 bps investigation threshold.

**Methodology:** OLS regression controlling for FICO, DTI, LTV, loan amount, loan purpose,
state, channel, and property type. Residual APR difference estimated at 16 bps
(95% CI: 12–20 bps).

**Root Cause Analysis:**
- Channel concentration: Black/African-American borrowers over-represented in broker/partner channel
  (+8 pp vs. white non-Hispanic) → broker commission adds ~12–18 bps to APR
- FICO distribution: 28% of Black/AA applicants in Near-Prime tier (620–659) vs. 19% white non-Hispanic
  → Near-Prime pricing adds 38 bps; after controlling for FICO, residual = 4 bps (non-significant)

**Conclusion:** APR difference explained by legitimate, risk-related and channel factors.
No disparate treatment. No remediation required. Enhanced monitoring implemented for 2020.

**Corrective Actions:**
1. Quarterly APR disparity report to Fair Lending Officer beginning Q1 2020
2. Broker channel compensation review — ensure no discretionary points above schedule
3. Near-Prime outreach program to improve FICO for returning applicants

**2019 Overall Assessment:** MARGINAL FLAG: APR regression-adjusted spread of 16 bps for Black/African-American borrowers. Investigation initiated Q3 2019. Root cause: concentration in Near-Prime FICO tier (620–659) → higher pricing, not discriminatory intent. No systemic disparities. Enhanced monitoring implemented.

            ---

            ## 6. Corrective Actions


            See Section 5 for investigation findings and resolution.


            ---

            ## 7. Fair Lending Officer Sign-off

            I certify that this Fair Lending Annual Report has been prepared in accordance with
            ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
            Examination Manual for Fair Lending.

            **Fair Lending Officer:** Patricia K. Owens
            **Date:** April 30, 2020
            **CRO Review:** Dr. Priya Nambiar — Approved

            ---

            *This report is prepared for internal compliance purposes and is available to regulatory
            examiners upon request. Retention: 25 years (ECOA record retention requirement).*
