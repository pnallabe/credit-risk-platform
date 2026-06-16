---
doc_type: committee_minutes
quarter: 2022-Q2
meeting_date: 2022-06-30
products_covered: [credit_card, personal_loan, mortgage]
---

# Credit Committee Meeting Minutes
## Q2 2022 — Inflation & Rate Response Session

**Date:** June 30, 2022
**Location:** Board Room, Level 12 + Video Conference
**Meeting Called to Order:** 9:00 AM
**Quorum:** Confirmed (8 of 8 voting members present)
**Special Topic:** Emergency Rate Environment Response — Portfolio & Policy Review

### Attendees

| Role | Name | Present |
|---|---|---|
| Chief Executive Officer | Jonathan A. Mercer | ✓ |
| Chief Risk Officer | Dr. Priya Nambiar | ✓ |
| Chief Financial Officer | Marcus T. Webb | ✓ |
| Chief Credit Officer | Sandra L. Chen | ✓ |
| Model Risk Officer | Dr. Alejandro Ruiz | ✓ |
| Compliance Officer | Patricia K. Owens | ✓ |
| Independent Director | Robert F. Kaminski | ✓ |
| Independent Director | Dr. Yuki Tanaka | ✓ |

---

## 1. Approval of Prior Minutes

Q1 2022 minutes approved. Note: Q1 2022 included the initial rate hike (+25 bps, March 16).

---

## 2. Macroeconomic Environment Review

**Presenter:** Chief Risk Officer

**Federal Reserve Rate Path (2022 YTD):**

| Date | Action | Target Rate |
|---|---|---|
| March 16, 2022 | +25 bps | 0.50% |
| May 4, 2022 | +50 bps | 1.00% |
| June 15, 2022 | +75 bps | 1.75% |

**Projected further hikes (based on Fed dot plot, June 2022):**
- July 2022: +75 bps expected → 2.50%
- September 2022: +50–75 bps → 3.00–3.25%
- Year-end 2022: 3.25–3.50% likely

**Inflation:** CPI at 8.6% (May 2022) — 40-year high.
**Consumer Debt Stress:** Real wage growth negative for 14 consecutive months.
Average consumer credit card balance up 12% YoY. Delinquency formation accelerating.

---

## 3. Prior Period Performance Review (Q1 2022)

| Metric | Q1 2022 | Q4 2021 | Q4 2019 (Pre-COVID Baseline) |
|---|---|---|---|
| Approval Rate | 28.9% | 34.0% | 28.1% |
| 30+ DPD Rate | 1.85% | 1.20% | 1.72% |
| Net Charge-Off Rate | 62 bps | 28 bps | 49 bps |
| Provision Expense | $780.9M | $45.0M | $38.0M |

**Discussion:** The $780.9M Q1 2022 provision reflects the CECL forward-looking reserve
build in response to the rate hike cycle and deteriorating macroeconomic outlook.
This represents a 20.6× multiple versus Q4 2019 baseline — consistent with stress modeling.

---

## 4. Emergency Policy Changes

### Item 4.1: Personal Loan APR Repricing — +150 bps All Tiers

**Presenter:** CFO / Chief Credit Officer
**Rationale:** Cost of funds increased 175 bps YTD. Current personal loan NIM has compressed
to 2.8% (target: 3.5%+). Without rate action, Q3/Q4 2022 vintages will be originated below
cost of funds on a risk-adjusted basis.

**Proposed Changes:**

| Risk Tier | Current Base Rate | Proposed Rate | Change |
|---|---|---|---|
| Prime-Plus (720+) | 10.49% | 11.99% | +150 bps |
| Prime (660–719) | 11.99% | 13.49% | +150 bps |
| Near-Prime (620–659) | 15.49% | 16.99% | +150 bps |

**Consumer Impact:** Estimated monthly payment increase of $18–$42 for average loan.
TILA disclosure updates required within 3 business days.

**Vote:** 7 in favor, 1 opposed (Director Tanaka — consumer affordability concerns).
**Motion carried. Board Resolution 2022-06.**

### Item 4.2: DTI Tightening — Personal Loan

**Presenter:** Chief Credit Officer
**Proposed:** Maximum DTI for personal loans reduce from 47% to 44%.
**Rationale:** At 6%+ rates, borrowers at 45–47% DTI are within 2–3% of unsustainable
debt service. Given income compression, protecting the top of the DTI band reduces
estimated future default exposure by $85M.

**Vote:** Unanimous. **Motion carried.**

### Item 4.3: Mortgage Policy — Refi Shutdown

**Discussion:** With 30-year fixed mortgage rates now at 5.81% (up from 3.10% in January),
the refi market has effectively shut down. Applications down 78% YoY.

- **Refi volume:** Q1 2022: 4,200 applications. Q2 2022: 910 applications.
- **Action:** Refi processing capacity reduced by 60%; staff redeployment to purchase channel.
- **HELOC:** Demand spiking as homeowners with sub-3% mortgages choose equity access over refi.
  HELOC max LTV confirmed at 85% CLTV.

No policy vote required — market-driven reduction.

### Item 4.4: Provision — Q2 2022 Outlook

CFO presented CECL scenario analysis for Q2 2022 provision:

| Scenario | Provision Estimate | Assumptions |
|---|---|---|
| Base Case | $420M | Fed hikes to 3.50% year-end; unemployment 4.5% |
| Adverse | $520M | Fed hikes to 4.00%; unemployment 5.5% |
| Severely Adverse | $680M | Fed hikes to 4.50%+; unemployment 7.0% |

**Resolution:** Provision at $420M (base case). **Vote:** Unanimous.

---

## 5. Model Performance

| Model | AUC | KS | PSI (DTI Characteristic) | Status |
|---|---|---|---|---|
| cc_pd_v1 | 0.803 | 47% | **0.22** | ⚠ Alert — PSI >0.20 |
| pl_pd_v1 | 0.798 | 46% | **0.25** | ⚠ Alert — recalibration required |
| mortgage_pd_v1 | 0.775 | 45% | **0.21** | ⚠ Alert |

**Finding:** PSI elevation driven by DTI distribution shift — rate hike cycle causing
significant changes to debt service coverage ratios across population.
Model Risk Officer recommends emergency recalibration for pl_pd_v1 and cc_pd_v1 by Q3 2022.

**Action:** Model recalibration project initiated. SR 11-7 amendment filed.

---

## 6. Regulatory Items

- **Reg B Appraisal Bias Rule:** CFPB/FRB/OCC joint NPRM — monitoring.
- **Basel III Endgame:** Comment period open. Capital implications being assessed.
- **State APR Caps:** IL 36% APR cap (SB 1792) — verify PL and CC compliance.
  CA, NM rate cap: verified compliant. No violations.

---

## Action Items

| Action | Owner | Due Date |
|---|---|---|
| APR repricing — TILA disclosures | Compliance | July 3, 2022 |
| Decision engine DTI parameter update | Technology | June 30, 2022 |
| Model recalibration scope + plan | Model Risk | July 31, 2022 |
| HELOC product capacity planning | Product | July 15, 2022 |
| Q2 2022 CECL provision — final | Finance | July 15, 2022 |

**Next Meeting:** September 30, 2022 (Q3 2022)

---

*Minutes recorded by: Office of the Chief Credit Officer*
*Board Resolution 2022-06 — Personal Loan APR Repricing and DTI Tightening*
