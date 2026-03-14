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
generate-data: ## Generate synthetic loan application data
	$(PYTHON) data/generate_synthetic_data.py --rows 10000

.PHONY: generate-data-full
generate-data-full: ## Generate full 100k synthetic dataset
	$(PYTHON) data/generate_synthetic_data.py --rows 100000

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
