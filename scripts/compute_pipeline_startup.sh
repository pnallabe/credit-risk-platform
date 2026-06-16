#!/usr/bin/env bash
# =============================================================================
# Compute Engine startup script — GCS ZIP → BigQuery pipeline
# =============================================================================
# This script runs automatically when the VM boots (passed as --metadata
# startup-script or stored in GCS and referenced via startup-script-url).
#
# It installs dependencies, copies the pipeline source from GCS, runs the
# pipeline, then optionally shuts the VM down when finished.
#
# Metadata keys consumed (set with --metadata key=value when creating the VM):
#   GCP_PROJECT_ID   – GCP project id
#   GCS_BUCKET       – source bucket (ai-risk-workflow-credit-risk-data-dev)
#   GCS_CRT_PREFIX   – ZIP prefix inside the bucket (default: crt/)
#   BQ_DATASET       – BigQuery dataset (default: freddie_mac_sflld)
#   GCP_REGION       – BigQuery dataset location (default: US)
#   PIPELINE_ARGS    – extra CLI args forwarded to gcs_zip_to_bigquery.py
#   AUTO_SHUTDOWN    – set to "true" to power off VM when pipeline finishes
# =============================================================================
# Do NOT use set -e: we must reach the shutdown trap even on pipeline failures.
# Individual critical steps use explicit error checks instead.
set -uo pipefail

LOG=/var/log/crt_pipeline.log
exec > >(tee -a "$LOG") 2>&1

# ── Guaranteed shutdown trap ─────────────────────────────────────────────────
# Registered early; fires on any exit (success, error, or signal).
# AUTO_SHUTDOWN is populated after metadata is read; we write to a tmp var
# first so the trap can always reference the final value.
_DO_SHUTDOWN=false
shutdown_handler() {
    local exit_code=$?
    echo ""
    echo "── EXIT trap (code ${exit_code}) at $(date -u '+%Y-%m-%dT%H:%M:%SZ') ──"
    if [[ "$_DO_SHUTDOWN" == "true" ]]; then
        echo "Auto-shutdown: powering off in 10 s …"
        sleep 10
        shutdown -h now
    else
        echo "Auto-shutdown disabled — VM will remain running."
    fi
}
trap 'shutdown_handler' EXIT

echo "============================================================"
echo " CRT Pipeline Startup — $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
echo "============================================================"

# ── 1. Read instance metadata ─────────────────────────────────────────────────
META_URL="http://metadata.google.internal/computeMetadata/v1/instance/attributes"
META_HEADER=(-H "Metadata-Flavor: Google")

get_meta() {
    local key="$1" default="${2:-}"
    curl -sf "${META_URL}/${key}" "${META_HEADER[@]}" 2>/dev/null || echo "$default"
}

GCP_PROJECT_ID=$(get_meta GCP_PROJECT_ID "")
GCS_BUCKET=$(get_meta GCS_BUCKET "ai-risk-workflow-credit-risk-data-dev")
GCS_CRT_PREFIX=$(get_meta GCS_CRT_PREFIX "crt/")
BQ_DATASET=$(get_meta BQ_DATASET "freddie_mac_sflld")
GCP_REGION=$(get_meta GCP_REGION "US")
PIPELINE_ARGS=$(get_meta PIPELINE_ARGS "")
AUTO_SHUTDOWN=$(get_meta AUTO_SHUTDOWN "true")

# Arm the shutdown trap now that AUTO_SHUTDOWN is known.
[[ "$AUTO_SHUTDOWN" == "true" ]] && _DO_SHUTDOWN=true

echo "  Project : $GCP_PROJECT_ID"
echo "  Bucket  : gs://$GCS_BUCKET/$GCS_CRT_PREFIX"
echo "  Dataset : $GCP_PROJECT_ID.$BQ_DATASET"
echo "  Region  : $GCP_REGION"
echo "  Shutdown: $AUTO_SHUTDOWN"

if [[ -z "$GCP_PROJECT_ID" ]]; then
    echo "ERROR: GCP_PROJECT_ID metadata is required."
    exit 1
fi

# ── 2. Install system dependencies ───────────────────────────────────────────
echo ""
echo "── Installing system packages ──"
apt-get update -qq || { echo "ERROR: apt-get update failed"; exit 1; }
apt-get install -y -qq python3-pip python3-venv git curl unzip || { echo "ERROR: apt-get install failed"; exit 1; }

# ── 3. Set up Python virtual environment ─────────────────────────────────────
echo ""
echo "── Setting up Python environment ──"
WORK_DIR=/opt/crt_pipeline
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

python3 -m venv venv
# shellcheck source=/dev/null
source venv/bin/activate

pip install --upgrade pip -q
pip install -q \
    google-cloud-bigquery \
    google-cloud-storage \
    pandas \
    pyarrow \
    db-dtypes

# ── 4. Download pipeline script from GCS ─────────────────────────────────────
echo ""
echo "── Fetching pipeline script ──"
SCRIPT_GCS="gs://${GCS_BUCKET}/scripts/gcs_zip_to_bigquery.py"

# Try to download from GCS first (uploaded by deploy script).
# Fall back to the repo if the bucket version is not found.
if gsutil -q stat "$SCRIPT_GCS" 2>/dev/null; then
    gsutil cp "$SCRIPT_GCS" "$WORK_DIR/gcs_zip_to_bigquery.py"
    echo "  Downloaded from GCS: $SCRIPT_GCS"
else
    echo "  Script not found in GCS — checking repo via git clone…"
    REPO_URL=$(get_meta REPO_URL "")
    if [[ -n "$REPO_URL" ]]; then
        git clone --depth 1 "$REPO_URL" repo
        cp repo/scripts/gcs_zip_to_bigquery.py "$WORK_DIR/"
    else
        echo "ERROR: Pipeline script not found in GCS and REPO_URL not set."
        exit 1
    fi
fi

# ── 5. Write minimal .env so the script can load config ───────────────────────
cat > "$WORK_DIR/.env" <<EOF
GCP_PROJECT_ID=$GCP_PROJECT_ID
GCS_BUCKET=$GCS_BUCKET
GCS_CRT_PREFIX_RAW=$GCS_CRT_PREFIX
BQ_DATASET=$BQ_DATASET
GCP_REGION=$GCP_REGION
EOF

# ── 5b. Set up authentication ────────────────────────────────────────────────
# The SA key was injected directly into VM metadata (sa-key-json key) by the
# deploy script's --metadata-from-file flag. Read it via the local curl call
# to the metadata server (plain HTTP, always works on GCE).
export GOOGLE_CLOUD_PROJECT="$GCP_PROJECT_ID"
SA_KEY_META=$(curl -sf "http://metadata.google.internal/computeMetadata/v1/instance/attributes/sa-key-json" \
    -H "Metadata-Flavor: Google" 2>/dev/null || echo "")
echo "  SA key from metadata: ${#SA_KEY_META} bytes"
if [[ -n "$SA_KEY_META" && "$SA_KEY_META" != "{}" ]]; then
    echo "$SA_KEY_META" > "$WORK_DIR/sa-key.json"
    chmod 600 "$WORK_DIR/sa-key.json"
    export GOOGLE_APPLICATION_CREDENTIALS="$WORK_DIR/sa-key.json"
    gcloud auth activate-service-account --key-file="$WORK_DIR/sa-key.json" --quiet
    echo "  ✓ Authenticated via SA key from metadata (GOOGLE_APPLICATION_CREDENTIALS=$WORK_DIR/sa-key.json)"
else
    echo "  No sa-key-json in metadata — falling back to instance service account ADC."
fi

# ── 6. Run the pipeline ───────────────────────────────────────────────────────
echo ""
echo "── Running pipeline ──"
echo "  Command: python gcs_zip_to_bigquery.py $PIPELINE_ARGS"

# shellcheck disable=SC2086
PIPELINE_EXIT=0
python "$WORK_DIR/gcs_zip_to_bigquery.py" \
    --project "$GCP_PROJECT_ID" \
    --bucket  "$GCS_BUCKET" \
    --prefix  "$GCS_CRT_PREFIX" \
    --dataset "$BQ_DATASET" \
    --location "$GCP_REGION" \
    $PIPELINE_ARGS || PIPELINE_EXIT=$?

echo ""
echo "── Pipeline finished (exit $PIPELINE_EXIT) at $(date -u '+%Y-%m-%dT%H:%M:%SZ') ──"

if [[ "$PIPELINE_EXIT" -ne 0 ]]; then
    echo "Pipeline FAILED — check $LOG for details."
fi

# The shutdown_handler trap (registered at the top) will fire on exit.
# Explicitly exit with the pipeline's exit code so the trap sees it.
exit $PIPELINE_EXIT
