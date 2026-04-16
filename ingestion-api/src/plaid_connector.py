"""
ingestion-api/src/plaid_connector.py
=====================================
Plaid / Finicity Cash Flow & Income Data Enrichment (PRD §4.2.2, Phase 3)

Provides:
  - Plaid Link token creation (for applicant bank account connection)
  - Plaid transaction pull + cash flow analysis
  - Finicity (MX / Mastercard Open Banking) fallback
  - Unified ``BankDataSummary`` output suitable for feature-pipeline ingestion
  - Mock bank response for local development (when credentials absent)

Environment variables
---------------------
PLAID_CLIENT_ID       — Plaid client ID
PLAID_SECRET          — Plaid API secret (environment-specific)
PLAID_ENV             — "sandbox" | "production" (default: "sandbox")
FINICITY_APP_KEY      — Finicity/MX application key (optional, fallback)
FINICITY_PARTNER_ID   — Finicity partner ID
BUREAU_PROVIDER       — "plaid" | "finicity" | "mock" (default: "plaid")

Public API
----------
>>> from ingestion_api.src.plaid_connector import enrich_with_cash_flow_data
>>> summary = await enrich_with_cash_flow_data(
...     application_id="app-123",
...     access_token="access-sandbox-xxxx",
... )
>>> summary.monthly_net_income          # float
>>> summary.nsfv_last_90_days           # int (insufficient fund events)
>>> summary.to_feature_dict()           # dict for feature pipeline
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PLAID_ENV = os.getenv("PLAID_ENV", "sandbox")
PLAID_BASE_URLS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}

BUREAU_PROVIDER: Literal["plaid", "finicity", "mock"] = (  # type: ignore[assignment]
    os.getenv("BUREAU_PROVIDER", "plaid")  # type: ignore[assignment]
)

CASH_FLOW_LOOKBACK_DAYS = 90   # default transaction lookback window


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlaidAccount:
    """A single linked bank account from Plaid."""

    account_id: str
    name: str
    official_name: Optional[str]
    type: str           # "depository" | "credit" | "loan" | "investment"
    subtype: Optional[str]   # "checking" | "savings" | "cd" | ...
    balance_available: Optional[float]
    balance_current: Optional[float]
    currency: str = "USD"


@dataclass
class PlaidTransaction:
    """A single bank transaction from Plaid."""

    transaction_id: str
    account_id: str
    amount: float           # positive = debit (money out); negative = credit (money in)
    date: str               # YYYY-MM-DD
    name: str
    merchant_name: Optional[str]
    category: List[str]     # Plaid's category hierarchy
    pending: bool
    payment_channel: str    # "online" | "in store" | "other"


@dataclass
class IncomeStream:
    """Detected recurring income stream from transaction history."""

    stream_id: str
    name: str
    description: str
    income_type: str           # "SALARY" | "BANK_INTEREST" | "GIG" | "RENTAL" | "GOVERNMENT"
    monthly_amount: float
    frequency: str             # "WEEKLY" | "BIWEEKLY" | "MONTHLY"
    status: str                # "ACTIVE" | "UNKNOWN"
    confidence: float          # 0.0 – 1.0


@dataclass
class BankDataSummary:
    """Unified cash flow and income summary for the feature pipeline.

    This is the canonical output regardless of provider (Plaid, Finicity, mock).
    """

    application_id: str
    provider: str              # "plaid" | "finicity" | "mock"
    generated_at: str
    lookback_days: int

    # Income
    monthly_net_income: float          # estimated take-home monthly income
    monthly_gross_income_est: float    # gross estimate (net * 1.28 as rough proxy)
    income_streams: List[IncomeStream] = field(default_factory=list)
    income_confidence: float = 0.0    # 0.0 – 1.0 aggregate confidence

    # Cash flow
    avg_monthly_inflow: float = 0.0           # average monthly deposits
    avg_monthly_outflow: float = 0.0          # average monthly debits
    avg_monthly_end_balance: float = 0.0      # average end-of-month closing balance
    min_balance_90d: float = 0.0              # minimum balance over lookback window
    max_balance_90d: float = 0.0

    # Credit behaviour signals
    nsfv_last_90_days: int = 0                # NSF / overdraft events
    returned_payment_count: int = 0
    gambling_transaction_count: int = 0
    payday_loan_detected: bool = False
    large_unusual_deposit_count: int = 0      # > 3x average monthly deposit

    # Accounts
    account_count: int = 0
    has_checking_account: bool = False
    has_savings_account: bool = False

    # Raw data reference
    account_ids: List[str] = field(default_factory=list)
    data_source_ref: Optional[str] = None     # Plaid item_id or Finicity customer_id

    def to_feature_dict(self) -> Dict[str, Any]:
        """Return a flat dict suitable for the feature pipeline."""
        return {
            "plaid_monthly_net_income": self.monthly_net_income,
            "plaid_monthly_gross_income_est": self.monthly_gross_income_est,
            "plaid_income_confidence": self.income_confidence,
            "plaid_avg_monthly_inflow": self.avg_monthly_inflow,
            "plaid_avg_monthly_outflow": self.avg_monthly_outflow,
            "plaid_avg_end_balance": self.avg_monthly_end_balance,
            "plaid_min_balance_90d": self.min_balance_90d,
            "plaid_nsfv_count_90d": self.nsfv_last_90_days,
            "plaid_returned_payment_count": self.returned_payment_count,
            "plaid_gambling_transactions": self.gambling_transaction_count,
            "plaid_payday_loan_detected": int(self.payday_loan_detected),
            "plaid_has_checking": int(self.has_checking_account),
            "plaid_has_savings": int(self.has_savings_account),
            "plaid_account_count": self.account_count,
            "plaid_provider": self.provider,
        }


# ---------------------------------------------------------------------------
# Plaid connector
# ---------------------------------------------------------------------------


class PlaidConnector:
    """Async Plaid API client for bank account data enrichment."""

    def __init__(self) -> None:
        self.client_id = os.getenv("PLAID_CLIENT_ID", "")
        self.secret = os.getenv("PLAID_SECRET", "")
        self.base_url = PLAID_BASE_URLS.get(PLAID_ENV, PLAID_BASE_URLS["sandbox"])

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}

    def _auth_payload(self) -> Dict[str, str]:
        return {"client_id": self.client_id, "secret": self.secret}

    async def create_link_token(
        self,
        user_id: str,
        products: Optional[List[str]] = None,
        country_codes: Optional[List[str]] = None,
    ) -> str:
        """Create a Plaid Link token for the front-end Link flow.

        Returns the ``link_token`` string.
        """
        if not self.client_id:
            raise ValueError("PLAID_CLIENT_ID not set")

        payload = {
            **self._auth_payload(),
            "user": {"client_user_id": user_id},
            "client_name": "ILOL Credit Platform",
            "products": products or ["transactions", "income_verification"],
            "country_codes": country_codes or ["US"],
            "language": "en",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/link/token/create", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["link_token"]

    async def exchange_public_token(self, public_token: str) -> str:
        """Exchange a public_token (from Link callback) for an access_token.

        Returns the ``access_token``.
        """
        payload = {**self._auth_payload(), "public_token": public_token}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/item/public_token/exchange", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["access_token"]

    async def get_accounts(self, access_token: str) -> List[PlaidAccount]:
        """Fetch linked accounts for an access_token."""
        payload = {**self._auth_payload(), "access_token": access_token}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self.base_url}/accounts/get", json=payload)
            resp.raise_for_status()
            data = resp.json()

        accounts = []
        for a in data.get("accounts", []):
            bal = a.get("balances", {})
            accounts.append(
                PlaidAccount(
                    account_id=a["account_id"],
                    name=a.get("name", ""),
                    official_name=a.get("official_name"),
                    type=a.get("type", ""),
                    subtype=a.get("subtype"),
                    balance_available=bal.get("available"),
                    balance_current=bal.get("current"),
                    currency=bal.get("iso_currency_code") or "USD",
                )
            )
        return accounts

    async def get_transactions(
        self,
        access_token: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> List[PlaidTransaction]:
        """Fetch transactions for the lookback window.

        Handles Plaid's cursor-based pagination automatically.
        """
        if end_date is None:
            end_date = date.today().isoformat()
        if start_date is None:
            start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

        all_txns: List[PlaidTransaction] = []
        cursor: Optional[str] = None

        while True:
            payload: Dict[str, Any] = {
                **self._auth_payload(),
                "access_token": access_token,
                "start_date": start_date,
                "end_date": end_date,
                "options": {"count": 500},
            }
            if cursor:
                payload["cursor"] = cursor

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{self.base_url}/transactions/get", json=payload)
                resp.raise_for_status()
                data = resp.json()

            for t in data.get("transactions", []):
                all_txns.append(
                    PlaidTransaction(
                        transaction_id=t["transaction_id"],
                        account_id=t["account_id"],
                        amount=float(t.get("amount", 0)),
                        date=t.get("date", ""),
                        name=t.get("name", ""),
                        merchant_name=t.get("merchant_name"),
                        category=t.get("category") or [],
                        pending=bool(t.get("pending", False)),
                        payment_channel=t.get("payment_channel", "other"),
                    )
                )
            if not data.get("has_more", False):
                break
            cursor = data.get("next_cursor")

        return all_txns

    async def get_income_verification(self, access_token: str) -> List[IncomeStream]:
        """Fetch Plaid Income verification results."""
        payload = {**self._auth_payload(), "access_token": access_token}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{self.base_url}/income/verification/paystubs/get", json=payload)
                if resp.status_code in (400, 404):
                    return []
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return []

        streams = []
        for item in data.get("income_streams", []):
            streams.append(
                IncomeStream(
                    stream_id=item.get("stream_id", str(uuid.uuid4())),
                    name=item.get("name", ""),
                    description=item.get("description", ""),
                    income_type=item.get("income_type", "SALARY"),
                    monthly_amount=float(item.get("monthly_amount", 0)),
                    frequency=item.get("frequency", "MONTHLY"),
                    status=item.get("status", "UNKNOWN"),
                    confidence=float(item.get("confidence", 0.5)),
                )
            )
        return streams


# ---------------------------------------------------------------------------
# Cash flow analyser (provider-agnostic)
# ---------------------------------------------------------------------------


def _analyse_transactions(
    txns: List[PlaidTransaction],
    lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """Derive cash flow analytics from a list of transactions."""
    # Exclude pending transactions
    settled = [t for t in txns if not t.pending]

    # Group by month
    monthly_inflow: Dict[str, float] = {}
    monthly_outflow: Dict[str, float] = {}

    for t in settled:
        month = t.date[:7]   # YYYY-MM
        if t.amount < 0:     # credit (Plaid: inflow is negative amount)
            monthly_inflow[month] = monthly_inflow.get(month, 0.0) + abs(t.amount)
        else:
            monthly_outflow[month] = monthly_outflow.get(month, 0.0) + t.amount

    months = sorted(set(monthly_inflow) | set(monthly_outflow))
    avg_in = statistics.mean(monthly_inflow.values()) if monthly_inflow else 0.0
    avg_out = statistics.mean(monthly_outflow.values()) if monthly_outflow else 0.0

    # NSF / overdraft detection
    nsf_keywords = {"insufficient funds", "overdraft fee", "nsf fee", "returned item"}
    nsfv = sum(
        1 for t in settled
        if any(kw in (t.name or "").lower() for kw in nsf_keywords)
    )

    # Returned payment detection
    returned_keywords = {"returned payment", "return payment", "payment returned"}
    returned = sum(
        1 for t in settled
        if any(kw in (t.name or "").lower() for kw in returned_keywords)
    )

    # Gambling
    gambling_cats = {"gambling", "casinos & gaming", "lottery"}
    gambling = sum(
        1 for t in settled
        if any(c.lower() in gambling_cats for c in t.category)
    )

    # Payday loan
    payday_keywords = {"payday loan", "advance america", "check into cash", "moneyloan", "speedy cash"}
    payday = any(
        any(kw in (t.name or "").lower() for kw in payday_keywords)
        for t in settled
    )

    # Large unusual deposits (> 3x avg monthly inflow)
    large_threshold = avg_in * 3.0 if avg_in > 0 else float("inf")
    large_deposits = sum(
        1 for t in settled
        if t.amount < 0 and abs(t.amount) > large_threshold / max(len(months), 1)
    )

    return {
        "avg_monthly_inflow": avg_in,
        "avg_monthly_outflow": avg_out,
        "nsfv_last_90_days": nsfv,
        "returned_payment_count": returned,
        "gambling_transaction_count": gambling,
        "payday_loan_detected": payday,
        "large_unusual_deposit_count": large_deposits,
    }


# ---------------------------------------------------------------------------
# Mock provider (for development / testing)
# ---------------------------------------------------------------------------


def _generate_mock_bank_data(application_id: str) -> BankDataSummary:
    """Return a realistic mock bank data summary for development without API keys."""
    logger.info("Using mock bank data for application %s (BUREAU_PROVIDER=mock)", application_id)
    return BankDataSummary(
        application_id=application_id,
        provider="mock",
        generated_at=datetime.now(timezone.utc).isoformat(),
        lookback_days=CASH_FLOW_LOOKBACK_DAYS,
        monthly_net_income=4_850.0,
        monthly_gross_income_est=6_208.0,
        income_streams=[
            IncomeStream(
                stream_id=str(uuid.uuid4()),
                name="Payroll — ACME Corp",
                description="Bi-weekly payroll deposit",
                income_type="SALARY",
                monthly_amount=4_850.0,
                frequency="BIWEEKLY",
                status="ACTIVE",
                confidence=0.95,
            )
        ],
        income_confidence=0.95,
        avg_monthly_inflow=5_200.0,
        avg_monthly_outflow=4_100.0,
        avg_monthly_end_balance=3_400.0,
        min_balance_90d=820.0,
        max_balance_90d=7_200.0,
        nsfv_last_90_days=0,
        returned_payment_count=0,
        gambling_transaction_count=0,
        payday_loan_detected=False,
        large_unusual_deposit_count=0,
        account_count=2,
        has_checking_account=True,
        has_savings_account=True,
        account_ids=["mock-checking-001", "mock-savings-001"],
        data_source_ref="mock",
    )


# ---------------------------------------------------------------------------
# Finicity connector (stub with Plaid-compatible output)
# ---------------------------------------------------------------------------


class FinicityConnector:
    """Minimal Finicity (now Mastercard Open Banking) connector.

    Produces BankDataSummary with the same structure as PlaidConnector.
    Full Finicity SDK integration is left as a vendored extension point;
    this stub demonstrates the interface contract.
    """

    def __init__(self) -> None:
        self.app_key = os.getenv("FINICITY_APP_KEY", "")
        self.partner_id = os.getenv("FINICITY_PARTNER_ID", "")
        self.base_url = "https://api.finicity.com"

    async def get_cash_flow_summary(self, customer_id: str, lookback_days: int = 90) -> BankDataSummary:
        if not self.app_key:
            logger.warning("FINICITY_APP_KEY not set; returning mock data")
            return _generate_mock_bank_data(customer_id)

        # Full Finicity integration: POST /aggregation/v1/customers/{customerId}/reports/cashFlowBusiness
        # For now, log and return mock to maintain interface contract
        logger.info("Finicity cash flow report requested for customer %s (full implementation pending)", customer_id)
        # TODO: Implement full Finicity API call when onboarded
        return _generate_mock_bank_data(customer_id)


# ---------------------------------------------------------------------------
# Main enrichment entry point (provider-agnostic)
# ---------------------------------------------------------------------------


async def enrich_with_cash_flow_data(
    application_id: str,
    plaid_access_token: Optional[str] = None,
    finicity_customer_id: Optional[str] = None,
    lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    force_provider: Optional[Literal["plaid", "finicity", "mock"]] = None,
) -> BankDataSummary:
    """Enrich an application with bank cash flow data.

    Provider selection order:
    1. ``force_provider`` if set
    2. ``BUREAU_PROVIDER`` env var
    3. Auto-detect: use Plaid if ``plaid_access_token`` provided,
       Finicity if ``finicity_customer_id`` provided, else mock.

    Parameters
    ----------
    application_id : str
        Loan application ID for logging and result attribution.
    plaid_access_token : str, optional
        Plaid access_token from the Link flow.
    finicity_customer_id : str, optional
        Finicity customer ID.
    lookback_days : int
        How many days of transaction history to analyse.
    force_provider : str, optional
        Override the provider selection.

    Returns
    -------
    BankDataSummary
    """
    provider = force_provider or BUREAU_PROVIDER

    # Fall back to mock if neither token is provided
    if not plaid_access_token and not finicity_customer_id and provider not in ("mock",):
        logger.info(
            "No bank credentials provided for application %s; falling back to mock data",
            application_id,
        )
        provider = "mock"

    if provider == "mock":
        return _generate_mock_bank_data(application_id)

    if provider == "finicity":
        connector = FinicityConnector()
        return await connector.get_cash_flow_summary(finicity_customer_id or application_id, lookback_days)

    # Default: Plaid
    if not plaid_access_token:
        logger.warning("Plaid provider selected but no access_token; using mock")
        return _generate_mock_bank_data(application_id)

    plaid = PlaidConnector()
    try:
        accounts, txns, income_streams = await asyncio.gather(
            plaid.get_accounts(plaid_access_token),
            plaid.get_transactions(plaid_access_token, lookback_days=lookback_days),
            plaid.get_income_verification(plaid_access_token),
        )
    except Exception as exc:
        logger.exception("Plaid API call failed for application %s: %s", application_id, exc)
        return _generate_mock_bank_data(application_id)

    # Cash flow analytics
    cf = _analyse_transactions(txns, lookback_days)

    # Compute monthly net income from income streams
    net_income = sum(s.monthly_amount for s in income_streams)
    if net_income == 0.0:
        # Fall back to cash-flow based income estimate
        net_income = cf["avg_monthly_inflow"]
    income_confidence = (
        statistics.mean(s.confidence for s in income_streams) if income_streams else 0.3
    )

    # Balance stats
    checking = [a for a in accounts if a.subtype == "checking"]
    savings_accounts = [a for a in accounts if a.subtype == "savings"]
    current_balances = [a.balance_current or 0.0 for a in accounts]

    return BankDataSummary(
        application_id=application_id,
        provider="plaid",
        generated_at=datetime.now(timezone.utc).isoformat(),
        lookback_days=lookback_days,
        monthly_net_income=net_income,
        monthly_gross_income_est=net_income * 1.28,
        income_streams=income_streams,
        income_confidence=income_confidence,
        avg_monthly_inflow=cf["avg_monthly_inflow"],
        avg_monthly_outflow=cf["avg_monthly_outflow"],
        avg_monthly_end_balance=statistics.mean(current_balances) if current_balances else 0.0,
        min_balance_90d=min(current_balances, default=0.0),
        max_balance_90d=max(current_balances, default=0.0),
        nsfv_last_90_days=cf["nsfv_last_90_days"],
        returned_payment_count=cf["returned_payment_count"],
        gambling_transaction_count=cf["gambling_transaction_count"],
        payday_loan_detected=cf["payday_loan_detected"],
        large_unusual_deposit_count=cf["large_unusual_deposit_count"],
        account_count=len(accounts),
        has_checking_account=bool(checking),
        has_savings_account=bool(savings_accounts),
        account_ids=[a.account_id for a in accounts],
        data_source_ref=None,  # Would be Plaid item_id in production
    )


# ---------------------------------------------------------------------------
# Token management helpers
# ---------------------------------------------------------------------------


async def create_plaid_link_token(user_id: str, products: Optional[List[str]] = None) -> str:
    """Convenience wrapper to create a Plaid Link token.

    Raises ValueError if PLAID_CLIENT_ID is not configured.
    In sandbox mode, returns a dummy token for development.
    """
    plaid = PlaidConnector()
    if not plaid.client_id:
        if PLAID_ENV == "sandbox":
            logger.info("Returning mock link token for sandbox development (PLAID_CLIENT_ID not set)")
            return f"link-sandbox-mock-{uuid.uuid4()}"
        raise ValueError("PLAID_CLIENT_ID environment variable must be set for Plaid integration")
    return await plaid.create_link_token(user_id, products=products)


async def exchange_plaid_public_token(public_token: str) -> str:
    """Exchange a Plaid Link public_token for a persistent access_token."""
    plaid = PlaidConnector()
    if not plaid.client_id:
        return f"access-sandbox-mock-{uuid.uuid4()}"
    return await plaid.exchange_public_token(public_token)
