"""
Basel III Capital Allocation & RWA Engine — Section 19.4
=========================================================
Implements the Basel III Standardised approach for credit card RWA
(consumer revolving exposure) and checks CET1 headroom before approving
new originations.

Risk Weight (RW):
  prime      (PD < 1.0%)  ->  75%   (retail regulatory retail exposure)
  near_prime (PD 1-3%)    -> 100%
  subprime   (PD > 3%)    -> 150%

Capital Requirement per $ outstanding:
  Capital = credit_limit x utilisation_rate x RW x CET1_target_ratio

Capital Availability:
  available_new_rwa = (cet1_capital_buffer - reserved_buffer) / CET1_target_ratio
  can_originate     = True if account_rwa <= available_new_rwa * capital_headroom_pct[scenario]

Usage
-----
    from models.pricing.capital_engine import check_capital_availability, CapitalCheck
    cap = check_capital_availability(
        credit_limit=7500, pd_score=0.022,
        product_id="cash_back_everyday", scenario="base",
        cet1_buffer_available=500_000_000,
    )
    print(cap.can_originate, cap.capital_required)
"""

from __future__ import annotations

from dataclasses import dataclass

from models.pricing.cc_valuation_assumptions import get_assumptions
from models.pricing.scenario_config import ScenarioKey

# All capital parameters live in models/pricing/cc_valuation_assumptions.py.
# Each function reads from get_assumptions() so that runtime patches via
# PATCH /assumptions are reflected without a restart.


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class CapitalCheck:
    """Outcome of a CET1 capital availability check for a single origination."""

    credit_limit:          float
    expected_utilisation:  float
    risk_weight:           float
    rwa:                   float    # credit_limit x utilisation x risk_weight
    capital_required:      float    # rwa x CET1_target_ratio
    available_capital:     float    # scenario-adjusted available capital (USD)
    capital_headroom_pct:  float    # scenario headroom multiplier
    can_originate:         bool
    pd_tier:               str      # prime | near_prime | subprime
    scenario:              str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def pd_to_tier(pd_score: float) -> str:
    """Map an annual PD score to a risk tier label."""
    if pd_score < 0.01:
        return "prime"
    elif pd_score < 0.03:
        return "near_prime"
    else:
        return "subprime"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_capital_availability(
    credit_limit: float,
    pd_score: float,
    product_id: str,
    scenario: ScenarioKey,
    cet1_buffer_available: float,
) -> CapitalCheck:
    """Compute RWA, capital required, and check CET1 headroom.

    Parameters
    ----------
    credit_limit:
        Proposed credit limit in USD.
    pd_score:
        Annual probability of default (e.g. 0.022 = 2.2%).
    product_id:
        Product identifier used to look up expected utilisation.
    scenario:
        Macroeconomic scenario key.
    cet1_buffer_available:
        Current firm CET1 capital buffer available for new originations (USD).

    Returns
    -------
    CapitalCheck
    """
    cap  = get_assumptions().capital
    scen = get_assumptions().scenarios[scenario]
    tier = pd_to_tier(pd_score)
    util = cap.expected_utilisation_by_product.get(product_id, 0.50)
    rw   = cap.risk_weight_by_tier[tier]
    rwa     = credit_limit * util * rw
    cap_req = rwa * cap.cet1_target_ratio
    headroom_pct        = scen.capital_headroom_pct
    effective_available = cet1_buffer_available * headroom_pct

    return CapitalCheck(
        credit_limit          = credit_limit,
        expected_utilisation  = util,
        risk_weight           = rw,
        rwa                   = round(rwa, 2),
        capital_required      = round(cap_req, 2),
        available_capital     = round(effective_available, 2),
        capital_headroom_pct  = headroom_pct,
        can_originate         = cap_req <= effective_available,
        pd_tier               = tier,
        scenario              = scenario,
    )


def compute_rwa_summary(
    credit_limit: float,
    pd_score: float,
    product_id: str,
) -> dict:
    """Return a RWA breakdown across all three scenarios.

    Useful for the capital panel on the frontend.
    """
    cet1 = get_assumptions().capital.cet1_buffer_available_usd
    return {
        scen_key: check_capital_availability(
            credit_limit, pd_score, product_id, scen_key,
            cet1_buffer_available=cet1,
        )
        for scen_key in ("base", "industry_worsening", "recession")
    }
