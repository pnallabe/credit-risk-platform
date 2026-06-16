"""
Prompt 4: Thin-file alt score enrichment tests + Prompt 5: Feature parity harness.

Covers:
- Deterministic outputs on fixed fixtures
- All-null input
- Zero-inflow scenario
- High-volatility (overdraft / NSF) scenario
- Open-banking signal deductions (NSF, returned payments, balance stress)
- Parity: same input must produce same thin_file_alt_score from API path (credit_core) and agent path
"""
from __future__ import annotations

import pandas as pd
import numpy as np
import pytest

from credit_core.features import _compute_thin_file_alt_score, compute_feature_matrix
from agents.feature_engineering_agent import FeatureEngineeringAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_row(**kwargs) -> pd.DataFrame:
    defaults = {
        "rent_payment_months": 0,
        "utility_payment_months": 0,
        "mobile_data_score": 0.0,
        "bank_account_age_months": 0,
        "avg_monthly_cash_inflow": 0.0,
        "avg_monthly_cash_outflow": 0.0,
        "nsfv_last_90_days": 0,
        "returned_payment_count": 0,
        "income_confidence": 0.0,
        "avg_monthly_end_balance": 0.0,
        "min_balance_90d": 0.0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


# ---------------------------------------------------------------------------
# Prompt 4 — deterministic behavior
# ---------------------------------------------------------------------------

def test_all_null_input_returns_zero():
    row = pd.DataFrame([{
        "rent_payment_months": None,
        "utility_payment_months": None,
        "mobile_data_score": None,
        "bank_account_age_months": None,
        "avg_monthly_cash_inflow": None,
        "avg_monthly_cash_outflow": None,
    }])
    scores = _compute_thin_file_alt_score(row)
    assert float(scores.iloc[0]) == pytest.approx(0.0)


def test_zero_inflow_no_crash():
    row = make_row(avg_monthly_cash_inflow=0.0, avg_monthly_cash_outflow=1000.0)
    scores = _compute_thin_file_alt_score(row)
    assert 0.0 <= float(scores.iloc[0]) <= 1.0


def test_positive_signals_increase_score():
    base = make_row()
    enriched = make_row(
        rent_payment_months=12,
        utility_payment_months=12,
        mobile_data_score=0.9,
        bank_account_age_months=24,
        avg_monthly_cash_inflow=5000.0,
        avg_monthly_cash_outflow=3000.0,
        income_confidence=0.95,
    )
    base_score = float(_compute_thin_file_alt_score(base).iloc[0])
    enriched_score = float(_compute_thin_file_alt_score(enriched).iloc[0])
    assert enriched_score > base_score


def test_nsf_events_reduce_score():
    clean = make_row(rent_payment_months=12, income_confidence=0.8)
    nsf = make_row(rent_payment_months=12, income_confidence=0.8, nsfv_last_90_days=3)
    assert float(_compute_thin_file_alt_score(nsf).iloc[0]) < float(_compute_thin_file_alt_score(clean).iloc[0])


def test_returned_payments_reduce_score():
    clean = make_row(income_confidence=0.8)
    with_returns = make_row(income_confidence=0.8, returned_payment_count=2)
    assert float(_compute_thin_file_alt_score(with_returns).iloc[0]) < float(_compute_thin_file_alt_score(clean).iloc[0])


def test_chronic_overdraft_reduces_score():
    solvent = make_row(avg_monthly_cash_inflow=4000.0, min_balance_90d=0.0)
    overdraft = make_row(avg_monthly_cash_inflow=4000.0, min_balance_90d=-1000.0)
    assert float(_compute_thin_file_alt_score(overdraft).iloc[0]) < float(_compute_thin_file_alt_score(solvent).iloc[0])


def test_score_always_within_0_1():
    """Extreme values should still clip to [0, 1]."""
    extreme = make_row(
        rent_payment_months=9999,
        utility_payment_months=9999,
        mobile_data_score=999.0,
        bank_account_age_months=9999,
        avg_monthly_cash_inflow=1_000_000.0,
        avg_monthly_cash_outflow=0.0,
        income_confidence=1.0,
    )
    score = float(_compute_thin_file_alt_score(extreme).iloc[0])
    assert 0.0 <= score <= 1.0


def test_score_deterministic_on_same_input():
    row = make_row(rent_payment_months=6, income_confidence=0.7, nsfv_last_90_days=1)
    s1 = float(_compute_thin_file_alt_score(row).iloc[0])
    s2 = float(_compute_thin_file_alt_score(row).iloc[0])
    assert s1 == s2


# ---------------------------------------------------------------------------
# Prompt 5 — API path vs agent path parity
# ---------------------------------------------------------------------------

PARITY_FIXTURE = {
    "application_id": "parity-001",
    "loan_amount": 10000.0,
    "loan_purpose": "personal",
    "loan_term_months": 24,
    "annual_income": 60000.0,
    "employment_status": "employed",
    "employer_tenure_months": 24.0,
    "debt_to_income_ratio": 0.25,
    "existing_debt_amount": 15000.0,
    "credit_score": None,  # thin-file
    "num_open_accounts": 2,
    "num_derogatory_marks": 0,
    "months_since_last_delinquency": None,
    # Alt-data
    "rent_payment_months": 12,
    "utility_payment_months": 6,
    "mobile_data_score": 0.7,
    "bank_account_age_months": 18,
    "avg_monthly_cash_inflow": 5000.0,
    "avg_monthly_cash_outflow": 3500.0,
    "nsfv_last_90_days": 1,
    "returned_payment_count": 0,
    "income_confidence": 0.85,
    "min_balance_90d": -50.0,
}


def test_api_agent_thin_file_score_parity():
    """API path (compute_feature_matrix) and agent path must yield identical thin_file_alt_score."""
    df = pd.DataFrame([PARITY_FIXTURE])

    # API path
    api_features = compute_feature_matrix(df.copy())
    api_score = float(api_features["thin_file_alt_score"].iloc[0])

    # Agent path — FeatureEngineeringAgent wraps input in ValidatedRecord format
    validated = [{"raw_features": {**PARITY_FIXTURE}}]
    agent = FeatureEngineeringAgent()
    result = agent._run({"validated": validated})
    assert result.payload, "Agent must return payload"
    agent_feature_records = result.payload.get("feature_df")
    assert agent_feature_records is not None
    agent_df = pd.DataFrame(agent_feature_records)
    agent_score = float(agent_df["thin_file_alt_score"].iloc[0])

    assert api_score == pytest.approx(agent_score, abs=1e-10), (
        f"Parity violation: API score={api_score:.8f}, agent score={agent_score:.8f}"
    )


def test_non_thin_file_scores_same_across_paths():
    """Non-thin-file applicant (with credit_score) must also show identical scores."""
    fixture = {**PARITY_FIXTURE, "credit_score": 720}
    df = pd.DataFrame([fixture])

    api_features = compute_feature_matrix(df.copy())
    api_score = float(api_features["thin_file_alt_score"].iloc[0])

    validated = [{"raw_features": {**fixture}}]
    agent = FeatureEngineeringAgent()
    result = agent._run({"validated": validated})
    agent_df = pd.DataFrame(result.payload["feature_df"])
    agent_score = float(agent_df["thin_file_alt_score"].iloc[0])

    assert api_score == pytest.approx(agent_score, abs=1e-10)
