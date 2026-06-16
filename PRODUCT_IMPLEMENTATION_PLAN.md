# Product Implementation Plan: Open-Banking-Driven Credit Products

## 1. Purpose

This plan defines how to deliver a prioritized portfolio of credit products using the existing platform and open-banking cash-flow data as the shared underwriting backbone.

Primary products (build first):
- BNPL
- Personal Loan
- SMB Loan (Secured)

Secondary products (build later):
- Credit Builder / Secured Card
- Overdraft / Cash Advance
- Mainstream Credit Card
- Auto Loan
- Mortgage

## 2. Delivery Principles

- Build one shared data plane first, then layer product policies.
- Keep a single canonical feature path for API and agent workflows.
- Treat each product as configuration + policy + tests, not bespoke pipeline forks.
- Require compliance, explainability, and release-safety gates before rollout.
- Prioritize products by near-term launch value and data readiness.

## 3. Release Waves

### Wave 1 (Primary Launch)
- BNPL
- Personal Loan
- SMB Loan (Secured)

### Wave 2 (Consumer Expansion)
- Credit Builder / Secured Card
- Overdraft / Cash Advance

### Wave 3 (Additional Data Dependency)
- Mainstream Credit Card
- Auto Loan

### Wave 4 (High Compliance + Collateral Complexity)
- Mortgage

## 4. Timeline (12 Weeks)

## Phase 1 (Weeks 1-2): Shared Open-Banking Backbone

Scope:
- Finalize provider-agnostic bank connector interface.
- Integrate Open Bank Project adapter in enrichment flow.
- Normalize transactions/accounts/balances into canonical summary contract.
- Harden enriched cash-flow contract and feature parity path.
- Add deterministic enrichment -> features integration tests.

Deliverables:
- Connector abstraction with provider selection/fallback.
- Stable enriched payload contract for product policies.
- Contract + integration tests.
- Structured observability and error taxonomy.

Exit criteria:
- Existing provider behavior remains backward compatible.
- End-to-end enrichment path deterministic on fixed fixtures.
- Staging API baseline thresholds pass.

## Phase 2 (Weeks 3-5): BNPL + Personal Loan Delivery

Scope:
- Harden Personal Loan profile (boundary-safe decisions, deterministic reasons).
- Harden BNPL profile (fraud routing, concurrent plan limits, merchant constraints).
- Add explainability/regression tests for both products.

Deliverables:
- Personal Loan and BNPL policy configs + tests.
- Boundary fixture packs and decision trace samples.
- Product runbooks for decline/manual-review routing.

Exit criteria:
- Boundary tests pass for PD/DTI/amount/fraud thresholds.
- Reason mappings are deterministic and complete.
- Regression metrics within agreed tolerances.

## Phase 3 (Weeks 6-8): SMB Loan (Secured) Delivery

Scope:
- Implement secured SMB profile with business cash-flow + collateral gates.
- Add required underwriting fields for secured SMB decisions.
- Add DSCR and collateral stress tests (low DSCR, high LTV, insufficient collateral coverage).

Deliverables:
- SMB secured policy rules and validation logic.
- Test fixtures for collateral quality and repayment capacity scenarios.
- Segment-level risk summary and monitoring slice definitions.

Exit criteria:
- Secure/decline/review behavior is deterministic at boundaries.
- Collateral and DSCR gates validated on fixed fixtures.
- Monitoring hooks defined for SMB secured segment.

## Phase 4 (Weeks 9-10): Cross-Product Hardening

Scope:
- Build cross-product simulation harness for Wave 1 products.
- Add reason-code + explainability regression suite.
- Add policy/feature consistency audits and remediation patches.

Deliverables:
- Simulation harness with baseline approval/review/decline distributions.
- Cross-product explainability regression tests.
- Audit reports (schema, feature-policy consistency, operational safety, test adequacy).

Exit criteria:
- Cross-product simulation outputs are deterministic.
- Explainability and reason-code suites pass for all primary products.
- High-risk audit findings resolved or explicitly waived.

## Phase 5 (Weeks 11-12): Launch Gates and Controlled Rollout

Scope:
- Add CI release gates for primary products.
- Configure canary rollout/rollback triggers.
- Finalize launch checklists and incident playbooks.

Deliverables:
- CI gate config and canary automation.
- Rollout and rollback runbook.
- End-to-end primary-product readiness suite.

Exit criteria:
- All release gates pass.
- Canary completes with no blocker incidents.
- Final readiness summary approved.

## 5. Workstreams

### A) Data and Integrations
- Connector abstraction and provider adapters.
- Canonical bank summary mapping and fallback behavior.
- Retry/backoff, timeout, and explicit error semantics.

### B) Feature Engineering
- Canonical API/agent feature parity.
- Cash-flow and thin-file synthesis hardening.
- Deterministic feature tests and versioning.

### C) Product Policy Engine
- Explicit required-field validation by product profile.
- BNPL + Personal Loan + SMB secured policy hardening.
- Tenant override safeguards and auditability.

### D) Explainability and Compliance
- Product-level decline reason consistency.
- Adverse-action coverage and regression checks.
- Audit trail completeness at each decision stage.

### E) QA, Observability, and Release
- End-to-end test matrix for primary products.
- Monitoring for drift, failure rates, and latency.
- Canary thresholds and automated rollback criteria.

## 6. Risks and Mitigations

- Risk: Provider schema drift or degraded enrichment.
  Mitigation: strict normalization + contract tests + fallback provider path.

- Risk: Feature-policy mismatch across API and agent paths.
  Mitigation: canonical feature module + CI parity harness.

- Risk: Secured SMB collateral data quality variability.
  Mitigation: explicit required-field validation + collateral sanity checks + manual review routing.

- Risk: Decision inconsistency at boundary thresholds.
  Mitigation: boundary fixtures + snapshot regression tests + deterministic reason mapping.

- Risk: Rollout instability.
  Mitigation: release gates + canary rollback automation + runbooks.

## 7. Definition of Done (Per Product)

- Product policy profile implemented and validated.
- Boundary fixtures for approve/reject/manual-review paths.
- Explainability and reason-code mapping regression coverage.
- Operational metrics and alerting added.
- Product docs and runbooks updated.

## 8. Suggested Branching and PR Strategy

- One branch per vertical slice (connector, feature parity, product profile, regression suite).
- Keep PRs small, testable, and tied to one roadmap prompt cluster.
- Require green CI plus explicit release-gate checks before merge.

## 9. Immediate Next Steps

1. Finalize connector and contract hardening for reliable enrichment inputs.
2. Ship BNPL and Personal Loan hardening with boundary and reason-code suites.
3. Implement SMB Secured Loan profile with collateral + DSCR validations.
4. Add cross-product simulation harness and launch gates for primary products.
