"""
Smoke tests for decision_engine/portfolio_review.py
"""
from __future__ import annotations

import pytest

from decision_engine.portfolio_review import (
    _pd_proxy,
    build_portfolio_summary,
    compute_cnpv_delta,
)


# ---------------------------------------------------------------------------
# _pd_proxy
# ---------------------------------------------------------------------------

def test_pd_proxy_returns_float():
    pd_val = _pd_proxy(720)
    assert isinstance(pd_val, float)
    assert 0.0 < pd_val < 1.0


def test_pd_proxy_higher_score_lower_pd():
    assert _pd_proxy(800) < _pd_proxy(600)


def test_pd_proxy_bounds():
    # Even extreme scores should return valid probabilities
    assert 0.0 < _pd_proxy(300) < 1.0
    assert 0.0 < _pd_proxy(850) < 1.0


# ---------------------------------------------------------------------------
# compute_cnpv_delta
# ---------------------------------------------------------------------------

def _mock_account():
    from unittest.mock import MagicMock
    acct = MagicMock()
    acct.credit_limit = 5_000.0
    acct.apr = 19.99
    acct.score = 720
    acct.balance = 2_000.0
    return acct


def test_compute_cnpv_delta_returns_dict():
    acct = _mock_account()
    features = {"pd_score": 0.05, "utilization": 0.40, "dscr": 1.1}
    product = {"lgd": 0.45, "yield_rate": 0.20, "cost_of_funds": 0.05}
    result = compute_cnpv_delta(
        account=acct,
        features=features,
        new_limit=6_000.0,
        new_apr=18.99,
        product=product,
        cet1_buffer_available=500.0,
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# build_portfolio_summary
# ---------------------------------------------------------------------------

def test_build_portfolio_summary_empty():
    summary = build_portfolio_summary(
        results=[],
        cet1_buffer_available=1_000_000.0,
        scenario="baseline",
    )
    assert isinstance(summary, dict)
    assert summary.get("total_accounts", 0) == 0


def test_build_portfolio_summary_with_results():
    results = [
        {"final_action": "CLI", "cnpv_delta": 50.0, "limit_change_pct": 0.20, "guardrail_reason": ""},
        {"final_action": "HOLD", "cnpv_delta": 0.0, "guardrail_reason": ""},
        {"final_action": "CLD", "cnpv_delta": -20.0, "guardrail_reason": "low_util"},
    ]
    summary = build_portfolio_summary(
        results=results,
        cet1_buffer_available=1_000_000.0,
        scenario="stress_test",
    )
    assert isinstance(summary, dict)
    assert summary.get("total_accounts_reviewed") == 3


# ---------------------------------------------------------------------------
# Extended tests for higher coverage
# ---------------------------------------------------------------------------

import numpy as np
import pandas as pd

import decision_engine.portfolio_review as pr_mod
from decision_engine.portfolio_review import (
    _get_scenarios,
    _load_statements_parquet,
    _load_transactions_parquet,
    _load_events_parquet,
    ACTIVE_ACCOUNTS_SQL,
)


def _full_result_row(**overrides) -> dict:
    base = {
        "final_action": "HOLD",
        "risk_segment": "near_prime",
        "guardrail_reason": "",
        "current_credit_limit": 5000.0,
        "current_apr": 0.1999,
        "current_delinquency": "CURRENT",
        "bureau_score_current": 700.0,
        "incremental_rwa_usd": 0.0,
        "new_credit_limit": 5000.0,
        "new_apr": 0.1999,
        "limit_change_pct": 0.0,
        "apr_change_bps": 0.0,
        "action_confidence": 0.75,
        "cnpv_delta_base": 10.0,
        "cnpv_delta_worsening": 8.0,
        "cnpv_delta_recession": 5.0,
        "cnpv_delta_scenario_weighted": 9.0,
    }
    base.update(overrides)
    return base


def _small_accounts_df(n=4) -> pd.DataFrame:
    return pd.DataFrame({
        "origination_id": [f"orig_{i}" for i in range(n)],
        "customer_id": [f"cust_{i}" for i in range(n)],
        "product_id": ["cash_back_everyday"] * n,
        "current_credit_limit": [5000.0, 3000.0, 7500.0, 2000.0][:n],
        "current_apr": [0.1999, 0.2399, 0.1799, 0.2999][:n],
        "bureau_score_at_origination": [720, 660, 700, 610][:n],
        "current_delinquency": ["CURRENT", "CURRENT", "DPD30", "CURRENT"][:n],
        "bureau_score_current": [730, 650, 690, 600][:n],
        "risk_segment": ["prime", "near_prime", "near_prime", "subprime"][:n],
    })


# _pd_proxy boundary tests
def test_pd_proxy_boundary_values():
    from decision_engine.portfolio_review import _pd_proxy
    assert _pd_proxy(720) == 0.008   # prime threshold
    assert _pd_proxy(660) == 0.022   # near-prime threshold
    assert _pd_proxy(580) == 0.048   # subprime threshold
    assert _pd_proxy(400) == 0.085   # thin file


# _get_scenarios
def test_get_scenarios_structure():
    s = _get_scenarios()
    assert "base" in s and "recession" in s
    total = sum(v["probability_weight"] for v in s.values())
    assert abs(total - 1.0) < 0.001


# SQL templates
def test_sql_templates_non_empty():
    assert isinstance(ACTIVE_ACCOUNTS_SQL, str) and len(ACTIVE_ACCOUNTS_SQL) > 0


# _load_*_parquet with non-existent data dir
def test_load_parquets_missing_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pr_mod, "DATA_DIR", tmp_path)
    assert _load_statements_parquet(["x"], "2026-01-01").empty
    assert _load_transactions_parquet(["x"], "2026-01-01").empty
    assert _load_events_parquet(["x"]).empty


# build_portfolio_summary — full result rows
def test_build_portfolio_summary_cli_full():
    results = [
        _full_result_row(final_action="CLI", new_credit_limit=6000.0,
                         limit_change_pct=0.20, incremental_rwa_usd=300.0),
    ]
    s = build_portfolio_summary(results, 500_000_000, "base")
    assert s["actions"]["CLI"]["count"] == 1
    assert s["actions"]["CLI"]["avg_limit_increase_pct"] == pytest.approx(0.20)
    assert s["total_incremental_rwa_cli"] == pytest.approx(300.0)


def test_build_portfolio_summary_guardrail_counted():
    results = [
        _full_result_row(guardrail_reason="CNPV_GATE: scenario-weighted CNPV delta < 0"),
        _full_result_row(guardrail_reason=""),
    ]
    s = build_portfolio_summary(results, 500_000_000, "base")
    assert s["guardrail_override_count"] == 1


def test_build_portfolio_summary_cnpv_totals():
    results = [
        _full_result_row(cnpv_delta_base=100.0, cnpv_delta_scenario_weighted=90.0),
        _full_result_row(cnpv_delta_base=50.0, cnpv_delta_scenario_weighted=45.0),
    ]
    s = build_portfolio_summary(results, 500_000_000, "base")
    assert s["total_cnpv_delta_base"] == pytest.approx(150.0)
    assert s["total_cnpv_delta_scenario_weighted"] == pytest.approx(135.0)


def test_build_portfolio_summary_apr_actions():
    results = [
        _full_result_row(final_action="APR_UP", apr_change_bps=75.0),
        _full_result_row(final_action="APR_DOWN", apr_change_bps=-50.0),
    ]
    s = build_portfolio_summary(results, 500_000_000, "base")
    assert s["actions"]["APR_UP"]["avg_apr_increase_bps"] == pytest.approx(75.0)
    assert s["actions"]["APR_DOWN"]["avg_apr_decrease_bps"] == pytest.approx(-50.0)


def test_build_portfolio_summary_segment_breakdown():
    results = [
        _full_result_row(risk_segment="prime", final_action="CLI"),
        _full_result_row(risk_segment="prime", final_action="HOLD"),
    ]
    s = build_portfolio_summary(results, 500_000_000, "base")
    assert "prime" in s["actions_by_segment"]
    assert s["actions_by_segment"]["prime"]["CLI_pct"] == pytest.approx(0.5)


# run_portfolio_review — full end-to-end with tiny DataFrame
def test_run_portfolio_review_basic(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=4))
    result = pr_mod.run_portfolio_review(use_bq=False)

    assert "portfolio_summary" in result
    assert result["portfolio_summary"]["total_accounts_reviewed"] == 4
    assert result["model_version"] == "cc_portfolio_action_v1"


def test_run_portfolio_review_scenario_all(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=3))
    result = pr_mod.run_portfolio_review(scenario="all", use_bq=False)

    assert "scenario_sensitivity" in result["portfolio_summary"]


def test_run_portfolio_review_output_limit_respected(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=4))
    result = pr_mod.run_portfolio_review(use_bq=False, output_limit=2)

    assert len(result["sample_accounts"]) <= 2


def test_run_portfolio_review_scenario_weights_sum_to_one(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=2))
    result = pr_mod.run_portfolio_review(use_bq=False)

    weights = result["scenario_weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.001



def test_run_portfolio_review_worsening_scenario(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=2))
    result = pr_mod.run_portfolio_review(scenario="industry_worsening", use_bq=False)

    assert result["scenario"] == "industry_worsening"


def test_run_portfolio_review_product_filter(monkeypatch):
    monkeypatch.setattr(pr_mod, "_load_active_accounts_parquet",
                        lambda *a, **kw: _small_accounts_df(n=2))
    result = pr_mod.run_portfolio_review(
        use_bq=False, product_filter="cash_back_everyday"
    )
    assert "portfolio_summary" in result
