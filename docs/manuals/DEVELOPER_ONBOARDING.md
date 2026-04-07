# Developer Onboarding Manual
## Credit Risk Platform — `credit-risk-platform`

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: New backend engineers joining the platform team — zero prior codebase knowledge required
> Cross-references: `docs/TECHNICAL_ARCHITECTURE.md`, `docs/IMPLEMENTATION_PLAN_CORE_PLATFORM_2026_04_07.md`

---

## 1. Local Development Setup

### Prerequisites

| Tool | Minimum Version | Install Guide |
|---|---|---|
| Python | 3.11+ | `brew install python@3.11` or [python.org](https://python.org) |
| Docker Desktop | Latest stable | [docker.com/get-docker](https://docker.com/get-docker) |
| Docker Compose | v2.x (bundled with Docker Desktop) | Included with Docker Desktop |
| `gcloud` CLI | Latest | `brew install google-cloud-sdk` |
| Node.js + npm | 18+ (for UI work) | `brew install node` |
| `make` | Pre-installed on macOS/Linux | — |

---

### Step 1 — Clone and Bootstrap

```bash
git clone https://github.com/your-org/credit-risk-platform.git
cd credit-risk-platform

# Full first-run setup: creates venv, installs all Python + Node deps, copies .env, trains models
make bootstrap
```

`make bootstrap` runs the following in sequence:
1. `make venv` — creates `.venv/`
2. `pip install -r requirements.txt` — installs all Python dependencies
3. `make install-agent` — installs AI agent dependencies (`ai-agent/requirements.txt`)
4. `make npm-install` — installs Node deps for both Next.js UIs
5. `cp .env.example .env` — creates your local env file (fill in secrets before running live services)
6. `make train-all` — trains XGBoost PD + Fraud Isolation Forest models and registers them in local MLflow

---

### Step 2 — Environment Variables

Open `.env` (created from `.env.example`) and fill in the following:

| Variable | Purpose | Where to Get It | Safe Local Default |
|---|---|---|---|
| `POSTGRES_USER` | Postgres username | — | `credit_user` |
| `POSTGRES_PASSWORD` | Postgres password | — | `changeme` |
| `JWT_SECRET` | Token signing secret | Generate with `openssl rand -hex 32` | `dev-secret-change-me` |
| `GCS_BUCKET_NAME` | GCS bucket for raw ingestion | GCP Console → Storage | `local-mock` (ingestion API skips GCS write locally) |
| `PUBSUB_TOPIC` | Pub/Sub topic for ingestion events | GCP Console → Pub/Sub | `local-mock` (skips publish locally) |
| `BQ_DATASET` | BigQuery dataset for analytics sink | GCP Console → BigQuery | Leave empty to disable BQ write locally |
| `MLFLOW_TRACKING_URI` | MLflow server URI | — | `http://localhost:5000` |
| `DATABASE_URL` | Audit DB connection string | — | `sqlite:///./audit.db` |
| `LOANS_DB_URL` | Loans Postgres connection string | Compose service at port 5432 | `postgresql://credit_user:changeme@localhost:5432/credit_risk_loans` |
| `CARDS_DB_URL` | Credit Cards Postgres | Compose service at port 5434 | `postgresql://credit_user:changeme@localhost:5434/credit_risk_cards` |
| `TRANSACTIONS_DB_URL` | Transactions Postgres | Compose service at port 5433 | `postgresql://credit_user:changeme@localhost:5433/credit_risk_transactions` |
| `REDIS_URL` | Redis connection | Compose service at port 6379 | `redis://localhost:6379` |

> **Do not commit `.env` to git.** It is already in `.gitignore`.

---

### Step 3 — Start All Services

```bash
# Start all services (builds Docker images first)
make dev

# Or start in background (detached)
make dev-detach

# View service logs
make logs
```

**Services and ports after `make dev`:**

| Service | Port | Description |
|---|---|---|
| Postgres (Loans DB) | 5432 | Loan applications, funded loans, customers |
| Postgres (Transactions DB) | 5433 | Bank accounts, payments, fraud events |
| Postgres (Cards DB) | 5434 | Credit card accounts, transactions, statements |
| Redis | 6379 | Cache / rate-limit store (provisioned, rate limiting not yet active) |
| MLflow | 5000 | Model tracking UI + artifact registry |
| Ingestion API | 8080 | Data ingestion FastAPI service |
| Decision API | 8081 | Underwriting engine FastAPI service |
| AI Agent | 8082 | LangChain AI agent (FastAPI + SSE) |
| Streamlit Dashboard | 8501 | Legacy analytics dashboard (mock data) |
| Applicant Portal (Next.js) | 3000 | Customer-facing loan application UI |
| Analytics Dashboard (Next.js) | 3001 | Internal analytics UI |

---

### Step 4 — Running the Decision API Locally

Generate a development JWT token:

```bash
# Generate a test JWT with tenant_id claim
python generate_token.py --tenant-id acme-bank --environment dev
# Outputs: Bearer eyJ...
```

Submit a single credit decision:

```bash
curl -X POST http://localhost:8081/v1/decisions/single \
  -H "Authorization: Bearer <YOUR_JWT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "application_id": "APP-TEST-001",
    "annual_income": 85000,
    "loan_amount": 25000,
    "credit_score": 720,
    "employment_status": "employed",
    "existing_debt": 12000,
    "loan_purpose": "home_improvement",
    "dti": 0.28,
    "months_employed": 36,
    "num_open_accounts": 4
  }'
```

Expected response shape:

```json
{
  "application_id": "APP-TEST-001",
  "decision": "APPROVE",
  "risk_tier": "PRIME",
  "pd_score": 0.042,
  "fraud_score": 0.08,
  "reason_codes": ["R01", "R04"],
  "shap_explanation": {"annual_income": 0.31, "credit_score": 0.28, "dti": -0.18},
  "request_id": "req-uuid-here",
  "model_version": "1.0.0"
}
```

---

### Step 5 — Running the Agent Pipeline Locally

```bash
# Activate venv
source .venv/bin/activate

# Run the full agent pipeline against a sample file
python -c "
from orchestration.pipeline import CreditRiskPipeline
import asyncio, json

pipeline = CreditRiskPipeline()
sample = [{
    'application_id': 'APP-LOCAL-001',
    'annual_income': 75000,
    'loan_amount': 20000,
    'credit_score': 690,
    'employment_status': 'employed',
    'existing_debt': 9000,
    'dti': 0.32
}]
result = asyncio.run(pipeline.run(sample))
print(json.dumps(result, indent=2, default=str))
"
```

---

### Step 6 — Running Tests

```bash
# Run all tests
make test
# or directly:
.venv/bin/pytest tests/ -v

# Run a specific test file
.venv/bin/pytest tests/test_decision_parity.py -v

# Run with coverage report
.venv/bin/pytest tests/ --cov=. --cov-report=html

# Run only fast (no integration) tests
.venv/bin/pytest tests/ -m "not integration" -v
```

Expected output on a clean checkout: all tests pass except integration tests that require live GCP services (skipped with `pytest.mark.integration`).

---

## 2. Codebase Navigation Guide

### Top-Level Directory Map

| Directory | Purpose |
|---|---|
| `decision-api/` | Decision API FastAPI service (Cloud Run) — entry point `src/main.py` |
| `ingestion-api/` | Ingestion API FastAPI service (Cloud Run) — entry point `src/main.py` |
| `agents/` | Multi-agent pipeline components (`feature_engineering_agent.py`, `decision_engine_agent.py`, etc.) |
| `orchestration/` | Agent pipeline coordinator (`pipeline.py`) and message bus |
| `feature_pipeline/` | **Canonical** feature engineering library (`features.py`, `feature_store.py`, `lineage.py`) |
| `decision_engine/` | **Canonical** policy evaluation (`engine.py`, `policy_dsl.py`, `policy_version_store.py`) |
| `models/` | Model inference wrappers (`credit_risk/`, `fraud_detection/`, `pricing/`) |
| `audit/` | Append-only audit logger (`logger.py`) |
| `compliance/` | CFPB/fair-lending rules, RBAC, model docs, HMDA reporting |
| `schemas/` | Pydantic v2 contracts for inter-service data exchange (`contracts.py`) |
| `db/` | ORM models, BigQuery schema, SQL migration scripts |
| `config/` | Global YAML config (`agent_config.yaml`) — per-tenant config is planned (P3.2) |
| `scripts/` | Operational scripts: batch scoring, fairness checks, MRM lifecycle, data loading |
| `tests/` | Full test suite (unit, integration, golden) |
| `ui/` | Next.js frontend apps (`applicant-portal/`, `analytics-dashboard/`) |
| `dashboard/` | Streamlit dashboard (`app.py`) — currently mock data |
| `docs/` | Architecture docs, business assets, implementation plans, manuals |
| `ai-agent/` | LangChain-based AI agent service |
| `monitoring/` | Model drift and performance monitoring utilities |
| `reporting/` | HMDA and portfolio reporting |
| `mlflow_config/` | MLflow server configuration |
| `data/` | Local sample data for development and testing |

---

### "Start Here for X" Quick Reference

| If you need to... | Start at... |
|---|---|
| Add a new credit feature | `feature_pipeline/features.py` → then update `tests/feature_pipeline/` |
| Add a new policy rule | `decision_engine/policy_dsl.py` → `config/agent_config.yaml` (DSL format, NOT eval) |
| Add a new API endpoint | `decision-api/src/main.py` → `schemas/contracts.py` (schema first) |
| Add a new model | `models/credit_risk/predict.py` pattern → register in MLflow |
| Modify audit logging | `audit/logger.py` → run `tests/audit/test_tenant_isolation.py` |
| Understand data schemas | `schemas/contracts.py` |
| Understand BigQuery tables | `db/bigquery_schema.py` |
| Run a fairness check | `scripts/run_fairness_check.py` (planned — check current status) |
| Generate model documentation | `compliance/generate_model_doc.py` |
| Check compliance RBAC | `compliance/rbac.py` |
| Debug a pipeline decision | Start at `orchestration/pipeline.py` → follow the agent chain |
| Run batch scoring | `scripts/batch_score.py` |

---

### Where NOT to Add Code (Anti-Patterns)

> **STOP: Do not add feature logic to `agents/feature_engineering_agent.py`**
> This file is a duplicate of `feature_pipeline/features.py`. Any new feature added here will NOT be available in the Decision API path, meaning two channels will produce different results — a regulatory violation. Tracked as P0.2 for removal.

> **STOP: Do not add policy logic to `agents/decision_engine_agent.py`**
> This file uses `eval()` for rule evaluation and is a duplicate of `decision_engine/engine.py`. Adding rules here does not make them auditable. Tracked as P0.3 for removal.

> **STOP: Do not use `eval()` or `exec()` anywhere in this codebase**
> The safe DSL in `decision_engine/policy_dsl.py` exists for exactly this purpose. Use it.

> **STOP: Do not write to the audit log without `tenant_id` after P0.1 is merged**
> Tenantless audit writes will fail CI after the P0.1 guard is in place.

---

## 3. Making Your First Contribution

### 3a — Adding a New Credit Feature

1. **Define the feature function** in `feature_pipeline/features.py`:
   ```python
   def compute_payment_to_income_ratio(df: pd.DataFrame) -> pd.Series:
       """Monthly payment as a fraction of monthly income."""
       return (df["monthly_payment"] / (df["annual_income"] / 12)).clip(0, 1)
   ```

2. **Add it to `compute_feature_matrix()`** in the same file under the appropriate feature group.

3. **Update the feature contract** in `schemas/contracts.py`:
   ```python
   class FeatureVector(BaseModel):
       ...
       payment_to_income_ratio: float = Field(ge=0, le=1)
   ```

4. **Write a unit test** in `tests/feature_pipeline/test_features.py`:
   ```python
   def test_payment_to_income_ratio():
       df = pd.DataFrame({"monthly_payment": [500], "annual_income": [60000]})
       result = compute_payment_to_income_ratio(df)
       assert abs(result.iloc[0] - 0.1) < 1e-6
   ```

5. **Update the golden test**: run `tests/test_decision_parity.py` to confirm the new feature doesn't break parity between the Decision API path and the agent path. If it does, fix the agent path to use `credit_core` (P0.2 work).

---

### 3b — Adding a New Policy Rule

> ⚠️ **Use the safe DSL only.** Never use Python expressions in YAML that would require `eval()`.

1. **Add the rule to `config/agent_config.yaml`** using the DSL format:
   ```yaml
   hard_rules:
     - rule_id: HR-009
       description: "Auto-decline if payment-to-income ratio exceeds 50%"
       condition:
         field: payment_to_income_ratio
         op: ">"
         value: 0.50
       outcome: DECLINE
       reason_code: R09
   ```

2. **Validate the rule** passes the DSL parser:
   ```python
   from decision_engine.policy_dsl import evaluate_rule
   rule = {"field": "payment_to_income_ratio", "op": ">", "value": 0.50}
   result = evaluate_rule(rule, {"payment_to_income_ratio": 0.55})
   assert result is True
   ```

3. **Write a test** in `tests/test_policy_dsl.py`:
   ```python
   def test_pti_decline_rule():
       assert evaluate_rule({"field": "pti", "op": ">", "value": 0.5}, {"pti": 0.6}) is True
   ```

4. **Confirm forbidden syntax is rejected**:
   ```python
   # This must raise PolicyDSLError
   evaluate_rule({"field": "__import__('os').system('ls')", "op": "=", "value": 1}, {})
   ```

---

### 3c — Adding a New API Endpoint (Decision API Pattern)

Pattern: **route → schema → service function → audit log**

1. **Define the request/response schema** in `schemas/contracts.py` (Pydantic v2):
   ```python
   class PolicyRuleRequest(BaseModel):
       rule_id: str
       tenant_id: str  # will come from JWT in production

   class PolicyRuleResponse(BaseModel):
       rule_id: str
       active: bool
       version: str
   ```

2. **Add the route** in `decision-api/src/main.py`:
   ```python
   @app.get("/v1/policy/rules/{rule_id}", response_model=PolicyRuleResponse)
   async def get_policy_rule(rule_id: str, tenant_id: str = Depends(get_tenant_from_jwt)):
       ...
   ```

3. **Write the service function** — keep business logic out of the route handler.

4. **Log to audit** (all state-changing operations must log):
   ```python
   await audit_logger.log_policy_access(tenant_id=tenant_id, rule_id=rule_id, action="read")
   ```

5. **Write an integration test** in `tests/integration/`.

---

## 4. Testing Philosophy

### Test Structure

| Test Type | Location | What It Tests |
|---|---|---|
| Unit tests | `tests/<module>/` (mirrors source) | Individual functions in isolation |
| Golden tests | `tests/test_decision_parity.py` | API path == agent path for identical input |
| DSL safety tests | `tests/test_policy_dsl.py` | Safe DSL accepts/rejects correct expressions |
| Tenant isolation tests | `tests/audit/test_tenant_isolation.py` | Tenant A cannot read Tenant B's audit records |
| Integration tests | `tests/integration/` | Full service interactions; require live services |
| Feature pipeline tests | `tests/feature_pipeline/` | Feature computation correctness + PIT |

---

### Golden Test: `tests/test_decision_parity.py`

This is the **most important test in the codebase**. It asserts that for a fixed set of N sample applicants:

- Decision API path (via `feature_pipeline/features.py` + `decision_engine/engine.py`)
- Agent orchestrator path (via `agents/feature_engineering_agent.py` + `agents/decision_engine_agent.py`)

...produce **identical** values for `decision`, `risk_tier`, and `reason_codes`.

**Why it must not be bypassed**: In a regulated lending environment, two different credit decisions for the same application are a compliance violation. Any PR that causes this test to fail signals either (a) a divergence was introduced, or (b) the canonical path was updated without updating the other path. Either case must be resolved before merge.

---

### Tenant Isolation Test: `tests/audit/test_tenant_isolation.py`

Asserts:
1. An audit record written for `tenant_id=A` with `application_id=APP-001` cannot be retrieved by a query scoped to `tenant_id=B` using the same `application_id`.
2. Tenant B's audit reads return empty/404, not Tenant A's data.

This test is a CI gate (PR block on failure).

---

## 5. Common Pitfalls

| Pitfall | Why It Matters | What To Do Instead |
|---|---|---|
| Using `eval()` for conditional logic | Code injection, un-auditable, fails CI lint gate | Use `decision_engine/policy_dsl.py` AST evaluator |
| Calling `joblib.load()` inside a request handler | Per-request model load spikes p99 latency by 500–2000ms | Load models at startup using the `lifespan` event in FastAPI; inject via dependency |
| Writing to audit log without `tenant_id` | Tenantless data is un-routable post-P0.1; creates compliance gaps | Always include `TenantContext` in audit writes |
| Adding logic to `agents/*_agent.py` that duplicates `credit_core` | Guarantees divergent decisions; causes golden test failure | All business logic goes in `credit_core/` (or `feature_pipeline/` / `decision_engine/` today); agents are thin wrappers |
| Committing directly to `main` | — | PRs only; CI must pass including golden test |
| Using synchronous HTTP/GCS/Pub/Sub in async FastAPI handlers | Blocks the event loop; throttles throughput under load | Use `asyncio.get_event_loop().run_in_executor()` or `anyio.to_thread.run_sync()` |
| Hardcoding tenant IDs in tests | Tests become environment-specific | Use `pytest.fixture` with parameterized tenant IDs |

---

## 6. Deployment

### Cloud Run Deployment

```bash
# Build and push Decision API
cd decision-api
gcloud builds submit --tag gcr.io/$GCP_PROJECT/decision-api:latest

# Deploy to Cloud Run
gcloud run deploy decision-api \
  --image gcr.io/$GCP_PROJECT/decision-api:latest \
  --region us-central1 \
  --set-env-vars JWT_SECRET=$(gcloud secrets versions access latest --secret=jwt-secret) \
  --set-env-vars DATABASE_URL=$(gcloud secrets versions access latest --secret=audit-db-url) \
  --platform managed \
  --allow-unauthenticated  # Remove for production; use IAM auth

# Similarly for ingestion-api
cd ../ingestion-api
gcloud builds submit --tag gcr.io/$GCP_PROJECT/ingestion-api:latest
gcloud run deploy ingestion-api --image ... --region us-central1 ...
```

### Environment Variables in Secret Manager

```bash
# Store secrets
echo -n "your-jwt-secret" | gcloud secrets create jwt-secret --data-file=-
echo -n "postgresql://..." | gcloud secrets create audit-db-url --data-file=-
echo -n "postgresql://..." | gcloud secrets create loans-db-url --data-file=-

# Grant Cloud Run service account access
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:$SA@$PROJECT.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### BigQuery Table Creation

```bash
# Create all BigQuery tables from schema definitions
source .venv/bin/activate
python -c "
from db.bigquery_schema import create_all_tables
create_all_tables(project='your-gcp-project', dataset='credit_risk_prod')
"
```

### MLflow Model Registration Workflow

```bash
# Train and register PD model
make train-pd

# List registered models
.venv/bin/mlflow models list --tracking-uri http://localhost:5000

# Promote a model version to production
.venv/bin/mlflow models transition-to-production \
  --model-name credit_risk_pd \
  --version 3 \
  --tracking-uri http://localhost:5000
```

### Running Database Migrations

```bash
# Apply all pending Alembic migrations
.venv/bin/alembic upgrade head

# Create a new migration after schema changes
.venv/bin/alembic revision --autogenerate -m "add_tenant_id_to_audit"

# Downgrade one revision (test downgrade paths in CI)
.venv/bin/alembic downgrade -1
```
