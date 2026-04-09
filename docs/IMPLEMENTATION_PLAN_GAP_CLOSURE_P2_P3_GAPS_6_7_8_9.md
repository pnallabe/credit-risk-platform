# Implementation Plan: Gap Closure — GAP-06 through GAP-09
**Document**: Integrated Lending Operating Layer (ILOL)
**Gaps Addressed**: GAP-06 (NLG Summaries · P2), GAP-07 (Drift Alert Wiring · P2), GAP-08 (Lineage Query API · P3), GAP-09 (SR 11-7 Auto-Doc on Promotion · P3)
**Date**: 2026-04-07
**Estimated Total Effort**: 6 engineering days
**Dependencies**: Python 3.11+, `openai>=1.0`, `sqlalchemy`, existing `explainability/`, `monitoring/`, `feature_pipeline/`, `decisioning/`, `compliance/`, `decision-api/` modules

---

## Prerequisite Reading

Before starting, read:
- `explainability/shap_explainer.py` — `ExplanationResult` dataclass (fields: `top_positive_factors`, `top_negative_factors`, `predicted_value`, `explanation_text`)
- `monitoring/cc_pd_monitor.py` — `run_monitor()` function, the `alerts` list (~line 417), and threshold constants
- `monitoring/alert_router.py` — `AlertRouter.route()`, `build_channels_from_env()`, `DEFAULT_ALERT_ROUTER`
- `feature_pipeline/lineage.py` — `LineageClient`, `DatasetRef`, `emit_dataset_event()`
- `decisioning/champion_challenger.py` — `ChampionChallengerRouter`, `run_live_split()`, `run_both_shadow()`
- `compliance/generate_model_doc.py` — `generate_mdr()`, `ModelDocumentationConfig`, `validate_mdr_completeness()`
- `audit/logger.py` — `log_decision()` signature (to understand audit record structure)
- `decision-api/src/main.py` — `_run_pipeline()`, `verify_bearer()`, existing routes

---

## GAP-06 — NLG Decision Summaries

**Goal**: For every underwriting decision, auto-generate a plain-language narrative (≤ 200 words) suitable for (a) the loan officer dashboard, (b) the applicant-facing portal, and (c) the adverse action notice body.

**Effort**: ~2 days

---

### Prompt G6-A — Create `explainability/nlg_summarizer.py`

```
Create a new file `explainability/nlg_summarizer.py`.

Requirements:
1. Import `ExplanationResult` from `explainability/shap_explainer.py`.
2. Define a Pydantic (or dataclass) `NLGSummary` with fields:
   - `loan_officer_narrative: str`   — 3–5 sentence professional tone summary
   - `applicant_narrative: str`      — plain-language summary, 8th-grade reading level
   - `adverse_action_body: str`      — Reg B–compliant notice body (blank string if decision == APPROVE)
   - `top_reasons: list[str]`        — top 3 human-readable reason strings (for adverse action codes)
   - `model_version: str`
   - `generated_at: str`             — ISO-8601 UTC timestamp

3. Define `ECOA_REASON_CODES: dict[str, str]` mapping common SHAP feature names
   to Reg B reason codes. At minimum include mappings for:
   - `fico_score`        → "Credit score below threshold (code 01)"
   - `debt_to_income`    → "Debt-to-income ratio too high (code 08)"
   - `credit_util`       → "Proportion of revolving balances too high (code 10)"
   - `months_on_book`    → "Insufficient credit history length (code 14)"
   - `delinquency_count` → "Delinquent past or present credit obligations (code 03)"
   - `public_records`    → "Number of derogatory public records (code 12)"
   A fallback `"other"` → "Other: {feature_name}" must exist for unmapped features.

4. Define `def map_factors_to_ecoa_codes(negative_factors: list[dict]) -> list[str]`.
   Takes `ExplanationResult.top_negative_factors` and returns up to 4 ECOA reason strings.

5. Define the main public function:
   ```python
   def generate_decision_summary(
       explanation: ExplanationResult,
       decision: str,          # "APPROVE" | "REJECT" | "MANUAL_REVIEW"
       application_id: str,
       applicant_name: str = "Applicant",
       model_version: str = "unknown",
       creditor_name: str = "Creditor",
       creditor_phone: str = "1-800-000-0000",
       llm_client=None,        # optional pre-built openai.OpenAI instance
       llm_model: str = "gpt-4o-mini",
       timeout: float = 15.0,
   ) -> NLGSummary:
   ```

   Implementation rules:
   a. If `llm_client` is None, attempt `import openai; llm_client = openai.OpenAI()`.
      If `openai` is not installed or `OPENAI_API_KEY` env var is missing, fall back
      to a TEMPLATE_FALLBACK path (see rule e) and log a warning — never raise.
   b. Build two separate prompts (loan_officer and applicant) using the
      `explanation.top_positive_factors` and `explanation.top_negative_factors`.
      Include the predicted PD probability formatted as a percentage.
   c. Call `llm_client.chat.completions.create(model=llm_model, ...)` wrapped in
      a try/except. On any exception, fall back to TEMPLATE_FALLBACK (rule e).
   d. For `adverse_action_body`, if `decision` is "REJECT" or "MANUAL_REVIEW",
      populate with Reg B boilerplate that includes:
        - CFPB disclosure: "The federal Equal Credit Opportunity Act prohibits
          creditors from discriminating against credit applicants..."
        - The ECOA reason codes from `map_factors_to_ecoa_codes()`
        - Creditor contact info
      If `decision` == "APPROVE", set `adverse_action_body = ""`.
   e. TEMPLATE_FALLBACK function `_template_summary(explanation, decision,
      application_id, applicant_name, model_version, creditor_name, creditor_phone)`:
      Produces all three narrative strings using only f-strings and the data already
      in `ExplanationResult` — no external calls. Must always succeed.

6. Add a `__main__` block that creates a minimal synthetic `ExplanationResult`
   and prints a sample `NLGSummary` (use TEMPLATE_FALLBACK if openai unavailable).

7. Write docstrings for every public function and class.
8. All imports must be inside try/except where the library is optional (openai).
```

---

### Prompt G6-B — Wire `nlg_summarizer` into the Decision API pipeline

```
In `decision-api/src/main.py`, locate the `_run_pipeline()` function.

After the call to `explain_prediction()` and before `log_decision()`, add the
following:

1. Import (top of file, lazy-safe):
   ```python
   from explainability.nlg_summarizer import generate_decision_summary, NLGSummary
   ```

2. After `explanation_result` is obtained, call:
   ```python
   nlg_summary: NLGSummary = generate_decision_summary(
       explanation=explanation_result,
       decision=final_decision,           # existing variable
       application_id=application_id,    # existing variable
       applicant_name=payload.get("applicant_name", "Applicant"),
       model_version=model_version,       # existing variable or "unknown"
       creditor_name=os.getenv("CREDITOR_NAME", "Creditor"),
       creditor_phone=os.getenv("CREDITOR_PHONE", "1-800-000-0000"),
   )
   ```

3. Add `nlg_summary` fields to the pipeline result dict returned by `_run_pipeline()`:
   ```python
   result["loan_officer_narrative"] = nlg_summary.loan_officer_narrative
   result["applicant_narrative"]    = nlg_summary.applicant_narrative
   result["adverse_action_body"]    = nlg_summary.adverse_action_body
   result["adverse_action_reasons"] = nlg_summary.top_reasons
   ```
   These fields must be present whether or not the LLM call succeeded (because
   TEMPLATE_FALLBACK guarantees non-empty strings).

4. Pass `adverse_action_body` and `adverse_action_reasons` into `log_decision()`
   if that function's signature accepts extra kwargs; otherwise store them in the
   existing `notes` or `metadata` JSON field.

5. The HTTP response from `POST /v1/decisions` must include a new
   `"explanation_narrative"` key containing `result["loan_officer_narrative"]`
   so loan officer UIs receive the summary in-band.

6. Add integration test `tests/test_nlg_integration.py`:
   - Mock `openai.OpenAI` to raise `ImportError`.
   - Call `_run_pipeline()` with a synthetic payload.
   - Assert `result["loan_officer_narrative"]` is non-empty string.
   - Assert `result["adverse_action_reasons"]` is a list of length >= 1 for a
     REJECT decision.
```

---

## GAP-07 — Model Drift Alerts Wired to AlertRouter

**Goal**: When PSI > 0.20, KS < 0.30, or AUROC < 0.70 is detected, fire within 5 minutes via `AlertRouter` to the model risk officer channel.

**Effort**: ~1 day

---

### Prompt G7-A — Add `send_alert` public method to `AlertRouter`

```
In `monitoring/alert_router.py`, locate the `AlertRouter` class.

Add the following synchronous public method directly to the class body
(do NOT use the existing monkey-patch at the bottom of the file — remove that
monkey-patch and replace it with a proper method declaration):

```python
def send_alert(self, severity: str, title: str, body: str) -> AlertRecord:
    """Synchronous convenience wrapper around :meth:`route`.

    Parameters
    ----------
    severity:
        One of ``"CRITICAL"``, ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.
    title:
        Short alert title (used as email subject / Slack header).
    body:
        Full alert body text.

    Returns
    -------
    AlertRecord
        Record of which channels the alert was dispatched to.
    """
    return self.route(severity=severity, subject=title, body=body)
```

Also remove the `async def _send_alert` monkey-patch block at the bottom of the
file (lines beginning with `async def _send_alert` and `AlertRouter.send_alert
= _send_alert`) — the new class method replaces it.

After the change, run `python -c "from monitoring.alert_router import AlertRouter; r = AlertRouter(); r.send_alert('LOW', 'test', 'body')"` to confirm no import errors.
```

---

### Prompt G7-B — Wire drift thresholds to `AlertRouter` in `cc_pd_monitor.py`

```
In `monitoring/cc_pd_monitor.py`, locate the `run_monitor()` function (or the
equivalent top-level function that builds the `alerts` list and currently only
calls `log.warning(a)` for each alert).

Make the following changes:

1. Add import at the top of the file:
   ```python
   from monitoring.alert_router import DEFAULT_ALERT_ROUTER, AlertRouter
   ```

2. Change the `run_monitor()` function signature to accept an optional router:
   ```python
   def run_monitor(
       ...,                          # existing parameters unchanged
       alert_router: AlertRouter | None = None,
   ) -> dict:
   ```
   Inside the function, resolve the router:
   ```python
   router = alert_router or DEFAULT_ALERT_ROUTER
   ```

3. Replace the existing alert dispatch block:
   ```python
   if alerts:
       for a in alerts:
           log.warning(a)
   else:
       log.info("  All checks PASSED — no alerts.")
   ```
   With:
   ```python
   if alerts:
       for a in alerts:
           log.warning(a)
           severity = "CRITICAL" if a.startswith("CRITICAL") else "HIGH"
           router.send_alert(
               severity=severity,
               title=f"Model Drift Detected — {severity}",
               body=a,
           )
   else:
       log.info("  All checks PASSED — no alerts.")
   ```

4. Define explicit threshold constants at module level (before `run_monitor()`):
   ```python
   PSI_CRITICAL_THRESHOLD   = 0.20   # PRD §4.8
   AUROC_MIN_THRESHOLD      = 0.70   # PRD §4.8
   KS_MIN_THRESHOLD         = 0.30   # PRD §4.8
   DR_MAX_THRESHOLD         = 0.12   # PRD §4.8
   ```
   Replace any hard-coded float literals in the alert condition block with these
   constants so they can be overridden in tests.

5. Add unit test `tests/test_monitor_alert_routing.py`:
   - Instantiate a `LogOnlyChannel` and an `AlertRouter` wired to it.
   - Call `run_monitor()` with synthetic data engineered to produce PSI > 0.20.
   - Assert `router.send_alert` was called (use `unittest.mock.patch` or a
     subclassed `AlertRouter` that records calls).
   - Assert the returned `alerts` list is non-empty.
   - Assert no exception is raised when `alert_router=None` (uses DEFAULT).
```

---

## GAP-08 — Feature Lineage Queryable via API

**Goal**: Persist OpenLineage events to a local SQLite store and expose a `GET /v1/lineage/{run_id}` endpoint returning the lineage graph for a given run ID.

**Effort**: ~2 days

---

### Prompt G8-A — Add `LineageStore` to `feature_pipeline/lineage.py`

```
Extend `feature_pipeline/lineage.py` with a persistent `LineageStore` class.

Add the following after the existing `LineageClient` class:

```python
class LineageStore:
    """SQLite-backed store for OpenLineage events.

    Persists every event emitted by :class:`LineageClient` so they can be
    queried by run_id, job name, or dataset namespace after the fact.

    Schema
    ------
    Table ``lineage_events``:
      id            INTEGER PRIMARY KEY AUTOINCREMENT
      run_id        TEXT NOT NULL
      job_namespace TEXT NOT NULL
      job_name      TEXT NOT NULL
      event_type    TEXT NOT NULL          -- START / COMPLETE / FAIL
      event_time    TEXT NOT NULL          -- ISO-8601 UTC
      inputs_json   TEXT NOT NULL          -- JSON array of DatasetRef dicts
      outputs_json  TEXT NOT NULL          -- JSON array of DatasetRef dicts
      run_facets_json TEXT                 -- optional JSON
      created_at    TEXT NOT NULL          -- insert time ISO-8601 UTC
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS lineage_events (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id           TEXT    NOT NULL,
            job_namespace    TEXT    NOT NULL,
            job_name         TEXT    NOT NULL,
            event_type       TEXT    NOT NULL,
            event_time       TEXT    NOT NULL,
            inputs_json      TEXT    NOT NULL DEFAULT '[]',
            outputs_json     TEXT    NOT NULL DEFAULT '[]',
            run_facets_json  TEXT,
            created_at       TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_lineage_run_id
            ON lineage_events (run_id);
        CREATE INDEX IF NOT EXISTS ix_lineage_job_name
            ON lineage_events (job_name);
    """

    def __init__(self, db_path: str = "./feature_pipeline/lineage.db") -> None:
        import sqlite3  # stdlib
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(self._CREATE_TABLE)
        self._conn.commit()

    def record(
        self,
        run_id: str,
        job_namespace: str,
        job_name: str,
        event_type: str,
        event_time: str,
        inputs: list[dict],
        outputs: list[dict],
        run_facets: dict | None = None,
    ) -> None:
        """Persist one OpenLineage run event."""
        import json, sqlite3
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO lineage_events
               (run_id, job_namespace, job_name, event_type, event_time,
                inputs_json, outputs_json, run_facets_json, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id, job_namespace, job_name, event_type, event_time,
                json.dumps(inputs), json.dumps(outputs),
                json.dumps(run_facets) if run_facets else None,
                now,
            ),
        )
        self._conn.commit()

    def get_by_run_id(self, run_id: str) -> list[dict]:
        """Return all events for *run_id*, ordered by event_time ASC."""
        import json
        rows = self._conn.execute(
            "SELECT * FROM lineage_events WHERE run_id = ? ORDER BY event_time ASC",
            (run_id,),
        ).fetchall()
        cols = [d[0] for d in self._conn.execute(
            "SELECT * FROM lineage_events LIMIT 0"
        ).description or []]
        # Re-fetch column names properly:
        cur = self._conn.execute(
            "SELECT id,run_id,job_namespace,job_name,event_type,event_time,"
            "inputs_json,outputs_json,run_facets_json,created_at "
            "FROM lineage_events WHERE run_id = ? ORDER BY event_time ASC",
            (run_id,),
        )
        col_names = [d[0] for d in cur.description]
        result = []
        for row in cur.fetchall():
            rec = dict(zip(col_names, row))
            rec["inputs"]  = json.loads(rec.pop("inputs_json"))
            rec["outputs"] = json.loads(rec.pop("outputs_json"))
            rf = rec.pop("run_facets_json")
            rec["run_facets"] = json.loads(rf) if rf else {}
            result.append(rec)
        return result

    def get_by_job(self, job_name: str, limit: int = 100) -> list[dict]:
        """Return the most recent *limit* events for *job_name*."""
        import json
        cur = self._conn.execute(
            "SELECT id,run_id,job_namespace,job_name,event_type,event_time,"
            "inputs_json,outputs_json,run_facets_json,created_at "
            "FROM lineage_events WHERE job_name = ? ORDER BY event_time DESC LIMIT ?",
            (job_name, limit),
        )
        col_names = [d[0] for d in cur.description]
        result = []
        for row in cur.fetchall():
            rec = dict(zip(col_names, row))
            rec["inputs"]  = json.loads(rec.pop("inputs_json"))
            rec["outputs"] = json.loads(rec.pop("outputs_json"))
            rf = rec.pop("run_facets_json")
            rec["run_facets"] = json.loads(rf) if rf else {}
            result.append(rec)
        return result

    def close(self) -> None:
        self._conn.close()
```

Then modify `LineageClient.emit_dataset_event()`:
- Add an optional `store: LineageStore | None = None` parameter to `__init__`.
- After `self._send(event)` succeeds (or after the try/except), if `self._store`
  is set, call `self._store.record(...)` with the event fields.
- This makes persistence opt-in with zero impact on existing callers.

Wire a default file-backed store when the env var
`LINEAGE_STORE_PATH` is set:
```python
DEFAULT_LINEAGE_STORE: LineageStore | None = (
    LineageStore(os.environ["LINEAGE_STORE_PATH"])
    if "LINEAGE_STORE_PATH" in os.environ
    else None
)
```
```

---

### Prompt G8-B — Expose `GET /v1/lineage/{run_id}` in the Decision API

```
In `decision-api/src/main.py`, add a new read-only endpoint:

```python
@app.get("/v1/lineage/{run_id}")
async def get_lineage(
    run_id: str,
    token_data: dict = Depends(verify_bearer),
) -> JSONResponse:
    """Return all OpenLineage events for *run_id*.

    Query parameters
    ----------------
    None. The run_id is embedded in the URL.

    Response schema
    ---------------
    {
      "run_id": "...",
      "tenant_id": "...",
      "event_count": 3,
      "events": [ { ...OpenLineage event dict... }, ... ]
    }

    Errors
    ------
    404 — run_id not found in the lineage store
    503 — lineage store not configured (LINEAGE_STORE_PATH not set)
    """
    import os
    from feature_pipeline.lineage import LineageStore

    store_path = os.getenv("LINEAGE_STORE_PATH")
    if not store_path:
        return JSONResponse(
            status_code=503,
            content={"error": "Lineage store not configured. Set LINEAGE_STORE_PATH."},
        )

    store = LineageStore(store_path)
    events = store.get_by_run_id(run_id)
    store.close()

    if not events:
        return JSONResponse(
            status_code=404,
            content={"error": f"No lineage events found for run_id={run_id}"},
        )

    return JSONResponse(content={
        "run_id": run_id,
        "tenant_id": token_data.get("tenant_id"),
        "event_count": len(events),
        "events": events,
    })
```

Also add `GET /v1/lineage/job/{job_name}` for listing recent runs by job name,
following the same pattern (uses `store.get_by_job(job_name, limit=100)`).

Add an integration test `tests/test_lineage_api.py`:
- Create a temp `LineageStore`, insert two synthetic events for `run_id="run-001"`.
- Call `GET /v1/lineage/run-001` via FastAPI `TestClient`.
- Assert `event_count == 2` and `events[0]["run_id"] == "run-001"`.
- Assert 404 for `run_id="nonexistent"`.
- Assert 503 when `LINEAGE_STORE_PATH` env var is unset.
```

---

## GAP-09 — SR 11-7 Model Documentation Auto-Generated on Champion Promotion

**Goal**: When a challenger model is promoted to champion, automatically call `generate_mdr()` and attach the resulting document path to the audit record.

**Effort**: ~1 day

---

### Prompt G9-A — Add `promote_champion()` to `ChampionChallengerRouter`

```
In `decisioning/champion_challenger.py`, locate `ChampionChallengerRouter`.

Add the following method to the class:

```python
def promote_champion(
    self,
    new_champion_run_id: str,
    model_doc_config: "ModelDocumentationConfig | None" = None,
    docs_output_dir: str = "docs/mdr",
    audit_logger=None,
) -> dict:
    """Promote the challenger model identified by *new_champion_run_id* to champion.

    Steps
    -----
    1. Validate *new_champion_run_id* exists in the MLflow registry (or model
       artefact store).  If `mlflow` is not available, skip validation with a
       warning.
    2. Call `generate_mdr(run_id=new_champion_run_id, config=model_doc_config)`
       from `compliance.generate_model_doc` to produce an SR 11-7–compliant
       model documentation record.  If `model_doc_config` is None, build a
       minimal config using:
       `ModelDocumentationConfig(model_name="cc_pd_model", version=new_champion_run_id[:8], ...)`
    3. Validate the MDR via `validate_mdr_completeness(mdr)` — log a WARNING if
       incomplete but do not block promotion.
    4. Write the MDR markdown file to `{docs_output_dir}/mdr_{new_champion_run_id[:8]}.md`.
       Create the directory if it does not exist.
    5. Write the MDR JSON file to the same directory as `mdr_{new_champion_run_id[:8]}.json`.
    6. Update the internal champion/challenger store so `new_champion_run_id` is
       the active champion (update any SQLite config table your implementation
       uses).
    7. Build a promotion audit record dict:
       ```python
       promotion_record = {
           "event": "CHAMPION_PROMOTED",
           "promoted_run_id": new_champion_run_id,
           "mdr_md_path": str(md_path),
           "mdr_json_path": str(json_path),
           "mdr_completeness_passed": completeness_ok,
           "promoted_at": datetime.utcnow().isoformat() + "Z",
       }
       ```
    8. If `audit_logger` is provided and has a `log_decision()` or `log_portfolio_action()`
       method, call it with the promotion record.
    9. Return `promotion_record`.

    Parameters
    ----------
    new_champion_run_id:
        MLflow run ID (or any unique model identifier) of the model to promote.
    model_doc_config:
        Optional pre-built `ModelDocumentationConfig`. If None, a minimal config
        is constructed automatically.
    docs_output_dir:
        Directory path (relative to project root) where MDR files are written.
    audit_logger:
        Optional audit logger instance (`audit.logger.AuditLogger` or compatible).

    Returns
    -------
    dict
        Promotion audit record.
    """
```

Implementation notes:
- All imports from `compliance.generate_model_doc` must be inside the method body
  (lazy import) to avoid circular imports.
- Wrap the entire MLflow interaction in try/except — promotion must not fail if
  MLflow is unreachable.
- The MDR write step must also be wrapped in try/except — a disk write failure
  should log ERROR and attach `"mdr_write_error"` to the promotion record rather
  than raising.

Add the following unit tests in `tests/test_champion_promotion.py`:
1. Test `promote_champion()` with `mlflow` not installed — assert it completes
   without raising and returns a dict with key `"promoted_run_id"`.
2. Test that the MDR markdown file is written to `docs_output_dir` (use a tmp path).
3. Test that `audit_logger.log_portfolio_action` is called when provided
   (use `unittest.mock.MagicMock`).
4. Test that a missing `generate_mdr()` (mock to raise) still returns a
   promotion record with `"mdr_write_error"` key.
```

---

### Prompt G9-B — Register promotion endpoint in Decision API

```
In `decision-api/src/main.py`, add a new endpoint:

```python
@app.post("/v1/models/{run_id}/promote")
async def promote_model(
    run_id: str,
    body: dict = Body(default={}),
    token_data: dict = Depends(verify_bearer),
) -> JSONResponse:
    """Promote a challenger model to champion and auto-generate its SR 11-7 MDR.

    Required JWT claims
    -------------------
    role: "model_risk_officer" or "admin"

    Request body (all optional)
    ---------------------------
    {
      "model_name":          "cc_pd_model",
      "use_case":            "Credit Card PD",
      "owner":               "Risk Analytics",
      "reviewer":            "Model Risk",
      "approver":            "CRO",
      "intended_population": "US credit card applicants",
      "docs_output_dir":     "docs/mdr"
    }

    Response
    --------
    {
      "status": "promoted",
      "promotion_record": { ...dict returned by promote_champion()... }
    }
    """
    from decisioning.champion_challenger import ChampionChallengerRouter
    from compliance.generate_model_doc import ModelDocumentationConfig

    # RBAC: only model_risk_officer or admin may promote
    role = token_data.get("role", "")
    if role not in {"model_risk_officer", "admin"}:
        return JSONResponse(status_code=403, content={"error": "Insufficient role for model promotion."})

    config = ModelDocumentationConfig(
        model_name=body.get("model_name", "cc_pd_model"),
        version=run_id[:8],
        use_case=body.get("use_case", "Credit Card PD"),
        owner=body.get("owner", "Risk Analytics"),
        reviewer=body.get("reviewer", "Model Risk Management"),
        approver=body.get("approver", "Chief Risk Officer"),
        intended_population=body.get("intended_population", "US credit card applicants"),
    )

    router = ChampionChallengerRouter(
        champion_run_id=run_id,
        challenger_run_id=run_id,  # placeholder; actual routing state loaded from DB
    )

    record = router.promote_champion(
        new_champion_run_id=run_id,
        model_doc_config=config,
        docs_output_dir=body.get("docs_output_dir", "docs/mdr"),
    )

    return JSONResponse(content={"status": "promoted", "promotion_record": record})
```

Add an integration test `tests/test_promotion_endpoint.py`:
- POST to `/v1/models/abc123run/promote` with a valid admin token.
- Assert response status 200 and `promotion_record["promoted_run_id"] == "abc123run"`.
- POST with a non-admin token — assert 403.
- Assert the MDR file is written under a temp `docs_output_dir`.
```

---

## Execution Order & Dependencies

```
G6-A  ──────────────────────────► G6-B
                                        │
G7-A  ──────────────────────────► G7-B  │
                                        │──► Integration + smoke test suite
G8-A  ──────────────────────────► G8-B  │
                                        │
G9-A  ──────────────────────────► G9-B  │
```

Each `-A` prompt is independent and safe to implement in parallel.
Each `-B` prompt depends only on its corresponding `-A` being complete.

**Recommended sprint order**:
1. G7-A + G7-B (half day — lowest risk, highest monitoring ROI)
2. G9-A + G9-B (1 day — hooks into existing `generate_mdr`, minimal surface)
3. G6-A + G6-B (2 days — largest surface, but isolated to new module)
4. G8-A + G8-B (1.5 days — new store + API endpoint)

---

## Acceptance Criteria

| Gap | Criterion | Test |
|-----|-----------|------|
| G06 | Every REJECT decision response contains non-empty `loan_officer_narrative` | `tests/test_nlg_integration.py` |
| G06 | REJECT response contains `adverse_action_reasons` list (≥1 ECOA code) | `tests/test_nlg_integration.py` |
| G06 | APPROVE response has empty `adverse_action_body` | `tests/test_nlg_integration.py` |
| G06 | Works with `OPENAI_API_KEY` unset (template fallback) | `tests/test_nlg_integration.py` |
| G07 | PSI > 0.20 → `AlertRouter.send_alert("CRITICAL", ...)` called | `tests/test_monitor_alert_routing.py` |
| G07 | Alert fires within 5 minutes of `run_monitor()` invocation | Smoke test: wall-clock assert |
| G07 | `DEFAULT_ALERT_ROUTER` used when `alert_router=None` | `tests/test_monitor_alert_routing.py` |
| G08 | `GET /v1/lineage/{run_id}` returns 200 with events when store has data | `tests/test_lineage_api.py` |
| G08 | Returns 404 for unknown run_id | `tests/test_lineage_api.py` |
| G08 | Returns 503 when `LINEAGE_STORE_PATH` unset | `tests/test_lineage_api.py` |
| G09 | `promote_champion()` writes MDR `.md` and `.json` files | `tests/test_champion_promotion.py` |
| G09 | Promotion completes without raising when MLflow absent | `tests/test_champion_promotion.py` |
| G09 | `POST /v1/models/{run_id}/promote` returns 403 for non-admin | `tests/test_promotion_endpoint.py` |
| G09 | Promotion audit record attached to `log_portfolio_action()` call | `tests/test_champion_promotion.py` |

---

## Environment Variables Required

| Variable | Gap | Purpose |
|----------|-----|---------|
| `OPENAI_API_KEY` | G06 | LLM calls for narrative generation (optional — falls back gracefully) |
| `OPENAI_ORG_ID` | G06 | Optional org scoping |
| `CREDITOR_NAME` | G06 | Injected into adverse action notice body |
| `CREDITOR_PHONE` | G06 | Injected into adverse action notice body |
| `ALERT_SLACK_WEBHOOK_URL` | G07 | Slack channel for drift alerts (already documented in `.env.example`) |
| `ALERT_EMAIL_TO` | G07 | Email recipient for CRITICAL drift alerts |
| `LINEAGE_STORE_PATH` | G08 | Absolute path to SQLite lineage DB (e.g. `/data/lineage.db`) |

---

*For P1 and P2 (GAP-01 through GAP-05) gap closure, see [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P1_P2.md) and [`docs/IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_GAPS_3_4_5.md`](IMPLEMENTATION_PLAN_GAP_CLOSURE_P2_GAPS_3_4_5.md)*
