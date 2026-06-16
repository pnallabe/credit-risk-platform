"""Tests for BureauRouter waterfall logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import AsyncMock, patch

import pytest

from bureau_clients.base import BureauClient
from bureau_clients.models import (
    BureauProvider,
    BureauPullError,
    BureauRequest,
    BureauResponse,
)
from bureau_clients.router import BureauRouter


def _make_request() -> BureauRequest:
    return BureauRequest(
        application_id  ="router-test-1",
        first_name      ="Test",
        last_name       ="User",
        date_of_birth   ="1990-01-01",
        ssn_last4       ="0000",
        address_line1   ="1 Router St",
        city            ="Chicago",
        state           ="IL",
        zip_code        ="60601",
        requested_amount=5000.0,
        loan_purpose    ="personal",
    )


def _make_mock_response(app_id: str = "router-test-1") -> BureauResponse:
    return BureauResponse(
        provider=BureauProvider.MOCK,
        application_id=app_id,
        credit_score=700,
        score_model="MOCK_FICO_8",
        open_accounts=3,
        delinquencies_last_24m=0,
        total_debt=8000.0,
        utilisation_rate=0.2,
        inquiries_last_6m=1,
        months_since_oldest_account=48,
        public_records=0,
    )


class _FailingClient(BureauClient):
    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.EXPERIAN

    async def pull(self, request: BureauRequest) -> BureauResponse:
        raise BureauPullError("intentional failure", provider=BureauProvider.EXPERIAN)


class _SucceedingClient(BureauClient):
    def __init__(self, provider: BureauProvider = BureauProvider.MOCK):
        self._provider = provider

    @property
    def provider(self) -> BureauProvider:
        return self._provider

    async def pull(self, request: BureauRequest) -> BureauResponse:
        return _make_mock_response(request.application_id)


@pytest.mark.asyncio
async def test_falls_through_to_second_on_first_failure():
    router = BureauRouter([_FailingClient(), _SucceedingClient()])
    resp   = await router.pull(_make_request())
    assert resp.credit_score == 700


@pytest.mark.asyncio
async def test_all_clients_fail_raises():
    router = BureauRouter([_FailingClient(), _FailingClient()])
    with pytest.raises(BureauPullError, match="All bureau providers failed"):
        await router.pull(_make_request())


@pytest.mark.asyncio
async def test_raises_on_empty_clients():
    with pytest.raises(ValueError):
        BureauRouter([])


def test_from_env_mock_only():
    with patch.dict(os.environ, {"BUREAU_PRIMARY": "mock", "BUREAU_FALLBACK": ""}, clear=False):
        router = BureauRouter.from_env()
    # Only one client — MockBureauClient
    assert len(router._clients) == 1
    assert router._clients[0].provider == BureauProvider.MOCK


def test_from_env_experian_transunion_with_mock_fallback():
    env = {
        "BUREAU_PRIMARY":              "experian",
        "BUREAU_FALLBACK":             "transunion",
        "BUREAU_ALLOW_MOCK_FALLBACK":  "true",
    }
    with patch.dict(os.environ, env, clear=False):
        router = BureauRouter.from_env()

    providers = [c.provider for c in router._clients]
    assert BureauProvider.EXPERIAN   in providers
    assert BureauProvider.TRANSUNION in providers
    assert BureauProvider.MOCK       in providers
    assert len(providers) == 3
