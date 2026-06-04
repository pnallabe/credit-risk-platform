import pytest

from src import plaid_connector as connector


def test_provider_selection_falls_back_safely(monkeypatch):
    monkeypatch.delenv("BUREAU_PROVIDER", raising=False)
    monkeypatch.delenv("OBP_BASE_URL", raising=False)
    monkeypatch.delenv("FINICITY_PARTNER_ID", raising=False)

    assert connector._resolve_provider_choice("app-1", None, None, provider="invalid-provider") == "mock"
    assert connector._resolve_provider_choice("app-1", None, None, provider="openbankproject") == "mock"

    monkeypatch.setenv("OBP_BASE_URL", "https://obp.example")
    assert connector._resolve_provider_choice("app-1", None, None, provider="obp") == "openbankproject"
    assert connector._resolve_provider_choice("app-1", "plaid-token", None, provider="plaid") == "plaid"


def test_openbankproject_mapping_handles_edge_cases():
    obp = connector.OpenBankProjectConnector()

    account = obp._map_account(
        {
            "id": "acct-123",
            "name": "Main Checking",
            "balance": {"available": None, "current": None, "currency": "usd"},
            "type": "current",
        }
    )
    assert account.account_id == "acct-123"
    assert account.type == "depository"
    assert account.balance_available is None
    assert account.balance_current is None
    assert account.currency == "USD"

    transaction = obp._map_transaction(
        {
            "id": "txn-1",
            "account_id": "acct-123",
            "amount": "125.50",
            "date": "not-a-date",
            "name": "Rent",
            "category": "housing",
            "pending": True,
        },
        fallback_account_id="acct-123",
    )
    assert transaction.transaction_id == "txn-1"
    assert transaction.date == "1970-01-01"
    assert transaction.amount == 125.5
    assert transaction.category == ["housing"]
    assert transaction.pending is True

    assert connector._coerce_transaction_list({}) == []
    assert connector._coerce_transaction_list({"transactions": [{"id": 1}, "bad", None]}) == [{"id": 1}]


@pytest.mark.asyncio
async def test_legacy_keywords_preserve_plaid_flow(monkeypatch):
    async def fake_get_accounts(self, access_token):
        return [
            connector.PlaidAccount(
                account_id="acct-1",
                name="Checking",
                official_name=None,
                type="depository",
                subtype="checking",
                balance_available=100.0,
                balance_current=100.0,
                currency="USD",
            )
        ]

    async def fake_get_transactions(self, access_token, start_date=None, end_date=None, lookback_days=90):
        return [
            connector.PlaidTransaction(
                transaction_id="txn-1",
                account_id="acct-1",
                amount=-2500.0,
                date="2026-01-01",
                name="Payroll",
                merchant_name="ACME",
                category=["deposit"],
                pending=False,
                payment_channel="other",
            )
        ]

    async def fake_get_income_verification(self, access_token):
        return [
            connector.IncomeStream(
                stream_id="stream-1",
                name="Payroll",
                description="Bi-weekly payroll",
                income_type="SALARY",
                monthly_amount=3000.0,
                frequency="BIWEEKLY",
                status="ACTIVE",
                confidence=0.9,
            )
        ]

    monkeypatch.setattr(connector.PlaidConnector, "get_accounts", fake_get_accounts)
    monkeypatch.setattr(connector.PlaidConnector, "get_transactions", fake_get_transactions)
    monkeypatch.setattr(connector.PlaidConnector, "get_income_verification", fake_get_income_verification)

    summary = await connector.enrich_with_cash_flow_data(
        user_id="app-legacy",
        access_token="plaid-token",
        provider="plaid",
    )

    assert summary.application_id == "app-legacy"
    assert summary.provider == "plaid"
    assert summary.account_count == 1
    assert summary.monthly_net_income == 3000.0
    assert summary.to_feature_dict()["plaid_provider"] == "plaid"
