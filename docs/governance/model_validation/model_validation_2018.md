---
doc_type: model_validation
report_year: 2018
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2018

**Validation Period:** January 1, 2018 – December 31, 2018
**Report Date:** February 28, 2019
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.4.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
| pl_pd_v1 | 1.4.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
| mortgage_pd_v1 | 1.4.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2018–Jun 2018 | Jan 2018–Jun 2018 | Jan 2018–Jun 2018 |
| Outcome window | 12 months (Jun 2019) | 12 months (Jun 2019) | 12 months (Jun 2019) |
| N in-sample | 103,300,000 | 16,329,000 | 6,106,000 |
| N out-of-sample | 24,816,000 | 4,082,000 | 1,526,500 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 54% | 52% | 50% |
| Gini Coefficient | 0.640 | 0.616 | 0.578 |
| AUC-ROC | 0.820 | 0.808 | 0.789 |
| Brier Score | 0.186 | 0.206 | 0.166 |
| Log-Loss | 0.435 | 0.465 | 0.395 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.06 | 0.20 | 0.06 | 0.20 | 0.05 | 0.20 |
| DTI | 0.07 | 0.20 | 0.07 | 0.20 | 0.06 | 0.20 |
| Utilization | 0.05 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.05 | 0.20 |
| Employment Status | 0.06 | 0.20 | 0.06 | 0.20 | 0.05 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2015–2018):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2015 | 10,375,000 | 0.025 | 695 | 32.4% | Baseline cohort |
| 2016 | 10,400,000 | 0.028 | 692 | 33.1% | Slight DTI increase |
| 2017 | 10,425,000 | 0.031 | 689 | 33.8% | Normal variation |
| 2018 | 10,450,000 | 0.034 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0033 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0073 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0246 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0639 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1780 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.39 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | PSI within acceptable range. Rate hike impact incorporated in recalibration. FICO floor policy change reduces near-prime volume. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2019 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2019 | Complete |

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
