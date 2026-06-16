# Credit Risk Platform — High-Level Layered Architecture

> Generated: 2026-04-25
> Branch: v1.5.0
> Status: Reflects implemented state as of GAP-19 closure.

---

## 6-Layer Stack

```mermaid
block-beta
  columns 1

  block:experience["EXPERIENCE LAYER"]
    columns 3
    P["Applicant Portal\nNext.js :3000\n(Public)"]
    A["Analytics Dashboard\nNext.js :3001\n(Internal RBAC)"]
    S["Streamlit Dashboard\n:8501\n(Legacy / Internal)"]
  end

  space

  block:gateway["API GATEWAY LAYER"]
    columns 3
    G1["JWT Auth + RBAC\n8 Roles · 4-eyes\n(compliance/rbac.py)"]
    G2["Rate Limiting\nRedis token-bucket\n(middleware/rate_limit.py)"]
    G3["Idempotency\nRedis-backed\n(middleware/idempotency.py)"]
  end

  space

  block:services["APPLICATION SERVICES LAYER"]
    columns 3
    D["Decision API\nFastAPI :8081\nSingle + Batch underwriting"]
    AI["AI Agent Service\nFastAPI :8082\nMulti-agent pipeline + SSE"]
    ING["Ingestion API\nFastAPI :8080\nData ingest + Pub/Sub publish"]
  end

  space

  block:orchestration["EVENT & ORCHESTRATION LAYER"]
    columns 3
    ORCH["Multi-Agent Orchestrator\nPlanner → Specialists → Synthesizer\n(ai-agent/src/specialist_agents.py)"]
    PS["Google Pub/Sub\nEvent bus for ingestion\n(etl/pubsub_consumer.py)"]
    SCHED["Scheduler Sidecar\nDrift alerts · Reg B deadlines\n(ai-agent/src/scheduler.py)"]
  end

  space

  block:data["DATA & INTELLIGENCE LAYER"]
    columns 3
    FS["Feature Store\nPIT-correct · SHA-256 audit\n(feature_pipeline/feature_store.py)"]
    AUD["Immutable Audit Log\nHash-chain · PII-masked\n(audit/logger.py)"]
    BQ["BigQuery Warehouse\nAsync writer · 3 domain DBs\n(db/bigquery_client.py)"]
  end

  space

  block:infra["INFRASTRUCTURE & SECURITY"]
    columns 3
    GCP["GCP: Cloud Run · Secret Manager\nCloud KMS · Vertex AI"]
    DB["PostgreSQL ×3 + Redis\nLoans :5432 · Txns :5433 · Cards :5434"]
    OBS["OpenTelemetry Tracing\ngitleaks · TLS 1.2+ · mTLS bureaus"]
  end
```

---

## Layer-to-Layer Data Flow

```mermaid
flowchart TD
    subgraph EXP["EXPERIENCE LAYER"]
        direction LR
        AP["Applicant Portal\n:3000"]
        AD["Analytics Dashboard\n:3001"]
    end

    subgraph GW["API GATEWAY"]
        direction LR
        JWT["JWT + RBAC\n(compliance/rbac.py)"]
        RL["Rate Limit\n(Redis token-bucket)"]
        IDP["Idempotency\n(Redis cache)"]
    end

    subgraph APP["APPLICATION SERVICES"]
        DAPI["Decision API\n:8081"]
        AAPI["AI Agent\n:8082"]
        IAPI["Ingestion API\n:8080"]
    end

    subgraph ORCH_LAYER["ORCHESTRATION"]
        PLN["PlannerAgent\n(planner_agent.py)"]
        ORC["OrchestratorAgent\n(specialist_agents.py)"]
        SYN["SynthesizerAgent"]
    end

    subgraph DATA["DATA & INTELLIGENCE"]
        FEAT["Feature Store\n(feature_pipeline/)"]
        AUDITLOG["Audit Log\n(audit/logger.py)"]
        BQW["BigQuery Writer\n(db/bigquery_client.py)"]
        MLFLOW["MLflow Model Registry"]
    end

    subgraph INFRA["INFRASTRUCTURE"]
        PG1[("PostgreSQL\nLoans :5432")]
        PG2[("PostgreSQL\nTransactions :5433")]
        PG3[("PostgreSQL\nCards :5434")]
        REDIS[("Redis :6379")]
        PUBSUB["Google Pub/Sub"]
    end

    AP -->|REST POST /v1/decisions| GW
    AD -->|REST + SSE| GW
    GW --> DAPI
    GW --> AAPI
    GW --> IAPI

    DAPI -->|"compute features"| FEAT
    DAPI -->|"load model"| MLFLOW
    DAPI -->|"log_decision()"| AUDITLOG
    DAPI -->|"write async"| BQW

    AAPI --> PLN
    PLN -->|"AnalysisPlan"| ORC
    ORC -->|"sql_query_tool"| PG1
    ORC -->|"metrics/drift/fair-lending tools"| FEAT
    ORC --> SYN
    SYN -->|"assembled_answer + python artifacts"| AAPI
    AAPI -->|"log_ai_turn()"| AUDITLOG

    IAPI -->|"publish events"| PUBSUB
    PUBSUB -->|"ETL consumer"| PG1

    AUDITLOG --> PG1
    FEAT --> PG1
    BQW -->|"async sink"| GCP_BQ["Google BigQuery"]
    REDIS --> GW
```

---

## Decision Path (Single Application)

```mermaid
sequenceDiagram
    participant LOS as LOS / Portal
    participant GW as API Gateway<br/>(JWT + Rate Limit)
    participant DAPI as Decision API<br/>:8081
    participant FP as Feature Pipeline
    participant DE as Decision Engine
    participant COMP as Compliance<br/>(adverse_action, rbac)
    participant AUD as Audit Logger<br/>(hash-chain)
    participant BQ as BigQuery

    LOS->>GW: POST /v1/decisions {application}
    GW->>GW: JWT verify + RBAC check + rate limit
    GW->>DAPI: forward request
    DAPI->>FP: compute_features(application)
    FP-->>DAPI: feature_vector
    DAPI->>DE: make_decision(feature_vector, policy)
    DE-->>DAPI: outcome (APPROVE/REJECT/MANUAL_REVIEW/CONDITIONAL)
    alt REJECT
        DAPI->>COMP: generate_adverse_action(reason_codes)
        COMP-->>DAPI: AA notice (ECOA/FCRA codes)
    end
    DAPI->>AUD: log_decision(SHA-256 hash-chain)
    DAPI->>BQ: async write decision event
    DAPI-->>LOS: DecisionResponse {outcome, reason_codes, confidence}
```

---

## AI Agent Multi-Agent Pipeline

```mermaid
sequenceDiagram
    participant UI as Analytics Dashboard
    participant AAPI as AI Agent API<br/>:8082
    participant PLN as PlannerAgent<br/>(Stage 1)
    participant ORC as OrchestratorAgent<br/>(Stage 2)
    participant SQL as SQLAnalystAgent
    participant MET as MetricsAnalystAgent
    participant SYN as SynthesizerAgent
    participant LOG as AI Audit Log<br/>(GNRI-011)

    UI->>AAPI: POST /agent/chat {session_id, message}
    AAPI->>PLN: plan(message)
    PLN-->>AAPI: AnalysisPlan {intent, steps[], validation_checks}
    AAPI-->>UI: SSE: {plan: ...}

    loop For each plan step
        ORC->>SQL: run(step, sql_query_tool, generated_sql)
        SQL->>SQL: execute SELECT + interpret with LLM
        SQL-->>ORC: SpecialistResult {interpretation, sql_executed}
        AAPI-->>UI: SSE: {specialist_complete: step_id}

        ORC->>MET: run(step, metrics_tool)
        MET-->>ORC: SpecialistResult {interpretation}
    end

    ORC->>SYN: synthesize(all_specialist_results)
    SYN-->>AAPI: final_answer + python_code[]
    AAPI-->>UI: SSE: {token: ...} (streaming)

    AAPI->>LOG: log_ai_turn(hash-chain, confidence, sql, artifacts)
    AAPI-->>UI: SSE: {metadata: {confidence_score, grounded, code_artifacts}}
    AAPI-->>UI: SSE: [DONE]
```

---

## Compliance & Governance Subsystem

```mermaid
graph LR
    subgraph COMP_ENGINE["Compliance Engine"]
        RB["RBAC\n(compliance/rbac.py)\n8 roles · 4-eyes · SOD"]
        PV["Prohibited Variables\n(prohibited_variables.py)\nECOA/FHA gate"]
        AA["Adverse Action\n(adverse_action_generator.py)\nReg B / FCRA codes"]
        EP["Exam Packet Builder\n(exam_packet_builder.py)\n8 components · PDF"]
        EPA["Exam Packet Approval\n(exam_packet_approval_store.py)\npending→approved state machine"]
        RP["Retention Policy\n(retention_policy.py)\n7-year schedule"]
        ER["Erasure Requests\n(erasure_request.py)\nGDPR/CCPA"]
    end

    subgraph AUDIT_ENGINE["Audit Engine"]
        AL["Audit Logger\n(audit/logger.py)\nSHA-256 hash-chain"]
        CV["Chain Verifier\n(audit/chain_verifier.py)"]
        OL["Override Log\n(audit/override_log.py)"]
        TG["Tenant Guard\n(audit/tenant_guard.py)"]
        AI_LOG["AI Audit Log\n(ai_agent/src/ai_audit_log.py)\nGNRI-011 · hash-chained"]
    end

    subgraph MON["Monitoring & Fair Lending"]
        DR["Drift Monitor\n(monitoring/drift_monitor.py)\nPSI + KS"]
        FL["Fair Lending\n(monitoring/fair_lending.py)\nDIR / BISG"]
        SLA["Referral SLA Monitor\n(monitoring/referral_sla_monitor.py)"]
        AR["Alert Router\n(monitoring/alert_router.py)\nEmail + Slack TLS"]
    end

    RB --> AA
    PV --> AL
    AA --> AL
    EP --> EPA
    EPA --> AL
    AL --> CV
    DR --> AR
    FL --> AR
    SLA --> AR
    AI_LOG --> CV
```
