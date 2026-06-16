"""
clarification.py — POST /v1/agent/clarify

Multi-turn clarification endpoint. Accepts a previous request_id along with
slot overrides, then re-runs the pipeline with the clarifications applied.

The simplest implementation is a thin wrapper around /v1/agent/ask that
forwards the question + clarifications to DomainExpertAgent.ask().

In a future iteration this could maintain server-side session state,
but for now the client is responsible for resending the original question.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from analytics_api.src.agent.api.routes import AskResponse, _get_agent, _to_response

router = APIRouter()

_SERVICE_KEY = os.getenv("SERVICE_KEY", "")


class ClarifyRequest(BaseModel):
    request_id: str = Field(..., description="The request_id from the original clarification_needed response.")
    question: str = Field(..., description="The original question (re-sent by the client).")
    tenant_id: str = Field(default="default")
    clarifications: Dict[str, Any] = Field(
        ...,
        description="Slot overrides, e.g. {'product_type': 'PERSONAL', 'metric': 'DelinquencyRate'}.",
    )


@router.post(
    "/v1/agent/clarify",
    response_model=AskResponse,
    summary="Submit clarifications for a previous agent_ask that returned clarification_needed=true",
    tags=["agent"],
)
async def agent_clarify(
    body: ClarifyRequest,
    x_service_key: Optional[str] = Header(default=None, alias="x-service-key"),
) -> AskResponse:
    if _SERVICE_KEY and x_service_key != _SERVICE_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing x-service-key header.",
        )

    agent = _get_agent()
    result = await agent.ask(
        question=body.question,
        tenant_id=body.tenant_id,
        request_id=body.request_id,
        clarifications=body.clarifications,
    )
    return _to_response(result)
