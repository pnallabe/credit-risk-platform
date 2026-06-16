"""Tests for PortfolioConstructionAgent (S3-C)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monitoring.concentration_monitor import ConcentrationMonitor
from monitoring.portfolio_snapshot import compute_snapshot
from agents.portfolio_construction_agent import (
    PortfolioConstructionAgent,
    RebalancingAction,
    RebalancingPlan,
)


def _make_breach_df(n: int = 100) -> pd.DataFrame:
    """Portfolio where sector '44' is 60% — clear breach."""
    naics = ["44"] * 60 + ["52"] * 40
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "account_id": [f"ACC-{i:04d}" for i in range(n)],
        "decision": ["APPROVE"] * n,
        "exposure": [10_000.0] * n,
        "naics_2d": naics,
        "state": list(rng.choice(["CA", "TX", "FL", "NY"], size=n)),
        "risk_grade": list(rng.choice(["Prime", "Near-Prime"], size=n)),
        "product_type": list(rng.choice(["credit_card", "personal_loan"], size=n)),
        "pd_score": list(rng.beta(2, 20, size=n)),
        "lgd_score": list(rng.beta(3, 7, size=n)),
        "originated_at": pd.date_range(
            end=pd.Timestamp.utcnow(), periods=n, freq="6h"
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dpd_30": [False] * n,
        "dpd_60": [False] * n,
        "dpd_90": [False] * n,
    })


def _make_clean_df(n: int = 100) -> pd.DataFrame:
    """Well-distributed portfolio — no breaches."""
    rng = np.random.default_rng(9)
    return pd.DataFrame({
        "account_id": [f"ACC-{i:04d}" for i in range(n)],
        "decision": ["APPROVE"] * n,
        "exposure": [10_000.0] * n,
        "naics_2d": list(rng.choice(["44", "52", "53", "54", "72", "23", "62", "31"], size=n)),
        "state": list(rng.choice(["CA", "TX", "FL", "NY", "IL", "OH", "PA", "WA"], size=n)),
        "risk_grade": list(rng.choice(["Prime", "Near-Prime"], size=n, p=[0.6, 0.4])),
        "product_type": list(rng.choice(["credit_card", "personal_loan", "mortgage"], size=n)),
        "pd_score": list(rng.beta(2, 30, size=n)),
        "lgd_score": list(rng.beta(2, 8, size=n)),
        "originated_at": pd.date_range(
            end=pd.Timestamp.utcnow(), periods=n, freq="6h"
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dpd_30": [False] * n,
        "dpd_60": [False] * n,
        "dpd_90": [False] * n,
    })


def _build_inputs(df: pd.DataFrame) -> dict:
    monitor = ConcentrationMonitor()
    concentration = monitor.compute_report(df)
    snapshot = compute_snapshot(df)
    return {"concentration_report": concentration, "portfolio_snapshot": snapshot}


class TestPortfolioConstructionAgent:
    def setup_method(self):
        self.agent = PortfolioConstructionAgent()

    def test_returns_rebalancing_plan(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        assert result.ok
        plan = result.payload["rebalancing_plan"]
        assert isinstance(plan, RebalancingPlan)

    def test_breach_case_has_reduce_immediate(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        immediate = [a for a in plan.actions if a.urgency == "Immediate"]
        assert len(immediate) > 0, "Expected at least one Immediate urgency action"
        reduce_actions = [a for a in immediate if a.recommended_action == "REDUCE"]
        assert len(reduce_actions) > 0

    def test_actions_sorted_by_urgency(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        urgency_order = {"Immediate": 0, "Monitor": 1, "Opportunistic": 2}
        orders = [urgency_order.get(a.urgency, 3) for a in plan.actions]
        assert orders == sorted(orders), "Actions are not sorted by urgency"

    def test_clean_portfolio_no_breach_immediate_actions(self):
        """With a well-distributed portfolio the only REDUCE actions should be
        Monitor-level at most (no in_breach segments)."""
        df = _make_clean_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        # No segment should cause an in_breach flag in a clean portfolio
        from monitoring.concentration_monitor import ConcentrationMonitor
        monitor = ConcentrationMonitor()
        from monitoring.portfolio_snapshot import compute_snapshot
        concentration = monitor.compute_report(df)
        in_breach_dims = [d for d in concentration.dimensions if d.in_breach]
        if not in_breach_dims:
            # truly clean: no Immediate actions expected
            immediate = [a for a in plan.actions if a.urgency == "Immediate"]
            assert len(immediate) == 0

    def test_wa_pd_impact_arithmetically_correct(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        # projected = current + sum(impacts for REDUCE actions)
        reduce_impacts = sum(
            a.estimated_wa_pd_impact for a in plan.actions if a.recommended_action == "REDUCE"
        )
        expected_projected = plan.portfolio_wa_pd_current + reduce_impacts
        assert abs(plan.portfolio_wa_pd_projected - max(0.0, expected_projected)) < 1e-5

    def test_plan_summary_is_non_empty(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        assert len(plan.summary) > 20

    def test_action_fields_complete(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        for action in plan.actions:
            assert isinstance(action, RebalancingAction)
            assert action.segment
            assert action.dimension
            assert action.recommended_action in ("REDUCE", "HOLD", "GROW")
            assert action.urgency in ("Immediate", "Monitor", "Opportunistic")
            assert action.reasoning

    def test_current_pcts_are_fractions(self):
        df = _make_breach_df()
        result = self.agent.execute(_build_inputs(df))
        plan = result.payload["rebalancing_plan"]
        for action in plan.actions:
            assert 0.0 <= action.current_pct <= 1.0
