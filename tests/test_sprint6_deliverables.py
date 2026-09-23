import unittest

from compliance.corporate_kyc_engine import (
    AdverseMediaNLPClassifier,
    AdverseMediaResult,
    BeneficialOwner,
    FuzzySanctionsScreener,
    SanctionsMatchResult,
    UBOGraphTraversalEngine,
    UBOTraversalResult,
)


class TestSprint6Deliverables(unittest.TestCase):

    def test_ubo_graph_traversal_25pct_rule(self):
        engine = UBOGraphTraversalEngine(ubo_threshold_pct=25.0)

        # Set node attributes for natural persons
        engine.graph.add_node("Alice Smith", is_natural_person=True)
        engine.graph.add_node("Bob Jones", is_natural_person=True)

        # Multi-tier ownership structure:
        # Alice Smith (60%) -> Holding Co A (50%) -> Target Corp LLC  => Effective: 30% (Natural Person >= 25%)
        # Bob Jones (30%) -> Holding Co A (50%) -> Target Corp LLC    => Effective: 15% (Natural Person < 25%)
        engine.add_ownership_stake("Alice Smith", "Holding Co A", ownership_pct=60.0, is_natural_person=True)
        engine.add_ownership_stake("Bob Jones", "Holding Co A", ownership_pct=30.0, is_natural_person=True)
        engine.add_ownership_stake("Holding Co A", "Target Corp LLC", ownership_pct=50.0, is_natural_person=False)

        res = engine.resolve_ubos("Target Corp LLC")

        self.assertIsInstance(res, UBOTraversalResult)
        self.assertEqual(res.target_entity, "Target Corp LLC")
        self.assertTrue(len(res.ultimate_beneficial_owners) >= 1)

        # Find Alice Smith's UBO result
        alice_ubo = next((u for u in res.ultimate_beneficial_owners if u.name == "Alice Smith"), None)
        self.assertIsNotNone(alice_ubo)
        self.assertEqual(alice_ubo.effective_ownership_pct, 30.0)
        self.assertTrue(alice_ubo.requires_cdd_verification)  # 30% >= 25% threshold

        # Find Bob Jones's UBO result
        bob_ubo = next((u for u in res.ultimate_beneficial_owners if u.name == "Bob Jones"), None)
        self.assertIsNotNone(bob_ubo)
        self.assertEqual(bob_ubo.effective_ownership_pct, 15.0)
        self.assertFalse(bob_ubo.requires_cdd_verification)  # 15% < 25% threshold

    def test_fuzzy_sanctions_screening_jaro_winkler(self):
        screener = FuzzySanctionsScreener(match_threshold=0.85)

        # Test exact match
        res_exact = screener.screen_name("VLADIMIR PETROV")
        self.assertTrue(res_exact.match_found)
        self.assertEqual(res_exact.match_score, 1.0)

        # Test fuzzy match with typo (Vladimir Petrof -> Vladimir Petrov)
        res_fuzzy = screener.screen_name("Vladimir Petrof")
        self.assertTrue(res_fuzzy.match_found)
        self.assertTrue(res_fuzzy.match_score >= 0.85)

        # Test clean name (John Smith)
        res_clean = screener.screen_name("John Smith")
        self.assertFalse(res_clean.match_found)

    def test_adverse_media_nlp_classification(self):
        classifier = AdverseMediaNLPClassifier()

        # Test money laundering headline
        headline_ml = "Regulators investigate offshore shell company involved in massive money laundering scheme"
        res_ml = classifier.classify_headline(headline_ml)

        self.assertIsInstance(res_ml, AdverseMediaResult)
        self.assertTrue(res_ml.flagged)
        self.assertEqual(res_ml.risk_category, "MONEY_LAUNDERING")

        # Test clean headline
        headline_clean = "Tech startup raises Series B funding to expand AI underwriting team"
        res_clean = classifier.classify_headline(headline_clean)

        self.assertFalse(res_clean.flagged)
        self.assertEqual(res_clean.risk_category, "CLEAN")


if __name__ == "__main__":
    unittest.main()
