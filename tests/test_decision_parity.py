"""
P0.2 — Decision Parity Golden Test
=====================================
Verify that the Decision API path and the agent pipeline produce identical
decisions + reason codes for the same input.

This test is the acceptance criterion for P0.2 (Create Canonical Domain
Package "credit_core"). If both entry points now call credit_core, they
must return stable equality for every sample applicant.

The test does NOT require live models — it uses a deterministic stub scorer
for reproducibility and speed so it can run in CI without artifact files.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

import numpy as np
import pandas as pd
import pytest

from credit_core.features import compute_feature_matrix
from credit_core.policy import evaluate_policy, PolicyResult
from decision_engine.engine import (
    CreditResult,
    DecisionRequest,
    FraudResult,
    make_decision,
)
from models.pricing.engine import PricingConfig, calculate_pricing

# ---------------------------------------------------------------------------
# Sample applicant fixtures
# ---------------------------------------------------------------------------

_SAMPLE_APPLICANTS: List[Dict[str, Any]] = [
    # Applicant 1: strong profile — expect APPROVE
    {
        "application_id": "APP-001",
        "credit_score": 780,
        "annual_income": 90_000.0,
        "employment_status": "employed",
        "employer_tenure_months": 48,
        "debt_to_income_ratio": 0.20,
        "existing_debt_amount": 18_000.0,
        "loan_amount": 20_000.0,
        "loan_term_months": 36,
        "num_open_accounts": 6,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
        "borrower_state": "CA",
    },
    # Applicant 2: high DTI + derogatory marks — expect REJECT
    {
        "application_id": "APP-002",
        "credit_score": 540,
        "annual_income": 30_000.0,
        "employment_status": "unemployed",
        "employer_tenure_months": 0,
        "debt_to_income_ratio": 0.58,
        "existing_debt_amount": 17_400.0,
        "loan_amount": 15_000.0,
        "loan_term_months": 24,
        "num_open_accounts": 2,
        "num_derogatory_marks": 4,
        "months_since_last_delinquency": 3.0,
        "borrower_state": "TX",
    },
    # Applicant 3: thin-file, moderate risk
    {
        "application_id": "APP-003",
        "credit_score": None,  # thin-file
        "annual_income": 48_000.0,
        "employment_status": "self-employed",
        "employer_tenure_months": 24,
        "debt_to_income_ratio": 0.30,
        "existing_debt_amount": 14_400.0,
        "loan_amount": 10_000.0,
        "loan_term_months": 48,
        "num_open_accounts": 1,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
        "borrower_state": None,
        "rent_payment_months": 24,
        "utility_payment_months": 18,
        "mobile_data_score": 0.7,
        "bank_account_age_months": 36,
    },
    # Applicant 4: fraud flag — expect REJECT
    {
        "application_id": "APP-004",
        "credit_score": 650,
        "annual_income": 55_000.0,
        "employment_status": "employed",
        "employer_tenure_months": 12,
        "debt_to_income_ratio": 0.25,
        "existing_debt_amount": 13_750.0,
        "loan_amount": 8_000.0,
        "loan_term_months": 24,
        "num_open_accounts": 3,
        "num_derogatory_marks": 1,
        "months_since_last_delinquency": 24.0,
        "borrower_state": "FL",
    },
    # Applicant 5: borderline — manual review zone
    {
        "application_id": "APP-005",
        "credit_score": 620,
        "annual_income": 42_000.0,
        "employment_status": "employed",
        "employer_tenure_months": 18,
        "debt_to_income_ratio": 0.38,
        "existing_debt_amount": 15_960.0,
        "loan_amount": 12_000.0,
        "loan_term_months": 36,
        "num_open_accounts": 2,
        "num_derogatory_marks": 1,
        "months_since_last_delinquency": 18.0,
        "borrower_state": "NY",
    },
]

# ---------------------------------------------------------------------------
# Deterministic stub scorer
# ---------------------------------------------------------------------------

def _stub_score(app: Dict[str, Any]) -> Dict[str, float]:
    """
    Deterministic, model-free scorer for golden tests.
    Uses linear heuristics that are fully reproducible without artifact files.
    """
    dti = app.get("debt_to_income_ratio", 0.30)
    derogs = app.get("num_derogatory_marks", 0)
    credit_score = app.get("credit_score") or 500

    # Synthetic PD: higher DTI / derogatory marks / low credit score → higher risk
    pd_score = (
        (dti * 0.15)
        + (derogs * 0.05)
        + max(0.0, (700 - credit_score) / 700 * 0.20)
    )
    pd_score = float(np.clip(pd_score, 0.0, 1.0))

    # Synthetic fraud flag
    fraud_prob = 0.05 if derogs <= 1 else 0.35
    if app.get("application_id") == "APP-004":
        fraud_prob = 0.70  # Force fraud reject for test applicant 4
    fraud_flag = "continue"
    if fraud_prob >= 0.60:
        fraud_flag = "reject"
    elif fraud_prob >= 0.30:
        fraud_flag = "manual_review"

    pd_band = "low" if pd_score <= 0.05 else ("medium" if pd_score <= 0.10 else "high")

    return {"pd_score": pd_score, "pd_band": pd_band, "fraud_probability": fraud_prob, "fraud_flag": fraud_flag}


# ---------------------------------------------------------------------------
# Path A: "Decision API" path using credit_core directly
# ---------------------------------------------------------------------------

def _api_path_decision(app: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate what the Decision API does: compute_feature_matrix → stub score → make_decision."""
    _ = compute_feature_matrix(pd.DataFrame([app]), version="1.0.0")

    scores = _stub_score(app)
    pricing_cfg = PricingConfig()
    pricing_result = calculate_pricing(
        pd_score=scores["pd_score"],
        fraud_flag=scores["fraud_flag"],
        loan_amount=float(app["loan_amount"]),
        config=pricing_cfg,
        borrower_state=app.get("borrower_state"),
    )
    req = DecisionRequest(
        application_id=app["application_id"],
        fraud_result=FraudResult(
            fraud_probability=scores["fraud_probability"],
            fraud_flag=scores["fraud_flag"],
        ),
        credit_result=CreditResult(
            pd_score=scores["pd_score"],
            pd_band=scores["pd_band"],
        ),
        pricing_result=pricing_result,
        loan_amount=float(app["loan_amount"]),
        loan_term_months=int(app["loan_term_months"]),
        debt_to_income_ratio=float(app["debt_to_income_ratio"]),
        num_open_accounts=int(app.get("num_open_accounts", 0)),
        annual_income=float(app["annual_income"]),
    )
    dr = make_decision(req)
    return {"application_id": app["application_id"], "decision": dr.decision, "reason_codes": sorted(dr.reason_codes)}


# ---------------------------------------------------------------------------
# Path B: "Agent pipeline" path using evaluate_policy
# ---------------------------------------------------------------------------

def _agent_path_decision(app: Dict[str, Any]) -> Dict[str, Any]:
    """Simulate what the agent pipeline does: compute_feature_matrix → stub score → evaluate_policy."""
    _ = compute_feature_matrix(pd.DataFrame([app]), version="1.0.0")

    scores = _stub_score(app)
    scores_df = pd.DataFrame([{
        "application_id": app["application_id"],
        **scores,
    }])
    context_df = pd.DataFrame([{
        "application_id": app["application_id"],
        "loan_amount": float(app["loan_amount"]),
        "loan_term_months": int(app["loan_term_months"]),
        "debt_to_income_ratio": float(app["debt_to_income_ratio"]),
        "num_open_accounts": int(app.get("num_open_accounts", 0)),
        "annual_income": float(app["annual_income"]),
        "borrower_state": app.get("borrower_state"),
    }])
    results: List[PolicyResult] = evaluate_policy(
        scores_df, context_df, policy_version="v1"
    )
    pr = results[0]
    return {"application_id": app["application_id"], "decision": pr.decision, "reason_codes": sorted(pr.reason_codes)}


# ---------------------------------------------------------------------------
# Golden test
# ---------------------------------------------------------------------------


class TestDecisionParity:
    """API path and agent pipeline must return identical decisions + reason codes."""

    @pytest.mark.parametrize("app", _SAMPLE_APPLICANTS, ids=[a["application_id"] for a in _SAMPLE_APPLICANTS])
    def test_decision_parity_per_applicant(self, app: Dict[str, Any]) -> None:
        """For each sample applicant, both paths must agree on decision and reason codes."""
        api_result = _api_path_decision(copy.deepcopy(app))
        agent_result = _agent_path_decision(copy.deepcopy(app))

        assert api_result["decision"] == agent_result["decision"], (
            f"[{app['application_id']}] Decision mismatch: "
            f"API={api_result['decision']!r} vs Agent={agent_result['decision']!r}"
        )
        assert api_result["reason_codes"] == agent_result["reason_codes"], (
            f"[{app['application_id']}] Reason code mismatch: "
            f"API={api_result['reason_codes']} vs Agent={agent_result['reason_codes']}"
        )

    def test_bulk_parity_N_applicants(self) -> None:
        """Run all sample applicants in bulk and assert stable equality for key outputs."""
        for app in _SAMPLE_APPLICANTS:
            api_result = _api_path_decision(copy.deepcopy(app))
            agent_result = _agent_path_decision(copy.deepcopy(app))
            assert api_result["decision"] == agent_result["decision"], (
                f"Bulk parity failure for {app['application_id']}: "
                f"{api_result['decision']} != {agent_result['decision']}"
            )

    def test_feature_matrix_is_deterministic(self) -> None:
        """compute_feature_matrix must return identical output on identical input."""
        app = _SAMPLE_APPLICANTS[0]
        df1 = compute_feature_matrix(pd.DataFrame([app]), version="1.0.0")
        df2 = compute_feature_matrix(pd.DataFrame([app]), version="1.0.0")
        pd.testing.assert_frame_equal(df1, df2)
