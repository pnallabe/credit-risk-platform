# DESIGN.md — Helix Decisions Design System

> Source of truth for all UI design decisions across `ui/applicant-portal` and `ui/analytics-dashboard`.
> Created by /plan-design-review on 2026-04-25. Branch: v1.5.0.

---

## Product Context

Two distinct surfaces with different trust contracts:

1. **Applicant Portal** (`ui/applicant-portal`) — Consumer-facing. People applying for loans. Every pixel either builds or erodes the trust needed for a conversion. Design posture: premium financial institution, not generic SaaS.

2. **Analytics Dashboard** (`ui/analytics-dashboard`) — Internal B2B tool for underwriters, risk analysts, compliance officers, data scientists, executives, and regulators. Design posture: calm, dense, utility-first — NOT a marketing site.

These two surfaces should feel related (same brand) but different in density and tone.

---

## Brand Colors

Define via CSS variables in `globals.css`. Never hardcode hex values in component files.

### Applicant Portal

```css
:root {
  /* Brand */
  --brand-navy:       #0f172a;  /* Primary heading color — deep, trustworthy */
  --brand-navy-mid:   #1e3a5f;  /* Secondary UI elements */
  --brand-gold:       #b87333;  /* Primary CTA — warm, distinguished */
  --brand-gold-light: #f5e6d0;  /* CTA hover state, soft backgrounds */
  --brand-green:      #16a34a;  /* Approval, success, positive signals */
  --brand-red:        #dc2626;  /* Rejection, errors, critical alerts */
  --brand-amber:      #d97706;  /* Manual review, pending, caution */

  /* Surfaces */
  --surface-white:    #ffffff;
  --surface-cream:    #fafaf8;  /* Slightly warm off-white — more trustworthy than pure white */
  --surface-light:    #f1f5f9;  /* Section backgrounds */

  /* Text */
  --text-primary:     #0f172a;  /* Navy — main headings */
  --text-secondary:   #374151;  /* Body text — not pure black, softer */
  --text-muted:       #6b7280;  /* Supporting text — verify ≥4.5:1 contrast on white */
  --text-disabled:    #9ca3af;

  /* Borders */
  --border-default:   #e5e7eb;
  --border-focus:     #1e3a5f;

  /* Primary action */
  --primary:          221.2 83.2% 53.3%;  /* Keep for shadcn compatibility */
}
```

### Analytics Dashboard

```css
:root {
  /* Same core brand, tuned for data-dense UI */
  --brand-navy:       #0f172a;
  --brand-blue:       #1d4ed8;  /* Active nav, primary actions */
  --brand-blue-light: #dbeafe;  /* Badge backgrounds, highlights */

  /* Status colors — ALWAYS paired with text labels, never color-only */
  --status-green:     #16a34a;  /* Stable, approved, passing */
  --status-amber:     #d97706;  /* Caution, manual review, warning */
  --status-red:       #dc2626;  /* Critical, rejected, failing */

  /* Surfaces */
  --sidebar-bg:       #ffffff;
  --page-bg:          #f8fafc;
  --card-bg:          #ffffff;
  --border-default:   #e2e8f0;
}
```

---

## Typography

### Applicant Portal

Two typefaces. Display for headings (trust signal), Inter for body (readability).

```css
/* In layout.tsx */
import { Instrument_Serif, Inter } from "next/font/google";

const instrumentSerif = Instrument_Serif({
  weight: ["400"],
  subsets: ["latin"],
  variable: "--font-display",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-body",
});
```

**Type scale:**

| Role          | Font             | Size  | Weight | Line-height | Use |
|---------------|------------------|-------|--------|-------------|-----|
| Display XL    | Instrument Serif | 56px  | 400    | 1.1         | Hero headline (desktop) |
| Display L     | Instrument Serif | 40px  | 400    | 1.15        | Hero headline (mobile) |
| Heading 2     | Instrument Serif | 32px  | 400    | 1.2         | Section headings |
| Heading 3     | Inter            | 20px  | 700    | 1.3         | Card headings, subsections |
| Body L        | Inter            | 18px  | 400    | 1.6         | Hero subheadline |
| Body          | Inter            | 16px  | 400    | 1.6         | Standard body text |
| Body S        | Inter            | 14px  | 400    | 1.5         | Form labels, captions |
| Label         | Inter            | 12px  | 600    | 1.4         | ALL-CAPS labels, badges |
| Legal         | Inter            | 11px  | 400    | 1.6         | Footer disclaimers — verify contrast |

### Analytics Dashboard

Single typeface (Inter). Density-tuned.

| Role      | Size  | Weight | Line-height | Use |
|-----------|-------|--------|-------------|-----|
| Page title| 20px  | 700    | 1.2         | Page `<h1>` |
| Section   | 14px  | 600    | 1.3         | Section headings |
| Body      | 14px  | 400    | 1.5         | Standard body |
| Caption   | 12px  | 400    | 1.4         | Table cells, secondary info |
| Mono      | 13px  | 400    | 1.4         | SQL, code, IDs |
| KPI value | 24px  | 900    | 1.0         | KPI Card metric numbers |

---

## Spacing Scale

Based on 4px base unit. Use Tailwind spacing utilities.

```
4px   = p-1   — tight internal padding
8px   = p-2   — compact elements
12px  = p-3   — default button padding (vertical)
16px  = p-4   — standard card padding (tight)
20px  = p-5   — KPI card padding (current DashboardShell usage ✓)
24px  = p-6   — standard page content padding
32px  = p-8   — section internal padding
48px  = p-12  — section vertical spacing
64px  = p-16  — hero section vertical padding
```

**Section spacing rhythm (applicant portal):**
- Between hero and first section: none (wave divider handles transition)
- Between content sections: `py-20` (80px)
- Max content width: `max-w-4xl` for text-heavy, `max-w-5xl` for grids

---

## Border Radius

One radius system. Do NOT mix rounded-sm, rounded-lg, rounded-2xl ad-hoc.

| Element                  | Radius          | Tailwind |
|--------------------------|-----------------|----------|
| Cards                    | 12px            | rounded-xl |
| Buttons                  | 8px             | rounded-lg |
| Form inputs              | 8px             | rounded-lg |
| Badges / pills           | 999px           | rounded-full |
| Modal / sheet            | 16px top only   | rounded-t-2xl |
| KPI cards (dashboard)    | 12px            | rounded-xl (✓ current) |
| Sidebar (dashboard)      | 8px nav items   | rounded-lg (✓ current) |

---

## Elevation (Shadow System)

Applicant portal uses subtle shadows for cards. Dashboard is flatter.

```css
/* Applicant portal */
--shadow-card:   0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
--shadow-raised: 0 4px 12px rgba(0,0,0,0.08), 0 2px 4px rgba(0,0,0,0.04);
--shadow-modal:  0 20px 40px rgba(0,0,0,0.15);

/* Analytics dashboard — near-flat */
--shadow-card:   0 1px 3px rgba(0,0,0,0.06);  /* minimal lift */
/* No shadow-raised — use border instead */
```

Rule: **never use shadow as decoration**. Shadow should imply elevation (modal above page, tooltip above content). A KPI card at page level gets minimal shadow. A dropdown gets `shadow-raised`.

---

## Icon System

**Analytics Dashboard:** Lucide React (`lucide-react` is already installed).

Icon assignments for navigation:

| Nav Item                  | Lucide Component     |
|---------------------------|----------------------|
| Review Queue              | `ClipboardList`      |
| History                   | `FolderOpen`         |
| Portfolio Health          | `BarChart3`          |
| Credit Risk               | `AlertTriangle`      |
| Model Performance         | `Target`             |
| Command Center            | `LayoutDashboard`    |
| Fair Lending              | `Scale`              |
| Adverse Actions           | `AlertCircle`        |
| Audit Explorer            | `Search`             |
| Model Governance          | `Building2`          |
| Model Drift               | `TrendingDown`       |
| Feature Analysis          | `Microscope`         |
| Experiments               | `FlaskConical`       |
| Data Quality              | `CheckSquare`        |
| Executive Overview        | `TrendingUp`         |
| AI Assistant              | `Bot`                |
| Regulator Overview        | `Shield`             |
| Audit Records             | `FileText`           |
| Exam Packets              | `Package`            |
| AB Testing                | `GitCompare`         |

**DO NOT use emoji as icons in production UI.** Emoji are not icon substitutes:
- Inconsistent size across OS/browser
- Cannot be styled with brand colors
- Screen readers announce them as text, not icons

**Applicant portal:** Uses inline SVG for the logo and simple UI icons. Prefer lucide-react if adding icons here.

---

## Component Vocabulary

### Shared across both apps

**StatusBadge** (`DashboardShell.tsx`)
- Always shows text label
- Must include a shape affordance alongside color (see Pass 6 TODO)
- Status → icon mapping: APPROVE/approved=✓, REJECT=✗, MANUAL_REVIEW=⏳, PASS=✓, FAIL=✗

**KpiCard** (`DashboardShell.tsx`)
- Value: 24px font-black
- Label: 12px uppercase tracking-wide gray-500
- Trend indicator: ↑ green / ↓ red with % and label text
- Icon: optional, 36px container, colored per category

**TrafficLight** (`DashboardShell.tsx`)
- Must show text alongside indicator: "Stable", "Caution", "Critical"
- Never emoji-only

### Applicant Portal specific

**HeroSection**
- Left-aligned layout (NOT centered)
- Instrument Serif for headline
- Headline max 2 lines on desktop, 3 on mobile
- Single primary CTA — gold background, navy text
- Optional secondary CTA — outline style
- No decorative gradients as primary hero treatment
- Trust signal (compliance badge / rating) placed near CTA

**FormStep**
- Progress indicator at top (current: STEPS array — good)
- Each field: visible label above input (never placeholder-only)
- Error state: red border + error message below input
- Required fields marked with * explained once at form top, not per-field

**TrustSignals** (new component needed)
- Replace the 3-column BenefitCard grid
- Inline row: 3-4 signals with icon + short text
- Example: "256-bit encryption · FCRA compliant · No hard credit pull · <2s decisions"
- No cards, no containers — just text with separators

**DecisionResult**
- Three branches: APPROVE / REJECT / MANUAL_REVIEW
- APPROVE: Green accent, specific rate + term, monthly payment calc, next step CTA
- REJECT: Navy background, human-toned headline, FCRA codes with plain-English translation, action guidance
- MANUAL_REVIEW: Amber accent, explicit timeline (1-2 business days), email + reference number, status check link

---

## Motion

**Applicant portal — 3 intentional motions:**
1. Hero entrance: headline fades in + slight upward translate (200ms, ease-out)
2. Form step transition: slide-left between steps (150ms, ease-in-out)
3. CTA hover: subtle -translate-y-0.5 (already implemented ✓)

No looping animations except the "● Decisions in under 2 seconds" pulse dot (already implemented ✓).

**Analytics dashboard — minimal motion:**
- Sidebar open/close: `transition-all duration-200` (already implemented ✓)
- Table row hover: `bg-gray-50` on hover only, no transition needed
- No entrance animations — density matters more than delight here

---

## Accessibility Requirements

1. **Contrast minimums:** 4.5:1 for body text (WCAG AA). 3:1 for large text (18px+ regular or 14px+ bold). Verify `--text-muted` (#6b7280) on white before shipping.
2. **Touch targets:** 44px minimum on all interactive elements on mobile.
3. **Focus visible:** `:focus-visible` outline on all interactive elements. Never `outline: none` without a replacement.
4. **Keyboard navigation:** Sidebar nav items must be keyboard-accessible. Form steps must be navigable by Tab.
5. **Screen reader:** All icon-only buttons need `aria-label`. Collapsed sidebar items need `aria-label` matching their nav label.
6. **Color-only:** Never use color as the sole differentiator. Always pair with text, shape, or icon.
7. **Form labels:** All form inputs must have a visible `<label>` that remains visible when the field has content. Never placeholder-as-label.

---

## "What Already Exists" Inventory

| Component / Pattern         | Location                                   | Status    |
|-----------------------------|--------------------------------------------|-----------|
| DashboardShell              | `ui/analytics-dashboard/components/`       | ✓ Keep, extend with Lucide + a11y |
| KpiCard                     | `ui/analytics-dashboard/components/`       | ✓ Keep    |
| StatusBadge                 | `ui/analytics-dashboard/components/`       | ⚠ Needs shape affordances |
| TrafficLight                | `ui/analytics-dashboard/components/`       | ⚠ Needs text labels |
| CSS variable tokens         | Both `globals.css` files                   | ⚠ Needs brand update |
| Multi-step apply form       | `ui/applicant-portal/app/apply/page.tsx`   | ✓ Keep structure |
| Session draft persistence   | Apply form (sessionStorage)                | ✓ Good pattern |
| ROLE_NAV config             | DashboardShell                             | ✓ Keep    |
| ROLE_COLORS / ROLE_LABELS   | DashboardShell                             | ✓ Keep    |
| FCRA reason codes           | `ui/applicant-portal/app/decision/page.tsx`| ⚠ Needs human-tone wrapper |
| Heroic wave divider SVG     | `ui/applicant-portal/app/page.tsx`         | ✗ Remove — decorative blob |

---

## "NOT in Scope" Design Decisions

These were considered and explicitly deferred:

| Decision                          | Rationale for deferral |
|-----------------------------------|------------------------|
| Dark mode                         | Two apps, two globals.css — needs CSS variable audit first. Not in current sprint. |
| Data visualization style guide    | Recharts is already chosen. Chart color palette can be derived from brand colors but needs its own doc. |
| Print / PDF styles                | Exam packets may need print CSS. Deferred to exam packet UI sprint. |
| Animation library                 | Current CSS transitions are sufficient. Don't add Framer Motion unless a specific interaction requires it. |
| Design tokens build pipeline      | Token tooling (Style Dictionary, etc.) is premature. Direct CSS vars work at this scale. |
| Regulator portal design spec      | Kept separate by design (see Pass 1 decision). Spec needed before regulator sprint. |
