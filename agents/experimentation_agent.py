"""
Experimentation Agent
======================
Domain Owner : Credit Risk Strategy / ML Platform
SR 11-7 Stage: Champion/Challenger model governance

Responsibilities
----------------
* Manage champion/challenger A/B experiment lifecycle
* Route a configurable traffic % to challenger model
* Compute significance tests (chi-squared for approval rate, t-test for profit)
* Produce experiment evaluation reports
* Support gradual challenger promotion workflow

Inputs  : experiment config, scored results from champion + challenger
Outputs : AgentResult.payload["experiment_report"] = ExperimentReport
          AgentResult.payload["recommendation"]     = "promote" | "keep" | "inconclusive"
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from agents.base import AgentResult, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Experiment dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ExperimentArm:
    arm_id: str           # "control" | "treatment"
    model_version: str
    n_applications: int = 0
    n_approved: int = 0
    avg_pd_score: float = 0.0
    avg_profit: float = 0.0
    avg_rate: float = 0.0
    approval_rate: float = 0.0


@dataclass
class ExperimentReport:
    experiment_id: str
    started_at: str
    ended_at: Optional[str]
    status: str                          # "active" | "concluded" | "insufficient_data"
    control: ExperimentArm
    treatment: ExperimentArm
    primary_metric: str
    approval_rate_lift_pct: float        # treatment vs control
    profit_lift_pct: float
    chi2_stat: float
    p_value: float
    is_significant: bool
    recommendation: str                  # "promote" | "keep" | "inconclusive"
    recommendation_rationale: str
    min_sample_size_met: bool
    generated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Traffic Router
# ---------------------------------------------------------------------------


def route_to_arm(application_id: str, treatment_pct: float) -> str:
    """
    Deterministic, stable routing via MD5 hash modulo 100.
    Same application_id always routes to the same arm.
    Returns "treatment" or "control".
    """
    h = int(hashlib.md5(application_id.encode()).hexdigest(), 16) % 100
    return "treatment" if h < int(treatment_pct * 100) else "control"


# ---------------------------------------------------------------------------
# ExperimentationAgent
# ---------------------------------------------------------------------------


class ExperimentationAgent(BaseAgent):
    """
    Runs champion/challenger experiments and evaluates statistical significance.

    Config keys (agent_config.yaml → experimentation):
      default_experiment_duration_days, min_sample_size_per_arm,
      significance_level, primary_metric, traffic_split.treatment
    """

    name = "ExperimentationAgent"

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self._duration_days: int = self.config.get("default_experiment_duration_days", 14)
        self._min_n: int = self.config.get("min_sample_size_per_arm", 500)
        self._alpha: float = self.config.get("significance_level", 0.05)
        self._primary_metric: str = self.config.get("primary_metric", "approval_rate")
        self._treatment_pct: float = self.config.get(
            "traffic_split", {}
        ).get("treatment", 0.10)

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def assign_arm(self, application_id: str) -> str:
        """Assign application to control or treatment."""
        return route_to_arm(application_id, self._treatment_pct)

    # ------------------------------------------------------------------
    # Statistical testing
    # ------------------------------------------------------------------

    def _run_chi2_approval_rate(
        self,
        control_n: int,
        control_approved: int,
        treatment_n: int,
        treatment_approved: int,
    ) -> Tuple[float, float]:
        """Chi-squared test on approval proportions."""
        if control_n == 0 or treatment_n == 0:
            return 0.0, 1.0
        contingency = [
            [control_approved, control_n - control_approved],
            [treatment_approved, treatment_n - treatment_approved],
        ]
        chi2, p, _, _ = stats.chi2_contingency(contingency, correction=False)
        return float(chi2), float(p)

    def _run_ttest_profit(
        self,
        control_profits: List[float],
        treatment_profits: List[float],
    ) -> Tuple[float, float]:
        if len(control_profits) < 2 or len(treatment_profits) < 2:
            return 0.0, 1.0
        stat, p = stats.ttest_ind(treatment_profits, control_profits, equal_var=False)
        return float(stat), float(p)

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "experiment_id"    : str         — experiment identifier
          "started_at"       : str         — ISO datetime
          "control_scores"   : List[dict]  — ModelScores for control arm
          "treatment_scores" : List[dict]  — ModelScores for treatment arm
          "control_decisions"  : List[dict]  — CreditDecision for control
          "treatment_decisions": List[dict]  — CreditDecision for treatment
        """
        experiment_id: str = inputs.get("experiment_id", str(uuid.uuid4()))
        started_at: str = inputs.get("started_at", datetime.utcnow().isoformat())
        control_scores: List[Dict] = inputs.get("control_scores", [])
        treatment_scores: List[Dict] = inputs.get("treatment_scores", [])
        control_decisions: List[Dict] = inputs.get("control_decisions", [])
        treatment_decisions: List[Dict] = inputs.get("treatment_decisions", [])

        # ── Build arm summaries ─────────────────────────────────────────
        def _arm_summary(
            scores: List[Dict], decisions: List[Dict], arm_id: str
        ) -> ExperimentArm:
            n = len(decisions)
            if n == 0:
                return ExperimentArm(
                    arm_id=arm_id,
                    model_version="unknown",
                    n_applications=0,
                )
            approved = sum(1 for d in decisions if d.get("decision") == "APPROVE")
            model_version = scores[0].get("model_version", arm_id) if scores else arm_id
            avg_pd = float(np.mean([s.get("pd_score", 0) for s in scores])) if scores else 0.0
            avg_profit = float(np.mean([
                s.get("expected_profit", 0) or 0 for s in scores
            ])) if scores else 0.0
            avg_rate = float(np.mean([
                s.get("recommended_rate", 0) or 0 for s in scores
            ])) if scores else 0.0
            return ExperimentArm(
                arm_id=arm_id,
                model_version=model_version,
                n_applications=n,
                n_approved=approved,
                avg_pd_score=round(avg_pd, 4),
                avg_profit=round(avg_profit, 2),
                avg_rate=round(avg_rate, 4),
                approval_rate=round(approved / max(n, 1), 4),
            )

        control = _arm_summary(control_scores, control_decisions, "control")
        treatment = _arm_summary(treatment_scores, treatment_decisions, "treatment")

        # ── Statistical tests ───────────────────────────────────────────
        chi2_stat, p_value = self._run_chi2_approval_rate(
            control_n=control.n_applications,
            control_approved=control.n_approved,
            treatment_n=treatment.n_applications,
            treatment_approved=treatment.n_approved,
        )

        is_significant = p_value < self._alpha
        min_n_met = (
            control.n_applications >= self._min_n
            and treatment.n_applications >= self._min_n
        )

        # ── Compute lifts ───────────────────────────────────────────────
        approval_lift = (
            (treatment.approval_rate - control.approval_rate)
            / max(control.approval_rate, 1e-9) * 100
        )
        profit_lift = (
            (treatment.avg_profit - control.avg_profit)
            / max(abs(control.avg_profit), 1e-9) * 100
        )

        # ── Recommendation ──────────────────────────────────────────────
        if not min_n_met:
            recommendation = "inconclusive"
            rationale = (
                f"Insufficient sample size. Required {self._min_n} per arm; "
                f"got control={control.n_applications}, treatment={treatment.n_applications}."
            )
        elif is_significant and approval_lift > 0 and profit_lift >= 0:
            recommendation = "promote"
            rationale = (
                f"Treatment shows statistically significant improvement "
                f"(p={p_value:.4f} < {self._alpha}). "
                f"Approval lift: {approval_lift:+.1f}%, Profit lift: {profit_lift:+.1f}%. "
                "Recommend promoting challenger to champion."
            )
        elif is_significant and (approval_lift < 0 or profit_lift < -5):
            recommendation = "keep"
            rationale = (
                f"Treatment shows significant degradation "
                f"(p={p_value:.4f}, approval lift: {approval_lift:+.1f}%). "
                "Recommend keeping current champion."
            )
        else:
            recommendation = "inconclusive"
            rationale = (
                f"No statistically significant difference detected "
                f"(p={p_value:.4f} >= {self._alpha}). Extend experiment or review configs."
            )

        report = ExperimentReport(
            experiment_id=experiment_id,
            started_at=started_at,
            ended_at=datetime.utcnow().isoformat(),
            status="concluded" if min_n_met else "insufficient_data",
            control=control,
            treatment=treatment,
            primary_metric=self._primary_metric,
            approval_rate_lift_pct=round(approval_lift, 2),
            profit_lift_pct=round(profit_lift, 2),
            chi2_stat=round(chi2_stat, 4),
            p_value=round(p_value, 6),
            is_significant=is_significant,
            recommendation=recommendation,
            recommendation_rationale=rationale,
            min_sample_size_met=min_n_met,
        )

        self._log.info(
            "Experiment %s: %s — p=%.4f, approval_lift=%.1f%%",
            experiment_id,
            recommendation.upper(),
            p_value,
            approval_lift,
        )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "experiment_report": report.to_dict(),
                "recommendation": recommendation,
                "experiment_id": experiment_id,
            },
        )
