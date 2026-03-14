"""
Phase 13 – AI Agent Backend
LangChain ReAct agent + FastAPI + SSE streaming + rate limiting
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator

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
        return "ERROR: Only SELECT queries are allowed."
    try:
        with _get_conn() as conn:
            cur = conn.execute(query)
            rows = cur.fetchmany(200)
            if not rows:
                return "Query returned 0 rows."
            cols = [d[0] for d in cur.description]
            lines = ["\t".join(cols)]
            for row in rows:
                lines.append("\t".join(str(v) for v in row))
            return "\n".join(lines[:50])
    except Exception as exc:
        return f"SQL Error: {exc}"


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
# SSE streaming helper
# ---------------------------------------------------------------------------
async def _stream_agent_response(session_id: str, message: str, persona: str) -> AsyncGenerator[str, None]:
    session = _get_or_create_session(session_id, persona)
    executor: AgentExecutor = session["executor"]
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _run():
        try:
            async for chunk in executor.astream({"input": message}):
                if "output" in chunk:
                    for token in chunk["output"].split(" "):
                        await queue.put(json.dumps({"token": token + " "}))
                elif isinstance(chunk, dict) and "intermediate_steps" in chunk:
                    for step in chunk["intermediate_steps"]:
                        tool_name = step[0].tool if hasattr(step[0], "tool") else "tool"
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
                yield "data: [DONE]\n\n"
                break
            yield f"data: {item}\n\n"
    finally:
        task.cancel()


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
