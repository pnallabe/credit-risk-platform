# HITL Review Queue Lifecycle
**Source**: `decisioning/review_queue.py`
**Generated**: 2026-04-16 by GitHub Copilot

## State Diagram

```mermaid
stateDiagram-v2
    [*] --> PENDING : ReviewQueue.enqueue(application_id, pd_score, features, sla_hours=24)\nTriggered by MANUAL_REVIEW outcome from engine or cc_origination_policy\nSLA clock starts: sla_deadline = now + sla_hours

    PENDING --> UNDER_REVIEW : ReviewQueue.assign(item_id, reviewer_id)\nSets: assigned_to, review_started_at = now\nstatus = UNDER_REVIEW

    UNDER_REVIEW --> COMPLETED : ReviewQueue.complete(item_id,\n  override_decision,\n  override_reason_code,\n  notes)\nSets: completed_at, override_decision,\n  override_reason_code, override_notes\nstatus = COMPLETED

    PENDING --> SLA_BREACHED : ReviewQueue.check_sla_breaches()\nsla_deadline ≤ now AND status IN (PENDING, UNDER_REVIEW)\nstatus = SLA_BREACHED

    UNDER_REVIEW --> SLA_BREACHED : ReviewQueue.check_sla_breaches()\nsla_deadline ≤ now (still under review)\nstatus = SLA_BREACHED

    COMPLETED --> [*] : Final decision written to audit log\nAdverse action notice generated if override_decision = REJECT\n(⚠️ GAP-H05: override not written to audit/override_log.py)\n(⚠️ GAP-H06: adverse action on analyst REJECT — ABSENT)

    SLA_BREACHED --> UNDER_REVIEW : ⚠️ GAP-H07: Supervisor escalation — ABSENT\nNo re-assignment method exists in ReviewQueue

    note right of PENDING
        Fields set on enqueue:
        - item_id (UUID, primary key)
        - application_id
        - original_pd_score
        - original_features (JSON)
        - sla_deadline = now + sla_hours (default 24 h)
        - status = PENDING
        - assigned_to = NULL
    end note

    note right of COMPLETED
        Analyst writes:
        - override_decision: "APPROVE" | "DECLINE" | "REFER_TO_SENIOR"
        - override_reason_code (ReviewReasonCode enum)
        - override_notes (free text, optional)

        ⚠️ GAPS:
        - H-02: override_reason_code not validated as non-null
        - H-05: not written to policy_overrides_log
        - H-06: no adverse action notice triggered
    end note
```

## ReviewReasonCode Enum Values

| Value | Meaning |
|---|---|
| `INSUFFICIENT_INCOME` | Income below threshold |
| `THIN_FILE` | Insufficient credit history |
| `FRAUD_INDICATORS` | Elevated fraud signals |
| `POLICY_EXCEPTION` | Business policy exception |
| `INCORRECT_MODEL_INPUT` | Data quality / input error |
| `DATA_QUALITY_CONCERN` | Upstream data issue |
| `MANUAL_ESCALATION` | Supervisor requested review |
| `OTHER` | Catch-all |

## Override Decision Allowed Values

Method: `ReviewQueue.complete()` line 184

```python
allowed = {"APPROVE", "DECLINE", "REFER_TO_SENIOR"}
```

**Note**: The override decision values (`DECLINE`, `REFER_TO_SENIOR`) differ from the engine's canonical values (`REJECT`, `MANUAL_REVIEW`). This mapping gap may cause downstream issues when writing to the audit log. ⚠️ GAP-H05.
