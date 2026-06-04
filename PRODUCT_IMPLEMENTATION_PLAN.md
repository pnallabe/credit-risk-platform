# Product Implementation Plan: Open-Banking-Driven Credit Products

## 1. Purpose

This plan defines how to deliver a portfolio of credit products using the existing credit-risk platform and open-banking cash-flow data as the shared underwriting backbone.

Target products:
- Personal Loan
- BNPL
- Credit Builder / Secured Card
- Overdraft / Cash Advance
- SMB Working Capital
- Mainstream Credit Card (later)
- Auto Loan (later)
- Mortgage (later)

## 2. Delivery Principles

- Build one shared data plane first, then add product policies on top.
- Keep a single canonical feature path for API and agent workflows.
- Treat every product as configuration + policy + tests, not custom pipeline forks.
- Require compliance and safety gates before rollout.
- Roll out by ascending data and regulatory complexity.

## 3. Release Waves

### Wave 1 (fastest path, strongest fit)
- Personal Loan
- BNPL

### Wave 2 (same consumer cash-flow foundation)
- Credit Builder / Secured Card
- Overdraft / Cash Advance

### Wave 3 (business extension)
- SMB Working Capital

### Wave 4 (additional external data required)
- Mainstream Credit Card
- Auto Loan

### Wave 5 (heavy compliance + collateral)
- Mortgage

## 4. Timeline (12 Weeks)

## Phase 1 (Weeks 1-3): Shared Open-Banking Backbone

Scope:
- Add provider-agnostic bank connector interface.
- Integrate Open Bank Project adapter into existing enrichment flow.
- Normalize transactions/accounts/balances to canonical bank summary contract.
- Ensure thin-file feature enrichment consumes canonical summary fields.
- Add integration tests for enrichment -> features -> decision path.

Deliverables:
- Open-banking adapter abstraction with provider selection.
- Stable enriched payload contract.
- Contract and integration test suites.
- Observability events and error taxonomy.

Exit criteria:
- Existing provider behavior remains backward compatible.
- End-to-end enrichment path is deterministic on fixed fixtures.
- Canary and API baseline thresholds pass in staging.

## Phase 2 (Weeks 4-6): Wave 1 Product Delivery

Scope:
- Implement Personal Loan product profile and thresholds.
- Implement BNPL product profile and short-horizon controls.
- Add product-specific reason-code mapping and explainability checks.
- Add scenario backtests for approval-rate and expected-loss proxies.

Deliverables:
- Product policy configs and tests.
- Product regression dashboard output artifacts.
- Updated runbooks for declines/manual review routing.

Exit criteria:
- Product policy tests pass including boundary cases.
- Explainability outputs map to expected decline reasons.
- Regression metrics within pre-defined tolerances.

## Phase 3 (Weeks 7-8): Wave 2 Product Delivery

Scope:
- Add Credit Builder / Secured Card policy profile.
- Add Overdraft / Cash Advance policy profile.
- Add conservative limit and repayment guardrails.

Deliverables:
- Policy rules and test fixtures for thin-file cohorts.
- Product-level QA report with fraud sensitivity checks.

Exit criteria:
- Stable decision distribution on thin-file slices.
- No severe regression in fraud/risk controls.

## Phase 4 (Weeks 9-10): Wave 3 Product Delivery

Scope:
- Add SMB Working Capital profile using business cash-flow signals.
- Add business-specific underwriting fields and DSCR-style checks.
- Add monitoring slices for seasonal and volatile revenue cohorts.

Deliverables:
- SMB policy profiles and tests.
- Performance and fairness summaries for business cohorts.

Exit criteria:
- SMB policy pass/fail behavior validated on curated fixtures.
- Monitoring and alerting configured for new product segment.

## Phase 5 (Weeks 11-12): Hardening and Controlled Launch

Scope:
- Cross-product regression suite and release gates.
- Progressive canary rollout automation.
- Incident rollback and policy hotfix runbooks.

Deliverables:
- Cross-product test harness and CI gates.
- Launch checklist and runbooks.

Exit criteria:
- All launch-gate checks pass.
- Canary rollout completes with no blocker incidents.

## 5. Workstreams

### A) Data and Integrations
- Connector abstraction and provider adapters.
- Mapping and normalization to canonical contract.
- Retry/backoff and provider-failure fallback strategy.

### B) Feature Engineering
- Canonical feature parity between API and agent paths.
- Cash-flow stability, affordability, and thin-file composite improvements.
- Deterministic feature tests and versioning.

### C) Product Policy Engine
- Product profiles with explicit required fields.
- Fraud/DTI/amount/rule gate standardization.
- Tenant override safety checks and auditability.

### D) Explainability and Compliance
- Product-level decline reason consistency.
- Adverse-action text coverage and regression checks.
- Audit trail completeness for each decision stage.

### E) QA, Observability, and Release
- End-to-end test matrix by product and edge case.
- Monitoring for drift, failure rates, and latency.
- Canary thresholds and auto-rollback criteria.

## 6. Risks and Mitigations

- Risk: Provider payload variability and schema drift.
  Mitigation: strict normalization layer + contract tests + fallback path.

- Risk: Policy inconsistency across products.
  Mitigation: single policy evaluator and shared decision gate semantics.

- Risk: Feature divergence between API and agent pipelines.
  Mitigation: one canonical feature module + parity tests in CI.

- Risk: Rollout instability.
  Mitigation: staged canary rollout, health checks, and rollback playbook.

- Risk: Compliance gaps under rapid iteration.
  Mitigation: mandatory reason-code and audit-log checks in release gates.

## 7. Definition of Done (Per Product)

- Product policy profile implemented.
- Product test fixtures for approve/decline/manual-review boundaries.
- Explainability reason mapping validated.
- Operational metrics and alerting added.
- Documentation and runbook updated.

## 8. Suggested Branching and PR Strategy

- One feature branch per phase or sub-epic.
- Keep PRs vertical and testable (connector, features, policy, tests).
- Require green CI + explicit release-gate checks before merge.

## 9. Immediate Next Steps

1. Implement connector abstraction and OBP adapter behind existing enrichment API.
2. Lock contract tests for normalized bank summary payload.
3. Ship Personal Loan and BNPL policy profiles first.
4. Add cross-product simulation harness before Wave 2 rollout.
