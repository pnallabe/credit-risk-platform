---
doc_type: model_validation
report_year: 2026
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2026

**Validation Period:** January 1, 2026 – December 31, 2026
**Report Date:** February 28, 2027
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.12.0 | Credit Card | Logistic Regression + Gradient Boosting | Recalibrated Q3 2023 |
| pl_pd_v1 | 1.12.0 | Personal Loan | Logistic Regression + Scorecard | Recalibrated Q3 2023 |
| mortgage_pd_v1 | 1.12.0 | Mortgage | Logistic Regression + LTV Overlay | Recalibrated Q3 2023 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2026–Jun 2026 | Jan 2026–Jun 2026 | Jan 2026–Jun 2026 |
| Outcome window | 12 months (Jun 2027) | 12 months (Jun 2027) | 12 months (Jun 2027) |
| N in-sample | 103,700,000 | 16,393,000 | 6,130,000 |
| N out-of-sample | 24,912,000 | 4,098,000 | 1,532,500 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 53% | 52% | 50% |
| Gini Coefficient | 0.636 | 0.618 | 0.574 |
| AUC-ROC | 0.818 | 0.809 | 0.787 |
| Brier Score | 0.202 | 0.222 | 0.182 |
| Log-Loss | 0.475 | 0.505 | 0.435 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.04 | 0.20 | 0.04 | 0.20 | 0.03 | 0.20 |
| DTI | 0.05 | 0.20 | 0.05 | 0.20 | 0.04 | 0.20 |
| Utilization | 0.03 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.03 | 0.20 |
| Employment Status | 0.04 | 0.20 | 0.04 | 0.20 | 0.03 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2023–2026):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2023 | 10,415,000 | 0.033 | 695 | 32.4% | Baseline cohort |
| 2024 | 10,440,000 | 0.036 | 692 | 33.1% | Slight DTI increase |
| 2025 | 10,465,000 | 0.039 | 689 | 33.8% | Normal variation |
| 2026 | 10,490,000 | 0.042 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0041 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0081 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0262 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0663 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1860 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.31 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | Models in excellent health. Expansion cycle improving population quality. No material findings. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2027 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2027 | In Progress |

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
