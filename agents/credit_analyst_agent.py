"""
Credit Analyst Agent
====================
Performs deterministic qualitative credit assessment on each applicant,
mirroring the work of a human credit analyst:

  - Income and employment stability scoring
  - Collateral coverage analysis
  - Industry risk classification (NAICS-based)
  - Red flag detection (fraud, payment history, thin file, DTI, etc.)
  - Overall risk opinion synthesis

All logic is data-grounded and deterministic — no LLM calls.

Public API
----------
>>> from agents.credit_analyst_agent import CreditAnalystAgent
>>> agent = CreditAnalystAgent(config={"collateral_shortfall_threshold": 0.80})
>>> result = agent.execute({
...     "feature_vector": {"fico_score": 650, "dti": 0.35, ...},
...     "model_scores": model_scores,
...     "loan_amount": 25000.0,
... })
>>> assessment = result.payload["qualitative_assessment"]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from agents.base import AgentResult, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NAICS 2-digit sector → industry risk tier
# ---------------------------------------------------------------------------

NAICS_RISK_TIERS: Dict[str, str] = {
    "11": "Elevated",   # Agriculture, forestry, fishing, hunting
    "21": "Elevated",   # Mining, quarrying, oil and gas extraction
    "22": "Low",        # Utilities
    "23": "High",       # Construction
    "31": "Medium",     # Manufacturing (light)
    "32": "Medium",     # Manufacturing (paper, chemicals)
    "33": "Medium",     # Manufacturing (heavy)
    "42": "Low",        # Wholesale trade
    "44": "Low",        # Retail trade
    "45": "Low",        # Retail trade (non-store)
    "48": "Low",        # Transportation and warehousing
    "49": "Low",        # Postal and courier
    "51": "Low",        # Information
    "52": "Low",        # Finance and insurance
    "53": "Medium",     # Real estate and rental
    "54": "Low",        # Professional, scientific, technical services
    "55": "Low",        # Management of companies
    "56": "Medium",     # Administrative and support, waste management
    "61": "Medium",     # Educational services
    "62": "Medium",     # Health care and social assistance
    "71": "High",       # Arts, entertainment, recreation
    "72": "Medium",     # Accommodation and food services
    "81": "Medium",     # Other services (except public administration)
    "92": "Low",        # Public administration
    "default": "Medium",
}

# Human-readable sector names for narratives
NAICS_SECTOR_NAMES: Dict[str, str] = {
    "11": "Agriculture / Forestry / Fishing",
    "21": "Mining / Oil & Gas",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation / Warehousing",
    "49": "Postal / Courier",
    "51": "Information / Technology",
    "52": "Finance / Insurance",
    "53": "Real Estate",
    "54": "Professional / Technical Services",
    "55": "Management / Holding Companies",
    "56": "Administrative / Waste Management",
    "61": "Education",
    "62": "Health Care / Social Assistance",
    "71": "Arts / Entertainment / Recreation",
    "72": "Accommodation / Food Services",
    "81": "Other Services",
    "92": "Public Administration",
    "default": "General Industry",
}

# One-sentence sector outlook for narratives
NAICS_SECTOR_OUTLOOK: Dict[str, str] = {
    "11": "Agricultural sectors face elevated volatility from weather, commodity cycles, and export dependency.",
    "21": "Mining and energy sectors carry high cyclicality risk tied to commodity price fluctuations.",
    "22": "Utilities demonstrate stable, regulated cash flows with low default correlation.",
    "23": "Construction is highly cyclical, with elevated default rates during economic contractions.",
    "31": "Light manufacturing maintains moderate stability with some sensitivity to input costs.",
    "32": "Manufacturing is moderately sensitive to supply chain disruptions and trade policy.",
    "33": "Heavy manufacturing carries cyclical risk correlated with capital expenditure cycles.",
    "42": "Wholesale trade is relatively stable but exposed to supply chain and margin compression risk.",
    "44": "Retail trade faces structural headwinds from e-commerce competition and changing consumer patterns.",
    "45": "Non-store retail has shown resilience but faces intense competitive pressure.",
    "48": "Transportation and logistics have demonstrated stable demand with fuel cost sensitivity.",
    "49": "Postal and courier services benefit from e-commerce tailwinds.",
    "51": "Technology and information sectors show strong growth but elevated valuation risk.",
    "52": "Financial services maintain strong credit profiles with regulatory oversight.",
    "53": "Real estate is sensitive to interest rate cycles and local market conditions.",
    "54": "Professional services demonstrate stable demand and diversified client bases.",
    "55": "Management companies reflect the risk profile of their underlying operating entities.",
    "56": "Administrative services have moderate stability tied to broader economic activity.",
    "61": "Education services show stable demand with some exposure to enrollment trends.",
    "62": "Healthcare maintains resilient demand characteristics with regulatory reimbursement risk.",
    "71": "Arts and entertainment face high demand volatility tied to discretionary consumer spending.",
    "72": "Accommodation and food service sectors face high operating leverage and cyclical demand.",
    "81": "Other services demonstrate mixed risk profiles dependent on specific sub-sector.",
    "92": "Public administration entities carry sovereign-level credit characteristics.",
    "default": "This sector carries a medium risk profile based on general industry characteristics.",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RedFlag:
    """A specific risk concern identified during qualitative review."""

    flag_type: str
    severity: Literal["Low", "Medium", "High", "Critical"]
    feature: str
    observed_value: float
    threshold: float
    description: str


@dataclass
class QualitativeAssessment:
    """Full output of the CreditAnalystAgent for one applicant."""

    creditworthiness_score: int                                           # 1–5 ordinal
    collateral_quality: Literal["Adequate", "Marginal", "Insufficient", "N/A"]
    collateral_coverage_ratio: Optional[float]                            # collateral_value / loan_amount
    industry_risk_tier: Literal["Low", "Medium", "High", "Elevated"]
    naics_code: str
    sector_name: str
    red_flags: List[RedFlag] = field(default_factory=list)
    overall_risk_opinion: Literal["Acceptable", "Marginal", "Unacceptable"] = "Acceptable"

    def dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for JSON/audit storage."""
        return {
            "creditworthiness_score": self.creditworthiness_score,
            "collateral_quality": self.collateral_quality,
            "collateral_coverage_ratio": self.collateral_coverage_ratio,
            "industry_risk_tier": self.industry_risk_tier,
            "naics_code": self.naics_code,
            "sector_name": self.sector_name,
            "overall_risk_opinion": self.overall_risk_opinion,
            "red_flags": [
                {
                    "flag_type": f.flag_type,
                    "severity": f.severity,
                    "feature": f.feature,
                    "observed_value": f.observed_value,
                    "threshold": f.threshold,
                    "description": f.description,
                }
                for f in self.red_flags
            ],
        }


# ---------------------------------------------------------------------------
# CreditAnalystAgent
# ---------------------------------------------------------------------------

class CreditAnalystAgent(BaseAgent):
    """
    Qualitative credit assessment agent.

    Performs deterministic, rule-based assessment of borrower creditworthiness,
    collateral quality, industry risk, and red flags.  Produces a
    QualitativeAssessment that is stored in the pipeline payload alongside
    quantitative model scores.

    Config keys (from agent_config.yaml → credit_analyst):
      enabled:                      bool   (default: true)
      collateral_shortfall_threshold: float (default: 0.80)
      high_cash_advance_ratio:       float (default: 0.30)
      missed_payment_threshold:      int   (default: 2)
    """

    name = "CreditAnalystAgent"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(config)
        ca_cfg = self.config.get("credit_analyst", self.config)
        self._enabled: bool = ca_cfg.get("enabled", True)
        self._collateral_shortfall_threshold: float = float(
            ca_cfg.get("collateral_shortfall_threshold", 0.80)
        )
        self._high_cash_advance_ratio: float = float(
            ca_cfg.get("high_cash_advance_ratio", 0.30)
        )
        self._missed_payment_threshold: int = int(
            ca_cfg.get("missed_payment_threshold", 2)
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _creditworthiness_score(self, fv: Dict[str, Any]) -> int:
        """
        Returns an ordinal 1–5 score for borrower creditworthiness.

        Scoring grid (additive):
          employment_status == "employed" AND emp_years >= 2  → +2
          employment_status == "self_employed"                → +1
          annual_income > 150 000                            → +2
          annual_income > 80 000 (but <= 150 000)            → +1
        Base score starts at 1; capped at 5.
        """
        score = 1
        emp_status = str(fv.get("employment_status", "")).lower()
        emp_years = float(fv.get("emp_years", fv.get("employer_tenure_months", 0)) or 0)
        # Convert months to years if the feature is in months
        if emp_years > 50:  # almost certainly months, not years
            emp_years = emp_years / 12.0

        if emp_status == "employed" and emp_years >= 2:
            score += 2
        elif emp_status in ("self_employed", "self employed"):
            score += 1

        annual_income = float(fv.get("annual_income", 0) or 0)
        if annual_income > 150_000:
            score += 2
        elif annual_income > 80_000:
            score += 1

        return min(score, 5)

    def _collateral_analysis(
        self,
        fv: Dict[str, Any],
        loan_amount: float,
    ) -> tuple[Literal["Adequate", "Marginal", "Insufficient", "N/A"], Optional[float]]:
        """
        Returns (collateral_quality_label, coverage_ratio).
        Coverage ratio = collateral_value / loan_amount.
        """
        collateral_value = float(fv.get("collateral_value", fv.get("collateral_value_usd", 0)) or 0)
        if collateral_value <= 0 or loan_amount <= 0:
            return "N/A", None

        coverage = collateral_value / loan_amount
        if coverage >= 1.25:
            quality: Literal["Adequate", "Marginal", "Insufficient", "N/A"] = "Adequate"
        elif coverage >= 0.80:
            quality = "Marginal"
        else:
            quality = "Insufficient"
        return quality, round(coverage, 4)

    def _industry_risk(self, fv: Dict[str, Any]) -> tuple[str, str, str]:
        """Returns (naics_2d, sector_name, risk_tier)."""
        naics_raw = str(fv.get("naics_code", fv.get("industry_naics_2d", "")) or "")
        naics_2d = naics_raw[:2] if naics_raw else "default"
        if naics_2d not in NAICS_RISK_TIERS:
            naics_2d = "default"
        tier: str = NAICS_RISK_TIERS[naics_2d]
        name: str = NAICS_SECTOR_NAMES.get(naics_2d, "General Industry")
        return naics_2d, name, tier  # type: ignore[return-value]

    def _detect_red_flags(
        self,
        fv: Dict[str, Any],
        fraud_probability: float,
        coverage_ratio: Optional[float],
    ) -> List[RedFlag]:
        """
        Evaluates all red-flag conditions and returns every one that triggers.
        Order: Critical first, then High, then Medium, then Low.
        """
        flags: List[RedFlag] = []

        # ── FRAUD_INDICATORS ─────────────────────────────────────────
        fraud_threshold = 0.3
        if fraud_probability >= fraud_threshold:
            flags.append(RedFlag(
                flag_type="FRAUD_INDICATORS",
                severity="Critical",
                feature="fraud_probability",
                observed_value=round(fraud_probability, 4),
                threshold=fraud_threshold,
                description=(
                    f"Fraud model score {fraud_probability:.1%} exceeds the "
                    f"{fraud_threshold:.0%} review threshold, indicating potential "
                    "identity fraud or application misrepresentation."
                ),
            ))

        # ── RECENT_BANKRUPTCY ─────────────────────────────────────────
        num_bankruptcy = float(fv.get("num_bankruptcy", 0) or 0)
        if num_bankruptcy > 0:
            flags.append(RedFlag(
                flag_type="RECENT_BANKRUPTCY",
                severity="Critical",
                feature="num_bankruptcy",
                observed_value=num_bankruptcy,
                threshold=0,
                description=(
                    f"Applicant has {int(num_bankruptcy)} recorded bankruptcy event(s). "
                    "Bankruptcy on record is a critical adverse indicator."
                ),
            ))

        # ── HIGH_CASH_ADVANCE ─────────────────────────────────────────
        cash_advance = float(fv.get("cash_advance_total_12m", 0) or 0)
        credit_limit = float(fv.get("credit_limit", 0) or 0)
        cash_adv_threshold = self._high_cash_advance_ratio
        if credit_limit > 0 and cash_advance > cash_adv_threshold * credit_limit:
            flags.append(RedFlag(
                flag_type="HIGH_CASH_ADVANCE_USAGE",
                severity="High",
                feature="cash_advance_total_12m",
                observed_value=round(cash_advance, 2),
                threshold=round(cash_adv_threshold * credit_limit, 2),
                description=(
                    f"Cash advance usage of ${cash_advance:,.0f} represents "
                    f"{cash_advance / credit_limit:.1%} of credit limit, exceeding "
                    f"the {cash_adv_threshold:.0%} threshold. High cash advance "
                    "usage is a strong indicator of liquidity stress."
                ),
            ))

        # ── EXCESSIVE_MISSED_PAYMENTS ─────────────────────────────────
        missed_pmts = float(fv.get("num_missed_pmts_12m", 0) or 0)
        missed_threshold = self._missed_payment_threshold
        if missed_pmts > missed_threshold:
            flags.append(RedFlag(
                flag_type="EXCESSIVE_MISSED_PAYMENTS",
                severity="High",
                feature="num_missed_pmts_12m",
                observed_value=missed_pmts,
                threshold=float(missed_threshold),
                description=(
                    f"Applicant missed {int(missed_pmts)} payments in the last 12 months, "
                    f"exceeding the threshold of {missed_threshold}. "
                    "Persistent missed payments indicate poor debt management."
                ),
            ))

        # ── HIGH_DTI ──────────────────────────────────────────────────
        dti = float(fv.get("dti", fv.get("debt_to_income", 0)) or 0)
        if dti > 0.50:
            flags.append(RedFlag(
                flag_type="HIGH_DTI",
                severity="High",
                feature="dti",
                observed_value=round(dti, 4),
                threshold=0.50,
                description=(
                    f"Debt-to-income ratio of {dti:.1%} exceeds the 50% threshold. "
                    "Elevated DTI significantly constrains repayment capacity."
                ),
            ))

        # ── COLLATERAL_SHORTFALL ──────────────────────────────────────
        if coverage_ratio is not None and coverage_ratio < self._collateral_shortfall_threshold:
            flags.append(RedFlag(
                flag_type="COLLATERAL_SHORTFALL",
                severity="High",
                feature="collateral_coverage_ratio",
                observed_value=round(coverage_ratio, 4),
                threshold=self._collateral_shortfall_threshold,
                description=(
                    f"Collateral coverage ratio of {coverage_ratio:.2f}x is below "
                    f"the required {self._collateral_shortfall_threshold:.2f}x threshold. "
                    "Insufficient collateral increases loss severity on default."
                ),
            ))

        # ── HIGH_UTILIZATION ──────────────────────────────────────────
        utilization = float(fv.get("pct_rev_utilization", fv.get("credit_util", 0)) or 0)
        if utilization > 0.85:
            flags.append(RedFlag(
                flag_type="HIGH_REVOLVING_UTILIZATION",
                severity="Medium",
                feature="pct_rev_utilization",
                observed_value=round(utilization, 4),
                threshold=0.85,
                description=(
                    f"Revolving utilization of {utilization:.1%} exceeds the 85% "
                    "threshold, indicating the borrower is near their credit limit "
                    "and may be credit-dependent."
                ),
            ))

        # ── THIN_FILE ─────────────────────────────────────────────────
        num_open_trades = float(fv.get("num_open_trades", fv.get("num_open_accounts", 99)) or 99)
        if num_open_trades < 3:
            flags.append(RedFlag(
                flag_type="THIN_FILE",
                severity="Medium",
                feature="num_open_trades",
                observed_value=num_open_trades,
                threshold=3.0,
                description=(
                    f"Only {int(num_open_trades)} open trade line(s) on file. "
                    "A thin credit file limits the model's ability to accurately "
                    "assess repayment behaviour."
                ),
            ))

        # Sort: Critical → High → Medium → Low
        _severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        flags.sort(key=lambda f: _severity_order.get(f.severity, 9))
        return flags

    def _overall_opinion(
        self,
        red_flags: List[RedFlag],
        cw_score: int,
    ) -> Literal["Acceptable", "Marginal", "Unacceptable"]:
        """Derive overall risk opinion from red flags and creditworthiness score."""
        severities = {f.severity for f in red_flags}
        if "Critical" in severities:
            return "Unacceptable"
        if "High" in severities or cw_score <= 2:
            return "Marginal"
        return "Acceptable"

    # ------------------------------------------------------------------
    # _run
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        if not self._enabled:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                payload={"qualitative_assessment": None},
                warnings=["CreditAnalystAgent is disabled via config"],
            )

        fv: Dict[str, Any] = inputs.get("feature_vector", {})
        model_scores = inputs.get("model_scores")
        loan_amount = float(inputs.get("loan_amount", 0) or 0)

        # Extract fraud probability from model_scores (supports both dataclass and dict)
        if model_scores is None:
            fraud_probability = 0.0
        elif hasattr(model_scores, "fraud_probability"):
            fraud_probability = float(model_scores.fraud_probability)
        elif isinstance(model_scores, dict):
            fraud_probability = float(model_scores.get("fraud_probability", 0.0))
        else:
            fraud_probability = 0.0

        # ── Creditworthiness score ────────────────────────────────────
        cw_score = self._creditworthiness_score(fv)

        # ── Collateral analysis ───────────────────────────────────────
        collateral_quality, coverage_ratio = self._collateral_analysis(fv, loan_amount)

        # ── Industry risk ─────────────────────────────────────────────
        naics_2d, sector_name, industry_risk_tier = self._industry_risk(fv)

        # ── Red flags ────────────────────────────────────────────────
        red_flags = self._detect_red_flags(fv, fraud_probability, coverage_ratio)

        # ── Overall opinion ───────────────────────────────────────────
        overall_opinion = self._overall_opinion(red_flags, cw_score)

        assessment = QualitativeAssessment(
            creditworthiness_score=cw_score,
            collateral_quality=collateral_quality,
            collateral_coverage_ratio=coverage_ratio,
            industry_risk_tier=industry_risk_tier,  # type: ignore[arg-type]
            naics_code=naics_2d,
            sector_name=sector_name,
            red_flags=red_flags,
            overall_risk_opinion=overall_opinion,
        )

        self._log.info(
            "CreditAnalyst: cw_score=%d, collateral=%s, industry_risk=%s, "
            "flags=%d, opinion=%s",
            cw_score,
            collateral_quality,
            industry_risk_tier,
            len(red_flags),
            overall_opinion,
        )

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={"qualitative_assessment": assessment},
        )
