"""TransUnion TruVision credit pull client (mTLS + API key)."""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

import httpx

from .base import BureauClient
from .models import BureauProvider, BureauPullError, BureauRequest, BureauResponse, Tradeline

logger = logging.getLogger(__name__)

# Module-level cache: (cert_path, key_path) written once per process
_CERT_PATHS: Optional[tuple[str, str]] = None


class TransUnionClient(BureauClient):
    """
    TransUnion TruVision credit pull client.

    Required environment variables:
        TRANSUNION_API_KEY           — API key header value
        TRANSUNION_SUBSCRIBER_CODE   — Subscriber code
        TRANSUNION_CERT_PEM          — PEM-encoded client certificate (string)
        TRANSUNION_KEY_PEM           — PEM-encoded private key (string)
        TRANSUNION_ENV               — "sandbox" | "production" (default: "sandbox")

    mTLS: The client cert/key are written to a NamedTemporaryFile at first use
    and the path is passed to httpx.AsyncClient(cert=...).
    """

    _BASE_URL_SANDBOX    = "https://sandbox.api.transunion.com"
    _BASE_URL_PRODUCTION = "https://prod.api.transunion.com"
    _CREDIT_REPORT_PATH  = "/credit-report/v2/consumer"

    @property
    def provider(self) -> BureauProvider:
        return BureauProvider.TRANSUNION

    @property
    def _base_url(self) -> str:
        env = os.getenv("TRANSUNION_ENV", "sandbox").lower()
        return self._BASE_URL_PRODUCTION if env == "production" else self._BASE_URL_SANDBOX

    def _get_cert_paths(self) -> tuple[str, str]:
        """
        Write TRANSUNION_CERT_PEM and TRANSUNION_KEY_PEM env vars to
        NamedTemporaryFiles if not already written. Return (cert_path, key_path).
        Module-level cache ensures files are written only once per process.
        """
        global _CERT_PATHS
        if _CERT_PATHS is not None:
            return _CERT_PATHS

        cert_pem = os.getenv("TRANSUNION_CERT_PEM", "")
        key_pem  = os.getenv("TRANSUNION_KEY_PEM",  "")

        if not cert_pem:
            raise BureauPullError(
                "TRANSUNION_CERT_PEM environment variable is required for mTLS",
                provider=BureauProvider.TRANSUNION,
            )
        if not key_pem:
            raise BureauPullError(
                "TRANSUNION_KEY_PEM environment variable is required for mTLS",
                provider=BureauProvider.TRANSUNION,
            )

        cert_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        )
        cert_file.write(cert_pem)
        cert_file.flush()
        cert_file.close()

        key_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        )
        key_file.write(key_pem)
        key_file.flush()
        key_file.close()

        _CERT_PATHS = (cert_file.name, key_file.name)
        return _CERT_PATHS

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """POST to TransUnion TruVision credit-report endpoint."""
        api_key         = os.getenv("TRANSUNION_API_KEY", "")
        subscriber_code = os.getenv("TRANSUNION_SUBSCRIBER_CODE", "")

        if not api_key:
            raise BureauPullError(
                "TRANSUNION_API_KEY environment variable is required",
                provider=BureauProvider.TRANSUNION,
            )

        cert_paths = self._get_cert_paths()

        payload = {
            "requestReference": request.application_id,
            "subject": {
                "name": {
                    "firstName": request.first_name,
                    "lastName":  request.last_name,
                },
                "dateOfBirth": request.date_of_birth,
                "ssnLast4":    request.ssn_last4,
                "address": {
                    "addressLine1": request.address_line1,
                    "city":         request.city,
                    "state":        request.state,
                    "zipCode":      request.zip_code,
                },
            },
            "includeProducts": ["CreditScore", "TradeLines", "Inquiries", "PublicRecords"],
        }

        headers = {
            "X-API-Key":           api_key,
            "X-Subscriber-Code":   subscriber_code,
            "Content-Type":        "application/json",
        }

        url = self._base_url + self._CREDIT_REPORT_PATH
        try:
            async with httpx.AsyncClient(
                cert=cert_paths,
                timeout=15.0,
            ) as client:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    raise BureauPullError(
                        f"TransUnion {resp.status_code}: {resp.text[:200]}",
                        provider=BureauProvider.TRANSUNION,
                    )
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise BureauPullError(
                "TransUnion request timed out",
                provider=BureauProvider.TRANSUNION,
            ) from exc
        except BureauPullError:
            raise
        except Exception as exc:
            raise BureauPullError(
                f"TransUnion request error: {exc}",
                provider=BureauProvider.TRANSUNION,
            ) from exc

        credit_score = int(data.get("creditScore", {}).get("score", 0))
        score_model  = str(data.get("creditScore", {}).get("scoreModel", "VantageScore_4"))

        tradelines = [self._map_transunion_trade(t) for t in data.get("tradeLines", [])]
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

        # Inquiries (TransUnion returns a count directly or a list)
        inq_raw = data.get("inquiries", [])
        inq_last_6m = inq_raw if isinstance(inq_raw, int) else len(inq_raw)

        return BureauResponse(
            provider=BureauProvider.TRANSUNION,
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

    def _map_transunion_trade(self, trade: dict) -> Tradeline:
        """Map a single TransUnion tradeLines[] element to a Tradeline."""
        account_type_raw = str(trade.get("accountType", "other")).lower()
        if "revolv" in account_type_raw:
            account_type = "revolving"
        elif "install" in account_type_raw or "auto" in account_type_raw:
            account_type = "installment"
        elif "mortgage" in account_type_raw or "real" in account_type_raw:
            account_type = "mortgage"
        else:
            account_type = "other"

        status_raw = str(trade.get("paymentRating", "current")).lower()
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
