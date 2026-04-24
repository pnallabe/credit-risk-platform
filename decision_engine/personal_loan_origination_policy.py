"""
decision_engine/personal_loan_origination_policy.py
=====================================================
Tiered underwriting engine for personal loans (unsecured installment).

Framework
---------
  1. Hard declines  — absolute FICO / fraud / regulatory exclusions
  2. Soft declines  — risk appetite gates (DTI, PD, derogatories)
  3. Manual review  — borderline population (580–619 FICO band)
  4. Counter-offer  — lower amount or higher rate
  5. Auto-approve   — prime / prime-plus approval with pricing

FICO Tier Logic
---------------
  ≤579           → Hard decline (FICO_BELOW_MINIMUM)
  580–619        → Soft decline / manual review (PD-gated)
  620–659        → Near-prime: auto-approve at standard terms
  660–719        → Prime: auto-approve
  720+           → Prime-plus: preferred rate

DTI Tiers
---------
  ≤36%           → preferred
  36–50%         → standard
  >50%           → decline (DTI_EXCEED_MAX)

Usage
-----
    python decision_engine/personal_loan_origination_policy.py --demo 20
"""
from __future__ import annotations

import argparse
import logging
import math
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


class PLDecision(str, Enum):
    APPROVE       = "APPROVE"
    DECLINE       = "DECLINE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    COUNTER_OFFER = "COUNTER_OFFER"   # lower amount / higher rate


class PLDeclineReason(str, Enum):
    FICO_BELOW_MINIMUM      = "FICO_BELOW_MINIMUM"
    DTI_EXCEED_MAX          = "DTI_EXCEED_MAX"
    INCOME_INSUFFICIENT     = "INCOME_INSUFFICIENT"
    PD_ABOVE_CUTOFF         = "PD_ABOVE_CUTOFF"
    FRAUD_INDICATOR         = "FRAUD_INDICATOR"
    DEROGATORY_EXCESS       = "DEROGATORY_EXCESS"
    EMPLOYMENT_RISK         = "EMPLOYMENT_RISK"
    LOAN_PURPOSE_RESTRICTED = "LOAN_PURPOSE_RESTRICTED"
    AMOUNT_EXCEEDS_POLICY   = "AMOUNT_EXCEEDS_POLICY"


# ---------------------------------------------------------------------------
# Module-level default policy parameters (overridable via policy_params)
# ---------------------------------------------------------------------------

_DEFAULTS: dict = {
    "fico_floor_hard_decline": 580,
    "fico_floor_soft_decline": 600,   # soft_decline = hard + 20
    "fico_floor_near_prime":   620,   # near_prime   = hard + 40
    "max_dti_preferred":       0.36,
    "max_dti_standard":        0.50,
    "max_loan_amount":         50_000,
    "base_rate":               11.99,
    # Fraud and PD thresholds
    "fraud_reject_threshold":  0.65,
    "pd_hard_cutoff":          0.18,
    "pd_soft_cutoff":          0.12,
    # Income guardrail
    "min_annual_income":       12_000,
    # Derogatory max
    "max_derog_marks":         5,
}


# ---------------------------------------------------------------------------
# FICO tier helper
# ---------------------------------------------------------------------------


def _fico_tier(fico: int, params: dict) -> str:
    """Classify FICO score into tier string."""
    hard    = params.get("fico_floor_hard_decline", _DEFAULTS["fico_floor_hard_decline"])
    soft    = params.get("fico_floor_soft_decline", _DEFAULTS["fico_floor_soft_decline"])
    near    = params.get("fico_floor_near_prime",   _DEFAULTS["fico_floor_near_prime"])
    if fico >= 720:
        return "prime_plus"
    if fico >= 660:
        return "prime"
    if fico >= near:
        return "near_prime"
    if fico >= soft:
        return "soft_decline"
    if fico >= hard:
        return "hard_decline_zone"
    return "hard_decline"


def _dti_tier(dti: float, params: dict) -> str:
    """Classify DTI into tier string."""
    preferred = params.get("max_dti_preferred", _DEFAULTS["max_dti_preferred"])
    standard  = params.get("max_dti_standard",  _DEFAULTS["max_dti_standard"])
    if dti <= preferred:
        return "preferred"
    if dti <= standard:
        return "standard"
    return "exceed_max"


# ---------------------------------------------------------------------------
# Income verification threshold
# ---------------------------------------------------------------------------


def _income_verification(annual_income: float) -> str | None:
    """Return required verification document type based on income band."""
    if annual_income < 1_000:
        return None
    if annual_income <= 15_000:
        return "bank_statement"
    if annual_income <= 50_000:
        return "paystub"
    return "tax_return"


# ---------------------------------------------------------------------------
# Pricing matrix
# ---------------------------------------------------------------------------

_GRADE_SPREAD = {
    "prime_plus": -1.50,
    "prime":       0.00,
    "near_prime": +3.50,
}

_TERM_SPREAD = {
    24:  -0.25,
    36:   0.00,
    48:  +0.50,
    60:  +1.00,
    72:  +1.75,
}

_PURPOSE_SPREAD = {
    "debt_consolidation": +0.25,
    "medical":            -0.25,
    "home_improvement":   -0.50,
    "other":               0.00,
}

_RATE_MIN = 5.99
_RATE_MAX = 36.00


def compute_pl_rate(
    fico: int,
    dti: float,
    term_months: int,
    purpose: str,
    params: dict | None = None,
) -> float:
    """Compute the personal loan APR based on risk and product attributes.

    Parameters
    ----------
    fico : int
    dti  : float
    term_months : int — one of {24, 36, 48, 60, 72}
    purpose : str — one of {debt_consolidation, medical, home_improvement, other}
    params : dict | None — policy version parameters

    Returns
    -------
    float — APR clipped to [5.99%, 36.00%]
    """
    p = params or _DEFAULTS
    base_rate = p.get("base_rate", _DEFAULTS["base_rate"])
    tier = _fico_tier(fico, p)

    # Grade spread (use prime for tiers outside the matrix)
    grade_spread = _GRADE_SPREAD.get(tier, 0.0)

    # Term spread — nearest supported term
    supported_terms = list(_TERM_SPREAD.keys())
    nearest_term = min(supported_terms, key=lambda t: abs(t - term_months))
    term_spread = _TERM_SPREAD[nearest_term]

    # Purpose spread
    purpose_key = str(purpose).lower().strip().replace("-", "_").replace(" ", "_")
    purpose_spread = _PURPOSE_SPREAD.get(purpose_key, _PURPOSE_SPREAD["other"])

    rate = base_rate + grade_spread + term_spread + purpose_spread
    return float(np.clip(rate, _RATE_MIN, _RATE_MAX))


# ---------------------------------------------------------------------------
# Approved amount calculator
# ---------------------------------------------------------------------------

_SCORE_BASED_MAX = {
    "prime_plus": 100_000,
    "prime":       50_000,
    "near_prime":  25_000,
}


def _compute_approved_amount(
    requested: float,
    annual_income: float,
    fico: int,
    term_months: int,
    params: dict,
) -> float:
    """Compute approved loan amount (minimum of requested vs. income/score caps)."""
    tier = _fico_tier(fico, params)
    max_policy = params.get("max_loan_amount", _DEFAULTS["max_loan_amount"])

    # Income-based max: annual_income * 0.45 / 12 * term_months * 0.50
    income_based_max = annual_income * 0.45 / 12.0 * term_months * 0.50

    # Score-based max by tier
    score_based_max = float(_SCORE_BASED_MAX.get(tier, 15_000))

    cap = min(max(income_based_max, score_based_max), max_policy)
    return round(float(min(requested, cap)), 2)


# ---------------------------------------------------------------------------
# Monthly payment calculator
# ---------------------------------------------------------------------------


def _monthly_payment(principal: float, annual_rate: float, term_months: int) -> float:
    """Standard amortisation monthly payment."""
    if principal <= 0 or term_months <= 0:
        return 0.0
    r = annual_rate / 100.0 / 12.0
    if r == 0:
        return principal / term_months
    return float(principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1))


# ---------------------------------------------------------------------------
# FCRA adverse action code mapping
# ---------------------------------------------------------------------------

_DECLINE_TO_FCRA: dict[PLDeclineReason, str] = {
    PLDeclineReason.FICO_BELOW_MINIMUM:      "SHAP_CREDIT_SCORE",
    PLDeclineReason.DTI_EXCEED_MAX:          "AA04",
    PLDeclineReason.INCOME_INSUFFICIENT:     "SHAP_INCOME",
    PLDeclineReason.PD_ABOVE_CUTOFF:         "AA01",
    PLDeclineReason.FRAUD_INDICATOR:         "COMP_FRAUD",
    PLDeclineReason.DEROGATORY_EXCESS:       "SHAP_NUM_DEROG",
    PLDeclineReason.EMPLOYMENT_RISK:         "SHAP_EMPLOYMENT",
    PLDeclineReason.LOAN_PURPOSE_RESTRICTED: "AA05",
    PLDeclineReason.AMOUNT_EXCEEDS_POLICY:   "AA05",
}

_FCRA_SEVERITY: dict[str, int] = {
    "COMP_FRAUD":         10,
    "AA01":               9,
    "SHAP_CREDIT_SCORE":  8,
    "AA04":               7,
    "SHAP_DTI":           6,
    "SHAP_INCOME":        5,
    "SHAP_NUM_DEROG":     4,
    "SHAP_EMPLOYMENT":    3,
    "AA05":               2,
    "AA02":               1,
    "AA03":               1,
}


def _map_decline_to_fcra(reasons: list[PLDeclineReason]) -> list[str]:
    """Map decline reasons to FCRA codes, return top-4 sorted by severity."""
    codes = [_DECLINE_TO_FCRA.get(r, "AA05") for r in reasons]
    # Deduplicate preserving severity order
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
class PLDecisionResult:
    decision:            PLDecision
    decline_reasons:     list[PLDeclineReason] = field(default_factory=list)
    fcra_reason_codes:   list[str]             = field(default_factory=list)
    approved_amount:     Optional[float]       = None
    approved_rate:       Optional[float]       = None
    term_months:         Optional[int]         = None
    monthly_payment:     Optional[float]       = None
    apr:                 Optional[float]       = None
    verification_required: Optional[str]      = None
    fico_tier:           str                   = ""
    dti_tier:            str                   = ""
    policy_version_id:   Optional[int]         = None


# ---------------------------------------------------------------------------
# Core evaluation function
# ---------------------------------------------------------------------------


def evaluate_personal_loan(
    application: dict,
    pd_score: float,
    fraud_score: float,
    policy_params: dict | None = None,
) -> PLDecisionResult:
    """Evaluate a single personal loan application against the policy stack.

    Parameters
    ----------
    application : dict
        Keys: fico_score, annual_income, dti, num_derog_marks, employment_status,
              requested_amount, term_months, loan_purpose
    pd_score : float
        Probability of default from the PD model (0–1).
    fraud_score : float
        Fraud probability score (0–1).
    policy_params : dict | None
        Parameters from PolicyVersionStore.get_as_of(). Falls back to module defaults.

    Returns
    -------
    PLDecisionResult
    """
    p = policy_params or _DEFAULTS

    fico        = int(application.get("fico_score", 620))
    income      = float(application.get("annual_income", 30_000))
    dti         = float(application.get("dti", 0.35))
    derog       = int(application.get("num_derog_marks", 0))
    emp_status  = str(application.get("employment_status", "employed")).lower()
    requested   = float(application.get("requested_amount", 10_000))
    term        = int(application.get("term_months", 36))
    purpose     = str(application.get("loan_purpose", "other")).lower()
    version_id  = application.get("policy_version_id", None)

    # Enforce supported term lengths
    supported_terms = [24, 36, 48, 60, 72]
    if term not in supported_terms:
        term = min(supported_terms, key=lambda t: abs(t - term))

    tier     = _fico_tier(fico, p)
    dti_tier = _dti_tier(dti, p)
    reasons: list[PLDeclineReason] = []

    # ── Hard / fraud gates ────────────────────────────────────────────────

    fraud_reject  = p.get("fraud_reject_threshold", _DEFAULTS["fraud_reject_threshold"])
    if fraud_score >= fraud_reject:
        reasons.append(PLDeclineReason.FRAUD_INDICATOR)

    hard_floor = p.get("fico_floor_hard_decline", _DEFAULTS["fico_floor_hard_decline"])
    if fico < hard_floor:
        reasons.append(PLDeclineReason.FICO_BELOW_MINIMUM)

    min_income = p.get("min_annual_income", _DEFAULTS["min_annual_income"])
    if income < min_income:
        reasons.append(PLDeclineReason.INCOME_INSUFFICIENT)

    max_derog = p.get("max_derog_marks", _DEFAULTS["max_derog_marks"])
    if derog > max_derog:
        reasons.append(PLDeclineReason.DEROGATORY_EXCESS)

    max_dti_std = p.get("max_dti_standard", _DEFAULTS["max_dti_standard"])
    if dti > max_dti_std:
        reasons.append(PLDeclineReason.DTI_EXCEED_MAX)

    if emp_status in ("unemployed",):
        reasons.append(PLDeclineReason.EMPLOYMENT_RISK)

    pd_hard = p.get("pd_hard_cutoff", _DEFAULTS["pd_hard_cutoff"])
    if pd_score >= pd_hard:
        reasons.append(PLDeclineReason.PD_ABOVE_CUTOFF)

    max_loan = p.get("max_loan_amount", _DEFAULTS["max_loan_amount"])
    if requested > max_loan:
        reasons.append(PLDeclineReason.AMOUNT_EXCEEDS_POLICY)

    # Hard decline
    if reasons:
        return PLDecisionResult(
            decision=PLDecision.DECLINE,
            decline_reasons=reasons,
            fcra_reason_codes=_map_decline_to_fcra(reasons),
            verification_required=_income_verification(income),
            fico_tier=tier,
            dti_tier=dti_tier,
            policy_version_id=version_id,
        )

    # ── Soft decline / manual review (580–619 band) ───────────────────────

    soft_floor = p.get("fico_floor_soft_decline", _DEFAULTS["fico_floor_soft_decline"])
    pd_soft    = p.get("pd_soft_cutoff", _DEFAULTS["pd_soft_cutoff"])

    if tier in ("soft_decline", "hard_decline_zone") or (fico < soft_floor + 20 and pd_score >= pd_soft):
        # Bump to MANUAL_REVIEW — underwriter will decide
        return PLDecisionResult(
            decision=PLDecision.MANUAL_REVIEW,
            decline_reasons=[],
            fcra_reason_codes=["AA05"],
            verification_required=_income_verification(income),
            fico_tier=tier,
            dti_tier=dti_tier,
            policy_version_id=version_id,
        )

    # ── Approved ─────────────────────────────────────────────────────────

    approved_amount = _compute_approved_amount(requested, income, fico, term, p)
    # Counter-offer if capped below requested
    decision = PLDecision.COUNTER_OFFER if approved_amount < requested * 0.95 else PLDecision.APPROVE

    rate = compute_pl_rate(fico, dti, term, purpose, p)
    payment = _monthly_payment(approved_amount, rate, term)

    return PLDecisionResult(
        decision=decision,
        decline_reasons=[],
        fcra_reason_codes=[],
        approved_amount=approved_amount,
        approved_rate=rate,
        term_months=term,
        monthly_payment=round(payment, 2),
        apr=rate,   # simplified — full APR includes fees; same here
        verification_required=_income_verification(income),
        fico_tier=tier,
        dti_tier=dti_tier,
        policy_version_id=version_id,
    )


# ---------------------------------------------------------------------------
# Vectorised batch evaluation
# ---------------------------------------------------------------------------

def evaluate_batch(df: pd.DataFrame, policy_params: dict | None = None) -> pd.DataFrame:
    """Vectorised batch evaluation of personal loan applications.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns matching the ``evaluate_personal_loan`` application dict.
    policy_params : dict | None
        Policy parameters to use for the entire batch (epoch-level call).

    Returns
    -------
    pd.DataFrame
        Original DataFrame with added decision columns.
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

    fico      = _safe("fico_score",     620,  int)
    income    = _safe("annual_income",  30_000, float)
    dti       = _safe("dti",            0.35, float)
    derog     = _safe("num_derog_marks", 0,   int)
    emp       = _safe("employment_status", "employed", str)
    requested = _safe("requested_amount", 10_000, float)
    term      = _safe("term_months",    36,   int)
    purpose   = _safe("loan_purpose",   "other", str)
    pd_score  = _safe("pd_score",       0.05, float)
    fraud_sc  = _safe("fraud_score",    0.01, float)

    # Parameter scalars
    hard_floor    = p.get("fico_floor_hard_decline", _DEFAULTS["fico_floor_hard_decline"])
    soft_floor    = p.get("fico_floor_soft_decline", _DEFAULTS["fico_floor_soft_decline"])
    near_floor    = p.get("fico_floor_near_prime",   _DEFAULTS["fico_floor_near_prime"])
    max_dti_std   = p.get("max_dti_standard",        _DEFAULTS["max_dti_standard"])
    max_dti_pref  = p.get("max_dti_preferred",       _DEFAULTS["max_dti_preferred"])
    fraud_thresh  = p.get("fraud_reject_threshold",  _DEFAULTS["fraud_reject_threshold"])
    pd_hard       = p.get("pd_hard_cutoff",          _DEFAULTS["pd_hard_cutoff"])
    pd_soft       = p.get("pd_soft_cutoff",          _DEFAULTS["pd_soft_cutoff"])
    max_derog     = p.get("max_derog_marks",         _DEFAULTS["max_derog_marks"])
    min_income    = p.get("min_annual_income",       _DEFAULTS["min_annual_income"])
    max_loan      = p.get("max_loan_amount",         _DEFAULTS["max_loan_amount"])
    base_rate     = p.get("base_rate",               _DEFAULTS["base_rate"])

    # FICO tier (vectorised)
    fico_tier = pd.Series("prime", index=df.index, dtype=str)
    fico_tier = fico_tier.where(fico >= 720, "prime")
    fico_tier[fico >= 720] = "prime_plus"
    fico_tier[fico < 720]  = "prime"
    fico_tier[fico < 660]  = "near_prime"
    fico_tier[fico < near_floor]  = "soft_decline"
    fico_tier[fico < soft_floor]  = "hard_decline_zone"
    fico_tier[fico < hard_floor]  = "hard_decline"

    # DTI tier (vectorised)
    dti_tier = pd.Series("exceed_max", index=df.index, dtype=str)
    dti_tier[dti <= max_dti_std]  = "standard"
    dti_tier[dti <= max_dti_pref] = "preferred"

    # Decline flags (vectorised)
    hard_decline = (
        (fraud_sc >= fraud_thresh) |
        (fico < hard_floor) |
        (income < min_income) |
        (derog > max_derog) |
        (dti > max_dti_std) |
        (emp.str.lower() == "unemployed") |
        (pd_score >= pd_hard) |
        (requested > max_loan)
    )

    soft_review = (~hard_decline) & (
        (fico < soft_floor + 20) | (pd_score >= pd_soft)
    ) & (fico >= hard_floor)

    # For approved rows: compute amount, rate, payment
    approved_mask = ~hard_decline & ~soft_review

    # Approved amount (vectorised)
    income_max = income * 0.45 / 12.0 * term * 0.50
    score_max = fico_tier.map({"prime_plus": 100_000, "prime": 50_000, "near_prime": 25_000}).fillna(15_000)
    cap = np.minimum(np.maximum(income_max, score_max), max_loan)
    approved_amount = np.minimum(requested, cap)

    # Rate (vectorised approximation using base_rate + spreads)
    grade_spread_v = fico_tier.map(_GRADE_SPREAD).fillna(0.0)
    nearest_term_v = term.map(lambda t: min(_TERM_SPREAD.keys(), key=lambda x: abs(x - t)))
    term_spread_v  = nearest_term_v.map(_TERM_SPREAD).fillna(0.0)
    purpose_clean  = purpose.str.lower().str.strip().str.replace("-", "_").str.replace(" ", "_")
    purpose_spread_v = purpose_clean.map(_PURPOSE_SPREAD).fillna(0.0)
    rate_v = np.clip(base_rate + grade_spread_v + term_spread_v + purpose_spread_v, _RATE_MIN, _RATE_MAX)

    # Monthly payment (vectorised using numpy)
    r_monthly = rate_v / 100.0 / 12.0
    # Avoid division by zero for r=0
    with np.errstate(divide="ignore", invalid="ignore"):
        payment_v = np.where(
            r_monthly == 0,
            approved_amount / term,
            approved_amount * r_monthly * (1 + r_monthly) ** term / ((1 + r_monthly) ** term - 1),
        )

    # Compose output columns
    out = df.copy()
    out["fico_tier"]    = fico_tier
    out["dti_tier"]     = dti_tier
    out["verification_required"] = income.map(_income_verification)

    decision_outcome = pd.Series("APPROVE", index=df.index, dtype=str)
    decision_outcome[approved_mask & (approved_amount < requested * 0.95)] = "COUNTER_OFFER"
    decision_outcome[soft_review]  = "MANUAL_REVIEW"
    decision_outcome[hard_decline] = "DECLINE"
    out["decision_outcome"] = decision_outcome

    # Fill approved fields — NaN for non-approved rows
    out["approved_amount"]  = np.where(approved_mask, approved_amount, np.nan)
    out["approved_rate"]    = np.where(approved_mask, rate_v, np.nan)
    out["term_months_out"]  = np.where(approved_mask, term, np.nan)
    out["monthly_payment"]  = np.where(approved_mask, np.round(payment_v, 2), np.nan)
    out["apr"]              = np.where(approved_mask, rate_v, np.nan)

    # FCRA reason codes for declines (simplified — real batch would map per-row reasons)
    out["fcra_reason_codes"] = np.where(hard_decline, '["AA01"]', "[]")

    return out


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------


def _demo(n: int = 20) -> None:
    """Run a demo evaluation on n random applications."""
    rng = np.random.default_rng(42)

    apps = pd.DataFrame({
        "fico_score":        rng.integers(540, 810, n),
        "annual_income":     rng.uniform(20_000, 150_000, n),
        "dti":               rng.uniform(0.10, 0.60, n),
        "num_derog_marks":   rng.integers(0, 8, n),
        "employment_status": rng.choice(["employed", "self_employed", "unemployed"], n, p=[0.80, 0.15, 0.05]),
        "requested_amount":  rng.uniform(3_000, 55_000, n),
        "term_months":       rng.choice([24, 36, 48, 60, 72], n),
        "loan_purpose":      rng.choice(["debt_consolidation", "medical", "home_improvement", "other"], n),
        "pd_score":          rng.beta(1.5, 12, n),
        "fraud_score":       rng.beta(1, 50, n),
    })

    log.info("── Personal Loan Batch Demo (%d applications) ──", n)
    results = evaluate_batch(apps)
    summary = results["decision_outcome"].value_counts()
    print("\nDecision summary:")
    print(summary.to_string())
    print("\nSample results:")
    cols = ["fico_score", "dti", "decision_outcome", "approved_amount", "approved_rate", "fico_tier"]
    print(results[cols].head(20).to_string(index=False))

    # Single-row demo
    sample = {
        "fico_score": 685, "annual_income": 55_000, "dti": 0.30,
        "num_derog_marks": 0, "employment_status": "employed",
        "requested_amount": 20_000, "term_months": 48,
        "loan_purpose": "home_improvement",
    }
    r = evaluate_personal_loan(sample, pd_score=0.04, fraud_score=0.01)
    print(f"\nSingle-app result: {r.decision.value} | amount={r.approved_amount} | rate={r.approved_rate}%")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Personal Loan Origination Policy Engine")
    parser.add_argument("--demo", type=int, default=20, metavar="N",
                        help="Run demo on N random applications (default: 20)")
    args = parser.parse_args()
    _demo(args.demo)
