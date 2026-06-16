#!/usr/bin/env python3
"""
scripts/generate_governance_docs.py
=====================================
Phase 5 — Generate all 77 Markdown governance documents:
  - 9  Policy Manuals           → docs/governance/policy_manuals/
  - 44 Committee Minutes        → docs/governance/committee_minutes/
  - 12 Model Validation Reports → docs/governance/model_validation/
  - 12 Fair Lending Reports     → docs/governance/fair_lending/

Usage
-----
  python scripts/generate_governance_docs.py
  python scripts/generate_governance_docs.py --section policy_manuals
  python scripts/generate_governance_docs.py --section committee_minutes
  python scripts/generate_governance_docs.py --section model_validation
  python scripts/generate_governance_docs.py --section fair_lending
"""

from __future__ import annotations

import argparse
import logging
import textwrap
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GOVERNANCE_ROOT = PROJECT_ROOT / "docs" / "governance"

# ---------------------------------------------------------------------------
# Policy version epochs (mirrors Phase 1 seeder)
# ---------------------------------------------------------------------------

POLICY_EPOCHS = [
    # (tag_suffix, effective_from, cc_fico, pl_fico_hard, mort_fico_conf, cc_max_dti, pl_max_dti, mort_max_dti, notes)
    ("2015-expansion",          "2015-01-01", 620, 580, 640, 0.50, 0.50, 0.43, "Post-GFC expansion, low-rate environment"),
    ("2016-steady",             "2016-01-01", 620, 580, 640, 0.50, 0.50, 0.43, "Steady-state growth"),
    ("2017-tighten",            "2017-07-01", 640, 600, 660, 0.47, 0.47, 0.41, "Fed rate hike cycle begins"),
    ("2018-tighten",            "2018-01-01", 660, 620, 680, 0.45, 0.45, 0.40, "+125 bps cumulative"),
    ("2019-cautious",           "2019-01-01", 660, 620, 680, 0.43, 0.43, 0.40, "Late-cycle caution"),
    ("2020q1-covid-tighten",    "2020-03-15", 690, 650, 700, 0.40, 0.40, 0.38, "COVID-19 shock"),
    ("2020q2-covid-hard",       "2020-04-01", 700, 660, 720, 0.38, 0.38, 0.36, "Maximum restriction, jumbo halted"),
    ("2020q3-forbearance",      "2020-07-01", 680, 640, 700, 0.40, 0.42, 0.40, "Relief overlay"),
    ("2021-stimulus",           "2021-01-01", 660, 620, 680, 0.45, 0.48, 0.43, "Post-stimulus normalization"),
    ("2021-expand",             "2021-07-01", 640, 600, 660, 0.47, 0.50, 0.43, "Limit expansion"),
    ("2022q1-hike",             "2022-03-01", 660, 620, 680, 0.45, 0.47, 0.41, "Fed hike +25 bps"),
    ("2022q2-emergency",        "2022-06-01", 680, 650, 700, 0.42, 0.44, 0.39, "Emergency repricing"),
    ("2022q3-tighten",          "2022-09-01", 700, 660, 720, 0.40, 0.42, 0.38, "Refi shutdown"),
    ("2022q4-hold",             "2022-12-01", 700, 660, 720, 0.40, 0.42, 0.38, "Hold pattern"),
    ("2023-stable",             "2023-01-01", 700, 660, 720, 0.40, 0.43, 0.38, "High-rate stable"),
    ("2023-near-prime-tighten", "2023-07-01", 700, 660, 720, 0.40, 0.43, 0.38, "Near-prime selective tightening"),
    ("2024-hold",               "2024-01-01", 700, 660, 720, 0.40, 0.43, 0.38, "Hold"),
    ("2024-selective",          "2024-07-01", 695, 655, 715, 0.41, 0.44, 0.39, "Selective easing"),
    ("2025-ease",               "2025-01-01", 680, 640, 700, 0.43, 0.46, 0.41, "Easing cycle begins"),
    ("2025-expand",             "2025-07-01", 660, 620, 680, 0.45, 0.48, 0.43, "Expansion"),
    ("2026-expand",             "2026-01-01", 650, 610, 670, 0.47, 0.50, 0.43, "Continued expansion"),
    ("2026-current",            "2026-07-01", 640, 600, 660, 0.48, 0.50, 0.43, "Current projected"),
]

# Provision / performance data by quarter (consistent with Phase 4 outputs)
_PROV_BY_QTR: dict[str, dict] = {
    "2019-Q4": {"prov_m": 38.0,   "del_bps": 128, "cor_bps": 35,  "approval_pct": 31.2},
    "2020-Q1": {"prov_m": 58.0,   "del_bps": 145, "cor_bps": 41,  "approval_pct": 29.1},
    "2020-Q2": {"prov_m": 109.5,  "del_bps": 182, "cor_bps": 55,  "approval_pct": 24.8},
    "2020-Q3": {"prov_m": 88.0,   "del_bps": 175, "cor_bps": 50,  "approval_pct": 26.3},
    "2020-Q4": {"prov_m": 72.0,   "del_bps": 160, "cor_bps": 44,  "approval_pct": 27.5},
    "2021-Q1": {"prov_m": 62.0,   "del_bps": 148, "cor_bps": 38,  "approval_pct": 29.2},
    "2021-Q2": {"prov_m": 54.0,   "del_bps": 135, "cor_bps": 33,  "approval_pct": 31.0},
    "2021-Q3": {"prov_m": 48.0,   "del_bps": 125, "cor_bps": 30,  "approval_pct": 33.1},
    "2021-Q4": {"prov_m": 45.0,   "del_bps": 120, "cor_bps": 28,  "approval_pct": 34.0},
    "2022-Q1": {"prov_m": 780.9,  "del_bps": 185, "cor_bps": 62,  "approval_pct": 28.9},
    "2022-Q2": {"prov_m": 420.0,  "del_bps": 210, "cor_bps": 72,  "approval_pct": 25.4},
    "2022-Q3": {"prov_m": 310.0,  "del_bps": 225, "cor_bps": 80,  "approval_pct": 23.1},
    "2022-Q4": {"prov_m": 280.0,  "del_bps": 220, "cor_bps": 78,  "approval_pct": 23.5},
    "2023-Q1": {"prov_m": 245.0,  "del_bps": 215, "cor_bps": 74,  "approval_pct": 24.0},
    "2023-Q2": {"prov_m": 230.0,  "del_bps": 208, "cor_bps": 70,  "approval_pct": 24.5},
    "2023-Q3": {"prov_m": 218.0,  "del_bps": 200, "cor_bps": 66,  "approval_pct": 25.2},
    "2023-Q4": {"prov_m": 205.0,  "del_bps": 195, "cor_bps": 62,  "approval_pct": 25.8},
    "2024-Q1": {"prov_m": 195.0,  "del_bps": 190, "cor_bps": 59,  "approval_pct": 26.2},
    "2024-Q2": {"prov_m": 185.0,  "del_bps": 184, "cor_bps": 56,  "approval_pct": 26.8},
    "2024-Q3": {"prov_m": 175.0,  "del_bps": 178, "cor_bps": 52,  "approval_pct": 27.5},
    "2024-Q4": {"prov_m": 165.0,  "del_bps": 172, "cor_bps": 49,  "approval_pct": 28.1},
    "2025-Q1": {"prov_m": 155.0,  "del_bps": 165, "cor_bps": 45,  "approval_pct": 28.9},
    "2025-Q2": {"prov_m": 145.0,  "del_bps": 158, "cor_bps": 42,  "approval_pct": 29.5},
}


# ===========================================================================
# 5.1  Policy Manuals (9 files)
# ===========================================================================

_PM_SPECS = [
    # (filename,             product,         from,         to,           version_tag,                  epoch_range)
    ("cc_policy_2015_2016",  "credit_card",   "2015-01-01", "2016-12-31", "cc-policy-2015-2016",        [0, 1]),
    ("cc_policy_2017_2019",  "credit_card",   "2017-01-01", "2019-12-31", "cc-policy-2017-2019",        [2, 3, 4]),
    ("cc_policy_2020_2021",  "credit_card",   "2020-01-01", "2021-12-31", "cc-policy-2020-2021",        [5, 6, 7, 8, 9]),
    ("cc_policy_2022_2026",  "credit_card",   "2022-01-01", "2026-12-31", "cc-policy-2022-2026",        [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
    ("pl_policy_2015_2019",  "personal_loan", "2015-01-01", "2019-12-31", "pl-policy-2015-2019",        [0, 1, 2, 3, 4]),
    ("pl_policy_2020_2022",  "personal_loan", "2020-01-01", "2022-12-31", "pl-policy-2020-2022",        [5, 6, 7, 8, 9, 10, 11, 12, 13]),
    ("pl_policy_2023_2026",  "personal_loan", "2023-01-01", "2026-12-31", "pl-policy-2023-2026",        [14, 15, 16, 17, 18, 19, 20, 21]),
    ("mort_policy_2015_2021","mortgage",      "2015-01-01", "2021-12-31", "mort-policy-2015-2021",      [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]),
    ("mort_policy_2022_2026","mortgage",      "2022-01-01", "2026-12-31", "mort-policy-2022-2026",      [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]),
]

_PRODUCT_DISPLAY = {
    "credit_card":   "Credit Card",
    "personal_loan": "Personal Loan",
    "mortgage":      "Mortgage",
}

_PRODUCT_REG = {
    "credit_card":   "Truth in Lending Act (TILA / Regulation Z), Equal Credit Opportunity Act (ECOA / Regulation B), Fair Credit Reporting Act (FCRA)",
    "personal_loan": "Truth in Lending Act (TILA / Regulation Z), Equal Credit Opportunity Act (ECOA / Regulation B), Fair Credit Reporting Act (FCRA), Military Lending Act (MLA)",
    "mortgage":      "Truth in Lending Act (TILA / Regulation Z), RESPA/TRID (3-day Loan Estimate, 3-day Closing Disclosure), Equal Credit Opportunity Act (ECOA / Regulation B), Home Mortgage Disclosure Act (HMDA), Fair Credit Reporting Act (FCRA), ATR/QM Rule (12 CFR Part 1026.43)",
}


def _pm_version_history(epoch_indices: list[int]) -> str:
    rows = ["| Version Tag | Effective Date | CC FICO | PL FICO | Mort FICO | Notes |",
            "|---|---|---|---|---|---|"]
    for i in epoch_indices:
        e = POLICY_EPOCHS[i]
        tag = f"multi-v1-{e[0]}"
        rows.append(f"| `{tag}` | {e[1]} | {e[2]} | {e[3]} | {e[4]} | {e[8]} |")
    return "\n".join(rows)


def _pm_pricing_matrix(product: str) -> str:
    if product == "credit_card":
        return textwrap.dedent("""\
            | Risk Grade | FICO Range | Base APR | Max Credit Limit |
            |---|---|---|---|
            | Super-Prime | 740+ | 14.99% | $25,000 |
            | Prime | 700–739 | 18.99% | $15,000 |
            | Near-Prime | 660–699 | 22.99% | $7,500 |
            | Subprime | 620–659 | 27.99% | $3,000 |
            | Deep Subprime | <620 | Decline | — |
            """)
    elif product == "personal_loan":
        return textwrap.dedent("""\
            | Risk Grade | FICO Range | Base Rate | Max Loan |
            |---|---|---|---|
            | Prime-Plus | 720+ | 10.49% | $100,000 |
            | Prime | 660–719 | 11.99% | $50,000 |
            | Near-Prime | 620–659 | 15.49% | $25,000 |
            | Subprime | 580–619 | Manual Review | $10,000 |
            | Decline | <580 | Decline | — |

            **DTI Spreads:** ≤36% preferred (−0.50%), 37–50% standard (+0.00%), >50% decline.

            **Term Spreads:** 24m (−0.25%), 36m (0.00%), 48m (+0.50%), 60m (+1.00%), 72m (+1.75%).
            """)
    else:  # mortgage
        return textwrap.dedent("""\
            | Product | FICO | Rate Type | Base Rate | Jumbo Premium |
            |---|---|---|---|---|
            | Conforming | 740+ | 30-yr Fixed | 7.10% | — |
            | Conforming | 700–739 | 30-yr Fixed | 7.26% | — |
            | Conforming | 660–699 | 30-yr Fixed | 7.52% | — |
            | Conforming | 740+ | 15-yr Fixed | 6.50% | — |
            | Jumbo | 720+ | 30-yr Fixed | 7.475% | +0.375% |
            | Jumbo | 700–719 | 30-yr Fixed | 7.64% | +0.375% |
            | FHA | 580+ | 30-yr Fixed | 7.35% | — |

            **LTV Adjustments:** ≤80% (0 bps), 80–90% (+12.5 bps), 90–97% (+25 bps).
            **Points Discount:** −0.25% per point paid (max 3 points).
            """)


def _pm_approval_authority(product: str) -> str:
    if product == "mortgage":
        return textwrap.dedent("""\
            | Decision Type | Authority | Threshold |
            |---|---|---|
            | Automated Approval | System | FICO ≥720, DTI ≤43%, LTV ≤80%, no derogatory marks, fraud score <5% |
            | Loan Officer | Licensed MLO | FICO 620–719, or DTI 43–50% (Non-QM), or LTV 80–97% |
            | Credit Committee | Full Committee | Jumbo loans >$1.5M, exceptions, policy overrides, ATR non-compliance reviews |
            | Board Review | Board of Directors | Jumbo loans >$5M, new product approvals, policy framework changes |
            """)
    elif product == "personal_loan":
        return textwrap.dedent("""\
            | Decision Type | Authority | Threshold |
            |---|---|---|
            | Automated Approval | System | FICO ≥720, DTI ≤36%, fraud score <5%, PD <3% |
            | Loan Officer | Credit Analyst | FICO 620–719 or DTI 36–50% or requested amount ≥$50K |
            | Credit Committee | Full Committee | FICO 580–619, exceptions, policy overrides, amounts ≥$75K |
            """)
    else:
        return textwrap.dedent("""\
            | Decision Type | Authority | Threshold |
            |---|---|---|
            | Automated Approval | System | FICO ≥720, DTI ≤50%, fraud score <5%, PD <5% |
            | Hybrid Review | Credit Analyst | FICO 660–719 or DTI 45–50% or credit limit ≥$15K |
            | Credit Committee | Full Committee | FICO 620–659, near-prime exceptions, credit limit >$20K |
            """)


def generate_policy_manuals(root: Path = GOVERNANCE_ROOT) -> list[Path]:
    out_dir = root / "policy_manuals"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for (fname, product, eff_from, eff_to, vtag, epoch_idx) in _PM_SPECS:
        display = _PRODUCT_DISPLAY[product]
        regs    = _PRODUCT_REG[product]
        epochs  = [POLICY_EPOCHS[i] for i in epoch_idx]
        first_e = epochs[0]
        last_e  = epochs[-1]

        # Borrower profile from mid-range epoch
        mid_e = epochs[len(epochs) // 2]
        cc_fico, pl_fico, mo_fico = mid_e[2], mid_e[3], mid_e[4]
        cc_dti,  pl_dti,  mo_dti  = mid_e[5], mid_e[6], mid_e[7]

        if product == "credit_card":
            fico_floor = cc_fico; max_dti = cc_dti
        elif product == "personal_loan":
            fico_floor = pl_fico; max_dti = pl_dti
        else:
            fico_floor = mo_fico; max_dti = mo_dti

        covid_section = ""
        if any("covid" in POLICY_EPOCHS[i][0] or "forbearance" in POLICY_EPOCHS[i][0]
               for i in epoch_idx):
            covid_section = textwrap.dedent(f"""\
                ## COVID-19 Policy Overlay (March–December 2020)

                ### Emergency Credit Policy (Board Resolution 2020-03)

                Effective **March 20, 2020**, the Credit Committee enacted emergency overlay measures in
                response to the COVID-19 pandemic:

                | Parameter | Pre-COVID | COVID Emergency | Relief Phase |
                |---|---|---|---|
                | FICO Floor | {POLICY_EPOCHS[4][2] if product=="credit_card" else POLICY_EPOCHS[4][3] if product=="personal_loan" else POLICY_EPOCHS[4][4]} | {POLICY_EPOCHS[6][2] if product=="credit_card" else POLICY_EPOCHS[6][3] if product=="personal_loan" else POLICY_EPOCHS[6][4]} | {POLICY_EPOCHS[7][2] if product=="credit_card" else POLICY_EPOCHS[7][3] if product=="personal_loan" else POLICY_EPOCHS[7][4]} |
                | Max DTI | {POLICY_EPOCHS[4][5] if product=="credit_card" else POLICY_EPOCHS[4][6] if product=="personal_loan" else POLICY_EPOCHS[4][7]:.0%} | {POLICY_EPOCHS[6][5] if product=="credit_card" else POLICY_EPOCHS[6][6] if product=="personal_loan" else POLICY_EPOCHS[6][7]:.0%} | {POLICY_EPOCHS[7][5] if product=="credit_card" else POLICY_EPOCHS[7][6] if product=="personal_loan" else POLICY_EPOCHS[7][7]:.0%} |

                **Jumbo Suspension:** All jumbo originations suspended effective April 1, 2020, through
                December 31, 2020 (Board Resolution 2020-04).

                **Forbearance Program:** Customers experiencing COVID-19-related hardship may request
                payment deferral of up to 12 months. Forbearance does not trigger adverse credit
                reporting per CARES Act §4021.

                **Income Verification Relief:** Self-employed borrowers: bank statements (3 months)
                accepted in lieu of tax returns for originations March–September 2020.

                """)

        changelog_rows = []
        for i, idx in enumerate(epoch_idx):
            e = POLICY_EPOCHS[idx]
            if idx == 0:
                changelog_rows.append(f"| {e[1]} | Initial policy established | `multi-v1-{e[0]}` | Board Resolution 2015-01 |")
            else:
                prev = POLICY_EPOCHS[epoch_idx[i-1]] if i > 0 else e
                fico_curr = e[2] if product == "credit_card" else (e[3] if product == "personal_loan" else e[4])
                fico_prev = prev[2] if product == "credit_card" else (prev[3] if product == "personal_loan" else prev[4])
                if fico_curr != fico_prev:
                    delta = fico_curr - fico_prev
                    sign = "+" if delta > 0 else ""
                    desc = f"FICO floor {sign}{delta} pts ({fico_prev}→{fico_curr}); {e[8]}"
                else:
                    desc = e[8]
                brd = f"Board Resolution {e[1][:4]}-{(idx+1):02d}"
                changelog_rows.append(f"| {e[1]} | {desc} | `multi-v1-{e[0]}` | {brd} |")

        changelog = "\n".join(
            ["| Date | Change | Version Tag | Board Resolution |", "|---|---|---|---|"] + changelog_rows
        )

        if product == "personal_loan":
            income_verif = textwrap.dedent("""\
                | Annual Income | Verification Required | Method |
                |---|---|---|
                | $1K – $15K | Bank Statement | 3 months |
                | $15K – $50K | Pay Stub | 2 most recent |
                | $50K – $100K | Pay Stub + W-2 | Most recent |
                | $100K+ | Tax Return | 2 years (IRS 4506-C) |
                | Self-Employed | Tax Return + P&L | 2 years |
                """)
        elif product == "mortgage":
            income_verif = textwrap.dedent("""\
                | Income Type | Documentation | Verification |
                |---|---|---|
                | W-2 / Salaried | 30-day pay stubs, 2-yr W-2 | VOE via WVOE or 4506-C |
                | Self-Employed | 2-yr tax returns, YTD P&L | CPA letter required |
                | Rental Income | Schedule E, 1-yr leases | 75% gross rental income |
                | Investment | 2-yr statements | 100% of distributions |
                | Retirement / SSA | Award letters | 100% gross |

                **ATR Verification**: All 8 ATR factors must be documented per 12 CFR §1026.43(c).
                Exceptions require Credit Committee approval.
                """)
        else:
            income_verif = textwrap.dedent("""\
                | Credit Limit | Stated Income | Verification |
                |---|---|---|
                | ≤$5,000 | < $50K/yr | None required |
                | $5K – $15K | Any | Optional soft verification |
                | >$15K | Any | Full income verification required |
                """)

        tila_section = (
            "### TILA / Regulation Z\n"
            "- APR must be disclosed within 0.125% accuracy\n"
            "- Finance charge itemization required in disclosure package\n"
            "- Right of rescission: 3-business-day rescission period for refinances of primary residence"
        ) if product in ("personal_loan", "credit_card") else ""

        respa_section = (
            "### RESPA / TRID\n"
            "- Loan Estimate (LE) due within 3 business days of application\n"
            "- Closing Disclosure (CD) due 3 business days before consummation\n"
            "- Tolerance limits: 0% tolerance for origination charges, 10% tolerance for third-party services\n"
            "- HMDA LAR reporting required for mortgage applications \u2265$30,000\n\n"
            "### ATR / QM Rule (12 CFR \u00a71026.43)\n"
            "- All 8 ATR factors must be verified and documented\n"
            "- QM Safe Harbor: DTI \u226443%, no balloon payments, no negative amortisation\n"
            "- QM Rebuttable Presumption: HPML loans above threshold\n"
            "- Non-QM originations require enhanced documentation and Credit Committee approval"
        ) if product == "mortgage" else ""

        content = textwrap.dedent(f"""\
            ---
            product_type: {product}
            effective_from: {eff_from}
            effective_to: {eff_to}
            doc_type: policy_manual
            version_tag: {vtag}
            ---

            # {display} Underwriting Policy Manual
            **Period Covered:** {eff_from} – {eff_to}
            **Version Tag:** `{vtag}`
            **Regulatory Framework:** {regs}
            **Classification:** Internal — Restricted Distribution

            ---

            ## 1. Purpose & Scope

            This policy manual governs the underwriting, approval, and pricing of **{display}** products
            originated during the period {eff_from} through {eff_to}. It applies to all originations
            processed through the automated decision engine, hybrid review queues, and manual underwriting
            workflows.

            This manual supersedes all prior {display} underwriting guidelines for the stated period and
            is binding on all credit analysts, loan officers, and automated decision systems. Deviations
            require written exception approval per Section 5 (Exception Process).

            **Regulatory Framework**: {regs}

            ---

            ## 2. Effective Date & Version History

            {_pm_version_history(epoch_idx)}

            ---

            ## 3. Eligible Borrower Profile

            ### FICO Score Requirements

            | Tier | Score Range | Outcome |
            |---|---|---|
            | Prime-Plus | 740+ | Auto-approve, preferred pricing |
            | Prime | 700–739 | Auto-approve, standard pricing |
            | Near-Prime | {fico_floor}–699 | Approve with enhanced verification |
            | Hard Decline | <{fico_floor} | Automatic decline — FCRA reason code AA01 |

            *FICO floor as of {mid_e[1]}. See Version History for epoch-specific floors.*

            ### Debt-to-Income Requirements

            | DTI Band | Classification | Decision |
            |---|---|---|
            | ≤36% | Preferred | Auto-approve |
            | 37–{int(max_dti*100)}% | Standard | Approve with documentation |
            | >{int(max_dti*100)}% | Decline | FCRA reason code AA04 |

            ### Employment Requirements

            - Minimum 2 years continuous employment (or 2 years in same field for job changers)
            - Self-employed borrowers require 2-year self-employment history
            - Probationary employees: minimum 6 months in current role
            - Retired/disability income: award letter + 3-year continuance verified

            ---

            ## 4. Product Parameters

            {'### Loan Limits' if product != 'credit_card' else '### Credit Limits'}

            {'- **Minimum loan amount:** $1,000' if product == 'personal_loan' else ''}
            {'- **Maximum loan amount (prime-plus):** $100,000' if product == 'personal_loan' else ''}
            {'- **Term options:** 24, 36, 48, 60, 72 months' if product == 'personal_loan' else ''}
            {'- **Conforming loan limit:** $726,200' if product == 'mortgage' else ''}
            {'- **Jumbo threshold:** >$726,200 (subject to jumbo_enabled policy flag)' if product == 'mortgage' else ''}
            {'- **Maximum LTV (conforming):** 97% with PMI' if product == 'mortgage' else ''}
            {'- **Minimum credit limit:** $300' if product == 'credit_card' else ''}
            {'- **Maximum credit limit:** $25,000 (prime-plus)' if product == 'credit_card' else ''}

            ### Rate Ranges

            {'- **APR range:** 14.99% – 29.99% (subject to state usury caps)' if product == 'credit_card' else ''}
            {'- **Rate range:** 5.99% – 36.00%' if product == 'personal_loan' else ''}
            {'- **Rate range:** 3.00% – 14.99% (30-yr fixed)' if product == 'mortgage' else ''}

            ---

            ## 5. Underwriting Guidelines

            ### Income Verification Matrix

            {income_verif}

            ### Exception Process

            Exceptions to standard underwriting guidelines require:
            1. Written justification by the originating loan officer documenting compensating factors
            2. Supervisor countersignature for FICO exceptions within 20 points of floor
            3. Credit Committee approval for FICO exceptions >20 points below floor
            4. Documentation retained in loan file for 7 years (ECOA record retention)

            **Compensating Factors** (may offset borderline FICO/DTI):
            - Residual income >150% of threshold
            - 12+ months cash reserves
            - Low utilization rate (<20% revolving)
            - Long credit history (>15 years, no recent derogatories)

            ---

            ## 6. Pricing Matrix

            {_pm_pricing_matrix(product)}

            ---

            ## 7. Approval Authority Matrix

            {_pm_approval_authority(product)}

            ---

            ## 8. Regulatory Compliance Notes

            ### ECOA / Regulation B (Adverse Action)
            All declined applications must receive an Adverse Action Notice within **30 days**
            (3 days for counter-offers). The notice must include up to 4 FCRA principal reasons
            from the standardized code list (AA01–AA99). Reason codes must be ordered by impact
            severity (highest discriminating factor first).

            ### FCRA (Fair Credit Reporting Act)
            - Permissible purpose disclosure required at application
            - Credit file freeze check required before underwriting
            - Adverse action notices trigger 60-day dispute window
            - 2-year record retention for all credit pull authorizations

            {tila_section}
            {respa_section}

            ### State Usury Limits
            All originations must comply with applicable state usury caps. The pricing engine
            enforces per-state APR caps at origination. Any quote exceeding a state cap is
            automatically clamped and flagged for compliance review.

            ---

            {covid_section}## 9. Change Log

            {changelog}

            ---

            *This document is subject to annual review and may be updated more frequently in response
            to regulatory changes, macroeconomic conditions, or model performance findings.
            Approved by: Chief Credit Officer | Chief Risk Officer | Compliance Officer*
            """)

        path = out_dir / f"{fname}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
        log.info("Wrote %s", path)

    return written


# ===========================================================================
# 5.2  Committee Minutes (44 files)
# ===========================================================================

_QUARTER_END_DATES = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}

_REGULATORY_HORIZON: dict[tuple[int,int], str] = {
    (2015,1): "CFPB HMDA final rule anticipated; monitoring Basel III capital implementation.",
    (2015,2): "CFPB TILA-RESPA Integrated Disclosure (TRID) effective October 3, 2015.",
    (2015,3): "TRID implementation complete. CFPB HMDA rulemaking in progress.",
    (2015,4): "CFPB finalized HMDA data collection expansion rule (Reg C amendments).",
    (2016,1): "OCC guidance on responsible innovation; monitoring fintech charter proposal.",
    (2016,2): "CFPB arbitration rule proposed; FSOC systemic risk review of nonbank lenders.",
    (2016,3): "CFPB payday lending proposed rule; credit card fee disclosure review.",
    (2016,4): "OCC fintech charter finalized. Fed rate hike cycle accelerating.",
    (2017,1): "OCC Model Risk Management guidance update. CECL final standard (ASC 326) issued.",
    (2017,2): "CFPB prepaid rule effective. SIFI threshold review underway.",
    (2017,3): "CFPB arbitration rule struck down by Congress (CRA). Basel III US finalization.",
    (2017,4): "Tax Cuts and Jobs Act — implications for consumer debt capacity modeling.",
    (2018,1): "S.2155 (Economic Growth Act) signed: raised SIFI threshold. CECL adoption planning.",
    (2018,2): "CFPB leadership change; enforcement posture under review.",
    (2018,3): "OCC true lender proposal. State AG coordination on consumer protection.",
    (2018,4): "CECL early adopters reporting. Basel III US leverage ratio finalization.",
    (2019,1): "CFPB HMDA reporting threshold raised ($30K). Monitoring GSE reform discussions.",
    (2019,2): "CFPB qualified mortgage patch expiry anticipated 2021. Reviewing credit access impact.",
    (2019,3): "Fed rate cuts begin (−75bps YTD). Monitoring credit quality lagged response.",
    (2019,4): "CECL mandatory for large institutions January 2020. Final CECL transition rules.",
    (2020,1): "COVID-19 pandemic. CARES Act §4021 credit reporting provisions. Fed emergency actions.",
    (2020,2): "CARES Act forbearance compliance. OCC/FDIC/Fed joint guidance on loan modifications.",
    (2020,3): "CFPB CARES Act supervision priorities. SBA PPP coordination for small business borrowers.",
    (2020,4): "CFPB debt collection final rule (FDCPA). State eviction moratorium expiry tracking.",
    (2021,1): "Biden CFPB leadership change — increased enforcement posture anticipated.",
    (2021,2): "CFPB credit card late fee ANPR. Monitoring LIBOR transition for ARM products.",
    (2021,3): "CFPB Small Business Data Collection Rule (1071) proposed. SOFR transition.",
    (2021,4): "CFPB credit card penalty fee scrutiny. Infrastructure bill — construction loan demand.",
    (2022,1): "Fed rate hike cycle begins. CFPB junk fee initiative. Basel III endgame proposal.",
    (2022,2): "Reg B appraisal bias rule proposed. CFPB BNPL inquiry. Monitoring rent reporting.",
    (2022,3): "CFPB 1033 data portability NPRM. State USURY cap legislation (IL, CA). QM patch expired.",
    (2022,4): "CFPB mortgage servicing rule review. Basel III endgame comment period.",
    (2023,1): "SVB/Signature Bank failures — liquidity stress monitoring. Basel III comment period ends.",
    (2023,2): "CFPB 1071 small business rule final. DOJ/HUD joint redlining initiative.",
    (2023,3): "CFPB credit card late fee rule (proposed $8 cap). Basel III endgame proposal review.",
    (2023,4): "CFPB credit card fee final rule anticipated Q1 2024. OCC AI model risk guidance.",
    (2024,1): "Basel III endgame re-proposal expected. CFPB credit card late fee rule final.",
    (2024,2): "CFPB 1033 final rule. AI/ML model fairness guidance — FRB, OCC joint paper.",
    (2024,3): "Fed rate cut cycle begins. CFPB digital payment supervision expansion.",
    (2024,4): "Election outcome: regulatory posture shift anticipated. Monitoring CFPB 2025 agenda.",
    (2025,1): "New CFPB leadership — enforcement review. OCC AI guidance final expected Q3.",
    (2025,2): "Fed continued easing. Monitoring consumer debt-to-income trends.",
    (2025,3): "CFPB rulemaking pause period. State consumer protection laws — NY, CA activity.",
    (2025,4): "Monitoring 2026 economic outlook. Basel III US finalization timeline.",
    (2026,1): "Continued monitoring. Updated stress testing scenarios for 2027 planning.",
    (2026,2): "Mid-year credit quality review. Updated CECL assumptions.",
}


def _minutes_prior_period(yr: int, q: int) -> str:
    key = (yr, q)
    d = _PROV_BY_QTR.get(f"{yr}-Q{q}", {"prov_m": 150.0, "del_bps": 180, "cor_bps": 55, "approval_pct": 27.0})
    return textwrap.dedent(f"""\
        | Metric | Actual | Prior Quarter | Budget | YoY |
        |---|---|---|---|---|
        | Approval Rate | {d['approval_pct']:.1f}% | — | 28.0% | — |
        | 30+ DPD Rate | {d['del_bps']/10:.1f}% | — | 1.80% | — |
        | Net Charge-Off Rate (bps) | {d['cor_bps']} bps | — | 50 bps | — |
        | Provision Expense | ${d['prov_m']:.1f}M | — | — | — |
        """)


def _standard_minutes(yr: int, q: int) -> str:
    qdate = f"{yr}-{_QUARTER_END_DATES[q]}"
    meeting_label = f"Q{q} {yr} Credit Committee Meeting"
    prev_q, prev_y = (q-1, yr) if q > 1 else (4, yr-1)
    prev_label = f"Q{prev_q} {prev_y}"
    reg_note = _REGULATORY_HORIZON.get((yr, q), "No material new regulatory items this quarter.")

    return textwrap.dedent(f"""\
        ---
        doc_type: committee_minutes
        quarter: {yr}-Q{q}
        meeting_date: {qdate}
        products_covered: [credit_card, personal_loan, mortgage]
        ---

        # Credit Committee Meeting Minutes
        ## {meeting_label}

        **Date:** {qdate}
        **Location:** Board Room, Level 12 — also available via secure video conference
        **Meeting Called to Order:** 9:00 AM
        **Quorum:** Confirmed (7 of 8 voting members present)

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
        | Independent Director | Dr. Yuki Tanaka | {'✓' if yr % 2 == 0 else '— (excused)'} |

        ---

        ## 1. Approval of Prior Minutes

        Minutes from the {prev_label} meeting were reviewed and approved with no amendments.
        **Vote:** Unanimous.

        ---

        ## 2. Prior Period Performance Review

        The Chief Credit Officer presented Q{q} {yr} portfolio performance:

        {_minutes_prior_period(yr, q)}

        **Discussion:** The CRO noted {'delinquency trends remain elevated versus pre-2022 levels; however, charge-off experience is tracking within budget.' if yr >= 2022 else 'portfolio performance is within expected ranges for the current rate environment.'} No material adverse trends requiring immediate policy action were identified.

        ---

        ## 3. Policy Change Proposals & Votes

        {'**Item 3.1:** Review of FICO floor parameters for upcoming quarter — no changes proposed. Credit quality remains stable. **Vote:** No action required.' if yr not in (2017, 2018, 2020, 2022) else ''}
        {'**Item 3.1:** Annual rate calibration review. Presented by Chief Credit Officer. **Outcome:** Standard rate schedule maintained. Approved unanimously.' if yr in (2017, 2021, 2024) else ''}

        ---

        ## 4. Model Performance Update

        The Model Risk Officer presented the quarterly model performance summary:

        | Model | AUC | KS Statistic | PSI (30-day) | Status |
        |---|---|---|---|---|
        | cc_pd_v1 | {0.82 - (yr-2015)*0.003:.3f} | {52 - (yr-2015)}% | {0.05 + (0.01 if yr==2022 else 0):.2f} | {'⚠ Review' if yr == 2022 else '✓ Stable'} |
        | pl_pd_v1 | {0.80 - (yr-2015)*0.003:.3f} | {50 - (yr-2015)}% | {0.04 + (0.015 if yr==2022 else 0):.3f} | {'⚠ Elevated PSI' if yr == 2022 else '✓ Stable'} |
        | mortgage_pd_v1 | {0.78 - (yr-2015)*0.002:.3f} | {48 - (yr-2015)}% | {0.03 + (0.01 if yr==2022 else 0):.2f} | {'⚠ Monitor' if yr >= 2022 else '✓ Stable'} |

        {'**Alert:** PSI > 0.20 observed on DTI characteristic for pl_pd_v1. Model recalibration recommended by Q3. See Model Validation Report for details.' if yr == 2022 and q in (1,2) else ''}
        {'**Update:** Recalibration of pl_pd_v1 complete. PSI normalized to 0.08. SR 11-7 approval obtained.' if yr == 2023 and q in (2,3) else ''}

        ---

        ## 5. Regulatory Horizon Items

        {reg_note}

        ---

        ## 6. Action Items & Next Meeting

        | Action | Owner | Due Date |
        |---|---|---|
        | Distribute meeting minutes for review | Credit Ops | {yr}-{'0' if q < 3 else ''}{['01','04','07','10'][q-1].zfill(2) if False else ['01','04','07','10'][q-1]}-15 |
        | Submit model monitoring report | Model Risk Officer | Rolling monthly |
        | Regulatory update briefing | Compliance Officer | Next meeting |

        **Next Meeting:** End of Q{q % 4 + 1} {yr if q < 4 else yr+1} (tentative).

        ---

        *Minutes recorded by: Office of the Chief Credit Officer*
        *Minutes approved by: Credit Committee Chair (CRO)*
        *Distribution: Committee members, Board Audit Committee (summary only)*
        """)


def _extended_2018q4_minutes() -> str:
    return textwrap.dedent("""\
        ---
        doc_type: committee_minutes
        quarter: 2018-Q4
        meeting_date: 2018-12-31
        products_covered: [credit_card, personal_loan, mortgage]
        ---

        # Credit Committee Meeting Minutes
        ## Q4 2018 — Rate Hike Policy Review Session

        **Date:** December 31, 2018
        **Location:** Board Room, Level 12
        **Meeting Called to Order:** 9:00 AM
        **Quorum:** Confirmed (8 of 8 voting members present)
        **Special Topic:** Federal Reserve Rate Hike Cycle — Credit Policy Response

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

        Minutes from Q3 2018 approved unanimously.

        ---

        ## 2. Federal Reserve Rate Hike Cycle — Management Presentation

        The CFO presented a detailed analysis of the Fed rate hike cycle and its impact on portfolio economics.

        **Rate Path Summary (December 2015 – December 2018):**

        | Date | Federal Funds Rate | Cumulative Change |
        |---|---|---|
        | December 2015 | 0.50% | +0 bps (first hike post-ZLB) |
        | December 2016 | 0.75% | +25 bps |
        | March 2017 | 1.00% | +50 bps |
        | June 2017 | 1.25% | +75 bps |
        | December 2017 | 1.50% | +100 bps |
        | March 2018 | 1.75% | +125 bps |
        | June 2018 | 2.00% | +150 bps |
        | September 2018 | 2.25% | +175 bps |
        | December 2018 | 2.50% | +200 bps |

        **Portfolio Impact:**
        - Cost of funds increased by approximately 185 bps since December 2015 (including 150 bps spread)
        - Net interest margin compression: −42 bps YoY for credit card portfolio
        - Personal loan portfolio NIM relatively protected due to fixed-rate originations locked in 2015–2016
        - Mortgage refi activity down 38% YoY; purchase originations offsetting partially

        **Credit Quality Trends:**
        - 30+ DPD rate: 1.85% vs. 1.62% prior year — within acceptable range
        - Charge-off rate: 45 bps vs. 38 bps — slight deterioration in near-prime cohort
        - PD model PSI: 0.07 — stable population; no recalibration required

        ---

        ## 3. Policy Change Proposals & Votes

        ### Item 3.1: Credit Card FICO Floor — Raise from 640 to 660

        **Presenter:** Chief Credit Officer
        **Rationale:** Near-prime (FICO 640–659) cohort showing elevated charge-off rate of 285 bps
        (vs. 180 bps for prime 660+). In rising rate environment, near-prime borrowers' debt service
        capacity is more sensitive to rate increases. Raising floor will reduce portfolio vintage risk
        and improve NIM quality.

        **Projected Impact:**
        - Estimated 8–12% reduction in approval volume
        - Projected charge-off rate improvement: −35 bps over next 4 quarters
        - NIM improvement: +18 bps estimated (improved risk mix)

        **Vote:** 7 in favor, 1 abstention (Independent Director Tanaka — requested more granular
        demographic impact analysis before next meeting). **Motion carried.**

        **Effective Date:** January 1, 2019 (Version tag: `multi-v1-2019-cautious`)

        ### Item 3.2: Personal Loan FICO Floor — Raise from 600 to 620

        **Presenter:** Chief Credit Officer
        **Rationale:** Consistent with Item 3.1. PL near-prime (FICO 600–619) default rate reached
        4.2% annualized — above 3.5% underwriting assumption. DTI sensitivity analysis shows this
        cohort's debt service ratio has increased by 15% since 2016 due to rate hikes on variable-rate debt.

        **Vote:** Unanimous. **Motion carried.**

        **Effective Date:** January 1, 2019

        ### Item 3.3: APR Repricing — Personal Loans +50 bps Across All Tiers

        **Presenter:** Chief Financial Officer
        **Rationale:** Cost of funds has increased 200 bps since December 2015. Current spread
        compression requires rate action to maintain target NIM of 3.50%+.

        **Vote:** 6 in favor, 2 opposed (Independent Directors Kaminski and Tanaka cited consumer
        affordability concerns). **Motion carried by majority.**

        ---

        ## 4. Model Performance Update

        | Model | AUC | KS Statistic | PSI | Gini | Status |
        |---|---|---|---|---|---|
        | cc_pd_v1 | 0.811 | 49% | 0.06 | 0.622 | ✓ Stable |
        | pl_pd_v1 | 0.796 | 47% | 0.07 | 0.592 | ✓ Stable |
        | mortgage_pd_v1 | 0.773 | 45% | 0.05 | 0.546 | ✓ Stable |

        No models require immediate action. Annual validation reports submitted per SR 11-7.

        ---

        ## 5. Regulatory Horizon Items

        - **CECL (ASC 326):** Large institutions (SEC filers) mandatory adoption January 1, 2020.
          Implementation team on track. CECL provisioning expected to increase reserves by $45–60M.
        - **Basel III Endgame:** Monitoring Federal Reserve proposed rulemaking.
        - **S.2155 EGRRCPA:** Higher SIFI threshold confirmed — no change to our capital requirements.

        ---

        ## 6. Action Items

        | Action | Owner | Due Date |
        |---|---|---|
        | Implement FICO floor changes in decision engine | Technology | January 1, 2019 |
        | Adverse action notice updates for new decline reasons | Compliance | January 1, 2019 |
        | Dr. Tanaka demographic impact analysis | Chief Credit Officer | January 31, 2019 |
        | CECL parallel run — Q1 2019 | Finance / Model Risk | March 31, 2019 |
        | APR repricing disclosure updates | Compliance | January 1, 2019 |

        **Next Meeting:** March 31, 2019 (Q1 2019)

        ---

        *Minutes recorded by: Office of the Chief Credit Officer*
        *Minutes approved by: Credit Committee Chair (CRO)*
        *Board Resolution 2018-12 — FICO Floor and APR Policy Amendment*
        """)


def _extended_2020q1_minutes() -> str:
    return textwrap.dedent("""\
        ---
        doc_type: committee_minutes
        quarter: 2020-Q1
        meeting_date: 2020-03-31
        products_covered: [credit_card, personal_loan, mortgage]
        special_session: COVID-19 Emergency
        ---

        # SPECIAL EMERGENCY CREDIT COMMITTEE MEETING
        ## March 20, 2020 — COVID-19 Emergency Credit Policy Response

        **Date:** March 20, 2020 (Emergency Session — normally quarterly schedule)
        **Also:** Regular Q1 2020 minutes appended below (March 31, 2020)
        **Location:** Video Conference (all physical offices closed per COVID-19 protocols)
        **Meeting Called to Order:** 8:00 AM
        **Quorum:** Confirmed (8 of 8 voting members present via secure video)

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

        ## EMERGENCY SESSION — COVID-19 Credit Policy Response

        ### Background

        On March 11, 2020, the World Health Organization declared COVID-19 a global pandemic.
        The United States declared a national emergency on March 13, 2020. By March 20, 2020:
        - 12 states had issued shelter-in-place orders covering approximately 75M Americans
        - The Federal Reserve had cut the federal funds rate by 150 bps (to 0.25%) in two emergency actions
        - Unemployment claims were projected to spike from 3.5% to potentially 15–25%
        - Consumer credit demand was already showing stress signals in early March data

        The CEO called this emergency session to enact immediate credit policy changes to protect
        portfolio quality while also establishing forbearance infrastructure for existing borrowers.

        ---

        ## Emergency Resolution Items

        ### E-1: Immediate FICO Floor Tightening (Effective March 20, 2020)

        **Presenter:** Chief Credit Officer
        **Proposed Changes:**

        | Product | Current Floor | Proposed Floor | Change |
        |---|---|---|---|
        | Credit Card | 660 | 690 | +30 pts |
        | Personal Loan | 620 | 650 | +30 pts |
        | Mortgage (Conforming) | 680 | 700 | +20 pts |
        | Mortgage (FHA) | 580 | 600 | +20 pts |

        **Rationale:** Forward-looking unemployment scenarios project significant near-prime borrower
        stress within 60–90 days. FICO tightening is a leading indicator response — acting now will
        avoid materially adverse vintage quality for March–June 2020 originations.

        **Vote:** Unanimous. **Motion carried. Board Resolution 2020-03.**
        **Effective:** Immediately (March 20, 2020). Version tag: `multi-v1-2020q1-covid-tighten`.

        ### E-2: Jumbo Mortgage Originations — Immediate Suspension

        **Presenter:** Chief Risk Officer
        **Rationale:** Secondary market for jumbo mortgages has frozen. Spreads on jumbo RMBS widened
        to 350+ bps. We cannot hold a significant jumbo pipeline on balance sheet without secondary
        market execution risk. Suspension effective immediately pending secondary market normalization.

        **Additional conditions:**
        - Applications in process with rate locks: honor rate lock commitments, complete underwriting
        - Pipeline loans with rate locks expiring within 30 days: extend 30 days at no cost
        - New jumbo applications: decline with accommodation — refer to portfolio lenders

        **Vote:** Unanimous. **Motion carried. Board Resolution 2020-04.**
        **Effective:** March 20, 2020. Version tag: `multi-v1-2020q2-covid-hard` (effective April 1, 2020).

        ### E-3: Consumer Hardship Forbearance Program

        **Presenter:** Compliance Officer
        **Program Parameters:**
        - Eligibility: all existing borrowers experiencing COVID-19-related financial hardship
        - Documentation: self-attestation (no proof required per CARES Act guidance)
        - Duration: 3-month initial forbearance; renewable for 3 additional months
        - Payment treatment: deferred to end of loan term (no balloon payment surprise)
        - Credit reporting: per CARES Act §4021 — accounts current if in forbearance
        - Enrollment method: phone, online portal, mobile app

        **Staffing:** Hardship hotline activated with 150 additional agents (remote).
        Target handle time: <5 minutes from initial contact to enrollment.

        **Vote:** Unanimous. **Motion carried.**
        **Program Effective:** March 23, 2020.

        ### E-4: Income Verification Relief — Self-Employed Borrowers

        **Presenter:** Chief Credit Officer
        **Proposed:** Accept 3 months bank statements (rather than 2 years tax returns) for
        self-employed borrowers applying for personal loans or non-jumbo mortgages.
        Relief period: March 20 – September 30, 2020.

        **Compliance Note:** Modified standard is consistent with FHFA guidance on COVID-19 flexibilities.
        Income must still support DTI ≤38% using conservative assumptions.

        **Vote:** 7 in favor, 1 abstention (Director Kaminski — conflict of interest noted).
        **Motion carried.**

        ---

        ## Regular Q1 2020 Business (March 31, 2020)

        ### Prior Period Performance (Q4 2019)

        | Metric | Q4 2019 | Budget | Variance |
        |---|---|---|---|
        | Approval Rate | 28.1% | 29.5% | −1.4pp (rate environment tightening) |
        | 30+ DPD Rate | 1.72% | 1.80% | +8 bps favorable |
        | Net Charge-Off Rate | 49 bps | 50 bps | Flat |
        | Provision Expense | $38.0M | $40.0M | Under budget |

        **Discussion:** Q4 2019 performance was satisfactory. The March 2020 emergency actions
        will materially impact Q1 2020 metrics which will be presented at the next regular meeting.

        ### Regulatory Update

        - **CARES Act (March 27, 2020):** Key provisions: §4021 (credit reporting), §4022 (mortgage
          forbearance), §4023 (multifamily forbearance). Compliance team briefing scheduled March 30.
        - **Fed actions:** Fed Funds target 0.00–0.25%. IOER at 0.10%. QE unlimited — implications
          for mortgage rates (favorable for purchase demand once pandemic stabilizes).
        - **OCC/FDIC/Fed Joint Statement:** Encourages loan modifications; modified loans need not be
          classified as TDR if COVID-19-related.

        ---

        ## Action Items

        | Action | Owner | Due Date |
        |---|---|---|
        | Deploy FICO floor changes to decision engine | Technology | March 20, 2020 (DONE) |
        | Hardship hotline activation | Operations | March 23, 2020 |
        | CARES Act credit reporting compliance | Compliance | March 27, 2020 |
        | Q1 2020 provision — preliminary estimate | Finance | April 15, 2020 |
        | Jumbo pipeline letter to borrowers | Credit Ops | March 25, 2020 |
        | COVID CECL scenario analysis | Finance / Model Risk | April 30, 2020 |

        **Next Meeting:** June 30, 2020 (Q2 2020 Regular Session)

        ---

        *Minutes recorded by: Office of the Chief Credit Officer*
        *Board Resolution 2020-03 — COVID-19 Emergency Credit Policy*
        *Board Resolution 2020-04 — Jumbo Origination Suspension*
        """)


def _extended_2020q3_minutes() -> str:
    return textwrap.dedent("""\
        ---
        doc_type: committee_minutes
        quarter: 2020-Q3
        meeting_date: 2020-09-30
        products_covered: [credit_card, personal_loan, mortgage]
        ---

        # Credit Committee Meeting Minutes
        ## Q3 2020 — COVID Forbearance Program Status & CECL Impact

        **Date:** September 30, 2020
        **Location:** Video Conference
        **Meeting Called to Order:** 9:00 AM
        **Quorum:** Confirmed (7 of 8 voting members present)

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
        | Independent Director | Dr. Yuki Tanaka | — (medical leave) |

        ---

        ## 1. Approval of Prior Minutes

        Q2 2020 minutes (Emergency COVID session + regular) approved unanimously.

        ---

        ## 2. Forbearance Program Status Report

        **Presenter:** Chief Credit Officer

        ### Enrollment Summary (as of September 25, 2020)

        | Product | Active Forbearances | % of Portfolio | Avg Duration (months) | Expected Exit Date |
        |---|---|---|---|---|
        | Personal Loan | 24,180 | 11.9% | 4.2 | Q4 2020 – Q1 2021 |
        | Mortgage | 8,940 | 10.0% | 5.1 | Q1 – Q2 2021 |
        | Credit Card (payment plans) | 187,000 | 3.7% | 3.0 | Q4 2020 |

        **Key observations:**
        - Forbearance peak was June 2020 (12.4% of personal loan portfolio, 11.2% mortgage)
        - Roll-off is proceeding at approximately 3,200 accounts/month for PL
        - Re-default rate on exited forbearances: 18% (worse than modeled 12% — COVID scenario stress)
        - Delinquency suppression: true delinquency likely 200–250 bps higher than reported

        ### CARES Act Credit Reporting Compliance

        All 47,892 forbearance accounts correctly reported as current per CARES Act §4021.
        Compliance audit complete. No violations found.

        ---

        ## 3. CECL Stage Migration Analysis

        **Presenter:** Model Risk Officer / CFO

        The CECL provision at Q2 2020 was $109.5M (2.9× Q4 2019 baseline of $38.0M).
        This reflects the initial COVID shock provisioning. At Q3 2020, we present a reassessment.

        | Stage | Q4 2019 Balance | Q2 2020 Balance | Q3 2020 Balance | Change |
        |---|---|---|---|---|
        | Stage 1 (Current) | $4,240M | $3,890M | $3,950M | +1.5% QoQ |
        | Stage 2 (30–60 DPD + Forbearance) | $380M | $820M | $760M | −7.3% QoQ (forbearance exit) |
        | Stage 3 (90+, Default, CO) | $125M | $195M | $188M | −3.6% QoQ |

        **Provision at Q3 2020:** $88.0M (down from $109.5M — COVID provisioning partially releasing).
        Provision release of $21.5M subject to Board approval.

        **Vote on provision release:** 6 in favor, 1 opposed (CRO — prefers conservative posture).
        **Motion carried.** Provision release approved.

        ---

        ## 4. Modified Income Verification Standards — Extension Proposal

        **Presenter:** Chief Credit Officer
        **Proposal:** Extend COVID income verification relief (bank statements for self-employed)
        through December 31, 2020 (currently expires September 30, 2020).

        **Rationale:**
        - Economic recovery incomplete; unemployment at 8.4% (vs. 3.5% pre-COVID)
        - Self-employed sector disproportionately impacted; bank statements remain most reliable indicator
        - Denial rate for self-employed would spike ~40% without extension, risking ECOA disparate impact

        **Vote:** Unanimous. **Motion carried.**
        **Extension effective:** October 1 – December 31, 2020.

        ---

        ## 5. Policy Normalization Plan

        Target policy normalization trajectory presented by Chief Credit Officer:

        | Epoch | Planned Date | FICO Floor | Max DTI | Notes |
        |---|---|---|---|---|
        | Relief Phase | July 1, 2020 | 680/640/700 | 40%/42%/40% | ✓ In effect |
        | Stimulus Phase | January 1, 2021 | 660/620/680 | 45%/48%/43% | Pending |
        | Expansion Phase | July 1, 2021 | 640/600/660 | 47%/50%/43% | Pending |

        **Vote:** Approve normalization roadmap (informational — quarterly reviews required).
        **Vote:** Unanimous.

        ---

        ## 6. Model Performance & PSI Update

        | Model | AUC | KS | PSI | Finding |
        |---|---|---|---|---|
        | cc_pd_v1 | 0.808 | 49% | 0.14 | Elevated — employment status variable shifted |
        | pl_pd_v1 | 0.800 | 48% | 0.17 | Elevated — DTI distribution shifted due to forbearance |
        | mortgage_pd_v1 | 0.776 | 46% | 0.12 | Moderate — monitoring |

        **Finding:** PSI elevation driven by COVID-19 population composition shift, not model failure.
        Model Risk Officer recommends recalibration for 2021 vintages once population stabilizes.
        SR 11-7 annual validation to flag COVID overlay. **Noted.**

        ---

        ## 7. Regulatory Update

        - **CFPB COVID guidance:** Continued supervisory flexibility through December 2020.
        - **OCC TDR guidance:** Confirmed forbearance modifications need not be classified as TDR.
        - **State foreclosure moratoriums:** 22 states have active moratoriums; mortgage delinquency
          reporting must account for regulatory suppression when modeling losses.

        ---

        ## Action Items

        | Action | Owner | Due Date |
        |---|---|---|
        | Provision release documentation | Finance | October 15, 2020 |
        | Income verification extension deployment | Technology | October 1, 2020 |
        | Forbearance exit outreach campaign | Operations | October 1, 2020 |
        | CECL 2021 scenario refresh | Finance / Model Risk | December 31, 2020 |
        | Policy normalization plan — detailed roadmap | Chief Credit Officer | December 31, 2020 |

        **Next Meeting:** December 31, 2020 (Q4 2020)

        ---

        *Minutes recorded by: Office of the Chief Credit Officer*
        *Minutes approved by: Credit Committee Chair (CRO)*
        """)


def _extended_2022q2_minutes() -> str:
    return textwrap.dedent("""\
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
        """)


def generate_committee_minutes(root: Path = GOVERNANCE_ROOT) -> list[Path]:
    out_dir = root / "committee_minutes"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    extended = {
        (2018, 4): _extended_2018q4_minutes(),
        (2020, 1): _extended_2020q1_minutes(),
        (2020, 3): _extended_2020q3_minutes(),
        (2022, 2): _extended_2022q2_minutes(),
    }

    for yr in range(2015, 2026):
        for q in range(1, 5):
            fname = f"{yr}_Q{q}_credit_committee_minutes.md"
            path  = out_dir / fname
            key   = (yr, q)
            if key in extended:
                content = extended[key]
            else:
                content = _standard_minutes(yr, q)
            path.write_text(content, encoding="utf-8")
            written.append(path)
            log.info("Wrote %s", path)

    return written


# ===========================================================================
# 5.3  Model Validation Reports (12 files — 2015–2026)
# ===========================================================================

_MV_METRICS: dict[int, dict] = {
    2015: {"ks_cc":56, "ks_pl":54, "ks_mo":52, "auc_cc":0.832,"auc_pl":0.820,"auc_mo":0.798, "gini_cc":0.664,"gini_pl":0.640,"gini_mo":0.596, "psi_cc":0.04,"psi_pl":0.04,"psi_mo":0.03, "finding":"Low PSI across all models. Population stable in growth phase.",    "status":"Approved"},
    2016: {"ks_cc":57, "ks_pl":55, "ks_mo":53, "auc_cc":0.831,"auc_pl":0.819,"auc_mo":0.797, "gini_cc":0.662,"gini_pl":0.638,"gini_mo":0.594, "psi_cc":0.04,"psi_pl":0.04,"psi_mo":0.04, "finding":"All models performing within acceptable bounds. Vintage analysis stable.", "status":"Approved"},
    2017: {"ks_cc":56, "ks_pl":54, "ks_mo":51, "auc_cc":0.825,"auc_pl":0.813,"auc_mo":0.793, "gini_cc":0.650,"gini_pl":0.626,"gini_mo":0.586, "psi_cc":0.06,"psi_pl":0.06,"psi_mo":0.05, "finding":"PSI slightly elevated due to rate hike cycle — borrower DTI distribution shifting. Monitor.",  "status":"Approved"},
    2018: {"ks_cc":54, "ks_pl":52, "ks_mo":50, "auc_cc":0.820,"auc_pl":0.808,"auc_mo":0.789, "gini_cc":0.640,"gini_pl":0.616,"gini_mo":0.578, "psi_cc":0.07,"psi_pl":0.07,"psi_mo":0.06, "finding":"PSI within acceptable range. Rate hike impact incorporated in recalibration. FICO floor policy change reduces near-prime volume.", "status":"Approved"},
    2019: {"ks_cc":54, "ks_pl":52, "ks_mo":49, "auc_cc":0.818,"auc_pl":0.806,"auc_mo":0.786, "gini_cc":0.636,"gini_pl":0.612,"gini_mo":0.572, "psi_cc":0.06,"psi_pl":0.06,"psi_mo":0.05, "finding":"Late-cycle slowdown evident in DTI distribution. Models stable. No action required.",  "status":"Approved"},
    2020: {"ks_cc":51, "ks_pl":49, "ks_mo":47, "auc_cc":0.810,"auc_pl":0.800,"auc_mo":0.778, "gini_cc":0.620,"gini_pl":0.600,"gini_mo":0.556, "psi_cc":0.16,"psi_pl":0.18,"psi_mo":0.13, "finding":"COVID-19 population shift: employment status PSI elevated to 0.16–0.18. Significant. CECL overlay applied. Models approved with conditions pending 2021 recalibration.",  "status":"Approved with Conditions"},
    2021: {"ks_cc":52, "ks_pl":50, "ks_mo":48, "auc_cc":0.812,"auc_pl":0.802,"auc_mo":0.780, "gini_cc":0.624,"gini_pl":0.604,"gini_mo":0.560, "psi_cc":0.10,"psi_pl":0.11,"psi_mo":0.09, "finding":"Post-COVID population normalizing. PSI declining from 2020 peak. Recalibration complete for cc_pd_v1 and mortgage_pd_v1. pl_pd_v1 recalibration in progress.",  "status":"Approved"},
    2022: {"ks_cc":49, "ks_pl":47, "ks_mo":45, "auc_cc":0.803,"auc_pl":0.795,"auc_mo":0.773, "gini_cc":0.606,"gini_pl":0.590,"gini_mo":0.546, "psi_cc":0.22,"psi_pl":0.25,"psi_mo":0.21, "finding":"SIGNIFICANT: PSI > 0.20 on DTI characteristic across all models. Rate hike cycle driving unprecedented DTI distribution shift. Model recalibration initiated (target Q3 2023).",  "status":"Approved with Conditions"},
    2023: {"ks_cc":50, "ks_pl":49, "ks_mo":47, "auc_cc":0.808,"auc_pl":0.800,"auc_mo":0.778, "gini_cc":0.616,"gini_pl":0.600,"gini_mo":0.556, "psi_cc":0.08,"psi_pl":0.09,"psi_mo":0.07, "finding":"Recalibration complete for all three models (completed Q3 2023). PSI normalized. Models re-approved. SR 11-7 sign-off obtained.",  "status":"Approved"},
    2024: {"ks_cc":51, "ks_pl":50, "ks_mo":48, "auc_cc":0.812,"auc_pl":0.803,"auc_mo":0.781, "gini_cc":0.624,"gini_pl":0.606,"gini_mo":0.562, "psi_cc":0.07,"psi_pl":0.07,"psi_mo":0.06, "finding":"All models stable. Fed easing cycle beginning — monitoring rate-sensitive variables. No action required.",  "status":"Approved"},
    2025: {"ks_cc":52, "ks_pl":51, "ks_mo":49, "auc_cc":0.815,"auc_pl":0.806,"auc_mo":0.783, "gini_cc":0.630,"gini_pl":0.612,"gini_mo":0.566, "psi_cc":0.06,"psi_pl":0.06,"psi_mo":0.05, "finding":"Easing cycle improving borrower capacity metrics. FICO distribution shifting favorably. Models performing well.",  "status":"Approved"},
    2026: {"ks_cc":53, "ks_pl":52, "ks_mo":50, "auc_cc":0.818,"auc_pl":0.809,"auc_mo":0.787, "gini_cc":0.636,"gini_pl":0.618,"gini_mo":0.574, "psi_cc":0.05,"psi_pl":0.05,"psi_mo":0.04, "finding":"Models in excellent health. Expansion cycle improving population quality. No material findings.",  "status":"Approved"},
}


def generate_model_validation_reports(root: Path = GOVERNANCE_ROOT) -> list[Path]:
    out_dir = root / "model_validation"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for yr in range(2015, 2027):
        m = _MV_METRICS[yr]
        is_covid     = yr == 2020
        is_hike      = yr == 2022
        is_recalib   = yr == 2023
        psi_alert_cc = "⚠ **Alert** " if m["psi_cc"] > 0.20 else ""
        psi_alert_pl = "⚠ **Alert** " if m["psi_pl"] > 0.20 else ""
        psi_alert_mo = "⚠ **Alert** " if m["psi_mo"] > 0.20 else ""

        covid_note = ""
        if is_covid:
            covid_note = textwrap.dedent("""\
                ### COVID-19 Population Shift Analysis

                The 2020 validation period captures the most significant population composition
                shift in the models' history. COVID-19-related unemployment spike (3.5% → 14.7%
                between February and April 2020) created a bimodal employment distribution:
                employed (stable) vs. furloughed/unemployed (stressed). The employment status
                variable, historically a low-PSI characteristic, showed PSI of 0.16 (cc_pd_v1)
                and 0.18 (pl_pd_v1).

                **Recommendation:** Apply CECL overlay multiplier (2.5×) for Q2–Q3 2020 provisions.
                Recalibrate models using post-COVID population once stabilized (target Q3 2021).

                """)

        hike_note = ""
        if is_hike:
            hike_note = textwrap.dedent("""\
                ### Rate Hike Cycle — DTI Distribution Shift

                The Federal Reserve's 2022 rate hike cycle (+425 bps from March to December 2022)
                caused an unprecedented shift in the DTI characteristic distribution:
                - Average borrower DTI increased by 8.2 percentage points (variable-rate debt repricing)
                - DTI 40–50% band grew from 22% to 34% of applicants
                - DTI characteristic PSI: 0.25 (pl_pd_v1), 0.22 (cc_pd_v1), 0.21 (mortgage_pd_v1)

                All three values exceed the 0.20 investigation threshold per SR 11-7 guidelines.

                **Remediation Plan:**
                - Recalibrate pl_pd_v1 using Q3 2022 – Q2 2023 data window
                - Introduce rate-environment feature (Fed Funds rate) as external regressor
                - Target recalibration completion: Q3 2023

                """)

        recalib_note = ""
        if is_recalib:
            recalib_note = textwrap.dedent("""\
                ### Recalibration Completion (2022 → 2023)

                All three models were recalibrated using Q3 2022 – Q2 2023 data following the
                SR 11-7 findings from the 2022 validation cycle. Key changes:

                | Model | Change | PSI (post-recalibration) | AUC (post-recalibration) |
                |---|---|---|---|
                | cc_pd_v1 | DTI binning updated; rate environment feature added | 0.08 | 0.808 |
                | pl_pd_v1 | Full re-estimation on rate-hike vintage | 0.09 | 0.800 |
                | mortgage_pd_v1 | LTV-rate interaction term added | 0.07 | 0.778 |

                SR 11-7 sign-off obtained: October 2023. Models re-approved.

                """)

        content = textwrap.dedent(f"""\
            ---
            doc_type: model_validation
            report_year: {yr}
            models_validated: [cc_pd_v1, pl_pd_v1, mortgage_pd_v1]
            sr11_7_status: {m['status']}
            ---

            # Model Validation Report — {yr}

            **Validation Period:** January 1, {yr} – December 31, {yr}
            **Report Date:** February 28, {yr+1}
            **SR 11-7 Status:** {m['status']}
            **Prepared By:** Model Risk Management
            **Reviewed By:** Independent Model Validator (external)
            **Classification:** Internal — Model Risk Restricted

            ---

            ## 1. Models in Scope

            | Model ID | Version | Product | Model Type | Last Major Update |
            |---|---|---|---|---|
            | cc_pd_v1 | 1.{yr-2014}.0 | Credit Card | Logistic Regression + Gradient Boosting | {'Recalibrated Q3 2023' if yr >= 2023 else ('Recalibrated 2021' if yr == 2021 else 'Original 2015')} |
            | pl_pd_v1 | 1.{yr-2014}.0 | Personal Loan | Logistic Regression + Scorecard | {'Recalibrated Q3 2023' if yr >= 2023 else ('Recalibrated 2021' if yr == 2021 else 'Original 2015')} |
            | mortgage_pd_v1 | 1.{yr-2014}.0 | Mortgage | Logistic Regression + LTV Overlay | {'Recalibrated Q3 2023' if yr >= 2023 else ('Recalibrated 2021' if yr == 2021 else 'Original 2015')} |

            ---

            ## 2. Data Window

            | | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Observation window | Jan {yr}–Jun {yr} | Jan {yr}–Jun {yr} | Jan {yr}–Jun {yr} |
            | Outcome window | 12 months (Jun {yr+1}) | 12 months (Jun {yr+1}) | 12 months (Jun {yr+1}) |
            | N in-sample | {2400000 + yr*50000:,} | {185000 + yr*8000:,} | {52000 + yr*3000:,} |
            | N out-of-sample | {600000 + yr*12000:,} | {46000 + yr*2000:,} | {13000 + yr*750:,} |
            | Default rate (observed) | {0.028 + (0.004 if yr in (2020,2021) else 0) + (0.008 if yr==2022 else 0):.3f} | {0.032 + (0.005 if yr in (2020,2021) else 0) + (0.010 if yr==2022 else 0):.3f} | {0.018 + (0.003 if yr in (2020,2021) else 0) + (0.006 if yr==2022 else 0):.3f} |

            ---

            ## 3. Performance Metrics

            | Metric | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | KS Statistic | {m['ks_cc']}% | {m['ks_pl']}% | {m['ks_mo']}% |
            | Gini Coefficient | {m['gini_cc']:.3f} | {m['gini_pl']:.3f} | {m['gini_mo']:.3f} |
            | AUC-ROC | {m['auc_cc']:.3f} | {m['auc_pl']:.3f} | {m['auc_mo']:.3f} |
            | Brier Score | {0.18 + (yr-2015)*0.002:.3f} | {0.20 + (yr-2015)*0.002:.3f} | {0.16 + (yr-2015)*0.002:.3f} |
            | Log-Loss | {0.42 + (yr-2015)*0.005:.3f} | {0.45 + (yr-2015)*0.005:.3f} | {0.38 + (yr-2015)*0.005:.3f} |

            ---

            ## 4. Population Stability Index (PSI)

            | Characteristic | cc_pd_v1 | Threshold | pl_pd_v1 | Threshold | mortgage_pd_v1 | Threshold |
            |---|---|---|---|---|---|---|
            | FICO Score | {m['psi_cc']-0.01:.2f} | 0.20 | {m['psi_pl']-0.01:.2f} | 0.20 | {m['psi_mo']-0.01:.2f} | 0.20 |
            | DTI | {psi_alert_cc}{m['psi_cc']:.2f} | 0.20 | {psi_alert_pl}{m['psi_pl']:.2f} | 0.20 | {psi_alert_mo}{m['psi_mo']:.2f} | 0.20 |
            | Utilization | {m['psi_cc']-0.02:.2f} | 0.20 | — | — | — | — |
            | LTV | — | — | — | — | {m['psi_mo']-0.01:.2f} | 0.20 |
            | Employment Status | {m['psi_cc']-0.01:.2f} | 0.20 | {m['psi_pl']-0.01:.2f} | 0.20 | {m['psi_mo']-0.01:.2f} | 0.20 |

            ---

            ## 5. Characteristic Stability Analysis

            Population stability analysis across 4 key vintage cohorts ({yr-3}–{yr}):

            | Vintage | N | Default Rate | Avg FICO | Avg DTI | Notes |
            |---|---|---|---|---|---|
            | {yr-3} | {300000 + (yr-3)*5000:,} | {0.025 + (yr-3-2015)*0.001:.3f} | 695 | 32.4% | Baseline cohort |
            | {yr-2} | {320000 + (yr-2)*5000:,} | {0.027 + (yr-2-2015)*0.001:.3f} | 692 | 33.1% | Slight DTI increase |
            | {yr-1} | {340000 + (yr-1)*5000:,} | {0.029 + (yr-1-2015)*0.001:.3f} | 689 | 33.8% | {'Forbearance suppression' if yr-1 == 2020 else ('Rate hike impact' if yr-1 == 2022 else 'Normal variation')} |
            | {yr} | {360000 + yr*5000:,} | {0.031 + (yr-2015)*0.001:.3f} | 687 | 34.2% | Current validation cohort |

            ---

            ## 6. Outcome Analysis — Calibration

            | PD Decile | Predicted PD (avg) | Observed Default Rate | Ratio | Status |
            |---|---|---|---|---|
            | 1 (lowest risk) | 0.004 | {0.003 + (yr-2015)*0.0001:.4f} | 0.98 | ✓ Calibrated |
            | 2 | 0.008 | {0.007 + (yr-2015)*0.0001:.4f} | 0.95 | ✓ Calibrated |
            | 5 | 0.025 | {0.024 + (yr-2015)*0.0002:.4f} | 1.02 | ✓ Calibrated |
            | 8 | 0.065 | {0.063 + (yr-2015)*0.0003:.4f} | 0.98 | ✓ Calibrated |
            | 10 (highest risk) | 0.180 | {0.175 + (yr-2015)*0.001:.4f} | 1.04 | ✓ Calibrated |

            Hosmer-Lemeshow statistic: p-value = {0.42 - (yr-2015)*0.01:.2f} (χ² test, 10 groups). {'Pass' if 0.42 - (yr-2015)*0.01 > 0.05 else 'Borderline — monitor'}.

            ---

            {covid_note}{hike_note}{recalib_note}## 7. Findings

            | # | Severity | Finding | Model(s) Affected |
            |---|---|---|---|
            | 1 | {'Significant' if m['psi_pl'] > 0.20 or is_covid else 'Informational'} | {m['finding']} | {'All' if m['psi_pl'] > 0.20 or is_covid else 'pl_pd_v1'} |
            | 2 | Informational | Annual recalibration recommended per SR 11-7 best practices | All |
            {'| 3 | Significant | PSI > 0.20 on DTI characteristic — investigation required per SR 11-7 §4.3 | All |' if m['psi_pl'] > 0.20 else ''} |

            ---

            ## 8. Remediation Plan

            | Finding | Action | Responsible Party | Due Date | Status |
            |---|---|---|---|---|
            | {'PSI Elevation' if m['psi_pl'] > 0.15 else 'Annual Recalibration'} | {'Recalibrate models using post-shock population; add rate environment feature' if m['psi_pl'] > 0.15 else 'Schedule annual recalibration for next validation cycle'} | Model Risk + Data Science | {'Q3 ' + str(yr+1) if m['psi_pl'] > 0.15 else 'Q4 ' + str(yr+1)} | {'Complete' if yr == 2023 else 'In Progress' if m['psi_pl'] > 0.15 else 'Scheduled'} |
            | SR 11-7 Documentation Update | Update model inventory and validation documentation | Model Risk Officer | Q1 {yr+1} | {'Complete' if yr <= 2024 else 'In Progress'} |

            ---

            ## 9. SR 11-7 Status

            **Overall Status:** {m['status']}

            | Criteria | cc_pd_v1 | pl_pd_v1 | mortgage_pd_v1 |
            |---|---|---|---|
            | Conceptual Soundness | ✓ Pass | ✓ Pass | ✓ Pass |
            | Ongoing Monitoring | ✓ Pass | ✓ Pass | ✓ Pass |
            | Outcomes Analysis | ✓ Pass | ✓ Pass | ✓ Pass |
            | Documentation | ✓ Pass | ✓ Pass | ✓ Pass |
            | Compensating Controls | {'Required' if m['status'] != 'Approved' else 'N/A'} | {'Required' if m['status'] != 'Approved' else 'N/A'} | {'Required' if m['status'] != 'Approved' else 'N/A'} |

            **Sign-off:**
            - Model Risk Officer: Dr. Alejandro Ruiz — {m['status']}
            - Independent Validator: ExaminerCo LLC — {m['status']}
            - CRO: Dr. Priya Nambiar — {m['status']}

            ---

            *This report constitutes the annual model validation required by SR 11-7 and OCC Bulletin 2011-12.*
            *Retention: 7 years per examination record requirements.*
            """)

        path = out_dir / f"model_validation_{yr}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
        log.info("Wrote %s", path)

    return written


# ===========================================================================
# 5.4  Fair Lending Reports (12 files — 2015–2026)
# ===========================================================================

_FL_METRICS: dict[int, dict] = {
    2015: {"mo_apps":12800, "mo_orig":8960, "hmda_deny_rate":30.0, "air_hisp":0.88,"air_black":0.83,"air_female":0.94, "apr_diff_bps":8,  "finding":"No disparities. All AIR ≥0.80. APR difference within acceptable range.",           "cra":"none",    "covid_note":""},
    2016: {"mo_apps":15200, "mo_orig":10640,"hmda_deny_rate":30.0, "air_hisp":0.87,"air_black":0.82,"air_female":0.93, "apr_diff_bps":9,  "finding":"No disparities found.",                                                                    "cra":"none",    "covid_note":""},
    2017: {"mo_apps":18600, "mo_orig":13020,"hmda_deny_rate":30.0, "air_hisp":0.86,"air_black":0.81,"air_female":0.93, "apr_diff_bps":11, "finding":"No disparities. Minor APR variance on Hispanic segment — investigated, explained by FICO/LTV mix.", "cra":"none", "covid_note":""},
    2018: {"mo_apps":17400, "mo_orig":12180,"hmda_deny_rate":30.0, "air_hisp":0.85,"air_black":0.82,"air_female":0.92, "apr_diff_bps":12, "finding":"No disparities. AIR Black/African-American = 0.82 — within threshold but monitored.", "cra":"none", "covid_note":""},
    2019: {"mo_apps":22000, "mo_orig":15400,"hmda_deny_rate":30.0, "air_hisp":0.84,"air_black":0.81,"air_female":0.93, "apr_diff_bps":16, "finding":"MARGINAL FLAG: APR regression-adjusted spread of 16 bps for Black/African-American borrowers. Investigation initiated Q3 2019. Root cause: concentration in Near-Prime FICO tier (620–659) → higher pricing, not discriminatory intent. No systemic disparities. Enhanced monitoring implemented.", "cra":"monitor", "covid_note":""},
    2020: {"mo_apps":19800, "mo_orig":13860,"hmda_deny_rate":31.0, "air_hisp":0.86,"air_black":0.83,"air_female":0.94, "apr_diff_bps":10, "finding":"COVID-19 application volume down 10% YoY. Emergency FICO tightening applied equally across all groups. No systemic demographic disparities found. AIR improved vs. 2019 due to near-prime volume reduction (segment that previously showed marginally elevated APR disparity).", "cra":"none", "covid_note":"Application volume declined 10% due to COVID-19. Forbearance program available to all borrowers equally. CARES Act §4021 compliance confirmed."},
    2021: {"mo_apps":24500, "mo_orig":17150,"hmda_deny_rate":29.0, "air_hisp":0.87,"air_black":0.84,"air_female":0.94, "apr_diff_bps":9,  "finding":"No disparities. Post-COVID recovery — application volume up 24% YoY. Population mix normalizing. 2019 APR monitoring program closed — no recurrence.", "cra":"closed","covid_note":""},
    2022: {"mo_apps":12200, "mo_orig":8540, "hmda_deny_rate":41.0, "air_hisp":0.86,"air_black":0.83,"air_female":0.93, "apr_diff_bps":10, "finding":"Elevated denial rates across all demographic groups due to policy tightening (rate hike cycle). No demographic-specific disparities. AIR stable vs. prior year. Rate hike cycle creates affordability challenges equally across groups.", "cra":"none", "covid_note":""},
    2023: {"mo_apps":10800, "mo_orig":7560, "hmda_deny_rate":43.0, "air_hisp":0.85,"air_black":0.82,"air_female":0.93, "apr_diff_bps":11, "finding":"High-rate environment continues. No disparities. CRA assessment: satisfactory.",   "cra":"none",    "covid_note":""},
    2024: {"mo_apps":13500, "mo_orig":9450, "hmda_deny_rate":40.0, "air_hisp":0.86,"air_black":0.83,"air_female":0.94, "apr_diff_bps":10, "finding":"Fed easing cycle beginning. No disparities. Application volume recovering.",         "cra":"none",    "covid_note":""},
    2025: {"mo_apps":16200, "mo_orig":11340,"hmda_deny_rate":38.0, "air_hisp":0.87,"air_black":0.84,"air_female":0.94, "apr_diff_bps":9,  "finding":"No disparities. Easing cycle improving affordability across all groups.",            "cra":"none",    "covid_note":""},
    2026: {"mo_apps":18000, "mo_orig":12600,"hmda_deny_rate":35.0, "air_hisp":0.88,"air_black":0.85,"air_female":0.95, "apr_diff_bps":8,  "finding":"No disparities. Expansion cycle. AIR metrics at multi-year highs.",                  "cra":"none",    "covid_note":""},
}


def generate_fair_lending_reports(root: Path = GOVERNANCE_ROOT) -> list[Path]:
    out_dir = root / "fair_lending"
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for yr in range(2015, 2027):
        m = _FL_METRICS[yr]
        apr_flag = "⚠ **MARGINAL FLAG — Under Investigation**" if m["apr_diff_bps"] > 14 else "✓ Within threshold"
        air_flag_hisp  = "⚠ Monitor" if m["air_hisp"]  < 0.85 else "✓"
        air_flag_black = "⚠ Monitor" if m["air_black"] < 0.82 else "✓"

        covid_section = ""
        if m["covid_note"]:
            covid_section = f"\n### COVID-19 Impact Note\n\n{m['covid_note']}\n"

        monitor_section = ""
        if m["cra"] == "monitor":
            monitor_section = textwrap.dedent(f"""\
                ### APR Disparity Investigation — {yr}

                **Trigger:** Regression-adjusted APR difference of {m['apr_diff_bps']} bps for Black/African-American
                borrowers exceeded the 15 bps investigation threshold.

                **Methodology:** OLS regression controlling for FICO, DTI, LTV, loan amount, loan purpose,
                state, channel, and property type. Residual APR difference estimated at {m['apr_diff_bps']} bps
                (95% CI: 12–20 bps).

                **Root Cause Analysis:**
                - Channel concentration: Black/African-American borrowers over-represented in broker/partner channel
                  (+8 pp vs. white non-Hispanic) → broker commission adds ~12–18 bps to APR
                - FICO distribution: 28% of Black/AA applicants in Near-Prime tier (620–659) vs. 19% white non-Hispanic
                  → Near-Prime pricing adds 38 bps; after controlling for FICO, residual = 4 bps (non-significant)

                **Conclusion:** APR difference explained by legitimate, risk-related and channel factors.
                No disparate treatment. No remediation required. Enhanced monitoring implemented for 2020.

                **Corrective Actions:**
                1. Quarterly APR disparity report to Fair Lending Officer beginning Q1 {yr+1}
                2. Broker channel compensation review — ensure no discretionary points above schedule
                3. Near-Prime outreach program to improve FICO for returning applicants

                """)

        if m["cra"] == "closed":
            monitor_section = textwrap.dedent(f"""\
                ### 2019 APR Monitoring — Closed

                The enhanced APR monitoring program initiated in 2019 was closed in Q2 {yr} after
                4 consecutive quarters of no recurrence. Regression-adjusted APR difference for
                Black/African-American borrowers has normalized to {m['apr_diff_bps']} bps — below the
                15 bps threshold. Broker compensation review completed; no violations found.

                """)

        content = textwrap.dedent(f"""\
            ---
            doc_type: fair_lending
            report_year: {yr}
            products_covered: [credit_card, personal_loan, mortgage]
            hmda_reporting: true
            ---

            # Fair Lending Annual Report — {yr}

            **Report Period:** January 1, {yr} – December 31, {yr}
            **Report Date:** April 30, {yr+1}
            **Prepared By:** Fair Lending Officer
            **Reviewed By:** Compliance Officer, Chief Risk Officer
            **Classification:** Internal — Restricted; Regulator-ready upon request

            ---

            ## 1. HMDA LAR Summary (Mortgage — {yr})

            {covid_section}

            ### Application Volume by Action Taken

            | Action Taken | Count | Percentage |
            |---|---|---|
            | Loan Originated | {m['mo_orig']:,} | {m['mo_orig']/m['mo_apps']*100:.1f}% |
            | Approved, Not Accepted | {int(m['mo_apps']*0.04):,} | 4.0% |
            | Application Denied | {int(m['mo_apps']*m['hmda_deny_rate']/100):,} | {m['hmda_deny_rate']:.1f}% |
            | Application Withdrawn | {int(m['mo_apps']*0.08):,} | 8.0% |
            | File Closed Incomplete | {int(m['mo_apps']*0.02):,} | 2.0% |
            | **Total Applications** | **{m['mo_apps']:,}** | **100%** |

            ### Application Volume by Property Type

            | Property Type | Applications | Originated |
            |---|---|---|
            | Single-Family (1-4 unit) | {int(m['mo_apps']*0.72):,} | {int(m['mo_orig']*0.72):,} |
            | Multifamily (5+ units) | {int(m['mo_apps']*0.10):,} | {int(m['mo_orig']*0.08):,} |
            | Manufactured Home | {int(m['mo_apps']*0.08):,} | {int(m['mo_orig']*0.06):,} |
            | Condominium | {int(m['mo_apps']*0.10):,} | {int(m['mo_orig']*0.14):,} |

            ### Application Volume by Loan Purpose

            | Purpose | Applications | % |
            |---|---|---|
            | Home Purchase | {int(m['mo_apps']*0.58):,} | 58% |
            | Refinance | {int(m['mo_apps']*0.30):,} | 30% |
            | Cash-Out Refinance | {int(m['mo_apps']*0.12):,} | 12% |

            ---

            ## 2. Approval Rate Disparity Analysis

            **Methodology:** Raw approval rates compared by demographic group. Adverse Impact Ratio (AIR)
            = minority approval rate ÷ white non-Hispanic approval rate. AIR < 0.80 triggers investigation.

            | Demographic Group | Applications | Approvals | Approval Rate | AIR | Status |
            |---|---|---|---|---|---|
            | White Non-Hispanic (control) | {int(m['mo_apps']*0.62):,} | {int(m['mo_apps']*0.62*(1-m['hmda_deny_rate']/100)*1.05):,} | {(1-m['hmda_deny_rate']/100)*1.05*100:.1f}% | 1.000 | ✓ Control |
            | Hispanic | {int(m['mo_apps']*0.15):,} | {int(m['mo_apps']*0.15*(1-m['hmda_deny_rate']/100)*m['air_hisp']*1.05):,} | {(1-m['hmda_deny_rate']/100)*m['air_hisp']*1.05*100:.1f}% | {m['air_hisp']:.3f} | {air_flag_hisp} |
            | Black / African-American | {int(m['mo_apps']*0.12):,} | {int(m['mo_apps']*0.12*(1-m['hmda_deny_rate']/100)*m['air_black']*1.05):,} | {(1-m['hmda_deny_rate']/100)*m['air_black']*1.05*100:.1f}% | {m['air_black']:.3f} | {air_flag_black} |
            | Asian | {int(m['mo_apps']*0.08):,} | {int(m['mo_apps']*0.08*(1-m['hmda_deny_rate']/100)*0.97*1.05):,} | {(1-m['hmda_deny_rate']/100)*0.97*1.05*100:.1f}% | 0.970 | ✓ |
            | Female Applicant | {int(m['mo_apps']*0.45):,} | {int(m['mo_apps']*0.45*(1-m['hmda_deny_rate']/100)*m['air_female']*1.05):,} | {(1-m['hmda_deny_rate']/100)*m['air_female']*1.05*100:.1f}% | {m['air_female']:.3f} | ✓ |

            **Key Finding:** {'All AIR metrics ≥0.80 — no investigation threshold triggered.' if m['air_black'] >= 0.80 else 'Black/AA AIR = ' + str(m['air_black']) + ' — within threshold but monitored.'}

            ---

            ## 3. APR Pricing Disparity Analysis

            **Methodology:** Ordinary Least Squares regression controlling for FICO score, DTI,
            LTV ratio, loan amount (log), loan purpose (fixed effects), property type, state (fixed
            effects), and origination channel.

            ### Mortgage APR Disparity — Regression-Adjusted Results

            | Demographic Group | Unadjusted APR Diff (bps) | Regression-Adjusted Diff (bps) | Significance | Status |
            |---|---|---|---|---|
            | Hispanic | +{m['apr_diff_bps']+2} bps | +{m['apr_diff_bps']-2} bps | p = 0.{28+yr-2015} | {apr_flag if m['apr_diff_bps'] > 14 else '✓ Not significant'} |
            | Black / African-American | +{m['apr_diff_bps']+3} bps | +{m['apr_diff_bps']} bps | p = 0.{21+yr-2015} | {apr_flag} |
            | Female | +{m['apr_diff_bps']-3} bps | +{max(m['apr_diff_bps']-5, 2)} bps | p = 0.{38+yr-2015} | ✓ Not significant |

            **Threshold:** Investigation triggered if regression-adjusted spread > 15 bps (p < 0.05).
            **{yr} Status:** {'INVESTIGATION TRIGGERED — see Section 5.' if m['apr_diff_bps'] > 14 else 'No investigation threshold exceeded.'}

            ---

            ## 4. Statistical Methodology

            ### Regression Model

            **Dependent variable:** Note rate (APR) at origination
            **Independent variables:**
            - FICO score (continuous + squared term)
            - DTI ratio (continuous)
            - LTV at origination (continuous + interaction with loan purpose)
            - Loan amount (log-transformed)
            - Loan purpose (purchase / refi / cash-out — fixed effects)
            - Property type (fixed effects)
            - Channel (online / branch / partner / mobile — fixed effects)
            - State (fixed effects)
            - Origination month (year-quarter fixed effects)
            - Demographic group (indicator variables — coefficients of interest)

            **Redlining Analysis:** Geographic concentration analysis performed at census tract level.
            Proportion of applications in majority-minority tracts compared to market benchmarks
            using HMDA peer data. {'No redlining concerns identified.' if yr not in (2019,) else 'Tract-level analysis shows proportional coverage — no redlining concerns.'}

            **Intersectional Analysis:** Interaction terms tested for gender × race × income level.
            No significant intersectional disparities identified.

            ---

            ## 5. Disparate Impact Findings

            {monitor_section}**{yr} Overall Assessment:** {m['finding']}

            ---

            ## 6. Corrective Actions

            {'No corrective actions required. No disparities identified.' if m['cra'] == 'none' else ''}
            {'See Section 5 for investigation findings and resolution.' if m['cra'] == 'monitor' else ''}
            {'2019 enhanced monitoring program closed — no recurrence of APR disparity.' if m['cra'] == 'closed' else ''}

            ---

            ## 7. Fair Lending Officer Sign-off

            I certify that this Fair Lending Annual Report has been prepared in accordance with
            ECOA (Regulation B), the Fair Housing Act, HMDA (Regulation C), and the CFPB
            Examination Manual for Fair Lending.

            **Fair Lending Officer:** Patricia K. Owens
            **Date:** April 30, {yr+1}
            **CRO Review:** Dr. Priya Nambiar — Approved

            ---

            *This report is prepared for internal compliance purposes and is available to regulatory
            examiners upon request. Retention: 25 years (ECOA record retention requirement).*
            """)

        path = out_dir / f"fair_lending_{yr}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)
        log.info("Wrote %s", path)

    return written


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate governance documents (Phase 5)")
    parser.add_argument(
        "--section",
        choices=["policy_manuals", "committee_minutes", "model_validation", "fair_lending", "all"],
        default="all",
        help="Which section to generate",
    )
    parser.add_argument("--output-root", default=str(GOVERNANCE_ROOT), help="Root output directory")
    args = parser.parse_args()

    root = Path(args.output_root)
    sections = (
        ["policy_manuals", "committee_minutes", "model_validation", "fair_lending"]
        if args.section == "all"
        else [args.section]
    )

    total = 0
    for section in sections:
        if section == "policy_manuals":
            files = generate_policy_manuals(root)
        elif section == "committee_minutes":
            files = generate_committee_minutes(root)
        elif section == "model_validation":
            files = generate_model_validation_reports(root)
        else:
            files = generate_fair_lending_reports(root)
        total += len(files)
        log.info("Section %s: %d files written", section, len(files))

    print(f"\n{'='*60}")
    print(f"PHASE 5 GOVERNANCE DOCS COMPLETE")
    print(f"{'='*60}")
    print(f"  Output root:  {root}")
    print(f"  Total files:  {total}")
    print(f"\n  Breakdown:")
    for section in sections:
        sec_path = root / section
        n = len(list(sec_path.glob("*.md"))) if sec_path.exists() else 0
        print(f"    {section:30s} {n} files")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
