#!/usr/bin/env python3
"""
Freddie Mac SFLLD 2024 — Fair Lending Analysis
================================================
Connects to BigQuery (project: ai-risk-workflow, dataset: freddie_mac_sflld),
loads loans originated in calendar year 2024, and runs ECOA / HMDA-style
fair lending tests using the existing ``monitoring.fair_lending`` module.

Fair Lending Metrics Computed
------------------------------
1. **Rate-Spread DIR** (Disparate Impact Ratio)
   Classifies each loan as ``STANDARD_RATE`` (≤ national median + threshold)
   or ``HIGH_COST`` (above that line).  High-cost loans are treated as the
   adverse outcome.  DI is computed per income group (ZIP-based proxy).

2. **Approval Parity / Chi-squared** — income_group vs rate_flag independence.

3. **Geographic Bias** — state-level high-cost rate flagged at 1.5σ above mean.

4. **Loan Terms Disparity Table**
   Per income group: mean rate, LTV, DTI, UPB, credit score.
   Written to stdout + CSV.

5. **First-Time Homebuyer (FTHB) Disparity**
   Separate DIR pass comparing FTHB vs non-FTHB high-cost rate.

6. **Channel Disparity**
   DIR pass comparing broker-originated vs retail-originated high-cost rate.

Income Group Proxy
-------------------
Derived from ``postal_code`` (first 3 digits = ZIP3) bucketed into five
national ZIP-income quintiles based on ACS 5-year median household income
estimates (hardcoded for portability; swap with a lookup join in production).

Quintile boundaries (ZIP3 prefix → quintile):
  Q1 (lowest income):  prefixes 200–299, 700–749   (Deep South / Appalachia)
  Q2:                  prefixes 100–199, 300–349    (Urban fringe, rural SE)
  Q3 (middle):         prefixes 350–499, 750–799    (Midwest heartland)
  Q4:                  prefixes 500–699, 800–849    (Western / Great Plains)
  Q5 (highest income): prefixes 000–099, 850–999    (Coastal metros / Mountain West)

For official production use, replace with a full ZIP→median-income join
against ACS data stored in BigQuery.

Usage
-----
    # Full run against BigQuery
    python scripts/run_freddie_fair_lending_2024.py

    # Dry-run with synthetic data (no BQ credentials needed)
    python scripts/run_freddie_fair_lending_2024.py --dry-run

    # Tighter rate-spread threshold (100 bps)
    python scripts/run_freddie_fair_lending_2024.py --rate-threshold 0.01

    # Limit rows for a quick sanity-check
    python scripts/run_freddie_fair_lending_2024.py --limit 50000

    # Save reports to a custom directory
    python scripts/run_freddie_fair_lending_2024.py --output-dir reports/fair_lending/2024

Options
-------
  --project           GCP project ID (default: ai-risk-workflow)
  --dataset           BigQuery dataset (default: freddie_mac_sflld)
  --table             Origination table (default: freddie_origination)
  --rate-threshold    Basis-points above median for HIGH_COST classification
                      expressed as a decimal (default 0.015 = 150 bps)
  --output-dir        Directory for JSON/CSV output  (default: reports/fair_lending)
  --dry-run           Use synthetic data; skip BQ calls entirely
  --limit             Max rows to fetch (0 = all rows)
  --year              Origination year to filter (default: 2024)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

# ── Project root on sys.path ──────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# ── Auto-load .env ────────────────────────────────────────────────────────────
_env_path = _ROOT / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.split("#")[0].strip().strip('"').strip("'")
                os.environ.setdefault(_k.strip(), _v)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Fair lending module ───────────────────────────────────────────────────────
from monitoring.fair_lending import analyze_fair_lending, FairLendingReport

# ── BigQuery client (optional — skipped in dry-run) ───────────────────────────
try:
    from db.bigquery_client import query_to_df as bq_query
    _BQ_AVAILABLE = True
except ImportError:
    _BQ_AVAILABLE = False
    log.warning("db.bigquery_client not importable — BQ calls will be skipped.")

# =============================================================================
# Constants
# =============================================================================

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT_ID", "ai-risk-workflow")
DEFAULT_DATASET = os.environ.get("BQ_DATASET", "freddie_mac_sflld")
DEFAULT_TABLE   = "freddie_origination"
DEFAULT_YEAR    = 2024

# ZIP3 → income quintile mapping
#  Q1 = lowest household income (most likely minority/low-income areas)
#  Q5 = highest household income
_ZIP3_QUINTILE: dict[tuple[int, int], str] = {
    (200, 299): "Q1_LOW_INCOME",
    (700, 749): "Q1_LOW_INCOME",
    (100, 199): "Q2_LOWER_MID",
    (300, 349): "Q2_LOWER_MID",
    (350, 499): "Q3_MIDDLE",
    (750, 799): "Q3_MIDDLE",
    (500, 599): "Q4_UPPER_MID",
    (800, 849): "Q4_UPPER_MID",
    (600, 699): "Q5_HIGH_INCOME",
    (850, 999): "Q5_HIGH_INCOME",
    (0,   99):  "Q5_HIGH_INCOME",
}

# Columns fetched from BigQuery
_BQ_COLUMNS = [
    "loan_sequence_number",
    "first_payment_date",       # YYYYMM integer
    "credit_score",
    "first_time_homebuyer_flag",
    "msa",
    "mi_pct",
    "number_of_units",
    "occupancy_status",
    "ocltv",
    "odti",
    "original_upb",
    "oltv",
    "original_interest_rate",
    "channel",
    "product_type",
    "property_state",
    "property_type",
    "postal_code",
    "loan_purpose",
    "original_loan_term",
    "number_of_borrowers",
    "seller_name",
]

# =============================================================================
# Helpers
# =============================================================================


def _zip3_to_income_group(postal_code: str) -> str:
    """Assign an income quintile label based on the first 3 digits of ZIP."""
    if not postal_code or str(postal_code).strip() in ("", "nan", "None"):
        return "UNKNOWN"
    try:
        z3 = int(str(postal_code).zfill(5)[:3])
    except (ValueError, TypeError):
        return "UNKNOWN"
    for (lo, hi), label in _ZIP3_QUINTILE.items():
        if lo <= z3 <= hi:
            return label
    return "Q3_MIDDLE"  # fallback for anything not mapped


def _classify_rate_flag(
    df: pd.DataFrame,
    rate_col: str = "original_interest_rate",
    threshold: float = 0.015,
) -> pd.Series:
    """
    Classify each loan as STANDARD_RATE or HIGH_COST.

    HIGH_COST is defined as: rate > (national median rate + threshold).
    We use 'APPROVE' semantics for STANDARD_RATE and treat HIGH_COST as the
    adverse outcome (equivalent to 'REJECT' for DIR computation purposes).
    """
    national_median = df[rate_col].median()
    cutoff = national_median + threshold
    log.info(
        "Rate cutoff: median=%.4f  threshold=%.4f  cutoff=%.4f",
        national_median, threshold, cutoff,
    )
    return np.where(df[rate_col] <= cutoff, "APPROVE", "REJECT").tolist()


def _add_proxies(df: pd.DataFrame, rate_threshold: float) -> pd.DataFrame:
    """Enrich origination DataFrame with fair-lending proxy columns."""
    # Income group from ZIP
    df["income_group"] = df["postal_code"].astype(str).map(_zip3_to_income_group)

    # Rate-spread decision (APPROVE = standard, REJECT = high-cost)
    df["decision"] = _classify_rate_flag(df, threshold=rate_threshold)

    # State column alias expected by fair_lending module
    df["state"] = df["property_state"]

    return df


def _compute_terms_disparity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute mean key loan terms per income_group.
    Returns a styled comparison table.
    """
    cols = [
        "income_group",
        "original_interest_rate",
        "oltv",
        "odti",
        "original_upb",
        "credit_score",
    ]
    available = [c for c in cols if c in df.columns]
    summary = (
        df[available]
        .groupby("income_group")
        .agg(
            mean_rate    =("original_interest_rate", "mean"),
            mean_ltv     =("oltv", "mean"),
            mean_dti     =("odti", "mean"),
            mean_upb     =("original_upb", "mean"),
            mean_fico    =("credit_score", "mean"),
            n_loans      =("original_interest_rate", "count"),
        )
        .reset_index()
        .sort_values("income_group")
    )
    return summary


# =============================================================================
# BigQuery loader
# =============================================================================


def _load_from_bigquery(
    project: str,
    dataset: str,
    table: str,
    year: int,
    limit: int,
) -> pd.DataFrame:
    """
    Pull 2024 originations from BigQuery.

    ``first_payment_date`` is stored as YYYYMM integer.
    2024 originations have first_payment_date in [202401, 202412].
    """
    col_clause = ", ".join(_BQ_COLUMNS)
    year_min = year * 100 + 1    # e.g., 202401
    year_max = year * 100 + 12   # e.g., 202412
    limit_clause = f"LIMIT {limit}" if limit > 0 else ""

    sql = f"""
    SELECT {col_clause}
    FROM   `{project}.{dataset}.{table}`
    WHERE  first_payment_date BETWEEN {year_min} AND {year_max}
    {limit_clause}
    """

    log.info(
        "Querying BigQuery: %s.%s.%s  (year=%d, limit=%s)",
        project, dataset, table, year, limit or "ALL",
    )
    df = bq_query(sql, project=project)
    log.info("Loaded %d rows from BigQuery.", len(df))
    return df


# =============================================================================
# Synthetic data for dry-run
# =============================================================================


def _synthesize_loans(n: int = 50_000, year: int = 2024, seed: int = 42) -> pd.DataFrame:
    """
    Generate synthetic Freddie Mac-like origination records for testing.
    Introduces a deliberate rate disparity: Q1 (low-income) loans receive
    ~50 bps higher rates on average, ensuring the test produces non-trivial
    fair lending signals without real data.
    """
    rng = np.random.default_rng(seed)

    states = [
        "CA", "TX", "FL", "NY", "PA", "IL", "OH", "GA", "NC", "MI",
        "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
    ]
    channels   = ["R", "B", "C"]          # Retail, Broker, Correspondent
    loan_purps  = ["P", "C", "N"]          # Purchase, Cashout-refi, No-cash-refi
    occupancy   = ["P", "I", "S"]          # Principal, Investor, Second
    product_type = ["FRM", "ARM"]

    # ZIP3 brackets: Q1 low-income zips, Q5 high-income zips
    q1_zips = [f"{z:03d}" + str(rng.integers(0, 100)).zfill(2) for z in rng.integers(200, 300, n)]
    q5_zips = [f"{z:03d}" + str(rng.integers(0, 100)).zfill(2) for z in rng.integers(850, 999, n)]
    q3_zips = [f"{z:03d}" + str(rng.integers(0, 100)).zfill(2) for z in rng.integers(350, 499, n)]

    # Assign each loan a ZIP from mixed distribution (40% Q1, 20% Q3, 40% Q5)
    zip_draw = rng.choice([0, 1, 2], size=n, p=[0.40, 0.20, 0.40])
    postal_codes = np.where(
        zip_draw == 0, q1_zips[:n],
        np.where(zip_draw == 1, q3_zips[:n], q5_zips[:n])
    )

    # Base interest rate: 6.5% ± noise
    base_rate = rng.normal(6.5, 0.5, n)

    # Inject 50bps premium for Q1 (low-income) loans — the "disparity to detect"
    rate_premium = np.where(zip_draw == 0, rng.normal(0.50, 0.10, n), 0.0)
    interest_rates = np.clip(base_rate + rate_premium, 3.0, 12.0)

    # Loan origination months in 2024
    months = rng.integers(202401, 202413, n)

    df = pd.DataFrame({
        "loan_sequence_number":    [f"F24{i:08d}" for i in range(n)],
        "first_payment_date":      months,
        "credit_score":            rng.integers(580, 850, n),
        "first_time_homebuyer_flag": rng.choice(["Y", "N"], size=n, p=[0.35, 0.65]),
        "msa":                     rng.integers(10000, 99999, n).astype(str),
        "mi_pct":                  np.where(rng.random(n) < 0.2, rng.uniform(0.25, 2.5, n), 0.0),
        "number_of_units":         rng.choice([1, 2, 3, 4], size=n, p=[0.85, 0.10, 0.03, 0.02]),
        "occupancy_status":        rng.choice(occupancy, n),
        "ocltv":                   rng.uniform(60, 97, n).round(2),
        "odti":                    rng.uniform(20, 50, n).round(2),
        "original_upb":            rng.uniform(60_000, 750_000, n).round(-3),
        "oltv":                    rng.uniform(60, 97, n).round(2),
        "original_interest_rate":  interest_rates.round(3),
        "channel":                 rng.choice(channels, n, p=[0.55, 0.25, 0.20]),
        "product_type":            rng.choice(product_type, n, p=[0.80, 0.20]),
        "property_state":          rng.choice(states, n),
        "property_type":           rng.choice(["SF", "CO", "MH"], n, p=[0.75, 0.20, 0.05]),
        "postal_code":             postal_codes,
        "loan_purpose":            rng.choice(loan_purps, n, p=[0.55, 0.25, 0.20]),
        "original_loan_term":      rng.choice([360, 180, 240], n, p=[0.75, 0.15, 0.10]),
        "number_of_borrowers":     rng.choice([1, 2, 3], n, p=[0.40, 0.55, 0.05]),
        "seller_name":             rng.choice(
            ["WELLS FARGO", "JPMORGAN CHASE", "BANK OF AMERICA", "UNITED WHOLESALE",
             "PENNYMAC", "LOANDEPOT", "FREEDOM MORTGAGE"],
            n,
        ),
    })

    log.info("Synthesised %d dry-run loan records for year=%d.", n, year)
    return df


# =============================================================================
# Report writers
# =============================================================================


def _save_report(report: FairLendingReport, label: str, output_dir: Path) -> None:
    """Persist a FairLendingReport as JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"fair_lending_{label}_{timestamp}.json"
    with open(out_path, "w") as fh:
        import dataclasses
        json.dump(dataclasses.asdict(report), fh, indent=2, default=str)
    log.info("Saved report → %s", out_path)


def _save_terms_table(table: pd.DataFrame, label: str, output_dir: Path) -> None:
    """Persist the loan-terms disparity table as CSV."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"terms_disparity_{label}_{timestamp}.csv"
    table.to_csv(out_path, index=False)
    log.info("Saved terms table → %s", out_path)


def _print_terms_table(table: pd.DataFrame, title: str) -> None:
    """Pretty-print the disparity table."""
    print(f"\n{'='*72}")
    print(f"  {title}")
    print(f"{'='*72}")
    with pd.option_context("display.float_format", "{:.4f}".format, "display.max_columns", 20):
        print(table.to_string(index=False))
    print(f"{'='*72}\n")


# =============================================================================
# Main analysis pipeline
# =============================================================================


def _print_report(report: FairLendingReport, label: str) -> None:
    print(f"\n{'─'*72}")
    print(f"  FAIR LENDING REPORT: {label}")
    print(f"{'─'*72}")
    print(report.summary_text)
    if report.proxy_applied:
        print(f"  [Proxy methodology: {report.proxy_methodology}]")
    print(f"{'─'*72}\n")


def run_analysis(
    df: pd.DataFrame,
    rate_threshold: float,
    output_dir: Path,
    year: int,
    dry_run: bool,
) -> dict:
    """
    Full fair lending analysis pipeline.

    Returns a summary dict with pass/fail status for all tests.
    """
    results: dict = {"year": year, "n_loans": len(df), "tests": {}}

    # ── 1. Enrich with proxy columns ─────────────────────────────────────────
    df = _add_proxies(df, rate_threshold)
    log.info(
        "Income group distribution:\n%s",
        df["income_group"].value_counts().to_string()
    )
    log.info(
        "Rate flag distribution:\n%s",
        df["decision"].value_counts().to_string()
    )

    # ── 2. Loan terms disparity table ────────────────────────────────────────
    terms_table = _compute_terms_disparity(df)
    _print_terms_table(terms_table, f"Loan Terms Disparity by Income Group — {year}")
    _save_terms_table(terms_table, "income_group", output_dir)

    # ── 3(a). DIR: Low-income (Q1) vs High-income (Q5) ───────────────────────
    # Filter to just the two groups being compared so the DIR targets Q1 exactly.
    log.info("Running fair lending analysis: Q1_LOW_INCOME vs Q5_HIGH_INCOME …")
    df_q1_q5 = df[df["income_group"].isin(["Q1_LOW_INCOME", "Q5_HIGH_INCOME"])].copy()
    if len(df_q1_q5) >= 100:
        report_q1_q5 = analyze_fair_lending(
            decisions_df    = df_q1_q5,
            protected_col   = "income_group",
            control_group   = "Q5_HIGH_INCOME",
            decision_col    = "decision",
            state_col       = "state",
            output_dir      = str(output_dir),
            from_date       = f"{year}-01-01",
            to_date         = f"{year}-12-31",
        )
        _print_report(report_q1_q5, "Rate-Spread DIR: Q1_LOW_INCOME vs Q5_HIGH_INCOME")
        _save_report(report_q1_q5, "q1_vs_q5", output_dir)
        results["tests"]["dir_q1_vs_q5"] = {
            "dir_score":    report_q1_q5.dir_score,
            "dir_flag":     report_q1_q5.dir_flag,
            "parity_flag":  report_q1_q5.approval_parity_flag,
            "geo_flags":    report_q1_q5.geographic_flags,
            "pass":         not (report_q1_q5.dir_flag or report_q1_q5.approval_parity_flag),
        }
    else:
        log.warning("Insufficient Q1/Q5 data (%d rows) — skipping Q1 vs Q5 test.", len(df_q1_q5))

    # ── 3(b). DIR: Q2_LOWER_MID vs Q5_HIGH_INCOME ────────────────────────────
    log.info("Running fair lending analysis: Q2_LOWER_MID vs Q5_HIGH_INCOME …")
    df_q2_q5 = df[df["income_group"].isin(["Q2_LOWER_MID", "Q5_HIGH_INCOME"])].copy()
    if len(df_q2_q5) >= 100 and "Q2_LOWER_MID" in df_q2_q5["income_group"].values:
        report_q2_q5 = analyze_fair_lending(
            decisions_df    = df_q2_q5,
            protected_col   = "income_group",
            control_group   = "Q5_HIGH_INCOME",
            decision_col    = "decision",
            state_col       = "state",
            output_dir      = str(output_dir),
            from_date       = f"{year}-01-01",
            to_date         = f"{year}-12-31",
        )
        _print_report(report_q2_q5, "Rate-Spread DIR: Q2_LOWER_MID vs Q5_HIGH_INCOME")
        _save_report(report_q2_q5, "q2_vs_q5", output_dir)
        results["tests"]["dir_q2_vs_q5"] = {
            "dir_score":    report_q2_q5.dir_score,
            "dir_flag":     report_q2_q5.dir_flag,
            "parity_flag":  report_q2_q5.approval_parity_flag,
            "pass":         not (report_q2_q5.dir_flag or report_q2_q5.approval_parity_flag),
        }
    else:
        log.warning(
            "Insufficient Q2_LOWER_MID data in dataset — skipping Q2 vs Q5 test.  "
            "This is expected: Freddie Mac SFLLD ZIP coverage may vary."
        )

    # ── 4. FTHB disparity ────────────────────────────────────────────────────
    if "first_time_homebuyer_flag" in df.columns:
        log.info("Running FTHB fair lending analysis …")
        fthb_df = df[df["first_time_homebuyer_flag"].isin(["Y", "N"])].copy()
        fthb_groups = fthb_df["first_time_homebuyer_flag"].unique()
        if len(fthb_df) < 200 or not all(g in fthb_groups for g in ["Y", "N"]):
            log.warning(
                "Insufficient FTHB data (n=%d, groups=%s) — skipping FTHB test.",
                len(fthb_df), list(fthb_groups),
            )
        else:
            report_fthb = analyze_fair_lending(
                decisions_df    = fthb_df,
                protected_col   = "first_time_homebuyer_flag",
                control_group   = "N",
                decision_col    = "decision",
                state_col       = "state",
                output_dir      = str(output_dir),
                from_date       = f"{year}-01-01",
                to_date         = f"{year}-12-31",
            )
            _print_report(report_fthb, "Rate-Spread DIR: First-Time Homebuyer (Y vs N)")
            _save_report(report_fthb, "fthb_vs_non_fthb", output_dir)
            results["tests"]["dir_fthb"] = {
                "dir_score":    report_fthb.dir_score,
                "dir_flag":     report_fthb.dir_flag,
                "parity_flag":  report_fthb.approval_parity_flag,
                "pass":         not (report_fthb.dir_flag or report_fthb.approval_parity_flag),
            }

    # ── 5. Channel disparity: Broker vs Retail ───────────────────────────────
    if "channel" in df.columns:
        log.info("Running channel fair lending analysis (Broker vs Retail) …")
        channel_df = df[df["channel"].isin(["R", "B"])].copy()
        channel_groups = channel_df["channel"].unique()
        if len(channel_df) < 200 or not all(g in channel_groups for g in ["R", "B"]):
            log.warning(
                "Insufficient channel data (n=%d, groups=%s) — skipping channel test.",
                len(channel_df), list(channel_groups),
            )
        else:
            report_channel = analyze_fair_lending(
                decisions_df    = channel_df,
                protected_col   = "channel",
                control_group   = "R",
                decision_col    = "decision",
                state_col       = "state",
                output_dir      = str(output_dir),
                from_date       = f"{year}-01-01",
                to_date         = f"{year}-12-31",
            )
            _print_report(report_channel, "Rate-Spread DIR: Broker (B) vs Retail (R)")
            _save_report(report_channel, "broker_vs_retail", output_dir)
            results["tests"]["dir_broker_vs_retail"] = {
                "dir_score":    report_channel.dir_score,
                "dir_flag":     report_channel.dir_flag,
                "parity_flag":  report_channel.approval_parity_flag,
                "pass":         not (report_channel.dir_flag or report_channel.approval_parity_flag),
            }

    # ── 6. Overall pass/fail summary ─────────────────────────────────────────
    all_pass = all(t.get("pass", True) for t in results["tests"].values())
    results["overall_pass"]  = all_pass
    results["run_timestamp"] = datetime.now(timezone.utc).isoformat()
    results["mode"]          = "dry_run" if dry_run else "live_bigquery"
    results["rate_threshold_bps"] = int(rate_threshold * 10_000)

    # Persist master summary
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    summary_path = output_dir / f"fair_lending_summary_{year}_{ts}.json"
    with open(summary_path, "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    log.info("Master summary → %s", summary_path)

    # ── Final banner ──────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print(f"  FAIR LENDING SUMMARY — Freddie Mac SFLLD {year}")
    print(f"  Loans analysed : {len(df):,}")
    print(f"  Rate threshold : {int(rate_threshold * 10_000)} bps above median")
    print(f"  Mode           : {'dry-run (synthetic data)' if dry_run else 'LIVE BigQuery'}")
    print("=" * 72)
    for test_name, res in results["tests"].items():
        status = "✓ PASS" if res.get("pass") else "⚠ FAIL"
        dir_val = f"DIR={res['dir_score']:.4f}" if res.get("dir_score") is not None else "DIR=N/A"
        print(f"  {status}  {test_name:<35s}  {dir_val}")
    print("=" * 72)
    if all_pass:
        print("  ✓  ALL FAIR LENDING TESTS PASSED")
    else:
        print("  ⚠  ONE OR MORE FAIR LENDING TESTS FLAGGED — review reports above")
    print("=" * 72 + "\n")

    return results


# =============================================================================
# CLI
# =============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Freddie Mac SFLLD 2024 — Fair Lending Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--project",         default=DEFAULT_PROJECT)
    p.add_argument("--dataset",         default=DEFAULT_DATASET)
    p.add_argument("--table",           default=DEFAULT_TABLE)
    p.add_argument("--year",            type=int,   default=DEFAULT_YEAR)
    p.add_argument("--rate-threshold",  type=float, default=0.015,
                   help="Rate spread threshold above median (default 0.015 = 150 bps)")
    p.add_argument("--output-dir",      default="reports/fair_lending",
                   help="Directory for JSON / CSV reports")
    p.add_argument("--dry-run",         action="store_true",
                   help="Use synthetic data; skip BigQuery calls")
    p.add_argument("--limit",           type=int,   default=0,
                   help="Max rows to load from BQ (0 = no limit)")
    p.add_argument("--synth-n",         type=int,   default=50_000,
                   help="Number of synthetic rows for dry-run (default 50,000)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)

    # ── Load data ─────────────────────────────────────────────────────────────
    if args.dry_run:
        log.info("DRY-RUN mode — synthesising %d loans for year=%d.", args.synth_n, args.year)
        df = _synthesize_loans(n=args.synth_n, year=args.year)
    else:
        if not _BQ_AVAILABLE:
            log.error(
                "BigQuery client not available.  "
                "Install with: pip install google-cloud-bigquery pyarrow\n"
                "Or use --dry-run to test with synthetic data."
            )
            return 1
        try:
            df = _load_from_bigquery(
                project = args.project,
                dataset = args.dataset,
                table   = args.table,
                year    = args.year,
                limit   = args.limit,
            )
        except Exception as exc:
            log.error("Failed to load data from BigQuery: %s", exc)
            log.info("Tip: verify GCP credentials with `gcloud auth application-default login`")
            return 1

    if df.empty:
        log.warning(
            "No %d loans found in %s.%s.%s — checking for the most recent "
            "available year to fall back to …",
            args.year, args.project, args.dataset, args.table,
        )
        if not args.dry_run and _BQ_AVAILABLE:
            try:
                # Find the most recent year with >100K loans (fully-populated vintage)
                fallback_sql = f"""
                    SELECT
                        CAST(FLOOR(first_payment_date / 100) AS INT64) AS yr,
                        COUNT(*) AS n
                    FROM `{args.project}.{args.dataset}.{args.table}`
                    GROUP BY yr
                    ORDER BY yr DESC
                """
                fb = bq_query(fallback_sql, project=args.project)
                complete = fb[fb["n"] > 100_000].sort_values("yr", ascending=False)
                if complete.empty:
                    complete = fb.sort_values("n", ascending=False)
                latest_year = int(complete.iloc[0]["yr"])
                n_loans_in_year = int(complete.iloc[0]["n"])
                log.warning(
                    "2024 data not yet in BigQuery. "
                    "Most recent complete vintage: %d (%d loans). "
                    "Re-running with --year %d …",
                    latest_year, n_loans_in_year, latest_year,
                )
                df = _load_from_bigquery(
                    project = args.project,
                    dataset = args.dataset,
                    table   = args.table,
                    year    = latest_year,
                    limit   = args.limit,
                )
                args.year = latest_year
                log.info(
                    "NOTE: When 2024 Freddie Mac SFLLD data is available, load it with:\n"
                    "  python scripts/load_freddie_to_bigquery.py\n"
                    "Then re-run:  python scripts/run_freddie_fair_lending_2024.py --year 2024"
                )
            except Exception as exc:
                log.error("Fallback year detection failed: %s", exc)
        if df.empty:
            log.error("No data available. Use --dry-run for synthetic data testing.")
            return 0

    # ── Run analysis ──────────────────────────────────────────────────────────
    results = run_analysis(
        df             = df,
        rate_threshold = args.rate_threshold,
        output_dir     = output_dir,
        year           = args.year,
        dry_run        = args.dry_run,
    )

    return 0 if results.get("overall_pass") else 1


if __name__ == "__main__":
    sys.exit(main())
