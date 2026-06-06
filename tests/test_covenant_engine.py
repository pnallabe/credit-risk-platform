"""Tests for CovenantEngine (S4-B)."""

from __future__ import annotations

import pytest

from decision_engine.covenant_engine import Covenant, get_covenants


class TestCovenantEngine:
    def test_commercial_loan_any_tier_returns_three_covenants(self):
        covenants = get_covenants("commercial_loan", "Low")
        assert len(covenants) == 3
        types = {c.covenant_type for c in covenants}
        assert "DSCR_MAINTENANCE" in types
        assert "MAX_LTV" in types
        assert "FINANCIAL_REPORTING" in types

    def test_commercial_high_tier_also_returns_three_covenants(self):
        covenants = get_covenants("commercial_loan", "High")
        assert len(covenants) == 3

    def test_smb_high_tier_includes_personal_guarantee(self):
        covenants = get_covenants("smb_loan", "High")
        types = {c.covenant_type for c in covenants}
        assert "PERSONAL_GUARANTEE" in types

    def test_smb_elevated_tier_includes_revenue_covenant(self):
        covenants = get_covenants("smb_loan", "Elevated")
        types = {c.covenant_type for c in covenants}
        assert "REVENUE_COVENANT" in types

    def test_smb_low_tier_only_tax_returns(self):
        covenants = get_covenants("smb_loan", "Low")
        types = {c.covenant_type for c in covenants}
        assert types == {"ANNUAL_TAX_RETURNS"}

    def test_smb_medium_tier_only_tax_returns(self):
        covenants = get_covenants("smb_loan", "Medium")
        types = {c.covenant_type for c in covenants}
        assert types == {"ANNUAL_TAX_RETURNS"}

    def test_mortgage_any_tier_returns_lien_and_ltv(self):
        covenants = get_covenants("mortgage", "Low")
        types = {c.covenant_type for c in covenants}
        assert "LTV_LIMIT" in types
        assert "LIEN_SEARCH" in types

    def test_auto_loan_any_tier_returns_lien_and_ltv(self):
        covenants = get_covenants("auto_loan", "Medium")
        types = {c.covenant_type for c in covenants}
        assert "LTV_LIMIT" in types
        assert "LIEN_SEARCH" in types

    def test_credit_card_returns_empty(self):
        covenants = get_covenants("credit_card", "Low")
        assert covenants == []

    def test_personal_loan_returns_empty(self):
        covenants = get_covenants("personal_loan", "Medium")
        assert covenants == []

    def test_unknown_product_returns_empty(self):
        covenants = get_covenants("nonexistent_product", "Low")
        assert covenants == []

    def test_covenant_fields_populated(self):
        covenants = get_covenants("commercial_loan", "Low")
        for cov in covenants:
            assert isinstance(cov, Covenant)
            assert cov.covenant_type
            assert cov.description
            assert cov.frequency in ("Quarterly", "Annual", "At-Origination")
            assert cov.consequence

    def test_dscr_maintenance_threshold(self):
        covenants = get_covenants("commercial_loan", "Medium")
        dscr_cov = next(c for c in covenants if c.covenant_type == "DSCR_MAINTENANCE")
        assert dscr_cov.threshold == 1.25

    def test_max_ltv_threshold_commercial(self):
        covenants = get_covenants("commercial_loan", "Low")
        ltv_cov = next(c for c in covenants if c.covenant_type == "MAX_LTV")
        assert ltv_cov.threshold == 0.75

    def test_revenue_covenant_threshold(self):
        covenants = get_covenants("smb_loan", "High")
        rev_cov = next(c for c in covenants if c.covenant_type == "REVENUE_COVENANT")
        assert rev_cov.threshold == 0.80
