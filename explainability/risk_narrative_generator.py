"""
Risk Narrative Generator
========================
Produces a structured, per-account risk narrative document using
deterministic string templates — no LLM calls.  Every sentence is
data-grounded: it references a specific feature value or assessment result.

Public API
----------
>>> from explainability.risk_narrative_generator import generate_risk_narrative
>>> doc = generate_risk_narrative(
...     account_id="APP-001",
...     features={"annual_income": 85000, "dti": 0.32, ...},
...     assessment=assessment,
...     model_scores=model_scores,
... )
>>> print(doc.as_markdown())
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agents.credit_analyst_agent import (
    QualitativeAssessment,
    RedFlag,
)

import jinja2
from pathlib import Path

# Set up Jinja2 environment
_template_dir = Path(__file__).parent / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_template_dir),
    autoescape=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class RiskNarrativeDocument:
    """
    Structured per-account risk narrative.

    Each section is a rendered string.  Sections that are not applicable
    (e.g. collateral_analysis for unsecured loans) are empty strings.
    """

    account_id: str
    generated_at: str                  # ISO-8601 UTC
    borrower_profile: str
    financial_strength: str
    collateral_analysis: str           # "" if no collateral
    industry_macro: str
    red_flag_summary: str              # "" if no red flags
    overall_credit_opinion: str
    risk_opinion: str                  # Acceptable | Marginal | Unacceptable

    def as_markdown(self) -> str:
        """Render all non-empty sections as a Markdown document."""
        sections: List[Tuple[str, str]] = [
            ("Borrower Profile", self.borrower_profile),
            ("Financial Strength", self.financial_strength),
            ("Collateral Analysis", self.collateral_analysis),
            ("Industry & Macro Context", self.industry_macro),
            ("Red Flags", self.red_flag_summary),
            ("Overall Credit Opinion", self.overall_credit_opinion),
        ]
        lines: List[str] = [
            f"# Credit Risk Narrative — {self.account_id}",
            f"*Generated: {self.generated_at}*",
            "",
        ]
        for header, body in sections:
            if body.strip():
                lines.append(f"## {header}")
                lines.append(body.strip())
                lines.append("")
        return "\n".join(lines)

    def dict(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "generated_at": self.generated_at,
            "borrower_profile": self.borrower_profile,
            "financial_strength": self.financial_strength,
            "collateral_analysis": self.collateral_analysis,
            "industry_macro": self.industry_macro,
            "red_flag_summary": self.red_flag_summary,
            "overall_credit_opinion": self.overall_credit_opinion,
            "risk_opinion": self.risk_opinion,
        }


# ---------------------------------------------------------------------------
# Safe value helpers
# ---------------------------------------------------------------------------

def _g(features: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Get first matching key from features dict; return default if missing."""
    for k in keys:
        v = features.get(k)
        if v is not None:
            return v
    return default


def _fmt_money(v: Any) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "Not provided"


def _fmt_pct(v: Any, digits: int = 1) -> str:
    try:
        return f"{float(v) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "Not provided"


def _fmt_num(v: Any, digits: int = 0) -> str:
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "Not provided"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_borrower_profile(
    features: Dict[str, Any],
    assessment: QualitativeAssessment,
    pd_score: float,
    pd_band: str,
) -> str:
    income = _g(features, "annual_income")
    emp_status = _g(features, "employment_status", default="not provided")
    emp_years_raw = _g(features, "emp_years", "employer_tenure_months", default=None)
    if emp_years_raw is not None:
        emp_years = float(emp_years_raw)
        if emp_years > 50:
            emp_years = emp_years / 12.0
        emp_tenure = f"{emp_years:.1f} years"
    else:
        emp_tenure = "not provided"

    fico = _g(features, "fico_score", "credit_score", "credit_bureau_score", default=None)
    fico_str = f"{float(fico):.0f}" if fico is not None else "not provided"

    template = _jinja_env.get_template("borrower_profile.j2")
    return template.render(
        income=_fmt_money(income),
        emp_status=emp_status,
        emp_tenure=emp_tenure,
        fico=fico_str,
        pd_band=pd_band,
        pd_score=f"{pd_score:.2%}",
        creditworthiness_score=assessment.creditworthiness_score
    )


def _render_financial_strength(
    features: Dict[str, Any],
    pd_score: float,
    expected_loss: Optional[float],
) -> str:
    dti = _g(features, "dti", "debt_to_income")
    util = _g(features, "pct_rev_utilization", "credit_util", "avg_utilization_12m")
    ontime = _g(features, "pct_ontime_pmts_12m")
    derog = _g(features, "num_derog_marks", "num_derogatory_marks", default=0)
    bankruptcy = _g(features, "num_bankruptcy", default=0)

    has_data = any(x is not None for x in (dti, util, ontime, expected_loss)) or bool(derog) or bool(bankruptcy)

    template = _jinja_env.get_template("financial_strength.j2")
    return template.render(
        has_data=has_data,
        dti=_fmt_pct(dti) if dti is not None else None,
        dti_eval='within' if dti is not None and float(dti) <= 0.43 else 'above',
        util=_fmt_pct(util) if util is not None else None,
        ontime=_fmt_pct(ontime) if ontime is not None else None,
        derog=int(float(derog)) if derog else None,
        bankruptcy=int(float(bankruptcy)) if bankruptcy and float(bankruptcy) > 0 else None,
        expected_loss=_fmt_money(expected_loss) if expected_loss is not None else None
    )


def _render_collateral_analysis(
    features: Dict[str, Any],
    assessment: QualitativeAssessment,
) -> str:
    if assessment.collateral_quality == "N/A":
        return ""

    col_type = _g(features, "collateral_type", default="unspecified")
    col_value = _g(features, "collateral_value", "collateral_value_usd")
    coverage = assessment.collateral_coverage_ratio
    quality = assessment.collateral_quality

    quality_eval = (
        "fully covers the requested exposure." if quality == "Adequate"
        else "marginal coverage; additional security may be required." if quality == "Marginal"
        else "insufficient; collateral does not adequately secure the loan."
    )

    template = _jinja_env.get_template("collateral_analysis.j2")
    return template.render(
        has_collateral=True,
        col_type=col_type,
        col_value=_fmt_money(col_value),
        coverage=f"{coverage:.2f}x" if coverage is not None else None,
        quality=quality,
        quality_eval=quality_eval
    )


def _render_industry_macro(assessment: QualitativeAssessment) -> str:
    naics = assessment.naics_code
    sector = assessment.sector_name
    tier = assessment.industry_risk_tier
    # Import NAICS_SECTOR_OUTLOOK from agents/credit_analyst_agent here or hardcode it since it's just for the template
    # Wait, earlier we removed the import of NAICS_SECTOR_OUTLOOK.
    # Let's import it locally to avoid circular dependency issues
    from agents.credit_analyst_agent import NAICS_SECTOR_OUTLOOK
    outlook = NAICS_SECTOR_OUTLOOK.get(naics, NAICS_SECTOR_OUTLOOK["default"])
    template = _jinja_env.get_template("industry_macro.j2")
    return template.render(
        sector=sector,
        naics=naics,
        tier=tier,
        outlook=outlook
    )


def _render_red_flag_summary(red_flags: List[RedFlag]) -> str:
    if not red_flags:
        return ""
    template = _jinja_env.get_template("red_flags.j2")
    return template.render(red_flags=red_flags)


def _render_overall_opinion(
    assessment: QualitativeAssessment,
    pd_score: float,
    red_flags: List[RedFlag],
    shap_top_factors: Optional[List[Tuple[str, float]]],
) -> str:
    opinion = assessment.overall_risk_opinion
    flag_count = len(red_flags)
    critical_count = sum(1 for f in red_flags if f.severity == "Critical")
    high_count = sum(1 for f in red_flags if f.severity == "High")

    recommendation_map = {
        "Acceptable": "Recommend proceeding with standard credit terms.",
        "Marginal": "Recommend referral to senior underwriter for additional review.",
        "Unacceptable": "Recommend decline.",
    }
    recommendation = recommendation_map[opinion]

    recommendation = recommendation_map.get(opinion, recommendation_map["Marginal"])

    top_feature = None
    direction = None
    if shap_top_factors:
        top_feature, top_value = shap_top_factors[0]
        direction = "positively" if top_value > 0 else "negatively"

    template = _jinja_env.get_template("credit_opinion.j2")
    return template.render(
        opinion=opinion,
        flag_count=flag_count,
        critical_count=critical_count,
        high_count=high_count,
        pd_score=f"{pd_score:.2%}",
        cw_score=assessment.creditworthiness_score,
        top_feature=top_feature,
        direction=direction,
        recommendation=recommendation
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_risk_narrative(
    account_id: str,
    features: Dict[str, Any],
    assessment: QualitativeAssessment,
    model_scores: Any,
    shap_top_factors: Optional[List[Tuple[str, float]]] = None,
) -> RiskNarrativeDocument:
    """
    Generate a structured, data-grounded risk narrative document.

    Parameters
    ----------
    account_id:
        Application or account identifier for the document header.
    features:
        Feature dictionary as produced by FeatureEngineeringAgent.
    assessment:
        QualitativeAssessment from CreditAnalystAgent.
    model_scores:
        ModelScores dataclass (or dict) from RiskModelingAgent.
    shap_top_factors:
        Optional list of (feature_name, shap_value) tuples, descending by
        absolute value.  Used to cite the primary model driver in the
        overall opinion section.

    Returns
    -------
    RiskNarrativeDocument
        Fully populated narrative, serialisable via .as_markdown() or .dict().
    """
    # Extract scores defensively (supports dataclass and dict)
    if model_scores is None:
        pd_score = 0.0
        pd_band = "unknown"
        expected_loss = None
    elif hasattr(model_scores, "pd_score"):
        pd_score = float(model_scores.pd_score)
        pd_band = str(getattr(model_scores, "pd_band", "unknown"))
        expected_loss = getattr(model_scores, "expected_loss", None)
    elif isinstance(model_scores, dict):
        pd_score = float(model_scores.get("pd_score", 0.0))
        pd_band = str(model_scores.get("pd_band", "unknown"))
        expected_loss = model_scores.get("expected_loss")
    else:
        pd_score = 0.0
        pd_band = "unknown"
        expected_loss = None

    generated_at = datetime.now(timezone.utc).isoformat()

    borrower_profile = _render_borrower_profile(features, assessment, pd_score, pd_band)
    financial_strength = _render_financial_strength(features, pd_score, expected_loss)
    collateral_analysis = _render_collateral_analysis(features, assessment)
    industry_macro = _render_industry_macro(assessment)
    red_flag_summary = _render_red_flag_summary(assessment.red_flags)
    overall_credit_opinion = _render_overall_opinion(
        assessment, pd_score, assessment.red_flags, shap_top_factors
    )

    return RiskNarrativeDocument(
        account_id=account_id,
        generated_at=generated_at,
        borrower_profile=borrower_profile,
        financial_strength=financial_strength,
        collateral_analysis=collateral_analysis,
        industry_macro=industry_macro,
        red_flag_summary=red_flag_summary,
        overall_credit_opinion=overall_credit_opinion,
        risk_opinion=assessment.overall_risk_opinion,
    )
