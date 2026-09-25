# Enterprise Credit Risk Platform — Case Study Index

This case study directory contains 16 in-depth architectural and operational case studies documenting the end-to-end design, real-time data integrations, policy execution, machine learning models, regulatory compliance, and production metrics across our enterprise credit platform.

Unlike typical static portfolio projects that rely on offline CSV snapshots, all 16 case studies feature **real-time data ingestion streams**—integrating live FRED macroeconomic indicators, Yahoo Finance market feeds, SEC EDGAR filings, streaming Open Banking webhooks, and live Soft Bureau gateways.

---

## Portfolio Overview & Case Study Directory

| # | Case Study Title | Core Domain | Real-Time Data Source | Status |
|---|---|---|---|---|
| **01** | [Buy Now Pay Later (BNPL) Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/01_bnpl_underwriting_engine.md) | Sub-100ms Checkout Underwriting | Live Open Banking Webhooks & Merchant Risk Streams | **Completed** |
| **02** | [Personal Loan Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/02_personal_loan_underwriting_engine.md) | Cash-flow & Bureau Underwriting | Real-time FRED Economic API & Bank Webhooks | **Completed** |
| **03** | [Secured SMB Loan Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/03_secured_smb_loan_engine.md) | Commercial Underwriting & DSCR | Live SEC EDGAR API & FRED Rate Stream | **Completed** |
| **04** | [Credit Builder & Secured Card Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/04_credit_builder_secured_card.md) | Deposit-Backed Credit & Pathways | Real-time Balance Webhooks & Micro-deposit Stream | **Completed** |
| **05** | [Overdraft & Cash Advance Risk Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/05_overdraft_cash_advance_engine.md) | Payroll Frequency & Liquidity | Streaming Bank Push API & Payroll Deposit Events | **Completed** |
| **06** | [Mainstream Credit Card Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/06_mainstream_credit_card_engine.md) | Revolving Credit & Multi-Bureau | Live Soft Bureau Gateway & FRED Benchmark Rates | **Completed** |
| **07** | [Auto Loan Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/07_auto_loan_underwriting_engine.md) | Vehicle LTV & Dealer Routing | Live Vehicle Valuation Feeds & Income Streams | **Completed** |
| **08** | [Mortgage & Real Estate Underwriting Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/08_mortgage_underwriting_engine.md) | QM/TRID Compliance & DTI Stress | Real-time FRED Mortgage Index & Property Feeds | **Completed** |
| **09** | [Real-Time Financial Ingestion & Webhook API](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/09_realtime_financial_ingestion_api.md) | High-Throughput Stream Ingestion | Streaming Webhook Engine (`/v1/ingest/...`) | **Completed** |
| **10** | [Enterprise Feature Store & Pipeline Engine](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/10_enterprise_feature_store.md) | Dual Online/Offline Feature Store | Streaming Bank Events → In-Memory Online Store | **Completed** |
| **11** | [AI Decision Engine & Policy Challenger System](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/11_ai_decision_engine_policy_challenger.md) | Champion/Challenger & Rules | Real-Time Decision API (`/v1/decide`) | **Completed** |
| **12** | [Model Risk Management & Explainability Platform](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/12_model_risk_management_explainability.md) | SHAP Attributions & Adverse Action | Real-Time Inference Traces & Feature Attributions | **Completed** |
| **13** | [Regulatory Exam Packet & Immutable Audit Ledger](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/13_regulatory_exam_packet_compliance.md) | Cryptographic Audit & HITL Gate | Immutable Ledger (`decision_audit.db`) | **Completed** |
| **14** | [Real-Time Portfolio Monitoring & EWS System](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/14_portfolio_ews_monitoring.md) | Portfolio Vintages & Rate Shocks | Real-time Yahoo Finance & Macro FRED Feeds | **Completed** |
| **15** | [Enterprise Medallion Data Architecture (`agenthive_data`)](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/15_agenthive_data_medallion_architecture.md) | Bronze/Silver/Gold Lakehouse | Streaming Landing Zone → Silver → Gold Views | **Completed** |
| **16** | [AI Agent Code Transparency & Governance Platform](file:///Users/swarnabale/Documents/My%20Projects/credit-risk-platform/docs/case_studies/16_ai_agent_code_transparency.md) | Multi-Agent Query & Confidence Gate | Live Database SQL Execution Engine & Gate | **Completed** |

---

## Architectural Principles & Shared Infrastructure

All 16 projects leverage a unified core architecture built for extreme performance, auditability, and regulatory compliance:
- **Shared Cash-Flow Backbone**: Standardized Open Banking summary contracts across consumer and commercial products.
- **Zero-Lookahead Feature Parity**: Offline training features match online scoring features bit-for-bit.
- **Sub-100ms Latency P99**: In-memory caching, async feature extraction, and pre-compiled policy evaluation.
- **CFPB & OCC Exam-Ready**: Immutable SHA-256 hash chains for every decision trace, SHAP values, and adverse action reasons.
