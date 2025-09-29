
# AI Risk Workflow Platform

## 1. Project Overview

We are building a **multi-agent AI workflow** for credit risk management that:
- Ingests consumer & SMB financial data.
- Classifies and analyzes cashflows.
- Scores creditworthiness.
- Detects fraud & anomalies.
- Produces decisions with **human-in-the-loop (HITL)** review.
- Provides full compliance, audit trail, and explainability.

**Target Users**: banks, fintechs, and SMB lenders.

---

## 2. Objectives

- ✅ Create scalable ingestion pipelines on GCP.  
- ✅ Engineer underwriting features from real & synthetic transaction data.  
- ✅ Develop modular AI agents (classification, scoring, fraud, decisioning).  
- ✅ Build a human-in-the-loop review dashboard.  
- ✅ Ensure compliance (fairness, audit, logging).  
- ✅ Package as **API-first SaaS** for lenders.  

---

## 3. High-Level Architecture

```
Data Sources → Ingestion API (Cloud Run) → GCS (Raw) → Dataflow → BigQuery (Bronze/Silver) → dbt (Gold Features) → Vertex AI (Agents + Feature Store) → Decisioning API → HITL Dashboard → BigQuery (Audit & Feedback)
```

**Core GCP Services:**
- Cloud Run – APIs + lightweight services.  
- GCS – raw/landing storage.  
- Pub/Sub + Eventarc – event-driven pipelines.  
- Dataflow (Beam) – streaming ETL.  
- BigQuery + dbt – data warehouse + transformations.  
- Vertex AI Feature Store & Pipelines – ML training, serving, monitoring.  
- Secret Manager + KMS – credentials + encryption.  
- Looker Studio – monitoring dashboards.  

---

## 4. Phased Project Plan

### Phase 1 – Foundation & Environment Setup (Weeks 1–2)
- Create GCP Project + enable APIs.  
- Set up GitHub repo + CI/CD (Cloud Build).  
- Create GCS buckets (`raw`, `processed`, `logs`).  
- Define service accounts & IAM roles.  

### Phase 2 – Data Ingestion (Weeks 3–4)
- Build ingestion API (FastAPI → Cloud Run).  
- Store raw payloads in GCS.  
- Set up Eventarc → Pub/Sub → Dataflow pipeline (Landing → Bronze).  
- Write schema-normalized data to BigQuery.  

### Phase 3 – Transformation & Enrichment (Weeks 5–6)
- Create dbt models for Bronze → Silver → Gold.  
- Dedup, enrich transactions (MCC, balances).  
- Add Great Expectations tests for quality.  

### Phase 4 – Feature Engineering (Weeks 7–8)
- Engineer cashflow features (inflows/outflows, volatility).  
- Register features in Vertex AI Feature Store.  
- Create offline & online feature views.  

### Phase 5 – AI Agents (Weeks 9–12)
- Transaction Classification Agent (XGBoost).  
- Credit Scoring Agent (Logistic Regression / XGBoost).  
- Fraud Detection Agent (Isolation Forest).  
- Decisioning Agent (rules + ensemble).  

### Phase 6 – HITL Dashboard (Weeks 13–14)
- Build reviewer UI (Streamlit/Gradio → Cloud Run).  
- Log overrides in BigQuery `feedback` table.  
- Integrate feedback loop into retraining.  

### Phase 7 – Compliance, Monitoring & Scaling (Weeks 15–16)
- Build audit log (BigQuery + Looker dashboard).  
- Add Cloud Monitoring alerts (pipeline health, data freshness).  
- Harden security (VPC-SC, CMEK, Secret Manager).  
- Document model fairness testing (bias checks).  

---

## 5. Task Breakdown (Epic → User Stories → Tasks)

See Monday.com import files for detailed breakdown.

- Epic 1: Foundation (GCP project, repo, storage).  
- Epic 2: Ingestion (API, Eventarc, Dataflow).  
- Epic 3: Transformation (dbt, GE checks).  
- Epic 4: Features (aggregates, Vertex AI FS).  
- Epic 5: Agents (classification, scoring, fraud, decision).  
- Epic 6: HITL (dashboard, feedback loop).  
- Epic 7: Compliance (audit logs, monitoring, security).  

---

## 6. Documentation Standards

### Code Documentation
- Every repo has a `README.md` with:
  - Purpose
  - How to deploy (gcloud/Terraform)
  - Example API calls

### Data Documentation
- dbt docs: auto-generate schema lineage.  
- Data Catalog: document BigQuery datasets (bronze/silver/gold).  
- Great Expectations: store validation rules + test results.  

### System Documentation
- Architecture diagrams (Mermaid/Lucidchart).  
- Service accounts & roles matrix.  
- Runbooks:  
  - How to reprocess a batch  
  - How to rotate secrets  
  - How to onboard a new data source  

### AI Documentation
- Model cards for each agent (training data, metrics, biases).  
- Explainability reports (SHAP/LIME).  
- Auditability notes (decision logs).  

---

## 7. Deliverables

- MVP Demo: end-to-end flow with public datasets.  
- API Docs: ingestion + decision endpoints.  
- Dashboard: HITL + monitoring dashboards.  
- Compliance Pack:  
  - Adverse action letter template.  
  - Bias/fairness report.  
  - Audit log structure.  

---

## 8. Success Metrics

- Data pipeline SLA: <5 min RAW→Bronze lag.  
- Feature freshness: daily update within 1 hr.  
- Model accuracy:  
  - Classification >80% accuracy.  
  - Credit scoring AUC >0.70.  
- HITL adoption: <20% overrides required in pilot.  
- Compliance readiness: 100% decision log coverage.  
