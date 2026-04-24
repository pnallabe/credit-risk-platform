            ---
            doc_type: fair_lending
            report_year: 2020
            products_covered: [credit_card, personal_loan, mortgage]
            hmda_reporting: true
            ---

            # Fair Lending Annual Report — 2020

            **Report Period:** January 1, 2020 – December 31, 2020
            **Report Date:** April 30, 2021
            **Prepared By:** Fair Lending Officer
            **Reviewed By:** Compliance Officer, Chief Risk Officer
            **Classification:** Internal — Restricted; Regulator-ready upon request

            ---

            ## 1. HMDA LAR Summary (Mortgage — 2020)


### COVID-19 Impact Note

Application volume declined 10% due to COVID-19. Forbearance program available to all borrowers equally. CARES Act §4021 compliance confirmed.


            ### Application Volume by Action Taken

            | Action Taken | Count | Percentage |
            |---|---|---|
            | Loan Originated | 13,860 | 70.0% |
            | Approved, Not Accepted | 792 | 4.0% |
            | Application Denied | 6,138 | 31.0% |
            | Application Withdrawn | 1,584 | 8.0% |
            | File Closed Incomplete | 396 | 2.0% |
            | **Total Applications** | **19,800** | **100%** |

            ### Application Volume by Property Type

            | Property Type | Applications | Originated |
            |---|---|---|
            | Single-Family (1-4 unit) | 14,256 | 9,979 |
            | Multifamily (5+ units) | 1,980 | 1,108 |
            | Manufactured Home | 1,584 | 831 |
            | Condominium | 1,980 | 1,940 |

            ### Application Volume by Loan Purpose

            | Purpose | Applications | % |
            |---|---|---|
            | Home Purchase | 11,484 | 58% |
            | Refinance | 5,940 | 30% |
            | Cash-Out Refinance | 2,376 | 12% |

            ---

            ## 2. Approval Rate Disparity Analysis

            **Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
            = minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

            | Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
            |---|---|---|---|---|---|
            | White Non-Hispanic (control) | 12,276 | 8,893 | 72.4% | 1.000 | ✓ Control |
            | Hispanic | 2,970 | 1,850 | 62.3% | 0.860 | ✓ |
            | Black / African-American | 2,376 | 1,428 | 60.1% | 0.830 | ✓ |
            | Asian | 1,584 | 1,113 | 70.3% | 0.970 | ✓ |
            | Female Applicant | 8,910 | 6,067 | 68.1% | 0.940 | ✓ |

            **Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

            ---

            ## 3. APR Pricing Disparity Analysis

            **Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
            LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
            effects), and origination channel.

            ### Mortgage APR Disparity — Regression-Adjusted Results

            | Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
            |---|---|---|---|---|
            | Hispanic | +12 bps | +8 bps | p = 0.33 | ✓ Not significant |
            | Black / African-American | +13 bps | +10 bps | p = 0.26 | ✓ Within threshold |
            | Female | +7 bps | +5 bps | p = 0.43 | ✓ Not significant |

            **Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
            **2020 Status:** No investigation threshold exceeded.

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

            **2020 Overall Assessment:** COVID-19 application volume down 10% YoY. Emergency FICO tightening applied equally across all groups. No systemic demographic disparities found. AIR improved vs. 2019 due to near-prime volume reduction (segment that previously showed marginally elevated APR disparity).

            ---

            ## 6. Corrective Actions

            No corrective actions required. No disparities identified.



            ---

            ## 7. Fair Lending Officer Sign-off

            I certify that this Fair Lending Annual Report has been prepared in accordance with
            ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
            Examination Manual for Fair Lending.

            **Fair Lending Officer:** Patricia K. Owens
            **Date:** April 30, 2021
            **CRO Review:** Dr. Priya Nambiar — Approved

            ---

            *This report is prepared for internal compliance purposes and is available to regulatory
            examiners upon request. Retention: 25 years (ECOA record retention requirement).*
