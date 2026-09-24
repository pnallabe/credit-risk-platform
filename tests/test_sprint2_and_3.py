"""
Sprint 2 & 3 Test Suite
========================
Validates:
1. Stream Fraud Engine + Mule Network Analyzer + KafkaStreamFraudConsumer.
2. CausalForestUpliftEngine multi-treatment allocation & RegFContactGuard timezone rules.
3. BehavioralDepositDecayModel log-logistic deposit runoff curves & yield curve shocks.
4. CompetitorRateScraper market APR benchmark microservice.
5. LangGraphStateEngine multi-agent state machine workflow execution.
"""

import pytest
import numpy as np
import time

from models.fraud_detection.stream_fraud_engine import (
    StreamFraudEngine,
    TransactionEvent,
    MuleNetworkAnalyzer,
    KafkaStreamFraudConsumer,
)
from decision_engine.collections_engine import (
    CausalForestUpliftEngine,
    RegFContactGuard,
    TreatmentRecommendation,
)
from risk_models.alm_engine import (
    BehavioralDepositDecayModel,
    EVESensitivityEngine,
    CashFlowBucket,
)
from models.pricing.pricing_optimizer import (
    CompetitorRateScraper,
    CompetitorRateBenchmark,
)
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "ai-agent"))

from src.langgraph_orchestrator import (
    LangGraphStateEngine,
    AgentGraphState,
)


def test_stream_fraud_and_mule_clustering():
    mule_analyzer = MuleNetworkAnalyzer()
    # Create mule network structure: Mule Hub "MULE_01" receiving transfers from multiple senders
    mule_analyzer.add_transfer("SENDER_A", "MULE_01", 3000.0)
    mule_analyzer.add_transfer("SENDER_B", "MULE_01", 4500.0)
    mule_analyzer.add_transfer("SENDER_C", "MULE_01", 5000.0)
    mule_analyzer.add_transfer("MULE_01", "RECIPIENT_OUT", 12500.0)

    engine = StreamFraudEngine(mule_analyzer=mule_analyzer)
    consumer = KafkaStreamFraudConsumer(fraud_engine=engine)

    # Event involving mule hub
    event = TransactionEvent(
        transaction_id="TX_1001",
        sender_account_id="SENDER_D",
        recipient_account_id="MULE_01",
        amount=6000.0,
        timestamp=time.time(),
    )

    results = consumer.consume_stream([event])

    assert len(results) == 1
    res = results[0]
    assert res.mule_cluster_flag is True
    assert "MULE_NETWORK_CLUSTER_DETECTED" in res.reason_codes
    assert res.action in ["REVIEW", "REJECT"]


def test_causal_forest_uplift_and_reg_f_timezones():
    # Causal Forest Uplift Engine
    engine = CausalForestUpliftEngine()
    X_train = np.random.randn(30, 4)
    labels = ["SELF_CURE"] * 6 + ["EMAIL"] * 6 + ["SMS"] * 6 + ["CALL"] * 6 + ["SETTLEMENT_OFFER"] * 6
    y_rec = np.random.uniform(100, 1000, 30)

    engine.fit(X_train, labels, y_rec)
    rec = engine.predict_optimal_treatment("ACC_123", np.random.randn(4), dpd=45)

    assert isinstance(rec, TreatmentRecommendation)
    assert rec.recommended_treatment in engine.treatments

    # Reg F Contact Guard with Timezone Validation
    guard = RegFContactGuard(max_calls_per_7d=7)
    now = time.time()

    # Outside permissible hours (e.g. 10:00 PM EST -> local PST 7:00 PM OK, but local EST 10:00 PM Fail)
    res_late = guard.can_call_borrower("ACC_123", now, local_hour=22, timezone_code="EST")
    assert res_late.allowed is False

    # Within permissible hours (2:00 PM EST)
    res_ok = guard.can_call_borrower("ACC_123", now, local_hour=14, timezone_code="EST")
    assert res_ok.allowed is True


def test_behavioral_deposit_decay_model():
    model = BehavioralDepositDecayModel(base_annual_decay_rate=0.12, alpha_shape=1.5)
    curve = model.compute_runoff_curve(initial_deposit_balance=1_000_000.0, rate_shock_bps=200.0, projection_months=60)

    assert len(curve) == 60
    assert curve[0].remaining_balance_pct > curve[59].remaining_balance_pct
    assert curve[59].cumulative_runoff_amount > 0.0


def test_competitor_rate_scraper():
    scraper = CompetitorRateScraper()
    benchmarks = scraper.fetch_market_benchmarks("CREDIT_CARD")

    assert len(benchmarks) >= 4
    avg_apr = scraper.get_market_average_apr("CREDIT_CARD")
    assert 18.0 <= avg_apr <= 28.0


def test_langgraph_state_engine():
    engine = LangGraphStateEngine()
    state = engine.run_workflow("Analyze portfolio disparate impact for 2025 approvals", user_role="RISK_OFFICER")

    assert isinstance(state, AgentGraphState)
    assert len(state.node_history) == 4
    assert state.node_history == ["planner", "specialist_execution", "compliance_gate", "synthesizer"]
    assert state.compliance_passed is True
    assert "Executive Underwriting Analysis" in state.final_answer
