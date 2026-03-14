#!/usr/bin/env bash
# =============================================================================
# Credit Risk Platform — Vercel Frontend Deploy Script
#
# Deploys both Next.js apps to Vercel:
#   ui/applicant-portal    → applicant-facing loan portal
#   ui/analytics-dashboard → internal analytics (role-based)
#
# Usage:
#   ./deploy-vercel.sh [preview|production]
#
# Prerequisites:
#   npm install -g vercel
#   vercel login
#   export VERCEL_ORG_ID=...        (from vercel whoami)
#   GCP services must be deployed first (./deploy-gcp.sh)
#
# Vercel environment variables expected (set via `vercel env add` or dashboard):
#   crp_decision_api_url     → GCP Cloud Run decision-api URL
#   crp_ingestion_api_url    → GCP Cloud Run ingestion-api URL
#   crp_agent_api_url        → GCP Cloud Run ai-agent URL
#   NEXTAUTH_SECRET          → shared auth secret (openssl rand -base64 32)
# =============================================================================
set -euo pipefail

TARGET=${1:-preview}   # "preview" or "production"
PROD_FLAG=""
[[ "${TARGET}" == "production" ]] && PROD_FLAG="--prod"

# ── Preflight ─────────────────────────────────────────────────────────────────
if ! command -v vercel &>/dev/null; then
  echo "❌ Vercel CLI not found. Install with: npm install -g vercel"
  exit 1
fi

echo ""
echo "========================================================"
echo "  Credit Risk Platform — Vercel Deploy (${TARGET})"
echo "========================================================"
echo ""

deploy_app() {
  local dir=$1 name=$2
  echo "▶ Deploying ${name}..."
  pushd "${dir}" >/dev/null
  vercel ${PROD_FLAG} --yes 2>&1 | tail -5
  URL=$(vercel ls --scope="${VERCEL_ORG_ID:-}" 2>/dev/null | grep "${name}" | head -1 | awk '{print $2}' || echo "see vercel dashboard")
  echo "  ✓ ${name} → https://${URL}"
  popd >/dev/null
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

deploy_app "${SCRIPT_DIR}/ui/applicant-portal"    "applicant-portal"
deploy_app "${SCRIPT_DIR}/ui/analytics-dashboard" "analytics-dashboard"

echo ""
echo "========================================================"
echo "  ✅ Vercel deployment complete!"
echo ""
echo "  Tip: Set backend URLs as Vercel env vars:"
echo "    vercel env add crp_decision_api_url --cwd ui/applicant-portal"
echo "    vercel env add crp_decision_api_url --cwd ui/analytics-dashboard"
echo "    vercel env add crp_agent_api_url    --cwd ui/analytics-dashboard"
echo "    vercel env add NEXTAUTH_SECRET      --cwd ui/applicant-portal"
echo "    vercel env add NEXTAUTH_SECRET      --cwd ui/analytics-dashboard"
echo "========================================================"
echo ""
