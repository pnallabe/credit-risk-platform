"""
Customer Lifetime Net Present Value (CNPV) Engine — Section 19.5
=================================================================
36-month CNPV for a single credit card origination under a given
macroeconomic scenario.

Revenue streams (monthly):
  1. Interest Revenue    = balance x (APR / 12)
  2. Interchange Revenue = spend_volume x interchange_rate
  3. Annual Fee          = annual_fee / 12

Cost streams (monthly):
  4. FTP Cost            = balance x (ftp_rate / 12)
  5. Rewards Cost        = spend_volume x rewards_rate
  6. Expected Loss (EL)  = balance x (monthly_PD x LGD)
  7. Operating Cost      = operating_cost_per_account / 12

One-time costs:
  8. Acquisition Cost (CAC) = product-specific acquisition cost at t=0

Discount rate:
  WACC = 10.5% p.a. (firm-level hurdle rate; configurable via FTP_HURDLE_RATE)

CNPV = -CAC + sum_{t=1}^{36} [ (NRI_t - EL_t - OpEx_t) x survival_t / (1 + WACC/12)^t ]

Usage
-----
    from models.pricing.cnpv_engine import compute_cnpv, CNPVResult
    result = compute_cnpv(
        credit_limit=7500, annual_pd=0.022, apr=0.2199, annual_fee=0,
        interchange_rate=0.019, rewards_rate=0.015, monthly_spend=850,
        avg_utilisation=0.42, acquisition_cost=115,
        product_id="cash_back_everyday", bureau_score=695,
        scenario="base", cet1_buffer_available=500_000_000,
    )
    print(result.cnpv, result.acquisition_signal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from models.pricing.capital_engine import CapitalCheck, check_capital_availability
from models.pricing.cc_valuation_assumptions import get_assumptions
from models.pricing.ftp_engine import FTPRate, compute_ftp
from models.pricing.scenario_config import ScenarioKey

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# All CNPV model parameters live in models/pricing/cc_valuation_assumptions.py.
# compute_cnpv() reads them at call time so runtime PATCH /assumptions takes
# effect without restarting the server.


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class MonthlyCashflow:
    """Detailed cashflow record for a single month of the projection horizon."""

    month: int
    balance: float
    interest_income: float
    interchange_income: float
    fee_income: float
    ftp_cost: float
    rewards_cost: float
    expected_loss: float
    operating_cost: float
    net_revenue_income: float    # NRI = interest + interchange + fee - ftp - rewards
    net_cashflow: float          # NRI - EL - OpEx
    survival_rate: float
    pv_cashflow: float           # net_cashflow × survival / discount_factor


@dataclass
class CNPVResult:
    """Full CNPV computation output for one applicant under one scenario."""

    scenario: str
    cnpv: float                        # Customer Net Present Value ($)
    cnpv_per_dollar_limit: float       # CNPV / credit_limit (normalised)
    roe_3yr: float                     # 3-yr cumulative net income / capital_required
    acquisition_signal: str            # ACQUIRE | DECLINE | MANAGE_PRICE
    recommended_apr: float             # optimal APR for target CNPV breakeven
    recommended_credit_limit: float
    capital_check: CapitalCheck
    ftp: FTPRate
    monthly_cashflows: List[dict] = field(default_factory=list)
    sensitivity: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_cnpv(
    credit_limit: float,
    annual_pd: float,
    apr: float,
    annual_fee: float,
    interchange_rate: float,
    rewards_rate: float,
    monthly_spend: float,
    avg_utilisation: float,
    acquisition_cost: float,
    product_id: str,
    bureau_score: int,
    scenario: ScenarioKey,
    cet1_buffer_available: float,
    include_cashflows: bool = True,
) -> CNPVResult:
    """Compute the 36-month CNPV for a single applicant under one scenario.

    Parameters
    ----------
    credit_limit:
        Proposed credit limit in USD.
    annual_pd:
        Annual PD score from the credit model (e.g. 0.022).
    apr:
        Annualised percentage rate offered (e.g. 0.2199 = 21.99%).
    annual_fee:
        Annual card fee in USD.
    interchange_rate:
        Interchange rate on spend (e.g. 0.019 = 1.90%).
    rewards_rate:
        Rewards / cash-back cost rate on spend (e.g. 0.015 = 1.50%).
    monthly_spend:
        Estimated monthly spend in USD.
    avg_utilisation:
        Expected average balance utilisation over the projection horizon.
    acquisition_cost:
        Customer acquisition cost in USD (channel-dependent).
    product_id:
        Product identifier.
    bureau_score:
        Applicant's bureau score at origination.
    scenario:
        Macroeconomic scenario key.
    cet1_buffer_available:
        Firm CET1 capital buffer available for new originations (USD).
    include_cashflows:
        Whether to populate the monthly_cashflows list (expensive for batch).

    Returns
    -------
    CNPVResult
    """
    _a         = get_assumptions()
    scen       = _a.scenarios[scenario]
    cnpv_a     = _a.cnpv
    cap_a      = _a.capital
    adj_pd     = annual_pd * scen.annual_default_rate_mult
    monthly_pd_base = adj_pd / 12
    ftp        = compute_ftp(product_id, bureau_score, scenario)
    cap        = check_capital_availability(
        credit_limit, adj_pd, product_id, scenario, cet1_buffer_available
    )
    adj_spend          = monthly_spend * scen.spend_volume_mult
    monthly_attrition  = 0.008 * scen.attrition_mult   # ~9.6% base annual attrition

    cashflows: list[dict] = []
    balance   = credit_limit * avg_utilisation
    survival  = 1.0
    pv_total  = -acquisition_cost   # upfront CAC

    for t in range(1, cnpv_a.horizon_months + 1):
        monthly_pd  = monthly_pd_base * cnpv_a.pd_seasoning_curve[t - 1]
        el          = balance * monthly_pd * cap_a.lgd_default

        interest     = balance * (apr / 12)
        interchange  = adj_spend * interchange_rate
        fee_income   = annual_fee / 12
        ftp_cost     = balance * (ftp.total_ftp_rate / 12)
        rewards      = adj_spend * rewards_rate
        op_cost      = cnpv_a.monthly_operating_cost_usd

        nri      = interest + interchange + fee_income - ftp_cost - rewards
        net_cf   = nri - el - op_cost
        pv_cf    = net_cf * survival / ((1 + _a.ftp.hurdle_rate / 12) ** t)

        if include_cashflows:
            cashflows.append({
                "month":               t,
                "balance":             round(balance, 2),
                "interest_income":     round(interest, 2),
                "interchange_income":  round(interchange, 2),
                "fee_income":          round(fee_income, 2),
                "ftp_cost":            round(ftp_cost, 2),
                "rewards_cost":        round(rewards, 2),
                "expected_loss":       round(el, 2),
                "operating_cost":      round(op_cost, 2),
                "net_revenue_income":  round(nri, 2),
                "net_cashflow":        round(net_cf, 2),
                "survival_rate":       round(survival, 6),
                "pv_cashflow":         round(pv_cf, 2),
            })

        pv_total  += pv_cf
        survival  *= (1 - monthly_pd) * (1 - monthly_attrition)
        # Balance drifts with scenario-adjusted payment rate
        payment_ratio = 0.25 * scen.payment_rate_mult
        balance = max(0.0, balance * (1 - payment_ratio) + adj_spend * 0.40)
        balance = min(balance, credit_limit)

    roe_3yr    = pv_total / cap.capital_required if cap.capital_required > 0 else 0.0
    cnpv_norm  = pv_total / credit_limit if credit_limit > 0 else 0.0

    # Acquisition signal
    if not cap.can_originate:
        signal = "DECLINE"   # capital constrained
    elif pv_total >= cnpv_a.breakeven_threshold_usd:
        signal = "ACQUIRE"
    elif pv_total >= cnpv_a.acquire_signal_minimum_usd:
        signal = "MANAGE_PRICE"   # marginal — can be improved with APR adjustment
    else:
        signal = "DECLINE"

    # Sensitivity: finite-difference approximation
    sensitivity: dict = {}
    if include_cashflows:
        r_pd  = compute_cnpv(
            credit_limit, annual_pd + 0.01, apr, annual_fee, interchange_rate, rewards_rate,
            monthly_spend, avg_utilisation, acquisition_cost, product_id, bureau_score,
            scenario, cet1_buffer_available, include_cashflows=False,
        )
        r_apr = compute_cnpv(
            credit_limit, annual_pd, apr + 0.01, annual_fee, interchange_rate, rewards_rate,
            monthly_spend, avg_utilisation, acquisition_cost, product_id, bureau_score,
            scenario, cet1_buffer_available, include_cashflows=False,
        )
        sensitivity = {
            "cnpv_per_1pp_pd_increase_usd":     round(r_pd.cnpv  - pv_total, 2),
            "cnpv_per_100bps_apr_increase_usd": round(r_apr.cnpv - pv_total, 2),
        }

    # Recommended APR: binary search for APR where CNPV >= BREAKEVEN_THRESHOLD
    rec_apr = _solve_breakeven_apr(
        credit_limit, annual_pd, annual_fee, interchange_rate, rewards_rate,
        monthly_spend, avg_utilisation, acquisition_cost, product_id,
        bureau_score, scenario, cet1_buffer_available,
    )

    return CNPVResult(
        scenario                = scenario,
        cnpv                    = round(pv_total, 2),
        cnpv_per_dollar_limit   = round(cnpv_norm, 4),
        roe_3yr                 = round(roe_3yr, 4),
        acquisition_signal      = signal,
        recommended_apr         = round(rec_apr, 4),
        recommended_credit_limit = round(credit_limit, 2),
        capital_check           = cap,
        ftp                     = ftp,
        monthly_cashflows       = cashflows,
        sensitivity             = sensitivity,
    )


def _solve_breakeven_apr(
    credit_limit: float,
    annual_pd: float,
    annual_fee: float,
    interchange_rate: float,
    rewards_rate: float,
    monthly_spend: float,
    avg_utilisation: float,
    acquisition_cost: float,
    product_id: str,
    bureau_score: int,
    scenario: ScenarioKey,
    cet1_buffer_available: float,
    target_cnpv: float | None = None,
    max_iter: int = 40,
) -> float:
    """Binary search for the minimum APR that achieves CNPV >= target_cnpv.

    Search is bounded within [8%, 36%] — regulatory safe harbour.
    Converges in ≤ 40 iterations (precision < 0.001 bps).
    If target_cnpv is None, uses the live breakeven_threshold_usd from the
    central assumptions registry.
    """
    if target_cnpv is None:
        target_cnpv = get_assumptions().cnpv.breakeven_threshold_usd
    lo, hi = 0.08, 0.36
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        result = compute_cnpv(
            credit_limit, annual_pd, mid, annual_fee, interchange_rate, rewards_rate,
            monthly_spend, avg_utilisation, acquisition_cost, product_id,
            bureau_score, scenario, cet1_buffer_available, include_cashflows=False,
        )
        if result.cnpv >= target_cnpv:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2
