---
doc_type: model_validation
report_year: 2017
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2017

**Validation Period:** January 1, 2017 – December 31, 2017
**Report Date:** February 28, 2018
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.3.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
| pl_pd_v1 | 1.3.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
| mortgage_pd_v1 | 1.3.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2017–Jun 2017 | Jan 2017–Jun 2017 | Jan 2017–Jun 2017 |
| Outcome window | 12 months (Jun 2018) | 12 months (Jun 2018) | 12 months (Jun 2018) |
| N in-sample | 103,250,000 | 16,321,000 | 6,103,000 |
| N out-of-sample | 24,804,000 | 4,080,000 | 1,525,750 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 56% | 54% | 51% |
| Gini Coefficient | 0.650 | 0.626 | 0.586 |
| AUC-ROC | 0.825 | 0.813 | 0.793 |
| Brier Score | 0.184 | 0.204 | 0.164 |
| Log-Loss | 0.430 | 0.460 | 0.390 |

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

Population stability analysis across 4 key vintage cohorts (2014–2017):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2014 | 10,370,000 | 0.024 | 695 | 32.4% | Baseline cohort |
| 2015 | 10,395,000 | 0.027 | 692 | 33.1% | Slight DTI increase |
| 2016 | 10,420,000 | 0.030 | 689 | 33.8% | Normal variation |
| 2017 | 10,445,000 | 0.033 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0032 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0072 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0244 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0636 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1770 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.40 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | PSI slightly elevated due to rate hike cycle — borrower DTI distribution shifting. Monitor. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2018 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2018 | Complete |

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
