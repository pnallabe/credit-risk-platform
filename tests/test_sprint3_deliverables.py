import time
import unittest

from compliance.fincen_sar_agent import FinCENSARAgent, FinCENSARFilingPackage
from models.fraud_detection.stream_fraud_engine import (
    FraudScoreResult,
    MuleNetworkAnalyzer,
    StreamFraudEngine,
    TransactionEvent,
)


class TestSprint3Deliverables(unittest.TestCase):

    def test_stream_fraud_engine_velocity_scoring(self):
        engine = StreamFraudEngine(reject_threshold=0.65, review_threshold=0.35)
        now = time.time()

        # Send rapid velocity transfers from same sender to 4 different recipients
        events = [
            TransactionEvent(f"tx_00{i}", "acc_sender_100", f"acc_recip_{i}", 2500.0, now + i)
            for i in range(5)
        ]

        results = [engine.evaluate_transaction(e) for e in events]
        last_res = results[-1]

        self.assertIsInstance(last_res, FraudScoreResult)
        self.assertTrue(last_res.latency_ms < 50.0)  # Sub-50ms latency target
        self.assertTrue(last_res.app_scam_flag)
        self.assertEqual(last_res.action, "REJECT")
        self.assertIn("APP_PUSH_PAYMENT_SCAM_PATTERN", last_res.reason_codes)

    def test_mule_network_analyzer_cycle_detection(self):
        analyzer = MuleNetworkAnalyzer()

        # Build a circular transfer loop: acc_A -> acc_B -> acc_C -> acc_A
        analyzer.add_transfer("acc_A", "acc_B", 5000.0)
        analyzer.add_transfer("acc_B", "acc_C", 4800.0)
        analyzer.add_transfer("acc_C", "acc_A", 4600.0)

        # Build a high-in-degree mule hub: acc_X, acc_Y, acc_Z -> acc_MULE -> acc_OUT
        analyzer.add_transfer("acc_X", "acc_MULE", 1000.0)
        analyzer.add_transfer("acc_Y", "acc_MULE", 1500.0)
        analyzer.add_transfer("acc_Z", "acc_MULE", 2000.0)
        analyzer.add_transfer("acc_MULE", "acc_OUT", 4300.0)

        result = analyzer.detect_mule_clusters(min_in_degree=3)

        self.assertIn("acc_MULE", result.mule_account_ids)
        self.assertTrue(len(result.circular_loops_detected) > 0)
        self.assertTrue(result.total_suspicious_volume > 0)

    def test_fincen_sar_agent_drafting(self):
        agent = FinCENSARAgent()

        subject_data = {
            "name": "Johnathan Doe",
            "tax_id": "999-12-3456",
            "city": "Chicago",
            "state": "IL",
        }

        flagged_txs = [
            {"transaction_id": "tx_001", "amount": 5000.0},
            {"transaction_id": "tx_002", "amount": 7500.0},
        ]

        dummy_fraud_res = FraudScoreResult(
            transaction_id="tx_002",
            fraud_score=0.85,
            action="REJECT",
            velocity_1m_count=5,
            velocity_5m_count=5,
            velocity_1h_count=5,
            app_scam_flag=True,
            mule_cluster_flag=False,
            reason_codes=["APP_PUSH_PAYMENT_SCAM_PATTERN"],
            latency_ms=1.2,
        )

        sar_pkg = agent.draft_sar_filing(subject_data, flagged_txs, dummy_fraud_res)

        self.assertIsInstance(sar_pkg, FinCENSARFilingPackage)
        self.assertTrue(sar_pkg.sar_tracking_id.startswith("SAR-"))
        self.assertEqual(sar_pkg.activity_detail.activity_type, "APP_PUSH_PAYMENT_SCAM")
        self.assertEqual(sar_pkg.activity_detail.total_amount_involved, 12500.0)
        self.assertIn("SUMMARY OF SUSPICIOUS ACTIVITY", sar_pkg.activity_detail.narrative_summary)


if __name__ == "__main__":
    unittest.main()
