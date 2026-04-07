# Customer Integration Guide
## Credit Risk Platform — Decision API

> Version: 1.0 | Date: 2026-04-07 | Status: DRAFT
> Audience: Engineering teams at fintech lenders and banks integrating the Decision API into a Loan Origination System (LOS)
> Cross-references: `docs/TECHNICAL_ARCHITECTURE.md`, `docs/manuals/COMPLIANCE_AND_MODEL_RISK_MANUAL.md`

---

## 1. Integration Overview

### Architecture Context

The Credit Risk Platform's **Decision API** is a stateless REST microservice deployed on Google Cloud Run. It sits between your Loan Origination System and your credit decision workflow:

```
LOS / Origination System
        │
        │  POST /v1/decisions/single
        │  (application data + JWT)
        ▼
┌─────────────────────────────────┐
│   Credit Risk Platform          │
│   Decision API (Cloud Run)      │
│   ─────────────────────────     │
│   Feature Computation           │
│   PD + Fraud Scoring            │
│   Credit Policy Evaluation      │
│   SHAP Reason Codes             │
│   Audit Logging                 │
└─────────────────────────────────┘
        │
        │  Decision response
        │  (APPROVE / DECLINE / REFER + reason codes)
        ▼
LOS renders decision to applicant
(and generates Reg B adverse action notice if DECLINE)
```

### Authentication

**JWT Bearer Tokens** are required on all API calls (except `/health`).

```http
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

JWT payload must include:
- `tenant_id` (required): your unique tenant identifier assigned during onboarding
- `environment` (optional): `dev`, `staging`, or `prod`
- `exp`: standard expiry claim

**Token acquisition**: your Customer Success Manager will provide:
- A `client_id` and `client_secret` for your token endpoint
- Token endpoint URL: `https://auth.creditriskplatform.io/oauth2/token`
- Token TTL: 1 hour; refresh before expiry

```bash
# Obtain a token
curl -X POST https://auth.creditriskplatform.io/oauth2/token \
  -d "grant_type=client_credentials" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET"

# Response
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

> **Security requirement**: `tenant_id` is extracted from the JWT claim by the platform — do not send it in the request body. Mismatched or absent `tenant_id` claims will return HTTP 401.

### Rate Limits and Idempotency

| Plan Tier | Requests / Minute | Max Batch Size | Idempotency-Key support |
|---|---|---|---|
| Starter | 60 req/min | 100 records/batch | Required |
| Growth | 300 req/min | 500 records/batch | Required |
| Enterprise | 1,000 req/min | 2,000 records/batch | Required |

**Idempotency-Key header** (required for all decision requests):
- Set `Idempotency-Key: <your-unique-key>` on every request (UUID v4 recommended)
- If the platform receives a duplicate key within 24 hours, it returns the cached response without re-processing
- Prevents double audit writes in case of network retries

```http
POST /v1/decisions/single HTTP/1.1
Authorization: Bearer <token>
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json
```

---

## 2. API Reference

### POST `/v1/decisions/single`

Submit a single loan application for real-time underwriting.

**Request Schema:**

| Field | Type | Required | Description | Validation |
|---|---|---|---|---|
| `application_id` | string | ✅ | Your system's unique application identifier | Max 100 chars |
| `annual_income` | float | ✅ | Applicant gross annual income (USD) | > 0 |
| `loan_amount` | float | ✅ | Requested loan amount (USD) | > 0 |
| `credit_score` | integer | ✅ | Traditional bureau credit score | 300–850 |
| `employment_status` | string | ✅ | `employed`, `self_employed`, `unemployed`, `retired` | Enum |
| `existing_debt` | float | ✅ | Total outstanding debt balance (USD) | ≥ 0 |
| `loan_purpose` | string | ✅ | `home_improvement`, `debt_consolidation`, `personal`, `auto`, `business` | Enum |
| `dti` | float | ✅ | Debt-to-income ratio (0–1) | 0–1 |
| `months_employed` | integer | ✅ | Months at current employer | ≥ 0 |
| `num_open_accounts` | integer | ✅ | Number of open credit accounts | ≥ 0 |
| `monthly_payment` | float | ❌ | Estimated required monthly payment | > 0 if provided |
| `num_derogatory_marks` | integer | ❌ | Number of derogatory marks on credit report | ≥ 0, default 0 |
| `num_collections` | integer | ❌ | Number of collection accounts | ≥ 0, default 0 |
| `credit_utilization` | float | ❌ | Revolving credit utilization ratio | 0–1 |
| `open_banking_data` | object | ❌ | Transaction enrichment payload (if Plaid/MX connected) | See enrichment schema |

**Response Schema (200 OK):**

```json
{
  "application_id": "APP-2026-001",
  "decision": "APPROVE",
  "risk_tier": "PRIME",
  "pd_score": 0.042,
  "fraud_score": 0.08,
  "reason_codes": [],
  "shap_explanation": {
    "annual_income": 0.31,
    "credit_score": 0.28,
    "dti": -0.06,
    "existing_debt": -0.03
  },
  "request_id": "req-550e8400-e29b-41d4-a716-446655440000",
  "model_version": "credit_risk_pd:3",
  "policy_version": "policy-2026-03-15-a1b2c3",
  "decision_timestamp": "2026-04-07T14:32:01.123Z"
}
```

> `reason_codes` is populated only for DECLINE and REFER outcomes.

**Error Codes:**

| HTTP Code | Meaning | Safe to Retry? | Backoff |
|---|---|---|---|
| 400 | Validation error — missing or invalid field | NO — fix payload | — |
| 401 | Invalid or expired JWT | NO — refresh token first | — |
| 403 | Tenant quota exceeded or permission denied | NO — contact support | — |
| 409 | Duplicate Idempotency-Key — returns cached response | N/A | — |
| 422 | Unprocessable entity — schema mismatch | NO — fix schema | — |
| 429 | Rate limit exceeded | YES | Exponential backoff, min 1s |
| 500 | Internal server error | YES (1×) | 5s then escalate |
| 503 | Service temporarily unavailable | YES | 10s exponential backoff |

---

### POST `/v1/decisions/batch`

Submit up to 2,000 (Enterprise tier) applications in one call.

**Request:**
```json
{
  "applications": [
    { application object 1 },
    { application object 2 },
    ...
  ]
}
```

**Response (200 OK):**
```json
{
  "batch_id": "batch-a1b2c3d4",
  "results": [
    { decision object 1 },
    { decision object 2 }
  ],
  "total": 250,
  "processing_time_ms": 1840
}
```

Individual error objects within `results` use the same error format as the single endpoint.

---

### GET `/v1/audit/{application_id}`

Retrieve the complete audit record for a previously processed application.

**Access control**: the JWT `tenant_id` claim is enforced — you can only retrieve audit records belonging to your own tenant.

**Response (200 OK):**
```json
{
  "application_id": "APP-2026-001",
  "tenant_id": "acme-bank",
  "decisions": [
    {
      "audit_id": "aud-550e8400...",
      "decision": "APPROVE",
      "pd_score": 0.042,
      "fraud_score": 0.08,
      "risk_tier": "PRIME",
      "reason_codes": [],
      "shap_explanation": { ... },
      "feature_snapshot": { ... },
      "model_version": "credit_risk_pd:3",
      "policy_version": "policy-2026-03-15-a1b2c3",
      "decision_timestamp": "2026-04-07T14:32:01.123Z",
      "override_flag": false
    }
  ]
}
```

---

### POST `/v1/ingestion/batch`

Upload raw application data files for batch processing.

**Request**: multipart/form-data with JSON payload and optional file attachments.

**Response (202 Accepted):**
```json
{
  "batch_id": "ing-batch-a1b2c3",
  "records_received": 5000,
  "status": "queued",
  "estimated_processing_minutes": 4
}
```

Processing completes asynchronously; poll `GET /v1/ingestion/{batch_id}/status` for completion.

---

## 3. Request / Response Examples

### Curl — Single Decision

```bash
curl -X POST https://api.creditriskplatform.io/v1/decisions/single \
  -H "Authorization: Bearer eyJ..." \
  -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \
  -H "Content-Type: application/json" \
  -d '{
    "application_id": "APP-2026-001",
    "annual_income": 85000,
    "loan_amount": 25000,
    "credit_score": 720,
    "employment_status": "employed",
    "existing_debt": 12000,
    "loan_purpose": "home_improvement",
    "dti": 0.28,
    "months_employed": 36,
    "num_open_accounts": 4
  }'
```

### Python SDK (using `httpx`)

```python
import httpx
import uuid

BASE_URL = "https://api.creditriskplatform.io"

def get_token(client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        "https://auth.creditriskplatform.io/oauth2/token",
        data={"grant_type": "client_credentials",
              "client_id": client_id,
              "client_secret": client_secret}
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def submit_decision(token: str, application: dict) -> dict:
    idempotency_key = str(uuid.uuid4())
    resp = httpx.post(
        f"{BASE_URL}/v1/decisions/single",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
            "Content-Type": "application/json"
        },
        json=application,
        timeout=10.0
    )
    resp.raise_for_status()
    return resp.json()

# Usage
token = get_token("your-client-id", "your-client-secret")
decision = submit_decision(token, {
    "application_id": "APP-2026-001",
    "annual_income": 85000,
    "loan_amount": 25000,
    "credit_score": 720,
    "employment_status": "employed",
    "existing_debt": 12000,
    "loan_purpose": "home_improvement",
    "dti": 0.28,
    "months_employed": 36,
    "num_open_accounts": 4
})
print(decision["decision"])  # → "APPROVE"
```

---

## 4. Field Mapping Guide

| Platform Field | Description | Accepted Values | Validation Rule | Common Mismatch |
|---|---|---|---|---|
| `application_id` | Unique application ID from your LOS | Any string | Max 100 chars, unique per tenant | LOS may call this `loan_application_id` or `app_ref` — map accordingly |
| `annual_income` | Gross annual income in USD | Float > 0 | Reject ≤ 0 | Some LOS use `monthly_income` — multiply × 12 before sending |
| `existing_debt` | Total outstanding debt balance | Float ≥ 0 | — | LOS may use `existing_debt_amount` — field name must be exactly `existing_debt` |
| `dti` | Debt-to-income ratio | 0.0 – 1.0 | Reject > 1 or < 0 | LOS sometimes provides as percentage (e.g., 28) — divide by 100 |
| `credit_score` | Bureau credit score | Integer 300–850 | Reject outside range | Some bureau APIs return 0 for thin files — handle separately; send `null` if unavailable |
| `employment_status` | Employment status code | `employed`, `self_employed`, `unemployed`, `retired` | Strict enum | Map your LOS codes: `FULL_TIME` → `employed`, `CONTRACT` → `self_employed` |
| `loan_purpose` | Loan use case | `home_improvement`, `debt_consolidation`, `personal`, `auto`, `business` | Strict enum | Map your LOS product codes to these values |
| `months_employed` | Tenure at current employer in months | Integer ≥ 0 | — | Some systems store as years — multiply × 12 |
| `num_open_accounts` | Open credit accounts count | Integer ≥ 0 | — | Ensure you are counting open accounts only, not total tradelines |

---

## 5. Decision Output Interpretation

### Decision Codes

| Code | Meaning | Recommended Downstream Action |
|---|---|---|
| `APPROVE` | Application meets all credit policy criteria | Proceed to loan offer generation; no adverse action notice required |
| `DECLINE` | Application does not meet credit policy criteria | Generate Reg B adverse action notice using platform-provided reason codes |
| `REFER` | Application falls in a review band or triggers manual review flag | Route to human credit analyst queue; do not generate automated adverse action notice until manual review completes |

### Reason Codes (DECLINE and REFER)

| Code | Description | Reg B Adverse Action Mapping |
|---|---|---|
| R01 | Debt-to-income ratio too high | "Amount of monthly obligations in relation to income" |
| R02 | Insufficient credit history | "Length of credit history" |
| R03 | Credit score below threshold | "Credit score" |
| R04 | High existing debt burden | "Amount owed on revolving accounts" |
| R05 | Derogatory history present | "Derogatory public record or collection filed" |
| R06 | Employment history insufficient | "Inadequate employment record" |
| R07 | Fraud indicator present | "Unable to verify application information" |
| R08 | Loan amount exceeds policy limit | "Amount requested exceeds guidelines" |
| R09 | Payment-to-income ratio exceeds limit | "Amount of monthly obligations in relation to income" |

> **Reg B requirement**: for all DECLINE decisions, you must generate an adverse action notice within 30 days of the application date using reason codes as the basis.

### Score Interpretation

| Score | Range | Meaning |
|---|---|---|
| `pd_score` | 0.00 – 1.00 | Estimated probability of default within 12 months. < 0.05 = Prime; 0.05–0.15 = Near-Prime; 0.15–0.30 = Sub-Prime; > 0.30 = Deep Sub-Prime |
| `fraud_score` | 0.00 – 1.00 | Fraud anomaly score from Isolation Forest. > 0.80 triggers review. |
| `risk_tier` | Enum | `PRIME`, `NEAR_PRIME`, `SUB_PRIME`, `DEEP_SUB_PRIME` — mapped from `pd_score` by platform policy |

---

## 6. Error Handling

### Pydantic Validation Error Format

```json
{
  "detail": [
    {
      "loc": ["body", "dti"],
      "msg": "ensure this value is less than or equal to 1",
      "type": "value_error.number.not_le",
      "ctx": {"limit_value": 1}
    }
  ]
}
```

### Retry Strategy

```python
import time
import httpx

def submit_with_retry(token: str, application: dict, max_retries: int = 3) -> dict:
    retryable_status_codes = {429, 500, 503}
    for attempt in range(max_retries):
        try:
            resp = httpx.post(...)
            if resp.status_code in retryable_status_codes:
                wait = 2 ** attempt  # exponential backoff: 1s, 2s, 4s
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                time.sleep(5)
    raise Exception("Max retries exceeded")
```

---

## 7. Sandbox Environment

**Sandbox Base URL**: `https://sandbox.creditriskplatform.io`

All sandbox calls are fully functional but write to isolated test databases. No real credit decisions are made.

### Pre-Loaded Test Tenant Credentials

| Tenant | client_id | client_secret | Provided by |
|---|---|---|---|
| `sandbox-test-tenant` | `test-client-abc` | Provided at onboarding | Customer Success Manager |

### Synthetic Test Payloads

**APPROVE outcome:**
```json
{
  "application_id": "SANDBOX-APPROVE-001",
  "annual_income": 110000, "loan_amount": 20000,
  "credit_score": 760, "employment_status": "employed",
  "existing_debt": 8000, "loan_purpose": "debt_consolidation",
  "dti": 0.22, "months_employed": 48, "num_open_accounts": 6
}
```

**DECLINE outcome:**
```json
{
  "application_id": "SANDBOX-DECLINE-001",
  "annual_income": 42000, "loan_amount": 35000,
  "credit_score": 580, "employment_status": "employed",
  "existing_debt": 28000, "loan_purpose": "personal",
  "dti": 0.62, "months_employed": 6, "num_open_accounts": 2,
  "num_derogatory_marks": 3
}
```

**REFER outcome (review band):**
```json
{
  "application_id": "SANDBOX-REFER-001",
  "annual_income": 68000, "loan_amount": 22000,
  "credit_score": 650, "employment_status": "self_employed",
  "existing_debt": 15000, "loan_purpose": "business",
  "dti": 0.41, "months_employed": 14, "num_open_accounts": 3
}
```

---

## 8. Production Checklist

Before going live with your integration, confirm the following:

- [ ] `tenant_id` is present in all JWT tokens — never sent in the request body
- [ ] `Idempotency-Key` header is set on every decision request (UUID v4 format)
- [ ] Token refresh logic is implemented (tokens expire after 1 hour)
- [ ] Field name mapping is validated against the platform schema (especially `existing_debt`, `dti` as ratio not percentage)
- [ ] `credit_score` null handling is implemented for thin-file applicants
- [ ] mTLS VPN tunnel configured for on-premises LOS deployments (discuss with CSM)
- [ ] Adverse action notice generation is implemented in your LOS using platform reason codes for all DECLINE outcomes
- [ ] Audit record retention SLA agreed — platform retains for minimum 7 years; confirm your downstream systems match
- [ ] Rate limit tier confirmed and retry-with-backoff logic tested
- [ ] Webhook endpoint configured for asynchronous batch completion notifications (if using batch ingestion)
- [ ] Integration test run against sandbox with all three synthetic payloads (APPROVE / DECLINE / REFER)
- [ ] Signed Data Processing Agreement (DPA) and BAA on file
