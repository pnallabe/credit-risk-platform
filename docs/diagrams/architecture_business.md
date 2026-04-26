# Credit Risk Platform — Business Architecture

> Audience: Business stakeholders, investors, product leaders, bank/fintech partners
> Version: 1.5.0 | April 2026

---

## 1. Who Uses the Platform and Why

```mermaid
C4Context
  title Credit Risk Platform — Business Context

  Person(borrower, "Borrower / Applicant", "Submits a loan application online.\nGets a real-time credit decision\nwith plain-English explanation.")
  Person(lender, "Lender / Credit Analyst", "Reviews flagged applications,\napproves manual overrides,\nmonitors portfolio health.")
  Person(exec, "Risk Officer / CRO", "Sets credit policy,\nreviews fair-lending reports,\nsigns off on audit packages.")
  Person(examiner, "Regulator / Bank Examiner", "Reviews compliance artifacts —\nmodel documentation, adverse action\nnotices, audit logs — for OCC / CFPB.")

  System(crp, "Credit Risk Platform", "Governance-first underwriting SaaS.\nDecides, explains, and documents\nevery credit decision automatically.")

  System_Ext(los, "Bank / Fintech LOS", "Existing loan origination system\n(nCino, Blend, custom core banking).\nSends applications via API.")
  System_Ext(bureau, "Credit Bureaus", "Experian, Equifax, TransUnion.\nCredit history and scores.")
  System_Ext(openbanking, "Open Banking", "Plaid / MX bank-account\ntransaction data for thin-file borrowers.")
  System_Ext(cloud, "GCP Cloud Infrastructure", "Secure, regulated cloud hosting\nwith encryption at rest and in transit.")

  Rel(borrower, crp, "Applies for a loan online")
  Rel(lender, crp, "Reviews decisions, sets policy, exports reports")
  Rel(exec, crp, "Configures risk appetite, approves audit packages")
  Rel(examiner, crp, "Downloads exam-ready compliance packages")
  Rel(los, crp, "Sends application data via secure API")
  Rel(crp, bureau, "Enriches applicant credit profile (roadmap)")
  Rel(crp, openbanking, "Enriches with transaction data for thin-file (roadmap)")
  Rel(crp, cloud, "Runs on GCP — Cloud Run, KMS, Secret Manager")
```

---

## 2. Platform Capability Map

```mermaid
mindmap
  root((Credit Risk\nPlatform))
    Underwriting Engine
      Instant credit decisions
      Configurable policy rules — no code required
      Probability-of-default scoring via XGBoost
      Fraud detection on every application
      Risk-based loan pricing
      Batch processing for portfolios
    Compliance & Governance
      Adverse action notices Reg B / ECOA / FCRA
      Fair lending monitoring disparate impact
      Four-eyes approval for policy changes
      Model documentation SR 11-7 ready
      7-year immutable audit trail
      OCC / CFPB exam package — one click
      Data erasure GDPR / CCPA
    AI Analytics Assistant
      Natural language questions about your portfolio
      Automatic drift alerts when model performance degrades
      Fair lending reports with statistical evidence
      Reg B deadline monitoring
      SQL and chart generation — no data team needed
    Applicant Experience
      White-label online application portal
      Plain-English decision letters
      Real-time status updates
      FCRA-compliant adverse action delivery
    Risk Monitoring
      Model performance tracking AUC / KS daily
      Data drift detection PSI per feature
      Portfolio vintage curves
      Concentration and segment alerts
    Developer Platform
      REST API for LOS integration
      Webhook events on every decision
      Multi-tenant isolation — one platform, many lenders
      Role-based access control 8 roles
```

---

## 3. How a Loan Decision Works (End-to-End)

```mermaid
flowchart LR
    APP["Borrower submits\napplication online\nor via LOS API"]

    subgraph DECISION["Credit Decision Engine  ~50 ms"]
        direction TB
        FEAT["Data Enrichment\nCredit features computed\nfrom application data"]
        MODEL["Risk Scoring\nProbability of default\nFraud risk score"]
        POLICY["Policy Evaluation\nCredit policy rules\napplied by risk tier"]
        EXPLAIN["Reason Codes\nSHAP-driven plain-English\nfactors driving the decision"]
    end

    subgraph COMPLIANCE_CHECK["Compliance Gate  automatic"]
        direction TB
        PROTECTED["Protected Basis Check\nNo race, gender, or\nnational origin used"]
        AA_GEN["Adverse Action\nReg B compliant notice\nauto-generated if declined"]
    end

    subgraph OUTCOMES["Decision Outcomes"]
        APPROVE["APPROVE\nRate + terms offered"]
        MANUAL["MANUAL REVIEW\nFlagged for analyst\n(HITL queue)"]
        DECLINE["DECLINE\nAdverse action notice\ndelivered within 30 days"]
        CONDITIONAL["CONDITIONAL\nNeeds documentation\nor co-signer"]
    end

    AUDIT_TRAIL["Immutable Audit Log\nEvery decision hashed\nand chain-linked forever"]

    APP --> FEAT
    FEAT --> MODEL
    MODEL --> POLICY
    POLICY --> EXPLAIN
    EXPLAIN --> PROTECTED
    PROTECTED --> AA_GEN
    AA_GEN --> APPROVE
    AA_GEN --> MANUAL
    AA_GEN --> DECLINE
    AA_GEN --> CONDITIONAL
    APPROVE & MANUAL & DECLINE & CONDITIONAL --> AUDIT_TRAIL
```

---

## 4. Compliance & Audit Lifecycle

```mermaid
flowchart TD
    subgraph DAILY["Day-to-Day Operations"]
        DEC["Credit Decision\nmade and logged"]
        DRIFT["Drift Monitor\nDaily model health check"]
        FL["Fair Lending Monitor\nDisparate impact weekly"]
        DEADLINE["Reg B Deadline Watch\n30-day adverse action clock"]
    end

    subgraph CHANGE_CONTROL["Policy Change Control"]
        STAGE["Risk Officer\nstages a policy change"]
        FOUR["Four-Eyes Approval\na second officer must\napprove before it goes live"]
        LIVE["Policy goes live\nwith version history\nand rollback capability"]
    end

    subgraph EXAM_READY["Exam Package  one click"]
        PKG["Exam Packet Builder\n8 components assembled automatically"]
        C1["Decision Summary\napproval / decline rates"]
        C2["Adverse Action Log\nevery declined applicant"]
        C3["Model Documentation\nSR 11-7 compliant"]
        C4["Fair Lending Report\ndisparate impact analysis"]
        C5["Data Drift Report\nmodel stability evidence"]
        C6["Audit Chain Proof\ntamper-evident log verification"]
        C7["Policy Override Log\nall manual interventions"]
        C8["AI Query Audit\nevery analyst AI question logged"]
    end

    DEC --> DRIFT
    DRIFT -->|"PSI > 0.25\n= model retraining alert"| FL
    FL -->|"Disparate impact\n> 20% gap flagged"| DEADLINE
    STAGE --> FOUR --> LIVE
    LIVE --> DEC

    DEC --> PKG
    PKG --> C1 & C2 & C3 & C4 & C5 & C6 & C7 & C8

    subgraph APPROVAL["Compliance Sign-Off"]
        PENDING["Package submitted\nfor CRO approval"]
        SIGNED["CRO approves\n(separate from creator — SOD)"]
        PDF["Exam-ready PDF exported\nfor regulator"]
    end

    C1 & C2 & C3 & C4 & C5 & C6 & C7 & C8 --> PENDING
    PENDING --> SIGNED --> PDF
```

---

## 5. AI Analytics Assistant — How It Works

```mermaid
flowchart LR
    Q["Analyst asks a question\ne.g. 'Show me approval rates\nby risk tier this quarter'"]

    subgraph PIPELINE["AI Pipeline  fully automated"]
        direction TB
        PLAN["Understands the question\nBreaks it into analysis steps\n(no hallucination — plan shown upfront)"]
        SQL_SP["Data Retrieval\nWrites and runs SQL\nagainst your live data"]
        MET_SP["Model Performance\nAUC, KS, F1 scores\nvs regulatory thresholds"]
        DRIFT_SP["Drift Analysis\nFeature-level PSI trends\nSR 11-7 framing"]
        FL_SP["Fair Lending\nDisparate impact ratios\n80% rule check"]
        SYNTH["Synthesizes the answer\nOnly uses retrieved data\nRefuses to guess"]
    end

    subgraph CONTROLS["Safety Controls"]
        PROHIB["No protected characteristics\nused in any query"]
        GROUNDING["Grounded answer only\nlow-confidence responses\nautomatically refused"]
        LOG["Every question logged\nin immutable AI audit trail\nfor examiner review"]
    end

    ANSWER["Analyst gets\na plain-English answer\nwith supporting charts and SQL"]

    Q --> PLAN
    PLAN --> SQL_SP & MET_SP & DRIFT_SP & FL_SP
    SQL_SP & MET_SP & DRIFT_SP & FL_SP --> SYNTH
    SYNTH --> PROHIB --> GROUNDING --> LOG --> ANSWER
```

---

## 6. Stakeholder Value Summary

```mermaid
quadrantChart
    title Platform Value by Stakeholder
    x-axis Operational Value --> Strategic Value
    y-axis Compliance Value --> Revenue Value
    quadrant-1 Strategic Revenue
    quadrant-2 Compliance & Risk
    quadrant-3 Operational Efficiency
    quadrant-4 Growth Enablement

    Instant Decisions: [0.55, 0.72]
    Fair Lending Reports: [0.30, 0.62]
    Exam Packet Builder: [0.25, 0.75]
    AI Analytics Assistant: [0.70, 0.65]
    Policy Versioning: [0.45, 0.58]
    Audit Chain: [0.20, 0.80]
    Thin-File Scoring: [0.75, 0.55]
    Multi-Tenant API: [0.80, 0.70]
    Adverse Action Auto-Gen: [0.35, 0.55]
    Risk-Based Pricing: [0.72, 0.78]
```

---

## 7. Deployment Model

```mermaid
flowchart TD
    subgraph LENDER["Lender / Partner"]
        LOS_SYS["Existing LOS\nnCino · Blend · Custom"]
        PORTAL["Applicant Portal\nborrower-facing web app"]
        DASH["Analytics Dashboard\nrole-based internal UI"]
    end

    subgraph PLATFORM["Credit Risk Platform  GCP Cloud Run"]
        API["Secure Decision API\nREST · HTTPS · JWT auth"]
        AI_API["AI Analytics API\nStreaming · rate-limited"]
        ENGINE["Credit Decision Engine\npolicy + models + compliance"]
        AUDIT_DB["Immutable Audit Store\nhash-chained · 7-year retention"]
    end

    subgraph DATA["Data Layer  encrypted at rest"]
        PG["Transaction Database\nloans · decisions · audit"]
        BQ["Analytics Warehouse\nBigQuery · portfolio aggregates"]
        ML_REG["Model Registry\nMLflow · versioned XGBoost models"]
    end

    subgraph SECURITY["Security Controls"]
        KMS["Encryption at Rest\nGCP Cloud KMS"]
        SM["Secrets Management\nGCP Secret Manager"]
        TLS["Encryption in Transit\nTLS 1.3 · mTLS for bureaus"]
        RBAC_BOX["Role-Based Access\n8 roles · four-eyes enforcement\nper-lender data isolation"]
    end

    LOS_SYS -->|"POST /v1/decisions\nHTTPS + API key"| API
    PORTAL -->|"Applicant submits form"| API
    DASH -->|"Analyst queries portfolio"| AI_API
    API --> ENGINE
    AI_API --> ENGINE
    ENGINE --> AUDIT_DB
    ENGINE --> PG
    ENGINE --> BQ
    ENGINE --> ML_REG
    KMS & SM & TLS & RBAC_BOX -.->|"protect"| PLATFORM
    KMS -.->|"protect"| DATA
```

---

## 8. Regulatory Alignment at a Glance

| Regulation | Requirement | How the Platform Addresses It |
|---|---|---|
| **Reg B (ECOA)** | Adverse action notice within 30 days | Auto-generated at decision time, deadline tracked, delivered via portal |
| **FCRA** | Accurate adverse action reason codes | SHAP-driven codes, 5-factor model, compliant notice format |
| **Fair Housing Act** | No disparate impact on protected classes | Weekly DIR / BISG analysis, 80% rule monitoring, examiner report |
| **SR 11-7** | Model risk management documentation | Auto-generated model card, validation evidence, exam packet component |
| **GDPR / CCPA** | Right to erasure, data minimization | Erasure request workflow, PII masking in audit logs |
| **SOX / Internal Audit** | Change control, four-eyes approval | Policy versioning + two-officer approval gate, full override log |
| **OCC / CFPB Examination** | Exam-ready documentation package | One-click 8-component exam packet, PDF export, chain-of-custody proof |
