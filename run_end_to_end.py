#!/usr/bin/env python3
"""
run_end_to_end.py
==================
Production-grade end-to-end execution script for HelixDecision.

Demonstrates the complete pipeline:
  ApplicantInput JSON  →  DataIngestion  →  FeatureEngineering
  →  RiskModeling  →  DecisionEngine  →  Explainability  →  Output

Usage
-----
  # Single applicant
  python run_end_to_end.py

  # Custom applicant JSON
  python run_end_to_end.py --input /path/to/applicant.json

  # Batch mode from CSV
  python run_end_to_end.py --batch /path/to/applicants.csv --output /tmp/decisions.json

  # With challenger model (A/B experiment)
  python run_end_to_end.py --use-challenger --experiment-id exp_2026_q2

Environment
-----------
  AGENT_CONFIG_PATH : path to agent_config.yaml (default: config/agent_config.yaml)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

# ── Add project root to path ────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from orchestration.pipeline import CreditRiskPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("run_end_to_end")


# ---------------------------------------------------------------------------
# Sample applicant definitions
# ---------------------------------------------------------------------------

SAMPLE_APPLICANTS = [
    # 1. Thin-file applicant — no bureau data, relies on alt-data signals
    {
        "application_id": "APP-THIN-001",
        "loan_amount": 5000.0,
        "loan_purpose": "personal",
        "loan_term_months": 36,
        "annual_income": 42000.0,
        "employment_status": "employed",
        "employer_tenure_months": 18.0,
        "dti": None,
        "existing_debt": 2000.0,
        "credit_score": None,           # ← THIN FILE: no bureau score
        "num_open_accounts": None,      # ← THIN FILE: no bureau data
        "num_derogatory_marks": None,
        "months_since_last_delinquency": None,
        "borrower_state": "CA",
        # Alt-data signals
        "rent_payment_months": 24,
        "utility_payment_months": 20,
        "mobile_data_score": 0.72,
        "bank_account_age_months": 30,
        "avg_monthly_cash_inflow": 3500.0,
        "avg_monthly_cash_outflow": 2800.0,
        "channel": "mobile_app",
    },
    # 2. Prime bureau applicant — strong credit profile
    {
        "application_id": "APP-PRIME-002",
        "loan_amount": 15000.0,
        "loan_purpose": "debt_consolidation",
        "loan_term_months": 48,
        "annual_income": 95000.0,
        "employment_status": "employed",
        "employer_tenure_months": 72.0,
        "dti": 0.22,
        "existing_debt": 20900.0,
        "credit_score": 740.0,
        "num_open_accounts": 6,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": 48.0,
        "borrower_state": "TX",
        "channel": "web",
    },
    # 3. Near-prime / subprime applicant — high-risk profile
    {
        "application_id": "APP-SUB-003",
        "loan_amount": 8000.0,
        "loan_purpose": "personal",
        "loan_term_months": 24,
        "annual_income": 28000.0,
        "employment_status": "self_employed",
        "employer_tenure_months": 6.0,
        "dti": 0.48,
        "existing_debt": 13440.0,
        "credit_score": 580.0,
        "num_open_accounts": 2,
        "num_derogatory_marks": 3,
        "months_since_last_delinquency": 8.0,
        "borrower_state": "FL",
        "channel": "partner",
    },
    # 4. Young professional — thin credit history, high income
    {
        "application_id": "APP-YOUNG-004",
        "loan_amount": 3500.0,
        "loan_purpose": "education",
        "loan_term_months": 24,
        "annual_income": 68000.0,
        "employment_status": "employed",
        "employer_tenure_months": 9.0,
        "dti": 0.12,
        "existing_debt": 8160.0,
        "credit_score": None,           # ← recent graduate
        "num_open_accounts": 1,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
        "borrower_state": "NY",
        "rent_payment_months": 12,
        "bank_account_age_months": 14,
        "avg_monthly_cash_inflow": 5666.0,
        "avg_monthly_cash_outflow": 3200.0,
        "channel": "web",
    },
]


# ---------------------------------------------------------------------------
# Result formatter
# ---------------------------------------------------------------------------


def _format_result(result: Dict[str, Any]) -> str:
    """Pretty-print a single pipeline decision result."""
    app_id = result.get("application_id", "N/A")
    dec = result.get("decision", "N/A")
    pd_score = result.get("pd_score", 0.0)
    fraud = result.get("fraud_flag", "N/A")
    reasons = result.get("reason_codes", [])
    rate = result.get("approved_rate")
    amount = result.get("approved_amount")
    factors = result.get("top_factors", [])[:3]

    lines = [
        f"\n{'═' * 60}",
        f"  APPLICATION: {app_id}",
        f"  DECISION   : {'✅ ' + dec if dec == 'APPROVE' else '❌ ' + dec if dec == 'REJECT' else '⚠️  ' + dec}",
        f"  PD Score   : {pd_score:.4f}  │  Fraud Flag: {fraud}",
    ]
    if dec == "APPROVE":
        lines.append(f"  Approved   : ${amount:,.2f} @ {rate:.2f}% APR" if rate and amount else "  Approved")
    if reasons:
        lines.append(f"  Reason Codes: {', '.join(reasons)}")
    if factors:
        lines.append("  Top Factors:")
        for f in factors:
            feat = f.get("feature", "?")
            sv = f.get("shap_value", 0.0)
            direction = "▲" if sv > 0 else "▼"
            lines.append(f"    {direction} {feat}: {sv:+.4f}")
    lines.append(f"{'═' * 60}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(args: argparse.Namespace) -> int:
    config_path = os.environ.get("AGENT_CONFIG_PATH", "config/agent_config.yaml")

    logger.info("Initialising pipeline from config: %s", config_path)
    pipeline = CreditRiskPipeline.from_config(config_path)

    # ── Load applicants ──────────────────────────────────────────────────
    if args.input:
        with open(args.input) as f:
            applicants: List[Dict[str, Any]] = json.load(f)
        if isinstance(applicants, dict):
            applicants = [applicants]
        logger.info("Loaded %d applicant(s) from %s", len(applicants), args.input)
    elif args.batch:
        df = pd.read_csv(args.batch)
        applicants = df.to_dict(orient="records")
        logger.info("Loaded %d applicant(s) from CSV %s", len(applicants), args.batch)
    else:
        applicants = SAMPLE_APPLICANTS
        logger.info("Running with %d built-in sample applicant(s)", len(applicants))

    # ── Run pipeline ─────────────────────────────────────────────────────
    t0 = time.perf_counter()
    run = pipeline.run(
        applicant_dicts=applicants,
        tenant_id=args.tenant_id,
        experiment_id=args.experiment_id or None,
        use_challenger=args.use_challenger,
        source="cli",
    )
    elapsed = time.perf_counter() - t0

    # ── Display results ──────────────────────────────────────────────────
    print(f"\n{'━' * 60}")
    print(f"  HELIXDECISION — PIPELINE RUN: {run.run_id}")
    print(f"  Status   : {run.status.upper()}")
    print(f"  Duration : {elapsed:.3f}s")
    print(f"{'━' * 60}")

    if run.status == "failure":
        logger.error("Pipeline failed: %s", run.final_payload.get("error"))
        return 1

    # Decision stats
    stats = run.final_payload.get("decision_stats", {})
    n = stats.get("total", 0)
    print(f"\n  📊 DECISION SUMMARY")
    print(f"     Total Applications : {n}")
    print(f"     ✅ Approved         : {stats.get('approved', 0)} ({stats.get('approval_rate_pct', 0):.1f}%)")
    print(f"     ❌ Rejected         : {stats.get('rejected', 0)}")
    print(f"     ⚠️  Manual Review   : {stats.get('manual_review', 0)}")
    print(f"     Model Version       : {run.final_payload.get('model_version', 'N/A')}")

    # Merge decisions / scores / explanations for display
    decisions_by_id = {d["application_id"]: d for d in run.final_payload.get("decisions", [])}
    scores_by_id = {s["application_id"]: s for s in run.final_payload.get("model_scores", [])}
    expls_by_id = {e["application_id"]: e for e in run.final_payload.get("explanations", [])}

    print(f"\n  📋 INDIVIDUAL DECISIONS")
    for app_id, dec in decisions_by_id.items():
        score = scores_by_id.get(app_id, {})
        expl = expls_by_id.get(app_id, {})
        merged = {
            **dec,
            "pd_score": score.get("pd_score", 0.0),
            "fraud_flag": score.get("fraud_flag", "N/A"),
            "approved_rate": dec.get("approved_rate"),
            "top_factors": expl.get("top_factors", []),
        }
        print(_format_result(merged))

    # Adverse action notices
    notices = run.final_payload.get("adverse_action_notices", [])
    if notices:
        print(f"\n  📜 ADVERSE ACTION NOTICES ({len(notices)} generated)")
        for notice_rec in notices:
            print(f"\n  Application: {notice_rec['application_id']}")
            print("  " + "\n  ".join(notice_rec["notice"].split("\n")[:10]) + "\n  ...")

    # Pipeline stage timing
    print(f"\n  ⏱  PIPELINE STAGE TIMINGS")
    for stage in run.stages:
        status_icon = "✓" if stage.status == "success" else "✗"
        print(f"     {status_icon} {stage.stage:<30} {stage.duration_seconds:.3f}s")

    # ── Save output ──────────────────────────────────────────────────────
    if args.output:
        output_payload = {
            "run_id": run.run_id,
            "pipeline_status": run.status,
            "decision_stats": stats,
            "decisions": run.final_payload.get("decisions", []),
            "model_scores": run.final_payload.get("model_scores", []),
            "explanations": run.final_payload.get("explanations", []),
        }
        with open(args.output, "w") as f:
            json.dump(output_payload, f, indent=2, default=str)
        logger.info("Results saved to %s", args.output)
        print(f"\n  💾 Output saved to: {args.output}")

    print(f"\n{'━' * 60}\n")
    return 0


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HelixDecision — End-to-End Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Path to a JSON file containing a single applicant or a list of applicants",
    )
    parser.add_argument(
        "--batch",
        type=str,
        default=None,
        help="Path to a CSV file for batch scoring",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to write JSON output (optional)",
    )
    parser.add_argument(
        "--experiment-id",
        type=str,
        default=None,
        help="Experiment ID for champion/challenger runs",
    )
    parser.add_argument(
        "--use-challenger",
        action="store_true",
        default=False,
        help="Route traffic to challenger model",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        default="platform-default",
        help="Tenant ID for the pipeline run (required for production; defaults to 'platform-default' for local runs)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main(_parse_args()))
