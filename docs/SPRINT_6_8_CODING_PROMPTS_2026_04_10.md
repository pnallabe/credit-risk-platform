# Sprint 6–8: Phase 3 Implementation — Coding Prompts & Technical Reference

**Document:** `SPRINT_6_8_CODING_PROMPTS_2026_04_10.md`
**Status:** ✅ Implemented
**Platform:** `credit-risk-platform` (Python/FastAPI + Next.js 14)
**Prerequisite:** All Sprints 1–5 and Backlog items fully implemented

---

## Context

Sprints 1–5 and the Backlog addressed the 16 governance gaps identified in
`GOVERNANCE_PRD_GAP_ANALYSIS_2026_04_10.md`.  Sprint 6–8 implement the
**Phase 3 roadmap** from `PRD_INTEGRATED_LENDING_OPERATING_LAYER.md §11.1`,
covering capabilities that elevate the platform from compliance-complete to
commercially differentiated:

| Sprint | Focus Area | PRD Reference |
|--------|-----------|---------------|
| 6-A | Statistical A/B Testing Framework | §4.2.3 |
| 6-B | NLG Executive Summary Generator | §5.4 |
| 7-A | Multi-Product Policy Engine | §4.2.1 |
| 7-B | Plaid / Finicity Open-Banking Connector | §4.2.2 |
| 8-A | SOC 2 Type II Evidence Collector | §9.2 |
| 8-B | White-Label / OEM Tenant Branding | §8.1 |

---

## Sprint 6-A — Statistical A/B Testing Framework

### Deliverable
`decision_engine/ab_testing.py`

### Purpose
Provide a rigorous statistical framework for champion/challenger policy
experiments.  Tracks outcomes per arm, computes two-proportion z-tests without
scipy, enforces guardrails (approval delta, adverse-impact ratio delta), and
auto-promotes / auto-halts based on statistical evidence.

### Key Classes & Functions

| Symbol | Description |
|--------|-------------|
| `ExperimentConfig` | Dataclass: name, version tags, traffic split, α, MDE, power, guardrail thresholds |
| `Experiment` | Dataclass: lifecycle `DRAFT→RUNNING→PAUSED→COMPLETED|HALTED`, sample size progress |
| `ExperimentOutcomeRecord` | Per-decision attributed outcome (arm, decision, pd_score) |
| `StatisticalSignificanceReport` | z-score, p-value, 95% CI, power achieved, guardrail status, recommendation |
| `ABTestingFramework` | Orchestrator: `create_experiment()`, `start_experiment()`, `record_outcome()`, `get_significance_report()`, `export_results_as_evidence()`, `list_experiments()` |
| `required_sample_size()` | Power analysis calculator (MDE, α, power → n per arm) |

### DB Schema
```sql
CREATE TABLE ab_experiments (...)       -- experiment lifecycle
CREATE TABLE ab_experiment_outcomes (...) -- per-decision outcomes
```

### API Endpoints
```
POST /v1/experiments                          → Create experiment (DRAFT)
GET  /v1/experiments                          → List tenant experiments
POST /v1/experiments/{id}/start               → Transition to RUNNING
GET  /v1/experiments/{id}/report              → StatisticalSignificanceReport
POST /v1/experiments/{id}/export-evidence     → Evidence bundle for model-risk
```

### Tests
`decision_engine/tests/test_ab_testing.py` — 14 test cases covering:
- `required_sample_size()` math correctness
- DRAFT creation, conflict prevention
- Start / double-start guards
- Outcome recording
- Significance report with insufficient data → `INSUFFICIENT_DATA`
- Significance report with 20/20 outcomes → p-value, CI, recommendation
- Evidence export structure

---

## Sprint 6-B — NLG Executive Summary Generator

### Deliverable
`reporting/executive_summary.py`

### Purpose
Generate a weekly / monthly board-level narrative that aggregates portfolio KPIs,
model health, fair-lending AIRs, and compliance status into a structured report
with optional GPT-4o augmentation.  Renders to Markdown (default) or PDF.

### Key Classes & Functions

| Symbol | Description |
|--------|-------------|
| `PortfolioMetrics` | Dataclass: total_decisions, approval_rate, avg_loan_amount, etc. |
| `ModelHealthMetrics` | Dataclass: gini, ks_stat, psi, auc_roc |
| `FairLendingSnapshot` | Dataclass: air_gender, air_race, air_age |
| `ComplianceSummary` | Dataclass: open_escalations, pending_overrides, sod_violations |
| `ExecutiveSummary` | Output: headline, narrative (Markdown), action_items, key_metrics_table |
| `generate_executive_summary()` | Main entry: renders via template or LLM |
| `load_portfolio_metrics_from_db()` | Async helper querying `audit_log` |

### Render Modes
- `"template"` — Deterministic, always available, no external dependencies
- `"llm"` — GPT-4o augmented with numeric validation (requires `OPENAI_API_KEY`);
  falls back to `"template"` on error

### API Endpoint
```
GET /v1/analytics/executive-summary?period_label=2025-Q1&audience=cro&render_mode=template
```

### UI
`ui/analytics-dashboard/app/executive/page.tsx` — `NLGSummaryWidget` component added:
- Period selector (last-7d / last-30d / last-90d / Q1)
- Audience selector (CRO / Board / Regulator)
- Regenerate button (calls `/v1/analytics/executive-summary`)
- Headline banner, key-metrics grid, action-item list, expandable full narrative

---

## Sprint 7-A — Multi-Product Policy Engine

### Deliverable
`decision_engine/product_policies.py`

### Purpose
Extend the Decision Engine to support 6 distinct loan product types, each with
its own PD threshold, DTI cap, loan-amount bounds, fraud routing, APR ceiling,
required features, and product-specific rules (LTV for mortgage, vehicle age
for auto, DSCR for SBL, etc.).

### Supported Product Types
| Product Type | Notes |
|-------------|-------|
| `CREDIT_CARD` | Revolving; APR cap 29.99%; no collateral |
| `PERSONAL_LOAN` | Installment; unsecured; fair-lending focus |
| `AUTO_LOAN` | Collateralised; vehicle age ≤ 12 yrs; LTV check |
| `BNPL` | CFPB 2024 interpretive rule; low max amount |
| `MORTGAGE` | QM/ATR, HMDA, HOEPA; 43% DTI; LTV ≤ 97% |
| `SMALL_BUSINESS_LOAN` | CFPB §1071; DSCR ≥ 1.25; SBA-size check |

### Key Classes & Functions

| Symbol | Description |
|--------|-------------|
| `ProductPolicy` | Per-product policy configuration dataclass |
| `ProductPolicyInput` | Evaluation inputs: pd_score, fraud_score, income, DTI components, collateral |
| `ProductPolicyResult` | Verdict: pre_qualified, fraud_verdict, rule_outcomes, fcra_codes |
| `RuleOutcome` | Per-rule result: rule_name, passed, detail |
| `evaluate_product_policy()` | Evaluate inputs against a policy → result |
| `get_product_policy()` | Fetch default + tenant-override merged policy |
| `list_supported_products()` | All 6 product types for API serialisation |

### API Endpoints
```
GET  /v1/products                             → List all product policies
GET  /v1/products/{type}/policy               → Get effective policy for product type
POST /v1/products/{type}/evaluate             → Pre-qualify application against policy
```

### Tests
`decision_engine/tests/test_product_policies.py` — 11 test cases covering:
- All 6 product types returned by `list_supported_products()`
- Tenant override application
- Clean approval path for CREDIT_CARD, PERSONAL_LOAN, BNPL
- High PD → decline
- High fraud score → hard decline
- High DTI → decline (MORTGAGE)
- BNPL amount over limit
- Result structure validation

---

## Sprint 7-B — Plaid / Finicity Open-Banking Connector

### Deliverable
`ingestion-api/src/plaid_connector.py`

### Purpose
Integrate Plaid and Finicity APIs to enrich loan applications with real-time
bank cash-flow signals: monthly net income, NSF/overdraft count, payday-loan
detection, gambling transactions, unusual large deposits.

### Architecture
```
enrich_with_cash_flow_data(user_id, access_token, provider)
  ├── PlaidConnector.get_transactions()      — cursor-paginated
  ├── _analyse_transactions()                — NSF / gambling / payday detection
  ├── FinicityConnector (stub, same interface)
  └── _generate_mock_bank_data()             — dev fallback (no PLAID_CLIENT_ID)
```

### `BankDataSummary` Output Features
| Field | Use in Model |
|-------|-------------|
| `monthly_net_income` | Verifies stated income |
| `income_confidence` | Confidence score 0–1 |
| `nsfv_last_90_days` | Risk signal for overdraft propensity |
| `payday_loan_detected` | High-risk behaviour flag |
| `gambling_transaction_count` | Risk signal |
| `unusual_large_deposit_count` | Potential fraud signal |

### Environment Variables
```
PLAID_CLIENT_ID   — Plaid API key (falls back to mock if absent)
PLAID_SECRET      — Plaid secret
PLAID_ENV         — sandbox | development | production
FINICITY_APP_KEY  — Finicity app key
```

### API Endpoints
```
POST /v1/plaid/link-token                     → Create Plaid Link token
POST /v1/plaid/exchange-token                 → Exchange + enrich
POST /v1/bank/enrich/{application_id}         → Enrich with bank data
```

---

## Sprint 8-A — SOC 2 Type II Evidence Collector

### Deliverable
`compliance/soc2_evidence.py`

### Purpose
Automatically collect, package, and export evidence for SOC 2 Type II audits by
mapping platform capabilities to 15 AICPA Trust Service Criteria (CC1–CC9).

### TSC Coverage Matrix
| Control ID | Category | Platform Control | Collector |
|-----------|---------|-----------------|-----------|
| CC1.1 | Control Environment | Audit log + RBAC | `_collect_audit_log_evidence` |
| CC2.1 | Communication | Audit log immutability | `_collect_audit_log_evidence` |
| CC4.1 | Monitoring | Fair-lending metrics | `_collect_fair_lending_monitoring_evidence` |
| CC5.1 | Control Activities | Override review workflow | `_collect_audit_log_evidence` |
| CC6.1 | Logical Access | JWT RBAC + SOD engine | `_collect_rbac_evidence` |
| CC6.2 | Access Provisioning | Tenant onboarding + RBAC | `_collect_rbac_evidence` |
| CC6.3 | Access Removal | GDPR erasure workflow | generic |
| CC7.1 | Vulnerability Mgmt | Drift monitor + anomaly | generic |
| CC7.2 | Security Incidents | Observability tracing | generic |
| CC8.1 | Change Management | Alembic + model registry | `_collect_change_management_evidence` |
| CC9.1 | Vendor Selection | Third-party model registry | `_collect_vendor_registry_evidence` |
| CC9.2 | Business Continuity | Data-lineage + rollback | generic |

### Overall Status Logic
```
COMPLIANT      — all collected controls are SATISFIED
PARTIAL        — any PARTIAL or NOT_TESTED controls
NON_COMPLIANT  — any DEFICIENT controls
```

### API Endpoints
```
POST /v1/compliance/soc2/generate             → Generate evidence package
GET  /v1/compliance/soc2/packages             → List historical packages
GET  /v1/compliance/soc2/controls             → TSC catalogue
```

### Tests
`compliance/tests/test_soc2_evidence.py` — 14 test cases covering:
- TSC catalogue completeness
- Package generation (all controls / subset)
- Summary table format
- JSON round-trip serialisation
- `list_packages()` before/after generation
- `get_latest_package()` returns most recent

---

## Sprint 8-B — White-Label / OEM Tenant Branding

### Deliverable
`config_registry/tenant_branding.py`

### Purpose
Enable OEM partners and white-label customers to deploy the platform under their
own brand identity — custom logo, colours, domain, email sender, feature flags,
and API key prefix.

### `TenantBranding` Fields
| Field | Type | Example |
|-------|------|---------|
| `display_name` | str | "ACME Bank" |
| `logo_url_light` | str? | CDN URL |
| `logo_url_dark` | str? | CDN URL |
| `primary_color` | hex | "#2563EB" |
| `custom_domain` | FQDN? | "risk.acme.com" |
| `api_key_prefix` | str? | "acme" |
| `feature_flags` | Dict[str,bool] | `{"show_audit_log": true}` |

### Supported Feature Flags (14 flags)
`show_ai_explainability`, `show_fair_lending_tab`, `show_audit_log`,
`show_model_health`, `show_ab_testing`, `show_executive_summary`,
`enable_adverse_action_pdf`, `enable_plaid_enrichment`, `enable_multi_product`,
`enable_soc2_export`, `dark_mode_default`, `hide_score_raw`,
`require_mfa`, `allow_override_without_approval`

### `TenantBrandingStore` Operations
| Method | Description |
|--------|-------------|
| `get_branding(tenant_id)` | Fetch config |
| `upsert_branding(branding)` | Create / replace with audit |
| `patch_branding(tenant_id, updates)` | Partial update |
| `delete_branding(tenant_id)` | Soft delete (audit trail retained) |
| `list_tenants()` | All tenants with branding records |
| `get_audit_history(tenant_id)` | Last N change events |
| `get_css_variables(tenant_id)` | CSS `:root { --color-primary: … }` |

### API Endpoints
```
GET    /v1/tenant/branding               → Get branding config
PUT    /v1/tenant/branding               → Create / replace
PATCH  /v1/tenant/branding               → Partial update
GET    /v1/tenant/branding/css           → CSS custom properties (text/css)
GET    /v1/tenant/branding/audit         → Change audit trail
GET    /v1/tenant/branding/feature-flags → Supported flag catalogue
```

### Tests
`config_registry/tests/test_tenant_branding.py` — 20 test cases covering:
- Hex colour and URL validators
- Domain / API key prefix validation
- Feature flag boolean enforcement
- Full CRUD lifecycle (create → get → update → delete)
- `patch_branding()` partial update
- Audit trail entries for CREATED / UPDATED / DELETED
- CSS variable generation with and without branding record

---

## File Index — Sprint 6–8

```
decision_engine/
    ab_testing.py                           ← Sprint 6-A
    product_policies.py                     ← Sprint 7-A
    tests/
        test_ab_testing.py                  ← Sprint 6-A tests
        test_product_policies.py            ← Sprint 7-A tests

reporting/
    executive_summary.py                    ← Sprint 6-B

ingestion-api/src/
    plaid_connector.py                      ← Sprint 7-B

compliance/
    soc2_evidence.py                        ← Sprint 8-A
    tests/
        test_soc2_evidence.py               ← Sprint 8-A tests

config_registry/
    tenant_branding.py                      ← Sprint 8-B
    tests/
        test_tenant_branding.py             ← Sprint 8-B tests

decision-api/src/
    main.py                                 ← Sprint 6–8 endpoints appended

ui/analytics-dashboard/app/
    data-scientist/ab-testing/page.tsx      ← Sprint 6-A UI
    executive/page.tsx                      ← Sprint 6-B NLGSummaryWidget added

docs/
    SPRINT_6_8_CODING_PROMPTS_2026_04_10.md ← This document
```

---

## Running the New Tests

```bash
# From project root with venv activated
cd /path/to/credit-risk-platform

# Sprint 6-A
pytest decision_engine/tests/test_ab_testing.py -v

# Sprint 7-A
pytest decision_engine/tests/test_product_policies.py -v

# Sprint 8-A
pytest compliance/tests/test_soc2_evidence.py -v

# Sprint 8-B
pytest config_registry/tests/test_tenant_branding.py -v

# All Sprint 6-8 tests together
pytest decision_engine/tests/test_ab_testing.py \
       decision_engine/tests/test_product_policies.py \
       compliance/tests/test_soc2_evidence.py \
       config_registry/tests/test_tenant_branding.py -v
```

---

## Environment Variables — New in Sprint 6–8

| Variable | Module | Purpose |
|---------|--------|---------|
| `PLAID_CLIENT_ID` | `plaid_connector.py` | Plaid API key (omit → mock) |
| `PLAID_SECRET` | `plaid_connector.py` | Plaid secret |
| `PLAID_ENV` | `plaid_connector.py` | `sandbox` / `development` / `production` |
| `FINICITY_APP_KEY` | `plaid_connector.py` | Finicity app key |
| `OPENAI_API_KEY` | `executive_summary.py` | GPT-4o NLG (omit → template mode) |

All other modules use the existing `DATABASE_URL` environment variable.

---

## Dependency Notes

| Module | New Dependencies |
|--------|----------------|
| `ab_testing.py` | Pure stdlib math (no scipy) |
| `executive_summary.py` | Optional: `openai`, `reportlab` |
| `product_policies.py` | Stdlib only |
| `plaid_connector.py` | `httpx` (already in requirements.txt) |
| `soc2_evidence.py` | SQLAlchemy (already present) |
| `tenant_branding.py` | SQLAlchemy (already present) |

---

*Sprint 6–8 brings the platform to Phase 3 commercial readiness: statistical
experimentation, AI-generated executive reporting, multi-product credit policy,
open-banking enrichment, SOC 2 audit automation, and white-label OEM support.*
