from __future__ import annotations

import pandas as pd

from models.credit_risk.lgd_model import LGDModel
from risk_models.stress_test import DFAST_2026_SCENARIOS, run_portfolio_stress_test


def _portfolio_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "application_id": "A1",
                "product": "unsecured",
                "risk_grade": "C",
                "outstanding_balance": 1000.0,
                "credit_limit": 1500.0,
                "months_on_book": 6,
                "pd_12m": 0.05,
                "ccf": 0.75,
                "stage": 1,
            },
            {
                "application_id": "A2",
                "product": "unsecured",
                "risk_grade": "D",
                "outstanding_balance": 2000.0,
                "credit_limit": 2500.0,
                "months_on_book": 18,
                "pd_12m": 0.10,
                "ccf": 0.75,
                "stage": 2,
            },
            {
                "application_id": "A3",
                "product": "unsecured",
                "risk_grade": "B",
                "outstanding_balance": 500.0,
                "credit_limit": 1000.0,
                "months_on_book": 2,
                "pd_12m": 0.02,
                "ccf": 0.75,
                "stage": 1,
            },
        ]
    )


def test_severely_adverse_ecl_exceeds_base() -> None:
    report = run_portfolio_stress_test(_portfolio_df(), DFAST_2026_SCENARIOS, LGDModel())
    totals = {r.scenario: r.total_ecl for r in report.scenario_results}
    assert totals["severely_adverse"] > totals["base"]


def test_report_has_all_required_fields() -> None:
    report = run_portfolio_stress_test(_portfolio_df(), DFAST_2026_SCENARIOS, LGDModel())
    assert report.scenario_set_name == DFAST_2026_SCENARIOS.scenario_name
    assert report.portfolio_size == 3
    assert report.total_balance > 0
    assert report.probability_weighted_ecl > 0
    assert len(report.scenario_results) == 3
    assert isinstance(report.top10_contributors, list)
    assert "tier1_ratio_pre_stress" in report.capital_adequacy_check


def test_capital_adequacy_fails_when_ecl_exceeds_tier1() -> None:
    # Use a very low Tier-1 ratio so severe losses drive the ratio below 8%.
    report = run_portfolio_stress_test(
        _portfolio_df(),
        DFAST_2026_SCENARIOS,
        LGDModel(),
        tier1_ratio_pre_stress=0.06,
    )
    assert report.capital_adequacy_check["passes_minimum_8pct"] is False
