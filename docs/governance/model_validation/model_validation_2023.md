            ---
            doc_type: model_validation
            report_year: 2023
            models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
            sr11_7_status: Approved
            ---

            # Model Validation Report — 2023

            **Validation Period:** January 1, 2023 – December 31, 2023
            **Report Date:** February 28, 2024
            **SR 11-7 Status:** Approved
            **Prepared By:** Model Risk Management
            **Reviewed By:** Independent Model Validator (external)
            **Classification:** Internal — Model Risk Restricted

            ---

            ## 1. Models in Scope

            | Model ID | Version | Product | Model Type | Last Major Update |
            |---|---|---|---|---|
            | cc_pd_v1 | 1.9.0 | Credit Card | Logistic Regression + Gradient Boosting | Recalibrated Q3 2023 |
            | pl_pd_v1 | 1.9.0 | Personal Loan | Logistic Regression + Scorecard | Recalibrated Q3 2023 |
            | mortgage_pd_v1 | 1.9.0 | Mortgage | Logistic Regression + LTV Overlay | Recalibrated Q3 2023 |

            ---

            ## 2. Data Window

            | | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Observation window | Jan 2023–Jun 2023 | Jan 2023–Jun 2023 | Jan 2023–Jun 2023 |
            | Outcome window | 12 months (Jun 2024) | 12 months (Jun 2024) | 12 months (Jun 2024) |
            | N in-sample | 103,550,000 | 16,369,000 | 6,121,000 |
            | N out-of-sample | 24,876,000 | 4,092,000 | 1,530,250 |
            | Default rate (observed) | 0.028 | 0.032 | 0.018 |

            ---

            ## 3. Performance Metrics

            | Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | KS Statistic | 50% | 49% | 47% |
            | Gini Coefficient | 0.616 | 0.600 | 0.556 |
            | AUC-ROC | 0.808 | 0.800 | 0.778 |
            | Brier Score | 0.196 | 0.216 | 0.176 |
            | Log-Loss | 0.460 | 0.490 | 0.420 |

            ---

            ## 4. Population Stability Index (PSI)

            | Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
            |---|---|---|---|---|---|---|
            | FICO Score | 0.07 | 0.20 | 0.08 | 0.20 | 0.06 | 0.20 |
            | DTI | 0.08 | 0.20 | 0.09 | 0.20 | 0.07 | 0.20 |
            | Utilization | 0.06 | 0.20 | — | — | — | — |
            | LTV | — | — | — | — | 0.06 | 0.20 |
            | Employment Status | 0.07 | 0.20 | 0.08 | 0.20 | 0.06 | 0.20 |

            ---

            ## 5. Characteristic Stability Analysis

            Population stability analysis across 4 key vintage cohorts (2020–2023):

            | Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
            |---|---|---|---|---|---|
            | 2020 | 10,400,000 | 0.030 | 695 | 32.4% | Baseline cohort |
            | 2021 | 10,425,000 | 0.033 | 692 | 33.1% | Slight DTI increase |
            | 2022 | 10,450,000 | 0.036 | 689 | 33.8% | Rate hike impact |
            | 2023 | 10,475,000 | 0.039 | 687 | 34.2% | Current validation cohort |

            ---

            ## 6. Outcome Analysis — Calibration

            | PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
            |---|---|---|---|---|
            | 1 (lowest risk) | 0.004 | 0.0038 | 0.98 | ✓ Calibrated |
            | 2 | 0.008 | 0.0078 | 0.95 | ✓ Calibrated |
            | 5 | 0.025 | 0.0256 | 1.02 | ✓ Calibrated |
            | 8 | 0.065 | 0.0654 | 0.98 | ✓ Calibrated |
            | 10 (highest risk) | 0.180 | 0.1830 | 1.04 | ✓ Calibrated |

            Hosmer-Lemeshow statistic: p-value = 0.34 (χ² test, 10 groups). Pass.

            ---

            ### Recalibration Completion (2022 → 2023)

All three models were recalibrated using Q3 2022 – Q2 2023 data following the
SR 11-7 findings from the 2022 validation cycle. Key changes:

| Model | Change | PSI (post-recalibration) | AUC (post-recalibration) |
|---|---|---|---|
| cc_pd_v1 | DTI binning updated; rate environment feature added | 0.08 | 0.808 |
| pl_pd_v1 | Full re-estimation on rate-hike vintage | 0.09 | 0.800 |
| mortgage_pd_v1 | LTV-rate interaction term added | 0.07 | 0.778 |

SR 11-7 sign-off obtained: October 2023. Models re-approved.

## 7. Findings

            | # | Severity | Finding | Model(s) Affected |
            |---|---|---|---|
            | 1 | Informational | Recalibration complete for all three models (completed Q3 2023). PSI normalized. Models re-approved. SR 11-7 sign-off obtained. | pl_pd_v1 |
            | 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
             |

            ---

            ## 8. Remediation Plan

            | Finding | Action | Responsible Party | Due Date | Status |
            |---|---|---|---|---|
            | Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2024 | Complete |
            | SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2024 | Complete |

            ---

            ## 9. SR 11-7 Status

            **Overall Status:** Approved

            | Criteria | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Conceptual Soundness | ✓ Pass | ✓ Pass | ✓ Pass |
            | Ongoing Monitoring | ✓ Pass | ✓ Pass | ✓ Pass |
            | Outcomes Analysis | ✓ Pass | ✓ Pass | ✓ Pass |
            | Documentation | ✓ Pass | ✓ Pass | ✓ Pass |
            | Compensating Controls | N/A | N/A | N/A |

            **Sign-off:**
            - Model Risk Officer: Dr. Alejandro Ruiz — Approved
            - Independent Validator: ExaminerCo LLC — Approved
            - CRO: Dr. Priya Nambiar — Approved

            ---

            *This report constitutes the annual model validation required by SR 11-7 and OCC Bulletin 2011-12.*
            *Retention: 7 years per examination record requirements.*
