# HelixDecision Documentation Hub

Welcome to the central documentation index for the **HelixDecision Credit Risk & Decisioning Platform**.

Below is the directory of user guides, API specifications, compliance operations, and technical architecture manuals.

---

## 📚 Core Technical Guides

### 1. [API Reference & OpenAPI Specification](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/API_REFERENCE_GUIDE.md)
Comprehensive endpoint documentation for the Decision API (`:8080`) and Analytics API (`:8003`), including request/response JSON schemas, header authentication specs (`X-API-Key`, `X-Tenant-ID`), asynchronous batch job workflows, referral queues, and curl examples.

### 2. [Regulatory Compliance & BSA/FinCEN Operations Guide](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/COMPLIANCE_WORKFLOW_GUIDE.md)
Detailed guide on regulatory compliance features including automated FinCEN Suspicious Activity Report (SAR Form 111) drafting, FCRA adverse action notice & PDF generation, Corporate KYC/UBO verification, data retention schedules, and SOC2 bank exam packet creation.

### 3. [Risk Modeling, CNPV Pricing & Champion-Challenger Manual](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/RISK_AND_PRICING_ENGINE_GUIDE.md)
Technical manual on SciPy SLSQP continuous pricing optimization, Commercial Net Present Value (CNPV) formulations, Double Machine Learning (DML) price elasticity estimation, Funds Transfer Pricing (FTP), and deterministic champion/challenger policy experimentation.

### 4. [System Architecture & Data Lineage Overview](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/TECHNICAL_ARCHITECTURE.md)
Deep dive into the multi-agent architecture, feature engineering pipelines, model serving layer, audit database schema, and event telemetry.

---

## 📖 Operational Manuals & Onboarding

* 🚀 **[Developer Onboarding Guide](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/manuals/DEVELOPER_ONBOARDING.md)**: Local environment setup, running pytest suites, API servers, and local Docker compose stack.
* 🔌 **[Customer Integration Guide](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/manuals/CUSTOMER_INTEGRATION_GUIDE.md)**: Quickstart for fintech partners integrating loan application intake with HelixDecision.
* 🛡️ **[Compliance & Model Risk Manual](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md)**: Model risk management (MRM) procedures, model validation checklists, and audit logging specifications.

---

## 📊 Visual Flow Diagrams

* 📐 [Detailed System Architecture Diagram](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/diagrams/architecture_detailed.md)
* 📐 [Credit Card Origination Policy Flow](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/diagrams/cc_origination_policy_flow.md)
* 📐 [Human-in-the-Loop Referral Queue Lifecycle](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/diagrams/hitl_review_queue_lifecycle.md)
