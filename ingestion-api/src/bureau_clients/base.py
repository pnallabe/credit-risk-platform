"""Abstract base class for all bureau provider clients."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import BureauProvider, BureauRequest, BureauResponse


class BureauClient(ABC):
    """Abstract base for all bureau provider clients."""

    @property
    @abstractmethod
    def provider(self) -> BureauProvider:
        """The bureau provider this client talks to."""

    @abstractmethod
    async def pull(self, request: BureauRequest) -> BureauResponse:
        """
        Perform a live credit pull.

        Raises:
            BureauPullError: if the request fails (network, auth, throttle).
                             Caller is responsible for fallback logic.
        """

    async def health_check(self) -> bool:
        """
        Ping the bureau's health endpoint.
        Default implementation returns True (override in concrete clients).
        """
        return True
