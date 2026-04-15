"""Deterministic mock bureau client for local development and testing."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .base import BureauClient
from .models import BureauProvider, BureauRequest, BureauResponse, Tradeline


class MockBureauClient(BureauClient):
    """
    Deterministic mock bureau client for local development and testing.

    Score and field values are derived from SHA-256(application_id) so
    the same application ID always receives the same mock response.
    """

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.MOCK

    async def pull(self, request: BureauRequest) -> BureauResponse:
        seed = int(hashlib.sha256(request.application_id.encode()).hexdigest(), 16)

        # Deterministic values seeded from application_id hash
        credit_score   = 580 + (seed % 270)          # 580–849
        open_accounts  = 2 + (seed % 10)
        delinquencies  = 0 if (seed % 5) != 0 else (seed % 3)
        total_debt     = round(5000 + (seed % 45000), 2)
        utilisation    = round((seed % 60) / 100, 2)  # 0.00–0.59
        inquiries      = seed % 5
        months_oldest  = 24 + (seed % 120)
        public_records = 0 if (seed % 8) != 0 else 1

        tradelines = [
            Tradeline(
                creditor_name="Mock Bank NA",
                account_type="revolving",
                balance=round(total_debt * 0.4, 2),
                credit_limit=round(total_debt * 0.8, 2),
                payment_status="current",
                opened_date=None,
                months_on_file=months_oldest // 2,
            ),
            Tradeline(
                creditor_name="Mock Auto Finance",
                account_type="installment",
                balance=round(total_debt * 0.6, 2),
                credit_limit=None,
                payment_status="current" if delinquencies == 0 else "30_dpd",
                opened_date=None,
                months_on_file=months_oldest,
            ),
        ]

        return BureauResponse(
            provider=BureauProvider.MOCK,
            application_id=request.application_id,
            credit_score=credit_score,
            score_model="MOCK_FICO_8",
            open_accounts=open_accounts,
            delinquencies_last_24m=delinquencies,
            total_debt=total_debt,
            utilisation_rate=utilisation,
            inquiries_last_6m=inquiries,
            months_since_oldest_account=months_oldest,
            public_records=public_records,
            tradelines=tradelines,
            raw_response={"mock": True, "seed": seed % 99999},
            pulled_at=datetime.now(timezone.utc).isoformat(),
        )
