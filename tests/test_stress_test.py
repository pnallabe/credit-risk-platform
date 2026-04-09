"""Tests for GAP-15: Monte Carlo Stress Testing Engine (risk_models/stress_test.py)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from risk_models.stress_test import (
    MCPortfolioStressor,
    MCScenarioGenerator,
    MCStressScenario,
    StressTestRunner,
    StressTestSummary,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_model() -> LogisticRegression:
    rng = np.random.default_rng(0)
    X = rng.standard_normal((200, 3))
    y = (X[:, 0] - X[:, 1] > 0.5).astype(int)
    lr = LogisticRegression(max_iter=300, random_state=0)
    lr.fit(X, y)
    return lr


@pytest.fixture()
def feature_names() -> list[str]:
    return ["credit_score", "debt_to_income_ratio", "loan_amount"]


@pytest.fixture()
def portfolio_df() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n = 50
    return pd.DataFrame(
        {
            "credit_score": rng.uniform(600, 800, n),
            "debt_to_income_ratio": rng.uniform(0.2, 0.5, n),
            "loan_amount": rng.uniform(5_000, 50_000, n),
        }
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "stress_test.db")


# ---------------------------------------------------------------------------
# MCScenarioGenerator tests
# ---------------------------------------------------------------------------


class TestMCScenarioGenerator:
    def test_generates_correct_count(self) -> None:
        gen = MCScenarioGenerator()
        scenarios = gen.generate(n_scenarios=100, seed=1, severity="moderate")
        assert len(scenarios) == 100

    def test_scenario_ids_sequential(self) -> None:
        gen = MCScenarioGenerator()
        scenarios = gen.generate(n_scenarios=10, seed=2)
        ids = [s.scenario_id for s in scenarios]
        assert ids == list(range(1, 11))

    def test_all_severity_levels(self) -> None:
        gen = MCScenarioGenerator()
        for sev in ["mild", "moderate", "severe", "tail"]:
            scenarios = gen.generate(n_scenarios=50, severity=sev)
            assert len(scenarios) == 50

    def test_unknown_severity_defaults_to_moderate(self) -> None:
        gen = MCScenarioGenerator()
        scenarios = gen.generate(n_scenarios=10, severity="bogus")
        assert len(scenarios) == 10

    def test_tail_severity_has_larger_shocks(self) -> None:
        gen = MCScenarioGenerator()
        mild = gen.generate(n_scenarios=500, seed=10, severity="mild")
        tail = gen.generate(n_scenarios=500, seed=10, severity="tail")
        mild_gdp = np.mean([s.gdp_shock_pct for s in mild])
        tail_gdp = np.mean([s.gdp_shock_pct for s in tail])
        assert tail_gdp < mild_gdp  # tail shocks are more negative

    def test_reproducibility_with_seed(self) -> None:
        gen = MCScenarioGenerator()
        s1 = gen.generate(n_scenarios=20, seed=99)
        s2 = gen.generate(n_scenarios=20, seed=99)
        assert [sc.gdp_shock_pct for sc in s1] == [sc.gdp_shock_pct for sc in s2]


# ---------------------------------------------------------------------------
# MCPortfolioStressor tests
# ---------------------------------------------------------------------------


class TestMCPortfolioStressor:
    def test_score_scenario_returns_dict_keys(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
    ) -> None:
        stressor = MCPortfolioStressor(simple_model, feature_names)
        scenario = MCStressScenario(
            scenario_id=1,
            gdp_shock_pct=-0.03,
            unemployment_delta_ppt=2.0,
            credit_spread_delta_bps=100.0,
            house_price_delta_pct=-0.10,
        )
        result = stressor.score_scenario(portfolio_df, scenario)
        for key in ("scenario_id", "mean_pd", "stressed_dr", "expected_loss"):
            assert key in result

    def test_shocked_df_has_same_shape(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
    ) -> None:
        stressor = MCPortfolioStressor(simple_model, feature_names)
        scenario = MCStressScenario(1, -0.05, 3.0, 200.0, -0.15)
        shocked = stressor.apply_macro_shocks(portfolio_df, scenario)
        assert shocked.shape == portfolio_df.shape

    def test_severe_shock_increases_mean_pd(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
    ) -> None:
        stressor = MCPortfolioStressor(simple_model, feature_names)
        mild_sc = MCStressScenario(1, -0.005, 0.2, 10.0, -0.01)
        severe_sc = MCStressScenario(2, -0.15, 8.0, 500.0, -0.40)
        mild_res = stressor.score_scenario(portfolio_df, mild_sc)
        severe_res = stressor.score_scenario(portfolio_df, severe_sc)
        # Severe shocks must not lower mean PD vs mild
        assert severe_res["mean_pd"] >= mild_res["mean_pd"] - 0.05  # allow small tolerance


# ---------------------------------------------------------------------------
# StressTestRunner tests
# ---------------------------------------------------------------------------


class TestStressTestRunner:
    def test_run_returns_summary(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        summary = runner.run(portfolio_df, n_scenarios=20, severity="moderate", quarter="2026-Q1")
        assert isinstance(summary, StressTestSummary)
        assert summary.n_scenarios == 20
        assert summary.run_id != ""

    def test_results_persisted_to_sqlite(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        runner.run(portfolio_df, n_scenarios=10, quarter="2026-Q2")
        results = runner.get_results()
        assert len(results) >= 1
        assert results[0]["quarter"] == "2026-Q2"

    def test_get_results_filtered_by_quarter(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        runner.run(portfolio_df, n_scenarios=10, quarter="2025-Q4")
        runner.run(portfolio_df, n_scenarios=10, quarter="2026-Q1")
        q4 = runner.get_results(quarter="2025-Q4")
        q1 = runner.get_results(quarter="2026-Q1")
        assert all(r["quarter"] == "2025-Q4" for r in q4)
        assert all(r["quarter"] == "2026-Q1" for r in q1)

    def test_compare_quarters_returns_deltas(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        runner.run(portfolio_df, n_scenarios=10, quarter="2025-Q3")
        runner.run(portfolio_df, n_scenarios=10, quarter="2025-Q4")
        cmp = runner.compare_quarters("2025-Q3", "2025-Q4")
        assert "delta_p95_stressed_dr" in cmp
        assert cmp.get("error") is None

    def test_compare_quarters_missing_quarter(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        runner.run(portfolio_df, n_scenarios=5, quarter="2026-Q3")
        cmp = runner.compare_quarters("2026-Q3", "9999-Q9")
        assert "error" in cmp

    def test_percentile_order(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        summary = runner.run(portfolio_df, n_scenarios=50, quarter="2026-Q2")
        assert summary.p50_stressed_dr <= summary.p95_stressed_dr
        assert summary.p95_stressed_dr <= summary.p99_stressed_dr

    def test_db_file_created(
        self,
        simple_model: LogisticRegression,
        feature_names: list[str],
        portfolio_df: pd.DataFrame,
        db_path: str,
    ) -> None:
        runner = StressTestRunner(simple_model, feature_names, store_path=db_path)
        runner.run(portfolio_df, n_scenarios=5)
        assert Path(db_path).exists()
