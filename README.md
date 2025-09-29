
# AI Risk Workflow Platform

Welcome to the **AI Risk Workflow Platform** — a multi-agent system for **consumer & SMB lending risk management**.

This project leverages **Google Cloud Platform (GCP)** and **modular AI agents** to provide:

- Automated **data ingestion & pipelines** (Cloud Run, GCS, Dataflow, BigQuery).
- **Feature engineering** for underwriting & monitoring (dbt + Vertex AI Feature Store).
- **AI agents** for transaction classification, credit scoring, fraud detection, and decisioning.
- **Human-in-the-loop (HITL)** dashboard for overrides & compliance review.
- **Audit-ready compliance** with monitoring, explainability, and fairness checks.

---

## 📂 Repository Structure

```
.
├── PROJECT_PLAN.md       # Full project plan & documentation
├── ingestion/            # Cloud Run ingestion API
├── pipelines/            # Dataflow/Beam + dbt pipelines
├── features/             # Feature engineering scripts
├── agents/               # ML agents (classification, scoring, fraud, decision)
├── dashboard/            # HITL reviewer dashboard
└── infra/                # Terraform/IaC for GCP setup
```

---

## 🚀 Quickstart

### 1. Clone the Repository
```bash
git clone https://github.com/<your-org>/ai-risk-workflow.git
cd ai-risk-workflow
```

### 2. Setup Environment
- Install [gcloud CLI](https://cloud.google.com/sdk/docs/install).
- Authenticate:
```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
```

### 3. Deploy Ingestion API
```bash
cd ingestion
gcloud run deploy ingestion-api   --source .   --region us-central1   --service-account sa-run-ingest@<PROJECT_ID>.iam.gserviceaccount.com
```

### 4. Run dbt Models
```bash
cd pipelines/dbt
dbt run
dbt test
```

### 5. Train AI Agents
```bash
cd agents
python train_classifier.py
python train_credit_scoring.py
python train_fraud_detector.py
```

---

## 📑 Documentation

- [Project Plan](PROJECT_PLAN.md) — full phased roadmap, architecture, tasks.  
- [Ingestion API Docs](ingestion/README.md) — endpoints & usage.  
- [Pipelines Docs](pipelines/README.md) — Dataflow & dbt transformations.  
- [Agents Docs](agents/README.md) — models & explainability.  
- [Dashboard Docs](dashboard/README.md) — HITL reviewer workflow.  

---

## 🛡️ Security

- Service Accounts with **least-privilege IAM**.  
- Secrets in **Secret Manager**.  
- Encryption via **Cloud KMS**.  
- VPC-SC for perimeter security.  

---

## 📈 Roadmap

- [x] Foundation (GCP setup, CI/CD, storage).  
- [ ] Data Ingestion MVP.  
- [ ] Transformation & Features.  
- [ ] AI Agents.  
- [ ] HITL Dashboard.  
- [ ] Compliance & Monitoring.  

For full details, see [PROJECT_PLAN.md](PROJECT_PLAN.md).

---

## 🤝 Contributing

We welcome contributions!  
- Fork the repo, create a feature branch, submit PRs.  
- Open issues for bugs/feature requests.  

---

## 📜 License

MIT License — see [LICENSE](LICENSE).
