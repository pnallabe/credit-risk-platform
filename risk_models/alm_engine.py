from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CashFlowBucket:
    maturity_months: int
    asset_cash_flow: float
    liability_cash_flow: float
    asset_weighted_rate: float
    liability_weighted_rate: float


@dataclass
class EVEResult:
    scenario_name: str
    rate_shock_bps: int
    base_eve: float
    shocked_eve: float
    delta_eve_amount: float
    delta_eve_pct: float


@dataclass
class NIIResult:
    scenario_name: str
    rate_shock_bps: int
    base_nii_12m: float
    shocked_nii_12m: float
    nii_at_risk_amount: float
    nii_at_risk_pct: float


class DepositBetaModel:
    """Empirical Deposit Beta Model estimating deposit rate pass-through lag:
    Delta(r_deposit) = beta * Delta(r_market)
    """

    def __init__(self, default_beta: float = 0.45) -> None:
        self.beta = default_beta
        self._is_fitted = False

    def fit(self, delta_market_rate: np.ndarray, delta_deposit_rate: np.ndarray) -> DepositBetaModel:
        """Estimate empirical deposit beta via OLS regression."""
        delta_mkt = np.asarray(delta_market_rate, dtype=float)
        delta_dep = np.asarray(delta_deposit_rate, dtype=float)

        denom = float(np.sum(delta_mkt ** 2))
        if denom > 0:
            self.beta = float(np.sum(delta_mkt * delta_dep) / denom)
            self.beta = float(np.clip(self.beta, 0.05, 0.95))
            self._is_fitted = True
        return self

    def predict_deposit_rate_change(self, delta_market_bps: float) -> float:
        """Predict deposit rate change in bps given market rate change in bps."""
        return self.beta * delta_market_bps


class EVESensitivityEngine:
    """Economic Value of Equity (EVE) Sensitivity & Interest Rate Stress Testing Engine."""

    def __init__(self, discount_rate_base: float = 0.05) -> None:
        self.discount_rate_base = discount_rate_base

    def _pv_cash_flows(self, cash_flows: List[CashFlowBucket], rate_shock_bps: float, is_asset: bool) -> float:
        rate_shock_decimal = rate_shock_bps / 10000.0
        pv_sum = 0.0

        for b in cash_flows:
            cf = b.asset_cash_flow if is_asset else b.liability_cash_flow
            t_years = b.maturity_months / 12.0
            r = self.discount_rate_base + rate_shock_decimal
            pv = cf / ((1.0 + r) ** t_years)
            pv_sum += pv

        return pv_sum

    def compute_eve_sensitivity(
        self,
        cash_flows: List[CashFlowBucket],
        rate_shock_bps: float,
        scenario_name: str = "UP_200BPS",
    ) -> EVEResult:
        """Compute EVE sensitivity under a given rate shock scenario."""
        # Base EVE = PV(Assets) - PV(Liabilities)
        pv_assets_base = self._pv_cash_flows(cash_flows, 0.0, is_asset=True)
        pv_liab_base = self._pv_cash_flows(cash_flows, 0.0, is_asset=False)
        base_eve = pv_assets_base - pv_liab_base

        # Shocked EVE
        pv_assets_shocked = self._pv_cash_flows(cash_flows, rate_shock_bps, is_asset=True)
        pv_liab_shocked = self._pv_cash_flows(cash_flows, rate_shock_bps, is_asset=False)
        shocked_eve = pv_assets_shocked - pv_liab_shocked

        delta_eve = shocked_eve - base_eve
        delta_pct = (delta_eve / base_eve) * 100.0 if base_eve > 0 else 0.0

        return EVEResult(
            scenario_name=scenario_name,
            rate_shock_bps=int(rate_shock_bps),
            base_eve=round(base_eve, 2),
            shocked_eve=round(shocked_eve, 2),
            delta_eve_amount=round(delta_eve, 2),
            delta_eve_pct=round(delta_pct, 2),
        )


class NIIAtRiskEngine:
    """12-Month Net Interest Income (NII) at Risk Engine incorporating Deposit Beta."""

    def __init__(self, deposit_beta_model: Optional[DepositBetaModel] = None) -> None:
        self.beta_model = deposit_beta_model or DepositBetaModel(default_beta=0.45)

    def compute_nii_at_risk(
        self,
        total_assets: float,
        total_liabilities: float,
        asset_yield_base: float = 0.07,
        liability_cost_base: float = 0.03,
        rate_shock_bps: float = 200.0,
        scenario_name: str = "UP_200BPS",
    ) -> NIIResult:
        """Compute 12-month NII at risk under parallel rate shock."""
        # Base 12-month NII
        base_nii = (total_assets * asset_yield_base) - (total_liabilities * liability_cost_base)

        rate_shock_dec = rate_shock_bps / 10000.0
        deposit_shock_bps = self.beta_model.predict_deposit_rate_change(rate_shock_bps)
        deposit_shock_dec = deposit_shock_bps / 10000.0

        shocked_asset_yield = asset_yield_base + rate_shock_dec
        shocked_liability_cost = liability_cost_base + deposit_shock_dec

        shocked_nii = (total_assets * shocked_asset_yield) - (total_liabilities * shocked_liability_cost)
        nii_delta = shocked_nii - base_nii
        nii_at_risk_pct = (nii_delta / base_nii) * 100.0 if base_nii > 0 else 0.0

        return NIIResult(
            scenario_name=scenario_name,
            rate_shock_bps=int(rate_shock_bps),
            base_nii_12m=round(base_nii, 2),
            shocked_nii_12m=round(shocked_nii, 2),
            nii_at_risk_amount=round(-nii_delta, 2),  # Positive value indicates risk amount
            nii_at_risk_pct=round(nii_at_risk_pct, 2),
        )
