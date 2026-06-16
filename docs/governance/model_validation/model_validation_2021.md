---
doc_type: model_validation
report_year: 2021
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2021

**Validation Period:** January 1, 2021 – December 31, 2021
**Report Date:** February 28, 2022
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.7.0 | Credit Card | Logistic Regression + Gradient Boosting | Recalibrated 2021 |
| pl_pd_v1 | 1.7.0 | Personal Loan | Logistic Regression + Scorecard | Recalibrated 2021 |
| mortgage_pd_v1 | 1.7.0 | Mortgage | Logistic Regression + LTV Overlay | Recalibrated 2021 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2021–Jun 2021 | Jan 2021–Jun 2021 | Jan 2021–Jun 2021 |
| Outcome window | 12 months (Jun 2022) | 12 months (Jun 2022) | 12 months (Jun 2022) |
| N in-sample | 103,450,000 | 16,353,000 | 6,115,000 |
| N out-of-sample | 24,852,000 | 4,088,000 | 1,528,750 |
| Default rate (observed) | 0.032 | 0.037 | 0.021 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 52% | 50% | 48% |
| Gini Coefficient | 0.624 | 0.604 | 0.560 |
| AUC-ROC | 0.812 | 0.802 | 0.780 |
| Brier Score | 0.192 | 0.212 | 0.172 |
| Log-Loss | 0.450 | 0.480 | 0.410 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.09 | 0.20 | 0.10 | 0.20 | 0.08 | 0.20 |
| DTI | 0.10 | 0.20 | 0.11 | 0.20 | 0.09 | 0.20 |
| Utilization | 0.08 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.08 | 0.20 |
| Employment Status | 0.09 | 0.20 | 0.10 | 0.20 | 0.08 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2018–2021):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2018 | 10,390,000 | 0.028 | 695 | 32.4% | Baseline cohort |
| 2019 | 10,415,000 | 0.031 | 692 | 33.1% | Slight DTI increase |
| 2020 | 10,440,000 | 0.034 | 689 | 33.8% | Forbearance suppression |
| 2021 | 10,465,000 | 0.037 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0036 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0076 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0252 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0648 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1810 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.36 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | Post-COVID population normalizing. PSI declining from 2020 peak. Recalibration complete for cc_pd_v1 and mortgage_pd_v1. pl_pd_v1 recalibration in progress. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2022 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2022 | Complete |

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
