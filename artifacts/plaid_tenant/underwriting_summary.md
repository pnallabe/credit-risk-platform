# Plaid Data Tenant — Underwriting Policy Summary

*Generated: 2026-06-04 19:55 UTC  |  Tenant: `plaid_data`  |  Policy Version: v1*

## Overview

The `plaid_data` tenant uses Plaid Open-Banking data as the primary
underwriting signal.  Bureau scores are supplemental (or optional for
thin-file applicants).  All PD thresholds are calibrated against
Plaid cash-flow features: `cash_flow_stability_score`, `nsf_count_90d`,
`avg_monthly_inflow`, and `plaid_income_estimate`.

## Product Policy Parameters

| Product | Approve PD ≤ | Refer PD ≤ | Max DTI | Loan Range (USD) | Base APR | Max APR |
|---------|-------------|-----------|---------|-----------------|---------|--------|
| CREDIT_CARD | 6% | 12% | 48% | $500 – $40,000 | 14.99% | 29.99% |
| PERSONAL_LOAN | 7% | 14% | 55% | $500 – $75,000 | 9.99% | 36.00% |
| AUTO_LOAN | 7% | 14% | 55% | $3,000 – $120,000 | 5.99% | 24.99% |
| BNPL | 10% | 18% | 70% | $10 – $7,500 | 0.00% | 36.00% |
| MORTGAGE | 4% | 8% | 43% | $50,000 – $3,500,000 | 6.50% | 14.99% |
| SMALL_BUSINESS_LOAN | 8% | 16% | 60% | $5,000 – $5,000,000 | 7.50% | 40.00% |
| SMB_SECURED_LOAN | 9% | 17% | 65% | $5,000 – $500,000 | 8.50% | 35.00% |
| CREDIT_BUILDER | 15% | 25% | 80% | $300 – $2,500 | 0.00% | 36.00% |
| OVERDRAFT_CASH_ADVANCE | 12% | 20% | 85% | $20 – $500 | 0.00% | 36.00% |

## Plaid Cash-Flow PD Threshold Adjustments

| Cash Flow Stability | NSF Events (90d) | PD Threshold Multiplier |
|---------------------|-----------------|------------------------|
| ≥ 0.70 | 0 | ×1.20 (relax 20%) |
| ≥ 0.50 | ≤ 1 | ×1.10 (relax 10%) |
| any | 3–4 | ×0.85 (tighten 15%) |
| any | ≥ 5 | ×0.80 (tighten 20%) |
| < 0.20 | any | ×0.80 (tighten 20%) |

## Plaid Bank-Data Features Used

| Feature | Description | Products |
|---------|-------------|---------|
| `avg_monthly_inflow` | Rolling 90-day avg monthly deposits | All |
| `net_monthly_cash_flow` | Inflow − outflow | All |
| `cash_flow_stability_score` | CoV of monthly income (0–1, higher=stable) | All |
| `nsf_count_90d` | Non-sufficient-fund events (90 days) | All |
| `overdraft_count_90d` | Overdraft events (90 days) | Overdraft, Personal |
| `bank_account_age_months` | Age of oldest linked account | All |
| `plaid_income_estimate` | Plaid Income annualised estimate | Personal, SMB, Card |
| `income_source_count` | Distinct payroll / deposit sources | Personal, SMB |
| `savings_balance` | Current savings/checking snapshot | Card, Overdraft |
| `recurring_expense_ratio` | Fixed expenses / total outflow | Credit Builder |

## Wave Delivery Map

| Wave | Products | Timeline |
|------|----------|----------|
| Wave 1 | BNPL, Personal Loan, SMB Secured Loan | Weeks 1–5 |
| Wave 2 | Credit Card, Credit Builder, Overdraft/Cash Advance | Weeks 6–9 |
| Wave 3 | Auto Loan, Small Business Loan | Weeks 10–12 |
| Wave 4 | Mortgage | Post-launch |

## Regulatory Compliance Summary

| Regulation | Applies To | Key Requirement |
|------------|-----------|----------------|
| TILA / Reg Z | All products | APR, finance charge, payment schedule disclosed |
| ECOA / Reg B | All products | Adverse action citing Plaid data attributes |
| FCRA §604 | All products | Permissible purpose documented per transaction |
| FCRA §615 | All products | Plaid identified as data source in adverse action |
| CFPB 2024 | BNPL, Overdraft | BNPL = open-end credit; overdraft fee cap |
| MLA | Personal Loan | MAPR ≤ 36% for covered borrowers |
| CARD Act | Credit Card | 45-day APR notice; ability-to-pay |
| CRA | SMB, Mortgage | Community reinvestment tracking |
| BSA/AML | SMB, SBL | FinCEN beneficial ownership CDD |
| TRID | Mortgage | Loan Estimate + Closing Disclosure timing |
| Plaid ToS | All products | OAuth consent via Plaid Link; retained 7 years |
| CCPA/CPRA | All products | Plaid data in erasure and DSAR workflows |

---
*See individual product JSON artifacts in this directory for full parameter listings.*
