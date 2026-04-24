---
doc_type: model_validation
report_year: 2016
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2016

**Validation Period:** January 1, 2016 – December 31, 2016
**Report Date:** February 28, 2017
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.2.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
| pl_pd_v1 | 1.2.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
| mortgage_pd_v1 | 1.2.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2016–Jun 2016 | Jan 2016–Jun 2016 | Jan 2016–Jun 2016 |
| Outcome window | 12 months (Jun 2017) | 12 months (Jun 2017) | 12 months (Jun 2017) |
| N in-sample | 103,200,000 | 16,313,000 | 6,100,000 |
| N out-of-sample | 24,792,000 | 4,078,000 | 1,525,000 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 57% | 55% | 53% |
| Gini Coefficient | 0.662 | 0.638 | 0.594 |
| AUC-ROC | 0.831 | 0.819 | 0.797 |
| Brier Score | 0.182 | 0.202 | 0.162 |
| Log-Loss | 0.425 | 0.455 | 0.385 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.03 | 0.20 | 0.03 | 0.20 | 0.03 | 0.20 |
| DTI | 0.04 | 0.20 | 0.04 | 0.20 | 0.04 | 0.20 |
| Utilization | 0.02 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.03 | 0.20 |
| Employment Status | 0.03 | 0.20 | 0.03 | 0.20 | 0.03 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2013–2016):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2013 | 10,365,000 | 0.023 | 695 | 32.4% | Baseline cohort |
| 2014 | 10,390,000 | 0.026 | 692 | 33.1% | Slight DTI increase |
| 2015 | 10,415,000 | 0.029 | 689 | 33.8% | Normal variation |
| 2016 | 10,440,000 | 0.032 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0031 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0071 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0242 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0633 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1760 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.41 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | All models performing within acceptable bounds. Vintage analysis stable. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2017 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2017 | Complete |

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
