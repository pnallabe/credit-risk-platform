#!/usr/bin/env bash
# =============================================================================
# Credit Risk Platform — GCP Data Infrastructure Setup
#
# Provisions:
#   1. GCS bucket for Parquet data files
#   2. Cloud SQL PostgreSQL instance  (db-n1-standard-2, 50 GB SSD)
#   3. Credit-risk database + user
#   4. Schema applied from db/schema.sql
#   5. Service account with minimum permissions for data pipeline
#
# Prerequisites:
#   gcloud CLI authenticated:  gcloud auth login
#   gcloud project set:        gcloud config set project PROJECT_ID
#   Required APIs enabled by this script automatically.
#
# Usage:
#   ./scripts/setup_gcp_data_infra.sh [--project PROJECT] [--region REGION] [--env ENV]
#
# Flags:
#   --project   GCP project ID   (or set GCP_PROJECT_ID env var)
#   --region    GCP region        (default: us-central1)
#   --env       dev | staging | prod  (default: dev)
#   --instance  Cloud SQL instance name suffix  (default: credit-risk)
#   --db-tier   Cloud SQL tier (default: db-n1-standard-2)
#   --dry-run   Print commands without executing them
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults (overridden by flags below)
# ---------------------------------------------------------------------------
PROJECT="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
ENV="dev"
INSTANCE_SUFFIX="credit-risk"
DB_TIER="db-custom-2-7680"   # 2 vCPUs, 7.5 GB RAM — PostgreSQL custom tier
DB_STORAGE_GB=50
DB_NAME="credit_risk"
DB_USER="credit_user"
DRY_RUN=false
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)  PROJECT="$2";          shift 2 ;;
    --region)   REGION="$2";           shift 2 ;;
    --env)      ENV="$2";              shift 2 ;;
    --instance) INSTANCE_SUFFIX="$2";  shift 2 ;;
    --db-tier)  DB_TIER="$2";          shift 2 ;;
    --dry-run)  DRY_RUN=true;          shift   ;;
    *)          echo "Unknown flag: $1"; exit 1 ;;
  esac
done

if [[ -z "$PROJECT" ]]; then
  echo "ERROR: GCP project ID is required. Set GCP_PROJECT_ID or pass --project PROJECT"
  exit 1
fi

# ---------------------------------------------------------------------------
# Derived names
# ---------------------------------------------------------------------------
INSTANCE_NAME="${INSTANCE_SUFFIX}-${ENV}"
BUCKET_NAME="${PROJECT}-${INSTANCE_SUFFIX}-data-${ENV}"
SA_NAME="crp-data-pipeline-${ENV}"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
SA_KEY_FILE="${REPO_ROOT}/.gcp-sa-key-${ENV}.json"

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
run() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] $*"
  else
    echo "▶  $*"
    "$@"
  fi
}

separator() { echo; echo "─────────────────────────────────────────────────────────"; echo "  $1"; echo "─────────────────────────────────────────────────────────"; }

# ---------------------------------------------------------------------------
# 0.  Enable required APIs
# ---------------------------------------------------------------------------
separator "0. Enabling GCP APIs"
run gcloud services enable \
  storage.googleapis.com \
  sqladmin.googleapis.com \
  sql-component.googleapis.com \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  --project="${PROJECT}"

# ---------------------------------------------------------------------------
# 1.  GCS bucket
# ---------------------------------------------------------------------------
separator "1. GCS bucket: gs://${BUCKET_NAME}"
BUCKET_EXISTS=$(gsutil ls -p "${PROJECT}" "gs://${BUCKET_NAME}" 2>/dev/null && echo yes || echo no)
if [[ "$BUCKET_EXISTS" == "no" ]]; then
  run gsutil mb \
    -p "${PROJECT}" \
    -c STANDARD \
    -l "${REGION}" \
    -b on \
    "gs://${BUCKET_NAME}"
  echo "  ✅  Bucket created: gs://${BUCKET_NAME}"
else
  echo "  ℹ️   Bucket already exists: gs://${BUCKET_NAME}"
fi

# Lifecycle: delete objects older than 1 year
cat > /tmp/lifecycle.json <<'EOF'
{
  "rule": [
    {
      "action": { "type": "Delete" },
      "condition": { "age": 365, "matchesStorageClass": ["STANDARD"] }
    }
  ]
}
EOF
run gsutil lifecycle set /tmp/lifecycle.json "gs://${BUCKET_NAME}"
echo "  ✅  Lifecycle policy applied (delete after 365 days)"

# ---------------------------------------------------------------------------
# 2.  Cloud SQL PostgreSQL instance
# ---------------------------------------------------------------------------
separator "2. Cloud SQL instance: ${INSTANCE_NAME}"
INSTANCE_EXISTS=$(gcloud sql instances list \
  --filter="name=${INSTANCE_NAME}" \
  --project="${PROJECT}" \
  --format="value(name)" 2>/dev/null || echo "")

if [[ -z "$INSTANCE_EXISTS" ]]; then
  echo "  Creating Cloud SQL instance (this takes ~5 minutes) …"
  run gcloud beta sql instances create "${INSTANCE_NAME}" \
    --project="${PROJECT}" \
    --region="${REGION}" \
    --database-version=POSTGRES_16 \
    --edition=ENTERPRISE \
    --tier="${DB_TIER}" \
    --storage-size="${DB_STORAGE_GB}GB" \
    --storage-type=SSD \
    --storage-auto-increase \
    --availability-type=ZONAL \
    --no-backup \
    --database-flags="max_connections=200" \
    --labels="environment=${ENV},platform=crp,component=database"
  echo "  ✅  Cloud SQL instance created: ${INSTANCE_NAME}"
else
  echo "  ℹ️   Cloud SQL instance already exists: ${INSTANCE_NAME}"
fi

# ---------------------------------------------------------------------------
# 3.  Database + user
# ---------------------------------------------------------------------------
separator "3. Database & User"

# Generate a random password (or read from Secret Manager if it exists)
DB_PASSWORD=$(python3 -c "import secrets, string; \
  chars=string.ascii_letters+string.digits; \
  print(''.join(secrets.choice(chars) for _ in range(32)))")

DB_EXISTS=$(gcloud sql databases list \
  --instance="${INSTANCE_NAME}" \
  --project="${PROJECT}" \
  --filter="name=${DB_NAME}" \
  --format="value(name)" 2>/dev/null || echo "")

if [[ -z "$DB_EXISTS" ]]; then
  run gcloud sql databases create "${DB_NAME}" \
    --instance="${INSTANCE_NAME}" \
    --project="${PROJECT}"
  echo "  ✅  Database '${DB_NAME}' created"
fi

USER_EXISTS=$(gcloud sql users list \
  --instance="${INSTANCE_NAME}" \
  --project="${PROJECT}" \
  --filter="name=${DB_USER}" \
  --format="value(name)" 2>/dev/null || echo "")

if [[ -z "$USER_EXISTS" ]]; then
  run gcloud sql users create "${DB_USER}" \
    --instance="${INSTANCE_NAME}" \
    --project="${PROJECT}" \
    --password="${DB_PASSWORD}"
  echo "  ✅  DB user '${DB_USER}' created"
  echo ""
  echo "  ⚠️  SAVE THIS PASSWORD: ${DB_PASSWORD}"
  echo "  Store it in Secret Manager:"
  echo "    echo -n '${DB_PASSWORD}' | gcloud secrets create crp-db-password-${ENV} --data-file=- --project=${PROJECT}"
  echo ""
else
  echo "  ℹ️   DB user '${DB_USER}' already exists"
  DB_PASSWORD="(existing — retrieve from Secret Manager)"
fi

# Store password in Secret Manager
if [[ "$DRY_RUN" == "false" ]] && [[ "$DB_PASSWORD" != "(existing"* ]]; then
  gcloud services enable secretmanager.googleapis.com --project="${PROJECT}" --quiet 2>/dev/null || true
  echo -n "${DB_PASSWORD}" | gcloud secrets create "crp-db-password-${ENV}" \
    --data-file=- \
    --project="${PROJECT}" \
    --replication-policy="automatic" 2>/dev/null || \
  echo -n "${DB_PASSWORD}" | gcloud secrets versions add "crp-db-password-${ENV}" \
    --data-file=- \
    --project="${PROJECT}"
  echo "  ✅  Password stored in Secret Manager: crp-db-password-${ENV}"
fi

# ---------------------------------------------------------------------------
# 4.  Apply schema via Cloud SQL Auth Proxy
# ---------------------------------------------------------------------------
separator "4. Applying database schema"
INSTANCE_CONNECTION_NAME="${PROJECT}:${REGION}:${INSTANCE_NAME}"

# Check if cloud-sql-proxy is available
if command -v cloud-sql-proxy &>/dev/null; then
  echo "  Starting Cloud SQL Auth Proxy on 127.0.0.1:5433 …"
  cloud-sql-proxy "${INSTANCE_CONNECTION_NAME}" --port=5433 &
  PROXY_PID=$!
  sleep 5

  PGPASSWORD="${DB_PASSWORD}" psql \
    -h 127.0.0.1 -p 5433 \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    -f "${REPO_ROOT}/db/schema.sql" && echo "  ✅  Schema applied"

  kill "${PROXY_PID}" 2>/dev/null || true
elif [[ "$DRY_RUN" == "false" ]]; then
  echo "  ⚠️  cloud-sql-proxy not found. Apply the schema manually:"
  echo "  1. Install: https://cloud.google.com/sql/docs/postgres/sql-proxy"
  echo "  2. Run:"
  echo "     cloud-sql-proxy ${INSTANCE_CONNECTION_NAME} --port=5433 &"
  echo "     PGPASSWORD='\$DB_PASSWORD' psql -h 127.0.0.1 -p 5433 -U ${DB_USER} -d ${DB_NAME} -f db/schema.sql"
fi

# ---------------------------------------------------------------------------
# 5.  Service account for data pipeline
# ---------------------------------------------------------------------------
separator "5. Service account: ${SA_EMAIL}"
SA_EXISTS=$(gcloud iam service-accounts list \
  --filter="email=${SA_EMAIL}" \
  --project="${PROJECT}" \
  --format="value(email)" 2>/dev/null || echo "")

if [[ -z "$SA_EXISTS" ]]; then
  run gcloud iam service-accounts create "${SA_NAME}" \
    --project="${PROJECT}" \
    --display-name="CRP Data Pipeline (${ENV})" \
    --description="Used by the synthetic data generation and GCS loading scripts"
  echo "  ✅  Service account created: ${SA_EMAIL}"
fi

# Grant GCS object admin on the data bucket
run gsutil iam ch \
  "serviceAccount:${SA_EMAIL}:objectAdmin" \
  "gs://${BUCKET_NAME}"

# Grant Cloud SQL Client
run gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudsql.client" \
  --condition=None

echo "  ✅  IAM bindings applied"

# Create + download key (only if not already present)
if [[ ! -f "$SA_KEY_FILE" ]]; then
  run gcloud iam service-accounts keys create "${SA_KEY_FILE}" \
    --iam-account="${SA_EMAIL}" \
    --project="${PROJECT}"
  echo "  ✅  Service account key → ${SA_KEY_FILE}"
  echo "  ⚠️  Add this file to .gitignore — it is a secret!"
else
  echo "  ℹ️   Key already exists at ${SA_KEY_FILE}"
fi

# ---------------------------------------------------------------------------
# 6.  Print summary + next steps
# ---------------------------------------------------------------------------
separator "Setup complete — next steps"

INSTANCE_IP=$(gcloud sql instances describe "${INSTANCE_NAME}" \
  --project="${PROJECT}" \
  --format="value(ipAddresses[0].ipAddress)" 2>/dev/null || echo "<pending>")

cat <<EOF

  GCS bucket:        gs://${BUCKET_NAME}
  Cloud SQL name:    ${INSTANCE_NAME}
  Cloud SQL IP:      ${INSTANCE_IP}
  Connection name:   ${INSTANCE_CONNECTION_NAME}
  Database:          ${DB_NAME}
  DB User:           ${DB_USER}
  Service account:   ${SA_EMAIL}

  Add these to your .env (or GitHub Secrets for CI/CD):

    GCS_BUCKET=${BUCKET_NAME}
    GCP_PROJECT_ID=${PROJECT}
    GCP_REGION=${REGION}
    CLOUD_SQL_INSTANCE=${INSTANCE_CONNECTION_NAME}
    DATABASE_URL_SYNC=postgresql://${DB_USER}:<PASSWORD>@127.0.0.1:5433/${DB_NAME}
    DATABASE_URL=postgresql+asyncpg://${DB_USER}:<PASSWORD>@127.0.0.1:5433/${DB_NAME}
    GOOGLE_APPLICATION_CREDENTIALS=${SA_KEY_FILE}

  Generate 10M rows and upload to GCS:
    make data-generate-gcp

  Load GCS Parquet files into Cloud SQL:
    make data-load-cloudsql

  Query data with pandas (no Cloud SQL needed):
    python3 -c "
    import pandas as pd
    df = pd.read_parquet(
        'gs://${BUCKET_NAME}/data/train/',
        storage_options={'project': '${PROJECT}'}
    )
    print(df.shape, df['default_flag'].mean())
    "

EOF
