"""
Batch Scoring CLI
=================
Reads loan applications from Parquet/CSV, runs the full underwriting pipeline
for each row, and writes DecisionResponse fields to an output Parquet file.

Usage
-----
    python scripts/batch_score.py --input data/raw/loan_applications.parquet \
        --output data/scored/results.parquet --limit 100
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Make project root importable
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from decision_engine.engine import CreditResult, DecisionRequest, FraudResult, make_decision
from feature_pipeline.features import FeaturePipelineConfig, compute_features
from models.credit_risk.predict import predict_pd
from models.fraud_detection.predict import predict_fraud
from models.pricing.engine import PricingConfig, calculate_pricing


FEATURE_CONFIG = FeaturePipelineConfig()
PRICING_CONFIG = PricingConfig()


def _score_batch_sync(df: pd.DataFrame) -> pd.DataFrame:
    """Score a DataFrame of applications and return a results DataFrame."""
    # Compute features
    features_df = compute_features(df, FEATURE_CONFIG)

    # Fraud detection
    fraud_df = predict_fraud(features_df)

    # Credit risk
    credit_df = predict_pd(features_df)

    results = []
    for i, (_, row) in enumerate(df.iterrows()):
        start = time.perf_counter()

        fraud_prob = float(fraud_df["fraud_probability"].iloc[i])
        fraud_flag = str(fraud_df["fraud_flag"].iloc[i])
        pd_score = float(credit_df["pd_score"].iloc[i])
        pd_band = str(credit_df["pd_band"].iloc[i])

        pricing = calculate_pricing(
            pd_score=pd_score,
            fraud_flag=fraud_flag,
            loan_amount=float(row.get("loan_amount", 10000)),
            config=PRICING_CONFIG,
        )

        decision_req = DecisionRequest(
            application_id=str(row.get("application_id", f"row-{i}")),
            fraud_result=FraudResult(fraud_probability=fraud_prob, fraud_flag=fraud_flag),
            credit_result=CreditResult(pd_score=pd_score, pd_band=pd_band),
            pricing_result=pricing,
            loan_amount=float(row.get("loan_amount", 10000)),
            loan_term_months=int(row.get("loan_term_months", 36)),
            debt_to_income_ratio=float(row.get("debt_to_income_ratio", 0.3)),
            num_open_accounts=int(row.get("num_open_accounts", 2)),
            annual_income=float(row.get("annual_income", 50000)),
        )
        decision = make_decision(decision_req)
        latency_ms = int((time.perf_counter() - start) * 1000)

        results.append(
            {
                "application_id": decision.application_id,
                "decision": decision.decision,
                "recommended_rate": decision.recommended_rate,
                "reason_codes": ";".join(decision.reason_codes),
                "fraud_probability": fraud_prob,
                "pd_score": pd_score,
                "pd_band": pd_band,
                "expected_loss": pricing.expected_loss,
                "expected_profit": pricing.expected_profit,
                "profitability_flag": pricing.profitability_flag,
                "decision_latency_ms": latency_ms,
            }
        )

    return pd.DataFrame(results)


def _print_summary(results_df: pd.DataFrame) -> None:
    """Print a Rich summary table of batch scoring results."""
    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="Batch Scoring Summary", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        total = len(results_df)
        approved = (results_df["decision"] == "APPROVE").sum()
        rejected = (results_df["decision"] == "REJECT").sum()
        manual = (results_df["decision"] == "MANUAL_REVIEW").sum()
        frauds = (results_df["fraud_probability"] > 0.3).sum()
        avg_rate = results_df.loc[results_df["recommended_rate"].notna(), "recommended_rate"].mean()
        avg_pd = results_df["pd_score"].mean()
        avg_latency = results_df["decision_latency_ms"].mean()

        table.add_row("Total Applications", str(total))
        table.add_row("Approved", f"{approved} ({approved / total:.1%})")
        table.add_row("Rejected", f"{rejected} ({rejected / total:.1%})")
        table.add_row("Manual Review", f"{manual} ({manual / total:.1%})")
        table.add_row("Fraud Flag Count (prob>0.3)", str(frauds))
        table.add_row("Avg Risk Score (PD)", f"{avg_pd:.4f}")
        table.add_row("Avg Recommended Rate", f"{avg_rate:.2f}%" if not np.isnan(avg_rate) else "N/A")
        table.add_row("Avg Latency (ms)", f"{avg_latency:.1f}")

        console.print(table)
    except ImportError:
        # Fallback text summary when rich is not installed
        print("\n=== Batch Scoring Summary ===")
        total = len(results_df)
        for decision in ["APPROVE", "REJECT", "MANUAL_REVIEW"]:
            n = (results_df["decision"] == decision).sum()
            print(f"  {decision}: {n} ({n / total:.1%})")
        print(f"  Avg PD: {results_df['pd_score'].mean():.4f}")
        print(f"  Avg latency: {results_df['decision_latency_ms'].mean():.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch score loan applications")
    parser.add_argument("--input", required=True, help="Path to input Parquet or CSV file")
    parser.add_argument("--output", required=True, help="Path to write output Parquet file")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of rows (for testing)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)

    print(f"Loading applications from {input_path}...")
    if input_path.suffix.lower() == ".csv":
        df = pd.read_csv(input_path)
    else:
        df = pd.read_parquet(input_path)

    if args.limit:
        df = df.head(args.limit)
    print(f"Loaded {len(df):,} applications")

    t0 = time.perf_counter()
    results_df = _score_batch_sync(df)
    elapsed = time.perf_counter() - t0
    print(f"Scoring complete in {elapsed:.2f}s ({len(results_df)/elapsed:.0f} apps/sec)")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    results_df.to_parquet(output_path, index=False)
    print(f"Results written to {output_path}")

    _print_summary(results_df)


if __name__ == "__main__":
    main()
