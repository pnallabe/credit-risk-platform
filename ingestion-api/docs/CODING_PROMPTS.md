# AI Lending Decision Platform — Coding Prompts

A sequential build guide. Each prompt is self-contained and references the PRD.
Complete them in order; later prompts depend on artifacts from earlier ones.

---

## Phase 1 — Data Foundation

### Prompt 1 — Synthetic Dataset Generator

```
Build a Python script at `data/generate_synthetic_data.py` that generates a
realistic loan application dataset for development and model training.

Requirements:
- Use Faker and numpy/pandas; install via requirements.txt
- Generate a configurable number of records (default 100,000; support up to 10M via CLI flag --rows)
- Output a Parquet file to data/raw/loan_applications.parquet

Each record must include:
  application_id (UUID), customer_id, submitted_at (datetime)
  credit_score (300–850), annual_income (float), employment_status
  (employed/self-employed/unemployed/retired), employer_tenure_months (int),
  debt_to_income_ratio (0.0–0.65), existing_debt_amount (float),
  loan_amount (1000–100000), loan_purpose (personal/auto/home_improvement/
  medical/education/debt_consolidation), loan_term_months (12/24/36/48/60),
  num_open_accounts (int), num_derogatory_marks (int),
  months_since_last_delinquency (int, nullable),
  state (US state code), zip_code_prefix (3-digit str)

Target variable:
  default_flag (bool) — derive using a logistic formula so that higher
  credit_score, lower DTI, higher income, and shorter term reduce default
  probability. Target ~12% overall default rate.

Also generate a held-out test set (10% of total) saved separately to
data/raw/loan_applications_test.parquet.

Add a short README section in data/README.md describing the schema and
generation methodology.
```

---

### Prompt 2 — Database & Feature Store Schema

```
Create a PostgreSQL schema at `db/schema.sql` for the lending platform.

Tables required:

1. loan_applications — stores raw intake fields (mirror the Pydantic model in
   ingestion-api/src/models.py LoanApplication)

2. features — feature store table:
   application_id, feature_set_version (str), computed_at (timestamp),
   credit_utilization (float), income_stability_score (float),
   repayment_capacity (float), debt_service_coverage_ratio (float),
   credit_age_months (int), payment_history_score (float),
   feature_json (JSONB for additional features)

3. model_predictions — one row per model run:
   prediction_id (UUID PK), application_id (FK), model_name, model_version,
   predicted_at, score (float), label (str), confidence (float), metadata (JSONB)

4. audit_log — append-only decision log:
   log_id (UUID PK), application_id, logged_at, input_features (JSONB),
   model_version, feature_version, fraud_score, risk_score,
   decision_output, reason_codes (text[]), decision_latency_ms (int)

5. model_registry — governance table:
   model_id (UUID PK), model_name, model_version, status
   (candidate/approved/deprecated), approved_by, approved_at,
   performance_metrics (JSONB), created_at

Add appropriate indexes (application_id, logged_at, model_version).
Add a db/migrations/001_initial_schema.sql using Flyway-compatible naming.
Use SQLAlchemy ORM models mirroring this schema in db/orm_models.py.
```

---

## Phase 2 — Feature Engineering

### Prompt 3 — Feature Engineering Pipeline

```
Build a feature engineering module at `feature_pipeline/features.py`.

Input: a pandas DataFrame with the raw loan application fields from Prompt 1.
Output: the same DataFrame with the following new columns appended.

Features to compute:
  credit_utilization        = existing_debt_amount / (annual_income * 0.4)
                              clipped to [0, 1]
  income_stability_score    = sigmoid(employer_tenure_months / 12)
  repayment_capacity        = 1 - debt_to_income_ratio
  debt_service_coverage     = annual_income / (existing_debt_amount + 1)
  credit_age_score          = min(num_open_accounts / 10, 1.0)
  derogatory_penalty        = num_derogatory_marks * 0.05, clipped to [0, 0.5]
  months_since_delinquency  = fill nulls with 999, then clip to [0, 999]
  log_loan_amount           = log1p(loan_amount)
  log_annual_income         = log1p(annual_income)
  dti_x_loan_amount         = debt_to_income_ratio * loan_amount  (interaction)
  employment_encoded        = ordinal: unemployed=0, retired=1,
                              self-employed=2, employed=3

Requirements:
- All functions must be pure (no side effects).
- Each feature function has a docstring explaining the credit rationale.
- Write unit tests in feature_pipeline/tests/test_features.py using pytest
  covering edge cases (zero income, missing delinquency, max DTI).
- Add a FeaturePipelineConfig dataclass holding version string and
  feature list so the version can be logged to the feature store.
- Expose a compute_features(df, config) -> DataFrame top-level function.
```

---

### Prompt 4 — Feature Store Writer

```
Create feature_pipeline/feature_store.py that persists computed features
to the PostgreSQL features table defined in Prompt 2.

Requirements:
- Accept a DataFrame (output of compute_features) and a FeaturePipelineConfig.
- Use SQLAlchemy async engine (asyncpg driver).
- Perform an upsert on (application_id, feature_set_version) using
  ON CONFLICT DO UPDATE.
- Batch inserts in chunks of 1000 rows.
- Log total rows written and duration.
- Expose write_features(df, config, db_url) -> dict with keys
  {rows_written, duration_seconds, feature_version}.
- Add integration test in feature_pipeline/tests/test_feature_store.py
  using pytest-asyncio and a SQLite in-memory fallback for CI.
```

---

## Phase 3 — Machine Learning Models

### Prompt 5 — Fraud Detection Model

```
Build a fraud detection model at `models/fraud_detection/train.py`.

Dataset: load data/raw/loan_applications.parquet.
Target: synthesize a fraud_flag column — flag ~3% of records as fraudulent
using a rule-based heuristic (e.g., very high loan amount + low income +
short employment + 0 open accounts → higher fraud probability).

Model:
- Train a GradientBoostingClassifier (scikit-learn) using the engineered
  features from Prompt 3.
- Hyperparameter tune with Optuna (10 trials) optimizing F1 score.
- Evaluate on the held-out test set; assert precision > 0.85 and AUC > 0.80.
- Save the trained model as models/fraud_detection/fraud_model_v1.pkl
  using joblib.
- Log all metrics (precision, recall, F1, AUC, KS statistic) to MLflow
  with experiment name "fraud_detection".
- Print a classification report and confusion matrix to stdout.

Also create models/fraud_detection/predict.py:
- Load a model from a path provided as arg.
- Expose predict_fraud(features_df) -> DataFrame with columns
  fraud_probability and fraud_flag (using 0.3 / 0.6 thresholds from PRD).
- Include threshold logic: <0.3 → continue, 0.3–0.6 → manual_review,
  >0.6 → reject.
```

---

### Prompt 6 — Credit Risk Model (Probability of Default)

```
Build a credit risk model at `models/credit_risk/train.py`.

Dataset: data/raw/loan_applications.parquet; target column: default_flag.
Features: use all engineered features from the feature pipeline (Prompt 3).

Model:
- Train a LightGBM classifier.
- Perform 5-fold stratified cross-validation.
- Hyperparameter tune with Optuna (20 trials).
- Evaluate on held-out test set; assert AUC > 0.75 and KS > 0.35.
- Save model as models/credit_risk/risk_model_v1.pkl.
- Log all metrics + feature importances to MLflow experiment "credit_risk".
- Generate and save a KS plot (matplotlib) to models/credit_risk/ks_plot.png.

Create models/credit_risk/predict.py:
- Expose predict_pd(features_df) -> DataFrame with columns
  pd_score (float 0–1) and pd_band (str: low/medium/high).
  Bands: low < 0.05, medium 0.05–0.10, high > 0.10.
- All model files versioned via a MODEL_VERSION constant.
```

---

### Prompt 7 — Pricing Engine

```
Build a rule-based + ML pricing engine at `models/pricing/engine.py`.

The pricing model calculates the recommended interest rate based on:
  base_rate              = 5.0%  (configurable)
  risk_premium           = pd_score * 25  (maps PD to extra rate)
  fraud_adjustment       = 2.0% if fraud_flag == manual_review else 0
  Expected Loss          = pd_score * loan_amount * 0.45  (LGD = 45%)
  Expected Profit        = (interest_rate/100) * loan_amount
                           - Expected Loss - (funding_cost_rate * loan_amount)
  funding_cost_rate      = 3.5%  (configurable)

Output per application:
  recommended_rate (float)   capped at [5.0, 36.0] %
  expected_loss (float)
  expected_profit (float)
  profitability_flag (bool)  True if expected_profit > 0

Expose a PricingConfig dataclass for all rates and a
calculate_pricing(pd_score, fraud_flag, loan_amount) -> PricingResult
function.

Write unit tests in models/pricing/tests/test_engine.py covering:
- Low PD → rate near base_rate
- High PD → rate near cap
- Negative profit scenarios
```

---

## Phase 4 — Decision Engine

### Prompt 8 — Decision Engine

```
Build the decision engine at `decision_engine/engine.py`.

The engine combines fraud detection, credit risk, and pricing into a
final loan decision.

Decision logic (from PRD):
  if fraud_flag == "reject":            → REJECT  (reason: FRAUD_DETECTED)
  elif fraud_flag == "manual_review":   → MANUAL_REVIEW
  elif pd_score < 0.05:                 → APPROVE  (standard terms)
  elif pd_score <= 0.10:                → APPROVE  (recommended_rate from pricing engine)
  else:                                 → REJECT   (reason: HIGH_DEFAULT_RISK)

Reason codes (FCRA-compliant adverse action codes):
  AA01 — High probability of default
  AA02 — Fraud indicators detected
  AA03 — Insufficient credit history
  AA04 — Debt-to-income ratio too high
  AA05 — Application requires manual review

Input: a DecisionRequest dataclass with fraud_result, credit_result,
pricing_result, and raw application fields.

Output: a DecisionResult dataclass with:
  application_id, decision (APPROVE/REJECT/MANUAL_REVIEW),
  recommended_rate, loan_terms (dict), reason_codes (List[str]),
  decision_timestamp, decision_latency_ms

Write unit tests in decision_engine/tests/test_engine.py
covering all decision branches.
```

---

## Phase 5 — Explainability

### Prompt 9 — SHAP Explainability Module

```
Build an explainability module at `explainability/shap_explainer.py`.

Requirements:
- Load any scikit-learn or LightGBM model and a feature DataFrame.
- Compute SHAP values using the appropriate explainer (TreeExplainer for
  tree models, LinearExplainer otherwise).
- Expose explain_prediction(model, features_row_df) -> ExplanationResult
  dataclass with:
    top_positive_factors  (List[dict] with feature, shap_value, direction)
    top_negative_factors  (List[dict])
    base_value            (float)
    predicted_value       (float)
    explanation_text      (str) — human-readable summary for adverse action notice

- Generate and save a SHAP waterfall plot for a single prediction to a
  given output path.
- Explanation text format example:
    "Your application was [approved/declined] primarily due to:
     (+) High annual income (+0.12)
     (+) Low credit utilization (+0.08)
     (-) Short employment history (-0.05)"

Write unit tests using a small synthetic dataset and a dummy
RandomForestClassifier.

Also create explainability/lime_explainer.py with a
explain_with_lime(model, features_row, feature_names) -> dict
function as an alternative explainer.
```

---

## Phase 6 — Audit & Traceability

### Prompt 10 — Audit Logger

```
Build an audit logging module at `audit/logger.py`.

Requirements:
- Expose an async log_decision(decision_result, feature_version,
  model_versions, input_features, db_url) -> str (returns log_id)
- Write to the audit_log PostgreSQL table from Prompt 2.
- All fields from the PRD must be present:
  application_id, timestamp, input_features (JSONB), model_version,
  feature_version, fraud_score, risk_score, decision_output,
  reason_codes, decision_latency_ms
- PII masking: before writing, mask SSN (replace with SHA-256 hash),
  mask bank_account (last 4 digits only), hash customer_id.
- Implement an async get_audit_record(application_id, db_url)
  -> dict function for auditor replay.
- Write tests in audit/tests/test_logger.py using pytest-asyncio
  and SQLite in-memory.
```

---

## Phase 7 — API Layer

### Prompt 11 — Decision API (FastAPI)

```
Build a FastAPI decision service at `decision-api/src/main.py`
that orchestrates the full underwriting pipeline.

POST /v1/decisions
  Body: LoanApplication (reuse model from ingestion-api/src/models.py)
  Auth: Bearer JWT (reuse auth.py pattern from ingestion-api)

Pipeline steps (executed in order, total latency < 2 seconds):
  1. Validate input (Pydantic)
  2. Compute features (feature_pipeline.features.compute_features)
  3. Run fraud detection (models.fraud_detection.predict.predict_fraud)
  4. Run credit risk model (models.credit_risk.predict.predict_pd)
  5. Run pricing engine (models.pricing.engine.calculate_pricing)
  6. Run decision engine (decision_engine.engine.make_decision)
  7. Generate SHAP explanation (explainability.shap_explainer.explain_prediction)
  8. Write audit log (audit.logger.log_decision)
  9. Return DecisionResponse

DecisionResponse schema:
  application_id, decision, recommended_rate, loan_terms,
  reason_codes, explanation (top 3 factors), decision_latency_ms,
  audit_log_id

GET /v1/decisions/{application_id}/audit
  Returns the full audit record for regulators.

GET /v1/health  — returns model versions and DB status.

Add OpenAPI metadata, proper HTTP status codes (422 for validation,
200 for approve/reject, 202 for manual review).
Include a Dockerfile at decision-api/Dockerfile.
```

---

### Prompt 12 — Batch Scoring API

```
Extend decision-api with a batch scoring endpoint.

POST /v1/decisions/batch
  Body: List[LoanApplication] (max 1000)
  Processing: run the full pipeline for each application using
  asyncio.gather for concurrent model inference.
  Response: List[DecisionResponse] with a batch_summary object:
    total, approved, rejected, manual_review, avg_latency_ms

Also build a standalone CLI script at `scripts/batch_score.py`:
  - Accept --input (Parquet or CSV path) and --output (Parquet path)
  - Load applications, call the pipeline for each row
  - Write DecisionResponse fields to output Parquet
  - Print a summary table (rich library) with approval rate,
    avg risk score, avg rate, fraud flag count
  - Support --limit flag for testing on small subsets
```

---

## Phase 8 — Monitoring & Governance

### Prompt 13 — Model Drift Monitor

```
Build a drift monitoring module at `monitoring/drift_monitor.py`.

Requirements:
- Compare a reference feature distribution (training data) against
  a production batch using Population Stability Index (PSI) and
  Kolmogorov-Smirnov test.
- PSI formula: PSI = Σ (Actual% - Expected%) × ln(Actual% / Expected%)
  Thresholds: PSI < 0.1 → stable, 0.1–0.25 → minor shift,
              > 0.25 → major drift (alert)
- For each numeric feature compute PSI and KS p-value.
- Output a DriftReport dataclass with per-feature results and an
  overall drift_status (stable/minor/major).
- Expose monitor_drift(reference_df, production_df, feature_list)
  -> DriftReport.
- Save the drift report as JSON to monitoring/reports/.
- Write unit tests in monitoring/tests/test_drift_monitor.py.
```

---

### Prompt 14 — Fair Lending Monitor

```
Build a fair lending analysis module at `monitoring/fair_lending.py`.

Requirements:
Compute the following metrics from a DecisionResult DataFrame that
includes a demographic_group column (e.g., derived from geography/zip):

  Disparate Impact Ratio (DIR):
    DIR = Approval rate (protected group) / Approval rate (control group)
    Flag if DIR < 0.80 (4/5ths rule under ECOA/HMDA)

  Approval Parity:
    Chi-squared test for independence between demographic_group and decision.
    Flag if p-value < 0.05.

  Geographic Bias:
    Compare approval rates by state; flag states with rate > 1.5 standard
    deviations from the national mean.

Expose:
  analyze_fair_lending(decisions_df, protected_col, control_group)
    -> FairLendingReport dataclass with dir_score, dir_flag,
       approval_parity_p_value, geographic_flags (List[str]),
       summary_text

Save results to monitoring/reports/fair_lending_{date}.json.
Write unit tests with a synthetic decisions DataFrame.
```

---

### Prompt 15 — Risk Dashboard (Streamlit)

```
Build a Streamlit dashboard at `dashboard/app.py`.

Objective:
Deliver an enterprise-ready Streamlit dashboard suitable for executive, risk,
and compliance consumption. The UI must feel polished, consistent, and
presentation-quality (not a prototype).

Enterprise UX and design requirements:
- Use a professional visual system in `.streamlit/config.toml`:
  typography hierarchy, consistent spacing scale, neutral enterprise palette,
  status colors (success/warn/error), and compact KPI card styling.
- Add global filter controls in the sidebar: date range, product type,
  region/state, and decision status.
- Ensure responsive layouts for large laptop and standard monitor views.
- Add loading, empty-state, and error-state UI for every page.
- Use clear metric definitions and tooltips for non-obvious fields.

Required pages (sidebar navigation):

1. Portfolio Overview
  - KPI cards: total applications, approval rate, avg risk score, fraud rate
  - Time-series: daily approval rate (last 30 days)
  - Decision mix by product and by loan purpose
  - Source panel showing where each metric came from

2. Model Performance
  - AUC and KS KPI cards (from MLflow or governed metrics artifact)
  - ROC curve plot
  - Feature importance bar chart (top 10 SHAP values)
  - Model version + training window + metrics timestamp

3. Drift Monitor
  - Load drift reports from monitoring/reports/
  - Traffic-light table: green/yellow/red per feature
  - PSI trend line chart
  - Drill-through list of accounts/applications driving highest drift features

4. Fair Lending
  - DIR score gauge chart
  - Approval rate by state choropleth (plotly)
  - Approval parity p-value with PASS/FAIL badge
  - Segment table with product-level disparity breakdown

5. Audit Lookup
  - Text input for application_id
  - Calls GET /v1/decisions/{id}/audit and displays full audit record
  - Shows SHAP waterfall chart for that decision
  - Linked evidence panel (decision trace id, model version, policy version)

Data source transparency (mandatory):
- Every page must include a visible "Data Sources" section with:
  source system, dataset/table/file path, refresh timestamp, and owner.
- Add per-chart footnotes that map visualization -> query/source artifact.
- Add a data freshness indicator with warning when stale.

Drill-down requirements (mandatory):
- Implement hierarchical drill-down flow:
  portfolio -> product -> account/application.
- Product drill-down view must show risk, approval, delinquency, and volume
  trends by product family (e.g., BNPL, Personal Loan, SMB Loan).
- Account/application drill-down must include timeline, key decision factors,
  latest model outputs, and direct link to audit payload.
- Preserve filter context while drilling down and when navigating back.

Implementation constraints:
- Use plotly for all charts and `st.cache_data` for data-loading functions.
- Keep data adapters separate from presentation code.
- Avoid hardcoded/mock values in production paths; clearly label any demo data.

Testing and acceptance:
- Add tests for page rendering with empty and populated data.
- Add tests for filter behavior and drill-down state preservation.
- Add tests validating that data-source metadata is present for each page.
- Include a short "dashboard readiness" checklist in docs covering
  accessibility, performance, and source traceability.
```

---

## Phase 9 — Infrastructure & CI/CD

### Prompt 16 — MLflow Experiment Tracking Setup

```
Create an MLflow tracking setup at `mlflow/mlflow_config.py`.

Requirements:
- Configure MLflow to log to a local SQLite backend
  (mlflow/mlruns.db) for development and a specified remote URI
  for production (read from MLFLOW_TRACKING_URI env var).
- Create a ModelRegistry class with methods:
    register_model(model_name, model_path, metrics, params) -> version_str
    promote_model(model_name, version, stage)  # Staging → Production
    get_production_model(model_name) -> (model_object, metadata_dict)
    list_model_versions(model_name) -> List[dict]
- Add a governance check: promotion to Production requires
  'auc' >= 0.75 AND 'ks' >= 0.35 in logged metrics, else raise
  GovernanceError.
- Write unit tests using mlflow's in-memory tracking store.
```

---

### Prompt 17 — Docker Compose & Local Dev Stack

```
Create a docker-compose.yml at the project root that wires up
the full local development environment:

Services:
  postgres:
    image: postgres:16-alpine
    env: POSTGRES_DB=credit_risk, POSTGRES_USER, POSTGRES_PASSWORD
    volume: ./db/schema.sql → /docker-entrypoint-initdb.d/
    healthcheck: pg_isready

  mlflow:
    build from a minimal Python image
    command: mlflow server --backend-store-uri postgresql://...
             --default-artifact-root /mlflow/artifacts
    depends_on: postgres

  ingestion-api:
    build: ./ingestion-api
    env_file: .env
    depends_on: postgres
    ports: "8080:8080"

  decision-api:
    build: ./decision-api
    env_file: .env
    depends_on: postgres, mlflow
    ports: "8081:8081"

  dashboard:
    build: ./dashboard
    depends_on: decision-api
    ports: "8501:8501"

Add a .env.example with all required environment variables documented.
Add a Makefile target `make dev` that runs docker-compose up --build.
Add a Makefile target `make test` that runs pytest across all modules.
```

---

### Prompt 18 — CI/CD Pipeline (GitHub Actions)

```
Create GitHub Actions workflows at `.github/workflows/`.

1. ci.yml — triggered on push/PR to main:
   - Job: lint (ruff, black --check)
   - Job: test (pytest with coverage ≥ 80%, upload to Codecov)
   - Job: build (docker build ingestion-api and decision-api,
     push to GitHub Container Registry)

2. model-validation.yml — triggered manually or on schedule (weekly):
   - Checkout code
   - Set up Python + install deps
   - Run models/credit_risk/train.py on a 10k-row sample
   - Assert AUC > 0.75 and KS > 0.35
   - If passing, register model version in MLflow
   - Post results as a PR comment using GitHub script

3. deploy.yml — triggered on push to main after ci passes:
   - Deploy ingestion-api and decision-api to Cloud Run
     using gcloud CLI (parameterized by environment: staging/prod)
   - Run smoke tests (curl /health endpoints)
   - Notify Slack on failure

Use reusable workflows where logic is shared between jobs.
Store secrets in GitHub Secrets (POSTGRES_URL, GCP_SA_KEY, SLACK_WEBHOOK).
```

---

## Phase 10 — End-to-End Integration Test

### Prompt 19 — Integration Test Suite

```
Create a full end-to-end integration test suite at
`tests/integration/test_e2e_pipeline.py`.

Test scenarios (use pytest fixtures and the docker-compose stack):

1. test_happy_path_approve
   Submit a low-risk application (high income, low DTI, good credit score).
   Assert: decision == APPROVE, pd_score < 0.05, fraud_flag == continue,
   rate between 5–10%, audit record exists in DB.

2. test_high_risk_reject
   Submit a high-risk application (low credit score, high DTI).
   Assert: decision == REJECT, reason_codes contains AA01.

3. test_fraud_rejection
   Submit an application matching fraud heuristics (very low income,
   max loan, zero accounts).
   Assert: decision == REJECT or MANUAL_REVIEW, fraud_probability > 0.3.

4. test_audit_replay
   After test_happy_path_approve, call GET /v1/decisions/{id}/audit.
   Assert all required audit fields are present and non-null.

5. test_batch_scoring
   Submit a batch of 50 mixed-risk applications.
   Assert: response contains 50 results, latency < 10 seconds total,
   at least one APPROVE and one REJECT.

6. test_latency_slo
   Submit 100 applications concurrently using asyncio.gather.
   Assert p95 latency < 2000ms.

Use httpx.AsyncClient, pytest-asyncio, and a shared postgres fixture
that rolls back transactions after each test.
```

---

## Phase 11 — UI: Applicant-Facing Portal

### Prompt 20 — Loan Application Portal (Next.js)

```
Build a customer-facing loan application portal at `ui/applicant-portal/`
using Next.js 14 (App Router), TypeScript, Tailwind CSS, and shadcn/ui.

Pages and routes:

1. / (Landing)
   - Hero section: headline, CTA button "Check Your Rate"
   - Three benefit cards: Fast Decision, Transparent Pricing, Secure
   - Footer with regulatory disclaimer text

2. /apply (Multi-step Application Form)
   Step 1 — Loan Details
     - Loan amount slider (1,000–100,000) with live monthly payment estimate
     - Loan purpose dropdown (personal/auto/home_improvement/medical/
       education/debt_consolidation)
     - Loan term radio group (12/24/36/48/60 months)

   Step 2 — Personal & Financial Info
     - Annual income (number input with $ formatting)
     - Employment status (select)
     - Employer tenure months (number input, shown only if employed/self-employed)
     - Credit score range (dropdown: Excellent 750+, Good 700–749,
       Fair 650–699, Poor <650) — maps to numeric midpoint for API call
     - Debt-to-income ratio (auto-calculated from income + existing debt fields)
     - Existing debt amount (number input)

   Step 3 — Review & Submit
     - Summary card of all entered values
     - Checkbox: consent to credit check
     - Submit button — calls POST /v1/decisions via the decision-api

3. /decision (Result Page)
   Rendered after submit, receives DecisionResponse:
   - APPROVE: green banner, approved amount, recommended rate, monthly
     payment, loan term, "Next Steps" CTA
   - REJECT: red banner, reason codes translated to human-readable text
     using a reasons map, link to dispute process
   - MANUAL_REVIEW: amber banner, "Your application is under review",
     expected timeline
   - Show top 3 SHAP explanation factors (icons + text)

4. /status/:application_id (Application Status Tracker)
   - Timeline component showing: Submitted → Under Review → Decision
   - Polls GET /v1/decisions/{id}/audit every 5 seconds until resolved

Form state management: React Hook Form + Zod validation schemas.
API calls: use a typed API client generated from the OpenAPI spec
(openapi-typescript-codegen).
Accessibility: WCAG 2.1 AA — label all inputs, keyboard navigation,
focus management between steps.
Add a Storybook at ui/applicant-portal/.storybook/ with stories for
each form step and the result page variants.
```

---

### Prompt 21 — Applicant Portal API Client & Auth

```
Add authentication and a typed API client to the applicant portal.

Authentication:
- Use NextAuth.js v5 with two providers:
    1. Credentials provider (email + OTP sent via email)
    2. Google OAuth (optional, feature-flagged)
- Store session in a JWT cookie; include application_ids array so
  applicants can see their own history.
- Protect /decision and /status routes with middleware.

Typed API client:
- Generate a TypeScript client from the decision-api OpenAPI schema at
  `ui/applicant-portal/src/lib/api-client.ts` using fetch.
- Wrap every call in a Result<T, ApiError> type (no thrown errors).
- Add request/response interceptors: attach Bearer token, log
  response latency to console in dev.

Form persistence:
- Auto-save form state to sessionStorage on each step so users
  don't lose progress on accidental navigation.
- Clear sessionStorage on successful submission.

Add unit tests for the Zod validation schemas in
ui/applicant-portal/src/__tests__/apply-form.test.ts using Vitest.
```

---

## Phase 12 — UI: Role-Based Analytics Dashboards (React)

### Prompt 22 — Dashboard Shell & Role-Based Routing

```
Create a shared analytics dashboard shell at `ui/analytics-dashboard/`
using Next.js 14, TypeScript, Tailwind CSS, and shadcn/ui.

Roles and their access:
  underwriter     — Application review queue, individual decision details
  risk_analyst    — Model performance, credit risk metrics, portfolio health
  compliance      — Fair lending, audit log explorer, adverse action reports
  data_scientist  — Model drift, feature distributions, training data stats
  executive       — High-level KPI summary, portfolio P&L, trend charts

Authentication:
- Reuse NextAuth.js; read role from JWT claims.
- Implement a RoleGuard component that redirects unauthorized
  users to /unauthorized.
- Sidebar nav dynamically renders only links the current role can access.

Shell layout:
- Left sidebar (collapsible): logo, nav links, role badge, user avatar
- Top bar: global date-range picker (last 7/30/90 days, custom),
  notification bell (alerts from drift monitor), dark/light mode toggle
- Main content area with breadcrumb

Create a shared hooks package at ui/analytics-dashboard/src/hooks/:
  useDecisionsData(dateRange) — fetches aggregated decision stats
  useModelMetrics()          — fetches latest MLflow metrics
  useDriftReport()           — fetches latest drift report JSON
  useFairLendingReport()     — fetches latest fair lending JSON

All hooks use SWR with a 60-second revalidation interval.
```

---

### Prompt 23 — Underwriter Dashboard

```
Build the Underwriter role dashboard at
`ui/analytics-dashboard/src/app/underwriter/`.

Pages:

1. /underwriter/queue (Application Review Queue)
   - Data table (TanStack Table v8) of MANUAL_REVIEW applications:
     columns: application_id, submitted_at, loan_amount, credit_score,
     pd_score, fraud_probability, status, actions
   - Column filters: date range, loan amount range, pd_score range
   - Sortable by all numeric columns
   - "Review" button opens a slide-over panel (shadcn Sheet)

2. /underwriter/queue/:id (Application Detail Slide-over)
   Content:
   - Applicant summary card: loan amount, purpose, term, income, DTI
   - Risk score gauge (0–1 scale, color-coded green/amber/red)
   - Fraud score gauge
   - SHAP waterfall chart (embed as SVG from the explainability endpoint)
   - Reason codes with human-readable descriptions
   - Audit timeline (all events for this application)
   - Action buttons: APPROVE / REJECT / REQUEST_MORE_INFO
     Clicking calls a PATCH /v1/decisions/{id}/manual-override endpoint
     and requires a free-text notes field (required, min 20 chars)

3. /underwriter/history
   - Same table but for completed decisions the underwriter acted on
   - Export to CSV button

Add keyboard shortcut a = approve, r = reject in the slide-over.
```

---

### Prompt 24 — Risk Analyst Dashboard

```
Build the Risk Analyst role dashboard at
`ui/analytics-dashboard/src/app/risk-analyst/`.

Pages:

1. /risk-analyst/portfolio (Portfolio Health)
   - KPI cards: total active loans, avg PD score, expected loss ($),
     default rate (%), approval rate (%)
   - Stacked area chart: weekly application volume by decision outcome
   - Scatter plot: loan_amount vs pd_score, colored by decision,
     with loan_purpose as shape
   - Vintage analysis table: cohort (month of origination) vs
     cumulative default rate at 3/6/12/18 months

2. /risk-analyst/credit-risk (Credit Risk Deep Dive)
   - PD score distribution histogram (binned 0–1 in 0.05 buckets)
   - Box plots: PD score by loan_purpose and by employment_status
   - Correlation heatmap: all numeric features vs default_flag
   - KS curve chart showing separation between default and non-default
     score distributions

3. /risk-analyst/model-performance (Model Metrics)
   - ROC curve with AUC annotation
   - Precision-Recall curve
   - Confusion matrix heatmap
   - Metric trend line: AUC over last 12 model versions (from MLflow)
   - Feature importance bar chart (top 15 SHAP mean |values|)
   - SLO gauges: AUC ≥ 0.75 ✓/✗, KS ≥ 0.35 ✓/✗, Latency < 2s ✓/✗

Use Recharts for all charts. Load chart data from dedicated
GET /v1/analytics/* endpoints (build stubs returning mock data if
not yet implemented).
```

---

### Prompt 25 — Compliance Dashboard

```
Build the Compliance role dashboard at
`ui/analytics-dashboard/src/app/compliance/`.

Pages:

1. /compliance/fair-lending
   - DIR gauge chart: large dial showing current DIR, threshold line at 0.80,
     color: green ≥ 0.80, red < 0.80
   - Approval rate by demographic group bar chart (side-by-side)
   - Approval rate by state choropleth map (react-simple-maps or
     a Plotly iframe from the Streamlit dashboard endpoint)
   - Approval parity chi-squared result card with PASS/FAIL badge
   - "Download HMDA Report" button — calls GET /v1/reports/hmda
     returns a CSV

2. /compliance/adverse-actions
   - Table of all REJECT decisions with reason codes
   - Filters: date range, reason code, state
   - "Generate Adverse Action Notice" button per row — renders a
     printable PDF using react-pdf/renderer with the applicant's
     name, decision date, reason codes translated to FCRA-compliant
     plain English, and lender contact information

3. /compliance/audit-explorer
   - Search bar: lookup by application_id
   - Full audit record display: all fields from the audit_log table
     in a structured key-value layout
   - "Replay Decision" button: re-runs the decision using stored
     input_features and model_version — calls POST /v1/decisions/replay
   - Export full audit trail to JSON button

4. /compliance/model-governance
   - Model registry table: model_name, version, status, approved_by,
     approved_at, AUC, KS
   - Status badges: Candidate (gray), Approved (green), Deprecated (red)
   - "Approve Model" button (compliance role only) with confirmation dialog
```

---

### Prompt 26 — Data Scientist Dashboard

```
Build the Data Scientist role dashboard at
`ui/analytics-dashboard/src/app/data-scientist/`.

Pages:

1. /data-scientist/drift (Model & Feature Drift)
   - Traffic-light table: each feature row with PSI value, KS p-value,
     color-coded: green (stable), amber (minor), red (major drift)
   - PSI trend sparkline per feature (last 30 days)
   - Overall drift status banner at top with last-checked timestamp
   - "Trigger Retraining" button — calls POST /v1/models/retrain
     (protected; requires 2-factor confirmation dialog)

2. /data-scientist/feature-analysis
   - Feature distribution viewer: select a feature from a dropdown,
     renders overlaid histograms for training vs recent production data
   - Feature correlation matrix heatmap (all engineered features)
   - Missing value heatmap across recent production batches
   - Feature importance change over model versions (grouped bar chart)

3. /data-scientist/experiments (MLflow Experiment Browser)
   - Table of all MLflow runs with metrics (AUC, KS, F1, precision, recall)
   - Run comparison: select 2 runs → side-by-side metric diff table
   - Click a run → detail page with all logged params, metrics, artifacts
   - "Promote to Staging" button — calls the ModelRegistry.promote_model API
     with governance check response displayed inline

4. /data-scientist/data-quality
   - Schema validation results from the last ingestion batch
   - Anomaly detection flags from the ingestion API
   - Data completeness score per field (% non-null) as a horizontal bar
   - Outlier count per numeric feature (values > 3σ from mean)
```

---

### Prompt 27 — Executive Dashboard

```
Build the Executive role dashboard at
`ui/analytics-dashboard/src/app/executive/`.

Single-page layout with sections (no sub-pages; designed for
a large monitor or TV display):

KPI Row (top):
  - Applications Today | This Month | YTD (with % change vs prior period)
  - Approval Rate (%) with sparkline trend
  - Portfolio Expected Loss ($M) with trend arrow
  - Avg Decision Latency (ms) with SLO badge

Section 1 — Business Performance
  - Line chart: daily application volume + approval rate overlay (dual axis)
  - Donut chart: revenue breakdown by loan purpose
  - Bar chart: approved loan amount by state (top 10)

Section 2 — Risk Snapshot
  - Gauge: portfolio weighted average PD score
  - Heat map calendar: default events in last 12 months (GitHub-style)
  - Trend line: fraud detection rate over last 90 days

Section 3 — Compliance Health
  - DIR score card with trend (last 6 months)
  - Model governance status: N models approved, N pending, N deprecated
  - Last audit date and next scheduled review

Section 4 — Operational Health
  - API uptime % (last 30 days)
  - P95 decision latency trend
  - Error rate trend

Add a "Download Board Report" button that generates a PDF summary
of all KPIs using react-pdf/renderer, formatted as an executive
briefing document with date, charts as embedded images (html2canvas),
and a written summary paragraph.

Auto-refresh the entire page every 5 minutes using SWR's
refreshInterval option.
```

---

## Phase 13 — Internal AI Agent

### Prompt 28 — AI Agent Backend (LangChain + FastAPI)

```
Build an internal AI analyst agent at `ai-agent/src/main.py`
using LangChain, FastAPI, and an LLM backend (OpenAI GPT-4o by
default; configurable via AGENT_LLM_PROVIDER env var to support
Anthropic Claude or local Ollama).

The agent has two personas (selectable per request):
  data_analyst   — answers data/metrics questions, writes SQL, builds charts
  business_analyst — generates reports, interprets trends, gives recommendations

Tools available to the agent (implement each as a LangChain Tool):

  sql_query_tool
    - Input: natural language question
    - Action: translate to SQL using the DB schema context, execute
      against PostgreSQL read replica, return results as markdown table
    - Schema context: load db/schema.sql into the system prompt

  metrics_tool
    - Input: metric name + date range
    - Action: query pre-aggregated analytics endpoints (GET /v1/analytics/*)
    - Returns: JSON metrics data

  drift_report_tool
    - Input: (none or feature name)
    - Action: load latest drift report from monitoring/reports/
    - Returns: structured drift summary

  fair_lending_tool
    - Input: (none or demographic group)
    - Action: load latest fair lending report
    - Returns: DIR score + flag status + recommendations

  chart_generator_tool
    - Input: chart_type (bar/line/scatter/histogram), data (JSON),
      x_col, y_col, title
    - Action: generate a Plotly figure, save to a temp file,
      return a signed URL to the file
    - Supported chart types: bar, line, scatter, histogram, heatmap

  report_generator_tool
    - Input: report_type (portfolio_summary/model_performance/
      fair_lending_summary/executive_briefing), date_range
    - Action: gather data from multiple tools, assemble a structured
      Markdown report with sections, charts, and recommendations
    - Returns: Markdown string + list of chart URLs

Agent endpoints:

  POST /v1/agent/chat
    Body: { persona: "data_analyst"|"business_analyst",
            message: str, session_id: str, context?: dict }
    Response: { reply: str, charts: List[str], sql_used?: str,
                tool_calls: List[str] }
    Streams response using Server-Sent Events for real-time typing effect.

  POST /v1/agent/report
    Body: { report_type: str, date_range: { start, end }, format: "markdown"|"pdf" }
    Response: { report_markdown: str, pdf_url?: str, charts: List[str] }

  GET /v1/agent/sessions/{session_id}/history
    Returns full conversation history for a session.

Conversation memory: use LangChain ConversationSummaryBufferMemory
with a 4000-token limit per session, persisted to PostgreSQL
(add an agent_sessions table to the schema).

System prompt for data_analyst persona:
  "You are an expert data analyst for a credit risk lending platform.
   You have access to loan application data, model metrics, and
   feature engineering outputs. You answer questions precisely using
   data, write clean SQL when needed, and produce clear charts.
   Always cite the data source and time range in your answers."

System prompt for business_analyst persona:
  "You are a senior business analyst for a credit risk lending platform.
   You interpret data trends, identify business risks and opportunities,
   write executive-ready reports, and make actionable recommendations
   grounded in the data. Use plain language and structure answers as
   briefings with: Key Finding → Supporting Data → Recommendation."

Add rate limiting: 60 requests/minute per session using slowapi.
Add a Dockerfile at ai-agent/Dockerfile.
```

---

### Prompt 29 — AI Agent Chat UI (React)

```
Build an AI agent chat interface at
`ui/analytics-dashboard/src/app/agent/` accessible to all
authenticated roles.

Layout:
- Two-panel layout: left sidebar (conversation history list),
  right main chat area
- Top bar: persona selector toggle (Data Analyst / Business Analyst),
  new conversation button, export conversation button

Chat area:
- Message bubbles: user messages right-aligned (blue), agent
  messages left-aligned (white/gray)
- Agent messages support full Markdown rendering (react-markdown
  with remark-gfm for tables)
- Inline chart rendering: if the agent response contains a chart URL,
  render an <img> tag with a zoom-on-click modal (shadcn Dialog)
- SQL display: if the response contains sql_used, render it in a
  collapsible <details> block with syntax highlighting (Prism.js)
- Streaming: connect to the SSE endpoint and render tokens in
  real-time as they arrive (use EventSource API)
- Typing indicator: animated dots while agent is processing

Input area:
- Textarea (auto-grow, max 6 rows)
- Send button (disabled while streaming)
- Suggested prompt chips below input that change based on active role:
    data_analyst chips:
      "Show approval rate trend last 30 days"
      "What is the current portfolio default rate?"
      "Compare PD score distributions by loan purpose"
      "Are there any features showing major drift?"
    business_analyst chips:
      "Generate a monthly portfolio summary report"
      "What are the top risks in the current portfolio?"
      "Summarize fair lending compliance status"
      "Give me an executive briefing for this week"

Report panel:
- When the agent generates a report (via report_generator_tool),
  display it in a slide-over panel (shadcn Sheet) with:
  - Rendered Markdown with a table of contents
  - Embedded charts
  - "Download PDF" button (calls the report endpoint with format=pdf)
  - "Share" button — copies a shareable link with the session_id

Add unit tests for the chat component in
ui/analytics-dashboard/src/__tests__/agent-chat.test.tsx using
Vitest and React Testing Library.
```

---

### Prompt 30 — Automated Reporting & Scheduled Insights

```
Build a scheduled reporting service at `ai-agent/src/scheduler.py`
using APScheduler.

Scheduled jobs:

1. Daily Portfolio Summary (runs 7:00 AM weekdays)
   - Calls POST /v1/agent/report with report_type="portfolio_summary"
   - Sends the report via email using SendGrid to the executive
     and risk_analyst role distribution list
   - Saves report to PostgreSQL (add a reports table)

2. Weekly Model Health Report (runs Monday 8:00 AM)
   - Calls the drift monitor, fair lending, and model performance tools
   - Assembles a comprehensive weekly model health report
   - Emails to data_scientist and compliance roles
   - Posts a Slack message with a summary and link to the full report

3. Monthly Fair Lending Report (runs 1st of each month)
   - Runs fair_lending_tool for the prior month
   - Generates a full fair lending compliance report with DIR,
     approval parity results, and geographic analysis
   - Emails to compliance role

4. Real-time Alert (triggered by the drift monitor)
   - If drift_status == "major", immediately:
     a. Create an in-app notification (POST /v1/notifications)
     b. Send a Slack alert to #model-monitoring channel
     c. Email the data_scientist role
   - Alert message template:
     "ALERT: Major feature drift detected in {feature_name}.
      PSI = {psi_value:.3f}. Immediate review recommended."

Notification persistence:
  - Add a notifications table to the DB (id, role, message, read,
    created_at, metadata JSONB)
  - Add GET /v1/notifications (returns unread for current user) and
    PATCH /v1/notifications/{id}/read endpoints to the decision-api
  - The dashboard notification bell polls this endpoint every 30 seconds

Configuration:
  - All schedules configurable via environment variables
  - All email recipients configurable via a YAML config file at
    ai-agent/config/notification_config.yaml
  - Add a manual trigger endpoint POST /v1/agent/reports/trigger
    for ad-hoc report generation

Add unit tests for the scheduler job functions using pytest and
freezegun for time manipulation.
```

---

## Appendix — Suggested Build Order

| # | Prompt | Depends On |
|---|--------|-----------|
| 1 | Synthetic Dataset | — |
| 2 | DB Schema | — |
| 3 | Feature Engineering | 1 |
| 4 | Feature Store Writer | 2, 3 |
| 5 | Fraud Detection Model | 1, 3 |
| 6 | Credit Risk Model | 1, 3 |
| 7 | Pricing Engine | 6 |
| 8 | Decision Engine | 5, 6, 7 |
| 9 | SHAP Explainability | 5, 6 |
| 10 | Audit Logger | 2, 8 |
| 11 | Decision API | 3–10 |
| 12 | Batch Scoring | 11 |
| 13 | Drift Monitor | 1, 6 |
| 14 | Fair Lending Monitor | 11 |
| 15 | Streamlit Dashboard (dev) | 11, 13, 14 |
| 16 | MLflow Setup | 5, 6 |
| 17 | Docker Compose | all |
| 18 | CI/CD | all |
| 19 | Integration Tests | all |
| 20 | Loan Application Portal | 11 |
| 21 | Portal Auth & API Client | 20 |
| 22 | Dashboard Shell & Routing | 11 |
| 23 | Underwriter Dashboard | 22 |
| 24 | Risk Analyst Dashboard | 22 |
| 25 | Compliance Dashboard | 22, 14 |
| 26 | Data Scientist Dashboard | 22, 13, 16 |
| 27 | Executive Dashboard | 22–26 |
| 28 | AI Agent Backend | 11, 13, 14 |
| 29 | AI Agent Chat UI | 22, 28 |
| 30 | Scheduled Reporting | 28, 29 |
