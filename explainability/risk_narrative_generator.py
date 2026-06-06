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
    NAICS_SECTOR_NAMES,
    NAICS_SECTOR_OUTLOOK,
    QualitativeAssessment,
    RedFlag,
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

    parts = [
        f"Borrower reports annual income of {_fmt_money(income)} "
        f"with {emp_status} employment status and {emp_tenure} of employment history."
    ]
    parts.append(
        f"Credit bureau score is {fico_str} ({pd_band} risk band). "
        f"Probability of Default: {pd_score:.2%}. "
        f"Creditworthiness score: {assessment.creditworthiness_score}/5."
    )
    return " ".join(parts)


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

    parts: List[str] = []
    if dti is not None:
        parts.append(f"Debt-to-income ratio is {_fmt_pct(dti)}, "
                     f"which is {'within' if float(dti) <= 0.43 else 'above'} "
                     "standard underwriting guidelines.")
    if util is not None:
        parts.append(f"Revolving credit utilization stands at {_fmt_pct(util)}.")
    if ontime is not None:
        parts.append(f"On-time payment rate over the last 12 months is {_fmt_pct(ontime)}.")
    if derog:
        parts.append(f"There are {int(float(derog))} derogatory mark(s) on file.")
    if bankruptcy and float(bankruptcy) > 0:
        parts.append(f"A total of {int(float(bankruptcy))} bankruptcy event(s) have been recorded.")
    if expected_loss is not None:
        parts.append(f"Expected loss on this account is estimated at {_fmt_money(expected_loss)}.")
    return " ".join(parts) if parts else "Insufficient financial data to perform full strength assessment."


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

    parts = [
        f"Collateral type: {col_type}.",
        f"Appraised value: {_fmt_money(col_value)}.",
    ]
    if coverage is not None:
        parts.append(
            f"Loan-to-collateral coverage ratio: {coverage:.2f}x "
            f"({quality} — "
            + ("fully covers the requested exposure."
               if quality == "Adequate"
               else "marginal coverage; additional security may be required."
               if quality == "Marginal"
               else "insufficient; collateral does not adequately secure the loan.") + ")"
        )
    return " ".join(parts)


def _render_industry_macro(assessment: QualitativeAssessment) -> str:
    naics = assessment.naics_code
    sector = assessment.sector_name
    tier = assessment.industry_risk_tier
    outlook = NAICS_SECTOR_OUTLOOK.get(naics, NAICS_SECTOR_OUTLOOK["default"])
    return (
        f"Borrower operates in the {sector} sector (NAICS {naics}), "
        f"classified as {tier} industry risk. {outlook}"
    )


def _render_red_flag_summary(red_flags: List[RedFlag]) -> str:
    if not red_flags:
        return ""
    lines = ["The following risk concerns were identified during qualitative review:", ""]
    for flag in red_flags:
        lines.append(
            f"- **[{flag.severity}] {flag.flag_type}**: {flag.description}"
        )
    return "\n".join(lines)


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

    parts = [
        f"Based on the qualitative assessment, this application presents a "
        f"**{opinion}** risk profile."
    ]

    if flag_count > 0:
        parts.append(
            f"A total of {flag_count} risk flag(s) were identified "
            f"({critical_count} Critical, {high_count} High)."
        )

    parts.append(
        f"The probability of default is {pd_score:.2%} and the "
        f"creditworthiness score is {assessment.creditworthiness_score}/5."
    )

    if shap_top_factors:
        top_feature, top_value = shap_top_factors[0]
        direction = "positively" if top_value > 0 else "negatively"
        parts.append(
            f"The primary model driver is `{top_feature}`, which {direction} "
            "influenced the risk score."
        )

    parts.append(recommendation)
    return " ".join(parts)


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
