---
doc_type: model_validation
report_year: 2025
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2025

**Validation Period:** January 1, 2025 – December 31, 2025
**Report Date:** February 28, 2026
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.11.0 | Credit Card | Logistic Regression + Gradient Boosting | Recalibrated Q3 2023 |
| pl_pd_v1 | 1.11.0 | Personal Loan | Logistic Regression + Scorecard | Recalibrated Q3 2023 |
| mortgage_pd_v1 | 1.11.0 | Mortgage | Logistic Regression + LTV Overlay | Recalibrated Q3 2023 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2025–Jun 2025 | Jan 2025–Jun 2025 | Jan 2025–Jun 2025 |
| Outcome window | 12 months (Jun 2026) | 12 months (Jun 2026) | 12 months (Jun 2026) |
| N in-sample | 103,650,000 | 16,385,000 | 6,127,000 |
| N out-of-sample | 24,900,000 | 4,096,000 | 1,531,750 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 52% | 51% | 49% |
| Gini Coefficient | 0.630 | 0.612 | 0.566 |
| AUC-ROC | 0.815 | 0.806 | 0.783 |
| Brier Score | 0.200 | 0.220 | 0.180 |
| Log-Loss | 0.470 | 0.500 | 0.430 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.05 | 0.20 | 0.05 | 0.20 | 0.04 | 0.20 |
| DTI | 0.06 | 0.20 | 0.06 | 0.20 | 0.05 | 0.20 |
| Utilization | 0.04 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.04 | 0.20 |
| Employment Status | 0.05 | 0.20 | 0.05 | 0.20 | 0.04 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2022–2025):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2022 | 10,410,000 | 0.032 | 695 | 32.4% | Baseline cohort |
| 2023 | 10,435,000 | 0.035 | 692 | 33.1% | Slight DTI increase |
| 2024 | 10,460,000 | 0.038 | 689 | 33.8% | Normal variation |
| 2025 | 10,485,000 | 0.041 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0040 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0080 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0260 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0660 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1850 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.32 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | Easing cycle improving borrower capacity metrics. FICO distribution shifting favorably. Models performing well. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2026 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2026 | In Progress |

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
