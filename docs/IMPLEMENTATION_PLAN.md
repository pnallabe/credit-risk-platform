# Implementation Plan — Data Assets PRD v1.0.0
**Date:** April 23, 2026 | **Project:** credit-risk-platform
**Reference:** `docs/data_assets_prd.md`

---

## Execution Order

```
Phase 1 (Policy Infrastructure)
  └─► Phase 2 (Data Generation)
        └─► Phase 3 (Decision Registry)
              └─► Phase 4 (Financial Data)
Phase 5 (Governance Docs) ← can run in parallel with Phases 2–4
Phase 5 ─► Phase 6 (LucidCredit Integration)
```

**Total files to create:** 14 code/data files + 77 Markdown governance documents + 1 LucidCredit file.

---

## Phase 1 — Policy Infrastructure

### Prompt 1.1 — `decision_engine/policy_history_seeder.py`

**Context to read first:**
- `decision_engine/policy_version_store.py` — `PolicyVersionStore.publish()`, `extract_current_policy_parameters()`, `PolicyVersion` dataclass
- `decision_engine/cc_origination_policy.py` — `PRODUCT_POLICIES` dict shape, `CreditProduct` enum

**Task:** Create `decision_engine/policy_history_seeder.py` that seeds 22 versioned policy snapshots (2015–2026) into `policy_versions.db` using the existing `PolicyVersionStore.publish()` API.

**Requirements:**
1. Import `PolicyVersionStore` from `decision_engine.policy_version_store`.
2. Define a list of 22 `PolicySnapshot` dicts (or similar named tuples) in chronological order. Each snapshot must include:
   - `version_tag` (e.g., `"cc-v1-2015-expansion"`, `"pl-v2-covid-tighten"`, `"mort-v3-rate-hike"`)
   - `effective_from` as ISO-8601 string
   - `author` as `"policy_seeder_v1"`
   - `parameters` dict with product-specific keys below

3. Map the 9 macro-cycle epochs from the PRD to parameters for all three products (`CREDIT_CARD`, `PERSONAL_LOAN`, `MORTGAGE`). Minimum parameter keys per product:

   **CREDIT_CARD** parameters: `fico_floor`, `max_dti`, `max_pd_hard`, `max_pd_review`, `apr_floor`, `max_credit_limit`

   **PERSONAL_LOAN** parameters: `fico_floor_hard_decline` (≤579), `fico_floor_soft_decline` (580–619), `fico_floor_near_prime` (620–659), `max_dti_preferred` (≤36%), `max_dti_standard` (≤50%), `max_loan_amount`, `base_rate`

   **MORTGAGE** parameters: `fico_floor_fha`, `fico_floor_conforming`, `fico_floor_jumbo`, `max_dti_qm`, `max_ltv_standard`, `conforming_loan_limit`, `jumbo_enabled`

4. Macro-cycle parameter schedule (implement these as the 22 rows):

   | version_tag suffix | effective_from | CC FICO floor | PL FICO hard decline | Mort FICO conforming | CC max_dti | PL max_dti_standard | Mort max_dti_qm | Notes |
   |---|---|---|---|---|---|---|---|---|
   | `2015-expansion` | 2015-01-01 | 620 | 580 | 640 | 0.50 | 0.50 | 0.43 | Post-GFC expansion |
   | `2016-steady` | 2016-01-01 | 620 | 580 | 640 | 0.50 | 0.50 | 0.43 | |
   | `2017-tighten` | 2017-07-01 | 640 | 600 | 660 | 0.47 | 0.47 | 0.41 | Rate hike cycle begins |
   | `2018-tighten` | 2018-01-01 | 660 | 620 | 680 | 0.45 | 0.45 | 0.40 | +125bps cumulative |
   | `2019-cautious` | 2019-01-01 | 660 | 620 | 680 | 0.43 | 0.43 | 0.40 | Late-cycle caution |
   | `2020q1-covid-tighten` | 2020-03-15 | 690 | 650 | 700 | 0.40 | 0.40 | 0.38 | COVID-19 shock |
   | `2020q2-covid-hard` | 2020-04-01 | 700 | 660 | 720 | 0.38 | 0.38 | 0.36 | Jumbo halted |
   | `2020q3-forbearance` | 2020-07-01 | 680 | 640 | 700 | 0.40 | 0.42 | 0.40 | Relief overlay |
   | `2021-stimulus` | 2021-01-01 | 660 | 620 | 680 | 0.45 | 0.48 | 0.43 | Normalization |
   | `2021-expand` | 2021-07-01 | 640 | 600 | 660 | 0.47 | 0.50 | 0.43 | Limits expanded |
   | `2022q1-hike` | 2022-03-01 | 660 | 620 | 680 | 0.45 | 0.47 | 0.41 | Fed hike +25bps |
   | `2022q2-emergency` | 2022-06-01 | 680 | 650 | 700 | 0.42 | 0.44 | 0.39 | Emergency repricing |
   | `2022q3-tighten` | 2022-09-01 | 700 | 660 | 720 | 0.40 | 0.42 | 0.38 | Refi shutdown |
   | `2022q4-hold` | 2022-12-01 | 700 | 660 | 720 | 0.40 | 0.42 | 0.38 | |
   | `2023-stable` | 2023-01-01 | 700 | 660 | 720 | 0.40 | 0.43 | 0.38 | High-rate stable |
   | `2023-near-prime-tighten` | 2023-07-01 | 700 | 660 | 720 | 0.40 | 0.43 | 0.38 | Near-prime selective |
   | `2024-hold` | 2024-01-01 | 700 | 660 | 720 | 0.40 | 0.43 | 0.38 | |
   | `2024-selective` | 2024-07-01 | 695 | 655 | 715 | 0.41 | 0.44 | 0.39 | |
   | `2025-ease` | 2025-01-01 | 680 | 640 | 700 | 0.43 | 0.46 | 0.41 | Easing cycle begins |
   | `2025-expand` | 2025-07-01 | 660 | 620 | 680 | 0.45 | 0.48 | 0.43 | |
   | `2026-expand` | 2026-01-01 | 650 | 610 | 670 | 0.47 | 0.50 | 0.43 | |
   | `2026-current` | 2026-07-01 | 640 | 600 | 660 | 0.48 | 0.50 | 0.43 | Projected |

5. The `parameters` dict for CREDIT_CARD rows must also include `jumbo_enabled: bool` for mortgage rows (set to `False` during `2020q2-covid-hard`, `True` otherwise).

6. Main entry point:
   ```python
   def seed(db_path: str = "policy_versions.db", dry_run: bool = False) -> list[int]:
       """Seed all 22 snapshots. Returns list of version_ids created."""

   if __name__ == "__main__":
       import argparse
       # --db-path, --dry-run flags
   ```

7. Before publishing, call `store.list_versions()` and skip any version_tag that already exists (idempotent).

8. **Verification**: After seeding, assert `len(store.list_versions()) == 22`. Print a summary table of all versions.

---

### Prompt 1.2 — `decision_engine/personal_loan_origination_policy.py`

**Context to read first:**
- `decision_engine/cc_origination_policy.py` — Full file. Mirror the same 4-phase decision stack and policy tier structure.
- `decision_engine/product_policies.py` — `ProductPolicy` dataclass, `evaluate_product_policy()`, FCRA decline codes
- `compliance/adverse_action.py` — `REG_B_REASON_CODES`, `AdverseActionNotice`

**Task:** Create `decision_engine/personal_loan_origination_policy.py` — a tiered underwriting engine for personal loans.

**Requirements:**
1. **Enums** (mirror `cc_origination_policy.py` pattern):
   ```python
   class PLDecision(str, Enum):
       APPROVE = "APPROVE"
       DECLINE = "DECLINE"
       MANUAL_REVIEW = "MANUAL_REVIEW"
       COUNTER_OFFER = "COUNTER_OFFER"   # lower amount / higher rate

   class PLDeclineReason(str, Enum):
       FICO_BELOW_MINIMUM = "FICO_BELOW_MINIMUM"
       DTI_EXCEED_MAX = "DTI_EXCEED_MAX"
       INCOME_INSUFFICIENT = "INCOME_INSUFFICIENT"
       PD_ABOVE_CUTOFF = "PD_ABOVE_CUTOFF"
       FRAUD_INDICATOR = "FRAUD_INDICATOR"
       DEROGATORY_EXCESS = "DEROGATORY_EXCESS"
       EMPLOYMENT_RISK = "EMPLOYMENT_RISK"
       LOAN_PURPOSE_RESTRICTED = "LOAN_PURPOSE_RESTRICTED"
       AMOUNT_EXCEEDS_POLICY = "AMOUNT_EXCEEDS_POLICY"
   ```

2. **FICO tier logic** (hard-coded in evaluate function; also overridable via policy version params):
   | FICO range | Outcome |
   |---|---|
   | ≤579 | Hard decline — FICO_BELOW_MINIMUM |
   | 580–619 | Soft decline — manual review with decline if PD > threshold |
   | 620–659 | Near-prime: auto-approve with standard terms |
   | 660–719 | Prime: auto-approve |
   | 720+ | Prime-plus: preferred rate |

3. **DTI tiers**: ≤36% preferred, 36–50% standard, >50% decline (DTI_EXCEED_MAX).

4. **Income verification thresholds** (attach to application record, not a decline gate):
   - $1K–$15K → `verification_required = "bank_statement"`
   - $15K–$50K → `verification_required = "paystub"`
   - $50K+ → `verification_required = "tax_return"`

5. **Pricing matrix** — `compute_pl_rate(fico, dti, term_months, purpose) -> float`:
   - base_rate (from policy version params, default 11.99%)
   - grade_spread: `{prime_plus: -1.5%, prime: 0, near_prime: +3.5%}`
   - term_spread: `{24m: -0.25%, 36m: 0, 48m: +0.50%, 60m: +1.00%, 72m: +1.75%}`
   - purpose_spread: `{debt_consolidation: +0.25%, medical: -0.25%, home_improvement: -0.50%, other: 0}`
   - Output clipped to [5.99%, 36.00%]

6. **Approved amount**: `min(requested, max(income_based_max, score_based_max))`
   - `income_based_max = annual_income * 0.45 / 12 * term_months * 0.50`
   - `score_based_max`: lookup table by FICO tier: `{prime_plus: $100K, prime: $50K, near_prime: $25K}`

7. **Adverse action codes**: map decline reasons to FCRA codes using `compliance/adverse_action.py` — `REG_B_REASON_CODES`. Return top-4 sorted by severity.

8. **Policy-version-aware evaluation**: function signature:
   ```python
   def evaluate_personal_loan(
       application: dict,
       pd_score: float,
       fraud_score: float,
       policy_params: dict | None = None,  # from PolicyVersionStore.get_as_of()
   ) -> PLDecisionResult:
   ```
   If `policy_params` is None, use module-level defaults.

9. **`PLDecisionResult` dataclass**:
   ```python
   @dataclass
   class PLDecisionResult:
       decision: PLDecision
       decline_reasons: list[PLDeclineReason]
       fcra_reason_codes: list[str]
       approved_amount: float | None
       approved_rate: float | None
       term_months: int | None
       monthly_payment: float | None
       apr: float | None
       verification_required: str | None
       fico_tier: str
       dti_tier: str
       policy_version_id: int | None
   ```

10. **Batch evaluation** `evaluate_batch(df: pd.DataFrame, policy_params: dict) -> pd.DataFrame` — vectorised, no Python loops over rows. Mirror the pattern from `cc_origination_policy.evaluate_batch()`.

11. CLI demo: `python decision_engine/personal_loan_origination_policy.py --demo 20`

---

### Prompt 1.3 — `decision_engine/mortgage_origination_policy.py`

**Context to read first:**
- `decision_engine/personal_loan_origination_policy.py` (just created in Prompt 1.2) — mirror its structure
- `decision_engine/product_policies.py` — `ProductPolicy` for MORTGAGE, `extra_rules` list including `qm_ability_to_repay_check`, `ltv_97%_conforming`, `hmda_reporting`
- `compliance/adverse_action.py` — FCRA codes

**Task:** Create `decision_engine/mortgage_origination_policy.py` — QM/ATR mortgage underwriting engine.

**Requirements:**
1. **Enums**:
   ```python
   class MortgageDecision(str, Enum):
       APPROVE_QM = "APPROVE_QM"            # Safe harbor
       APPROVE_NON_QM = "APPROVE_NON_QM"    # Rebuttable presumption
       DECLINE = "DECLINE"
       MANUAL_REVIEW = "MANUAL_REVIEW"      # Near DTI boundary, near-prime
       REFER_FHA = "REFER_FHA"              # Conventional declined, FHA eligible

   class MortgageDeclineReason(str, Enum):
       FICO_BELOW_MINIMUM = "FICO_BELOW_MINIMUM"
       DTI_EXCEED_QM = "DTI_EXCEED_QM"
       LTV_EXCEEDS_LIMIT = "LTV_EXCEEDS_LIMIT"
       ATR_FAILED = "ATR_FAILED"
       JUMBO_POLICY_SUSPENDED = "JUMBO_POLICY_SUSPENDED"
       INSUFFICIENT_ASSETS = "INSUFFICIENT_ASSETS"
       PROPERTY_TYPE_INELIGIBLE = "PROPERTY_TYPE_INELIGIBLE"
       INCOME_UNVERIFIABLE = "INCOME_UNVERIFIABLE"
   ```

2. **QM/ATR 8-factor check** (`check_atr(application) -> tuple[bool, list[str]]`):
   - Factor 1: Current or reasonably expected income / assets — income > 0 and assets verified
   - Factor 2: Current employment status — not UNEMPLOYED
   - Factor 3: Monthly mortgage payment on the covered transaction — computed monthly_payment / gross_income ≤ 0.28
   - Factor 4: Monthly payment on simultaneous loans — included in DTI
   - Factor 5: Current debt obligations (DTI) — ≤43% for QM safe harbor
   - Factor 6: Monthly debt-to-income ratio or residual income — residual_income = monthly_income − total_monthly_debt ≥ $1,500 (single) / $2,500 (family)
   - Factor 7: Credit history — no bankruptcy in last 4 years
   - Factor 8: Monthly payments on mortgage-related obligations (MIP/PMI, homeowner insurance, taxes) — PITI ÷ gross monthly income ≤ 0.31
   - Return `(is_qm, failed_factors: list[str])`

3. **LTV tiers** (function `classify_ltv(ltv) -> str`):
   - ≤0.80 → `"preferred"` (no PMI)
   - 0.80–0.97 → `"standard"` (PMI required)
   - >0.97 → `"high_ltv"` (FHA/VA/USDA only, decline conventional)

4. **Product routing** (`route_mortgage_product(application, policy_params) -> str`):
   - `loan_amount ≤ conforming_loan_limit` (default $726,200) → `"conforming"`
   - `loan_amount > conforming_loan_limit` and `fico ≥ jumbo_fico_min` (default 700) and `jumbo_enabled` → `"jumbo"`
   - `loan_amount > conforming_loan_limit` and conditions not met → decline JUMBO_POLICY_SUSPENDED or insufficient FICO
   - `fico ≥ 580` and `ltv ≤ 0.965` (3.5% down) → `"FHA"` (as alternative path)
   - `fico ≥ 620` and VA-eligible → `"VA"` (if `va_eligible` flag present in application)

5. **Property-type overlays**:
   - `primary_residence` — all products eligible, max LTV per product rules
   - `second_home` — max LTV 90% (decline if `ltv > 0.90`)
   - `investment_property` — max LTV 75% (decline if `ltv > 0.75`)

6. **Rate matrix** (`compute_mortgage_rate(rate_type, fico, ltv, product_type, points_paid, policy_params) -> float`):
   - Base rates (from policy params or defaults): `fixed_30: 7.10%`, `fixed_15: 6.50%`, `arm_5_1: 6.75%`, `arm_7_1: 6.90%`
   - FICO adjustment: `-(fico - 740) * 0.004` (negative = discount, positive = premium)
   - LTV adjustment: `0 if ltv≤0.80`, `+0.125% if 0.80<ltv≤0.90`, `+0.25% if 0.90<ltv≤0.97`
   - Jumbo premium: `+0.375%` for jumbo product
   - Points discount: `-0.25% per point paid`, max 3 points
   - Output clipped to [3.00%, 14.99%]

7. **`MortgageDecisionResult` dataclass** (similar to PLDecisionResult but with mortgage fields):
   - All PLDecisionResult fields plus: `is_qm`, `pmi_required`, `product_type`, `rate_type`, `points_paid`, `ltv_at_origination`, `property_type`, `atr_factors_passed`, `atr_factors_failed`

8. **Main evaluation function**:
   ```python
   def evaluate_mortgage(
       application: dict,
       pd_score: float,
       fraud_score: float,
       policy_params: dict | None = None,
   ) -> MortgageDecisionResult:
   ```

9. **Batch evaluation** `evaluate_batch(df, policy_params) -> pd.DataFrame` — vectorised.

10. CLI: `python decision_engine/mortgage_origination_policy.py --demo 10`

---

## Phase 2 — Data Generation

### Prompt 2.1 — `data/generate_personal_loans_simulated.py`

**Context to read first:**
- `data/generate_loans_data.py` — Full file. Use same chunking pattern, Parquet output, parallel executor.
- `decision_engine/personal_loan_origination_policy.py` (Prompt 1.2)
- `decision_engine/policy_version_store.py` — `get_as_of(datetime)` usage

**Task:** Generate 750,000 personal loan applications, ~530,000 funded loans, and full payment histories, spread across 2015–2026.

**Requirements:**
1. **Output paths** (create `data/raw/loans/` if missing):
   - `data/raw/loans/personal_loan_applications.parquet`
   - `data/raw/loans/personal_loans_funded.parquet`
   - `data/raw/loans/personal_loan_payments.parquet`

2. **Application volume**: 750,000 rows. Date distribution: weight applications toward 2017–2022 peak years. Use `np.random.choice` with weights, not Python loops.

3. **Products**: `PERS-STD` (65%) and `DEBT-CONS` (35%).

4. **Schema additions** on top of `generate_loans_data.py` base application schema:
   - `decision_id` — UUID4 (new, not deterministic — that's only CC)
   - `policy_version_id` — call `PolicyVersionStore.get_as_of(applied_at)` during generation; cache the store instance; batch calls by date bucket (do not call per-row)
   - `policy_version_tag` — from the returned PolicyVersion
   - `applied_at` — datetime spread 2015-01-01 to 2026-12-31
   - All columns from `PLDecisionResult`: `decision_outcome`, `fcra_reason_codes`, `approved_amount`, `approved_rate`, `term_months`, `monthly_payment`, `apr`, `verification_required`, `fico_tier`, `dti_tier`

5. **Policy-aware decision generation**:
   - Group applications by policy epoch (get unique `applied_at` month buckets)
   - Fetch policy params once per epoch via `PolicyVersionStore.get_as_of(bucket_date)`
   - Call `evaluate_personal_loan()` batch-wise on each epoch group
   - This ensures approval rates naturally vary across the 2015–2026 time range

6. **Funded loans schema** (`personal_loans_funded.parquet`):
   - Only rows where `decision_outcome == "APPROVE"`
   - Additional columns: `loan_id` (UUID4), `principal_amount`, `interest_rate`, `annual_percentage_rate`, `monthly_payment`, `loan_status`, `origination_date` (applied_at + 5–30 days)
   - Loan statuses (derived from origination_date vs. today, + random defaults): `current` (76%), `30dpd` (4%), `60dpd` (2%), `90dpd` (1.5%), `default` (2%), `charged_off` (1.5%), `paid_off` (10%), `in_forbearance` (2%), `modified` (1%)

7. **Payments schema** (`personal_loan_payments.parquet`):
   - Mirror `generate_loans_data.py::generate_payments_for_chunk()` pattern
   - Additional columns: `principal_portion`, `interest_portion`, `fees_portion`, `days_late`, `remaining_balance`
   - Skip fully paid-off loans beyond their payoff date

8. **Additional tables** (write to same `data/raw/loans/` folder):
   - `personal_loan_credit_bureau_pulls.parquet` — mirror `generate_bureau_pulls()` from generate_loans_data.py
   - `personal_loan_modifications.parquet` — for in_forbearance + modified loans only; columns: `modification_id`, `modification_type`, `effective_date`, `reason`

9. **Performance**: Use `ProcessPoolExecutor` for payments (same pattern as `generate_loans_data.py`). Target <5 min on 8-core machine for full 750K set.

10. **CLI**:
    ```bash
    python data/generate_personal_loans_simulated.py \
        --applications 750000 \
        --threads 8 \
        --db-path policy_versions.db \
        --output-dir data/raw/loans/
    ```

---

### Prompt 2.2 — `data/generate_mortgage_simulated.py`

**Context to read first:**
- `data/generate_loans_data.py` — chunking, Parquet output, customer generation
- `data/generate_personal_loans_simulated.py` (Prompt 2.1) — epoch-based policy lookup pattern
- `decision_engine/mortgage_origination_policy.py` (Prompt 1.3)

**Task:** Generate 200,000 mortgage applications, ~140,000 funded mortgages, and payment histories. Fully synthetic — do not parse Freddie Mac zips.

**Requirements:**
1. **Output paths**:
   - `data/raw/loans/mortgage_applications.parquet`
   - `data/raw/loans/mortgages_funded.parquet`
   - `data/raw/loans/mortgage_payments.parquet`

2. **Application distribution**: weight toward 2016–2019 refi boom and 2020–2022 purchase surge; sharply lower 2022-Q3 onward (rate shock).

3. **Property type mix**: `primary_residence` 72%, `second_home` 18%, `investment_property` 10%.

4. **Application schema** — base loan columns from `generate_loans_data.py` + all mortgage-specific columns from PRD §3.2:
   - `property_type`, `occupancy_type`, `appraised_value`, `ltv_at_origination`, `is_qm`, `pmi_required`, `product_type`, `rate_type`, `points_paid`
   - `decision_id` (UUID4), `policy_version_id`, `policy_version_tag`
   - `loan_purpose`: `purchase` (58%), `refinance` (30%), `cash_out_refi` (12%)
   - `va_eligible` (bool, 8% of applicants)
   - `atr_factors_failed` (JSON array, empty if QM)

5. **Funded mortgages schema** — include all fields from `MortgageDecisionResult` plus:
   - `origination_date`, `maturity_date` (origination + term * 30 days)
   - `escrow_monthly` — estimated PITI escrow (property tax + insurance), roughly 0.25% of property value / 12
   - `loan_status` — similar distribution to personal loans but with `in_foreclosure` (0.5%) replacing `charged_off`

6. **Payment schedule** — 30-year loans need special handling: only generate up to `min(origination_date + elapsed_months, today)` payments. Use amortisation formula consistent with `generate_loans_data.py`.

7. **Ensure**: `≥95%` of funded loans with `dti ≤ 0.43` have `is_qm = True` (verification check from PRD §8).

8. **CLI**:
    ```bash
    python data/generate_mortgage_simulated.py \
        --applications 200000 \
        --threads 8 \
        --db-path policy_versions.db \
        --output-dir data/raw/loans/
    ```

---

### Prompt 2.3 — `data/generate_cc_decision_ids.py`

**Context to read first:**
- `data/generate_cc_pd_dataset.py` — origination_5m.parquet schema: `account_id`, `orig_date`, all origination fields
- `decision_engine/policy_version_store.py` — `get_as_of()`
- `compliance/adverse_action.py` — `REG_B_REASON_CODES`

**Task:** Augment `data/raw/cc_pd/origination_5m.parquet` with decision metadata, producing `data/raw/cc_pd/origination_5m_with_decisions.parquet`.

**Requirements:**
1. Load `origination_5m.parquet`. Confirm no duplicate `(account_id, orig_date)` pairs — raise `ValueError` with count if any exist.

2. **Deterministic UUID5** generation:
   ```python
   import uuid
   DECISION_NS = uuid.NAMESPACE_OID

   def make_decision_id(account_id: int, orig_date: pd.Timestamp) -> str:
       key = f"{account_id}:{orig_date.date().isoformat()}"
       return str(uuid.uuid5(DECISION_NS, key))
   ```
   Vectorise using `pd.Series.apply` or a comprehension over zipped arrays — not `.iterrows()`.

3. **Policy version lookup**: batch by month (not per-row). For each unique month in `orig_date`:
   - Call `PolicyVersionStore.get_as_of(month_start)` once
   - Broadcast `policy_version_id` and `policy_version_tag` to all rows in that month

4. **Decision outcome derivation** (use existing origination columns):
   - Map `pd_score` and existing `decision` column (if present) or re-derive:
     - If `fico < policy.fico_floor` → `"REJECT"`, reason `AA01`
     - If `dti > policy.max_dti` → `"REJECT"`, reason `AA04`
     - If approved → `"APPROVE"`
     - Else `"REFER"` (manual review)
   - Produce `decision_outcome` (APPROVE/REJECT/REFER) and `decision_reason_codes` (JSON array)

5. **Write** `origination_5m_with_decisions.parquet` to `data/raw/cc_pd/`. Preserve all original columns. Append only the 4 new columns: `decision_id`, `policy_version_id`, `policy_version_tag`, `decision_outcome`, `decision_reason_codes`.

6. **Verification** print: row count before and after, unique decision_id count (must equal row count), coverage % of `policy_version_id` non-null.

---

## Phase 3 — Decision Registry

### Prompt 3.1 — `data/generate_decision_registry.py`

**Context to read first:**
- `data/raw/cc_pd/origination_5m_with_decisions.parquet` (output of Prompt 2.3)
- `data/raw/loans/personal_loan_applications.parquet` (output of Prompt 2.1)
- `data/raw/loans/mortgage_applications.parquet` (output of Prompt 2.2)
- `compliance/adverse_action.py` — FCRA codes
- `audit/logger.py` — `mask_pii()` (for `customer_id`)

**Task:** Create unified cross-product decision registry in `data/raw/decisions/decision_registry.parquet`.

**Requirements:**
1. **Schema** — exactly as specified in PRD §4. All column names, types, and nullability must match.

2. **Data sourcing**:
   | Source file | product_type | application_id col | customer_id col |
   |---|---|---|---|
   | `origination_5m_with_decisions.parquet` | `credit_card` | `account_id` (cast to str) | `account_id` (SHA-256 via `mask_pii`) |
   | `personal_loan_applications.parquet` | `personal_loan` | `application_id` | `customer_id` |
   | `mortgage_applications.parquet` | `mortgage` | `application_id` | `customer_id` |

3. **Model version IDs**: hardcode mapping:
   - `credit_card` → `"cc_pd_v1"`
   - `personal_loan` → `"pl_pd_v1"`
   - `mortgage` → `"mortgage_pd_v1"`

4. **Underwriter type derivation**:
   - APPROVE with FICO ≥ 720 and fraud_score < 0.05 → `"automated"`
   - APPROVE with 620 ≤ FICO < 720 → `"hybrid"`
   - MANUAL_REVIEW or REFER outcome → `"human_underwriter"`
   - All else → `"automated"`

5. **Override flags**: set `override_flag = True` for 2% of APPROVE rows where FICO was below the policy floor but approved (simulate underwriter override). Set `override_reason` and `override_author` on these rows.

6. **Channels**: derive from source application data if channel column exists; otherwise assign randomly with distribution: `online` 52%, `branch` 20%, `mobile` 15%, `partner` 10%, `phone` 3%.

7. **Referential integrity guarantee**: For every row, verify `policy_version_id` is valid by joining to a snapshot of `policy_versions.db` exported via `store.export_audit_trail()`. Log a warning (do not fail) for any row where the timestamp falls outside the policy's `effective_from`/`superseded_at` window.

8. **Output**:
   - Write `data/raw/decisions/decision_registry.parquet` (create directory if needed)
   - Print: total rows, breakdown by `product_type`, `decision_outcome`, `underwriter_type`
   - Print: referential integrity pass rate (must be 100% or log discrepancies)

---

## Phase 4 — Financial Data

### Prompt 4.1 — `data/generate_org_financials.py`

**Context to read first:**
- `data/raw/loans/personal_loans_funded.parquet`, `data/raw/loans/mortgages_funded.parquet`
- `data/raw/cc_pd/origination_5m.parquet`, `data/raw/cc_pd/txn_summary_5m.parquet`, `data/raw/cc_pd/cost_assumptions.parquet`

**Task:** Generate quarterly org-level P&L + balance sheet for 44 quarters (Q1 2015 → Q4 2026).

**Requirements:**
1. **Output paths**:
   - `data/raw/financials/org_income_statement.parquet`
   - `data/raw/financials/org_balance_sheet.parquet`

2. **Cost of funds rate schedule** — track Fed Funds Rate:
   ```python
   FED_FUNDS_SCHEDULE = [
       ("2015-01-01", 0.0025), ("2015-12-16", 0.005),
       ("2016-12-14", 0.0075), ("2017-03-15", 0.0100),
       ("2017-06-14", 0.0125), ("2017-12-13", 0.0150),
       ("2018-03-21", 0.0175), ("2018-06-13", 0.0200),
       ("2018-09-26", 0.0225), ("2018-12-19", 0.0250),
       ("2019-07-31", 0.0225), ("2019-09-18", 0.0200),
       ("2019-10-30", 0.0175), ("2020-03-03", 0.0125),
       ("2020-03-16", 0.0025), ("2022-03-16", 0.005),
       ("2022-05-04", 0.010), ("2022-06-15", 0.0175),
       ("2022-07-27", 0.025), ("2022-09-21", 0.0325),
       ("2022-11-02", 0.040), ("2022-12-14", 0.045),
       ("2023-02-01", 0.0475), ("2023-03-22", 0.0500),
       ("2023-05-03", 0.0525), ("2024-09-18", 0.0500),
       ("2024-11-07", 0.0475), ("2024-12-18", 0.0450),
       ("2025-03-19", 0.0425), ("2025-05-07", 0.0400),
   ]
   ```
   Function `get_cost_of_funds(date: datetime) -> float` — step function, return rate effective at `date`.

3. **`org_income_statement`** — one row per (quarter, product_type) + one `total` row per quarter:
   - Aggregate funded loan portfolios by product and quarter
   - `interest_income`: sum of interest accrued on outstanding balances per quarter
   - `fee_income`: origination fees earned + late fees from payment data
   - `net_interest_income`: `interest_income − (avg_outstanding × cost_of_funds_rate × 0.25)` (quarterly)
   - `provision_for_credit_losses`: CECL proxy = `avg_outstanding × charge_off_rate_trailing_4q × 1.5` (Stage 1); for 2020-Q2 and 2022-Q1 apply a 2.5× multiplier
   - `net_credit_income`: `NII − provision`
   - `operating_expenses`: flat per-account servicing cost × number_active_accounts per quarter
   - `net_income_before_tax`: `net_credit_income − operating_expenses`
   - `net_interest_margin`: `net_interest_income / avg_outstanding` (annualized)
   - `charge_off_rate`: gross charge-offs in quarter / avg portfolio
   - `recovery_rate`: recoveries / prior gross charge-offs (lag 2 quarters)
   - `net_charge_off_rate`: `charge_off_rate − recovery_rate`

4. **`org_balance_sheet`** — one row per (quarter, product_type) + total:
   - `gross_loan_portfolio_outstanding`: sum of remaining_balance for active loans at quarter-end
   - `allowance_for_credit_losses`: 1.5% × gross_loan_portfolio for Stage 1; 5% for Stage 2; 15% for Stage 3 (use loan_status as stage proxy)
   - `net_loan_portfolio`: gross − ACL
   - `number_of_active_accounts`, `average_loan_balance`, `portfolio_yield`
   - DPD rates: count loans by status (30dpd / 60dpd / 90dpd), divide by total loans
   - `delinquency_rate`: (30dpd + 60dpd + 90dpd) / total

5. **Provision spike constraint** (PRD §8 check 5): After generation, assert `provision_2020Q2 ≥ 2 × provision_2019Q4` and `provision_2022Q1 ≥ 2 × provision_2019Q4`. Raise `AssertionError` with details if either fails.

6. **Financial reconciliation** (PRD §8 check 6): assert sum of monthly interest income from `loan_monthly_ledger` (if available) ≈ quarterly interest_income within 1% tolerance.

---

### Prompt 4.2 — `data/generate_loan_economics.py`

**Context to read first:**
- `data/raw/loans/personal_loans_funded.parquet`, `data/raw/loans/personal_loan_payments.parquet`
- `data/raw/loans/mortgages_funded.parquet`, `data/raw/loans/mortgage_payments.parquet`
- `data/raw/cc_pd/origination_5m.parquet`, `data/raw/cc_pd/txn_summary_5m.parquet`, `data/raw/cc_pd/cost_assumptions.parquet`
- `data/generate_org_financials.py` — `get_cost_of_funds()` function (import it)

**Task:** Generate per-loan itemized ledger + CC account monthly economics.

**Requirements:**
1. **Output paths**:
   - `data/raw/financials/loan_origination_economics.parquet`
   - `data/raw/financials/loan_monthly_ledger.parquet`
   - `data/raw/financials/cc_account_monthly_economics.parquet`

2. **`loan_origination_economics`** — one row per funded loan (personal + mortgage combined):
   - All columns from PRD §5.2 exactly
   - Fee schedules (vectorised):
     - Personal loan: `origination_fee_rate` = 1.5–5% (inversely proportional to FICO), `processing_fee` = $250 flat, `doc_prep_fee` = $50
     - Mortgage: `appraisal_fee` = $400–$600 random, `title_insurance_fee` = 0.5% of loan, `recording_fee` = $125, `escrow_fee` = $350; `broker_commission` = 1% of loan if channel == 'partner' else null
   - `cost_of_funds_at_origination`: call `get_cost_of_funds(origination_date)` + 150bps spread
   - `initial_net_spread`: `note_rate − cost_of_funds_at_origination`

3. **`loan_monthly_ledger`** — one row per (loan_id × calendar_month):
   - Generate from `origination_date` to `min(today, maturity_date)` for each loan
   - This will be ~50M rows for personal loans + ~200M rows for 30yr mortgages — **must use chunked Parquet writes** (`pyarrow.parquet.ParquetWriter` with row group size 500K), not `.to_parquet()` on the full frame
   - Use effective interest method for `interest_income_recognized`
   - `stage` assignment: 1 = current, 2 = 30-60dpd or in_forbearance, 3 = 90dpd+ or default
   - `credit_loss_provision`: 0.5% annualized / 12 for Stage 1; 3% / 12 for Stage 2; 15% / 12 for Stage 3 of remaining balance
   - `servicing_cost_allocation`: 50bps / 12 × remaining_balance
   - `cost_of_funds_allocation`: `get_cost_of_funds(ledger_month) + 150bps` / 12 × remaining_balance

4. **`cc_account_monthly_economics`** — one row per (account_id × ledger_month):
   - Source from `txn_summary_5m.parquet` (monthly aggregates) + `cost_assumptions.parquet`
   - All columns from PRD §5.2 exactly
   - `interchange_revenue`: 1.8% × purchase_volume_month (approximate from annual `interchange_rev_12m / 12`)
   - `rewards_cost`: reward_rate × purchase_volume_month
   - `cost_of_funds_allocation`: `get_cost_of_funds(ledger_month)` / 12 × avg_balance_month
   - **Note**: CC accounts only have 12 months of transaction data in `txn_summary_5m`. Generate 12 ledger rows per account.

5. **Chunked writes** for `loan_monthly_ledger` — process loans in batches of 10,000 to stay within memory limits. Print progress every 100K rows.

---

## Phase 5 — Governance Documentation

> All 77 Markdown files follow a strict structural template. Use a single Python script to generate them programmatically, then write each to disk. Do not hand-write 77 files.

### Prompt 5.1 — Policy Manuals Generator

**Task:** Create a Python script `scripts/generate_governance_docs.py` with a function `generate_policy_manuals()` that writes 9 Markdown files to `docs/governance/policy_manuals/`.

**Requirements for each policy manual:**

Each file must include these 9 sections (see PRD §6.1):

1. **Purpose & Scope** — product name, regulatory framework (TILA, ECOA, RESPA/TRID for mortgage), date range
2. **Effective Date & Version History** — table linking to `policy_version_tag` values from the seeder (Phase 1). Each epoch covered by the manual must have a row.
3. **Eligible Borrower Profile** — FICO tiers, DTI limits, income requirements, employment requirements for that epoch
4. **Product Parameters** — loan limits, rate ranges, term options; must reflect the macro-cycle phase (e.g., 2019-2022 manual shows tighter limits during COVID-19 period)
5. **Underwriting Guidelines** — income verification matrix (bank statement / paystub / tax return thresholds), exception process (credit committee escalation)
6. **Pricing Matrix** — rate tier table by risk grade (Super-Prime through Near-Prime), showing base rates + spreads
7. **Approval Authority Matrix** — automated (FICO ≥ 720, fraud < 5%, no derogatories) / loan officer ($250K+ or near-prime) / credit committee (jumbo, exceptions, overrides)
8. **Regulatory Compliance Notes** — ECOA (FCRA reason codes), TILA (APR disclosure), RESPA/TRID (3-day LOAN ESTIMATE, 3-day Closing Disclosure for mortgage), state usury limits
9. **Change Log** — each policy version change in the manual's epoch with date, change description, and Board Resolution reference. Example: `"2020-03-20: FICO floor tightened from 620 to 660 — COVID-19 emergency response, ref. Board Resolution 2020-03"`

**Content matrix** — generate per the epoch→parameter values in Prompt 1.1 table. The 2019–2022 manual must include distinct COVID sections.

**Front matter** (YAML block at top of each file, consumed by LucidCredit ingestor in Phase 6):
```yaml
---
product_type: credit_card | personal_loan | mortgage
effective_from: YYYY-MM-DD
effective_to: YYYY-MM-DD
doc_type: policy_manual
version_tag: cc-policy-2015-2018 | pl-policy-2019-2022 | etc.
---
```

---

### Prompt 5.2 — Committee Minutes Generator

**Task:** Add `generate_committee_minutes()` function to `scripts/generate_governance_docs.py` that writes 44 Markdown files to `docs/governance/committee_minutes/`.

**File naming**: `YYYY_QN_credit_committee_minutes.md`

**Standard sections** (all 44 files):
1. **Meeting Header** — date (last day of quarter: Mar 31 / Jun 30 / Sep 30 / Dec 31), location, quorum status, attendees (CEO, CRO, CFO, Chief Credit Officer, Model Risk Officer, Compliance Officer, 2 independent directors)
2. **Prior Period Performance Review** — approval rate (%), delinquency rate (%), charge-off rate (bps), provision expense ($M) vs. budget — use numbers consistent with the financial data from Phase 4
3. **Policy Change Proposals & Votes** — unanimous / majority / tabled
4. **Model Performance Update** — PSI, AUC, KS statistic for active models; flag if PSI > 0.2
5. **Regulatory Horizon Items** — CFPB rulemaking, state law changes, Fed guidance relevant to the quarter
6. **Action Items & Next Meeting Date**

**Four extended milestone sessions** (significantly more detail):

- **`2018_Q4`**: Rate hike policy review. Detail the Fed rate path (+125bps in 18 months), credit quality discussion, vote to raise CC FICO floor from 640→660 and PL FICO floor from 600→620, APR repricing discussion.
- **`2020_Q1`**: COVID-19 emergency session (label as "SPECIAL EMERGENCY MEETING — March 20, 2020"). Credit freeze resolution (FICO floors +30–40pts), jumbo halt, hardship hotline activation, forbearance program authorized. Unanimous vote. Board Resolution 2020-03 referenced.
- **`2020_Q3`**: COVID forbearance program status. Modified income verification standards adopted. Stage 2 loan migration discussed (CECL impact). Stimulus credit quality improvement noted.
- **`2022_Q2`**: Inflation/rate response. Emergency APR repricing (personal loans: +150bps), refi volume collapse discussion, HELOC demand spike, DTI floor tightening vote.

**Front matter** (YAML):
```yaml
---
doc_type: committee_minutes
quarter: YYYY-QN
meeting_date: YYYY-MM-DD
products_covered: [credit_card, personal_loan, mortgage]
---
```

---

### Prompt 5.3 — Model Validation Reports Generator

**Task:** Add `generate_model_validation_reports()` function to `scripts/generate_governance_docs.py` that writes 12 Markdown files to `docs/governance/model_validation/`.

**File naming**: `model_validation_YYYY.md`

**Structure per report:**
1. **Models in Scope** — PD model (cc_pd_v1 / pl_pd_v1 / mortgage_pd_v1), scorecard versions
2. **Data Window** — 12-month outcome window, population definition, N in-sample / N out-of-sample
3. **Performance Metrics**:
   - KS statistic (realistic: 45–62 across years)
   - Gini coefficient (0.55–0.70)
   - AUC-ROC (0.75–0.87)
   - Brier score
4. **PSI Table** — by characteristic (FICO, DTI, utilisation); flag PSI > 0.2 as requiring investigation
5. **Characteristic Stability Analysis** — population shift by vintage
6. **Outcome Analysis** — realized default rate vs. model-predicted PD; calibration chart description
7. **Findings** — severity: Critical / Significant / Informational; include at least one Significant finding per report related to PSI drift on DTI during 2020–2022
8. **Remediation Plan** — timeline, responsible party
9. **SR 11-7 Status** — Approved / Approved with Conditions / Rejected; sign-off fields

**Key data points to be internally consistent:**
- 2020 report: flag high PSI on employment status variable (COVID-19 population shift)
- 2022 report: flag PSI > 0.25 on DTI distribution (rate hike-driven shift); model recalibration recommended
- 2023 report: recalibration complete, PSI normalized

**Front matter**:
```yaml
---
doc_type: model_validation
report_year: YYYY
models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
sr11_7_status: Approved | Approved with Conditions
---
```

---

### Prompt 5.4 — Fair Lending Reports Generator

**Task:** Add `generate_fair_lending_reports()` function to `scripts/generate_governance_docs.py` that writes 12 Markdown files to `docs/governance/fair_lending/`.

**File naming**: `fair_lending_YYYY.md`

**Structure per report:**
1. **HMDA LAR Summary** — total mortgage applications, breakdown by action taken (originated, approved not accepted, denied, withdrawn, incomplete), by property type (single-family, multifamily, manufactured), by loan purpose (purchase, refi, cash-out)
2. **Approval Rate Disparity Analysis** — by demographic proxy: White non-Hispanic (control), Hispanic, Black/African-American, Female applicant. Report approval rates and adverse impact ratios (AIR = minority rate / control rate). Flag AIR < 0.80.
3. **APR Pricing Disparity Analysis** — mean APR by group, regression-adjusted mean difference controlling for FICO, DTI, LTV, loan amount. Flag if adjusted spread > 15bps.
4. **Statistical Methodology** — logistic regression with matched controls; redlining geographic analysis for mortgage; intersectional analysis
5. **Disparate Impact Findings** — any flagged disparities with root cause analysis
6. **Corrective Actions** — if any disparities found: remediation steps, timeline, monitoring plan
7. **Fair Lending Officer Sign-off**

**Data consistency requirements**:
- Numbers should be plausible and consistent with the 200K mortgage applications generated in Phase 2
- 2020 report: note COVID-19 application volume drop; note no systemic disparities found
- 2022 report: note elevated denial rates broadly (policy tightening), no demographic-specific disparities
- At least one year (e.g., 2019) should show a marginal AIR flag on APR pricing that was investigated and resolved

**Front matter**:
```yaml
---
doc_type: fair_lending
report_year: YYYY
products_covered: [credit_card, personal_loan, mortgage]
hmda_reporting: true
---
```

---

## Phase 6 — LucidCredit Integration

### Prompt 6.1 — `LucidCredit/backend/app/rag/policy_doc_ingestor.py`

**Context to read first:**
- `LucidCredit/` directory structure — identify existing `embedder.py`, `policy_docs` table migration, pgvector setup
- `docs/governance/` directory (just created in Phase 5) — understand YAML front-matter format

**Task:** Create `backend/app/rag/policy_doc_ingestor.py` in the LucidCredit project.

**Requirements:**
1. **Document scanning**:
   ```python
   def scan_governance_docs(root_path: Path) -> list[Path]:
       """Recursively find all *.md files under root_path."""
   ```
   Default `root_path` = `../credit-risk-platform/docs/governance/` (relative to LucidCredit repo).

2. **Front-matter extraction**:
   ```python
   def extract_front_matter(md_path: Path) -> dict:
       """Parse YAML front matter between --- delimiters. Return {} if absent."""
   ```
   Required fields: `doc_type`, `product_type` (optional for committee_minutes), `effective_from`.
   Infer `effective_to` from `report_year` if not present.

3. **Chunking strategy**:
   ```python
   def chunk_document(text: str, max_tokens: int = 512, overlap_tokens: int = 100) -> list[str]:
       """Paragraph-level chunking with token overlap."""
   ```
   - Split on double-newline paragraph boundaries first
   - Merge short paragraphs (< 50 tokens) with next
   - Respect `max_tokens` hard limit — split oversized paragraphs at sentence boundaries
   - Overlap: last `overlap_tokens` tokens of chunk N prepended to chunk N+1

4. **Embedding**: call existing `embedder.py` (discover its interface by reading the file — do not assume the function signature). Batch embed in groups of 64 to avoid rate limits.

5. **Upsert to pgvector**:
   ```python
   async def upsert_chunks(
       chunks: list[dict],  # {text, embedding, metadata}
       db_session: AsyncSession,
   ) -> int:
       """INSERT ... ON CONFLICT (source_path, chunk_index) DO UPDATE. Returns rows upserted."""
   ```
   Table: `policy_docs`. Columns: `id`, `source_path`, `chunk_index`, `content`, `embedding` (vector), `source_type`, `product_type`, `effective_from`, `effective_to`, `version_tag`, `doc_type`, `metadata_json`.

6. **Main ingestion pipeline**:
   ```python
   async def ingest_all(
       governance_root: Path,
       db_url: str,
       dry_run: bool = False,
   ) -> dict:
       """
       Returns summary: {
           "docs_found": int,
           "chunks_created": int,
           "rows_upserted": int,
           "errors": list[str],
       }
       """
   ```

7. **CLI**:
   ```bash
   python backend/app/rag/policy_doc_ingestor.py \
       --governance-root ../credit-risk-platform/docs/governance/ \
       --db-url postgresql+asyncpg://... \
       --dry-run
   ```

8. **Verification** (PRD §8 check 7): After ingestion, query `SELECT COUNT(*), COUNT(DISTINCT product_type), COUNT(DISTINCT doc_type) FROM policy_docs` and assert count ≥ 9 (one per governance doc minimum), `product_type` non-null on policy manual rows, `effective_from` non-null on all rows.

---

## Verification Checklist

After all phases complete, run these checks. Each maps to PRD §8.

| # | Command/Check | Pass Condition |
|---|---|---|
| 1 | `python decision_engine/policy_history_seeder.py --dry-run` | Prints 22 snapshots; no date gaps |
| 2 | Compare PL approval rates: `2015–16 avg vs. 2020-Q2` | ≥5% higher in 2015–16 |
| 3 | `SELECT is_qm, COUNT(*) FROM mortgages WHERE dti <= 0.43 GROUP BY is_qm` | ≥95% rows have `is_qm=True` |
| 4 | `decision_registry.parquet` → join to policy version audit trail | 100% join rate |
| 5 | `org_income_statement`: Q2 2020 and Q1 2022 provision vs. Q4 2019 | Both ≥ 2× baseline |
| 6 | Sum `loan_monthly_ledger.interest_income_recognized` by quarter vs. `org_income_statement` | Within 1% |
| 7 | `SELECT COUNT(*) FROM policy_docs` | ≥ 9 documents ingested |
| 8 | Trace 3 sampled `decision_id` values end-to-end | Full chain reconstructable |

---

## Dependency Graph

```
Prompt 1.1 (policy_history_seeder)
    │
    ├─► Prompt 1.2 (personal_loan_origination_policy)
    │       │
    │       └─► Prompt 2.1 (generate_personal_loans_simulated)
    │
    ├─► Prompt 1.3 (mortgage_origination_policy)
    │       │
    │       └─► Prompt 2.2 (generate_mortgage_simulated)
    │
    └─► Prompt 2.3 (generate_cc_decision_ids)
              │
              ├─► Prompt 3.1 (generate_decision_registry)  [also depends on 2.1, 2.2]
              │       │
              │       └─► Prompt 4.1 (generate_org_financials)  [also depends on 2.1, 2.2]
              │               │
              │               └─► Prompt 4.2 (generate_loan_economics)
              │
              └─► Prompt 5.1 (policy_manuals)  ─┐
                  Prompt 5.2 (committee_minutes) ├─► Prompt 6.1 (policy_doc_ingestor)
                  Prompt 5.3 (model_validation)  │
                  Prompt 5.4 (fair_lending)      ─┘
```

**Prompts that can run in parallel** (after their dependencies are met):
- 1.2 and 1.3 (both depend only on 1.1)
- 2.1, 2.2, 2.3 (each depends on 1.x but not each other)
- 5.1, 5.2, 5.3, 5.4 (all independent; each is a function in the same script)
