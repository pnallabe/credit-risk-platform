---
doc_type: model_validation
report_year: 2015
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved
---

# Model Validation Report — 2015

**Validation Period:** January 1, 2015 – December 31, 2015
**Report Date:** February 28, 2016
**SR 11-7 Status:** Approved
**Prepared By:** Model Risk Management
**Reviewed By:** Independent Model Validator (external)
**Classification:** Internal — Model Risk Restricted

---

## 1. Models in Scope

| Model ID | Version | Product | Model Type | Last Major Update |
|---|---|---|---|---|
| cc_pd_v1 | 1.1.0 | Credit Card | Logistic Regression + Gradient Boosting | Original 2015 |
| pl_pd_v1 | 1.1.0 | Personal Loan | Logistic Regression + Scorecard | Original 2015 |
| mortgage_pd_v1 | 1.1.0 | Mortgage | Logistic Regression + LTV Overlay | Original 2015 |

---

## 2. Data Window

| | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| Observation window | Jan 2015–Jun 2015 | Jan 2015–Jun 2015 | Jan 2015–Jun 2015 |
| Outcome window | 12 months (Jun 2016) | 12 months (Jun 2016) | 12 months (Jun 2016) |
| N in-sample | 103,150,000 | 16,305,000 | 6,097,000 |
| N out-of-sample | 24,780,000 | 4,076,000 | 1,524,250 |
| Default rate (observed) | 0.028 | 0.032 | 0.018 |

---

## 3. Performance Metrics

| Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
|---|---|---|---|
| KS Statistic | 56% | 54% | 52% |
| Gini Coefficient | 0.664 | 0.640 | 0.596 |
| AUC-ROC | 0.832 | 0.820 | 0.798 |
| Brier Score | 0.180 | 0.200 | 0.160 |
| Log-Loss | 0.420 | 0.450 | 0.380 |

---

## 4. Population Stability Index (PSI)

| Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
|---|---|---|---|---|---|---|
| FICO Score | 0.03 | 0.20 | 0.03 | 0.20 | 0.02 | 0.20 |
| DTI | 0.04 | 0.20 | 0.04 | 0.20 | 0.03 | 0.20 |
| Utilization | 0.02 | 0.20 | — | — | — | — |
| LTV | — | — | — | — | 0.02 | 0.20 |
| Employment Status | 0.03 | 0.20 | 0.03 | 0.20 | 0.02 | 0.20 |

---

## 5. Characteristic Stability Analysis

Population stability analysis across 4 key vintage cohorts (2012–2015):

| Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
|---|---|---|---|---|---|
| 2012 | 10,360,000 | 0.022 | 695 | 32.4% | Baseline cohort |
| 2013 | 10,385,000 | 0.025 | 692 | 33.1% | Slight DTI increase |
| 2014 | 10,410,000 | 0.028 | 689 | 33.8% | Normal variation |
| 2015 | 10,435,000 | 0.031 | 687 | 34.2% | Current validation cohort |

---

## 6. Outcome Analysis — Calibration

| PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
|---|---|---|---|---|
| 1 (lowest risk) | 0.004 | 0.0030 | 0.98 | ✓ Calibrated |
| 2 | 0.008 | 0.0070 | 0.95 | ✓ Calibrated |
| 5 | 0.025 | 0.0240 | 1.02 | ✓ Calibrated |
| 8 | 0.065 | 0.0630 | 0.98 | ✓ Calibrated |
| 10 (highest risk) | 0.180 | 0.1750 | 1.04 | ✓ Calibrated |

Hosmer-Lemeshow statistic: p-value = 0.42 (χ² test, 10 groups). Pass.

---

## 7. Findings

| # | Severity | Finding | Model(s) Affected |
|---|---|---|---|
| 1 | Informational | Low PSI across all models. Population stable in growth phase. | pl_pd_v1 |
| 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
 |

---

## 8. Remediation Plan

| Finding | Action | Responsible Party | Due Date | Status |
|---|---|---|---|---|
| Annual Recalibration | Schedule annual recalibration for next validation cycle | Model Risk + Data Science | Q4 2016 | Scheduled |
| SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 2016 | Complete |

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
