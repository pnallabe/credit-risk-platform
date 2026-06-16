---
doc_type: model_validation
report_year: 2019
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2019

**Validation Period:** January 1, 2019 – December 31, 2019
**Report Date:** February 28, 2020
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.5.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
| pl_pd_v1 | 1.5.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
| mortgage_pd_v1 | 1.5.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2019–Jun 2019 | Jan 2019–Jun 2019 | Jan 2019–Jun 2019 |
| Outcome window | 12 months (Jun 2020) | 12 months (Jun 2020) | 12 months (Jun 2020) |
| N in-sample | 103,350,000 | 16,337,000 | 6,109,000 |
| N out-of-sample | 24,828,000 | 4,084,000 | 1,527,250 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 54% | 52% | 49% |
| Gini Coefficient | 0.636 | 0.612 | 0.572 |
| AUC-ROC | 0.818 | 0.806 | 0.786 |
| Brier Score | 0.188 | 0.208 | 0.168 |
| Log-Loss | 0.440 | 0.470 | 0.400 |

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

Population stability analysis across 4 key vintage cohorts (2016–2019):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2016 | 10,380,000 | 0.026 | 695 | 32.4% | Baseline cohort |
| 2017 | 10,405,000 | 0.029 | 692 | 33.1% | Slight DTI increase |
| 2018 | 10,430,000 | 0.032 | 689 | 33.8% | Normal variation |
| 2019 | 10,455,000 | 0.035 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0034 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0074 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0248 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0642 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1790 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.38 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | Late-cycle slowdown evident in DTI distribution. Models stable. No action required. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2020 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2020 | Complete |

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
