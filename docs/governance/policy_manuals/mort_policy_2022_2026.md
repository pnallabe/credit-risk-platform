            ---
            product_type: mortgage
            effective_from: 2022-01-01
            effective_to: 2026-12-31
            doc_type: policy_manual
            version_tag: mort-policy-2022-2026
            ---

            # Mortgage Underwriting Policy Manual
            **Period Covered:** 2022-01-01 – 2026-12-31
            **Version Tag:** `mort-policy-2022-2026`
            **Regulatory Framework:** Truth in Lending Act (TILA / Regulation Z), RESPA/TRID (3-day Loan Estimate, 3-day Closing Disclosure), Equal Credit Opportunity Act (ECOA / Regulation B), Home Mortgage Disclosure Act (HMDA), Fair Credit Reporting Act (FCRA), ATR/QM Rule (12 CFR Part 1026.43)
            **Classification:** Internal — Restricted Distribution

            ---

            ## 1. Purpose & Scope

            This policy manual governs the underwriting, approval, and pricing of **Mortgage** products
            originated during the period 2022-01-01 through 2026-12-31. It applies to all originations
            processed through the automated decision engine, hybrid review queues, and manual underwriting
            workflows.

            This manual supersedes all prior Mortgage underwriting guidelines for the stated period and
            is binding on all credit analysts, loan officers, and automated decision systems. Deviations
            require written exception approval per Section 5 (Exception Process).

            **Regulatory Framework**: Truth in Lending Act (TILA / Regulation Z), RESPA/TRID (3-day Loan Estimate, 3-day Closing Disclosure), Equal Credit Opportunity Act (ECOA / Regulation B), Home Mortgage Disclosure Act (HMDA), Fair Credit Reporting Act (FCRA), ATR/QM Rule (12 CFR Part 1026.43)

            ---

            ## 2. Effective Date & Version History

            | Version Tag | Effective Date | CC FICO | PL FICO | Mort FICO | Notes |
|---|---|---|---|---|---|
| `multi-v1-2022q1-hike` | 2022-03-01 | 660 | 620 | 680 | Fed hike +25 bps |
| `multi-v1-2022q2-emergency` | 2022-06-01 | 680 | 650 | 700 | Emergency repricing |
| `multi-v1-2022q3-tighten` | 2022-09-01 | 700 | 660 | 720 | Refi shutdown |
| `multi-v1-2022q4-hold` | 2022-12-01 | 700 | 660 | 720 | Hold pattern |
| `multi-v1-2023-stable` | 2023-01-01 | 700 | 660 | 720 | High-rate stable |
| `multi-v1-2023-near-prime-tighten` | 2023-07-01 | 700 | 660 | 720 | Near-prime selective tightening |
| `multi-v1-2024-hold` | 2024-01-01 | 700 | 660 | 720 | Hold |
| `multi-v1-2024-selective` | 2024-07-01 | 695 | 655 | 715 | Selective easing |
| `multi-v1-2025-ease` | 2025-01-01 | 680 | 640 | 700 | Easing cycle begins |
| `multi-v1-2025-expand` | 2025-07-01 | 660 | 620 | 680 | Expansion |
| `multi-v1-2026-expand` | 2026-01-01 | 650 | 610 | 670 | Continued expansion |
| `multi-v1-2026-current` | 2026-07-01 | 640 | 600 | 660 | Current projected |

            ---

            ## 3. Eligible Borrower Profile

            ### FICO Score Requirements

            | Tier | Score Range | Outcome |
            |---|---|---|
            | Prime-Plus | 740+ | Auto-approve, preferred pricing |
            | Prime | 700–739 | Auto-approve, standard pricing |
            | Near-Prime | 720–699 | Approve with enhanced verification |
            | Hard Decline | <720 | Automatic decline — FCRA reason code AA01 |

            *FICO floor as of 2024-01-01. See Version History for epoch-specific floors.*

            ### Debt-to-Income Requirements

            | DTI Band | Classification | Decision |
            |---|---|---|
            | ≤36% | Preferred | Auto-approve |
            | 37–38% | Standard | Approve with documentation |
            | >38% | Decline | FCRA reason code AA04 |

            ### Employment Requirements

            - Minimum 2 years continuous employment (or 2 years in same field for job changers)
            - Self-employed borrowers require 2-year self-employment history
            - Probationary employees: minimum 6 months in current role
            - Retired/disability income: award letter + 3-year continuance verified

            ---

            ## 4. Product Parameters

            ### Loan Limits




            - **Conforming loan limit:** $726,200
            - **Jumbo threshold:** >$726,200 (subject to jumbo_enabled policy flag)
            - **Maximum LTV (conforming):** 97% with PMI



            ### Rate Ranges



            - **Rate range:** 3.00% – 14.99% (30-yr fixed)

            ---

            ## 5. Underwriting Guidelines

            ### Income Verification Matrix

            | Income Type | Documentation | Verification |
|---|---|---|
| W-2 / Salaried | 30-day pay stubs, 2-yr W-2 | VOE via WVOE or 4506-C |
| Self-Employed | 2-yr tax returns, YTD P&L | CPA letter required |
| Rental Income | Schedule E, 1-yr leases | 75% gross rental income |
| Investment | 2-yr statements | 100% of distributions |
| Retirement / SSA | Award letters | 100% gross |

**ATR Verification**: All 8 ATR factors must be documented per 12 CFR §1026.43(c).
Exceptions require Credit Committee approval.


            ### Exception Process

            Exceptions to standard underwriting guidelines require:
            1. Written justification by the originating loan officer documenting compensating factors
            2. Supervisor countersignature for FICO exceptions within 20 points of floor
            3. Credit Committee approval for FICO exceptions >20 points below floor
            4. Documentation retained in loan file for 7 years (ECOA record retention)

            **Compensating Factors** (may offset borderline FICO/DTI):
            - Residual income >150% of threshold
            - 12+ months cash reserves
            - Low utilization rate (<20% revolving)
            - Long credit history (>15 years, no recent derogatories)

            ---

            ## 6. Pricing Matrix

            | Product | FICO | Rate Type | Base Rate | Jumbo Premium |
|---|---|---|---|---|
| Conforming | 740+ | 30-yr Fixed | 7.10% | — |
| Conforming | 700–739 | 30-yr Fixed | 7.26% | — |
| Conforming | 660–699 | 30-yr Fixed | 7.52% | — |
| Conforming | 740+ | 15-yr Fixed | 6.50% | — |
| Jumbo | 720+ | 30-yr Fixed | 7.475% | +0.375% |
| Jumbo | 700–719 | 30-yr Fixed | 7.64% | +0.375% |
| FHA | 580+ | 30-yr Fixed | 7.35% | — |

**LTV Adjustments:** ≤80% (0 bps), 80–90% (+12.5 bps), 90–97% (+25 bps).
**Points Discount:** −0.25% per point paid (max 3 points).


            ---

            ## 7. Approval Authority Matrix

            | Decision Type | Authority | Threshold |
|---|---|---|
| Automated Approval | System | FICO ≥720, DTI ≤43%, LTV ≤80%, no derogatory marks, fraud score <5% |
| Loan Officer | Licensed MLO | FICO 620–719, or DTI 43–50% (Non-QM), or LTV 80–97% |
| Credit Committee | Full Committee | Jumbo loans >$1.5M, exceptions, policy overrides, ATR non-compliance reviews |
| Board Review | Board of Directors | Jumbo loans >$5M, new product approvals, policy framework changes |


            ---

            ## 8. Regulatory Compliance Notes

            ### ECOA / Regulation B (Adverse Action)
            All declined applications must receive an Adverse Action Notice within **30 days**
            (3 days for counter-offers). The notice must include up to 4 FCRA principal reasons
            from the standardized code list (AA01–AA99). Reason codes must be ordered by impact
            severity (highest discriminating factor first).

            ### FCRA (Fair Credit Reporting Act)
            - Permissible purpose disclosure required at application
            - Credit file freeze check required before underwriting
            - Adverse action notices trigger 60-day dispute window
            - 2-year record retention for all credit pull authorizations


            ### RESPA / TRID
- Loan Estimate (LE) due within 3 business days of application
- Closing Disclosure (CD) due 3 business days before consummation
- Tolerance limits: 0% tolerance for origination charges, 10% tolerance for third-party services
- HMDA LAR reporting required for mortgage applications ≥$30,000

### ATR / QM Rule (12 CFR §1026.43)
- All 8 ATR factors must be verified and documented
- QM Safe Harbor: DTI ≤43%, no balloon payments, no negative amortisation
- QM Rebuttable Presumption: HPML loans above threshold
- Non-QM originations require enhanced documentation and Credit Committee approval

            ### State Usury Limits
            All originations must comply with applicable state usury caps. The pricing engine
            enforces per-state APR caps at origination. Any quote exceeding a state cap is
            automatically clamped and flagged for compliance review.

            ---

            ## 9. Change Log

            | Date | Change | Version Tag | Board Resolution |
|---|---|---|---|
| 2022-03-01 | Fed hike +25 bps | `multi-v1-2022q1-hike` | Board Resolution 2022-11 |
| 2022-06-01 | FICO floor +20 pts (680→700); Emergency repricing | `multi-v1-2022q2-emergency` | Board Resolution 2022-12 |
| 2022-09-01 | FICO floor +20 pts (700→720); Refi shutdown | `multi-v1-2022q3-tighten` | Board Resolution 2022-13 |
| 2022-12-01 | Hold pattern | `multi-v1-2022q4-hold` | Board Resolution 2022-14 |
| 2023-01-01 | High-rate stable | `multi-v1-2023-stable` | Board Resolution 2023-15 |
| 2023-07-01 | Near-prime selective tightening | `multi-v1-2023-near-prime-tighten` | Board Resolution 2023-16 |
| 2024-01-01 | Hold | `multi-v1-2024-hold` | Board Resolution 2024-17 |
| 2024-07-01 | FICO floor -5 pts (720→715); Selective easing | `multi-v1-2024-selective` | Board Resolution 2024-18 |
| 2025-01-01 | FICO floor -15 pts (715→700); Easing cycle begins | `multi-v1-2025-ease` | Board Resolution 2025-19 |
| 2025-07-01 | FICO floor -20 pts (700→680); Expansion | `multi-v1-2025-expand` | Board Resolution 2025-20 |
| 2026-01-01 | FICO floor -10 pts (680→670); Continued expansion | `multi-v1-2026-expand` | Board Resolution 2026-21 |
| 2026-07-01 | FICO floor -10 pts (670→660); Current projected | `multi-v1-2026-current` | Board Resolution 2026-22 |

            ---

            *This document is subject to annual review and may be updated more frequently in response
            to regulatory changes, macroeconomic conditions, or model performance findings.
            Approved by: Chief Credit Officer | Chief Risk Officer | Compliance Officer*
