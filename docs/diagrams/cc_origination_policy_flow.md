# CC Origination Policy Decision Flow
**Source**: `decision_engine/cc_origination_policy.py`
**Generated**: 2026-04-16 by GitHub Copilot

## CC Product Policy Gate Flowchart

```mermaid
flowchart TD
    A([CC Application Received\nevaluate_application]) --> B{configure_review_queue\ncalled at startup?}
    B -- "⚠️ GAP-H09: NOT wired\nin decision-api/src/main.py" --> C["_REVIEW_QUEUE = None\nEnqueue silently skipped\n(warning logged only)"]
    B -- "configure_review_queue\nqueue called" --> D["_REVIEW_QUEUE set\nEnqueue fully operational"]
    C --> E
    D --> E

    E[Phase 1: Hard Decline Checks\nEvaluate all hard gates in parallel] --> F{Any hard gate fails?}

    F -- "age < 18 → AGED_BELOW_MINIMUM" --> REJ
    F -- "fico_score < policy.min_fico → FICO_BELOW_MINIMUM" --> REJ
    F -- "annual_income < policy.min_income_annual → INSUFFICIENT_INCOME" --> REJ
    F -- "dti > policy.max_dti → DTI_EXCEED_MAX" --> REJ
    F -- "num_bankruptcy > policy.max_bk_within_yr → BANKRUPTCY_RECENT" --> REJ
    F -- "num_derog_marks > policy.max_derog_marks → DEROGATORY_EXCESS" --> REJ
    F -- "inq_last_6m > policy.max_inq_6m → TOO_MANY_INQUIRIES" --> REJ
    F -- "employment_status == unemployed → EMPLOYMENT_RISK" --> REJ
    F -- "pct_rev_utilization > 0.95 → UTILIZATION_TOO_HIGH" --> REJ
    F -- "pd_score >= policy.pd_hard_decline → PD_ABOVE_CUTOFF" --> REJ

    REJ{Counter-offer\nto Secured?} -- "product != secured\nAND fico >= 300\nAND pd < secured.pd_hard_decline" --> RSEC["Decision: REFER_SECURED\nCounter-offer: secured card\nCredit limit assigned\nAPR computed"]
    REJ -- "No counter-offer eligible" --> DEC["❌ Decision: DECLINE\nList of decline_reasons returned\nautomaticDecision=true"]

    F -- "All hard gates pass" --> G{Phase 2: PD Band Check\npd_score >= policy.pd_manual_review?}

    G -- "pd_score >= policy.pd_manual_review\nAND pd_score < policy.pd_hard_decline" --> MR["🟡 Decision: MANUAL_REVIEW\nautomaticDecision=false\nCredit limit and APR pre-computed\nLGD model used for break-even PD"]
    MR --> QE{_REVIEW_QUEUE\nnot None?}
    QE -- "Yes" --> ENQ["ReviewQueue.enqueue\napplication_id, pd_score,\nfull feature dict, sla_hours=24"]
    QE -- "No (GAP-H09)" --> SKIP["⚠️ Enqueue SKIPPED\nlogging.warning only\nNo SLA clock started"]

    G -- "pd_score < policy.pd_manual_review" --> APP["✅ Decision: APPROVE\nautomaticDecision=true\nCredit limit: income × fico_mult × pd_haircut × dti_haircut\nAPR: policy.apr_base + spread\nBreak-even PD computed via LGDModel"]
```

## Product Policy Thresholds (Source: `cc_origination_policy.py` lines 152–213)

| Product | min_fico | max_dti | min_income | pd_hard_decline | pd_manual_review |
|---|---|---|---|---|---|
| secured | 300 | 0.65 | $8,000 | 0.55 | 0.40 |
| student | 600 | 0.50 | $10,000 | 0.30 | 0.18 |
| basic | 620 | 0.50 | $18,000 | 0.25 | 0.14 |
| rewards | 670 | 0.45 | $30,000 | 0.18 | 0.10 |
| premium | 720 | 0.40 | $60,000 | 0.12 | 0.07 |
| ultra_premium | 760 | 0.35 | $150,000 | 0.06 | 0.04 |
| business | 650 | 0.50 | $40,000 | 0.22 | 0.12 |

## configure_review_queue() Wiring Note

The module-level `_REVIEW_QUEUE: Optional[ReviewQueue]` is set via:
```python
# decision_engine/cc_origination_policy.py lines 70–73
_REVIEW_QUEUE: Optional["ReviewQueue"] = None

def configure_review_queue(queue: "ReviewQueue") -> None:
    global _REVIEW_QUEUE
    _REVIEW_QUEUE = queue
```

**⚠️ GAP-H09**: `configure_review_queue()` is **not called** in `decision-api/src/main.py` startup. The queue is `None` in production, meaning all MANUAL_REVIEW outcomes from the CC origination policy silently skip the enqueue step (with only a `logging.warning`).

## Policy Override Bypass Path

`make_decision()` in `engine.py` supports `policy_overrides` dict — overrides `pd_threshold_low`, `pd_threshold`, `dti_high`.
Four-eyes sign-off required: `submitted_by != approved_by`, min 10-char justification.
Override records written to `audit/override_log.py` `policy_overrides_log` table via `PolicyOverrideRecord`.
