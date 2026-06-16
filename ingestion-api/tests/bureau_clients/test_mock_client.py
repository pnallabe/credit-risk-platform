"""Tests for MockBureauClient."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import asyncio
import pytest

from bureau_clients.mock_client import MockBureauClient
from bureau_clients.models import BureauProvider, BureauRequest


def _make_request(application_id: str = "test-app-1") -> BureauRequest:
    return BureauRequest(
        application_id  =application_id,
        first_name      ="Jane",
        last_name       ="Doe",
        date_of_birth   ="1985-03-15",
        ssn_last4       ="1234",
        address_line1   ="123 Main St",
        city            ="Springfield",
        state           ="IL",
        zip_code        ="62701",
        requested_amount=10000.0,
        loan_purpose    ="personal",
    )


@pytest.mark.asyncio
async def test_same_application_id_same_score():
    client = MockBureauClient()
    r1 = await client.pull(_make_request("app-abc"))
    r2 = await client.pull(_make_request("app-abc"))
    assert r1.credit_score == r2.credit_score


@pytest.mark.asyncio
async def test_credit_score_in_range():
    client = MockBureauClient()
    for app_id in ["id-1", "id-2", "id-99", "zzz", "aaa-bbb-ccc"]:
        resp = await client.pull(_make_request(app_id))
        assert 580 <= resp.credit_score <= 849, f"Score out of range for {app_id}: {resp.credit_score}"


@pytest.mark.asyncio
async def test_tradeline_count():
    client = MockBureauClient()
    resp   = await client.pull(_make_request("x"))
    assert len(resp.tradelines) == 2


@pytest.mark.asyncio
async def test_provider():
    client = MockBureauClient()
    resp   = await client.pull(_make_request("x"))
    assert resp.provider == BureauProvider.MOCK


@pytest.mark.asyncio
async def test_feature_dict_correct_values():
    client = MockBureauClient()
    resp   = await client.pull(_make_request("deterministic-app"))
    fd     = resp.to_feature_dict()

    # All derived keys must be present
    assert "revolving_utilisation_avg" in fd
    assert "derogatory_tradeline_count" in fd
    assert "tradeline_count" in fd
    assert fd["tradeline_count"] == 2
    assert 580 <= fd["credit_score"] <= 849
