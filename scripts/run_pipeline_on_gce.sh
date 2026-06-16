#!/usr/bin/env bash
# =============================================================================
# run_pipeline_on_gce.sh — Deploy & run the GCS ZIP → BigQuery pipeline on a
#                          Compute Engine instance.
#
# What this script does
# ---------------------
#  1. Reads configuration from .env (falls back to environment variables)
#  2. Uploads the pipeline Python script to GCS so the VM can download it
#  3. Uploads the startup script to GCS
#  4. Creates a Compute Engine VM with the startup script URL + metadata
#  5. Streams the serial-port log until the pipeline finishes
#  6. Deletes the VM when done (unless --keep-vm is passed)
#
# Usage
# -----
#  bash scripts/run_pipeline_on_gce.sh [OPTIONS]
#
#  Options
#  -------
#  --prefix PREFIX      GCS prefix for ZIPs (default: crt/)
#  --dataset DATASET    BQ dataset           (default: freddie_mac_sflld)
#  --machine TYPE       VM machine type      (default: n2-standard-4)
#  --zone ZONE          GCP zone             (default: us-central1-a)
#  --append             Pass --append to pipeline (WRITE_APPEND mode)
#  --dry-run            Pass --dry-run to pipeline (no BQ writes)
#  --reset              Pass --reset to pipeline  (ignore checkpoint)
#  --keep-vm            Do not delete VM after pipeline exits
#  --help               Show this message
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# ── Load .env ─────────────────────────────────────────────────────────────────
if [[ -f "$PROJECT_DIR/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
fi

# ── Defaults (overridden by CLI flags) ───────────────────────────────────────
GCP_PROJECT="${GCP_PROJECT_ID:-}"
GCS_BUCKET="${GCS_BUCKET:-ai-risk-workflow-credit-risk-data-dev}"
GCS_PREFIX="crt/"
BQ_DATASET="${BQ_DATASET:-freddie_mac_sflld}"
GCP_REGION="${GCP_REGION:-US}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
MACHINE_TYPE="n2-standard-4"
PIPELINE_ARGS=""
AUTO_SHUTDOWN="true"
KEEP_VM="false"

# ── Parse CLI arguments ───────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --prefix)   GCS_PREFIX="$2";   shift 2 ;;
        --dataset)  BQ_DATASET="$2";   shift 2 ;;
        --machine)  MACHINE_TYPE="$2"; shift 2 ;;
        --zone)     GCP_ZONE="$2";     shift 2 ;;
        --append)   PIPELINE_ARGS="$PIPELINE_ARGS --append"; shift ;;
        --dry-run)  PIPELINE_ARGS="$PIPELINE_ARGS --dry-run"; shift ;;
        --reset)    PIPELINE_ARGS="$PIPELINE_ARGS --reset"; shift ;;
        --keep-vm)  KEEP_VM="true"; shift ;;
        --help|-h)
            sed -n '3,35p' "$0"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

PIPELINE_ARGS="${PIPELINE_ARGS# }"  # trim leading space

# ── Validate required vars ────────────────────────────────────────────────────
if [[ -z "$GCP_PROJECT" ]]; then
    echo "ERROR: GCP_PROJECT_ID is not set. Export it or add it to .env."
    exit 1
fi

# ── Derived names ─────────────────────────────────────────────────────────────
TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
VM_NAME="crt-pipeline-${TIMESTAMP}"
SCRIPTS_GCS="gs://${GCS_BUCKET}/scripts"
STARTUP_GCS="${SCRIPTS_GCS}/compute_pipeline_startup.sh"
PIPELINE_GCS="${SCRIPTS_GCS}/gcs_zip_to_bigquery.py"

echo "============================================================"
echo " CRT Pipeline — Compute Engine Deployment"
echo "============================================================"
echo "  Project  : $GCP_PROJECT"
echo "  Zone     : $GCP_ZONE"
echo "  VM name  : $VM_NAME"
echo "  Machine  : $MACHINE_TYPE"
echo "  Bucket   : gs://$GCS_BUCKET/$GCS_PREFIX"
echo "  Dataset  : $GCP_PROJECT.$BQ_DATASET"
echo "  Region   : $GCP_REGION"
echo "  Args     : $PIPELINE_ARGS"
echo "  Keep VM  : $KEEP_VM"
echo "============================================================"

# ── 1. Upload scripts to GCS ──────────────────────────────────────────────────
echo ""
echo "── Uploading scripts to GCS ──"
gsutil -q cp "$SCRIPT_DIR/gcs_zip_to_bigquery.py"        "$PIPELINE_GCS"
gsutil -q cp "$SCRIPT_DIR/compute_pipeline_startup.sh"    "$STARTUP_GCS"
echo "  ✓ gs://$GCS_BUCKET/scripts/gcs_zip_to_bigquery.py"
echo "  ✓ gs://$GCS_BUCKET/scripts/compute_pipeline_startup.sh"

# ── 1b. Validate SA key exists locally ─────────────────────────────────────────
SA_KEY_LOCAL="${PROJECT_DIR}/${GCP_SA_KEY:-.gcp-sa-key-dev.json}"
if [[ ! -f "$SA_KEY_LOCAL" ]]; then
    echo "WARNING: SA key not found at $SA_KEY_LOCAL — VM will rely on instance service account ADC."
    SA_KEY_LOCAL=""
else
    echo "  ✓ SA key found at $SA_KEY_LOCAL (will be injected via VM metadata)"
fi
echo ""
echo "── Creating VM: $VM_NAME ──"

# Build metadata string (AFTER SA key validation)
METADATA="GCP_PROJECT_ID=${GCP_PROJECT}"
METADATA+=",GCS_BUCKET=${GCS_BUCKET}"
METADATA+=",GCS_CRT_PREFIX=${GCS_PREFIX}"
METADATA+=",BQ_DATASET=${BQ_DATASET}"
METADATA+=",GCP_REGION=${GCP_REGION}"
METADATA+=",AUTO_SHUTDOWN=${AUTO_SHUTDOWN}"
if [[ -n "$PIPELINE_ARGS" ]]; then
    METADATA+=",PIPELINE_ARGS=${PIPELINE_ARGS}"
fi

# Build --metadata-from-file args (startup-script + optional SA key)
METADATA_FILES="startup-script=${SCRIPT_DIR}/compute_pipeline_startup.sh"
if [[ -n "$SA_KEY_LOCAL" ]]; then
    METADATA_FILES+=",sa-key-json=${SA_KEY_LOCAL}"
fi

gcloud compute instances create "$VM_NAME" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" \
    --machine-type="$MACHINE_TYPE" \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-ssd \
    --scopes=cloud-platform \
    --metadata="$METADATA" \
    --metadata-from-file="$METADATA_FILES" \
    --quiet

echo "  ✓ VM created: $VM_NAME"

# ── Guaranteed VM deletion trap ──────────────────────────────────────────────
# Fires on normal exit, timeout, Ctrl-C (SIGINT), or SIGTERM.
# --keep-vm disables deletion so the user can SSH in and inspect.
delete_vm() {
    if [[ "$KEEP_VM" == "false" ]]; then
        echo ""
        echo "── Deleting VM: $VM_NAME (trap) ──"
        gcloud compute instances delete "$VM_NAME" \
            --project="$GCP_PROJECT" \
            --zone="$GCP_ZONE" \
            --quiet 2>/dev/null && echo "  ✓ VM deleted." || echo "  VM already gone or deletion failed."
    else
        echo ""
        echo "  --keep-vm set — VM retained: $VM_NAME (zone: $GCP_ZONE)"
        echo "  SSH:  gcloud compute ssh $VM_NAME --project=$GCP_PROJECT --zone=$GCP_ZONE"
        echo "  Logs: gcloud compute ssh $VM_NAME --project=$GCP_PROJECT --zone=$GCP_ZONE -- 'tail -f /var/log/crt_pipeline.log'"
    fi
}
trap 'delete_vm' EXIT INT TERM

# ── 3. Monitor VM serial console output ──────────────────────────────────────
echo ""
echo "── Streaming VM serial-console output (Ctrl-C to detach) ──"
echo "   Logs are also written on the VM to /var/log/crt_pipeline.log"
echo ""

# Poll serial console output until the pipeline completion marker appears
MAX_WAIT_SECS=14400  # 4 hours
POLL_INTERVAL=30
elapsed=0
pipeline_done=false

while [[ $elapsed -lt $MAX_WAIT_SECS ]]; do
    sleep "$POLL_INTERVAL"
    elapsed=$(( elapsed + POLL_INTERVAL ))

    # Fetch serial port output and display new lines
    gcloud compute instances get-serial-port-output "$VM_NAME" \
        --project="$GCP_PROJECT" \
        --zone="$GCP_ZONE" 2>/dev/null | tail -20 || true

    # Check if VM is still running
    VM_STATUS=$(gcloud compute instances describe "$VM_NAME" \
        --project="$GCP_PROJECT" \
        --zone="$GCP_ZONE" \
        --format='value(status)' 2>/dev/null || echo "UNKNOWN")

    if [[ "$VM_STATUS" == "TERMINATED" || "$VM_STATUS" == "STOPPED" ]]; then
        echo ""
        echo "  VM reached status: $VM_STATUS"
        pipeline_done=true
        break
    fi

    echo "  [+${elapsed}s] VM status: $VM_STATUS …"
done

if [[ "$pipeline_done" == "false" ]]; then
    echo ""
    echo "WARNING: Timed out after ${MAX_WAIT_SECS}s — forcing VM deletion via trap."
fi

# ── 4. Print final logs ───────────────────────────────────────────────────────
echo ""
echo "── Final serial-console output ──"
gcloud compute instances get-serial-port-output "$VM_NAME" \
    --project="$GCP_PROJECT" \
    --zone="$GCP_ZONE" 2>/dev/null | tail -50 || true

# VM deletion is handled by the trap registered above.
# It fires automatically when this script exits (here or on error/signal).

echo ""
echo "============================================================"
echo " Pipeline deployment complete!"
echo "  Verify in BigQuery:"
echo "    bq query --project=$GCP_PROJECT \\"
echo "      'SELECT COUNT(*) FROM \`$GCP_PROJECT.$BQ_DATASET.freddie_origination\`'"
echo "============================================================"
