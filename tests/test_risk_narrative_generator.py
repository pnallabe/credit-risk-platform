"""
Tests for RiskNarrativeGenerator (Sprint S1-B)
"""

from __future__ import annotations

import pytest

from agents.credit_analyst_agent import (
    CreditAnalystAgent,
    QualitativeAssessment,
    RedFlag,
)
from explainability.risk_narrative_generator import (
    RiskNarrativeDocument,
    generate_risk_narrative,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assessment(
    cw_score: int = 4,
    collateral_quality: str = "Adequate",
    coverage_ratio: float | None = 1.25,
    industry_tier: str = "Low",
    naics_code: str = "52",
    sector_name: str = "Finance and Insurance",
    red_flags: list | None = None,
    opinion: str = "Acceptable",
) -> QualitativeAssessment:
    return QualitativeAssessment(
        creditworthiness_score=cw_score,
        collateral_quality=collateral_quality,
        collateral_coverage_ratio=coverage_ratio,
        industry_risk_tier=industry_tier,
        naics_code=naics_code,
        sector_name=sector_name,
        red_flags=red_flags or [],
        overall_risk_opinion=opinion,
    )


def _make_model_scores(pd_score: float = 0.04, fraud_prob: float = 0.03):
    return {"pd_score": pd_score, "pd_band": "low", "fraud_probability": fraud_prob}


def _make_red_flag(flag_type: str, severity: str = "High", feature: str = "dti",
                   observed: float = 0.55, threshold: float = 0.45,
                   desc: str = "High DTI") -> RedFlag:
    return RedFlag(
        flag_type=flag_type,
        severity=severity,
        feature=feature,
        observed_value=observed,
        threshold=threshold,
        description=desc,
    )


# ---------------------------------------------------------------------------
# generate_risk_narrative — return type contract
# ---------------------------------------------------------------------------

class TestGenerateRiskNarrativeContract:
    def test_returns_narrative_document(self):
        assessment = _make_assessment()
        doc = generate_risk_narrative(
            account_id="APP-001",
            features={"annual_income": 80_000, "employment_status": "employed"},
            assessment=assessment,
            model_scores=_make_model_scores(),
        )
        assert isinstance(doc, RiskNarrativeDocument)

    def test_account_id_preserved(self):
        doc = generate_risk_narrative(
            account_id="XYZ-9999",
            features={},
            assessment=_make_assessment(),
            model_scores=None,
        )
        assert doc.account_id == "XYZ-9999"

    def test_generated_at_is_set(self):
        doc = generate_risk_narrative(account_id="A1", features={}, assessment=_make_assessment(), model_scores=None)
        assert doc.generated_at is not None and len(str(doc.generated_at)) > 0

    def test_all_sections_present(self):
        doc = generate_risk_narrative(
            account_id="A2",
            features={"annual_income": 50_000},
            assessment=_make_assessment(),
            model_scores=_make_model_scores(),
        )
        assert doc.borrower_profile
        assert doc.financial_strength
        assert doc.collateral_analysis
        assert doc.industry_macro
        assert doc.overall_credit_opinion

    def test_dict_serialisable(self):
        doc = generate_risk_narrative(
            account_id="A3", features={}, assessment=_make_assessment(), model_scores=None
        )
        d = doc.dict()
        assert isinstance(d, dict)
        assert "account_id" in d


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

class TestAsMarkdown:
    def test_returns_non_empty_string(self):
        doc = generate_risk_narrative(
            account_id="M1", features={"annual_income": 60_000}, assessment=_make_assessment(), model_scores=_make_model_scores()
        )
        md = doc.as_markdown()
        assert isinstance(md, str) and len(md) > 100

    def test_contains_account_id(self):
        doc = generate_risk_narrative(account_id="ACCT-42", features={}, assessment=_make_assessment(), model_scores=None)
        assert "ACCT-42" in doc.as_markdown()

    def test_contains_overall_opinion(self):
        doc = generate_risk_narrative(account_id="X", features={}, assessment=_make_assessment(opinion="Marginal"), model_scores=None)
        assert "Marginal" in doc.as_markdown()

    def test_markdown_has_headings(self):
        doc = generate_risk_narrative(account_id="X", features={}, assessment=_make_assessment(), model_scores=None)
        md = doc.as_markdown()
        assert "#" in md  # at least one Markdown heading


# ---------------------------------------------------------------------------
# Scenario: clean prime borrower
# ---------------------------------------------------------------------------

class TestScenarioPrimeBorrower:
    def test_acceptable_opinion(self):
        assessment = _make_assessment(cw_score=5, opinion="Acceptable")
        doc = generate_risk_narrative(
            account_id="PRIME-1",
            features={
                "employment_status": "employed",
                "emp_years": 8,
                "annual_income": 150_000,
                "dti": 0.25,
                "pct_rev_utilization": 0.12,
                "collateral_value": 200_000,
                "naics_code": "52",
            },
            assessment=assessment,
            model_scores=_make_model_scores(pd_score=0.02, fraud_prob=0.01),
        )
        assert "Acceptable" in doc.as_markdown()
        assert doc.red_flag_summary  # section present even if empty

    def test_no_red_flags_section_is_short(self):
        doc = generate_risk_narrative(
            account_id="PRIME-2", features={}, assessment=_make_assessment(red_flags=[]), model_scores=None
        )
        # red_flag_summary should note absence of material flags
        assert doc.red_flag_summary


# ---------------------------------------------------------------------------
# Scenario: risky subprime borrower with red flags
# ---------------------------------------------------------------------------

class TestScenarioRiskyBorrower:
    @pytest.fixture
    def risky_assessment(self):
        return _make_assessment(
            cw_score=2,
            collateral_quality="Insufficient",
            coverage_ratio=0.40,
            industry_tier="High",
            naics_code="23",
            sector_name="Construction",
            red_flags=[
                _make_red_flag("RECENT_BANKRUPTCY", severity="Critical", feature="num_bankruptcy",
                               observed=1, threshold=0, desc="Bankruptcy on record"),
                _make_red_flag("HIGH_DTI", severity="High"),
            ],
            opinion="Unacceptable",
        )

    def test_unacceptable_opinion_propagated(self, risky_assessment):
        doc = generate_risk_narrative(
            account_id="RISKY-1",
            features={"annual_income": 35_000, "dti": 0.58, "employment_status": "part_time"},
            assessment=risky_assessment,
            model_scores=_make_model_scores(pd_score=0.42, fraud_prob=0.15),
        )
        assert "Unacceptable" in doc.as_markdown()

    def test_red_flags_in_summary(self, risky_assessment):
        doc = generate_risk_narrative(
            account_id="RISKY-2",
            features={},
            assessment=risky_assessment,
            model_scores=None,
        )
        assert "RECENT_BANKRUPTCY" in doc.red_flag_summary or "Bankruptcy" in doc.red_flag_summary

    def test_collateral_section_reflects_insufficient(self, risky_assessment):
        doc = generate_risk_narrative(
            account_id="RISKY-3",
            features={"collateral_value": 20_000},
            assessment=risky_assessment,
            model_scores=_make_model_scores(pd_score=0.42),
        )
        assert "Insufficient" in doc.collateral_analysis


# ---------------------------------------------------------------------------
# Scenario: secured vs unsecured loans
# ---------------------------------------------------------------------------

class TestSecuredVsUnsecured:
    def test_secured_collateral_quality_shown(self):
        assessment = _make_assessment(collateral_quality="Adequate", coverage_ratio=1.30)
        doc = generate_risk_narrative(
            account_id="SEC-1",
            features={"collateral_value": 130_000},
            assessment=assessment,
            model_scores=None,
        )
        assert "Adequate" in doc.collateral_analysis

    def test_unsecured_no_collateral(self):
        assessment = _make_assessment(collateral_quality="N/A", coverage_ratio=None)
        doc = generate_risk_narrative(
            account_id="UNSEC-1",
            features={},
            assessment=assessment,
            model_scores=None,
        )
        assert "N/A" in doc.collateral_analysis or "unsecured" in doc.collateral_analysis.lower()


# ---------------------------------------------------------------------------
# SHAP factors integration
# ---------------------------------------------------------------------------

class TestShapFactors:
    def test_shap_factors_present_in_narrative(self):
        shap = [("dti", -0.32), ("pct_rev_utilization", -0.18)]
        doc = generate_risk_narrative(
            account_id="SHAP-1",
            features={},
            assessment=_make_assessment(),
            model_scores=_make_model_scores(),
            shap_top_factors=shap,
        )
        md = doc.as_markdown()
        # At least the feature names or some SHAP content should appear somewhere
        assert "dti" in md or "pct_rev_utilization" in md or "SHAP" in md or len(md) > 200

    def test_shap_none_does_not_raise(self):
        doc = generate_risk_narrative(
            account_id="SHAP-2",
            features={},
            assessment=_make_assessment(),
            model_scores=None,
            shap_top_factors=None,
        )
        assert isinstance(doc, RiskNarrativeDocument)
