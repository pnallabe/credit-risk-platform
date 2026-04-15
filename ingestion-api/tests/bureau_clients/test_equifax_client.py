"""Tests for EquifaxClient."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bureau_clients.equifax_client import EquifaxClient
from bureau_clients.models import BureauProvider, BureauPullError, BureauRequest


def _make_request() -> BureauRequest:
    return BureauRequest(
        application_id  ="eq-test-1",
        first_name      ="Bob",
        last_name       ="Williams",
        date_of_birth   ="1990-12-01",
        ssn_last4       ="3456",
        address_line1   ="300 Pine Rd",
        city            ="Atlanta",
        state           ="GA",
        zip_code        ="30301",
        requested_amount=20000.0,
        loan_purpose    ="home_improvement",
    )


def _mock_token_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "eq-tok-xyz", "expires_in": 3600}
    return mock_resp


def _mock_credit_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "score": {"value": 740, "model": "FICO_8"},
        "tradelines": [],
        "inquiries": 0,
        "publicRecords": [],
    }
    return mock_resp


@pytest.mark.asyncio
async def test_token_cached():
    client = EquifaxClient()
    calls  = []

    async def fake_post(url, **kwargs):
        calls.append(url)
        return _mock_token_response()

    with (
        patch.dict("os.environ", {"EQUIFAX_CLIENT_ID": "cid", "EQUIFAX_CLIENT_SECRET": "cs"}),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        await client._get_token()
        first_count = len(calls)
        await client._get_token()
        assert len(calls) == first_count  # no extra HTTP call


@pytest.mark.asyncio
async def test_pull_maps_credit_score():
    client = EquifaxClient()

    async def fake_post(url, **kwargs):
        if "token" in url:
            return _mock_token_response()
        return _mock_credit_response()

    with (
        patch.dict("os.environ", {
            "EQUIFAX_CLIENT_ID":       "cid",
            "EQUIFAX_CLIENT_SECRET":   "cs",
            "EQUIFAX_CUSTOMER_NUMBER": "cust-123",
        }),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        resp = await client.pull(_make_request())

    assert resp.credit_score == 740
    assert resp.provider     == BureauProvider.EQUIFAX


@pytest.mark.asyncio
async def test_http_500_raises_bureau_pull_error():
    client = EquifaxClient()

    async def fake_post(url, **kwargs):
        if "token" in url:
            return _mock_token_response()
        mock_r = MagicMock()
        mock_r.status_code = 500
        mock_r.text = "server error"
        return mock_r

    with (
        patch.dict("os.environ", {
            "EQUIFAX_CLIENT_ID":       "cid",
            "EQUIFAX_CLIENT_SECRET":   "cs",
            "EQUIFAX_CUSTOMER_NUMBER": "cust-123",
        }),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        with pytest.raises(BureauPullError):
            await client.pull(_make_request())
