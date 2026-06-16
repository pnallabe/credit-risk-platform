"""Tests for ExperianClient."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bureau_clients.experian_client import ExperianClient
from bureau_clients.models import BureauProvider, BureauPullError, BureauRequest


def _make_request() -> BureauRequest:
    return BureauRequest(
        application_id  ="exp-test-1",
        first_name      ="John",
        last_name       ="Smith",
        date_of_birth   ="1980-06-20",
        ssn_last4       ="9999",
        address_line1   ="100 Oak Ave",
        city            ="Austin",
        state           ="TX",
        zip_code        ="78701",
        requested_amount=15000.0,
        loan_purpose    ="auto",
    )


def _mock_token_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "tok-abc", "expires_in": 3600}
    return mock_resp


def _mock_credit_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "scores": [{"scoreValue": 710, "scoreModel": "FICO_8"}],
        "trades": [
            {
                "subscriberName": "Chase",
                "accountType": "revolving",
                "balance": 3000.0,
                "creditLimit": 10000.0,
                "paymentStatus": "current",
                "openDate": "2020-01-01",
                "monthsOnFile": 48,
            }
        ],
        "inquiries": [],
        "publicRecords": [],
    }
    return mock_resp


@pytest.mark.asyncio
async def test_token_cached_after_first_call():
    client = ExperianClient()

    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if "token" in args[0]:
            return _mock_token_response()
        return _mock_credit_response()

    with (
        patch.dict("os.environ", {"EXPERIAN_CLIENT_ID": "cid", "EXPERIAN_CLIENT_SECRET": "cs"}),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        await client._get_token()
        token_calls_first = call_count
        # Second call should use cache — no extra HTTP call
        await client._get_token()
        assert call_count == token_calls_first  # token was cached


@pytest.mark.asyncio
async def test_pull_maps_credit_score():
    client = ExperianClient()

    async def fake_post(url, **kwargs):
        if "token" in url:
            return _mock_token_response()
        return _mock_credit_response()

    with (
        patch.dict(
            "os.environ",
            {"EXPERIAN_CLIENT_ID": "cid", "EXPERIAN_CLIENT_SECRET": "cs"},
        ),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        resp = await client.pull(_make_request())

    assert resp.credit_score == 710
    assert resp.provider == BureauProvider.EXPERIAN


@pytest.mark.asyncio
async def test_http_429_raises_bureau_pull_error():
    client = ExperianClient()

    async def fake_post(url, **kwargs):
        if "token" in url:
            return _mock_token_response()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "rate limited"
        return mock_resp

    with (
        patch.dict(
            "os.environ",
            {"EXPERIAN_CLIENT_ID": "cid", "EXPERIAN_CLIENT_SECRET": "cs"},
        ),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
    ):
        with pytest.raises(BureauPullError):
            await client.pull(_make_request())


@pytest.mark.asyncio
async def test_ssn_never_in_logs(caplog):
    """SSN last4 must never appear in any log output."""
    client = ExperianClient()
    req    = _make_request()

    async def fake_post(url, **kwargs):
        if "token" in url:
            return _mock_token_response()
        return _mock_credit_response()

    import logging
    with (
        patch.dict(
            "os.environ",
            {"EXPERIAN_CLIENT_ID": "cid", "EXPERIAN_CLIENT_SECRET": "cs"},
        ),
        patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_post)),
        caplog.at_level(logging.DEBUG),
    ):
        await client.pull(req)

    combined_log = " ".join(caplog.messages)
    assert req.ssn_last4 not in combined_log, "SSN last4 found in log output!"
