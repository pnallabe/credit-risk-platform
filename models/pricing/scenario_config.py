"""
Credit Card Economic Scenario Configuration
============================================
Single source of truth for the three macroeconomic scenarios used in
Section 19 (Origination Valuation) and Section 20 (Portfolio Management).

These scenarios supersede the two-state base/stress model used in earlier
projection endpoints (Section 5.4).

Usage
-----
    from models.pricing.scenario_config import CC_SCENARIOS, ScenarioKey
"""

from __future__ import annotations

from typing import Dict, Literal

from models.pricing.cc_valuation_assumptions import get_assumptions

ScenarioKey = Literal["base", "industry_worsening", "recession"]
SCENARIO_KEYS: tuple = ("base", "industry_worsening", "recession")


def get_cc_scenarios() -> Dict[str, dict]:
    """Return a **live** snapshot of CC scenarios from the central registry.

    Reads the global assumptions singleton on every call so that runtime
    patches via ``patch_assumptions()`` or ``PATCH /assumptions`` are
    reflected in the next engine invocation without a server restart.
    """
    a = get_assumptions()
    return {
        k: {
            "label":                    s.label,
            "description":              s.description,
            "annual_default_rate_mult": s.annual_default_rate_mult,
            "ftp_spread_bps":           s.ftp_spread_bps,
            "spend_volume_mult":        s.spend_volume_mult,
            "payment_rate_mult":        s.payment_rate_mult,
            "attrition_mult":           s.attrition_mult,
            "capital_headroom_pct":     s.capital_headroom_pct,
            "probability_weight":       s.probability_weight,
        }
        for k, s in a.scenarios.items()
    }


# Backward-compatible module-level alias — snapshot at import time.
# NOTE: For live/mutable access use get_cc_scenarios() or get_assumptions().scenarios
CC_SCENARIOS: Dict[str, dict] = get_cc_scenarios()
