"""
decision_engine/mortgage_origination_policy.py
================================================
QM/ATR-compliant mortgage underwriting engine.

Framework
---------
  1. Hard declines  — FICO below minimum, LTV too high, ATR failure, jumbo suspended
  2. Manual review  — near-prime (580-659), near DTI QM boundary
  3. REFER_FHA      — conventional declined but FHA-eligible
  4. QM safe harbor — DTI ≤43%, all 8 ATR factors pass → APPROVE_QM
  5. Non-QM         — conditional approval outside safe harbor → APPROVE_NON_QM

Product routing
---------------
  Conforming (loan ≤ $726,200)
  Jumbo       (loan > $726,200, FICO ≥ jumbo_floor, jumbo_enabled=True)
  FHA         (FICO ≥ 580, LTV ≤ 96.5%)
  VA          (FICO ≥ 620, va_eligible=True)

Usage
-----
    python decision_engine/mortgage_origination_policy.py --demo 10
"""
from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compliance.adverse_action import REG_B_REASON_CODES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MortgageDecision(str, Enum):
    APPROVE_QM     = "APPROVE_QM"         # Safe harbor QM
    APPROVE_NON_QM = "APPROVE_NON_QM"     # Rebuttable presumption
    DECLINE        = "DECLINE"
    MANUAL_REVIEW  = "MANUAL_REVIEW"      # Near DTI boundary, near-prime
    REFER_FHA      = "REFER_FHA"          # Conventional declined, FHA eligible


class MortgageDeclineReason(str, Enum):
    FICO_BELOW_MINIMUM       = "FICO_BELOW_MINIMUM"
    DTI_EXCEED_QM            = "DTI_EXCEED_QM"
    LTV_EXCEEDS_LIMIT        = "LTV_EXCEEDS_LIMIT"
    ATR_FAILED               = "ATR_FAILED"
    JUMBO_POLICY_SUSPENDED   = "JUMBO_POLICY_SUSPENDED"
    INSUFFICIENT_ASSETS      = "INSUFFICIENT_ASSETS"
    PROPERTY_TYPE_INELIGIBLE = "PROPERTY_TYPE_INELIGIBLE"
    INCOME_UNVERIFIABLE      = "INCOME_UNVERIFIABLE"


# ---------------------------------------------------------------------------
# Module-level default policy parameters
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "fico_floor_fha":         580,
    "fico_floor_conforming":  640,
    "fico_floor_jumbo":       700,
    "max_dti_qm":             0.43,
    "max_ltv_standard":       0.97,
    "conforming_loan_limit":  726_200,
    "jumbo_enabled":          True,
    # Base rates (%)
    "fixed_30":               7.10,
    "fixed_15":               6.50,
    "arm_5_1":                6.75,
    "arm_7_1":                6.90,
    # Residual income thresholds ($)
    "residual_income_single": 1_500.0,
    "residual_income_family": 2_500.0,
    # Fraud / PD
    "fraud_reject_threshold": 0.50,
    "pd_hard_cutoff":         0.08,
    "pd_review_cutoff":       0.05,
}


# ---------------------------------------------------------------------------
# ATR / QM checker
# ---------------------------------------------------------------------------


def check_atr(application: dict) -> tuple[bool, list[str]]:
    """Evaluate the 8 ATR (Ability-to-Repay) factors per CFPB/Reg Z.

    Parameters
    ----------
    application : dict
        Expected keys: annual_income, monthly_income, assets_verified,
        employment_status, monthly_mortgage_payment, monthly_debt_total,
        dti, residual_income, bankruptcy_within_4yrs, monthly_piti,
        family_size (optional, default 1)

    Returns
    -------
    tuple[bool, list[str]]
        (is_qm, failed_factors)
    """
    failed: list[str] = []

    monthly_income  = float(application.get("monthly_income", 0))
    assets_verified = bool(application.get("assets_verified", False))
    emp_status      = str(application.get("employment_status", "employed")).lower()
    monthly_payment = float(application.get("monthly_mortgage_payment", 0))
    dti             = float(application.get("dti", 0.0))
    residual_income = float(application.get("residual_income", monthly_income * (1 - dti)))
    bk_within_4yr   = bool(application.get("bankruptcy_within_4yrs", False))
    monthly_piti    = float(application.get("monthly_piti", monthly_payment * 1.20))
    family_size     = int(application.get("family_size", 1))

    residual_threshold = (
        _DEFAULTS["residual_income_family"] if family_size > 1
        else _DEFAULTS["residual_income_single"]
    )

    # Factor 1: Income / assets
    if monthly_income <= 0 and not assets_verified:
        failed.append("factor_1_income_assets")

    # Factor 2: Employment status
    if emp_status == "unemployed":
        failed.append("factor_2_employment")

    # Factor 3: Monthly mortgage payment ≤28% of gross income
    if monthly_income > 0 and (monthly_payment / monthly_income) > 0.28:
        failed.append("factor_3_mortgage_payment_ratio")

    # Factor 4 & 5: DTI ≤43% for QM safe harbor
    if dti > 0.43:
        failed.append("factor_4_5_dti_qm_limit")

    # Factor 6: Residual income
    if residual_income < residual_threshold:
        failed.append("factor_6_residual_income")

    # Factor 7: No bankruptcy within 4 years
    if bk_within_4yr:
        failed.append("factor_7_bankruptcy")

    # Factor 8: PITI ≤31% of gross monthly income
    if monthly_income > 0 and (monthly_piti / monthly_income) > 0.31:
        failed.append("factor_8_piti_ratio")

    is_qm = len(failed) == 0
    return is_qm, failed


# ---------------------------------------------------------------------------
# LTV classification
# ---------------------------------------------------------------------------


def classify_ltv(ltv: float) -> str:
    """Classify LTV into tier string."""
    if ltv <= 0.80:
        return "preferred"
    if ltv <= 0.97:
        return "standard"
    return "high_ltv"


# ---------------------------------------------------------------------------
# Product routing
# ---------------------------------------------------------------------------


def route_mortgage_product(application: dict, policy_params: dict) -> str:
    """Determine the mortgage product type for this application.

    Returns one of: 'conforming', 'jumbo', 'FHA', 'VA', or 'DECLINE_JUMBO'.
    """
    p = policy_params or _DEFAULTS
    loan_amount    = float(application.get("loan_amount", 200_000))
    fico           = int(application.get("fico_score", 640))
    ltv            = float(application.get("ltv_at_origination", 0.80))
    va_eligible    = bool(application.get("va_eligible", False))
    conforming_lim = p.get("conforming_loan_limit", _DEFAULTS["conforming_loan_limit"])
    jumbo_floor    = p.get("fico_floor_jumbo",       _DEFAULTS["fico_floor_jumbo"])
    fha_floor      = p.get("fico_floor_fha",         _DEFAULTS["fico_floor_fha"])
    jumbo_enabled  = p.get("jumbo_enabled",           _DEFAULTS["jumbo_enabled"])

    # VA takes priority if eligible
    if va_eligible and fico >= 620:
        return "VA"

    # Conforming
    if loan_amount <= conforming_lim:
        return "conforming"

    # Jumbo
    if loan_amount > conforming_lim:
        if not jumbo_enabled:
            return "DECLINE_JUMBO_SUSPENDED"
        if fico >= jumbo_floor:
            return "jumbo"
        return "DECLINE_JUMBO_FICO"

    return "conforming"


# ---------------------------------------------------------------------------
# Property-type LTV overlay
# ---------------------------------------------------------------------------

_PROPERTY_MAX_LTV: dict[str, float] = {
    "primary_residence":  0.97,
    "second_home":        0.90,
    "investment_property": 0.75,
}


def _check_property_ltv(property_type: str, ltv: float) -> bool:
    """Return True if LTV is within the property-type overlay limit."""
    max_ltv = _PROPERTY_MAX_LTV.get(property_type.lower().strip(), 0.97)
    return ltv <= max_ltv


# ---------------------------------------------------------------------------
# Rate matrix
# ---------------------------------------------------------------------------

_SUPPORTED_RATE_TYPES = {"fixed_30", "fixed_15", "arm_5_1", "arm_7_1"}
_RATE_MIN = 3.00
_RATE_MAX = 14.99


def compute_mortgage_rate(
    rate_type: str,
    fico: int,
    ltv: float,
    product_type: str,
    points_paid: float,
    policy_params: dict | None = None,
) -> float:
    """Compute the mortgage note rate.

    Parameters
    ----------
    rate_type : str — one of {fixed_30, fixed_15, arm_5_1, arm_7_1}
    fico : int
    ltv : float
    product_type : str — one of {conforming, jumbo, FHA, VA}
    points_paid : float — discount points paid (max 3)
    policy_params : dict | None

    Returns
    -------
    float — note rate clipped to [3.00%, 14.99%]
    """
    p = policy_params or _DEFAULTS

    # Base rate from policy params
    rate_key = rate_type if rate_type in _SUPPORTED_RATE_TYPES else "fixed_30"
    base_rate = float(p.get(rate_key, _DEFAULTS.get(rate_key, 7.10)))

    # FICO adjustment: -(fico - 740) * 0.004 (discount below 740 = positive premium)
    fico_adj = -(fico - 740) * 0.004

    # LTV adjustment
    if ltv <= 0.80:
        ltv_adj = 0.0
    elif ltv <= 0.90:
        ltv_adj = 0.125
    else:
        ltv_adj = 0.25

    # Jumbo premium
    jumbo_premium = 0.375 if product_type.lower() == "jumbo" else 0.0

    # Points discount: -0.25% per point, max 3 points
    points_discount = -0.25 * min(float(points_paid), 3.0)

    rate = base_rate + fico_adj + ltv_adj + jumbo_premium + points_discount
    return float(np.clip(rate, _RATE_MIN, _RATE_MAX))


# ---------------------------------------------------------------------------
# Monthly payment (amortisation)
# ---------------------------------------------------------------------------


def _monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    if principal <= 0 or term_months <= 0:
        return 0.0
    r = annual_rate / 100.0 / 12.0
    if r == 0:
        return principal / term_months
    return float(principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1))


# ---------------------------------------------------------------------------
# FCRA code mapping
# ---------------------------------------------------------------------------

_DECLINE_TO_FCRA: dict[MortgageDeclineReason, str] = {
    MortgageDeclineReason.FICO_BELOW_MINIMUM:       "SHAP_CREDIT_SCORE",
    MortgageDeclineReason.DTI_EXCEED_QM:            "AA04",
    MortgageDeclineReason.LTV_EXCEEDS_LIMIT:        "AA05",
    MortgageDeclineReason.ATR_FAILED:               "AA01",
    MortgageDeclineReason.JUMBO_POLICY_SUSPENDED:   "AA05",
    MortgageDeclineReason.INSUFFICIENT_ASSETS:      "AA02",
    MortgageDeclineReason.PROPERTY_TYPE_INELIGIBLE: "AA05",
    MortgageDeclineReason.INCOME_UNVERIFIABLE:      "AA02",
}

_FCRA_SEVERITY: dict[str, int] = {
    "AA01": 9, "SHAP_CREDIT_SCORE": 8, "AA04": 7, "AA02": 6, "AA05": 2,
}


def _map_decline_to_fcra(reasons: list[MortgageDeclineReason]) -> list[str]:
    codes = [_DECLINE_TO_FCRA.get(r, "AA05") for r in reasons]
    seen: set[str] = set()
    unique: list[str] = []
    for c in sorted(codes, key=lambda x: -_FCRA_SEVERITY.get(x, 0)):
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique[:4]


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MortgageDecisionResult:
    decision:             MortgageDecision
    decline_reasons:      list[MortgageDeclineReason] = field(default_factory=list)
    fcra_reason_codes:    list[str]                   = field(default_factory=list)
    approved_amount:      Optional[float]             = None
    approved_rate:        Optional[float]             = None
    term_months:          Optional[int]               = None
    monthly_payment:      Optional[float]             = None
    apr:                  Optional[float]             = None
    verification_required: Optional[str]              = None
    fico_tier:            str                         = ""
    dti_tier:             str                         = ""
    policy_version_id:    Optional[int]               = None
    # Mortgage-specific
    is_qm:                bool                        = False
    pmi_required:         bool                        = False
    product_type:         str                         = ""
    rate_type:            str                         = "fixed_30"
    points_paid:          float                       = 0.0
    ltv_at_origination:   Optional[float]             = None
    property_type:        str                         = "primary_residence"
    atr_factors_passed:   list[str]                   = field(default_factory=list)
    atr_factors_failed:   list[str]                   = field(default_factory=list)


# ---------------------------------------------------------------------------
# FICO / DTI tier helpers
# ---------------------------------------------------------------------------

_ALL_ATR_FACTORS = [
    "factor_1_income_assets",
    "factor_2_employment",
    "factor_3_mortgage_payment_ratio",
    "factor_4_5_dti_qm_limit",
    "factor_6_residual_income",
    "factor_7_bankruptcy",
    "factor_8_piti_ratio",
]


def _fico_tier_mortgage(fico: int, params: dict) -> str:
    jumbo_floor = params.get("fico_floor_jumbo",      _DEFAULTS["fico_floor_jumbo"])
    conform_floor = params.get("fico_floor_conforming", _DEFAULTS["fico_floor_conforming"])
    fha_floor   = params.get("fico_floor_fha",        _DEFAULTS["fico_floor_fha"])

    if fico >= 760:
        return "super_prime"
    if fico >= 720:
        return "prime_plus"
    if fico >= 660:
        return "prime"
    if fico >= conform_floor:
        return "near_prime"
    if fico >= fha_floor:
        return "fha_eligible"
    return "sub_fha"


def _dti_tier_mortgage(dti: float, qm_limit: float) -> str:
    if dti <= 0.36:
        return "preferred"
    if dti <= qm_limit:
        return "qm"
    if dti <= 0.50:
        return "non_qm"
    return "exceed_max"


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


def evaluate_mortgage(
    application: dict,
    pd_score: float,
    fraud_score: float,
    policy_params: dict | None = None,
) -> MortgageDecisionResult:
    """Evaluate a single mortgage application.

    Parameters
    ----------
    application : dict
        Keys: fico_score, annual_income, monthly_income, dti, loan_amount,
              appraised_value, ltv_at_origination, property_type, occupancy_type,
              rate_type, points_paid, va_eligible, employment_status,
              assets_verified, residual_income, bankruptcy_within_4yrs,
              monthly_piti, family_size
    pd_score : float
    fraud_score : float
    policy_params : dict | None

    Returns
    -------
    MortgageDecisionResult
    """
    p = policy_params or _DEFAULTS

    fico          = int(application.get("fico_score", 640))
    income_annual = float(application.get("annual_income", 80_000))
    monthly_inc   = float(application.get("monthly_income", income_annual / 12))
    dti           = float(application.get("dti", 0.38))
    loan_amount   = float(application.get("loan_amount", 300_000))
    appraised     = float(application.get("appraised_value", loan_amount / 0.80))
    ltv           = float(application.get("ltv_at_origination", loan_amount / max(appraised, 1)))
    prop_type     = str(application.get("property_type", "primary_residence")).lower().strip()
    rate_type     = str(application.get("rate_type", "fixed_30")).lower()
    points        = float(application.get("points_paid", 0.0))
    version_id    = application.get("policy_version_id", None)

    max_dti_qm     = p.get("max_dti_qm",            _DEFAULTS["max_dti_qm"])
    fha_floor      = p.get("fico_floor_fha",         _DEFAULTS["fico_floor_fha"])
    conform_floor  = p.get("fico_floor_conforming",  _DEFAULTS["fico_floor_conforming"])
    fraud_thresh   = p.get("fraud_reject_threshold", _DEFAULTS["fraud_reject_threshold"])
    pd_hard        = p.get("pd_hard_cutoff",         _DEFAULTS["pd_hard_cutoff"])
    pd_review      = p.get("pd_review_cutoff",       _DEFAULTS["pd_review_cutoff"])

    fico_tier = _fico_tier_mortgage(fico, p)
    dti_tier  = _dti_tier_mortgage(dti, max_dti_qm)
    reasons:  list[MortgageDeclineReason] = []

    # ── Hard decline gates ─────────────────────────────────────────────────

    if fraud_score >= fraud_thresh:
        reasons.append(MortgageDeclineReason.ATR_FAILED)

    if pd_score >= pd_hard:
        reasons.append(MortgageDeclineReason.ATR_FAILED)

    # Product routing
    product_type = route_mortgage_product(application, p)

    if product_type in ("DECLINE_JUMBO_SUSPENDED",):
        reasons.append(MortgageDeclineReason.JUMBO_POLICY_SUSPENDED)
    elif product_type in ("DECLINE_JUMBO_FICO",):
        reasons.append(MortgageDeclineReason.FICO_BELOW_MINIMUM)

    # FICO floor check for conforming / FHA
    if product_type == "conforming" and fico < conform_floor:
        if fico >= fha_floor:
            # Can refer to FHA
            return MortgageDecisionResult(
                decision=MortgageDecision.REFER_FHA,
                decline_reasons=[MortgageDeclineReason.FICO_BELOW_MINIMUM],
                fcra_reason_codes=["SHAP_CREDIT_SCORE"],
                fico_tier=fico_tier,
                dti_tier=dti_tier,
                product_type="FHA",
                policy_version_id=version_id,
                ltv_at_origination=ltv,
                property_type=prop_type,
                rate_type=rate_type,
            )
        reasons.append(MortgageDeclineReason.FICO_BELOW_MINIMUM)

    # DTI hard decline (>50%)
    if dti > 0.50:
        reasons.append(MortgageDeclineReason.DTI_EXCEED_QM)

    # LTV property-type overlay
    if not _check_property_ltv(prop_type, ltv):
        reasons.append(MortgageDeclineReason.LTV_EXCEEDS_LIMIT)

    # LTV hard limit (>97% for conventional)
    ltv_tier = classify_ltv(ltv)
    if ltv_tier == "high_ltv" and product_type not in ("FHA", "VA"):
        reasons.append(MortgageDeclineReason.LTV_EXCEEDS_LIMIT)

    if reasons:
        return MortgageDecisionResult(
            decision=MortgageDecision.DECLINE,
            decline_reasons=reasons,
            fcra_reason_codes=_map_decline_to_fcra(reasons),
            fico_tier=fico_tier,
            dti_tier=dti_tier,
            product_type=product_type if "DECLINE" not in product_type else "",
            policy_version_id=version_id,
            ltv_at_origination=ltv,
            property_type=prop_type,
            rate_type=rate_type,
        )

    # ── ATR / QM check ─────────────────────────────────────────────────────

    # Compute monthly mortgage payment for ATR
    rate = compute_mortgage_rate(rate_type, fico, ltv, product_type, points, p)
    term_months = 360 if "30" in rate_type or "arm" in rate_type else 180  # 30yr or 15yr
    monthly_pmt = _monthly_payment(loan_amount, rate, term_months)

    # Enrich application with derived ATR fields
    atr_app = {**application}
    atr_app.setdefault("monthly_income", monthly_inc)
    atr_app.setdefault("monthly_mortgage_payment", monthly_pmt)
    atr_app.setdefault("monthly_piti", monthly_pmt * 1.20)  # rough PITI add 20%
    atr_app.setdefault("residual_income", monthly_inc * (1 - dti))

    is_qm, atr_failed = check_atr(atr_app)
    atr_passed = [f for f in _ALL_ATR_FACTORS if f not in atr_failed]

    # Near-prime / near-DTI → manual review
    if fico < conform_floor + 20 or (max_dti_qm - 0.02 < dti <= max_dti_qm) or pd_score >= pd_review:
        return MortgageDecisionResult(
            decision=MortgageDecision.MANUAL_REVIEW,
            decline_reasons=[],
            fcra_reason_codes=["AA05"],
            approved_amount=loan_amount,
            approved_rate=rate,
            term_months=term_months,
            monthly_payment=round(monthly_pmt, 2),
            apr=rate,
            fico_tier=fico_tier,
            dti_tier=dti_tier,
            policy_version_id=version_id,
            is_qm=is_qm,
            pmi_required=(ltv > 0.80),
            product_type=product_type,
            rate_type=rate_type,
            points_paid=points,
            ltv_at_origination=ltv,
            property_type=prop_type,
            atr_factors_passed=atr_passed,
            atr_factors_failed=atr_failed,
        )

    # QM vs Non-QM
    if atr_failed:
        decision = MortgageDecision.APPROVE_NON_QM
    else:
        decision = MortgageDecision.APPROVE_QM

    return MortgageDecisionResult(
        decision=decision,
        decline_reasons=[],
        fcra_reason_codes=[],
        approved_amount=loan_amount,
        approved_rate=rate,
        term_months=term_months,
        monthly_payment=round(monthly_pmt, 2),
        apr=rate,
        fico_tier=fico_tier,
        dti_tier=dti_tier,
        policy_version_id=version_id,
        is_qm=is_qm,
        pmi_required=(ltv > 0.80),
        product_type=product_type,
        rate_type=rate_type,
        points_paid=points,
        ltv_at_origination=ltv,
        property_type=prop_type,
        atr_factors_passed=atr_passed,
        atr_factors_failed=atr_failed,
    )


# ---------------------------------------------------------------------------
# Vectorised batch evaluation
# ---------------------------------------------------------------------------


def evaluate_batch(df: pd.DataFrame, policy_params: dict | None = None) -> pd.DataFrame:
    """Vectorised batch evaluation of mortgage applications.

    Parameters
    ----------
    df : pd.DataFrame
    policy_params : dict | None

    Returns
    -------
    pd.DataFrame — original columns + decision columns
    """
    p = policy_params or _DEFAULTS
    n = len(df)
    if n == 0:
        return df.copy()

    def _safe(col: str, default, dtype=None):
        if col in df.columns:
            s = df[col]
            return s.astype(dtype) if dtype else s
        return pd.Series([default] * n, index=df.index)

    fico        = _safe("fico_score",           640,    int)
    income_ann  = _safe("annual_income",        80_000, float)
    monthly_inc = income_ann / 12.0
    dti         = _safe("dti",                  0.38,   float)
    loan_amount = _safe("loan_amount",          300_000, float)
    appraised   = _safe("appraised_value",      loan_amount / 0.80, float)
    ltv         = _safe("ltv_at_origination",   loan_amount / appraised.clip(lower=1), float)
    prop_type   = _safe("property_type",        "primary_residence", str)
    rate_type   = _safe("rate_type",            "fixed_30", str)
    points      = _safe("points_paid",          0.0,    float)
    va_elig     = _safe("va_eligible",          False,  bool)
    pd_score    = _safe("pd_score",             0.03,   float)
    fraud_sc    = _safe("fraud_score",          0.01,   float)

    max_dti_qm     = p.get("max_dti_qm",            _DEFAULTS["max_dti_qm"])
    fha_floor      = p.get("fico_floor_fha",         _DEFAULTS["fico_floor_fha"])
    conform_floor  = p.get("fico_floor_conforming",  _DEFAULTS["fico_floor_conforming"])
    jumbo_floor    = p.get("fico_floor_jumbo",       _DEFAULTS["fico_floor_jumbo"])
    conform_limit  = p.get("conforming_loan_limit",  _DEFAULTS["conforming_loan_limit"])
    jumbo_enabled  = p.get("jumbo_enabled",           _DEFAULTS["jumbo_enabled"])
    fraud_thresh   = p.get("fraud_reject_threshold", _DEFAULTS["fraud_reject_threshold"])
    pd_hard        = p.get("pd_hard_cutoff",         _DEFAULTS["pd_hard_cutoff"])
    pd_review_t    = p.get("pd_review_cutoff",       _DEFAULTS["pd_review_cutoff"])

    base_rate = float(p.get("fixed_30", _DEFAULTS["fixed_30"]))

    # Product type (simplified vectorised routing)
    product_type = pd.Series("conforming", index=df.index, dtype=str)
    product_type[va_elig & (fico >= 620)]                         = "VA"
    product_type[
        (~(va_elig & (fico >= 620))) &
        (loan_amount > conform_limit) & jumbo_enabled & (fico >= jumbo_floor)
    ] = "jumbo"
    product_type[
        (~(va_elig & (fico >= 620))) &
        (loan_amount > conform_limit) & (~jumbo_enabled)
    ] = "DECLINE_JUMBO"
    product_type[
        (~(va_elig & (fico >= 620))) &
        (loan_amount > conform_limit) & jumbo_enabled & (fico < jumbo_floor)
    ] = "DECLINE_JUMBO"

    # LTV tier
    ltv_tier = pd.Series("preferred", index=df.index, dtype=str)
    ltv_tier[ltv > 0.97] = "high_ltv"
    ltv_tier[(ltv > 0.80) & (ltv <= 0.97)] = "standard"

    # Property LTV max
    prop_max_ltv = prop_type.map(_PROPERTY_MAX_LTV).fillna(0.97)
    ltv_violation = ltv > prop_max_ltv

    # Hard decline mask
    hard_decline = (
        (fraud_sc >= fraud_thresh) |
        (pd_score >= pd_hard) |
        product_type.str.startswith("DECLINE") |
        ((product_type == "conforming") & (fico < conform_floor) & (fico < fha_floor)) |
        (dti > 0.50) |
        ltv_violation |
        ((ltv_tier == "high_ltv") & ~product_type.isin(["FHA", "VA"]))
    )

    # FHA referral
    refer_fha = (
        ~hard_decline &
        (product_type == "conforming") &
        (fico < conform_floor) & (fico >= fha_floor)
    )

    # Manual review
    manual_review = (
        ~hard_decline & ~refer_fha & (
            (fico < conform_floor + 20) |
            ((dti > max_dti_qm - 0.02) & (dti <= max_dti_qm)) |
            (pd_score >= pd_review_t)
        )
    )

    approved_mask = ~hard_decline & ~refer_fha & ~manual_review

    # Rate (vectorised)
    fico_adj = -(fico - 740) * 0.004
    ltv_adj  = pd.Series(0.0, index=df.index)
    ltv_adj[ltv > 0.90] = 0.25
    ltv_adj[(ltv > 0.80) & (ltv <= 0.90)] = 0.125
    jumbo_prem = (product_type == "jumbo").astype(float) * 0.375
    pts_disc   = -0.25 * points.clip(upper=3.0)
    rate_v     = np.clip(base_rate + fico_adj + ltv_adj + jumbo_prem + pts_disc, _RATE_MIN, _RATE_MAX)

    # Term
    term_v = np.where(rate_type.str.contains("15"), 180, 360)

    # Monthly payment
    r_monthly = rate_v / 100.0 / 12.0
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_v = np.where(
            r_monthly == 0,
            loan_amount / term_v,
            loan_amount * r_monthly * (1 + r_monthly) ** term_v /
            ((1 + r_monthly) ** term_v - 1),
        )

    # is_qm: simplified — true when dti <= max_dti_qm and not bankrupt
    bk_4yr = _safe("bankruptcy_within_4yrs", False, bool)
    is_qm_v = (dti <= max_dti_qm) & (~bk_4yr)

    # Decision outcome
    decision_outcome = pd.Series("APPROVE_QM", index=df.index, dtype=str)
    decision_outcome[approved_mask & ~is_qm_v] = "APPROVE_NON_QM"
    decision_outcome[manual_review]  = "MANUAL_REVIEW"
    decision_outcome[refer_fha]      = "REFER_FHA"
    decision_outcome[hard_decline]   = "DECLINE"

    out = df.copy()
    out["decision_outcome"]   = decision_outcome
    out["product_type"]       = product_type
    out["fico_tier"]          = fico.map(lambda f: _fico_tier_mortgage(f, p))
    out["dti_tier"]           = dti.map(lambda d: _dti_tier_mortgage(d, max_dti_qm))
    out["ltv_tier"]           = ltv_tier
    out["is_qm"]              = is_qm_v
    out["pmi_required"]       = ltv > 0.80
    out["approved_amount"]    = np.where(approved_mask | manual_review, loan_amount, np.nan)
    out["approved_rate"]      = np.where(approved_mask | manual_review, rate_v, np.nan)
    out["term_months_out"]    = np.where(approved_mask | manual_review, term_v, np.nan)
    out["monthly_payment"]    = np.where(approved_mask | manual_review, np.round(payment_v, 2), np.nan)
    out["apr"]                = np.where(approved_mask | manual_review, rate_v, np.nan)
    out["atr_factors_failed"] = np.where(~is_qm_v, '["factor_4_5_dti_qm_limit"]', "[]")

    return out


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------


def _demo(n: int = 10) -> None:
    """Run a demo evaluation on n random mortgage applications."""
    rng = np.random.default_rng(42)

    apps = pd.DataFrame({
        "fico_score":          rng.integers(560, 820, n),
        "annual_income":       rng.uniform(50_000, 250_000, n),
        "dti":                 rng.uniform(0.20, 0.55, n),
        "loan_amount":         rng.uniform(150_000, 1_200_000, n),
        "appraised_value":     rng.uniform(200_000, 1_500_000, n),
        "ltv_at_origination":  rng.uniform(0.60, 0.99, n),
        "property_type":       rng.choice(["primary_residence", "second_home", "investment_property"], n,
                                          p=[0.72, 0.18, 0.10]),
        "rate_type":           rng.choice(["fixed_30", "fixed_15", "arm_5_1", "arm_7_1"], n,
                                          p=[0.60, 0.15, 0.15, 0.10]),
        "points_paid":         rng.uniform(0, 3, n),
        "va_eligible":         rng.random(n) < 0.08,
        "pd_score":            rng.beta(1, 20, n),
        "fraud_score":         rng.beta(1, 60, n),
        "bankruptcy_within_4yrs": rng.random(n) < 0.02,
        "employment_status":   rng.choice(["employed", "self_employed", "retired"], n, p=[0.80, 0.15, 0.05]),
    })

    log.info("── Mortgage Batch Demo (%d applications) ──", n)
    results = evaluate_batch(apps)
    summary = results["decision_outcome"].value_counts()
    print("\nDecision summary:")
    print(summary.to_string())
    print("\nSample results:")
    cols = ["fico_score", "dti", "loan_amount", "decision_outcome",
            "is_qm", "product_type", "approved_rate", "pmi_required"]
    print(results[cols].head(n).to_string(index=False))

    # Single-row demo
    sample = {
        "fico_score": 720, "annual_income": 120_000, "monthly_income": 10_000,
        "dti": 0.35, "loan_amount": 450_000, "appraised_value": 550_000,
        "ltv_at_origination": 0.818, "property_type": "primary_residence",
        "rate_type": "fixed_30", "points_paid": 1.0, "va_eligible": False,
        "employment_status": "employed", "assets_verified": True,
        "bankruptcy_within_4yrs": False, "family_size": 2,
    }
    r = evaluate_mortgage(sample, pd_score=0.025, fraud_score=0.01)
    print(f"\nSingle-app: {r.decision.value} | product={r.product_type} | "
          f"rate={r.approved_rate:.3f}% | is_qm={r.is_qm} | pmi={r.pmi_required}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mortgage Origination Policy Engine")
    parser.add_argument("--demo", type=int, default=10, metavar="N",
                        help="Run demo on N random applications (default: 10)")
    args = parser.parse_args()
    _demo(args.demo)
