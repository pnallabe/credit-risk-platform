"""Bureau router with configurable waterfall fallback logic."""

from __future__ import annotations

import logging
import os
from typing import List

from .base import BureauClient
from .models import BureauProvider, BureauPullError, BureauRequest, BureauResponse

logger = logging.getLogger(__name__)


class BureauRouter:
    """
    Waterfall bureau router with configurable primary/fallback order.

    Usage::

        router = BureauRouter.from_env()
        response = await router.pull(request)
    """

    def __init__(self, clients: List[BureauClient]) -> None:
        """
        clients: ordered list; first is primary, remainder are fallbacks.
        Must contain at least one client.
        """
        if not clients:
            raise ValueError("BureauRouter requires at least one client")
        self._clients = clients

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        Try each client in order. On BureauPullError, log a warning and
        try the next client. If all fail, raise BureauPullError with a
        summary of all failures.

        Successful pulls are logged at INFO level with provider name and
        application_id (no PII beyond application_id in log lines).
        """
        errors: list[str] = []
        for client in self._clients:
            try:
                response = await client.pull(request)
                logger.info(
                    "Bureau pull succeeded: provider=%s application_id=%s",
                    client.provider.value,
                    request.application_id,
                )
                return response
            except BureauPullError as exc:
                logger.warning(
                    "Bureau pull failed: provider=%s application_id=%s error=%s — trying next",
                    client.provider.value,
                    request.application_id,
                    exc,
                )
                errors.append(f"{client.provider.value}: {exc}")

        raise BureauPullError(
            f"All bureau providers failed for application_id={request.application_id}: "
            + "; ".join(errors)
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "BureauRouter":
        """
        Construct a BureauRouter from environment variables.

        BUREAU_PRIMARY   — "experian" | "transunion" | "equifax" | "mock"
                           (default: "mock")
        BUREAU_FALLBACK  — comma-separated list of fallback providers
                           (default: "mock")

        Examples::

            BUREAU_PRIMARY=experian BUREAU_FALLBACK=transunion,mock
            → ExperianClient → TransUnionClient → MockBureauClient

        Always appends MockBureauClient as the last resort if no other
        client succeeds and BUREAU_ALLOW_MOCK_FALLBACK=true
        (default: true in non-production).
        """
        from .experian_client   import ExperianClient    # noqa: PLC0415
        from .transunion_client import TransUnionClient  # noqa: PLC0415
        from .equifax_client    import EquifaxClient     # noqa: PLC0415
        from .mock_client       import MockBureauClient  # noqa: PLC0415

        _CLIENT_MAP = {
            "experian":   ExperianClient,
            "transunion": TransUnionClient,
            "equifax":    EquifaxClient,
            "mock":       MockBureauClient,
        }

        primary      = os.getenv("BUREAU_PRIMARY",  "mock").lower()
        fallback_str = os.getenv("BUREAU_FALLBACK", "mock")
        fallbacks    = [f.strip().lower() for f in fallback_str.split(",") if f.strip()]
        allow_mock   = os.getenv("BUREAU_ALLOW_MOCK_FALLBACK", "true").lower() == "true"

        providers = [primary] + fallbacks
        if allow_mock and "mock" not in providers:
            providers.append("mock")

        # Deduplicate preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for p in providers:
            if p not in seen:
                seen.add(p)
                ordered.append(p)

        clients: list[BureauClient] = [
            _CLIENT_MAP[p]()        # type: ignore[abstract]
            for p in ordered
            if p in _CLIENT_MAP
        ]
        return cls(clients)
