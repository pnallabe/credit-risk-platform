#!/bin/bash
set -e

# Deployment script for ingestion API
# Usage: ./deploy.sh [dev|prod]

ENVIRONMENT=${1:-dev}
PROJECT_ID=${GCP_PROJECT_ID:-"ai-risk-workflow"}
REGION=${REGION:-"us-central1"}
SERVICE_NAME="ingestion-api-${ENVIRONMENT}"
IMAGE_TAG=$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short HEAD 2>/dev/null || echo "manual")

echo "🚀 Deploying Ingestion API to ${ENVIRONMENT} environment"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Image Tag: ${IMAGE_TAG}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "❌ gcloud CLI not found. Please install it first."
    exit 1
fi

# Check if logged in
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo "❌ Not logged in to gcloud. Run: gcloud auth login"
    exit 1
fi

# Set project
echo "Setting project to ${PROJECT_ID}..."
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo "Enabling required APIs..."
gcloud services enable \
    run.googleapis.com \
    storage.googleapis.com \
    pubsub.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com \
    secretmanager.googleapis.com

# Create Artifact Registry repository if it doesn't exist
REPO_NAME="risk-platform"
if ! gcloud artifacts repositories describe ${REPO_NAME} --location=${REGION} &> /dev/null; then
    echo "Creating Artifact Registry repository: ${REPO_NAME}"
    gcloud artifacts repositories create ${REPO_NAME} \
        --repository-format=docker \
        --location=${REGION} \
        --description="Risk Platform Docker Images"
else
    echo "✓ Artifact Registry repository already exists: ${REPO_NAME}"
fi

# Create GCS bucket if it doesn't exist
BUCKET_NAME="risk-raw-data-${ENVIRONMENT}"
if ! gsutil ls -b gs://${BUCKET_NAME} &> /dev/null; then
    echo "Creating GCS bucket: ${BUCKET_NAME}"
    gsutil mb -p ${PROJECT_ID} -l ${REGION} gs://${BUCKET_NAME}
    gsutil versioning set on gs://${BUCKET_NAME}
    gsutil lifecycle set - gs://${BUCKET_NAME} <<EOF
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {"age": 90}
      }
    ]
  }
}
EOF
else
    echo "✓ GCS bucket already exists: ${BUCKET_NAME}"
fi

# Create Pub/Sub topic if it doesn't exist
TOPIC_NAME="ingestion-events-${ENVIRONMENT}"
if ! gcloud pubsub topics describe ${TOPIC_NAME} &> /dev/null; then
    echo "Creating Pub/Sub topic: ${TOPIC_NAME}"
    gcloud pubsub topics create ${TOPIC_NAME}
else
    echo "✓ Pub/Sub topic already exists: ${TOPIC_NAME}"
fi

# Create service account if it doesn't exist
SERVICE_ACCOUNT="ingestion-api@${PROJECT_ID}.iam.gserviceaccount.com"
if ! gcloud iam service-accounts describe ${SERVICE_ACCOUNT} &> /dev/null; then
    echo "Creating service account: ${SERVICE_ACCOUNT}"
    gcloud iam service-accounts create ingestion-api \
        --display-name="Ingestion API Service Account" \
        --description="Service account for ingestion API"
    
    # Grant necessary permissions
    echo "Granting permissions to service account..."
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/storage.objectCreator"
    
    gcloud projects add-iam-policy-binding ${PROJECT_ID} \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/pubsub.publisher"
else
    echo "✓ Service account already exists: ${SERVICE_ACCOUNT}"
fi

# Create JWT secret in Secret Manager if it doesn't exist
SECRET_NAME="jwt-secret"
if ! gcloud secrets describe ${SECRET_NAME} &> /dev/null; then
    echo "Creating secret: ${SECRET_NAME}"
    echo "Please enter a secure JWT secret key (or press Enter to generate one):"
    read -s JWT_SECRET
    if [ -z "$JWT_SECRET" ]; then
        JWT_SECRET=$(openssl rand -base64 32)
        echo "Generated JWT secret"
    fi
    echo -n ${JWT_SECRET} | gcloud secrets create ${SECRET_NAME} \
        --data-file=- \
        --replication-policy="automatic"
    
    # Grant service account access to secret
    gcloud secrets add-iam-policy-binding ${SECRET_NAME} \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor"
else
    echo "✓ Secret already exists: ${SECRET_NAME}"
fi

# Build and deploy using Cloud Build
echo ""
echo "Building and deploying with Cloud Build..."
gcloud builds submit \
    --config=deployment/cloudbuild.yaml \
    --substitutions=_REGION=${REGION},_ENVIRONMENT=${ENVIRONMENT},_IMAGE_TAG=${IMAGE_TAG},_GCS_RAW_BUCKET=${BUCKET_NAME},_PUBSUB_TOPIC=projects/${PROJECT_ID}/topics/${TOPIC_NAME},_SERVICE_ACCOUNT=${SERVICE_ACCOUNT},_REPO_NAME=${REPO_NAME}

# Get service URL
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
    --region=${REGION} \
    --format="value(status.url)" 2>/dev/null || echo "Not deployed yet")

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Service URL: ${SERVICE_URL}"
echo "Service Account: ${SERVICE_ACCOUNT}"
echo "GCS Bucket: gs://${BUCKET_NAME}"
echo "Pub/Sub Topic: ${TOPIC_NAME}"
echo "Image: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/ingestion-api:${IMAGE_TAG}"
echo ""
echo "To test the API:"
echo "  1. Generate a test token:"
echo "     python -c \"from src.auth import create_access_token; print(create_access_token('test-user'))\""
echo ""
echo "  2. Make a test request:"
echo "     curl -X POST ${SERVICE_URL}/transactions \\"
echo "       -H \"Authorization: Bearer YOUR_TOKEN\" \\"
echo "       -H \"Content-Type: application/json\" \\"
echo "       -d @examples/example_payloads.json"
echo ""