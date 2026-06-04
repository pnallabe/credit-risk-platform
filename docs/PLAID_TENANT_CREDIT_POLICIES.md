# Plaid Data Tenant — Credit Policy Documents

**Tenant ID:** `plaid_data`
**Policy Version:** v1
**Effective Date:** 2026-06-04
**Document Owner:** Credit Risk / Compliance
**Review Cycle:** Quarterly (or upon material regulatory change)

---

## 1. Overview

The `plaid_data` tenant is the open-banking underwriting track of the
Credit Risk Platform.  Plaid acts as the primary bank-data connector
(90-day cash-flow lookback via Plaid Transactions + Plaid Income APIs).

Traditional bureau scores are **supplemental**.  For thin-file applicants
with no bureau history, Plaid cash-flow signals are the **sole**
underwriting basis on designated products (BNPL, Credit Builder, Overdraft).

### 1.1 Supported Credit Products

| Product | Wave | Bureau Required? | Plaid Required? |
|---------|------|-----------------|----------------|
| BNPL | Wave 1 | No | Yes |
| Personal Loan | Wave 1 | Preferred | Yes |
| SMB Secured Loan | Wave 1 | No | Yes |
| Credit Card | Wave 2 | Preferred | Yes |
| Credit Builder | Wave 2 | No | Yes |
| Overdraft / Cash Advance | Wave 2 | No | Yes |
| Auto Loan | Wave 3 | Yes | Supplemental |
| Small Business Loan | Wave 3 | No | Yes |
| Mortgage | Wave 4 | Yes | Supplemental |

### 1.2 Key Implementation Files

| File | Purpose |
|------|---------|
| `ingestion-api/src/plaid_connector.py` | Plaid/Finicity/OpenBankProject connector |
| `decision_engine/plaid_tenant_policies.py` | Plaid-aware product policy overrides |
| `config_registry/plaid_tenant_seed.py` | Tenant config registration |
| `compliance/plaid_policy_artifacts.py` | JSON + Markdown artifact generator |
| `credit_core/features.py` | Canonical feature matrix (includes Plaid signals) |

---

## 2. Plaid Bank-Data Features

All features below are produced by `ingestion-api/src/plaid_connector.py`
and normalised into the canonical feature matrix via `credit_core/features.py`.

| Feature | Type | Description |
|---------|------|-------------|
| `avg_monthly_inflow` | float (USD) | Rolling 90-day average monthly deposits |
| `avg_monthly_outflow` | float (USD) | Rolling 90-day average monthly debits |
| `net_monthly_cash_flow` | float (USD) | Inflow − outflow |
| `cash_flow_stability_score` | float 0–1 | Coefficient of variation of monthly inflows (1 = perfectly stable) |
| `income_source_count` | int | Distinct payroll / deposit sources |
| `income_volatility` | float | StdDev(monthly income) / mean(monthly income) |
| `bank_account_age_months` | int | Age of oldest linked account |
| `nsf_count_90d` | int | Non-sufficient-fund events in last 90 days |
| `overdraft_count_90d` | int | Overdraft events in last 90 days |
| `savings_balance` | float (USD) | Current savings/checking balance snapshot |
| `recurring_expense_ratio` | float 0–1 | Recurring fixed expenses / total outflow |
| `plaid_income_estimate` | float (USD/yr) | Plaid Income product annualised estimate |

---

## 3. PD Threshold Adjustment Logic

Plaid cash-flow signals dynamically adjust per-product PD approval thresholds
at decision time via `get_plaid_cash_flow_pd_adjustment()`.

```
adjusted_threshold = base_threshold × multiplier
```

| Cash Flow Stability Score | NSF Events (90d) | Multiplier | Effect |
|--------------------------|-----------------|------------|--------|
| ≥ 0.70 | 0 | ×1.20 | Relax 20% — strong cash flow |
| ≥ 0.50 | ≤ 1 | ×1.10 | Relax 10% — good cash flow |
| any | 3–4 | ×0.85 | Tighten 15% — stressed cash flow |
| any | ≥ 5 | ×0.80 | Tighten 20% — severely stressed |
| < 0.20 | any | ×0.80 | Tighten 20% — highly volatile income |
| default | default | ×1.00 | No adjustment |

---

## 4. Product Credit Policies

### 4.1 BNPL (Wave 1)

**Purpose:** Short-term buy-now-pay-later installment plans, $10–$7,500.
Primary underwriting basis: Plaid cash-flow. Bureau score de-emphasised.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 10% |
| Refer PD ≤ | 18% |
| Max DTI | 70% |
| Loan Range | $10 – $7,500 |
| Base APR | 0.00% (promotional) |
| Max APR | 36.00% |
| Fraud Reject ≥ | 70% |
| Fraud Review ≥ | 45% |

**Required Plaid Signals:** `payment_history`, `avg_monthly_inflow`,
`net_monthly_cash_flow`, `cash_flow_stability_score`, `nsf_count_90d`,
`bank_account_age_months`

**Extra Rules:**
- `max_concurrent_bnpl_plans_4` — reject if applicant has ≥ 4 open BNPL plans
- `merchant_category_check` — block prohibited merchant categories
- `plaid_nsf_gate_3` — reject if `nsf_count_90d ≥ 3`
- `plaid_min_inflow_200` — reject if `avg_monthly_inflow < $200`

**Regulatory Notes:**
- CFPB 2024 interpretive rule: BNPL = open-end credit under TILA
  → Periodic statements, dispute rights, and Reg Z disclosures required
- Plaid OAuth consent = FCRA authorisation record; retain 7 years
- Adverse action must cite specific Plaid data attributes per ECOA Reg B §202.9

---

### 4.2 Personal Loan (Wave 1)

**Purpose:** Unsecured installment loans $500–$75,000.
Plaid Income estimate replaces manual pay-stub income verification.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 7% |
| Refer PD ≤ | 14% |
| Max DTI | 55% |
| Min Open Accounts | 0 (Plaid substitutes) |
| Loan Range | $500 – $75,000 |
| Base APR | 9.99% |
| Max APR | 36.00% |

**Required Plaid Signals:** All base + extended Plaid features plus
`credit_score`, `debt_to_income`, `annual_income`

**Extra Rules:**
- `income_verification_required` — Plaid income path satisfies this
- `plaid_income_estimate_consistency_check` — Plaid vs stated income gap < 30%; else manual review
- `plaid_nsf_gate_3`
- `plaid_bank_age_min_3_months`
- `plaid_min_net_cashflow_positive`

**Regulatory Notes:**
- TILA Reg Z, ECOA Reg B, FCRA
- Plaid data accessed under FCRA §604(a)(3)(A) permissible purpose
- MLA: MAPR ≤ 36% for covered borrowers; MLA screening at origination
- Income gap > 30% triggers MANUAL_REVIEW, not auto-reject (UDAAP)

---

### 4.3 SMB Secured Loan (Wave 1)

**Purpose:** Secured term loan for small businesses, $5,000–$500,000.
Business cash-flow from Plaid replaces 2-year tax return for companies
< 24 months operating history.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 9% |
| Refer PD ≤ | 17% |
| Max DTI | 65% |
| DSCR Minimum | 1.20× (real-time Plaid DSCR) |
| Loan Range | $5,000 – $500,000 |
| Base APR | 8.50% |
| Max APR | 35.00% |

**Required Plaid Signals:** Base Plaid features plus `annual_revenue`,
`years_in_business`, `debt_service_coverage_ratio`, `business_type`,
`collateral_value_usd`, `collateral_type`, `plaid_income_estimate`,
`income_source_count`

**Extra Rules:**
- `years_in_business_min_1`
- `dscr_min_1_20`
- `personal_guarantee_required_under_250k`
- `collateral_lien_search_required`
- `plaid_business_revenue_min_3_months`
- `plaid_nsf_gate_2` — stricter for SMB (2 NSF events trigger review)

**Regulatory Notes:**
- ECOA Reg B (business credit); adverse action within 30 days
- CRA small-business loan reporting
- UCC-1 fixture filing within 5 business days of closing
- Plaid business account OAuth must be signed by authorized controller
- FinCEN CDD beneficial ownership (≥ 25% owners)

---

### 4.4 Credit Card (Wave 2)

**Purpose:** Revolving credit card, $500–$40,000 credit limit.
Plaid bank data supplements bureau score; bureau score optional for thin files.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 6% |
| Refer PD ≤ | 12% |
| Max DTI | 48% |
| Min Open Accounts | 0 (Plaid substitutes) |
| Credit Limit Range | $500 – $40,000 |
| Base APR | 14.99% |
| Max APR | 29.99% |

**Extra Rules:**
- `revolving_utilization_check`
- `min_credit_age_6_months`
- `plaid_nsf_gate_3`
- `plaid_savings_balance_min_100`
- `plaid_min_net_cashflow_positive`

**Regulatory Notes:** CARD Act (45-day APR notice), TILA Reg Z (Schumer Box),
ECOA Reg B (adverse action citing Plaid data if dispositive)

---

### 4.5 Credit Builder (Wave 2)

**Purpose:** Secured installment product for thin-file / credit-invisible applicants.
Bureau score NOT required. Plaid bank signals are the sole underwriting basis.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 15% |
| Refer PD ≤ | 25% |
| Max DTI | 80% |
| Loan Range | $300 – $2,500 |
| Fee-Based APR | 0.00% (fee structure) |
| Max APR | 36.00% |

**Extra Rules:**
- `plaid_nsf_gate_5` (lenient — building credit)
- `plaid_bank_age_min_1_month`
- `plaid_min_inflow_100`
- `plaid_recurring_expense_ratio_max_90pct`

**Regulatory Notes:**
- CFPB 2020: Loan proceeds held in savings account until paid off
- FCRA: Report payment history to ≥ 1 bureau after 6 months
- TILA Reg Z installment disclosures; ECOA Reg B adverse action

---

### 4.6 Overdraft / Cash Advance (Wave 2)

**Purpose:** Real-time cash advance, $20–$500. Near-real-time Plaid balance
check required at disbursement.

| Parameter | Value |
|-----------|-------|
| Approve PD ≤ | 12% |
| Refer PD ≤ | 20% |
| Max DTI | 85% |
| Advance Range | $20 – $500 |
| Fee-Based APR | 0.00% (fee structure) |
| Max APR | 36.00% |

**Required Plaid Signals:** `avg_monthly_inflow`, `net_monthly_cash_flow`,
`nsf_count_90d`, `overdraft_count_90d`, `savings_balance`,
`bank_account_age_months`

**Extra Rules:**
- `plaid_balance_realtime_check` — live balance fetch before disbursement
- `plaid_nsf_gate_5`
- `plaid_bank_age_min_2_months`
- `plaid_min_inflow_500_monthly`
- `overdraft_count_gate_10_90d`

**Regulatory Notes:**
- CFPB 2024 overdraft rule: fee-based overdraft capped at cost or $5
- CFPB: Systematic fee-based overdraft = TILA credit; disclose APR equivalent
- Real-time balance check must be disclosed in account agreement (UDAAP)

---

## 5. Regulatory Compliance Matrix

| Regulation | Applies To | Key Requirement | Plaid-Specific Note |
|------------|-----------|----------------|---------------------|
| TILA / Reg Z | All | APR, finance charge, payment schedule | — |
| ECOA / Reg B | All | Adverse action within 30 days | Cite Plaid feature if dispositive |
| FCRA §604 | All | Permissible purpose documented per tx | Plaid = consumer report |
| FCRA §615 | All | Adverse action identifies data source | Name Plaid + contact info |
| CFPB 2024 | BNPL, Overdraft | Open-end credit / overdraft fee cap | BNPL = Reg Z credit card |
| MLA | Personal Loan | MAPR ≤ 36% for covered borrowers | MLA screening at origination |
| CARD Act | Credit Card | 45-day APR notice; ability-to-pay | — |
| CRA | SMB, Mortgage | Community reinvestment tracking | — |
| BSA/AML | SMB, SBL | FinCEN CDD / beneficial ownership | Required for entities |
| TRID | Mortgage | Loan Estimate + Closing Disclosure | — |
| RESPA | Mortgage | CFPB TRID replaces legacy GFE | — |
| HOEPA | Mortgage | High-cost mortgage APR triggers | — |
| CFPB 2020 | Credit Builder | Proceeds held in savings until paid | — |
| Plaid ToS | All | OAuth consent via Plaid Link | Retain consent record 7 years |
| CCPA / CPRA | All | Plaid data in DSAR and erasure flows | Include in erasure_request.py |
| SOC 2 Type II | All | Plaid credentials in secrets manager | Not in code or config files |

---

## 6. Adverse Action Reason Codes — Plaid Data

When a Plaid cash-flow signal is the primary or contributing reason for denial,
the adverse action generator must include the appropriate reason code.

| Reason Code | Description | Plaid Feature |
|-------------|-------------|---------------|
| `PLAID_NSF_EXCESS` | Excessive non-sufficient fund events | `nsf_count_90d` |
| `PLAID_CASH_FLOW_VOLATILE` | Insufficient cash-flow stability | `cash_flow_stability_score` |
| `PLAID_INFLOW_INSUFFICIENT` | Average monthly deposits too low | `avg_monthly_inflow` |
| `PLAID_NET_CASHFLOW_NEGATIVE` | Negative net monthly cash flow | `net_monthly_cash_flow` |
| `PLAID_BANK_AGE_INSUFFICIENT` | Bank account history too short | `bank_account_age_months` |
| `PLAID_INCOME_INCONSISTENCY` | Stated income inconsistent with bank data | `plaid_income_estimate` |
| `PLAID_OVERDRAFT_EXCESS` | Excessive overdraft events | `overdraft_count_90d` |
| `PLAID_SAVINGS_INSUFFICIENT` | Savings balance below minimum | `savings_balance` |
| `PLAID_EXPENSE_RATIO_HIGH` | Recurring expenses exceed free-cash limit | `recurring_expense_ratio` |

---

## 7. Artifact Generation

Policy artifacts (JSON sheets, compliance checklists, Markdown summary)
are generated by:

```bash
python -m compliance.plaid_policy_artifacts --out-dir artifacts/plaid_tenant
```

Or from the dashboard: **📋 Credit Policy Docs → Regenerate Artifacts**

Artifacts written to `artifacts/plaid_tenant/`:
- `policy_manifest.json`
- `policy_{product}.json` (one per product)
- `underwriting_summary.md`

---

## 8. Tenant Seeding

Register the `plaid_data` tenant in the Config Registry:

```bash
python -m config_registry.plaid_tenant_seed
```

The seed is idempotent; re-running detects the existing tenant and skips.

---

## 9. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| v1 | 2026-06-04 | System | Initial policy document — all Wave 1–4 products |
