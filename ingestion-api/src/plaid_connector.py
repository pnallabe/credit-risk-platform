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
>>> token = os.getenv("PLAID_ACCESS_TOKEN")  # never hardcode tokens
>>> summary = await enrich_with_cash_flow_data(
...     application_id="app-123",
...     access_token=token,
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
from security.secrets_manager import get_secret
from typing import Any, Dict, List, Literal, Optional

import httpx
from dateutil import parser as date_parser

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

SUPPORTED_BUREAU_PROVIDERS = {"plaid", "finicity", "openbankproject", "mock"}
BUREAU_PROVIDER = os.getenv("BUREAU_PROVIDER", "plaid")

CASH_FLOW_LOOKBACK_DAYS = 90   # default transaction lookback window


class ProviderConnectorError(RuntimeError):
    """Raised when a provider cannot be queried or returns unusable data."""

    def __init__(
        self,
        provider: str,
        application_id: str,
        error_category: str,
        message: str,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.application_id = application_id
        self.error_category = error_category


class ProviderConfigurationError(ProviderConnectorError):
    """Raised when provider configuration is incomplete or invalid."""


class ProviderResponseError(ProviderConnectorError):
    """Raised when a provider returns an unexpected response payload."""


def _log_provider_event(
    level: int,
    message: str,
    *,
    provider: str,
    application_id: str,
    error_category: str = "info",
) -> None:
    logger.log(
        level,
        "%s provider=%s application_id=%s error_category=%s",
        message,
        provider,
        application_id,
        error_category,
    )


def _normalize_provider_name(provider: Optional[str]) -> str:
    if not provider:
        return "plaid"
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"obp", "open_bank_project", "openbankproject"}:
        return "openbankproject"
    if normalized not in SUPPORTED_BUREAU_PROVIDERS:
        return "plaid"
    return normalized


def _configured_provider_name() -> str:
    return _normalize_provider_name(os.getenv("BUREAU_PROVIDER", "plaid"))


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_date_string(value: Any) -> str:
    if not value:
        return "1970-01-01"
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = date_parser.parse(str(value))
    except (ValueError, TypeError, OverflowError):
        return "1970-01-01"
    return parsed.date().isoformat()


def _coerce_transaction_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    transactions = payload.get("transactions")
    if isinstance(transactions, list):
        return [txn for txn in transactions if isinstance(txn, dict)]
    data = payload.get("data")
    if isinstance(data, list):
        return [txn for txn in data if isinstance(txn, dict)]
    return []


async def _request_json_with_retries(
    method: str,
    url: str,
    *,
    provider: str,
    application_id: str,
    headers: Optional[Dict[str, str]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    error_category: str = "upstream_http_error",
    retries: int = 3,
    timeout: int = 30,
    empty_status_codes: Optional[set[int]] = None,
) -> Dict[str, Any]:
    last_exception: Optional[Exception] = None
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_payload,
                    params=params,
                )
            if empty_status_codes and response.status_code in empty_status_codes:
                return {}
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderResponseError(
                    provider=provider,
                    application_id=application_id,
                    error_category="schema_mismatch",
                    message="Provider response must be a JSON object",
                )
            return payload
        except ProviderConnectorError as exc:
            raise exc
        except (httpx.HTTPError, ValueError) as exc:
            last_exception = exc
            if attempt < retries - 1:
                await asyncio.sleep(0.1 * (2 ** attempt))
                continue
            raise ProviderResponseError(
                provider=provider,
                application_id=application_id,
                error_category=error_category,
                message=f"{provider} request failed for {application_id}: {exc}",
            ) from exc
    raise ProviderResponseError(
        provider=provider,
        application_id=application_id,
        error_category=error_category,
        message=f"{provider} request failed for {application_id}: {last_exception}",
    )


class BankDataConnectorBase:
    """Provider-agnostic bank data connector interface."""

    provider_name = "unknown"

    async def get_cash_flow_summary(
        self,
        application_id: str,
        access_token: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> "BankDataSummary":
        raise NotImplementedError


def _resolve_provider_choice(
    application_id: str,
    plaid_access_token: Optional[str],
    finicity_customer_id: Optional[str],
    provider: Optional[str] = None,
) -> str:
    requested = _normalize_provider_name(provider or _configured_provider_name())

    if requested == "mock":
        return "mock"

    if requested == "openbankproject":
        if os.getenv("OBP_BASE_URL"):
            return "openbankproject"
        _log_provider_event(
            logging.WARNING,
            "Open Bank Project configuration missing; using fallback provider",
            provider=requested,
            application_id=application_id,
            error_category="configuration_missing",
        )
        return "plaid" if plaid_access_token else "mock"

    if requested == "finicity":
        if finicity_customer_id and os.getenv("FINICITY_PARTNER_ID"):
            return "finicity"
        _log_provider_event(
            logging.WARNING,
            "Finicity configuration missing; using fallback provider",
            provider=requested,
            application_id=application_id,
            error_category="configuration_missing",
        )
        return "plaid" if plaid_access_token else "mock"

    if plaid_access_token:
        return "plaid"
    if finicity_customer_id and os.getenv("FINICITY_PARTNER_ID"):
        return "finicity"
    return "mock"


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


class PlaidConnector(BankDataConnectorBase):
    """Async Plaid API client for bank account data enrichment."""

    provider_name = "plaid"

    def __init__(self) -> None:
        self.client_id = get_secret("PLAID_CLIENT_ID", "")
        self.secret = get_secret("PLAID_SECRET", "")
        self.base_url = PLAID_BASE_URLS.get(PLAID_ENV, PLAID_BASE_URLS["sandbox"])

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json"}

    def _auth_payload(self) -> Dict[str, str]:
        return {"client_id": self.client_id, "secret": self.secret}

    async def create_link_token(
        self,
        user_id: str,
        client_name: Optional[str] = None,
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
            "client_name": client_name or "HelixDecision",
            "products": products or ["transactions", "income_verification"],
            "country_codes": country_codes or ["US"],
            "language": "en",
        }
        data = await _request_json_with_retries(
            "POST",
            f"{self.base_url}/link/token/create",
            provider=self.provider_name,
            application_id=user_id,
            headers=self._headers(),
            json_payload=payload,
            error_category="link_token_create",
        )
        return data["link_token"]

    async def exchange_public_token(self, public_token: str) -> str:
        """Exchange a public_token (from Link callback) for an access_token.

        Returns the ``access_token``.
        """
        payload = {**self._auth_payload(), "public_token": public_token}
        data = await _request_json_with_retries(
            "POST",
            f"{self.base_url}/item/public_token/exchange",
            provider=self.provider_name,
            application_id=public_token,
            headers=self._headers(),
            json_payload=payload,
            error_category="token_exchange",
        )
        return data["access_token"]

    async def get_accounts(self, access_token: str) -> List[PlaidAccount]:
        """Fetch linked accounts for an access_token."""
        payload = {**self._auth_payload(), "access_token": access_token}
        data = await _request_json_with_retries(
            "POST",
            f"{self.base_url}/accounts/get",
            provider=self.provider_name,
            application_id=access_token,
            headers=self._headers(),
            json_payload=payload,
            error_category="account_fetch",
        )

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

            data = await _request_json_with_retries(
                "POST",
                f"{self.base_url}/transactions/get",
                provider=self.provider_name,
                application_id=access_token,
                headers=self._headers(),
                json_payload=payload,
                error_category="transaction_fetch",
            )

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
            data = await _request_json_with_retries(
                "POST",
                f"{self.base_url}/income/verification/paystubs/get",
                provider=self.provider_name,
                application_id=access_token,
                headers=self._headers(),
                json_payload=payload,
                error_category="income_verification",
                empty_status_codes={400, 404},
            )
        except ProviderConnectorError:
            return []
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

    async def get_cash_flow_summary(
        self,
        application_id: str,
        access_token: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> BankDataSummary:
        if not access_token:
            raise ProviderConfigurationError(
                provider=self.provider_name,
                application_id=application_id,
                error_category="missing_access_token",
                message="plaid access token is required",
            )

        try:
            accounts, txns, income_streams = await asyncio.gather(
                self.get_accounts(access_token),
                self.get_transactions(access_token, lookback_days=lookback_days),
                self.get_income_verification(access_token),
            )
        except ProviderConnectorError:
            raise
        except Exception as exc:
            _log_provider_event(
                logging.ERROR,
                "Plaid enrichment failed",
                provider=self.provider_name,
                application_id=application_id,
                error_category="upstream_failure",
            )
            raise ProviderResponseError(
                provider=self.provider_name,
                application_id=application_id,
                error_category="upstream_failure",
                message=str(exc),
            ) from exc

        return _build_bank_data_summary(
            application_id=application_id,
            provider=self.provider_name,
            lookback_days=lookback_days,
            accounts=accounts,
            txns=txns,
            income_streams=income_streams,
            data_source_ref=None,
        )


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


def _build_bank_data_summary(
    *,
    application_id: str,
    provider: str,
    lookback_days: int,
    accounts: List[PlaidAccount],
    txns: List[PlaidTransaction],
    income_streams: List[IncomeStream],
    data_source_ref: Optional[str] = None,
) -> BankDataSummary:
    cf = _analyse_transactions(txns, lookback_days)

    net_income = sum(stream.monthly_amount for stream in income_streams)
    if net_income == 0.0:
        net_income = cf["avg_monthly_inflow"]

    income_confidence = statistics.mean(stream.confidence for stream in income_streams) if income_streams else 0.3
    checking_accounts = [account for account in accounts if account.subtype == "checking"]
    savings_accounts = [account for account in accounts if account.subtype == "savings"]
    current_balances = [account.balance_current or 0.0 for account in accounts]

    return BankDataSummary(
        application_id=application_id,
        provider=provider,
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
        has_checking_account=bool(checking_accounts),
        has_savings_account=bool(savings_accounts),
        account_ids=[account.account_id for account in accounts],
        data_source_ref=data_source_ref,
    )


class OpenBankProjectConnector(BankDataConnectorBase):
    """Adapter for Open Bank Project / open-banking endpoints."""

    provider_name = "openbankproject"

    def __init__(self) -> None:
        self.base_url = os.getenv("OBP_BASE_URL", "").rstrip("/")
        self.bank_id = os.getenv("OBP_BANK_ID", "")
        self.access_token = get_secret("OBP_ACCESS_TOKEN", "")
        self.consumer_key = get_secret("OBP_CONSUMER_KEY", "")
        self.consumer_secret = get_secret("OBP_CONSUMER_SECRET", "")

    def _headers(self, access_token: Optional[str] = None) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = access_token or self.access_token
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif self.consumer_key and self.consumer_secret:
            headers["X-Consumer-Key"] = self.consumer_key
            headers["X-Consumer-Secret"] = self.consumer_secret
        return headers

    def _require_base_url(self, application_id: str) -> None:
        if not self.base_url:
            raise ProviderConfigurationError(
                provider=self.provider_name,
                application_id=application_id,
                error_category="configuration",
                message="OBP_BASE_URL not configured",
            )

    def _map_account(self, raw: Dict[str, Any]) -> PlaidAccount:
        balances = raw.get("balance") or raw.get("balances") or {}
        account_type = str(raw.get("type") or raw.get("account_type") or "depository").strip().lower()
        subtype = raw.get("subtype") or raw.get("product") or raw.get("account_type")

        if account_type in {"current", "checking", "cash"}:
            account_type = "depository"

        return PlaidAccount(
            account_id=str(raw.get("account_id") or raw.get("id") or uuid.uuid4()),
            name=str(raw.get("name") or raw.get("label") or raw.get("nickname") or "OBP Account"),
            official_name=raw.get("official_name") or raw.get("label"),
            type=account_type,
            subtype=str(subtype).strip().lower() if subtype else None,
            balance_available=_safe_float(balances.get("available")),
            balance_current=_safe_float(balances.get("current", balances.get("balance"))),
            currency=str(balances.get("iso_currency_code") or balances.get("currency") or "USD").upper(),
        )

    def _map_transaction(self, raw: Dict[str, Any], fallback_account_id: str) -> PlaidTransaction:
        amount = _safe_float(raw.get("amount") or raw.get("value") or raw.get("transactionAmount"),) or 0.0
        category = raw.get("category") or raw.get("categories") or []
        if not isinstance(category, list):
            category = [str(category)]
        merchant_name = raw.get("merchant_name") or raw.get("merchant") or raw.get("counterparty")

        return PlaidTransaction(
            transaction_id=str(raw.get("transaction_id") or raw.get("id") or uuid.uuid4()),
            account_id=str(raw.get("account_id") or fallback_account_id or raw.get("accountId") or ""),
            amount=amount,
            date=_safe_date_string(raw.get("date") or raw.get("posted_at") or raw.get("bookingDate")),
            name=str(raw.get("name") or raw.get("description") or merchant_name or "OBP transaction"),
            merchant_name=str(merchant_name) if merchant_name not in (None, "") else None,
            category=[str(item) for item in category if item not in (None, "")],
            pending=bool(raw.get("pending", False)),
            payment_channel=str(raw.get("payment_channel") or raw.get("channel") or "other"),
        )

    async def get_accounts(self, access_token: str) -> List[PlaidAccount]:
        self._require_base_url(access_token)
        account_path = f"/obp/v5.1.0/banks/{self.bank_id}/accounts" if self.bank_id else "/obp/v5.1.0/accounts"
        payload = {"access_token": access_token}
        data = await _request_json_with_retries(
            "GET",
            f"{self.base_url}{account_path}",
            provider=self.provider_name,
            application_id=access_token,
            headers=self._headers(access_token),
            json_payload=payload,
            error_category="account_fetch",
        )
        records = data.get("accounts") or data.get("data") or []
        return [self._map_account(record) for record in records if isinstance(record, dict)]

    async def get_transactions(
        self,
        access_token: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> List[PlaidTransaction]:
        self._require_base_url(access_token)
        if end_date is None:
            end_date = date.today().isoformat()
        if start_date is None:
            start_date = (date.today() - timedelta(days=lookback_days)).isoformat()

        account_path = f"/obp/v5.1.0/banks/{self.bank_id}/accounts" if self.bank_id else "/obp/v5.1.0/accounts"
        txn_path = "/transactions"

        account_data = await _request_json_with_retries(
            "GET",
            f"{self.base_url}{account_path}",
            provider=self.provider_name,
            application_id=access_token,
            headers=self._headers(access_token),
            json_payload={"access_token": access_token},
            error_category="account_fetch",
        )
        accounts = account_data.get("accounts") or account_data.get("data") or []

        mapped: List[PlaidTransaction] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            account_id = str(account.get("account_id") or account.get("id") or "")
            txn_data = await _request_json_with_retries(
                "GET",
                f"{self.base_url}{txn_path}",
                provider=self.provider_name,
                application_id=access_token,
                headers=self._headers(access_token),
                json_payload={
                    "access_token": access_token,
                    "account_id": account_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                error_category="transaction_fetch",
            )
            for txn in _coerce_transaction_list(txn_data):
                mapped.append(self._map_transaction(txn, account_id))

        return mapped

    async def get_cash_flow_summary(
        self,
        application_id: str,
        access_token: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> BankDataSummary:
        resolved_access_token = access_token or self.access_token or application_id
        accounts = await self.get_accounts(resolved_access_token)
        txns = await self.get_transactions(resolved_access_token, lookback_days=lookback_days)
        return _build_bank_data_summary(
            application_id=application_id,
            provider=self.provider_name,
            lookback_days=lookback_days,
            accounts=accounts,
            txns=txns,
            income_streams=[],
            data_source_ref=None,
        )


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


class FinicityConnector(BankDataConnectorBase):
    """Minimal Finicity (now Mastercard Open Banking) connector.

    Produces BankDataSummary with the same structure as PlaidConnector.
    Full Finicity SDK integration is left as a vendored extension point;
    this stub demonstrates the interface contract.
    """

    def __init__(self) -> None:
        self.app_key = os.getenv("FINICITY_APP_KEY", "")
        self.partner_id = os.getenv("FINICITY_PARTNER_ID", "")
        self.base_url = "https://api.finicity.com"

    async def get_cash_flow_summary(
        self,
        customer_id: str,
        access_token: Optional[str] = None,
        lookback_days: int = 90,
    ) -> BankDataSummary:
        if not self.app_key:
            logger.warning("FINICITY_APP_KEY not set; returning mock data")
            return _generate_mock_bank_data(customer_id)

        # Full Finicity integration: POST /aggregation/v1/customers/{customerId}/reports/cashFlowBusiness
        # For now, log and return mock to maintain interface contract
        logger.info("Finicity cash flow report requested for customer %s (full implementation pending)", customer_id)
        # TODO: Implement full Finicity API call when onboarded
        return _generate_mock_bank_data(customer_id)


class MockConnector(BankDataConnectorBase):
    provider_name = "mock"

    async def get_cash_flow_summary(
        self,
        application_id: str,
        access_token: Optional[str] = None,
        lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    ) -> BankDataSummary:
        return _generate_mock_bank_data(application_id)


def _provider_connector_for_name(provider_name: str) -> BankDataConnectorBase:
    if provider_name == "plaid":
        return PlaidConnector()
    if provider_name == "finicity":
        return FinicityConnector()
    if provider_name == "openbankproject":
        return OpenBankProjectConnector()
    if provider_name == "mock":
        return MockConnector()
    raise ProviderConfigurationError(
        provider=provider_name,
        application_id="unknown",
        error_category="configuration",
        message=f"Unsupported provider: {provider_name}",
    )


# ---------------------------------------------------------------------------
# Main enrichment entry point (provider-agnostic)
# ---------------------------------------------------------------------------


async def enrich_with_cash_flow_data(
    application_id: Optional[str] = None,
    plaid_access_token: Optional[str] = None,
    finicity_customer_id: Optional[str] = None,
    lookback_days: int = CASH_FLOW_LOOKBACK_DAYS,
    force_provider: Optional[Literal["plaid", "finicity", "openbankproject", "mock"]] = None,
    *,
    user_id: Optional[str] = None,
    access_token: Optional[str] = None,
    provider: Optional[str] = None,
) -> BankDataSummary:
    """Enrich an application with bank cash flow data.

     Provider selection order:
     1. ``force_provider`` / ``provider`` if set
     2. ``BUREAU_PROVIDER`` env var
     3. Auto-detect: use Plaid if ``plaid_access_token`` or ``access_token`` provided,
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
    resolved_application_id = application_id or user_id
    if not resolved_application_id:
        raise ValueError("application_id is required")

    resolved_plaid_access_token = plaid_access_token or access_token
    requested_provider = provider or force_provider
    provider_name = _resolve_provider_choice(
        resolved_application_id,
        resolved_plaid_access_token,
        finicity_customer_id,
        provider=requested_provider,
    )

    if not resolved_plaid_access_token and not finicity_customer_id and provider_name != "mock":
        _log_provider_event(
            logging.INFO,
            "No bank credentials provided; using mock provider",
            provider=provider_name,
            application_id=resolved_application_id,
            error_category="fallback",
        )
        provider_name = "mock"

    connector = _provider_connector_for_name(provider_name)

    if provider_name == "plaid":
        if not resolved_plaid_access_token:
            logger.warning("Plaid provider selected but no access_token; using mock")
            return _generate_mock_bank_data(resolved_application_id)
        return await connector.get_cash_flow_summary(
            resolved_application_id,
            access_token=resolved_plaid_access_token,
            lookback_days=lookback_days,
        )

    if provider_name == "finicity":
        return await connector.get_cash_flow_summary(
            finicity_customer_id or resolved_application_id,
            access_token=resolved_plaid_access_token,
            lookback_days=lookback_days,
        )

    if provider_name == "openbankproject":
        return await connector.get_cash_flow_summary(
            resolved_application_id,
            access_token=resolved_plaid_access_token,
            lookback_days=lookback_days,
        )

    return await connector.get_cash_flow_summary(
        resolved_application_id,
        access_token=resolved_plaid_access_token,
        lookback_days=lookback_days,
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
