import unittest
import numpy as np
import pandas as pd

from models.pricing.pricing_optimizer import SLSQPPricingOptimizer, PricingOptimizer
from monitoring.fair_lending import find_less_discriminatory_alternative, LDACandidateResult
from risk_models.ecl_engine import ExposureRecord, MacroScenario, compute_reserve_attribution_waterfall


class TestSprint1Deliverables(unittest.TestCase):

    def test_slsqp_pricing_optimizer_convergence(self):
        optimizer = SLSQPPricingOptimizer(
            wacc=0.08,
            opex_rate=0.015,
            usury_cap=0.36,
            max_line_cap=20000.0,
            max_loss_budget=1000.0,
        )
        res = optimizer.optimize_offer(annual_pd=0.03, lgd=0.85)

        self.assertTrue(res.success)
        self.assertTrue(0.08 <= res.optimal_apr <= 0.36)
        self.assertTrue(500.0 <= res.optimal_credit_limit <= 20000.0)
        self.assertTrue(res.expected_loss <= 1000.0 + 1e-3)
        self.assertIsInstance(res.expected_cnpv, float)

    def test_fair_lending_lda_pareto_search(self):
        np.random.seed(42)
        n = 200
        scores = np.random.uniform(0.1, 0.9, size=n)
        groups = np.random.choice(["white", "black", "hispanic"], size=n, p=[0.5, 0.25, 0.25])

        df = pd.DataFrame({
            "risk_score": scores,
            "demographic_group": groups,
        })

        candidates = find_less_discriminatory_alternative(
            df,
            scores_col="risk_score",
            protected_col="demographic_group",
            control_group="white",
            min_air_threshold=0.75,
        )

        self.assertTrue(len(candidates) > 0)
        self.assertIsInstance(candidates[0], LDACandidateResult)
        self.assertTrue(any(c.air_compliant for c in candidates))

    def test_cecl_reserve_attribution_waterfall(self):
        rec1 = ExposureRecord(
            application_id="app_001",
            product="credit_card",
            outstanding_balance=5000.0,
            credit_limit=10000.0,
            months_on_book=12,
            pd_12m=0.03,
            lgd=0.45,
            ccf=0.50,
            stage=1,
        )
        rec2 = ExposureRecord(
            application_id="app_002",
            product="personal_loan",
            outstanding_balance=12000.0,
            credit_limit=12000.0,
            months_on_book=24,
            pd_12m=0.08,
            lgd=0.50,
            ccf=1.0,
            stage=2,
        )

        opening = [rec1]
        closing = [rec1, rec2]

        scen_base = MacroScenario("base", 1.0, 1.0, 1.0)
        scen_adverse = MacroScenario("adverse", 1.5, 1.2, 1.0)

        waterfall = compute_reserve_attribution_waterfall(
            opening_exposures=opening,
            closing_exposures=closing,
            macro_scenario_t0=scen_base,
            macro_scenario_t1=scen_adverse,
        )

        self.assertTrue(waterfall.opening_reserve > 0)
        self.assertTrue(waterfall.volume_effect > 0)
        self.assertTrue(waterfall.macroeconomic_shift_effect > 0)
        self.assertTrue(waterfall.closing_reserve > waterfall.opening_reserve)
        self.assertEqual(waterfall.plotly_waterfall_json["type"], "waterfall")


if __name__ == "__main__":
    unittest.main()
