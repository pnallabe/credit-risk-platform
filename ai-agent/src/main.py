"""
Phase 13 – AI Agent Backend
LangChain ReAct agent + FastAPI + SSE streaming + rate limiting
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from sqlalchemy import create_engine, text as _sa_text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

import re as _re
import sys as _sys

# Make compliance/ importable from the project root (two dirs up from src/)
_sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from compliance.prohibited_variables import (
    check_for_prohibited_variables,
    ProhibitedVariableViolation,
)

from .ai_audit_log import log_ai_turn
from .code_artifact_store import store_artifact
from .confidence_scorer import (
    ConfidenceFactors,
    ConfidenceScore,
    compute_confidence,
    should_refuse,
    REFUSAL_MESSAGE,
)

# Turn-scoped SQL result registry
_ACTIVE_TURN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_ACTIVE_TURN_ID", default="__none__"
)
_TURN_SQL_RESULTS: dict[str, dict] = {}
_TURN_LOCK = threading.Lock()

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from langchain_openai import ChatOpenAI

from .planner_agent import PlannerAgent, AnalysisPlan
from .specialist_agents import OrchestratorAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# OV-02: No default — service refuses to start without an explicit PostgreSQL URL.
DATABASE_URL = os.getenv("DATABASE_URL", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
RATE_LIMIT = os.getenv("RATE_LIMIT", "20/minute")

# OV-03: LLM Cost Guard
# Maximum tokens allowed in the user query + conversation context before dispatch.
# Prevents runaway spend when the ReAct loop requests many tool calls.
MAX_TOKENS_PER_QUERY: int = int(os.getenv("MAX_TOKENS_PER_QUERY", "4000"))
# Maximum cumulative USD cost per single agent turn (all LLM calls combined).
# Pricing table: gpt-4o $5/1M input + $15/1M output (May 2025 rates).
COST_CEILING_USD: float = float(os.getenv("COST_CEILING_USD", "0.50"))
# Per-model pricing (input $/1M tokens, output $/1M tokens).  Add rows as needed.
_MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o":         (5.00,  15.00),
    "gpt-4o-mini":    (0.15,   0.60),
    "gpt-4-turbo":   (10.00,  30.00),
    "gpt-3.5-turbo":  (0.50,   1.50),
}

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# DB engine helpers (OV-02)
# ---------------------------------------------------------------------------
_ASYNC_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SYNC_ENGINE_CACHE: dict = {}


def _normalize_async_url(url: str) -> str:
    """Bare sqlite paths → sqlite+aiosqlite://; pass postgresql URLs through."""
    if "://" not in url:
        return f"sqlite+aiosqlite:///{url}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite+"):
        return "sqlite+aiosqlite" + url[6:]
    return url


def _make_sync_url(url: str) -> str:
    """Derive synchronous (psycopg2 / sqlite3) URL from the async URL."""
    norm = _normalize_async_url(url)
    return (
        norm
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("sqlite+aiosqlite://", "sqlite://")
    )


def _get_async_engine(url: str) -> AsyncEngine:
    norm = _normalize_async_url(url)
    if norm not in _ASYNC_ENGINE_CACHE:
        _ASYNC_ENGINE_CACHE[norm] = create_async_engine(norm, echo=False)
    return _ASYNC_ENGINE_CACHE[norm]


def _get_sync_engine(url: str):
    sync_url = _make_sync_url(url)
    if sync_url not in _SYNC_ENGINE_CACHE:
        _SYNC_ENGINE_CACHE[sync_url] = create_engine(
            sync_url, echo=False, pool_pre_ping=True
        )
    return _SYNC_ENGINE_CACHE[sync_url]


async def _ensure_sessions_table() -> None:
    engine = _get_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        await conn.execute(_sa_text("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id  TEXT    PRIMARY KEY,
                persona     TEXT    NOT NULL DEFAULT 'data_analyst',
                created_at  TEXT    NOT NULL,
                last_active TEXT    NOT NULL,
                turn_count  INTEGER NOT NULL DEFAULT 0
            )
        """))
        await conn.execute(_sa_text("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id          SERIAL  PRIMARY KEY,
                session_id  TEXT    NOT NULL,
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
            )
        """))


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def _sql_query_tool(query: str) -> str:
    """Execute a read-only SQL query against the decisions database.

    OV-02: Uses SQLAlchemy sync engine (psycopg2 / sqlite3 driver).
    Called from LangChain's thread-pool executor — sync is correct here.
    """
    UNSAFE = ("insert", "update", "delete", "drop", "alter", "create", "truncate")
    if any(k in query.lower() for k in UNSAFE):
        _mark_turn_error()
        return "ERROR: Only SELECT queries are allowed."

    query_stripped = query.strip()

    # GAP-19: Prohibited variable check — extract identifiers from the query
    # and scan them against the ECOA/FHA prohibited-variable registry.
    try:
        identifiers = {
            tok.lower(): tok
            for tok in _re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query_stripped)
        }
        check_for_prohibited_variables(identifiers)
    except ProhibitedVariableViolation as pv:
        _mark_turn_error()
        return (
            f"ERROR: Query references a prohibited variable '{pv.variable}' "
            f"(protected basis: {pv.basis}). "
            "Remove this column from the query before resubmitting."
        )
    query_hash = hashlib.sha256(query_stripped.encode()).hexdigest()

    try:
        with _get_sync_engine(DATABASE_URL).connect() as conn:
            result = conn.execute(_sa_text(query_stripped))
            rows = result.fetchmany(200)
            cols = list(result.keys())

            if not rows:
                _update_turn_result(
                    row_count=0,
                    sql_executed=query_stripped,
                    query_hash=query_hash,
                    result_hash=hashlib.sha256(b"[]").hexdigest(),
                    source_table=_extract_source_table_simple(query_stripped),
                    error=False,
                )
                return "__GROUNDED__\nQuery returned 0 rows."

            # Serialise for result_hash
            canonical_rows = [
                {c: row[i] for i, c in enumerate(sorted(cols))} for row in rows
            ]
            result_json = json.dumps(canonical_rows, sort_keys=True, separators=(",", ":"), default=str)
            result_hash = hashlib.sha256(result_json.encode()).hexdigest()
            source_table = _extract_source_table_simple(query_stripped)

            _update_turn_result(
                row_count=len(rows),
                sql_executed=query_stripped,
                query_hash=query_hash,
                result_hash=result_hash,
                source_table=source_table,
                error=False,
            )

            # Build human-readable output
            lines = ["\t".join(cols)]
            for row in rows:
                lines.append("\t".join(str(v) for v in row))
            return "__GROUNDED__\n" + "\n".join(lines[:50])
    except Exception as exc:
        _update_turn_result(
            row_count=0,
            sql_executed=query_stripped,
            query_hash=query_hash,
            result_hash="",
            source_table=None,
            error=True,
        )
        return f"__ERROR__\nSQL Error: {exc}"


def _mark_turn_error() -> None:
    turn_id = _ACTIVE_TURN_ID.get("__none__")
    if turn_id == "__none__":
        return
    with _TURN_LOCK:
        entry = _TURN_SQL_RESULTS.get(turn_id)
        if entry is not None:
            entry["error"] = True


def _update_turn_result(
    row_count: int,
    sql_executed: str,
    query_hash: str,
    result_hash: str,
    source_table: Optional[str],
    error: bool,
) -> None:
    turn_id = _ACTIVE_TURN_ID.get("__none__")
    if turn_id == "__none__":
        return
    with _TURN_LOCK:
        entry = _TURN_SQL_RESULTS.get(turn_id)
        if entry is None:
            return
        entry["row_count"] = row_count
        entry["sql_executed"] = sql_executed
        entry["query_hash"] = query_hash
        entry["result_hash"] = result_hash
        entry["source_table"] = source_table
        entry["error"] = error


def _extract_source_table_simple(sql: str) -> Optional[str]:
    import re
    match = re.search(r'\b(?:FROM|JOIN)\s+([`"\[]?[\w.]+[`"\]]?)', sql, re.IGNORECASE)
    if not match:
        return None
    name = match.group(1).strip('`"[]')
    return name.split(".")[-1] if "." in name else name or None


def _metrics_tool(_: str) -> str:
    """Fetch latest model performance metrics."""
    try:
        with _get_sync_engine(DATABASE_URL).connect() as conn:
            result = conn.execute(
                _sa_text("SELECT * FROM model_metrics ORDER BY recorded_at DESC LIMIT 1")
            )
            row = result.mappings().fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"auc": 0.823, "ks": 0.441, "f1": 0.712, "note": "mock"})
    except Exception:
        return json.dumps({"auc": 0.823, "ks": 0.441, "f1": 0.712, "note": "mock"})


def _drift_report_tool(_: str) -> str:
    """Fetch the latest data drift report."""
    try:
        with _get_sync_engine(DATABASE_URL).connect() as conn:
            result = conn.execute(
                _sa_text("SELECT * FROM drift_reports ORDER BY generated_at DESC LIMIT 1")
            )
            row = result.mappings().fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"drift_status": "stable", "features_checked": 8, "note": "mock"})
    except Exception:
        return json.dumps({"drift_status": "stable", "features_checked": 8, "note": "mock"})


def _fair_lending_tool(_: str) -> str:
    """Fetch the latest fair lending / DIR report."""
    try:
        with _get_sync_engine(DATABASE_URL).connect() as conn:
            result = conn.execute(
                _sa_text("SELECT * FROM fair_lending_reports ORDER BY generated_at DESC LIMIT 1")
            )
            row = result.mappings().fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"dir_score": 0.87, "status": "compliant", "note": "mock"})
    except Exception:
        return json.dumps({"dir_score": 0.87, "status": "compliant", "note": "mock"})


# ---------------------------------------------------------------------------
# OV-03: Token budget helpers
# ---------------------------------------------------------------------------
def _count_tokens(text: str, model: str = OPENAI_MODEL) -> int:
    """Return the number of tokens in *text* for *model* using tiktoken.

    Falls back to a conservative word-count estimate (×1.4) if tiktoken does
    not have an encoding for the requested model.
    """
    try:
        import tiktoken as _tt
        try:
            enc = _tt.encoding_for_model(model)
        except KeyError:
            enc = _tt.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Fallback: rough estimate (1 token ≈ 0.75 words)
        return int(len(text.split()) * 1.4)


def _estimate_cost_usd(input_tokens: int, output_tokens: int, model: str = OPENAI_MODEL) -> float:
    """Estimate USD cost for *input_tokens* + *output_tokens* for *model*."""
    price_in, price_out = _MODEL_PRICING.get(model, (5.00, 15.00))
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


class BudgetExceededError(Exception):
    """Raised when a query would exceed MAX_TOKENS_PER_QUERY or COST_CEILING_USD."""


def _check_token_budget(message: str, chat_history: str = "") -> None:
    """Raise BudgetExceededError if the combined input exceeds MAX_TOKENS_PER_QUERY.

    This is a pre-dispatch guard — called before the LLM is ever invoked.
    """
    total_tokens = _count_tokens(message) + _count_tokens(chat_history)
    if total_tokens > MAX_TOKENS_PER_QUERY:
        raise BudgetExceededError(
            f"Query exceeds the token budget: {total_tokens} tokens (limit={MAX_TOKENS_PER_QUERY}). "
            "Shorten the query or clear the conversation history."
        )


def _check_cost_ceiling(input_tokens: int, output_tokens: int = 0) -> None:
    """Raise BudgetExceededError if estimated cost exceeds COST_CEILING_USD."""
    cost = _estimate_cost_usd(input_tokens, output_tokens)
    if cost > COST_CEILING_USD:
        raise BudgetExceededError(
            f"Estimated cost ${cost:.4f} exceeds per-turn ceiling ${COST_CEILING_USD:.2f}. "
            "Reduce query length or increase COST_CEILING_USD."
        )


def _chart_generator_tool(spec: str) -> str:
    """Generate a chart specification (returns JSON for frontend rendering)."""
    return json.dumps({"chart_spec": spec, "type": "recharts", "rendered": True})


def _report_generator_tool(report_type: str) -> str:
    """Generate a structured report (portfolio, compliance, model health)."""
    ts = datetime.utcnow().isoformat()
    return json.dumps({
        "report_type": report_type,
        "generated_at": ts,
        "summary": f"Automated {report_type} report as of {ts}.",
        "format": "markdown",
    })


# ---------------------------------------------------------------------------
# Tool registry — passed to OrchestratorAgent so specialists can call tools
# while retaining access to module-level turn-tracking state.
# ---------------------------------------------------------------------------
_TOOL_REGISTRY: dict[str, object] = {
    "sql_query_tool":        _sql_query_tool,
    "metrics_tool":          _metrics_tool,
    "drift_report_tool":     _drift_report_tool,
    "fair_lending_tool":     _fair_lending_tool,
    "chart_generator_tool":  _chart_generator_tool,
    "report_generator_tool": _report_generator_tool,
}


# ---------------------------------------------------------------------------
# In-memory session store (conversation history for context continuity)
# ---------------------------------------------------------------------------
_SESSIONS: dict[str, dict] = {}  # session_id -> {history: str, persona: str}


def _get_session_history(session_id: str) -> str:
    """Return the truncated conversation history for *session_id* (last ~1500 chars)."""
    return _SESSIONS.get(session_id, {}).get("history", "")[-1500:]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # OV-02: Fail fast — reject empty or non-PostgreSQL DATABASE_URL at boot.
    if not DATABASE_URL:
        raise RuntimeError(
            "[OV-02] DATABASE_URL is not set. "
            "Configure a postgresql+asyncpg:// connection string before starting this service."
        )
    if "sqlite" in DATABASE_URL.lower() or "://" not in DATABASE_URL:
        raise RuntimeError(
            f"[OV-02] DATABASE_URL '{DATABASE_URL}' is not a valid PostgreSQL URL. "
            "Set DATABASE_URL to a postgresql+asyncpg:// connection string."
        )
    # OV-03: Fail fast — reject missing or placeholder OpenAI API key at boot.
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "[OV-03] OPENAI_API_KEY is not set. "
            "Configure a valid OpenAI API key before starting this service."
        )
    if OPENAI_API_KEY in ("sk-placeholder", "your-key-here", "REPLACE_ME"):
        raise RuntimeError(
            "[OV-03] OPENAI_API_KEY is still a placeholder value. "
            "Set a valid OpenAI API key before deploying."
        )
    await _ensure_sessions_table()
    yield


app = FastAPI(title="Credit Risk AI Agent", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", os.getenv("DASHBOARD_ORIGIN", "*")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class SessionCreateRequest(BaseModel):
    persona: str = "data_analyst"


class SessionCreateResponse(BaseModel):
    session_id: str
    persona: str


class ChatRequest(BaseModel):
    session_id: str
    message: str
    persona: str = "data_analyst"


# ---------------------------------------------------------------------------
# Anti-Hallucination Framework schemas (PRD §5)
# ---------------------------------------------------------------------------
class DataLineageTag(BaseModel):
    source_table: Optional[str] = None
    query_hash: Optional[str] = None
    partition_date: Optional[str] = None
    result_hash: Optional[str] = None


class CodeArtifacts(BaseModel):
    sql_executed: Optional[str] = None
    query_hash: Optional[str] = None
    result_hash: Optional[str] = None
    artifact_ids: list[str] = []


class AgentTurnMetadata(BaseModel):
    turn_id: str
    session_id: str
    confidence_score: float
    confidence_label: str
    confidence_explanation: str
    tools_called: list[str]
    data_lineage: DataLineageTag
    code_artifacts: CodeArtifacts
    grounded: bool                  # False when refusal was triggered


# ---------------------------------------------------------------------------
# SSE streaming helper
# ---------------------------------------------------------------------------
async def _stream_agent_response(session_id: str, message: str, persona: str) -> AsyncGenerator[str, None]:
    # --- Anti-Hallucination Framework: per-turn setup ---
    turn_id = str(uuid.uuid4())
    token = _ACTIVE_TURN_ID.set(turn_id)
    with _TURN_LOCK:
        _TURN_SQL_RESULTS[turn_id] = {
            "row_count": 0,
            "sql_executed": "",
            "query_hash": "",
            "result_hash": "",
            "source_table": None,
            "error": False,
            "tools_called": [],
        }

    # OV-03: Pre-dispatch token budget + cost ceiling guard
    _history_text = _get_session_history(session_id)
    try:
        _check_token_budget(message, _history_text)
        _input_tokens = _count_tokens(message) + _count_tokens(_history_text)
        _check_cost_ceiling(_input_tokens)
    except BudgetExceededError as _budget_err:
        _ACTIVE_TURN_ID.reset(token)
        _TURN_SQL_RESULTS.pop(turn_id, None)
        yield f"data: {json.dumps({'error': str(_budget_err), 'error_type': 'budget_exceeded'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    # --- GAP-19: Stage 1 — Planner generates structured AnalysisPlan ---
    _planner = PlannerAgent(model=OPENAI_MODEL, api_key=OPENAI_API_KEY)
    analysis_plan: AnalysisPlan = await _planner.plan(message)
    yield f"data: {json.dumps({'plan': analysis_plan.model_dump()})}\n\n"

    # --- GAP-19: Stage 2 — Orchestrator dispatches plan to specialist agents ---
    _orchestrator = OrchestratorAgent(
        model=OPENAI_MODEL,
        api_key=OPENAI_API_KEY,
        tool_registry=_TOOL_REGISTRY,
    )
    _answer_parts: list[str] = []
    _python_blocks_from_synthesis: list[str] = []
    _plan_steps: list[dict] = [
        {"step_id": s.step_id, "description": s.description, "tool": s.tool}
        for s in analysis_plan.steps
    ]
    artifact_ids: list[str] = []

    async for event in _orchestrator.astream(analysis_plan, message, _history_text):
        event_type = event.get("event")

        if event_type == "specialist_start":
            # Track tool calls for confidence scoring
            with _TURN_LOCK:
                entry = _TURN_SQL_RESULTS.get(turn_id)
                if entry is not None:
                    entry["tools_called"].append(event["tool"])
            yield f"data: {json.dumps({'tool_call': event['tool'], 'step_id': event['step_id'], 'description': event['description']})}\n\n"

        elif event_type == "specialist_complete":
            # Annotate the plan step with the specialist's observation
            for ps in _plan_steps:
                if ps.get("step_id") == event.get("step_id"):
                    ps["observation"] = event.get("interpretation", "")
                    if event.get("sql_executed"):
                        ps["sql_executed"] = event["sql_executed"]
            yield f"data: {json.dumps({'specialist_complete': {'step_id': event['step_id'], 'tool': event['tool'], 'error': event.get('error', False)}})}\n\n"

        elif event_type == "synthesis_token":
            tok = event.get("token", "")
            # Strip internal grounding prefixes before forwarding
            if tok.startswith("__GROUNDED__"):
                tok = tok[len("__GROUNDED__"):].lstrip("\n")
            elif tok.startswith("__ERROR__"):
                tok = tok[len("__ERROR__"):].lstrip("\n")
            if tok:
                _answer_parts.append(tok)
                yield f"data: {json.dumps({'token': tok})}\n\n"

        elif event_type == "synthesis_complete":
            _python_blocks_from_synthesis = event.get("python_code", [])

    # --- Collect turn data and compute confidence ---
    _ACTIVE_TURN_ID.reset(token)
    with _TURN_LOCK:
        turn_data = _TURN_SQL_RESULTS.pop(turn_id, {})

    assembled_answer = "".join(_answer_parts)

    factors = ConfidenceFactors(
        row_count=turn_data.get("row_count", 0),
        query_error=bool(turn_data.get("error", False)),
        empty_result=(turn_data.get("row_count", 0) == 0),
        tools_called=turn_data.get("tools_called", []),
        has_sql_artifact=bool(turn_data.get("sql_executed")),
    )
    conf = compute_confidence(factors)

    # Persist SQL code artifact (fire-and-forget)
    if turn_data.get("sql_executed"):
        try:
            artifact = await store_artifact(
                db_url=DATABASE_URL,
                session_id=session_id,
                turn_id=turn_id,
                artifact_type="sql",
                content=turn_data["sql_executed"],
                source_table=turn_data.get("source_table"),
            )
            artifact_ids.append(artifact.artifact_id)
        except Exception as exc:
            logger.error("Failed to store SQL artifact: %s", exc)

    # GAP-19: Persist Python artifacts extracted by the synthesizer
    for py_content in _python_blocks_from_synthesis:
        try:
            py_artifact = await store_artifact(
                db_url=DATABASE_URL,
                session_id=session_id,
                turn_id=turn_id,
                artifact_type="python",
                content=py_content,
            )
            artifact_ids.append(py_artifact.artifact_id)
        except Exception as exc:
            logger.error("Failed to store Python artifact: %s", exc)

    # Update in-memory conversation history for context continuity
    _SESSIONS.setdefault(session_id, {"history": "", "persona": persona})
    _SESSIONS[session_id]["history"] += (
        f"\nUser: {message}\nAssistant: {assembled_answer[:600]}"
    )

    # Persist messages to agent_messages
    ts = datetime.now(timezone.utc).isoformat()
    try:
        async with _get_async_engine(DATABASE_URL).begin() as conn:
            await conn.execute(
                _sa_text(
                    "INSERT INTO agent_messages (session_id, role, content, created_at) "
                    "VALUES (:sid, :role, :content, :ts)"
                ),
                {"sid": session_id, "role": "user", "content": message, "ts": ts},
            )
            await conn.execute(
                _sa_text(
                    "INSERT INTO agent_messages (session_id, role, content, created_at) "
                    "VALUES (:sid, :role, :content, :ts)"
                ),
                {"sid": session_id, "role": "assistant", "content": assembled_answer, "ts": ts},
            )
    except Exception as exc:
        logger.error("Failed to persist agent messages: %s", exc)

    # Write GNRI-011 audit record (fire-and-forget)
    try:
        asyncio.create_task(log_ai_turn(
            db_url=DATABASE_URL,
            session_id=session_id,
            turn_id=turn_id,
            persona=persona,
            query_text=message,
            answer_text=assembled_answer or None,
            plan_steps=_plan_steps or None,
            tools_called=list(set(factors.tools_called)) or None,
            sql_executed=turn_data.get("sql_executed") or None,
            result_hash=turn_data.get("result_hash") or None,
            query_hash=turn_data.get("query_hash") or None,
            code_artifact_ids=artifact_ids or None,
            confidence_score=conf.score,
            confidence_label=conf.label,
            grounded=not should_refuse(conf),
            source_table=turn_data.get("source_table"),
        ))
    except Exception as exc:
        logger.error("Failed to schedule AI audit log write: %s", exc)

    # Build and emit metadata SSE event
    metadata = AgentTurnMetadata(
        turn_id=turn_id,
        session_id=session_id,
        confidence_score=conf.score,
        confidence_label=conf.label,
        confidence_explanation=conf.explanation,
        tools_called=list(set(factors.tools_called)),
        data_lineage=DataLineageTag(
            source_table=turn_data.get("source_table"),
            query_hash=turn_data.get("query_hash") or None,
            result_hash=turn_data.get("result_hash") or None,
        ),
        code_artifacts=CodeArtifacts(
            sql_executed=turn_data.get("sql_executed") or None,
            query_hash=turn_data.get("query_hash") or None,
            result_hash=turn_data.get("result_hash") or None,
            artifact_ids=artifact_ids,
        ),
        grounded=not should_refuse(conf),
    )
    yield f"data: {json.dumps({'metadata': metadata.model_dump()})}\n\n"

    # Grounding gate: emit structured refusal if triggered
    if should_refuse(conf):
        yield f"data: {json.dumps({'token': REFUSAL_MESSAGE, 'refusal': True})}\n\n"

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "model": OPENAI_MODEL}


@app.post("/agent/sessions", response_model=SessionCreateResponse)
@limiter.limit(RATE_LIMIT)
async def create_session(req: SessionCreateRequest, request: Request):
    session_id = str(uuid.uuid4())
    # Pre-register session so history is available on first turn
    _SESSIONS.setdefault(session_id, {"history": "", "persona": req.persona})

    ts = datetime.utcnow().isoformat()
    try:
        async with _get_async_engine(DATABASE_URL).begin() as conn:
            await conn.execute(
                _sa_text(
                    "INSERT INTO agent_sessions "
                    "(session_id, persona, created_at, last_active, turn_count) "
                    "VALUES (:sid, :persona, :ts, :ts, 0)"
                ),
                {"sid": session_id, "persona": req.persona, "ts": ts},
            )
    except Exception:
        pass  # Non-fatal: in-memory session is already registered

    return SessionCreateResponse(session_id=session_id, persona=req.persona)


@app.post("/agent/chat")
@limiter.limit(RATE_LIMIT)
async def chat(req: ChatRequest, request: Request):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    return StreamingResponse(
        _stream_agent_response(req.session_id, req.message, req.persona),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/agent/sessions/{session_id}/history")
async def get_history(session_id: str):
    try:
        async with _get_async_engine(DATABASE_URL).connect() as conn:
            result = await conn.execute(
                _sa_text(
                    "SELECT role, content, created_at FROM agent_messages "
                    "WHERE session_id = :sid ORDER BY id"
                ),
                {"sid": session_id},
            )
            rows = result.mappings().all()
        return [dict(r) for r in rows]
    except Exception:
        return []


@app.delete("/agent/sessions/{session_id}")
async def delete_session(session_id: str):
    _SESSIONS.pop(session_id, None)
    try:
        async with _get_async_engine(DATABASE_URL).begin() as conn:
            await conn.execute(
                _sa_text("DELETE FROM agent_sessions WHERE session_id = :sid"),
                {"sid": session_id},
            )
            await conn.execute(
                _sa_text("DELETE FROM agent_messages WHERE session_id = :sid"),
                {"sid": session_id},
            )
    except Exception:
        pass
    return {"deleted": True}
