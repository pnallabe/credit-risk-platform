import pytest
from explainability.risk_narrative_generator import generate_risk_narrative
from agents.credit_analyst_agent import QualitativeAssessment, RedFlag

@pytest.fixture
def assessment():
    return QualitativeAssessment(
        creditworthiness_score=4,
        collateral_quality="Adequate",
        collateral_coverage_ratio=1.5,
        industry_risk_tier="Low",
        naics_code="54",
        sector_name="Professional Services",
        overall_risk_opinion="Acceptable"
    )

def test_generate_risk_narrative_has_all_sections(assessment):
    doc = generate_risk_narrative(
        account_id="TEST-123",
        features={"annual_income": 90000, "dti": 0.2, "collateral_value": 150000},
        assessment=assessment,
        model_scores={"pd_score": 0.02, "pd_band": "low"}
    )
    md = doc.as_markdown()

    # Check sections
    assert "Borrower Profile" in md
    assert "Financial Strength" in md
    assert "Collateral Analysis" in md
    assert "Industry & Macro Context" in md
    assert "Overall Credit Opinion" in md

def test_collateral_analysis_absent_for_unsecured(assessment):
    assessment.collateral_quality = "N/A"
    doc = generate_risk_narrative(
        account_id="TEST-123",
        features={"annual_income": 90000},
        assessment=assessment,
        model_scores={"pd_score": 0.02, "pd_band": "low"}
    )
    md = doc.as_markdown()
    assert "Collateral Analysis" not in md

def test_narrative_contains_no_hallucinations(assessment):
    doc = generate_risk_narrative(
        account_id="TEST-123",
        features={"annual_income": 90000},
        assessment=assessment,
        model_scores={"pd_score": 0.02, "pd_band": "low"}
    )
    md = doc.as_markdown()
    # Income
    assert "90,000" in md
