# Data Contracts Changelog

All notable changes to the credit-risk-platform data contracts are documented here.
Versioning follows [Semantic Versioning](https://semver.org/):
- **MAJOR** — breaking change (field removed, renamed, or type changed)
- **MINOR** — backwards-compatible addition (new optional field)
- **PATCH** — documentation or description fix; no schema change

---

## [1.0.0] — 2026-04-25

### Added — Initial release

#### Domain: `application`
- `ApplicantProfileV1` — canonical applicant demographics and financial snapshot
  with thin-file alt-data signals (rent, utility, mobile score, bank account age,
  cash flow)
- `ApplicationSubmittedV1` — event emitted on application receipt; includes
  idempotency key support
- `ApplicationValidatedV1` — post-ingestion validation result with completeness
  score and thin-file flag

#### Domain: `decisions`
- `PricingTermsV1` — approved loan terms (amount, APR, term, credit limit,
  EL, expected profit, risk-based pricing tier)
- `DecisionExplanationV1` — SHAP-based explanation with per-factor Reg B reason
  codes and adverse action narrative; PD score and fraud probability included
- `CreditDecisionV1` — final underwriting verdict (APPROVE | REJECT |
  MANUAL_REVIEW) with policy version, model version, experiment ID, and
  amendment linkage via `supersedes_decision_id`
- `DecisionRecordV1` — composite bundle of decision + explanation for single-
  payload consumers

#### Domain: `features`
- `FeatureVectorV1` — point-in-time feature snapshot with `as_of_date` for
  look-ahead-bias prevention and SHA-256 `feature_hash` for audit
- `FeatureDriftResultV1` — per-feature PSI + KS metrics
- `FeatureDriftReportV1` — aggregate drift report with PSI thresholds:
  stable (<0.10) / minor (0.10–0.25) / major (>0.25)
- `ModelPerformanceSnapshotV1` — AUC-ROC, Gini, KS, Brier score, bad rate,
  and champion promotion eligibility flag

#### Domain: `portfolio`
- `VintageCohortV1` — origination-month cohort performance by MOB with
  cumulative default rate and net loss rate
- `RollRateBucketV1` — monthly delinquency transition matrix with forward roll
  rate, cure rate, and charge-off rate headlines
- `SegmentBreakdownV1` — approval rate and expected profit by segment dimension
  (FICO band, DTI band, channel, etc.)
- `PortfolioSummaryV1` — aggregate portfolio health with volume, balance, risk,
  performance, and profitability metrics; links to segment breakdown records

#### Domain: `compliance`
- `AdverseActionNoticeV1` — FCRA/Reg B adverse action notice with up to 4
  principal reason codes, credit score disclosure (FCRA §615(a)), delivery
  method, and 30-day deadline tracking
- `HMDARecordV1` — full HMDA LAR record per 2018+ Reg C spec including loan
  characteristics, property, applicant demographics (PII-annotated), AUS, and
  rate spread
- `Metro2TradelineV1` — monthly credit bureau tradeline in CDIA Metro 2 format
  with 24-month payment history profile and PII annotations
- `FairLendingFlagV1` — disparate impact / 4-5ths rule monitoring flag with
  approval rate ratio, statistical significance, and reviewer workflow fields

#### Domain: `audit`
- `DecisionAuditRecordV1` — immutable end-to-end pipeline audit trail with
  per-step hashes and top-level `record_hash` for tamper detection
- `PolicyChangeAuditV1` — immutable policy version change log with diff,
  regulatory basis, committee approval linkage, and `record_hash`
- `ModelDeploymentAuditV1` — model lifecycle audit from training through
  champion promotion / rollback with AUC gate evidence
- `ManualReviewRecordV1` — credit analyst manual review outcome with override
  rationale, escalation chain, and review duration

#### Domain: `events`
- `DataContractEvent` — base event envelope with deduplication `event_id`,
  correlation/causation chain, and tenant scoping
- `ApplicationSubmittedEvent` — typed wrapper for `application.submitted`
- `DecisionMadeEvent` — typed wrapper for `decision.approved | rejected |
  manual_review`
- `BatchCompleteEvent` — typed wrapper for `batch.complete`
- `DriftAlertEvent` — typed wrapper for `model.drift_alert`
- `PolicyChangedEvent` — typed wrapper for `policy.changed | policy.activated`

#### Infrastructure
- `DataContractRegistry` — schema catalogue with JSON Schema export (draft-07),
  OpenAPI components export, and payload validation

---

## Planned for [1.1.0]

- `BureauPullRecordV1` — credit bureau pull metadata (bureau, pull type,
  pull timestamp, permissible purpose)
- `IncomeVerificationRecordV1` — income verification attempt and result
  (bank statement / paystub / tax return)
- `CollateralValuationV1` — mortgage property valuation record (AVM / appraisal)
- `CoApplicantProfileV1` — secondary applicant on joint applications

## Planned for [2.0.0]

- Remove deprecated `channel` field from `ApplicationSubmittedV1`
  (superseded by `OriginationChannelV1` enum)
- Rename `pd_band` → `default_risk_band` across all contracts for clarity
