"""Experian ConnectPlus credit pull client."""

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


class ExperianClient(BureauClient):
    """
    Experian ConnectPlus credit pull client.

    Required environment variables (or GCP Secret Manager secrets):
        EXPERIAN_CLIENT_ID       — OAuth2 client ID
        EXPERIAN_CLIENT_SECRET   — OAuth2 client secret
        EXPERIAN_SUBSCRIBER_CODE — Experian subscriber/member code
        EXPERIAN_ENV             — "sandbox" | "production" (default: "sandbox")

    Token refresh: OAuth2 client-credentials token is cached in-memory
    with a 5-minute buffer before expiry.
    """

    _BASE_URL_SANDBOX    = "https://sandbox.experian.com"
    _BASE_URL_PRODUCTION = "https://us.api.experian.com"
    _TOKEN_PATH          = "/oauth2/v1/token"
    _CREDIT_PROFILE_PATH = "/consumerservices/credit-profile/v2/credit-score"

    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.EXPERIAN

    @property
    def _base_url(self) -> str:
        env = os.getenv("EXPERIAN_ENV", "sandbox").lower()
        return self._BASE_URL_PRODUCTION if env == "production" else self._BASE_URL_SANDBOX

    async def _get_token(self) -> str:
        """
        Return a valid bearer token. Refresh if expired or within 5 minutes of expiry.
        Uses httpx.AsyncClient with a 10-second timeout.
        """
        # 5-minute buffer before expiry
        if self._token and time.time() < self._token_expires_at - 300:
            return self._token

        client_id     = os.getenv("EXPERIAN_CLIENT_ID", "")
        client_secret = os.getenv("EXPERIAN_CLIENT_SECRET", "")

        if not client_id or not client_secret:
            raise BureauPullError(
                "EXPERIAN_CLIENT_ID and EXPERIAN_CLIENT_SECRET are required",
                provider=BureauProvider.EXPERIAN,
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
                        f"Experian token fetch failed {resp.status_code}: {resp.text[:200]}",
                        provider=BureauProvider.EXPERIAN,
                    )
                data = resp.json()
                self._token = data["access_token"]
                expires_in  = int(data.get("expires_in", 3600))
                self._token_expires_at = time.time() + expires_in
                return self._token  # type: ignore[return-value]
        except httpx.TimeoutException as exc:
            raise BureauPullError(
                "Experian token request timed out",
                provider=BureauProvider.EXPERIAN,
            ) from exc
        except BureauPullError:
            raise
        except Exception as exc:
            raise BureauPullError(
                f"Experian token request error: {exc}",
                provider=BureauProvider.EXPERIAN,
            ) from exc

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """POST to Experian credit-profile endpoint and map response."""
        token = await self._get_token()
        subscriber_code = os.getenv("EXPERIAN_SUBSCRIBER_CODE", "")

        # Convert DOB from YYYY-MM-DD → MMDDYYYY
        dob_parts = request.date_of_birth.replace("-", "")
        if len(dob_parts) == 8:
            dob_experian = dob_parts[4:6] + dob_parts[6:8] + dob_parts[0:4]
        else:
            dob_experian = dob_parts

        payload = {
            "appReference": request.application_id,
            "subscriberCode": subscriber_code,
            "primaryConsumer": {
                "name": {
                    "firstName": request.first_name,
                    "lastName":  request.last_name,
                },
                "dob":  {"dob": dob_experian},
                "ssn":  {"last4": request.ssn_last4},
                "currentAddress": {
                    "line1":   request.address_line1,
                    "city":    request.city,
                    "state":   request.state,
                    "zipCode": request.zip_code,
                },
            },
            "requestedAttributes": ["scores", "trades", "inquiries", "publicRecords"],
        }

        url = self._base_url + self._CREDIT_PROFILE_PATH
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type":  "application/json",
                    },
                )
                if resp.status_code >= 400:
                    raise BureauPullError(
                        f"Experian {resp.status_code}: {resp.text[:200]}",
                        provider=BureauProvider.EXPERIAN,
                    )
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise BureauPullError(
                "Experian request timed out",
                provider=BureauProvider.EXPERIAN,
            ) from exc
        except BureauPullError:
            raise
        except Exception as exc:
            raise BureauPullError(
                f"Experian request error: {exc}",
                provider=BureauProvider.EXPERIAN,
            ) from exc

        # Map Experian response fields
        scores    = data.get("scores",        [{}])
        trades    = data.get("trades",        [])
        inquiries = data.get("inquiries",     [])
        pub_recs  = data.get("publicRecords", [])

        credit_score  = int(scores[0].get("scoreValue", 0)) if scores else 0
        score_model   = str(scores[0].get("scoreModel", "FICO_8")) if scores else "FICO_8"

        tradelines = [self._map_experian_trade(t) for t in trades]

        total_debt = sum(t.balance for t in tradelines)
        revolving  = [t for t in tradelines if t.account_type == "revolving"]
        total_limit = sum(t.credit_limit or 0 for t in revolving)
        total_rev_bal = sum(t.balance for t in revolving)
        util = (total_rev_bal / total_limit) if total_limit > 0 else 0.0

        open_accounts     = sum(1 for t in tradelines)
        delinquencies_24m = sum(
            1 for t in tradelines
            if t.payment_status not in ("current",)
        )
        oldest_months = max((t.months_on_file or 0 for t in tradelines), default=0)

        # Inquiries in last 6 months — Experian marks them with a date
        from datetime import timezone as _tz, timedelta as _td
        cutoff = datetime.now(_tz.utc) - _td(days=182)
        inq_last_6m = 0
        for inq in inquiries:
            inq_date_str = inq.get("date", "")
            if inq_date_str:
                try:
                    from dateutil.parser import parse as _dparse
                    inq_dt = _dparse(inq_date_str)
                    if inq_dt.replace(tzinfo=_tz.utc) >= cutoff:
                        inq_last_6m += 1
                except Exception:
                    pass
            else:
                inq_last_6m += 1  # date unknown; count conservatively

        return BureauResponse(
            provider=BureauProvider.EXPERIAN,
            application_id=request.application_id,
            credit_score=credit_score,
            score_model=score_model,
            open_accounts=open_accounts,
            delinquencies_last_24m=delinquencies_24m,
            total_debt=total_debt,
            utilisation_rate=round(util, 4),
            inquiries_last_6m=inq_last_6m,
            months_since_oldest_account=oldest_months,
            public_records=len(pub_recs),
            tradelines=tradelines,
            raw_response=data,
            pulled_at=datetime.now(timezone.utc).isoformat(),
        )

    def _map_experian_trade(self, trade: dict) -> Tradeline:
        """Map a single Experian trades[] element to a Tradeline."""
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
            creditor_name  =str(trade.get("subscriberName", "Unknown")),
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
