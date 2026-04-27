"""
compliance_gate_agent.py — Prompt 20-A (GAP-20)
Pre-planning compliance gate. Screens raw user queries for ECOA-prohibited
variables and PII indicators before the PlannerAgent receives them.
PRD §4.6.6, §5.2 (Enforcement Layer 2)
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Optional

from pydantic import BaseModel

from compliance.prohibited_variables import (
    PROHIBITED_VARIABLES,
    PROXY_VARIABLE_MAP,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class GateDecision(BaseModel):
    allowed: bool
    blocked_terms: list[str]          # Empty if allowed
    refusal_message: Optional[str]    # Human-readable reason if not allowed
    gate_id: str                      # UUID for audit cross-reference


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ComplianceGateAgent:
    """
    Pre-planning compliance gate. Blocks ECOA-prohibited variables and PII
    indicators from entering the query pipeline.
    Synchronous — performs no I/O.
    """

    # Compile PII patterns once at class instantiation for performance
    _PII_PATTERNS: list[re.Pattern] = [
        re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),          # SSN: 123-45-6789
        re.compile(r'\b\d{9}\b'),                        # 9-digit SSN without dashes
        re.compile(
            r'\b(?:4[0-9]{12}(?:[0-9]{3})?'             # Visa
            r'|5[1-5][0-9]{14}'                           # MasterCard
            r'|3[47][0-9]{13}'                            # Amex
            r'|6(?:011|5[0-9]{2})[0-9]{12})\b'           # Discover
        ),                                                # Credit card numbers
        re.compile(
            r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'
        ),                                                # Email addresses
    ]

    # Build a combined word-boundary pattern for prohibited/proxy variable names
    # at instantiation so per-call scanning is fast
    _ALL_PROHIBITED: frozenset[str] = PROHIBITED_VARIABLES | frozenset(PROXY_VARIABLE_MAP.keys())

    def evaluate(self, query_text: str, tenant_id: str) -> GateDecision:
        """
        Evaluate query_text for compliance violations.
        Returns a GateDecision (never raises).
        """
        blocked_terms: list[str] = []
        query_lower = query_text.lower()

        # 1. Check against ECOA-prohibited variables (word-boundary aware)
        for term in self._ALL_PROHIBITED:
            # Use word-boundary regex for accurate matching
            pattern = r'\b' + re.escape(term.replace("_", r"[_\s]?")) + r'\b'
            if re.search(pattern, query_lower):
                blocked_terms.append(term)

        # 2. Direct PII scan
        for pii_pattern in self._PII_PATTERNS:
            if pii_pattern.search(query_text):
                if "direct_pii" not in blocked_terms:
                    blocked_terms.append("direct_pii")
                break

        gate_id = str(uuid.uuid4())

        if blocked_terms:
            refusal_message = (
                f"Query blocked: contains prohibited or sensitive content "
                f"({', '.join(blocked_terms)}). "
                "Remove references to protected-class variables, proxy variables, "
                "and direct PII before resubmitting."
            )
            return GateDecision(
                allowed=False,
                blocked_terms=blocked_terms,
                refusal_message=refusal_message,
                gate_id=gate_id,
            )

        return GateDecision(
            allowed=True,
            blocked_terms=[],
            refusal_message=None,
            gate_id=gate_id,
        )

    def log_gate_decision(self, decision: GateDecision, session_id: str) -> None:
        """
        Write a single-line JSON log entry to stderr via Python's logging module.
        WARNING level if blocked; INFO level if allowed.
        """
        entry = json.dumps(
            {
                "gate_id": decision.gate_id,
                "session_id": session_id,
                "allowed": decision.allowed,
                "blocked_terms": decision.blocked_terms,
            },
            separators=(",", ":"),
        )
        if not decision.allowed:
            logger.warning(entry)
        else:
            logger.info(entry)
