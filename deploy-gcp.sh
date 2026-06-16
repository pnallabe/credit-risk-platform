#!/usr/bin/env bash
# =============================================================================
# HelixDecision — GCP Backend Deploy Script
#
# Provisions all GCP infrastructure and deploys backend services:
#   - Cloud SQL (PostgreSQL 16)
#   - Cloud Memorystore (Redis 7)
#   - Artifact Registry (Docker)
#   - Secret Manager (JWT, DB password, OpenAI key)
#   - Cloud Run: crp-ingestion-api, crp-decision-api, crp-ai-agent
#
# Usage:
#   ./deploy-gcp.sh [dev|prod]
#
# Prerequisites:
#   gcloud auth login
#   gcloud auth application-default login
# =============================================================================
set -euo pipefail

ENVIRONMENT=${1:-dev}
PROJECT_ID=${GCP_PROJECT_ID:-""}
REGION=${GCP_REGION:-"us-central1"}
REPO_NAME="crp-platform"
DB_INSTANCE="crp-postgres-${ENVIRONMENT}"
DB_NAME="credit_risk"
DB_USER="crp_user"
REDIS_INSTANCE="crp-redis-${ENVIRONMENT}"
IMAGE_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "manual-$(date +%Y%m%d)")

# ── Preflight checks ──────────────────────────────────────────────────────────
if [[ -z "${PROJECT_ID}" ]]; then
  echo "❌ GCP_PROJECT_ID is not set. Export it first:"
  echo "   export GCP_PROJECT_ID=your-project-id"
  exit 1
fi

if ! command -v gcloud &>/dev/null; then
  echo "❌ gcloud CLI not found. Install from: https://cloud.google.com/sdk/docs/install"
  exit 1
fi

if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q .; then
  echo "❌ Not logged in. Run: gcloud auth login"
  exit 1
fi

echo ""
echo "========================================================"
echo "  HelixDecision — GCP Deploy"
echo "  Environment : ${ENVIRONMENT}"
echo "  Project     : ${PROJECT_ID}"
echo "  Region      : ${REGION}"
echo "  Image Tag   : ${IMAGE_TAG}"
echo "========================================================"
echo ""

gcloud config set project "${PROJECT_ID}" --quiet

# ── Enable APIs ───────────────────────────────────────────────────────────────
echo "▶ Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  redis.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  vpcaccess.googleapis.com \
  servicenetworking.googleapis.com \
  --quiet

# ── Artifact Registry ─────────────────────────────────────────────────────────
echo "▶ Ensuring Artifact Registry repo: ${REPO_NAME}..."
if ! gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" &>/dev/null; then
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="HelixDecision Docker images"
  echo "  ✓ Created ${REPO_NAME}"
else
  echo "  ✓ Already exists"
fi

# ── Cloud SQL (PostgreSQL) ────────────────────────────────────────────────────
echo "▶ Ensuring Cloud SQL instance: ${DB_INSTANCE}..."
if ! gcloud sql instances describe "${DB_INSTANCE}" &>/dev/null; then
  DB_PASSWORD=$(openssl rand -base64 24)
  gcloud sql instances create "${DB_INSTANCE}" \
    --database-version=POSTGRES_16 \
    --tier=db-g1-small \
    --region="${REGION}" \
    --storage-auto-increase \
    --backup-start-time=03:00 \
    --availability-type=zonal \
    --quiet
  gcloud sql databases create "${DB_NAME}" --instance="${DB_INSTANCE}" --quiet
  gcloud sql users create "${DB_USER}" \
    --instance="${DB_INSTANCE}" \
    --password="${DB_PASSWORD}" \
    --quiet
  # Store password in Secret Manager
  _upsert_secret "crp-db-password" "${DB_PASSWORD}"
  echo "  ✓ Cloud SQL created. Password stored in secret: crp-db-password"
else
  echo "  ✓ Already exists"
fi

DB_CONNECTION_NAME=$(gcloud sql instances describe "${DB_INSTANCE}" --format="value(connectionName)")
echo "  Connection name: ${DB_CONNECTION_NAME}"

# ── Cloud Memorystore (Redis) ─────────────────────────────────────────────────
echo "▶ Ensuring Memorystore Redis: ${REDIS_INSTANCE}..."
if ! gcloud redis instances describe "${REDIS_INSTANCE}" --region="${REGION}" &>/dev/null; then
  gcloud redis instances create "${REDIS_INSTANCE}" \
    --size=1 \
    --region="${REGION}" \
    --redis-version=redis_7_0 \
    --tier=basic \
    --quiet
  echo "  ✓ Redis created"
else
  echo "  ✓ Already exists"
fi

REDIS_HOST=$(gcloud redis instances describe "${REDIS_INSTANCE}" --region="${REGION}" --format="value(host)")
echo "  Redis host: ${REDIS_HOST}"

# ── Secret Manager ────────────────────────────────────────────────────────────
_upsert_secret() {
  local name=$1 value=$2
  if ! gcloud secrets describe "${name}" &>/dev/null; then
    printf '%s' "${value}" | gcloud secrets create "${name}" --data-file=- --replication-policy=automatic --quiet
    echo "  ✓ Secret created: ${name}"
  else
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=- --quiet
    echo "  ✓ Secret updated: ${name}"
  fi
}

echo "▶ Upserting secrets in Secret Manager..."

# JWT secret
JWT_SECRET=${JWT_SECRET:-$(openssl rand -base64 32)}
_upsert_secret "crp-jwt-secret" "${JWT_SECRET}"

# OpenAI key — pulled from env or prompted
if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  read -r -s -p "  Enter OPENAI_API_KEY (leave blank to skip): " OPENAI_API_KEY
  echo ""
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
  _upsert_secret "crp-openai-key" "${OPENAI_API_KEY}"
fi

# ── Service Accounts ──────────────────────────────────────────────────────────
_ensure_sa() {
  local sa_name=$1 display=$2
  local sa_email="${sa_name}@${PROJECT_ID}.iam.gserviceaccount.com"
  if ! gcloud iam service-accounts describe "${sa_email}" &>/dev/null; then
    gcloud iam service-accounts create "${sa_name}" --display-name="${display}" --quiet
    echo "  ✓ Created SA: ${sa_email}"
  else
    echo "  ✓ Exists: ${sa_email}"
  fi
  echo "${sa_email}"
}

echo "▶ Ensuring service accounts..."
SA_INGESTION=$(_ensure_sa "crp-ingestion-api"  "CRP Ingestion API")
SA_DECISION=$(_ensure_sa  "crp-decision-api"   "CRP Decision API")
SA_AGENT=$(_ensure_sa     "crp-ai-agent"       "CRP AI Agent")

# Grant Cloud SQL client to all backend service accounts
for SA in "${SA_INGESTION}" "${SA_DECISION}" "${SA_AGENT}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA}" --role="roles/cloudsql.client" --quiet
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor" --quiet
done

# ── Cloud Build ───────────────────────────────────────────────────────────────
echo ""
echo "▶ Submitting Cloud Build..."
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --substitutions="\
_REGION=${REGION},\
_ENVIRONMENT=${ENVIRONMENT},\
_IMAGE_TAG=${IMAGE_TAG},\
_REPO_NAME=${REPO_NAME},\
_DB_HOST=127.0.0.1,\
_DB_USER=${DB_USER},\
_DB_NAME=${DB_NAME}"

# ── Output service URLs ───────────────────────────────────────────────────────
echo ""
echo "========================================================"
echo "  ✅ GCP deployment complete!"
echo "========================================================"
for SVC in crp-ingestion-api crp-decision-api crp-ai-agent; do
  URL=$(gcloud run services describe "${SVC}-${ENVIRONMENT}" \
    --region="${REGION}" \
    --format="value(status.url)" 2>/dev/null || echo "(not yet available)")
  printf "  %-30s %s\n" "${SVC}-${ENVIRONMENT}:" "${URL}"
done

echo ""
echo "  Set these as env vars in Vercel:"
INGESTION_URL=$(gcloud run services describe "crp-ingestion-api-${ENVIRONMENT}" --region="${REGION}" --format="value(status.url)" 2>/dev/null || echo "")
DECISION_URL=$(gcloud run services describe "crp-decision-api-${ENVIRONMENT}" --region="${REGION}" --format="value(status.url)" 2>/dev/null || echo "")
AGENT_URL=$(gcloud run services describe "crp-ai-agent-${ENVIRONMENT}" --region="${REGION}" --format="value(status.url)" 2>/dev/null || echo "")
echo "  NEXT_PUBLIC_INGESTION_API_URL=${INGESTION_URL}"
echo "  NEXT_PUBLIC_DECISION_API_URL=${DECISION_URL}"
echo "  NEXT_PUBLIC_AGENT_API_URL=${AGENT_URL}"
echo ""
