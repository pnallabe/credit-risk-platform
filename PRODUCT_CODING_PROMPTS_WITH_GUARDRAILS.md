# Series of Coding Prompts With Guard Rails

This file contains detailed prompts you can run sequentially with a coding agent to deliver the product roadmap.

Priority focus for this prompt pack:
- BNPL
- Personal Loan
- SMB Loan (Secured)

Secondary products are intentionally moved to the end.

Usage guidance:
- Execute prompts in order.
- Do not skip guard-rail prompts.
- Require tests and a short implementation note after every prompt.

---

## Global Guard-Rail Prompt (Run Before Every Implementation Prompt)

Use this prompt before each coding task:

```text
You are implementing changes in a regulated credit-risk platform.
Guard rails are mandatory:
1) Preserve backward compatibility unless explicitly instructed otherwise.
2) Do not remove existing tests. Add or update tests for every behavior change.
3) Keep one canonical feature path; do not duplicate feature logic.
4) Add structured logging for failures and edge cases.
5) Validate inputs and return explicit, typed errors.
6) Avoid broad refactors unrelated to this task.
7) Update docs for any API/schema change.
8) Provide: (a) files changed, (b) tests added/updated, (c) risk notes.
Now implement the task below.
```

---

## Prompt 1: Provider-Agnostic Open-Banking Connector Layer

```text
Task:
Create a provider-agnostic connector interface for bank enrichment in ingestion-api/src/plaid_connector.py.

Requirements:
- Introduce a clean interface for providers (plaid, finicity, openbankproject, mock).
- Preserve existing public API function signatures where possible.
- Add provider selection via config with safe fallback behavior.
- Keep output normalized to the existing BankDataSummary contract.

Implementation details:
- Add an adapter class for Open Bank Project provider.
- Map OBP accounts/transactions/balances into canonical transaction/account models.
- Implement retries/backoff for provider HTTP calls.
- Add structured logs with provider, application_id, and error category.

Testing:
- Unit tests for provider selection and fallback.
- Unit tests for OBP mapping edge cases (empty transactions, null balances, malformed date).
- Regression test proving plaid flow remains unchanged.

Deliverables:
- Code changes
- Tests
- Brief compatibility note
```

## Prompt 2: Wire OBP into Enrichment Endpoints

```text
Task:
Integrate Open Bank Project as a provider option in decision-api/src/main.py enrichment routes.

Requirements:
- Extend existing enrichment endpoint provider handling.
- Keep authentication and existing response structure unchanged.
- Return explicit 4xx/5xx semantics for provider errors.

Implementation details:
- Add provider validation and explicit allow-list.
- Ensure response still serializes BankDataSummary.
- Add error mapping for timeout, auth failure, invalid account link, and upstream schema mismatch.

Testing:
- API tests for success path with OBP provider.
- API tests for provider timeout and invalid provider.
- Regression tests for current providers.

Deliverables:
- Updated routes and request validation
- Endpoint tests
- API compatibility note
```

## Prompt 3: Contract Hardening for Enriched Cash-Flow Fields

```text
Task:
Update schemas/contracts.py to harden and document enriched cash-flow fields used by thin-file logic.

Requirements:
- Ensure enriched fields are present as optional validated fields.
- Add clear descriptions and bounds validation.
- Keep backward compatibility for existing consumers.

Implementation details:
- Validate non-negative numeric constraints.
- Add tests for missing fields, invalid negative values, and null handling.

Testing:
- Schema validation unit tests.
- Regression test with old payload shape.

Deliverables:
- Contract updates
- Validation tests
- Migration note for downstream users
```

## Prompt 4: Strengthen Thin-File Feature Synthesis

```text
Task:
Enhance thin-file feature synthesis in credit_core/features.py while preserving deterministic behavior.

Requirements:
- Improve thin_file_alt_score using cash-flow and account-tenure signals.
- Keep feature outputs stable and clipped to expected ranges.
- Do not fork feature logic outside canonical module.

Implementation details:
- Add optional weighted contributions for inflow/outflow stability and overdraft proxies.
- Keep defaults backward compatible.
- Add clear comments for model-risk reviewers.

Testing:
- Deterministic tests on fixed fixtures.
- Tests for all-null, zero-inflow, and high-volatility inputs.
- Parity test between API and agent feature generation paths.

Deliverables:
- Feature updates
- Tests and parity report
- Versioning note
```

## Prompt 5: Enforce API/Agent Feature Parity

```text
Task:
Guarantee parity between agents/feature_engineering_agent.py and credit_core/features.py.

Requirements:
- No divergent transformations.
- Same input should produce same engineered values in both paths.

Implementation details:
- Add a test utility that compares feature outputs row-by-row.
- Fail CI on mismatch.

Testing:
- Parity tests on thin-file and non-thin-file fixtures.

Deliverables:
- Parity harness
- CI-integrated parity test
```

## Prompt 6: Product Policy Validation Layer

```text
Task:
Extend decision_engine/product_policies.py with explicit required-field validation and clearer gate outcomes.

Requirements:
- Validate required fields per product type before policy checks.
- Emit structured flags for missing required fields.
- Preserve existing evaluate_product_policy return contract.

Implementation details:
- Add helper: validate_required_features(product_type, input).
- Integrate validation early in evaluation flow.
- Avoid changing unrelated policy behavior.

Testing:
- Tests per product type for missing required fields.
- Regression tests for existing happy paths.

Deliverables:
- Validation logic
- Product-specific tests
- Risk note for policy governance
```

## Prompt 7: Personal Loan Product Profile Hardening

```text
Task:
Implement and harden Personal Loan profile behavior with boundary-safe decisions.

Requirements:
- Validate approve/reject/review behavior at PD/DTI/amount edges.
- Ensure reason codes are consistent and deterministic.

Implementation details:
- Add policy fixtures for edge values.
- Verify decision outputs are stable under close threshold values.

Testing:
- Boundary tests around max_dti, pd_threshold_approve, pd_threshold_refer.
- Snapshot tests for decline reason outputs.

Deliverables:
- Policy tests
- Decision trace examples
```

## Prompt 8: BNPL Product Profile Hardening

```text
Task:
Implement and harden BNPL profile with short-horizon risk controls.

Requirements:
- Validate merchant-category and concurrent-plan constraints.
- Ensure fraud routing behavior is explicit and testable.

Implementation details:
- Add rule-level test fixtures for BNPL-specific checks.
- Keep reason-code outputs aligned with decline causes.

Testing:
- Tests for high-fraud, high-dti, and concurrent-plan scenarios.
- Regression tests for non-BNPL profiles.

Deliverables:
- BNPL policy tests
- Rule coverage summary
```

## Prompt 9: SMB Secured Loan Profile Hardening

```text
Task:
Implement and harden SMB Secured Loan profile using business cash-flow and collateral controls.

Requirements:
- Add secured-SMB underwriting fields and policy checks.
- Validate DSCR and collateral protection gates with deterministic outcomes.
- Maintain compatibility with existing product evaluator patterns.

Implementation details:
- Add required-field validation for:
	annual_revenue, years_in_business, debt_service_coverage_ratio,
	collateral_type, collateral_value, collateral_ltv.
- Add secured-loan rules for collateral adequacy and LTV bounds.
- Add seasonal revenue sensitivity tests and collateral stress cases.

Testing:
- Product tests for low-DSCR, insufficient collateral, and high-LTV scenarios.
- Regression tests across Personal Loan and BNPL profiles.

Deliverables:
- SMB secured profile logic and tests
- Product-level secured lending risk summary
```

## Prompt 10: Cross-Product Simulation Harness (Primary Products)

```text
Task:
Build a cross-product simulation harness for BNPL, Personal Loan, and SMB Secured policy evaluation.

Requirements:
- Run all primary product policies on shared fixture sets.
- Report approval/review/decline distributions and expected-loss proxies.

Implementation details:
- Add script under scripts/ or tests/helpers to run scenario batches.
- Persist summary artifacts for review.

Testing:
- Deterministic output tests for fixed input fixtures.

Deliverables:
- Simulation harness
- Baseline output report for primary products
```

## Prompt 11: Explainability and Reason-Code Regression Suite (Primary Products)

```text
Task:
Create a regression suite that validates reason-code and explanation consistency for BNPL, Personal Loan, and SMB Secured.

Requirements:
- Every major decline route has predictable reason outputs.
- Product-specific rules map to expected explanation fields.

Implementation details:
- Add snapshot tests for explanation payloads.
- Add mapping tests for reason-code completeness.

Testing:
- Cross-product explanation regression tests for primary products.

Deliverables:
- Explanation test suite
- Snapshot update policy note
```

## Prompt 12: Release Gates and Canary Automation (Primary Launch)

```text
Task:
Add release-gate checks and canary automation for primary product rollout safety.

Requirements:
- Gate merges on policy regression, parity checks, and API health thresholds.
- Define canary rollback triggers and validation steps.

Implementation details:
- Add CI checks for key suites.
- Add deployment checklist and rollback command references.

Testing:
- Validate gates fail on simulated regressions.

Deliverables:
- CI/release gate config
- Rollout and rollback runbook
```

## Prompt 13: End-to-End Production Readiness Suite (Primary Launch)

```text
Task:
Build full end-to-end tests from enrichment to final decision for BNPL, Personal Loan, and SMB Secured.

Requirements:
- Validate deterministic outputs on fixed fixtures.
- Cover success, degraded provider, and invalid-input paths.

Implementation details:
- Add product fixture packs and test orchestration.
- Ensure tests run in CI with clear failure diagnostics.

Testing:
- Full E2E tests for primary products.

Deliverables:
- E2E suite
- Final readiness summary
```

## Prompt 14: Credit Builder / Secured Card Profile (Secondary)

```text
Task:
Add Credit Builder / Secured Card profile optimized for thin-file applicants.

Requirements:
- Conservative limits and stricter guardrails by default.
- Explicit routing for missing bureau signals.

Implementation details:
- Add profile configuration and rule checks.
- Reuse canonical thin-file features; no duplicate logic.

Testing:
- Tests for no-credit-score applicants.
- Tests for limit assignment and manual-review routing.

Deliverables:
- New profile config
- Profile test suite
```

## Prompt 15: Overdraft / Cash Advance Profile (Secondary)

```text
Task:
Add Overdraft/Cash Advance policy profile using paycheck cadence and balance stress signals.

Requirements:
- Guard against repeat negative-balance behavior.
- Add conservative repayment-capacity gates.

Implementation details:
- Add rule checks for overdraft frequency and net-inflow adequacy.
- Add clear decline flags for affordability risk.

Testing:
- Tests for frequent NSF-like behavior.
- Tests for stable payroll vs volatile inflow cohorts.

Deliverables:
- New profile implementation
- Affordability-focused tests
```

---

## Dedicated Guard-Rail Prompt Pack (Run at Milestones)

## Guard-Rail Prompt A: Schema and Compatibility Audit

```text
Audit all recent changes for schema compatibility.
Check request/response contracts, feature payloads, and policy input models.
List any breaking changes and provide exact migration actions.
Fail the audit if undocumented contract changes are found.
```

## Guard-Rail Prompt B: Feature-Policy Consistency Audit

```text
Audit whether engineered features used by policy decisions are consistent across API and agent paths.
Identify any mismatch in field names, null handling, scaling, clipping, or defaults.
Provide a patch plan and tests for each mismatch.
```

## Guard-Rail Prompt C: Compliance and Explainability Audit

```text
Audit decline reason and explainability outputs for all product profiles.
Ensure every major decline route has explicit reason codes and human-readable explanation text.
Flag missing, ambiguous, or duplicate reason mappings.
```

## Guard-Rail Prompt D: Operational Safety Audit

```text
Audit logging, error handling, retry behavior, timeout handling, and fallback paths.
Verify no silent failures in provider integrations.
Confirm canary rollback triggers are explicit and tested.
```

## Guard-Rail Prompt E: Test Adequacy Audit

```text
Audit test coverage for new logic.
For each changed file, list behavior covered and behavior not covered.
Add missing high-risk tests, especially threshold boundaries and malformed input handling.
```

---

## Suggested Run Order

1. Prompt 1 + Guard-Rail A
2. Prompt 2 + Guard-Rail D
3. Prompt 3 + Guard-Rail A
4. Prompt 4 + Prompt 5 + Guard-Rail B
5. Prompt 6 + Guard-Rail E
6. Prompt 7 + Guard-Rail C and E
7. Prompt 8 + Guard-Rail C and E
8. Prompt 9 + Guard-Rail C and E
9. Prompt 10 + Guard-Rail B
10. Prompt 11 + Guard-Rail C
11. Prompt 12 + Guard-Rail D
12. Prompt 13 + Full A/B/C/D/E audits for primary launch
13. Prompt 14 + Guard-Rail C and E
14. Prompt 15 + Guard-Rail C and E

This sequence prioritizes primary-product launch value while keeping integration and compliance risk low.
