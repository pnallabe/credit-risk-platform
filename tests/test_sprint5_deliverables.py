import unittest
import numpy as np

from risk_models.alm_engine import (
    CashFlowBucket,
    DepositBetaModel,
    EVEResult,
    EVESensitivityEngine,
    NIIAtRiskEngine,
    NIIResult,
)


class TestSprint5Deliverables(unittest.TestCase):

    def test_deposit_beta_estimation(self):
        np.random.seed(42)
        delta_mkt = np.array([50.0, 100.0, -25.0, 75.0, -50.0])
        delta_dep = np.array([20.0, 45.0, -10.0, 30.0, -22.0])

        model = DepositBetaModel()
        model.fit(delta_mkt, delta_dep)

        self.assertTrue(0.35 <= model.beta <= 0.55)
        predicted_dep_change = model.predict_deposit_rate_change(200.0)
        self.assertAlmostEqual(predicted_dep_change, model.beta * 200.0, places=4)

    def test_eve_sensitivity_rate_shocks(self):
        cash_flows = [
            CashFlowBucket(
                maturity_months=12,
                asset_cash_flow=100000.0,
                liability_cash_flow=80000.0,
                asset_weighted_rate=0.07,
                liability_weighted_rate=0.03,
            ),
            CashFlowBucket(
                maturity_months=36,
                asset_cash_flow=200000.0,
                liability_cash_flow=150000.0,
                asset_weighted_rate=0.075,
                liability_weighted_rate=0.035,
            ),
        ]

        engine = EVESensitivityEngine(discount_rate_base=0.05)
        result = engine.compute_eve_sensitivity(cash_flows, rate_shock_bps=200.0, scenario_name="UP_200BPS")

        self.assertIsInstance(result, EVEResult)
        self.assertTrue(result.base_eve > 0)
        self.assertTrue(result.shocked_eve > 0)
        self.assertEqual(result.rate_shock_bps, 200)
        self.assertIsInstance(result.delta_eve_pct, float)

    def test_nii_at_risk_calculation(self):
        beta_model = DepositBetaModel(default_beta=0.45)
        nii_engine = NIIAtRiskEngine(deposit_beta_model=beta_model)

        result = nii_engine.compute_nii_at_risk(
            total_assets=10000000.0,
            total_liabilities=8000000.0,
            asset_yield_base=0.07,
            liability_cost_base=0.03,
            rate_shock_bps=200.0,
            scenario_name="UP_200BPS",
        )

        self.assertIsInstance(result, NIIResult)
        self.assertTrue(result.base_nii_12m == 460000.0)  # (10M * 0.07) - (8M * 0.03) = 700k - 240k = 460k
        self.assertEqual(result.rate_shock_bps, 200)
        self.assertIsInstance(result.nii_at_risk_amount, float)


if __name__ == "__main__":
    unittest.main()
