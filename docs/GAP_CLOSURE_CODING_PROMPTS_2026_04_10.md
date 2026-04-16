# Gap Closure — Coding Prompts
**Derived from**: `docs/GOVERNANCE_PRD_GAP_ANALYSIS_2026_04_10.md`
**Platform**: `credit-risk-platform`
**Date**: 2026-04-10
**Sprints**: 1–5 + Backlog

Each prompt is self-contained. Execute them in the sprint order shown below. All paths are relative to the repo root.

---

## Sprint 1 — Override Detection + Prohibited Variables (3–5 days)

---

### PROMPT-S1-A: Override Detection Engine (GAP-02)

**Goal**: Every use of `policy_overrides` in the decision engine must be justified, approved, and appended to an immutable, hash-chained audit log. Individual decision-level override rate must become a queryable metric.

**Files to create**:
- `audit/override_log.py`

**Files to modify**:
- `decision_engine/engine.py`
- `compliance/rbac.py`
- `audit/logger.py`

---

#### Step 1 — Create `audit/override_log.py`

Create a new module `audit/override_log.py`. It must:

1. Define a dataclass `PolicyOverrideRecord`:
   ```python
   @dataclass
   class PolicyOverrideRecord:
       override_id: str          # UUID
       decision_id: str          # application_id of the affected decision
       tenant_id: str
       override_type: str        # e.g. "pd_threshold_low" | "pd_threshold"
       original_value: float
       override_value: float
       justification: str        # free text, min 10 chars
       submitted_by: str         # actor email
       approved_by: str          # second approver email, must != submitted_by
       approved_at: str          # ISO-8601 UTC
       record_hash: str          # sha256 of all fields + previous_hash
       previous_hash: str        # hash of the prior record for this tenant (or "GENESIS")
   ```

2. Define `OVERRIDE_LOG_DDL`:
   ```sql
   CREATE TABLE IF NOT EXISTS policy_overrides_log (
       override_id    TEXT PRIMARY KEY,
       decision_id    TEXT NOT NULL,
       tenant_id      TEXT NOT NULL,
       override_type  TEXT NOT NULL,
       original_value REAL NOT NULL,
       override_value REAL NOT NULL,
       justification  TEXT NOT NULL,
       submitted_by   TEXT NOT NULL,
       approved_by    TEXT NOT NULL,
       approved_at    TEXT NOT NULL,
       record_hash    TEXT NOT NULL,
       previous_hash  TEXT NOT NULL
   );
   ```
   The table is append-only — no UPDATE or DELETE ever.

3. Implement `async def log_override(record: PolicyOverrideRecord, db_url: str) -> str`:
   - Compute `previous_hash` by fetching the `record_hash` of the most-recent row for this `tenant_id`, defaulting to `"GENESIS"`.
   - Compute `record_hash` as `sha256(json.dumps(dataclasses.asdict(record), sort_keys=True).encode())`.
   - Insert into `policy_overrides_log` and return `override_id`.
   - Use the same `sqlalchemy.ext.asyncio` engine pattern as `audit/logger.py`.

4. Implement `async def get_override_rate(tenant_id: str, from_date: str, to_date: str, db_url: str) -> float`:
   - Returns `(count of override rows) / (total audit_log rows in the same period)` for the tenant. Returns `0.0` when denominator is zero.

5. Add `async def verify_override_chain(tenant_id: str, db_url: str) -> bool` that re-walks the `previous_hash` chain for the tenant and returns `True` if every link is valid.

---

#### Step 2 — Update `compliance/rbac.py`

Add a new entry to `FOUR_EYES_RULES`:
```python
"policy_override": {
    "min_approver_role": "risk_analyst",
    "submitter_cannot_approve": True,
    "description": "Policy threshold override requires a second approver",
}
```

Add a helper `validate_override_submission(submitted_by: str, approved_by: str) -> None` that:
- Calls `enforce_four_eyes("policy_override", actor=submitted_by, approver=approved_by)`.
- Raises `SeparationOfDutiesViolation` if `submitted_by == approved_by`.
- Raises `ValueError` if `justification` is fewer than 10 characters.

---

#### Step 3 — Update `decision_engine/engine.py`

Change the signature of `make_decision()`:
```python
def make_decision(
    request: DecisionRequest,
    policy_overrides: Optional[Dict[str, Any]] = None,
    # NEW:
    override_submitted_by: Optional[str] = None,
    override_approved_by: Optional[str] = None,
    override_justification: Optional[str] = None,
) -> DecisionResult:
```

Inside `make_decision()`, immediately after `overrides = policy_overrides or {}`:
- If `overrides` is non-empty:
  - If any of `override_submitted_by`, `override_approved_by`, `override_justification` is `None` or `override_justification` has fewer than 10 characters, raise `ValueError("policy_overrides require override_submitted_by, override_approved_by, and override_justification (min 10 chars)")`.
  - Call `validate_override_submission(override_submitted_by, override_approved_by)`.
  - For each key `k` in `overrides`, build a `PolicyOverrideRecord` and collect them in a list attached to the returned `DecisionResult`.

Add an `override_records: List["PolicyOverrideRecord"]` field (defaulting to `[]`) to `DecisionResult`.

---

#### Step 4 — Persist override records in `decision-api/src/main.py`

In `_run_pipeline()`, after `audit_log_id = await log_decision(...)`:
```python
for ov_rec in decision_result.override_records:
    from audit.override_log import log_override
    await log_override(ov_rec, DB_URL)
```

---

#### Step 5 — Tests

Create `audit/tests/test_override_log.py` with:
- `test_chain_genesis` — first record has `previous_hash == "GENESIS"`.
- `test_chain_links` — second record's `previous_hash` equals the first record's `record_hash`.
- `test_verify_chain_valid` — `verify_override_chain` returns `True` on a valid chain.
- `test_verify_chain_tampered` — manually corrupt one `record_hash`; verify returns `False`.
- `test_four_eyes_enforced` — `submitted_by == approved_by` raises `SeparationOfDutiesViolation`.
- `test_override_rate` — inserts 3 overrides for 10 total decisions, asserts rate == 0.3.

**Acceptance criteria**:
- `make_decision(req, policy_overrides={"pd_threshold_low": 0.03})` with no justification raises `ValueError`.
- `make_decision(req, policy_overrides={"pd_threshold_low": 0.03}, override_submitted_by="alice@co", override_approved_by="alice@co", override_justification="test")` raises `SeparationOfDutiesViolation`.
- A valid call logs a row to `policy_overrides_log` with a sha256 hash that verifies.
- `get_override_rate` returns the correct fraction.

---

### PROMPT-S1-B: Prohibited Variables Registry (GAP-08)

**Goal**: Block any request that passes a protected-class or proxy variable into the decision engine. Log violations as compliance events.

**Files to create**:
- `compliance/prohibited_variables.py`

**Files to modify**:
- `compliance/engine.py`
- `decision-api/src/main.py`

---

#### Step 1 — Create `compliance/prohibited_variables.py`

```python
"""
compliance/prohibited_variables.py
=====================================
Registry of ECOA / Fair Housing Act / FCRA prohibited variables and
their known proxy features.

Public API
----------
>>> from compliance.prohibited_variables import check_for_prohibited_variables
>>> check_for_prohibited_variables({"race": "white", "credit_score": 720})
# raises ProhibitedVariableViolation
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Set


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

#: Direct prohibited basis variables (ECOA §202.2(z), Fair Housing Act)
PROHIBITED_VARIABLES: FrozenSet[str] = frozenset({
    "race", "color", "religion", "national_origin", "sex", "gender",
    "marital_status", "age", "familial_status", "disability",
    "immigration_status", "citizenship_status", "sexual_orientation",
    "gender_identity", "receipt_of_public_assistance",
    # common variants / misspellings
    "ethnicity", "ancestry", "country_of_birth", "birthplace",
    "religion_type", "sex_type",
})

#: Proxy variables that correlate with protected class at census-tract level
PROXY_VARIABLE_MAP: Dict[str, str] = {
    "zip_code":              "national_origin / race (redlining proxy)",
    "census_tract":          "race / national_origin",
    "neighborhood_code":     "race / national_origin",
    "last_name_score":       "national_origin / race (surname proxy)",
    "language":              "national_origin",
    "maiden_name":           "sex / marital_status",
    "social_club_membership":"religion / national_origin",
}


@dataclass
class ProhibitedVariableViolation(ValueError):
    """Raised when a prohibited or proxy variable is found in the feature set."""
    variable: str
    basis: str  # which protected class it maps to

    def __str__(self) -> str:
        return (
            f"Prohibited variable '{self.variable}' detected "
            f"(protected basis: {self.basis}). "
            "Remove this feature before submitting to the decision engine."
        )


def check_for_prohibited_variables(features: Dict) -> None:
    """Raise ProhibitedVariableViolation on the first prohibited or proxy
    feature key found in *features*.  Keys are compared case-insensitively.

    Parameters
    ----------
    features : dict
        Feature dictionary (or any mapping whose keys are feature names).

    Raises
    ------
    ProhibitedVariableViolation
    """
    lowered = {k.lower(): k for k in features}
    for key_lower, key_orig in lowered.items():
        if key_lower in PROHIBITED_VARIABLES:
            raise ProhibitedVariableViolation(
                variable=key_orig,
                basis=key_lower,
            )
        if key_lower in PROXY_VARIABLE_MAP:
            raise ProhibitedVariableViolation(
                variable=key_orig,
                basis=PROXY_VARIABLE_MAP[key_lower],
            )
```

---

#### Step 2 — Add gate to `compliance/engine.py`

Inside `ComplianceEngine.gate()`, as the **first** check before any existing compliance rule:
```python
# §6.2 — Prohibited variables gate
try:
    from compliance.prohibited_variables import check_for_prohibited_variables
    check_for_prohibited_variables(input_features or {})
except ProhibitedVariableViolation as pv:
    result.passed = False
    result.flags.append(ComplianceFlag(
        rule_code="PV001",
        severity="BLOCK",
        message=str(pv),
        field=pv.variable,
    ))
    result.override = "DECLINE"
    return result
```

(`input_features` is a new `Optional[Dict]` parameter — add it to the `gate()` signature.)

---

#### Step 3 — Wire into request pipeline in `decision-api/src/main.py`

In `_run_pipeline()`, after `features_df = _build_feature_df(app_req)` and before the fraud model call:
```python
# GAP-08: Prohibited variables check
from compliance.prohibited_variables import check_for_prohibited_variables, ProhibitedVariableViolation
try:
    check_for_prohibited_variables(features_df.iloc[0].to_dict())
except ProhibitedVariableViolation as pv:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Prohibited variable in feature set: {pv}",
    )
```

---

#### Step 4 — Tests

Create `compliance/tests/test_prohibited_variables.py`:
- `test_direct_prohibited_variable` — `{"race": "white"}` raises `ProhibitedVariableViolation`.
- `test_proxy_variable` — `{"zip_code": "90210"}` raises `ProhibitedVariableViolation`.
- `test_case_insensitive` — `{"RACE": "hispanic"}` raises `ProhibitedVariableViolation`.
- `test_clean_features` — standard feature dict (credit_score, dti, etc.) does not raise.
- `test_compliance_gate_blocks_on_prohibited` — `ComplianceEngine().gate(input_features={"gender": "female"})` returns `passed=False` with `rule_code="PV001"`.

**Acceptance criteria**:
- Any request to `POST /v1/decisions` that includes a prohibited feature key returns HTTP 422 with the variable name in the error detail.
- The check is deterministic — same features always produce the same result (no network calls).

---

## Sprint 2 — Exam Packet + Command Center (5–7 days)

---

### PROMPT-S2-A: Exam Packet Builder — Wire Live Components (GAP-01 + partial GAP-07)

**Goal**: Replace all `status="stub"` components in `compliance/exam_packet_builder.py` with real data, add PDF export, add a `CommitteeApproval` entity, and expose a POST API endpoint.

**Files to create**:
- `compliance/committee_approval_store.py`

**Files to modify**:
- `compliance/exam_packet_builder.py`
- `compliance/adverse_action_pdf.py` (extend for full packet)
- `decision-api/src/main.py` (add `POST /v1/audit/generate-package`)

---

#### Step 1 — Create `compliance/committee_approval_store.py`

Implement a lightweight SQLite store for committee approvals:

```python
@dataclass
class CommitteeApproval:
    approval_id: str           # UUID
    tenant_id: str
    subject: str               # e.g. "Credit Policy v3.2 — Q1 2026 Review"
    approval_type: str         # "POLICY_CHANGE" | "MODEL_APPROVAL" | "LIMIT_INCREASE"
    submitted_by: str
    approved_by: str
    approved_at: str           # ISO-8601 UTC
    notes: str
    effective_date: str        # YYYY-MM-DD
```

DDL table: `committee_approvals` with the above columns plus `created_at TEXT NOT NULL`.

Implement:
- `async def save_approval(approval: CommitteeApproval, db_url: str) -> str`
- `async def list_approvals(tenant_id: str, from_date: str, to_date: str, db_url: str) -> List[CommitteeApproval]`

---

#### Step 2 — Implement all stub components in `exam_packet_builder.py`

Replace the `else` branch in `build_exam_packet()` with per-component async builder functions. Implement each one:

**`build_model_documentation_component(spec, db_url)`**:
- Instantiate `ModelDocumentationConfig` with defaults and call `generate_mdr()` from `compliance/generate_model_doc.py`.
- Return `ExamPacketComponent(name="model_documentation", status="complete", data=dataclasses.asdict(mdr))`.

**`build_policy_snapshots_component(spec, db_url)`**:
- Create `PolicyVersionStore()` and call `store.get_as_of(datetime.fromisoformat(spec.to_date))` to get the policy active at the end of the exam period.
- Also call `store.list_versions(limit=20)` for the change log.
- Return `ExamPacketComponent(name="policy_snapshots", status="complete", data={...})`.

**`build_decision_samples_component(spec, db_url)`**:
- Call `await get_audit_records_by_period(tenant_id, from_date, to_date, db_url, limit=50)` from `audit/logger.py`.
- For each record, if an `nlg_summary` is stored in the audit log, include it; otherwise call `generate_decision_summary()` on the stored features.
- Return `ExamPacketComponent(name="decision_samples", status="complete", data={"sample_count": N, "samples": [...]})`.

**`build_fair_lending_component(spec, db_url)`**:
- Load audit records for the period and reconstruct a decisions DataFrame.
- Call `analyze_fair_lending(decisions_df, proxy_col="bisg_minority_proxy")` from `monitoring/fair_lending.py`.
- Return `ExamPacketComponent(name="fair_lending_analysis", status="complete", data=dataclasses.asdict(report))`.

**`build_committee_approvals_component(spec, db_url)`**:
- Call `await list_approvals(spec.tenant_id, spec.from_date, spec.to_date, db_url)`.
- Return `ExamPacketComponent(name="committee_approvals", status="complete", data={"count": N, "approvals": [...]})`.

**`build_data_lineage_component(spec, db_url)`** (placeholder until GAP-03 is implemented):
- Return `ExamPacketComponent(name="data_lineage", status="pending", data={"message": "Data lineage module not yet implemented — see GAP-03"})`. Use `"pending"` (not `"stub"`) so the packet can still be exported.

---

#### Step 3 — Add PDF rendering for the full packet

In `compliance/adverse_action_pdf.py` (or a new `compliance/exam_packet_pdf.py`):

Implement `render_exam_packet_pdf(packet: ExamPacket) -> bytes` using `reportlab`:
- Page 1: Cover sheet (packet_id, tenant, period, template, generated_at).
- One section per `ExamPacketComponent` with a heading and JSON-formatted data (multi-line wrapped).
- Components with `status="complete"` render their data. Components with `status="pending"` render a notice block. Components with `status="error"` render a red-bordered error block.
- Return the PDF bytes.

---

#### Step 4 — Expose `POST /v1/audit/generate-package` in `decision-api/src/main.py`

```python
class GeneratePackageRequest(BaseModel):
    from_date: str  # YYYY-MM-DD
    to_date: str    # YYYY-MM-DD
    components: List[str] = ["adverse_actions", "model_documentation",
                              "policy_snapshots", "decision_samples",
                              "fair_lending_analysis", "committee_approvals",
                              "data_lineage"]
    format: Literal["json", "pdf_zip"] = "json"
    template: str = "OCC_EXAMINATION"

@app.post("/v1/audit/generate-package")
async def generate_audit_package(
    req: GeneratePackageRequest,
    payload: Dict = Depends(verify_bearer),
):
    tenant_id = payload["tenant_id"]
    spec = ExamPacketSpec(
        tenant_id=tenant_id,
        from_date=req.from_date,
        to_date=req.to_date,
        components=req.components,
        format=req.format,
        template=req.template,
    )
    packet = await build_exam_packet(spec, DB_URL)
    if req.format == "pdf_zip":
        pdf_bytes = render_exam_packet_pdf(packet)
        return Response(content=pdf_bytes, media_type="application/pdf",
                        headers={"Content-Disposition": f"attachment; filename=exam_packet_{packet.packet_id}.pdf"})
    return packet.to_dict()
```

---

#### Step 5 — Tests

Create `compliance/tests/test_exam_packet_builder.py`:
- `test_adverse_actions_component_complete` — existing test.
- `test_model_documentation_component_complete` — asserts `status == "complete"` and `data["model_name"]` is present.
- `test_policy_snapshots_component_complete` — asserts `status == "complete"` and `data["version_id"]` is present.
- `test_committee_approvals_no_data` — when no approvals exist in the period, returns `status="complete"` with `count == 0`.
- `test_full_packet_json` — calls `build_exam_packet` with all components, asserts no component has `status="stub"`.
- `test_generate_package_endpoint` — integration test against the FastAPI test client, asserts HTTP 200 and `packet_id` in response.

**Acceptance criteria**:
- `POST /v1/audit/generate-package` returns HTTP 200 with a `packet_id` and no component has `status="stub"` (may have `status="pending"` for data_lineage until GAP-03 is resolved).
- PDF format returns a non-empty byte stream with `Content-Type: application/pdf`.

---

### PROMPT-S2-B: Compliance Command Center Homepage (GAP-06)

**Goal**: Build the unified compliance command center: a `GET /api/v1/compliance/health` backend endpoint and a `ui/analytics-dashboard/app/compliance/command-center/page.tsx` front-end page.

**Files to create**:
- `ui/analytics-dashboard/app/compliance/command-center/page.tsx`

**Files to modify**:
- `decision-api/src/main.py` (add health endpoint)
- `ui/analytics-dashboard/app/page.tsx` (update `ROLE_HOME`)

---

#### Step 1 — Add `GET /v1/compliance/health` to `decision-api/src/main.py`

```python
@app.get("/v1/compliance/health")
async def compliance_health(payload: Dict = Depends(verify_bearer)):
    """Return the 8-dimension compliance health score for the calling tenant."""
    from compliance.health_score import compute_health_score
    score = compute_health_score()
    return {
        "overall_score": score.overall_score,
        "dimension_scores": score.dimension_scores,
        "failing_dimensions": score.failing_dimensions,
        "computed_at": datetime.utcnow().isoformat() + "Z",
    }
```

---

#### Step 2 — Create `ui/analytics-dashboard/app/compliance/command-center/page.tsx`

Build a Next.js 14 `"use client"` page with the following layout. Use the existing `DashboardShell` and `StatusBadge` component patterns from `ui/analytics-dashboard/components/DashboardShell.tsx`.

**KPI Row** (top, 4 cards):
1. **Audit Readiness Score** — `GET /v1/compliance/health` → `overall_score` (0–100, colour: green ≥80, amber ≥60, red <60, with a ring progress indicator).
2. **Active Compliance Flags** — count of `failing_dimensions` from the same response.
3. **Model Health** — fetch from `GET /v1/analytics/vintage-curves` (latest cohort charge_off_rate; show as green/amber/red).
4. **Fair Lending Alerts** — placeholder count (0) until GAP-12 is resolved; labelled "Historical trend pending".

**Dimension Score Grid** (below KPIs):
- 2-column grid, one card per dimension in `dimension_scores`. Show dimension name, score bar (0–100), and a red badge if it appears in `failing_dimensions`.

**Quick Action Buttons** (right sidebar):
- **Generate Audit Package** — `POST /v1/audit/generate-package` with `{ from_date: quarter_start, to_date: today, format: "json" }`. On success, redirect to a download link or show a toast with `packet_id`.
- **View Decision Trace** — navigate to `/compliance/audit-explorer`.
- **Run Fair Lending Analysis** — navigate to `/compliance/fair-lending`.

**Data fetching**:
- Use `useSWR` with a 60-second refresh interval for the health endpoint.
- Show skeleton loaders while data is loading.

---

#### Step 3 — Update `ui/analytics-dashboard/app/page.tsx`

```typescript
const ROLE_HOME: Record<UserRole, string> = {
  underwriter: "/underwriter/queue",
  risk_analyst: "/risk-analyst/portfolio",
  compliance: "/compliance/command-center",  // was: "/compliance/fair-lending"
  data_scientist: "/data-scientist/drift",
  executive: "/executive",
};
```

**Acceptance criteria**:
- Logging in as a `compliance` role user redirects to `/compliance/command-center`.
- The health endpoint returns HTTP 200 with `overall_score` in [0, 100].
- The KPI cards render with correct values (not hardcoded).
- "Generate Audit Package" button calls the endpoint and shows a toast or download link.

---

## Sprint 3 — Data Lineage + Model Governance Live Data + Validation Workflow (4–6 days)

---

### PROMPT-S3-A: Data Lineage Module (GAP-03)

**Goal**: Capture source → transform → feature → model provenance as a queryable DAG and wire it into the exam packet.

**Files to create**:
- `data_lineage/__init__.py`
- `data_lineage/lineage_tracker.py`

**Files to modify**:
- `feature_pipeline/features.py` (add instrumentation hook)
- `compliance/exam_packet_builder.py` (replace data_lineage stub)

---

#### Step 1 — Create `data_lineage/lineage_tracker.py`

Implement the following:

```python
@dataclass
class LineageNode:
    node_id: str          # UUID
    node_type: str        # "source" | "transform" | "feature" | "model"
    name: str             # e.g. "bureau_pull", "compute_dti", "credit_score", "credit_risk_v1"
    version: str
    schema_hash: str      # sha256 of the schema/column-list
    created_at: str       # ISO-8601 UTC

@dataclass
class LineageEdge:
    edge_id: str
    from_node_id: str
    to_node_id: str
    transform_description: str
    created_at: str
```

DDL — two tables: `lineage_nodes` and `lineage_edges` (append-only).

Implement:
- `async def record_node(node: LineageNode, db_url: str) -> str` — upsert by `(node_type, name, version)`.
- `async def record_edge(edge: LineageEdge, db_url: str) -> str`.
- `async def get_lineage_graph(root_node_name: str, db_url: str) -> Dict` — returns `{"nodes": [...], "edges": [...]}` for the subgraph reachable from `root_node_name`.
- `async def export_lineage_report(tenant_id: str, db_url: str) -> DataLineageReport`:
  ```python
  @dataclass
  class DataLineageReport:
      generated_at: str
      node_count: int
      nodes: List[LineageNode]
      edges: List[LineageEdge]
      data_dictionary: Dict[str, str]  # feature_name → description
  ```

---

#### Step 2 — Instrument `feature_pipeline/features.py`

At the end of `compute_feature_matrix()`, add:
```python
# Lineage instrumentation (best-effort; never blocks the pipeline)
try:
    import asyncio
    from data_lineage.lineage_tracker import LineageNode, LineageEdge, record_node, record_edge
    _db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./decision_audit.db")
    _schema_hash = hashlib.sha256(",".join(sorted(result_df.columns)).encode()).hexdigest()[:16]
    asyncio.ensure_future(record_node(LineageNode(
        node_id=str(uuid.uuid4()),
        node_type="feature",
        name="compute_feature_matrix",
        version=version,
        schema_hash=_schema_hash,
        created_at=datetime.utcnow().isoformat() + "Z",
    ), _db_url))
except Exception:
    pass
```

---

#### Step 3 — Replace data_lineage stub in `exam_packet_builder.py`

Replace the `"pending"` placeholder added in PROMPT-S2-A:
```python
async def build_data_lineage_component(spec: ExamPacketSpec, db_url: str) -> ExamPacketComponent:
    from data_lineage.lineage_tracker import export_lineage_report
    report = await export_lineage_report(spec.tenant_id, db_url)
    return ExamPacketComponent(
        name="data_lineage",
        status="complete",
        data=dataclasses.asdict(report),
    )
```

**Acceptance criteria**:
- `export_lineage_report` returns at least one node after running `compute_feature_matrix()` once.
- The exam packet `data_lineage` component has `status="complete"` (not `"stub"` or `"pending"`).
- `get_lineage_graph("compute_feature_matrix", db_url)` returns a valid DAG dict with non-empty `nodes`.

---

### PROMPT-S3-B: Model Governance UI — Live Data (GAP-05)

**Goal**: Replace `MOCK_MODELS` in the model governance page with live data from MLflow + `governance_approval_log`.

**Files to create**:
- None (use existing logger helpers)

**Files to modify**:
- `decision-api/src/main.py` (add two endpoints)
- `ui/analytics-dashboard/app/compliance/model-governance/page.tsx`

---

#### Step 1 — Add model registry endpoints to `decision-api/src/main.py`

```python
@app.get("/v1/models")
async def list_models(payload: Dict = Depends(verify_bearer)):
    """Return live model inventory from MLflow + governance_approval_log."""
    import mlflow
    from mlflow.tracking import MlflowClient
    client = MlflowClient()
    versions = client.search_model_versions("")
    results = []
    for v in versions:
        gov_log = await get_governance_audit_log(v.name, DB_URL, limit=1)
        latest_action = gov_log[0]["action"] if gov_log else "REGISTERED"
        results.append({
            "model_id": f"{v.name}-{v.version}",
            "model_name": v.name,
            "version": v.version,
            "stage": v.current_stage,
            "status": v.status,
            "auc": v.tags.get("auc"),
            "ks": v.tags.get("ks"),
            "trained_at": v.creation_timestamp,
            "deployed_at": v.last_updated_timestamp,
            "latest_governance_action": latest_action,
        })
    return {"models": results}


class PromoteModelRequest(BaseModel):
    approved_by: str   # second approver — enforced != JWT actor
    notes: str

@app.post("/v1/models/{model_name}/{version}/promote")
async def promote_model(
    model_name: str,
    version: str,
    req: PromoteModelRequest,
    payload: Dict = Depends(verify_bearer),
):
    from compliance.rbac import enforce_four_eyes, SeparationOfDutiesViolation
    actor = payload.get("email", payload["tenant_id"])
    enforce_four_eyes("model_promote_to_production", actor=actor, approver=req.approved_by)
    import mlflow
    mlflow.MlflowClient().transition_model_version_stage(
        name=model_name, version=version, stage="Production"
    )
    await log_governance_action(
        model_name=model_name,
        model_version=version,
        action="PROMOTE_PRODUCTION",
        from_stage="Staging",
        to_stage="Production",
        performed_by=actor,
        approved_by=req.approved_by,
        governance_metrics={},
        notes=req.notes,
        mlflow_run_id=None,
        db_url=DB_URL,
    )
    return {"status": "promoted", "model_name": model_name, "version": version}
```

---

#### Step 2 — Update `ui/analytics-dashboard/app/compliance/model-governance/page.tsx`

1. Remove `MOCK_MODELS` and the `useState(MOCK_MODELS)` initialiser.
2. Add `useSWR("/v1/models", fetcher)` (where `fetcher` calls the Decision API with the user's Bearer token).
3. Replace `setModels(...)` inside `promoteModel()` with a `fetch("POST /v1/models/{model_id}/promote", { approved_by, notes })` call followed by `mutate()` to refresh the SWR cache.
4. Show a loading skeleton while data is fetching. Show an error banner if the fetch fails.
5. Remove the `setTimeout` stub entirely.

**Acceptance criteria**:
- Model governance page loads real model data without `MOCK_MODELS`.
- Clicking Promote calls the real endpoint, and `approve_model()` is rejected with HTTP 422 if the same user is both actor and approver.
- After promotion, the table refreshes with the new stage.

---

### PROMPT-S3-C: Independent Model Validation State Machine + SLA Enforcement (GAP-09)

**Goal**: Enforce four-eyes on `log_model_validation()`; add a nightly SLA-staleness check; expose a validation history endpoint.

**Files to modify**:
- `audit/logger.py`
- `decision-api/src/main.py`

**Files to create**:
- `scripts/nightly_validation_sla_check.py`

---

#### Step 1 — Enforce four-eyes in `audit/logger.py`

At the top of `log_model_validation()`, add:
```python
from compliance.rbac import enforce_four_eyes
# The model developer (performed_by equivalent) should not self-validate.
# We treat validator_email as the "approver" in the four-eyes model.
# For INITIAL and TRIGGERED validations, require that validator != the
# model's registered creator (passed in via a new optional arg).
if submitted_by and validator_email == submitted_by:
    raise SeparationOfDutiesViolation(
        "Validator and model submitter must be different people (SR 11-7 independence requirement)."
    )
```

Add an optional `submitted_by: Optional[str] = None` parameter to `log_model_validation()`.

---

#### Step 2 — Create `scripts/nightly_validation_sla_check.py`

```python
"""
scripts/nightly_validation_sla_check.py
========================================
Nightly job: flag models where the most recent validation is older than
VALIDATION_SLA_DAYS (default 365). Creates a REVIEW_DUE governance log entry
and outputs a summary.

Usage:
    python scripts/nightly_validation_sla_check.py [--sla-days 365] [--dry-run]
"""
```

Logic:
1. Load all distinct `(model_name, model_version)` pairs from `model_validation_log`.
2. For each model, find the most recent `validation_date`.
3. If `(today - validation_date).days > VALIDATION_SLA_DAYS`, call `log_governance_action(action="REVIEW_DUE", ...)`.
4. Print a tabular summary: `model_name | last_validated | days_overdue | action_taken`.
5. Exit with code 1 if any model is overdue (so CI/cron can alert).

---

#### Step 3 — Expose validation history endpoint in `decision-api/src/main.py`

```python
@app.get("/v1/models/{model_name}/validations")
async def list_model_validations(
    model_name: str,
    payload: Dict = Depends(verify_bearer),
):
    from audit.logger import get_model_validations
    records = await get_model_validations(model_name, DB_URL)
    return {"model_name": model_name, "validations": records}
```

**Acceptance criteria**:
- `log_model_validation(..., validator_email="alice@co", submitted_by="alice@co")` raises `SeparationOfDutiesViolation`.
- The nightly script exits with code 1 when a model has not been validated within `SLA_DAYS`.
- `GET /v1/models/{name}/validations` returns a list of validation records newest-first.

---

## Sprint 4 — Consistency Score + Historical Fair Lending (2–4 days)

---

### PROMPT-S4-A: Decision Consistency Score (GAP-04)

**Goal**: Implement a deterministic decision replay to measure whether the same inputs produce the same output as the originally logged decision.

**Files to create**:
- `audit/consistency_scorer.py`

**Files to modify**:
- `decision-api/src/main.py` (add endpoint)

---

#### Step 1 — Create `audit/consistency_scorer.py`

```python
"""
audit/consistency_scorer.py
============================
Decision consistency scorer (PRD §3.1, §7.1).

Replays a stored decision through the current policy + model and reports
the delta between the original and replayed outputs.

Public API
----------
>>> from audit.consistency_scorer import score_decision_consistency
>>> result = await score_decision_consistency("app-uuid-123", db_url, model_loader)
>>> print(result.consistent, result.delta_pd, result.score)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ConsistencyResult:
    application_id: str
    consistent: bool            # True if decision matches and |delta_pd| < threshold
    original_decision: str
    replayed_decision: str
    original_pd: float
    replayed_pd: float
    delta_pd: float             # replayed_pd - original_pd
    score: float                # 1.0 = identical; 0.0 = flipped decision
    flagged: bool               # True if delta_pd > CONSISTENCY_THRESHOLD or decision flipped
    checked_at: str             # ISO-8601 UTC


CONSISTENCY_THRESHOLD = 0.02   # PD delta above this is flagged


async def score_decision_consistency(
    application_id: str,
    db_url: str,
    fraud_model: Any,
    risk_model: Any,
) -> ConsistencyResult:
    """
    1. Load the stored audit record for *application_id*.
    2. Reconstruct the input feature DataFrame from stored ``input_features``.
    3. Re-run fraud + credit risk models.
    4. Re-run the decision engine with the stored ``policy_version``'s cutoffs.
    5. Compare original vs replayed (decision, pd_score).
    6. Return a ConsistencyResult.
    """
```

Implementation notes:
- Use `get_audit_record(application_id, tenant_id=None, db_url=db_url)` from `audit/logger.py` (pass tenant_id from the JWT on the API side).
- Deserialise `input_features` (stored as JSON string) back into a DataFrame.
- Use `predict_pd()` and `predict_fraud()` with the passed-in model objects.
- Load the policy version active at `logged_at` from `PolicyVersionStore().get_as_of(logged_at)`.
- `score = 1.0` if decisions match, `0.5` if `|delta_pd| < CONSISTENCY_THRESHOLD` but same decision bucket, `0.0` if decision flipped.

---

#### Step 2 — Expose endpoint in `decision-api/src/main.py`

```python
@app.get("/v1/decisions/{application_id}/consistency")
async def decision_consistency(
    application_id: str,
    payload: Dict = Depends(verify_bearer),
):
    from audit.consistency_scorer import score_decision_consistency
    result = await score_decision_consistency(
        application_id, DB_URL, _fraud_model, _risk_model
    )
    return dataclasses.asdict(result)
```

---

#### Step 3 — Tests

Create `audit/tests/test_consistency_scorer.py`:
- `test_identical_replay` — same stored features + models → `consistent=True`, `score=1.0`.
- `test_model_drift_detected` — corrupt the stored `pd_score` by +0.05; `flagged=True`.
- `test_decision_flip_score_zero` — original APPROVE, replayed REJECT → `score=0.0`.

**Acceptance criteria**:
- `GET /v1/decisions/{id}/consistency` returns HTTP 200 with `consistent`, `score`, `delta_pd`.
- `flagged=True` appears in the response if `|delta_pd| > 0.02` or the decision outcome changed.

---

### PROMPT-S4-B: Historical Fair Lending Trend Tracking (GAP-12)

**Goal**: Persist `FairLendingReport` to a time-series table and expose a history endpoint + trend chart.

**Files to modify**:
- `monitoring/fair_lending.py`
- `decision-api/src/main.py`
- `ui/analytics-dashboard/app/compliance/fair-lending/page.tsx`

---

#### Step 1 — Add persistence to `monitoring/fair_lending.py`

1. Add DDL for `fair_lending_history` table:
   ```sql
   CREATE TABLE IF NOT EXISTS fair_lending_history (
       report_id   TEXT PRIMARY KEY,
       tenant_id   TEXT NOT NULL,
       run_date    TEXT NOT NULL,
       from_date   TEXT NOT NULL,
       to_date     TEXT NOT NULL,
       dir_minority REAL,
       dir_female   REAL,
       approval_rate_majority REAL,
       approval_rate_minority REAL,
       chi_sq_p_value REAL,
       alert_triggered INTEGER,
       report_json TEXT NOT NULL
   );
   ```

2. Add `async def save_fair_lending_report(report: FairLendingReport, tenant_id: str, db_url: str) -> str`:
   - Serialise the full `FairLendingReport` to JSON and insert into `fair_lending_history`.
   - Return the `report_id` (UUID).

3. After `_save_report(report, output_dir)` in `analyze_fair_lending()`, call `save_fair_lending_report()` if `db_url` is passed as an optional kwarg.

---

#### Step 2 — Add history endpoint to `decision-api/src/main.py`

```python
@app.get("/v1/fair-lending/history")
async def fair_lending_history(
    from_date: str = Query(..., description="YYYY-MM-DD"),
    to_date: str = Query(..., description="YYYY-MM-DD"),
    payload: Dict = Depends(verify_bearer),
):
    tenant_id = payload["tenant_id"]
    # SELECT * FROM fair_lending_history WHERE tenant_id=:t AND run_date BETWEEN :f AND :t
    rows = await _query_fair_lending_history(tenant_id, from_date, to_date, DB_URL)
    return {"history": rows}
```

Implement `_query_fair_lending_history()` using the async SQLAlchemy engine pattern from `audit/logger.py`.

---

#### Step 3 — Add trend chart to the fair lending UI

In `ui/analytics-dashboard/app/compliance/fair-lending/page.tsx`:
1. Add a `useSWR` call to `GET /v1/fair-lending/history?from=<30d_ago>&to=<today>`.
2. Add a `recharts` `<LineChart>` below the existing fair lending metrics cards:
   - X-axis: `run_date`.
   - Two lines: `dir_minority` and `dir_female`.
   - A horizontal reference line at `y=0.8` (the 80% rule threshold).
3. Wire the date-range picker to update the `from/to` parameters of the SWR fetch.

**Acceptance criteria**:
- `POST` to the analysis route saves a record to `fair_lending_history`.
- `GET /v1/fair-lending/history` returns rows sorted by `run_date` descending.
- The date-range picker on the UI triggers a re-fetch and the trend chart updates.

---

## Sprint 5 — Fair Lending Simulation + LOS Integration + Regulator Portal (5–7 days)

---

### PROMPT-S5-A: Fair Lending Scenario Simulation (GAP-11)

**Goal**: Add `simulate_fair_lending_impact()` that replays historical decisions under a proposed policy and reports the delta DIR.

**Files to modify**:
- `monitoring/fair_lending.py`
- `decision-api/src/main.py`

---

#### Step 1 — Implement `simulate_fair_lending_impact()` in `monitoring/fair_lending.py`

```python
@dataclass
class FairLendingSimulationResult:
    baseline_dir_minority: float
    simulated_dir_minority: float
    delta_dir_minority: float        # simulated - baseline
    baseline_approval_rate: float
    simulated_approval_rate: float
    delta_approval_rate: float
    alert: bool                      # True if simulated DIR < 0.8
    applications_tested: int
    policy_config_used: Dict[str, Any]

def simulate_fair_lending_impact(
    new_policy_config: Dict[str, Any],
    historical_decisions_df: pd.DataFrame,
    fraud_model: Any,
    risk_model: Any,
) -> FairLendingSimulationResult:
```

Implementation:
1. For each row in `historical_decisions_df`, reconstruct a `DecisionRequest` (use stored input features).
2. Call `make_decision(req, policy_overrides=new_policy_config)` — note this call uses the test policy config and does **not** require justification/approval fields (simulation context, not production).
3. Collect simulated decisions into a new DataFrame with the same `bisg_minority_proxy` column.
4. Run `analyze_fair_lending()` on both original and simulated DataFrames.
5. Return `FairLendingSimulationResult`.

---

#### Step 2 — Expose simulation endpoint in `decision-api/src/main.py`

```python
class SimulateFairLendingRequest(BaseModel):
    new_policy_config: Dict[str, Any]  # e.g. {"pd_threshold_low": 0.04}
    lookback_days: int = 90            # how many days of history to replay

@app.post("/v1/fair-lending/simulate")
async def simulate_fair_lending(
    req: SimulateFairLendingRequest,
    payload: Dict = Depends(verify_bearer),
):
    tenant_id = payload["tenant_id"]
    # Load historical decisions for the period
    from_date = (datetime.utcnow() - timedelta(days=req.lookback_days)).date().isoformat()
    to_date = datetime.utcnow().date().isoformat()
    records = await get_audit_records_by_period(tenant_id, from_date, to_date, DB_URL, limit=5000)
    historical_df = pd.DataFrame(records)
    if historical_df.empty:
        raise HTTPException(400, "No historical decisions found for simulation period")
    from monitoring.fair_lending import simulate_fair_lending_impact
    result = simulate_fair_lending_impact(
        req.new_policy_config, historical_df, _fraud_model, _risk_model
    )
    return dataclasses.asdict(result)
```

**Acceptance criteria**:
- `POST /v1/fair-lending/simulate` with `{"pd_threshold_low": 0.04}` returns `delta_dir_minority`, `alert`, and `applications_tested`.
- Tightening the PD threshold (smaller number) should increase approval rate; the test asserts `delta_approval_rate > 0`.

---

### PROMPT-S5-B: LOS / Credit Bureau Integration (GAP-13)

**Goal**: Add an inbound LOS webhook receiver and a bureau data enrichment stub to `ingestion-api`.

**Files to modify**:
- `ingestion-api/src/main.py`
- `ingestion-api/src/models.py`

---

#### Step 1 — Add LOS webhook receiver to `ingestion-api/src/main.py`

```python
class LOSWebhookPayload(BaseModel):
    los_application_id: str
    event_type: str           # "APPLICATION_SUBMITTED" | "STATUS_UPDATED" | "DOCUMENT_UPLOADED"
    applicant: Dict[str, Any]
    loan_request: Dict[str, Any]
    submitted_at: str

@app.post("/webhook/los", status_code=202)
async def los_webhook(
    payload: LOSWebhookPayload,
    x_los_signature: str = Header(..., alias="X-LOS-Signature"),
):
    """
    Receive an inbound event from a Loan Origination System.
    1. Validate HMAC-SHA256 signature using LOS_WEBHOOK_SECRET env var.
    2. Map LOSWebhookPayload to the ingestion-api ApplicationPayload schema.
    3. Forward to the Decision API (POST /v1/decisions) if event_type == APPLICATION_SUBMITTED.
    4. Return { "received": true, "application_id": <los_application_id> }.
    """
    import hmac, hashlib
    secret = os.getenv("LOS_WEBHOOK_SECRET", "")
    if secret:
        expected = hmac.new(secret.encode(), msg=request.body(), digestmod=hashlib.sha256).hexdigest()
        if not hmac.compare_digest(f"sha256={expected}", x_los_signature):
            raise HTTPException(401, "Invalid LOS webhook signature")
    # Forward to Decision API
    if payload.event_type == "APPLICATION_SUBMITTED":
        decision_payload = _map_los_to_decision(payload)
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                os.getenv("DECISION_API_URL", "http://decision-api:8000") + "/v1/decisions",
                json=decision_payload,
                headers={"Authorization": f"Bearer {os.getenv('INTERNAL_JWT', '')}"},
                timeout=30,
            )
            resp.raise_for_status()
    return {"received": True, "los_application_id": payload.los_application_id}
```

Implement `_map_los_to_decision(payload: LOSWebhookPayload) -> Dict` to map the LOS field names to `LoanApplicationRequest` field names (add a mapping table for the five most common LOS vendors: Encompass, Blend, Maxwell, BeSmartee, Floify — use configurable field-name maps via env vars with sensible defaults).

---

#### Step 2 — Bureau data enrichment stub

Add a `BureauEnrichmentMiddleware` async function that:
1. Accepts an `application_id` and `applicant` dict.
2. If `BUREAU_API_KEY` is set, calls the configured bureau endpoint (default: Experian sandbox).
3. If not set, returns a mock bureau response with realistic structure (for development).

```python
async def enrich_with_bureau_data(
    application_id: str,
    applicant: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich application with bureau data. Returns merged dict."""
```

Wire this into the `/webhook/los` handler so bureau data is fetched before forwarding to the Decision API.

**Acceptance criteria**:
- `POST /webhook/los` with a valid signature and `event_type=APPLICATION_SUBMITTED` returns HTTP 202.
- `POST /webhook/los` with an invalid signature returns HTTP 401.
- When `BUREAU_API_KEY` is not set, the mock bureau response is used and the Decision API call still succeeds.

---

### PROMPT-S5-C: Regulator Read-Only Portal (GAP-14)

**Goal**: Add a regulator-scoped Next.js route group with read-only access to exam packets and audit records.

**Files to create**:
- `ui/analytics-dashboard/app/regulator/layout.tsx`
- `ui/analytics-dashboard/app/regulator/page.tsx`
- `ui/analytics-dashboard/app/regulator/audit-records/page.tsx`
- `ui/analytics-dashboard/app/regulator/exam-packets/page.tsx`

**Files to modify**:
- `ui/analytics-dashboard/auth.ts`
- `ui/analytics-dashboard/middleware.ts`

---

#### Step 1 — Add `regulator` role to `auth.ts`

Add `"regulator"` to the `UserRole` type union. Add `regulator: "/regulator"` to `ROLE_HOME` in `app/page.tsx`.

---

#### Step 2 — Create `app/regulator/layout.tsx`

A layout that:
- Checks the session role is `"regulator"` (redirect to `/unauthorized` otherwise).
- Renders a simplified read-only sidebar with: "Audit Records", "Exam Packets".
- Shows a read-only badge in the header: `"🔒 Read-Only Regulator View"`.
- Does **not** show any edit, approve, generate, or promote actions.

---

#### Step 3 — Create `app/regulator/page.tsx`

Landing page showing:
- The compliance health score (read-only, fetched from `GET /v1/compliance/health`).
- The two most recent exam packets (from `GET /v1/audit/generate-package` in list mode — add a `GET /v1/audit/packets` list endpoint if not present).
- A link to the full audit records search.

---

#### Step 4 — Create `app/regulator/audit-records/page.tsx`

Read-only version of the audit explorer UI with:
- Search by `application_id` (calls `GET /v1/decisions/{id}/audit`).
- Date-range filter.
- Export button (calls `GET /v1/decisions/{id}/audit` with `?format=json`, downloads the result).
- No write operations.

---

#### Step 5 — Create `app/regulator/exam-packets/page.tsx`

- List exam packets (add `GET /v1/audit/packets` endpoint in `decision-api/src/main.py` that queries `compliance_exam_packets` log table).
- Download button per packet → calls `POST /v1/audit/generate-package` for the given period with `format=pdf_zip`.

---

#### Step 6 — Update `middleware.ts`

Add `/regulator` to the protected routes and restrict it to users with `role === "regulator"`. All `/regulator` routes must be read-only — enforce at the middleware level by stripping any non-GET method to a 405 response for this prefix.

**Acceptance criteria**:
- A user with `role=compliance` navigating to `/regulator` is redirected to `/unauthorized`.
- A user with `role=regulator` can view audit records and download exam packets.
- No write-operation button (Promote, Generate, Approve) is rendered on any regulator page.

---

## Backlog — AI Anomaly Detection + Remediation Advisor

---

### PROMPT-BL-A: AI-Powered Anomaly Detection (GAP-15)

**Goal**: Add an `IsolationForest` anomaly detection layer to `monitoring/drift_monitor.py` as a supplementary signal alongside PSI/KS.

**Files to modify**:
- `monitoring/drift_monitor.py`
- `monitoring/alert_router.py`

---

#### Step 1 — Add `detect_anomalies()` to `monitoring/drift_monitor.py`

```python
def detect_anomalies(
    reference_df: pd.DataFrame,
    production_df: pd.DataFrame,
    contamination: float = 0.05,
) -> AnomalyDetectionResult:
    """
    Train an IsolationForest on *reference_df* and predict anomalies in
    *production_df*.  Returns an AnomalyDetectionResult summarising which
    production rows are flagged and an overall anomaly rate.
    """
```

```python
@dataclass
class AnomalyDetectionResult:
    anomaly_rate: float            # fraction of production rows flagged
    flagged_indices: List[int]
    method: str = "IsolationForest"
    contamination: float = 0.05
    alert: bool = False            # True if anomaly_rate > contamination * 2
```

Use `sklearn.ensemble.IsolationForest(contamination=contamination, random_state=42)` trained on `reference_df[numeric_cols]`, with `predict()` on `production_df[numeric_cols]`. Map predictions: `-1 → flagged`.

---

#### Step 2 — Integrate into the main drift monitoring report

In the existing drift report generation, after PSI and KS checks, add:
```python
anomaly_result = detect_anomalies(reference_df, production_df)
if anomaly_result.alert:
    alert_router.route_alert(
        AlertEvent(
            alert_type="ANOMALY_DETECTED",
            severity="HIGH",
            details=dataclasses.asdict(anomaly_result),
        )
    )
```

**Acceptance criteria**:
- `detect_anomalies(ref_df, prod_df_with_outliers)` returns `anomaly_rate > 0`.
- An alert is routed when `anomaly_rate > contamination * 2`.

---

### PROMPT-BL-B: Automated Remediation Recommendations (GAP-16)

**Goal**: Map every compliance event `rule_code` to a structured `RemediationRecommendation` and surface them in the command center.

**Files to create**:
- `compliance/remediation_advisor.py`

**Files to modify**:
- `decision-api/src/main.py` (expose remediation endpoint)
- `ui/analytics-dashboard/app/compliance/command-center/page.tsx` (show recommendations)

---

#### Step 1 — Create `compliance/remediation_advisor.py`

```python
"""
compliance/remediation_advisor.py
===================================
Maps compliance event rule_codes to structured RemediationRecommendation objects.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class RemediationRecommendation:
    rule_code: str
    action: str              # imperative sentence, e.g. "Review and re-notify applicants within 30 days"
    owner_role: str          # "compliance" | "risk_analyst" | "data_scientist"
    sla_days: int            # recommended resolution SLA
    regulatory_citation: str # e.g. "ECOA §202.9, Reg B Form C-1"
    severity: str            # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    escalation_contact: Optional[str] = None


# Remediation catalogue
REMEDIATION_CATALOGUE: Dict[str, RemediationRecommendation] = {
    "AA_SLA_BREACH": RemediationRecommendation(
        rule_code="AA_SLA_BREACH",
        action="Immediately issue overdue adverse action notices and document delay reason",
        owner_role="compliance",
        sla_days=1,
        regulatory_citation="ECOA §202.9 — 30-day adverse action notice requirement",
        severity="CRITICAL",
    ),
    "MLA_MAPR_VIOLATION": RemediationRecommendation(
        rule_code="MLA_MAPR_VIOLATION",
        action="Void the affected loan, refund charged fees, and file corrective SAR",
        owner_role="compliance",
        sla_days=3,
        regulatory_citation="Military Lending Act §987, 32 CFR 232 — 36% MAPR cap",
        severity="CRITICAL",
    ),
    "PV001": RemediationRecommendation(
        rule_code="PV001",
        action="Remove prohibited variable from feature pipeline and retrain model",
        owner_role="data_scientist",
        sla_days=14,
        regulatory_citation="ECOA §202.2(z) / Fair Housing Act §3604 — prohibited basis variables",
        severity="CRITICAL",
    ),
    "MODEL_VALIDATION_OVERDUE": RemediationRecommendation(
        rule_code="MODEL_VALIDATION_OVERDUE",
        action="Initiate independent model validation and submit findings to Model Risk Committee",
        owner_role="risk_analyst",
        sla_days=30,
        regulatory_citation="SR 11-7 — model validation within 12 months of deployment",
        severity="HIGH",
    ),
    "OVERRIDE_RATE_HIGH": RemediationRecommendation(
        rule_code="OVERRIDE_RATE_HIGH",
        action="Review override approvals for last 90 days and document business justification",
        owner_role="compliance",
        sla_days=7,
        regulatory_citation="OCC 2021-25 — override logging and rate monitoring",
        severity="HIGH",
    ),
    # ... add additional rule codes as needed
}


def get_recommendation(rule_code: str) -> Optional[RemediationRecommendation]:
    """Return the RemediationRecommendation for *rule_code*, or None if unknown."""
    return REMEDIATION_CATALOGUE.get(rule_code)


def get_all_active_recommendations(active_rule_codes: list[str]) -> list[RemediationRecommendation]:
    """Return recommendations for all supplied active rule codes, sorted by severity."""
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    recs = [r for rc in active_rule_codes if (r := get_recommendation(rc)) is not None]
    return sorted(recs, key=lambda r: severity_order.get(r.severity, 99))
```

---

#### Step 2 — Add remediation endpoint to `decision-api/src/main.py`

```python
@app.get("/v1/compliance/remediation")
async def compliance_remediation(payload: Dict = Depends(verify_bearer)):
    """Return active remediation recommendations based on current compliance flags."""
    from compliance.health_score import compute_health_score
    from compliance.remediation_advisor import get_all_active_recommendations
    score = compute_health_score()
    # Map failing dimensions to rule codes
    rule_codes = [d.upper() for d in score.failing_dimensions]
    recs = get_all_active_recommendations(rule_codes)
    return {"recommendations": [dataclasses.asdict(r) for r in recs]}
```

---

#### Step 3 — Surface in command center UI

In `ui/analytics-dashboard/app/compliance/command-center/page.tsx`, add a `useSWR` call to `GET /v1/compliance/remediation` and render a "Remediation Actions" section below the KPI grid:
- One row per recommendation with: severity badge, rule_code, action text, SLA, regulatory citation, owner role.
- Sort by severity (CRITICAL first).
- Show a "Resolved" button (no-op for now, styling only).

**Acceptance criteria**:
- `get_all_active_recommendations(["PV001", "AA_SLA_BREACH"])` returns two items, CRITICAL first.
- `GET /v1/compliance/remediation` returns HTTP 200 with a `recommendations` array.
- The command center shows the recommendations section when failing dimensions exist.

---

## Cross-Cutting: Tests for All Gaps

After implementing each prompt, run the full test suite:

```bash
# Unit + integration tests
pytest tests/ compliance/tests/ audit/tests/ monitoring/tests/ -v --tb=short

# Specific gap-closure tests
pytest -k "override_log or prohibited_variables or data_lineage or consistency_scorer or fair_lending_history or simulation or anomaly or remediation" -v
```

All new code must achieve **≥90% branch coverage** for the new modules. Add the following `pytest.ini` markers if not already present:

```ini
[pytest]
markers =
    gap_closure: marks tests that close a specific gap from the gap analysis
    p1: P1-Critical gap closure tests
    p2: P2-High gap closure tests
```

Tag each new test with the appropriate marker, e.g.:
```python
@pytest.mark.gap_closure
@pytest.mark.p1
def test_override_chain_genesis():
    ...
```
