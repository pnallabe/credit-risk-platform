SHELL := /bin/bash
PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
VENV := .venv

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-28s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
.PHONY: venv
venv: ## Create Python virtual environment
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

.PHONY: install
install: venv ## Install all Python dependencies
	$(PIP) install -r requirements.txt
	$(PIP) install shap lime "python-jose[cryptography]" aiofiles python-multipart pytest-asyncio aiosqlite

.PHONY: install-agent
install-agent: ## Install AI agent Python dependencies
	$(PIP) install -r ai-agent/requirements.txt

.PHONY: npm-install
npm-install: ## Install Node dependencies for both UI apps
	cd ui/applicant-portal && npm ci
	cd ui/analytics-dashboard && npm ci

.PHONY: setup
setup: install install-agent npm-install ## Install all deps (Python + Node)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
.PHONY: bootstrap
bootstrap: setup ## Full first-run setup: install deps, copy .env, train models
	@if [ ! -f .env ]; then cp .env.example .env && echo "✅  .env created from .env.example — fill in secrets before running."; fi
	$(MAKE) train-all
	@echo ""
	@echo "✅  Bootstrap complete!"
	@echo "   Run 'make dev' to start the full stack."

# ---------------------------------------------------------------------------
# Development  (Docker Compose)
# ---------------------------------------------------------------------------
.PHONY: dev
dev: ## Start the full development stack (Docker Compose)
	docker compose up --build

.PHONY: dev-detach
dev-detach: ## Start development stack in background
	docker compose up --build -d

.PHONY: dev-backends
dev-backends: ## Start only backend services (no UI builds)
	docker compose up --build postgres redis mlflow ingestion-api decision-api ai-agent ai-agent-scheduler -d

.PHONY: dev-ui
dev-ui: ## Start UI apps in dev mode (hot-reload, local Node)
	@echo "Starting both UI apps in dev mode…"
	@(cd ui/applicant-portal   && npm run dev -- --port 3000) &
	@(cd ui/analytics-dashboard && npm run dev -- --port 3001) &
	@wait

.PHONY: down
down: ## Stop and remove all containers and volumes
	docker compose down -v

.PHONY: down-keep-data
down-keep-data: ## Stop containers but keep data volumes
	docker compose down

.PHONY: restart
restart: down dev-detach ## Full restart (down + up)

.PHONY: logs
logs: ## Tail logs from all running services
	docker compose logs -f

.PHONY: logs-api
logs-api: ## Tail logs from API services only
	docker compose logs -f decision-api ingestion-api ai-agent

.PHONY: ps
ps: ## Show running container status
	docker compose ps

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
.PHONY: test
test: ## Run all Python unit tests
	$(PYTEST) \
		feature_pipeline/tests/ \
		decision_engine/tests/ \
		models/pricing/tests/ \
		explainability/tests/ \
		audit/tests/ \
		monitoring/tests/ \
		mlflow_config/tests/ \
		decision-api/tests/ \
		-v --tb=short \
		--ignore=.venv \
		-p no:warnings

.PHONY: test-fast
test-fast: ## Run fast unit tests only (skip slow integration tests)
	$(PYTEST) \
		feature_pipeline/tests/ \
		decision_engine/tests/ \
		models/pricing/tests/ \
		monitoring/tests/ \
		-v --tb=short -p no:warnings -x

.PHONY: test-integration
test-integration: ## Run E2E integration tests (requires running decision-api)
	$(PYTEST) tests/integration/ -v --tb=short -p no:warnings

.PHONY: test-agent
test-agent: ## Run AI agent scheduler tests
	$(PYTEST) ai-agent/tests/ -v --tb=short -p no:warnings

.PHONY: test-ui
test-ui: ## Run UI Vitest tests for both apps
	cd ui/applicant-portal    && npm run test -- --run
	cd ui/analytics-dashboard && npm run test -- --run

.PHONY: test-all
test-all: test test-agent test-ui ## Run all tests (Python + Node)

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PYTEST) \
		feature_pipeline/tests/ \
		decision_engine/tests/ \
		models/pricing/tests/ \
		explainability/tests/ \
		audit/tests/ \
		monitoring/tests/ \
		mlflow_config/tests/ \
		decision-api/tests/ \
		--cov=. \
		--cov-report=term-missing \
		--cov-report=html:htmlcov \
		--cov-omit=".venv/*,*/tests/*" \
		-p no:warnings

.PHONY: test-ingestion
test-ingestion: ## Run ingestion API tests
	$(PYTEST) ingestion-api/tests/ -v --tb=short

# ---------------------------------------------------------------------------
# Services  (local, without Docker)
# ---------------------------------------------------------------------------
.PHONY: api-ingestion
api-ingestion: ## Start the ingestion API locally
	cd ingestion-api && ../.venv/bin/uvicorn src.main:app --reload --port 8080

.PHONY: api-decision
api-decision: ## Start the decision API locally
	$(PYTHON) -m uvicorn decision-api.src.main:app --reload --port 8081

.PHONY: api-agent
api-agent: ## Start the AI agent API locally
	cd ai-agent && PYTHONPATH=src ../.venv/bin/uvicorn src.main:app --reload --port 8082

.PHONY: scheduler
scheduler: ## Run the AI agent scheduler locally
	cd ai-agent && PYTHONPATH=src $(PYTHON) src/scheduler.py

.PHONY: dashboard
dashboard: ## Start the Streamlit dashboard locally
	.venv/bin/streamlit run dashboard/app.py --server.port 8501

.PHONY: mlflow-ui
mlflow-ui: ## Start MLflow UI locally
	.venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow/mlruns.db --port 5000

.PHONY: portal
portal: ## Start applicant portal (Next.js dev)
	cd ui/applicant-portal && npm run dev -- --port 3000

.PHONY: analytics
analytics: ## Start analytics dashboard (Next.js dev)
	cd ui/analytics-dashboard && npm run dev -- --port 3001

# ---------------------------------------------------------------------------
# Build  (production)
# ---------------------------------------------------------------------------
.PHONY: build
build: ## Build all Docker images (no cache)
	docker compose build --no-cache

.PHONY: build-portal
build-portal: ## Build applicant-portal Docker image
	docker build -t credit-risk/applicant-portal:latest \
		--build-arg NEXT_PUBLIC_DECISION_API_URL=$${DECISION_API_URL:-http://localhost:8081} \
		-f ui/applicant-portal/Dockerfile .

.PHONY: build-analytics
build-analytics: ## Build analytics-dashboard Docker image
	docker build -t credit-risk/analytics-dashboard:latest \
		--build-arg NEXT_PUBLIC_DECISION_API_URL=$${DECISION_API_URL:-http://localhost:8081} \
		--build-arg NEXT_PUBLIC_AGENT_API_URL=$${AGENT_API_URL:-http://localhost:8082} \
		-f ui/analytics-dashboard/Dockerfile .

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
.PHONY: generate-data
generate-data: ## Generate synthetic loan application data (10k rows, local)
	$(PYTHON) data/generate_synthetic_data.py --rows 10000

.PHONY: generate-data-full
generate-data-full: ## Generate full 100k synthetic dataset (local)
	$(PYTHON) data/generate_synthetic_data.py --rows 100000

# ---------------------------------------------------------------------------
# Multi-Domain Synthetic Data  (Loans · Transactions · Credit Cards)
# ---------------------------------------------------------------------------
.PHONY: generate-loans
generate-loans: ## Generate loans domain data  (500k customers, 1M apps, ~8M payments)
	$(PYTHON) data/generate_loans_data.py \
		--customers 500000 \
		--applications 1000000 \
		--threads 4

.PHONY: generate-transactions
generate-transactions: ## Generate transactions domain data  (300k accounts, 15M txns)
	$(PYTHON) data/generate_transactions_data.py \
		--accounts 300000 \
		--transactions 15000000 \
		--threads 6

.PHONY: generate-cards
generate-cards: ## Generate credit-cards domain data  (500k accounts, 25M txns)
	$(PYTHON) data/generate_credit_cards_data.py \
		--accounts 500000 \
		--transactions 25000000 \
		--threads 6

.PHONY: generate-all-domains
generate-all-domains: ## Generate ALL domains with default scale  (~55M rows total) — ~30-45 min
	$(PYTHON) data/generate_all_domains.py --mode default --threads 6

.PHONY: generate-all-small
generate-all-small: ## Quick smoke test: all domains at tiny scale  (<1 min)
	$(PYTHON) data/generate_all_domains.py --mode small

.PHONY: generate-all-medium
generate-all-medium: ## Generate all domains at medium scale  (~7M rows, ~5 min)
	$(PYTHON) data/generate_all_domains.py --mode medium --threads 4

.PHONY: generate-all-large
generate-all-large: ## LARGE: 2M customers, ~160M rows total  — ~2 hrs, needs 32 GB RAM
	$(PYTHON) data/generate_all_domains.py --mode large --threads 8

# ---------------------------------------------------------------------------
# Multi-Domain GCS Upload
# ---------------------------------------------------------------------------
.PHONY: data-generate-multi-gcp
data-generate-multi-gcp: ## Generate all domains (default scale) and upload to GCS
	$(PYTHON) data/generate_all_domains.py \
		--mode default \
		--upload \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--gcs-prefix "$${GCS_DATA_PREFIX:-data}" \
		--threads 6

.PHONY: data-generate-multi-gcp-small
data-generate-multi-gcp-small: ## Generate all domains (small scale) and upload to GCS (smoke test)
	$(PYTHON) data/generate_all_domains.py \
		--mode small \
		--upload \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--gcs-prefix "$${GCS_DATA_PREFIX:-data}"

# ---------------------------------------------------------------------------
# Multi-Domain DB initialisation
# ---------------------------------------------------------------------------
.PHONY: db-init-loans
db-init-loans: ## Apply loans schema to postgres:5432
	docker compose exec -T postgres \
		psql -U "$${POSTGRES_USER:-credit_user}" -d "$${LOANS_DB:-credit_risk_loans}" \
		-f /docker-entrypoint-initdb.d/02_loans_schema.sql

.PHONY: db-init-transactions
db-init-transactions: ## Apply transactions schema to postgres-transactions:5433
	docker compose exec -T postgres-transactions \
		psql -U "$${POSTGRES_USER:-credit_user}" -d "$${TRANSACTIONS_DB:-credit_risk_transactions}" \
		-f /docker-entrypoint-initdb.d/01_transactions_schema.sql

.PHONY: db-init-cards
db-init-cards: ## Apply credit-cards schema to postgres-cards:5434
	docker compose exec -T postgres-cards \
		psql -U "$${POSTGRES_USER:-credit_user}" -d "$${CARDS_DB:-credit_risk_cards}" \
		-f /docker-entrypoint-initdb.d/01_cards_schema.sql

.PHONY: db-init-all
db-init-all: db-init-loans db-init-transactions db-init-cards ## Initialise all 3 domain databases

.PHONY: data-setup-gcp
data-setup-gcp: ## Provision GCS bucket + Cloud SQL instance (requires gcloud auth)
	@chmod +x scripts/setup_gcp_data_infra.sh
	./scripts/setup_gcp_data_infra.sh \
		--project "$${GCP_PROJECT_ID}" \
		--region "$${GCP_REGION:-us-central1}" \
		--env "$${ENVIRONMENT:-dev}"

.PHONY: data-generate-gcp
data-generate-gcp: ## Generate 10M rows and upload to GCS (set GCS_BUCKET + GCP_PROJECT_ID)
	$(PYTHON) scripts/generate_and_upload_gcp.py \
		--rows 10000000 \
		--chunk-size 500000 \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_DATA_PREFIX:-data}" \
		--workers 4

.PHONY: data-generate-gcp-small
data-generate-gcp-small: ## Generate 100k rows and upload to GCS (quick smoke test)
	$(PYTHON) scripts/generate_and_upload_gcp.py \
		--rows 100000 \
		--chunk-size 50000 \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_DATA_PREFIX:-data}" \
		--workers 2

.PHONY: data-load-cloudsql
data-load-cloudsql: ## Load all GCS Parquet files into Cloud SQL (requires proxy on :5433)
	$(PYTHON) scripts/load_gcs_to_cloudsql.py \
		--db-url "$${DATABASE_URL_SYNC}" \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_DATA_PREFIX:-data}" \
		--split both

.PHONY: data-load-cloudsql-train
data-load-cloudsql-train: ## Load only the train split into Cloud SQL
	$(PYTHON) scripts/load_gcs_to_cloudsql.py \
		--db-url "$${DATABASE_URL_SYNC}" \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_DATA_PREFIX:-data}" \
		--split train

.PHONY: crt-list
crt-list: ## List available Freddie Mac CRT SFLLD deals/files (no download)
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--username "$${FREDDIE_MAC_USERNAME}" \
		--password "$${FREDDIE_MAC_PASSWORD}" \
		$${FREDDIE_MAC_TOKEN:+--token "$${FREDDIE_MAC_TOKEN}"} \
		--list

.PHONY: crt-upload
crt-upload: ## Download all CRT SFLLD files and upload to GCS as Parquet
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--username "$${FREDDIE_MAC_USERNAME}" \
		--password "$${FREDDIE_MAC_PASSWORD}" \
		$${FREDDIE_MAC_TOKEN:+--token "$${FREDDIE_MAC_TOKEN}"} \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--skip-existing

.PHONY: crt-upload-deal
crt-upload-deal: ## Upload a specific deal: make crt-upload-deal DEAL=STACR-2023
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--username "$${FREDDIE_MAC_USERNAME}" \
		--password "$${FREDDIE_MAC_PASSWORD}" \
		$${FREDDIE_MAC_TOKEN:+--token "$${FREDDIE_MAC_TOKEN}"} \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--deal "$${DEAL}" \
		--skip-existing

.PHONY: crt-upload-year
crt-upload-year: ## Upload a specific year: make crt-upload-year YEAR=2023
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--username "$${FREDDIE_MAC_USERNAME}" \
		--password "$${FREDDIE_MAC_PASSWORD}" \
		$${FREDDIE_MAC_TOKEN:+--token "$${FREDDIE_MAC_TOKEN}"} \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--year "$${YEAR}" \
		--skip-existing

.PHONY: crt-upload-local
crt-upload-local: ## Upload all local Freddie Mac ZIPs from data/Freddiemac/ to GCS (auto-deletes local parquet after each upload)
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--local-dir data/Freddiemac \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}"

.PHONY: crt-upload-local-year
crt-upload-local-year: ## Upload local ZIP for a specific year: make crt-upload-local-year YEAR=2015
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/upload_freddie_crt_to_gcs.py \
		--local-dir data/Freddiemac \
		--bucket "$${GCS_BUCKET}" \
		--project "$${GCP_PROJECT_ID}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--year "$${YEAR}"

.PHONY: crt-bq-load
crt-bq-load: ## Load Freddie Mac parquet from GCS into BigQuery (2 tables: origination + performance)
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/load_freddie_to_bigquery.py \
		--project "$${GCP_PROJECT_ID}" \
		--bucket "$${GCS_BUCKET}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--dataset "$${BQ_DATASET:-freddie_mac_sflld}" \
		--location "$${GCP_REGION:-US}"

.PHONY: crt-bq-load-append
crt-bq-load-append: ## Append (not replace) Freddie Mac parquet from GCS into BigQuery
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/load_freddie_to_bigquery.py \
		--project "$${GCP_PROJECT_ID}" \
		--bucket "$${GCS_BUCKET}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--dataset "$${BQ_DATASET:-freddie_mac_sflld}" \
		--location "$${GCP_REGION:-US}" \
		--append

.PHONY: crt-bq-dry-run
crt-bq-dry-run: ## Show which GCS parquet files would be loaded into BigQuery
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/load_freddie_to_bigquery.py \
		--project "$${GCP_PROJECT_ID}" \
		--bucket "$${GCS_BUCKET}" \
		--prefix "$${GCS_CRT_PREFIX:-crt/sflld}" \
		--dataset "$${BQ_DATASET:-freddie_mac_sflld}" \
		--dry-run

.PHONY: crt-full-pipeline
crt-full-pipeline: ## Full pipeline: local ZIPs → GCS parquet (no local copy) → BigQuery
	@echo "Step 1/2: Converting ZIPs → Parquet → GCS (local parquet auto-deleted)..."
	$(MAKE) crt-upload-local
	@echo "Step 2/2: Loading GCS parquet → BigQuery..."
	$(MAKE) crt-bq-load
	@echo ""
	@echo "✅  Freddie Mac pipeline complete."
	@set -a && [ -f .env ] && source .env; set +a; \
	echo "   Origination: $${GCP_PROJECT_ID}.$${BQ_DATASET:-freddie_mac_sflld}.freddie_origination"; \
	echo "   Performance: $${GCP_PROJECT_ID}.$${BQ_DATASET:-freddie_mac_sflld}.freddie_performance"

# ---------------------------------------------------------------------------
# CRT ZIP → BigQuery pipeline  (reads ZIPs directly from GCS crt/ prefix)
# ---------------------------------------------------------------------------

.PHONY: crt-zip-bq
crt-zip-bq: ## Stream ZIPs from GCS crt/ → parse → BigQuery (local run)
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/gcs_zip_to_bigquery.py \
		--project  "$${GCP_PROJECT_ID}" \
		--bucket   "$${GCS_BUCKET}" \
		--prefix   "$${GCS_CRT_PREFIX_RAW:-crt/}" \
		--dataset  "$${BQ_DATASET:-freddie_mac_sflld}" \
		--location "$${GCP_REGION:-US}"

.PHONY: crt-zip-bq-append
crt-zip-bq-append: ## Append ZIPs from GCS crt/ to existing BigQuery tables
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/gcs_zip_to_bigquery.py \
		--project  "$${GCP_PROJECT_ID}" \
		--bucket   "$${GCS_BUCKET}" \
		--prefix   "$${GCS_CRT_PREFIX_RAW:-crt/}" \
		--dataset  "$${BQ_DATASET:-freddie_mac_sflld}" \
		--location "$${GCP_REGION:-US}" \
		--append

.PHONY: crt-zip-bq-dry-run
crt-zip-bq-dry-run: ## Dry-run: list ZIPs that would be loaded (no BQ writes)
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/gcs_zip_to_bigquery.py \
		--project  "$${GCP_PROJECT_ID}" \
		--bucket   "$${GCS_BUCKET}" \
		--prefix   "$${GCS_CRT_PREFIX_RAW:-crt/}" \
		--dry-run

.PHONY: crt-zip-bq-reset
crt-zip-bq-reset: ## Reprocess all ZIPs (ignore checkpoint): make crt-zip-bq-reset
	set -a && [ -f .env ] && source .env; set +a; \
	$(PYTHON) scripts/gcs_zip_to_bigquery.py \
		--project  "$${GCP_PROJECT_ID}" \
		--bucket   "$${GCS_BUCKET}" \
		--prefix   "$${GCS_CRT_PREFIX_RAW:-crt/}" \
		--dataset  "$${BQ_DATASET:-freddie_mac_sflld}" \
		--location "$${GCP_REGION:-US}" \
		--reset

# Run the ZIP → BigQuery pipeline on a Compute Engine instance.
# Optional env overrides: GCE_MACHINE_TYPE, GCE_ZONE, GCS_CRT_PREFIX_RAW.
# Pass extra pipeline flags via PIPELINE_FLAGS, e.g.:
#   make crt-zip-bq-gce PIPELINE_FLAGS="--append"
.PHONY: crt-zip-bq-gce
crt-zip-bq-gce: ## Deploy & run ZIP→BQ pipeline on a Compute Engine VM
	set -a && [ -f .env ] && source .env; set +a; \
	bash scripts/run_pipeline_on_gce.sh \
		--prefix  "$${GCS_CRT_PREFIX_RAW:-crt/}" \
		--dataset "$${BQ_DATASET:-freddie_mac_sflld}" \
		--machine "$${GCE_MACHINE_TYPE:-n2-standard-4}" \
		--zone    "$${GCE_ZONE:-us-central1-a}" \
		$${PIPELINE_FLAGS:-}

.PHONY: crt-zip-bq-gce-dry
crt-zip-bq-gce-dry: ## Dry-run on Compute Engine (no BQ writes, VM auto-deleted)
	$(MAKE) crt-zip-bq-gce PIPELINE_FLAGS="--dry-run"

.PHONY: data-pipeline-full
data-pipeline-full: data-setup-gcp data-generate-gcp data-load-cloudsql ## Full GCP data pipeline: infra + generate + load
	@echo ""
	@echo "✅  Full data pipeline complete."
	@echo "   10M rows in GCS: gs://$${GCS_BUCKET}/$${GCS_DATA_PREFIX:-data}/"
	@echo "   10M rows in Cloud SQL: $${CLOUD_SQL_INSTANCE}"

.PHONY: data-query-gcs
data-query-gcs: ## Query GCS Parquet row count + stats via pandas (no Cloud SQL needed)
	$(PYTHON) -c "import pandas as pd, os; b=os.environ['GCS_BUCKET']; p=os.environ.get('GCS_DATA_PREFIX','data'); proj=os.environ['GCP_PROJECT_ID']; df=pd.read_parquet(f'gs://{b}/{p}/train/', storage_options={'project': proj}); print(df.shape); print(df[['credit_score','annual_income','default_flag']].describe())"

.PHONY: data-verify
data-verify: ## Print row counts from GCS manifest
	$(PYTHON) -c "import json,os; from google.cloud import storage; b=os.environ['GCS_BUCKET']; p=os.environ.get('GCS_DATA_PREFIX','data'); proj=os.environ['GCP_PROJECT_ID']; cl=storage.Client(project=proj); m=json.loads(cl.bucket(b).blob(f'{p}/manifest.json').download_as_text()); [print(f'{k}: {v}') for k,v in m.items()]"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
.PHONY: train-fraud
train-fraud: ## Train the fraud detection model
	$(PYTHON) models/fraud_detection/train.py

.PHONY: train-credit-risk
train-credit-risk: ## Train the credit risk model
	$(PYTHON) models/credit_risk/train.py

.PHONY: train-all
train-all: generate-data train-fraud train-credit-risk ## Generate data and train all models

# ---------------------------------------------------------------------------
# Code quality
# ---------------------------------------------------------------------------
.PHONY: lint
lint: ## Run ruff linter
	.venv/bin/ruff check . --ignore=E501,E402 --exclude=.venv || true

.PHONY: format
format: ## Format code with black
	.venv/bin/black . --exclude=".venv|node_modules" || true

.PHONY: clean
clean: ## Remove build artifacts, caches, and egg-info
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -not -path "./.venv/*" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage 2>/dev/null || true
	rm -rf ui/applicant-portal/.next ui/analytics-dashboard/.next 2>/dev/null || true

# ---------------------------------------------------------------------------
# Shell / debug helpers
# ---------------------------------------------------------------------------
.PHONY: shell-decision
shell-decision: ## Open a shell in the decision-api container
	docker compose exec decision-api bash

.PHONY: shell-agent
shell-agent: ## Open a shell in the ai-agent container
	docker compose exec ai-agent bash

.PHONY: shell-ingestion
shell-ingestion: ## Open a shell in the ingestion-api container
	docker compose exec ingestion-api bash

.PHONY: shell-db
shell-db: ## Open psql in the postgres container
	docker compose exec postgres psql -U $${POSTGRES_USER:-creditrisk} $${POSTGRES_DB:-creditrisk}

.PHONY: restart-agent
restart-agent: ## Restart AI agent + scheduler (e.g. after code change)
	docker compose restart ai-agent ai-agent-scheduler

.PHONY: restart-apis
restart-apis: ## Restart all API services
	docker compose restart ingestion-api decision-api ai-agent ai-agent-scheduler

.PHONY: pull-images
pull-images: ## Pull latest base images (postgres, redis, mlflow)
	docker compose pull postgres redis

# ---------------------------------------------------------------------------
# Security / pre-commit hooks
# ---------------------------------------------------------------------------
.PHONY: install-hooks
install-hooks: ## Install pre-commit hooks into .git/hooks (run once after clone)
	.venv/bin/pip install pre-commit detect-secrets -q
	.venv/bin/pre-commit install --install-hooks
	@echo "✅  pre-commit hooks installed"

.PHONY: update-hooks
update-hooks: ## Update all pre-commit hook versions to latest
	.venv/bin/pre-commit autoupdate

.PHONY: check-secrets
check-secrets: ## Scan entire repo for secrets / large files (dry run, no commit needed)
	.venv/bin/pre-commit run --all-files

.PHONY: check-secrets-fast
check-secrets-fast: ## Run secret scan on staged files only
	.venv/bin/pre-commit run

.PHONY: secrets-baseline
secrets-baseline: ## Regenerate detect-secrets baseline (after reviewing & approving current state)
	.venv/bin/detect-secrets scan \
	  --exclude-files '\.venv/' \
	  --exclude-files 'node_modules/' \
	  --exclude-files '\.git/' \
	  --exclude-files '\.secrets\.baseline' \
	  --exclude-files 'mlruns/' \
	  > .secrets.baseline
	@echo "✅  .secrets.baseline updated — review and commit it"

.PHONY: audit-secrets
audit-secrets: ## Interactive audit: mark detected secrets as real or false-positive
	.venv/bin/detect-secrets audit .secrets.baseline

# =============================================================================
# Cloud Deployment
# =============================================================================

.PHONY: deploy-gcp-dev
deploy-gcp-dev: ## Deploy all backend services to GCP Cloud Run (dev)
	./deploy-gcp.sh dev

.PHONY: deploy-gcp-prod
deploy-gcp-prod: ## Deploy all backend services to GCP Cloud Run (prod)
	./deploy-gcp.sh prod

.PHONY: deploy-vercel-preview
deploy-vercel-preview: ## Deploy both Next.js frontends to Vercel (preview)
	./deploy-vercel.sh preview

.PHONY: deploy-vercel-prod
deploy-vercel-prod: ## Deploy both Next.js frontends to Vercel (production)
	./deploy-vercel.sh production

.PHONY: deploy-all-dev
deploy-all-dev: deploy-gcp-dev deploy-vercel-preview ## Full platform deploy to dev (GCP backends + Vercel frontends)

.PHONY: deploy-all-prod
deploy-all-prod: deploy-gcp-prod deploy-vercel-prod ## Full platform deploy to production

.PHONY: cloud-status
cloud-status: ## Show live Cloud Run service URLs and status
	@echo "=== Cloud Run Services ==="
	@gcloud run services list --platform=managed --region=$${GCP_REGION:-us-central1} \
	  --filter="metadata.labels.platform=crp" \
	  --format="table(metadata.name,status.url,status.conditions[0].type)" 2>/dev/null || \
	  echo "  (gcloud not configured — set GCP_PROJECT_ID and run: gcloud auth login)"
