# SR 11-7 Gap Scanner — GitHub Project Build Prompt

> **Date:** April 16, 2026
> **Purpose:** Agent-ready coding prompt to scaffold and deploy the SR 11-7 Gap Scanner as a standalone public-facing GitHub repository, reusing `credit-risk-platform` compliance logic.
> **GTM Reference:** ILOL 90-Day GTM Traction Playbook — Leverage Move #1

---

## Mission

Build and deploy a public-facing web application called the **SR 11-7 Gap Scanner** as a standalone GitHub repository. The app is the primary lead-generation asset described in the ILOL 90-Day GTM Traction Playbook. It must be live, deployable, and production-ready in a single implementation pass.

---

## Context: What This Product Does

The SR 11-7 Gap Scanner is a free, ungated 5-minute self-assessment tool for Model Risk Managers at mid-market lenders ($100M–$10B AUM). A user answers questions across 12 SR 11-7 control domains, receives a scored gap heatmap PDF report, and is gated only at the point of receiving the personalized remediation guidance — requiring a 20-minute discovery call booking.

The backend reuses production-grade logic from the existing `credit-risk-platform` monorepo. The frontend is a modern public-facing web app with zero auth friction for the self-assessment.

---

## Repository to Create

**Name:** `sr117-gap-scanner`
**Visibility:** Public
**Structure:**

```
sr117-gap-scanner/
├── README.md
├── .github/
│   └── workflows/
│       ├── ci.yml           # lint + test on PR
│       └── deploy.yml       # auto-deploy on push to main
├── frontend/                # Next.js 14 App Router (TypeScript)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                  # Landing page with CTA
│   │   ├── scanner/
│   │   │   ├── page.tsx              # Multi-step assessment form
│   │   │   └── results/
│   │   │       └── page.tsx          # Results + heatmap + CTA
│   │   └── api/
│   │       └── submit/route.ts       # Calls backend API
│   ├── components/
│   │   ├── AssessmentForm.tsx        # Step-by-step form wizard
│   │   ├── DomainCard.tsx            # Individual domain question card
│   │   ├── GapHeatmap.tsx            # Visual heatmap (recharts)
│   │   ├── ScoreGauge.tsx            # Overall score gauge
│   │   └── CTABookCall.tsx           # Calendly embed CTA
│   ├── lib/
│   │   ├── domains.ts                # 12 SR 11-7 domain definitions + questions
│   │   └── scoring.ts                # Client-side pre-scoring logic
│   └── public/
│       └── og-image.png
├── backend/                 # FastAPI (Python 3.11)
│   ├── main.py
│   ├── requirements.txt
│   ├── routers/
│   │   ├── assessment.py    # POST /assess — receives answers, returns score + heatmap data
│   │   └── report.py        # POST /report — generates PDF, stores lead, sends email
│   ├── services/
│   │   ├── scorer.py        # Domain scoring engine (wraps credit-risk-platform compliance logic)
│   │   ├── pdf_generator.py # PDF report generator with heatmap (ReportLab or WeasyPrint)
│   │   ├── lead_store.py    # Stores lead email + scores to Supabase or GCP Firestore
│   │   └── email_sender.py  # Sends scored PDF via SendGrid or Resend
│   └── tests/
│       ├── test_scorer.py
│       └── test_report.py
├── docker-compose.yml       # Local dev: frontend + backend
├── Dockerfile.frontend
├── Dockerfile.backend
└── deploy/
    ├── cloudbuild.yaml      # GCP Cloud Build pipeline
    ├── cloudrun-backend.yaml
    └── vercel.json          # Frontend deploy to Vercel
```

---

## The 12 SR 11-7 Control Domains

Each domain maps to 3–4 assessment questions scored 0–3 (0 = no control, 3 = fully implemented and documented). Implement all 12:

| # | Domain | Key SR 11-7 Section |
|---|---|---|
| 1 | Model Inventory & Classification | §4.1 |
| 2 | Model Development Documentation | §4.2 |
| 3 | Model Validation Independence | §4.3 |
| 4 | Conceptual Soundness Review | §4.3.1 |
| 5 | Ongoing Monitoring & Performance Tracking | §4.4 |
| 6 | Model Change Management | §4.4.1 |
| 7 | Outcomes Analysis & Back-testing | §4.4.2 |
| 8 | Model Use Policy & Governance | §5.1 |
| 9 | Third-Party / Vendor Model Oversight | §5.2 |
| 10 | Data Quality & Data Governance | §5.3 |
| 11 | Fair Lending / Disparate Impact Controls | §5.4 |
| 12 | Board & Senior Management Oversight | §6.0 |

For each domain, define:
- **3 assessment questions** (yes/partial/no → maps to 3/1.5/0)
- **Domain weight** (domains 3, 5, 11 are weighted 1.3x — examiners cite these most frequently in 2025–2026 enforcement actions)
- **Red flag threshold** (domain score < 40% = RED, 40–69% = AMBER, ≥70% = GREEN)
- **Remediation blurb** (2–3 sentences explaining the gap risk and what ILOL provides — used in the gated PDF report)

---

## Scoring Logic (`backend/services/scorer.py`)

Reuse and adapt logic from `credit-risk-platform/compliance/health_score.py` and `compliance/engine.py`.

```python
class SR117Score:
    institution_name: str
    email: str
    asset_size_bucket: str  # "<$500M" | "$500M–$2B" | "$2B–$10B"
    domain_scores: dict[str, DomainScore]  # keyed by domain slug
    overall_score: float           # 0–100, weighted
    overall_band: Literal["RED", "AMBER", "GREEN"]
    top_3_gaps: list[str]          # domain slugs with lowest scores
    exam_readiness_statement: str  # 1-sentence narrative
    generated_at: datetime
```

The overall score formula:

```
weighted_sum = Σ (domain_raw_score × domain_weight)
max_weighted = Σ (3.0 × domain_weight)
overall_score = (weighted_sum / max_weighted) × 100
```

Band thresholds: RED < 50, AMBER 50–74, GREEN ≥ 75.

---

## PDF Report (`backend/services/pdf_generator.py`)

Reuse patterns from `credit-risk-platform/compliance/exam_packet_pdf.py` and `adverse_action_pdf.py`.

The PDF must contain:
1. **Cover page** — institution name, date, overall score band (RED/AMBER/GREEN with color block), ILOL logo
2. **Executive Summary** — 3-sentence assessment, exam readiness statement, top 3 gaps
3. **Domain Heatmap** — 12-row table with RAG status, domain name, score %, key finding
4. **Domain Detail Pages (for RED domains only)** — question-level breakdown + gap narrative + remediation preview (with "Full remediation guidance available in your 20-min diagnostic call" CTA)
5. **Regulatory Context Page** — 3 enforcement action citations from 2025 FDIC/OCC public database relevant to the institution's gaps
6. **Call to Action Page** — Calendly booking link QR code + URL, ILOL contact info

**Ungated:** The PDF is emailed automatically after form submission. No human gate on the raw scored report.
**Gated:** The "Full Remediation Roadmap" (domain-specific fix guidance) is only shared on the 20-minute call.

---

## Frontend Assessment Form (`frontend/components/AssessmentForm.tsx`)

- **Step 0:** Institution name, email, asset size bucket (3 options), primary role (CRO / MRM / CCO / Other) — this is the lead capture step, required before scoring begins
- **Steps 1–12:** One domain per step. Show domain name, regulatory context sentence, 3 questions per domain. Use radio buttons: "Yes — fully implemented", "Partially — in progress or undocumented", "No — not in place"
- **Progress bar** showing step completion
- **Step 13:** Results page — show GapHeatmap component + ScoreGauge + top 3 gaps + PDF-sending confirmation message + Calendly CTA

The form must be:
- Mobile-responsive (Tailwind CSS)
- Stateful with React `useReducer` — answers persist across steps
- Submittable via server action to `/api/submit` which calls the FastAPI backend

---

## Visual Components

### `GapHeatmap.tsx`
12-row heatmap table. Each row: domain name | score % | RAG badge (colored pill). Sort by score ascending (worst gaps first). Use Tailwind for colors: `bg-red-100 text-red-800`, `bg-amber-100 text-amber-800`, `bg-green-100 text-green-800`.

### `ScoreGauge.tsx`
Semicircular gauge using Recharts `RadialBarChart`. Display overall score (0–100) with band label. Color: red < 50, amber 50–74, green ≥ 75.

### `CTABookCall.tsx`
Embed a Calendly inline widget (`https://calendly.com/YOUR_LINK/sr-117-diagnostic`). Show only after results are displayed. Include copy: *"Your gap score is in the [BAND] range. Get your personalized remediation roadmap in a free 20-minute diagnostic call."*

---

## Lead Capture & Email Flow

1. User submits form (Step 0 captures email)
2. Backend scores the assessment → `SR117Score` object
3. Backend generates PDF → stores in GCP Cloud Storage bucket `sr117-reports/{uuid}.pdf`
4. Backend stores lead: `{email, institution, asset_size, overall_score, band, domain_scores_json, submitted_at}` → Supabase table `gap_scanner_leads` (or Firestore collection `leads`)
5. Backend sends email via Resend (or SendGrid): subject `"Your SR 11-7 Gap Report — [Institution Name]"`, body = 3-sentence summary + PDF attachment + Calendly link
6. Frontend redirects to `/scanner/results?score=XX&band=AMBER` with heatmap data in query params or sessionStorage

---

## Integration Points with `credit-risk-platform`

The scanner is a **standalone repo** but imports select modules from the monorepo as an installable local package or via a published PyPI package `ilol-compliance-core`. For the MVP, use direct path imports via a `requirements.txt` git+https reference or copy the following modules into `backend/lib/`:

| Module | Purpose |
|---|---|
| `compliance/health_score.py` | Domain health scoring logic |
| `compliance/exam_packet_builder.py` | Exam packet structure and SR 11-7 requirement mapping |
| `compliance/regulatory_horizon.py` | Regulatory citation lookups |
| `monitoring/fair_lending.py` | Domain 11 (fair lending) question context and scoring hints |
| `monitoring/drift_monitor.py` | Domain 5 (ongoing monitoring) scoring context |

Do not import database models, tenant auth, or any multi-tenant infra from the monorepo. The scanner is stateless except for lead storage.

---

## Deployment Architecture

### Frontend → Vercel
- Deploy `frontend/` to Vercel
- Environment variable: `NEXT_PUBLIC_BACKEND_URL=https://sr117-scanner-api-HASH-uc.a.run.app`
- Custom domain: `scanner.ilol.ai` (or equivalent)
- `vercel.json` already in `deploy/` directory

### Backend → GCP Cloud Run
- Deploy `backend/` as a containerized FastAPI service to Cloud Run (us-central1)
- Min instances: 1 (cold start avoidance for public tool)
- Max instances: 10
- CPU: 1, Memory: 512Mi
- Cloud Build trigger: push to `main` → build → deploy
- Cloud Storage bucket for PDF storage (create in deploy script)
- Service account with Storage Object Creator + Firestore User roles

### CI/CD (`.github/workflows/`)
- **`ci.yml`:** On PR — `ruff` lint + `pytest` (backend), `tsc --noEmit` + `eslint` (frontend)
- **`deploy.yml`:** On push to `main` — trigger Cloud Build for backend + `vercel --prod` for frontend

---

## Environment Variables

```env
# Backend
RESEND_API_KEY=
GCP_PROJECT_ID=
GCP_BUCKET_NAME=sr117-reports
SUPABASE_URL=           # or FIRESTORE_PROJECT_ID
SUPABASE_KEY=
CALENDLY_LINK=https://calendly.com/YOUR_LINK/sr-117-diagnostic

# Frontend
NEXT_PUBLIC_BACKEND_URL=
NEXT_PUBLIC_CALENDLY_LINK=
```

---

## Quality & Performance Requirements

- Lighthouse score ≥ 90 (performance, accessibility, SEO) — this is a public marketing asset
- Form submission → scored results rendered: < 3 seconds
- PDF generation + email delivery: < 30 seconds (async, non-blocking on frontend)
- All 12 domains fully scored and rendered — no stub domains
- PDF must be a real, styled document — not a text dump
- Mobile-first responsive design

---

## Out of Scope for MVP

- User accounts / authentication
- Saved assessments / history
- Payment or subscription
- Admin dashboard (use Supabase Studio or Firestore console for lead review)
- Multi-tenant features from the credit-risk-platform monorepo

---

## Definition of Done

1. `git clone` → `docker-compose up` → app runs locally at `localhost:3000`
2. Complete a full 12-domain assessment → receive scored PDF via email
3. Frontend deployed to Vercel, backend deployed to Cloud Run — both live and accessible
4. GitHub Actions CI passes on a test PR
5. `README.md` includes: product description, local setup instructions, deployment instructions, environment variable table, and a link to the live URL
