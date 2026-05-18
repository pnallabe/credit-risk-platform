#!/bin/bash
# Start analytics API under Python 3.11 (OpenSSL 3.6.1 — fixes Azure TLS)
set -a
source "$(dirname "$0")/.env"
set +a
export GOOGLE_APPLICATION_CREDENTIALS="$(dirname "$0")/.gcp-sa-key-dev.json"
cd "$(dirname "$0")"
exec .venv311/bin/uvicorn analytics_api.src.main:app --host 0.0.0.0 --port 8001
