# Multi-Agent Credit Risk Platform

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                   CREDIT RISK PLATFORM — AGENT MAP                 │
├────────────────────────────────────────────────────────────────────┤
│                                                                    │
│  [Raw Applicant JSON]                                              │
│         │                                                          │
│  ┌──────▼──────────────────┐                                       │
│  │  1. DataIngestionAgent   │  Schema validation, DQ rules,        │
│  │     agents/              │  thin-file detection, quarantine      │
│  └──────┬──────────────────┘                                       │
│         │  ValidatedRecord[]                                        │
│  ┌──────▼──────────────────┐                                       │
│  │  2. FeatureEngineering   │  11 credit features + thin-file      │
│  │     Agent               │  alt-data composite score             │
│  └──────┬──────────────────┘                                       │
│         │  FeatureVector[]                                          │
│  ┌──────▼──────────────────┐    ┌──────────────────────────────┐   │
│  │  3. RiskModelingAgent   │◄───│  8. ExperimentationAgent     │   │
│  │     LightGBM PD model   │    │     Champion/Challenger       │   │
│  │     Fraud GBM model     │    │     A/B routing + stat tests  │   │
│  │     Pricing engine      │    └──────────────────────────────┘   │
│  └──────┬──────────────────┘                                       │
│         │  ModelScores[]                                            │
│  ┌──────▼──────────────────┐                                       │
│  │  4. DecisionEngineAgent  │  Config-driven hard rules +          │
│  │     APPROVE/REJECT/       │  score cutoffs + FCRA reason codes  │
│  │     MANUAL_REVIEW         │                                     │
│  └──────┬──────────────────┘                                       │
│         │  CreditDecision[]                                         │
│  ┌──────▼──────────────────┐                                       │
│  │  5. ExplainabilityAgent  │  SHAP-based explanations +           │
│  │                          │  FCRA adverse action notices         │
│  └──────┬──────────────────┘                                       │
│         │  ExplanationRecord[]                                      │
│  ┌──────▼──────────────────┐                                       │
│  │  6. API Agent            │  FastAPI gateway                     │
│  │     agents/api_agent.py  │  POST /v1/score, /v1/score/batch     │
│  └─────────────────────────┘                                       │
│                                                                    │
│  ┌──────────────────────────┐   (scheduled / async)               │
│  │  7. MonitoringAgent       │  PSI drift + Fair Lending (DIR)     │
│  │     monitoring/           │  + Decision distribution alerts     │
│  └──────────────────────────┘                                      │
│                                                                    │
└────────────────────────────────────────────────────────────────────┘
```

## Agent Descriptions

| # | Agent | File | Domain | Key Output |
|---|-------|------|--------|------------|
| 1 | Data Ingestion | `agents/data_ingestion_agent.py` | Data Engineering | `ValidatedRecord[]` |
| 2 | Feature Engineering | `agents/feature_engineering_agent.py` | ML Platform | `FeatureVector[]` |
| 3 | Risk Modeling | `agents/risk_modeling_agent.py` | ML / MRM | `ModelScores[]` |
| 4 | Decision Engine | `agents/decision_engine_agent.py` | Credit Policy | `CreditDecision[]` |
| 5 | Explainability | `agents/explainability_agent.py` | Compliance / MRM | `ExplanationRecord[]` |
| 6 | API | `agents/api_agent.py` | Platform Eng. | FastAPI endpoints |
| 7 | Monitoring | `agents/monitoring_agent.py` | MLOps | Drift + fairness alerts |
| 8 | Experimentation | `agents/experimentation_agent.py` | Risk Strategy | Experiment reports |

## Interface Contracts

All agents communicate through typed schemas defined in `schemas/contracts.py`.
No raw dicts cross agent boundaries.

```
ApplicantInput  →  DataIngestionAgent  →  ValidatedRecord
ValidatedRecord →  FeatureEngineeringAgent → FeatureVector
FeatureVector   →  RiskModelingAgent   →  ModelScores
ModelScores     →  DecisionEngineAgent →  CreditDecision
CreditDecision  →  ExplainabilityAgent →  ExplanationRecord
```

## Config-Driven Design

All thresholds, rules, and parameters live in `config/agent_config.yaml`:

```yaml
decision_engine:
  score_cutoffs:
    approve_max_pd: 0.05    # ← change here, not in code
    review_max_pd: 0.10
  hard_rules:
    - rule_id: HR-004
      condition: "dti > 0.55"
      action: REJECT
      reason_code: AA04
```

## Running the Platform

### End-to-End Pipeline (CLI)

```bash
# Run with 4 built-in sample applicants (including thin-file cases)
python run_end_to_end.py

# Score a single applicant from JSON
python run_end_to_end.py --input data/sample_applicant.json

# Batch score from CSV
python run_end_to_end.py --batch data/raw/loan_applications.csv --output /tmp/decisions.json

# Champion/Challenger experiment
python run_end_to_end.py --use-challenger --experiment-id exp_2026_q2
```

### API Server

```bash
# Start the unified FastAPI service
uvicorn agents.api_agent:app --host 0.0.0.0 --port 8080

# Score a single applicant
curl -X POST http://localhost:8080/v1/score \
  -H "X-API-Key: dev-key-12345" \
  -H "Content-Type: application/json" \
  -d @data/sample_applicant.json

# Batch score
curl -X POST http://localhost:8080/v1/score/batch \
  -H "X-API-Key: dev-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"applicants": [...]}'
```

### Programmatic Usage

```python
from orchestration.pipeline import CreditRiskPipeline

pipeline = CreditRiskPipeline.from_config()

run = pipeline.run(applicant_dicts=[
    {
        "application_id": "APP-001",
        "loan_amount": 5000,
        "loan_purpose": "personal",
        "loan_term_months": 36,
        "annual_income": 45000,
        "employment_status": "employed",
        # thin-file alt data
        "rent_payment_months": 18,
        "mobile_data_score": 0.7,
    }
])

print(run.final_payload["decisions"])
print(run.final_payload["explanations"])
```

## Thin-File Underwriting

When `credit_score`, `num_open_accounts`, or `months_since_last_delinquency` are null:

1. `DataIngestionAgent` tags record as thin-file (warning, not rejection)
2. `FeatureEngineeringAgent` computes `thin_file_alt_score` from:
   - On-time rent payments (`rent_payment_months`)
   - On-time utility payments (`utility_payment_months`)
   - Mobile usage score (`mobile_data_score`)
   - Bank account tenure (`bank_account_age_months`)
   - Cash-flow stability (`avg_monthly_cash_inflow / outflow`)
3. Alt-data score boosts `income_stability_score` for thin-file applicants
4. Models score using the augmented features
5. `ExplainabilityAgent` flags `thin_file_signals_used: true` in explanation

## Regulatory Compliance (SR 11-7)

| Requirement | Implementation |
|-------------|----------------|
| Model documentation | `docs/` + inline docstrings |
| Performance thresholds | `min_auc: 0.75`, `min_ks: 0.35` in config |
| Champion/challenger | `ExperimentationAgent` + chi-squared significance test |
| Adverse action | FCRA reason codes AA01-AA05 in `ExplainabilityAgent` |
| Fair lending | DIR + approval parity in `MonitoringAgent` |
| Audit trail | Every decision logged with reason codes + scores |
| Drift monitoring | PSI + KS in `MonitoringAgent` |

## Folder Structure

```
credit-risk-platform/
├── agents/                    ← NEW: all agent modules
│   ├── __init__.py
│   ├── base.py                ← BaseAgent, AgentResult
│   ├── data_ingestion_agent.py
│   ├── feature_engineering_agent.py
│   ├── risk_modeling_agent.py
│   ├── decision_engine_agent.py
│   ├── explainability_agent.py
│   ├── api_agent.py           ← FastAPI service
│   ├── monitoring_agent.py
│   └── experimentation_agent.py
├── orchestration/             ← NEW: pipeline + message bus
│   ├── __init__.py
│   ├── pipeline.py            ← CreditRiskPipeline (DAG orchestrator)
│   └── message_bus.py         ← Agent communication protocol
├── schemas/                   ← NEW: typed I/O contracts
│   ├── __init__.py
│   └── contracts.py           ← Pydantic models for all agent I/O
├── config/                    ← NEW: externalized configuration
│   └── agent_config.yaml      ← All thresholds, rules, and tuning knobs
├── run_end_to_end.py          ← NEW: CLI end-to-end runner
├── data/
│   └── sample_applicant.json  ← NEW: thin-file example
├── decision_engine/           ← EXISTING (wrapped by DecisionEngineAgent)
├── feature_pipeline/          ← EXISTING (wrapped by FeatureEngineeringAgent)
├── models/                    ← EXISTING (wrapped by RiskModelingAgent)
├── monitoring/                ← EXISTING (wrapped by MonitoringAgent)
├── explainability/            ← EXISTING (wrapped by ExplainabilityAgent)
└── ingestion-api/             ← EXISTING (extended by API Agent)
```
