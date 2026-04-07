"""
FTP (Funds Transfer Pricing) Engine — Section 19.3
====================================================
Pool-based matched-maturity FTP for credit cards.

FTP Rate =  Base Rate (benchmark)
          + Liquidity Premium
          + Credit-Tier Adjustment
          + Scenario Spread

Where:
  Base Rate         = 3-month USD SOFR (or configured benchmark rate)
  Liquidity Premium = 25-60bps depending on product tier (revolving vs term)
  Credit-Tier Adj   = 0bps (prime) / +20bps (near-prime) / +45bps (subprime)
  Scenario Spread   = CC_SCENARIOS[scenario]["ftp_spread_bps"] / 10_000

Usage
-----
    from models.pricing.ftp_engine import compute_ftp, FTPRate
    rate = compute_ftp("cash_back_everyday", bureau_score=695, scenario="base")
    print(rate.total_ftp_rate)   # e.g. 0.0600
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from models.pricing.cc_valuation_assumptions import get_assumptions
from models.pricing.scenario_config import ScenarioKey

# All FTP parameters live in models/pricing/cc_valuation_assumptions.py.
# Each function reads from get_assumptions() so that runtime patches via
# PATCH /assumptions are reflected without a restart.


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FTPRate:
    """Fully decomposed FTP rate for a single origination."""

    benchmark_rate: float         # e.g. 0.0530
    liquidity_premium_bps: int
    credit_tier_adj_bps: int
    scenario_spread_bps: int
    total_ftp_rate: float         # annualised decimal (e.g. 0.0680)
    credit_tier: str              # prime | near_prime | subprime
    product_id: str
    scenario: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_credit_tier(bureau_score: int) -> str:
    """Map a bureau score to a credit tier using live assumption thresholds."""
    ftp = get_assumptions().ftp
    if bureau_score >= ftp.prime_score_floor:
        return "prime"
    elif bureau_score >= ftp.near_prime_score_floor:
        return "near_prime"
    else:
        return "subprime"


def compute_ftp(
    product_id: str,
    bureau_score: int,
    scenario: ScenarioKey,
) -> FTPRate:
    """Compute the FTP rate for a single origination.

    Parameters
    ----------
    product_id:
        Product identifier (must be a key in LIQUIDITY_PREMIUM, or falls
        back to the 45bps default).
    bureau_score:
        Applicant's bureau score at origination.
    scenario:
        Macroeconomic scenario key: ``"base"``, ``"industry_worsening"``,
        or ``"recession"``.

    Returns
    -------
    FTPRate
        Fully decomposed FTP rate with the total annualised rate.
    """
    f        = get_assumptions().ftp
    scen     = get_assumptions().scenarios[scenario]
    liq_bps  = f.liquidity_premium_bps.get(product_id, 45)
    tier     = get_credit_tier(bureau_score)
    tier_bps = f.credit_tier_adj_bps[tier]
    scen_bps = scen.ftp_spread_bps
    total    = f.benchmark_rate + (liq_bps + tier_bps + scen_bps) / 10_000

    return FTPRate(
        benchmark_rate        = f.benchmark_rate,
        liquidity_premium_bps = liq_bps,
        credit_tier_adj_bps   = tier_bps,
        scenario_spread_bps   = scen_bps,
        total_ftp_rate        = round(total, 6),
        credit_tier           = tier,
        product_id            = product_id,
        scenario              = scenario,
    )


def ftp_rate_table() -> list[dict]:
    """Return FTP rate breakdown for all products across all three scenarios.

    Useful for the frontend FTP assumptions panel.
    """
    f    = get_assumptions().ftp
    rows = []
    for product_id, liq_bps in f.liquidity_premium_bps.items():
        for score_label, score in [("prime", 750), ("near_prime", 690), ("subprime", 620)]:
            tier     = get_credit_tier(score)
            tier_bps = f.credit_tier_adj_bps[tier]
            row: dict = {
                "product_id":            product_id,
                "credit_tier":           score_label,
                "benchmark_rate":        f.benchmark_rate,
                "liquidity_premium_bps": liq_bps,
                "credit_tier_adj_bps":   tier_bps,
            }
            for scen_key in ("base", "industry_worsening", "recession"):
                scen_bps = get_assumptions().scenarios[scen_key].ftp_spread_bps
                total    = f.benchmark_rate + (liq_bps + tier_bps + scen_bps) / 10_000
                row[f"ftp_rate_{scen_key}"]            = round(total, 6)
                row[f"scenario_spread_bps_{scen_key}"] = scen_bps
            rows.append(row)
    return rows
