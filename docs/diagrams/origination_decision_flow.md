# Origination Decision Flow
**Source**: `decision_engine/engine.py`, `models/fraud_detection/predict.py`, `models/credit_risk/predict.py`
**Generated**: 2026-04-16 by GitHub Copilot

## Primary Origination Flowchart

```mermaid
flowchart TD
    A([Application Received]) --> B[Feature Pipeline\nfeature_pipeline/features.py]
    B --> C[Fraud Model\nmodels/fraud_detection/predict.py\nGradientBoostingClassifier v1]
    C --> D{fraud_probability?}
    D -- "fraud_probability > 0.60\nTHRESHOLD_REJECT = 0.60" --> E["❌ REJECT\nAA02 — Fraud Indicators\nautomaticDecision=true\nFCRA codes: AA02\n± AA03 if open_accounts < 1\n± AA04 if DTI > 0.43"]
    D -- "0.30 ≤ fraud_probability ≤ 0.60\nTHRESHOLD_REVIEW = 0.30" --> F["🟡 MANUAL_REVIEW\nAA05 — Requires Human Review\nautomaticDecision=false"]
    D -- "fraud_probability < 0.30\nflag = 'continue'" --> G[Credit Risk Model\nmodels/credit_risk/predict.py\nPD score computed]
    G --> H{pd_score}
    H -- "pd_score > 0.10\nPD_THRESHOLD_MEDIUM = 0.10" --> I["❌ REJECT\nAA01 — High PD\nautomaticDecision=true\nFCRA codes: AA01\n± AA03 if open_accounts < 1\n± AA04 if DTI > 0.43"]
    H -- "0.05 ≤ pd_score ≤ 0.10\nPD_THRESHOLD_LOW = 0.05" --> J["✅ APPROVE\nRisk-Priced Rate\nautomaticDecision=true\nreason_codes: empty"]
    H -- "pd_score < 0.05" --> K["✅ APPROVE\nBase Rate\nautomaticDecision=true\nreason_codes: empty"]
    I --> L{Supplemental\nReason Codes?}
    L -- "num_open_accounts < 1\nOPEN_ACCOUNTS_MIN = 1" --> M[Append AA03\nInsufficient Credit History]
    L -- "debt_to_income_ratio > 0.43\nDTI_HIGH_THRESHOLD = 0.43" --> N[Append AA04\nHigh DTI]
    M --> O[Reg B Adverse Action Notice\ncompliance/adverse_action_generator.py\ngenerate_notice → save_notice\nDelivery within 30 days]
    N --> O
    L --> O
    E --> O
    F --> P["HITL Queue\ndecisioning/review_queue.py\nReviewQueue.enqueue()\nSLA clock starts: default 24 h\nautomaticDecision=false"]
    J --> Q[Pricing Engine\nmodels/pricing/engine.py\ncalculate_pricing(pd_score, ...)]
    K --> Q
    Q --> R[Offer Terms Generated\nloan_terms dict\napproved APR, monthly_payment,\nexpected_loss, expected_profit]
    O --> S([Decision Logged\naudit/logger.py\nlog_decision() + hash chain])
    R --> S
    P --> S
```

## Terminal Node Summary

| Node | Decision | automaticDecision | FCRA Codes | Downstream Effect |
|---|---|---|---|---|
| E | REJECT | true | AA02 ± AA03/AA04 | Reg B notice generated + logged |
| F | MANUAL_REVIEW | **false** | AA05 | ReviewQueue.enqueue() called; 24 h SLA clock starts |
| I | REJECT | true | AA01 ± AA03/AA04 | Reg B notice generated + logged |
| J | APPROVE | true | none | Pricing engine called; offer terms generated |
| K | APPROVE | true | none | Pricing engine called; offer terms generated |

## Fraud Threshold Source
**File**: `models/fraud_detection/predict.py` lines 32–33

```python
THRESHOLD_REJECT = 0.60   # fraud_probability > 0.60 → "reject"
THRESHOLD_REVIEW = 0.30   # fraud_probability ≥ 0.30 → "manual_review"
                          # fraud_probability < 0.30 → "continue"
```

These thresholds are **hardcoded** — not configurable via env vars or config registry (⚠️ see GAP-H documentation).

## PD Threshold Source
**File**: `decision_engine/engine.py` lines 60–61

```python
PD_THRESHOLD_LOW    = 0.05   # below → APPROVE at base rate
PD_THRESHOLD_MEDIUM = 0.10   # 0.05–0.10 → APPROVE at risk-priced rate
                             # above → REJECT (AA01)
```

Per-tenant overrides are supported via `policy_overrides` dict in `make_decision()` (keys: `pd_threshold_low`, `pd_threshold`, `dti_high`). Overrides require four-eyes sign-off (GAP-02 control).
