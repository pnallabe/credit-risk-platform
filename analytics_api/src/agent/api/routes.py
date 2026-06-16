"""
routes.py — POST /v1/agent/ask

FastAPI router for the Semantic Intelligence agent endpoint.
Auth: same x-service-key header used by the existing /v1/analytics/s2s/ask endpoint.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from analytics_api.src.agent.config import AgentConfig
from analytics_api.src.agent.orchestrator import AgentResponse, DomainExpertAgent

router = APIRouter()

_SERVICE_KEY = os.getenv("SERVICE_KEY", "")
_agent: Optional[DomainExpertAgent] = None


def _get_agent() -> DomainExpertAgent:
    global _agent
    if _agent is None:
        _agent = DomainExpertAgent(config=AgentConfig())
    return _agent


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(..., description="Natural language question about the credit portfolio.")
    tenant_id: str = Field(default="default")
    clarifications: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Slot overrides to resolve a previous clarification_needed response.",
    )


class RuleViolation(BaseModel):
    rule: str
    reason: str


class AskResponse(BaseModel):
    request_id: str
    question: str
    answer: str
    sql: Optional[str] = None
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    row_count: int
    metric: Optional[str] = None
    source: Optional[str] = None
    clarification_needed: bool
    clarification_reason: Optional[str] = None
    rule_violations: List[RuleViolation] = Field(default_factory=list)
    execution_ms: int
    error: Optional[str] = None


def _to_response(ar: AgentResponse) -> AskResponse:
    return AskResponse(
        request_id=ar.request_id,
        question=ar.question,
        answer=ar.answer,
        sql=ar.sql,
        rows=ar.rows,
        row_count=ar.row_count,
        metric=ar.metric,
        source=ar.source,
        clarification_needed=ar.clarification_needed,
        clarification_reason=ar.clarification_reason,
        rule_violations=[RuleViolation(**v) for v in ar.rule_violations],
        execution_ms=ar.execution_ms,
        error=ar.error,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/v1/agent/ask",
    response_model=AskResponse,
    summary="Semantic Intelligence Agent — ask a question about the credit portfolio",
    tags=["agent"],
)
async def agent_ask(
    body: AskRequest,
    x_service_key: Optional[str] = Header(default=None, alias="x-service-key"),
) -> AskResponse:
    """Answer a natural language question using the 4-layer Semantic Intelligence pipeline."""
    if _SERVICE_KEY and x_service_key != _SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing x-service-key header.",
        )

    agent = _get_agent()
    result = await agent.ask(
        question=body.question,
        tenant_id=body.tenant_id,
        clarifications=body.clarifications,
    )
    return _to_response(result)
