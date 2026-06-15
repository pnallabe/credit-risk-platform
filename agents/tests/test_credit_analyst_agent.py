import pytest
from agents.credit_analyst_agent import CreditAnalystAgent

@pytest.fixture
def agent():
    return CreditAnalystAgent(config={"enabled": True})

def test_fraud_flag_creates_red_flag(agent):
    res = agent.execute({
        "feature_vector": {"annual_income": 100000},
        "model_scores": {"fraud_probability": 0.4},
        "loan_amount": 10000
    })
    flags = res.payload["qualitative_assessment"].red_flags
    assert any(f.flag_type == "FRAUD_INDICATORS" and f.severity == "Critical" for f in flags)

def test_dti_creates_red_flag(agent):
    res = agent.execute({
        "feature_vector": {"dti": 0.60},
        "model_scores": {"fraud_probability": 0.0},
        "loan_amount": 10000
    })
    flags = res.payload["qualitative_assessment"].red_flags
    assert any(f.flag_type == "HIGH_DTI" for f in flags)

def test_collateral_shortfall(agent):
    res = agent.execute({
        "feature_vector": {"collateral_value": 80000},
        "model_scores": {"fraud_probability": 0.0},
        "loan_amount": 100000
    })
    assessment = res.payload["qualitative_assessment"]
    assert assessment.collateral_quality == "Marginal"

def test_naics_parsing(agent):
    res = agent.execute({
        "feature_vector": {"naics_code": "72"},
        "model_scores": {"fraud_probability": 0.0},
        "loan_amount": 10000
    })
    assessment = res.payload["qualitative_assessment"]
    assert assessment.industry_risk_tier == "High"

def test_missing_naics_parsing(agent):
    res = agent.execute({
        "feature_vector": {},
        "model_scores": {"fraud_probability": 0.0},
        "loan_amount": 10000
    })
    assessment = res.payload["qualitative_assessment"]
    assert assessment.industry_risk_tier == "Medium"
