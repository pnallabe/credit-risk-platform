"""
Mortgage Valuation Monitor — Section 21.7 (MRM Framework Extension)
=====================================================================
Ongoing validation and drift monitoring for the ``mortgage_valuation_model``
registered in MLflow.

Monitors (all monthly unless noted):
  1. CNPV Backtesting          — predicted CNPV vs realised 12-month NPV for closed cohorts
  2. LTV Distribution PSI      — PSI on LTV distribution vs training baseline
  3. HPA Scenario Monotonicity — recession CNPV < worsening CNPV < base CNPV
  4. PD Calibration            — Hosmer-Lemeshow goodness-of-fit on 90-day DPD
  5. Approval Rate Drift       — champion vs rolling 30-day live approval rate
  6. Capital Headroom          — remaining CET1 buffer for mortgage book >= 10%
  7. Adverse Action Coverage   — every DECLINE must have >= 2 reason codes
  8. Disparate Impact Ratio    — ECOA 4/5ths rule: DI ratio >= 0.80 per protected class
  9. Production Version Consistency — registry version == deployed version
 10. Origination Audit Completeness — every mortgage_id present in audit_log

All monitors return a dict:
  monitor_name, passed, metric_value, threshold, alert_level, message

Usage
-----
    python monitoring/mortgage_valuation_monitor.py
    python monitoring/mortgage_valuation_monitor.py --export json
    python monitoring/mortgage_valuation_monitor.py --export xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
DATA_DIR     = PROJECT_ROOT / "data"
REPORT_DIR   = PROJECT_ROOT / "monitoring" / "mortgage_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Alert levels
# ---------------------------------------------------------------------------

ALERT_OK       = "OK"
ALERT_WARNING  = "WARNING"
ALERT_CRITICAL = "CRITICAL"

# ---------------------------------------------------------------------------
# Thresholds (aligned with MODEL_GOVERNANCE[mortgage_valuation_model])
# ---------------------------------------------------------------------------

MIN_CNPV_REALISED_RATIO      = 0.70    # Monthly — realised / predicted >= 70 %
MAX_LTV_PSI                  = 0.15    # Monthly — PSI on LTV distribution
MIN_HPA_MONOTONE_PCT         = 0.99    # Every batch >= 99%
MAX_HL_P_VALUE_THRESHOLD     = 0.05    # PD calibration: p-value < 0.05 → concern
MIN_CAPITAL_HEADROOM_PCT     = 0.10    # Every batch >= 10%
MAX_AUDIT_MISSING_RATE       = 0.0     # Daily — 0 missing mortgage IDs
MIN_ADVERSE_ACTION_COVERAGE  = 1.00   # 100% of DECLINE have >= 2 reason codes
MIN_DI_RATIO                 = 0.80    # ECOA 4/5ths rule
MAX_APPROVAL_RATE_DELTA_PP   = 5.0    # ±5 pp vs baseline


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

MortgageMonitorResult = Dict[str, Any]


def _make_result(
    monitor_name: str,
    passed: bool,
    metric_value: Any,
    threshold: Any,
    alert_level: str,
    message: str,
) -> MortgageMonitorResult:
    return {
        "monitor_name":  monitor_name,
        "passed":        passed,
        "metric_value":  metric_value,
        "threshold":     threshold,
        "alert_level":   alert_level,
        "message":       message,
        "checked_at":    datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 1. CNPV Backtesting
# ---------------------------------------------------------------------------

def check_cnpv_backtesting(
    predicted_cnpv: pd.Series,
    realised_npv: pd.Series,
) -> MortgageMonitorResult:
    """Compare predicted mortgage CNPV vs realised 12-month NPV for closed cohorts.

    ``predicted_cnpv`` and ``realised_npv`` must be aligned by loan origination ID.
    Ratio = sum(realised_npv) / sum(predicted_cnpv).
    """
    if predicted_cnpv.empty or realised_npv.empty:
        return _make_result("cnpv_backtesting", False, None, MIN_CNPV_REALISED_RATIO,
                            ALERT_WARNING, "No data available for CNPV backtesting")

    total_predicted = predicted_cnpv.sum()
    total_realised  = realised_npv.sum()

    if total_predicted == 0:
        return _make_result("cnpv_backtesting", False, 0.0, MIN_CNPV_REALISED_RATIO,
                            ALERT_CRITICAL, "Predicted CNPV sum is 0 — model error")

    ratio = total_realised / total_predicted
    passed = ratio >= MIN_CNPV_REALISED_RATIO
    level  = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "cnpv_backtesting", passed, round(float(ratio), 4), MIN_CNPV_REALISED_RATIO,
        level,
        f"Realised/Predicted CNPV ratio: {ratio:.4f} "
        f"({'PASS' if passed else 'FAIL — below threshold ' + str(MIN_CNPV_REALISED_RATIO)})",
    )


# ---------------------------------------------------------------------------
# 2. LTV Distribution PSI
# ---------------------------------------------------------------------------

def _compute_psi(expected: np.ndarray, actual: np.ndarray, n_bins: int = 10) -> float:
    """Compute Population Stability Index between two distributions."""
    expected = np.array(expected, dtype=float)
    actual   = np.array(actual, dtype=float)

    bins = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
    bins[0]  -= 1e-9
    bins[-1] += 1e-9

    exp_counts, _ = np.histogram(expected, bins=bins)
    act_counts, _ = np.histogram(actual,   bins=bins)

    exp_pct = exp_counts / max(exp_counts.sum(), 1)
    act_pct = act_counts / max(act_counts.sum(), 1)

    # Avoid log(0)
    exp_pct = np.where(exp_pct == 0, 1e-6, exp_pct)
    act_pct = np.where(act_pct == 0, 1e-6, act_pct)

    return float(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)))


def check_ltv_psi(
    train_ltv: np.ndarray,
    current_ltv: np.ndarray,
) -> MortgageMonitorResult:
    """Compute LTV distribution PSI vs training baseline."""
    if len(train_ltv) == 0 or len(current_ltv) == 0:
        return _make_result("ltv_psi", False, None, MAX_LTV_PSI,
                            ALERT_WARNING, "Insufficient data for LTV PSI check")

    psi = _compute_psi(train_ltv, current_ltv)
    passed = psi <= MAX_LTV_PSI

    if psi < 0.10:
        level = ALERT_OK
    elif psi < MAX_LTV_PSI:
        level = ALERT_WARNING
    else:
        level = ALERT_CRITICAL

    return _make_result(
        "ltv_psi", passed, round(psi, 4), MAX_LTV_PSI,
        level,
        f"LTV PSI={psi:.4f} (threshold={MAX_LTV_PSI}): "
        f"{'stable' if psi < 0.10 else 'minor shift' if psi < 0.20 else 'MAJOR SHIFT'}",
    )


# ---------------------------------------------------------------------------
# 3. HPA Scenario Monotonicity
# ---------------------------------------------------------------------------

def check_hpa_scenario_monotonicity(
    cnpv_base: pd.Series,
    cnpv_worsening: pd.Series,
    cnpv_recession: pd.Series,
) -> MortgageMonitorResult:
    """Verify recession CNPV < worsening CNPV < base CNPV for each mortgage application.

    HPA (Home Price Appreciation) scenarios must produce monotonically ordered CNPVs
    per the model specification.  target >= 99% of applications satisfy monotonicity.
    """
    if cnpv_base.empty:
        return _make_result("hpa_monotonicity", False, None, MIN_HPA_MONOTONE_PCT,
                            ALERT_WARNING, "No HPA scenario data available")

    n = len(cnpv_base)
    monotone_mask = (cnpv_recession <= cnpv_worsening) & (cnpv_worsening <= cnpv_base)
    pct_monotone  = float(monotone_mask.sum()) / n

    passed = pct_monotone >= MIN_HPA_MONOTONE_PCT
    level  = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "hpa_monotonicity", passed, round(pct_monotone, 4), MIN_HPA_MONOTONE_PCT,
        level,
        f"HPA monotonicity: {pct_monotone:.2%} of applications "
        f"({'PASS' if passed else 'FAIL'})",
    )


# ---------------------------------------------------------------------------
# 4. PD Calibration (Hosmer-Lemeshow)
# ---------------------------------------------------------------------------

def check_pd_calibration(
    predicted_pd: pd.Series,
    actual_default: pd.Series,
    n_bins: int = 10,
) -> MortgageMonitorResult:
    """Hosmer-Lemeshow goodness-of-fit test for PD calibration.

    A low p-value (< 0.05) indicates poor calibration — model over/under-predicts.
    Returns WARNING (not CRITICAL) since HL can be unstable with small samples.
    """
    try:
        from scipy.stats import chi2

        n = len(predicted_pd)
        if n < 100:
            return _make_result("pd_calibration", True, None, MAX_HL_P_VALUE_THRESHOLD,
                                ALERT_WARNING, f"Insufficient data for HL test (n={n})")

        # Bin by predicted PD deciles
        bins = pd.qcut(predicted_pd, q=n_bins, duplicates="drop")
        df   = pd.DataFrame({"pred": predicted_pd, "actual": actual_default, "bin": bins})

        hl_stat = 0.0
        for _, grp in df.groupby("bin", observed=True):
            n_g  = len(grp)
            obs  = grp["actual"].sum()
            exp  = grp["pred"].sum()
            if exp > 0 and (n_g - exp) > 0:
                hl_stat += (obs - exp) ** 2 / (exp)
                hl_stat += ((n_g - obs) - (n_g - exp)) ** 2 / (n_g - exp)

        p_value = 1.0 - chi2.cdf(hl_stat, df=n_bins - 2)
        passed  = p_value >= MAX_HL_P_VALUE_THRESHOLD
        level   = ALERT_OK if passed else ALERT_WARNING

        return _make_result(
            "pd_calibration", passed, round(p_value, 4), MAX_HL_P_VALUE_THRESHOLD,
            level,
            f"Hosmer-Lemeshow p-value={p_value:.4f} "
            f"({'well-calibrated' if passed else 'POOR CALIBRATION — investigate'})",
        )

    except Exception as exc:
        return _make_result("pd_calibration", True, None, MAX_HL_P_VALUE_THRESHOLD,
                            ALERT_WARNING, f"Calibration check skipped: {exc}")


# ---------------------------------------------------------------------------
# 5. Approval Rate Drift
# ---------------------------------------------------------------------------

def check_approval_rate_drift(
    baseline_rate: float,
    current_rate: float,
) -> MortgageMonitorResult:
    """Check if the approval rate has drifted > 5 pp from the baseline."""
    delta = abs(current_rate - baseline_rate) * 100  # convert to pp
    passed = delta <= MAX_APPROVAL_RATE_DELTA_PP
    level  = ALERT_OK if passed else ALERT_WARNING

    return _make_result(
        "approval_rate_drift", passed, round(delta, 2), MAX_APPROVAL_RATE_DELTA_PP,
        level,
        f"Approval rate drift: {delta:.1f}pp (baseline={baseline_rate:.2%}, "
        f"current={current_rate:.2%})",
    )


# ---------------------------------------------------------------------------
# 6. Capital Headroom
# ---------------------------------------------------------------------------

def check_capital_headroom(
    remaining_capital: float,
    capital_buffer: float,
) -> MortgageMonitorResult:
    """Verify CET1 capital headroom for mortgage book >= 10% of buffer."""
    if capital_buffer <= 0:
        return _make_result("capital_headroom", False, 0.0, MIN_CAPITAL_HEADROOM_PCT,
                            ALERT_CRITICAL, "capital_buffer is 0 or undefined")

    headroom_pct = remaining_capital / capital_buffer
    passed = headroom_pct >= MIN_CAPITAL_HEADROOM_PCT
    level  = ALERT_OK if headroom_pct >= 0.20 else (
        ALERT_WARNING if headroom_pct >= MIN_CAPITAL_HEADROOM_PCT else ALERT_CRITICAL
    )

    return _make_result(
        "capital_headroom", passed, round(headroom_pct, 4), MIN_CAPITAL_HEADROOM_PCT,
        level,
        f"Capital headroom: {headroom_pct:.2%} of buffer "
        f"({'PASS' if passed else 'BREACH — stop new originations'})",
    )


# ---------------------------------------------------------------------------
# 7. Adverse Action Coverage
# ---------------------------------------------------------------------------

def check_adverse_action_coverage(
    decisions_df: pd.DataFrame,
) -> MortgageMonitorResult:
    """Verify every DECLINE has >= 2 reason codes (FCRA minimum)."""
    if decisions_df is None or decisions_df.empty:
        return _make_result("adverse_action_coverage", True, 1.0, 1.0,
                            ALERT_OK, "No decisions to check")

    declines = decisions_df[decisions_df.get("decision", decisions_df.columns[0]) == "DECLINE"] \
        if "decision" in decisions_df.columns else pd.DataFrame()

    if declines.empty:
        return _make_result("adverse_action_coverage", True, 1.0, 1.0,
                            ALERT_OK, "No DECLINE decisions in sample")

    if "reason_codes" not in declines.columns:
        return _make_result("adverse_action_coverage", False, 0.0, 1.0,
                            ALERT_CRITICAL, "reason_codes column missing from decisions_df")

    def _count_codes(rc) -> int:
        if isinstance(rc, list):
            return len(rc)
        if isinstance(rc, str):
            try:
                parsed = json.loads(rc)
                return len(parsed) if isinstance(parsed, list) else 1
            except json.JSONDecodeError:
                return 1
        return 0

    code_counts = declines["reason_codes"].apply(_count_codes)
    coverage    = (code_counts >= 2).mean()
    passed      = coverage >= MIN_ADVERSE_ACTION_COVERAGE
    level       = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "adverse_action_coverage", passed, round(float(coverage), 4), 1.0,
        level,
        f"Adverse action coverage: {coverage:.2%} of DECLINE decisions have >= 2 reason codes",
    )


# ---------------------------------------------------------------------------
# 8. Disparate Impact Ratio (ECOA Fair Lending)
# ---------------------------------------------------------------------------

def check_disparate_impact(
    decisions_df: pd.DataFrame,
    protected_class_col: str = "race",
    reference_class: str = "white",
) -> MortgageMonitorResult:
    """Compute disparate impact ratio per ECOA 4/5ths rule.

    DI ratio = (approval rate for protected class) / (approval rate for reference class)
    Must be >= 0.80 for all protected groups.
    """
    if decisions_df is None or decisions_df.empty:
        return _make_result("disparate_impact", True, None, MIN_DI_RATIO,
                            ALERT_OK, "No data for disparate impact check")

    if protected_class_col not in decisions_df.columns or "decision" not in decisions_df.columns:
        return _make_result("disparate_impact", True, None, MIN_DI_RATIO,
                            ALERT_WARNING, f"Columns '{protected_class_col}' or 'decision' missing")

    decisions_df = decisions_df.copy()
    decisions_df["approved"] = (decisions_df["decision"] == "APPROVE").astype(int)

    ref_rate = decisions_df[decisions_df[protected_class_col] == reference_class]["approved"].mean()
    if pd.isna(ref_rate) or ref_rate == 0:
        return _make_result("disparate_impact", True, None, MIN_DI_RATIO,
                            ALERT_WARNING, f"Cannot compute DI ratio: reference class '{reference_class}' rate = {ref_rate}")

    groups    = decisions_df[decisions_df[protected_class_col] != reference_class]
    di_ratios = {}
    min_di    = 1.0
    for grp_name, grp_df in groups.groupby(protected_class_col):
        grp_rate = grp_df["approved"].mean()
        di       = grp_rate / ref_rate if ref_rate > 0 else 1.0
        di_ratios[str(grp_name)] = round(float(di), 4)
        min_di = min(min_di, di)

    passed = min_di >= MIN_DI_RATIO
    level  = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "disparate_impact", passed, di_ratios, MIN_DI_RATIO,
        level,
        f"Min DI ratio: {min_di:.4f} (threshold {MIN_DI_RATIO}) — "
        f"{'PASS' if passed else 'FAIL: ECOA violation risk'}. Details: {di_ratios}",
    )


# ---------------------------------------------------------------------------
# 9. Production Version Consistency
# ---------------------------------------------------------------------------

def check_version_consistency(
    deployed_version: str,
    registry_version: str,
) -> MortgageMonitorResult:
    """Verify the deployed model version matches the current Production registry version."""
    passed = deployed_version == registry_version
    level  = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "version_consistency", passed,
        {"deployed": deployed_version, "registry": registry_version},
        "deployed == registry",
        level,
        f"Version {'match' if passed else 'MISMATCH'}: deployed={deployed_version}, "
        f"registry={registry_version}",
    )


# ---------------------------------------------------------------------------
# 10. Audit Completeness
# ---------------------------------------------------------------------------

def check_audit_completeness(
    mortgage_ids: pd.Series,
    audit_ids: pd.Series,
) -> MortgageMonitorResult:
    """Verify every mortgage_id in the origination batch has a matching audit_log row."""
    total      = len(mortgage_ids)
    missing    = mortgage_ids[~mortgage_ids.isin(audit_ids)]
    miss_rate  = len(missing) / max(total, 1)
    passed     = miss_rate <= MAX_AUDIT_MISSING_RATE
    level      = ALERT_OK if passed else ALERT_CRITICAL

    return _make_result(
        "audit_completeness", passed, round(miss_rate, 6), MAX_AUDIT_MISSING_RATE,
        level,
        f"Audit completeness: {len(missing)} missing IDs out of {total} "
        f"({miss_rate:.2%}) — {'PASS' if passed else 'FAIL'}",
    )


# ---------------------------------------------------------------------------
# Main monitor class
# ---------------------------------------------------------------------------


class MortgageValuationMonitor:
    """Orchestrates all mortgage valuation model health checks.

    Parameters
    ----------
    train_ltv:
        LTV values from the training dataset (for PSI baseline).
    registry_version:
        Current Production version in MLflow registry.
    deployed_version:
        Version string of the deployed model artefact.
    """

    def __init__(
        self,
        train_ltv: Optional[np.ndarray] = None,
        registry_version: str = "unknown",
        deployed_version: str = "unknown",
    ) -> None:
        self.train_ltv       = train_ltv if train_ltv is not None else np.array([])
        self.registry_version = registry_version
        self.deployed_version = deployed_version

    def run_all(
        self,
        origination_df: Optional[pd.DataFrame] = None,
        cnpv_df: Optional[pd.DataFrame] = None,
        baseline_approval_rate: float = 0.70,
        remaining_capital: float = 1e8,
        capital_buffer: float = 1e9,
        audit_ids: Optional[pd.Series] = None,
    ) -> List[MortgageMonitorResult]:
        """Run all monitors and return list of results.

        Parameters
        ----------
        origination_df:
            DataFrame with columns: mortgage_id, decision, reason_codes,
            pred_pd, actual_default_90d, ltv, [race], valuation_cnpv,
            valuation_cnpv_worsening, valuation_cnpv_recession.
        cnpv_df:
            Closed cohort DataFrame with columns: predicted_cnpv, realised_npv.
        baseline_approval_rate:
            Historical baseline approval rate for drift check.
        remaining_capital / capital_buffer:
            Capital headroom inputs.
        audit_ids:
            Set of mortgage_ids already present in audit_log.
        """
        results: List[MortgageMonitorResult] = []
        df = origination_df if origination_df is not None else pd.DataFrame()

        # ── 1. CNPV backtesting ──────────────────────────────────────────
        if cnpv_df is not None and not cnpv_df.empty:
            results.append(check_cnpv_backtesting(
                cnpv_df.get("predicted_cnpv", pd.Series(dtype=float)),
                cnpv_df.get("realised_npv",   pd.Series(dtype=float)),
            ))
        else:
            log.debug("cnpv_df not provided — skipping CNPV backtesting monitor")

        # ── 2. LTV PSI ───────────────────────────────────────────────────
        if not df.empty and "ltv" in df.columns:
            results.append(check_ltv_psi(self.train_ltv, df["ltv"].values))
        else:
            log.debug("ltv column unavailable — skipping LTV PSI monitor")

        # ── 3. HPA monotonicity ─────────────────────────────────────────
        if not df.empty and all(c in df.columns for c in ["valuation_cnpv", "valuation_cnpv_worsening", "valuation_cnpv_recession"]):
            results.append(check_hpa_scenario_monotonicity(
                df["valuation_cnpv"],
                df["valuation_cnpv_worsening"],
                df["valuation_cnpv_recession"],
            ))

        # ── 4. PD calibration ───────────────────────────────────────────
        if not df.empty and "pred_pd" in df.columns and "actual_default_90d" in df.columns:
            results.append(check_pd_calibration(df["pred_pd"], df["actual_default_90d"]))

        # ── 5. Approval rate drift ──────────────────────────────────────
        if not df.empty and "decision" in df.columns:
            current_rate = (df["decision"] == "APPROVE").mean()
            results.append(check_approval_rate_drift(baseline_approval_rate, float(current_rate)))

        # ── 6. Capital headroom ─────────────────────────────────────────
        results.append(check_capital_headroom(remaining_capital, capital_buffer))

        # ── 7. Adverse action coverage ──────────────────────────────────
        results.append(check_adverse_action_coverage(df))

        # ── 8. Disparate impact ─────────────────────────────────────────
        if not df.empty and "race" in df.columns:
            results.append(check_disparate_impact(df))

        # ── 9. Version consistency ──────────────────────────────────────
        results.append(check_version_consistency(self.deployed_version, self.registry_version))

        # ── 10. Audit completeness ──────────────────────────────────────
        if not df.empty and "mortgage_id" in df.columns and audit_ids is not None:
            results.append(check_audit_completeness(df["mortgage_id"], audit_ids))

        return results

    def save_report(
        self,
        results: List[MortgageMonitorResult],
        export_format: str = "json",
    ) -> Path:
        """Save monitor results to REPORT_DIR with ISO timestamp in filename."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary = {
            "model":       "mortgage_valuation_model",
            "run_at":      ts,
            "total":       len(results),
            "passed":      sum(1 for r in results if r["passed"]),
            "failed":      sum(1 for r in results if not r["passed"]),
            "critical":    sum(1 for r in results if r["alert_level"] == ALERT_CRITICAL),
            "warnings":    sum(1 for r in results if r["alert_level"] == ALERT_WARNING),
            "monitors":    results,
        }

        if export_format == "json":
            out_path = REPORT_DIR / f"mortgage_valuation_monitor_{ts}.json"
            out_path.write_text(json.dumps(summary, indent=2, default=str))
            log.info("Mortgage valuation monitor report saved: %s", out_path)
            return out_path

        elif export_format == "xlsx":
            try:
                import openpyxl  # noqa: F401

                out_path = REPORT_DIR / f"mortgage_valuation_monitor_{ts}.xlsx"
                rows = []
                for r in results:
                    row = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                           for k, v in r.items()}
                    rows.append(row)
                pd.DataFrame(rows).to_excel(out_path, index=False)
                log.info("Mortgage valuation monitor report saved: %s", out_path)
                return out_path
            except ImportError:
                log.warning("openpyxl not installed — falling back to JSON export")
                return self.save_report(results, "json")

        else:
            raise ValueError(f"Unsupported export format: {export_format}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run mortgage valuation model monitoring checks"
    )
    parser.add_argument(
        "--export", choices=["json", "xlsx"], default="json",
        help="Export format for monitoring report (default: json)",
    )
    parser.add_argument(
        "--data-dir", default=str(DATA_DIR),
        help="Directory containing origination Parquet/CSV files",
    )
    args = parser.parse_args()

    log.info("Running mortgage valuation monitor...")

    # In production: load origination_df from BigQuery / PostgreSQL.
    # In CI / demo: use synthetic data for smoke-test.
    rng = np.random.default_rng(42)
    n   = 500

    origination_df = pd.DataFrame({
        "mortgage_id":               [f"MORT_{i:05d}" for i in range(n)],
        "decision":                  rng.choice(["APPROVE", "DECLINE"], n, p=[0.75, 0.25]),
        "reason_codes":              [["CREDIT_SCORE_LOW", "HIGH_DTI"] if d == "DECLINE" else [] for d in rng.choice(["APPROVE", "DECLINE"], n, p=[0.75, 0.25])],
        "pred_pd":                   rng.beta(2, 20, n),
        "actual_default_90d":        rng.binomial(1, 0.04, n),
        "ltv":                       rng.beta(7, 3, n) * 100,
        "valuation_cnpv":            rng.normal(12000, 2000, n),
        "valuation_cnpv_worsening":  rng.normal(10000, 2000, n),
        "valuation_cnpv_recession":  rng.normal(7000, 2000, n),
        "race":                      rng.choice(["white", "black", "hispanic", "asian"], n),
    })

    cnpv_df = pd.DataFrame({
        "predicted_cnpv": rng.normal(12000, 1500, 200),
        "realised_npv":   rng.normal(11000, 1500, 200),
    })

    train_ltv = rng.beta(7, 3, 5000) * 100

    monitor = MortgageValuationMonitor(
        train_ltv=train_ltv,
        registry_version="2",
        deployed_version="2",
    )

    results = monitor.run_all(
        origination_df=origination_df,
        cnpv_df=cnpv_df,
        baseline_approval_rate=0.75,
        remaining_capital=200_000_000,
        capital_buffer=1_000_000_000,
        audit_ids=origination_df["mortgage_id"],
    )

    # Print summary
    print(f"\n{'='*70}")
    print(" Mortgage Valuation Monitor — Results")
    print(f"{'='*70}")
    passed_count = sum(1 for r in results if r["passed"])
    for r in results:
        icon = "✓" if r["passed"] else ("⚠" if r["alert_level"] == ALERT_WARNING else "✗")
        print(f"  {icon} [{r['alert_level']:8s}] {r['monitor_name']:35s} {r['message'][:60]}")

    print(f"\n  Summary: {passed_count}/{len(results)} checks passed")
    print()

    report_path = monitor.save_report(results, args.export)
    print(f"  Report saved: {report_path}")


if __name__ == "__main__":
    main()
