#!/usr/bin/env bash
# Start analytics API with BQ + Azure OpenAI config loaded from .env
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -d ".venv" ]; then
  source .venv/bin/activate
elif [ -d "venv" ]; then
  source venv/bin/activate
else
  echo "No venv found — using system Python"
fi

# Export all non-comment, non-blank lines from .env
while IFS= read -r line; do
  [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
  # Strip inline comments
  line="${line%%  #*}"
  export "$line" 2>/dev/null || true
done < .env

# GOOGLE_APPLICATION_CREDENTIALS must be absolute
export GOOGLE_APPLICATION_CREDENTIALS="$SCRIPT_DIR/.gcp-sa-key-dev.json"

echo "BQ_PROJECT=$BQ_PROJECT"
echo "BQ_DATASET=$BQ_DATASET"
echo "AZURE_OPENAI_DEPLOYMENT=$AZURE_OPENAI_DEPLOYMENT"
echo "GOOGLE_APPLICATION_CREDENTIALS=$GOOGLE_APPLICATION_CREDENTIALS"
echo ""
echo "Starting analytics API on port 8001..."

uvicorn analytics_api.src.main:app --host 0.0.0.0 --port 8001
