"""
Tests for CreditAnalystAgent (Sprint S1-A)
"""

from __future__ import annotations

import pytest

from agents.base import AgentStatus
from agents.credit_analyst_agent import (
    CreditAnalystAgent,
    QualitativeAssessment,
    RedFlag,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent() -> CreditAnalystAgent:
    return CreditAnalystAgent(config={
        "credit_analyst": {
            "enabled": True,
            "collateral_shortfall_threshold": 0.80,
            "high_cash_advance_ratio": 0.30,
            "missed_payment_threshold": 2,
        }
    })


def _make_model_scores(pd_score: float = 0.05, fraud_prob: float = 0.05):
    """Returns a minimal dict mimicking ModelScores."""
    return {"pd_score": pd_score, "pd_band": "low", "fraud_probability": fraud_prob}


# ---------------------------------------------------------------------------
# Creditworthiness scoring
# ---------------------------------------------------------------------------

class TestCreditworthinessScore:
    def test_employed_high_income(self, agent):
        fv = {"employment_status": "employed", "emp_years": 5, "annual_income": 200_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        assessment: QualitativeAssessment = result.payload["qualitative_assessment"]
        assert assessment.creditworthiness_score == 5  # base1 + emp2 + income2 = 5

    def test_self_employed_medium_income(self, agent):
        fv = {"employment_status": "self_employed", "emp_years": 1, "annual_income": 90_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        assessment = result.payload["qualitative_assessment"]
        assert assessment.creditworthiness_score == 3  # base1 + self_emp1 + income1

    def test_unemployed_low_income(self, agent):
        fv = {"employment_status": "unemployed", "emp_years": 0, "annual_income": 20_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 5_000})
        assessment = result.payload["qualitative_assessment"]
        assert assessment.creditworthiness_score == 1  # base1, no additions

    def test_employment_months_converted(self, agent):
        """employer_tenure_months > 50 should be converted to years."""
        fv = {"employment_status": "employed", "employer_tenure_months": 36, "annual_income": 90_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 5_000})
        assessment = result.payload["qualitative_assessment"]
        assert assessment.creditworthiness_score >= 3  # 3 years → qualifies for +2 emp

    def test_score_capped_at_5(self, agent):
        fv = {"employment_status": "employed", "emp_years": 10, "annual_income": 500_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 1_000})
        assert result.payload["qualitative_assessment"].creditworthiness_score == 5


# ---------------------------------------------------------------------------
# Collateral analysis
# ---------------------------------------------------------------------------

class TestCollateralAnalysis:
    def test_adequate_coverage(self, agent):
        fv = {"collateral_value": 150_000, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 100_000})
        a = result.payload["qualitative_assessment"]
        assert a.collateral_quality == "Adequate"
        assert a.collateral_coverage_ratio == pytest.approx(1.50, rel=0.01)

    def test_marginal_coverage(self, agent):
        fv = {"collateral_value": 90_000, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 100_000})
        a = result.payload["qualitative_assessment"]
        assert a.collateral_quality == "Marginal"

    def test_insufficient_coverage(self, agent):
        fv = {"collateral_value": 50_000, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 100_000})
        a = result.payload["qualitative_assessment"]
        assert a.collateral_quality == "Insufficient"

    def test_no_collateral(self, agent):
        fv = {"employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 20_000})
        a = result.payload["qualitative_assessment"]
        assert a.collateral_quality == "N/A"
        assert a.collateral_coverage_ratio is None


# ---------------------------------------------------------------------------
# Industry risk
# ---------------------------------------------------------------------------

class TestIndustryRisk:
    @pytest.mark.parametrize("naics,expected_tier", [
        ("52", "Low"),     # Finance
        ("44", "Low"),     # Retail
        ("23", "High"),    # Construction
        ("11", "Elevated"),  # Agriculture
        ("72", "Medium"),  # Accommodation
    ])
    def test_known_naics_codes(self, agent, naics, expected_tier):
        fv = {"naics_code": naics, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 0})
        a = result.payload["qualitative_assessment"]
        assert a.industry_risk_tier == expected_tier

    def test_unknown_naics_defaults_to_medium(self, agent):
        fv = {"naics_code": "99", "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 0})
        a = result.payload["qualitative_assessment"]
        assert a.industry_risk_tier == "Medium"

    def test_no_naics_defaults(self, agent):
        fv = {"employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 0})
        assert result.ok


# ---------------------------------------------------------------------------
# Red flag detection
# ---------------------------------------------------------------------------

class TestRedFlagDetection:
    def test_fraud_flag_critical(self, agent):
        fv = {"employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({
            "feature_vector": fv,
            "model_scores": _make_model_scores(fraud_prob=0.5),
            "loan_amount": 10_000,
        })
        flags = result.payload["qualitative_assessment"].red_flags
        fraud_flags = [f for f in flags if f.flag_type == "FRAUD_INDICATORS"]
        assert len(fraud_flags) == 1
        assert fraud_flags[0].severity == "Critical"

    def test_bankruptcy_flag_critical(self, agent):
        fv = {"num_bankruptcy": 1, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        assert any(f.flag_type == "RECENT_BANKRUPTCY" and f.severity == "Critical" for f in flags)

    def test_high_dti_flag(self, agent):
        fv = {"dti": 0.55, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        assert any(f.flag_type == "HIGH_DTI" and f.severity == "High" for f in flags)

    def test_thin_file_flag(self, agent):
        fv = {"num_open_trades": 2, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        assert any(f.flag_type == "THIN_FILE" and f.severity == "Medium" for f in flags)

    def test_missed_payments_flag(self, agent):
        fv = {"num_missed_pmts_12m": 3, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        assert any(f.flag_type == "EXCESSIVE_MISSED_PAYMENTS" for f in flags)

    def test_cash_advance_flag(self, agent):
        fv = {
            "cash_advance_total_12m": 4_000,
            "credit_limit": 10_000,
            "employment_status": "employed",
            "emp_years": 3,
            "annual_income": 80_000,
        }
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        assert any(f.flag_type == "HIGH_CASH_ADVANCE_USAGE" for f in flags)

    def test_no_flags_on_clean_applicant(self, agent):
        fv = {
            "employment_status": "employed",
            "emp_years": 5,
            "annual_income": 120_000,
            "dti": 0.28,
            "num_missed_pmts_12m": 0,
            "num_bankruptcy": 0,
            "num_open_trades": 8,
            "pct_rev_utilization": 0.20,
        }
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(fraud_prob=0.02), "loan_amount": 30_000})
        a = result.payload["qualitative_assessment"]
        assert a.red_flags == []
        assert a.overall_risk_opinion == "Acceptable"

    def test_flags_sorted_critical_first(self, agent):
        fv = {
            "num_bankruptcy": 1,                 # Critical
            "num_missed_pmts_12m": 4,            # High
            "num_open_trades": 1,                # Medium
            "employment_status": "employed",
            "emp_years": 3,
            "annual_income": 80_000,
        }
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(fraud_prob=0.4), "loan_amount": 10_000})
        flags = result.payload["qualitative_assessment"].red_flags
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        for i in range(len(flags) - 1):
            assert severity_order[flags[i].severity] <= severity_order[flags[i + 1].severity]


# ---------------------------------------------------------------------------
# Overall risk opinion
# ---------------------------------------------------------------------------

class TestOverallRiskOpinion:
    def test_critical_flag_gives_unacceptable(self, agent):
        fv = {"num_bankruptcy": 1, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(), "loan_amount": 10_000})
        assert result.payload["qualitative_assessment"].overall_risk_opinion == "Unacceptable"

    def test_high_flag_gives_marginal(self, agent):
        fv = {
            "dti": 0.55,  # High flag
            "employment_status": "employed",
            "emp_years": 3,
            "annual_income": 80_000,
            "num_bankruptcy": 0,
        }
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(fraud_prob=0.05), "loan_amount": 10_000})
        assert result.payload["qualitative_assessment"].overall_risk_opinion == "Marginal"

    def test_low_cw_score_gives_marginal(self, agent):
        fv = {"employment_status": "unemployed", "emp_years": 0, "annual_income": 10_000}
        result = agent.execute({"feature_vector": fv, "model_scores": _make_model_scores(fraud_prob=0.05), "loan_amount": 1_000})
        a = result.payload["qualitative_assessment"]
        # cw_score == 1, no high/critical flags → Marginal
        assert a.overall_risk_opinion == "Marginal"


# ---------------------------------------------------------------------------
# Agent contract
# ---------------------------------------------------------------------------

class TestAgentContract:
    def test_result_ok_on_valid_inputs(self, agent):
        result = agent.execute({"feature_vector": {}, "model_scores": None, "loan_amount": 0})
        assert result.ok
        assert result.status == AgentStatus.SUCCESS

    def test_payload_contains_assessment(self, agent):
        result = agent.execute({"feature_vector": {}, "model_scores": None, "loan_amount": 0})
        assert "qualitative_assessment" in result.payload
        assert isinstance(result.payload["qualitative_assessment"], QualitativeAssessment)

    def test_disabled_agent_returns_none_assessment(self):
        agent = CreditAnalystAgent(config={"credit_analyst": {"enabled": False}})
        result = agent.execute({"feature_vector": {}, "model_scores": None, "loan_amount": 0})
        assert result.ok
        assert result.payload["qualitative_assessment"] is None

    def test_assessment_dict_serialisable(self, agent):
        result = agent.execute({
            "feature_vector": {"num_bankruptcy": 1, "employment_status": "employed", "emp_years": 3, "annual_income": 80_000},
            "model_scores": _make_model_scores(),
            "loan_amount": 50_000,
        })
        d = result.payload["qualitative_assessment"].dict()
        assert isinstance(d, dict)
        assert "overall_risk_opinion" in d
        assert isinstance(d["red_flags"], list)
