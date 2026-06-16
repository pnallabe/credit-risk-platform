            ---
            doc_type: model_validation
            report_year: 2020
            models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
            sr11_7_status: Approved with Conditions
            ---

            # Model Validation Report — 2020

            **Validation Period:** January 1, 2020 – December 31, 2020
            **Report Date:** February 28, 2021
            **SR 11-7 Status:** Approved with Conditions
            **Prepared By:** Model Risk Management
            **Reviewed By:** Independent Model Validator (external)
            **Classification:** Internal — Model Risk Restricted

            ---

            ## 1. Models in Scope

            | Model ID | Version | Product | Model Type | Last Major Update |
            |---|---|---|---|---|
            | cc_pd_v1 | 1.6.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
            | pl_pd_v1 | 1.6.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
            | mortgage_pd_v1 | 1.6.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

            ---

            ## 2. Data Window

            | | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Observation window | Jan 2020–Jun 2020 | Jan 2020–Jun 2020 | Jan 2020–Jun 2020 |
            | Outcome window | 12 months (Jun 2021) | 12 months (Jun 2021) | 12 months (Jun 2021) |
            | N in-sample | 103,400,000 | 16,345,000 | 6,112,000 |
            | N out-of-sample | 24,840,000 | 4,086,000 | 1,528,000 |
            | Default rate (observed) | 0.032 | 0.037 | 0.021 |

            ---

            ## 3. Performance Metrics

            | Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | KS Statistic | 51% | 49% | 47% |
            | Gini Coefficient | 0.620 | 0.600 | 0.556 |
            | AUC-ROC | 0.810 | 0.800 | 0.778 |
            | Brier Score | 0.190 | 0.210 | 0.170 |
            | Log-Loss | 0.445 | 0.475 | 0.405 |

            ---

            ## 4. Population Stability Index (PSI)

            | Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
            |---|---|---|---|---|---|---|
            | FICO Score | 0.15 | 0.20 | 0.17 | 0.20 | 0.12 | 0.20 |
            | DTI | 0.16 | 0.20 | 0.18 | 0.20 | 0.13 | 0.20 |
            | Utilization | 0.14 | 0.20 | — | — | — | — |
            | LTV | — | — | — | — | 0.12 | 0.20 |
            | Employment Status | 0.15 | 0.20 | 0.17 | 0.20 | 0.12 | 0.20 |

            ---

            ## 5. Characteristic Stability Analysis

            Population stability analysis across 4 key vintage cohorts (2017–2020):

            | Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
            |---|---|---|---|---|---|
            | 2017 | 10,385,000 | 0.027 | 695 | 32.4% | Baseline cohort |
            | 2018 | 10,410,000 | 0.030 | 692 | 33.1% | Slight DTI increase |
            | 2019 | 10,435,000 | 0.033 | 689 | 33.8% | Normal variation |
            | 2020 | 10,460,000 | 0.036 | 687 | 34.2% | Current validation cohort |

            ---

            ## 6. Outcome Analysis — Calibration

            | PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
            |---|---|---|---|---|
            | 1 (lowest risk) | 0.004 | 0.0035 | 0.98 | ✓ Calibrated |
            | 2 | 0.008 | 0.0075 | 0.95 | ✓ Calibrated |
            | 5 | 0.025 | 0.0250 | 1.02 | ✓ Calibrated |
            | 8 | 0.065 | 0.0645 | 0.98 | ✓ Calibrated |
            | 10 (highest risk) | 0.180 | 0.1800 | 1.04 | ✓ Calibrated |

            Hosmer-Lemeshow statistic: p-value = 0.37 (χ² test, 10 groups). Pass.

            ---

            ### COVID-19 Population Shift Analysis

The 2020 validation period captures the most significant population composition
shift in the models' history. COVID-19-related unemployment spike (3.5% → 14.7%
between February and April 2020) created a bimodal employment distribution:
employed (stable) vs. furloughed/unemployed (stressed). The employment status
variable, historically a low-PSI characteristic, showed PSI of 0.16 (cc_pd_v1)
and 0.18 (pl_pd_v1).

**Recommendation:** Apply CECL overlay multiplier (2.5×) for Q2–Q3 2020 provisions.
Recalibrate models using post-COVID population once stabilized (target Q3 2021).

## 7. Findings

            | # | Severity | Finding | Model(s) Affected |
            |---|---|---|---|
            | 1 | Significant | COVID-19 population shift: employment status PSI elevated to 0.16–0.18. Significant. CECL overlay applied. Models approved with conditions pending 2021 recalibration. | All |
            | 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
             |

            ---

            ## 8. Remediation Plan

            | Finding | Action | Responsible Party | Due Date | Status |
            |---|---|---|---|---|
            | PSI Elevation | Recalibrate models using post-shock population; add rate environment feature | Model Risk + Data Science | Q3 2021 | In Progress |
            | SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2021 | Complete |

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
