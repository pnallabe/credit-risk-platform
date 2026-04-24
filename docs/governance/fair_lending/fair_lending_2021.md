            ---
            doc_type: fair_lending
            report_year: 2021
            products_covered: [credit_card, personal_loan, mortgage]
            hmda_reporting: true
            ---

            # Fair Lending Annual Report — 2021

            **Report Period:** January 1, 2021 – December 31, 2021
            **Report Date:** April 30, 2022
            **Prepared By:** Fair Lending Officer
            **Reviewed By:** Compliance Officer, Chief Risk Officer
            **Classification:** Internal — Restricted; Regulator-ready upon request

            ---

            ## 1. HMDA LAR Summary (Mortgage — 2021)



            ### Application Volume by Action Taken

            | Action Taken | Count | Percentage |
            |---|---|---|
            | Loan Originated | 17,150 | 70.0% |
            | Approved, Not Accepted | 980 | 4.0% |
            | Application Denied | 7,105 | 29.0% |
            | Application Withdrawn | 1,960 | 8.0% |
            | File Closed Incomplete | 490 | 2.0% |
            | **Total Applications** | **24,500** | **100%** |

            ### Application Volume by Property Type

            | Property Type | Applications | Originated |
            |---|---|---|
            | Single-Family (1-4 unit) | 17,640 | 12,348 |
            | Multifamily (5+ units) | 2,450 | 1,372 |
            | Manufactured Home | 1,960 | 1,029 |
            | Condominium | 2,450 | 2,401 |

            ### Application Volume by Loan Purpose

            | Purpose | Applications | % |
            |---|---|---|
            | Home Purchase | 14,209 | 58% |
            | Refinance | 7,350 | 30% |
            | Cash-Out Refinance | 2,940 | 12% |

            ---

            ## 2. Approval Rate Disparity Analysis

            **Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
            = minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

            | Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
            |---|---|---|---|---|---|
            | White Non-Hispanic (control) | 15,190 | 11,324 | 74.5% | 1.000 | ✓ Control |
            | Hispanic | 3,675 | 2,383 | 64.9% | 0.870 | ✓ |
            | Black / African-American | 2,940 | 1,841 | 62.6% | 0.840 | ✓ |
            | Asian | 1,960 | 1,417 | 72.3% | 0.970 | ✓ |
            | Female Applicant | 11,025 | 7,725 | 70.1% | 0.940 | ✓ |

            **Key Finding:** All AIR metrics ≥0.80 — no investigation threshold triggered.

            ---

            ## 3. APR Pricing Disparity Analysis

            **Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
            LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
            effects), and origination channel.

            ### Mortgage APR Disparity — Regression-Adjusted Results

            | Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
            |---|---|---|---|---|
            | Hispanic | +11 bps | +7 bps | p = 0.34 | ✓ Not significant |
            | Black / African-American | +12 bps | +9 bps | p = 0.27 | ✓ Within threshold |
            | Female | +6 bps | +4 bps | p = 0.44 | ✓ Not significant |

            **Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
            **2021 Status:** No investigation threshold exceeded.

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

            ### 2019 APR Monitoring — Closed

The enhanced APR monitoring program initiated in 2019 was closed in Q2 2021 after
4 consecutive quarters of no recurrence. Regression-adjusted APR difference for
Black/African-American borrowers has normalized to 9 bps — below the
15 bps threshold. Broker compensation review completed; no violations found.

**2021 Overall Assessment:** No disparities. Post-COVID recovery — application volume up 24% YoY. Population mix normalizing. 2019 APR monitoring program closed — no recurrence.

            ---

            ## 6. Corrective Actions



            2019 enhanced monitoring program closed — no recurrence of APR disparity.

            ---

            ## 7. Fair Lending Officer Sign-off

            I certify that this Fair Lending Annual Report has been prepared in accordance with
            ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
            Examination Manual for Fair Lending.

            **Fair Lending Officer:** Patricia K. Owens
            **Date:** April 30, 2022
            **CRO Review:** Dr. Priya Nambiar — Approved

            ---

            *This report is prepared for internal compliance purposes and is available to regulatory
            examiners upon request. Retention: 25 years (ECOA record retention requirement).*
