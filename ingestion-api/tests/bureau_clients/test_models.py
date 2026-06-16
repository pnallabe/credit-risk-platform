"""Tests for bureau_clients data models."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import pytest
from bureau_clients.models import (
    BureauProvider,
    BureauRequest,
    BureauResponse,
    BureauPullError,
    Tradeline,
)


def _make_response(**overrides) -> BureauResponse:
    defaults = dict(
        provider=BureauProvider.MOCK,
        application_id="app-test-1",
        credit_score=720,
        score_model="MOCK_FICO_8",
        open_accounts=4,
        delinquencies_last_24m=0,
        total_debt=12000.0,
        utilisation_rate=0.22,
        inquiries_last_6m=1,
        months_since_oldest_account=84,
        public_records=0,
    )
    defaults.update(overrides)
    return BureauResponse(**defaults)


class TestBureauProvider:
    def test_values(self):
        assert BureauProvider.EXPERIAN.value   == "experian"
        assert BureauProvider.TRANSUNION.value == "transunion"
        assert BureauProvider.EQUIFAX.value    == "equifax"
        assert BureauProvider.MOCK.value       == "mock"


class TestBureauResponse:
    def test_to_feature_dict_keys(self):
        revolving = Tradeline(
            creditor_name="Bank A",
            account_type="revolving",
            balance=2000.0,
            credit_limit=5000.0,
            payment_status="current",
            opened_date=None,
            months_on_file=24,
        )
        installment = Tradeline(
            creditor_name="Finance Co",
            account_type="installment",
            balance=8000.0,
            credit_limit=None,
            payment_status="current",
            opened_date=None,
            months_on_file=36,
        )
        resp = _make_response(tradelines=[revolving, installment])
        fd = resp.to_feature_dict()

        required_keys = [
            "bureau_provider",
            "credit_score",
            "open_accounts",
            "delinquencies_last_24m",
            "total_debt",
            "utilisation_rate",
            "inquiries_last_6m",
            "months_since_oldest_account",
            "public_records",
            "tradeline_count",
            "derogatory_tradeline_count",
            "revolving_utilisation_avg",
        ]
        for k in required_keys:
            assert k in fd, f"Missing key: {k}"

    def test_revolving_util_avg(self):
        revolving = Tradeline(
            creditor_name="Bank A",
            account_type="revolving",
            balance=2500.0,
            credit_limit=5000.0,
            payment_status="current",
            opened_date=None,
            months_on_file=12,
        )
        resp = _make_response(tradelines=[revolving])
        assert resp._revolving_util_avg() == pytest.approx(0.5)

    def test_revolving_util_avg_no_revolving(self):
        installment = Tradeline(
            creditor_name="Auto Fin",
            account_type="installment",
            balance=10000.0,
            credit_limit=None,
            payment_status="current",
            opened_date=None,
            months_on_file=24,
        )
        resp = _make_response(tradelines=[installment])
        assert resp._revolving_util_avg() == 0.0

    def test_derogatory_tradeline_count(self):
        current_tl = Tradeline(
            creditor_name="Bank A",
            account_type="revolving",
            balance=1000.0,
            credit_limit=5000.0,
            payment_status="current",
            opened_date=None,
            months_on_file=12,
        )
        derog_tl = Tradeline(
            creditor_name="Bank B",
            account_type="installment",
            balance=500.0,
            credit_limit=None,
            payment_status="30_dpd",
            opened_date=None,
            months_on_file=6,
        )
        resp = _make_response(tradelines=[current_tl, derog_tl])
        fd = resp.to_feature_dict()
        assert fd["derogatory_tradeline_count"] == 1

    def test_tradeline_count(self):
        t = Tradeline("X", "other", 100.0, None, "current", None, None)
        resp = _make_response(tradelines=[t, t])
        assert resp.to_feature_dict()["tradeline_count"] == 2


class TestBureauPullError:
    def test_provider_attached(self):
        err = BureauPullError("boom", provider=BureauProvider.EXPERIAN)
        assert err.provider == BureauProvider.EXPERIAN
        assert "boom" in str(err)

    def test_no_provider(self):
        err = BureauPullError("generic error")
        assert err.provider is None
