from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import numpy as np
from scipy.optimize import minimize
from sklearn.linear_model import Ridge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class DMLElasticityResult:
    causal_elasticity: float
    r2_treatment_model: float
    r2_outcome_model: float
    sample_size: int


class DMLPriceElasticityEstimator:
    """Double Machine Learning (DML) two-stage residualized estimator for causal price elasticity.

    Identifies unconfounded demand sensitivity epsilon = d(Volume) / d(APR)
    from observational rate changes by orthogonalizing against borrower risk covariates X.
    """

    def __init__(self, alpha: float = 1.0) -> None:
        self.model_y = Ridge(alpha=alpha)
        self.model_t = Ridge(alpha=alpha)

    def fit_estimate(
        self,
        X: np.ndarray,
        treatment_apr: np.ndarray,
        outcome_volume: np.ndarray,
    ) -> DMLElasticityResult:
        """Estimate causal price elasticity using two-stage DML residualization."""
        # Stage 1: Partial out confounders X from outcome Y and treatment T
        self.model_y.fit(X, outcome_volume)
        res_y = outcome_volume - self.model_y.predict(X)

        self.model_t.fit(X, treatment_apr)
        res_t = treatment_apr - self.model_t.predict(X)

        # Stage 2: Ordinary Least Squares on orthogonalized residuals
        denom = float(np.sum(res_t ** 2))
        if denom == 0:
            elasticity = -1.5
        else:
            elasticity = float(np.sum(res_t * res_y) / denom)

        return DMLElasticityResult(
            causal_elasticity=round(elasticity, 4),
            r2_treatment_model=round(float(self.model_t.score(X, treatment_apr)), 4),
            r2_outcome_model=round(float(self.model_y.score(X, outcome_volume)), 4),
            sample_size=len(outcome_volume),
        )


@dataclass
class SLSQPOptimizationResult:
    optimal_apr: float
    optimal_credit_limit: float
    expected_cnpv: float
    expected_loss: float
    causal_elasticity_used: float
    status_message: str
    success: bool


class SLSQPPricingOptimizer:
    """Non-linear continuous risk-based pricing & limit optimizer using SciPy SLSQP.

    Objective:
        Maximize Expected CNPV(APR, Limit) =
            Limit * DemandMultiplier(APR, elasticity) * [ APR + Interchange - FTP - OpEx - (PD * LGD) ]

    Constraints:
        1. APR >= WACC + OpEx + Risk Spread
        2. APR <= Max Usury Cap (e.g. 36%)
        3. Limit <= Max Allowed Line Cap (e.g. 25,000)
        4. Limit * (PD * LGD) <= Max Loss Budget
    """

    def __init__(
        self,
        wacc: float = 0.08,
        opex_rate: float = 0.015,
        ftp_rate: float = 0.05,
        interchange_rate: float = 0.018,
        usury_cap: float = 0.36,
        max_line_cap: float = 25000.0,
        max_loss_budget: float = 1500.0,
        dml_estimator: Optional[DMLPriceElasticityEstimator] = None,
    ) -> None:
        self.wacc = wacc
        self.opex_rate = opex_rate
        self.ftp_rate = ftp_rate
        self.interchange_rate = interchange_rate
        self.usury_cap = usury_cap
        self.max_line_cap = max_line_cap
        self.max_loss_budget = max_loss_budget
        self.dml_estimator = dml_estimator or DMLPriceElasticityEstimator()

    def optimize_offer(
        self,
        annual_pd: float,
        lgd: float = 0.85,
        initial_apr: float = 0.18,
        initial_limit: float = 5000.0,
        causal_elasticity: float = -1.5,
    ) -> SLSQPOptimizationResult:
        """Solve for continuous (APR, Credit_Limit) that maximizes expected CNPV."""
        el_rate = annual_pd * lgd

        # Objective function with demand elasticity response multiplier
        def objective(x: np.ndarray) -> float:
            apr, limit = x[0], x[1]
            net_margin = apr + self.interchange_rate - self.ftp_rate - self.opex_rate - el_rate
            # Demand multiplier: 1 + elasticity * (apr - initial_apr)
            demand_mult = max(0.1, 1.0 + causal_elasticity * (apr - initial_apr))
            expected_cnpv = limit * demand_mult * net_margin
            return -expected_cnpv


        # Constraint 1: Minimum APR hurdle
        min_apr_hurdle = self.wacc + self.opex_rate + (el_rate * 0.5)
        cons = [
            {"type": "ineq", "fun": lambda x: x[0] - min_apr_hurdle},  # APR >= min_apr_hurdle
            {"type": "ineq", "fun": lambda x: self.max_loss_budget - (x[1] * el_rate)},  # Loss <= Budget
        ]

        bounds = [
            (min_apr_hurdle, self.usury_cap),
            (500.0, self.max_line_cap),
        ]

        x0 = np.array([initial_apr, initial_limit])
        res = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=cons)

        opt_apr = float(res.x[0])
        opt_limit = float(res.x[1])
        opt_cnpv = float(-res.fun)
        opt_el = opt_limit * el_rate

        return SLSQPOptimizationResult(
            optimal_apr=round(opt_apr, 4),
            optimal_credit_limit=round(opt_limit, 2),
            expected_cnpv=round(opt_cnpv, 2),
            expected_loss=round(opt_el, 2),
            causal_elasticity_used=round(causal_elasticity, 4),
            status_message=str(res.message),
            success=bool(res.success),
        )



class PricingOptimizer:
    def __init__(self, tenant_id: str = "lending_club") -> None:
        policy_path = f"config/{tenant_id}_policy.json"
        if os.path.exists(policy_path):
            with open(policy_path, "r") as f:
                self.policy = json.load(f)
            self.wacc = self.policy["pricing_rules"]["WACC"]
            self.opex_bps = self.policy["pricing_rules"]["operational_cost_bps"]
            self.target_roa = self.policy["risk_appetite"]["target_roa"]
        else:
            self.wacc = 0.08
            self.opex_bps = 150.0
            self.target_roa = 0.02

        self.tenant_id = tenant_id
        self.slsqp_solver = SLSQPPricingOptimizer(wacc=self.wacc)

    def calculate_expected_loss(self, loan_amount: float, pd: float, ead_ratio: float, lgd: float) -> float:
        return pd * loan_amount * ead_ratio * lgd

    def calculate_interest_rate(self, loan_amount: float, pd: float, ead_ratio: float, lgd: float) -> float:
        el_dollars = self.calculate_expected_loss(loan_amount, pd, ead_ratio, lgd)
        el_ratio = el_dollars / loan_amount
        base_rate = self.wacc + (self.opex_bps / 10000.0) + self.target_roa
        required_rate = base_rate + el_ratio
        return round(required_rate * 100, 2)

    def grade_pricing_table(self) -> None:
        logger.info("Generating Pricing Table by Grade for %s...", self.tenant_id)
        grades = ["A", "B", "C", "D", "E"]
        pds = [0.02, 0.05, 0.10, 0.18, 0.30]
        lgd = 0.85
        ead_ratio = 1.0

        print(f"{'Grade':<10} {'Avg PD':<10} {'Expected Loss Ratio':<20} {'Recommended Rate (%)':<20}")
        print("-" * 65)

        for g, pd in zip(grades, pds):
            el_ratio = pd * ead_ratio * lgd
            rate = self.wacc + (self.opex_bps / 10000.0) + self.target_roa + el_ratio
            rate_pct = round(rate * 100, 2)
            print(f"{g:<10} {pd:<10.2%} {el_ratio:<20.2%} {rate_pct:<20.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant_id", type=str, default="lending_club")
    args = parser.parse_args()
    optimizer = PricingOptimizer(tenant_id=args.tenant_id)
    optimizer.grade_pricing_table()

    slsqp = SLSQPPricingOptimizer()
    res = slsqp.optimize_offer(annual_pd=0.03, lgd=0.85)
    print("\n--- SLSQP Profit Optimization Result ---")
    print(f"Optimal APR: {res.optimal_apr:.2%}")
    print(f"Optimal Credit Limit: ${res.optimal_credit_limit:,.2f}")
    print(f"Expected CNPV: ${res.expected_cnpv:,.2f}")
    print(f"Status: {res.status_message}")
