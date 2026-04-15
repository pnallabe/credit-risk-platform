"""Equifax OneView credit pull client (OAuth2 + customer number header)."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import BureauClient
from .models import BureauProvider, BureauPullError, BureauRequest, BureauResponse, Tradeline

logger = logging.getLogger(__name__)


class EquifaxClient(BureauClient):
    """
    Equifax OneView credit pull client.

    Required environment variables:
        EQUIFAX_CLIENT_ID         — OAuth2 client ID
        EQUIFAX_CLIENT_SECRET     — OAuth2 client secret
        EQUIFAX_CUSTOMER_NUMBER   — Required header value
        EQUIFAX_ENV               — "sandbox" | "production" (default: "sandbox")
    """

    _BASE_URL_SANDBOX    = "https://api.sandbox.equifax.com"
    _BASE_URL_PRODUCTION = "https://api.equifax.com"
    _TOKEN_PATH          = "/v1/oauth/token"
    _CREDIT_REPORT_PATH  = "/business/creditreports/v1/basic"

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.EQUIFAX

    @property
    def _base_url(self) -> str:
        env = os.getenv("EQUIFAX_ENV", "sandbox").lower()
        return self._BASE_URL_PRODUCTION if env == "production" else self._BASE_URL_SANDBOX

    async def _get_token(self) -> str:
        """
        Return a valid bearer token. Refresh if expired or within 5 minutes of expiry.
        """
        if self._token and time.time() < self._token_expires_at - 300:
            return self._token

        client_id     = os.getenv("EQUIFAX_CLIENT_ID", "")
        client_secret = os.getenv("EQUIFAX_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            raise BureauPullError(
                "EQUIFAX_CLIENT_ID and EQUIFAX_CLIENT_SECRET are required",
                provider=BureauProvider.EQUIFAX,
            )

        url = self._base_url + self._TOKEN_PATH
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    data={
                        "grant_type":    "client_credentials",
                        "client_id":     client_id,
                        "client_secret": client_secret,
                    },
                )
                if resp.status_code >= 400:
                    raise BureauPullError(
                        f"Equifax token fetch failed {resp.status_code}: {resp.text[:200]}",
                        provider=BureauProvider.EQUIFAX,
                    )
                data = resp.json()
                self._token = data["access_token"]
                expires_in  = int(data.get("expires_in", 3600))
                self._token_expires_at = time.time() + expires_in
                return self._token  # type: ignore[return-value]
        except httpx.TimeoutException as exc:
            raise BureauPullError(
                "Equifax token request timed out",
                provider=BureauProvider.EQUIFAX,
            ) from exc
        except BureauPullError:
            raise
        except Exception as exc:
            raise BureauPullError(
                f"Equifax token request error: {exc}",
                provider=BureauProvider.EQUIFAX,
            ) from exc

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """POST to Equifax credit report endpoint."""
        token           = await self._get_token()
        customer_number = os.getenv("EQUIFAX_CUSTOMER_NUMBER", "")

        payload = {
            "consumers": {
                "name": [
                    {"firstName": request.first_name, "lastName": request.last_name}
                ],
                "socialNum": [{"ssnLast4": request.ssn_last4}],
                "addresses": [
                    {
                        "addressLine1": request.address_line1,
                        "city":         request.city,
                        "state":        request.state,
                        "zip":          request.zip_code,
                    }
                ],
            }
        }

        headers = {
            "Authorization":            f"Bearer {token}",
            "X-Equifax-Customer-Number": customer_number,
            "Content-Type":             "application/json",
        }

        url = self._base_url + self._CREDIT_REPORT_PATH
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise BureauPullError(
                        f"Equifax {resp.status_code}: {resp.text[:200]}",
                        provider=BureauProvider.EQUIFAX,
                    )
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise BureauPullError(
                "Equifax request timed out",
                provider=BureauProvider.EQUIFAX,
            ) from exc
        except BureauPullError:
            raise
        except Exception as exc:
            raise BureauPullError(
                f"Equifax request error: {exc}",
                provider=BureauProvider.EQUIFAX,
            ) from exc

        credit_score = int(data.get("score", {}).get("value", 0))
        score_model  = str(data.get("score", {}).get("model", "FICO_8"))

        tradelines = [self._map_equifax_trade(t) for t in data.get("tradelines", [])]
        pub_recs   = data.get("publicRecords", [])

        total_debt    = sum(t.balance for t in tradelines)
        revolving     = [t for t in tradelines if t.account_type == "revolving"]
        total_limit   = sum(t.credit_limit or 0 for t in revolving)
        total_rev_bal = sum(t.balance for t in revolving)
        util          = (total_rev_bal / total_limit) if total_limit > 0 else 0.0
        open_accounts = len(tradelines)
        delinquencies = sum(
            1 for t in tradelines if t.payment_status not in ("current",)
        )
        oldest_months = max((t.months_on_file or 0 for t in tradelines), default=0)

        inq_raw = data.get("inquiries", [])
        inq_last_6m = inq_raw if isinstance(inq_raw, int) else len(inq_raw)

        return BureauResponse(
            provider=BureauProvider.EQUIFAX,
            application_id=request.application_id,
            credit_score=credit_score,
            score_model=score_model,
            open_accounts=open_accounts,
            delinquencies_last_24m=delinquencies,
            total_debt=total_debt,
            utilisation_rate=round(util, 4),
            inquiries_last_6m=inq_last_6m,
            months_since_oldest_account=oldest_months,
            public_records=len(pub_recs),
            tradelines=tradelines,
            raw_response=data,
            pulled_at=datetime.now(timezone.utc).isoformat(),
        )

    def _map_equifax_trade(self, trade: dict) -> Tradeline:
        """Map a single Equifax tradelines[] element to a Tradeline."""
        account_type_raw = str(trade.get("accountType", "other")).lower()
        if "revolv" in account_type_raw:
            account_type = "revolving"
        elif "install" in account_type_raw or "auto" in account_type_raw:
            account_type = "installment"
        elif "mortgage" in account_type_raw or "real" in account_type_raw:
            account_type = "mortgage"
        else:
            account_type = "other"

        status_raw = str(trade.get("paymentStatus", "current")).lower()
        if "30" in status_raw:
            payment_status = "30_dpd"
        elif "60" in status_raw:
            payment_status = "60_dpd"
        elif "90" in status_raw or "120" in status_raw:
            payment_status = "90_dpd"
        elif "charge" in status_raw or "off" in status_raw:
            payment_status = "chargeoff"
        else:
            payment_status = "current"

        return Tradeline(
            creditor_name  =str(trade.get("creditorName", "Unknown")),
            account_type   =account_type,
            balance        =float(trade.get("balance",     0)),
            credit_limit   =float(trade.get("creditLimit", 0)) or None,
            payment_status =payment_status,
            opened_date    =trade.get("openDate"),
            months_on_file =trade.get("monthsOnFile"),
        )

    async def health_check(self) -> bool:
        """Return True if a token can be obtained successfully."""
        try:
            await self._get_token()
            return True
        except BureauPullError:
            return False
