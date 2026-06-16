            ---
            doc_type: model_validation
            report_year: 2022
            models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
            sr11_7_status: Approved with Conditions
            ---

            # Model Validation Report — 2022

            **Validation Period:** January 1, 2022 – December 31, 2022
            **Report Date:** February 28, 2023
            **SR 11-7 Status:** Approved with Conditions
            **Prepared By:** Model Risk Management
            **Reviewed By:** Independent Model Validator (external)
            **Classification:** Internal — Model Risk Restricted

            ---

            ## 1. Models in Scope

            | Model ID | Version | Product | Model Type | Last Major Update |
            |---|---|---|---|---|
            | cc_pd_v1 | 1.8.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
            | pl_pd_v1 | 1.8.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
            | mortgage_pd_v1 | 1.8.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

            ---

            ## 2. Data Window

            | | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Observation window | Jan 2022–Jun 2022 | Jan 2022–Jun 2022 | Jan 2022–Jun 2022 |
            | Outcome window | 12 months (Jun 2023) | 12 months (Jun 2023) | 12 months (Jun 2023) |
            | N in-sample | 103,500,000 | 16,361,000 | 6,118,000 |
            | N out-of-sample | 24,864,000 | 4,090,000 | 1,529,500 |
            | Default rate (observed) | 0.036 | 0.042 | 0.024 |

            ---

            ## 3. Performance Metrics

            | Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | KS Statistic | 49% | 47% | 45% |
            | Gini Coefficient | 0.606 | 0.590 | 0.546 |
            | AUC-ROC | 0.803 | 0.795 | 0.773 |
            | Brier Score | 0.194 | 0.214 | 0.174 |
            | Log-Loss | 0.455 | 0.485 | 0.415 |

            ---

            ## 4. Population Stability Index (PSI)

            | Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
            |---|---|---|---|---|---|---|
            | FICO Score | 0.21 | 0.20 | 0.24 | 0.20 | 0.20 | 0.20 |
            | DTI | ⚠ **Alert** 0.22 | 0.20 | ⚠ **Alert** 0.25 | 0.20 | ⚠ **Alert** 0.21 | 0.20 |
            | Utilization | 0.20 | 0.20 | — | — | — | — |
            | LTV | — | — | — | — | 0.20 | 0.20 |
            | Employment Status | 0.21 | 0.20 | 0.24 | 0.20 | 0.20 | 0.20 |

            ---

            ## 5. Characteristic Stability Analysis

            Population stability analysis across 4 key vintage cohorts (2019–2022):

            | Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
            |---|---|---|---|---|---|
            | 2019 | 10,395,000 | 0.029 | 695 | 32.4% | Baseline cohort |
            | 2020 | 10,420,000 | 0.032 | 692 | 33.1% | Slight DTI increase |
            | 2021 | 10,445,000 | 0.035 | 689 | 33.8% | Normal variation |
            | 2022 | 10,470,000 | 0.038 | 687 | 34.2% | Current validation cohort |

            ---

            ## 6. Outcome Analysis — Calibration

            | PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
            |---|---|---|---|---|
            | 1 (lowest risk) | 0.004 | 0.0037 | 0.98 | ✓ Calibrated |
            | 2 | 0.008 | 0.0077 | 0.95 | ✓ Calibrated |
            | 5 | 0.025 | 0.0254 | 1.02 | ✓ Calibrated |
            | 8 | 0.065 | 0.0651 | 0.98 | ✓ Calibrated |
            | 10 (highest risk) | 0.180 | 0.1820 | 1.04 | ✓ Calibrated |

            Hosmer-Lemeshow statistic: p-value = 0.35 (χ² test, 10 groups). Pass.

            ---

            ### Rate Hike Cycle — DTI Distribution Shift

The Federal Reserve's 2022 rate hike cycle (+425 bps from March to December 2022)
caused an unprecedented shift in the DTI characteristic distribution:
- Average borrower DTI increased by 8.2 percentage points (variable-rate debt repricing)
- DTI 40–50% band grew from 22% to 34% of applicants
- DTI characteristic PSI: 0.25 (pl_pd_v1), 0.22 (cc_pd_v1), 0.21 (mortgage_pd_v1)

All three values exceed the 0.20 investigation threshold per SR 11-7 guidelines.

**Remediation Plan:**
- Recalibrate pl_pd_v1 using Q3 2022 – Q2 2023 data window
- Introduce rate-environment feature (Fed Funds rate) as external regressor
- Target recalibration completion: Q3 2023

## 7. Findings

            | # | Severity | Finding | Model(s) Affected |
            |---|---|---|---|
            | 1 | Significant | SIGNIFICANT: PSI > 0.20 on DTI characteristic across all models. Rate hike cycle driving unprecedented DTI distribution shift. Model recalibration initiated (target Q3 2023). | All |
            | 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
            | 3 | Significant | PSI > 0.20 on DTI characteristic — investigation required per SR 11-7 §4.3 | All | |

            ---

            ## 8. Remediation Plan

            | Finding | Action | Responsible Party | Due Date | Status |
            |---|---|---|---|---|
            | PSI Elevation | Recalibrate models using post-shock population; add rate environment feature | Model Risk + Data Science | Q3 2023 | In Progress |
            | SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2023 | Complete |

            ---

            ## 9. SR 11-7 Status

            **Overall Status:** Approved with Conditions

            | Criteria | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Conceptual Soundness | ✓ Pass | ✓ Pass | ✓ Pass |
            | Ongoing Monitoring | ✓ Pass | ✓ Pass | ✓ Pass |
            | Outcomes Analysis | ✓ Pass | ✓ Pass | ✓ Pass |
            | Documentation | ✓ Pass | ✓ Pass | ✓ Pass |
            | Compensating Controls | Required | Required | Required |

            **Sign-off:**
            - Model Risk Officer: Dr. Alejandro Ruiz — Approved with Conditions
            - Independent Validator: ExaminerCo LLC — Approved with Conditions
            - CRO: Dr. Priya Nambiar — Approved with Conditions

            ---

            *This report constitutes the annual model validation required by SR 11-7 and OCC Bulletin 2011-12.*
            *Retention: 7 years per examination record requirements.*
