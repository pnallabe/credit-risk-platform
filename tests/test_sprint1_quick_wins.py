"""
Sprint 1 Quick Wins Test Suite
================================
Validates:
1. Commercial Document Parser (IRS 1120-S regex/LLM line item extraction & MCA debt-stacking detection).
2. Multi-objective Pareto Frontier LDA Search in Fair Lending.
3. Live Sanctions & PEP screening engine with TTL caching and alias matching.
"""

import pytest
import pandas as pd
import numpy as np

from compliance.commercial_document_parser import (
    CommercialDocumentParser,
    CommercialFinancialSpreading,
    MCADebtStackingResult,
)
from monitoring.fair_lending import (
    find_less_discriminatory_alternative,
    ParetoLDASearchEngine,
    LDACandidateResult,
)
from compliance.corporate_kyc_engine import (
    LiveSanctionsScreeningEngine,
    FuzzySanctionsScreener,
    SanctionsMatchResult,
)


def test_commercial_document_parser_regex():
    parser = CommercialDocumentParser()
    sample_text = """
    Name of Corporation: APEX MANUFACTURING INC.
    EIN: 12-3456789
    Form 1120-S (2025)
    Line 1a Gross receipts or sales: $4,500,000.00
    Line 2 Cost of goods sold: $2,100,000.00
    Line 7 Compensation of officers: $350,000.00
    Line 14 Depreciation: $120,000.00
    Line 21 Ordinary business income: $680,000.00
    Total Assets: $3,200,000.00
    Total Liabilities: $1,400,000.00
    """
    res = parser.parse_document_with_llm_vision(sample_text, form_type="1120-S", use_llm=False)

    assert isinstance(res, CommercialFinancialSpreading)
    assert res.entity_name == "APEX MANUFACTURING INC."
    assert res.tax_id == "12-3456789"
    assert res.gross_receipts_sales == 4500000.0
    assert res.cost_of_goods_sold == 2100000.0
    assert res.gross_profit == 2400000.0
    assert res.officer_compensation == 350000.0
    assert res.net_taxable_income == 680000.0
    assert res.ebitda > 0
    assert res.dscr > 1.0


def test_mca_debt_stacking_detection():
    parser = CommercialDocumentParser()
    sample_bank_txs = [
        {"date": "2026-09-01", "description": "ACH DEBIT - KABBAGE DAILY PAY", "amount": -450.00, "type": "debit"},
        {"date": "2026-09-02", "description": "ACH DEBIT - KABBAGE DAILY PAY", "amount": -450.00, "type": "debit"},
        {"date": "2026-09-01", "description": "ONDECK CAPITAL DAILY ACH", "amount": -320.00, "type": "debit"},
        {"date": "2026-09-02", "description": "ONDECK CAPITAL DAILY ACH", "amount": -320.00, "type": "debit"},
        {"date": "2026-09-01", "description": "FUNDBOX ACH WITHDRAWAL", "amount": -280.00, "type": "debit"},
        {"date": "2026-09-02", "description": "FUNDBOX ACH WITHDRAWAL", "amount": -280.00, "type": "debit"},
    ]

    res = parser.detect_mca_debt_stacking(sample_bank_txs, monthly_revenue=40000.0)

    assert isinstance(res, MCADebtStackingResult)
    assert res.mca_detected is True
    assert res.concurrent_mca_count == 3
    assert "KABBAGE" in res.flagged_funders
    assert "ONDECK" in res.flagged_funders
    assert "FUNDBOX" in res.flagged_funders
    assert res.risk_level in ["HIGH", "CRITICAL"]
    assert res.mca_debt_service_strain_ratio > 0.20


def test_mca_remediations_routine_exclusions_and_multi_positions():
    parser = CommercialDocumentParser()
    sample_bank_txs = [
        # Routine business transactions (should be excluded)
        {"date": "2026-09-01", "description": "GUSTO PAYROLL ACH DEBIT", "amount": 12000.00, "type": "debit"},
        {"date": "2026-09-01", "description": "IRS TAX PAYMENT ACH DEBIT", "amount": 3500.00, "type": "debit"},
        {"date": "2026-09-02", "description": "CITY POWER UTILITY PAYMENT", "amount": 450.00, "type": "debit"},
        # Multiple positions from SAME lender (OnDeck Position #1: $300/day, OnDeck Position #2: $800/day)
        {"date": "2026-09-01", "description": "ONDECK CAPITAL DAILY ACH", "amount": 300.00, "type": "withdrawal"},
        {"date": "2026-09-02", "description": "ONDECK CAPITAL DAILY ACH", "amount": 300.00, "type": "withdrawal"},
        {"date": "2026-09-01", "description": "ONDECK CAPITAL DAILY ACH", "amount": 800.00, "type": "withdrawal"},
        {"date": "2026-09-02", "description": "ONDECK CAPITAL DAILY ACH", "amount": 800.00, "type": "withdrawal"},
    ]

    res = parser.detect_mca_debt_stacking(sample_bank_txs, monthly_revenue=30000.0)

    assert isinstance(res, MCADebtStackingResult)
    # Payroll & tax payments must NOT be flagged
    assert not any("GUSTO" in tx["description"] for tx in res.detected_transactions)
    assert not any("IRS" in tx["description"] for tx in res.detected_transactions)

    # 2 distinct positions identified for OnDeck
    assert res.concurrent_mca_count == 2
    assert "ONDECK" in res.flagged_funders
    # Total monthly payment: ($300 * 21) + ($800 * 21) = $6,300 + $16,800 = $23,100
    assert res.estimated_monthly_mca_payment == pytest.approx(23100.0, rel=1e-2)

    # Synthetic dataset with mild disparate impact
    np.random.seed(42)
    n = 200
    scores = np.random.uniform(0.10, 0.90, n)
    group = np.random.choice(["white", "minority"], size=n, p=[0.6, 0.4])

    # Add artificial score drift for minority group
    scores[group == "minority"] += 0.12

    df = pd.DataFrame({
        "risk_score": scores,
        "demographic_group": group,
    })

    candidates = find_less_discriminatory_alternative(
        df,
        scores_col="risk_score",
        protected_col="demographic_group",
        control_group="white",
        threshold_grid=[0.30, 0.40, 0.50, 0.60, 0.70],
        min_air_threshold=0.75,
    )

    assert len(candidates) > 0
    assert any(c.pareto_optimal for c in candidates)

    pareto_candidates = [c for c in candidates if c.pareto_optimal]
    for c in pareto_candidates:
        assert c.air_compliant is True
        assert c.dominated_by_count == 0
        assert "Pareto Optimal" in c.recommendation_reason


def test_live_sanctions_screening_engine():
    engine = LiveSanctionsScreeningEngine(ttl_seconds=300, match_threshold=0.85)

    # Screening match
    res1 = engine.screen("Vlad Petrov")  # Match alias
    assert res1.match_found is True
    assert res1.matched_sdn_name == "VLADIMIR PETROV"
    assert res1.match_score >= 0.85

    # Screening clean name
    res2 = engine.screen("Jane Smith")
    assert res2.match_found is False

    # Dynamic refresh
    success = engine.refresh_sanctions_lists({"NEW SANCTIONED ENTITY": ["NSE CORP"]})
    assert success is True

    res3 = engine.screen("NSE Corp", force_refresh=True)
    assert res3.match_found is True
    assert res3.matched_sdn_name == "NEW SANCTIONED ENTITY"
