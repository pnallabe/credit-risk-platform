"""Risk models package (ECL, stress testing, etc.).

Phase 2 introduces a minimum-viable Expected Credit Loss (ECL) engine.
"""

from .ecl_engine import (  # noqa: F401
    ExposureRecord,
    MacroScenario,
    SICRTrigger,
    LifetimePDTermStructure,
    build_default_scenarios,
    check_sicr,
    compute_12m_ecl,
    compute_ead,
    compute_lifetime_ecl,
    compute_portfolio_ecl,
    compute_scenario_weighted_ecl,
    ifrs9_stage_ecl,
)
