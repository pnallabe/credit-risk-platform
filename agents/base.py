"""
Base Agent Contract
===================
All agents inherit BaseAgent and communicate through AgentResult.
This enforces a homogeneous interface across the entire pipeline.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class AgentResult:
    """Universal return type for every agent run."""

    agent_name: str
    status: AgentStatus
    payload: Dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    duration_seconds: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == AgentStatus.SUCCESS

    def raise_on_failure(self) -> "AgentResult":
        if not self.ok:
            raise RuntimeError(
                f"[{self.agent_name}] failed with errors: {self.errors}"
            )
        return self


class BaseAgent(ABC):
    """
    Every sub-agent must implement `_run()`.
    `execute()` wraps it with timing, error capture, and logging.
    """

    name: str = "BaseAgent"

    def __init__(self, config: Dict[str, Any] | None = None):
        self.config: Dict[str, Any] = config or {}
        self._log = logging.getLogger(f"agents.{self.name}")

    @abstractmethod
    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """Core agent logic — override in each sub-agent."""
        ...

    def execute(self, inputs: Dict[str, Any]) -> AgentResult:
        """Public entry point with timing + structured error capture."""
        self._log.info("Starting %s", self.name)
        t0 = time.perf_counter()
        try:
            result = self._run(inputs)
        except Exception as exc:  # noqa: BLE001
            self._log.exception("Unhandled error in %s", self.name)
            result = AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=[str(exc), traceback.format_exc()],
            )
        result.duration_seconds = time.perf_counter() - t0
        self._log.info(
            "%s finished in %.3fs — status=%s",
            self.name,
            result.duration_seconds,
            result.status,
        )
        return result
