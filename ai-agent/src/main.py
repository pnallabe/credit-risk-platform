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
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

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

from langchain.agents import AgentExecutor, create_react_agent
from langchain.memory import ConversationSummaryBufferMemory
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from langchain_openai import ChatOpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "decision_audit.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
RATE_LIMIT = os.getenv("RATE_LIMIT", "20/minute")

limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_URL)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_sessions_table():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                session_id TEXT PRIMARY KEY,
                persona TEXT NOT NULL DEFAULT 'data_analyst',
                created_at TEXT NOT NULL,
                last_active TEXT NOT NULL,
                turn_count INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES agent_sessions(session_id)
            )
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def _sql_query_tool(query: str) -> str:
    """Execute a read-only SQL query against the decisions database."""
    UNSAFE = ("insert", "update", "delete", "drop", "alter", "create", "truncate")
    if any(k in query.lower() for k in UNSAFE):
        _mark_turn_error()
        return "ERROR: Only SELECT queries are allowed."

    query_stripped = query.strip()
    query_hash = hashlib.sha256(query_stripped.encode()).hexdigest()

    try:
        with _get_conn() as conn:
            cur = conn.execute(query_stripped)
            rows = cur.fetchmany(200)
            cols = [d[0] for d in cur.description] if cur.description else []

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
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM model_metrics ORDER BY recorded_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"auc": 0.823, "ks": 0.441, "f1": 0.712, "note": "mock"})
    except Exception:
        return json.dumps({"auc": 0.823, "ks": 0.441, "f1": 0.712, "note": "mock"})


def _drift_report_tool(_: str) -> str:
    """Fetch the latest data drift report."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM drift_reports ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"drift_status": "stable", "features_checked": 8, "note": "mock"})
    except Exception:
        return json.dumps({"drift_status": "stable", "features_checked": 8, "note": "mock"})


def _fair_lending_tool(_: str) -> str:
    """Fetch the latest fair lending / DIR report."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM fair_lending_reports ORDER BY generated_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return json.dumps(dict(row), default=str)
        return json.dumps({"dir_score": 0.87, "status": "compliant", "note": "mock"})
    except Exception:
        return json.dumps({"dir_score": 0.87, "status": "compliant", "note": "mock"})


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


TOOLS = [
    Tool(name="sql_query_tool", func=_sql_query_tool, description=(
        "Run a read-only SQL SELECT query against the decisions database. "
        "Input: SQL string. Useful for ad-hoc data analysis."
    )),
    Tool(name="metrics_tool", func=_metrics_tool, description=(
        "Retrieve the latest model performance metrics (AUC, KS, F1). Input: empty string."
    )),
    Tool(name="drift_report_tool", func=_drift_report_tool, description=(
        "Fetch the latest data drift report including PSI per feature. Input: empty string."
    )),
    Tool(name="fair_lending_tool", func=_fair_lending_tool, description=(
        "Fetch the latest fair lending report including DIR score. Input: empty string."
    )),
    Tool(name="chart_generator_tool", func=_chart_generator_tool, description=(
        "Generate a chart specification for frontend rendering. "
        "Input: JSON string describing chart type, data, and title."
    )),
    Tool(name="report_generator_tool", func=_report_generator_tool, description=(
        "Generate a full structured report. Input: report type string "
        "(portfolio|model_health|fair_lending|drift)."
    )),
]

# ---------------------------------------------------------------------------
# Personas
# ---------------------------------------------------------------------------
PERSONA_PROMPTS = {
    "data_analyst": (
        "You are a data analyst assistant for a credit risk platform. "
        "You help credit risk analysts, underwriters, and data scientists understand "
        "model performance, data drift, and portfolio metrics. "
        "Be precise, cite numbers, and offer to run SQL queries when appropriate. "
        "When you write SQL show it in ```sql blocks."
    ),
    "business_analyst": (
        "You are a business analyst assistant for a credit risk platform. "
        "You help executives and compliance officers understand the business impact "
        "of credit decisions, regulatory compliance, and portfolio health. "
        "Avoid technical jargon. Summarize findings in plain English. "
        "Use percentages, dollar amounts, and trend language."
    ),
}

REACT_TEMPLATE = """{persona}

You have access to the following tools:
{tools}

Use the following format:
Question: the input question
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Previous conversation:
{chat_history}

Question: {input}
Thought:{agent_scratchpad}"""


def _build_agent_executor(persona: str, memory: ConversationSummaryBufferMemory) -> AgentExecutor:
    llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, streaming=True, openai_api_key=OPENAI_API_KEY)
    prompt = PromptTemplate.from_template(
        REACT_TEMPLATE.replace("{persona}", PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["data_analyst"]))
    )
    agent = create_react_agent(llm=llm, tools=TOOLS, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=TOOLS,
        memory=memory,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=8,
    )


# ---------------------------------------------------------------------------
# In-memory session store
# ---------------------------------------------------------------------------
_SESSIONS: dict[str, dict] = {}  # session_id -> {executor, memory, persona}


def _get_or_create_session(session_id: str, persona: str = "data_analyst") -> dict:
    if session_id not in _SESSIONS:
        llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0, openai_api_key=OPENAI_API_KEY)
        memory = ConversationSummaryBufferMemory(
            llm=llm,
            max_token_limit=2000,
            memory_key="chat_history",
            return_messages=False,
        )
        executor = _build_agent_executor(persona, memory)
        _SESSIONS[session_id] = {"executor": executor, "memory": memory, "persona": persona}
    return _SESSIONS[session_id]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_sessions_table()
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

    session = _get_or_create_session(session_id, persona)
    executor: AgentExecutor = session["executor"]
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    _answer_parts: list[str] = []
    _plan_steps: list[dict] = []

    async def _run():
        try:
            async for chunk in executor.astream({"input": message}):
                if "output" in chunk:
                    answer = chunk["output"]
                    _answer_parts.append(answer)
                    for token_word in answer.split(" "):
                        await queue.put(json.dumps({"token": token_word + " "}))
                elif isinstance(chunk, dict) and "intermediate_steps" in chunk:
                    for step in chunk["intermediate_steps"]:
                        tool_name = step[0].tool if hasattr(step[0], "tool") else "tool"
                        tool_input = step[0].tool_input if hasattr(step[0], "tool_input") else ""
                        observation = step[1] if len(step) > 1 else ""
                        # Strip internal prefixes from observation before storing
                        obs_str = str(observation)
                        if obs_str.startswith("__GROUNDED__"):
                            obs_str = obs_str[len("__GROUNDED__"):].lstrip("\n")
                        elif obs_str.startswith("__ERROR__"):
                            obs_str = obs_str[len("__ERROR__"):].lstrip("\n")
                        _plan_steps.append({
                            "thought": "",
                            "action": tool_name,
                            "action_input": str(tool_input),
                            "observation": obs_str,
                        })
                        with _TURN_LOCK:
                            entry = _TURN_SQL_RESULTS.get(turn_id)
                            if entry is not None:
                                entry["tools_called"].append(tool_name)
                        # Strip internal prefixes before echoing tool_call event
                        await queue.put(json.dumps({"tool_call": tool_name}))
        except Exception as exc:
            await queue.put(json.dumps({"error": str(exc)}))
        finally:
            await queue.put(None)

    task = asyncio.create_task(_run())

    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            # Strip internal grounding prefixes from token events before forwarding
            try:
                parsed = json.loads(item)
                if "token" in parsed:
                    tok = parsed["token"]
                    if tok.startswith("__GROUNDED__"):
                        tok = tok[len("__GROUNDED__"):].lstrip("\n")
                        parsed["token"] = tok
                    elif tok.startswith("__ERROR__"):
                        tok = tok[len("__ERROR__"):].lstrip("\n")
                        parsed["token"] = tok
                    item = json.dumps(parsed)
            except Exception:
                pass
            yield f"data: {item}\n\n"
    finally:
        task.cancel()

    # --- Collect turn data and compute confidence ---
    _ACTIVE_TURN_ID.reset(token)
    with _TURN_LOCK:
        turn_data = _TURN_SQL_RESULTS.pop(turn_id, {})

    factors = ConfidenceFactors(
        row_count=turn_data.get("row_count", 0),
        query_error=bool(turn_data.get("error", False)),
        empty_result=(turn_data.get("row_count", 0) == 0),
        tools_called=turn_data.get("tools_called", []),
        has_sql_artifact=bool(turn_data.get("sql_executed")),
    )
    conf = compute_confidence(factors)

    # Persist SQL code artifact (fire-and-forget)
    artifact_ids: list[str] = []
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
            logger.error("Failed to store code artifact: %s", exc)

    # Persist messages to agent_messages
    assembled_answer = " ".join(_answer_parts)
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, "user", message, ts),
            )
            conn.execute(
                "INSERT INTO agent_messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (session_id, "assistant", assembled_answer, ts),
            )
            conn.commit()
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
    _get_or_create_session(session_id, req.persona)

    ts = datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_sessions VALUES (?, ?, ?, ?, ?)",
                (session_id, req.persona, ts, ts, 0),
            )
            conn.commit()
    except Exception:
        pass  # SQLite may not be fully set up in all envs

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
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT role, content, created_at FROM agent_messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


@app.delete("/agent/sessions/{session_id}")
async def delete_session(session_id: str):
    _SESSIONS.pop(session_id, None)
    try:
        with _get_conn() as conn:
            conn.execute("DELETE FROM agent_sessions WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM agent_messages WHERE session_id = ?", (session_id,))
            conn.commit()
    except Exception:
        pass
    return {"deleted": True}
