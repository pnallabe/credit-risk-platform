"""
planner_agent.py — GAP-19 Multi-Agent Pipeline: Stage 1 Planner
================================================================
Stage 1 of the two-stage agent pipeline:

    PlannerAgent  →  ExecutorAgent (existing LangChain ReAct loop)

The PlannerAgent makes a single structured LLM call to generate an AnalysisPlan
before any tools are invoked. The plan is:

  - Emitted as a ``"plan"`` SSE event so the frontend can show step-by-step
    progress to the user before execution begins.
  - Injected as a preamble into the ReAct executor prompt so the agent
    follows the plan instead of discovering steps ad-hoc.
  - Stored verbatim in ``ai_agent_audit_log.plan_text`` (GNRI-011).

Never raises: falls back to a minimal one-step plan on any LLM or parse failure
so the ExecutorAgent is never blocked.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Planner system prompt
# ---------------------------------------------------------------------------
_PLANNER_SYSTEM_PROMPT = """\
You are the Analysis Planner for an enterprise credit risk platform.
Your job is to produce a structured, step-by-step analysis plan for the user's
question BEFORE any data is retrieved.

OUTPUT FORMAT
-------------
Output ONLY a valid JSON object — no markdown fences, no prose, no commentary.
The JSON must match this schema exactly:

{
  "intent": "<one-sentence description of what will be computed>",
  "data_sources": ["<table or view name>", ...],
  "steps": [
    {
      "step_id": 1,
      "description": "<what this step does>",
      "tool": "<one of the tools listed below>",
      "rationale": "<why this step is necessary>"
    }
  ],
  "validation_checks": ["<plain-English validation check>", ...],
  "output_type": "summary | table | chart | report"
}

AVAILABLE TOOLS
---------------
- sql_query_tool        — run a read-only SELECT query against the decisions DB
- metrics_tool          — retrieve latest model performance metrics (AUC, KS, F1)
- drift_report_tool     — fetch the latest data drift / PSI report
- fair_lending_tool     — fetch the latest fair lending / DIR report
- chart_generator_tool  — generate a chart specification for frontend rendering
- report_generator_tool — produce a structured report document

CONSTRAINTS
-----------
- Plan at most 5 steps.
- Use ONLY the tools listed above.
- Include at least one validation_check.
- Keep each description under 120 characters.
"""


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class PlanStep(BaseModel):
    step_id: int
    description: str
    tool: str
    rationale: str


class AnalysisPlan(BaseModel):
    intent: str
    data_sources: list[str] = []
    steps: list[PlanStep] = []
    validation_checks: list[str] = []
    output_type: str = "summary"

    def to_executor_preamble(self) -> str:
        """Return a human-readable plan string to inject into the ReAct prompt."""
        lines = [f"ANALYSIS PLAN: {self.intent}", ""]
        for step in self.steps:
            lines.append(f"Step {step.step_id}: {step.description} (tool: {step.tool})")
        if self.validation_checks:
            lines.append("")
            lines.append("Validation: " + "; ".join(self.validation_checks))
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Fallback plan (returned on any planner failure — never blocks execution)
# ---------------------------------------------------------------------------

def _fallback_plan(user_query: str) -> AnalysisPlan:
    return AnalysisPlan(
        intent=user_query[:120],
        data_sources=[],
        steps=[
            PlanStep(
                step_id=1,
                description="Execute SQL query to retrieve relevant data.",
                tool="sql_query_tool",
                rationale="Direct data retrieval to answer the question.",
            )
        ],
        validation_checks=["Verify row count > 0"],
        output_type="summary",
    )


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent:
    """Single-LLM-call planner that produces a structured AnalysisPlan.

    Parameters
    ----------
    model:
        OpenAI model name (e.g. ``"gpt-4o"``).
    api_key:
        OpenAI API key.
    """

    def __init__(self, model: str, api_key: str) -> None:
        self._llm = ChatOpenAI(
            model=model,
            temperature=0,
            openai_api_key=api_key,
        )

    async def plan(self, user_query: str) -> AnalysisPlan:
        """Generate an AnalysisPlan for *user_query*.

        Returns a minimal fallback plan on any LLM call or JSON parse failure
        so the ExecutorAgent is never blocked.
        """
        try:
            from langchain.schema import HumanMessage, SystemMessage  # noqa: PLC0415

            messages = [
                SystemMessage(content=_PLANNER_SYSTEM_PROMPT),
                HumanMessage(content=user_query),
            ]
            response = await self._llm.ainvoke(messages)
            raw: str = response.content.strip()

            # Strip markdown fences if the model wraps despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            data = json.loads(raw)
            return AnalysisPlan(
                intent=data.get("intent", user_query[:120]),
                data_sources=data.get("data_sources", []),
                steps=[PlanStep(**s) for s in data.get("steps", [])],
                validation_checks=data.get("validation_checks", []),
                output_type=data.get("output_type", "summary"),
            )
        except Exception as exc:
            logger.warning("PlannerAgent: falling back to minimal plan (%s)", exc)
            return _fallback_plan(user_query)
