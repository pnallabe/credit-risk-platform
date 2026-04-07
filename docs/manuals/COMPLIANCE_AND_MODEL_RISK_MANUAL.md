# Compliance & Model Risk Management Manual
## Credit Risk Platform — `credit-risk-platform`

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: Compliance Officers, Model Risk Managers, OCC / CFPB Examiners, Internal Audit
> Regulatory scope: SR 11-7, ECOA / Reg B, HMDA, CECL / IFRS 9
> Cross-references: `docs/TECHNICAL_ARCHITECTURE.md`, `docs/GOVERNANCE_AUDIT_2026_04_06.md`, `docs/IMPLEMENTATION_PLAN_CORE_PLATFORM_2026_04_07.md`

---

## 1. Platform Governance Overview

### What Decisions the Platform Makes

The Credit Risk Platform is an **automated underwriting engine** that performs the following decision actions for each submitted loan application:

| Action | Description |
|---|---|
| **Feature computation** | Derives ~30+ credit risk features from raw application data (income ratios, credit utilization, fraud indicators) |
| **Probability of Default scoring** | XGBoost model produces a numerical PD score (0–1); mapped to five risk tiers (Prime, Near-Prime, Sub-Prime, Deep Sub-Prime, Decline) |
| **Fraud risk scoring** | Isolation Forest model produces a fraud anomaly score for each application |
| **Credit policy evaluation** | Rule-based hard cutoffs and soft criteria determine APPROVE / DECLINE / REFER outcome |
| **Adverse action reason code generation** | SHAP explainability layer maps top model drivers to CFPB-compliant reason codes |
| **Audit record creation** | Every decision is appended immutably to the audit log with model version, policy version, feature snapshot, and timestamp |

### Human-in-the-Loop Override

- **REFER outcomes**: applications that fall below a defined confidence threshold or trigger policy exception flags are routed to a human review queue rather than receiving an automated final decision.
- **Manual override capability**: authorized credit analysts can override a platform APPROVE or DECLINE decision. Every override is logged with: `reviewer_id`, `override_reason`, `original_decision`, `override_decision`, `timestamp`. This log is append-only and immutable.
- **Audit trail**: all human overrides are queryable via `GET /v1/audit/{application_id}` and are included in audit package exports.

### Audit Log Schema

The audit log (`audit/logger.py`, backed by Postgres in production) stores the following fields for every decision event:

| Field | Type | Description | Immutability |
|---|---|---|---|
| `audit_id` | UUID | Unique audit record identifier | Immutable |
| `tenant_id` | String | Tenant scoping key — planned P0.1 | Immutable once written |
| `application_id` | String | Applicant / loan application identifier | Immutable |
| `decision` | Enum | APPROVE / DECLINE / REFER | Immutable |
| `pd_score` | Float | Probability of default (0–1) | Immutable |
| `fraud_score` | Float | Fraud anomaly score (0–1) | Immutable |
| `risk_tier` | String | Prime / Near-Prime / Sub-Prime / etc. | Immutable |
| `reason_codes` | JSON array | Adverse action reason codes | Immutable |
| `shap_values` | JSON | SHAP feature importance snapshot | Immutable |
| `feature_snapshot` | JSON | Feature values used at decision time | Immutable |
| `model_version` | String | MLflow model version string | Immutable |
| `policy_version` | String | Policy config version hash | Immutable |
| `decision_timestamp` | Timestamp | UTC timestamp of decision creation | Immutable |
| `request_id` | UUID | Unique request identifier for idempotency | Immutable |
| `override_flag` | Boolean | True if a human override was applied | Immutable |
| `override_reason` | String | Analyst override justification | Immutable when set |

**Immutability guarantee**: Audit rows are appended only — no UPDATE or DELETE operations are permitted by the application layer. Postgres row-level security enforces this in production.

**Retention**: Audit records are retained indefinitely by default. Configurable retention policy is implemented in `compliance/retention_policy.py` (minimum 7 years recommended for ECOA compliance).

---

## 2. Model Inventory

| Model Name | Purpose | Algorithm | Training Data Type | Current Version | Monitoring Status |
|---|---|---|---|---|---|
| `credit_risk_pd` | Probability of Default scoring | XGBoost Gradient Boosted Tree | Historical loan performance (vintage data) | Tracked in MLflow | **Partial** — drift detection in `agents/monitoring_agent.py`; fairness check planned |
| `fraud_detection` | Application fraud anomaly detection | Isolation Forest (unsupervised) | Historical transaction + application data | Tracked in MLflow | **Partial** — anomaly threshold monitoring |
| `pricing` | Risk-adjusted rate / pricing | Lookup / rules-based engine | Policy-defined | `config/agent_config.yaml` | Manual review |

### Where Model Artifacts Are Stored and Versioned

- **MLflow registry**: all model artifacts are stored in and served from MLflow (`mlflow_config/`). Each training run creates a new version in the registry with a unique `run_id`.
- **GCS**: serialized joblib artifacts are also stored in GCS for Cloud Run deployments (`GCS_BUCKET_NAME/models/`).
- **Version traceability**: the `model_version` field in every audit record links back to the exact MLflow run that produced the artifact.

### Model Validation Workflow

```
Train (scripts/retrain_model.py or make train-pd)
  ↓
Validate (AUC, KS, Gini; fairness metrics via scripts/run_fairness_check.py)
  ↓
Approve (MRM sign-off via scripts/review_queue_cli.py — records approval with reviewer_id + timestamp)
  ↓
Production bind (mlflow models transition-to-production; update binding in config registry)
  ↓
Monitor (agents/monitoring_agent.py — PSI, AUC/KS drift, fairness metrics monthly)
  ↓
Retrain trigger (drift threshold exceeded → scripts/retrain_model.py → repeat cycle)
```

All approvals and version transitions are logged with reviewer identity, timestamp, and rationale.

---

## 3. SR 11-7 Compliance Checklist

### 3a — Model Risk Management Governance

| Requirement | Platform Implementation | Status |
|---|---|---|
| **Policy owner documented** | Head of Credit Risk / CRO as policy owner of `config/agent_config.yaml` versions | Partially implemented — version control via git; formal policy ownership document pending |
| **Change control** | Policy config changes require PR approval + golden test pass; audit log captures `policy_version` on every decision | **YES** |
| **Model documentation** | `compliance/generate_model_doc.py` generates SR 11-7 compliant model cards | **Partial** — template exists; auto-generation triggered post-training |
| **Model governance register** | MLflow registry serves as model inventory | **Partial** — formal governance register (`models/model_card.json` pattern) in progress |

### 3b — Validation Independence

| Requirement | Platform Implementation | Status |
|---|---|---|
| **Separate development vs. validation** | Train scripts (`scripts/retrain_model.py`) are separate from validation scripts (`scripts/check_governance_thresholds.py`, `scripts/mrm_lifecycle.py`) | **YES** |
| **Out-of-time validation** | Test set uses held-out time period (not random split) | **Partial** — implemented in CC PD pipeline; confirm for all models |
| **Challenger model** | Policy Workbench supports champion/challenger setup (`decision_engine/policy_version_store.py`) | **Partial** — framework exists; A/B traffic split not yet production-wired |
| **Independent validation sign-off** | `scripts/review_queue_cli.py` captures MRM reviewer approval before production bind | **YES** |

### 3c — Ongoing Monitoring

| Metric | Tool | Threshold | Alert Mechanism |
|---|---|---|---|
| Population Stability Index (PSI) | `agents/monitoring_agent.py` | PSI > 0.2 triggers review | Configurable alert |
| AUC / KS degradation | `agents/monitoring_agent.py` | > 5% AUC drop from baseline | Alert + review queue |
| Fair lending disparate impact | `scripts/run_fairness_check.py` (planned) | 80% rule threshold | Compliance escalation |
| Approval rate by protected class | `compliance/engine.py` | Configurable threshold | Compliance escalation |

### 3d — Audit Artifact Auto-Generation

On every model production bind, the following artifacts are automatically generated:

1. Model card (`compliance/generate_model_doc.py`) — algorithm, training data summary, performance metrics, limitations
2. Validation report — out-of-time AUC, KS, Gini, discrimination metrics
3. Fairness assessment — disparate impact ratios by protected class proxies
4. Governance approval record — reviewer, timestamp, policy version, binding decision

---

## 4. CFPB Reg B (Adverse Action) Compliance

### How the Platform Generates Adverse Action Reason Codes

1. **SHAP explainability** (`agents/explainability_agent.py`) computes SHAP values for each application's XGBoost decision.
2. The top N features (typically 4–5) with the most negative impact on the decision are mapped to standardized reason codes.
3. Reason codes follow the Federal Reserve / CFPB sample adverse action notice format.

### Reason Code Mapping (Reference)

| Platform Reason Code | Plain-Language Description | CFPB / Reg B Mapping |
|---|---|---|
| R01 | Debt-to-income ratio too high | "Amount of monthly obligations in relation to income" |
| R02 | Insufficient credit history | "Length of credit history" |
| R03 | Credit score below threshold | "Credit score" |
| R04 | High existing debt burden | "Amount owed on revolving accounts" |
| R05 | Delinquency record present | "Derogatory public record or collection filed" |
| R06 | Employment history insufficient | "Inadequate relationship with lender / employment record" |
| R07 | Fraud indicator present | "Unable to verify identity / information in application" |
| R08 | Loan amount exceeds policy limit | "Amount requested exceeds guidelines" |
| R09 | Payment-to-income ratio exceeds limit | "Amount of monthly obligations in relation to income" |

### Adverse Action Notice Generation

- The platform **generates** reason codes and SHAP explanation outputs.
- Adverse action notices (written letters per ECOA/Reg B) must be generated by the lender's downstream loan origination system using the reason codes and decision output from the platform.
- The platform's API response includes all fields required to populate a Reg B notice: `decision`, `reason_codes`, `shap_explanation`, `decision_timestamp`, `application_id`.

### SHAP Output Interpretation

| SHAP Field | Meaning |
|---|---|
| Positive SHAP value for a feature | This feature increased the applicant's credit score (favorable) |
| Negative SHAP value for a feature | This feature decreased the applicant's credit score (adverse) |
| Top 4–5 features by absolute SHAP | These are the primary drivers of the decision — these map to reason codes |

---

## 5. Fair Lending (ECOA / HMDA)

### Fairness Check Scripts

The platform provides fairness monitoring via the compliance module:

```bash
# Run disparate impact analysis across protected class proxies
python scripts/run_fairness_check.py \
  --tenant-id your-tenant \
  --start-date 2026-01-01 \
  --end-date 2026-03-31 \
  --output-format json
```

**What it tests**:
- Approval rate disparities by race/ethnicity proxies (geography + surname proxy method)
- Approval rate disparities by gender proxies
- 80% rule (adverse impact ratio): if the approval rate for a protected class is < 80% of the highest-approval-rate class, a flag is triggered
- Credit score distribution comparison across proxied classes

**Output**: JSON report with approval rates by group, adverse impact ratios, flagged disparities.

### Disparate Impact Metrics Tracked

| Metric | Threshold | Action if Breached |
|---|---|---|
| Adverse Impact Ratio (AIR) | < 0.80 | Compliance escalation + model review |
| Mean Approval Rate Difference | > 5 pp between groups | Review required |
| SHAP Mismatch by Protected Proxy | Feature importance differs by > 15% | Model fairness investigation |

### HMDA Field Mapping

The `compliance/` module extracts HMDA-required fields from decision records:

| HMDA Field | Platform Source | Location |
|---|---|---|
| Application date | `decision_timestamp` | `audit/logger.py` |
| Loan type | `loan_purpose` | `schemas/contracts.py` |
| Property type / purpose | `loan_purpose` | `schemas/contracts.py` |
| Action taken | `decision` (APPROVE/DECLINE/REFER) | `audit/logger.py` |
| Applicant income | `annual_income` / 12 | `feature_pipeline/features.py` |
| HMDA race / ethnicity | Not collected by platform (lender responsibility) | — |
| Rate spread | Derived from `pricing/` model output | `models/pricing/` |

HMDA LAR (Loan Application Register) export is available via `reporting/` module.

---

## 6. Audit Workflow

### 6a — Retrieve a Complete Audit Record for a Single Application

```bash
# Via Decision API
curl -X GET http://localhost:8081/v1/audit/APP-TEST-001 \
  -H "Authorization: Bearer <JWT with tenant_id>"

# Returns full audit record including:
# - decision, scores, reason codes, SHAP values
# - feature snapshot at time of decision
# - model_version, policy_version
# - all override records (if any)
# - timestamps
```

### 6b — Generate a Model Monitoring Report

```bash
# Generate monitoring report for the PD model
python scripts/mrm_lifecycle.py \
  --model-name credit_risk_pd \
  --version 3 \
  --reporting-period 2026-Q1 \
  --output-dir reports/model_monitoring/

# Output:
# reports/model_monitoring/credit_risk_pd_v3_2026Q1_report.json
# reports/model_monitoring/credit_risk_pd_v3_2026Q1_report.html
```

**Report contents**: AUC, KS, Gini, PSI, approval rate trend, fairness metrics, drift flag status, next review date.

### 6c — Export a Full Audit Package for Regulatory Examination

```bash
# Generate complete audit package for a date range
python scripts/check_audit_completeness.py \
  --tenant-id acme-bank \
  --start-date 2025-07-01 \
  --end-date 2026-06-30 \
  --output-dir exports/audit_package_2026/
```

**Audit package contents**:
- All decision records for the period (JSON + CSV)
- Model cards for all active model versions during the period
- Policy version history and approval records
- Fairness assessment reports
- Monitoring reports (PSI, AUC trends)
- Override log with justifications
- HMDA LAR export

### 6d — Audit Package Completeness Validation

```bash
python scripts/check_audit_schema_compat.py --package-dir exports/audit_package_2026/
# Validates: all required fields present, no null decisions, model versions resolvable,
# policy versions traceable, fair lending metrics computed for the period
```

---

## 7. Policy Change Governance

### Proposing and Versioning a Policy Change

1. **Propose** the change via PR: modify `config/agent_config.yaml` or the policy version store (`decision_engine/policy_version_store.py`).
2. **Document** the business rationale in the PR description.
3. **Run the golden test** (`tests/test_decision_parity.py`) — must pass.
4. **Run the impact analysis**: `python scripts/check_governance_thresholds.py --policy-diff`
   - Shows expected change in approval rate, risk tier distribution, and adverse action reason code frequency.
5. **MRM review**: assigned model risk reviewer approves via `scripts/review_queue_cli.py` (records `reviewer_id`, timestamp, sign-off).
6. **Merge and deploy**: policy version hash is computed at deploy time and stored in all subsequent audit records.

### Champion / Challenger Test Framework

```bash
# Configure a challenger policy in the policy version store
python decision_engine/policy_version_store.py add-version \
  --version-id challenger-v2 \
  --config config/challenger_policy_v2.yaml \
  --description "Test tighter DTI thresholds in prime tier"

# Route 10% of traffic to challenger (configured in decision-api/src/main.py)
# CHALLENGER_TRAFFIC_PCT=0.10 is set via environment variable after MRM approval
```

**Measurement**: compare `approval_rate`, `bad_rate_forecast`, `risk_tier_distribution` between champion and challenger cohorts over a minimum 30-day window.

**Conclusion criteria**: challenger is promoted if it achieves equal or better expected bad rate at a statistically significant sample size (minimum 500 decisions per arm).

### Policy Rollback Procedure

```bash
# Roll back to previous policy version with full audit trail
python decision_engine/policy_version_store.py rollback \
  --from-version challenger-v2 \
  --to-version champion-v1 \
  --reason "DTI threshold causing unacceptable approval rate decline"
  --reviewer-id john.doe@lender.com

# This writes a rollback event to the audit log and immediately switches
# the active policy version in the decision engine
```

All rollbacks are logged with: `rollback_timestamp`, `from_version`, `to_version`, `rollback_reason`, `reviewer_id`.

---

## 8. Known Gaps and Remediation Timeline

| Gap | Description | Impact | Remediation Reference | Target |
|---|---|---|---|---|
| **`eval()`-based policy rules** | `agents/decision_engine_agent.py` evaluates YAML conditions via `eval()`. Not governance-grade; not auditable. | Governance audit finding; MRM risk | P0.3 — replace with `decision_engine/policy_dsl.py` | 1–2 weeks |
| **Tenant isolation absent** | No `tenant_id` in audit log, BigQuery schemas, or JWT enforcement | Cross-tenant data leakage; SaaS unsellable | P0.1 — add `TenantContext` throughout | 1–2 weeks |
| **Dual decisioning engines** | Decision API and agent path can produce different credit decisions for identical input | Regulatory inconsistency; MRM finding risk | P0.2 — create `credit_core` canonical package | 2–3 weeks |
| **Deterministic replay not implemented** | Cannot replay a historical decision with the exact model artifact, policy version, and feature set from the original decision time | Audit examination gap; cannot satisfy post-hoc review requests | P3.1 — add artifact hashes + feature snapshots to audit events | Phase 3 |
| **Fair lending fairness check script** | `scripts/run_fairness_check.py` is planned but not confirmed as fully operational | Cannot demonstrate automated fair lending monitoring | P2.x — wire to production decision data | Phase 2 |
| **Redis rate limiting inactive** | Redis is provisioned but rate limiting and idempotency are not implemented | Duplicate audit writes possible; no tenant quota enforcement | P1.1 — implement token-bucket rate limiter | Phase 1 |
| **Streamlit dashboard on mock data** | `dashboard/app.py` does not reflect production decision data | Monitoring gap; examiner cannot use dashboard for evidence | P2.x — wire to BigQuery | Phase 2 |
