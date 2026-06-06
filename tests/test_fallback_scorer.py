"""Tests for rule-based fallback scorer (S6-A)."""

from __future__ import annotations

import pytest

from decision_engine.rule_based_fallback import rule_based_pd_estimate


class TestRuleBasedFallback:
    def test_high_fico_low_dti_no_derog_returns_low_pd(self):
        pd, rationale = rule_based_pd_estimate({"fico_score": 750, "dti": 0.30, "num_derog_marks": 0})
        assert pd == 0.03
        assert "0.03" in rationale

    def test_fico_720_boundary(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 720, "dti": 0.35, "num_derog_marks": 0})
        assert pd == 0.03

    def test_fico_720_but_with_derog_falls_to_next_band(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 720, "dti": 0.35, "num_derog_marks": 1})
        assert pd == 0.07

    def test_fico_680_band(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 680, "dti": 0.40})
        assert pd == 0.07

    def test_fico_650_band(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 650, "dti": 0.45})
        assert pd == 0.13

    def test_fico_620_dti_below_050(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 620, "dti": 0.49})
        assert pd == 0.13

    def test_fico_620_dti_at_050_drops_to_next_band(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 620, "dti": 0.50})
        assert pd == 0.22

    def test_fico_580_band(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 580, "dti": 0.60})
        assert pd == 0.22

    def test_fico_below_580_high_risk(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 550, "dti": 0.60})
        assert pd == 0.40

    def test_missing_fico_forces_refer(self):
        pd, rationale = rule_based_pd_estimate({"dti": 0.40})
        assert pd == 0.99
        assert "not available" in rationale.lower()

    def test_accepts_credit_score_alias(self):
        pd, _ = rule_based_pd_estimate({"credit_score": 750, "dti": 0.30, "num_derog_marks": 0})
        assert pd == 0.03

    def test_accepts_debt_to_income_ratio_alias(self):
        pd, _ = rule_based_pd_estimate({"fico_score": 750, "debt_to_income_ratio": 0.30, "num_derog_marks": 0})
        assert pd == 0.03

    def test_all_bands_return_tuple_float_str(self):
        cases = [
            {"fico_score": 750, "dti": 0.30, "num_derog_marks": 0},
            {"fico_score": 700, "dti": 0.40},
            {"fico_score": 640, "dti": 0.45},
            {"fico_score": 590, "dti": 0.60},
            {"fico_score": 540, "dti": 0.70},
            {"dti": 0.40},
        ]
        for features in cases:
            pd_score, rationale = rule_based_pd_estimate(features)
            assert isinstance(pd_score, float)
            assert isinstance(rationale, str)
            assert 0.0 <= pd_score <= 1.0
