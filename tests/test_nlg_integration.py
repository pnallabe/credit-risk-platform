"""Integration tests for NLG decision summaries (GAP-06 acceptance criteria)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from explainability.shap_explainer import ExplanationResult
from explainability.nlg_summarizer import (
    NLGSummary,
    generate_decision_summary,
    map_factors_to_ecoa_codes,
    ECOA_REASON_CODES,
)


# ---------------------------------------------------------------------------
# Synthetic ExplanationResult fixtures
# ---------------------------------------------------------------------------

def _reject_explanation() -> ExplanationResult:
    return ExplanationResult(
        top_positive_factors=[
            {"feature": "fico_score",     "shap_value": -0.10, "direction": "positive"},
        ],
        top_negative_factors=[
            {"feature": "debt_to_income",    "shap_value": 0.20, "direction": "negative"},
            {"feature": "delinquency_count", "shap_value": 0.15, "direction": "negative"},
            {"feature": "credit_util",       "shap_value": 0.09, "direction": "negative"},
        ],
        predicted_value=0.28,
        explanation_text="Model predicts high default risk.",
    )


def _approve_explanation() -> ExplanationResult:
    return ExplanationResult(
        top_positive_factors=[
            {"feature": "fico_score",     "shap_value": -0.25, "direction": "positive"},
            {"feature": "months_on_book", "shap_value": -0.12, "direction": "positive"},
        ],
        top_negative_factors=[],
        predicted_value=0.03,
        explanation_text="Model predicts low default risk.",
    )


# ---------------------------------------------------------------------------
# Test: REJECT produces non-empty loan_officer_narrative
# ---------------------------------------------------------------------------

def test_reject_produces_non_empty_loan_officer_narrative() -> None:
    """GAP-06: Every REJECT decision must produce non-empty loan_officer_narrative."""
    explanation = _reject_explanation()
    with patch.dict("sys.modules", {"openai": None}):
        summary = generate_decision_summary(
            explanation=explanation,
            decision="REJECT",
            application_id="APP-TEST-001",
        )

    assert isinstance(summary, NLGSummary)
    assert isinstance(summary.loan_officer_narrative, str)
    assert len(summary.loan_officer_narrative) > 10


# ---------------------------------------------------------------------------
# Test: REJECT produces adverse_action_reasons list ≥ 1 ECOA code
# ---------------------------------------------------------------------------

def test_reject_produces_adverse_action_reasons() -> None:
    """GAP-06: REJECT response must contain adverse_action_reasons list (≥1 ECOA code)."""
    explanation = _reject_explanation()
    with patch.dict("sys.modules", {"openai": None}):
        summary = generate_decision_summary(
            explanation=explanation,
            decision="REJECT",
            application_id="APP-TEST-002",
        )

    assert isinstance(summary.top_reasons, list)
    assert len(summary.top_reasons) >= 1
    # Should contain ECOA-style reason text
    for reason in summary.top_reasons:
        assert isinstance(reason, str)
        assert len(reason) > 5


# ---------------------------------------------------------------------------
# Test: APPROVE has empty adverse_action_body
# ---------------------------------------------------------------------------

def test_approve_has_empty_adverse_action_body() -> None:
    """GAP-06: APPROVE response must have empty adverse_action_body."""
    explanation = _approve_explanation()
    with patch.dict("sys.modules", {"openai": None}):
        summary = generate_decision_summary(
            explanation=explanation,
            decision="APPROVE",
            application_id="APP-TEST-003",
        )

    assert summary.adverse_action_body == "", (
        f"Expected empty adverse_action_body for APPROVE, got: {summary.adverse_action_body!r}"
    )


# ---------------------------------------------------------------------------
# Test: Works with OPENAI_API_KEY unset (template fallback)
# ---------------------------------------------------------------------------

def test_works_without_openai_api_key() -> None:
    """GAP-06: Must work with OPENAI_API_KEY unset (template fallback path)."""
    explanation = _reject_explanation()

    # Simulate missing API key and missing openai module
    with (
        patch.dict("sys.modules", {"openai": None}),
        patch.dict("os.environ", {}, clear=False),
    ):
        import os
        os.environ.pop("OPENAI_API_KEY", None)
        summary = generate_decision_summary(
            explanation=explanation,
            decision="REJECT",
            application_id="APP-TEST-004",
        )

    # Template fallback must produce all required fields
    assert isinstance(summary, NLGSummary)
    assert summary.loan_officer_narrative
    assert summary.applicant_narrative
    assert summary.adverse_action_body
    assert summary.top_reasons


# ---------------------------------------------------------------------------
# Test: LLM raise → template fallback, no exception
# ---------------------------------------------------------------------------

def test_llm_exception_falls_back_to_template() -> None:
    """If the LLM client raises, generate_decision_summary must not propagate."""
    explanation = _reject_explanation()

    class _FailingClient:
        class chat:
            class completions:
                @staticmethod
                def create(*a, **kw):
                    raise RuntimeError("LLM network timeout")

    summary = generate_decision_summary(
        explanation=explanation,
        decision="REJECT",
        application_id="APP-TEST-005",
        llm_client=_FailingClient(),
    )

    assert isinstance(summary, NLGSummary)
    assert summary.loan_officer_narrative  # template must produce a non-empty string


# ---------------------------------------------------------------------------
# Test: MANUAL_REVIEW decision produces non-empty adverse action body
# ---------------------------------------------------------------------------

def test_manual_review_has_adverse_action_body() -> None:
    explanation = _reject_explanation()
    with patch.dict("sys.modules", {"openai": None}):
        summary = generate_decision_summary(
            explanation=explanation,
            decision="MANUAL_REVIEW",
            application_id="APP-TEST-006",
        )

    assert summary.adverse_action_body != "", "MANUAL_REVIEW must produce an adverse_action_body"
    assert "ECOA" in summary.adverse_action_body or "Equal Credit" in summary.adverse_action_body


# ---------------------------------------------------------------------------
# Test: map_factors_to_ecoa_codes returns known codes for known features
# ---------------------------------------------------------------------------

def test_map_factors_known_features() -> None:
    factors = [
        {"feature": "debt_to_income",    "shap_value": 0.20},
        {"feature": "delinquency_count", "shap_value": 0.15},
        {"feature": "credit_util",       "shap_value": 0.09},
        {"feature": "public_records",    "shap_value": 0.07},
    ]
    codes = map_factors_to_ecoa_codes(factors)
    assert len(codes) == 4
    assert all(isinstance(c, str) and len(c) > 5 for c in codes)


# ---------------------------------------------------------------------------
# Test: map_factors_to_ecoa_codes handles unknown features gracefully
# ---------------------------------------------------------------------------

def test_map_factors_unknown_feature_fallback() -> None:
    factors = [{"feature": "some_weird_feature_xyz", "shap_value": 0.10}]
    codes = map_factors_to_ecoa_codes(factors)
    assert len(codes) == 1
    assert "some_weird_feature_xyz" in codes[0] or "Other" in codes[0]
