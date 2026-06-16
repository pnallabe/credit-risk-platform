#!/usr/bin/env python3
"""
run_compliance_preflight.py — Section 23.5
==========================================
Runs all 7 compliance pre-flight checks required before any policy
lifecycle stage transition or model deployment.

Pre-flight checks
-----------------
  1. Usury cap state coverage (all 50 states + DC + PR + VI)
  2. Usury cap legal sign-off age (<= 12 months)
  3. Adverse action code completeness
  4. Compliance data plane BQ schema validation
  5. Governance threshold regression check
  6. Audit DDL backward compatibility
  7. Audit completeness (0 gaps in last 24 hours)

Usage:
    python scripts/run_compliance_preflight.py \
        --policy-file config/usury_caps.yaml \
        --aa-codes-file config/adverse_action_codes.yaml \
        [--fail-fast]

Exit codes:
  0 — all checks passed
  1 — one or more checks failed
  2 — environment / import error
"""
import argparse
import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"

CHECKS = [
    {
        "id": "usury_coverage",
        "label": "Usury cap state coverage",
        "script": "verify_usury_cap_coverage.py",
        "args": ["--require-all-states"],
    },
    {
        "id": "usury_age",
        "label": "Usury cap legal sign-off age",
        "script": "check_usury_cap_age.py",
        "args": ["--max-age-days", "365"],
    },
    {
        "id": "aa_codes",
        "label": "Adverse action code completeness",
        "script": "validate_adverse_action_codes.py",
        "args": [],
    },
    {
        "id": "bq_schema",
        "label": "Compliance data plane BQ schema",
        "script": "check_compliance_schema.py",
        "args": [],
    },
    {
        "id": "governance",
        "label": "Governance threshold regression",
        "script": "check_governance_thresholds.py",
        "args": ["--baseline-file", str(REPO_ROOT / ".governance-baseline.json")],
    },
    {
        "id": "audit_compat",
        "label": "Audit DDL backward compatibility",
        "script": "check_audit_schema_compat.py",
        "args": [],
    },
    {
        "id": "audit_completeness",
        "label": "Audit completeness (0 gaps)",
        "script": "check_audit_completeness.py",
        "args": [],
    },
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy-file", default="config/usury_caps.yaml")
    p.add_argument("--aa-codes-file", default="config/adverse_action_codes.yaml")
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first failing check.",
    )
    return p.parse_args()


def run_check(check: dict, fail_fast: bool) -> bool:
    """Run a single check script and return True if it passed."""
    script = SCRIPTS_DIR / check["script"]
    if not script.exists():
        logger.error("[%s] Script not found: %s — SKIP", check["id"], script)
        return False

    cmd = [sys.executable, str(script)] + check["args"]
    logger.info("--- Running: %s ---", check["label"])
    result = subprocess.run(cmd, capture_output=False, cwd=str(REPO_ROOT))

    if result.returncode == 0:
        logger.info("[%s] PASS", check["id"])
        return True
    else:
        logger.error("[%s] FAIL (exit code %d)", check["id"], result.returncode)
        return False


def main() -> int:
    args = parse_args()
    passed = 0
    failed = 0

    for check in CHECKS:
        ok = run_check(check, fail_fast=args.fail_fast)
        if ok:
            passed += 1
        else:
            failed += 1
            if args.fail_fast:
                logger.error("--fail-fast: aborting after first failure.")
                break

    logger.info("=" * 60)
    logger.info("Compliance pre-flight: %d passed, %d failed", passed, failed)

    if failed > 0:
        logger.error(
            "COMPLIANCE PRE-FLIGHT FAILED.  "
            "Resolve all %d failure(s) before proceeding with deployment.",
            failed,
        )
        return 1

    logger.info("All 7 compliance pre-flight checks PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
