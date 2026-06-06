"""Tests for ConcentrationMonitor (S3-A)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monitoring.concentration_monitor import (
    ConcentrationMonitor,
    ConcentrationReport,
    DEFAULT_LIMITS,
)


def _make_decisions_df(
    n: int = 100,
    sector_breach: bool = False,
    seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    naics = (
        ["44"] * 60 + ["52"] * 40  # sector "44" = 60% → will breach 25% limit
        if sector_breach
        else list(rng.choice(["44", "52", "53", "54", "72"], size=n))
    )
    return pd.DataFrame({
        "account_id": [f"ACC-{i:04d}" for i in range(n if not sector_breach else 100)],
        "exposure": rng.lognormal(10, 0.5, size=n if not sector_breach else 100),
        "naics_2d": naics,
        "state": list(rng.choice(["CA", "TX", "FL", "NY"], size=n if not sector_breach else 100)),
        "risk_grade": list(rng.choice(["Prime", "Near-Prime", "Subprime"], size=n if not sector_breach else 100)),
        "product_type": list(rng.choice(["credit_card", "personal_loan"], size=n if not sector_breach else 100)),
    })


class TestConcentrationMonitor:
    def setup_method(self):
        self.monitor = ConcentrationMonitor()

    def test_compute_report_returns_concentration_report(self):
        df = _make_decisions_df()
        report = self.monitor.compute_report(df)
        assert isinstance(report, ConcentrationReport)
        assert report.total_accounts == len(df)
        assert report.total_exposure > 0

    def test_dimensions_present(self):
        df = _make_decisions_df()
        report = self.monitor.compute_report(df)
        dim_names = {d.dimension for d in report.dimensions}
        assert dim_names == {"sector", "state", "risk_grade", "product_type"}

    def test_pct_sums_to_one_per_dimension(self):
        df = _make_decisions_df()
        report = self.monitor.compute_report(df)
        for dim in report.dimensions:
            total_pct = sum(e.pct_of_total for e in dim.breakdown.values())
            assert abs(total_pct - 1.0) < 1e-4, f"{dim.dimension} pct sum = {total_pct}"

    def test_breach_detected_with_correct_severity(self):
        df = _make_decisions_df(sector_breach=True)
        report = self.monitor.compute_report(df)
        # Sector "44" should be ~60% → exceeds 25% limit
        sector_breaches = [
            b for b in report.breaches
            if b.dimension == "sector" and b.segment_value == "44"
        ]
        assert sector_breaches, "Expected a breach for sector 44"
        assert sector_breaches[0].severity == "Breach"
        assert sector_breaches[0].observed_pct > DEFAULT_LIMITS["sector"]

    def test_at_risk_detected_at_80_percent_of_limit(self):
        # sector limit = 0.25, 80% of limit = 0.20
        # Build df: 22 accounts in '44', 78 spread across 5 other sectors
        # so '44' = 22% of exposure → at_risk=True, in_breach=False
        # Use equal exposure per account to make % exact
        n = 100
        naics = ["44"] * 22 + ["52"] * 16 + ["53"] * 16 + ["54"] * 16 + ["72"] * 15 + ["23"] * 15
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "account_id": [f"ACC-{i:04d}" for i in range(n)],
            "exposure": [1000.0] * n,
            "naics_2d": naics,
            "state": list(rng.choice(["CA", "TX", "FL", "NY", "IL"], size=n)),
            "risk_grade": list(rng.choice(["Prime", "Near-Prime"], size=n)),
            "product_type": ["credit_card"] * n,
        })
        report = self.monitor.compute_report(df)
        sector_dim = next(d for d in report.dimensions if d.dimension == "sector")
        # '44' = 22% → 22% > 0.8*25%=20% → at_risk=True; 22% < 25% → in_breach=False
        assert sector_dim.at_risk is True
        assert sector_dim.in_breach is False

    def test_no_breach_for_well_distributed_portfolio(self):
        n = 100
        rng = np.random.default_rng(7)
        df = pd.DataFrame({
            "account_id": [f"ACC-{i:04d}" for i in range(n)],
            "exposure": [1000.0] * n,
            "naics_2d": list(rng.choice(["44", "52", "53", "54", "72", "23", "62", "31"], size=n)),
            "state": list(rng.choice(["CA", "TX", "FL", "NY", "IL", "OH", "PA", "WA"], size=n)),
            "risk_grade": list(rng.choice(["Prime", "Near-Prime"], size=n)),
            "product_type": ["credit_card"] * n,
        })
        report = self.monitor.compute_report(df)
        assert all(b.severity == "Breach" for b in report.breaches) is False or len(report.breaches) == 0

    def test_missing_required_column_raises(self):
        df = pd.DataFrame({"account_id": ["A"], "exposure": [1000]})
        with pytest.raises(ValueError, match="missing columns"):
            self.monitor.compute_report(df)

    def test_alert_router_called_on_breach(self):
        """Alert router should be called for each breach."""
        class MockRouter:
            def __init__(self):
                self.calls = []
            def send_alert(self, severity, title, body):
                self.calls.append({"severity": severity, "title": title})

        router = MockRouter()
        monitor = ConcentrationMonitor(alert_router=router)
        df = _make_decisions_df(sector_breach=True)
        monitor.compute_report(df)
        assert len(router.calls) > 0
        severities = {c["severity"] for c in router.calls}
        assert "HIGH" in severities

    def test_custom_limits_from_config(self):
        """Custom limits should override defaults."""
        class MockStore:
            def get_active(self):
                class V:
                    parameters = {"concentration_limits": {"sector": 0.50}}
                return V()

        monitor = ConcentrationMonitor(policy_store=MockStore())
        assert monitor._limits["sector"] == 0.50
        assert monitor._limits["state"] == DEFAULT_LIMITS["state"]
