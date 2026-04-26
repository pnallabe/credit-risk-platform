"""
Integration tests for the modified _sql_query_tool and _stream_agent_response
in ai-agent/src/main.py (GAP-19 anti-hallucination framework).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Patch heavy dependencies before importing main
import types

# Stub out langchain and openai so the module can be imported in tests
for name in [
    "langchain",
    "langchain.agents",
    "langchain.memory",
    "langchain.prompts",
    "langchain.tools",
    "langchain.schema",
    "langchain_openai",
    "slowapi",
    "slowapi.errors",
    "slowapi.util",
]:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)

# Provide minimal stubs
langchain_schema = sys.modules["langchain.schema"]
langchain_schema.HumanMessage = MagicMock  # type: ignore[attr-defined]
langchain_schema.SystemMessage = MagicMock  # type: ignore[attr-defined]

langchain_openai = sys.modules["langchain_openai"]
langchain_openai.ChatOpenAI = MagicMock  # type: ignore[attr-defined]

slowapi_mod = sys.modules["slowapi"]
slowapi_mod.Limiter = MagicMock  # type: ignore[attr-defined]
slowapi_mod._rate_limit_exceeded_handler = MagicMock()  # type: ignore[attr-defined]
sys.modules["slowapi.errors"].RateLimitExceeded = Exception  # type: ignore[attr-defined]
sys.modules["slowapi.util"].get_remote_address = MagicMock()  # type: ignore[attr-defined]

from src.main import (  # noqa: E402
    _sql_query_tool,
    _ACTIVE_TURN_ID,
    _TURN_SQL_RESULTS,
    _TURN_LOCK,
    _stream_agent_response,
)


# ---------------------------------------------------------------------------
# Test 1: SQL tool populates turn result
# ---------------------------------------------------------------------------
def test_sql_tool_populates_turn_result(tmp_path):
    """_sql_query_tool should populate _TURN_SQL_RESULTS with hashes and row count."""
    import src.main as main_mod

    test_turn_id = str(uuid.uuid4())
    token = _ACTIVE_TURN_ID.set(test_turn_id)
    with _TURN_LOCK:
        _TURN_SQL_RESULTS[test_turn_id] = {
            "row_count": 0,
            "sql_executed": "",
            "query_hash": "",
            "result_hash": "",
            "source_table": None,
            "error": False,
            "tools_called": [],
        }

    # Patch _get_sync_engine to use a tmp SQLite DB
    from unittest.mock import patch, MagicMock
    import sqlite3

    db_path = str(tmp_path / "test.db")
    real_conn = sqlite3.connect(db_path)
    real_conn.row_factory = sqlite3.Row

    # Wrap the sqlite3 connection in a SQLAlchemy-compatible mock
    class FakeResult:
        def __init__(self, cursor):
            self._cursor = cursor
        def fetchmany(self, n):
            return self._cursor.fetchmany(n)
        def keys(self):
            return [d[0] for d in self._cursor.description] if self._cursor.description else []

    class FakeConn:
        def __enter__(self_):
            return self_
        def __exit__(self_, *a):
            pass
        def execute(self_, stmt):
            cursor = real_conn.cursor()
            cursor.execute(str(stmt))
            return FakeResult(cursor)

    fake_engine = MagicMock()
    fake_engine.connect.return_value = FakeConn()

    with patch.object(main_mod, "_get_sync_engine", return_value=fake_engine):
        result = _sql_query_tool("SELECT 1 AS x")

    real_conn.close()
    _ACTIVE_TURN_ID.reset(token)

    entry = _TURN_SQL_RESULTS.get(test_turn_id, {})
    assert entry.get("row_count") == 1, f"Expected row_count=1, got {entry}"
    assert isinstance(entry.get("query_hash"), str) and len(entry["query_hash"]) == 64
    assert isinstance(entry.get("result_hash"), str) and len(entry["result_hash"]) == 64

    # Clean up
    with _TURN_LOCK:
        _TURN_SQL_RESULTS.pop(test_turn_id, None)


# ---------------------------------------------------------------------------
# Test 2: SQL tool error sets error flag
# ---------------------------------------------------------------------------
def test_sql_tool_error_sets_error_flag():
    """DROP TABLE in the SQL must trigger error state (UNSAFE keyword guard)."""
    import src.main as main_mod

    test_turn_id = str(uuid.uuid4())
    token = _ACTIVE_TURN_ID.set(test_turn_id)
    with _TURN_LOCK:
        _TURN_SQL_RESULTS[test_turn_id] = {
            "row_count": 0,
            "sql_executed": "",
            "query_hash": "",
            "result_hash": "",
            "source_table": None,
            "error": False,
            "tools_called": [],
        }

    result = _sql_query_tool("DROP TABLE foo")
    _ACTIVE_TURN_ID.reset(token)

    entry = _TURN_SQL_RESULTS.get(test_turn_id, {})
    assert entry.get("error") is True or result.startswith("ERROR:")

    with _TURN_LOCK:
        _TURN_SQL_RESULTS.pop(test_turn_id, None)


# ---------------------------------------------------------------------------
# Test 3: Metadata SSE event is emitted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_metadata_sse_event_emitted():
    """Streaming response must emit a metadata event with confidence_score."""
    import src.main as main_mod

    # Build a fake OrchestratorAgent that yields synthesis_token + synthesis_complete
    async def fake_orchestrator_astream(plan, query, history=""):
        yield {"event": "synthesis_token", "token": "mock answer "}
        yield {"event": "synthesis_complete", "answer": "mock answer", "python_code": []}

    fake_orchestrator = MagicMock()
    fake_orchestrator.astream = fake_orchestrator_astream

    with patch("src.main.OrchestratorAgent", return_value=fake_orchestrator), \
         patch.object(main_mod, "_get_async_engine") as mock_engine:
        # Make DB calls no-ops
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()
        mock_engine.return_value.begin = MagicMock(return_value=mock_conn)

        events = []
        async for event in _stream_agent_response("sess-test", "hello", "data_analyst"):
            events.append(event)

    assert any('"metadata"' in e for e in events), "No metadata event found"
    assert any('"confidence_score"' in e for e in events), "No confidence_score in metadata"
    assert events[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Test 4: Grounding gate emits refusal on zero-row result
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_grounding_gate_emits_refusal():
    """When row_count == 0, a refusal event should be emitted in the stream."""
    import src.main as main_mod

    async def fake_orchestrator_astream(plan, query, history=""):
        # Emit empty output — no rows fetched → grounding gate fires
        yield {"event": "synthesis_token", "token": ""}
        yield {"event": "synthesis_complete", "answer": "", "python_code": []}

    fake_orchestrator = MagicMock()
    fake_orchestrator.astream = fake_orchestrator_astream

    with patch("src.main.OrchestratorAgent", return_value=fake_orchestrator), \
         patch.object(main_mod, "_get_async_engine") as mock_engine:
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock()
        mock_engine.return_value.begin = MagicMock(return_value=mock_conn)

        events = []
        async for event in _stream_agent_response("sess-refusal", "query", "data_analyst"):
            events.append(event)

    # With zero rows and no SQL artifact, should_refuse should trigger
    has_refusal = any('"refusal": true' in e or '"refusal":true' in e for e in events)
    assert has_refusal, f"Expected refusal event, got: {events}"
