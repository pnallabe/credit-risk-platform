import time
import unittest
import numpy as np

from decision_engine.collections_engine import (
    CausalUpliftModel,
    RegFContactGuard,
    SettlementCopilot,
    TreatmentRecommendation,
    SettlementOffer,
)


class TestSprint4Deliverables(unittest.TestCase):

    def test_causal_uplift_model_allocation(self):
        np.random.seed(42)
        n = 100
        X = np.random.normal(0, 1, size=(n, 3))
        treatment = np.random.binomial(1, 0.5, size=n)
        # Outcome recovery: higher for treatment group
        y_recovery = 0.2 * treatment + 0.1 * X[:, 0] + np.random.normal(0, 0.05, size=n)

        model = CausalUpliftModel()
        model.fit(X, treatment, y_recovery)

        sample_x = np.array([0.5, 1.0, -0.2])
        rec = model.allocate_treatment("acc_100", sample_x, dpd=60)

        self.assertIsInstance(rec, TreatmentRecommendation)
        self.assertIn(rec.recommended_treatment, ["CALL", "SMS", "EMAIL", "SELF_CURE"])
        self.assertIsInstance(rec.estimated_uplift, float)

    def test_reg_f_contact_guard_limits(self):
        guard = RegFContactGuard(max_calls_per_7d=7)
        now = time.time()

        # 1. Test permissible hours check (outside window: 7:00 AM)
        res_early = guard.can_call_borrower("acc_200", now, local_hour=7)
        self.assertFalse(res_early.allowed)
        self.assertEqual(res_early.reason, "OUTSIDE_PERMISSIBLE_HOURS_REG_F")

        # 2. Test permissible call (10:00 AM)
        res_ok = guard.can_call_borrower("acc_200", now, local_hour=10)
        self.assertTrue(res_ok.allowed)

        # 3. Simulate 7 call attempts within past 3 days
        for i in range(7):
            guard.record_call_attempt("acc_200", now - (i * 3600))

        res_exceeded = guard.can_call_borrower("acc_200", now, local_hour=14)
        self.assertFalse(res_exceeded.allowed)
        self.assertEqual(res_exceeded.reason, "REG_F_7_CALL_ATTEMPTS_EXCEEDED")
        self.assertEqual(res_exceeded.call_attempts_last_7d, 7)

    def test_settlement_copilot_offers(self):
        copilot = SettlementCopilot()
        offer = copilot.generate_offer("acc_300", balance=10000.0, dpd=120)

        self.assertIsInstance(offer, SettlementOffer)
        self.assertEqual(offer.dpd, 120)
        self.assertEqual(offer.lump_sum_discount_pct, 45.0)
        self.assertEqual(offer.lump_sum_offer, 5500.0)  # 10,000 * 0.55
        self.assertTrue(offer.npv_recovery_expectation > 0)


if __name__ == "__main__":
    unittest.main()
