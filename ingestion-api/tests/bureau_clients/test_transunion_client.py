"""Tests for TransUnionClient."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bureau_clients.transunion_client import TransUnionClient
from bureau_clients.models import BureauProvider, BureauPullError, BureauRequest
import bureau_clients.transunion_client as tu_module


def _make_request() -> BureauRequest:
    return BureauRequest(
        application_id  ="tu-test-1",
        first_name      ="Alice",
        last_name       ="Johnson",
        date_of_birth   ="1975-09-10",
        ssn_last4       ="5678",
        address_line1   ="200 Elm St",
        city            ="Denver",
        state           ="CO",
        zip_code        ="80203",
        requested_amount=8000.0,
        loan_purpose    ="personal",
    )


def _mock_tu_response():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "creditScore": {"score": 690, "scoreModel": "VantageScore_4"},
        "tradeLines": [],
        "inquiries": 2,
        "publicRecords": [],
    }
    return mock_resp


@pytest.mark.asyncio
async def test_provider_is_transunion():
    client = TransUnionClient()

    mock_resp = _mock_tu_response()

    # Mock the entire AsyncClient so SSL cert validation is bypassed
    mock_client_instance = MagicMock()
    mock_client_instance.post = AsyncMock(return_value=mock_resp)
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.dict(
            "os.environ",
            {
                "TRANSUNION_API_KEY":         "key",
                "TRANSUNION_CERT_PEM":        "-----BEGIN CERT-----",
                "TRANSUNION_KEY_PEM":         "-----BEGIN KEY-----",
                "TRANSUNION_SUBSCRIBER_CODE": "sub",
            },
        ),
        patch("httpx.AsyncClient", return_value=mock_client_instance),
    ):
        # Reset module-level cert path cache so the temp files are written fresh
        tu_module._CERT_PATHS = None
        resp = await client.pull(_make_request())

    assert resp.provider == BureauProvider.TRANSUNION
    assert resp.credit_score == 690


@pytest.mark.asyncio
async def test_missing_cert_raises_error():
    client = TransUnionClient()
    tu_module._CERT_PATHS = None  # reset cache

    with patch.dict("os.environ", {
        "TRANSUNION_API_KEY": "key",
        "TRANSUNION_CERT_PEM": "",  # missing
        "TRANSUNION_KEY_PEM":  "-----BEGIN KEY-----",
    }, clear=False):
        # Remove the env var entirely to simulate missing
        env_copy = {k: v for k, v in os.environ.items()
                    if k not in ("TRANSUNION_CERT_PEM",)}
        with patch.dict("os.environ", env_copy, clear=True):
            with pytest.raises(BureauPullError, match="TRANSUNION_CERT_PEM"):
                await client.pull(_make_request())


def test_cert_paths_cached():
    """Cert files should be written only once per process (module-level cache)."""
    tu_module._CERT_PATHS = None  # reset first

    client = TransUnionClient()
    with patch.dict("os.environ", {
        "TRANSUNION_CERT_PEM": "-----BEGIN CERT-----",
        "TRANSUNION_KEY_PEM":  "-----BEGIN KEY-----",
    }):
        paths1 = client._get_cert_paths()
        paths2 = client._get_cert_paths()

    assert paths1 == paths2  # same object — written once
    assert tu_module._CERT_PATHS is not None
