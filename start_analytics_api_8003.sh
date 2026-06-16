#!/bin/bash
# Start CRP analytics API on port 8003 (port 8001 is reserved for ThinFile)
set -a
source "$(dirname "$0")/.env"
set +a
export GOOGLE_APPLICATION_CREDENTIALS="$(dirname "$0")/.gcp-sa-key-dev.json"
cd "$(dirname "$0")"
exec .venv311/bin/uvicorn analytics_api.src.main:app --host 0.0.0.0 --port 8003
