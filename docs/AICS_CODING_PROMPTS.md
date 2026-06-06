# AICreditSystem — Coding Prompts
**Reference:** AICS_GAP_IMPLEMENTATION_PLAN.md
**Generated:** June 6, 2026

Each prompt is self-contained. Paste it directly into a coding session.
Prompts reference existing file paths so the AI has full context on conventions.

---

## Sprint 1 — Credit Analyst Agent

---

### PROMPT S1-A: Qualitative Assessment Engine

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - agents/base.py              (BaseAgent, AgentResult, AgentStatus)
  - agents/risk_modeling_agent.py (RiskModelingAgent output: ModelScores dataclass)
  - schemas/contracts.py        (ModelScores, FeatureVector data contracts)
  - feature_pipeline/features.py (available feature names)
  - data_contracts/v1/compliance.py (COLLATERAL enum)

Task: Create agents/credit_analyst_agent.py

Implement a CreditAnalystAgent(BaseAgent) with:

1. A QualitativeAssessment dataclass with fields:
     creditworthiness_score: int  # 1–5 ordinal (5 = strongest)
     collateral_quality: Literal["Adequate", "Marginal", "Insufficient", "N/A"]
     collateral_coverage_ratio: Optional[float]  # collateral_value / loan_amount
     industry_risk_tier: Literal["Low", "Medium", "High", "Elevated"]
     red_flags: list[RedFlag]
     overall_risk_opinion: Literal["Acceptable", "Marginal", "Unacceptable"]

2. A RedFlag dataclass with fields:
     flag_type: str       # e.g. "HIGH_CASH_ADVANCE_USAGE"
     severity: Literal["Low", "Medium", "High", "Critical"]
     feature: str         # the feature that triggered it
     observed_value: float
     threshold: float
     description: str     # plain-English explanation

3. A NAICS_RISK_TIERS dict (module-level constant) mapping NAICS 2-digit sector
   codes to risk tiers. Include at minimum:
     "44": "Low",   # Retail trade
     "52": "Low",   # Finance and insurance
     "53": "Medium", # Real estate
     "54": "Low",   # Professional services
     "56": "Medium", # Administrative services
     "62": "Medium", # Healthcare
     "71": "High",  # Arts / entertainment
     "72": "Medium", # Accommodation / food
     "23": "High",  # Construction
     "31": "Medium", # Manufacturing
     "48": "Low",   # Transportation
     "11": "Elevated", # Agriculture
     "21": "Elevated", # Mining / oil and gas
     "default": "Medium"

4. _run(inputs) logic:
   - Inputs dict contains keys:
       "feature_vector": dict of feature name → value
       "model_scores": ModelScores dataclass (or dict with pd_score, fraud_probability)
       "loan_amount": float (optional, default 0)
   - Income stability score (1–5):
       employment_status == "employed" and emp_years >= 2: +2
       employment_status == "self_employed": +1
       annual_income > 80000: +1
       annual_income > 150000: +2
       cap at 5
   - Collateral:
       if collateral_value present and loan_amount > 0:
         coverage = collateral_value / loan_amount
         if coverage >= 1.25: Adequate
         elif coverage >= 0.80: Marginal
         else: Insufficient
       else: "N/A"
   - Industry risk: look up naics_code (2-digit prefix) in NAICS_RISK_TIERS
   - Red flag detection (check all, collect all that trigger):
       FRAUD_INDICATORS:        model_scores.fraud_probability >= 0.3, Critical
       HIGH_CASH_ADVANCE:       cash_advance_total_12m > 0.3 * credit_limit, High
       EXCESSIVE_MISSED_PMTS:   num_missed_pmts_12m > 2, High
       RECENT_BANKRUPTCY:       num_bankruptcy > 0, Critical
       THIN_FILE:               num_open_trades < 3, Medium
       HIGH_UTILIZATION:        pct_rev_utilization > 0.85, Medium
       HIGH_DTI:                dti > 0.50, High
       COLLATERAL_SHORTFALL:    coverage_ratio < 0.80 (if collateral present), High
   - Overall risk opinion:
       any Critical flag → Unacceptable
       any High flag OR creditworthiness_score <= 2 → Marginal
       else → Acceptable
   - Return AgentResult with payload["qualitative_assessment"] = QualitativeAssessment

5. All logic must be deterministic (no LLM calls). Use only the feature values
   provided — never invent data.

6. Add full docstring, type hints, and unit-test-friendly design.
   No external dependencies beyond the existing project.
```

---

### PROMPT S1-B: Risk Narrative Generator

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - explainability/nlg_summarizer.py  (NLGSummary dataclass, existing Jinja pattern)
  - agents/credit_analyst_agent.py    (QualitativeAssessment, RedFlag — just created)
  - agents/risk_modeling_agent.py     (ModelScores)
  - explainability/shap_explainer.py  (ShapExplanation output structure)

Task: Create explainability/risk_narrative_generator.py

Implement generate_risk_narrative() that produces a RiskNarrativeDocument:

1. RiskNarrativeDocument dataclass:
     account_id: str
     generated_at: str          # ISO-8601 UTC
     borrower_profile: str      # rendered text
     financial_strength: str
     collateral_analysis: str   # empty string if no collateral
     industry_macro: str
     red_flag_summary: str      # empty string if no flags
     overall_credit_opinion: str
     risk_opinion: str          # Acceptable | Marginal | Unacceptable
     as_markdown() -> str       # joins all non-empty sections with headers

2. Use Python string templates (string.Template) — NOT an LLM. Every sentence
   must reference a specific data value from the inputs. Example template:

     borrower_profile:
       "Borrower reports annual income of ${income:,.0f} with
        ${employment_status} employment status and ${emp_years:.0f} years
        of employment history. Credit bureau score is ${fico_score:.0f}
        (${pd_band} risk band). Creditworthiness score: ${cw_score}/5."

   Create one Template per section. Handle missing optional fields with
   sensible defaults (e.g., "Not provided" or skip sentence).

3. Sections:
   - borrower_profile: income, employment, FICO, PD score, creditworthiness_score
   - financial_strength: DTI, utilization, payment history (pct_ontime_pmts_12m),
     derogatory marks, bankruptcy, expected loss ($)
   - collateral_analysis: only if collateral_quality != "N/A":
     type, value, coverage_ratio, quality label
   - industry_macro: naics_code → sector name, industry_risk_tier, one-sentence
     sector outlook (static lookup dict of 2-digit NAICS → brief description)
   - red_flag_summary: bulleted list of RedFlag descriptions with severity
     (skip section entirely if red_flags is empty)
   - overall_credit_opinion: one paragraph synthesizing the above, ending with
     the overall_risk_opinion label and recommended action
     (Acceptable → "Recommend proceeding",
      Marginal → "Recommend referral to senior underwriter",
      Unacceptable → "Recommend decline")

4. generate_risk_narrative(
       account_id: str,
       features: dict,
       assessment: QualitativeAssessment,
       model_scores: ModelScores,
       shap_top_factors: list[tuple[str, float]] | None = None,
   ) -> RiskNarrativeDocument

5. All output is deterministic. No randomness. No LLM calls.
   Add comprehensive unit tests in tests/test_risk_narrative_generator.py
   covering: secured loan, unsecured loan, red-flag case, clean file case.
```

---

### PROMPT S1-C: Wire CreditAnalystAgent into Pipeline

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - orchestration/pipeline.py           (CreditRiskPipeline, PipelineRun, _run_stage)
  - agents/credit_analyst_agent.py      (just created)
  - explainability/risk_narrative_generator.py (just created)
  - agents/explainability_agent.py      (ExplainabilityAgent — runs before this)
  - audit/logger.py                     (audit log write pattern)

Task: Wire CreditAnalystAgent and risk narrative into the orchestration pipeline.

Changes required:

1. In orchestration/pipeline.py:
   - Import CreditAnalystAgent
   - Import generate_risk_narrative from explainability.risk_narrative_generator
   - Add CreditAnalystAgent instantiation in __init__ alongside other agents
   - Insert a new pipeline stage "credit_analyst" AFTER "explainability" stage:
       a. Build inputs for CreditAnalystAgent:
            feature_vector: from pipeline payload["feature_df"] (first row as dict)
            model_scores:   from payload["model_scores"][0]
            loan_amount:    from payload.get("loan_amount", 0)
       b. Run CreditAnalystAgent
       c. If result.ok: generate_risk_narrative(...) using assessment + SHAP values
          Store narrative in pipeline payload["risk_narrative"]
       d. Store raw assessment in payload["qualitative_assessment"]
       e. Add stage result to PipelineRun via run.add_stage(result)
   - On CreditAnalystAgent failure: log warning, continue pipeline
     (do not abort — narrative is non-blocking)

2. In the final_payload assembly (where PipelineRun.final_payload is built):
   - Add "qualitative_assessment": assessment.dict() if present
   - Add "risk_narrative_markdown": narrative.as_markdown() if present

3. Add a config flag in agent_config.yaml under a new "credit_analyst" key:
     credit_analyst:
       enabled: true
       collateral_shortfall_threshold: 0.80
       high_cash_advance_ratio: 0.30
       missed_payment_threshold: 2
   Read this config in CreditAnalystAgent.__init__ and use the thresholds
   instead of hardcoded values.

4. Update the /v1/decide endpoint response schema in decision-api/src/main.py
   to include optional fields:
     qualitative_assessment: dict | None
     risk_narrative_markdown: str | None
   Populate from pipeline final_payload if present.

Do not change any existing stage ordering or break existing tests.
```

---

## Sprint 2 — Scorecards & LGD Model

---

### PROMPT S2-A: WoE Scorecard Builder

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - models/credit_risk/train_cc_pd_model.py
    (existing build_scorecard(), NUMERIC_COLS, CATEGORICAL_COLS, TARGET)
  - models/credit_risk/cc_pd_scorecard.json  (current output format)

Task: Add build_woe_scorecard() to models/credit_risk/train_cc_pd_model.py
and update the training script to call it.

Implement:

1. build_woe_scorecard(
       model,                    # trained LightGBM model
       X: np.ndarray,
       y: np.ndarray,
       feat_names: list[str],
       n_bins: int = 10,
       pdo: int = 20,            # Points-to-Double-Odds
       base_score: int = 600,    # score for base odds
       base_odds: float = 50.0,  # good:bad at base_score
   ) -> pd.DataFrame

   Algorithm:
   a. For each numeric feature in feat_names:
      - Bin X[:, i] into n_bins equal-frequency buckets using pd.qcut
      - For each bin compute: count, event_count (y==1), non_event_count (y==0)
      - WoE = ln(non_event_rate / event_rate), handle zero with 0.5 smoothing
      - IV (Information Value) per bin = (non_event_rate - event_rate) * WoE
      - Total IV per feature = sum of bin IVs
   b. Scale WoE to integer points:
      - factor = pdo / ln(2)
      - offset = base_score - factor * ln(base_odds)
      - points_i = round(-(woe_i * coef_i * factor))
        where coef_i is the LightGBM feature importance (gain) normalised to sum=1
   c. Return DataFrame with columns:
      feature | bin_label | bin_lower | bin_upper | count | event_rate |
      woe | iv | points

2. Save output to SCORECARD_PATH.replace(".json", "_woe.json")
   and log to MLflow as artifact "woe_scorecard"

3. Add a new endpoint to decision-api/src/main.py:
   GET /v1/models/{model_name}/scorecard
   Returns the WoE scorecard JSON for the named model.
   Load from MLflow artifact store via existing mlflow.artifacts.load_dict pattern.

4. Add unit test in tests/test_woe_scorecard.py:
   - Generate 1000 rows of synthetic data
   - Call build_woe_scorecard
   - Assert: all point values are integers
   - Assert: features with IV < 0.02 are present but flagged low_iv=true
   - Assert: sum of all bin counts per feature == len(X)
```

---

### PROMPT S2-B: SMB PD Model Training Script

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - models/credit_risk/train_cc_pd_model.py  (full file — use as the template)
  - models/credit_risk/predict.py            (predict_pd interface)
  - models/model_loader.py                   (model registration pattern)

Task: Create models/credit_risk/train_smb_pd_model.py

Requirements:

1. Mirror the structure of train_cc_pd_model.py exactly:
   - Same MLflow tracking pattern
   - Same monotone constraint map approach
   - Same build_scorecard() + build_woe_scorecard() calls
   - Same verify_monotonicity() call
   - Same MLflow model registration under name "smb_pd_v1"

2. Define SMB-specific feature sets:

   NUMERIC_COLS = [
     "business_age_years", "annual_revenue", "dscr",
     "debt_to_equity", "owner_fico", "num_employees",
     "trade_line_count", "months_oldest_trade",
     "num_derog_marks", "num_missed_pmts_12m",
     "inq_last_6m", "operating_cash_flow",
     "accounts_receivable_days", "inventory_days",
     "gross_margin", "net_profit_margin",
   ]
   CATEGORICAL_COLS = ["industry_naics_2d", "state", "legal_entity_type",
                       "collateral_type", "loan_purpose"]
   BOOL_COLS = ["personal_guarantee", "owner_bankruptcy_history",
                "revolving_credit_line_exists"]
   TARGET = "default_flag"

3. Define MONOTONE_CONSTRAINT_MAP for all SMB features:
   - business_age_years: +1  (older = lower PD)
   - annual_revenue: +1
   - dscr: +1                (higher DSCR = lower PD)
   - debt_to_equity: -1
   - owner_fico: +1
   - num_employees: 0
   - trade_line_count: +1
   - num_derog_marks: -1
   - num_missed_pmts_12m: -1
   - inq_last_6m: -1
   - operating_cash_flow: +1
   - accounts_receivable_days: -1 (longer AR days = cash flow risk)
   - inventory_days: -1
   - gross_margin: +1
   - net_profit_margin: +1
   All categorical/bool: 0

4. Synthetic data generator for CI / testing (no real data required):
   generate_synthetic_smb_data(n: int = 5000) -> pd.DataFrame
   - Use np.random with seed=42
   - Generate realistic ranges (dscr: 0.5–3.0, owner_fico: 450–850, etc.)
   - Default rate ~12% (higher than consumer)
   - Encode legal_entity_type choices: LLC, S-Corp, C-Corp, Sole-Prop

5. main() entrypoint that:
   - Loads data from DATA_DIR / "smb_pd_training.parquet" if exists,
     else calls generate_synthetic_smb_data()
   - Runs Optuna hyperparameter search (20 trials for CI, 200 for production)
   - Trains final model, verifies monotonicity
   - Builds scorecard + WoE scorecard
   - Registers in MLflow as "smb_pd_v1"
   - Prints summary table of AUC / KS / Gini

6. Add corresponding tests/test_smb_pd_model.py:
   - Smoke test: synthetic data → train → predict shape is correct
   - Monotonicity: verify_monotonicity passes on trained model
   - Scorecard: WoE scorecard JSON has expected columns
```

---

### PROMPT S2-C: Commercial PD Model Training Script

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - models/credit_risk/train_smb_pd_model.py  (just created — use as template)
  - models/credit_risk/train_cc_pd_model.py

Task: Create models/credit_risk/train_commercial_pd_model.py

Requirements — same structure as SMB script, but with commercial RE / CRE features:

1. NUMERIC_COLS = [
     "noi",                     # Net Operating Income
     "cap_rate",                # Capitalisation rate
     "ltv",                     # Loan-to-Value
     "dscr",
     "loan_amount",
     "property_age_years",
     "occupancy_rate",          # % leased
     "market_vacancy_rate",     # metro vacancy rate
     "sponsor_net_worth",
     "guarantor_fico",
     "amortization_period_years",
     "loan_term_years",
     "num_prior_commercial_loans",
     "prior_default_count",
   ]
   CATEGORICAL_COLS = ["property_type", "state", "market_tier",
                       "loan_purpose", "recourse_type"]
   BOOL_COLS = ["cross_collateralized", "interest_only_period",
                "environmental_flag"]
   TARGET = "default_flag"

2. MONOTONE_CONSTRAINT_MAP:
   - noi: +1
   - cap_rate: 0         (higher cap = higher yield but can signal risk)
   - ltv: -1             (higher LTV = higher PD)
   - dscr: +1
   - loan_amount: 0
   - property_age_years: 0
   - occupancy_rate: +1  (higher occupancy = lower PD)
   - market_vacancy_rate: -1
   - sponsor_net_worth: +1
   - guarantor_fico: +1
   - amortization_period_years: 0
   - loan_term_years: 0
   - num_prior_commercial_loans: +1
   - prior_default_count: -1
   All categorical/bool: 0

3. generate_synthetic_commercial_data(n: int = 3000) -> pd.DataFrame
   - dscr: uniform(0.8, 2.5), ltv: uniform(0.4, 0.95), noi: lognormal
   - occupancy_rate: beta(8, 2) * 100, cap_rate: uniform(0.04, 0.10)
   - Default rate ~8%
   - property_type choices: Office, Retail, Multifamily, Industrial, Hotel, Mixed-Use
   - market_tier: Tier1, Tier2, Tier3

4. Register in MLflow as "commercial_pd_v1"

5. Add tests/test_commercial_pd_model.py with same test structure as SMB.
```

---

### PROMPT S2-D: LGD Model

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - risk_models/ecl_engine.py        (uses lgd_rate config constant — replace this)
  - models/credit_risk/train_cc_pd_model.py  (training pattern)
  - models/model_loader.py           (preload / registry pattern)
  - agents/risk_modeling_agent.py    (ModelScores — add lgd_score field here)
  - schemas/contracts.py             (ModelScores dataclass)

Task 1: Create models/lgd/train_lgd_model.py

  FEATURES = [
    "collateral_type_encoded",  # label-encoded
    "ltv",                      # loan-to-value at origination
    "loan_term_months",
    "product_type_encoded",
    "borrower_segment_encoded", # consumer / smb / commercial
    "fico_score",
    "dti",
    "months_on_book",
    "economic_cycle",           # 0=expansion, 1=contraction (config-injected)
  ]
  TARGET = "realized_lgd"       # float 0.0–1.0

  Use a LightGBM regressor (not classifier).
  Constrain output to [0, 1] using a sigmoid wrapper in predict_lgd().
  Register in MLflow as "lgd_v1".
  Add generate_synthetic_lgd_data(n=4000) for CI:
    - collateral secured loans: realized_lgd ~ beta(2, 8) (low loss)
    - unsecured: realized_lgd ~ beta(5, 3) (higher loss)
    - Add 20% noise

Task 2: Create models/lgd/predict.py

  def predict_lgd(feature_df: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with columns: lgd_score (float 0-1), lgd_band (str)."""
    lgd_band thresholds:
      lgd_score < 0.20:  "Low"
      lgd_score < 0.45:  "Medium"
      lgd_score < 0.70:  "High"
      else:              "Severe"

Task 3: Update schemas/contracts.py
  Add to ModelScores dataclass:
    lgd_score: float = 0.40           # default until model available
    lgd_band: str = "Medium"

Task 4: Update agents/risk_modeling_agent.py
  - Import predict_lgd
  - Call predict_lgd() after predict_pd() in _run()
  - Populate ModelScores.lgd_score / lgd_band from output
  - Fall back to config lgd_rate constant if model unavailable

Task 5: Update risk_models/ecl_engine.py
  - Replace lgd_rate static constant with model_scores.lgd_score per account
  - Expected Loss per account: EL = pd_score * lgd_score * exposure
  - Retain existing lgd_rate as fallback when ModelScores.lgd_score == 0.40 default

Add tests/test_lgd_model.py:
  - Predict shape and range [0, 1]
  - ECL calculation uses lgd_score not constant when model scores present
```

---

## Sprint 3 — Portfolio Construction & Concentration Engine

---

### PROMPT S3-A: Concentration Monitor

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - monitoring/cc_portfolio_monitor.py    (monitoring pattern, alert thresholds)
  - monitoring/alert_router.py           (how alerts are fired)
  - decision_engine/policy_version_store.py (reading config from policy store)
  - audit/logger.py                      (audit write pattern)
  - data_contracts/v1/portfolio.py       (portfolio segment definitions)

Task: Create monitoring/concentration_monitor.py

Implement ConcentrationMonitor class:

1. ConcentrationReport dataclass:
     computed_at: str
     dimensions: list[ConcentrationDimension]
     breaches: list[ConcentrationBreach]
     total_accounts: int
     total_exposure: float

2. ConcentrationDimension dataclass:
     dimension: str        # "sector" | "state" | "risk_grade" | "product_type"
     breakdown: dict       # { value: { count, exposure, pct_of_total } }
     configured_limit_pct: float
     max_observed_pct: float
     at_risk: bool         # max_observed > 0.8 * configured_limit
     in_breach: bool       # max_observed > configured_limit

3. ConcentrationBreach dataclass:
     dimension: str
     segment_value: str
     observed_pct: float
     limit_pct: float
     excess_pct: float
     severity: Literal["Warning", "Breach"]

4. ConcentrationMonitor.__init__(db_path, policy_store):
   - Load concentration limits from policy_version_store under key
     "concentration_limits" (default if not configured):
       sector: 0.25    (no single NAICS sector > 25% of portfolio)
       state: 0.20     (no single state > 20%)
       risk_grade: 0.40 (no single grade > 40%)
       product_type: 0.60 (no single product > 60%)

5. compute_report(decisions_df: pd.DataFrame) -> ConcentrationReport
   decisions_df must have columns: account_id, exposure, naics_2d, state,
   risk_grade, product_type
   - Compute breakdown per dimension
   - Identify breaches
   - Fire alert via alert_router for each ConcentrationBreach

6. Expose via new FastAPI router mounted in decision-api/src/main.py:
   GET /v1/portfolio/concentration
   - Loads last 90 days of decisions from audit DB
   - Builds decisions_df
   - Returns ConcentrationReport as JSON

7. Add unit tests in tests/test_concentration_monitor.py:
   - Synthetic portfolio with deliberate sector breach
   - Assert breach detected with correct severity
   - Assert at_risk correctly identified at 80% of limit
```

---

### PROMPT S3-B: Portfolio Snapshot Enhancement

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - monitoring/cc_portfolio_monitor.py   (existing WA-PD computation)
  - risk_models/ecl_engine.py            (ECL computation)
  - schemas/contracts.py                 (ModelScores — now has lgd_score)
  - decision-api/src/main.py             (find existing portfolio endpoints)

Task: Create monitoring/portfolio_snapshot.py and a new API endpoint.

1. PortfolioSnapshot dataclass:
     computed_at: str
     total_accounts: int
     total_exposure: float
     wa_pd: float                # weighted average PD (exposure-weighted)
     wa_lgd: float               # weighted average LGD (exposure-weighted)
     wa_el: float                # weighted average EL = WA-PD * WA-LGD
     expected_loss_dollars: float # sum(pd * lgd * exposure) across portfolio
     risk_rating_distribution: dict  # { "Prime": %, "Near-Prime": %, "Subprime": % }
     delinquency_rates: dict     # { "30dpd": %, "60dpd": %, "90dpd": % }
     approval_rate_mtd: float
     approval_rate_qtd: float

2. Rating bands (map PD to rating):
     pd < 0.03:  "Prime"
     pd < 0.08:  "Near-Prime"
     pd < 0.15:  "Subprime"
     else:       "Deep-Subprime"

3. compute_snapshot(decisions_df: pd.DataFrame) -> PortfolioSnapshot
   decisions_df columns: account_id, decision, pd_score, lgd_score, exposure,
   originated_at, dpd_30, dpd_60, dpd_90

4. Add to decision-api/src/main.py:
   GET /v1/portfolio/snapshot
   - Load last 90 days of decisions from audit DB
   - Join model_scores from a model_scores table (or compute from latest scores)
   - Return PortfolioSnapshot JSON

5. Add unit tests in tests/test_portfolio_snapshot.py.
```

---

### PROMPT S3-C: Rebalancing Recommendation Engine

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - agents/base.py                         (BaseAgent pattern)
  - monitoring/concentration_monitor.py    (ConcentrationReport, ConcentrationDimension)
  - monitoring/portfolio_snapshot.py       (PortfolioSnapshot)
  - decision_engine/policy_version_store.py

Task: Create agents/portfolio_construction_agent.py

Implement PortfolioConstructionAgent(BaseAgent):

1. RebalancingAction dataclass:
     segment: str             # e.g. "sector:23" or "state:CA"
     dimension: str           # "sector" | "state" | "risk_grade" | "product_type"
     current_pct: float
     limit_pct: float
     recommended_action: Literal["REDUCE", "HOLD", "GROW"]
     urgency: Literal["Immediate", "Monitor", "Opportunistic"]
     reasoning: str           # plain-English, data-grounded
     estimated_wa_pd_impact: float  # change in portfolio WA-PD if actioned

2. RebalancingPlan dataclass:
     generated_at: str
     portfolio_wa_pd_current: float
     portfolio_wa_pd_projected: float  # after all REDUCE recommendations
     actions: list[RebalancingAction]
     summary: str             # 2–3 sentence executive summary

3. _run(inputs) logic:
   inputs keys: "concentration_report" (ConcentrationReport),
                "portfolio_snapshot" (PortfolioSnapshot)

   Algorithm:
   a. For each dimension in concentration_report.dimensions:
      - REDUCE: in_breach or (at_risk and trend > 0)
      - GROW:   max_observed < 0.3 * limit AND risk_grade not Subprime/Deep-Subprime
      - HOLD:   everything else
   b. Urgency:
      - in_breach → Immediate
      - at_risk → Monitor
      - else → Opportunistic
   c. Reasoning template (data-grounded, no LLM):
      REDUCE: "{segment} currently represents {current_pct:.1%} of portfolio,
               exceeding the {limit_pct:.1%} concentration limit by {excess:.1%}.
               Recommend reducing new originations in this segment."
      GROW:   "{segment} at {current_pct:.1%} is well below the {limit_pct:.1%}
               limit. Portfolio diversification benefit available."
   d. Estimate WA-PD impact:
      For REDUCE: if segment avg_pd > portfolio_wa_pd → reducing it lowers WA-PD
      projected_wa_pd = current_wa_pd - (excess_exposure * (seg_pd - wa_pd)) / total_exposure
   e. Build RebalancingPlan with actions sorted by urgency (Immediate first)

4. Add endpoint to decision-api/src/main.py:
   GET /v1/portfolio/rebalancing
   - Calls ConcentrationMonitor and PortfolioSnapshot
   - Runs PortfolioConstructionAgent
   - Returns RebalancingPlan JSON

5. Add GET /v1/portfolio/heatmap?dimension=sector|state|risk_grade
   Returns list of { label, value, pct_of_total, status: "ok"|"warning"|"breach" }
   Suitable for frontend chart rendering.

6. Add tests/test_portfolio_construction_agent.py:
   - Breach case: REDUCE recommended with Immediate urgency
   - Clean case: HOLD / GROW recommended
   - WA-PD impact calculation is arithmetically correct
```

---

## Sprint 4 — Underwriting Agent Enhancement

---

### PROMPT S4-A: Conditional Approval + Alternative Structures

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - decision_engine/engine.py
    (DECISION_APPROVE, DECISION_REJECT, DECISION_MANUAL_REVIEW, DecisionResult,
     make_decision() — read the full file)
  - decision_engine/policy_dsl.py      (policy rule evaluation)
  - decision-api/src/main.py           (DecisionResponse schema, /v1/decide)
  - schemas/contracts.py               (ModelScores)

Task 1: Add Conditional Approval to decision_engine/engine.py

1. Add DECISION_CONDITIONAL = "CONDITIONAL_APPROVAL" constant (already exists
   as a stub — wire it up).

2. Add Condition dataclass:
     condition_type: Literal[
       "INCOME_VERIFICATION_REQUIRED",
       "REDUCED_LIMIT",
       "COLLATERAL_REQUIRED",
       "ADDITIONAL_DOCUMENTATION",
       "GUARANTOR_REQUIRED",
     ]
     description: str
     suggested_limit: Optional[float]       # for REDUCED_LIMIT
     min_coverage_ratio: Optional[float]    # for COLLATERAL_REQUIRED
     doc_types: Optional[list[str]]         # for ADDITIONAL_DOCUMENTATION

3. Add conditions: list[Condition] field to DecisionResult.

4. In make_decision(), add Conditional Approval logic BEFORE the REJECT path:
   Trigger if ALL of these are true:
     a. pd_score <= 0.10 (would normally approve on risk)
     b. At least one of these soft conditions fires:
        - income unverified (feature "income_verified" == False or missing)
        - dti between 0.43 and 0.50 (elevated but not rejection)
        - collateral present but coverage_ratio < 1.0
        - thin file (num_open_trades < 3)
   Attach the relevant Condition object(s) to DecisionResult.conditions.
   Set decision = DECISION_CONDITIONAL.

Task 2: Create decision_engine/alternative_structures.py

1. AlternativeStructure dataclass:
     rank: int                     # 1 = most feasible
     structure_type: Literal["REDUCED_AMOUNT", "ADD_COLLATERAL", "REPRICE"]
     description: str
     suggested_loan_amount: Optional[float]
     suggested_collateral_type: Optional[str]
     suggested_apr: Optional[float]
     feasibility_score: float      # 0.0–1.0
     estimated_pd_at_structure: Optional[float]

2. generate_alternatives(
       request: DecisionRequest,
       model_scores: ModelScores,
       decision: str,
   ) -> list[AlternativeStructure]

   Only generates alternatives when decision == DECISION_REJECT.
   Evaluate these three options:
   a. REDUCED_AMOUNT:
      - Binary search: find largest loan_amount where pd_score would likely
        approve (proxy: reduce amount until dti < 0.40 assuming same income).
        feasibility = 0.8 if reduced amount >= 0.5 * original, else 0.4
   b. ADD_COLLATERAL:
      - If no collateral present: suggest real_estate or vehicle
        feasibility = 0.6
      - If collateral present but LTV too high: suggest LTV <= 0.75
        feasibility = 0.7
   c. REPRICE:
      - Suggest APR = current_apr + (pd_score - 0.10) * 200 bps
        (risk-based pricing to compensate for elevated PD)
        feasibility = 0.5 (lower — reprice does not change risk)
   Sort by feasibility_score descending, return top 3.

3. Integrate into decision_engine/engine.py:
   - Call generate_alternatives() when decision == DECISION_REJECT
   - Add alternative_structures: list[AlternativeStructure] to DecisionResult

4. Update decision-api/src/main.py DecisionResponse schema:
   - Add conditions: list[dict] | None
   - Add alternative_structures: list[dict] | None
   Populate from DecisionResult.

5. Add tests/test_conditional_approval.py and tests/test_alternatives.py.
```

---

### PROMPT S4-B: Risk Score Confidence Interval + Covenant Engine

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - agents/risk_modeling_agent.py  (RiskModelingAgent, champion/challenger loading)
  - schemas/contracts.py           (ModelScores dataclass)
  - models/credit_risk/predict.py  (predict_pd interface)
  - decision_engine/engine.py      (DecisionResult)

Task 1: Add Confidence Interval to Risk Scoring (risk_modeling_agent.py)

1. Add to ModelScores:
     pd_ci_lower: float = 0.0   # 5th percentile of bootstrap distribution
     pd_ci_upper: float = 1.0   # 95th percentile

2. In RiskModelingAgent._run(), after computing pd_score:
   If bootstrap_enabled (config flag, default False to preserve latency):
     - Run predict_pd on the same feature row 11 times using subsets of trees
       (LightGBM supports num_iteration parameter — use random samples of
       50%–100% of trees, 11 draws)
     - Take p5 and p95 of the 11 predictions
     - Populate pd_ci_lower and pd_ci_upper
   Else (default fast path):
     - pd_ci_lower = max(0, pd_score - 0.025)
     - pd_ci_upper = min(1, pd_score + 0.025)
   This ensures the field is always populated without breaking latency SLA.

   Add bootstrap_enabled: false to agent_config.yaml under risk_modeling.

Task 2: Create decision_engine/covenant_engine.py

1. Covenant dataclass:
     covenant_type: str           # e.g. "DSCR_MAINTENANCE"
     description: str             # plain-English
     threshold: Optional[float]   # numeric trigger value
     frequency: str               # "Quarterly" | "Annual" | "At-Origination"
     consequence: str             # what happens on breach

2. COVENANT_MATRIX (module-level dict):
   Structure: { product_type → industry_risk_tier → list[Covenant] }
   Include at minimum:
   - commercial loans, any tier:
       DSCR_MAINTENANCE: DSCR >= 1.25, Quarterly, "Loan placed on watchlist"
       MAX_LTV: LTV <= 75%, At-Origination, "Approval conditioned on appraisal"
       FINANCIAL_REPORTING: Annual audited financials, Annual, "Default if not provided"
   - smb loans, High/Elevated tier:
       PERSONAL_GUARANTEE: Owner guarantee required, At-Origination, "Required for approval"
       ANNUAL_TAX_RETURNS: Annual, "Default if not provided"
       REVENUE_COVENANT: Annual revenue >= 80% of projected, Annual, "Watchlist"
   - smb loans, Low/Medium tier:
       ANNUAL_TAX_RETURNS only
   - consumer secured (mortgage/auto):
       LTV_LIMIT: LTV <= 80%, At-Origination, "Conditional approval at higher LTV"
       LIEN_SEARCH: At-Origination, "Required before funding"
   - consumer unsecured: [] (no covenants)

3. get_covenants(
       product_type: str,
       industry_risk_tier: str,
       dscr: Optional[float],
       ltv: Optional[float],
       loan_amount: float,
   ) -> list[Covenant]

4. Add covenant_package: list[dict] to DecisionResult in decision_engine/engine.py.
   Call get_covenants() and populate for all APPROVE / CONDITIONAL_APPROVAL decisions.

5. Expose in /v1/decide response.

6. Add tests/test_covenant_engine.py covering all product/tier combinations.
```

---

## Sprint 5 — Policy Waiver Tracking & Adherence Reporting

---

### PROMPT S5-A: Waiver Management System

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - compliance/waiver_store.py  (does not exist — create it)
  - audit/logger.py             (append-only write pattern)
  - audit/override_log.py       (similar pattern for overrides — use as reference)
  - compliance/rbac.py          (role check pattern)
  - decision-api/src/main.py    (FastAPI router pattern, four-eyes approval pattern)

Task: Create compliance/waiver_store.py and wire API endpoints.

1. Waiver dataclass (frozen):
     waiver_id: str
     application_id: str
     policy_rule_id: str          # which rule was violated
     policy_rule_description: str
     waiver_reason: str
     requested_by: str            # user_id
     requested_at: str            # ISO-8601 UTC
     approved_by: Optional[str]
     approved_at: Optional[str]
     denied_by: Optional[str]
     denied_at: Optional[str]
     denial_reason: Optional[str]
     expires_at: Optional[str]    # ISO-8601 UTC; None = single-use
     scope: Literal["single", "portfolio"]
     status: Literal["pending", "approved", "denied", "expired"]
     notes: Optional[str]

2. WaiverStore class:
   - Backed by SQLite (waivers.db at project root)
   - Table: waivers (all fields as TEXT/REAL, status NOT NULL)
   - Methods:
       request_waiver(application_id, policy_rule_id, ...) -> Waiver
       approve_waiver(waiver_id, approved_by) -> Waiver
         Validate: approved_by != waiver.requested_by (four-eyes)
         Validate: status == "pending"
       deny_waiver(waiver_id, denied_by, denial_reason) -> Waiver
       get_waiver(waiver_id) -> Waiver
       list_waivers(status, limit, offset) -> list[Waiver]
       expire_stale_waivers() -> int   # returns count expired

3. expire_stale_waivers() should be called at startup and via a background
   task every 24 hours. Use FastAPI lifespan context to schedule.

4. Add API endpoints to decision-api/src/main.py:
   POST /v1/waivers/request         body: {application_id, policy_rule_id,
                                           waiver_reason, scope, expires_at}
   POST /v1/waivers/{id}/approve    body: {approved_by}
   POST /v1/waivers/{id}/deny       body: {denied_by, denial_reason}
   GET  /v1/waivers                 query: status, limit=50, offset=0
   GET  /v1/waivers/{id}
   GET  /v1/waivers/report          query: period=30d|90d|ytd
     Report response: {
       period, total_requested, total_approved, total_denied,
       approval_rate, by_policy_rule: [{rule_id, count, approved}]
     }

5. Write all waiver events to audit/logger.py with event_type="WAIVER_*"

6. Include waiver_count and pending_waivers in exam_packet_builder output.

7. Tests in tests/test_waiver_store.py:
   - Four-eyes enforcement (same user can't approve their own waiver)
   - Expiry logic
   - list_waivers filter by status
```

---

### PROMPT S5-B: Policy Adherence Report

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - reporting/dispatcher.py          (report dispatcher pattern)
  - reporting/executive_summary.py   (report output format)
  - compliance/exam_packet_builder.py (how reports are included in exam packets)
  - decision_engine/policy_version_store.py  (list policy rules)
  - audit/logger.py                  (query audit log by event_type)
  - compliance/waiver_store.py       (just created)

Task: Create reporting/policy_adherence.py

1. PolicyRuleStats dataclass:
     rule_id: str
     rule_description: str
     decisions_evaluated: int
     compliance_count: int
     compliance_rate: float         # compliance_count / decisions_evaluated
     exception_count: int           # decisions where rule triggered but not blocked
     waiver_count: int              # approved waivers for this rule
     trend_30d: float               # compliance_rate change vs prior 30-day window
     status: Literal["Healthy", "Watch", "Breach"]
       # Healthy: compliance_rate >= 0.95
       # Watch: 0.85 <= compliance_rate < 0.95
       # Breach: compliance_rate < 0.85

2. PolicyAdherenceReport dataclass:
     period: str              # "30d" | "90d" | "ytd"
     generated_at: str
     total_decisions: int
     overall_compliance_rate: float
     rules: list[PolicyRuleStats]
     top_exception_rules: list[str]  # top 3 rule_ids by exception_count
     summary: str             # 2-sentence data-grounded summary

3. generate_policy_adherence_report(
       period: Literal["30d", "90d", "ytd"],
       db_path: str,
       waiver_store: WaiverStore,
   ) -> PolicyAdherenceReport

   Algorithm:
   - Query audit log for all decision events in the period
   - For each policy rule in policy_version_store.get_active():
       count decisions where rule was evaluated (from audit event metadata)
       count where rule was triggered (exception) vs. passed
       join with waiver_store to count approved waivers for rule
   - Build PolicyRuleStats per rule
   - summary template:
     "In the {period} period ending {date}, {total_decisions} decisions were
      evaluated against {N} active policy rules with an overall compliance
      rate of {overall:.1%}. {len(breach_rules)} rules are in breach status
      requiring immediate attention."

4. Register with reporting/dispatcher.py under report_type="policy_adherence"

5. Add to compliance/exam_packet_builder.py:
   Include policy adherence report in Section "Policy Monitoring" of exam packet

6. Add API endpoint:
   GET /v1/compliance/policy-adherence?period=30d
   Returns PolicyAdherenceReport JSON

7. Tests in tests/test_policy_adherence.py:
   - Seeded audit data with known rule violations
   - Assert compliance_rate computed correctly
   - Assert trend_30d is negative when violations increased
```

---

## Sprint 6 — Orchestration Hardening & FFIEC

---

### PROMPT S6-A: Agent Fallback Strategies & Escalation Thresholds

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - orchestration/pipeline.py         (CreditRiskPipeline._run_stage, retry logic)
  - config/agent_config.yaml          (current config structure)
  - decision_engine/engine.py         (make_decision, pd_score thresholds)
  - decision_engine/policy_version_store.py

Task 1: Rule-Based Fallback Scorer

Create decision_engine/rule_based_fallback.py:

  def rule_based_pd_estimate(features: dict) -> tuple[float, str]:
    """
    Returns (pd_score, rationale) using only bureau features.
    Used when ML model is unavailable.
    Decision tree:
      fico_score >= 720 AND dti < 0.36 AND num_derog_marks == 0 → PD = 0.03
      fico_score >= 680 AND dti < 0.43                           → PD = 0.07
      fico_score >= 620 AND dti < 0.50                           → PD = 0.13
      fico_score >= 580                                          → PD = 0.22
      else                                                       → PD = 0.40
    If fico_score not available: return PD = 0.99 (force refer)
    """

Task 2: Update orchestration/pipeline.py

  In _run_stage() for the "risk_modeling" stage:
  - If RiskModelingAgent returns AgentStatus.FAILURE:
      1. Check config: risk_modeling.on_failure
         - "use_rule_based_fallback": call rule_based_pd_estimate(), build
           a minimal ModelScores object, set metadata["fallback"] = True
         - "skip": log warning, continue with empty model_scores
         - "abort": re-raise (current behaviour)
      2. Write fallback event to audit log with event_type="RISK_MODEL_FALLBACK"

Task 3: Configurable Escalation Thresholds

  Update config/agent_config.yaml, add:
    decision_engine:
      escalation_bands:
        - product: "credit_card"
          refer_if_pd_between: [0.08, 0.12]
        - product: "personal_loan"
          refer_if_pd_between: [0.07, 0.11]
        - product: "mortgage"
          refer_if_pd_between: [0.05, 0.09]
        - product: "smb_loan"
          refer_if_pd_between: [0.10, 0.16]
        - product: "commercial_loan"
          refer_if_pd_between: [0.06, 0.10]

  Update decision_engine/engine.py make_decision():
  - Replace hardcoded band thresholds with config lookup:
      bands = load_escalation_bands(product_type)
      if bands.refer_low <= pd_score <= bands.refer_high: → MANUAL_REVIEW
  - load_escalation_bands() reads from policy_version_store first
    (so bands can be updated via policy API), falls back to agent_config.yaml

Task 4: Tests
  - tests/test_fallback_scorer.py: all 5 FICO bands return expected PD range
  - tests/test_escalation_bands.py: config-driven bands respected per product
```

---

### PROMPT S6-B: FFIEC Call Report

```
You are working in the credit-risk-platform codebase.

Context files to read first:
  - reporting/hmda_lar.py     (regulatory report pattern — CSV output)
  - reporting/cra_activity.py (CRA report structure)
  - reporting/dispatcher.py   (registration pattern)
  - data_contracts/v1/portfolio.py (loan category definitions)

Task: Create reporting/ffiec_call_report.py

Implement FFIECCallReportGenerator:

1. FFIEC_LOAN_CATEGORIES mapping (Schedule RC-C Part I):
   Map internal product_type to FFIEC categories:
     "mortgage"          → "1a. Construction and land development"
                           or "1c. Secured by 1-4 family residential"
                           (use loan_purpose to disambiguate)
     "commercial_loan"   → "4. Commercial and industrial loans"
     "smb_loan"          → "4. Commercial and industrial loans"
     "credit_card"       → "6b. Revolving, open-end loans secured by 1-4 family"
                           or "6c. Other revolving credit plans" (use product flag)
     "personal_loan"     → "6d. Other consumer loans"
     "auto_loan"         → "6a. Automobile loans"
     "deposit"           → (exclude)

2. FFIECScheduleRCC dataclass:
     institution_name: str
     report_date: str            # quarter-end date YYYY-MM-DD
     rssd_id: Optional[str]      # Federal Reserve charter ID
     rows: list[FFIECLoanRow]

3. FFIECLoanRow dataclass:
     category_code: str
     category_description: str
     domestic_offices_amount: float   # in thousands USD
     foreign_offices_amount: float    # 0 for domestic-only lenders
     memo_past_due_30_89: float       # past-due 30-89 days
     memo_past_due_90_plus: float

4. generate_schedule_rcc(
       period_start: str,
       period_end: str,
       decisions_df: pd.DataFrame,
       institution_name: str,
   ) -> FFIECScheduleRCC

   - Group portfolio by FFIEC category
   - Sum outstanding balances, delinquency buckets
   - Amounts in thousands (divide by 1000, round to nearest thousand)

5. Export methods:
   to_csv() -> str     # pipe-delimited, FFIEC standard layout
   to_xml() -> str     # XBRL-compatible XML (basic, no taxonomy validation)
   to_dict() -> dict

6. Register with reporting/dispatcher.py as report_type="ffiec_rc_c"

7. Add to exam_packet_builder:
   Include FFIEC RC-C CSV in Section "Regulatory Reports"

8. Add API endpoint:
   GET /v1/reports/ffiec-rc-c?period_start=2026-01-01&period_end=2026-03-31
   Returns FFIECScheduleRCC JSON

9. Tests in tests/test_ffiec_call_report.py:
   - Loan category mapping covers all product_types
   - Amounts rounded to nearest thousand
   - Delinquency buckets sum correctly
```

---

## Sprint 7 — Frontend Dashboard

---

### PROMPT S7-A: Portfolio Overview Page

```
You are working in the credit-risk-platform codebase.

Context:
  - Backend endpoints available:
      GET /v1/portfolio/snapshot       → PortfolioSnapshot JSON
      GET /v1/portfolio/concentration  → ConcentrationReport JSON
      GET /v1/portfolio/rebalancing    → RebalancingPlan JSON
      GET /v1/portfolio/heatmap?dimension=sector
      GET /v1/health
  - Existing frontend tech (if ui/ exists, check its package.json for deps).
    Otherwise create a new Next.js app in ui/ using:
      npx create-next-app@latest ui --typescript --tailwind --app

Task: Build ui/app/portfolio/page.tsx — Portfolio Overview dashboard page.

Requirements:

1. Live metrics bar (top of page, SSE or 30-second poll):
   - Total Accounts: formatted number
   - WA PD: shown as percentage with colour coding (green <5%, amber 5-10%, red >10%)
   - WA LGD: percentage
   - Expected Loss ($): formatted currency
   - Approval Rate MTD: percentage
   All sourced from GET /v1/portfolio/snapshot

2. 30/60/90 DPD trend chart (Recharts LineChart):
   - X-axis: last 12 months
   - Y-axis: delinquency rate %
   - Three lines: 30dpd, 60dpd, 90dpd
   - Tooltip with exact values
   Data: GET /v1/portfolio/snapshot (include delinquency_rates)

3. Risk Rating Distribution (Recharts PieChart):
   - Slices: Prime (green), Near-Prime (yellow), Subprime (orange), Deep-Subprime (red)
   - Legend with percentages
   Data: portfolio_snapshot.risk_rating_distribution

4. Concentration Heatmap Table:
   - Rows: top 8 segments by exposure
   - Columns: Segment | Exposure % | Limit % | Status
   - Status cell: green "OK" / amber "Watch" / red "Breach"
   Data: GET /v1/portfolio/concentration

5. Active Alerts Panel (right sidebar):
   - List of concentration breaches and metric alerts
   - Each alert: icon + dimension + description + severity badge
   Data: concentration_report.breaches

6. Use Tailwind for styling. Follow a dark-background, card-based layout.
   Each metric card: white text on dark slate background.
   Charts: dark background, colourful lines.

7. Add a refresh button that refetches all data.

8. Handle loading and error states gracefully (skeleton loaders, error banners).

9. Create ui/lib/api.ts with typed fetch wrappers for all endpoints used.
```

---

### PROMPT S7-B: Scorecard Explorer Page

```
You are working in the credit-risk-platform codebase.

Context:
  Backend endpoints:
    GET /v1/models/{name}/scorecard      → WoE scorecard JSON
    GET /v1/models                       → MLflow model list
  Available model names: "cc_pd_v1", "smb_pd_v1", "commercial_pd_v1"

Task: Build ui/app/scorecard/page.tsx

Requirements:

1. Segment selector tabs at top: Consumer | SMB | Commercial
   Maps to model names: cc_pd_v1 | smb_pd_v1 | commercial_pd_v1

2. WoE Scorecard Table (left panel, 60% width):
   Columns: Feature | Bin Range | WoE | Points | IV
   - Rows grouped by feature (collapsible feature rows)
   - Points column: colour-coded (positive = green, negative = red)
   - IV column: badge — "Strong" (>0.3), "Medium" (0.1–0.3), "Weak" (<0.1)
   - Sort by IV descending by default
   - Search/filter input to find features

3. Performance Metrics panel (right panel, 40% width):
   - AUC-ROC: gauge chart (0.5–1.0 scale, green zone > 0.7)
   - Gini Coefficient: numeric + trend arrow
   - KS Statistic: numeric
   - Model version and training date

4. Calibration Curve chart (below table):
   - Recharts ScatterChart
   - X-axis: Predicted PD (0–1)
   - Y-axis: Observed Default Rate (0–1)
   - Diagonal reference line (perfect calibration)
   - Scatter dots = each score decile

5. On feature row click → expand to show:
   - Bar chart of WoE per bin for that feature
   - Distribution of population across bins (secondary Y-axis)

6. Add a "Download Scorecard CSV" button that exports the table.

7. Accessibility: all charts have aria-labels, tables have proper th/caption.
```

---

### PROMPT S7-C: Compliance & Waiver Dashboard Page

```
You are working in the credit-risk-platform codebase.

Context:
  Backend endpoints:
    GET /v1/compliance/policy-adherence?period=30d  → PolicyAdherenceReport
    GET /v1/waivers?status=pending
    GET /v1/reports/exam-packets                    → list of exam packets
    GET /v1/fair-lending/report                     → AIR by protected class
    POST /v1/reports/exam-packets/generate          → trigger generation

Task: Build ui/app/compliance/page.tsx

Requirements:

1. Period selector at top: 30 days | 90 days | YTD

2. Overall Compliance Score (large KPI card):
   - Circular progress gauge: overall_compliance_rate as %
   - Colour: green ≥95%, amber 85–95%, red <85%
   - Sub-text: "{total_decisions} decisions evaluated"

3. Policy Rules Table:
   Columns: Rule | Evaluated | Compliance Rate | Exceptions | Waivers | Status
   - Status badge: Healthy (green) / Watch (amber) / Breach (red)
   - Sort by status (Breach first), then by compliance_rate ascending
   - Expandable row: show trend sparkline for last 6 periods

4. Fair Lending AIR Panel:
   - Bar chart: AIR by protected class (race, sex, age, national_origin)
   - Horizontal reference line at 0.80 (4/5ths threshold)
   - Bars below 0.80: red fill; bars above: green fill
   Data: GET /v1/fair-lending/report

5. Pending Waivers Panel:
   - Card list: each pending waiver shows application_id, policy_rule, requested_by, age
   - "Approve" / "Deny" buttons (POST /v1/waivers/{id}/approve or /deny)
   - Confirmation modal before action
   - Refresh list after action

6. Exam Packet Generator:
   - "Generate Exam Packet" button → POST to trigger generation
   - Progress indicator (poll GET /v1/reports/exam-packets until status=ready)
   - "Download" button when ready

7. Use same Tailwind dark theme as Portfolio page.
   Reuse ui/lib/api.ts fetch wrappers, adding new typed methods.

8. Handle 403 (insufficient role) gracefully: show "Insufficient permissions" message
   rather than crashing.
```

---

## Cross-Cutting Prompt: Tests & Linting Gate

---

### PROMPT CX-1: Test Coverage Gate

```
You are working in the credit-risk-platform codebase.

Context files:
  - pytest.ini                    (current pytest config)
  - requirements.txt              (installed packages)
  - Makefile                      (existing make targets)

Task: Ensure all new modules from Sprints 1–6 have test coverage and update
the CI gate.

1. Update pytest.ini:
   addopts = --cov=agents --cov=decision_engine --cov=compliance
             --cov=monitoring --cov=reporting --cov=risk_models
             --cov=explainability --cov=models
             --cov-report=term-missing --cov-fail-under=80

2. Confirm tests exist for each new module (create stubs if missing):
   - tests/test_credit_analyst_agent.py
   - tests/test_risk_narrative_generator.py
   - tests/test_woe_scorecard.py
   - tests/test_smb_pd_model.py
   - tests/test_commercial_pd_model.py
   - tests/test_lgd_model.py
   - tests/test_concentration_monitor.py
   - tests/test_portfolio_snapshot.py
   - tests/test_portfolio_construction_agent.py
   - tests/test_conditional_approval.py
   - tests/test_alternatives.py
   - tests/test_covenant_engine.py
   - tests/test_waiver_store.py
   - tests/test_policy_adherence.py
   - tests/test_fallback_scorer.py
   - tests/test_escalation_bands.py
   - tests/test_ffiec_call_report.py

3. Add to Makefile:
   test:
       pytest tests/ -v

   test-sprint1:
       pytest tests/test_credit_analyst_agent.py
              tests/test_risk_narrative_generator.py -v

   test-sprint2:
       pytest tests/test_woe_scorecard.py tests/test_smb_pd_model.py
              tests/test_commercial_pd_model.py tests/test_lgd_model.py -v

   test-sprint3:
       pytest tests/test_concentration_monitor.py
              tests/test_portfolio_snapshot.py
              tests/test_portfolio_construction_agent.py -v

   test-sprint4:
       pytest tests/test_conditional_approval.py tests/test_alternatives.py
              tests/test_covenant_engine.py -v

   test-sprint5:
       pytest tests/test_waiver_store.py tests/test_policy_adherence.py -v

   test-sprint6:
       pytest tests/test_fallback_scorer.py tests/test_escalation_bands.py
              tests/test_ffiec_call_report.py -v

4. Run make test and confirm all tests pass before committing any sprint work.
```
