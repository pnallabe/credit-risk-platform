.PHONY: help install test lint format clean run docker-build docker-run deploy-dev deploy-prod

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install dependencies
	pip install -r requirements.txt
	pip install -e .

test: ## Run tests with coverage
	pytest test_main.py -v --cov=main --cov=models --cov=auth --cov-report=term --cov-report=html

test-fast: ## Run tests without coverage
	pytest test_main.py -v

lint: ## Run linting checks
	black --check main.py models.py auth.py test_main.py
	flake8 main.py models.py auth.py test_main.py --max-line-length=100
	mypy main.py models.py auth.py --ignore-missing-imports

format: ## Auto-format code
	black main.py models.py auth.py test_main.py

clean: ## Clean up generated files
	rm -rf __pycache__ .pytest_cache .mypy_cache htmlcov .coverage
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

run: ## Run the application locally
	uvicorn main:app --reload --port 8080

run-prod: ## Run with production settings
	uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4

docker-build: ## Build Docker image
	docker build -t ingestion-api:latest .

docker-run: ## Run Docker container locally
	docker run -p 8080:8080 \
		-e GCS_RAW_BUCKET=${GCS_RAW_BUCKET} \
		-e PUBSUB_TOPIC=${PUBSUB_TOPIC} \
		-e GCP_PROJECT_ID=${GCP_PROJECT_ID} \
		-e JWT_SECRET=${JWT_SECRET} \
		-e GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json \
		-v ${GOOGLE_APPLICATION_CREDENTIALS}:/app/credentials.json:ro \
		ingestion-api:latest

docker-test: ## Run tests in Docker
	docker run ingestion-api:latest pytest test_main.py -v

deploy-dev: ## Deploy to dev environment
	./deploy.sh dev

deploy-prod: ## Deploy to prod environment
	./deploy.sh prod

token: ## Generate a test JWT token
	@python -c "from auth import create_access_token; print(create_access_token('test-user', 3600))"

validate: lint test ## Run all validation checks

ci: validate ## Run CI pipeline locally
	@echo "✅ CI checks passed"

setup-gcp: ## Setup GCP resources (run once)
	@echo "Enabling required APIs..."
	gcloud services enable run.googleapis.com storage.googleapis.com pubsub.googleapis.com
	@echo "Creating GCS bucket..."
	gsutil mb -p ${GCP_PROJECT_ID} -l ${REGION} gs://${GCS_RAW_BUCKET}
	@echo "Creating Pub/Sub topic..."
	gcloud pubsub topics create ingestion-events-dev
	@echo "✅ GCP setup complete"

logs-dev: ## Tail logs from dev environment
	gcloud logging tail "resource.type=cloud_run_revision AND resource.labels.service_name=ingestion-api-dev" --format=json

logs-prod: ## Tail logs from prod environment
	gcloud logging tail "resource.type=cloud_run_revision AND resource.labels.service_name=ingestion-api-prod" --format=json

shell: ## Start Python shell with context
	python -i -c "from main import *; from models import *; from auth import *"