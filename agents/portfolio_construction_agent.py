"""
Portfolio Construction Agent — S3-C
====================================
Generates rebalancing recommendations based on concentration and snapshot data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from agents.base import AgentResult, AgentStatus, BaseAgent
from monitoring.concentration_monitor import ConcentrationReport, ConcentrationDimension
from monitoring.portfolio_snapshot import PortfolioSnapshot

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RebalancingAction:
    segment: str
    dimension: str
    current_pct: float
    limit_pct: float
    recommended_action: Literal["REDUCE", "HOLD", "GROW"]
    urgency: Literal["Immediate", "Monitor", "Opportunistic"]
    reasoning: str
    estimated_wa_pd_impact: float


@dataclass
class RebalancingPlan:
    generated_at: str
    portfolio_wa_pd_current: float
    portfolio_wa_pd_projected: float
    actions: List[RebalancingAction]
    summary: str


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class PortfolioConstructionAgent(BaseAgent):
    """Generates portfolio rebalancing recommendations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        concentration_report: ConcentrationReport = inputs["concentration_report"]
        portfolio_snapshot: PortfolioSnapshot = inputs["portfolio_snapshot"]

        actions = self._build_actions(concentration_report, portfolio_snapshot)
        # Sort by urgency: Immediate first, then Monitor, then Opportunistic
        urgency_order = {"Immediate": 0, "Monitor": 1, "Opportunistic": 2}
        actions.sort(key=lambda a: urgency_order.get(a.urgency, 3))

        wa_pd_current = portfolio_snapshot.wa_pd
        wa_pd_projected = self._estimate_projected_wa_pd(
            actions, portfolio_snapshot
        )

        summary = self._build_summary(actions, wa_pd_current, wa_pd_projected)

        plan = RebalancingPlan(
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            portfolio_wa_pd_current=round(wa_pd_current, 6),
            portfolio_wa_pd_projected=round(wa_pd_projected, 6),
            actions=actions,
            summary=summary,
        )

        return AgentResult(
            agent_name=self.__class__.__name__,
            status=AgentStatus.SUCCESS,
            payload={"rebalancing_plan": plan},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_actions(
        self,
        report: ConcentrationReport,
        snapshot: PortfolioSnapshot,
    ) -> List[RebalancingAction]:
        actions: List[RebalancingAction] = []
        total_exposure = report.total_exposure
        wa_pd = snapshot.wa_pd

        for dim in report.dimensions:
            for seg, entry in dim.breakdown.items():
                current_pct = entry.pct_of_total
                limit = dim.configured_limit_pct

                # Determine action
                if dim.in_breach and current_pct == dim.max_observed_pct:
                    action: Literal["REDUCE", "HOLD", "GROW"] = "REDUCE"
                elif dim.at_risk and current_pct == dim.max_observed_pct:
                    # at_risk and could be trending up — REDUCE
                    action = "REDUCE"
                elif (
                    current_pct < 0.3 * limit
                    and dim.dimension != "risk_grade"
                    and not self._is_high_risk_segment(seg, dim.dimension)
                ):
                    action = "GROW"
                else:
                    action = "HOLD"

                # Urgency
                if action == "REDUCE" and current_pct > limit:
                    urgency: Literal["Immediate", "Monitor", "Opportunistic"] = "Immediate"
                elif action == "REDUCE":
                    urgency = "Monitor"
                elif action == "GROW":
                    urgency = "Opportunistic"
                else:
                    urgency = "Monitor"

                # Reasoning
                reasoning = self._build_reasoning(
                    action, seg, dim.dimension, current_pct, limit
                )

                # WA-PD impact estimate
                impact = self._estimate_wa_pd_impact(
                    action, current_pct, limit, wa_pd, total_exposure, entry.exposure
                )

                actions.append(
                    RebalancingAction(
                        segment=f"{dim.dimension}:{seg}",
                        dimension=dim.dimension,
                        current_pct=round(current_pct, 6),
                        limit_pct=limit,
                        recommended_action=action,
                        urgency=urgency,
                        reasoning=reasoning,
                        estimated_wa_pd_impact=round(impact, 6),
                    )
                )

        return actions

    def _is_high_risk_segment(self, seg: str, dimension: str) -> bool:
        if dimension == "risk_grade":
            return seg in {"Subprime", "Deep-Subprime"}
        return False

    def _build_reasoning(
        self,
        action: str,
        seg: str,
        dimension: str,
        current_pct: float,
        limit_pct: float,
    ) -> str:
        excess = max(0.0, current_pct - limit_pct)
        if action == "REDUCE":
            return (
                f"{seg} currently represents {current_pct:.1%} of portfolio, "
                f"{'exceeding' if excess > 0 else 'approaching'} the {limit_pct:.1%} "
                f"concentration limit{f' by {excess:.1%}' if excess > 0 else ''}. "
                f"Recommend reducing new originations in this segment."
            )
        if action == "GROW":
            return (
                f"{seg} at {current_pct:.1%} is well below the {limit_pct:.1%} limit. "
                f"Portfolio diversification benefit available."
            )
        return (
            f"{seg} at {current_pct:.1%} is within the {limit_pct:.1%} concentration limit. "
            f"Continue monitoring."
        )

    def _estimate_wa_pd_impact(
        self,
        action: str,
        current_pct: float,
        limit_pct: float,
        wa_pd: float,
        total_exposure: float,
        seg_exposure: float,
    ) -> float:
        """Estimate change in portfolio WA-PD if this action is executed."""
        if action != "REDUCE" or total_exposure <= 0:
            return 0.0
        excess_pct = max(0.0, current_pct - limit_pct)
        excess_exposure = excess_pct * total_exposure
        # Proxy: assume segment avg PD = wa_pd * 1.3 (higher-risk segments get reduced)
        seg_avg_pd = wa_pd * 1.3
        impact = -(excess_exposure * (seg_avg_pd - wa_pd)) / total_exposure
        return impact

    def _estimate_projected_wa_pd(
        self,
        actions: List[RebalancingAction],
        snapshot: PortfolioSnapshot,
    ) -> float:
        projected = snapshot.wa_pd
        for action in actions:
            if action.recommended_action == "REDUCE":
                projected += action.estimated_wa_pd_impact
        return max(0.0, projected)

    def _build_summary(
        self,
        actions: List[RebalancingAction],
        wa_pd_current: float,
        wa_pd_projected: float,
    ) -> str:
        n_reduce = sum(1 for a in actions if a.recommended_action == "REDUCE")
        n_immediate = sum(1 for a in actions if a.urgency == "Immediate")
        pd_change = wa_pd_projected - wa_pd_current
        direction = "decrease" if pd_change < 0 else "increase"
        return (
            f"Portfolio analysis identified {len(actions)} rebalancing actions "
            f"({n_reduce} reductions, {n_immediate} requiring immediate attention). "
            f"Executing all REDUCE recommendations is estimated to {direction} "
            f"portfolio WA-PD by {abs(pd_change):.3%} "
            f"(from {wa_pd_current:.3%} to {wa_pd_projected:.3%})."
        )
