"""Tests for wiring: enrich_with_bureau_data() → BureauRouter."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from bureau_clients.models import (
    BureauProvider,
    BureauPullError,
    BureauResponse,
)
from main import enrich_with_bureau_data


def _make_bureau_response(app_id: str = "app-wiring-1") -> BureauResponse:
    return BureauResponse(
        provider=BureauProvider.MOCK,
        application_id=app_id,
        credit_score=755,
        score_model="MOCK_FICO_8",
        open_accounts=5,
        delinquencies_last_24m=0,
        total_debt=14000.0,
        utilisation_rate=0.28,
        inquiries_last_6m=2,
        months_since_oldest_account=96,
        public_records=0,
    )


@pytest.mark.asyncio
async def test_enrich_returns_merged_dict():
    applicant = {"first_name": "Jane", "last_name": "Doe", "loan_amount": 10000}
    mock_resp = _make_bureau_response("app-wiring-1")

    with patch(
        "main._get_bureau_router"
    ) as mock_get_router:
        mock_router = MagicMock()
        mock_router.pull = AsyncMock(return_value=mock_resp)
        mock_get_router.return_value = mock_router

        result = await enrich_with_bureau_data("app-wiring-1", applicant)

    assert "credit_score" in result
    assert result["credit_score"] == 755
    assert result["application_id"] == "app-wiring-1"
    # Original applicant fields should still be present
    assert result["first_name"] == "Jane"


@pytest.mark.asyncio
async def test_enrich_graceful_fallback_on_bureau_pull_error():
    applicant = {"first_name": "Bob", "loan_amount": 5000}

    with patch(
        "main._get_bureau_router"
    ) as mock_get_router:
        mock_router = MagicMock()
        mock_router.pull = AsyncMock(
            side_effect=BureauPullError("all providers down")
        )
        mock_get_router.return_value = mock_router

        result = await enrich_with_bureau_data("app-fail-1", applicant)

    # Should return original applicant dict without credit_score
    assert result["first_name"] == "Bob"
    assert result["application_id"] == "app-fail-1"
    assert "credit_score" not in result
