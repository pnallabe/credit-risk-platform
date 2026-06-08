from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Literal, Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExposureRecord:
    application_id: str
    product: str
    outstanding_balance: float
    credit_limit: float
    months_on_book: int
    pd_12m: float
    lgd: float
    ccf: float
    stage: Literal[1, 2, 3] = 1
    origination_date: date = date(1970, 1, 1)
    contractual_maturity_months: int = 60


class LifetimePDTermStructure:
    """Build a simple lifetime PD term structure from a 12-month PD.

    Implements the Phase 2 spec formula:
      marginal_PD(t) = pd_12m × (1 - pd_12m)^(t / 12 - 1)

    Output is normalized so cumulative PD never exceeds 1.
    """

    @staticmethod
    def build_term_structure(
        pd_12m: float, lgd: float, max_months: int = 60
    ) -> List[float]:
        _ = lgd  # included for signature parity with the spec
        pd_12m = float(pd_12m)
        max_months = int(max_months)
        if max_months <= 0:
            return []

        if pd_12m <= 0.0:
            return [0.0 for _ in range(max_months)]

        pd_12m = min(max(pd_12m, 0.0), 1.0)

        raw = [
            pd_12m * ((1.0 - pd_12m) ** (t / 12.0 - 1.0))
            for t in range(1, max_months + 1)
        ]
        cum = float(np.sum(raw))
        if cum <= 1.0 or cum == 0.0:
            return [float(x) for x in raw]

        scale = 1.0 / cum
        return [float(x * scale) for x in raw]


def compute_ead(record: ExposureRecord) -> float:
    """EAD = outstanding_balance + ccf × (credit_limit - outstanding_balance)."""
    undrawn = max(0.0, float(record.credit_limit) - float(record.outstanding_balance))
    ead = float(record.outstanding_balance) + float(record.ccf) * undrawn
    return float(ead)


def compute_12m_ecl(record: ExposureRecord) -> float:
    """ECL_12m = pd_12m × lgd × EAD."""
    ead = compute_ead(record)
    ecl = float(record.pd_12m) * float(record.lgd) * ead
    return float(ecl)


def _remaining_months(record: ExposureRecord) -> int:
    remaining = int(record.contractual_maturity_months) - int(record.months_on_book)
    return max(1, remaining)


def _lifetime_ecl_vectorized(
    pd_12m: np.ndarray,
    lgd: np.ndarray,
    ead: np.ndarray,
    remaining_months: np.ndarray,
    discount_rate: float,
) -> np.ndarray:
    """Vectorized lifetime ECL using a closed-form geometric-series approximation.

    This matches the spec's marginal PD form, and applies a normalization factor
    so cumulative PD across the remaining life never exceeds 1.

    Returns unrounded values.
    """
    pd_12m = np.clip(pd_12m.astype(float), 0.0, 1.0)
    lgd = np.clip(lgd.astype(float), 0.0, 1.0)
    ead = np.clip(ead.astype(float), 0.0, np.inf)
    n = np.maximum(remaining_months.astype(int), 1)

    # Handle p == 0 quickly
    out = np.zeros_like(pd_12m, dtype=float)
    mask = pd_12m > 0.0
    if not np.any(mask):
        return out

    p = pd_12m[mask]
    n_masked = n[mask].astype(float)

    # r = (1 - p)^(1/12)
    r = np.power(1.0 - p, 1.0 / 12.0)
    disc = 1.0 + float(discount_rate) / 12.0
    q = r / disc

    # k = p / (1 - p). For p=1, define k as large but we'll clip.
    denom = np.clip(1.0 - p, 1e-12, 1.0)
    k = p / denom

    # Raw (unnormalized) discounted sum: k * sum_{t=1..N} q^t
    # sum q^t = q*(1-q^N)/(1-q)
    one_minus_q = 1.0 - q
    q_pow_n = np.power(q, n_masked)

    # Stable handling when q ~= 1: sum ~= N
    near_one = np.abs(one_minus_q) < 1e-10
    sum_q = np.empty_like(q)
    sum_q[near_one] = n_masked[near_one]
    sum_q[~near_one] = q[~near_one] * (1.0 - q_pow_n[~near_one]) / one_minus_q[~near_one]

    raw_discounted = k * sum_q

    # Raw (unnormalized) cumulative PD across life: k * sum_{t=1..N} r^t
    one_minus_r = 1.0 - r
    r_pow_n = np.power(r, n_masked)

    near_one_r = np.abs(one_minus_r) < 1e-10
    sum_r = np.empty_like(r)
    sum_r[near_one_r] = n_masked[near_one_r]
    sum_r[~near_one_r] = r[~near_one_r] * (1.0 - r_pow_n[~near_one_r]) / one_minus_r[~near_one_r]

    raw_cum_pd = k * sum_r

    scale = np.ones_like(raw_cum_pd)
    over = raw_cum_pd > 1.0
    scale[over] = 1.0 / np.clip(raw_cum_pd[over], 1e-12, np.inf)

    lifetime = raw_discounted * scale * lgd[mask] * ead[mask]
    out[mask] = lifetime
    return out


def compute_lifetime_ecl(record: ExposureRecord, discount_rate: float = 0.05) -> float:
    """Compute lifetime ECL across remaining contractual months."""
    ead = compute_ead(record)
    remaining = _remaining_months(record)

    vals = _lifetime_ecl_vectorized(
        pd_12m=np.array([float(record.pd_12m)]),
        lgd=np.array([float(record.lgd)]),
        ead=np.array([ead]),
        remaining_months=np.array([remaining]),
        discount_rate=float(discount_rate),
    )
    return float(vals[0])


def ifrs9_stage_ecl(record: ExposureRecord, discount_rate: float = 0.05) -> float:
    """IFRS 9 staging: stage 1 = 12m ECL, stage 2/3 = lifetime ECL."""
    if int(record.stage) == 1:
        return compute_12m_ecl(record)
    return compute_lifetime_ecl(record, discount_rate=discount_rate)


@dataclass(frozen=True)
class MacroScenario:
    name: str
    pd_multiplier: float
    lgd_multiplier: float
    probability_weight: float


def build_default_scenarios() -> List[MacroScenario]:
    return [
        MacroScenario("base", 1.0, 1.0, 0.6),
        MacroScenario("adverse", 1.5, 1.2, 0.3),
        MacroScenario("severely_adverse", 2.5, 1.4, 0.1),
    ]


def compute_scenario_weighted_ecl(
    record: ExposureRecord,
    scenarios: Optional[List[MacroScenario]],
    discount_rate: float = 0.05,
) -> Dict[str, object]:
    scenarios = scenarios or build_default_scenarios()

    weight_sum = float(sum(float(s.probability_weight) for s in scenarios))
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Scenario weights must sum to 1.0 (got {weight_sum})")

    per_scenario: Dict[str, float] = {}
    weighted = 0.0

    for s in scenarios:
        credit_limit_s = float(record.credit_limit)
        if s.name == "severely_adverse":
            credit_limit_s *= 0.8
        scaled = ExposureRecord(
            **{
                **record.__dict__,
                "credit_limit": credit_limit_s,
                "pd_12m": float(record.pd_12m) * float(s.pd_multiplier),
                "lgd": float(record.lgd) * float(s.lgd_multiplier),
            }
        )
        ecl = ifrs9_stage_ecl(scaled, discount_rate=discount_rate)
        ecl = round(float(ecl), 2)
        per_scenario[s.name] = ecl
        weighted += float(s.probability_weight) * float(ecl)

    return {
        "scenarios": per_scenario,
        "ecl_weighted": round(float(weighted), 2),
    }


def compute_portfolio_ecl(
    records: List[ExposureRecord],
    scenarios: Optional[List[MacroScenario]] = None,
    discount_rate: float = 0.05,
) -> pd.DataFrame:
    """Compute scenario-weighted ECL for a portfolio.

    Notes
    -----
    - Vectorizes EAD, 12m ECL, and lifetime ECL computations.
    - scenario_breakdown is returned as a Python dict per-row.
    """
    if not records:
        return pd.DataFrame(
            columns=[
                "application_id",
                "stage",
                "ead",
                "pd_12m",
                "lgd",
                "ecl_12m",
                "ecl_lifetime",
                "ecl_weighted",
                "scenario_breakdown",
            ]
        )

    scenarios = scenarios or build_default_scenarios()
    weight_sum = float(sum(float(s.probability_weight) for s in scenarios))
    if not math.isclose(weight_sum, 1.0, rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(f"Scenario weights must sum to 1.0 (got {weight_sum})")

    df = pd.DataFrame([r.__dict__ for r in records])

    # Vectorized EAD
    outstanding = df["outstanding_balance"].astype(float)
    limit = df["credit_limit"].astype(float)
    ccf = df["ccf"].astype(float)
    undrawn = (limit - outstanding).clip(lower=0.0)
    df["ead"] = (outstanding + ccf * undrawn).astype(float)

    # Vectorized 12m ECL
    df["ecl_12m"] = (df["pd_12m"].astype(float) * df["lgd"].astype(float) * df["ead"]).astype(float)

    # Vectorized lifetime ECL
    remaining = (df["contractual_maturity_months"].astype(int) - df["months_on_book"].astype(int)).clip(lower=1)
    lifetime = _lifetime_ecl_vectorized(
        pd_12m=df["pd_12m"].to_numpy(dtype=float),
        lgd=df["lgd"].to_numpy(dtype=float),
        ead=df["ead"].to_numpy(dtype=float),
        remaining_months=remaining.to_numpy(dtype=int),
        discount_rate=float(discount_rate),
    )
    df["ecl_lifetime"] = lifetime

    # Scenario-weighted IFRS9 staging ECL (vectorized per-scenario, then combine)
    stage = df["stage"].astype(int).to_numpy()

    per_scenario_ecls: Dict[str, np.ndarray] = {}
    weighted = np.zeros(len(df), dtype=float)

    base_pd = df["pd_12m"].to_numpy(dtype=float)
    base_lgd = df["lgd"].to_numpy(dtype=float)
    ead_arr = df["ead"].to_numpy(dtype=float)
    remaining_arr = remaining.to_numpy(dtype=int)

    for s in scenarios:
        pd_s = base_pd * float(s.pd_multiplier)
        lgd_s = base_lgd * float(s.lgd_multiplier)

        if s.name == "severely_adverse":
            limit_s = limit * 0.8
            undrawn_s = (limit_s - outstanding).clip(lower=0.0)
            ead_s = (outstanding + ccf * undrawn_s).to_numpy(dtype=float)
        else:
            ead_s = ead_arr

        ecl_12m_s = pd_s * lgd_s * ead_s
        ecl_life_s = _lifetime_ecl_vectorized(
            pd_12m=pd_s,
            lgd=lgd_s,
            ead=ead_s,
            remaining_months=remaining_arr,
            discount_rate=float(discount_rate),
        )

        ecl_stage_s = np.where(stage == 1, ecl_12m_s, ecl_life_s)
        per_scenario_ecls[s.name] = ecl_stage_s
        weighted += float(s.probability_weight) * ecl_stage_s

    # Round monetary outputs
    df["ead"] = df["ead"].round(2)
    df["ecl_12m"] = df["ecl_12m"].round(2)
    df["ecl_lifetime"] = df["ecl_lifetime"].round(2)

    df["ecl_weighted"] = np.round(weighted, 2)

    # scenario_breakdown dict per row
    breakdown: List[Dict[str, float]] = []
    for i in range(len(df)):
        breakdown.append({k: round(float(v[i]), 2) for k, v in per_scenario_ecls.items()})
    df["scenario_breakdown"] = breakdown

    return df[
        [
            "application_id",
            "stage",
            "ead",
            "pd_12m",
            "lgd",
            "ecl_12m",
            "ecl_lifetime",
            "ecl_weighted",
            "scenario_breakdown",
        ]
    ]


@dataclass(frozen=True)
class SICRTrigger:
    pd_threshold_multiplier: float = 2.0
    dpd_threshold: int = 30


def check_sicr(
    record: ExposureRecord,
    origination_pd: float,
    pd_threshold_multiplier: float = 2.0,
    dpd_threshold: int = 30,
    days_past_due: Optional[int] = None,
) -> bool:
    """Return True if Significant Increase in Credit Risk occurred.

    Implements the PD-multiple trigger from the Phase 2 prompt.
    If *days_past_due* is provided, also triggers when DPD >= dpd_threshold.
    """
    if float(record.pd_12m) > float(origination_pd) * float(pd_threshold_multiplier):
        return True
    if days_past_due is not None and int(days_past_due) >= int(dpd_threshold):
        return True
    return False


# ---------------------------------------------------------------------------
# S2-D: Helper — build ExposureRecord from ModelScores
# ---------------------------------------------------------------------------

def exposure_record_from_model_scores(
    model_scores,
    outstanding_balance: float,
    credit_limit: float,
    product: str = "credit_card",
    months_on_book: int = 12,
    contractual_maturity_months: int = 60,
    ccf: float = 0.50,
    stage: int = 1,
    fallback_lgd: float = 0.40,
) -> ExposureRecord:
    """Construct an ExposureRecord from a ModelScores object (or dict).

    Uses model_scores.lgd_score when present and non-default; otherwise falls
    back to ``fallback_lgd`` (the Basel-floor conservative estimate).

    The default LGD sentinel value (0.40) indicates the LGD model has not
    been scored — in this case the fallback is used instead.
    """
    _DEFAULT_LGD_SENTINEL = 0.40

    if hasattr(model_scores, "lgd_score"):
        lgd_val = float(model_scores.lgd_score)
    elif isinstance(model_scores, dict):
        lgd_val = float(model_scores.get("lgd_score", fallback_lgd))
    else:
        lgd_val = fallback_lgd

    # If value equals the default sentinel, treat as unscored → use fallback
    if abs(lgd_val - _DEFAULT_LGD_SENTINEL) < 1e-6:
        lgd_val = fallback_lgd

    if hasattr(model_scores, "pd_score"):
        pd_val = float(model_scores.pd_score)
    elif isinstance(model_scores, dict):
        pd_val = float(model_scores.get("pd_score", 0.05))
    else:
        pd_val = 0.05

    if hasattr(model_scores, "application_id"):
        app_id = str(model_scores.application_id)
    elif isinstance(model_scores, dict):
        app_id = str(model_scores.get("application_id", "unknown"))
    else:
        app_id = "unknown"

    return ExposureRecord(
        application_id=app_id,
        product=product,
        outstanding_balance=float(outstanding_balance),
        credit_limit=float(credit_limit),
        months_on_book=int(months_on_book),
        pd_12m=float(pd_val),
        lgd=float(lgd_val),
        ccf=float(ccf),
        stage=stage,  # type: ignore[arg-type]
        contractual_maturity_months=int(contractual_maturity_months),
    )
