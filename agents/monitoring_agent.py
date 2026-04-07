"""
Monitoring & Drift Agent
=========================
Domain Owner : MLOps / Model Risk Management
SR 11-7 Stage: Ongoing model surveillance

Responsibilities
----------------
* PSI + KS feature drift detection (vs reference / training distribution)
* ECOA/HMDA fair lending analysis (DIR, approval parity, geographic bias)
* Decision distribution monitoring (approval rate bands)
* Alert generation when drift exceeds configured thresholds
* Persist audit reports to output directories

Inputs  : reference_df, production_df, decisions_df, demographic context
Outputs : AgentResult.payload["drift_report"]       = DriftReport
          AgentResult.payload["fair_lending_report"] = FairLendingReport
          AgentResult.payload["alerts"]              = List[dict]
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from agents.base import AgentResult, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

try:
    from monitoring.drift_monitor import monitor_drift, DriftReport
    from monitoring.fair_lending import analyze_fair_lending, FairLendingReport
    _MONITORING_AVAILABLE = True
except ImportError:
    _MONITORING_AVAILABLE = False
    logger.warning("Monitoring packages not importable — MonitoringAgent in stub mode")


# ---------------------------------------------------------------------------
# Alert Generator
# ---------------------------------------------------------------------------


def _build_alert(level: str, category: str, title: str, body: str) -> Dict[str, Any]:
    return {
        "level": level,          # "critical" | "warning" | "info"
        "category": category,    # "drift" | "fair_lending" | "decision_dist"
        "title": title,
        "body": body,
        "triggered_at": datetime.utcnow().isoformat(),
    }


# ---------------------------------------------------------------------------
# MonitoringAgent
# ---------------------------------------------------------------------------


class MonitoringAgent(BaseAgent):
    """
    Runs PSI drift + fair lending analyses and emits alerts.

    Config keys (agent_config.yaml → monitoring):
      drift.psi_stable_threshold, drift.psi_minor_threshold,
      drift.n_bins, drift.report_output_dir,
      fair_lending.protected_attributes, fair_lending.dir_flag_threshold,
      fair_lending.report_output_dir
    """

    name = "MonitoringAgent"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        drift_cfg = self.config.get("drift", {})
        fl_cfg = self.config.get("fair_lending", {})
        self._psi_stable = drift_cfg.get("psi_stable_threshold", 0.10)
        self._psi_minor = drift_cfg.get("psi_minor_threshold", 0.25)
        self._n_bins = drift_cfg.get("n_bins", 10)
        self._drift_output_dir: Optional[str] = drift_cfg.get("report_output_dir")
        self._fl_output_dir: Optional[str] = fl_cfg.get("report_output_dir")
        self._protected_attrs: List[str] = fl_cfg.get("protected_attributes", [])
        self._dir_threshold: float = fl_cfg.get("dir_flag_threshold", 0.80)

    # ------------------------------------------------------------------
    # Decision distribution monitor
    # ------------------------------------------------------------------

    def _monitor_decision_distribution(
        self, decisions_df: pd.DataFrame
    ) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Compute approval rate bands and flag unusual distribution shifts."""
        alerts: List[Dict[str, Any]] = []
        if "decision" not in decisions_df.columns or decisions_df.empty:
            return {}, alerts

        n = len(decisions_df)
        counts = decisions_df["decision"].value_counts().to_dict()
        approval_rate = counts.get("APPROVE", 0) / max(n, 1)
        reject_rate = counts.get("REJECT", 0) / max(n, 1)

        dist = {
            "total": n,
            "approval_rate_pct": round(approval_rate * 100, 2),
            "rejection_rate_pct": round(reject_rate * 100, 2),
            "review_rate_pct": round((1 - approval_rate - reject_rate) * 100, 2),
            "decision_counts": counts,
        }

        # Alert if unusual
        if approval_rate > 0.90:
            alerts.append(_build_alert(
                "warning", "decision_dist",
                "High Approval Rate Detected",
                f"Approval rate {approval_rate:.1%} exceeds 90% — review policy cutoffs."
            ))
        if reject_rate > 0.80:
            alerts.append(_build_alert(
                "warning", "decision_dist",
                "High Rejection Rate Detected",
                f"Rejection rate {reject_rate:.1%} exceeds 80% — review model score distribution."
            ))

        return dist, alerts

    # ------------------------------------------------------------------
    # Stub responses when packages unavailable
    # ------------------------------------------------------------------

    @staticmethod
    def _stub_drift_report() -> Dict[str, Any]:
        return {
            "overall_drift_status": "stable",
            "features_with_major_drift": [],
            "features_with_minor_drift": [],
            "stub": True,
        }

    @staticmethod
    def _stub_fl_report() -> Dict[str, Any]:
        return {
            "dir_score": 1.0,
            "dir_flag": False,
            "summary_text": "Fair lending analysis not available (stub mode)",
            "stub": True,
        }

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "reference_df"     : pd.DataFrame | List[dict]  — training/reference features
          "production_df"    : pd.DataFrame | List[dict]  — live production features
          "decisions_df"     : pd.DataFrame | List[dict]  — decision audit records
          "feature_list"     : List[str]                  — features to monitor
          "protected_col"    : str                        — e.g. "race" (optional)
          "control_group"    : str                        — reference demographic
        """
        ref = inputs.get("reference_df")
        prod = inputs.get("production_df")
        decisions = inputs.get("decisions_df")
        feature_list: List[str] = inputs.get("feature_list", [])
        protected_col: Optional[str] = inputs.get("protected_col")
        control_group: Optional[str] = inputs.get("control_group")

        alerts: List[Dict[str, Any]] = []
        drift_report_dict: Dict[str, Any] = {}
        fl_report_dict: Dict[str, Any] = {}
        decision_dist: Dict[str, Any] = {}

        # ── Drift Analysis ──────────────────────────────────────────────
        if ref is not None and prod is not None:
            if isinstance(ref, list):
                ref = pd.DataFrame(ref)
            if isinstance(prod, list):
                prod = pd.DataFrame(prod)

            if _MONITORING_AVAILABLE and feature_list:
                try:
                    drift_report: DriftReport = monitor_drift(
                        reference_df=ref,
                        production_df=prod,
                        feature_list=feature_list,
                        n_bins=self._n_bins,
                        output_dir=self._drift_output_dir,
                    )
                    drift_report_dict = {
                        "overall_drift_status": drift_report.overall_drift_status,
                        "features_with_major_drift": drift_report.features_with_major_drift,
                        "features_with_minor_drift": drift_report.features_with_minor_drift,
                        "n_reference_rows": drift_report.n_reference_rows,
                        "n_production_rows": drift_report.n_production_rows,
                        "report_timestamp": drift_report.report_timestamp,
                    }
                    if drift_report.features_with_major_drift:
                        alerts.append(_build_alert(
                            "critical", "drift",
                            "Major Feature Drift Detected",
                            f"Features with major PSI drift: {drift_report.features_with_major_drift}. "
                            "Immediate model review required."
                        ))
                    elif drift_report.features_with_minor_drift:
                        alerts.append(_build_alert(
                            "warning", "drift",
                            "Minor Feature Drift Detected",
                            f"Features with minor PSI drift: {drift_report.features_with_minor_drift}."
                        ))
                except Exception as exc:  # noqa: BLE001
                    self._log.error("Drift analysis failed: %s", exc)
                    drift_report_dict = self._stub_drift_report()
            else:
                drift_report_dict = self._stub_drift_report()

        # ── Fair Lending Analysis ───────────────────────────────────────
        if decisions is not None and protected_col and control_group:
            if isinstance(decisions, list):
                decisions = pd.DataFrame(decisions)

            if _MONITORING_AVAILABLE:
                try:
                    fl_report: FairLendingReport = analyze_fair_lending(
                        decisions_df=decisions,
                        protected_col=protected_col,
                        control_group=control_group,
                        output_dir=self._fl_output_dir,
                    )
                    fl_report_dict = {
                        "dir_score": fl_report.dir_score,
                        "dir_flag": fl_report.dir_flag,
                        "protected_approval_rate": fl_report.protected_approval_rate,
                        "control_approval_rate": fl_report.control_approval_rate,
                        "approval_parity_flag": fl_report.approval_parity_flag,
                        "geographic_flags": fl_report.geographic_flags,
                        "summary_text": fl_report.summary_text,
                    }
                    if fl_report.dir_flag:
                        alerts.append(_build_alert(
                            "critical", "fair_lending",
                            "Disparate Impact Detected",
                            f"DIR = {fl_report.dir_score:.3f} < {self._dir_threshold} threshold. "
                            "Immediate compliance review required."
                        ))
                except Exception as exc:  # noqa: BLE001
                    self._log.error("Fair lending analysis failed: %s", exc)
                    fl_report_dict = self._stub_fl_report()

        # ── Decision Distribution ───────────────────────────────────────
        if decisions is not None:
            if isinstance(decisions, list):
                decisions = pd.DataFrame(decisions)
            if not decisions.empty:
                decision_dist, dist_alerts = self._monitor_decision_distribution(decisions)
                alerts.extend(dist_alerts)

        self._log.info(
            "Monitoring complete: drift_status=%s, alerts=%d",
            drift_report_dict.get("overall_drift_status", "N/A"),
            len(alerts),
        )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "drift_report": drift_report_dict,
                "fair_lending_report": fl_report_dict,
                "decision_distribution": decision_dist,
                "alerts": alerts,
            },
        )
