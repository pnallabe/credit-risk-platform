"""
CC Originations Valuation Pipeline — Section 19.11
====================================================
Orchestration script: BQ pull → CNPV batch → policy report → monitor run.

Usage
-----
    # Evaluate current month-to-date origination cohort
    python scripts/run_cc_valuation_pipeline.py --period mtd

    # Evaluate a specific date range
    python scripts/run_cc_valuation_pipeline.py --date-from 2026-03-01 --date-to 2026-04-01

    # Override scenarios weights and capital buffer
    python scripts/run_cc_valuation_pipeline.py --period mtd --cet1-buffer 400000000

    # Dry run (no BigQuery — uses Parquet fallback)
    python scripts/run_cc_valuation_pipeline.py --period mtd --no-bq
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Make repo root importable
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

import pandas as pd

from decision_engine.cc_origination_policy import (
    load_applicant_cohort_from_bq,
    run_batch_valuation,
)
from models.pricing.scenario_config import CC_SCENARIOS
from monitoring.cc_valuation_monitor import CCValuationMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cc_valuation_pipeline")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

BQ_PROJECT = os.getenv("GCP_PROJECT_ID", "ai-risk-workflow")
BQ_DATASET = os.getenv("BQ_DATASET",     "credit_risk_model_dev")
CET1_BUFFER = float(os.getenv("CET1_BUFFER_AVAILABLE_USD", "500000000"))
PARQUET_ROOT = _REPO_ROOT / "data" / "cc_analytics"
REPORT_DIR   = _REPO_ROOT / "reports" / "cc_valuation"

# Parquet fallback: approx 2 000 rows for demo / CI
_PARQUET_COHORT_LIMIT = 2_000
_BQ_COHORT_LIMIT = 50_000


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def _mtd_dates() -> tuple[str, str]:
    today = date.today()
    return today.replace(day=1).isoformat(), today.isoformat()


def _resolve_dates(period: str, date_from: str | None, date_to: str | None) -> tuple[str, str]:
    if date_from and date_to:
        return date_from, date_to
    if period == "mtd":
        return _mtd_dates()
    if period == "last_month":
        today = date.today()
        first_of_month = today.replace(day=1)
        last_month_end = first_of_month - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)
        return last_month_start.isoformat(), first_of_month.isoformat()
    raise ValueError(f"Unknown period '{period}'; use mtd, last_month, or --date-from/--date-to")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_from_bq(
    project: str,
    dataset: str,
    date_from: str,
    date_to: str,
    limit: int,
) -> pd.DataFrame:
    """Load cohort from BigQuery."""
    try:
        from google.cloud import bigquery
        client = bigquery.Client(project=project)
        logger.info("Loading cohort from BigQuery: %s.%s [%s → %s]", project, dataset, date_from, date_to)
        df = load_applicant_cohort_from_bq(client, project, dataset, date_from, date_to, limit=limit)
        logger.info("Loaded %d applicants from BigQuery", len(df))
        return df
    except ImportError:
        logger.warning("google-cloud-bigquery not installed; falling back to Parquet")
        return _load_from_parquet()
    except Exception as exc:
        logger.warning("BigQuery load failed (%s); falling back to Parquet", exc)
        return _load_from_parquet()


def _load_from_parquet() -> pd.DataFrame:
    """Load a demo cohort from local Parquet files (fallback)."""
    orig_path = PARQUET_ROOT / "cc_originations.parquet"
    cust_path = PARQUET_ROOT / "cc_customers.parquet"
    stmt_path = PARQUET_ROOT / "cc_monthly_statements.parquet"

    if not orig_path.exists():
        logger.warning("Parquet fallback not found at %s. Generating synthetic demo data.", PARQUET_ROOT)
        return _synthetic_demo_cohort()

    df_orig = pd.read_parquet(orig_path).head(_PARQUET_COHORT_LIMIT)
    df_cust = pd.read_parquet(cust_path)[["customer_id", "income_annual_usd", "thin_file"]] \
        if cust_path.exists() else pd.DataFrame()

    if not df_cust.empty:
        df_orig = df_orig.merge(df_cust, on="customer_id", how="left")

    # Derive PD score proxy
    def _pd_proxy(score: float) -> float:
        if score >= 720: return 0.008
        if score >= 660: return 0.022
        if score >= 580: return 0.048
        return 0.085

    df_orig["pd_score"]              = df_orig.get("bureau_score_at_orig", pd.Series([680] * len(df_orig))).apply(_pd_proxy)
    df_orig["monthly_spend_estimated"] = df_orig.get("purchase_volume_usd", pd.Series([650] * len(df_orig)))
    df_orig["expected_utilisation"]  = df_orig.get("utilization_rate", pd.Series([0.45] * len(df_orig)))
    df_orig["risk_segment"]          = df_orig.get("bureau_score_at_orig", pd.Series([680] * len(df_orig))).apply(
        lambda s: "prime" if s >= 720 else ("near_prime" if s >= 660 else ("subprime" if s >= 580 else "thin_file"))
    )
    df_orig["application_id"]        = df_orig.get("origination_id", df_orig.index.astype(str))
    df_orig["apr_offered"]           = df_orig.get("apr_purchase", 0.2199)
    df_orig["annual_fee"]            = df_orig.get("annual_fee_usd", 0.0)
    df_orig["requested_credit_limit"] = df_orig.get("credit_limit_usd", 5_000)
    df_orig["interchange_rate"]      = 0.0190
    df_orig["rewards_rate"]          = 0.0150
    df_orig["acquisition_cost"]      = 115.0

    logger.info("Loaded %d applicants from Parquet fallback", len(df_orig))
    return df_orig


def _synthetic_demo_cohort(n: int = 500) -> pd.DataFrame:
    """Generate a small synthetic cohort for testing when no data is available."""
    import numpy as np
    rng = np.random.default_rng(42)
    scores = rng.integers(560, 820, n)
    return pd.DataFrame({
        "application_id":         [f"DEMO_{i:05d}" for i in range(n)],
        "product_id":             rng.choice(["cash_back_everyday", "travel_rewards", "classic_unsecured"], n),
        "bureau_score_at_orig":   scores,
        "requested_credit_limit": rng.integers(1_500, 15_000, n).astype(float),
        "apr_offered":            rng.uniform(0.15, 0.29, n).round(4),
        "annual_fee":             rng.choice([0, 0, 0, 95, 450], n).astype(float),
        "interchange_rate":       0.0190,
        "rewards_rate":           0.0150,
        "monthly_spend_estimated": rng.integers(300, 2_000, n).astype(float),
        "expected_utilisation":   rng.uniform(0.20, 0.80, n).round(2),
        "acquisition_cost":       rng.choice([95, 115, 130, 180], n).astype(float),
        "pd_score":               pd.Series(scores).apply(
            lambda s: 0.008 if s >= 720 else (0.022 if s >= 660 else (0.048 if s >= 580 else 0.085))
        ),
        "risk_segment":           pd.Series(scores).apply(
            lambda s: "prime" if s >= 720 else ("near_prime" if s >= 660 else ("subprime" if s >= 580 else "thin_file"))
        ),
        "channel": rng.choice(["digital", "branch", "partner"], n),
    })


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def _write_report(result: dict, date_from: str, date_to: str, report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = report_dir / f"cc_valuation_{date_from}_{date_to}_{now}.json"

    # Truncate applicant_results to first 200 rows in the report (can be large)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {"from": date_from, "to": date_to},
        "portfolio_summary": result.get("portfolio_summary", {}),
        "scenario_weights_used": result.get("scenario_weights_used", {}),
        "cet1_buffer_input": result.get("cet1_buffer_input"),
        "sample_applicant_results": result.get("applicant_results", [])[:200],
    }

    report_path.write_text(json.dumps(output, indent=2, default=str))
    logger.info("Report written to %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run_pipeline(
    period: str = "mtd",
    date_from: str | None = None,
    date_to: str | None = None,
    use_bq: bool = True,
    cet1_buffer: float = CET1_BUFFER,
    project: str = BQ_PROJECT,
    dataset: str = BQ_DATASET,
    write_report: bool = True,
) -> dict:
    """Run the full CC originations valuation pipeline.

    Returns
    -------
    dict — combined batch valuation result + monitor alerts.
    """
    df, dt = _resolve_dates(period, date_from, date_to)
    logger.info("CC Valuation Pipeline — period=%s [%s → %s]", period, df, dt)

    # 1. Load data
    if use_bq:
        cohort = _load_from_bq(project, dataset, df, dt, limit=_BQ_COHORT_LIMIT)
    else:
        cohort = _load_from_parquet()

    if cohort.empty:
        logger.error("No applicant data loaded — aborting pipeline")
        return {"error": "No applicant data available"}

    # 2. Run batch CNPV valuation
    logger.info("Running batch CNPV valuation on %d applicants...", len(cohort))
    result = run_batch_valuation(cohort, cet1_buffer_available=cet1_buffer)

    if "error" in result:
        logger.error("Batch valuation failed: %s", result["error"])
        return result

    summary = result["portfolio_summary"]
    logger.info(
        "Valuation complete — approve_rate=%.1f%%, expected_cnpv=$%.0f, capital_consumed=$%,.0f",
        summary.get("approve_rate", 0) * 100,
        summary.get("expected_portfolio_cnpv", 0),
        summary.get("capital_consumed", 0),
    )

    # 3. Run monitors
    df_results = pd.DataFrame(result.get("applicant_results", []))
    df_declines = df_results[df_results.get("acquisition_signal", pd.Series([])) == "DECLINE"] \
        if not df_results.empty else pd.DataFrame()

    monitor = CCValuationMonitor(cet1_buffer_available=cet1_buffer)
    alerts = monitor.run_all(
        df_batch_results=df_results if not df_results.empty else None,
        capital_consumed=summary.get("capital_consumed", 0),
        df_declines=df_declines if not df_declines.empty else None,
    )

    result["monitor_alerts"] = [
        {
            "monitor_name": a.monitor_name,
            "passed": a.passed,
            "alert_level": a.alert_level,
            "message": a.message,
            "metric_value": a.metric_value,
            "threshold": a.threshold,
            "checked_at": a.checked_at,
        }
        for a in alerts
    ]

    # 4. Write report
    if write_report:
        _write_report(result, df, dt, REPORT_DIR)

    # 5. Exit non-zero if any critical alerts
    critical = [a for a in alerts if a.alert_level == "CRITICAL" and not a.passed]
    if critical:
        logger.error("%d CRITICAL monitor(s) fired:", len(critical))
        for a in critical:
            logger.error("  [CRITICAL] %s: %s", a.monitor_name, a.message)

    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="CC Originations Valuation Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--period",    default="mtd", choices=["mtd", "last_month"],
                    help="Date period shortcut")
    ap.add_argument("--date-from", default=None, help="Override start date (YYYY-MM-DD)")
    ap.add_argument("--date-to",   default=None, help="Override end date (YYYY-MM-DD)")
    ap.add_argument("--no-bq",     action="store_true", help="Force Parquet fallback (no BigQuery)")
    ap.add_argument("--cet1-buffer", type=float, default=CET1_BUFFER,
                    help="CET1 capital buffer available for originations (USD)")
    ap.add_argument("--project",   default=BQ_PROJECT, help="GCP project ID")
    ap.add_argument("--dataset",   default=BQ_DATASET, help="BigQuery dataset")
    ap.add_argument("--no-report", action="store_true", help="Suppress JSON report write")
    args = ap.parse_args()

    result = run_pipeline(
        period     = args.period,
        date_from  = args.date_from,
        date_to    = args.date_to,
        use_bq     = not args.no_bq,
        cet1_buffer = args.cet1_buffer,
        project    = args.project,
        dataset    = args.dataset,
        write_report = not args.no_report,
    )

    # Print portfolio summary
    ps = result.get("portfolio_summary", {})
    if ps:
        print("\n── Portfolio Summary ─────────────────────────────────────────────")
        print(f"  Total applicants:       {ps.get('total_applicants', 0):>8,}")
        print(f"  Approve:                {ps.get('approve_count', 0):>8,}  ({ps.get('approve_rate', 0):.1%})")
        print(f"  Manage Price:           {ps.get('manage_price_count', 0):>8,}")
        print(f"  Decline:                {ps.get('decline_count', 0):>8,}")
        print(f"  Expected Portfolio CNPV: ${ps.get('expected_portfolio_cnpv', 0):>12,.2f}")
        print(f"  Avg CNPV per Approved: ${ps.get('avg_cnpv_per_approved', 0):>12,.2f}")
        print(f"  Capital Consumed:      ${ps.get('capital_consumed', 0):>12,.2f}")
        print(f"  Remaining Capital:     ${ps.get('remaining_capital', 0):>12,.2f}")
        sc = ps.get("scenario_comparison", {})
        print(f"\n  Scenario avg CNPVs:")
        print(f"    Base:       ${sc.get('base_avg_cnpv', 0):>10,.2f}")
        print(f"    Worsening:  ${sc.get('worsening_avg_cnpv', 0):>10,.2f}")
        print(f"    Recession:  ${sc.get('recession_avg_cnpv', 0):>10,.2f}")
