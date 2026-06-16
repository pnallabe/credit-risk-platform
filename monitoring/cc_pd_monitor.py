"""
Credit Card PD Model & Portfolio Monitor
=========================================
Provides ongoing model performance tracking, population stability,
score distribution drift, and portfolio risk reporting.

Reports generated:
  1.  PSI (Population Stability Index) — score and input feature drift
  2.  Vintage curves          — default rate by origination cohort
  3.  KS / AUROC decay        — model performance over time
  4.  Score band migration     — rolling period-over-period distribution shift
  5.  Portfolio concentration  — exposure by risk grade, product, state
  6.  Cost vs revenue tracker  — expected vs realised P&L per cohort
  7.  Policy efficiency        — approval rate, manual rate, decline breakdown
  8.  Early warning signals    — 30/60/90 DPD roll rates

Usage
-----
    python monitoring/cc_pd_monitor.py               # full report (synthetic data)
    python monitoring/cc_pd_monitor.py --export xlsx  # write Excel report
"""

from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path
from typing import Optional

from monitoring.alert_router import AlertRouter, DEFAULT_ALERT_ROUTER

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR     = PROJECT_ROOT / "data" / "raw" / "cc_pd"
REPORT_DIR   = PROJECT_ROOT / "monitoring" / "cc_pd_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── Drift / performance thresholds (PRD §4.8) ─────────────────────────────────
PSI_CRITICAL_THRESHOLD = 0.20   # PRD §4.8
AUROC_MIN_THRESHOLD    = 0.70   # PRD §4.8
KS_MIN_THRESHOLD       = 0.30   # PRD §4.8
DR_MAX_THRESHOLD       = 0.12   # PRD §4.8


# ── PSI ────────────────────────────────────────────────────────────────────────

def compute_psi(
    reference: np.ndarray,
    current:   np.ndarray,
    n_bins:    int = 10,
    eps:       float = 1e-6,
) -> tuple[float, pd.DataFrame]:
    """
    Population Stability Index.

    Interpretation:
      PSI < 0.10  → No significant change
      PSI  0.10 – 0.25 → Some shift; monitor closely
      PSI > 0.25  → Significant population shift; investigate / retrain
    """
    bins = np.percentile(reference, np.linspace(0, 100, n_bins + 1))
    bins[0] -= 1e-9
    bins[-1] += 1e-9

    ref_counts  = np.histogram(reference, bins=bins)[0]
    curr_counts = np.histogram(current,   bins=bins)[0]

    ref_pct  = ref_counts  / ref_counts.sum()
    curr_pct = curr_counts / curr_counts.sum()

    ref_pct[ref_pct == 0]   = eps
    curr_pct[curr_pct == 0] = eps

    psi_per_bin = (curr_pct - ref_pct) * np.log(curr_pct / ref_pct)
    psi = psi_per_bin.sum()

    tbl = pd.DataFrame({
        "bin_lower" : bins[:-1].round(4),
        "bin_upper" : bins[1:].round(4),
        "ref_count" : ref_counts,
        "curr_count": curr_counts,
        "ref_pct"   : ref_pct.round(4),
        "curr_pct"  : curr_pct.round(4),
        "psi_contrib": psi_per_bin.round(4),
    })
    return float(psi), tbl


# ── Vintage curve ──────────────────────────────────────────────────────────────

def compute_vintage_curves(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute cumulative default rate by origination month cohort.
    Expects:  orig_date (datetime), months_on_book (float), default_flag (int)
    """
    df = df.copy()
    df["orig_month"] = df["orig_date"].dt.to_period("M")
    vintage = (
        df.groupby("orig_month")
          .agg(
              accounts   = ("default_flag", "count"),
              defaults   = ("default_flag", "sum"),
              avg_mob    = ("months_on_book", "mean"),
              avg_fico   = ("fico_score", "mean"),
              avg_cl     = ("credit_limit", "mean"),
          )
          .reset_index()
    )
    vintage["cumulative_dr"] = vintage["defaults"] / vintage["accounts"]
    vintage["orig_month"]    = vintage["orig_month"].astype(str)
    return vintage


# ── Score band distribution ────────────────────────────────────────────────────

def score_band_distribution(
    pd_scores: np.ndarray,
    n_bands:   int = 10,
    labels:    Optional[list] = None,
) -> pd.DataFrame:
    if labels is None:
        labels = [f"Band {i+1}" for i in range(n_bands)]
    bins   = np.percentile(pd_scores, np.linspace(0, 100, n_bands + 1))
    bins[0] -= 1e-9; bins[-1] += 1e-9
    counts  = np.histogram(pd_scores, bins=bins)[0]
    return pd.DataFrame({
        "band"      : labels[:len(counts)],
        "min_score" : bins[:-1].round(4),
        "max_score" : bins[1:].round(4),
        "count"     : counts,
        "pct"       : (counts / counts.sum() * 100).round(2),
    })


# ── KS and AUROC over rolling windows ─────────────────────────────────────────

def rolling_performance(df: pd.DataFrame, window_months: int = 3) -> pd.DataFrame:
    """
    Compute KS and AUROC for each rolling 3-month window in the dataset.
    Requires columns:  orig_date, true_pd (or pd_score), default_flag
    """
    pd_col = "true_pd" if "true_pd" in df.columns else "pd_score"
    df = df.copy()
    df["period"] = df["orig_date"].dt.to_period("M")
    periods = sorted(df["period"].unique())

    rows = []
    for i, p in enumerate(periods):
        if i < window_months - 1:
            continue
        window = [periods[j] for j in range(i - window_months + 1, i + 1)]
        sub = df[df["period"].isin(window)]
        if sub["default_flag"].sum() < 10 or sub["default_flag"].nunique() < 2:
            continue
        y_true = sub["default_flag"].values
        y_prob = sub[pd_col].values
        auc    = roc_auc_score(y_true, y_prob)
        probs1 = y_prob[y_true == 1]
        probs0 = y_prob[y_true == 0]
        ks     = abs(
            np.sort(probs1).searchsorted(np.sort(probs0), side="right") / len(probs1)
            - np.arange(len(probs0)) / len(probs0)
        ).max() if len(probs1) > 0 and len(probs0) > 0 else 0.0

        rows.append({
            "end_period"  : str(p),
            "n_accounts"  : len(sub),
            "default_rate": float(y_true.mean()),
            "auroc"       : round(auc, 4),
            "ks"          : round(ks, 4),
        })
    return pd.DataFrame(rows)


# ── Roll rate analysis (DPD buckets) ──────────────────────────────────────────

def simulate_roll_rates(df: pd.DataFrame, rng_seed: int = 42) -> pd.DataFrame:
    """
    Simulate 30/60/90/120+ DPD roll rates from missed payment features.
    Returns a transition matrix summarising early delinquency behaviour.
    """
    rng = np.random.default_rng(rng_seed)
    n   = len(df)

    miss         = df["num_missed_pmts_12m"].values.astype(float)
    util         = df["avg_utilization_12m"].values.astype(float)
    fico_norm    = (df["fico_score"].values.astype(float) - 300) / 550  # 0-1

    p_30dpd  = np.clip(0.02 + 0.12 * miss / 12 + 0.05 * util - 0.04 * fico_norm, 0, 1)
    p_60dpd  = np.clip(p_30dpd * (0.30 + 0.20 * util), 0, 1)
    p_90dpd  = np.clip(p_60dpd * (0.45 + 0.15 * util), 0, 1)
    p_120dpd = np.clip(p_90dpd * 0.65, 0, 1)

    dpd30  = rng.binomial(1, p_30dpd, n)
    dpd60  = rng.binomial(1, p_60dpd, n) * dpd30
    dpd90  = rng.binomial(1, p_90dpd, n) * dpd60
    dpd120 = rng.binomial(1, p_120dpd, n) * dpd90

    return pd.DataFrame({
        "dpd30_rate" : [dpd30.mean()],
        "dpd60_rate" : [dpd60.mean()],
        "dpd90_rate" : [dpd90.mean()],
        "dpd120_rate": [dpd120.mean()],
        "roll_30_60" : [dpd60.sum() / max(dpd30.sum(), 1)],
        "roll_60_90" : [dpd90.sum() / max(dpd60.sum(), 1)],
        "roll_90_120": [dpd120.sum() / max(dpd90.sum(), 1)],
    }).round(4)


# ── Portfolio concentration risk ───────────────────────────────────────────────

def portfolio_concentration(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Summarise portfolio exposure by key dimensions."""
    pd_col = "true_pd" if "true_pd" in df.columns else "pd_score"
    dims   = {}

    for col in ("risk_grade", "product", "state"):
        if col not in df.columns:
            continue
        grp = (
            df.groupby(col)
              .agg(
                  accounts     = ("default_flag", "count"),
                  defaults     = ("default_flag", "sum"),
                  total_cl     = ("credit_limit", "sum"),
                  avg_pd       = (pd_col, "mean"),
                  avg_fico     = ("fico_score", "mean"),
              )
              .reset_index()
        )
        grp["default_rate"]   = grp["defaults"] / grp["accounts"]
        grp["pct_of_book"]    = grp["accounts"] / grp["accounts"].sum() * 100
        grp["pct_of_exposure"]= grp["total_cl"] / grp["total_cl"].sum() * 100
        grp = grp.sort_values("total_cl", ascending=False)
        dims[col] = grp
    return dims


# ── Cost vs revenue tracker ────────────────────────────────────────────────────

def cost_revenue_report(train_df: pd.DataFrame, cost_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge training spine with cost ledger and summarise P&L by risk grade.
    """
    if "account_id" not in train_df.columns or "account_id" not in cost_df.columns:
        return pd.DataFrame()

    merged = train_df[["account_id", "risk_grade", "default_flag", "credit_limit"]].merge(
        cost_df[["account_id", "total_cost_annual", "total_revenue_12m",
                 "net_income_12m", "expected_loss", "ead"]],
        on="account_id", how="inner"
    )
    grp = (
        merged.groupby("risk_grade")
              .agg(
                  accounts      = ("account_id", "count"),
                  total_rev     = ("total_revenue_12m", "sum"),
                  total_cost    = ("total_cost_annual", "sum"),
                  total_el      = ("expected_loss", "sum"),
                  total_ni      = ("net_income_12m", "sum"),
                  total_ead     = ("ead", "sum"),
                  default_rate  = ("default_flag", "mean"),
              )
              .reset_index()
    )
    grp["avg_rev_per_acct"]  = grp["total_rev"]  / grp["accounts"]
    grp["avg_cost_per_acct"] = grp["total_cost"] / grp["accounts"]
    grp["avg_ni_per_acct"]   = grp["total_ni"]   / grp["accounts"]
    grp["roi"]               = grp["total_ni"]   / grp["total_cost"].clip(1)
    grp["loss_rate"]         = grp["total_el"]   / grp["total_ead"].clip(1)
    return grp.round(2)


# ── Plotting helpers ───────────────────────────────────────────────────────────

def plot_vintage_curves(vintage_df: pd.DataFrame, path: Path) -> None:
    top_cohorts = vintage_df.sort_values("accounts", ascending=False).head(12)
    fig, ax = plt.subplots(figsize=(11, 6))
    for _, row in top_cohorts.iterrows():
        ax.bar(row["orig_month"], row["cumulative_dr"] * 100, color="steelblue", alpha=0.7)
    ax.set_xlabel("Origination Month")
    ax.set_ylabel("Cumulative Default Rate (%)")
    ax.set_title("Vintage Default Rates by Origination Cohort")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_score_distribution(dist_df: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(dist_df["band"], dist_df["pct"], color="darkorange", alpha=0.8)
    ax.set_xlabel("Score Band")
    ax.set_ylabel("% of Portfolio")
    ax.set_title("PD Score Distribution")
    ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_rolling_perf(perf_df: pd.DataFrame, path: Path) -> None:
    if perf_df.empty:
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax1.plot(perf_df["end_period"], perf_df["auroc"], marker="o", color="steelblue")
    ax1.axhline(0.70, color="red", linestyle="--", label="Min AUROC = 0.70")
    ax1.set_ylabel("AUROC")
    ax1.set_title("Rolling Model Performance (3-month window)")
    ax1.legend()

    ax2.plot(perf_df["end_period"], perf_df["ks"], marker="s", color="darkorange")
    ax2.axhline(0.30, color="red", linestyle="--", label="Min KS = 0.30")
    ax2.set_ylabel("KS Statistic")
    ax2.tick_params(axis="x", rotation=45)
    ax2.legend()

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ── Full monitoring run ────────────────────────────────────────────────────────

def run_monitoring(
    sample: int = 200_000,
    export_xlsx: bool = False,
    alert_router: AlertRouter | None = None,
) -> dict:
    """Run the full CC PD monitoring pipeline.

    Parameters
    ----------
    sample:
        Number of records to sub-sample for fast monitoring runs.
    export_xlsx:
        If True, write the report to an Excel file under ``REPORT_DIR``.
    alert_router:
        Optional :class:`~monitoring.alert_router.AlertRouter` instance used
        to dispatch drift alerts. Defaults to ``DEFAULT_ALERT_ROUTER``.
    """
    log.info("=" * 60)
    log.info("CC PD Model & Portfolio Monitor")
    log.info("=" * 60)

    # ── Load data ──────────────────────────────────────────────────────────
    train_path = DATA_DIR / "pd_training_5m.parquet"
    cost_path  = DATA_DIR / "cost_assumptions.parquet"

    if not train_path.exists():
        log.error("Training data not found. Run generate_cc_pd_dataset.py first.")
        return {}

    log.info("Loading data …")
    df_full = pd.read_parquet(train_path)
    df_cost = pd.read_parquet(cost_path) if cost_path.exists() else pd.DataFrame()

    # Sub-sample for fast monitoring runs
    df = df_full.sample(n=min(sample, len(df_full)), random_state=42)
    log.info("  Monitoring sample: {:,} accounts".format(len(df)))

    pd_col = "true_pd" if "true_pd" in df.columns else "pd_score"

    # ── 1. PSI — score distribution ────────────────────────────────────────
    log.info("[1/7] Computing PSI (score distribution) …")
    # Simulate reference (first 50%) vs current (last 50%) cohort
    df_sorted = df.sort_values("orig_date")
    half      = len(df_sorted) // 2
    ref_scores  = df_sorted.iloc[:half][pd_col].values
    curr_scores = df_sorted.iloc[half:][pd_col].values
    psi_val, psi_tbl = compute_psi(ref_scores, curr_scores)
    psi_status = (
        "GREEN"  if psi_val < 0.10 else
        "YELLOW" if psi_val < 0.25 else "RED"
    )
    log.info("  Score PSI: %.4f (%s)", psi_val, psi_status)

    # ── 2. Vintage curves ─────────────────────────────────────────────────
    log.info("[2/7] Computing vintage default rates …")
    vintage_df = compute_vintage_curves(df)
    log.info("  Cohorts: %d  |  avg CDR: %.2f%%",
             len(vintage_df), vintage_df["cumulative_dr"].mean() * 100)

    # ── 3. Score band distribution ────────────────────────────────────────
    log.info("[3/7] Score band distribution …")
    score_dist = score_band_distribution(df[pd_col].values, n_bands=10)

    # ── 4. Rolling model performance ──────────────────────────────────────
    log.info("[4/7] Rolling AUROC / KS …")
    perf_df = rolling_performance(df, window_months=3)
    if not perf_df.empty:
        log.info("  Latest AUROC: %.4f  |  Latest KS: %.4f",
                 perf_df["auroc"].iloc[-1], perf_df["ks"].iloc[-1])

    # ── 5. Portfolio concentration ────────────────────────────────────────
    log.info("[5/7] Portfolio concentration …")
    concentration = portfolio_concentration(df)
    for dim, tbl in concentration.items():
        log.info("  %s — top-5 by exposure:\n%s",
                 dim, tbl.head(5)[["default_rate", "pct_of_book", "pct_of_exposure"]].to_string())

    # ── 6. Cost vs revenue ────────────────────────────────────────────────
    log.info("[6/7] Cost vs revenue …")
    if not df_cost.empty:
        cost_sample = df_cost.sample(n=min(sample, len(df_cost)), random_state=42)
        pnl = cost_revenue_report(df, cost_sample)
        log.info("  P&L by risk grade:\n%s", pnl[["risk_grade", "accounts",
                 "avg_rev_per_acct", "avg_cost_per_acct", "avg_ni_per_acct",
                 "roi", "loss_rate"]].to_string(index=False))
    else:
        pnl = pd.DataFrame()

    # ── 7. Roll rates ─────────────────────────────────────────────────────
    log.info("[7/7] DPD roll rates …")
    roll = simulate_roll_rates(df)
    log.info("  Roll rates:\n%s", roll.to_string(index=False))

    # ── Plots ─────────────────────────────────────────────────────────────
    log.info("Generating plots …")
    plot_vintage_curves(vintage_df, REPORT_DIR / "vintage_curves.png")
    plot_score_distribution(score_dist, REPORT_DIR / "score_distribution.png")
    plot_rolling_perf(perf_df, REPORT_DIR / "rolling_performance.png")
    log.info("  Plots saved to %s", REPORT_DIR)

    # ── Alert summary ──────────────────────────────────────────────────────
    router = alert_router or DEFAULT_ALERT_ROUTER
    alerts = []
    if psi_val >= PSI_CRITICAL_THRESHOLD:
        alerts.append(f"CRITICAL: Score PSI={psi_val:.3f} — population shift detected (threshold={PSI_CRITICAL_THRESHOLD})")
    elif psi_val >= 0.10:
        alerts.append(f"WARNING : Score PSI={psi_val:.3f} — monitor closely")
    if not perf_df.empty and perf_df["auroc"].iloc[-1] < AUROC_MIN_THRESHOLD:
        alerts.append(f"CRITICAL: AUROC={perf_df['auroc'].iloc[-1]:.3f} < {AUROC_MIN_THRESHOLD} — consider retrain")
    if not perf_df.empty and perf_df["ks"].iloc[-1] < KS_MIN_THRESHOLD:
        alerts.append(f"WARNING : KS={perf_df['ks'].iloc[-1]:.3f} < {KS_MIN_THRESHOLD}")
    dr = df["default_flag"].mean()
    if dr > DR_MAX_THRESHOLD:
        alerts.append(f"WARNING : Portfolio default rate={dr:.2%} exceeds {DR_MAX_THRESHOLD:.0%} threshold")

    log.info("\n── Monitoring Alerts ────────────────────────────────────────")
    if alerts:
        for a in alerts:
            log.warning(a)
            severity = "CRITICAL" if a.startswith("CRITICAL") else "HIGH"
            router.send_alert(
                severity=severity,
                title=f"Model Drift Detected — {severity}",
                body=a,
            )
    else:
        log.info("  All checks PASSED — no alerts.")

    # ── Optional Excel export ──────────────────────────────────────────────
    if export_xlsx:
        xlsx_path = REPORT_DIR / "cc_pd_monitoring_report.xlsx"
        try:
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
                vintage_df.to_excel(xw, sheet_name="Vintage_Curves",      index=False)
                score_dist.to_excel(xw, sheet_name="Score_Distribution",  index=False)
                psi_tbl.to_excel(   xw, sheet_name="PSI",                 index=False)
                perf_df.to_excel(   xw, sheet_name="Rolling_Performance", index=False)
                roll.to_excel(      xw, sheet_name="Roll_Rates",          index=False)
                if not pnl.empty:
                    pnl.to_excel(xw, sheet_name="PnL_By_RiskGrade",       index=False)
                for dim, tbl in concentration.items():
                    sheet = f"Concentration_{dim[:12]}"
                    tbl.to_excel(xw, sheet_name=sheet,                    index=False)
            log.info("Excel report → %s", xlsx_path)
        except ImportError:
            log.warning("openpyxl not installed; skipping Excel export.")

    return {
        "psi"           : psi_val,
        "psi_status"    : psi_status,
        "vintage_df"    : vintage_df,
        "score_dist"    : score_dist,
        "rolling_perf"  : perf_df,
        "concentration" : concentration,
        "roll_rates"    : roll,
        "pnl"           : pnl,
        "alerts"        : alerts,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CC PD Model Monitor")
    ap.add_argument("--sample",  type=int, default=200_000,
                    help="Number of records to sample for monitoring (default 200k)")
    ap.add_argument("--export",  choices=["xlsx"], default=None,
                    help="Export report format")
    args = ap.parse_args()
    run_monitoring(sample=args.sample, export_xlsx=args.export == "xlsx")
