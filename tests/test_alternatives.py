"""Tests for alternative structures generator (S4-A)."""

from __future__ import annotations

import pytest

from decision_engine.alternative_structures import (
    AlternativeStructure,
    generate_alternatives,
)
from decision_engine.engine import DECISION_REJECT, DECISION_APPROVE


def _make_request(
    loan_amount: float = 20_000.0,
    dti: float = 0.55,
    annual_income: float = 60_000.0,
    has_collateral: bool = False,
    ltv: float = 0.90,
    current_apr: float = 18.0,
):
    class _P:
        recommended_rate = current_apr

    class _R:
        pricing_result = _P()

    req = _R()
    req.loan_amount = loan_amount
    req.debt_to_income_ratio = dti
    req.annual_income = annual_income
    req.features = {
        "collateral_value": 15_000.0 if has_collateral else 0.0,
        "ltv": ltv,
    }
    return req


class TestAlternativeStructures:
    def test_no_alternatives_for_approve(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.07, decision=DECISION_APPROVE)
        assert alts == []

    def test_alternatives_returned_for_reject(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        assert len(alts) > 0

    def test_maximum_three_alternatives(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        assert len(alts) <= 3

    def test_alternatives_sorted_by_feasibility_desc(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        scores = [a.feasibility_score for a in alts]
        assert scores == sorted(scores, reverse=True)

    def test_ranks_assigned_correctly(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        for i, alt in enumerate(alts):
            assert alt.rank == i + 1

    def test_reprice_suggested_apr_is_higher(self):
        req = _make_request(current_apr=18.0)
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        reprice = next((a for a in alts if a.structure_type == "REPRICE"), None)
        if reprice:
            assert reprice.suggested_apr is not None
            assert reprice.suggested_apr > 18.0

    def test_add_collateral_without_collateral(self):
        req = _make_request(has_collateral=False)
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        add_col = next((a for a in alts if a.structure_type == "ADD_COLLATERAL"), None)
        assert add_col is not None
        assert "real_estate" in add_col.description.lower() or "vehicle" in add_col.description.lower()

    def test_add_collateral_high_ltv(self):
        req = _make_request(has_collateral=True, ltv=0.90)
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        add_col = next((a for a in alts if a.structure_type == "ADD_COLLATERAL"), None)
        assert add_col is not None
        assert add_col.feasibility_score == 0.7

    def test_feasibility_scores_in_range(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        for alt in alts:
            assert 0.0 <= alt.feasibility_score <= 1.0

    def test_alternative_structure_types(self):
        req = _make_request()
        alts = generate_alternatives(req, pd_score=0.20, decision=DECISION_REJECT)
        valid_types = {"REDUCED_AMOUNT", "ADD_COLLATERAL", "REPRICE"}
        for alt in alts:
            assert alt.structure_type in valid_types
