"""
CC Originations Valuation — Central Assumptions Registry
=========================================================
**All** model parameters for Section 19 live here and only here.

The three calculation engines (FTP, Capital, CNPV) and the three macroeconomic
scenario definitions all read from this module at *call time*, so any change
made via the ``patch_assumptions()`` function (or the HTTP PATCH endpoint) is
reflected immediately in the next computation — no restart required.

Public API
----------
    from models.pricing.cc_valuation_assumptions import get_assumptions, patch_assumptions

    # Read — returns the singleton CCValuationAssumptions object
    a = get_assumptions()
    print(a.ftp.benchmark_rate)          # 0.053
    print(a.scenarios["base"].probability_weight)   # 0.55

    # Update at runtime — deep-merge a partial dict
    patch_assumptions({"ftp": {"benchmark_rate": 0.0545}})

    # Reset to env-var defaults
    from models.pricing.cc_valuation_assumptions import reset_assumptions
    reset_assumptions()

    # HTTP (via AgentHiveHQ API):
    GET   /api/analytics/cc-valuation/assumptions
    PATCH /api/analytics/cc-valuation/assumptions
"""

from __future__ import annotations

import copy
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List

# ---------------------------------------------------------------------------
# Sub-dataclasses (one per section)
# ---------------------------------------------------------------------------


@dataclass
class ScenarioDef:
    """One macroeconomic scenario."""

    label: str
    description: str
    # ── Multipliers ──────────────────────────────────────────────────────
    # Applied on top of the product-level expected annual default rate
    annual_default_rate_mult: float
    # FTP spread over benchmark (bps)
    ftp_spread_bps: int
    # Revenue/cost volume multipliers
    spend_volume_mult: float
    payment_rate_mult: float
    # Attrition: higher value = faster account closures
    attrition_mult: float
    # Fraction of CET1 buffer available for new originations in this scenario
    capital_headroom_pct: float
    # Weight used in scenario-weighted CNPV computation; must sum to 1.0 across all scenarios
    probability_weight: float


@dataclass
class FTPAssumptions:
    """Pool-based matched-maturity FTP parameters."""

    # Annualised benchmark rate (3-month SOFR proxy), e.g. 0.0530 = 5.30%
    benchmark_rate: float
    # Firm hurdle rate / WACC used for NPV discounting, e.g. 0.105 = 10.5%
    hurdle_rate: float
    # Liquidity premium by product (basis points added to benchmark)
    liquidity_premium_bps: Dict[str, int]
    # Credit-tier adjustment (basis points)
    credit_tier_adj_bps: Dict[str, int]
    # Bureau score thresholds for tier classification
    prime_score_floor: int       # score >= this → prime
    near_prime_score_floor: int  # score >= this (and < prime_score_floor) → near_prime; below → subprime


@dataclass
class CapitalAssumptions:
    """Basel III capital allocation parameters."""

    # Minimum CET1 capital ratio target, e.g. 0.125 = 12.5%
    cet1_target_ratio: float
    # Buffer always reserved above regulatory minimum (ratio), e.g. 0.020 = 200bps
    reserved_buffer_ratio: float
    # Total CET1 capital buffer available to the origination desk (USD)
    cet1_buffer_available_usd: float
    # Expected card balance utilisation at origination (fraction of credit limit)
    expected_utilisation_by_product: Dict[str, float]
    # Basel III Standardised risk weight by PD tier (fraction)
    risk_weight_by_tier: Dict[str, float]
    # Loss Given Default for unsecured revolving credit (fraction), e.g. 0.65
    lgd_default: float


@dataclass
class CNPVAssumptions:
    """CNPV model parameters."""

    # Number of monthly periods in the projection horizon
    horizon_months: int
    # Minimum CNPV ($) to emit ACQUIRE signal
    breakeven_threshold_usd: float
    # Below this CNPV ($) → MANAGE_PRICE (must be <= breakeven_threshold_usd)
    acquire_signal_minimum_usd: float
    # If recession CNPV falls below this ($), override signal to DECLINE (negative)
    recession_decline_threshold_usd: float
    # Per-account monthly operating cost (USD) — servicing + fraud + ops overhead
    monthly_operating_cost_usd: float
    # 36-element PD seasoning curve: multiplicative adjustment on flat monthly PD
    # Index 0 = month 1, index 35 = month 36
    pd_seasoning_curve: List[float]


@dataclass
class CCValuationAssumptions:
    """Root assumptions container — one singleton instance is maintained at runtime."""

    model_version: str
    scenarios: Dict[str, ScenarioDef]
    ftp: FTPAssumptions
    capital: CapitalAssumptions
    cnpv: CNPVAssumptions


# ---------------------------------------------------------------------------
# Default factory (reads from environment variables for overridable params)
# ---------------------------------------------------------------------------


def _build_defaults() -> CCValuationAssumptions:
    """Construct the default assumptions, respecting env-var overrides."""

    return CCValuationAssumptions(
        model_version="cc_origination_valuation_v1",

        # ── Macroeconomic Scenarios ──────────────────────────────────────
        scenarios={
            "base": ScenarioDef(
                label="Base",
                description=(
                    "Fed Funds rate holds 4.25–4.50%; unemployment 4.1%; GDP growth "
                    "+1.8% YoY. Credit card delinquency tracks 2023–2024 normalisation levels. "
                    "Consumer spending grows +3% real. Cost of funds stable."
                ),
                annual_default_rate_mult=1.00,
                ftp_spread_bps=0,
                spend_volume_mult=1.00,
                payment_rate_mult=1.00,
                attrition_mult=1.00,
                capital_headroom_pct=1.00,
                probability_weight=0.55,
            ),
            "industry_worsening": ScenarioDef(
                label="Industry Worsening",
                description=(
                    "Fed Funds rate rises +75bps to 5.00–5.25%; unemployment drifts "
                    "to 5.2%; GDP growth slows to +0.6% YoY. Subprime and near-prime "
                    "delinquency rises 15–25%; charge-off rates increase +20%. Consumer "
                    "spending growth flat. Industry tightening visible in bureau data."
                ),
                annual_default_rate_mult=1.22,
                ftp_spread_bps=40,
                spend_volume_mult=0.94,
                payment_rate_mult=0.91,
                attrition_mult=1.12,
                capital_headroom_pct=0.88,
                probability_weight=0.30,
            ),
            "recession": ScenarioDef(
                label="Recession",
                description=(
                    "Fed Funds rate rises 150bps+ or emergency cut scenario; "
                    "unemployment spikes to 7.5–8.5%; GDP contracts –1.5% YoY. "
                    "Charge-off rates increase +55–80% over base. Consumer spending contracts "
                    "4–6%. Capital constraints bite — origination volumes cut 30–40%."
                ),
                annual_default_rate_mult=1.72,
                ftp_spread_bps=90,
                spend_volume_mult=0.82,
                payment_rate_mult=0.78,
                attrition_mult=1.35,
                capital_headroom_pct=0.62,
                probability_weight=0.15,
            ),
        },

        # ── FTP ──────────────────────────────────────────────────────────
        ftp=FTPAssumptions(
            benchmark_rate=float(os.getenv("FTP_BENCHMARK_RATE", "0.0530")),
            hurdle_rate=float(os.getenv("FTP_HURDLE_RATE", "0.1050")),
            liquidity_premium_bps={
                "secured_starter":    60,
                "classic_unsecured":  50,
                "cash_back_everyday": 40,
                "travel_rewards":     35,
                "premium_rewards":    30,
                "business_basic":     45,
                "business_preferred": 35,
                "student_rewards":    55,
                "elite_metal":        25,
                "private_client":     20,
            },
            credit_tier_adj_bps={
                "prime":      0,
                "near_prime": 20,
                "subprime":   45,
            },
            prime_score_floor=720,
            near_prime_score_floor=660,
        ),

        # ── Capital ──────────────────────────────────────────────────────
        capital=CapitalAssumptions(
            cet1_target_ratio=float(os.getenv("CET1_TARGET_RATIO", "0.125")),
            reserved_buffer_ratio=0.020,
            cet1_buffer_available_usd=float(os.getenv("CET1_BUFFER_AVAILABLE_USD", "500000000")),
            expected_utilisation_by_product={
                "secured_starter":    0.72,
                "classic_unsecured":  0.65,
                "cash_back_everyday": 0.45,
                "travel_rewards":     0.38,
                "premium_rewards":    0.30,
                "business_basic":     0.50,
                "business_preferred": 0.42,
                "student_rewards":    0.60,
                "elite_metal":        0.22,
                "private_client":     0.18,
            },
            risk_weight_by_tier={
                "prime":      0.75,   # PD < 1.0%  — retail regulatory exposure
                "near_prime": 1.00,   # PD 1–3%
                "subprime":   1.50,   # PD > 3%
            },
            lgd_default=float(os.getenv("CC_LGD_DEFAULT", "0.65")),
        ),

        # ── CNPV Model ───────────────────────────────────────────────────
        cnpv=CNPVAssumptions(
            horizon_months=int(os.getenv("CNPV_HORIZON_MONTHS", "36")),
            breakeven_threshold_usd=float(os.getenv("CNPV_BREAKEVEN_THRESHOLD_USD", "50.0")),
            acquire_signal_minimum_usd=0.0,
            recession_decline_threshold_usd=-200.0,
            monthly_operating_cost_usd=float(os.getenv("CC_MONTHLY_OP_COST_USD", "4.20")),
            pd_seasoning_curve=[
                # Months 1–6: ramp-up period
                0.30, 0.55, 0.72, 0.85, 0.95, 1.05,
                # Months 7–12: peak charge-off season
                1.15, 1.20, 1.22, 1.20, 1.18, 1.15,
                # Months 13–18: gradual decline
                1.12, 1.10, 1.08, 1.05, 1.03, 1.00,
                # Months 19–24: plateau
                0.98, 0.96, 0.95, 0.95, 0.95, 0.95,
                # Months 25–30: slow decline
                0.94, 0.93, 0.93, 0.93, 0.92, 0.92,
                # Months 31–36: mature stable
                0.92, 0.92, 0.91, 0.91, 0.91, 0.91,
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_registry: CCValuationAssumptions = _build_defaults()


def get_assumptions() -> CCValuationAssumptions:
    """Return the current active assumptions singleton.

    Engines should call this inside every public function — not at module
    load time — so that runtime patches via ``patch_assumptions()`` are
    reflected immediately.
    """
    return _registry


def assumptions_as_dict() -> dict:
    """Serialise the current assumptions to a plain JSON-serialisable dict."""
    return asdict(_registry)


def patch_assumptions(patch: dict) -> CCValuationAssumptions:
    """Deep-merge *patch* into the live assumptions and return the updated registry.

    Only top-level section keys are accepted: ``scenarios``, ``ftp``,
    ``capital``, ``cnpv``, ``model_version``.

    Raises
    ------
    ValueError
        If the scenario ``probability_weight`` values no longer sum to 1.0
        after the patch.
    TypeError
        If a patched value has the wrong type.
    """
    global _registry
    current = asdict(_registry)
    _deep_merge(current, patch)
    _registry = _from_dict(current)

    total_weight = sum(
        s.probability_weight for s in _registry.scenarios.values()
    )
    if abs(total_weight - 1.0) > 0.001:
        # Roll back
        current_rollback = asdict(_build_defaults())
        _deep_merge(current_rollback, patch)
        raise ValueError(
            f"scenario probability_weights must sum to 1.0 (got {total_weight:.4f}). "
            "Adjust the weights so they sum to 1.0."
        )

    if len(_registry.cnpv.pd_seasoning_curve) != 36:
        raise ValueError(
            f"pd_seasoning_curve must have exactly 36 elements "
            f"(got {len(_registry.cnpv.pd_seasoning_curve)})"
        )

    return _registry


def reset_assumptions() -> CCValuationAssumptions:
    """Discard any in-memory patches and rebuild from env-var defaults."""
    global _registry
    _registry = _build_defaults()
    return _registry


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, patch: dict) -> None:
    """Recursively merge *patch* into *base* in-place."""
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)


def _from_dict(raw: dict) -> CCValuationAssumptions:
    """Reconstruct a CCValuationAssumptions from a plain dict (reverse of asdict)."""
    return CCValuationAssumptions(
        model_version=raw["model_version"],
        scenarios={
            k: ScenarioDef(**v) for k, v in raw["scenarios"].items()
        },
        ftp=FTPAssumptions(**raw["ftp"]),
        capital=CapitalAssumptions(**raw["capital"]),
        cnpv=CNPVAssumptions(**raw["cnpv"]),
    )
