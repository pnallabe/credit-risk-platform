# Credit Risk Platform — Detailed Implementation Architecture

> Generated: 2026-04-25
> Branch: v1.5.0
> All GAPs 01–23 closed + OV-01 through OV-04 closed.

---

## 1. Full Service Topology (Docker Compose)

```mermaid
graph TB
    subgraph BROWSER["Browser / External Clients"]
        AP_UI["Applicant Portal\nlocalhost:3000\nNext.js 14"]
        AD_UI["Analytics Dashboard\nlocalhost:3001\nNext.js 14"]
        LOS_EXT["LOS / Partner API\n(external REST client)"]
    end

    subgraph APIS["FastAPI Services"]
        IAPI["ingestion-api\n:8080\n/v1/ingest/transactions\n/v1/ingest/applications"]
        DAPI["decision-api\n:8081\n/v1/decisions\n/v1/decisions/batch\n/v1/config/*\n/v1/audit/*\n/v1/review/*\n/v1/portal/*"]
        AAPI["ai-agent\n:8082\n/agent/sessions\n/agent/chat (SSE)\n/agent/sessions/{id}/history"]
        SCHED["ai-agent-scheduler\nsidecar\nscheduler.py"]
    end

    subgraph MIDDLEWARE["Middleware Stack (decision-api)"]
        RL_MW["RateLimitMiddleware\n(middleware/rate_limit.py)\nRedis token-bucket · per (tenant,route)"]
        IDP_MW["IdempotencyMiddleware\n(middleware/idempotency.py)\nRedis · 24h TTL · per (tenant, key)"]
        OTEL["OpenTelemetry Instrumentation\n(observability/tracing.py)"]
    end

    subgraph DOMAIN["Domain Packages"]
        DE["decision_engine/\nengine.py · policy_dsl.py\npolicy_version_store.py\npolicy_challenger.py"]
        FP["feature_pipeline/\nfeatures.py · feature_store.py\nlineage.py (OpenLineage)"]
        MOD["models/\ncredit_risk/predict.py (XGBoost)\nfraud_detection/predict.py (IsoForest)\npricing/engine.py\nmodel_loader.py (cached)"]
    end

    subgraph COMPLIANCE["Compliance Domain"]
        RBAC["compliance/rbac.py\n8 roles · 4-eyes SOD\ncro · compliance_officer\nauditor · legal_counsel\nml_developer · ml_validator\ndata_engineer · system_service_acct"]
        COMPENG["compliance/engine.py\nFair lending rule checks\nECOA / FHA / TRID / state usury"]
        PROHIB["compliance/prohibited_variables.py\nprotected-basis column gate\n(gender, race, national_origin…)"]
        AA_GEN["compliance/adverse_action_generator.py\nReg B reason codes\nAA01–AA05 · FCRA"]
        AA_STORE["compliance/adverse_action_store.py\n30-day Reg B deadline tracking"]
        EP_BUILD["compliance/exam_packet_builder.py\n8 components · OCC/CFPB ready\nbuild_ai_agent_audit_component()"]
        EP_APPR["compliance/exam_packet_approval_store.py\npending_approval→approved|rejected\nSOD enforced"]
        RET["compliance/retention_policy.py\nRETENTION_SCHEDULE\n7-year window for ai_agent_audit_log"]
    end

    subgraph AUDIT["Audit Domain"]
        ALOGG["audit/logger.py\nlog_decision() async\nSHA-256 hash-chain\nPII masking (SSN hash, acct last-4)"]
        CVERIF["audit/chain_verifier.py\nverify_chain()\nverify_ai_agent_chain()"]
        OVRLOG["audit/override_log.py\nlog_override()\npolicy_overrides_log table"]
        TGUARD["audit/tenant_guard.py\nassert_same_tenant()\nprevents cross-tenant leakage"]
        CONSIST["audit/consistency_scorer.py\nfairness across similar applicants"]
    end

    subgraph AI_AGENT["AI Agent Pipeline (GAP-19)"]
        direction TB
        PLAN["planner_agent.py\nPlannerAgent\nStage 1: structured AnalysisPlan\n≤5 steps · intent · validation_checks"]
        ORC_AG["specialist_agents.py\nOrchestratorAgent\nStage 2-A: dispatch to specialists"]
        SQL_SP["SQLAnalystAgent\ngenerate SQL → execute → interpret"]
        MET_SP["MetricsAnalystAgent\nAUC/KS/F1 interpretation"]
        DRIFT_SP["DriftAnalystAgent\nPSI/KS · SR 11-7 context"]
        FL_SP["FairLendingAnalystAgent\nDIR/BISG · 80% rule"]
        CHART_SP["ChartGeneratorAgent\nRecharts spec generation"]
        REP_SP["ReportGeneratorAgent\nMarkdown audit-ready reports"]
        SYNTH["SynthesizerAgent\nStage 2-B: ground + combine\nfinal answer + python artifacts"]
        CONF["confidence_scorer.py\nCompute 0–1 score\nGrounding gate (refusal < 0.10)"]
        ART["code_artifact_store.py\nSQL + Python artifact persistence\nSHA-256 fingerprint"]
        AI_AUD["ai_audit_log.py (GNRI-011)\nAppend-only hash-chained\nlog_ai_turn() · 7-year retention"]
    end

    subgraph MONITORING["Monitoring & Observability"]
        DRIFT_M["monitoring/drift_monitor.py\nPSI + KS test · per feature"]
        FL_M["monitoring/fair_lending.py\nDIR · BISG disparate impact"]
        SLA_M["monitoring/referral_sla_monitor.py\nReg B 30-day SLA breach"]
        ALERT["monitoring/alert_router.py\nEmail/Slack · SMTP TLS"]
        CC_MON["monitoring/cc_portfolio_monitor.py\nCC pd monitor · cc valuation"]
    end

    subgraph DATA_STORES["Data Stores"]
        PG1[("PostgreSQL :5432\nLoans DB\nloan_applications · decisions\naudits · agent_sessions")]
        PG2[("PostgreSQL :5433\nTransactions DB\nbank_accounts · payments · fraud")]
        PG3[("PostgreSQL :5434\nCredit Cards DB\ncard_accounts · statements")]
        REDIS_DB[("Redis :6379\nRate-limit counters\nIdempotency cache\nSession state")]
        BQDB[("Google BigQuery\nAnalytics Warehouse\ndecisions · audit_logs · features")]
        MLFLOW_DB[("MLflow :5000\nModel Registry\nExperiment tracking\nArtifact versioning")]
    end

    subgraph ETL["ETL & Data Quality"]
        PUBSUB_ETL["etl/pubsub_consumer.py\nGoogle Pub/Sub subscriber\nexponential backoff retry ×3"]
        DQ["data_quality/expectations.py\nGreat Expectations validation"]
        LIN["feature_pipeline/lineage.py\nOpenLineage / Marquez"]
        DC["data_contracts/registry.py\nContract versioning\ndata_contracts/v1/"]
    end

    subgraph INFRA_GCP["GCP Infrastructure"]
        CR["Cloud Run\ndecision-api · ai-agent\ningestion-api · portals"]
        SM["Secret Manager\nJWT_SECRET · API keys"]
        KMS["Cloud KMS\nEncryption at rest"]
        GCS_B["Cloud Storage\nRaw ingestion payloads\nModel artifacts"]
        VA["Vertex AI\nFeature Store · Pipelines"]
    end

    %% External → API
    AP_UI -->|"REST"| DAPI
    AD_UI -->|"REST + SSE"| DAPI
    AD_UI -->|"REST + SSE"| AAPI
    LOS_EXT -->|"POST /v1/decisions"| DAPI
    LOS_EXT -->|"POST /v1/ingest/*"| IAPI

    %% Middleware chain
    DAPI --> RL_MW --> IDP_MW --> OTEL

    %% Decision-API → Domain
    DAPI --> RBAC
    DAPI --> DE
    DAPI --> FP
    DAPI --> MOD
    DAPI --> PROHIB
    DAPI --> ALOGG
    DAPI --> AA_GEN
    DAPI --> AA_STORE
    DAPI --> EP_BUILD
    DAPI --> EP_APPR
    DAPI --> OVRLOG

    %% AI Agent pipeline
    AAPI --> PLAN
    PLAN --> ORC_AG
    ORC_AG --> SQL_SP
    ORC_AG --> MET_SP
    ORC_AG --> DRIFT_SP
    ORC_AG --> FL_SP
    ORC_AG --> CHART_SP
    ORC_AG --> REP_SP
    ORC_AG --> SYNTH
    SYNTH --> CONF
    CONF --> ART
    ART --> AI_AUD
    AAPI --> AI_AUD
    SQL_SP --> PROHIB

    %% Ingestion → Pub/Sub
    IAPI --> PUBSUB_ETL
    PUBSUB_ETL --> PG1
    IAPI --> DQ

    %% Data flows
    ALOGG --> PG1
    AI_AUD --> PG1
    FP --> PG1
    CVERIF --> PG1
    OVRLOG --> PG1
    AA_STORE --> PG1
    EP_APPR --> PG1
    REDIS_DB --> RL_MW
    REDIS_DB --> IDP_MW

    %% BigQuery
    DAPI --> BQDB
    AAPI --> BQDB

    %% MLflow
    MOD --> MLFLOW_DB

    %% Monitoring
    DRIFT_M --> ALERT
    FL_M --> ALERT
    SLA_M --> ALERT
    SCHED --> DRIFT_M
    SCHED --> SLA_M

    %% GCP
    IAPI --> GCS_B
    SM --> DAPI
    SM --> AAPI
    KMS --> PG1
```

---

## 2. Decision API — Route Map

```mermaid
mindmap
  root((Decision API\n:8081))
    Decisioning
      POST /v1/decisions
      POST /v1/decisions/batch
      GET  /v1/batch/status/{id}
      GET  /v1/batch/results/{id}
    Config & Policy
      GET/PUT /v1/config/policy
      POST /v1/config/policy/stage
      POST /v1/config/policy/approve
      GET  /v1/config/policy/versions
      GET  /v1/config/policy/versions/{v}
      POST /v1/config/policy/rollback
      POST /v1/config/policy/challenge
    Audit & Compliance
      POST /v1/audit/generate-package
      POST /v1/audit/packets/{id}/approve
      POST /v1/audit/packets/{id}/reject
      GET  /v1/audit/packets/{id}
      GET  /v1/audit/packets/pending
      GET  /v1/audit/chain/verify
      GET  /v1/audit/replay/{id}
    Review Queue
      GET  /v1/review/queue
      POST /v1/review/{id}/claim
      POST /v1/decisions/{id}/override
    Adverse Action
      GET  /v1/adverse-action/pending
      GET  /v1/adverse-action/{id}
      GET  /v1/adverse-action/
      POST /v1/adverse-action/{id}/mark-delivered
    Erasure
      POST /v1/erasure/request
      GET  /v1/erasure/requests
    Portal
      POST /v1/portal/apply
      GET  /v1/portal/status/{id}
    Health
      GET  /v1/health
      GET  /v1/health/dependencies
      GET  /v1/metrics
```

---

## 3. AI Agent — Specialist Dispatch Logic

```mermaid
flowchart TD
    Q["User Query\n(POST /agent/chat)"] --> BUDGET["Token Budget Check\n(OV-03: MAX_TOKENS_PER_QUERY\nCOST_CEILING_USD)"]
    BUDGET -->|"over budget"| ERR["SSE: budget_exceeded error"]
    BUDGET -->|"ok"| PLANNER["PlannerAgent\nSingle LLM call → AnalysisPlan JSON\n≤5 steps, ≥1 validation_check"]
    PLANNER --> EMIT_PLAN["SSE: {plan: AnalysisPlan}"]
    PLANNER --> ORC["OrchestratorAgent\nastream(plan, query, history)"]

    ORC -->|"step.tool == sql_query_tool"| SQL_GEN["_generate_sql_for_step()\nLLM generates SELECT query"]
    SQL_GEN --> SQL_EXEC["_sql_query_tool()\nProhibited variable gate\nSHA-256 query_hash + result_hash\n__GROUNDED__ prefix"]
    SQL_EXEC --> SQL_INTERP["SQLAnalystAgent\n_interpret(): domain LLM call\nOutputs ```sql block"]

    ORC -->|"step.tool == metrics_tool"| MET_EXEC["_metrics_tool()"]
    MET_EXEC --> MET_INTERP["MetricsAnalystAgent\nAUC/KS/F1 vs thresholds\n(AUC<0.75, KS<0.30 flagged)"]

    ORC -->|"step.tool == drift_report_tool"| DR_EXEC["_drift_report_tool()"]
    DR_EXEC --> DR_INTERP["DriftAnalystAgent\nPSI thresholds\n(>0.25 = significant drift)"]

    ORC -->|"step.tool == fair_lending_tool"| FL_EXEC["_fair_lending_tool()"]
    FL_EXEC --> FL_INTERP["FairLendingAnalystAgent\nDIR < 0.80 = disparate impact flag"]

    SQL_INTERP --> SYNTH["SynthesizerAgent\nStreamingLLM: astream()\nCombines all specialist outputs\nGrounded answer only"]
    MET_INTERP --> SYNTH
    DR_INTERP --> SYNTH
    FL_INTERP --> SYNTH

    SYNTH -->|"token"| SSE_TOK["SSE: {token: ...}"]
    SYNTH -->|"complete"| CONF_CALC["compute_confidence()\nrow_count · has_sql · tool_diversity\n0.0–1.0 score"]

    CONF_CALC -->|"score < 0.10"| REFUSAL["SSE: {refusal: true}\n(Grounding Gate)"]
    CONF_CALC -->|"score >= 0.10"| ARTIFACTS["store_artifact()\nSQL + Python → code_artifact_store\nSHA-256 fingerprint"]
    ARTIFACTS --> AUDIT_LOG["log_ai_turn()\nai_agent_audit_log\nHash-chained · GNRI-011"]
    AUDIT_LOG --> META["SSE: {metadata: {\nconfidence_score,\ngrounded,\ncode_artifacts,\ndata_lineage\n}}"]
    META --> DONE["SSE: [DONE]"]
```

---

## 4. Immutable Audit Chain — Hash Algorithm

```mermaid
flowchart LR
    subgraph GENESIS["Genesis Record"]
        G["previous_hash = 'GENESIS'\nrecord_hash = SHA256(canonical_0)"]
    end

    subgraph REC1["Record N"]
        R1["log_id · logged_at\nquery_text · result_hash\nconfidence_score · answer_text\nprevious_hash = record_hash_N-1\nrecord_hash = SHA256(\n  prev | log_id | logged_at | canonical\n)"]
    end

    subgraph REC2["Record N+1"]
        R2["previous_hash = record_hash_N\nrecord_hash = SHA256(...)"]
    end

    subgraph VERIF["verify_ai_agent_chain()"]
        V["Recompute each record_hash\nCompare to stored value\nAny mismatch → TAMPERED"]
    end

    GENESIS -->|"record_hash_0"| REC1
    REC1 -->|"record_hash_N"| REC2
    REC2 --> VERIF
```

---

## 5. Multi-Tenant Isolation Model

```mermaid
graph TD
    subgraph T1["Tenant A"]
        T1_APP["Applications\ntenant_id = T1"]
        T1_AUD["Audit Records\ntenant_id = T1"]
        T1_FEAT["Feature Vectors\ntenant_id = T1"]
    end

    subgraph T2["Tenant B"]
        T2_APP["Applications\ntenant_id = T2"]
        T2_AUD["Audit Records\ntenant_id = T2"]
        T2_FEAT["Feature Vectors\ntenant_id = T2"]
    end

    GUARD["audit/tenant_guard.py\nassert_same_tenant()\nRaises TenantIsolationError\nif entity.tenant_id != request.tenant_id"]

    JWT_AUTH["JWT Token\n{ tenant_id, role, sub }"]

    RBAC["compliance/rbac.py\nrequire_role()\nhas_permission()\nfour_eyes_check()"]

    JWT_AUTH --> RBAC
    RBAC --> GUARD
    GUARD --> T1
    GUARD --> T2
    T1 -.->|"blocked"| T2
```

---

## 6. Compliance Exam Packet — 8 Components

```mermaid
flowchart LR
    TRIGGER["POST /v1/audit/generate-package\n{tenant_id, exam_period}"] --> BUILD["exam_packet_builder.py\nbuild_exam_packet()"]

    BUILD --> C1["Component 1\nDecision Summary\n(approve/reject/manual rates)"]
    BUILD --> C2["Component 2\nAdverse Action Log\n(Reg B / FCRA notices)"]
    BUILD --> C3["Component 3\nModel Documentation\n(SR 11-7 model card)"]
    BUILD --> C4["Component 4\nFair Lending Report\n(DIR / BISG / 80% rule)"]
    BUILD --> C5["Component 5\nData Drift Report\n(PSI / KS per feature)"]
    BUILD --> C6["Component 6\nAudit Chain Verification\n(hash integrity check)"]
    BUILD --> C7["Component 7\nPolicy Override Log\n(four-eyes verified)"]
    BUILD --> C8["Component 8\nAI Agent Audit Appendix\n(ai_agent_audit_log)\nSQL artifacts · confidence dist\nGrounding rate · chain verify"]

    C1 & C2 & C3 & C4 & C5 & C6 & C7 & C8 --> PENDING["status = pending_approval\n(exam_packet_approvals table)"]
    PENDING --> APPROVE["POST /v1/audit/packets/{id}/approve\napprover ≠ generator (SOD)\nApproval event → audit log"]
    APPROVE --> PDF["exam_packet_pdf.py\nGenerate PDF export\n8-section structured document"]
```

---

## 7. Data Store Schema Summary

```mermaid
erDiagram
    loan_applications {
        uuid id PK
        text tenant_id
        uuid applicant_id
        integer credit_score
        decimal income
        decimal dti
        decimal loan_amount
        text status
        timestamp created_at
        text decision
        boolean fraud_flag
    }

    decisions {
        uuid id PK
        uuid application_id FK
        text tenant_id
        text outcome
        jsonb reason_codes
        decimal confidence_score
        text model_version
        timestamp decided_at
    }

    audit_log {
        uuid id PK
        text event_type
        uuid entity_id
        text actor
        jsonb details
        timestamp created_at
        text record_hash
        text previous_hash
    }

    ai_agent_audit_log {
        text log_id PK
        text session_id
        text turn_id UK
        text tenant_id
        text persona
        text query_text
        text plan_text
        text sql_executed
        text result_hash
        text query_hash
        text confidence_label
        decimal confidence_score
        boolean grounded
        text record_hash
        text previous_hash
        text logged_at
    }

    code_artifacts {
        text artifact_id PK
        text session_id
        text turn_id
        text artifact_type
        text content_hash
        text content
        text source_table
        timestamp created_at
    }

    loan_applications ||--o{ decisions : "has"
    decisions ||--o{ audit_log : "logged in"
    ai_agent_audit_log ||--o{ code_artifacts : "produces"
```

---

## 8. Port Reference

| Service | Port | Protocol | Purpose |
|---|---|---|---|
| `ingestion-api` | 8080 | REST | Data ingest, Pub/Sub publish |
| `decision-api` | 8081 | REST | Underwriting, audit, compliance |
| `ai-agent` | 8082 | REST + SSE | Multi-agent AI query pipeline |
| `applicant-portal` | 3000 | HTTP | Loan application UI (Next.js) |
| `analytics-dashboard` | 3001 | HTTP | Internal analytics UI (Next.js) |
| `dashboard` | 8501 | HTTP | Streamlit portfolio dashboard (legacy) |
| `mlflow` | 5000 | HTTP | ML experiment tracking |
| `postgres` (Loans) | 5432 | TCP | Primary OLTP — decisions, audit |
| `postgres-transactions` | 5433 | TCP | Transactions domain |
| `postgres-cards` | 5434 | TCP | Credit cards domain |
| `redis` | 6379 | TCP | Rate limiting, idempotency cache |

---

## 9. Key Security Controls

```mermaid
mindmap
  root((Security Controls))
    Identity & Access
      JWT_SECRET mandatory non-empty at boot
      8-role RBAC (compliance/rbac.py)
      Four-eyes enforcement (SOD)
      Per-tenant isolation (tenant_guard.py)
    Data Protection
      PII masking in audit_log (SSN hash, acct last-4)
      TLS 1.2+ / 1.3 on all connections
      mTLS for credit bureau clients
      Cloud KMS encryption at rest
      Secret Manager for credentials
    API Security
      Redis token-bucket rate limiting per (tenant, route)
      Idempotency middleware prevents duplicate audit entries
      Prohibited variable gate (ECOA/FHA protected bases)
      SQL injection prevention (SELECT-only gate + parameterized queries)
      OpenAI API key startup assertion (OV-03)
    Supply Chain
      gitleaks (.gitleaks.toml) — secrets scanning
      No eval() in policy path (Policy DSL replaces decision_engine_agent)
    Audit & Compliance
      Immutable append-only audit log (SHA-256 hash chain)
      AI agent audit log (GNRI-011, 7-year retention)
      Exam packet HITL approval gate
      Reg B 30-day adverse action deadline monitoring
      OCC/CFPB exam packet — 8 components, PDF export
```
