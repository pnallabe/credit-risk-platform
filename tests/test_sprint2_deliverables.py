import unittest
import numpy as np
import pandas as pd

from compliance.commercial_document_parser import CommercialDocumentParser, CommercialFinancialSpreading
from agents.credit_analyst_agent import CreditAnalystAgent
from models.pricing.pricing_optimizer import DMLPriceElasticityEstimator, SLSQPPricingOptimizer
from models.credit_risk.lgd_model import TwoStageHurdleLGDModel


class TestSprint2Deliverables(unittest.TestCase):

    def test_commercial_document_parser_spreading(self):
        parser = CommercialDocumentParser()
        raw_doc = {
            "entity_name": "Apex Industrial Logistics LLC",
            "tax_id": "84-1234567",
            "fiscal_year": 2025,
            "gross_receipts_sales": 5400000.0,
            "cost_of_goods_sold": 3200000.0,
            "operating_expenses": 1400000.0,
            "net_taxable_income": 800000.0,
            "depreciation": 150000.0,
            "interest_expense": 50000.0,
            "total_assets": 4500000.0,
            "total_debt": 1800000.0,
            "annual_debt_service": 250000.0,
        }
        spreading = parser.parse_tax_return(raw_doc, form_type="1120-S")

        self.assertIsInstance(spreading, CommercialFinancialSpreading)
        self.assertEqual(spreading.entity_name, "Apex Industrial Logistics LLC")
        self.assertEqual(spreading.ebitda, 1000000.0)  # 800k + 150k + 50k
        self.assertEqual(spreading.dscr, 4.0)  # 1,000,000 / 250,000

        # Test CreditAnalystAgent memo generation
        agent = CreditAnalystAgent()
        memo = agent.generate_commercial_credit_memo(spreading, requested_loan_amount=500000.0)

        self.assertIn("COMMERCIAL CREDIT UNDERWRITING MEMO", memo["title"])
        self.assertEqual(memo["credit_recommendation"]["recommendation"], "APPROVE")

    def test_dml_causal_price_elasticity_estimator(self):
        np.random.seed(42)
        n = 150
        X = np.random.normal(0, 1, size=(n, 3))
        # Treatment APR: function of X + noise
        treatment = 0.15 + 0.02 * X[:, 0] + np.random.normal(0, 0.01, size=n)
        # Outcome Volume: true elasticity -2.0 * treatment + 5.0 * X[:, 0] + noise
        outcome = 1000.0 - 2000.0 * (treatment - 0.15) + 100.0 * X[:, 0] + np.random.normal(0, 5, size=n)

        dml = DMLPriceElasticityEstimator()
        result = dml.fit_estimate(X, treatment, outcome)

        self.assertTrue(result.sample_size == 150)
        self.assertIsInstance(result.causal_elasticity, float)

        # Test SLSQPPricingOptimizer with elasticity
        optimizer = SLSQPPricingOptimizer(dml_estimator=dml)
        res = optimizer.optimize_offer(annual_pd=0.04, causal_elasticity=result.causal_elasticity)

        self.assertTrue(res.success)
        self.assertTrue(0.08 <= res.optimal_apr <= 0.36)

    def test_two_stage_hurdle_lgd_model(self):
        np.random.seed(42)
        n = 200
        X = np.random.normal(0, 1, size=(n, 4))
        # Simulate LGD with zeros (no-loss) and non-zero severities
        prob_loss = 1.0 / (1.0 + np.exp(- (0.5 * X[:, 0] - 0.2)))
        loss_occurred = np.random.binomial(1, prob_loss)
        severity = np.clip(0.3 + 0.2 * X[:, 1] + np.random.normal(0, 0.05, size=n), 0.05, 0.95)
        y = loss_occurred * severity

        lgd_model = TwoStageHurdleLGDModel(apply_basel_floor=True, basel_floor=0.45)
        lgd_model.fit(X, y)

        preds_unsecured = lgd_model.predict(X, is_unsecured=True)
        preds_secured = lgd_model.predict(X, is_unsecured=False)

        self.assertTrue(np.all(preds_unsecured >= 0.45))  # Enforces 45% floor
        self.assertTrue(np.all(preds_secured >= 0.0))
        self.assertTrue(np.all(preds_secured <= 1.0))


if __name__ == "__main__":
    unittest.main()
