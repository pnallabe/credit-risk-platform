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
15. Prompt 16 + Guard-Rail D (Helix Decisions rebrand)
16. Prompt 17 + Guard-Rail D and F (Tenant portal login wiring)
17. Prompt 18 + Guard-Rail D and F (Tenant signup contact flow)

This sequence prioritizes primary-product launch value while keeping integration and compliance risk low.

---

## Helix Decisions — Tenant Portal & Rebrand Prompts

These prompts wire the Helix Decisions marketing frontend (previously AgentHiveHQ)
to the credit-risk-platform multitenant backend and rebrand all user-facing surfaces.

---

## Prompt 16: Rebrand AgentHiveHQ to Helix Decisions

```text
Task:
Rebrand all user-facing surfaces in the AgentHiveHQ Next.js frontend from
"AgentHiveHQ" to "Helix Decisions".

Context:
- The marketing site and tenant portal frontend live in AgentHiveHQ/AgentHiveHQ/src/.
- "Helix Decisions" is the new product brand name for the credit-risk platform frontend.
- The hexagonal logomark SVG should be retained; only the wordmark text changes.

Requirements:
- Replace every occurrence of "AgentHiveHQ" (and casing variants: agentHiveHQ,
  agent-hive, agenthivehq) with "Helix Decisions" / "helix-decisions" /
  "helixdecisions" as context demands.
- Update the Logo component (src/components/shared/Logo.tsx): change the wordmark
  span text from "AgentHive" to "Helix Decisions".
- Update footer copyright (src/components/layout/footer.tsx) to
  "Helix Decisions, Inc."
- Update meta title and metadataBase URL in src/app/layout.tsx to reflect the new
  brand domain (helixdecisions.ai).
- Update terms-of-service and privacy-policy pages to reference
  "Helix Decisions, Inc." and contact email hello@helixdecisions.ai.
- Update about-section.tsx company description to:
  "Helix Decisions is a frontier AI company building compliant, explainable credit
  intelligence for modern lenders."
- Update pricing-section.tsx and contact-section.tsx Calendly/demo booking URLs
  to the new brand domain; if not yet configured, insert a TODO comment:
  // TODO: replace with helixdecisions.ai Calendly link
- Do NOT change internal code identifiers, env var names, or API routes — only
  user-visible text and brand strings.

Testing:
- Lint pass: npm run lint (zero new errors).
- Search repo for remaining "AgentHive" occurrences and document any intentional
  exceptions in a code comment.
- Visual smoke test: confirm Logo renders "Helix Decisions" wordmark.

Deliverables:
- List of all files changed
- Before/after wordmark diff
- Remaining intentional brand exceptions documented inline
```

---

## Prompt 17: Tenant Portal Login — Connect Frontend to CRP Auth

```text
Task:
Connect the Helix Decisions login page (src/app/login/page.tsx) to the
credit-risk-platform multitenant authentication flow so tenants log in with
their tenant-specific credentials and are routed to their scoped dashboard.

Context:
- credit-risk-platform exposes a REST API (decision-api) with tenant-scoped JWT
  auth. Each tenant has a unique slug (e.g., "acme-lending").
- src/lib/crp-routing.ts already contains redirectUserToCrp() and
  sanitizeNextPath() helpers.
- Firebase Auth is used for identity; the CRP backend validates Firebase ID tokens
  and maps them to tenant memberships via GET /api/v1/tenants/me.
- Post-login, the user must be routed to
  {NEXT_PUBLIC_CRP_BASE_URL}/t/{tenantSlug}/dashboard.

Requirements:
- After a successful Firebase sign-in (email/password or Google) in login/page.tsx,
  call redirectUserToCrp(user, nextPath) as currently wired.
- In crp-routing.ts, ensure redirectUserToCrp fetches GET /api/v1/tenants/me from
  NEXT_PUBLIC_API_URL with the Firebase ID token in the Authorization: Bearer header.
- If the API returns a non-empty tenant membership list, extract the first tenant
  where status === "active" (fall back to the first entry if no active flag) and
  redirect to {NEXT_PUBLIC_CRP_BASE_URL}/t/{tenantSlug}/dashboard.
- If the API returns an empty membership list or a 401/403, show an inline error:
  "Your account is not linked to any tenant. Contact support@helixdecisions.ai."
- If NEXT_PUBLIC_CRP_BASE_URL is not set, fall back to http://localhost:3005.
- Preserve the sanitizeNextPath guard to block open-redirect on the ?next= param.
- Add structured console.error logs for failures: { userId, endpoint, statusCode }.

Backend sub-task (credit-risk-platform — decision-api):
- Confirm GET /api/v1/tenants/me exists and returns
  [{ tenantSlug, status, role }] for the authenticated Firebase UID.
- If the endpoint does not exist, create it. Validate the Firebase ID token via
  the Firebase Admin SDK and look up the tenant_members table by firebase_uid.
- Return 200 with an empty array (not 404) when no memberships are found.

Testing:
- Unit test: redirectUserToCrp with mock returning one active tenant → correct
  redirect URL.
- Unit test: redirectUserToCrp with empty membership list → returns false.
- Unit test: sanitizeNextPath open-redirect attack vectors remain blocked.
- Integration test: log in with a seeded test-tenant user → assert redirect lands
  on /t/test-tenant/dashboard.

Deliverables:
- Files changed (crp-routing.ts, login/page.tsx if touched, backend endpoint)
- Tests added/updated
- Risk notes: open-redirect mitigation, ID token exposure surface, cross-tenant
  isolation check
```

---

## Prompt 18: Tenant Signup — Contact & Interest Form (No Self-Serve)

```text
Task:
Replace the self-serve Firebase account-creation flow in src/app/signup/page.tsx
with a tenant interest / contact form that queues prospects for manual onboarding.
Do NOT create Firebase accounts automatically on form submission.

Context:
- credit-risk-platform is a regulated, multitenant B2B SaaS. New tenants are
  onboarded manually after a qualification review.
- The current signup page calls createUserWithEmailAndPassword immediately, which
  bypasses the tenant provisioning workflow.

Requirements — Frontend (src/app/signup/page.tsx):
- Remove createUserWithEmailAndPassword and all Google OAuth sign-up calls.
- Replace the form with a Tenant Interest Form with these fields:
    • Full name (required)
    • Work email (required, validated)
    • Company name (required)
    • Job title (optional)
    • Use case (required, textarea ≤ 500 chars) — label:
      "Describe your lending product and how you plan to use Helix Decisions."
    • Monthly application volume (optional, select:
      <500 / 500–5 k / 5 k–50 k / 50 k+)
    • How did you hear about us? (optional, free text)
- On submit, POST the form data to POST /api/v1/tenant-inquiries on
  NEXT_PUBLIC_API_URL. If the request fails or the env var is absent, fall back
  to opening a pre-filled mailto:hello@helixdecisions.ai link with subject
  "Helix Decisions — Tenant Inquiry" and body containing the form values.
- On successful submission, replace the form with a confirmation state (no page
  redirect):
    Headline: "Thanks — we'll be in touch."
    Body: "Our team reviews every request and typically responds within
           1 business day. In the meantime, you can book a demo below."
    CTA button: "Book a Demo" → Calendly demo URL.
- Add a note below the form:
  "We do not offer self-serve signup. All tenants are onboarded by our team to
   ensure compliance and a smooth integration."
- Brand panel left copy: "Join lending teams making smarter, fairer credit
  decisions with Helix Decisions."
- Keep the "Already have an account? Sign in" link pointing to /login.

Requirements — Backend (credit-risk-platform — new endpoint):
- Add POST /api/v1/tenant-inquiries to ingestion-api (or a dedicated leads module).
- Request schema (validated, all strings, trimmed):
    { name, email, company, title?, useCase, volume?, referral? }
- Persist to a new tenant_inquiries table (Postgres). This table must NOT have a
  FK to the tenants table — it is a pre-provisioning staging record only.
- Migration: add tenant_inquiries table with columns:
    id (uuid PK), name, email, company, title, use_case, volume, referral,
    created_at, ip_hash (sha256 of remote IP for rate-limit tracking).
- On insert, fire an async notification: send email to INQUIRY_NOTIFY_EMAIL and/or
  POST to INQUIRY_NOTIFY_SLACK_WEBHOOK (both optional env vars; skip if unset).
- Rate-limit: reject with 429 if the same IP (hashed) submits more than 3 times
  within a 1-hour rolling window.
- Return 201 { id, message: "Inquiry received." } on success.
- Return 422 { errors: { field: message } } on validation failure.
- Do NOT expose raw IP addresses in logs or responses — store only sha256 hash.

Testing:
- Frontend unit: required-field validation (name, email, company, useCase).
- Frontend unit: email format validation.
- Frontend unit: textarea enforces 500-char max.
- Frontend unit: successful POST → confirmation state renders, form hidden.
- Frontend unit: POST failure (network error) → mailto fallback link shown.
- Backend unit: POST /api/v1/tenant-inquiries happy path → 201, row inserted.
- Backend unit: same IP submits 4th request in 1 hour → 429.
- Backend unit: missing required field → 422 with field-level error map.
- Backend unit: notification fires when INQUIRY_NOTIFY_EMAIL is set.

Deliverables:
- Files changed (signup/page.tsx, new backend endpoint, Alembic migration)
- Tests added/updated
- Risk notes: PII storage (email in DB), rate-limit bypass via proxy headers,
  no Firebase account created on submission confirmed

```

---

## Guard-Rail Prompt F: Tenant Isolation & Portal Security Audit

```text
Before shipping any tenant portal changes (Prompts 17–18), run this audit:

1. Confirm every API endpoint in decision-api and ingestion-api that returns or
   writes data validates the tenant_id claim from the JWT against the resource
   being accessed. Cross-tenant data access must be impossible.
2. Confirm the frontend never constructs a tenant slug from raw user-supplied URL
   params without passing through canonicalizeTenantSlug().
3. Confirm the ?next= redirect param is validated by sanitizeNextPath() before
   every window.location or router.push call in the login flow.
4. Confirm the tenant_inquiries table has no FK to the tenants table and that
   submitting an inquiry grants zero system access until manual provisioning.
5. Confirm no Firebase UID is trusted server-side without a corresponding
   backend membership check against tenant_members.
6. Confirm no raw IP addresses are stored or logged — only hashed values.

Fail the audit and block the PR if any condition above is violated. Provide exact
file and line references for each finding and a suggested remediation.
```
