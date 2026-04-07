# GOVERNANCE REMEDIATION — IMPLEMENTATION PLAN
## Credit Risk Platform — April 6, 2026

> **Derived from:** `GOVERNANCE_AUDIT_2026_04_06.md`
> **Target state:** SR 11-7 compliant, CECL-ready, CFPB-defensible
> **Horizon:** 12 months across 3 phases

Each entry below is a **self-contained coding prompt** that can be handed directly to an engineer or AI coding session. Prompts are ordered by dependency — complete them top-to-bottom within each phase.

---

## Phase 1 — Critical Remediation (0–3 Months)
*These are pre-production blockers. No real money should flow through this platform until all P1 items are complete.*

---

### PROMPT P1.1 — Point-in-Time Feature Store

**Severity:** CRITICAL — all existing backtests are suspect for look-ahead bias
**File:** `feature_pipeline/feature_store.py`
**Also touches:** `db/schema.sql`, `feature_pipeline/tests/test_feature_store.py`

```
You are implementing point-in-time correctness for the credit risk feature store.

CONTEXT
-------
File: feature_pipeline/feature_store.py
The current `write_features()` function writes features keyed by `application_id`
and `feature_set_version` (string). There is no `event_timestamp` or `as_of_date`
column. This means any backtest that reads the feature store can inadvertently
pull future feature values for a historical application — classic look-ahead bias.
This is a SR 11-7 model risk finding.

TASK
----
1. In `feature_pipeline/feature_store.py`:
   a. Add `event_timestamp: datetime` (the moment the feature row was computed)
      and `as_of_date: date` (the business date the features represent) parameters
      to `write_features()`. Both should be required, with no default.
   b. Persist both columns into the `features` table. Update the upsert SQL so the
      conflict key is `(application_id, feature_set_version, as_of_date)` — NOT
      just `application_id`. This prevents a newer feature row from silently
      overwriting a historical row.
   c. Add a new function `read_features_as_of(application_ids: list[str],
      as_of_date: date, feature_set_version: str, engine: AsyncEngine) -> pd.DataFrame`
      that executes: WHERE application_id IN (...) AND as_of_date <= :as_of_date
      ORDER BY as_of_date DESC — returning only the latest row at or before the
      requested date.
   d. Add a `FeatureStoreAuditProof` dataclass with fields:
      application_id, feature_set_version, as_of_date, event_timestamp, feature_hash
      where feature_hash = sha256(sorted JSON of all feature values).
      Every call to `read_features_as_of()` must write one audit proof record
      to a `feature_read_audit` table.

2. In `db/schema.sql`:
   a. Add `event_timestamp TIMESTAMPTZ NOT NULL` and `as_of_date DATE NOT NULL`
      to the `features` table.
   b. Drop the old unique constraint on `(application_id, feature_set_version)`.
   c. Add unique constraint on `(application_id, feature_set_version, as_of_date)`.
   d. Add `feature_read_audit` table:
      id SERIAL PK, application_id TEXT, feature_set_version TEXT, as_of_date DATE,
      event_timestamp TIMESTAMPTZ, feature_hash TEXT, read_at TIMESTAMPTZ DEFAULT NOW().

3. In `feature_pipeline/tests/test_feature_store.py`:
   a. Add `test_no_lookahead_bias()`: write feature row at as_of_date=2024-01-15,
      then write a DIFFERENT feature row for the same app at as_of_date=2024-06-01.
      Query with as_of_date=2024-03-01 and assert the returned values match the
      2024-01-15 row — proving that the June update did not pollute the March read.
   b. Add `test_audit_proof_written()`: confirm that after `read_features_as_of()`
      a row in `feature_read_audit` exists with a valid non-empty feature_hash.

CONSTRAINTS
-----------
- Do not break the existing `write_features()` public API — keep it but add the
  new required parameters with no defaults so callers must be updated explicitly.
- Keep all async (AsyncEngine / asyncpg). No sync SQLAlchemy.
- All new columns must be NOT NULL with sensible DDL defaults where appropriate.
- The feature_hash must be deterministic: sort keys before json.dumps.
```

---

### PROMPT P1.2 — Monotonic Constraints in LightGBM PD Model

**Severity:** CRITICAL — non-monotone regions create fair lending exposure
**File:** `models/credit_risk/train_cc_pd_model.py`
**Also touches:** `models/credit_risk/cc_pd_scorecard.json` (or model card JSON)

```
You are enforcing monotonic constraints in the LightGBM credit card PD model.

CONTEXT
-------
File: models/credit_risk/train_cc_pd_model.py
The current model trains a LightGBM binary classifier with Optuna tuning but
does NOT pass the `monotone_constraints` parameter. Without monotonic constraints,
the model can produce regions where a higher FICO score increases predicted PD —
a non-intuitive result that can proxy discrimination and will be challenged in a
CFPB examination.

TASK
----
1. Define a `MONOTONE_CONSTRAINT_MAP: dict[str, int]` constant near the top of
   the file. Map each feature name to:
     +1  = higher value → lower PD (protective; e.g., fico_score, annual_income,
           months_oldest_trade, payment_history_score)
     -1  = higher value → higher PD (risk-increasing; e.g., dti, num_derog_marks,
           pct_rev_utilization, num_recent_inquiries)
      0  = no constraint (categorical, interaction terms, unclear direction)
   Document the rationale for each assignment in an inline comment.

2. In the LightGBM `.fit()` or `lgb.train()` call, construct the
   `monotone_constraints` parameter as an ordered list aligned to the feature
   column order at training time:
     constraints = [MONOTONE_CONSTRAINT_MAP.get(col, 0) for col in feature_cols]
   Pass as `model.set_params(monotone_constraints=constraints)` for sklearn API
   or as `params["monotone_constraints"] = constraints` for lgb.train().

3. When Optuna tunes hyperparameters, ensure monotone_constraints is NOT a
   tunable parameter — it is always applied from `MONOTONE_CONSTRAINT_MAP`.

4. After training, add a `verify_monotonicity()` function that:
   a. Takes the trained model and training DataFrame.
   b. For each constrained feature (constraint != 0), sweeps that feature from
      5th to 95th percentile while holding all other features at their median.
   c. Asserts that predicted PD moves in the expected direction (strictly
      monotone within tolerance 1e-5).
   d. Logs a `MonotonicityCheckResult` dataclass with: feature, constraint_dir,
      passes (bool), min_delta, max_delta.
   e. Raises `ValueError` if any constrained feature fails the check.

5. Write the constraint vector and monotonicity check results to the model card
   JSON artifact (create or update `cc_pd_model_card.json`) under keys:
   `monotone_constraints` and `monotonicity_verification`.

6. Add a pytest in `tests/models/test_cc_pd_monotonicity.py` that loads the
   trained model artifact and runs `verify_monotonicity()`, requiring all
   constrained features to pass.

CONSTRAINTS
-----------
- The monotone_constraints list MUST be aligned to the actual feature column
  order used at fit time — derive it programmatically, not hardcoded by index.
- Do not remove Optuna tuning for other hyperparameters.
- verify_monotonicity() must run in < 30 seconds on any laptop.
```

---

### PROMPT P1.3 — Data Quality Enforcement Module

**Severity:** CRITICAL — training data is indefensible without quality controls
**File:** `data_quality/expectations.py` (NEW)
**Also touches:** `data_quality/__init__.py` (NEW), `models/credit_risk/train_cc_pd_model.py`

```
You are building a data quality enforcement module for the credit risk platform.

CONTEXT
-------
There are zero data quality controls anywhere in the codebase. Great Expectations
was planned but never implemented. An examiner asking "How do you know your
training data is clean?" gets nothing today. This module is a pre-requisite for
any SR 11-7 model development documentation.

TASK
----
1. Create `data_quality/__init__.py` exporting:
   DataQualityReport, DataQualityRule, run_expectations, assert_quality_gate

2. Create `data_quality/expectations.py` implementing:

   a. `DataQualityRule` dataclass:
      name: str, description: str, column: str | None, check: Callable[[pd.DataFrame], bool],
      severity: Literal["ERROR", "WARNING"], expected: str

   b. `DataQualityReport` dataclass:
      dataset_name: str, run_at: datetime, total_rules: int, passed: int, failed: int,
      errors: list[dict], warnings: list[dict], quality_score: float (0–1),
      gate_passed: bool  # True only if zero ERROR-severity failures

   c. `CC_PD_TRAINING_RULES: list[DataQualityRule]` — the standard expectation
      suite for the CC PD training dataset. Must include:
      - Schema: all required columns present (fico_score, dti, annual_income, etc.)
      - Dtype: fico_score is numeric, dti is float between 0 and 1.5
      - Range: fico_score between 300 and 850 (ERROR if violated)
      - Range: dti between 0 and 2.0 (ERROR), and < 1.0 for > 99% of rows (WARNING)
      - Completeness: months_since_last_delinq null rate < 15% (WARNING)
      - Completeness: fico_score null rate = 0% (ERROR)
      - Cross-field: annual_fee > 0 only when product in ("premium", "secured") (ERROR)
      - Uniqueness: application_id has zero duplicate rows (ERROR)
      - Target: default_flag is binary 0/1 only (ERROR)
      - Target: default_rate between 1% and 25% — flag if outside (WARNING)

   d. `run_expectations(df: pd.DataFrame, rules: list[DataQualityRule],
      dataset_name: str) -> DataQualityReport`:
      Runs all rules, catches exceptions per rule (a single bad rule should not
      abort the whole run), populates DataQualityReport.

   e. `assert_quality_gate(report: DataQualityReport) -> None`:
      Raises `DataQualityGateError(report)` if `report.gate_passed` is False.
      The exception message must list each ERROR-severity failure by name.

   f. `save_report(report: DataQualityReport, path: Path) -> None`:
      Serializes to JSON using dataclasses.asdict(). Writes to path.

3. In `models/credit_risk/train_cc_pd_model.py`, before any feature engineering:
   a. Import and run `run_expectations(raw_df, CC_PD_TRAINING_RULES, "cc_pd_training")`.
   b. Call `assert_quality_gate(report)` — training aborts if data fails.
   c. Call `save_report(report, Path("reports/data_quality/cc_pd_training_{timestamp}.json"))`.
   d. Log the quality_score and gate_passed status via the existing audit logger.

4. Create `tests/data_quality/test_expectations.py` with:
   - test_clean_data_passes_all_rules(): inject a valid synthetic DataFrame
   - test_null_fico_triggers_error(): set fico_score column to NaN, assert gate fails
   - test_bad_target_distribution_triggers_warning(): set default_rate = 0.5, assert
     WARNING is present but gate still passes (since it is WARNING not ERROR)
   - test_duplicate_application_id_triggers_error(): duplicate one row, assert gate fails

CONSTRAINTS
-----------
- Pure Python + pandas + standard library only. No Great Expectations dependency.
- DataQualityRule.check is a lambda/function receiving the full DataFrame; it must
  return bool (True = rule passes).
- All report artifacts must be JSON-serializable (use str for datetime, float for numpy).
- The module must run end-to-end in < 5 seconds on a 1M-row DataFrame.
```

---

### PROMPT P1.4 — Automated Model Development Report Generator

**Severity:** HIGH — MDR documentation mismatch is the #1 SR 11-7 finding
**File:** `compliance/generate_model_doc.py` (NEW)
**Also touches:** `compliance/__init__.py`, `scripts/mrm_lifecycle.py`

```
You are building a Model Development Report (MDR) generator that auto-populates
from MLflow run metadata.

CONTEXT
-------
File: scripts/mrm_lifecycle.py (556 lines — existing MRM lifecycle CLI)
The platform has an MLflow registry and a full MRM workflow, but model
documentation exists only as narrative prose in ThinFile/docs/. There is no
MDR template and no automated way to produce one. The audit's sample MDR YAML
(Section 7A) is the target output format.

TASK
----
1. Create `compliance/generate_model_doc.py` implementing:

   a. `ModelDocumentationConfig` dataclass:
      mlflow_run_id: str, risk_tier: Literal[1, 2, 3],
      use_classification: Literal["DECISION_CRITICAL", "DECISION_SUPPORT", "INFORMATIONAL"],
      owner_email: str, review_cycle_months: int = 12,
      assumption_overrides: list[dict] = field(default_factory=list)

   b. `generate_mdr(config: ModelDocumentationConfig, mlflow_tracking_uri: str,
      output_dir: Path) -> tuple[Path, Path]`:
      - Connect to MLflow using `mlflow.tracking.MlflowClient`.
      - Pull: run params, run metrics, run tags, registered model info, artifact list.
      - Compute sha256 of the primary model artifact (`.pkl` or `.txt` file) from the
        MLflow artifact store path.
      - Populate the MDR YAML structure from Section 7A of the governance audit:
        model_identity, purpose_and_scope, data, performance, limitations,
        assumptions (merging defaults + assumption_overrides from config), governance.
      - Auto-populate default assumptions from the model's params:
        if "lgd" not in run.params: add assumption A001 (hardcoded LGD);
        if "cost_of_funds" not in run.params: add assumption A002.
      - Write output_dir/mdr_{model_name}_{run_id[:8]}.yaml (YAML).
      - Write output_dir/mdr_{model_name}_{run_id[:8]}.json (JSON — same content).
      - Set MLflow tag `mdr_artifact_path` = the output YAML path and
        `mdr_generated_at` = ISO timestamp.
      - Return (yaml_path, json_path).

   c. `validate_mdr_completeness(mdr_dict: dict) -> list[str]`:
      Returns a list of human-readable errors for any required MDR field that is
      missing or contains a template placeholder like "{{...}}". Required fields:
      model_identity.model_id, model_identity.risk_tier, purpose_and_scope.intended_use,
      data.training_dataset.record_count, performance.hold_out_auc,
      limitations (non-empty list), governance.approved_by.

2. Add a CLI entry to `scripts/mrm_lifecycle.py`:
   `python scripts/mrm_lifecycle.py generate-mdr --run-id <run_id> \
     --risk-tier 2 --use-class DECISION_CRITICAL --owner ds@example.com \
     --output-dir reports/model_docs/`
   The command should call `generate_mdr()` then `validate_mdr_completeness()`.
   If there are completeness errors, print them as warnings (do not abort).
   Print the output file path on success.

3. Create `tests/compliance/test_generate_model_doc.py`:
   - Mock the MLflow client to return a fake run with known params/metrics/tags.
   - test_mdr_yaml_is_valid(): run generate_mdr(), parse YAML output, assert all
     required keys are present.
   - test_mdr_sha256_is_correct(): mock artifact binary, assert sha256 matches.
   - test_validate_completeness_catches_missing_auc(): remove hold_out_auc from
     the dict, assert validate_mdr_completeness() returns a non-empty error list.
   - test_validate_completeness_catches_placeholder(): set approved_by = "{{cro_email}}",
     assert completeness check flags it.

CONSTRAINTS
-----------
- Use PyYAML for YAML output (already in requirements.txt via mlflow).
- The sha256 must be computed on the raw bytes of the artifact file — not the path.
- Do not require the artifact to be local — use mlflow.artifacts.download_artifacts()
  to a temp dir, compute hash, then delete.
- All template placeholders in the MDR YAML (Section 7A) must be replaced with
  actual values or the string "REQUIRES_MANUAL_ENTRY" if not available.
- Idempotent: re-running generate_mdr() for the same run_id overwrites output files.
```

---

### PROMPT P1.5 — BISG Proxy for Fair Lending Analysis

**Severity:** CRITICAL — CFPB HMDA examinations require proxy methodology
**File:** `monitoring/fair_lending.py`
**Also creates:** `monitoring/bisg.py` (NEW)

```
You are adding BISG (Bayesian Improved Surname Geocoding) proxy methodology
to the fair lending analysis module.

CONTEXT
-------
File: monitoring/fair_lending.py (332 lines)
The existing `analyze_fair_lending()` function requires a `demographic_group`
column in the decisions DataFrame. In real deployments, lenders cannot store
race/ethnicity in non-HMDA origination databases. The CFPB-approved approach
is BISG: combine surname probability tables (Census Bureau) with census tract
race distributions (ACS 5-Year) to estimate P(race | surname, geography).

TASK
----
1. Create `monitoring/bisg.py` implementing the BISG algorithm:

   a. `load_surname_table(path: Path | None = None) -> pd.DataFrame`:
      Load the Census Bureau surname frequency CSV
      (https://www.census.gov/topics/population/genealogy/data/2010_surnames.html).
      Columns to produce: surname (uppercase), p_white, p_black, p_asian,
      p_hispanic, p_other. If path is None, use a bundled minimal lookup table
      of 200 most common surnames as fallback. Cache in module-level dict.

   b. `load_tract_demographics(tract_fips: str | pd.Series,
      acs_data: pd.DataFrame | None = None) -> pd.DataFrame`:
      Return ACS 5-Year census tract race distribution for given FIPS codes.
      Columns: tract_fips, p_white, p_black, p_asian, p_hispanic, p_other.
      If acs_data is None, return uniform 0.2 for all groups (fallback mode —
      must be clearly flagged in the output).

   c. `compute_bisg_probabilities(df: pd.DataFrame,
      surname_col: str = "surname",
      tract_col: str = "census_tract",
      surname_table: pd.DataFrame | None = None,
      acs_data: pd.DataFrame | None = None) -> pd.DataFrame`:
      Implements the BISG update:
        P(r | surname, geo) ∝ P(surname | r) × P(r | geo)
      Normalizes to sum to 1 across race groups for each applicant.
      Returns input df with appended columns:
        bisg_p_white, bisg_p_black, bisg_p_asian, bisg_p_hispanic, bisg_p_other,
        bisg_mode_race (argmax), bisg_fallback_used (bool).
      Log a WARNING if more than 20% of rows use fallback.

   d. `assign_proxy_group(df: pd.DataFrame,
      protected_group: str,       # e.g. "black"
      control_group: str,         # e.g. "white"
      threshold: float = 0.5) -> pd.DataFrame`:
      Add column `proxy_group` = protected_group if bisg_p_{protected_group} >= threshold,
      else control_group if bisg_p_{control_group} >= threshold, else "other".
      Also add `proxy_weight_{protected_group}` = bisg_p_{protected_group} for use
      in weighted DIR calculations.

2. In `monitoring/fair_lending.py`:
   a. Add an optional preprocessing step at the top of `analyze_fair_lending()`:
      if `demographic_group` column is absent AND both `surname` + `census_tract`
      columns are present, auto-call `compute_bisg_probabilities()` then
      `assign_proxy_group()`, and set `demographic_group = "proxy_group"`.
   b. When BISG proxy is used, add a `proxy_methodology` field to `FairLendingReport`:
      method = "BISG", protected_group, control_group, threshold, fallback_pct.
   c. Add a `weighted_dir_calculation` field to `FairLendingReport` that computes a
      probability-weighted DIR using `proxy_weight_{protected_group}` instead of
      hard-assigned groups (CFPB preferred methodology for proxy-based analysis).
      Weighted approval rate = sum(proxy_weight × decision) / sum(proxy_weight).

3. In `monitoring/tests/test_fair_lending.py`:
   a. test_bisg_proxy_auto_applied(): build a DataFrame with `surname` + `census_tract`
      but no `demographic_group`; assert `analyze_fair_lending()` runs without error
      and report.proxy_methodology is not None.
   b. test_weighted_dir_differs_from_unweighted(): verify that weighted and
      unweighted DIR values are computed and may differ (do not assert equal).
   c. test_bisg_updates_correctly(): manually supply a single-row DataFrame with
      known surname priors and tract priors; verify posterior sums to 1.0.

CONSTRAINTS
-----------
- Do not make any external HTTP calls — all data is loaded from local files or
  fallback tables. The module must work offline.
- BISG probabilities must always sum to 1.0 per row (normalize even if priors
  do not sum to exactly 1 due to floating point).
- Fallback mode must be clearly documented in the report — never silently produce
  proxy results without flagging whether they used real ACS data or uniform priors.
- Maintain backward compatibility: existing callers that pass `demographic_group`
  explicitly must continue to work without change.
```

---

### PROMPT P1.6 — Policy Version Table

**Severity:** HIGH — cannot answer "what policy was effective on date X?"
**File:** `decision_engine/cc_origination_policy.py`
**Also creates:** `decision_engine/policy_version_store.py` (NEW), `db/policy_versions.sql` (NEW)

```
You are replacing hardcoded ProductPolicy dataclasses with a database-backed
policy versioning system.

CONTEXT
-------
File: decision_engine/cc_origination_policy.py (705 lines)
The current code defines ProductPolicy dataclasses with hardcoded threshold
values directly in the source file. There is no history of prior policy
parameter sets. If an examiner asks "what credit limit cap was in effect for
the Standard product on March 15, 2025?", there is no way to answer.
The platform must be able to replay the exact policy that governed a historical
decision.

TASK
----
1. Create `decision_engine/policy_version_store.py` implementing:

   a. `PolicyVersion` dataclass:
      version_id: str (UUID4), policy_name: str, effective_date: date,
      sunset_date: date | None, approved_by: str, approval_timestamp: datetime,
      git_commit_hash: str, parameters: dict (all threshold values as JSON),
      is_active: bool, created_at: datetime.

   b. `PolicyVersionStore` class (sync SQLAlchemy, uses sqlite or postgres):
      - `__init__(db_url: str)`: create engine, call `_create_tables()`.
      - `_create_tables()`: CREATE TABLE IF NOT EXISTS policy_versions with
        columns matching PolicyVersion. Add unique constraint on
        (policy_name, effective_date).
      - `publish(version: PolicyVersion) -> str`: INSERT and return version_id.
        Validates: effective_date > any existing active version's effective_date
        for the same policy_name (raises PolicyVersionConflict otherwise).
        Sets is_active=True on the new version and is_active=False on the
        previously active version.
      - `get_active(policy_name: str) -> PolicyVersion`: returns the
        current active version (is_active=True). Raises if none found.
      - `get_as_of(policy_name: str, as_of_date: date) -> PolicyVersion`:
        returns the version where effective_date <= as_of_date AND
        (sunset_date IS NULL OR sunset_date > as_of_date). Raises if none found.
      - `list_versions(policy_name: str) -> list[PolicyVersion]`: returns
        all versions ordered by effective_date DESC.
      - `rollback(policy_name: str, to_version_id: str, approved_by: str) -> str`:
        creates a NEW version copying parameters from to_version_id with
        effective_date = today, approved_by = approved_by. Returns new version_id.

   c. `extract_current_policy_parameters() -> dict`:
      Reads the current hardcoded ProductPolicy dataclasses from the module and
      serializes all threshold fields to a flat dict keyed by
      "{product_tier}.{field_name}". This is the migration bootstrap function.

2. In `decision_engine/cc_origination_policy.py`:
   a. Add a `_POLICY_STORE: PolicyVersionStore | None = None` module-level singleton.
   b. Add `configure_policy_store(db_url: str) -> None` that initializes the singleton.
   c. Modify the core policy engine's parameter lookup:
      - If `_POLICY_STORE` is configured: load parameters from
        `_POLICY_STORE.get_active("cc_origination")` and overlay onto ProductPolicy.
      - If `_POLICY_STORE` is None: fall back to hardcoded values (backward compat).
   d. Pass an optional `as_of_date: date | None = None` parameter to the top-level
      scoring/decision function. If provided, use `get_as_of()` instead of `get_active()`.
      This is the point-in-time replay capability.

3. Create `db/policy_versions.sql`:
   Standard SQL DDL for the policy_versions table (PostgreSQL compatible).

4. Create a migration script `scripts/migrate_policy_to_store.py`:
   - Reads hardcoded parameters via `extract_current_policy_parameters()`.
   - Creates a PolicyVersion with today's date, git_commit_hash from
     `git rev-parse HEAD`, approved_by="migration_bootstrap".
   - Publishes to the store. Prints the version_id.

5. Create `tests/decision_engine/test_policy_version_store.py`:
   - Use an in-memory SQLite DB for all tests.
   - test_publish_and_get_active(): publish a version, get_active(), assert match.
   - test_point_in_time_replay(): publish v1 with effective_date=2025-01-01,
     publish v2 with effective_date=2025-06-01; get_as_of(2025-03-15) returns v1.
   - test_rollback_creates_new_version(): rollback to v1 from v2, assert new v3
     has v1's parameters and a new version_id.
   - test_conflict_raises(): publish two versions with the same effective_date,
     assert PolicyVersionConflict is raised on the second publish.

CONSTRAINTS
-----------
- SQLite must work for testing and local dev without any setup.
- PostgreSQL must be supported for production via the same db_url pattern.
- Do NOT remove the existing hardcoded ProductPolicy dataclasses — they serve as
  the fallback. The store is opt-in until fully migrated.
- git_commit_hash should be read via `subprocess.check_output(["git", "rev-parse", "HEAD"])`
  with a fallback of "unknown" if git is unavailable.
- All PublicAPI (publish, get_active, get_as_of, rollback) must be atomic
  (single transaction) to prevent partial writes.
```

---

## Phase 2 — Scale & Robustness (3–6 Months)

---

### PROMPT P2.1 — ECL Engine (CECL / IFRS 9)

**Severity:** CRITICAL gap — zero CECL/IFRS 9 capability exists
**File:** `risk_models/ecl_engine.py` (NEW)
**Also creates:** `risk_models/__init__.py`, `tests/risk_models/test_ecl_engine.py`

```
You are building a minimum-viable Expected Credit Loss (ECL) engine supporting
both CECL (lifetime loss rate method) and IFRS 9 (3-stage PD × LGD × EAD).

CONTEXT
-------
The platform has a 12-month PD model but no ECL engine. For CECL, a US bank must
compute lifetime expected losses. For IFRS 9, exposures are staged (1/2/3) and
ECL is either 12-month or lifetime depending on stage.

TASK
----
1. Create `risk_models/ecl_engine.py` with the following components:

   a. `ExposureRecord` dataclass:
      application_id: str, product: str, outstanding_balance: float,
      credit_limit: float, months_on_book: int, pd_12m: float,
      lgd: float, ccf: float (credit conversion factor),
      stage: Literal[1, 2, 3] = 1, origination_date: date,
      contractual_maturity_months: int

   b. `LifetimePDTermStructure` — converts a 12-month PD to a multi-period
      term structure using a Markov chain approach:
      `build_term_structure(pd_12m: float, lgd: float, max_months: int = 60)
       -> list[float]` where output[i] = marginal PD for month i+1.
      Use: marginal_PD(t) = pd_12m × (1 - pd_12m)^(t / 12 - 1) as a simplified
      conditional survival curve. Normalized so cumulative PD never exceeds 1.

   c. `compute_ead(record: ExposureRecord) -> float`:
      EAD = outstanding_balance + ccf × (credit_limit - outstanding_balance)

   d. `compute_12m_ecl(record: ExposureRecord) -> float`:
      ECL_12m = pd_12m × lgd × EAD

   e. `compute_lifetime_ecl(record: ExposureRecord,
      discount_rate: float = 0.05) -> float`:
      Sum over remaining contractual life:
      ECL = Σ_{t=1}^{remaining_months} [ marginal_PD(t) × lgd × EAD × discount_factor(t) ]
      discount_factor(t) = 1 / (1 + discount_rate / 12) ^ t

   f. `ifrs9_stage_ecl(record: ExposureRecord,
      discount_rate: float = 0.05) -> float`:
      Stage 1 → compute_12m_ecl()
      Stage 2 or 3 → compute_lifetime_ecl()

   g. `MacroScenario` dataclass:
      name: str (e.g., "base", "adverse", "severely_adverse"),
      pd_multiplier: float, lgd_multiplier: float, probability_weight: float

   h. `compute_scenario_weighted_ecl(record: ExposureRecord,
      scenarios: list[MacroScenario],
      discount_rate: float = 0.05) -> dict`:
      For each scenario, scale record.pd_12m and record.lgd by the multipliers,
      compute ifrs9_stage_ecl(), return dict with per-scenario ECL and the
      probability-weighted average ECL.
      Default scenarios if none provided:
        base = (pd_mult=1.0, lgd_mult=1.0, weight=0.6),
        adverse = (pd_mult=1.5, lgd_mult=1.2, weight=0.3),
        severely_adverse = (pd_mult=2.5, lgd_mult=1.4, weight=0.1)

   i. `compute_portfolio_ecl(records: list[ExposureRecord],
      scenarios: list[MacroScenario] | None = None,
      discount_rate: float = 0.05) -> pd.DataFrame`:
      Apply compute_scenario_weighted_ecl() to each record.
      Return DataFrame with columns:
        application_id, stage, ead, pd_12m, lgd, ecl_12m,
        ecl_lifetime, ecl_weighted (scenario-weighted), scenario_breakdown (dict).

   j. `SICRTrigger` dataclass + `check_sicr(record: ExposureRecord,
      origination_pd: float, pd_threshold_multiplier: float = 2.0,
      dpd_threshold: int = 30) -> bool`:
      Significant Increase in Credit Risk (IFRS 9 Stage 1→2 trigger).
      Returns True (SICR occurred) if:
        current pd_12m > origination_pd × pd_threshold_multiplier.
      (dpd_threshold-based trigger requires delinquency data — accept as optional
      parameter, skip if None).

2. Create `tests/risk_models/test_ecl_engine.py`:
   - test_12m_ecl_formula(): PD=0.05, LGD=0.65, balance=5000, limit=10000, CCF=0.6
     → EAD = 5000 + 0.6×5000 = 8000; ECL_12m = 0.05 × 0.65 × 8000 = 260.0
   - test_stage1_equals_12m_ecl()
   - test_stage2_lifetime_ecl_greater_than_12m()
   - test_scenario_weights_sum_to_1(): supply 3 scenarios, assert weights sum to 1.0
   - test_sicr_trigger(): pd_12m = 0.10 with origination_pd = 0.04 → SICR True
     (multiplier 2.0 means threshold = 0.08).
   - test_portfolio_ecl_returns_all_columns(): supply 3 records, assert output
     DataFrame has all required columns and 3 rows.

CONSTRAINTS
-----------
- Pure Python + pandas + numpy — no additional ML libraries needed.
- All monetary values to 2 decimal places in final output (round(), not truncate).
- The engine must handle edge cases: pd_12m=0.0, lgd=1.0, remaining_months=1.
- compute_portfolio_ecl must run on 1M records in < 60 seconds (vectorize
  compute_12m_ecl using pandas operations instead of row-by-row loop).
```

---

### PROMPT P2.2 — LGD Segmentation Model

**Severity:** HIGH — hardcoded LGD is not acceptable under Basel III
**File:** `models/credit_risk/lgd_model.py` (NEW)
**Also creates:** `tests/models/test_lgd_model.py`, `models/credit_risk/lgd_model_card.json`

```
You are building an LGD (Loss Given Default) segmentation model to replace the
hardcoded 65–85% range in cc_origination_policy.py.

CONTEXT
-------
LGD represents the fraction of the exposure lost when a borrower defaults.
Basel III requires: (a) LGD segmented by product and collateral; (b) a downturn
LGD equal to the average LGD during years when portfolio-level losses exceed the
99th historical percentile; (c) LGD >= 45% floor for senior unsecured retail.

TASK
----
1. Create `models/credit_risk/lgd_model.py` implementing:

   a. `LGDSegment` dataclass:
      segment_id: str, product_type: Literal["unsecured", "secured"],
      risk_grade: str, collateral_type: str | None,
      mean_lgd: float, std_lgd: float, downturn_lgd: float,
      sample_size: int, 95th_percentile_lgd: float

   b. `DEFAULT_LGD_SEGMENTS: list[LGDSegment]` — a table of regulatory
      defensible starting segments derived from industry benchmarks:
      - unsecured CC standard: mean=0.72, std=0.12, downturn=0.85
      - unsecured CC premium: mean=0.68, std=0.10, downturn=0.80
      - secured CC: mean=0.42, std=0.08, downturn=0.55
      (Add Basel floor enforcement: min(mean_lgd, 0.45) for senior unsecured.)

   c. `LGDModel` class:
      - `__init__(segments: list[LGDSegment] | None = None)`:
        uses DEFAULT_LGD_SEGMENTS if None.
      - `predict(product_type: str, risk_grade: str,
              collateral_type: str | None = None,
              use_downturn: bool = False) -> float`:
        Looks up the best matching segment (exact match on product_type first,
        then nearest risk_grade). Returns downturn_lgd if use_downturn=True,
        else mean_lgd. Applies Basel III floor of 0.45 for senior unsecured.
      - `predict_batch(df: pd.DataFrame, use_downturn: bool = False) -> pd.Series`:
        Vectorized version. df must have product_type, risk_grade columns.
      - `fit(recovery_df: pd.DataFrame) -> "LGDModel"`:
        Accepts columns: [defaulted_balance, recovered_amount, product_type,
        risk_grade, collateral_type, year]. Computes observed LGD per record
        (lgd = 1 - recovered_amount/defaulted_balance, clipped [0,1]).
        Segments by (product_type, risk_grade). Computes mean, std, 95th pct.
        Computes downturn_lgd = mean LGD in years where portfolio LGD exceeds
        the 99th percentile of all annual mean LGDs.
        Updates self._segments. Returns self.
      - `save(path: Path) -> None` / `load(path: Path) -> "LGDModel"` (classmethod):
        JSON serialization of segment parameters.

   d. `generate_lgd_model_card(model: LGDModel, output_path: Path) -> None`:
      Writes `lgd_model_card.json` with: segment table, Basel III compliance
      attestation (min LGD floor applied Y/N), downturn LGD methodology,
      sample sizes. Must conform to the MDR structure from P1.4.

2. In `decision_engine/cc_origination_policy.py`:
   a. Import `LGDModel` and instantiate a module-level `_LGD_MODEL = LGDModel()`.
   b. Replace all hardcoded `lgd=0.65` / `lgd=0.85` references with
      `_LGD_MODEL.predict(product_type=..., risk_grade=..., use_downturn=False)`.
   c. For the break-even PD calculation, use downturn LGD
      (`use_downturn=True`) to be conservative per Basel III.

3. Create `tests/models/test_lgd_model.py`:
   - test_unsecured_lgd_above_basel_floor(): predict for unsecured product, assert >= 0.45
   - test_downturn_lgd_greater_than_mean(): for any segment, assert downturn_lgd >= mean_lgd
   - test_fit_on_synthetic_data(): generate 500-row recovery DataFrame, call fit(),
     assert segments are populated with sample_size > 0.
   - test_predict_batch_shape(): supply 100-row df, assert output Series has 100 values.

CONSTRAINTS
-----------
- The model must NOT require scipy, statsmodels, or any ML framework — pure pandas/numpy.
- Basel III floors must be enforced in all predict() paths without exception.
- fit() must be idempotent: calling it twice with the same data produces the same segments.
```

---

### PROMPT P2.3 — Champion / Challenger Infrastructure

**Severity:** HIGH — no model update can be deployed safely without C/C
**File:** `decisioning/champion_challenger.py` (NEW)
**Inspired by:** `ThinFile_Credit_Underwriting_Engine/src/shadow/pipeline.py`

```
You are building a Champion/Challenger (C/C) decision routing framework
for the main credit-risk-platform.

CONTEXT
-------
ThinFile has src/shadow/pipeline.py but the main platform has no C/C capability.
The C/C framework lets a new model (Challenger) run in shadow alongside the live
model (Champion), with optional percentage-based traffic splitting for live tests.

TASK
----
1. Create `decisioning/champion_challenger.py` implementing:

   a. `ModelConfig` dataclass:
      role: Literal["CHAMPION", "CHALLENGER"],
      model_registry_name: str, model_version: str,
      traffic_pct: float,  # 0.0–1.0; CHAMPION gets (1 - challenger_traffic_pct)
      active: bool = True

   b. `CCDecisionRecord` dataclass:
      application_id: str, timestamp: datetime, role: str, model_version: str,
      pd_score: float, decision: str, credit_limit: float | None,
      apr: float | None, is_shadow: bool  # True = challenger ran but did not govern

   c. `ChampionChallengerRouter` class:
      - `__init__(champion: ModelConfig, challenger: ModelConfig | None,
                  store: "CCDecisionStore", random_seed: int | None = None)`.
      - `route(application_id: str) -> Literal["CHAMPION", "CHALLENGER"]`:
        deterministic routing — hash(application_id + salt) % 100 < challenger_traffic_pct × 100.
        If no challenger is configured, always returns "CHAMPION".
      - `run_both_shadow(application_id: str,
                         features: dict,
                         score_fn: Callable[[dict, str], dict]) -> CCDecisionRecord`:
        Always governs with CHAMPION, but also calls score_fn with CHALLENGER
        config in shadow mode. Logs both records to the store. Returns champion
        CCDecisionRecord.
      - `run_live_split(application_id: str,
                        features: dict,
                        score_fn: Callable[[dict, str], dict]) -> CCDecisionRecord`:
        Routes based on traffic split. The routed model governs. Logs the result.
        Returns governing CCDecisionRecord.

   d. `CCDecisionStore` class (SQLite/postgres backend):
      - Persist CCDecisionRecord to a `cc_decisions` table.
      - `generate_comparison_report(lookback_days: int = 7) -> ChallengerComparisonReport`:
        Computes approval rate delta, mean PD delta, credit limit delta between
        champion and challenger decisions over the lookback window.

   e. `ChallengerComparisonReport` dataclass:
      period_start: date, period_end: date, champion_approval_rate: float,
      challenger_approval_rate: float, approval_rate_delta: float,
      champion_mean_pd: float, challenger_mean_pd: float,
      sample_size_champion: int, sample_size_challenger: int,
      recommendation: Literal["PROMOTE", "HOLD", "REJECT"].
      recommendation logic: PROMOTE if challenger_approval_rate within ±3pp
      of champion AND challenger_mean_pd <= champion_mean_pd × 1.05.

2. Add `ChallengerGoNoGoCheck` to the promotion workflow:
   In `scripts/mrm_lifecycle.py`, add a `promote-challenger` command that:
   - Loads the latest ChallengerComparisonReport.
   - Auto-approves promotion if recommendation == "PROMOTE".
   - Requires manual four-eyes approval (via CLI prompt) if recommendation == "HOLD".
   - Blocks promotion if recommendation == "REJECT" and logs the block.

3. Create `tests/decisioning/test_champion_challenger.py`:
   - test_shadow_mode_returns_champion_decision(): configure 0% challenger traffic,
     assert run_both_shadow returns champion result.
   - test_live_split_routing_is_deterministic(): same application_id always routes
     to the same model version.
   - test_comparison_report_promote_logic(): inject records where challenger is
     better, assert recommendation == "PROMOTE".
   - test_reject_logic(): inject records where challenger approval_rate is 10pp higher
     AND mean_pd is 20% higher, assert recommendation == "REJECT".

CONSTRAINTS
-----------
- Routing MUST be deterministic per application_id (use hash, not random.random()).
- Shadow mode must NEVER change the governing decision — only log the challenger result.
- The report generator must use only the CC decisions store — no external dependencies.
- Do not copy ThinFile's shadow pipeline — write from scratch for the main platform.
```

---

### PROMPT P2.4 — Alert Notification Integration

**Severity:** MEDIUM — alerts computed but never delivered
**File:** `monitoring/alert_router.py`

```
You are adding real notification delivery to the alert router.

CONTEXT
-------
File: monitoring/alert_router.py
The router classifies alerts by severity and routes them, but has no actual
notification transport. In a live deployment, PSI breaches and compliance
violations must reach engineers within minutes, not hours.

TASK
----
1. Define a `NotificationChannel` protocol (typing.Protocol):
   `def send(self, subject: str, body: str, severity: str) -> bool` (returns True on success)

2. Implement three channel adapters:
   a. `SlackWebhookChannel(webhook_url: str)`:
      POST to Slack webhook URL. Payload: {text: f"*[{severity}]* {subject}\n{body}"}.
      Retry up to 3 times on HTTP 429 or 5xx. Use `urllib.request` (no extra deps).
   b. `EmailChannel(smtp_host: str, smtp_port: int, from_addr: str, to_addrs: list[str],
      use_tls: bool = True, username: str | None = None, password: str | None = None)`:
      Send via smtplib.SMTP_SSL or STARTTLS. Subject = provided subject. Body = plain text.
   c. `LogOnlyChannel(logger_name: str = "alert_router")`:
      Fallback: log at WARNING (severity=MEDIUM/LOW) or ERROR (HIGH/CRITICAL).
      Always returns True (never fails).

3. Modify `alert_router.py` routing logic:
   - `AlertRouter.__init__` now accepts `channels: dict[str, list[NotificationChannel]]`
     mapping severity level to list of channels. Default: `{"CRITICAL": [LogOnlyChannel()],
     "HIGH": [LogOnlyChannel()], "MEDIUM": [LogOnlyChannel()], "LOW": [LogOnlyChannel()]}`.
   - After generating an alert, call each channel in the list for the alert's severity.
   - If a channel raises an exception or returns False, log the failure and continue.
   - Add `sent_to_channels: list[str]` field to the alert record.

4. Add environment-variable-driven configuration:
   `build_channels_from_env() -> dict[str, list[NotificationChannel]]`:
   Reads: ALERT_SLACK_WEBHOOK_URL, ALERT_EMAIL_SMTP_HOST, ALERT_EMAIL_TO,
   ALERT_EMAIL_FROM, ALERT_EMAIL_SMTP_PASSWORD.
   Returns populated channels dict. If env vars are absent, falls back to
   LogOnlyChannel for all severities and logs a startup WARNING.

5. Wire `build_channels_from_env()` into the alert router initialization so that
   alerts are delivered automatically in production without code changes.

6. Add `tests/monitoring/test_alert_router_channels.py`:
   - test_slack_channel_sends_correct_payload(): mock urllib.request.urlopen,
     assert payload contains severity and subject.
   - test_email_channel_sends(): mock smtplib.SMTP_SSL, assert sendmail called.
   - test_failed_channel_does_not_abort(): make SlackWebhookChannel raise
     ConnectionError, assert the router continues without exception.
   - test_build_channels_from_env_fallback(): with no env vars set, assert all
     channels are LogOnlyChannel instances.

CONSTRAINTS
-----------
- No new pip dependencies: use only urllib.request, smtplib, ssl from stdlib.
- All channel adapters must be mockable via standard unittest.mock.
- Sensitive credentials (webhook_url, passwords) must never be logged.
```

---

### PROMPT P2.5 — Human-in-the-Loop Review Queue

**Severity:** HIGH — MANUAL_REVIEW decisions have no workflow today
**File:** `decisioning/review_queue.py` (NEW)
**Also touches:** `decision_engine/cc_origination_policy.py`

```
You are building a Human-in-the-Loop (HITL) review queue for MANUAL_REVIEW credit
decisions.

CONTEXT
-------
The decision engine generates Decision.MANUAL_REVIEW outcomes but nothing manages
the queue of pending reviews. ECOA requires adverse action notices within 30 days.
The platform needs a queue, SLA tracker, override capture, and audit trail.

TASK
----
1. Create `decisioning/review_queue.py` implementing:

   a. `ReviewItem` dataclass:
      item_id: str (UUID4), application_id: str, created_at: datetime,
      sla_deadline: datetime,  # created_at + 24h default (configurable)
      status: Literal["PENDING", "UNDER_REVIEW", "COMPLETED", "SLA_BREACHED"],
      assigned_to: str | None, review_started_at: datetime | None,
      completed_at: datetime | None, override_decision: str | None,
      override_reason_code: str | None, override_notes: str | None,
      original_pd_score: float, original_features: dict

   b. `ReviewQueue` class (SQLite/postgres via SQLAlchemy sync):
      - `enqueue(application_id: str, pd_score: float, features: dict,
                 sla_hours: int = 24) -> ReviewItem`
      - `assign(item_id: str, reviewer_id: str) -> ReviewItem`:
        Sets status=UNDER_REVIEW and assigned_to.
      - `complete(item_id: str, override_decision: str,
                  override_reason_code: str, notes: str = "") -> ReviewItem`:
        Sets status=COMPLETED. Validates override_decision is in
        {"APPROVE", "DECLINE", "REFER_TO_SENIOR"}.
      - `get_pending(limit: int = 50) -> list[ReviewItem]`:
        Returns PENDING items ordered by sla_deadline ASC.
      - `check_sla_breaches() -> list[ReviewItem]`:
        Updates all PENDING/UNDER_REVIEW items past their sla_deadline to
        SLA_BREACHED. Returns the newly breached items.
      - `export_feedback(output_path: Path) -> int`:
        Exports all COMPLETED items where override_decision != the engine's
        original decision to a Parquet file for retraining feedback.
        Returns row count. Columns: application_id, original_features (dict),
        override_decision (relabeled target), completed_at.

   c. `ReviewReasonCode` enum:
      INSUFFICIENT_INCOME, THIN_FILE, FRAUD_INDICATORS, POLICY_EXCEPTION,
      INCORRECT_MODEL_INPUT, DATA_QUALITY_CONCERN, MANUAL_ESCALATION, OTHER

2. In `decision_engine/cc_origination_policy.py`:
   a. At the point where Decision.MANUAL_REVIEW is returned, if a
      `ReviewQueue` is configured in the module singleton, call
      `review_queue.enqueue(application_id, pd_score, features)`.
   b. Add `configure_review_queue(queue: ReviewQueue) -> None` module function.

3. Create a simple CLI in `scripts/review_queue_cli.py`:
   - `python scripts/review_queue_cli.py list` → print pending items, highlight
     SLA-breached items in red.
   - `python scripts/review_queue_cli.py assign <item_id> <reviewer_id>`
   - `python scripts/review_queue_cli.py complete <item_id> APPROVE POLICY_EXCEPTION`

4. Create `tests/decisioning/test_review_queue.py`:
   - test_enqueue_and_get_pending()
   - test_sla_breach_detection(): enqueue with sla_hours=0 (immediate), run
     check_sla_breaches(), assert item is SLA_BREACHED.
   - test_complete_sets_status(): complete an item, get_pending() should not include it.
   - test_feedback_export_only_includes_overrides(): complete one item with same
     decision as original, one with different; assert export contains only 1 row.

CONSTRAINTS
-----------
- No Flask/FastAPI required — this is a library module with a separate CLI script.
- All SLA breach detection must use timezone-aware UTC datetimes.
- override_decision must be validated against allowed values — raise ValueError if not.
- export_feedback writes Parquet via pandas (pyarrow already in requirements).
```

---

## Phase 3 — Advanced Capabilities (6–12 Months)

---

### PROMPT P3.1 — Stress Testing Framework

**Severity:** HIGH — required for DFAST/capital adequacy planning
**File:** `risk_models/stress_test.py` (NEW)

```
You are building a macro stress testing framework aligned to DFAST scenarios.

CONTEXT
-------
File: risk_models/ecl_engine.py (built in P2.1)
The platform has an ECL engine and a PD model but no ability to answer:
"What is total portfolio ECL under a severe recession scenario?"

TASK
----
1. Create `risk_models/stress_test.py` implementing:

   a. `MacroScenarioSet` dataclass:
      scenario_name: str (e.g., "DFAST_2026_SEVERELY_ADVERSE"),
      source: str, vintage: str,
      scenarios: list[MacroScenario]  # from ecl_engine.py

   b. `DFAST_2026_SCENARIOS: MacroScenarioSet` — a hardcoded reasonable approximation
      based on publicly available Fed DFAST scenario documentation:
      base = (pd_mult=1.0, lgd_mult=1.0, weight=0.5),
      adverse = (pd_mult=1.8, lgd_mult=1.15, weight=0.35),
      severely_adverse = (pd_mult=3.0, lgd_mult=1.35, weight=0.15).
      Document source = "Fed DFAST 2026 (approximate — replace with official values)".

   c. `run_portfolio_stress_test(portfolio_df: pd.DataFrame,
      scenario_set: MacroScenarioSet,
      lgd_model: "LGDModel",
      discount_rate: float = 0.05) -> StressTestReport`:
      - Build ExposureRecord list from portfolio_df.
      - For each scenario, scale PD and LGD.
      - Compute portfolio-level ECL per scenario.
      - Compute: total_ecl, ecl_as_pct_of_portfolio, scenario_delta_vs_base.
      - Identify top-10 accounts by ECL contribution under severely adverse.

   d. `StressTestReport` dataclass:
      scenario_set_name: str, run_at: datetime, portfolio_size: int,
      total_balance: float,
      scenario_results: list[ScenarioResult],  # one per scenario
      probability_weighted_ecl: float,
      top10_contributors: list[dict],
      capital_adequacy_check: dict  # {"tier1_ratio_pre_stress": float,
                                    #  "tier1_ratio_post_stress": float,
                                    #  "passes_minimum_8pct": bool}

   e. `generate_stress_test_report_markdown(report: StressTestReport,
      output_path: Path) -> None`:
      Write a Markdown report with: executive summary, scenario table,
      ECL waterfall chart (ASCII), top contributors table.

2. Create `tests/risk_models/test_stress_test.py`:
   - test_severely_adverse_ecl_exceeds_base()
   - test_report_has_all_required_fields()
   - test_capital_adequacy_fails_when_ecl_exceeds_tier1()

CONSTRAINTS
-----------
- Reuse `MacroScenario` and `compute_portfolio_ecl` from ecl_engine.py exactly.
- Tier-1 capital ratio placeholder: accept as input parameter (default 0.12 = 12%).
- DFAST scenario multipliers are approximations — document this prominently in code.
```

---

### PROMPT P3.2 — HMDA LAR Builder

**Severity:** HIGH — required for mortgage products under HMDA
**File:** `reporting/hmda_lar.py` (NEW)

```
You are building a HMDA Loan/Application Register (LAR) export module.

CONTEXT
-------
HMDA requires covered institutions to report loan-level data annually
(or quarterly for large institutions). The platform has an audit logger but
no HMDA extract. The output must conform to FFIEC HMDA Filing Instructions
Guide (FIG) 2023 column specifications.

TASK
----
1. Create `reporting/hmda_lar.py` implementing:

   a. `HMDALARRecord` dataclass with all HMDA FIG 2023 required fields:
      lei: str, lar_id: str, application_date: str (YYYYMMDD),
      loan_type: int (1=Conventional,2=FHA,3=VA,4=FSA),
      loan_purpose: int (1=Purchase,2=Improvement,31=Refi,32=CashOutRefi,4=Other),
      preapproval: int, construction_method: int, occupancy_type: int,
      loan_amount: float, action_taken: int (1=Originated,2=Approved-NotAccepted,
      3=Denied,4=Withdrawn,5=Closed-Incomplete,6=Purchased,7=Preapproval-Denied,
      8=Preapproval-Approved-NotAccepted),
      action_taken_date: str, state_code: str, county_code: str,
      census_tract: str, applicant_ethnicity_1: int, co_applicant_ethnicity_1: int,
      applicant_race_1: int, co_applicant_race_1: int, applicant_sex: int,
      co_applicant_sex: int, applicant_age: int, co_applicant_age: int,
      income: int (thousands), purchaser_type: int, rate_spread: float | None,
      hoepa_status: int, lien_status: int, credit_score_applicant: int,
      credit_score_model_applicant: int, denial_reason_1: int | None,
      total_loan_costs: float | None, interest_rate: float, total_points_fees: float | None,
      debt_to_income_ratio: str, combined_loan_to_value: float | None,
      loan_term: int, introductory_rate_period: int | None,
      balloon_payment: int, interest_only_payment: int, negative_amortization: int,
      other_non_amortizing_features: int, property_value: float | None,
      manufactured_home_secured_property_type: int,
      manufactured_home_land_property_interest: int,
      total_units: int, multifamily_affordable_units: str,
      submission_of_application: int, initially_payable_to_institution: int,
      aus_1: int, reverse_mortgage: int, open_end_line_of_credit: int,
      business_or_commercial_purpose: int

   b. `build_lar_from_audit_log(audit_records: list[dict],
      lei: str,
      product_filter: list[str] | None = None) -> list[HMDALARRecord]`:
      Maps audit log records to HMDA fields. Only include records where
      product is in {"mortgage", "home_equity"}. Applies the mapping:
        pd_score → estimate credit_score_applicant using inverse scorecard lookup.
        adverse_action_reasons → map FCRA codes to HMDA denial_reason_1 codes.
        apr_assigned → interest_rate.
        Features dict fields → income, dti, ltv, etc.
      For fields not available in audit log, use HMDA exempt value (1111 for numeric,
      "Exempt" for string fields). Document every mapping assumption.

   c. `export_lar_pipe_delimited(records: list[HMDALARRecord],
      output_path: Path) -> int`:
      Write FFIEC pipe-delimited format (one record per line, fields separated by |).
      First line is NOT a header (HMDA FIG requires no header row). Return row count.

   d. `validate_lar(records: list[HMDALARRecord]) -> list[dict]`:
      Run HMDA validity checks: LEI is 20 characters, action_taken in 1–8,
      census_tract is 11 digits, loan_amount > 0. Return list of {lar_id, field, error}.

2. Create `tests/reporting/test_hmda_lar.py`:
   - test_pipe_format_no_header()
   - test_lei_validation_length()
   - test_denial_reason_mapping_from_fcra_code()
   - test_exempt_fields_use_correct_hmda_code()

CONSTRAINTS
-----------
- This module is data transformation only — no HTTP, no database. Pure function.
- Use HMDA FIG 2023 codes exactly as documented in the prompt — do not invent codes.
- Fields not mappable from audit log must use the HMDA "Exempt" or 1111/1 coding,
  not Python None, to produce a valid pipe-delimited file.
```

---

### PROMPT P3.3 — OpenLineage Data Lineage Integration

**Severity:** MEDIUM — required for SR 11-7 data integrity attestation
**File:** `feature_pipeline/lineage.py` (NEW)
**Also touches:** `feature_pipeline/feature_store.py`

```
You are adding OpenLineage data lineage tracking to the feature pipeline.

CONTEXT
-------
Currently no data transformation in the platform emits lineage events. This means
a feature value cannot be traced back to the raw source record. SR 11-7 requires
the ability to attest that model inputs derive from defensible data sources.
OpenLineage is the CNCF standard for cross-platform lineage.

TASK
----
1. Create `feature_pipeline/lineage.py` implementing:

   a. `LineageClient` class that wraps OpenLineage event emission:
      - `__init__(transport: Literal["http", "console"] = "console",
                  endpoint: str | None = None, api_key: str | None = None)`.
        "console" transport logs events as structured JSON (no external dep).
        "http" transport POSTs to Marquez/OpenLineage API endpoint.
      - `emit_dataset_event(run_id: str, job_name: str,
                            inputs: list[DatasetRef], outputs: list[DatasetRef],
                            event_type: Literal["START", "COMPLETE", "FAIL"],
                            run_facets: dict | None = None) -> None`.
      - `new_run_id() -> str`: returns UUID4 as string.

   b. `DatasetRef` dataclass:
      namespace: str, name: str, facets: dict | None = None.
      (OpenLineage dataset has namespace + name as unique key.)

   c. Helper builders:
      - `feature_store_dataset(version: str, as_of_date: str) -> DatasetRef`
      - `raw_parquet_dataset(filename: str) -> DatasetRef`
      - `model_training_dataset(run_id: str, model_name: str) -> DatasetRef`

2. In `feature_pipeline/feature_store.py`:
   a. Add optional `lineage_client: LineageClient | None = None` parameter to
      `write_features()`.
   b. If provided, emit a COMPLETE event after successful write:
      inputs = [raw_parquet_dataset(source_file)] if source_file is known,
      outputs = [feature_store_dataset(version, as_of_date)],
      run_facets = {"rowCount": rows_written, "feature_hash": hash}.

3. In `models/credit_risk/train_cc_pd_model.py`:
   a. Add lineage emission at training start (START event) and end (COMPLETE event):
      inputs = [feature_store_dataset(version, as_of_date)],
      outputs = [model_training_dataset(mlflow_run_id, "cc_pd_model")].

4. Write `tests/feature_pipeline/test_lineage.py`:
   - test_console_transport_emits_json(): capture stdout, assert valid JSON with
     eventType="COMPLETE" and correct dataset names.
   - test_http_transport_posts_correct_payload(): mock requests.post (or urllib),
     assert payload has inputs/outputs/eventType.
   - test_dataset_ref_has_namespace_and_name()

CONSTRAINTS
-----------
- "console" transport requires ZERO additional pip packages.
- "http" transport uses urllib.request only (no requests library added).
- OpenLineage event schema must match the 1.0.x spec: eventType, eventTime (ISO),
  run.runId, job.namespace, job.name, inputs[], outputs[].
- The LineageClient must never raise an unhandled exception — wrap all sends in
  try/except and log errors without crashing the pipeline.
```

---

### PROMPT P3.4 — Closed-Loop Reject Inference

**Severity:** HIGH — model bias in riskiest segments is undocumented
**File:** `models/credit_risk/reject_inference.py` (NEW)
**Also touches:** `models/credit_risk/train_cc_pd_model.py`

```
You are implementing reject inference to correct model bias from training only
on approved accounts.

CONTEXT
-------
The CC PD model is trained on booked accounts only (applicants who were approved).
Declined applicants are excluded from training, but in reality some would have
defaulted and some would not. This exclusion biases the PD model to underestimate
risk in segments that are frequently declined — a fundamental model bias.
This is well-documented in the ThinFile audit (reports/reject_inference_summary.json)
but not implemented in the main platform.

TASK
----
1. Create `models/credit_risk/reject_inference.py` implementing:

   a. `RejectInferenceConfig` dataclass:
      method: Literal["augmentation", "parceling"],
      augmentation_weight: float = 0.5,  # weight given to rejected records vs approved
      parceling_threshold_bad: float = 0.5,  # PD above this → assign bad outcome
      random_seed: int = 42,
      document_bias_adjustment: bool = True

   b. `augmentation_method(approved_df: pd.DataFrame,
      rejected_df: pd.DataFrame,
      model: Any,  # trained PD model with predict_proba()
      config: RejectInferenceConfig) -> pd.DataFrame`:
      1. Score rejected applicants using the current model.
      2. Add rejected applicants to the training set with:
         - label = 1 with probability = predicted PD (probabilistic assignment)
         - label = 0 with probability = 1 - predicted PD
         - sample_weight = config.augmentation_weight
      3. Return combined DataFrame with columns: all features, default_flag, sample_weight.

   c. `parceling_method(approved_df: pd.DataFrame,
      rejected_df: pd.DataFrame,
      model: Any,
      config: RejectInferenceConfig) -> pd.DataFrame`:
      1. Score rejected applicants.
      2. Hard-assign: default_flag = 1 if pd_score >= parceling_threshold_bad else 0.
      3. sample_weight = config.augmentation_weight.
      4. Return combined DataFrame.

   d. `run_reject_inference(approved_df: pd.DataFrame,
      rejected_df: pd.DataFrame,
      model: Any,
      config: RejectInferenceConfig) -> tuple[pd.DataFrame, RejectInferenceSummary]`:
      Dispatches to the correct method. Returns augmented training set + summary.

   e. `RejectInferenceSummary` dataclass:
      method: str, approved_count: int, rejected_count: int, total_count: int,
      approved_default_rate: float, rejected_imputed_default_rate: float,
      combined_default_rate: float, bias_adjustment_factor: float,
      # = combined_default_rate / approved_default_rate — measures how much
      # reject inference increased the estimated default rate.
      generated_at: datetime

   f. `save_summary(summary: RejectInferenceSummary, path: Path) -> None`:
      Write to JSON. Mirror the format of
      ThinFile/reports/reject_inference_summary.json.

2. In `models/credit_risk/train_cc_pd_model.py`:
   a. Add `--reject-inference` CLI flag (default: off).
   b. When enabled: load rejected applications from a configurable CSV/Parquet path
      (`--rejected-data-path`), run `run_reject_inference()`, use augmented
      DataFrame for training. Save summary to `reports/reject_inference_summary.json`.
   c. Write `reject_inference_method` and `bias_adjustment_factor` to the model card
      and as MLflow tags.

3. Create `tests/models/test_reject_inference.py`:
   - test_augmentation_increases_training_size(): combined > approved_df only.
   - test_parceling_produces_binary_labels(): all default_flag values are 0 or 1.
   - test_bias_adjustment_factor_gt_1(): combined default rate should be >=
     approved default rate (reject inference adds risk, never removes it).
   - test_summary_is_json_serializable(): save_summary, read back, assert fields match.

CONSTRAINTS
-----------
- The model passed to augmentation/parceling must only use predict_proba() — do not
  assume any other model API.
- rejected_df must NOT have a default_flag column — this is the point (outcomes unknown).
- Augmentation must use a fixed random_seed for reproducibility.
- The bias_adjustment_factor must be documented in the MDR assumption register
  (link to P1.4).
```

---

### PROMPT P3.5 — Automated Model Validation Suite

**Severity:** HIGH — validation reports are currently hollow manual text entries
**File:** `validation/automated_suite.py` (NEW)
**Also touches:** `scripts/mrm_lifecycle.py`

```
You are building an automated model validation suite that runs on every
model promotion request and produces a cryptographically-signed validation report.

CONTEXT
-------
File: scripts/mrm_lifecycle.py
`log_model_validation(outcome=PASS/FAIL)` exists but it is a human text entry.
There is no automated test suite. SR 11-7 requires validation to generate an
evidentiary record, not just a human assertion.

TASK
----
1. Create `validation/automated_suite.py` implementing:

   a. `ValidationConfig` dataclass:
      model_registry_name: str, model_version: str, mlflow_run_id: str,
      holdout_data_path: Path, feature_cols: list[str], target_col: str,
      auc_floor: float = 0.75, gini_floor: float = 0.50, ks_floor: float = 0.30,
      brier_ceiling: float = 0.15, calibration_slope_range: tuple = (0.90, 1.10),
      dir_floor: float = 0.80,  # minimum disparate impact ratio
      demographic_col: str | None = None

   b. `ModelValidationReport` dataclass:
      report_id: str (UUID4), generated_at: datetime, model_version: str,
      mlflow_run_id: str, model_artifact_sha256: str,
      holdout_size: int, holdout_default_rate: float,
      auc: float, gini: float, ks: float, brier_score: float,
      calibration_slope: float, calibration_intercept: float,
      dir_result: float | None,  # None if no demographic column
      monotonicity_check_passed: bool,
      all_gates_passed: bool,  # True only if ALL metric floors are met
      gate_failures: list[str],  # human-readable list of failed gates
      report_signature: str      # sha256(report_id + all metrics + model_artifact_sha256)

   c. `run_validation_suite(config: ValidationConfig,
      mlflow_tracking_uri: str) -> ModelValidationReport`:
      1. Load holdout data from config.holdout_data_path.
      2. Load model artifact from MLflow using model_version.
      3. Compute model_artifact_sha256.
      4. Run predict_proba on holdout data.
      5. Compute AUC (sklearn.metrics.roc_auc_score).
      6. Compute KS: max(TPR - FPR) across thresholds.
      7. Compute Gini = 2 × AUC - 1.
      8. Compute Brier score (sklearn.metrics.brier_score_loss).
      9. Compute calibration: fit LinearRegression(predicted_proba → actual);
         slope and intercept are the calibration metrics.
      10. If demographic_col provided: compute DIR using fair_lending module.
      11. Run monotonicity check from P1.2 (import verify_monotonicity).
      12. Evaluate all gate conditions; populate gate_failures.
      13. Compute report_signature = sha256(json.dumps of all numeric fields, sorted).
      14. Return populated report.

   d. `save_validation_report(report: ModelValidationReport,
      output_dir: Path,
      commit_to_mlflow: bool = True,
      mlflow_tracking_uri: str | None = None) -> Path`:
      Write JSON to output_dir/mvr_{model_version}_{report_id[:8]}.json.
      If commit_to_mlflow: set MLflow tag `mvr_report_path` and `mvr_all_gates_passed`.

2. In `scripts/mrm_lifecycle.py`, add `validate` command:
   `python scripts/mrm_lifecycle.py validate --model-name cc_pd_model \
     --version 1 --holdout data/holdout/cc_pd_holdout.parquet \
     --output reports/mvr/`
   Run the suite, save the report. If all_gates_passed=False, print failures
   and return exit code 1 (CI/CD integration).

3. Update `scripts/mrm_lifecycle.py` promote command:
   Before promoting a model from STAGING → PRODUCTION, check that a valid MVR
   (all_gates_passed=True) exists for the model version in MLflow tags.
   Block promotion if no valid MVR is found.

4. Create `tests/validation/test_automated_suite.py`:
   - test_perfect_model_passes_all_gates(): generate synthetic perfect predictions,
     assert all_gates_passed=True and gate_failures is empty.
   - test_low_auc_fails_gate(): AUC = 0.60 < floor 0.75, assert "AUC" in gate_failures.
   - test_report_signature_is_deterministic(): run twice on same data, assert same signature.
   - test_signature_changes_on_different_artifact_hash(): change model_artifact_sha256,
     assert report_signature changes.
   - test_promotion_blocked_without_mvr(): mock mrm_lifecycle to check for MVR tag;
     assert SystemExit(1) when tag is absent.

CONSTRAINTS
-----------
- sklearn is already in requirements.txt — use it for AUC, Brier, etc.
- The report_signature must be a deterministic hash of the REPORT CONTENT, not just
  the timestamp. This ensures the report cannot be silently altered after signing.
- save_validation_report must be atomic — write to a temp file then rename,
  to prevent partial writes.
- All gate failures must use consistent naming matching the metric field names
  (e.g., "AUC below floor: 0.60 < 0.75").
```

---

## Execution Checklist

```
Phase 1 (0–3 months) — PRE-PRODUCTION GATES
[ ] P1.1  Point-in-time feature store
[ ] P1.2  Monotonic constraints + verification
[ ] P1.3  Data quality enforcement module
[ ] P1.4  Model Development Report generator
[ ] P1.5  BISG proxy for fair lending
[ ] P1.6  Policy version table

Phase 2 (3–6 months) — SCALE & ROBUSTNESS
[ ] P2.1  ECL engine (CECL / IFRS 9)
[ ] P2.2  LGD segmentation model
[ ] P2.3  Champion/Challenger infrastructure
[ ] P2.4  Alert notification integration
[ ] P2.5  HITL review queue

Phase 3 (6–12 months) — ADVANCED CAPABILITIES
[ ] P3.1  Stress testing framework (DFAST)
[ ] P3.2  HMDA LAR builder
[ ] P3.3  OpenLineage data lineage
[ ] P3.4  Closed-loop reject inference
[ ] P3.5  Automated model validation suite
```

---

## Dependency Graph

```
P1.1 (feature store PIT)
    └── P3.3 (OpenLineage) — wraps P1.1 write_features()

P1.2 (monotone constraints)
    └── P3.5 (automated validation) — calls verify_monotonicity()

P1.3 (data quality)
    └── P3.5 (automated validation) — quality gate before training

P1.4 (MDR generator)
    └── P2.2 (LGD model card) — uses MDR structure
    └── P3.5 (automated validation) — links MVR to MDR

P1.5 (BISG)
    └── P3.5 (automated validation) — DIR check uses BISG

P1.6 (policy versioning)
    └── P2.3 (C/C) — challenger promotion creates new policy version
    └── P2.5 (HITL queue) — overrides logged against policy version

P2.1 (ECL engine)
    └── P2.2 (LGD model) — P2.1 consumes LGD from P2.2
    └── P3.1 (stress test) — P3.1 calls P2.1 compute_portfolio_ecl

P2.3 (champion/challenger)
    └── P3.5 (automated validation) — go/no-go check reads MVR from P3.5
```

---

*Document generated: 2026-04-06*
*Source audit:* `docs/GOVERNANCE_AUDIT_2026_04_06.md`
*Next review when Phase 1 complete.*
