# Decision Routing Summary
**Platform**: `credit-risk-platform`
**Date**: 2026-04-16
**Analyst**: GitHub Copilot
**Scope**: Full audit of automatic vs. HITL decision routing

---

## 1. Decision Outcome Constants

Defined in `decision_engine/engine.py` lines 48–50:

| Constant | Value | Meaning |
|---|---|---|
| `DECISION_APPROVE` | `"APPROVE"` | Automatic approval — no human action needed |
| `DECISION_REJECT` | `"REJECT"` | Automatic rejection — Reg B adverse action notice triggered |
| `DECISION_MANUAL_REVIEW` | `"MANUAL_REVIEW"` | Flagged — enqueued to HITL `ReviewQueue` |

---

## 2. Fraud Detection Thresholds

**File**: `models/fraud_detection/predict.py` lines 32–33

```python
THRESHOLD_REJECT = 0.60   # fraud_probability > 0.60  → fraud_flag = "reject"
THRESHOLD_REVIEW = 0.30   # fraud_probability >= 0.30 → fraud_flag = "manual_review"
                          # fraud_probability < 0.30  → fraud_flag = "continue"
```

**Status**: These thresholds are **hardcoded constants** — they are not configurable via environment variables or the config registry. Any change requires a code deployment.

**Model**: `GradientBoostingClassifier` loaded from `models/fraud_detection/fraud_model_v1.pkl` (version `v1`). Loaded once via `models/model_loader.get_or_load()` (process-level cache — no per-request disk I/O).

---

## 3. Credit Risk (PD) Thresholds

**File**: `decision_engine/engine.py` lines 60–61

```python
PD_THRESHOLD_LOW    = 0.05   # pd_score < 0.05           → APPROVE at base rate
PD_THRESHOLD_MEDIUM = 0.10   # 0.05 ≤ pd_score ≤ 0.10   → APPROVE at risk-priced rate
                             # pd_score > 0.10            → REJECT (AA01)
```

**Per-tenant overrides**: Supported via `policy_overrides` dict in `make_decision()`. Keys: `pd_threshold_low`, `pd_threshold`, `dti_high`. Require four-eyes sign-off (`submitted_by != approved_by`, min 10-char justification). Override records are written to `audit/override_log.py` `policy_overrides_log` table.

**Supplemental thresholds**:
- `DTI_HIGH_THRESHOLD = 0.43` — triggers AA04 on REJECT decisions
- `OPEN_ACCOUNTS_MIN = 1` — triggers AA03 on REJECT decisions

---

## 4. Decision Routing: Automatic vs. Human Review

### Complete Decision Tree

```
Application In
│
├─ Fraud Model (fraud_probability)
│   ├─ > 0.60  (THRESHOLD_REJECT)    → REJECT (AA02)         ← automatic
│   ├─ ≥ 0.30  (THRESHOLD_REVIEW)    → MANUAL_REVIEW (AA05)  ← human review
│   └─ < 0.30  → "continue" to PD model
│       │
│       └─ PD Model (pd_score)
│           ├─ > 0.10 (PD_THRESHOLD_MEDIUM)  → REJECT (AA01)  ← automatic
│           ├─ 0.05–0.10                       → APPROVE        ← automatic
│           └─ < 0.05 (PD_THRESHOLD_LOW)      → APPROVE        ← automatic
│
└─ CC Origination Policy (evaluate_application) — additional product gates
    ├─ Hard decline gates → DECLINE / REFER_SECURED              ← automatic
    ├─ pd_score ≥ policy.pd_manual_review (per product)          → MANUAL_REVIEW ← human review
    └─ pd_score < policy.pd_manual_review                        → APPROVE        ← automatic
```

### Automatic Decision Fraction (design target)

In a typical conforming population the expected routing split is approximately:

| Outcome | Typical Rate |
|---|---|
| Automatic APPROVE | ~60–70% |
| Automatic REJECT | ~25–30% |
| MANUAL_REVIEW (HITL) | ~5–10% |

Runtime measurement available via `GET /v1/analytics/decision-mix` (implemented in `decision-api/src/main.py` and `decisioning/decision_metrics.py`).

---

## 5. HITL Queue Lifecycle

**File**: `decisioning/review_queue.py`

| Status | Entry Trigger | Exit Trigger |
|---|---|---|
| `PENDING` | `ReviewQueue.enqueue()` | `assign()` or SLA breach |
| `UNDER_REVIEW` | `assign(item_id, analyst_email)` | `complete()` or SLA breach |
| `COMPLETED` | `complete(item_id, override_decision, ...)` | Terminal |
| `SLA_BREACHED` | `check_sla_breaches()` — sla_deadline ≤ now | Manual escalation (GAP-H07) |

**Override decision values** (accepted by `complete()`): `APPROVE`, `DECLINE`, `REFER_TO_SENIOR`

**Note**: These differ from engine canonical values (`REJECT` → engine uses `REJECT`, queue uses `DECLINE`). Mapping is required when writing overrides to the audit log.

---

## 6. HITL Control Status (H-01 through H-10)

| # | Control | Status | Notes |
|---|---|---|---|
| H-01 | `assign_to_analyst()` method exists | **Partial** — method exists as `assign()` not `assign_to_analyst()` | See GAP-H01 |
| H-02 | `complete_review()` requires non-null `override_reason_code` | **Absent** — parameter accepted but not validated non-null | See GAP-H02 |
| H-03 | `check_sla_breaches()` exists and is scheduled | **Partial** — method exists but no scheduler in `orchestration/` | See GAP-H03 |
| H-04 | Assignment requires RBAC role `analyst` or `supervisor` | **Absent** — no RBAC check inside `assign()` | See GAP-H04 |
| H-05 | HITL override written to `policy_overrides_log` | **Absent** — `complete()` does not call `audit/override_log.py` | See GAP-H05 |
| H-06 | Adverse action notice on analyst `override_decision=REJECT` | **Absent** — no notice triggered on analyst DECLINE | See GAP-H06 |
| H-07 | Escalation path `SLA_BREACHED` → supervisor re-assignment | **Absent** — no escalation method exists | See GAP-H07 |
| H-08 | HITL metrics surfaced in monitoring dashboard | **Partial** — `/v1/analytics/decision-mix` endpoint added (2026-04-16); no monitoring dashboard widget | See GAP-H08 |
| H-09 | `configure_review_queue()` called at app startup | **Absent** — not called in `decision-api/src/main.py`; `_REVIEW_QUEUE = None` in production | See GAP-H09 |
| H-10 | Second-approver check on policy overrides | **Partial** — enforced in `engine.py make_decision()` for threshold overrides; absent in `ReviewQueue.complete()` override path | See GAP-H10 |

---

## 7. Audit Trail Completeness

- **APPROVE / REJECT decisions**: Written to `audit_log` via `audit/logger.py log_decision()` with SHA-256 hash chain. ✅
- **MANUAL_REVIEW decisions**: Written to `audit_log` via `log_decision()`. ✅
- **ReviewQueue enqueue**: Written to `review_queue` table in SQLite. ✅
- **ReviewQueue override**: Written to `review_queue` table only. **Not** written to `policy_overrides_log`. ⚠️ GAP-H05
- **Adverse action on analyst REJECT override**: Not triggered. ⚠️ GAP-H06

---

## 8. Key Source Files

| File | Role |
|---|---|
| `decision_engine/engine.py` | Primary decision tree: fraud gate → PD gate → reason codes |
| `models/fraud_detection/predict.py` | Fraud flag thresholds (THRESHOLD_REJECT=0.60, THRESHOLD_REVIEW=0.30) |
| `decision_engine/cc_origination_policy.py` | CC-specific product policy gates + HITL queue hook |
| `decisioning/review_queue.py` | SQLAlchemy HITL queue: enqueue, assign, complete, SLA check |
| `decisioning/decision_metrics.py` | Runtime auto-vs-HITL metrics report |
| `compliance/adverse_action_generator.py` | Reg B adverse action notice generation |
| `audit/logger.py` | Append-only audit log with SHA-256 hash chain |
| `audit/override_log.py` | Policy threshold override log with four-eyes enforcement |
| `decision-api/src/main.py` | API wiring: `_run_pipeline()`, `/v1/analytics/decision-mix` |
