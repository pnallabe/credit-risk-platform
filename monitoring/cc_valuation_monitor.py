"""
CC Originations Valuation Monitor — Section 19.13.4
====================================================
Monitors and backtests the CNPV origination valuation model.

Monitors:
  1. CNPV backtesting  — predicted CNPV vs realised 12m revenue for closed cohorts
  2. FTP PSI           — FTP rate distribution stability vs prior quarter
  3. Approval rate drift — champion vs rolling 30-day live rate
  4. Scenario monotonicity audit — recession CNPV < worsening CNPV < base CNPV
  5. Capital headroom breach — remaining_capital < 10% of buffer
  6. Adverse action code coverage — every DECLINE must have ≥ 2 reason codes
  7. Audit completeness — every origination_id present in audit_log

All monitors return a dict with keys:
  monitor_name, passed, metric_value, threshold, alert_level, message

Usage
-----
    from monitoring.cc_valuation_monitor import CCValuationMonitor
    mon = CCValuationMonitor(bq_client=client, project="ai-risk-workflow", dataset="credit_risk_model_dev")
    alerts = mon.run_all()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Alert levels
# ---------------------------------------------------------------------------

ALERT_OK       = "OK"
ALERT_WARNING  = "WARNING"
ALERT_CRITICAL = "CRITICAL"

# ---------------------------------------------------------------------------
# Thresholds (aligned with Section 19.12 Quality Gates & 19.13.4 table)
# ---------------------------------------------------------------------------

MIN_CNPV_REALISED_RATIO      = 0.70    # Monthly — realised / predicted >= 70 %
MAX_FTP_PSI                  = 0.15    # Monthly — PSI on FTP rates
MAX_APPROVAL_RATE_DELTA_PP   = 5.0     # Daily  — ±5 pp vs baseline
MIN_MONOTONE_PCT             = 0.99    # Every batch — >= 99 % monotone
MIN_CAPITAL_HEADROOM_PCT     = 0.10    # Every batch — remaining / buffer >= 10 %
MAX_AUDIT_MISSING_RATE       = 0.0     # Daily  — 0 missing origination IDs


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class MonitorResult:
    monitor_name:  str
    passed:        bool
    metric_value:  float | None
    threshold:     float | None
    alert_level:   str              # OK | WARNING | CRITICAL
    message:       str
    checked_at:    str = ""

    def __post_init__(self) -> None:
        if not self.checked_at:
            self.checked_at = datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Monitor class
# ---------------------------------------------------------------------------


class CCValuationMonitor:
    """Runs all Section 19 monitoring checks.

    Parameters
    ----------
    bq_client:
        An initialised ``google.cloud.bigquery.Client`` (or None for
        Parquet fallback).
    project:
        GCP project ID.
    dataset:
        BigQuery dataset name.
    baseline_approval_rate:
        Champion approval rate baseline (fraction, e.g. 0.72).
    cet1_buffer_available:
        Current firm CET1 buffer for card originations (USD).
    db_url:
        SQLAlchemy async DB URL for audit_log completeness check.
    """

    def __init__(
        self,
        bq_client: Any | None = None,
        project: str = "ai-risk-workflow",
        dataset: str = "credit_risk_model_dev",
        baseline_approval_rate: float = 0.72,
        cet1_buffer_available: float = 500_000_000.0,
        db_url: str = "sqlite+aiosqlite:///./audit.db",
    ) -> None:
        self.bq_client              = bq_client
        self.project                = project
        self.dataset                = dataset
        self.baseline_approval_rate = baseline_approval_rate
        self.cet1_buffer_available  = cet1_buffer_available
        self.db_url                 = db_url

    # ------------------------------------------------------------------
    # 1. CNPV Backtesting
    # ------------------------------------------------------------------

    def check_cnpv_backtesting(
        self,
        df_closed_cohort: pd.DataFrame,
    ) -> MonitorResult:
        """Compare predicted CNPV vs realised 12-month revenue for closed cohorts.

        Parameters
        ----------
        df_closed_cohort:
            DataFrame with columns: ``predicted_cnpv``, ``realised_12m_revenue``.
        """
        if df_closed_cohort.empty:
            return MonitorResult(
                monitor_name="cnpv_backtesting",
                passed=False,
                metric_value=None,
                threshold=MIN_CNPV_REALISED_RATIO,
                alert_level=ALERT_WARNING,
                message="No closed cohort data available for backtesting",
            )

        total_predicted = df_closed_cohort["predicted_cnpv"].sum()
        total_realised  = df_closed_cohort["realised_12m_revenue"].sum()

        if total_predicted <= 0:
            return MonitorResult(
                monitor_name="cnpv_backtesting",
                passed=False,
                metric_value=None,
                threshold=MIN_CNPV_REALISED_RATIO,
                alert_level=ALERT_WARNING,
                message="Sum of predicted CNPV is zero or negative; cannot compute ratio",
            )

        ratio  = total_realised / total_predicted
        passed = ratio >= MIN_CNPV_REALISED_RATIO
        level  = ALERT_OK if passed else ALERT_CRITICAL

        return MonitorResult(
            monitor_name="cnpv_backtesting",
            passed=passed,
            metric_value=round(ratio, 4),
            threshold=MIN_CNPV_REALISED_RATIO,
            alert_level=level,
            message=(
                f"CNPV realised/predicted ratio = {ratio:.2%} "
                f"({'PASS' if passed else 'FAIL — trigger model review'})"
            ),
        )

    # ------------------------------------------------------------------
    # 2. FTP PSI
    # ------------------------------------------------------------------

    def check_ftp_psi(
        self,
        ftp_rates_current: pd.Series,
        ftp_rates_prior: pd.Series,
        n_bins: int = 10,
    ) -> MonitorResult:
        """Compute PSI on FTP rate distribution vs prior quarter.

        Parameters
        ----------
        ftp_rates_current:
            Series of computed FTP rates for the current period.
        ftp_rates_prior:
            Series of computed FTP rates for the prior quarter.
        """
        if ftp_rates_current.empty or ftp_rates_prior.empty:
            return MonitorResult(
                monitor_name="ftp_psi",
                passed=True,
                metric_value=None,
                threshold=MAX_FTP_PSI,
                alert_level=ALERT_WARNING,
                message="Insufficient data to compute FTP PSI",
            )

        psi = _compute_psi(ftp_rates_current, ftp_rates_prior, n_bins=n_bins)
        passed = psi <= MAX_FTP_PSI
        level  = ALERT_OK if passed else ALERT_WARNING

        return MonitorResult(
            monitor_name="ftp_psi",
            passed=passed,
            metric_value=round(psi, 4),
            threshold=MAX_FTP_PSI,
            alert_level=level,
            message=(
                f"FTP PSI = {psi:.4f} "
                f"({'OK' if passed else 'ESCALATE to treasury'})"
            ),
        )

    # ------------------------------------------------------------------
    # 3. Approval rate drift
    # ------------------------------------------------------------------

    def check_approval_rate_drift(
        self,
        current_approval_rate: float,
    ) -> MonitorResult:
        """Check whether the daily approval rate has drifted by > 5 pp.

        Parameters
        ----------
        current_approval_rate:
            Rolling 30-day approval rate for live originations (fraction).
        """
        delta_pp = abs(current_approval_rate - self.baseline_approval_rate) * 100
        passed   = delta_pp <= MAX_APPROVAL_RATE_DELTA_PP
        level    = ALERT_OK if passed else ALERT_WARNING

        return MonitorResult(
            monitor_name="approval_rate_drift",
            passed=passed,
            metric_value=round(delta_pp, 2),
            threshold=MAX_APPROVAL_RATE_DELTA_PP,
            alert_level=level,
            message=(
                f"Approval rate delta = {delta_pp:.1f} pp vs baseline "
                f"({current_approval_rate:.1%} vs {self.baseline_approval_rate:.1%})"
                f" — {'OK' if passed else 'CHAMPION/CHALLENGER alert'}"
            ),
        )

    # ------------------------------------------------------------------
    # 4. Scenario monotonicity audit
    # ------------------------------------------------------------------

    def check_scenario_monotonicity(
        self,
        df_results: pd.DataFrame,
    ) -> MonitorResult:
        """Verify recession CNPV < worsening CNPV < base CNPV for >= 99% of records.

        Parameters
        ----------
        df_results:
            Batch result DataFrame with columns:
            ``cnpv_base``, ``cnpv_worsening``, ``cnpv_recession``.
        """
        if df_results.empty:
            return MonitorResult(
                monitor_name="scenario_monotonicity",
                passed=False,
                metric_value=None,
                threshold=MIN_MONOTONE_PCT,
                alert_level=ALERT_CRITICAL,
                message="No batch results to audit",
            )

        monotone_mask = (
            (df_results["cnpv_recession"] <= df_results["cnpv_worsening"]) &
            (df_results["cnpv_worsening"] <= df_results["cnpv_base"])
        )
        monotone_pct = float(monotone_mask.mean())
        passed       = monotone_pct >= MIN_MONOTONE_PCT
        level        = ALERT_OK if passed else ALERT_CRITICAL

        return MonitorResult(
            monitor_name="scenario_monotonicity",
            passed=passed,
            metric_value=round(monotone_pct, 4),
            threshold=MIN_MONOTONE_PCT,
            alert_level=level,
            message=(
                f"Monotone pct = {monotone_pct:.2%} "
                f"({'OK' if passed else 'BLOCK batch — page on-call'})"
            ),
        )

    # ------------------------------------------------------------------
    # 5. Capital headroom breach
    # ------------------------------------------------------------------

    def check_capital_headroom(
        self,
        capital_consumed: float,
    ) -> MonitorResult:
        """Check whether remaining capital drops below 10% of the buffer.

        Parameters
        ----------
        capital_consumed:
            Capital consumed by ACQUIRE decisions in the current batch (USD).
        """
        remaining     = self.cet1_buffer_available - capital_consumed
        headroom_pct  = remaining / self.cet1_buffer_available if self.cet1_buffer_available > 0 else 0
        passed        = headroom_pct >= MIN_CAPITAL_HEADROOM_PCT
        level         = ALERT_OK if passed else ALERT_CRITICAL

        return MonitorResult(
            monitor_name="capital_headroom",
            passed=passed,
            metric_value=round(headroom_pct, 4),
            threshold=MIN_CAPITAL_HEADROOM_PCT,
            alert_level=level,
            message=(
                f"Capital headroom = {headroom_pct:.1%} "
                f"(remaining ${remaining:,.0f} of ${self.cet1_buffer_available:,.0f}) "
                f"{'OK' if passed else '— AUTO-PAUSE originations'}"
            ),
        )

    # ------------------------------------------------------------------
    # 6. Adverse action code coverage
    # ------------------------------------------------------------------

    def check_adverse_action_coverage(
        self,
        df_declines: pd.DataFrame,
    ) -> MonitorResult:
        """Verify every DECLINE has >= 2 ECOA Regulation B reason codes.

        Parameters
        ----------
        df_declines:
            DataFrame with column ``reason_codes`` (list or JSON string).
        """
        if df_declines.empty:
            return MonitorResult(
                monitor_name="adverse_action_coverage",
                passed=True,
                metric_value=1.0,
                threshold=1.0,
                alert_level=ALERT_OK,
                message="No declines in this batch",
            )

        def _code_count(val: Any) -> int:
            if isinstance(val, list):
                return len(val)
            if isinstance(val, str):
                import json
                try:
                    parsed = json.loads(val)
                    return len(parsed) if isinstance(parsed, list) else 0
                except Exception:
                    return 0
            return 0

        code_counts    = df_declines["reason_codes"].apply(_code_count)
        coverage_rate  = float((code_counts >= 2).mean())
        passed         = coverage_rate == 1.0
        level          = ALERT_OK if passed else ALERT_CRITICAL

        return MonitorResult(
            monitor_name="adverse_action_coverage",
            passed=passed,
            metric_value=round(coverage_rate, 4),
            threshold=1.0,
            alert_level=level,
            message=(
                f"Adverse action code coverage = {coverage_rate:.2%} "
                f"({'OK' if passed else 'COMPLIANCE ALERT — declines missing reason codes'})"
            ),
        )

    # ------------------------------------------------------------------
    # 7. Audit completeness
    # ------------------------------------------------------------------

    def check_audit_completeness(
        self,
        origination_ids: list[str],
        audit_ids: list[str],
    ) -> MonitorResult:
        """Verify every origination_id appears in the audit_log.

        Parameters
        ----------
        origination_ids:
            List of origination IDs from the batch.
        audit_ids:
            List of origination IDs present in the audit_log for the same period.
        """
        batch_set  = set(origination_ids)
        audit_set  = set(audit_ids)
        missing    = batch_set - audit_set
        missing_pct = len(missing) / len(batch_set) if batch_set else 0.0
        passed     = len(missing) == 0
        level      = ALERT_OK if passed else ALERT_CRITICAL

        return MonitorResult(
            monitor_name="audit_completeness",
            passed=passed,
            metric_value=round(missing_pct, 4),
            threshold=0.0,
            alert_level=level,
            message=(
                f"{len(missing)} origination IDs missing from audit_log "
                f"({missing_pct:.2%}) — "
                f"{'OK' if passed else 'CRITICAL — audit gap detected'}"
            ),
        )

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run_all(
        self,
        df_batch_results: Optional[pd.DataFrame] = None,
        df_closed_cohort: Optional[pd.DataFrame] = None,
        ftp_rates_current: Optional[pd.Series] = None,
        ftp_rates_prior: Optional[pd.Series] = None,
        current_approval_rate: Optional[float] = None,
        capital_consumed: float = 0.0,
        df_declines: Optional[pd.DataFrame] = None,
        origination_ids: Optional[list[str]] = None,
        audit_ids: Optional[list[str]] = None,
    ) -> list[MonitorResult]:
        """Run all monitors and return a list of MonitorResult objects.

        Only monitors with sufficient input data are executed.
        """
        results: list[MonitorResult] = []

        if df_closed_cohort is not None:
            results.append(self.check_cnpv_backtesting(df_closed_cohort))

        if ftp_rates_current is not None and ftp_rates_prior is not None:
            results.append(self.check_ftp_psi(ftp_rates_current, ftp_rates_prior))

        if current_approval_rate is not None:
            results.append(self.check_approval_rate_drift(current_approval_rate))

        if df_batch_results is not None:
            results.append(self.check_scenario_monotonicity(df_batch_results))

        results.append(self.check_capital_headroom(capital_consumed))

        if df_declines is not None:
            results.append(self.check_adverse_action_coverage(df_declines))

        if origination_ids is not None and audit_ids is not None:
            results.append(self.check_audit_completeness(origination_ids, audit_ids))

        # Log summary
        n_fail = sum(1 for r in results if not r.passed)
        n_crit = sum(1 for r in results if r.alert_level == ALERT_CRITICAL)
        logger.info(
            "CCValuationMonitor: %d checks, %d failed, %d critical",
            len(results), n_fail, n_crit,
        )
        for r in results:
            if not r.passed:
                logger.warning("Monitor %s FAILED: %s", r.monitor_name, r.message)

        return results


# ---------------------------------------------------------------------------
# PSI utility
# ---------------------------------------------------------------------------


def _compute_psi(
    expected: pd.Series,
    actual: pd.Series,
    n_bins: int = 10,
    epsilon: float = 1e-6,
) -> float:
    """Compute Population Stability Index between two numeric distributions."""
    min_val = min(expected.min(), actual.min())
    max_val = max(expected.max(), actual.max())
    breakpoints = np.linspace(min_val, max_val, n_bins + 1)

    exp_counts  = np.histogram(expected, bins=breakpoints)[0]
    act_counts  = np.histogram(actual,   bins=breakpoints)[0]

    exp_pct = exp_counts / (len(expected) + epsilon)
    act_pct = act_counts / (len(actual)   + epsilon)

    # Avoid log(0)
    exp_pct = np.where(exp_pct < epsilon, epsilon, exp_pct)
    act_pct = np.where(act_pct < epsilon, epsilon, act_pct)

    psi = float(np.sum((exp_pct - act_pct) * np.log(exp_pct / act_pct)))
    return max(0.0, psi)
