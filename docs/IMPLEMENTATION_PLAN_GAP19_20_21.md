# Implementation Plan: GAP-19 through GAP-23
**PRD Reference**: Unified ILOL PRD v3.0.0 — §5 Anti-Hallucination Framework; GNRI-011; §4.4.1 Exam Packet AI Appendix; §11.3 HITL Controls; Appendix C R-01; §4.2.1 DE-005/DE-006/DE-007
**Sprint Target**: GAP-19 + GAP-20 → Sprint 14; GAP-21 + GAP-22 + GAP-23 → Sprint 15
**Estimated Effort**: ~32 engineering days total
**Execution Order**: GAP-19 → GAP-20 → GAP-21 (depends on GAP-20); GAP-22 and GAP-23 are independent and can run in parallel with any sprint

---

## Overview

Five gaps remain open against PRD v3.0.

| Gap | Description | Priority | Est. Days | Depends On |
|-----|-------------|:--------:|:---------:|:-----------|
| GAP-19 | Anti-Hallucination Framework + Code Transparency Layer | P1 | ~10 | None |
| GAP-20 | GNRI-011 Immutable AI Agent Audit Log non-compliant | P1 | ~6 | None |
| GAP-21 | AI Agent Audit Appendix missing from Exam Packet Generator | P2 | ~3 | GAP-20 |
| GAP-22 | HITL approval gate absent for exam packet export and AI regulatory submissions | P2 | ~5 | None |
| GAP-23 | Manual Review Referral Queue — no resolution workflow, no post-decision override API | P2 | ~8 | None |

---

## GAP-19: Anti-Hallucination Framework + Code Transparency Layer

### Context
`ai-agent/src/main.py` runs SQL via `_sql_query_tool()` but never surfaces the SQL, result hash, query hash, or a confidence score in the API response. The agent can hallucinate summaries over empty result sets. None of the transparency artifacts required by PRD §5 (executable SQL/Python, `result_hash`, `query_hash`, source table tags, BQ job ID) are captured or returned.

### Files to Create
- `ai-agent/src/code_artifact_store.py`
- `ai-agent/src/confidence_scorer.py`
- `ai-agent/tests/test_code_artifact_store.py`
- `ai-agent/tests/test_confidence_scorer.py`
- `ai-agent/tests/test_anti_hallucination.py`

### Files to Modify
- `ai-agent/src/main.py` — extend `_sql_query_tool`, `_stream_agent_response`, SSE schema, and `AgentResponse`

---

### Coding Prompt 19-A: Create `ai-agent/src/code_artifact_store.py`

```
Create the file ai-agent/src/code_artifact_store.py.

PURPOSE
-------
Persist per-answer code artifacts (SQL strings and optional Python snippets)
alongside their cryptographic fingerprints. Every artifact is immutable once
written — no UPDATE or DELETE is permitted at the application layer.

REQUIREMENTS
------------
1. SQLite-backed (same DATABASE_URL env var used in main.py, default
   "decision_audit.db").
2. Table DDL (create if not exists):

   CREATE TABLE IF NOT EXISTS agent_code_artifacts (
       artifact_id    TEXT    PRIMARY KEY,   -- UUID4
       session_id     TEXT    NOT NULL,
       turn_id        TEXT    NOT NULL,      -- UUID4 per chat turn
       artifact_type  TEXT    NOT NULL,      -- 'sql' | 'python'
       content        TEXT    NOT NULL,      -- full source text
       content_hash   TEXT    NOT NULL,      -- SHA-256 of content (hex)
       source_table   TEXT,                  -- table name extracted from SQL (nullable)
       partition_date TEXT,                  -- ISO date of most recent partition queried (nullable)
       created_at     TEXT    NOT NULL       -- ISO-8601 UTC
   );

3. No UPDATE or DELETE methods on this table; the store is append-only.

PUBLIC API
----------

@dataclass
class CodeArtifact:
    artifact_id: str
    session_id: str
    turn_id: str
    artifact_type: Literal["sql", "python"]
    content: str
    content_hash: str        # SHA-256 hex of content
    source_table: Optional[str]
    partition_date: Optional[str]
    created_at: str

async def store_artifact(
    db_url: str,
    session_id: str,
    turn_id: str,
    artifact_type: Literal["sql", "python"],
    content: str,
    source_table: Optional[str] = None,
    partition_date: Optional[str] = None,
) -> CodeArtifact:
    """
    Compute content_hash = SHA-256(content), assign a new UUID4 artifact_id,
    insert a row, and return the CodeArtifact dataclass.
    Raise ValueError if artifact_type is not 'sql' or 'python'.
    """

async def get_artifacts_for_turn(
    db_url: str,
    turn_id: str,
) -> list[CodeArtifact]:
    """Return all artifacts for a given turn_id ordered by created_at ASC."""

async def get_artifacts_for_session(
    db_url: str,
    session_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
) -> list[CodeArtifact]:
    """
    Return all artifacts for a session optionally filtered by created_at
    ISO date range [from_date, to_date] (both inclusive, both optional).
    Results ordered by created_at ASC.
    """

IMPLEMENTATION NOTES
--------------------
- Use sqlite3 (synchronous) wrapped in asyncio.to_thread() for all DB calls
  so the function signatures are async without requiring aiosqlite.
- _ensure_schema(db_url) must be called once before any other function;
  call it inside each public function with a module-level threading.Lock
  to ensure it runs at most once per process.
- SHA-256 helper: use hashlib.sha256(content.encode()).hexdigest().
- _extract_source_table(sql: str) -> Optional[str]: extract the first table
  name that follows FROM or JOIN using a simple regex; return None if not found.
  This is best-effort; do not raise on failure.
```

---

### Coding Prompt 19-B: Create `ai-agent/src/confidence_scorer.py`

```
Create the file ai-agent/src/confidence_scorer.py.

PURPOSE
-------
Compute a grounding confidence score (0.0–1.0) for an AI agent answer based
on the quality and coverage of the data the agent retrieved. A score of 0.0
means the answer has no data support; 1.0 means fully grounded.

REQUIREMENTS
------------

@dataclass
class ConfidenceFactors:
    row_count: int           # number of rows returned by the primary SQL tool call
    query_error: bool        # True if the SQL tool returned an error string
    empty_result: bool       # True if row_count == 0
    tools_called: list[str]  # names of tools invoked during the turn
    has_sql_artifact: bool   # True if at least one SQL artifact was stored

@dataclass
class ConfidenceScore:
    score: float                      # 0.0 – 1.0, rounded to 4 decimal places
    label: Literal["high", "medium", "low", "none"]
    factors: ConfidenceFactors
    explanation: str                  # one-sentence plain English explanation

def compute_confidence(factors: ConfidenceFactors) -> ConfidenceScore:
    """
    Scoring algorithm:
      base_score = 0.0

      1. +0.40 if row_count >= 1
      2. +0.20 if row_count >= 10
      3. +0.10 if row_count >= 50
      4. +0.15 if has_sql_artifact is True
      5. +0.15 if len(tools_called) >= 2 (multi-tool grounding)
      6. -1.00 (floor to 0.0) if query_error is True
      7. -0.80 (effective 0.0 in most cases) if empty_result is True and
              not query_error — meaning the query ran but returned nothing

    label assignment (after clamping to [0.0, 1.0]):
      score >= 0.75  → "high"
      score >= 0.45  → "medium"
      score >= 0.10  → "low"
      else           → "none"

    explanation: produce a single sentence that names the dominant factor,
    e.g. "Answer grounded in 42 data rows from 2 tool calls." or
    "No data rows returned; answer may not reflect current portfolio state."
    """

GROUNDING GATE FUNCTION
-----------------------

def should_refuse(score: ConfidenceScore) -> bool:
    """
    Return True when the label is "none" OR when empty_result is True
    AND score.score < 0.10.
    Used by the streaming agent to substitute a structured refusal message
    instead of allowing the LLM to summarise empty context.
    """

REFUSAL MESSAGE TEMPLATE
------------------------

REFUSAL_MESSAGE = (
    "I was unable to retrieve data to answer this question. "
    "The underlying query returned no results for the specified parameters. "
    "This may indicate the data is outside the available date range, "
    "the tenant has no records matching the criteria, or the relevant "
    "table is empty. Please refine your question or verify the data availability."
)

No external dependencies. Pure Python only.
```

---

### Coding Prompt 19-C: Modify `ai-agent/src/main.py` — SQL Tool, SSE Schema, Streaming

```
Modify ai-agent/src/main.py to implement PRD §5 Anti-Hallucination Framework.
Do NOT rewrite unaffected sections. All changes are additive or minimal edits.

CHANGE 1 — New imports (add after existing imports block)
---------------------------------------------------------
Add at the top of the file (after existing imports):

    import hashlib
    import threading
    from ai-agent.src.code_artifact_store import store_artifact   # use relative: from .code_artifact_store import store_artifact
    from .confidence_scorer import (
        ConfidenceFactors,
        ConfidenceScore,
        compute_confidence,
        should_refuse,
        REFUSAL_MESSAGE,
    )

Also add a module-level turn ID registry:
    _TURN_SQL_RESULTS: dict[str, dict] = {}
    # key: turn_id → {"row_count": int, "sql_executed": str, "query_hash": str,
    #                  "result_hash": str, "source_table": str | None,
    #                  "error": bool, "tools_called": list[str]}
    _TURN_LOCK = threading.Lock()

CHANGE 2 — Replace _sql_query_tool (the entire function body)
--------------------------------------------------------------
Replace the existing _sql_query_tool function body so it:

1. Executes the existing safety check (UNSAFE keywords → early return "ERROR: ...")
2. Computes query_hash = SHA-256 of the stripped SQL string (hex)
3. Runs the query (same logic as before)
4. If successful:
   a. Serialises the result rows to a canonical JSON string (sorted column order)
   b. Computes result_hash = SHA-256 of that JSON string (hex)
   c. Extracts source_table from the SQL (best-effort: first word after FROM,
      strip schema prefix if present)
   d. Persists the artifact via asyncio.run_coroutine_threadsafe or
      threading: call asyncio.get_event_loop().run_until_complete(
          store_artifact(DATABASE_URL, session_id="__tool__", turn_id=_current_turn_id(),
                         artifact_type="sql", content=query,
                         source_table=source_table))
      — but since _sql_query_tool is synchronous, store the metadata in
      _TURN_SQL_RESULTS under the current turn_id (set by the streaming path).
   e. Returns a structured string:
      "__GROUNDED__\n" + original_tabular_result

   NOTE: The "__GROUNDED__\n" prefix is stripped by the SSE wrapper before
   sending to the LLM. It is internal signalling only.

5. If SQL error:
   Prefix result with "__ERROR__\n".

6. Row count: store in _TURN_SQL_RESULTS[current_turn_id]["row_count"].

Expose a module-level function:
    def _current_turn_id() -> str:
        """Return the turn_id for the currently executing streaming context."""
        # Returns _ACTIVE_TURN_ID thread-local or a sentinel "__none__"
        return _ACTIVE_TURN_ID.value if hasattr(_ACTIVE_TURN_ID, "value") else "__none__"

Add a threading.local or contextvars.ContextVar:
    import contextvars
    _ACTIVE_TURN_ID: contextvars.ContextVar[str] = contextvars.ContextVar(
        "_ACTIVE_TURN_ID", default="__none__"
    )

CHANGE 3 — New Pydantic schemas (add after existing schema section)
--------------------------------------------------------------------
Add before AgentResponse (which may need to be created if not present):

    class DataLineageTag(BaseModel):
        source_table: Optional[str] = None
        partition_date: Optional[str] = None
        query_hash: Optional[str] = None
        result_hash: Optional[str] = None

    class CodeArtifacts(BaseModel):
        sql_executed: Optional[str] = None
        query_hash: Optional[str] = None
        result_hash: Optional[str] = None
        artifact_ids: list[str] = []

    class AgentTurnMetadata(BaseModel):
        turn_id: str
        confidence_score: float
        confidence_label: str           # "high" | "medium" | "low" | "none"
        confidence_explanation: str
        data_lineage_tags: list[DataLineageTag]
        code_artifacts: CodeArtifacts
        grounded: bool                  # False when refusal was triggered

CHANGE 4 — Modify _stream_agent_response
-----------------------------------------
At the START of _stream_agent_response (before creating the session):

    turn_id = str(uuid.uuid4())
    token = _ACTIVE_TURN_ID.set(turn_id)
    _TURN_SQL_RESULTS[turn_id] = {
        "row_count": 0, "sql_executed": "", "query_hash": "", "result_hash": "",
        "source_table": None, "error": False, "tools_called": []
    }

Inside the _run() coroutine, after collecting intermediate_steps:
    - For each step, append the tool name to _TURN_SQL_RESULTS[turn_id]["tools_called"]
    - Strip the "__GROUNDED__\n" or "__ERROR__\n" prefix from tool outputs before
      passing observations back to the LLM (so it never sees the internal tags)

After the executor finishes (in the outer generator, after the _run task completes):

    turn_data = _TURN_SQL_RESULTS.pop(turn_id, {})
    _ACTIVE_TURN_ID.reset(token)

    factors = ConfidenceFactors(
        row_count=turn_data.get("row_count", 0),
        query_error=turn_data.get("error", False),
        empty_result=turn_data.get("row_count", 0) == 0 and not turn_data.get("error", False),
        tools_called=turn_data.get("tools_called", []),
        has_sql_artifact=bool(turn_data.get("sql_executed")),
    )
    conf = compute_confidence(factors)

    # Store artifact asynchronously (fire-and-forget; don't block streaming)
    if turn_data.get("sql_executed"):
        asyncio.create_task(store_artifact(
            DATABASE_URL, session_id=session_id, turn_id=turn_id,
            artifact_type="sql",
            content=turn_data["sql_executed"],
            source_table=turn_data.get("source_table"),
        ))

    # Build and emit the final metadata SSE event
    metadata = AgentTurnMetadata(
        turn_id=turn_id,
        confidence_score=conf.score,
        confidence_label=conf.label,
        confidence_explanation=conf.factors.__class__.__name__,  # replaced below
        data_lineage_tags=[DataLineageTag(
            source_table=turn_data.get("source_table"),
            query_hash=turn_data.get("query_hash"),
            result_hash=turn_data.get("result_hash"),
        )] if turn_data.get("query_hash") else [],
        code_artifacts=CodeArtifacts(
            sql_executed=turn_data.get("sql_executed"),
            query_hash=turn_data.get("query_hash"),
            result_hash=turn_data.get("result_hash"),
        ),
        grounded=not should_refuse(conf),
    )
    yield f"data: {json.dumps({'metadata': metadata.model_dump()})}\n\n"

    # Grounding gate: if refusal triggered, also emit a structured refusal token event
    if should_refuse(conf):
        yield f"data: {json.dumps({'token': REFUSAL_MESSAGE, 'refusal': True})}\n\n"

    yield "data: [DONE]\n\n"

CHANGE 5 — Persist messages to agent_messages table
-----------------------------------------------------
At the end of _stream_agent_response (before the final [DONE]) persist
the user message and the agent's assembled answer to agent_messages:

    try:
        ts = datetime.utcnow().isoformat()
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO agent_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
                (session_id, "user", message, ts),
            )
            conn.execute(
                "INSERT INTO agent_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
                (session_id, "assistant", assembled_answer, ts),
            )
            conn.commit()
    except Exception:
        pass

    (assembled_answer must be built by concatenating all "token" items from the
    token queue as the stream runs — maintain an `_answer_parts: list[str]` in
    `_run()` and join them after the executor finishes.)
```

---

### Coding Prompt 19-D: Tests for Anti-Hallucination Framework

```
Create the following three test files:

FILE 1: ai-agent/tests/test_code_artifact_store.py
---------------------------------------------------
Test module for ai-agent/src/code_artifact_store.py.

Use pytest + pytest-asyncio. Use a tmp_path-scoped SQLite file URL for db_url.

Tests to include:
1. test_store_and_retrieve_sql_artifact:
   - Call store_artifact with artifact_type="sql", some SQL content.
   - Assert returned CodeArtifact has correct content_hash (SHA-256 of content).
   - Assert artifact_id is a valid UUID4 string.
   - Call get_artifacts_for_turn and assert the artifact is returned.

2. test_store_python_artifact:
   - Store a Python snippet. Assert artifact_type is "python".

3. test_invalid_artifact_type_raises:
   - Call store_artifact with artifact_type="bash". Assert ValueError is raised.

4. test_get_artifacts_for_session_date_filter:
   - Store two artifacts at different created_at values.
   - Filter by from_date / to_date and assert only the correct one is returned.

5. test_source_table_extraction:
   - Store an artifact with sql = "SELECT * FROM audit_log WHERE tenant_id = ?"
   - Assert source_table == "audit_log".

6. test_no_delete_method:
   - Assert that the code_artifact_store module has no function named
     "delete_artifact" or "update_artifact".

FILE 2: ai-agent/tests/test_confidence_scorer.py
-------------------------------------------------
Test module for ai-agent/src/confidence_scorer.py.

Tests to include:
1. test_high_confidence_many_rows:
   - factors: row_count=100, query_error=False, empty_result=False,
     tools_called=["sql_query_tool", "metrics_tool"], has_sql_artifact=True
   - Assert score >= 0.75 and label == "high"

2. test_none_confidence_empty_result:
   - factors: row_count=0, query_error=False, empty_result=True,
     tools_called=["sql_query_tool"], has_sql_artifact=True
   - Assert label == "none" or score < 0.10

3. test_none_confidence_sql_error:
   - factors: row_count=0, query_error=True, empty_result=False,
     tools_called=[], has_sql_artifact=False
   - Assert score == 0.0 and label == "none"

4. test_should_refuse_on_empty_result:
   - For a ConfidenceScore with label="none", assert should_refuse returns True.

5. test_should_not_refuse_on_high_confidence:
   - For a ConfidenceScore with score=0.9, label="high", assert should_refuse
     returns False.

6. test_refusal_message_is_non_empty_string:
   - Assert REFUSAL_MESSAGE is a str with len > 20.

FILE 3: ai-agent/tests/test_anti_hallucination.py
--------------------------------------------------
Integration tests for the modified _sql_query_tool and _stream_agent_response.

Tests to include:
1. test_sql_tool_populates_turn_result:
   - Set _ACTIVE_TURN_ID to a test UUID.
   - Initialise _TURN_SQL_RESULTS[turn_id] = {"row_count": 0, ...}.
   - Call _sql_query_tool("SELECT 1 AS x") directly.
   - Assert _TURN_SQL_RESULTS[turn_id]["row_count"] == 1.
   - Assert _TURN_SQL_RESULTS[turn_id]["query_hash"] is a 64-char hex string.
   - Assert _TURN_SQL_RESULTS[turn_id]["result_hash"] is a 64-char hex string.

2. test_sql_tool_error_sets_error_flag:
   - Set a valid turn_id in _ACTIVE_TURN_ID.
   - Call _sql_query_tool("DROP TABLE foo").
   - Assert _TURN_SQL_RESULTS[turn_id]["error"] is truthy OR the tool
     returned an "ERROR:" prefixed string (since DROP is in UNSAFE).

3. test_metadata_sse_event_emitted (async test):
   - Mock AgentExecutor.astream to yield {"output": "mock answer"}.
   - Collect all items from _stream_agent_response.
   - Assert at least one item contains '"metadata"' in the string.
   - Assert at least one item contains '"confidence_score"' in the string.
   - Assert the stream ends with "data: [DONE]".

4. test_grounding_gate_emits_refusal (async test):
   - Mock the executor to yield {"output": ""} (empty output, simulating
     zero-row tool result with _TURN_SQL_RESULTS row_count=0).
   - Assert the collected stream contains an event with '"refusal": true'.
```

---

## GAP-20: GNRI-011 Immutable AI Agent Audit Log

### Context
`ai-agent/src/main.py` has `agent_sessions` and `agent_messages` SQLite tables but neither is append-only, neither has a hash chain, and neither captures the GNRI-011-required fields (`plan_text`, `sql_executed`, `result_hash`, `code_artifact_ref`, `confidence_score`, `bq_job_id`). No 7-year retention rule exists for these tables.

### Files to Create
- `ai-agent/src/ai_audit_log.py`
- `ai-agent/tests/test_ai_audit_log.py`

### Files to Modify
- `ai-agent/src/main.py` — wire `_stream_agent_response` to write audit records post-turn
- `audit/chain_verifier.py` — add `verify_ai_agent_chain()`
- `compliance/retention_policy.py` — add `"audit.ai_agent_audit_log": 7`

---

### Coding Prompt 20-A: Create `ai-agent/src/ai_audit_log.py`

```
Create the file ai-agent/src/ai_audit_log.py.

PURPOSE
-------
Append-only, cryptographically hash-chained audit log for every AI agent
query turn. Implements GNRI-011 requirements. Follows the exact same
hash-chain pattern as audit/logger.py.

TABLE DDL
---------
CREATE TABLE IF NOT EXISTS ai_agent_audit_log (
    log_id              TEXT    PRIMARY KEY,         -- UUID4
    session_id          TEXT    NOT NULL,
    turn_id             TEXT    NOT NULL UNIQUE,     -- UUID4; one row per turn
    tenant_id           TEXT    NOT NULL DEFAULT 'default',
    persona             TEXT    NOT NULL,
    query_text          TEXT    NOT NULL,            -- original user message
    plan_text           TEXT,                        -- JSON array of ReAct steps (thought + action + observation)
    tools_called        TEXT,                        -- JSON array of tool names
    sql_executed        TEXT,                        -- SQL string(s) executed, newline-separated
    result_hash         TEXT,                        -- SHA-256 of serialised query result
    query_hash          TEXT,                        -- SHA-256 of sql_executed
    code_artifact_ref   TEXT,                        -- comma-separated artifact_ids from agent_code_artifacts
    confidence_score    REAL,
    confidence_label    TEXT,
    answer_text         TEXT,                        -- assembled final answer
    grounded            INTEGER NOT NULL DEFAULT 1,  -- 0 = refusal triggered
    bq_job_id           TEXT,                        -- BigQuery job ID if BQ backend used
    source_table        TEXT,
    partition_date      TEXT,
    logged_at           TEXT    NOT NULL,            -- ISO-8601 UTC
    record_hash         TEXT    NOT NULL,            -- SHA-256 chain hash
    previous_hash       TEXT    NOT NULL,            -- hash of preceding row (or 'GENESIS' for first)
    hash_algorithm      TEXT    NOT NULL DEFAULT 'sha256'
);

IMPORTANT: Application-layer enforcement of append-only semantics.
Never expose an UPDATE or DELETE function. The schema comment should
state: "APPEND-ONLY — no UPDATE or DELETE operations are permitted."

HASH CHAIN ALGORITHM
--------------------
Mirror audit/logger.py's compute_chain_hash() exactly:

    CANONICAL_FIELDS_AI = ("query_text", "result_hash", "confidence_score", "answer_text")

    def _build_canonical_ai(log_id: str, logged_at: str,
                             query_text: str, result_hash: Optional[str],
                             confidence_score: Optional[float],
                             answer_text: Optional[str]) -> str:
        payload = {
            "query_text": query_text,
            "result_hash": result_hash or "",
            "confidence_score": str(round(confidence_score, 6)) if confidence_score is not None else "",
            "answer_text": (answer_text or "")[:200],  # first 200 chars for chain stability
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _compute_chain_hash(log_id: str, logged_at: str, previous_hash: str,
                             query_text: str, result_hash: Optional[str],
                             confidence_score: Optional[float],
                             answer_text: Optional[str]) -> str:
        canonical = _build_canonical_ai(log_id, logged_at, query_text,
                                         result_hash, confidence_score, answer_text)
        raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_previous_hash(conn: sqlite3.Connection, session_id: str) -> str:
        """Return the record_hash of the most recent entry for this session,
        or 'GENESIS' if no entries yet exist."""
        row = conn.execute(
            "SELECT record_hash FROM ai_agent_audit_log "
            "WHERE session_id = ? ORDER BY logged_at DESC LIMIT 1",
            (session_id,)
        ).fetchone()
        return row[0] if row else "GENESIS"

PUBLIC API
----------

@dataclass
class AIAgentAuditRecord:
    log_id: str
    session_id: str
    turn_id: str
    tenant_id: str
    persona: str
    query_text: str
    plan_text: Optional[str]          # raw JSON string
    tools_called: Optional[str]       # raw JSON string
    sql_executed: Optional[str]
    result_hash: Optional[str]
    query_hash: Optional[str]
    code_artifact_ref: Optional[str]
    confidence_score: Optional[float]
    confidence_label: Optional[str]
    answer_text: Optional[str]
    grounded: bool
    bq_job_id: Optional[str]
    source_table: Optional[str]
    partition_date: Optional[str]
    logged_at: str
    record_hash: str
    previous_hash: str

async def log_ai_turn(
    db_url: str,
    session_id: str,
    turn_id: str,
    persona: str,
    query_text: str,
    answer_text: Optional[str],
    plan_steps: Optional[list[dict]],      # list of {"thought": ..., "action": ..., "observation": ...}
    tools_called: Optional[list[str]],
    sql_executed: Optional[str],
    result_hash: Optional[str],
    query_hash: Optional[str],
    code_artifact_ids: Optional[list[str]],
    confidence_score: Optional[float],
    confidence_label: Optional[str],
    grounded: bool,
    tenant_id: str = "default",
    bq_job_id: Optional[str] = None,
    source_table: Optional[str] = None,
    partition_date: Optional[str] = None,
) -> AIAgentAuditRecord:
    """
    Insert one row into ai_agent_audit_log with a computed hash chain.
    Steps:
      1. Use asyncio.to_thread to avoid blocking the event loop.
      2. Inside the thread: open the DB, compute previous_hash, compute
         record_hash, INSERT the row, return AIAgentAuditRecord.
      3. If session_id is None or empty, raise ValueError.
    """

async def get_ai_audit_records(
    db_url: str,
    session_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    tenant_id: Optional[str] = None,
    limit: int = 1000,
) -> list[AIAgentAuditRecord]:
    """
    Query ai_agent_audit_log. All filter parameters are optional.
    Results ordered by logged_at ASC.
    """

IMPLEMENTATION NOTES
--------------------
- Use sqlite3 (synchronous) wrapped in asyncio.to_thread() for all DB calls.
- _ensure_schema() called once per process using a threading.Lock.
- The db_url can be a bare filename (e.g. "decision_audit.db") or a
  SQLAlchemy-style URL beginning with "sqlite:///"; strip the prefix if needed.
```

---

### Coding Prompt 20-B: Wire `ai-agent/src/main.py` to Write Audit Records

```
Modify ai-agent/src/main.py to write a full audit record to ai_agent_audit_log
after every completed agent turn.

CHANGE 1 — New import
---------------------
Add to the imports section:
    from .ai_audit_log import log_ai_turn

CHANGE 2 — Capture plan_steps in _stream_agent_response
---------------------------------------------------------
Inside the _run() coroutine, while iterating over executor.astream chunks,
collect intermediate steps into a list:

    _plan_steps: list[dict] = []

    For each chunk that contains "intermediate_steps":
        for step in chunk["intermediate_steps"]:
            action = step[0]
            observation = step[1]
            _plan_steps.append({
                "thought": getattr(action, "log", ""),
                "action": getattr(action, "tool", ""),
                "action_input": getattr(action, "tool_input", ""),
                "observation": str(observation)[:500],  # truncate long tool outputs
            })

    For the "output" chunk, capture the full answer text:
        if "output" in chunk:
            _answer_parts.append(chunk["output"])

After all chunks are processed, assembled_answer = "".join(_answer_parts).

CHANGE 3 — Write audit record after stream completes
-----------------------------------------------------
After computing `conf` (ConfidenceScore) and BEFORE emitting the metadata
SSE event, write the audit record:

    asyncio.create_task(log_ai_turn(
        db_url=DATABASE_URL,
        session_id=session_id,
        turn_id=turn_id,
        persona=persona,
        query_text=message,
        answer_text=assembled_answer,
        plan_steps=_plan_steps,
        tools_called=turn_data.get("tools_called", []),
        sql_executed=turn_data.get("sql_executed"),
        result_hash=turn_data.get("result_hash"),
        query_hash=turn_data.get("query_hash"),
        code_artifact_ids=None,   # populated after store_artifact tasks complete
        confidence_score=conf.score,
        confidence_label=conf.label,
        grounded=not should_refuse(conf),
        tenant_id="default",       # TODO: extract from JWT in Sprint 15
        source_table=turn_data.get("source_table"),
    ))

Note: fire-and-forget via create_task is acceptable here because the audit
write must not block the SSE response. If the task fails, log the error via
the standard logger — don't raise.
```

---

### Coding Prompt 20-C: Extend `audit/chain_verifier.py` with `verify_ai_agent_chain()`

```
Modify audit/chain_verifier.py to add verify_ai_agent_chain().

CONTEXT
-------
The existing verify_chain() function verifies audit_log, portfolio_audit_log,
and adverse_action_log using SQLAlchemy async engine. The new function targets
the SQLite-backed ai_agent_audit_log table in the AI agent database.
Use sqlite3 (sync, wrapped in asyncio.to_thread) — NOT SQLAlchemy — since the
AI agent uses a bare SQLite file, not a SQLAlchemy URL.

CANONICAL FIELDS (must match ai_audit_log.py exactly)
------------------------------------------------------
    AI_CANONICAL_FIELDS = ("query_text", "result_hash", "confidence_score", "answer_text")

    def _rebuild_ai_canonical(row: dict) -> str:
        payload = {
            "query_text": row.get("query_text") or "",
            "result_hash": row.get("result_hash") or "",
            "confidence_score": str(round(float(row["confidence_score"]), 6))
                                  if row.get("confidence_score") is not None else "",
            "answer_text": (row.get("answer_text") or "")[:200],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def _recompute_ai_hash(row: dict) -> str:
        previous_hash = row.get("previous_hash") or "GENESIS"
        log_id = row.get("log_id") or ""
        logged_at = row.get("logged_at") or ""
        canonical = _rebuild_ai_canonical(row)
        raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical
        return hashlib.sha256(raw.encode()).hexdigest()

NEW PUBLIC FUNCTION
-------------------

async def verify_ai_agent_chain(
    db_url: str,
    session_id: Optional[str] = None,
    from_logged_at: Optional[str] = None,
    to_logged_at: Optional[str] = None,
) -> ChainVerificationResult:
    """
    Verify the hash chain of ai_agent_audit_log using sqlite3.

    Parameters
    ----------
    db_url:
        Path to the SQLite file or bare filename (strip "sqlite:///" prefix
        if present). Accepts the same value as DATABASE_URL in ai-agent/src/main.py.
    session_id:
        If provided, scope verification to this session.
    from_logged_at / to_logged_at:
        ISO-8601 UTC date-time window (inclusive). None means unbounded.

    Returns ChainVerificationResult with the same semantics as verify_chain().

    Algorithm:
    1. Open SQLite DB (read-only: "file:{path}?mode=ro&uri=true" is preferred
       but fall back to read-write if the file does not yet support URI mode).
    2. Build SELECT query scoped by session_id (if provided) and date window.
       ORDER BY logged_at ASC.
    3. For each row (as dict):
       a. Recompute expected_hash = _recompute_ai_hash(row).
       b. Compare to row["record_hash"].
       c. Verify row["previous_hash"] matches the record_hash of the preceding row
          (or "GENESIS" for the first row).
       d. On mismatch, record first_tampered_log_id and set verified=False.
    4. Detect log_id gaps (rows where previous_hash does not match preceding
       row's record_hash).
    5. Return ChainVerificationResult.

    Wrap all sqlite3 calls in asyncio.to_thread.
    """

ALSO UPDATE
-----------
Update _CANONICAL_FIELDS dict at the top of chain_verifier.py to add the new table:
    _CANONICAL_FIELDS["ai_agent_audit_log"] = ("query_text", "result_hash",
                                                "confidence_score", "answer_text")
```

---

### Coding Prompt 20-D: Update `compliance/retention_policy.py`

```
Modify compliance/retention_policy.py to add the AI agent audit log to the
7-year retention schedule.

CHANGE — Add entry to RETENTION_SCHEDULE dict
---------------------------------------------
Inside the RETENTION_SCHEDULE dict (near the other "audit.*": 7 entries),
add the following entry AFTER the existing "audit.access_event_log" entry:

    "audit.ai_agent_audit_log": 7,  # GNRI-011 — 7-year retention; OCC 2021-25

No other changes to retention_policy.py are required for this gap.
```

---

### Coding Prompt 20-E: Tests for GNRI-011 Audit Log

```
Create ai-agent/tests/test_ai_audit_log.py.

Use pytest + pytest-asyncio. Use a tmp_path-scoped SQLite file for db_url.

Tests to include:

1. test_log_ai_turn_creates_record:
   - Call log_ai_turn with all required fields.
   - Assert returned AIAgentAuditRecord has a valid log_id (UUID4).
   - Assert record_hash is a 64-char hex string.
   - Assert previous_hash == "GENESIS" for the first record.

2. test_hash_chain_links_correctly:
   - Log two turns sequentially (same session_id).
   - Retrieve logs via get_ai_audit_records.
   - Assert record2.previous_hash == record1.record_hash.

3. test_verify_ai_agent_chain_clean:
   - Log 5 turns with distinct turn_ids.
   - Call verify_ai_agent_chain(db_url, session_id=...).
   - Assert result.verified == True and result.rows_checked == 5.

4. test_verify_ai_agent_chain_detects_tamper:
   - Log 3 turns.
   - Directly modify record_hash of the second row via raw sqlite3 connection.
   - Call verify_ai_agent_chain.
   - Assert result.verified == False.
   - Assert result.first_tampered_log_id is not None.

5. test_no_update_or_delete_functions:
   - Import ai_audit_log module.
   - Assert dir(ai_audit_log) does not contain "update_ai_turn" or
     "delete_ai_turn" or "delete_audit_record".

6. test_get_ai_audit_records_date_filter:
   - Log turns at two different logged_at timestamps.
   - Filter by from_date covering only the second timestamp.
   - Assert only 1 record returned.

7. test_plan_steps_serialised_to_json:
   - Log a turn with plan_steps=[{"thought": "x", "action": "sql_query_tool",
     "action_input": "SELECT 1", "observation": "1"}]
   - Assert plan_text is a valid JSON string containing "sql_query_tool".

8. test_retention_schedule_contains_ai_audit_log:
   - Import RETENTION_SCHEDULE from compliance.retention_policy.
   - Assert "audit.ai_agent_audit_log" in RETENTION_SCHEDULE.
   - Assert RETENTION_SCHEDULE["audit.ai_agent_audit_log"] == 7.
```

---

## GAP-21: AI Agent Audit Appendix in Exam Packet Generator

### Context
`compliance/exam_packet_builder.py` has 7 component builders but no `ai_agent_audit` component. GAP-20 must be resolved first because this component queries the `ai_agent_audit_log` table populated by GAP-20.

### Files to Modify
- `compliance/exam_packet_builder.py` — add `build_ai_agent_audit_component()` + register in `_COMPONENT_BUILDERS`
- `compliance/exam_packet_pdf.py` — add AI appendix PDF section renderer
- `decision-api/src/main.py` — add `"ai_agent_audit"` to default components list in `POST /v1/audit/generate-package`

### Files to Create
- `compliance/tests/test_exam_packet_ai_appendix.py`

---

### Coding Prompt 21-A: Add `build_ai_agent_audit_component()` to `compliance/exam_packet_builder.py`

```
Modify compliance/exam_packet_builder.py to add the AI Agent Audit Appendix
component builder. Follow the exact same structure as the existing
build_adverse_action_component() function in that file.

CHANGE 1 — New component builder function
------------------------------------------
Add this function BEFORE the _COMPONENT_BUILDERS dict (around line 438):

async def build_ai_agent_audit_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """
    Build the AI Agent Audit Appendix component for regulatory exam packets.

    Queries ai_agent_audit_log for all turns within the spec date range and
    computes summary statistics required by PRD §4.4.1 GNRI-011:
      - Total query count
      - Unique session count
      - Code artifact summaries (SQL hash previews)
      - Confidence score distribution (P25, P50, P75, P90)
      - Grounding rate (fraction of turns where grounded=1)
      - BQ job ID list (non-null only)
      - Chain verification status via verify_ai_agent_chain()

    Returns ExamPacketComponent with status="complete" on success,
    status="error" on any exception, status="stub" if ai_agent_audit_log
    is empty for the specified period.
    """
    try:
        from ai_agent.src.ai_audit_log import get_ai_audit_records  # noqa: E402
        from audit.chain_verifier import verify_ai_agent_chain

        records = await get_ai_audit_records(
            db_url=db_url,
            from_date=spec.from_date,
            to_date=spec.to_date,
            tenant_id=spec.tenant_id,
            limit=10_000,
        )

        if not records:
            return ExamPacketComponent(
                name="ai_agent_audit",
                status="stub",
                data={"note": "No AI agent audit records found for the specified period."},
            )

        import statistics

        # Basic counts
        total_queries = len(records)
        unique_sessions = len({r.session_id for r in records})

        # Code artifact hashes
        sql_hashes = [r.query_hash for r in records if r.query_hash]
        result_hashes = [r.result_hash for r in records if r.result_hash]

        # Confidence score distribution
        scores = [r.confidence_score for r in records if r.confidence_score is not None]
        score_distribution: Dict[str, Any] = {}
        if scores:
            sorted_scores = sorted(scores)
            n = len(sorted_scores)
            score_distribution = {
                "count": n,
                "min": round(sorted_scores[0], 4),
                "p25": round(sorted_scores[int(n * 0.25)], 4),
                "p50": round(sorted_scores[int(n * 0.50)], 4),
                "p75": round(sorted_scores[int(n * 0.75)], 4),
                "p90": round(sorted_scores[int(n * 0.90)], 4),
                "max": round(sorted_scores[-1], 4),
            }

        # Grounding rate
        grounded_count = sum(1 for r in records if r.grounded)
        grounding_rate = round(grounded_count / total_queries * 100, 2)

        # BQ job IDs
        bq_job_ids = [r.bq_job_id for r in records if r.bq_job_id]

        # Chain verification
        chain_result = await verify_ai_agent_chain(db_url=db_url)
        chain_status = "verified" if chain_result.verified else "TAMPERED"

        return ExamPacketComponent(
            name="ai_agent_audit",
            status="complete",
            data={
                "total_queries": total_queries,
                "unique_sessions": unique_sessions,
                "date_range": {"from": spec.from_date, "to": spec.to_date},
                "sql_artifact_hashes": sql_hashes[:50],   # cap at 50 for report size
                "result_hashes": result_hashes[:50],
                "confidence_score_distribution": score_distribution,
                "grounded_count": grounded_count,
                "refusal_count": total_queries - grounded_count,
                "grounding_rate_pct": grounding_rate,
                "bq_job_ids": bq_job_ids[:100],
                "chain_verification": {
                    "status": chain_status,
                    "rows_checked": chain_result.rows_checked,
                    "first_tampered_log_id": chain_result.first_tampered_log_id,
                },
            },
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="ai_agent_audit",
            status="error",
            data=None,
            error_message=str(exc),
        )

CHANGE 2 — Register in _COMPONENT_BUILDERS dict
------------------------------------------------
In the _COMPONENT_BUILDERS dict, add after the "data_lineage" entry:

    "ai_agent_audit": build_ai_agent_audit_component,

The dict should now have 8 entries total.

CHANGE 3 — Add to DEFAULT_COMPONENTS list (if one exists)
----------------------------------------------------------
If there is a DEFAULT_COMPONENTS list or constant anywhere in the file,
append "ai_agent_audit" to it. If no such list exists, note that the
`build_exam_packet` function accepts components explicitly and no change
is needed here — the caller (decision-api) controls the default list.
```

---

### Coding Prompt 21-B: Update `compliance/exam_packet_pdf.py` — AI Appendix Section

```
Modify compliance/exam_packet_pdf.py to render the "ai_agent_audit" component
as a PDF section.

CONTEXT
-------
The existing render_exam_packet_pdf() function at line 51 iterates over
packet.components and renders each one. Find the per-component rendering loop
(around line 150) and add a new elif/case for "ai_agent_audit".

CHANGE — Add AI appendix rendering branch
------------------------------------------
Within the per-component iteration loop, add a new condition after the last
existing elif branch:

    elif comp.name == "ai_agent_audit" and comp.status == "complete" and comp.data:
        d = comp.data
        story.append(Paragraph("AI Agent Audit Appendix (GNRI-011)", styles["Heading2"]))
        story.append(Spacer(1, 0.15 * inch))

        # Summary statistics table
        summary_rows = [
            ["Metric", "Value"],
            ["Total AI Queries", str(d.get("total_queries", 0))],
            ["Unique Sessions", str(d.get("unique_sessions", 0))],
            ["Grounded Answers", str(d.get("grounded_count", 0))],
            ["Refusals (Zero-Data)", str(d.get("refusal_count", 0))],
            ["Grounding Rate", f"{d.get('grounding_rate_pct', 0):.2f}%"],
            ["Exam Period", f"{d.get('date_range', {}).get('from', '')} – {d.get('date_range', {}).get('to', '')}"],
        ]
        summary_table = Table(summary_rows, colWidths=[3.5 * inch, 3.5 * inch])
        summary_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(summary_table)
        story.append(Spacer(1, 0.2 * inch))

        # Confidence score distribution
        if conf_dist := d.get("confidence_score_distribution"):
            story.append(Paragraph("Confidence Score Distribution", styles["Heading3"]))
            conf_rows = [["Percentile", "Score"]]
            for pct_label in ("p25", "p50", "p75", "p90"):
                conf_rows.append([pct_label.upper(), str(conf_dist.get(pct_label, "—"))])
            conf_table = Table(conf_rows, colWidths=[3.5 * inch, 3.5 * inch])
            conf_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5f8a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            story.append(conf_table)
            story.append(Spacer(1, 0.2 * inch))

        # Chain verification status
        chain = d.get("chain_verification", {})
        chain_color = colors.HexColor("#006400") if chain.get("status") == "verified" else colors.red
        story.append(Paragraph(
            f"Hash Chain Integrity: <font color='{chain_color.hexval() if hasattr(chain_color, 'hexval') else '#006400'}'>"
            f"{chain.get('status', 'unknown').upper()}</font> "
            f"({chain.get('rows_checked', 0)} rows checked)",
            styles["Normal"]
        ))

        # SQL artifact hash list (first 10 for readability)
        sql_hashes = d.get("sql_artifact_hashes", [])
        if sql_hashes:
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph("SQL Artifact Hashes (first 10)", styles["Heading3"]))
            for h in sql_hashes[:10]:
                story.append(Paragraph(f"• {h}", styles["Code"]))

        story.append(Spacer(1, 0.3 * inch))

NOTE: Import styles["Code"] using the existing styles dict already in use in
render_exam_packet_pdf(). If styles["Code"] is not available, use styles["Normal"]
with a monospace font override. Do not add new top-level imports; only extend
the existing function body.
```

---

### Coding Prompt 21-C: Update `decision-api/src/main.py` — Add `ai_agent_audit` to Default Exam Packet

```
Modify decision-api/src/main.py to include "ai_agent_audit" in the default
list of exam packet components.

Find the POST /v1/audit/generate-package endpoint handler (search for the
route decorator or the function that calls build_exam_packet). Specifically,
find where the ExamPacketSpec is constructed and where the default components
list is defined.

If there is a DEFAULT_EXAM_COMPONENTS list or a hardcoded list of component
names, append "ai_agent_audit" to it.

Example: If the existing code reads:
    DEFAULT_EXAM_COMPONENTS = [
        "adverse_actions", "model_documentation", "policy_snapshots",
        "decision_samples", "fair_lending_analysis", "committee_approvals",
        "data_lineage",
    ]
Change it to:
    DEFAULT_EXAM_COMPONENTS = [
        "adverse_actions", "model_documentation", "policy_snapshots",
        "decision_samples", "fair_lending_analysis", "committee_approvals",
        "data_lineage", "ai_agent_audit",
    ]

If the components are specified inline in the ExamPacketSpec instantiation,
add "ai_agent_audit" to that list.

Also update the route docstring / OpenAPI description to mention
"ai_agent_audit" as an available component.
```

---

### Coding Prompt 21-D: Tests for AI Agent Audit Appendix

```
Create compliance/tests/test_exam_packet_ai_appendix.py.

Use pytest + pytest-asyncio. Mock all external DB calls using unittest.mock.

Tests to include:

1. test_build_ai_agent_audit_component_complete:
   - Mock get_ai_audit_records to return 5 fake AIAgentAuditRecord objects
     with varying confidence_score values (0.2, 0.5, 0.7, 0.8, 0.9),
     grounded=True for 4 of them, and non-null query_hash and result_hash.
   - Mock verify_ai_agent_chain to return ChainVerificationResult(
       verified=True, rows_checked=5, first_tampered_log_id=None,
       first_tampered_at=None, gap_detected=False).
   - Build a minimal ExamPacketSpec(tenant_id="test", from_date="2026-01-01",
     to_date="2026-03-31", components=["ai_agent_audit"], format="json").
   - Call build_ai_agent_audit_component(spec, "test.db").
   - Assert component.status == "complete".
   - Assert component.data["total_queries"] == 5.
   - Assert component.data["unique_sessions"] >= 1.
   - Assert component.data["grounding_rate_pct"] == 80.0.
   - Assert component.data["chain_verification"]["status"] == "verified".

2. test_build_ai_agent_audit_component_stub_when_empty:
   - Mock get_ai_audit_records to return [].
   - Assert component.status == "stub".
   - Assert "No AI agent audit records" in component.data["note"].

3. test_build_ai_agent_audit_component_error_on_exception:
   - Mock get_ai_audit_records to raise RuntimeError("DB unavailable").
   - Assert component.status == "error".
   - Assert "DB unavailable" in component.error_message.

4. test_ai_agent_audit_in_component_builders:
   - Import _COMPONENT_BUILDERS from compliance.exam_packet_builder.
   - Assert "ai_agent_audit" in _COMPONENT_BUILDERS.
   - Assert callable(_COMPONENT_BUILDERS["ai_agent_audit"]).

5. test_full_exam_packet_includes_ai_agent_audit:
   - Mock build_ai_agent_audit_component to return a complete component.
   - Mock all other 7 component builders to return stub components.
   - Call build_exam_packet with components=["ai_agent_audit", ...all 7...].
   - Assert the returned ExamPacket has a component with name="ai_agent_audit"
     and status="complete".

6. test_pdf_renders_ai_appendix_section:
   - Construct a minimal ExamPacket containing one ExamPacketComponent with
     name="ai_agent_audit", status="complete", and the expected data dict
     (total_queries=10, unique_sessions=2, grounding_rate_pct=90.0,
      confidence_score_distribution={...}, chain_verification={...},
      sql_artifact_hashes=["abc123"], result_hashes=[]).
   - Call render_exam_packet_pdf(packet) from compliance.exam_packet_pdf.
   - Assert the returned bytes starts with b"%PDF".
   - Assert len(bytes) > 1000.
```

---

## Dependency and Execution Order

```
Sprint 14
├── GAP-19
│   ├── Prompt 19-A  →  ai-agent/src/code_artifact_store.py        (no deps)
│   ├── Prompt 19-B  →  ai-agent/src/confidence_scorer.py          (no deps)
│   ├── Prompt 19-C  →  ai-agent/src/main.py (modify)              (deps: 19-A, 19-B)
│   └── Prompt 19-D  →  ai-agent/tests/test_*.py (3 files)         (deps: 19-A, 19-B, 19-C)
│
└── GAP-20
    ├── Prompt 20-A  →  ai-agent/src/ai_audit_log.py               (no deps)
    ├── Prompt 20-B  →  ai-agent/src/main.py (modify)              (dep: 20-A + 19-C already done)
    ├── Prompt 20-C  →  audit/chain_verifier.py (modify)           (dep: 20-A)
    ├── Prompt 20-D  →  compliance/retention_policy.py (modify)    (no deps)
    └── Prompt 20-E  →  ai-agent/tests/test_ai_audit_log.py        (deps: 20-A, 20-C, 20-D)

Sprint 15  (requires GAP-20 complete)
└── GAP-21
    ├── Prompt 21-A  →  compliance/exam_packet_builder.py (modify)  (dep: GAP-20 → ai_audit_log)
    ├── Prompt 21-B  →  compliance/exam_packet_pdf.py (modify)      (dep: 21-A)
    ├── Prompt 21-C  →  decision-api/src/main.py (modify)           (dep: 21-A)
    └── Prompt 21-D  →  compliance/tests/test_exam_packet_ai_appendix.py  (deps: 21-A, 21-B)
```

---

## Validation Checklist (post-implementation)

Run the following after all 3 gaps are closed:

```bash
# Unit tests for new modules
pytest ai-agent/tests/test_code_artifact_store.py -v
pytest ai-agent/tests/test_confidence_scorer.py -v
pytest ai-agent/tests/test_anti_hallucination.py -v
pytest ai-agent/tests/test_ai_audit_log.py -v
pytest compliance/tests/test_exam_packet_ai_appendix.py -v

# Regression: existing chain verifier must still pass
pytest audit/tests/test_chain_verifier.py -v
pytest audit/tests/test_hash_chain_migration.py -v

# Regression: retention policy
pytest compliance/tests/ -v

# Full suite (no regressions)
pytest --tb=short -q
```

### PRD §5 Controls Acceptance Criteria

| Control | Acceptance Criterion |
|---------|----------------------|
| Executable SQL surfaced with every answer | `AgentTurnMetadata.code_artifacts.sql_executed` is non-null for any turn that calls `sql_query_tool` |
| Confidence score on every answer | `AgentTurnMetadata.confidence_score` is in [0.0, 1.0] for every SSE stream |
| Grounding gate | Empty-result turns emit `"refusal": True` SSE event; no hallucinated summary |
| `query_hash` + `result_hash` | Both are 64-char hex strings for every `sql_query_tool` invocation |
| GNRI-011 audit table | `ai_agent_audit_log` rows present after each `/agent/chat` call |
| Hash chain integrity | `verify_ai_agent_chain()` returns `verified=True` on clean log |
| 7-year retention rule | `"audit.ai_agent_audit_log"` in `RETENTION_SCHEDULE` with value `7` |
| Exam packet appendix | `build_exam_packet(spec)` with `components=["ai_agent_audit"]` returns `status="complete"` |
| Tamper detection | Manually modifying a `record_hash` in `ai_agent_audit_log` causes `verify_ai_agent_chain()` to return `verified=False` |

---

*For the gap analysis that drives this plan, see [GAP_ANALYSIS_PRD_VS_IMPLEMENTATION.md](GAP_ANALYSIS_PRD_VS_IMPLEMENTATION.md). For the unified PRD, see [Unified_ILOL_PRD.md](Unified_ILOL_PRD.md).*

---

## GAP-22: HITL Approval Gate for Exam Packet Export and AI Regulatory Submissions

### Context
`POST /v1/audit/generate-package` returns the full exam packet payload immediately. PRD §11.3 and Appendix C R-01 require a human approver to explicitly confirm the packet (or AI-generated regulatory output) before it is released. No `exam_packet_approvals` table, no pending/approved state machine, and no approval endpoints exist anywhere in the codebase.

### Files to Create
- `compliance/exam_packet_approval_store.py`
- `compliance/tests/test_exam_packet_approval.py`

### Files to Modify
- `decision-api/src/main.py` — modify `POST /v1/audit/generate-package`; add `POST /v1/audit/packets/{id}/approve`, `POST /v1/audit/packets/{id}/reject`, `GET /v1/audit/packets/{id}`
- `compliance/exam_packet_builder.py` — add `status` field to `ExamPacket`

---

### Coding Prompt 22-A: Create `compliance/exam_packet_approval_store.py`

```
Create the file compliance/exam_packet_approval_store.py.

PURPOSE
-------
Manage the approval state machine for generated exam packets.
Every packet must pass through the states:
  pending_approval → approved | rejected
No packet payload is accessible via API until status = "approved".

TABLE DDL
---------
CREATE TABLE IF NOT EXISTS exam_packet_approvals (
    packet_id        TEXT    PRIMARY KEY,      -- FK to the packet (UUID4 from build_exam_packet)
    tenant_id        TEXT    NOT NULL,
    generated_by     TEXT    NOT NULL,         -- user ID / JWT sub of the generator
    generated_at     TEXT    NOT NULL,         -- ISO-8601 UTC
    status           TEXT    NOT NULL DEFAULT 'pending_approval',
                                               -- 'pending_approval' | 'approved' | 'rejected'
    reviewed_by      TEXT,                     -- user ID of approver/rejector (NULL until actioned)
    reviewed_at      TEXT,                     -- ISO-8601 UTC (NULL until actioned)
    review_notes     TEXT,                     -- free-text justification from reviewer
    packet_json      TEXT    NOT NULL,         -- full serialised ExamPacket JSON (stored on generation)
    created_at       TEXT    NOT NULL
);

Important integrity rules (enforced at application layer):
- `reviewed_by` MUST NOT equal `generated_by` (SOD — approver ≠ generator).
- Once status is 'approved' or 'rejected', no further status transition is allowed.

PUBLIC API
----------

@dataclass
class ExamPacketApprovalRecord:
    packet_id: str
    tenant_id: str
    generated_by: str
    generated_at: str
    status: str                        # 'pending_approval' | 'approved' | 'rejected'
    reviewed_by: Optional[str]
    reviewed_at: Optional[str]
    review_notes: Optional[str]
    created_at: str

async def submit_packet_for_approval(
    db_url: str,
    packet_id: str,
    tenant_id: str,
    generated_by: str,
    packet_json: str,
) -> ExamPacketApprovalRecord:
    """
    Store the generated packet in pending_approval state.
    Raise ValueError if packet_id already exists.
    """

async def approve_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: Optional[str] = None,
) -> ExamPacketApprovalRecord:
    """
    Approve the packet. Transitions status from 'pending_approval' -> 'approved'.
    Raise PermissionError if reviewed_by == generated_by (SOD violation).
    Raise ValueError if packet is not in 'pending_approval' state.
    """

async def reject_packet(
    db_url: str,
    packet_id: str,
    reviewed_by: str,
    review_notes: str,
) -> ExamPacketApprovalRecord:
    """
    Reject the packet. Transitions status from 'pending_approval' -> 'rejected'.
    review_notes is required (min 10 chars) when rejecting.
    Raise PermissionError if reviewed_by == generated_by (SOD violation).
    Raise ValueError if packet is not in 'pending_approval' state.
    """

async def get_approval_record(
    db_url: str,
    packet_id: str,
) -> Optional[ExamPacketApprovalRecord]:
    """Return the approval record for the given packet_id, or None if not found."""

async def get_approved_packet_json(
    db_url: str,
    packet_id: str,
) -> Optional[str]:
    """
    Return the serialised ExamPacket JSON only if status == 'approved'.
    Return None if not found.
    Raise PermissionError if status is 'pending_approval' or 'rejected'.
    """

async def list_pending_packets(
    db_url: str,
    tenant_id: str,
) -> list[ExamPacketApprovalRecord]:
    """Return all packets with status='pending_approval' for a tenant."""

IMPLEMENTATION NOTES
--------------------
- Use sqlite3 wrapped in asyncio.to_thread() (same pattern as referral_store.py).
- Write an approval event to the existing audit_log via a direct sqlite3 INSERT
  whenever a packet is approved or rejected (table: audit_log, action:
  'EXAM_PACKET_APPROVED' or 'EXAM_PACKET_REJECTED', decision_output: packet_id).
  If the audit_log table is not on the same DB connection, skip silently.
- SOD check: if reviewed_by == generated_by, raise PermissionError with message
  "Approver and generator must be different users (SOD violation)".
```

---

### Coding Prompt 22-B: Modify `decision-api/src/main.py` — Exam Packet HITL Gate

```
Modify decision-api/src/main.py to implement the HITL approval gate for exam
packets. Follow the existing stage/approve pattern already used for policy
config (POST /v1/config/stage and POST /v1/config/approve).

CHANGE 1 — New import
---------------------
Add to imports:
    from compliance.exam_packet_approval_store import (
        submit_packet_for_approval,
        approve_packet,
        reject_packet,
        get_approval_record,
        get_approved_packet_json,
        list_pending_packets,
    )

CHANGE 2 — Modify POST /v1/audit/generate-package
--------------------------------------------------
Current behaviour: calls build_exam_packet() and returns the full packet.
New behaviour:
  1. Build the packet as before (build_exam_packet()).
  2. Serialise to JSON (packet.to_dict()).
  3. Extract generated_by from the JWT (_user["sub"] or _user["user_id"]).
  4. Call submit_packet_for_approval(DB_URL, packet_id, tenant_id,
     generated_by, packet_json).
  5. Return HTTP 202 with body:
     {
       "packet_id": "...",
       "status": "pending_approval",
       "message": "Exam packet generated. Awaiting approval by a second authorised user before export.",
       "approve_url": "/v1/audit/packets/{packet_id}/approve",
       "reject_url": "/v1/audit/packets/{packet_id}/reject"
     }
  Do NOT return the packet payload in this response.

CHANGE 3 — Add POST /v1/audit/packets/{packet_id}/approve
----------------------------------------------------------
@app.post(
    "/v1/audit/packets/{packet_id}/approve",
    summary="Approve a generated exam packet for export (HITL gate)",
)
async def approve_exam_packet(
    packet_id: str,
    notes: Optional[str] = Body(None),
    _user: Dict = Depends(verify_bearer),
):
    reviewed_by = _user.get("sub") or _user.get("user_id", "unknown")
    try:
        record = await approve_packet(DB_URL, packet_id, reviewed_by, notes)
        return {"packet_id": packet_id, "status": record.status,
                "reviewed_by": reviewed_by, "reviewed_at": record.reviewed_at}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

CHANGE 4 — Add POST /v1/audit/packets/{packet_id}/reject
---------------------------------------------------------
@app.post(
    "/v1/audit/packets/{packet_id}/reject",
    summary="Reject a generated exam packet (HITL gate)",
)
async def reject_exam_packet(
    packet_id: str,
    notes: str = Body(..., min_length=10),
    _user: Dict = Depends(verify_bearer),
):
    reviewed_by = _user.get("sub") or _user.get("user_id", "unknown")
    try:
        record = await reject_packet(DB_URL, packet_id, reviewed_by, notes)
        return {"packet_id": packet_id, "status": record.status,
                "reviewed_by": reviewed_by}
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

CHANGE 5 — Add GET /v1/audit/packets/{packet_id}
-------------------------------------------------
@app.get(
    "/v1/audit/packets/{packet_id}",
    summary="Retrieve an approved exam packet payload",
)
async def get_exam_packet(
    packet_id: str,
    _user: Dict = Depends(verify_bearer),
):
    try:
        packet_json = await get_approved_packet_json(DB_URL, packet_id)
        if packet_json is None:
            raise HTTPException(status_code=404, detail="Packet not found.")
        return json.loads(packet_json)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

CHANGE 6 — Add GET /v1/audit/packets/pending
---------------------------------------------
@app.get(
    "/v1/audit/packets/pending",
    summary="List exam packets awaiting human approval",
)
async def list_pending_exam_packets(_user: Dict = Depends(verify_bearer)):
    tenant_id = _user["tenant_id"]
    records = await list_pending_packets(DB_URL, tenant_id)
    return [{"packet_id": r.packet_id, "generated_by": r.generated_by,
             "generated_at": r.generated_at} for r in records]
```

---

### Coding Prompt 22-C: Tests for HITL Approval Gate

```
Create compliance/tests/test_exam_packet_approval.py.

Use pytest + pytest-asyncio. Use a tmp_path-scoped SQLite file for db_url.

Tests to include:

1. test_submit_creates_pending_record:
   - Call submit_packet_for_approval with valid arguments.
   - Assert returned record.status == "pending_approval".
   - Assert record.reviewed_by is None.

2. test_approve_transitions_to_approved:
   - Submit a packet as user_a.
   - Call approve_packet with reviewed_by=user_b (different from user_a).
   - Assert record.status == "approved".
   - Assert record.reviewed_by == user_b.
   - Call get_approved_packet_json and assert the JSON is returned.

3. test_reject_transitions_to_rejected:
   - Submit a packet as user_a.
   - Call reject_packet with reviewed_by=user_b and notes="Test rejection reason".
   - Assert record.status == "rejected".

4. test_sod_violation_raises_permission_error:
   - Submit a packet as user_a.
   - Call approve_packet with reviewed_by=user_a (same user).
   - Assert PermissionError is raised.
   - Assert "SOD" in the error message.

5. test_double_approval_raises_value_error:
   - Submit and approve a packet.
   - Call approve_packet again on the same packet_id.
   - Assert ValueError is raised.

6. test_get_approved_raises_permission_error_when_pending:
   - Submit a packet (do not approve it).
   - Call get_approved_packet_json.
   - Assert PermissionError is raised.

7. test_reject_requires_notes:
   - Call reject_packet with review_notes="" (empty).
   - Assert ValueError is raised (notes too short).

8. test_list_pending_returns_only_pending:
   - Submit 3 packets; approve 1, reject 1, leave 1 pending.
   - Call list_pending_packets.
   - Assert only 1 record is returned.
```

---

## GAP-23: Manual Review Referral Queue and Post-Decision Override API

### Context
When the decision engine returns `MANUAL_REVIEW`, the API returns HTTP 202 but nothing persists the case for a loan officer to act on it. There is no queue, no claim mechanism, no post-decision override endpoint, and no `CONDITIONAL` decision type. The PRD requires a full referral lifecycle: engine flags → queue entry created → loan officer claims → loan officer resolves (override APPROVE/REJECT/CONDITIONAL with justification) → four-eyes approval → logged immutably.

### Files to Create
- `decision-api/src/referral_store.py`
- `monitoring/referral_sla_monitor.py`
- `decision-api/tests/test_referral_queue.py`
- `decision-api/tests/test_post_decision_override.py`
- `monitoring/tests/test_referral_sla.py`

### Files to Modify
- `decision_engine/engine.py` — add `DECISION_CONDITIONAL`, `ConditionalTerms`, wire into `make_decision()`
- `decision-api/src/main.py` — wire `create_referral()` on MANUAL_REVIEW; add queue/claim/override endpoints

---

### Coding Prompt 23-A: Create `decision-api/src/referral_store.py`

```
Create the file decision-api/src/referral_store.py.

PURPOSE
-------
Persist and manage credit decision referral cases that require manual human
review. Every MANUAL_REVIEW decision output triggers a referral entry.
The resolution of a referral (approve/reject/conditional override) must be
written to audit.override_log via the existing log_override() function.

TABLE DDL
---------
CREATE TABLE IF NOT EXISTS referral_queue (
    referral_id        TEXT    PRIMARY KEY,   -- UUID4
    application_id     TEXT    NOT NULL UNIQUE,
    tenant_id          TEXT    NOT NULL,
    created_at         TEXT    NOT NULL,      -- ISO-8601 UTC; when MANUAL_REVIEW decision fired
    sla_deadline       TEXT    NOT NULL,      -- ISO-8601 UTC; created_at + SLA_HOURS
    status             TEXT    NOT NULL DEFAULT 'pending',
                                              -- 'pending' | 'claimed' | 'resolved' | 'sla_breached'
    claimed_by         TEXT,                  -- user ID of loan officer who claimed it
    claimed_at         TEXT,
    resolution         TEXT,                  -- 'APPROVE' | 'REJECT' | 'CONDITIONAL'
    resolution_notes   TEXT,
    resolved_by        TEXT,                  -- user ID of resolver (submitter)
    resolved_at        TEXT,
    approved_by        TEXT,                  -- second approver (four-eyes); NULL until approved
    approved_at        TEXT,
    override_id        TEXT,                  -- FK to policy_overrides_log.override_id
    pd_score           REAL,                  -- stored at creation for context
    fraud_probability  REAL
);

SLA_HOURS = 72  # 3 business days; configurable via REFERRAL_SLA_HOURS env var

PUBLIC API
----------

@dataclass
class ReferralRecord:
    referral_id: str
    application_id: str
    tenant_id: str
    created_at: str
    sla_deadline: str
    status: str
    claimed_by: Optional[str]
    claimed_at: Optional[str]
    resolution: Optional[str]
    resolution_notes: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[str]
    override_id: Optional[str]
    pd_score: Optional[float]
    fraud_probability: Optional[float]

async def create_referral(
    db_url: str,
    application_id: str,
    tenant_id: str,
    pd_score: Optional[float] = None,
    fraud_probability: Optional[float] = None,
    sla_hours: int = 72,
) -> ReferralRecord:
    """
    Create a new pending referral for the given application.
    sla_deadline = created_at + sla_hours.
    Raise ValueError if application_id already has a pending/claimed referral.
    """

async def claim_referral(
    db_url: str,
    referral_id: str,
    claimed_by: str,
) -> ReferralRecord:
    """
    Assign a loan officer to a pending referral.
    Transition: 'pending' -> 'claimed'.
    Raise ValueError if referral is not in 'pending' state.
    """

async def resolve_referral(
    db_url: str,
    referral_id: str,
    resolution: str,           # 'APPROVE' | 'REJECT' | 'CONDITIONAL'
    resolution_notes: str,     # min 20 chars required
    resolved_by: str,
    approved_by: str,          # four-eyes: must differ from resolved_by
    conditional_terms: Optional[dict] = None,  # populated when resolution='CONDITIONAL'
) -> ReferralRecord:
    """
    Resolve a claimed referral.
    Steps:
      1. Validate: resolution in ('APPROVE', 'REJECT', 'CONDITIONAL').
      2. Validate: approved_by != resolved_by (four-eyes).
      3. Validate: resolution_notes len >= 20.
      4. Transition status: 'claimed' -> 'resolved'.
      5. Build a PolicyOverrideRecord and call log_override() to write to
         policy_overrides_log. Use override_type='MANUAL_REVIEW_RESOLUTION',
         original_value=0.0 (placeholder), override_value=1.0 (placeholder),
         justification=resolution_notes, submitted_by=resolved_by,
         approved_by=approved_by.
      6. Store override_id from step 5 in the referral row.
      7. Return updated ReferralRecord.
    """

async def get_queue(
    db_url: str,
    tenant_id: str,
    status_filter: Optional[str] = None,   # None = all statuses
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[ReferralRecord], int]:
    """
    Return paginated referral queue for a tenant.
    Also mark any 'pending' or 'claimed' rows past sla_deadline as
    'sla_breached' at query time (lazy SLA evaluation).
    Returns (records, total_count).
    """

async def get_sla_breaches(
    db_url: str,
    tenant_id: str,
) -> list[ReferralRecord]:
    """
    Return all referrals where sla_deadline < now() and status != 'resolved'.
    This is the data source for the referral SLA monitor.
    """

IMPLEMENTATION NOTES
--------------------
- Use sqlite3 wrapped in asyncio.to_thread() for all DB calls.
- Import log_override from audit.override_log inside resolve_referral() (lazy
  import to avoid circular dependencies).
- The DB_URL for override_log (SQLAlchemy async URL) may differ from the
  referral_store DB_URL (SQLite filename). Accept both as parameters.
- REFERRAL_SLA_HOURS = int(os.getenv("REFERRAL_SLA_HOURS", "72")).
```

---

### Coding Prompt 23-B: Add `DECISION_CONDITIONAL` to `decision_engine/engine.py`

```
Modify decision_engine/engine.py to add the CONDITIONAL decision type.

CHANGE 1 — New constant
------------------------
After the existing DECISION_MANUAL_REVIEW constant, add:

    DECISION_CONDITIONAL = "CONDITIONAL"
    #: Application is conditionally approved subject to specified terms.
    #: Terms are stored in DecisionResult.conditional_terms.

CHANGE 2 — New dataclass
-------------------------
@dataclass
class ConditionalTerms:
    """
    Terms attached to a CONDITIONAL approval.

    Examples: reduced loan amount, co-signer required, additional collateral,
    income re-verification within N days.
    """
    approved_amount: Optional[float] = None     # if different from requested
    co_signer_required: bool = False
    collateral_required: bool = False
    income_reverification_days: Optional[int] = None
    additional_conditions: Optional[str] = None  # free-text

CHANGE 3 — Add conditional_terms to DecisionResult
----------------------------------------------------
In the DecisionResult dataclass, add an optional field after override_records:

    conditional_terms: Optional[ConditionalTerms] = None
    #: Populated only when decision == DECISION_CONDITIONAL.

CHANGE 4 — Export in __all__ / public API comment
--------------------------------------------------
Update the module docstring and `__all__` (if present) to include:
    DECISION_CONDITIONAL, ConditionalTerms

No changes to the make_decision() function logic are required at this stage —
conditional decisions are generated by the post-decision override workflow
(referral resolution), not by the automated pipeline. The engine simply needs
the constant and dataclass so the override API can produce well-typed results.
```

---

### Coding Prompt 23-C: Wire `create_referral()` and Add Queue/Override Endpoints to `decision-api/src/main.py`

```
Modify decision-api/src/main.py to:
  1. Create a referral entry whenever _run_pipeline() produces MANUAL_REVIEW.
  2. Expose the referral queue and post-decision override endpoints.

CHANGE 1 — New imports
-----------------------
Add:
    from .referral_store import (
        create_referral,
        claim_referral,
        resolve_referral,
        get_queue,
        get_sla_breaches,
        ReferralRecord,
    )

CHANGE 2 — Wire create_referral into _run_pipeline()
------------------------------------------------------
In _run_pipeline(), after the block that calls save_notice() on REJECT (the
adverse action notice path), add a similar block for MANUAL_REVIEW:

    if decision_result.decision == "MANUAL_REVIEW":
        asyncio.create_task(create_referral(
            db_url=_REFERRAL_DB_URL,
            application_id=application.application_id,
            tenant_id=tenant_id,
            pd_score=getattr(decision_result, 'pd_score', None),
            fraud_probability=getattr(decision_result, 'fraud_probability', None),
            sla_hours=int(os.getenv("REFERRAL_SLA_HOURS", "72")),
        ))

_REFERRAL_DB_URL = os.getenv("REFERRAL_DB_URL", "referral_queue.db")

CHANGE 3 — New request/response schemas (add to schemas section)
----------------------------------------------------------------
class ClaimReferralRequest(BaseModel):
    pass  # claimed_by comes from JWT

class OverrideResolutionRequest(BaseModel):
    referral_id: str
    resolution: Literal["APPROVE", "REJECT", "CONDITIONAL"]
    resolution_notes: str = Field(..., min_length=20)
    approved_by: str = Field(..., description="Second approver user ID (four-eyes)")
    conditional_terms: Optional[dict] = None

CHANGE 4 — Add GET /v1/review/queue
------------------------------------
@app.get("/v1/review/queue", summary="List manual review referral queue for tenant")
async def get_referral_queue(
    status: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    _user: Dict = Depends(verify_bearer),
):
    tenant_id = _user["tenant_id"]
    records, total = await get_queue(_REFERRAL_DB_URL, tenant_id, status, page, per_page)
    return {"items": [dataclasses.asdict(r) for r in records],
            "total": total, "page": page, "per_page": per_page}

CHANGE 5 — Add POST /v1/review/{referral_id}/claim
----------------------------------------------------
@app.post("/v1/review/{referral_id}/claim",
          summary="Claim a pending referral for manual review")
async def claim_referral_endpoint(
    referral_id: str,
    _user: Dict = Depends(verify_bearer),
):
    claimed_by = _user.get("sub") or _user.get("user_id", "unknown")
    try:
        record = await claim_referral(_REFERRAL_DB_URL, referral_id, claimed_by)
        return dataclasses.asdict(record)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

CHANGE 6 — Add POST /v1/decisions/{application_id}/override
------------------------------------------------------------
@app.post("/v1/decisions/{application_id}/override",
          summary="Submit a post-decision override for a MANUAL_REVIEW application")
async def post_decision_override(
    application_id: str,
    req: OverrideResolutionRequest,
    _user: Dict = Depends(verify_bearer),
):
    resolved_by = _user.get("sub") or _user.get("user_id", "unknown")
    try:
        from .referral_store import resolve_referral as _resolve
        # look up referral by application_id
        records, _ = await get_queue(
            _REFERRAL_DB_URL, _user["tenant_id"], status_filter="claimed"
        )
        match = next((r for r in records if r.application_id == application_id), None)
        if not match:
            raise HTTPException(status_code=404,
                detail="No claimed referral found for this application.")
        record = await _resolve(
            db_url=_REFERRAL_DB_URL,
            referral_id=match.referral_id,
            resolution=req.resolution,
            resolution_notes=req.resolution_notes,
            resolved_by=resolved_by,
            approved_by=req.approved_by,
            conditional_terms=req.conditional_terms,
        )
        return dataclasses.asdict(record)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
```

---

### Coding Prompt 23-D: Create `monitoring/referral_sla_monitor.py`

```
Create monitoring/referral_sla_monitor.py.

PURPOSE
-------
Detect referral cases that have exceeded the SLA deadline without resolution
and fire an alert via the existing AlertRouter.
Mirrors the pattern in monitoring/cc_pd_monitor.py.

PUBLIC API
----------

@dataclass
class ReferralSLAReport:
    checked_at: str              # ISO-8601 UTC
    tenant_id: str
    breaches: list[dict]         # list of {referral_id, application_id, sla_deadline, hours_overdue}
    breach_count: int
    alert_fired: bool

async def monitor_referral_sla(
    db_url: str,
    tenant_id: str,
    alert_router=None,           # defaults to DEFAULT_ALERT_ROUTER
) -> ReferralSLAReport:
    """
    1. Call get_sla_breaches(db_url, tenant_id) from referral_store.
    2. For each breach, compute hours_overdue = (now - sla_deadline) in hours.
    3. If len(breaches) > 0:
       - Format an alert body listing application_ids, deadline times,
         and hours overdue.
       - Call alert_router.send_alert(
             severity="P2",
             title=f"{len(breaches)} referral(s) past SLA deadline (tenant: {tenant_id})",
             body=body,
         )
       - Set alert_fired = True.
    4. Return ReferralSLAReport.
    """

IMPLEMENTATION NOTES
--------------------
- Import DEFAULT_ALERT_ROUTER from monitoring.alert_router (already implemented).
- Import get_sla_breaches from decision_api.src.referral_store (or accept it
  as an injected callable for testability).
- If the import fails (e.g., running outside the decision-api context),
  return a ReferralSLAReport with breach_count=0 and alert_fired=False
  rather than raising.
- This function is intended to be called by APScheduler on a configurable
  cron (e.g., hourly). Add a comment showing the suggested scheduler config:

    scheduler.add_job(
        monitor_referral_sla,
        CronTrigger(minute=0),   # every hour on the hour
        kwargs={"db_url": REFERRAL_DB_URL, "tenant_id": "*all*"},
        id="referral_sla_monitor",
    )

  (The actual wiring into ai-agent/src/scheduler.py is optional; document
   the hook as a TODO comment in scheduler.py.)
```

---

### Coding Prompt 23-E: Tests

```
Create the following two test files:

FILE 1: decision-api/tests/test_referral_queue.py
--------------------------------------------------
Use pytest + pytest-asyncio. Use a tmp_path SQLite DB for referral_store
and a separate SQLAlchemy async SQLite URL for override_log.

1. test_create_referral_inserts_pending:
   - Call create_referral with valid arguments.
   - Assert status == "pending".
   - Assert sla_deadline is a valid ISO date string AFTER created_at.

2. test_claim_referral_transitions_status:
   - Create then claim a referral.
   - Assert status == "claimed" and claimed_by is set.

3. test_claim_pending_only_raises_on_already_claimed:
   - Create and claim a referral.
   - Attempt to claim again. Assert ValueError raised.

4. test_resolve_referral_approve:
   - Create, claim, then resolve with resolution="APPROVE",
     resolved_by=user_a, approved_by=user_b.
   - Assert status == "resolved" and resolution == "APPROVE".
   - Assert override_id is not None (log_override was called).

5. test_resolve_four_eyes_violation:
   - Create, claim, then resolve with resolved_by=user_a, approved_by=user_a.
   - Assert PermissionError raised.

6. test_resolve_notes_too_short:
   - Attempt resolve with resolution_notes="Too short".
   - Assert ValueError raised.

7. test_get_queue_pagination:
   - Create 5 referrals. Call get_queue(per_page=2, page=1).
   - Assert len(records) == 2 and total == 5.

8. test_sla_breach_detection:
   - Create a referral with sla_hours=0 (immediately breached).
   - Call get_sla_breaches.
   - Assert 1 breach returned.

9. test_sla_status_updated_on_queue_query:
   - Create a referral with sla_hours=0.
   - Call get_queue.
   - Assert the returned record has status == "sla_breached".

FILE 2: decision-api/tests/test_post_decision_override.py
----------------------------------------------------------
Use pytest + httpx AsyncClient against the FastAPI app.

1. test_override_endpoint_approve:
   - Mock _run_pipeline to return MANUAL_REVIEW.
   - POST /v1/underwrite to create the decision and referral.
   - POST claim to /v1/review/{referral_id}/claim.
   - POST /v1/decisions/{application_id}/override with resolution="APPROVE",
     resolution_notes="Reviewed full file; income verified manually. Safe to approve.",
     approved_by="supervisor_1".
   - Assert 200 response.
   - Assert record["resolution"] == "APPROVE".

2. test_override_sod_violation_returns_403:
   - Same setup as above but set approved_by equal to the JWT user_id.
   - Assert 403 response.

3. test_override_no_claimed_referral_returns_404:
   - Call POST /v1/decisions/nonexistent-app-id/override.
   - Assert 404 response.

4. test_conditional_override:
   - POST override with resolution="CONDITIONAL",
     conditional_terms={"approved_amount": 5000, "co_signer_required": True}.
   - Assert 200 and record["resolution"] == "CONDITIONAL".
```

---

## Updated Dependency and Execution Order

```
Sprint 14
├── GAP-19 (10 days)
│   ├── Prompt 19-A  ai-agent/src/code_artifact_store.py
│   ├── Prompt 19-B  ai-agent/src/confidence_scorer.py
│   ├── Prompt 19-C  ai-agent/src/main.py (modify)
│   └── Prompt 19-D  ai-agent/tests/* (3 files)
│
├── GAP-20 (6 days)
│   ├── Prompt 20-A  ai-agent/src/ai_audit_log.py
│   ├── Prompt 20-B  ai-agent/src/main.py (modify)
│   ├── Prompt 20-C  audit/chain_verifier.py (modify)
│   ├── Prompt 20-D  compliance/retention_policy.py (modify)
│   └── Prompt 20-E  ai-agent/tests/test_ai_audit_log.py
│
├── GAP-23 (8 days, PARALLEL with GAP-19/20)
    ├── Prompt 23-B  decision_engine/engine.py (modify)         (no deps)
    ├── Prompt 23-A  decision-api/src/referral_store.py          (dep: 23-B)
    ├── Prompt 23-C  decision-api/src/main.py (modify)           (dep: 23-A)
    ├── Prompt 23-D  monitoring/referral_sla_monitor.py          (dep: 23-A)
    └── Prompt 23-E  tests (2 files)                             (dep: 23-A, 23-C)

Sprint 15  (requires GAP-20 complete)
├── GAP-21 (3 days)
│   ├── Prompt 21-A  compliance/exam_packet_builder.py (modify)
│   ├── Prompt 21-B  compliance/exam_packet_pdf.py (modify)
│   ├── Prompt 21-C  decision-api/src/main.py (modify)
│   └── Prompt 21-D  compliance/tests/test_exam_packet_ai_appendix.py
│
└── GAP-22 (5 days, PARALLEL with GAP-21)
    ├── Prompt 22-A  compliance/exam_packet_approval_store.py
    ├── Prompt 22-B  decision-api/src/main.py (modify)
    └── Prompt 22-C  compliance/tests/test_exam_packet_approval.py
```

---

## Full Validation Checklist (all 5 gaps)

```bash
# GAP-19
pytest ai-agent/tests/test_code_artifact_store.py -v
pytest ai-agent/tests/test_confidence_scorer.py -v
pytest ai-agent/tests/test_anti_hallucination.py -v

# GAP-20
pytest ai-agent/tests/test_ai_audit_log.py -v

# GAP-21
pytest compliance/tests/test_exam_packet_ai_appendix.py -v

# GAP-22
pytest compliance/tests/test_exam_packet_approval.py -v

# GAP-23
pytest decision-api/tests/test_referral_queue.py -v
pytest decision-api/tests/test_post_decision_override.py -v
pytest monitoring/tests/test_referral_sla.py -v

# Regression
pytest audit/tests/test_chain_verifier.py -v
pytest --tb=short -q
```

### Acceptance Criteria Summary

| Gap | Criterion |
|-----|----------|
| GAP-22 | `POST /v1/audit/generate-package` returns 202 with `status="pending_approval"; GET packet before approval returns 403; approve/reject endpoints enforce SOD |
| GAP-23 | MANUAL_REVIEW decision creates a row in referral_queue; `GET /v1/review/queue` returns it; `POST /v1/decisions/{id}/override` resolves it with four-eyes and writes to `policy_overrides_log`; SLA monitor alerts on breach |
| HITL scope | Auto-approved and auto-rejected decisions require NO human action; only MANUAL_REVIEW cases and exam packet exports require human gates |

---

*For the gap analysis that drives this plan, see [GAP_ANALYSIS_PRD_VS_IMPLEMENTATION.md](GAP_ANALYSIS_PRD_VS_IMPLEMENTATION.md). For the unified PRD, see [Unified_ILOL_PRD.md](Unified_ILOL_PRD.md).*
