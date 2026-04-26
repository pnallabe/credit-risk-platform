"""
specialist_agents.py — GAP-19 Multi-Agent Pipeline: Specialist Agents + Orchestrator
======================================================================================

Stage 2 of the multi-agent pipeline:

    PlannerAgent (Stage 1)
        ↓
    OrchestratorAgent (Stage 2-A)
        ├─ SQLAnalystAgent        — generates SQL → executes → interprets
        ├─ MetricsAnalystAgent    — fetches model metrics → interprets
        ├─ DriftAnalystAgent      — fetches drift report → interprets
        ├─ FairLendingAnalystAgent — fetches DIR/BISG report → interprets
        ├─ ChartGeneratorAgent    — generates Recharts spec → formats
        └─ ReportGeneratorAgent   — assembles structured report
        ↓
    SynthesizerAgent (Stage 2-B)

Each specialist agent:
  1. Calls its designated tool function (passed as a callable from main.py so the
     tool functions retain access to module-level turn-tracking state).
  2. Makes a focused LLM call to interpret the raw tool output in domain context.
  3. Returns a SpecialistResult with interpretation + code artifacts.

The OrchestratorAgent:
  1. Receives the AnalysisPlan from the PlannerAgent.
  2. Dispatches each plan step to the matching specialist.
  3. Yields SSE-ready event dicts as each specialist completes (streaming UX).
  4. Calls the SynthesizerAgent to produce a final grounded answer.

Never raises: on specialist failure a SpecialistResult with error=True is produced
and execution continues, so the synthesizer always receives a complete result set.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import AsyncGenerator, Callable, Optional

from langchain.schema import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .planner_agent import AnalysisPlan, PlanStep

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SpecialistResult:
    step_id: int
    tool_called: str
    raw_data: str            # verbatim tool output (truncated at 4 KB for storage)
    interpretation: str      # LLM-generated domain interpretation
    sql_executed: Optional[str] = None
    python_code: Optional[str] = None
    error: bool = False
    error_message: Optional[str] = None


@dataclass
class OrchestratorResult:
    step_results: list[SpecialistResult] = field(default_factory=list)
    final_answer: str = ""
    all_sql: list[str] = field(default_factory=list)
    all_python: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Base specialist
# ---------------------------------------------------------------------------

class BaseSpecialistAgent:
    """Common interpretation pattern: call tool → interpret result with focused LLM.

    Subclasses override SYSTEM_PROMPT to provide domain expertise.
    """

    SYSTEM_PROMPT: str = (
        "You are an analyst for an enterprise credit risk platform. "
        "Interpret the data returned by the tool accurately and concisely."
    )

    def __init__(self, model: str, api_key: str) -> None:
        self._llm = ChatOpenAI(model=model, temperature=0, openai_api_key=api_key)

    async def _interpret(
        self,
        step: PlanStep,
        raw_tool_output: str,
        user_query: str,
        plan_intent: str,
    ) -> str:
        """Interpret raw tool output using a domain-focused LLM call."""
        try:
            messages = [
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=(
                    f"Analysis intent: {plan_intent}\n"
                    f"Step: {step.description}\n"
                    f"User question: {user_query}\n\n"
                    f"Raw data from {step.tool}:\n{raw_tool_output[:3000]}\n\n"
                    "Provide a concise, accurate interpretation. "
                    "If a SQL query produced this data, show executable SQL in ```sql blocks. "
                    "If Python analysis is useful, show it in ```python blocks."
                )),
            ]
            response = await self._llm.ainvoke(messages)
            return response.content.strip()
        except Exception as exc:
            logger.warning(
                "Specialist %s interpretation failed: %s", self.__class__.__name__, exc
            )
            return f"Unable to interpret results: {exc}"

    async def run(
        self,
        step: PlanStep,
        tool_fn: Callable[[str], str],
        tool_input: str,
        user_query: str,
        plan_intent: str,
    ) -> SpecialistResult:
        try:
            raw = tool_fn(tool_input)
        except Exception as exc:
            return SpecialistResult(
                step_id=step.step_id,
                tool_called=step.tool,
                raw_data="",
                interpretation="",
                error=True,
                error_message=str(exc),
            )

        interpretation = await self._interpret(step, raw, user_query, plan_intent)
        return SpecialistResult(
            step_id=step.step_id,
            tool_called=step.tool,
            raw_data=raw[:4096],
            interpretation=interpretation,
            error="__ERROR__" in raw or raw.startswith("ERROR:"),
        )


# ---------------------------------------------------------------------------
# SQL Analyst Agent
# ---------------------------------------------------------------------------

class SQLAnalystAgent(BaseSpecialistAgent):
    """Generates a SQL query, executes it, and interprets the results."""

    SYSTEM_PROMPT = (
        "You are a SQL data analyst for an enterprise credit risk platform. "
        "You specialize in interpreting credit decision data, loan performance metrics, "
        "fraud indicators, and portfolio analytics. "
        "Provide precise numerical insights with context for credit risk professionals. "
        "Always cite the exact numbers from the data. "
        "Show the SQL query that produced the results in a ```sql block at the end."
    )

    async def run(
        self,
        step: PlanStep,
        tool_fn: Callable[[str], str],
        tool_input: str,          # pre-generated SQL query string
        user_query: str,
        plan_intent: str,
    ) -> SpecialistResult:
        sql_query = tool_input
        try:
            raw = tool_fn(sql_query)
        except Exception as exc:
            return SpecialistResult(
                step_id=step.step_id,
                tool_called="sql_query_tool",
                raw_data="",
                interpretation="",
                sql_executed=sql_query,
                error=True,
                error_message=str(exc),
            )

        interpretation = await self._interpret(step, raw, user_query, plan_intent)

        # Prefer the SQL from the interpretation (cleaned version) if present
        sql_match = re.search(r"```sql\s*([\s\S]*?)```", interpretation, re.IGNORECASE)
        final_sql = sql_match.group(1).strip() if sql_match else sql_query

        return SpecialistResult(
            step_id=step.step_id,
            tool_called="sql_query_tool",
            raw_data=raw[:4096],
            interpretation=interpretation,
            sql_executed=final_sql,
            error="__ERROR__" in raw or raw.startswith("ERROR:"),
        )


# ---------------------------------------------------------------------------
# Domain Specialist Agents
# ---------------------------------------------------------------------------

class MetricsAnalystAgent(BaseSpecialistAgent):
    SYSTEM_PROMPT = (
        "You are a model performance analyst for an enterprise credit risk platform. "
        "You specialize in interpreting AUC-ROC, KS statistics, F1 scores, PSI, "
        "and other ML model performance metrics in the context of credit underwriting. "
        "Explain what the metrics mean for model reliability and regulatory compliance. "
        "Flag any metrics below acceptable thresholds: AUC < 0.75, KS < 0.30, F1 < 0.65."
    )


class DriftAnalystAgent(BaseSpecialistAgent):
    SYSTEM_PROMPT = (
        "You are a data drift analyst for an enterprise credit risk platform. "
        "You specialize in interpreting PSI (Population Stability Index) and KS test results. "
        "PSI > 0.25 = significant drift requiring model review. "
        "PSI 0.10–0.25 = moderate drift. PSI < 0.10 = stable. "
        "Explain implications for model reliability and SR 11-7 model risk governance."
    )


class FairLendingAnalystAgent(BaseSpecialistAgent):
    SYSTEM_PROMPT = (
        "You are a fair lending compliance analyst for an enterprise credit risk platform. "
        "You specialize in Disparate Impact Ratios (DIR), BISG methodology, "
        "ECOA/FHA compliance, and adverse action analysis. "
        "DIR < 0.80 (the 80% rule) indicates potential disparate impact requiring review. "
        "Explain findings in terms of CFPB/OCC examination readiness. "
        "Never suggest using protected class variables in models."
    )


class ChartGeneratorAgent(BaseSpecialistAgent):
    SYSTEM_PROMPT = (
        "You are a data visualization specialist for an enterprise credit risk platform. "
        "You generate chart specifications for Recharts (React). "
        "Produce clear, accessible chart specs that highlight key credit risk insights. "
        "Always include chart title, axis labels, and data series names. "
        "Output the spec as a JSON object in a ```json block."
    )


class ReportGeneratorAgent(BaseSpecialistAgent):
    SYSTEM_PROMPT = (
        "You are a structured report writer for an enterprise credit risk platform. "
        "You produce professional reports for credit risk analysts, "
        "compliance officers, and executives. "
        "Use clear Markdown headings, bullet points for findings, and cite specific metrics. "
        "Reports must be audit-ready: cite data sources, dates, and model versions."
    )


# ---------------------------------------------------------------------------
# Specialist registry — maps tool names to specialist classes
# ---------------------------------------------------------------------------

_SPECIALIST_MAP: dict[str, type[BaseSpecialistAgent]] = {
    "sql_query_tool":        SQLAnalystAgent,
    "metrics_tool":          MetricsAnalystAgent,
    "drift_report_tool":     DriftAnalystAgent,
    "fair_lending_tool":     FairLendingAnalystAgent,
    "chart_generator_tool":  ChartGeneratorAgent,
    "report_generator_tool": ReportGeneratorAgent,
}


# ---------------------------------------------------------------------------
# SQL Generator helper
# Used by OrchestratorAgent to generate a SQL query for sql_query_tool steps.
# ---------------------------------------------------------------------------

_SQL_GENERATOR_SYSTEM_PROMPT = """\
You are a SQL expert for an enterprise credit risk platform.
Generate a single, read-only SELECT query to fulfill the analysis step described.
Output ONLY the SQL — no markdown fences, no explanation, no commentary.

Available PostgreSQL tables:
  loan_applications  (id, tenant_id, applicant_id, credit_score, income, dti,
                      loan_amount, status, created_at, decision, fraud_flag)
  decisions          (id, application_id, tenant_id, outcome, reason_codes,
                      confidence_score, model_version, decided_at)
  audit_log          (id, event_type, entity_id, actor, details, created_at,
                      record_hash)
  model_metrics      (id, model_name, model_version, auc, ks_stat, f1, gini,
                      recorded_at)
  drift_reports      (id, model_name, psi_total, features_checked,
                      drift_status, generated_at)
  fair_lending_reports (id, model_name, dir_score, bisg_method, status,
                        generated_at)
  agent_sessions     (session_id, persona, created_at, last_active, turn_count)
"""


async def _generate_sql_for_step(
    step: PlanStep,
    user_query: str,
    plan_intent: str,
    llm: ChatOpenAI,
) -> str:
    """Ask the LLM to generate a SQL SELECT for the given plan step.

    Returns a plain SQL string. Falls back to a safe no-op on any failure.
    """
    try:
        messages = [
            SystemMessage(content=_SQL_GENERATOR_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Analysis intent: {plan_intent}\n"
                f"Step: {step.description}\n"
                f"User question: {user_query}"
            )),
        ]
        response = await llm.ainvoke(messages)
        sql = response.content.strip()
        # Strip markdown fences if the model wraps despite instructions
        if sql.startswith("```"):
            sql = "\n".join(
                line for line in sql.split("\n")
                if not line.strip().startswith("```")
            ).strip()
        return sql or "SELECT 'SQL generation produced empty output' AS warning"
    except Exception as exc:
        logger.warning("SQL generator failed for step %s: %s", step.step_id, exc)
        return "SELECT 'SQL generation failed' AS error"


# ---------------------------------------------------------------------------
# Synthesizer system prompt
# ---------------------------------------------------------------------------

_SYNTHESIZER_SYSTEM_PROMPT = """\
You are the Answer Synthesizer for an enterprise credit risk platform.
You receive structured analysis results from multiple specialist agents and produce
a single, coherent, grounded answer for the user.

Rules:
1. Only use information from the specialist results — never hallucinate numbers or facts.
2. Cite specific numbers and metrics directly from the data.
3. If a specialist returned an error or no data, acknowledge the limitation honestly.
4. If Python analysis would help clarify the findings, include it in ```python blocks.
5. Use bullet points for multiple findings; keep the answer concise but complete.
6. End with a one-sentence confidence summary that references the data source(s).
"""


# ---------------------------------------------------------------------------
# OrchestratorAgent
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    """Multi-agent orchestrator — GAP-19 Stage 2.

    Dispatches each plan step to a specialist agent that:
      1. Calls the appropriate tool (passed from main.py via ``tool_registry``).
      2. Interprets the result with a domain-focused LLM call.

    Then synthesizes all specialist outputs into a final grounded answer via
    the SynthesizerAgent (a structured GPT-4o call).

    Parameters
    ----------
    model : str
        OpenAI model name (e.g. ``"gpt-4o"``).
    api_key : str
        OpenAI API key.
    tool_registry : dict[str, Callable[[str], str]]
        Maps tool name → callable.  Passed from main.py so tool functions
        retain access to module-level turn-tracking state
        (``_ACTIVE_TURN_ID``, ``_TURN_SQL_RESULTS``, ``_TURN_LOCK``).
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        tool_registry: dict[str, Callable[[str], str]],
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._tool_registry = tool_registry
        # Shared LLM instance used for SQL generation and synthesis
        self._llm = ChatOpenAI(model=model, temperature=0, openai_api_key=api_key)

    def _get_specialist(self, tool_name: str) -> BaseSpecialistAgent:
        cls = _SPECIALIST_MAP.get(tool_name, BaseSpecialistAgent)
        return cls(model=self._model, api_key=self._api_key)

    async def astream(
        self,
        plan: AnalysisPlan,
        user_query: str,
        conversation_history: str = "",
    ) -> AsyncGenerator[dict, None]:
        """Async generator yielding SSE-ready event dicts as the pipeline executes.

        Event types emitted (keyed by ``"event"``):
          ``specialist_start``    — emitted before each specialist runs.
          ``specialist_complete`` — emitted after each specialist finishes.
          ``synthesis_token``     — one token from the streaming synthesizer call.
          ``synthesis_complete``  — final answer + extracted Python code blocks.
        """
        step_results: list[SpecialistResult] = []

        for step in plan.steps:
            tool_fn = self._tool_registry.get(step.tool)
            if tool_fn is None:
                logger.warning(
                    "No tool registered for '%s'; skipping step %s",
                    step.tool, step.step_id,
                )
                continue

            yield {
                "event": "specialist_start",
                "step_id": step.step_id,
                "tool": step.tool,
                "description": step.description,
            }

            specialist = self._get_specialist(step.tool)

            # SQL steps: generate the query first; all other steps pass empty string.
            if step.tool == "sql_query_tool":
                tool_input = await _generate_sql_for_step(
                    step, user_query, plan.intent, self._llm
                )
            else:
                tool_input = ""

            result = await specialist.run(
                step=step,
                tool_fn=tool_fn,
                tool_input=tool_input,
                user_query=user_query,
                plan_intent=plan.intent,
            )
            step_results.append(result)

            yield {
                "event": "specialist_complete",
                "step_id": step.step_id,
                "tool": step.tool,
                "interpretation": result.interpretation,
                "sql_executed": result.sql_executed,
                "error": result.error,
            }

        # --- Synthesizer: combine specialist outputs into final grounded answer ---
        specialist_summaries = "\n\n".join(
            f"[Step {r.step_id} — {r.tool_called}]\n"
            + (f"SQL executed:\n```sql\n{r.sql_executed}\n```\n" if r.sql_executed else "")
            + r.interpretation
            for r in step_results
        )

        synthesizer_input = (
            f"User question: {user_query}\n\n"
            f"Analysis plan intent: {plan.intent}\n\n"
            f"Specialist results:\n{specialist_summaries}"
        )
        if conversation_history:
            synthesizer_input = (
                f"Previous conversation:\n{conversation_history}\n\n" + synthesizer_input
            )

        final_answer_parts: list[str] = []
        try:
            messages = [
                SystemMessage(content=_SYNTHESIZER_SYSTEM_PROMPT),
                HumanMessage(content=synthesizer_input),
            ]
            async for chunk in self._llm.astream(messages):
                tok = chunk.content if hasattr(chunk, "content") else str(chunk)
                if tok:
                    final_answer_parts.append(tok)
                    yield {"event": "synthesis_token", "token": tok}
        except Exception as exc:
            logger.error("Synthesizer failed: %s", exc)
            # Fallback: join non-error specialist interpretations
            fallback = "\n\n".join(
                r.interpretation for r in step_results if not r.error and r.interpretation
            )
            if not fallback:
                fallback = "Unable to synthesize results. Please try a more specific question."
            final_answer_parts.append(fallback)
            yield {"event": "synthesis_token", "token": fallback}

        final_answer = "".join(final_answer_parts)

        # Extract Python code blocks from the synthesized answer for artifact storage
        python_blocks = re.findall(
            r"```python\s*([\s\S]*?)```", final_answer, re.IGNORECASE
        )

        yield {
            "event": "synthesis_complete",
            "answer": final_answer,
            "python_code": [b.strip() for b in python_blocks if b.strip()],
        }
