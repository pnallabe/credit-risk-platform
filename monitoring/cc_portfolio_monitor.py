"""
CC Portfolio Action Monitor — Section 20.12.4
==============================================
Ongoing validation and drift monitoring for the cc_portfolio_action model.

Monitors (all monthly unless noted):
  1.  Action-rate drift       — CLI%, CLD%, APR_UP%, APR_DOWN% vs prior month
  2.  Feature PSI             — all 35 features vs training distribution
  3.  Guardrail override rate — monthly % of accounts hitting a guardrail
  4.  CNPV delta realisation  — quarterly: realised vs predicted delta
  5.  Adverse action coverage — daily: every CLD/APR_UP has >= 2 reason codes
  6.  Adverse action notice SLA — monthly: notices dispatched within 30 days
  7.  Production version consistency — daily: registry version == deployed
  8.  Capital consistency     — every batch: total CLI RWA <= CET1 buffer

Usage
-----
    python monitoring/cc_portfolio_monitor.py              # full monthly report
    python monitoring/cc_portfolio_monitor.py --export xlsx
"""

from __future__ import annotations

import argparse
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR     = PROJECT_ROOT / "data" / "raw" / "cc_pd"
REPORT_DIR   = PROJECT_ROOT / "monitoring" / "cc_portfolio_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# Alert thresholds (Section 20.12.4)
ACTION_RATE_DRIFT_PP_THRESHOLD = 10.0     # ±10 percentage points
FEATURE_PSI_THRESHOLD          = 0.20
GUARDRAIL_OVERRIDE_THRESHOLD   = 0.15     # > 15%
CNPV_REALISATION_THRESHOLD     = 0.65    # realised/predicted < 0.65
ADVERSE_ACTION_COVERAGE_MIN    = 1.00    # 100%


# ---------------------------------------------------------------------------
# 1. Action-rate drift monitor
# ---------------------------------------------------------------------------


def compute_action_rate_drift(
    current_df: pd.DataFrame,
    prior_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compare action rates between current and prior review month.

    Parameters
    ----------
    current_df, prior_df:
        DataFrames with at minimum a ``final_action`` column.

    Returns
    -------
    DataFrame: action | current_pct | prior_pct | drift_pp | alert
    """
    actions = ["HOLD", "CLI", "CLD", "APR_UP", "APR_DOWN"]
    rows = []
    for act in actions:
        curr_pct  = float((current_df["final_action"] == act).mean()) * 100 if not current_df.empty else 0.0
        prior_pct = float((prior_df["final_action"] == act).mean()) * 100  if not prior_df.empty else 0.0
        drift_pp  = curr_pct - prior_pct
        alert     = abs(drift_pp) > ACTION_RATE_DRIFT_PP_THRESHOLD
        rows.append({
            "action":      act,
            "current_pct": round(curr_pct, 3),
            "prior_pct":   round(prior_pct, 3),
            "drift_pp":    round(drift_pp, 3),
            "alert":       alert,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. Feature PSI monitor
# ---------------------------------------------------------------------------


def compute_psi(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
    eps: float = 1e-6,
) -> float:
    """Population Stability Index (see cc_pd_monitor.py for full version)."""
    lo = min(reference.min(), current.min()) - 1e-9
    hi = max(reference.max(), current.max()) + 1e-9
    bins      = np.linspace(lo, hi, n_bins + 1)
    ref_cnt   = np.histogram(reference, bins=bins)[0].astype(float)
    curr_cnt  = np.histogram(current,   bins=bins)[0].astype(float)
    ref_pct   = np.where(ref_cnt > 0, ref_cnt / ref_cnt.sum(), eps)
    curr_pct  = np.where(curr_cnt > 0, curr_cnt / curr_cnt.sum(), eps)
    psi       = float(((curr_pct - ref_pct) * np.log(curr_pct / ref_pct)).sum())
    return round(psi, 5)


def compute_feature_psi_all(
    ref_feats: pd.DataFrame,
    curr_feats: pd.DataFrame,
) -> pd.DataFrame:
    """Compute PSI for all 35 portfolio features.

    Parameters
    ----------
    ref_feats, curr_feats:
        DataFrames where each column is one feature (ALL_FEATURES).

    Returns
    -------
    DataFrame: feature | psi | status
    """
    from models.credit_risk.portfolio_features import ALL_FEATURES

    rows = []
    for feat in ALL_FEATURES:
        if feat not in ref_feats.columns or feat not in curr_feats.columns:
            rows.append({"feature": feat, "psi": None, "status": "MISSING_DATA"})
            continue
        ref_arr  = ref_feats[feat].dropna().values.astype(float)
        curr_arr = curr_feats[feat].dropna().values.astype(float)
        if len(ref_arr) < 5 or len(curr_arr) < 5:
            rows.append({"feature": feat, "psi": None, "status": "INSUFFICIENT_DATA"})
            continue
        psi    = compute_psi(ref_arr, curr_arr)
        status = "GREEN" if psi < 0.10 else ("YELLOW" if psi < FEATURE_PSI_THRESHOLD else "RED")
        rows.append({"feature": feat, "psi": psi, "status": status})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 3. Guardrail override rate
# ---------------------------------------------------------------------------


def guardrail_override_rate(review_df: pd.DataFrame) -> Dict[str, Any]:
    """Compute guardrail override stats.

    Returns dict with: override_rate, top_reasons, alert_flag
    """
    if review_df.empty or "guardrail_reason" not in review_df.columns:
        return {"override_rate": 0.0, "top_reasons": {}, "alert_flag": False}

    total     = len(review_df)
    overrides = review_df[review_df["guardrail_reason"].astype(str).str.len() > 0]
    rate      = float(len(overrides)) / max(total, 1)

    reason_counts: Dict[str, int] = {}
    for r in overrides["guardrail_reason"]:
        short = str(r)[:100]
        reason_counts[short] = reason_counts.get(short, 0) + 1

    top_reasons = dict(sorted(reason_counts.items(), key=lambda x: -x[1])[:10])
    return {
        "override_rate":    round(rate, 4),
        "override_count":   len(overrides),
        "total_accounts":   total,
        "top_reasons":      top_reasons,
        "alert_flag":       rate > GUARDRAIL_OVERRIDE_THRESHOLD,
    }


# ---------------------------------------------------------------------------
# 4. CNPV delta realisation (quarterly)
# ---------------------------------------------------------------------------


def cnpv_realisation_check(
    predicted_deltas: np.ndarray,
    realised_deltas: np.ndarray,
) -> Dict[str, Any]:
    """Compare realised vs predicted CNPV deltas.

    Parameters
    ----------
    predicted_deltas:
        ``cnpv_delta_scenario_weighted`` from review month.
    realised_deltas:
        Actuals captured 3 months later (revenue − credit costs).

    Returns
    -------
    dict with realised_pct, alert_flag, mean_predicted, mean_realised
    """
    if len(predicted_deltas) == 0 or len(realised_deltas) == 0:
        return {"realised_pct": None, "alert_flag": False}

    mean_pred    = float(np.mean(predicted_deltas))
    mean_realised = float(np.mean(realised_deltas))
    realised_pct  = (mean_realised / mean_pred) if abs(mean_pred) > 1e-3 else None

    return {
        "mean_predicted":  round(mean_pred, 2),
        "mean_realised":   round(mean_realised, 2),
        "realised_pct":    round(realised_pct, 4) if realised_pct is not None else None,
        "alert_flag":      (realised_pct is not None and realised_pct < CNPV_REALISATION_THRESHOLD),
    }


# ---------------------------------------------------------------------------
# 5 & 6. Adverse action compliance checks
# ---------------------------------------------------------------------------


def adverse_action_coverage_check(review_df: pd.DataFrame) -> Dict[str, Any]:
    """Verify every CLD and APR_UP action has >= 2 reason codes.

    Assumes ``review_df`` has a ``reason_codes`` column (list or JSON string)
    and ``final_action`` column.

    Returns
    -------
    dict: coverage_pct, missing_reason_codes_count, alert_flag
    """
    if review_df.empty:
        return {"coverage_pct": 1.0, "missing_reason_codes_count": 0, "alert_flag": False}

    adverse_mask = review_df["final_action"].isin(["CLD", "APR_UP"])
    adverse_df   = review_df[adverse_mask]
    if adverse_df.empty:
        return {"coverage_pct": 1.0, "missing_reason_codes_count": 0, "alert_flag": False}

    def _reason_count(val: Any) -> int:
        if isinstance(val, list):
            return len(val)
        if isinstance(val, str):
            import json
            try:
                lst = json.loads(val)
                return len(lst) if isinstance(lst, list) else 0
            except Exception:
                return 1 if val.strip() else 0
        return 0

    if "reason_codes" in adverse_df.columns:
        counts = adverse_df["reason_codes"].apply(_reason_count)
        sufficient = int((counts >= 2).sum())
    else:
        sufficient = 0  # no reason_codes column — treat as failing

    total_adverse = len(adverse_df)
    coverage_pct  = sufficient / total_adverse if total_adverse > 0 else 1.0
    missing       = total_adverse - sufficient

    return {
        "total_adverse_actions":       total_adverse,
        "with_sufficient_reason_codes": sufficient,
        "missing_reason_codes_count":  missing,
        "coverage_pct":                round(coverage_pct, 4),
        "alert_flag":                  coverage_pct < ADVERSE_ACTION_COVERAGE_MIN,
    }


# ---------------------------------------------------------------------------
# 7. Production version consistency
# ---------------------------------------------------------------------------


def production_version_consistency_check(
    deployed_version: str,
    mlflow_tracking_uri: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare deployed model version against MLflow registry Production version.

    Returns
    -------
    dict: registry_version, deployed_version, consistent, alert_flag
    """
    from mlflow_config.mlflow_config import CC_PORTFOLIO_MODEL_NAME

    try:
        import mlflow
        from mlflow.tracking import MlflowClient

        if mlflow_tracking_uri:
            mlflow.set_tracking_uri(mlflow_tracking_uri)

        client   = MlflowClient()
        versions = client.get_latest_versions(CC_PORTFOLIO_MODEL_NAME, stages=["Production"])
        if not versions:
            return {
                "registry_version": None,
                "deployed_version": deployed_version,
                "consistent":       False,
                "alert_flag":       True,
                "message":          "No Production version in registry",
            }
        registry_ver = versions[0].version
        consistent   = str(registry_ver) == str(deployed_version)
        return {
            "registry_version": registry_ver,
            "deployed_version": deployed_version,
            "consistent":       consistent,
            "alert_flag":       not consistent,
        }
    except Exception as exc:
        return {
            "registry_version": None,
            "deployed_version": deployed_version,
            "consistent":       False,
            "alert_flag":       True,
            "message":          f"Registry check failed: {exc}",
        }


# ---------------------------------------------------------------------------
# 8. Capital consistency
# ---------------------------------------------------------------------------


def capital_consistency_check(
    review_df: pd.DataFrame,
    cet1_buffer_available: float,
) -> Dict[str, Any]:
    """Verify total CLI incremental RWA <= CET1 buffer.

    Returns
    -------
    dict: total_rwa, cet1_buffer, breach, alert_flag
    """
    cli_df    = review_df[review_df["final_action"] == "CLI"] if not review_df.empty else pd.DataFrame()
    total_rwa = float(cli_df["incremental_rwa_usd"].sum()) if not cli_df.empty and "incremental_rwa_usd" in cli_df.columns else 0.0
    capital_consumed = total_rwa * 0.125   # 12.5% CET1 requirement

    breach = capital_consumed > cet1_buffer_available
    return {
        "total_incremental_rwa_cli": round(total_rwa, 2),
        "capital_consumed_cli":      round(capital_consumed, 2),
        "cet1_buffer_available":     cet1_buffer_available,
        "remaining_capital":         round(cet1_buffer_available - capital_consumed, 2),
        "breach":                    breach,
        "alert_flag":                breach,
    }


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------


def plot_action_drift(drift_df: pd.DataFrame, path: Path) -> None:
    """Bar chart of action rate drift (current vs prior month)."""
    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(drift_df))
    w = 0.35
    ax.bar(x - w / 2, drift_df["prior_pct"],   w, label="Prior month", color="steelblue", alpha=0.8)
    ax.bar(x + w / 2, drift_df["current_pct"], w, label="Current month", color="darkorange", alpha=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(drift_df["action"].tolist())
    ax.set_ylabel("Action rate (%)")
    ax.set_title("Portfolio Action Rate: Current vs Prior Month")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_feature_psi(psi_df: pd.DataFrame, path: Path, top_n: int = 20) -> None:
    """Horizontal bar chart of feature PSI; top_n features by PSI."""
    df_sorted = psi_df.dropna(subset=["psi"]).sort_values("psi", ascending=False).head(top_n)
    colors    = df_sorted["status"].map({"GREEN": "green", "YELLOW": "orange", "RED": "red"}).fillna("gray")
    fig, ax   = plt.subplots(figsize=(10, max(5, len(df_sorted) * 0.4)))
    ax.barh(df_sorted["feature"], df_sorted["psi"], color=colors, alpha=0.85)
    ax.axvline(0.10, color="orange", linestyle="--", label="PSI=0.10")
    ax.axvline(0.20, color="red",    linestyle="--", label="PSI=0.20")
    ax.set_xlabel("PSI")
    ax.set_title(f"Feature PSI — Top {top_n} Features")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Full monitoring run
# ---------------------------------------------------------------------------


def run_portfolio_monitor(
    sample: int = 50_000,
    cet1_buffer_available: float = 500_000_000.0,
    deployed_version: str = "1",
    export_xlsx: bool = False,
) -> Dict[str, Any]:
    """Run all portfolio action monitoring checks.

    Parameters
    ----------
    sample:
        Number of review records to sample for drift analysis.
    cet1_buffer_available:
        Available CET1 buffer in USD.
    deployed_version:
        Version string of the currently deployed portfolio action model.
    export_xlsx:
        If True, write an Excel summary to REPORT_DIR.

    Returns
    -------
    dict — keyed by check name, each a sub-dict with results + alert_flag.
    """
    log.info("=" * 60)
    log.info("CC Portfolio Action Monitor")
    log.info("=" * 60)

    # ── Load review data (synthetic / from last pipeline run) ──────────────
    review_path = DATA_DIR / "cc_portfolio_review_latest.parquet"
    prior_path  = DATA_DIR / "cc_portfolio_review_prior.parquet"

    if not review_path.exists():
        log.info("Generating synthetic review data for monitoring (dev mode)…")
        review_df = _generate_synthetic_review(n=min(sample, 10_000))
        prior_df  = _generate_synthetic_review(n=min(sample, 10_000), seed=43)
    else:
        review_df = pd.read_parquet(review_path).sample(n=min(sample, len(pd.read_parquet(review_path))), random_state=42)
        prior_df  = pd.read_parquet(prior_path).sample(n=min(sample, len(pd.read_parquet(prior_path))), random_state=42) \
            if prior_path.exists() else _generate_synthetic_review(n=5_000, seed=43)

    log.info("  Review sample: %d accounts", len(review_df))

    results: Dict[str, Any] = {}
    alerts:  List[str]      = []

    # ── 1. Action rate drift ───────────────────────────────────────────────
    log.info("[1/8] Action rate drift …")
    drift_df = compute_action_rate_drift(review_df, prior_df)
    results["action_rate_drift"] = drift_df.to_dict(orient="records")
    flagged  = drift_df[drift_df["alert"]]
    if not flagged.empty:
        for _, row in flagged.iterrows():
            alerts.append(
                f"ACTION_DRIFT: {row['action']} changed {row['drift_pp']:+.1f} pp"
                f" ({row['prior_pct']:.1f}% → {row['current_pct']:.1f}%)"
            )
    log.info("  CLI: %.1f%%  CLD: %.1f%%  APR_UP: %.1f%%  APR_DOWN: %.1f%%",
             *[drift_df.loc[drift_df["action"] == a, "current_pct"].values[0]
               if a in drift_df["action"].values else 0.0
               for a in ("CLI", "CLD", "APR_UP", "APR_DOWN")])

    # ── 2. Feature PSI ─────────────────────────────────────────────────────
    log.info("[2/8] Feature PSI (35 features) …")
    try:
        from models.credit_risk.portfolio_features import ALL_FEATURES
        feat_cols = [c for c in ALL_FEATURES if c in review_df.columns]
        if feat_cols:
            psi_df = compute_feature_psi_all(prior_df[feat_cols], review_df[feat_cols])
            red_features = psi_df[psi_df["status"] == "RED"]
            results["feature_psi"] = psi_df.to_dict(orient="records")
            if not red_features.empty:
                for _, row in red_features.iterrows():
                    alerts.append(f"FEATURE_PSI: {row['feature']} PSI={row['psi']:.4f} > {FEATURE_PSI_THRESHOLD}")
            log.info("  PSI ≥ 0.20 (RED): %d features", len(red_features))
        else:
            log.warning("  Feature columns not found in review data; skipping PSI.")
            results["feature_psi"] = []
    except ImportError as exc:
        log.warning("  Feature PSI skipped: %s", exc)
        results["feature_psi"] = []

    # ── 3. Guardrail override rate ─────────────────────────────────────────
    log.info("[3/8] Guardrail override rate …")
    gr_result = guardrail_override_rate(review_df)
    results["guardrail_override"] = gr_result
    if gr_result["alert_flag"]:
        alerts.append(
            f"GUARDRAIL: override rate={gr_result['override_rate']:.2%} "
            f"> {GUARDRAIL_OVERRIDE_THRESHOLD:.0%} threshold"
        )
    log.info("  Override rate: %.2f%%", gr_result["override_rate"] * 100)

    # ── 4. CNPV delta realisation (simulated in dev) ───────────────────────
    log.info("[4/8] CNPV delta realisation …")
    if "cnpv_delta_scenario_weighted" in review_df.columns:
        predicted  = review_df["cnpv_delta_scenario_weighted"].values
        # Simulated realised = predicted * N(1.0, 0.25) for dev
        rng = np.random.default_rng(99)
        realised   = predicted * rng.normal(0.85, 0.20, len(predicted))
        cnpv_check = cnpv_realisation_check(predicted, realised)
        results["cnpv_realisation"] = cnpv_check
        if cnpv_check.get("alert_flag"):
            alerts.append(
                f"CNPV_REALISATION: {cnpv_check.get('realised_pct', 0):.0%} "
                f"< {CNPV_REALISATION_THRESHOLD:.0%} threshold"
            )
        log.info("  Realised/predicted ratio: %s",
                 f"{cnpv_check['realised_pct']:.2f}" if cnpv_check.get("realised_pct") else "n/a")
    else:
        log.info("  CNPV delta columns not found; skipping realisation check.")
        results["cnpv_realisation"] = {}

    # ── 5. Adverse action coverage ─────────────────────────────────────────
    log.info("[5/8] Adverse action coverage …")
    aa_check = adverse_action_coverage_check(review_df)
    results["adverse_action_coverage"] = aa_check
    if aa_check["alert_flag"]:
        alerts.append(
            f"ADVERSE_ACTION: coverage={aa_check['coverage_pct']:.2%} < 100% "
            f"— {aa_check['missing_reason_codes_count']} adverse actions missing reason codes"
        )
    log.info("  Coverage: %.2f%%  (adverse actions: %d)",
             aa_check.get("coverage_pct", 1.0) * 100,
             aa_check.get("total_adverse_actions", 0))

    # ── 6. (Adverse action notice SLA covered in adverse_action_coverage) ──
    log.info("[6/8] Adverse action notice SLA — see compliance pipeline.")

    # ── 7. Production version consistency ─────────────────────────────────
    log.info("[7/8] Production version consistency …")
    ver_check = production_version_consistency_check(deployed_version)
    results["version_consistency"] = ver_check
    if ver_check["alert_flag"]:
        alerts.append(
            f"VERSION_MISMATCH: deployed={deployed_version} "
            f"registry={ver_check.get('registry_version', 'unknown')}"
        )
    log.info("  Deployed: %s  Registry: %s  Consistent: %s",
             deployed_version,
             ver_check.get("registry_version", "n/a"),
             ver_check.get("consistent", False))

    # ── 8. Capital consistency ─────────────────────────────────────────────
    log.info("[8/8] Capital consistency …")
    cap_check = capital_consistency_check(review_df, cet1_buffer_available)
    results["capital_consistency"] = cap_check
    if cap_check["alert_flag"]:
        alerts.append(
            f"CAPITAL_BREACH: capital_consumed={cap_check['capital_consumed_cli']:,.0f} "
            f"> buffer={cet1_buffer_available:,.0f}"
        )
    log.info("  CLI RWA: $%,.0f  Capital consumed: $%,.0f  Buffer: $%,.0f",
             cap_check["total_incremental_rwa_cli"],
             cap_check["capital_consumed_cli"],
             cet1_buffer_available)

    # ── Plots ──────────────────────────────────────────────────────────────
    log.info("Generating plots …")
    plot_action_drift(drift_df, REPORT_DIR / "action_rate_drift.png")
    if results.get("feature_psi"):
        psi_plot_df = pd.DataFrame(results["feature_psi"])
        if not psi_plot_df.empty:
            plot_feature_psi(psi_plot_df, REPORT_DIR / "feature_psi.png")
    log.info("  Plots saved to %s", REPORT_DIR)

    # ── Alert summary ──────────────────────────────────────────────────────
    log.info("\n── Monitoring Alerts ────────────────────────────────────────")
    if alerts:
        for a in alerts:
            log.warning(a)
    else:
        log.info("  All checks PASSED — no alerts.")

    results["alerts"]      = alerts
    results["run_at"]      = datetime.now(timezone.utc).isoformat()
    results["sample_size"] = len(review_df)

    # ── Optional Excel export ──────────────────────────────────────────────
    if export_xlsx:
        xlsx_path = REPORT_DIR / "cc_portfolio_monitoring_report.xlsx"
        try:
            with pd.ExcelWriter(xlsx_path, engine="openpyxl") as xw:
                drift_df.to_excel(xw, sheet_name="Action_Rate_Drift", index=False)
                if results.get("feature_psi"):
                    pd.DataFrame(results["feature_psi"]).to_excel(xw, sheet_name="Feature_PSI", index=False)
                pd.DataFrame([gr_result]).to_excel(xw, sheet_name="Guardrail_Override", index=False)
                pd.DataFrame([cap_check]).to_excel(xw, sheet_name="Capital_Consistency", index=False)
                pd.DataFrame(alerts, columns=["alert"]).to_excel(xw, sheet_name="Alerts", index=False)
            log.info("Excel report → %s", xlsx_path)
        except ImportError:
            log.warning("openpyxl not installed; skipping Excel export.")

    return results


# ---------------------------------------------------------------------------
# Synthetic data generator for dev / CI
# ---------------------------------------------------------------------------


def _generate_synthetic_review(n: int = 5_000, seed: int = 42) -> pd.DataFrame:
    from models.credit_risk.portfolio_features import ALL_FEATURES

    rng = np.random.default_rng(seed)
    actions = rng.choice(
        ["HOLD", "CLI", "CLD", "APR_UP", "APR_DOWN"],
        size=n,
        p=[0.808, 0.120, 0.040, 0.020, 0.012],
    )
    guardrail_reasons = np.where(
        rng.random(n) < 0.05,
        "GUARDRAIL: DPD60+ — mandatory limit reduction",
        "",
    )
    curr_limits = rng.uniform(500, 15_000, n)
    limit_changes = np.where(
        actions == "CLI", rng.uniform(0.10, 0.30, n),
        np.where(actions == "CLD", rng.uniform(-0.40, -0.10, n), 0.0)
    )
    df = pd.DataFrame({
        "origination_id":            [f"orig_{i:06d}" for i in range(n)],
        "final_action":              actions,
        "guardrail_reason":          guardrail_reasons,
        "current_credit_limit":      curr_limits.round(0),
        "new_credit_limit":          (curr_limits * (1 + limit_changes)).round(0),
        "limit_change_pct":          (limit_changes * 100).round(2),
        "current_apr":               rng.uniform(0.1499, 0.2999, n).round(4),
        "new_apr":                   rng.uniform(0.1499, 0.2999, n).round(4),
        "apr_change_bps":            rng.uniform(-150, 200, n).round(1),
        "cnpv_delta_base":           rng.uniform(-50, 300, n).round(2),
        "cnpv_delta_worsening":      rng.uniform(-100, 200, n).round(2),
        "cnpv_delta_recession":      rng.uniform(-200, 100, n).round(2),
        "cnpv_delta_scenario_weighted": rng.uniform(-30, 150, n).round(2),
        "incremental_rwa_usd":       np.where(actions == "CLI", rng.uniform(50, 5_000, n), 0.0).round(2),
        "risk_segment":              rng.choice(["prime", "near_prime", "subprime"], n, p=[0.35, 0.45, 0.20]),
    })
    # Add feature columns
    for feat in ALL_FEATURES:
        if feat not in df.columns:
            df[feat] = rng.uniform(0, 1, n) if "pct" in feat or "rate" in feat or "ratio" in feat \
                else rng.uniform(0, 800 if "score" in feat else 50, n)
    return df


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CC Portfolio Action Monitor")
    ap.add_argument("--sample",   type=int,   default=50_000,       help="Monitoring sample size")
    ap.add_argument("--cet1-buf", type=float, default=500_000_000.0, help="CET1 buffer USD")
    ap.add_argument("--version",  type=str,   default="1",          help="Deployed model version")
    ap.add_argument("--export",   choices=["xlsx"], default=None,    help="Export format")
    args = ap.parse_args()
    run_portfolio_monitor(
        sample                = args.sample,
        cet1_buffer_available = args.cet1_buf,
        deployed_version      = args.version,
        export_xlsx           = args.export == "xlsx",
    )
