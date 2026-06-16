"""Tests for PortfolioSnapshot (S3-B)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monitoring.portfolio_snapshot import PortfolioSnapshot, compute_snapshot, _pd_to_rating


def _make_df(n: int = 100, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    decisions = rng.choice(["APPROVE", "REJECT", "MANUAL_REVIEW"], size=n, p=[0.7, 0.2, 0.1])
    return pd.DataFrame({
        "account_id": [f"ACC-{i:04d}" for i in range(n)],
        "decision": decisions,
        "pd_score": rng.beta(2, 20, size=n),
        "lgd_score": rng.beta(3, 7, size=n),
        "exposure": rng.lognormal(10, 1, size=n),
        "originated_at": pd.date_range(
            end=pd.Timestamp.utcnow(), periods=n, freq="6h"
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dpd_30": rng.choice([True, False], size=n, p=[0.05, 0.95]),
        "dpd_60": rng.choice([True, False], size=n, p=[0.02, 0.98]),
        "dpd_90": rng.choice([True, False], size=n, p=[0.01, 0.99]),
    })


class TestPortfolioSnapshot:
    def test_returns_portfolio_snapshot(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert isinstance(snap, PortfolioSnapshot)

    def test_total_accounts(self):
        df = _make_df(50)
        snap = compute_snapshot(df)
        assert snap.total_accounts == 50

    def test_total_exposure_matches(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert abs(snap.total_exposure - float(df["exposure"].sum())) < 0.01

    def test_wa_pd_is_exposure_weighted(self):
        df = _make_df()
        snap = compute_snapshot(df)
        expected_wa_pd = float(
            (df["pd_score"] * df["exposure"]).sum() / df["exposure"].sum()
        )
        assert abs(snap.wa_pd - expected_wa_pd) < 1e-5

    def test_wa_lgd_is_exposure_weighted(self):
        df = _make_df()
        snap = compute_snapshot(df)
        expected_wa_lgd = float(
            (df["lgd_score"] * df["exposure"]).sum() / df["exposure"].sum()
        )
        assert abs(snap.wa_lgd - expected_wa_lgd) < 1e-5

    def test_wa_el_equals_wa_pd_times_wa_lgd(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert abs(snap.wa_el - snap.wa_pd * snap.wa_lgd) < 1e-5

    def test_expected_loss_dollars(self):
        df = _make_df()
        snap = compute_snapshot(df)
        expected = float((df["pd_score"] * df["lgd_score"] * df["exposure"]).sum())
        assert abs(snap.expected_loss_dollars - expected) < 0.01

    def test_risk_rating_distribution_sums_to_one(self):
        df = _make_df()
        snap = compute_snapshot(df)
        total = sum(snap.risk_rating_distribution.values())
        assert abs(total - 1.0) < 1e-4

    def test_risk_rating_all_buckets_present(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert set(snap.risk_rating_distribution.keys()) == {
            "Prime", "Near-Prime", "Subprime", "Deep-Subprime"
        }

    def test_delinquency_rates_present(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert "30dpd" in snap.delinquency_rates
        assert "60dpd" in snap.delinquency_rates
        assert "90dpd" in snap.delinquency_rates

    def test_delinquency_rates_are_fractions(self):
        df = _make_df()
        snap = compute_snapshot(df)
        for key, rate in snap.delinquency_rates.items():
            assert 0.0 <= rate <= 1.0, f"{key} rate {rate} out of [0,1]"

    def test_missing_lgd_col_defaults_to_040(self):
        df = _make_df()
        df = df.drop(columns=["lgd_score"])
        snap = compute_snapshot(df)
        assert abs(snap.wa_lgd - 0.40) < 1e-4

    def test_missing_required_column_raises(self):
        df = pd.DataFrame({"account_id": ["A"], "exposure": [1000]})
        with pytest.raises(ValueError, match="missing columns"):
            compute_snapshot(df)

    def test_approval_rates_are_fractions(self):
        df = _make_df()
        snap = compute_snapshot(df)
        assert 0.0 <= snap.approval_rate_mtd <= 1.0
        assert 0.0 <= snap.approval_rate_qtd <= 1.0


class TestPdToRating:
    def test_prime(self):
        assert _pd_to_rating(0.01) == "Prime"
        assert _pd_to_rating(0.029) == "Prime"

    def test_near_prime(self):
        assert _pd_to_rating(0.03) == "Near-Prime"
        assert _pd_to_rating(0.07) == "Near-Prime"

    def test_subprime(self):
        assert _pd_to_rating(0.08) == "Subprime"
        assert _pd_to_rating(0.14) == "Subprime"

    def test_deep_subprime(self):
        assert _pd_to_rating(0.15) == "Deep-Subprime"
        assert _pd_to_rating(0.50) == "Deep-Subprime"
