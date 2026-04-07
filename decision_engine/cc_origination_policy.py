"""
Credit Card Origination Policy Engine
======================================
Implements a tiered, rule-based origination credit policy for credit cards,
overlaid on top of the PD model score.

The framework:
  1.  Hard declines  — regulatory / absolute exclusions
  2.  Soft declines  — risk appetite gates per product tier
  3.  Manual review  — borderline population (human-in-the-loop)
  4.  Auto-approve   — pass all gates with assigned product + credit limit
  5.  Credit limit   — model-driven, income-capped, product-bounded
  6.  Cut-off analysis — economic break-even PD by product using cost ledger

Cost Assumptions (2024 US credit card industry)
------------------------------------------------
  Acquisition cost:          $45 – $180  (channel-driven)
  Annual servicing cost:     $28 – $55   (per active account)
  Loss given default (LGD):  65 – 85 %   (unsecured revolving; 55 % secured)
  Credit conversion factor:  60 %        (for undrawn commitment EAD)
  Capital ratio requirement: 10 %        (Tier-1 Basel III retail revolving)
  Cost of capital (hurdle):  12 %
  Revenue:
    Interchange:             1.55 %      (spend × rate)
    Interest margin:         APR – CoF   (APR spread net of cost of funds ~4 %)
    Annual fee:              product-specific
    Late / overlimit fees:   $27 – $40
  Break-even PD:
    Derived per product from  Revenue ≥ EL + Servicing + Acquisition/LT
    where LT = expected account lifetime (months).

Usage
-----
    python decision_engine/cc_origination_policy.py            # demo on random apps
    python decision_engine/cc_origination_policy.py --demo 50  # 50-app demo
"""

from __future__ import annotations

import argparse
import logging
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from models.credit_risk.lgd_model import LGDModel

try:
    from decisioning.review_queue import ReviewQueue
except Exception:  # noqa: BLE001
    ReviewQueue = None  # type: ignore[assignment]

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Phase 2: LGD model + HITL review queue hooks ───────────────────────────

_LGD_MODEL = LGDModel()
_REVIEW_QUEUE: Optional["ReviewQueue"] = None


def configure_review_queue(queue: "ReviewQueue") -> None:
    """Configure a module-level ReviewQueue for MANUAL_REVIEW outcomes."""
    global _REVIEW_QUEUE
    _REVIEW_QUEUE = queue


def _risk_grade_from_fico(fico_score: int) -> str:
    """Map FICO to a coarse ordinal risk grade (A best → E worst)."""
    fico = int(fico_score)
    if fico >= 760:
        return "A"
    if fico >= 720:
        return "B"
    if fico >= 680:
        return "C"
    if fico >= 640:
        return "D"
    return "E"


def _product_type_from_product(product: str) -> str:
    return "secured" if str(product).lower().strip() == "secured" else "unsecured"


# ── Decision outcomes ─────────────────────────────────────────────────────────

class Decision(str, Enum):
    APPROVE        = "APPROVE"
    DECLINE        = "DECLINE"
    MANUAL_REVIEW  = "MANUAL_REVIEW"
    REFER_SECURED  = "REFER_SECURED"   # counter-offer: secured card


class DeclineReason(str, Enum):
    BANKRUPTCY_RECENT    = "BANKRUPTCY_RECENT"
    FICO_BELOW_MINIMUM   = "FICO_BELOW_MINIMUM"
    DTI_EXCEED_MAX       = "DTI_EXCEED_MAX"
    FRAUD_INDICATOR      = "FRAUD_INDICATOR"
    INSUFFICIENT_INCOME  = "INSUFFICIENT_INCOME"
    PD_ABOVE_CUTOFF      = "PD_ABOVE_CUTOFF"
    DEROGATORY_EXCESS    = "DEROGATORY_EXCESS"
    TOO_MANY_INQUIRIES   = "TOO_MANY_INQUIRIES"
    EMPLOYMENT_RISK      = "EMPLOYMENT_RISK"
    AGED_BELOW_MINIMUM   = "AGED_BELOW_MINIMUM"
    UTILIZATION_TOO_HIGH = "UTILIZATION_TOO_HIGH"


# ── Product policy thresholds ─────────────────────────────────────────────────

@dataclass
class ProductPolicy:
    """Full origination policy for a single card product."""
    name:              str
    # ── Hard declines ───────────────────
    min_fico:          int   = 580
    max_dti:           float = 0.55
    min_income_annual: int   = 15_000
    max_inq_6m:        int   = 7
    max_derog_marks:   int   = 6
    min_age:           int   = 18
    max_bk_within_yr:  int   = 0      # bankruptcies within last 4 years
    # ── PD cut-off (model-driven) ────────
    pd_hard_decline:   float = 0.30   # > this → always decline
    pd_manual_review:  float = 0.15   # between manual_review & hard_decline → refer
    # ── Credit limit policy ──────────────
    cl_income_multiple_min: float = 0.05   # min CL = income × factor
    cl_income_multiple_max: float = 0.45   # max CL = income × factor (income-cap)
    cl_abs_min:        int   = 500
    cl_abs_max:        int   = 50_000
    # ── Economics ────────────────────────
    annual_fee:        float = 0.0
    apr_base:          float = 19.99
    reward_rate:       float = 0.01
    interchange_rate:  float = 0.0155
    acq_cost_mean:     float = 90.0
    servicing_cost_yr: float = 40.0
    lgd:               float = 0.75
    ccf:               float = 0.60
    cost_of_funds:     float = 0.04   # cost of funds (APR spread denominator)
    hurdle_rate:       float = 0.12
    expected_tenure_mo:float = 36.0   # avg months account stays open


PRODUCT_POLICIES: dict[str, ProductPolicy] = {
    "secured": ProductPolicy(
        name="secured",
        min_fico=300, max_dti=0.65, min_income_annual=8_000,
        max_inq_6m=12, max_derog_marks=15, max_bk_within_yr=2,
        pd_hard_decline=0.55, pd_manual_review=0.40,
        cl_income_multiple_min=0.025, cl_income_multiple_max=0.10,
        cl_abs_min=200, cl_abs_max=1_000,
        annual_fee=35, apr_base=24.99, lgd=0.55,
        acq_cost_mean=60, servicing_cost_yr=35,
    ),
    "student": ProductPolicy(
        name="student",
        min_fico=600, max_dti=0.50, min_income_annual=10_000,
        max_inq_6m=6, max_derog_marks=3,
        pd_hard_decline=0.30, pd_manual_review=0.18,
        cl_abs_min=500, cl_abs_max=3_000,
        annual_fee=0, apr_base=20.99, acq_cost_mean=55,
    ),
    "basic": ProductPolicy(
        name="basic",
        min_fico=620, max_dti=0.50, min_income_annual=18_000,
        max_inq_6m=5, max_derog_marks=4,
        pd_hard_decline=0.25, pd_manual_review=0.14,
        cl_abs_min=1_000, cl_abs_max=7_500,
        annual_fee=0, apr_base=19.99, acq_cost_mean=70,
    ),
    "rewards": ProductPolicy(
        name="rewards",
        min_fico=670, max_dti=0.45, min_income_annual=30_000,
        max_inq_6m=4, max_derog_marks=2,
        pd_hard_decline=0.18, pd_manual_review=0.10,
        cl_abs_min=2_000, cl_abs_max=20_000,
        annual_fee=95, apr_base=18.99, acq_cost_mean=95,
        reward_rate=0.015,
    ),
    "premium": ProductPolicy(
        name="premium",
        min_fico=720, max_dti=0.40, min_income_annual=60_000,
        max_inq_6m=3, max_derog_marks=1,
        pd_hard_decline=0.12, pd_manual_review=0.07,
        cl_abs_min=5_000, cl_abs_max=50_000,
        annual_fee=250, apr_base=17.99, acq_cost_mean=130,
        reward_rate=0.02,
    ),
    "ultra_premium": ProductPolicy(
        name="ultra_premium",
        min_fico=760, max_dti=0.35, min_income_annual=150_000,
        max_inq_6m=2, max_derog_marks=0,
        pd_hard_decline=0.06, pd_manual_review=0.04,
        cl_abs_min=10_000, cl_abs_max=100_000,
        annual_fee=550, apr_base=16.99, acq_cost_mean=180,
        reward_rate=0.03,
    ),
    "business": ProductPolicy(
        name="business",
        min_fico=650, max_dti=0.50, min_income_annual=40_000,
        max_inq_6m=5, max_derog_marks=3,
        pd_hard_decline=0.22, pd_manual_review=0.12,
        cl_abs_min=3_000, cl_abs_max=75_000,
        annual_fee=95, apr_base=18.49, acq_cost_mean=110,
        reward_rate=0.02,
    ),
}


# ── Economic break-even calculator ───────────────────────────────────────────

def compute_breakeven_pd(
    policy: ProductPolicy,
    avg_balance: float,
    avg_spend: float = 800.0,
    risk_grade: str = "C",
) -> dict:
    """
    Compute the economic break-even PD for a product+balance combination.

    Break-even condition:
      Revenue per year ≥ Expected Loss + Servicing + Amortised Acquisition Cost

    Revenue = Interchange + Net Interest Margin + Annual Fee
    EL      = PD × LGD × EAD
    """
    ead         = avg_balance + policy.ccf * max(0, avg_balance * 0.5)
    interchange = avg_spend * 12 * policy.interchange_rate
    nim         = avg_balance * (policy.apr_base / 100 - policy.cost_of_funds)
    annual_fee_rev = policy.annual_fee
    total_rev   = interchange + nim + annual_fee_rev

    # Amortised acquisition cost per year
    acq_cost_yr = policy.acq_cost_mean / (policy.expected_tenure_mo / 12)

    total_cost_excl_el = policy.servicing_cost_yr + acq_cost_yr
    capital_cost = ead * 0.75 * 0.10 * policy.hurdle_rate  # RWA capital charge

    # Break-even PD: total_rev - cost_excl_el - PD×LGD×EAD - capital_cost >= 0
    # ⟹  PD_BE = (total_rev - cost_excl_el - capital_cost) / (LGD × EAD)
    # Phase 2: use downturn LGD for conservative break-even economics.
    lgd = _LGD_MODEL.predict(
        product_type=_product_type_from_product(policy.name),
        risk_grade=risk_grade,
        use_downturn=True,
    )

    breakeven_pd = max(0.0, (total_rev - total_cost_excl_el - capital_cost) / (lgd * max(ead, 1.0)))
    return {
        "product"          : policy.name,
        "avg_balance"      : avg_balance,
        "ead"              : round(ead, 2),
        "revenue_yr"       : round(total_rev, 2),
        "servicing_cost_yr": round(policy.servicing_cost_yr, 2),
        "acq_cost_yr"      : round(acq_cost_yr, 2),
        "capital_cost_yr"  : round(capital_cost, 2),
        "breakeven_pd"     : round(breakeven_pd, 4),
        "hard_decline_pd"  : policy.pd_hard_decline,
        "policy_headroom"  : round(policy.pd_hard_decline - breakeven_pd, 4),
    }


# ── Credit limit calculator ────────────────────────────────────────────────────

def assign_credit_limit(
    policy: ProductPolicy,
    annual_income: float,
    fico_score:    int,
    pd_score:      float,
    dti:           float,
) -> int:
    """Base limit on income affordability, capped by PD risk adjustment."""
    # Income-based range
    lo = annual_income * policy.cl_income_multiple_min
    hi = annual_income * policy.cl_income_multiple_max

    # FICO multiplier  (0.70 @ 580 → 1.20 @ 850)
    fico_mult = 0.70 + 0.50 * (fico_score - 580) / 270

    # PD risk haircut  (1.0 @ pd=0 → 0.50 @ pd=pd_hard_decline)
    pd_haircut = 1.0 - 0.50 * (pd_score / policy.pd_hard_decline)

    # DTI affordability haircut
    dti_haircut = max(0.50, 1 - (dti - 0.30) * 1.5)

    raw_cl = hi * fico_mult * pd_haircut * dti_haircut
    cl = int(round(np.clip(raw_cl, max(lo, policy.cl_abs_min), policy.cl_abs_max) / 100) * 100)
    return cl


# ── Main decision function ────────────────────────────────────────────────────

@dataclass
class PolicyDecision:
    account_id:       Optional[int]
    decision:         Decision
    product:          str
    decline_reasons:  list[str] = field(default_factory=list)
    credit_limit:     int = 0
    apr:              float = 0.0
    pd_score:         float = 0.0
    tier_breakeven_pd: float = 0.0


def evaluate_application(
    account_id:      Optional[int],
    # Bureau / underwriting inputs
    fico_score:      int,
    annual_income:   float,
    dti:             float,
    num_bankruptcy:  int,
    num_derog_marks: int,
    inq_last_6m:     int,
    age:             int,
    employment_status: str,
    pct_rev_utilization: float,
    # Model PD score
    pd_score:        float,
    # Requested product (may be overridden to cheaper tier)
    requested_product: str = "rewards",
) -> PolicyDecision:
    """
    Evaluate a single credit card application against the full policy stack.
    Returns a PolicyDecision with decision, limit, APR and reasons.
    """
    product  = requested_product
    policy   = PRODUCT_POLICIES.get(product, PRODUCT_POLICIES["basic"])
    reasons: list[str] = []

    # ── Hard decline checks ────────────────────────────────────────────────
    if age < 18:
        reasons.append(DeclineReason.AGED_BELOW_MINIMUM)
    if fico_score < policy.min_fico:
        reasons.append(DeclineReason.FICO_BELOW_MINIMUM)
    if annual_income < policy.min_income_annual:
        reasons.append(DeclineReason.INSUFFICIENT_INCOME)
    if dti > policy.max_dti:
        reasons.append(DeclineReason.DTI_EXCEED_MAX)
    if num_bankruptcy > policy.max_bk_within_yr:
        reasons.append(DeclineReason.BANKRUPTCY_RECENT)
    if num_derog_marks > policy.max_derog_marks:
        reasons.append(DeclineReason.DEROGATORY_EXCESS)
    if inq_last_6m > policy.max_inq_6m:
        reasons.append(DeclineReason.TOO_MANY_INQUIRIES)
    if employment_status == "unemployed" and product not in ("secured",):
        reasons.append(DeclineReason.EMPLOYMENT_RISK)
    if pct_rev_utilization > 0.95:
        reasons.append(DeclineReason.UTILIZATION_TOO_HIGH)

    # PD-based hard decline
    if pd_score >= policy.pd_hard_decline:
        reasons.append(DeclineReason.PD_ABOVE_CUTOFF)

    if reasons:
        # Try counter-offer to secured card if not already there
        if product != "secured" and fico_score >= 300:
            sec_pol = PRODUCT_POLICIES["secured"]
            sec_reasons = [
                r for r in reasons
                if r not in (
                    DeclineReason.FICO_BELOW_MINIMUM,
                    DeclineReason.PD_ABOVE_CUTOFF,
                    DeclineReason.DEROGATORY_EXCESS,
                    DeclineReason.UTILIZATION_TOO_HIGH,
                    DeclineReason.EMPLOYMENT_RISK,
                )
                and fico_score >= sec_pol.min_fico
                and pd_score < sec_pol.pd_hard_decline
            ]
            if not sec_reasons:
                cl = assign_credit_limit(sec_pol, annual_income, fico_score, pd_score, dti)
                apr = round(sec_pol.apr_base + 6 * (1 - fico_score / 850) ** 1.5, 2)
                be = compute_breakeven_pd(sec_pol, cl * 0.50, risk_grade=_risk_grade_from_fico(fico_score))
                return PolicyDecision(
                    account_id=account_id,
                    decision=Decision.REFER_SECURED,
                    product="secured",
                    decline_reasons=reasons,
                    credit_limit=cl,
                    apr=apr,
                    pd_score=pd_score,
                    tier_breakeven_pd=be["breakeven_pd"],
                )
        return PolicyDecision(
            account_id=account_id,
            decision=Decision.DECLINE,
            product=product,
            decline_reasons=[r.value if hasattr(r, "value") else r for r in reasons],
            pd_score=pd_score,
        )

    # ── Manual review band ─────────────────────────────────────────────────
    if pd_score >= policy.pd_manual_review:
        cl = assign_credit_limit(policy, annual_income, fico_score, pd_score, dti)
        be = compute_breakeven_pd(policy, cl * 0.40, risk_grade=_risk_grade_from_fico(fico_score))

        if _REVIEW_QUEUE is not None:
            try:
                _REVIEW_QUEUE.enqueue(
                    application_id=str(account_id or ""),
                    pd_score=float(pd_score),
                    features={
                        "fico_score": int(fico_score),
                        "annual_income": float(annual_income),
                        "dti": float(dti),
                        "num_bankruptcy": int(num_bankruptcy),
                        "num_derog_marks": int(num_derog_marks),
                        "inq_last_6m": int(inq_last_6m),
                        "age": int(age),
                        "employment_status": str(employment_status),
                        "pct_rev_utilization": float(pct_rev_utilization),
                        "requested_product": str(requested_product),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("ReviewQueue enqueue failed (continuing): %s", exc)

        return PolicyDecision(
            account_id=account_id,
            decision=Decision.MANUAL_REVIEW,
            product=product,
            credit_limit=cl,
            apr=round(policy.apr_base + 3 * (1 - fico_score / 850) ** 1.5, 2),
            pd_score=pd_score,
            tier_breakeven_pd=be["breakeven_pd"],
        )

    # ── Auto-approve ───────────────────────────────────────────────────────
    cl  = assign_credit_limit(policy, annual_income, fico_score, pd_score, dti)
    apr = round(policy.apr_base + 6 * (1 - fico_score / 850) ** 1.5, 2)
    be  = compute_breakeven_pd(policy, cl * 0.35, risk_grade=_risk_grade_from_fico(fico_score))

    return PolicyDecision(
        account_id=account_id,
        decision=Decision.APPROVE,
        product=product,
        credit_limit=cl,
        apr=apr,
        pd_score=pd_score,
        tier_breakeven_pd=be["breakeven_pd"],
    )


# ── Batch policy evaluation ───────────────────────────────────────────────────

def evaluate_batch(df: pd.DataFrame, product_col: str = "product") -> pd.DataFrame:
    """
    Apply policy to a full origination DataFrame (from generate_cc_pd_dataset.py).
    Expects PD score in column 'true_pd' or 'pd_score'.
    """
    pd_col = "true_pd" if "true_pd" in df.columns else "pd_score"

    results = []
    for row in df.itertuples(index=False):
        d = evaluate_application(
            account_id        = getattr(row, "account_id", None),
            fico_score        = int(row.fico_score),
            annual_income     = float(row.annual_income),
            dti               = float(row.dti),
            num_bankruptcy    = int(row.num_bankruptcy),
            num_derog_marks   = int(row.num_derog_marks),
            inq_last_6m       = int(row.inq_last_6m),
            age               = int(row.age),
            employment_status = str(row.employment_status),
            pct_rev_utilization = float(row.pct_rev_utilization),
            pd_score          = float(getattr(row, pd_col, 0.10)),
            requested_product = str(getattr(row, product_col, "basic")),
        )
        results.append({
            "account_id"       : d.account_id,
            "policy_decision"  : d.decision.value,
            "policy_product"   : d.product,
            "policy_cl"        : d.credit_limit,
            "policy_apr"       : d.apr,
            "pd_score"         : d.pd_score,
            "breakeven_pd"     : d.tier_breakeven_pd,
            "decline_reasons"  : "|".join(d.decline_reasons),
        })
    return pd.DataFrame(results)


# ── Break-even table ──────────────────────────────────────────────────────────

def print_breakeven_table() -> pd.DataFrame:
    """Print economic break-even PD by product at typical balance levels."""
    rows = []
    typical_balances = {
        "secured": 400,   "student": 800,    "basic": 1_500,
        "rewards": 3_500, "premium": 8_000,  "ultra_premium": 18_000, "business": 7_000,
    }
    for pname, pol in PRODUCT_POLICIES.items():
        be = compute_breakeven_pd(pol, typical_balances[pname], risk_grade="C")
        rows.append(be)
    df = pd.DataFrame(rows)
    log.info("\n── Economic Break-Even PD by Product ───────────────────────")
    log.info("\n%s", df[["product", "avg_balance", "revenue_yr",
                          "servicing_cost_yr", "acq_cost_yr", "capital_cost_yr",
                          "breakeven_pd", "hard_decline_pd", "policy_headroom"]].to_string(index=False))
    return df


# ── Section 19 — CNPV-based batch origination valuation ──────────────────────

def run_batch_valuation(
    df_applicants: pd.DataFrame,
    scenario_weights: dict | None = None,
    cet1_buffer_available: float = 500_000_000.0,
) -> dict:
    """Evaluate a cohort of applicants using the 36-month CNPV model.

    Each applicant is scored under Base, Industry Worsening, and Recession
    scenarios.  The final acquisition signal uses base-scenario logic but
    downgrades to DECLINE if recession CNPV < -$200.

    Parameters
    ----------
    df_applicants:
        DataFrame with columns: application_id, product_id,
        bureau_score_at_orig, requested_credit_limit, apr_offered,
        annual_fee, interchange_rate, rewards_rate, monthly_spend_estimated,
        expected_utilisation, acquisition_cost, pd_score, risk_segment, channel.
    scenario_weights:
        Optional override of CC_SCENARIOS probability weights.
    cet1_buffer_available:
        Firm CET1 capital buffer available for originations (USD).

    Returns
    -------
    dict with keys:
        applicant_results   — list of per-applicant dicts
        portfolio_summary   — aggregate KPIs
        scenario_weights_used
        cet1_buffer_input
    """
    try:
        from models.pricing.cnpv_engine import compute_cnpv
        from models.pricing.scenario_config import CC_SCENARIOS
    except ImportError:
        log.error("models.pricing package not found — cannot run CNPV batch valuation")
        return {"error": "models.pricing not available"}

    weights = scenario_weights or {s: CC_SCENARIOS[s]["probability_weight"] for s in CC_SCENARIOS}
    results = []

    for _, row in df_applicants.iterrows():
        per_scenario: dict = {}
        for scen in ["base", "industry_worsening", "recession"]:
            per_scenario[scen] = compute_cnpv(
                credit_limit          = float(row.get("requested_credit_limit", 5_000)),
                annual_pd             = float(row.get("pd_score", 0.025)),
                apr                   = float(row.get("apr_offered", 0.2199)),
                annual_fee            = float(row.get("annual_fee", 0)),
                interchange_rate      = float(row.get("interchange_rate", 0.0190)),
                rewards_rate          = float(row.get("rewards_rate", 0.015)),
                monthly_spend         = float(row.get("monthly_spend_estimated", 650)),
                avg_utilisation       = float(row.get("expected_utilisation", 0.45)),
                acquisition_cost      = float(row.get("acquisition_cost", 120)),
                product_id            = str(row.get("product_id", "cash_back_everyday")),
                bureau_score          = int(row.get("bureau_score_at_orig", 680)),
                scenario              = scen,
                cet1_buffer_available = cet1_buffer_available,
                include_cashflows     = False,
            )

        sw_cnpv = sum(weights[s] * per_scenario[s].cnpv for s in weights)
        signal  = per_scenario["base"].acquisition_signal
        if per_scenario["recession"].cnpv < -200:
            signal = "DECLINE"

        results.append({
            "applicant_id":             row.get("application_id", ""),
            "product_id":               row.get("product_id", ""),
            "bureau_score":             row.get("bureau_score_at_orig"),
            "risk_segment":             row.get("risk_segment", "near_prime"),
            "cnpv_base":                per_scenario["base"].cnpv,
            "cnpv_worsening":           per_scenario["industry_worsening"].cnpv,
            "cnpv_recession":           per_scenario["recession"].cnpv,
            "scenario_weighted_cnpv":   round(sw_cnpv, 2),
            "acquisition_signal":       signal,
            "recommended_apr":          per_scenario["base"].recommended_apr,
            "recommended_credit_limit": per_scenario["base"].recommended_credit_limit,
            "capital_required":         per_scenario["base"].capital_check.capital_required,
            "roe_3yr_base":             per_scenario["base"].roe_3yr,
            "ftp_rate_base":            per_scenario["base"].ftp.total_ftp_rate,
        })

    df_results = pd.DataFrame(results)
    approved   = df_results[df_results["acquisition_signal"] == "ACQUIRE"]

    portfolio_summary: dict = {
        "total_applicants":      len(df_results),
        "approve_count":         int((df_results["acquisition_signal"] == "ACQUIRE").sum()),
        "manage_price_count":    int((df_results["acquisition_signal"] == "MANAGE_PRICE").sum()),
        "decline_count":         int((df_results["acquisition_signal"] == "DECLINE").sum()),
        "approve_rate":          round(len(approved) / len(df_results), 4) if len(df_results) > 0 else 0,
        "expected_portfolio_cnpv": round(float(approved["scenario_weighted_cnpv"].sum()), 2) if len(approved) > 0 else 0,
        "avg_cnpv_per_approved": round(float(approved["scenario_weighted_cnpv"].mean()), 2) if len(approved) > 0 else 0,
        "capital_consumed":      round(float(approved["capital_required"].sum()), 2) if len(approved) > 0 else 0,
        "remaining_capital":     round(
            cet1_buffer_available - float(approved["capital_required"].sum()), 2
        ) if len(approved) > 0 else cet1_buffer_available,
        "avg_ftp_rate_approved": round(float(approved["ftp_rate_base"].mean()), 4) if len(approved) > 0 else 0,
        "avg_roe_3yr_approved":  round(float(approved["roe_3yr_base"].mean()), 4) if len(approved) > 0 else 0,
        "cnpv_by_risk_segment":  df_results.groupby("risk_segment")["scenario_weighted_cnpv"].mean().round(2).to_dict(),
        "cnpv_p10_p50_p90": {
            "p10": round(float(df_results["scenario_weighted_cnpv"].quantile(0.10)), 2),
            "p50": round(float(df_results["scenario_weighted_cnpv"].quantile(0.50)), 2),
            "p90": round(float(df_results["scenario_weighted_cnpv"].quantile(0.90)), 2),
        },
        "scenario_comparison": {
            "base_avg_cnpv":      round(float(df_results["cnpv_base"].mean()), 2),
            "worsening_avg_cnpv": round(float(df_results["cnpv_worsening"].mean()), 2),
            "recession_avg_cnpv": round(float(df_results["cnpv_recession"].mean()), 2),
        },
    }

    return {
        "applicant_results":   df_results.to_dict(orient="records"),
        "portfolio_summary":   portfolio_summary,
        "scenario_weights_used": weights,
        "cet1_buffer_input":   cet1_buffer_available,
    }


_BQ_APPLICANT_COHORT_QUERY = """
SELECT
  o.origination_id                              AS application_id,
  o.product_id,
  o.bureau_score_at_orig,
  o.credit_limit_usd                            AS requested_credit_limit,
  o.apr_purchase                                AS apr_offered,
  o.annual_fee_usd                              AS annual_fee,
  o.channel,
  c.income_annual_usd,
  c.thin_file,
  CASE
    WHEN o.bureau_score_at_orig >= 720 THEN 'prime'
    WHEN o.bureau_score_at_orig >= 660 THEN 'near_prime'
    WHEN o.bureau_score_at_orig >= 580 THEN 'subprime'
    ELSE 'thin_file'
  END                                           AS risk_segment,
  COALESCE(t.avg_monthly_spend, 650)            AS monthly_spend_estimated,
  COALESCE(t.avg_utilisation, 0.45)             AS expected_utilisation,
  COALESCE(ms.pd_score,
    CASE
      WHEN o.bureau_score_at_orig >= 720 THEN 0.008
      WHEN o.bureau_score_at_orig >= 660 THEN 0.022
      WHEN o.bureau_score_at_orig >= 580 THEN 0.048
      ELSE 0.085
    END
  )                                             AS pd_score
FROM `{project}.{dataset}.cc_originations` o
JOIN `{project}.{dataset}.cc_customers` c
  ON o.customer_id = c.customer_id
LEFT JOIN (
    SELECT origination_id,
           AVG(purchase_volume_usd)  AS avg_monthly_spend,
           AVG(utilization_rate)     AS avg_utilisation
    FROM `{project}.{dataset}.cc_monthly_statements`
    WHERE account_age_months BETWEEN 1 AND 3
    GROUP BY origination_id
) t ON o.origination_id = t.origination_id
LEFT JOIN `{project}.{dataset}.model_scores` ms
  ON o.origination_id = ms.application_id
WHERE o.origination_date >= '{date_from}'
  AND o.origination_date < '{date_to}'
  AND o.decision = 'APPROVED'
LIMIT {limit}
"""


def load_applicant_cohort_from_bq(
    bq_client,
    project: str,
    dataset: str,
    date_from: str,
    date_to: str,
    limit: int = 50_000,
) -> pd.DataFrame:
    """Pull origination cohort from BigQuery for batch CNPV valuation.

    Parameters
    ----------
    bq_client:
        An initialised google-cloud-bigquery ``Client`` instance.
    project:
        GCP project ID (e.g. ``"ai-risk-workflow"``).
    dataset:
        BigQuery dataset name (e.g. ``"credit_risk_model_dev"``).
    date_from / date_to:
        ISO date strings bounding the origination cohort (``"YYYY-MM-DD"``).
    limit:
        Maximum rows to return.

    Returns
    -------
    pandas DataFrame with columns required by run_batch_valuation().
    """
    query = _BQ_APPLICANT_COHORT_QUERY.format(
        project=project,
        dataset=dataset,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    return bq_client.query(query).to_dataframe()


# ── CLI demo ─────────────────────────────────────────────────────────────────

def _demo(n: int = 20) -> None:
    """Generate n random applications and evaluate them."""
    rng = np.random.default_rng(99)

    demo_apps = pd.DataFrame({
        "account_id"          : np.arange(1, n + 1),
        "fico_score"          : rng.integers(580, 820, n),
        "annual_income"       : (np.exp(rng.normal(10.8, 0.5, n)) / 100).astype(int) * 100,
        "dti"                 : rng.uniform(0.10, 0.55, n).round(2),
        "num_bankruptcy"      : rng.choice([0, 0, 0, 0, 1], n),
        "num_derog_marks"     : rng.integers(0, 5, n),
        "inq_last_6m"         : rng.integers(0, 8, n),
        "age"                 : rng.integers(21, 65, n),
        "employment_status"   : rng.choice(["employed_ge2yr", "employed_lt2yr", "unemployed"],
                                           n, p=[0.75, 0.20, 0.05]),
        "pct_rev_utilization" : rng.uniform(0.0, 0.90, n).round(2),
        "true_pd"             : rng.uniform(0.01, 0.35, n).round(3),
        "product"             : rng.choice(list(PRODUCT_POLICIES.keys()), n),
    })

    results = evaluate_batch(demo_apps)
    combined = demo_apps.merge(results, on="account_id")

    summary = combined["policy_decision"].value_counts()
    log.info("\n── Demo Decisions (%d apps) ──────────────────────────────", n)
    log.info("\n%s", summary.to_string())
    log.info("\n── Sample rows ──────────────────────────────────────────────")
    cols = ["account_id", "fico_score", "annual_income", "true_pd",
            "policy_decision", "policy_cl", "policy_apr", "breakeven_pd", "decline_reasons"]
    log.info("\n%s", combined[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CC Origination Policy Engine")
    ap.add_argument("--demo", type=int, default=20, metavar="N",
                    help="Evaluate N random demo applications")
    ap.add_argument("--breakeven", action="store_true",
                    help="Print break-even PD table and exit")
    args = ap.parse_args()

    print_breakeven_table()

    if args.breakeven:
        pass
    else:
        _demo(args.demo)
