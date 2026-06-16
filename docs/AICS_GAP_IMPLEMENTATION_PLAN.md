# AICreditSystem PRD — Gap Analysis & Implementation Plan
**Generated:** June 5, 2026
**PRD Reference:** AICreditSystem_PRD.md v1.0

---

## Legend
✅ Implemented | ⚠️ Partial | ❌ Missing

---

## Part 1 — Gap Analysis

### Agent Roster (PRD §4)

#### 4.1 Data Ingestion Agent — ✅ IMPLEMENTED
`agents/data_ingestion_agent.py` + `ingestion-api/` cover parsing, normalization, bureau pulls, Plaid, OCR, and data quality checks via `data_quality/expectations.py`. FR-DP-001 through FR-DP-006 satisfied.

---

#### 4.2 Credit Analyst Agent — ❌ NOT IMPLEMENTED
The largest gap. Requires a dedicated qualitative assessment agent that:
- Analyzes borrower creditworthiness beyond a PD score (income stability, employment quality)
- Assesses industry risk and macro environment for the borrower's sector
- Evaluates collateral quality and coverage ratios
- Identifies red flags (fraud patterns, covenant violations, anomalous transaction behavior)
- Generates a structured **risk narrative document** per account

**What exists:** `collateral_type` / `collateral_value` / `collateral_ltv` fields are in the data schema and SHAP/NLG explain model scores — but there is no agent performing qualitative due diligence or writing per-account risk narratives. `ai-agent/specialist_agents.py` routes to SQL/Metrics/FairLending analysts — none is a Credit Analyst performing borrower-level qualitative review.

---

#### 4.3 Credit Modeling Agent — ⚠️ PARTIAL
**Implemented:** `RiskModelingAgent` executes PD scoring via LightGBM champion/challenger; `ecl_engine.py` computes EAD + LGD for IFRS 9; `stress_test.py` runs Monte Carlo; CC PD scorecard (`cc_pd_scorecard.json`) produced by `train_cc_pd_model.py` with calibration curves and score-band tables.

**Gaps:**
- Only one product segment (credit card) has a trained scorecard — no **SMB** or **Commercial** PD model
- Scorecard `build_scorecard()` produces score-band → default-rate tables but not **feature-level point assignments** (WoE scorecard format)
- No **LGD model** — ECL engine uses a `lgd_rate` config constant, not a model
- No dedicated scoring endpoint returning PD + LGD + EAD + scorecard contribution in a single response

---

#### 4.4 Credit Policy Development & Monitoring Agent — ⚠️ PARTIAL
**Implemented:** Policy DSL with AST-validated rules; version store + hash-chain + rollback + four-eyes staging; `compliance/engine.py` enforces rules at decision time; champion/challenger + A/B testing.

**Gaps:**
- No **waiver tracking workflow** — review queue handles overrides but no structured waiver object (waiver ID, expiry, approval chain, scope)
- No **policy adherence report** — no scheduled/on-demand report showing compliance rate per rule, exception counts, trend
- No **exposure limit monitoring** — policy engine enforces per-application limits but does not aggregate to check portfolio-level exposure caps in real time
- No dedicated `PolicyAgent` in the agent pipeline — compliance is a side-effect of `DecisionEngineAgent`

---

#### 4.5 Underwriting Agent — ⚠️ PARTIAL
**Implemented:** `/v1/decide` produces Approve / Decline / Refer with risk score, PD, and reason codes; `review_queue.py` routes refer cases; override log captures human decisions.

**Gaps:**
- **"Conditional Approval"** is not a distinct decision outcome — no decision state with attached conditions (e.g., "approved subject to income verification" or "approved at reduced limit")
- **Credit term recommendations** — pricing engine computes APR and limit but **covenants** are not generated
- **Alternative structure / mitigants** — no suggestion of alternative deal structures when declining (e.g., "would approve at 60% LTV instead of 80%")
- **Confidence interval on risk score** — 0-100 score output but no confidence interval

---

#### 4.6 Portfolio Construction & Monitoring Agent — ⚠️ PARTIAL
**Implemented:** `cc_portfolio_monitor.py` tracks CC portfolio health; `drift_monitor.py` monitors PSI; `alert_router.py` fires threshold alerts; weighted average PD computed in ECL engine.

**Gaps:**
- No **portfolio construction logic** — no optimal allocation target computation or risk/return optimization across segments
- No **rebalancing recommendation engine** — nothing generates actionable recommendations
- No **sector / geographic concentration tracking** — only product-level concentration
- No **risk heatmap generation**
- No **peer benchmarking** — metrics not compared to industry benchmarks
- Weighted average **LGD** not tracked at portfolio level

---

#### 4.7 Compliance Monitoring Agent — ✅ SUBSTANTIALLY IMPLEMENTED
`compliance/` covers adverse action, ECOA, FCRA, CRA, HMDA, fair lending (BISG, AIR), exam packets, health score, and model governance docs.

**Remaining gap:** FFIEC call report format not implemented.

---

#### 4.8 Orchestration Agent — ⚠️ PARTIAL
**Implemented:** `orchestration/pipeline.py` DAG with configurable retry + per-stage timeouts; `review_queue.py` for HITL referrals.

**Gaps:**
- No **agent failure fallback strategy** — if `RiskModelingAgent` fails the pipeline raises `RuntimeError`; no fallback to rule-based scoring
- No **configurable escalation thresholds** — borderline PD band for auto-refer is not config-driven
- No **cross-agent persistent state store** — results are in-memory, not durable across pod restarts for long-running batch jobs

---

### Output Artifact Gaps (PRD §6)

| Artifact | Status | Gap |
|---|---|---|
| **6.1** Approve / Decline / Conditional Approval + confidence interval | ⚠️ | Conditional Approval state + confidence interval missing |
| **6.1** Recommended covenants | ❌ | Not implemented |
| **6.1** Alternative structures / mitigants | ❌ | Not implemented |
| **6.2** Portfolio snapshot (WA PD/LGD/EAD, rating distribution) | ⚠️ | WA PD ✅; WA LGD and rating distribution missing |
| **6.2** Sector + geographic concentration analysis | ❌ | Not implemented |
| **6.2** Risk heatmaps | ❌ | Not implemented |
| **6.2** Peer benchmarking | ❌ | Not implemented |
| **6.2** Rebalancing recommendations | ❌ | Not implemented |
| **6.3** Scorecards — Consumer, SMB, Commercial segments | ⚠️ | CC (consumer) only; SMB + Commercial missing |
| **6.3** Feature-level point assignments (WoE format) | ⚠️ | Score-band table exists; WoE per-feature scorecard format missing |
| **6.3** Visual SHAP explanations | ⚠️ | SHAP values computed; no chart/visual output |
| **6.4** FFIEC regulatory reporting | ❌ | Not implemented |
| **6.5** Per-account risk narrative (borrower + industry + collateral + macro) | ❌ | No Credit Analyst Agent |
| **6.5** Red Flag Reports | ❌ | Not implemented as distinct output |
| **6.6** Executive dashboards (frontend UI) | ❌ | No frontend dashboard |

---

### Functional Requirement Coverage

| ID | Requirement | Status | Notes |
|---|---|---|---|
| FR-DP-001 | JSON, CSV, Parquet ingestion | ✅ | |
| FR-DP-002 | Schema validation | ✅ | `data_contracts/` |
| FR-DP-003 | Data quality checks | ✅ | `data_quality/expectations.py` |
| FR-DP-004 | Missing data imputation | ⚠️ | Feature pipeline imputes; strategy not documented per field |
| FR-DP-005 | Data quality reports | ⚠️ | Anomaly detection exists; no standalone quality report artifact |
| FR-DP-006 | Batch + real-time | ✅ | |
| FR-CA-001 | Autonomous credit analysis per account | ⚠️ | Quantitative only; no qualitative Credit Analyst Agent |
| FR-CA-002 | Risk score 0-100 + PD | ✅ | |
| FR-CA-003 | Explicit reasoning with key factors | ✅ | SHAP + NLG |
| FR-CA-004 | Policy-driven exception + waiver management | ⚠️ | Exception routing ✅; waiver tracking ❌ |
| FR-CA-005 | Human override with documented reasoning | ✅ | `override_log.py` |
| FR-CA-006 | Escalate borderline cases | ⚠️ | Review queue ✅; configurable escalation thresholds ❌ |
| FR-PM-001 | Real-time portfolio composition tracking | ⚠️ | CC portfolio ✅; SMB/Commercial ❌ |
| FR-PM-002 | Concentration risk monitoring | ⚠️ | Score-band level ✅; sector/geo concentration ❌ |
| FR-PM-003 | Alerts on portfolio threshold breach | ✅ | `alert_router.py` |
| FR-PM-004 | Rebalancing recommendations | ❌ | Not implemented |
| FR-PM-005 | Portfolio-level PD, LGD, EL | ⚠️ | PD ✅; LGD model ❌; EL via ECL engine ✅ |
| FR-CR-001 | Complete audit logs | ✅ | Hash-chained |
| FR-CR-002 | Fair Lending monitoring | ✅ | BISG + AIR |
| FR-CR-003 | Disparate impact reports | ✅ | |
| FR-CR-004 | HMDA, CRA, FFIEC | ⚠️ | HMDA + CRA ✅; FFIEC ❌ |
| FR-CR-005 | Adverse action notices | ✅ | |
| FR-CR-006 | Policy compliance enforcement | ✅ | |
| FR-EX-001 | SHAP feature importance | ✅ | |
| FR-EX-002 | Model input influence display | ✅ | |
| FR-EX-003 | Key risk factor highlighting | ✅ | |
| FR-EX-004 | Citability / reviewability | ⚠️ | Code artifacts exist; no credit-officer-facing review UI |

---

## Part 2 — Implementation Plan

---

### Sprint 1 — Credit Analyst Agent (Weeks 1–3)
**Closes:** §4.2, FR-CA-001, §6.5

Build `agents/credit_analyst_agent.py` as a new `BaseAgent` subclass with three sub-components.

#### 1a. Qualitative Assessment Engine
```
Input:  FeatureVector + ModelScores (from RiskModelingAgent)
Logic:
  - Income stability score: employment_status + emp_years + income volatility
  - Collateral coverage: collateral_value / loan_amount → coverage_ratio; flag if < 1.0
  - Industry risk lookup: map borrower SIC/NAICS to sector risk tier (pre-seeded table)
  - Red flag detector: check fraud_flag="review", num_missed_pmts_12m > 2,
    cash_advance_total_12m > 0.3 * credit_limit, recent bankruptcy, thin-file
Output: QualitativeAssessment dataclass
  - creditworthiness_score: 1–5 ordinal
  - collateral_quality: Adequate | Marginal | Insufficient
  - industry_risk_tier: Low | Medium | High | Elevated
  - red_flags: List[RedFlag]
  - overall_risk_opinion: Acceptable | Marginal | Unacceptable
```

#### 1b. Risk Narrative Generator
```
Input:  QualitativeAssessment + ModelScores + SHAP values
Output: RiskNarrativeDocument (structured JSON + rendered Markdown)
  - borrower_profile_section
  - financial_strength_section
  - collateral_analysis_section (if secured)
  - industry_macro_section
  - red_flag_section (if any flags)
  - overall_credit_opinion
Implementation: extend existing nlg_summarizer.py with Jinja2 templates
  per section, data-grounded (no LLM hallucination risk)
```

#### 1c. Red Flag Report
```
Standalone artifact: list of flagged conditions with severity,
supporting evidence (feature value + threshold), and recommended action.
```

Wire `CreditAnalystAgent` into `orchestration/pipeline.py` after `ExplainabilityAgent`.

---

### Sprint 2 — Scorecard Expansion + LGD Model (Weeks 3–5)
**Closes:** §4.3, §6.3

#### 2a. SMB and Commercial PD Scorecards
```
New training scripts:
  models/credit_risk/train_smb_pd_model.py
  models/credit_risk/train_commercial_pd_model.py

SMB features:
  business_age_years, annual_revenue, dscr, debt_to_equity,
  owner_fico, business_fico, industry_risk_tier, num_employees,
  trade_line_count, delinquency_history

Commercial features:
  noi, cap_rate, ltv, dscr, property_type, market_vacancy_rate,
  sponsor_net_worth, guarantor_fico, loan_to_value, amortization_period

Each script produces:
  - Trained LightGBM model with monotone constraints
  - Segment scorecard JSON (same format as cc_pd_scorecard.json)
  - Calibration curve + AUC/KS/Gini metrics
  - MLflow-registered artifact
```

#### 2b. Feature-Level Point Assignment (WoE Scorecard Format)
```
Add build_woe_scorecard() to train_cc_pd_model.py (and SMB/Commercial):
  - Bin each numeric feature into 8–12 buckets
  - Compute Weight of Evidence per bin
  - Scale WoE coefficients to integer point scale (PDO = 20)
  - Output: cc_pd_woe_scorecard.json with structure:
    { "feature": "fico_score", "bin": "700-749", "woe": 0.42, "points": +35 }
  - Expose via: GET /v1/models/{name}/scorecard
```

#### 2c. LGD Model
```
New: models/lgd/train_lgd_model.py
  Features: collateral_type, ltv, loan_term, product_type,
            recovery_cost_estimate, borrower_segment
  Output: LGD prediction (0–1) replacing config constant in ecl_engine.py
  Register in MLflow; wire into RiskModelingAgent
```

---

### Sprint 3 — Portfolio Construction & Concentration Engine (Weeks 5–7)
**Closes:** §4.6, FR-PM-001–005, §6.2

#### 3a. Sector + Geographic Concentration Tracker
```
New: monitoring/concentration_monitor.py
  - Maps each account to NAICS sector tier + state
  - Computes real-time concentration % by: sector, state, risk-grade, product
  - Configurable limits (from policy_version_store) per dimension
  - Fires alert if any dimension exceeds limit
  - Exposes: GET /v1/portfolio/concentration
```

#### 3b. Weighted Average LGD + Rating Distribution
```
Extend: monitoring/cc_portfolio_monitor.py
  - Add wa_lgd computation using LGD model outputs (Sprint 2c)
  - Add risk_rating_distribution: { prime: %, near_prime: %, subprime: % }
  - Expose via: GET /v1/portfolio/snapshot
```

#### 3c. Rebalancing Recommendation Engine
```
New: agents/portfolio_construction_agent.py
  Input: ConcentrationReport + PortfolioSnapshot + policy limits
  Logic:
    1. Identify segments breaching limits or approaching thresholds (>80%)
    2. Score each segment on: current_concentration, trend (30d), PD_band, EL
    3. Generate recommendation list:
       { segment, action: REDUCE|HOLD|GROW,
         current_pct, limit_pct, reasoning }
    4. Estimate impact on portfolio WA-PD if recommendation followed
  Output: RebalancingPlan with prioritized action list
  Expose via: GET /v1/portfolio/rebalancing
```

#### 3d. Risk Heatmap Data API
```
New endpoint: GET /v1/portfolio/heatmap?dimension=geography|sector|rating
  Returns GeoJSON-compatible or tabular data for frontend rendering
```

---

### Sprint 4 — Underwriting Agent Enhancement (Weeks 7–8)
**Closes:** §4.5, §6.1 gaps

#### 4a. Conditional Approval Decision State
```
Extend decision_engine/engine.py:
  Add DecisionOutcome.CONDITIONAL_APPROVAL
  Conditions type: List[Condition]
    - INCOME_VERIFICATION_REQUIRED
    - REDUCED_LIMIT (with suggested_limit)
    - COLLATERAL_REQUIRED (with min_coverage_ratio)
    - ADDITIONAL_DOCUMENTATION (with doc_type list)
  Trigger: when policy allows approval but one condition is unmet
  Store conditions in audit log; surface in /v1/decide response
```

#### 4b. Risk Score Confidence Interval
```
Extend RiskModelingAgent:
  Use LightGBM bootstrap ensemble (5 sub-models) to compute [p5, p95] interval on PD
  Add pd_confidence_interval: [lower, upper] to ModelScores dataclass
```

#### 4c. Alternative Structure Suggestions
```
New: decision_engine/alternative_structures.py
  When decision = DECLINE, evaluate 3 alternative structures:
    1. Reduce loan amount to where policy approves → suggest reduced_amount
    2. Add collateral requirement → suggest collateral_type + min_coverage
    3. Re-price to compensate for risk → suggest_apr
  Return up to 3 alternatives ranked by feasibility score
  Add alternatives[] to /v1/decide response
```

#### 4d. Covenant Recommendation Engine
```
New: decision_engine/covenant_engine.py
  Input: product_type, industry_risk_tier, dscr, ltv, loan_amount
  Logic: lookup covenant matrix (configurable JSON):
    - Commercial: DSCR >= 1.25, max LTV 75%, quarterly financials
    - SMB: personal guarantee if revenue < $1M, annual tax returns
    - Secured consumer: LTV <= 80%, lien search within 5 days
  Output: CovenantPackage added to underwriting decision
```

---

### Sprint 5 — Policy Waiver Tracking + Adherence Reporting (Weeks 8–9)
**Closes:** §4.4, FR-CA-004

#### 5a. Waiver Management System
```
New: compliance/waiver_store.py
  Waiver dataclass:
    waiver_id, application_id, policy_rule_violated,
    waiver_reason, requested_by, approved_by, expires_at,
    scope (single|portfolio), status (pending|approved|denied|expired)
  SQLite table: waivers (append-only)
  API endpoints:
    POST /v1/waivers/request
    POST /v1/waivers/{id}/approve  (requires second approver)
    GET  /v1/waivers?status=pending|active|expired
    GET  /v1/waivers/report?period=30d|90d|ytd
```

#### 5b. Policy Adherence Report
```
New: reporting/policy_adherence.py
  Computes per policy rule:
    - rule_id, rule_description
    - decisions_evaluated: N
    - compliance_rate: %
    - exceptions_triggered: count
    - waivers_granted: count
    - trend vs prior 30d
  Scheduled: daily refresh
  Expose: GET /v1/compliance/policy-adherence?period=30d
  Include in exam_packet_builder
```

---

### Sprint 6 — Orchestration Hardening + FFIEC (Weeks 9–10)
**Closes:** §4.8, FR-CR-004

#### 6a. Agent Fallback Strategies
```
Extend orchestration/pipeline.py:
  Per-agent fallback config in agent_config.yaml:
    risk_modeling:
      on_failure: use_rule_based_fallback | skip | abort
      rule_based_fallback:
        decline_if_pd_unknown: true
  Implement RuleBasedFallbackScorer in decision_engine/:
    Simple: fico_score < 580 → high_risk; fico_score > 720 → low_risk
    Used only when ML model fails — logged as fallback=true in audit
```

#### 6b. Configurable Escalation Thresholds
```
Extend decision_engine/engine.py:
  Add escalation_bands config (per product, per tenant) to policy_version_store:
    refer_if: 0.08 <= pd <= 0.12   # borderline band → auto-refer
    decline_if: pd > 0.12
  Config-driven so thresholds can be updated without redeploy
```

#### 6c. FFIEC Reporting
```
New: reporting/ffiec_call_report.py
  Generates Schedule RC-C (Loans and Lease Financing) data
  Maps portfolio segments to FFIEC loan categories
  Outputs: FFIEC-formatted CSV/XML for Schedule RC-C
```

---

### Sprint 7 — Frontend Dashboard (Weeks 10–13)
**Closes:** §6.2, §6.6, NFR-P-003

```
Build React dashboard in ui/ (Next.js + Recharts):

  Page 1: Portfolio Overview
    - WA PD, WA LGD, WA EL (live, <5s refresh via SSE)
    - Approval rate MTD / QTD
    - 30/60/90 DPD trend chart
    - Concentration heatmap (top 5 sectors + geographic map)
    - Active alerts panel

  Page 2: Scorecard Explorer
    - Segment selector: Consumer / SMB / Commercial
    - WoE scorecard table (feature → bin → points)
    - Calibration curve chart
    - Gini / KS / AUC by vintage (time-series)
    - SHAP beeswarm chart (top 20 features)

  Page 3: Rebalancing Recommendations
    - Concentration table with RAG traffic-light status
    - Recommendation cards (action + reasoning + estimated impact)

  Page 4: Compliance
    - AIR trend by protected class
    - Policy adherence table
    - Waiver queue
    - Exam packet generator

  Tech: Next.js + Recharts, FastAPI SSE for live metrics
        Reuse existing /v1/ API endpoints
```

---

## Summary Backlog

| Sprint | Deliverable | PRD Sections Closed | Weeks |
|---|---|---|---|
| 1 | Credit Analyst Agent + Risk Narrative + Red Flag Report | §4.2, FR-CA-001, §6.5 | 1–3 |
| 2 | SMB/Commercial Scorecards + WoE Format + LGD Model | §4.3, §6.3 | 3–5 |
| 3 | Concentration Engine + Rebalancing Agent + Heatmap API | §4.6, FR-PM-001–005, §6.2 | 5–7 |
| 4 | Conditional Approval + Covenants + Alternatives + Confidence Interval | §4.5, §6.1 | 7–8 |
| 5 | Waiver Tracking + Policy Adherence Report | §4.4, FR-CA-004 | 8–9 |
| 6 | Orchestration Fallbacks + Escalation Thresholds + FFIEC | §4.8, FR-CR-004 | 9–10 |
| 7 | Frontend Dashboard (Portfolio + Scorecard + Compliance) | §6.2, §6.6, NFR-P-003 | 10–13 |

**Total: ~13 weeks to full PRD coverage.**
Sprints 1–3 are highest priority — they represent entirely absent capabilities.
