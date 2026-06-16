from __future__ import annotations

from datetime import date

import pandas as pd

from risk_models.ecl_engine import (
    ExposureRecord,
    MacroScenario,
    compute_12m_ecl,
    compute_ead,
    compute_portfolio_ecl,
    ifrs9_stage_ecl,
    check_sicr,
)


def _record(stage: int = 1) -> ExposureRecord:
    return ExposureRecord(
        application_id="app_1",
        product="basic",
        outstanding_balance=5000.0,
        credit_limit=10000.0,
        months_on_book=3,
        pd_12m=0.05,
        lgd=0.65,
        ccf=0.6,
        stage=stage,  # type: ignore[arg-type]
        origination_date=date(2024, 1, 1),
        contractual_maturity_months=60,
    )


def test_12m_ecl_formula() -> None:
    r = _record(stage=1)
    assert compute_ead(r) == 8000.0
    assert compute_12m_ecl(r) == 260.0


def test_stage1_equals_12m_ecl() -> None:
    r = _record(stage=1)
    assert ifrs9_stage_ecl(r) == compute_12m_ecl(r)


def test_stage2_lifetime_ecl_greater_than_12m() -> None:
    r1 = _record(stage=1)
    r2 = _record(stage=2)
    assert ifrs9_stage_ecl(r2) > ifrs9_stage_ecl(r1)


def test_scenario_weights_sum_to_1() -> None:
    scenarios = [
        MacroScenario("base", 1.0, 1.0, 0.5),
        MacroScenario("adverse", 1.5, 1.2, 0.3),
        MacroScenario("severe", 2.5, 1.4, 0.2),
    ]
    assert sum(s.probability_weight for s in scenarios) == 1.0


def test_sicr_trigger() -> None:
    r = _record(stage=1)
    r = ExposureRecord(**{**r.__dict__, "pd_12m": 0.10})
    assert check_sicr(r, origination_pd=0.04) is True


def test_portfolio_ecl_returns_all_columns() -> None:
    recs = [
        _record(stage=1),
        ExposureRecord(**{**_record(stage=2).__dict__, "application_id": "app_2"}),
        ExposureRecord(**{**_record(stage=3).__dict__, "application_id": "app_3", "pd_12m": 0.02}),
    ]
    df = compute_portfolio_ecl(recs)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 3
    assert set(df.columns) == {
        "application_id",
        "stage",
        "ead",
        "pd_12m",
        "lgd",
        "ecl_12m",
        "ecl_lifetime",
        "ecl_weighted",
        "scenario_breakdown",
    }
