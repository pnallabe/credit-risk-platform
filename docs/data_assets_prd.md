# Data Assets PRD — Lending Organization Simulation
**Version:** 1.0.0 | **Date:** April 23, 2026 | **Status:** DRAFT
**Project:** credit-risk-platform
**Products in scope:** Credit Cards · Personal Loans · Mortgages
**Time range:** 2015-01-01 → 2026-12-31

---

## 1. Overview

This PRD defines the data assets, credit approval policies, governance documentation, and financial data required to simulate a full-spectrum consumer lending organization. All raw data lives in `credit-risk-platform/data/raw/`; governance documents live in `credit-risk-platform/docs/governance/` and are ingested by LucidCredit's pgvector RAG store.

### 1.1 Existing Assets

| Asset | Location | Status |
|---|---|---|
| CC origination (5M records) | `data/raw/cc_pd/origination_5m.parquet` | ✅ Complete |
| CC transaction summary (5M) | `data/raw/cc_pd/txn_summary_5m.parquet` | ✅ Complete |
| CC PD training matrix | `data/raw/cc_pd/pd_training_5m.parquet` | ✅ Complete |
| CC cost/revenue ledger | `data/raw/cc_pd/cost_assumptions.parquet` | ✅ Complete |
| Freddie Mac mortgage zips | `data/Freddiemac/historical_data_2023/2024.zip` | ✅ Present (raw) |
| Multi-product loan applications | `data/raw/loan_applications.parquet` | ✅ Mixed products |
| Decision engine + policy store | `decision_engine/` | ✅ Operational |
| Compliance & audit layer | `compliance/`, `audit/` | ✅ Operational |

### 1.2 Assets To Build

Six delivery phases producing 14 new artifacts.

---

## 2. Phase 1 — Policy Infrastructure

> **Dependency**: All downstream phases depend on this.

### 2.1 `decision_engine/policy_history_seeder.py`

Seeds **22 versioned policy snapshots** (2015–2026) into `policy_versions.db` via the existing `PolicyVersionStore.publish()` API. Products: CREDIT_CARD, PERSONAL_LOAN, MORTGAGE.

**Macro-cycle mapping:**

| Period | Macro Event | Policy Change |
|---|---|---|
| 2015–2016 | Post-GFC expansion, rates near zero | Expansionary: moderate FICO floors, generous limits |
| 2017–2018 | Fed rate hikes (+125bps) | Tighten: FICO floor +20pts, max DTI −3%, APR repriced |
| 2019 | Late-cycle caution | Tighten PD thresholds, shrink max loan limits |
| 2020-Q1/Q2 | COVID-19 shock | Hard tighten: FICO floor +30pts, DTI −5%, jumbo halt |
| 2020-Q3 | COVID relief programs | Forbearance overlay, expanded income verification |
| 2021 | Stimulus normalization | Loosen FICO floors, raise limits, expand approvals |
| 2022 | Fed hikes +425bps (fastest since 1980) | APR floor repriced, refi shutdown, tighten DTI |
| 2023–2024 | Stable high-rate environment | Hold, selective tightening of near-prime |
| 2025–2026 | Gradual easing cycle | FICO floors lowered, limits expanded |

**Reuses:** `PolicyVersionStore.publish()`, `extract_current_policy_parameters()` from `decision_engine/policy_version_store.py`

---

### 2.2 `decision_engine/personal_loan_origination_policy.py`

Tiered underwriting engine mirroring `cc_origination_policy.py`:

**FICO tiers:**

| Band | Outcome |
|---|---|
| ≤579 | Hard decline |
| 580–619 | Soft decline |
| 620–659 | Near-prime: manual review |
| 660–719 | Prime: auto-approve standard terms |
| 720+ | Prime-plus: auto-approve preferred terms |

**DTI tiers:** ≤36% preferred · 36–50% standard · >50% decline

**Income verification by loan amount:**
- $1K–$15K: bank statement
- $15K–$50K: paystub
- $50K+: tax return

**Pricing matrix:** base rate + grade spread + term spread + purpose spread
**Approved amount:** `min(requested, max(income-based_max, score-based_max))`
**Adverse action codes:** AA01–AA06 (FCRA/Reg B, from `compliance/adverse_action.py`)

---

### 2.3 `decision_engine/mortgage_origination_policy.py`

**QM / Non-QM routing** per Reg Z 12 CFR 1026.43:
- ATR 8-factor check (income, assets, employment, credit history, payment obligations, DTI, MIP/PMI, residual income)
- DTI ≤43% → Qualified Mortgage safe harbor

**LTV tiers:**

| LTV | Treatment |
|---|---|
| ≤80% | Preferred — no PMI |
| 80–97% | Standard — PMI required |
| >97% | FHA / VA / USDA only |

**Product routing:**
- Conforming: loan ≤ $726,200 (2023+ limit)
- Jumbo: loan > $726,200, FICO ≥700 required
- FHA: FICO ≥580, 3.5% minimum down

**Property-type overlays:** Primary (all products) · Secondary (max 90% LTV) · Investment (max 75% LTV)
**Rate types:** fixed_30 / fixed_15 / arm_5_1 / arm_7_1

---

## 3. Phase 2 — Data Generation

> **Dependency**: Phase 1 must complete first.

### 3.1 `data/generate_personal_loans_simulated.py`

**Volume:** 750,000 applications · ~530,000 funded loans · 2015–2026
**Products:** `PERS-STD` (Personal Loan Standard) + `DEBT-CONS` (Debt Consolidation)

**Schema** (extends `generate_loans_data.py` base):

| Table | Key columns added |
|---|---|
| `loan_applications` | `decision_id` (UUID), `policy_version_id` (FK), `applied_at` spread 2015–2026 |
| `loans` | `loan_id`, `principal_amount`, `interest_rate`, `annual_percentage_rate`, `monthly_payment`, `loan_status`, `origination_date` |
| `loan_payments` | `payment_id`, `payment_date`, `principal_portion`, `interest_portion`, `fees_portion`, `days_late`, `remaining_balance` |
| `credit_bureau_pulls` | `pull_id`, `bureau` (Equifax/Experian/TransUnion), `pull_type`, `score_returned` |
| `loan_modifications` | `modification_id`, `modification_type`, `effective_date`, `reason` |

**Policy awareness:** Each application calls `PolicyVersionStore.get_as_of(applied_at)` to fetch the era-appropriate FICO/DTI thresholds and pricing matrix.

**Outputs:**
- `data/raw/loans/personal_loan_applications.parquet`
- `data/raw/loans/personal_loans_funded.parquet`
- `data/raw/loans/personal_loan_payments.parquet`

---

### 3.2 `data/generate_mortgage_simulated.py`

**Volume:** 200,000 applications · ~140,000 funded mortgages · 2015–2026
**Note:** Fully synthetic — Freddie Mac zips not parsed, ensuring full schema and policy alignment.

**Extended mortgage columns** (on top of base loan schema):

| Column | Type | Notes |
|---|---|---|
| `property_type` | str | primary_residence / second_home / investment_property |
| `occupancy_type` | str | owner_occupied / non_owner_occupied |
| `appraised_value` | float | USD |
| `ltv_at_origination` | float | `loan_amount / appraised_value` |
| `is_qm` | bool | True if ATR check passes and DTI ≤43% |
| `pmi_required` | bool | True if LTV > 80% |
| `product_type` | str | conforming / jumbo / FHA / VA / USDA |
| `rate_type` | str | fixed_30 / fixed_15 / arm_5_1 / arm_7_1 |
| `points_paid` | float | 0–3 discount points |
| `decision_id` | UUID | |
| `policy_version_id` | int | FK to policy_versions.db |

**Outputs:**
- `data/raw/loans/mortgage_applications.parquet`
- `data/raw/loans/mortgages_funded.parquet`
- `data/raw/loans/mortgage_payments.parquet`

---

### 3.3 `data/generate_cc_decision_ids.py`

Augments the existing 5M CC origination records with decision metadata. Uses **deterministic UUID5** (`namespace_oid + account_id + orig_date`) to preserve all existing analytics joins.

**Adds to each row:**

| Column | Notes |
|---|---|
| `decision_id` | UUID5, deterministic |
| `policy_version_id` | CC policy active at `orig_date` |
| `policy_version_tag` | e.g. `"cc-v3-covid-tighten"` |
| `decision_outcome` | APPROVE / REJECT / REFER |
| `decision_reason_codes` | JSON array AA01–AA06 |

**Output:** `data/raw/cc_pd/origination_5m_with_decisions.parquet`

---

## 4. Phase 3 — Decision Registry

> **Dependency**: Phase 2 must complete first.

### 4.1 `data/generate_decision_registry.py`

Unified cross-product registry linking every application to its governing policy version.

**Schema — `decision_registry`:**

| Column | Type | Notes |
|---|---|---|
| `decision_id` | UUID PK | |
| `product_type` | str | credit_card / personal_loan / mortgage |
| `application_id` | UUID | FK to product-specific application table |
| `customer_id` | UUID | |
| `decision_outcome` | str | APPROVE / REJECT / REFER / COUNTER_OFFER |
| `decision_timestamp` | datetime | |
| `policy_version_id` | int | FK to policy_versions.db |
| `policy_version_tag` | str | e.g. `"pl-v2-rate-hike"` |
| `model_version_id` | str | `cc_pd_v1`, `pl_pd_v1`, `mortgage_pd_v1` |
| `underwriter_type` | str | automated / human_underwriter / hybrid |
| `override_flag` | bool | |
| `override_reason` | str | nullable |
| `override_author` | str | nullable (underwriter ID) |
| `fcra_reason_codes` | JSON | array of AA01–AA06 codes |
| `credit_score_at_decision` | int | |
| `dti_at_decision` | float | |
| `pd_score` | float | model output |
| `fraud_score` | float | model output |
| `approved_amount` | float | nullable |
| `approved_rate` | float | nullable |
| `channel` | str | online / branch / mobile / partner / phone |
| `state` | str | US state code |

**Output:** `data/raw/decisions/decision_registry.parquet`

**Referential integrity guarantee:** Every `decision_id` has a `policy_version_id` where `effective_from ≤ decision_timestamp < superseded_at`.

---

## 5. Phase 4 — Financial Data

> **Dependency**: Phases 2–3 must complete first.

### 5.1 `data/generate_org_financials.py`

Org-level quarterly P&L + balance sheet, **44 quarters** (2015–2026), broken out by product.

**`org_income_statement`:**

| Column | Notes |
|---|---|
| `period_end_date` | Quarterly (Mar/Jun/Sep/Dec 31) |
| `product_type` | credit_card / personal_loan / mortgage / total |
| `interest_income` | Recognized interest on outstanding balances |
| `fee_income` | Origination + annual + late fees |
| `net_interest_income` | interest_income − cost_of_funds |
| `provision_for_credit_losses` | CECL ECL: 12-month (Stage 1), lifetime (Stage 2/3) |
| `net_credit_income` | NII − provision |
| `operating_expenses` | Servicing + tech + compliance + overhead |
| `net_income_before_tax` | |
| `net_interest_margin` | NIM % |
| `cost_of_funds_rate` | Tracks Fed Funds Rate + spread |
| `charge_off_rate` | Gross charge-offs / avg portfolio |
| `recovery_rate` | Recoveries / prior gross charge-offs |
| `net_charge_off_rate` | |

**`org_balance_sheet`:**

| Column | Notes |
|---|---|
| `period_end_date` | Quarterly |
| `product_type` | |
| `gross_loan_portfolio_outstanding` | USD |
| `allowance_for_credit_losses` | ACL (CECL reserve) |
| `net_loan_portfolio` | Gross − ACL |
| `number_of_active_accounts` | |
| `average_loan_balance` | |
| `portfolio_yield` | Annualized interest income / avg balance |
| `30dpd_rate` | % of portfolio 30+ days past due |
| `60dpd_rate` | |
| `90dpd_rate` | |
| `delinquency_rate` | Composite |

**Outputs:** `data/raw/financials/org_income_statement.parquet`, `data/raw/financials/org_balance_sheet.parquet`

---

### 5.2 `data/generate_loan_economics.py`

Itemized expense/income ledger at loan and account level.

**`loan_origination_economics`** *(one row per loan):*

| Column | Notes |
|---|---|
| `loan_id` | |
| `product_type` | |
| `origination_date` | |
| `origination_fee_amount` | |
| `origination_fee_rate` | % of loan amount |
| `points_paid` | Mortgage only |
| `doc_prep_fee` | |
| `processing_fee` | |
| `broker_commission` | nullable (broker channel only) |
| `appraisal_fee` | Mortgage only |
| `title_insurance_fee` | Mortgage only |
| `recording_fee` | Mortgage only |
| `escrow_fee` | Mortgage only |
| `total_closing_costs` | |
| `net_proceeds` | `funded_amount − total_closing_costs` |
| `funded_amount` | |
| `note_rate` | |
| `cost_of_funds_at_origination` | Spread to Fed Funds / SOFR |
| `initial_net_spread` | `note_rate − cost_of_funds` |

**`loan_monthly_ledger`** *(one row per loan × calendar month):*

| Column | Notes |
|---|---|
| `loan_id` | |
| `ledger_month` | YYYY-MM |
| `product_type` | |
| `scheduled_payment` | |
| `actual_payment_received` | |
| `interest_income_recognized` | Effective interest method |
| `principal_reduction` | |
| `servicing_cost_allocation` | 50bps annualized flat rate |
| `cost_of_funds_allocation` | Matched-maturity or pool cost |
| `credit_loss_provision` | ECL-based monthly provision |
| `net_interest_margin_contribution` | |
| `days_past_due` | |
| `stage` | 1 (performing) / 2 (SICR) / 3 (impaired) per CECL |
| `charge_off_amount` | If charged off this month |
| `recovery_amount` | If recovery received |

**`cc_account_monthly_economics`** *(one row per CC account × calendar month):*

| Column | Notes |
|---|---|
| `account_id` | |
| `ledger_month` | |
| `interest_charged` | |
| `annual_fee_income` | Pro-rated monthly |
| `late_fee_income` | |
| `overlimit_fee_income` | |
| `interchange_revenue` | 1.8% avg of purchase volume |
| `rewards_cost` | Cash-back / points redemption cost |
| `balance_transfer_fee_income` | |
| `cash_advance_fee_income` | |
| `fraud_loss` | |
| `servicing_cost_allocation` | |
| `cost_of_funds_allocation` | |
| `net_monthly_revenue` | Sum of income − costs |

**Outputs:** `data/raw/financials/loan_origination_economics.parquet`, `data/raw/financials/loan_monthly_ledger.parquet`, `data/raw/financials/cc_account_monthly_economics.parquet`

---

## 6. Phase 5 — Governance Documentation

> **Can run in parallel with Phases 2–4.**

### 6.1 Policy Manuals — `docs/governance/policy_manuals/`

9 Markdown files: `{product}_policy_{epoch}.md`

| File | Epoch |
|---|---|
| `credit_card_policy_2015_2018.md` | 2015-01-01 → 2018-12-31 |
| `credit_card_policy_2019_2022.md` | 2019-01-01 → 2022-12-31 |
| `credit_card_policy_2023_2026.md` | 2023-01-01 → 2026-12-31 |
| `personal_loan_policy_2015_2018.md` | 2015-01-01 → 2018-12-31 |
| `personal_loan_policy_2019_2022.md` | 2019-01-01 → 2022-12-31 |
| `personal_loan_policy_2023_2026.md` | 2023-01-01 → 2026-12-31 |
| `mortgage_policy_2015_2018.md` | 2015-01-01 → 2018-12-31 |
| `mortgage_policy_2019_2022.md` | 2019-01-01 → 2022-12-31 |
| `mortgage_policy_2023_2026.md` | 2023-01-01 → 2026-12-31 |

**Each manual structure:**
1. Purpose & Scope
2. Effective Date & Version History (linking to `policy_version_tag`)
3. Eligible Borrower Profile (FICO, DTI, income, employment)
4. Product Parameters (limits, rates, terms)
5. Underwriting Guidelines (verification requirements, exception process)
6. Pricing Matrix (rate tiers by risk grade)
7. Approval Authority Matrix (automated / loan officer / credit committee)
8. Regulatory Compliance Notes (ECOA, TILA, RESPA/TRID for mortgage)
9. Change Log — example entry: *"2020-03-20: FICO floor tightened from 620 to 660 — COVID-19 emergency response, ref. Board Resolution 2020-03"*

---

### 6.2 Credit Committee Meeting Minutes — `docs/governance/committee_minutes/`

44 Markdown files: `YYYY_QN_credit_committee_minutes.md` (quarterly 2015–2026).

**Standard section structure:**
- Attendees & quorum
- Prior period performance review (approval rate, delinquency, charge-offs vs. forecast)
- Policy change proposals & votes
- Model performance update (PSI, AUC drift)
- Regulatory horizon items
- Action items & next meeting

**Key milestone sessions with extended detail:**

| Session | Event |
|---|---|
| `2018_Q4` | Rate hike policy review; FICO floor increase approved |
| `2020_Q1` | COVID-19 emergency session (special meeting); credit freeze resolution voted |
| `2020_Q3` | COVID forbearance program approval; modified income verification adopted |
| `2022_Q2` | Inflation/rate response; emergency APR repricing and DTI floor tightening |

---

### 6.3 Model Validation Reports — `docs/governance/model_validation/`

12 Markdown files: `model_validation_YYYY.md` (annual 2015–2026).

**Structure per report:**
- Models in scope (PD model, fraud model, scorecard versions)
- Data window and population definition
- Performance metrics: KS statistic, Gini coefficient, AUC-ROC
- Population Stability Index (PSI) — flag if PSI > 0.2
- Characteristic stability analysis
- Outcome analysis (realized default rate vs. predicted PD)
- Findings severity (Critical / Significant / Informational)
- Remediation plan & timeline
- SR 11-7 approval status (Approved / Approved with Conditions / Rejected)
- Sign-off: Model Risk Officer, CRO

---

### 6.4 Fair Lending & HMDA Reports — `docs/governance/fair_lending/`

12 Markdown files: `fair_lending_YYYY.md` (annual 2015–2026).

**Structure per report:**
- HMDA LAR summary (mortgage applications: counts by action taken, property type, purpose)
- Approval rate disparity analysis by demographic proxy group
- APR pricing disparity analysis (Control: White non-Hispanic; compare: Hispanic, Black/African-American, Female)
- Statistical methodology (logistic regression with matched controls)
- Disparate impact findings (>80% adverse impact ratio = flag)
- Corrective actions taken (if any)
- Fair Lending Officer sign-off

---

## 7. Phase 6 — LucidCredit Integration

> **Dependency**: Phase 5 must complete first.

### 7.1 `backend/app/rag/policy_doc_ingestor.py` (LucidCredit)

Ingests governance Markdown files into LucidCredit's pgvector `policy_docs` table.

**Pipeline:**
1. Scan `credit-risk-platform/docs/governance/` recursively for `*.md`
2. Extract front-matter metadata: `product_type`, `effective_from`, `effective_to`, `doc_type` (policy_manual / committee_minutes / model_validation / fair_lending)
3. Chunk: paragraph-level, 100-token overlap, max 512 tokens per chunk
4. Embed via `embedder.py` (text-embedding-3-small or equivalent)
5. Upsert to pgvector `policy_docs` table with metadata: `source_type`, `product_type`, `effective_from`, `effective_to`, `version_tag`, `doc_type`, `source_path`

---

## 8. Verification

| # | Check | Pass Condition |
|---|---|---|
| 1 | Policy seeder | `list_versions()` returns 22 snapshots; no gaps in `effective_from`/`superseded_at` coverage |
| 2 | PL approval rate variance | Approval rate ≥5% higher in 2015–16 than 2020-Q2 |
| 3 | Mortgage QM flag | ≥95% of loans with DTI ≤43% have `is_qm=True` |
| 4 | Decision registry integrity | 100% of `decision_id` rows join to a policy version where `effective_from ≤ decision_timestamp < superseded_at` |
| 5 | Provision spike | `provision_for_credit_losses` in 2020-Q2 and 2022-Q1 are ≥2× the 2019-Q4 baseline |
| 6 | Financial reconciliation | Sum of `loan_monthly_ledger.interest_income_recognized` per quarter matches `org_income_statement.interest_income` within 1% |
| 7 | LucidCredit ingestion | `policy_docs` table has ≥9 documents; `product_type` and `effective_from` populated on all rows |
| 8 | End-to-end trace | 3 sampled `decision_id` values trace fully: decision → policy_version → policy parameters → application data → approval/rejection outcome |

---

## 9. Files To Create

### `credit-risk-platform/`

| File | Purpose |
|---|---|
| `decision_engine/policy_history_seeder.py` | Seed 22 policy snapshots 2015–2026 |
| `decision_engine/personal_loan_origination_policy.py` | Tiered PL underwriting engine |
| `decision_engine/mortgage_origination_policy.py` | QM/ATR mortgage underwriting engine |
| `data/generate_personal_loans_simulated.py` | 750K personal loan records |
| `data/generate_mortgage_simulated.py` | 200K mortgage records |
| `data/generate_cc_decision_ids.py` | Augment 5M CC records with decision IDs |
| `data/generate_decision_registry.py` | Unified cross-product decision registry |
| `data/generate_org_financials.py` | Quarterly P&L + balance sheet |
| `data/generate_loan_economics.py` | Per-loan itemized ledger + CC account economics |
| `docs/governance/policy_manuals/` | 9 policy manual Markdowns |
| `docs/governance/committee_minutes/` | 44 quarterly meeting minutes |
| `docs/governance/model_validation/` | 12 annual model validation reports |
| `docs/governance/fair_lending/` | 12 annual fair lending reports |

### `LucidCredit/`

| File | Purpose |
|---|---|
| `backend/app/rag/policy_doc_ingestor.py` | Governance doc ingestion pipeline |

### Key Existing Files To Reuse

| File | Role |
|---|---|
| `decision_engine/policy_version_store.py` | `PolicyVersionStore.publish()`, `get_as_of()` |
| `decision_engine/cc_origination_policy.py` | Template for PL/mortgage policy engines |
| `decision_engine/product_policies.py` | `ProductPolicy` dataclass, `evaluate_product_policy()` |
| `data/generate_loans_data.py` | Base schema for PL/mortgage generators |
| `data/generate_cc_pd_dataset.py` | Reference for CC decision ID augmentation |
| `compliance/adverse_action.py` | FCRA reason codes AA01–AA06 for decision registry |
| `audit/logger.py` | Optional hash-chaining for decision records |

---

## 10. Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Data location | `credit-risk-platform/data/raw/` | Consistent with existing structure |
| Policy format | Dual: Python objects + Markdown manuals | Machine-readable for engine; human-readable for regulators |
| Time range | 2015-01-01 → 2026-12-31 | 11 years covers full rate cycle, COVID, post-COVID |
| Personal loan products | PERS-STD + DEBT-CONS only | Debt consolidation is a PL variant; excludes auto/SBL |
| Mortgage data source | Fully synthetic | Schema control; Freddie Mac zips not parsed |
| Decision IDs on CC | Deterministic UUID5 (`account_id + orig_date`) | Preserves all existing analytics joins |
| Financial scope | Org-level quarterly + per-loan itemized | Both required for CECL provisioning and unit economics |
| Excluded products | HELOC, Auto, BNPL, SBL | Out of stated scope |

---

## 11. Open Questions

1. **Freddie Mac data**: Should extracted Freddie Mac records be stored as a separate `agency_comparables` dataset for model validation benchmarking alongside the synthetic mortgages?
2. **CC UUID5 uniqueness**: Confirm no duplicate `(account_id, orig_date)` pairs exist in `origination_5m.parquet` before implementing deterministic UUID5 decision IDs.
3. **LucidCredit pgvector migration**: Does the Alembic migration creating the `policy_docs` table need to be part of this deliverable, or is it treated as a LucidCredit Sprint 1 prerequisite?
