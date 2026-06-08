# Lending Club Tenant: Business & Model Assumptions

## Financial Assumptions
- **WACC (Weighted Average Cost of Capital):** 7.0%
- **Operational Cost:** 150 bps (1.5% of principal)
  - Includes: underwriting, servicing, collections, technology, regulatory
- **Origination Cost:** $50 per loan (fixed) + 1.5% of principal (variable)
- **Funding Source:** Assume investor funding at 7% all-in cost
- **Tax Rate:** 21% (federal corporate income tax)
- **Risk-Free Rate:** 2.5% (proxy: 10-year US Treasury)
- **Equity Risk Premium:** 4.5% (standard assumption for consumer credit)

## Credit Assumptions
- **Default Definition:** 120+ days past due or charge-off
- **Recovery Assumption by Loan Purpose:**
  - Debt Consolidation: 15% recovery rate (LGD 85%)
  - Home Improvement: 10% recovery rate (LGD 90%)
  - Personal Loans: 8% recovery rate (LGD 92%)
  - Business: 20% recovery rate with collateral (LGD 70%)

- **Prepayment Rate:** 15% annual (CPR) — loans paid off early, reduces loss exposure
- **Cure Rate:** 10% of 30+ DPD accounts cure before 120+ DPD
- **Loss Severity:** Add 5% OpEx for collections, legal fees, fraud; subtract recoveries

## Portfolio Assumptions
- **Target Portfolio Size:** 10,000–50,000 loans
- **Acceptable Portfolio Default Rate:** ≤ 8% (policy limit)
- **Concentration Limits:**
  - Single borrower: ≤ 5% of portfolio
  - Single purpose: ≤ 30% of portfolio
- **Growth Target:** 20% YoY new originations (sustainable growth)

## Risk Metrics & Thresholds
- **Leverage Ratio:** Assets / Equity = 10x (10:1 leverage, standard for lending platforms)
- **Capital Adequacy:** Equity must cover Expected Loss at 99% confidence interval
- **Liquidity:** Maintain 30-day funding buffer
- **Stress Test Scenarios:**
  - Base case: 5% default rate, 15% recovery rate
  - Downturn: 10% default rate, 10% recovery rate
  - Severe: 15% default rate, 5% recovery rate

## Regulatory & Compliance Assumptions
- **Interest Rate Cap:** 36% APR (SCRA / UDAP guidelines)
- **Usury Laws:** Assume compliance with federal banking (not state-specific)
- **Disclosure:** All fees and APRs disclosed upfront; comply with TILA/RESPA
- **Data Privacy:** CCPA / GDPR-compliant (PII encrypted, tenant-isolated)

## Model Calibration & Backtesting
- **Backtesting Frequency:** Quarterly
- **Retraining Frequency:** Semi-annually (or when PSI > 0.15)
- **Holdout Test Set:** 20% of most recent originations (temporal)
- **Model Governance:** Validate all predictions against actual defaults observed
- **Audit Trail:** Version all models; document changes and reasons
