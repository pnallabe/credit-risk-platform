"""
compliance/plaid_policy_artifacts.py
======================================
Policy Artifact Generator — Plaid Data Tenant (PRD §4.2.1, §23.x)

Generates machine-readable and human-readable policy artifacts for the
``plaid_data`` tenant:

  1. JSON policy sheet per product  (artifacts/plaid_tenant/policy_{product}.json)
  2. Master policy manifest         (artifacts/plaid_tenant/policy_manifest.json)
  3. Markdown underwriting summary  (artifacts/plaid_tenant/underwriting_summary.md)
  4. Regulatory compliance checklist per product (JSON + Markdown)

Artifacts are written to ``<repo_root>/artifacts/plaid_tenant/`` and can be
served directly from the docs dashboard or exam-packet builder.

CLI usage:
    python -m compliance.plaid_policy_artifacts --out-dir artifacts/plaid_tenant

Programmatic usage:
    from compliance.plaid_policy_artifacts import generate_all_artifacts
    generate_all_artifacts(out_dir="artifacts/plaid_tenant")
"""

from __future__ import annotations

import argparse
import json
import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import — avoids circular at module load time
# ---------------------------------------------------------------------------

def _get_plaid_policies():
    from decision_engine.plaid_tenant_policies import plaid_tenant_policy_overrides
    return plaid_tenant_policy_overrides()


# ---------------------------------------------------------------------------
# Regulatory compliance checklist per product
# ---------------------------------------------------------------------------

REGULATORY_CHECKLISTS: Dict[str, List[Dict[str, str]]] = {
    "BNPL": [
        {"regulation": "TILA / Reg Z", "requirement": "Periodic statement disclosure", "status": "required"},
        {"regulation": "TILA / Reg Z", "requirement": "Dispute rights disclosed at account opening", "status": "required"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action notice within 30 days", "status": "required"},
        {"regulation": "FCRA", "requirement": "Permissible purpose documented (underwriting)", "status": "required"},
        {"regulation": "FCRA", "requirement": "Plaid OAuth consent logged as FCRA authorisation", "status": "required"},
        {"regulation": "CFPB 2024", "requirement": "BNPL treated as open-end credit under TILA", "status": "required"},
        {"regulation": "UDAAP", "requirement": "Fee disclosure in plain language", "status": "required"},
    ],
    "PERSONAL_LOAN": [
        {"regulation": "TILA / Reg Z", "requirement": "APR, finance charge, and payment schedule disclosed", "status": "required"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action notice — cite Plaid data attributes if dispositive", "status": "required"},
        {"regulation": "FCRA", "requirement": "Plaid data accessed under §604(a)(3)(A) permissible purpose", "status": "required"},
        {"regulation": "MLA", "requirement": "MAPR ≤ 36% for covered borrowers; MLA screening at origination", "status": "required"},
        {"regulation": "Reg B", "requirement": "Monitoring data (HMDA gender/ethnicity) not used in decisioning", "status": "required"},
        {"regulation": "UDAAP", "requirement": "Plaid income estimate gap > 30% triggers manual review, not auto-reject", "status": "required"},
    ],
    "SMB_SECURED_LOAN": [
        {"regulation": "ECOA / Reg B", "requirement": "Business credit adverse action within 30 days", "status": "required"},
        {"regulation": "CRA", "requirement": "Small business loan reported to community reinvestment record", "status": "required"},
        {"regulation": "UCC-1", "requirement": "Fixture filing for collateral within 5 business days of close", "status": "required"},
        {"regulation": "SBA", "requirement": "SBA 7(a) eligibility check for loans ≤ $5M", "status": "conditional"},
        {"regulation": "FCRA", "requirement": "Business Plaid account OAuth by authorized signer logged", "status": "required"},
        {"regulation": "BSA/AML", "requirement": "FinCEN beneficial ownership CDD for entities ≥ 25% ownership", "status": "required"},
    ],
    "CREDIT_CARD": [
        {"regulation": "CARD Act", "requirement": "45-day notice before APR increases; ability-to-pay assessment", "status": "required"},
        {"regulation": "TILA / Reg Z", "requirement": "Schumer Box disclosure at application", "status": "required"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action citing Plaid data if used in decision", "status": "required"},
        {"regulation": "FCRA", "requirement": "Plaid supplemental data disclosed in adverse action", "status": "required"},
    ],
    "CREDIT_BUILDER": [
        {"regulation": "TILA / Reg Z", "requirement": "Installment loan disclosures (APR, schedule, total of payments)", "status": "required"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action if denied (Plaid bank age / NSF cited)", "status": "required"},
        {"regulation": "CFPB 2020", "requirement": "Loan proceeds held in savings account until paid off", "status": "required"},
        {"regulation": "FCRA", "requirement": "Report payment history to ≥ 1 bureau after 6 months", "status": "required"},
    ],
    "OVERDRAFT_CASH_ADVANCE": [
        {"regulation": "TILA / Reg Z", "requirement": "Systematic overdraft = credit if fee-based; disclose APR equivalent", "status": "required"},
        {"regulation": "CFPB 2024", "requirement": "Fee-based overdraft capped at cost or $5 per CFPB overdraft rule", "status": "required"},
        {"regulation": "UDAAP", "requirement": "Real-time balance check must be disclosed in account agreement", "status": "required"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action if declined for cash advance", "status": "required"},
    ],
    "AUTO_LOAN": [
        {"regulation": "TILA / Reg Z", "requirement": "Finance charge, APR, and payment schedule disclosed", "status": "required"},
        {"regulation": "FTC Holder Rule", "requirement": "FTC notice in dealer-originated contracts", "status": "conditional"},
        {"regulation": "ECOA / Reg B", "requirement": "Adverse action if declined", "status": "required"},
        {"regulation": "State Lemon Law", "requirement": "State-specific lemon law compliance per origination state", "status": "required"},
    ],
    "MORTGAGE": [
        {"regulation": "TRID", "requirement": "Loan Estimate within 3 business days of application", "status": "required"},
        {"regulation": "TRID", "requirement": "Closing Disclosure ≥ 3 business days before closing", "status": "required"},
        {"regulation": "QM / ATR", "requirement": "Ability-to-Repay documentation; QM safe harbor if qualifying", "status": "required"},
        {"regulation": "HMDA", "requirement": "HMDA LAR filing for covered institutions", "status": "conditional"},
        {"regulation": "RESPA", "requirement": "GFE / CFPB TRID replaces legacy GFE", "status": "required"},
        {"regulation": "HOEPA", "requirement": "High-cost mortgage triggers at APR + 1.5pp over APOR (1st lien)", "status": "required"},
        {"regulation": "CRA", "requirement": "Mortgage origination tracked for CRA assessment area", "status": "required"},
    ],
    "SMALL_BUSINESS_LOAN": [
        {"regulation": "ECOA / Reg B", "requirement": "Business credit adverse action within 30 days", "status": "required"},
        {"regulation": "CRA", "requirement": "Small business reporting", "status": "required"},
        {"regulation": "BSA/AML", "requirement": "FinCEN CDD / beneficial ownership verification", "status": "required"},
    ],
}

# Plaid-specific FCRA / data governance entries appended to every product
_PLAID_COMMON_CHECKS: List[Dict[str, str]] = [
    {"regulation": "FCRA §604", "requirement": "Permissible purpose (underwriting) documented per transaction", "status": "required"},
    {"regulation": "FCRA §615", "requirement": "Adverse action notice identifies Plaid as data source and provides contact details", "status": "required"},
    {"regulation": "Plaid ToS", "requirement": "End-user OAuth consent captured via Plaid Link; consent record retained 7 years", "status": "required"},
    {"regulation": "CCPA / CPRA", "requirement": "Plaid bank data included in data-subject access and erasure workflows", "status": "required"},
    {"regulation": "SOC 2 Type II", "requirement": "Plaid API credentials stored in secrets manager; not in code or config files", "status": "required"},
]


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------


def _policy_to_dict(policy) -> Dict[str, Any]:
    """Convert ProductPolicy dataclass to a serialisable dict."""
    import dataclasses
    return dataclasses.asdict(policy)


def _generate_product_json(product_type: str, policy, out_dir: Path) -> Path:
    checklist = REGULATORY_CHECKLISTS.get(product_type, []) + _PLAID_COMMON_CHECKS
    artifact = {
        "tenant_id": "plaid_data",
        "product_type": product_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": "v1",
        "policy_parameters": _policy_to_dict(policy),
        "regulatory_compliance_checklist": checklist,
        "underwriting_data_sources": {
            "primary": "Plaid (bank account cash-flow)",
            "secondary": "Credit bureau (Experian / Equifax / TransUnion)",
            "tertiary": "Alt-data (rent, utilities, mobile via ingestion-api)",
        },
        "plaid_features_used": [
            f for f in (policy.required_features or [])
            if any(kw in f for kw in ["plaid", "cash_flow", "nsf", "overdraft",
                                       "bank_account", "monthly_inflow", "monthly_outflow",
                                       "net_monthly", "savings_balance", "income_source",
                                       "income_volatility", "recurring_expense"])
        ],
    }
    out_path = out_dir / f"policy_{product_type.lower()}.json"
    out_path.write_text(json.dumps(artifact, indent=2, default=str))
    logger.info("Written %s", out_path)
    return out_path


def _generate_manifest(policies, artifact_paths: List[Path], out_dir: Path) -> Path:
    manifest = {
        "tenant_id": "plaid_data",
        "tenant_name": "Plaid Data Open-Banking Tenant",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": "v1",
        "products": list(policies.keys()),
        "artifacts": [str(p.name) for p in artifact_paths],
        "wave_map": {
            "Wave 1 (Weeks 1-5)": ["BNPL", "PERSONAL_LOAN", "SMB_SECURED_LOAN"],
            "Wave 2 (Weeks 6-9)": ["CREDIT_CARD", "CREDIT_BUILDER", "OVERDRAFT_CASH_ADVANCE"],
            "Wave 3 (Weeks 10-12)": ["AUTO_LOAN", "SMALL_BUSINESS_LOAN"],
            "Wave 4 (Post-launch)": ["MORTGAGE"],
        },
        "plaid_integration": {
            "connector": "ingestion-api/src/plaid_connector.py",
            "env_vars": ["PLAID_CLIENT_ID", "PLAID_SECRET", "PLAID_ENV"],
            "bank_lookback_days": 90,
            "income_product_enabled": True,
        },
    }
    out_path = out_dir / "policy_manifest.json"
    out_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Written manifest: %s", out_path)
    return out_path


def _generate_markdown_summary(policies, out_dir: Path) -> Path:
    lines: List[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines += [
        "# Plaid Data Tenant — Underwriting Policy Summary",
        "",
        f"*Generated: {now}  |  Tenant: `plaid_data`  |  Policy Version: v1*",
        "",
        "## Overview",
        "",
        textwrap.dedent("""\
            The `plaid_data` tenant uses Plaid Open-Banking data as the primary
            underwriting signal.  Bureau scores are supplemental (or optional for
            thin-file applicants).  All PD thresholds are calibrated against
            Plaid cash-flow features: `cash_flow_stability_score`, `nsf_count_90d`,
            `avg_monthly_inflow`, and `plaid_income_estimate`.
        """),
        "## Product Policy Parameters",
        "",
        "| Product | Approve PD ≤ | Refer PD ≤ | Max DTI | Loan Range (USD) | Base APR | Max APR |",
        "|---------|-------------|-----------|---------|-----------------|---------|--------|",
    ]

    for pt, pol in policies.items():
        lines.append(
            f"| {pt} | {pol.pd_threshold_approve:.0%} | {pol.pd_threshold_refer:.0%}"
            f" | {pol.max_dti:.0%}"
            f" | ${pol.min_loan_amount_usd:,.0f} – ${pol.max_loan_amount_usd:,.0f}"
            f" | {pol.base_apr:.2f}% | {pol.max_apr:.2f}% |"
        )

    lines += [
        "",
        "## Plaid Cash-Flow PD Threshold Adjustments",
        "",
        "| Cash Flow Stability | NSF Events (90d) | PD Threshold Multiplier |",
        "|---------------------|-----------------|------------------------|",
        "| ≥ 0.70 | 0 | ×1.20 (relax 20%) |",
        "| ≥ 0.50 | ≤ 1 | ×1.10 (relax 10%) |",
        "| any | 3–4 | ×0.85 (tighten 15%) |",
        "| any | ≥ 5 | ×0.80 (tighten 20%) |",
        "| < 0.20 | any | ×0.80 (tighten 20%) |",
        "",
        "## Plaid Bank-Data Features Used",
        "",
        "| Feature | Description | Products |",
        "|---------|-------------|---------|",
        "| `avg_monthly_inflow` | Rolling 90-day avg monthly deposits | All |",
        "| `net_monthly_cash_flow` | Inflow − outflow | All |",
        "| `cash_flow_stability_score` | CoV of monthly income (0–1, higher=stable) | All |",
        "| `nsf_count_90d` | Non-sufficient-fund events (90 days) | All |",
        "| `overdraft_count_90d` | Overdraft events (90 days) | Overdraft, Personal |",
        "| `bank_account_age_months` | Age of oldest linked account | All |",
        "| `plaid_income_estimate` | Plaid Income annualised estimate | Personal, SMB, Card |",
        "| `income_source_count` | Distinct payroll / deposit sources | Personal, SMB |",
        "| `savings_balance` | Current savings/checking snapshot | Card, Overdraft |",
        "| `recurring_expense_ratio` | Fixed expenses / total outflow | Credit Builder |",
        "",
        "## Wave Delivery Map",
        "",
        "| Wave | Products | Timeline |",
        "|------|----------|----------|",
        "| Wave 1 | BNPL, Personal Loan, SMB Secured Loan | Weeks 1–5 |",
        "| Wave 2 | Credit Card, Credit Builder, Overdraft/Cash Advance | Weeks 6–9 |",
        "| Wave 3 | Auto Loan, Small Business Loan | Weeks 10–12 |",
        "| Wave 4 | Mortgage | Post-launch |",
        "",
        "## Regulatory Compliance Summary",
        "",
        "| Regulation | Applies To | Key Requirement |",
        "|------------|-----------|----------------|",
        "| TILA / Reg Z | All products | APR, finance charge, payment schedule disclosed |",
        "| ECOA / Reg B | All products | Adverse action citing Plaid data attributes |",
        "| FCRA §604 | All products | Permissible purpose documented per transaction |",
        "| FCRA §615 | All products | Plaid identified as data source in adverse action |",
        "| CFPB 2024 | BNPL, Overdraft | BNPL = open-end credit; overdraft fee cap |",
        "| MLA | Personal Loan | MAPR ≤ 36% for covered borrowers |",
        "| CARD Act | Credit Card | 45-day APR notice; ability-to-pay |",
        "| CRA | SMB, Mortgage | Community reinvestment tracking |",
        "| BSA/AML | SMB, SBL | FinCEN beneficial ownership CDD |",
        "| TRID | Mortgage | Loan Estimate + Closing Disclosure timing |",
        "| Plaid ToS | All products | OAuth consent via Plaid Link; retained 7 years |",
        "| CCPA/CPRA | All products | Plaid data in erasure and DSAR workflows |",
        "",
        "---",
        "*See individual product JSON artifacts in this directory for full parameter listings.*",
    ]

    out_path = out_dir / "underwriting_summary.md"
    out_path.write_text("\n".join(lines))
    logger.info("Written markdown summary: %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def generate_all_artifacts(out_dir: str | Path = "artifacts/plaid_tenant") -> Dict[str, Path]:
    """Generate all Plaid tenant policy artifacts.

    Returns:
        dict mapping artifact name → Path.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    policies = _get_plaid_policies()
    artifact_paths: List[Path] = []
    output: Dict[str, Path] = {}

    for product_type, policy in policies.items():
        p = _generate_product_json(product_type, policy, out)
        artifact_paths.append(p)
        output[f"policy_{product_type.lower()}"] = p

    manifest_path = _generate_manifest(policies, artifact_paths, out)
    output["manifest"] = manifest_path

    summary_path = _generate_markdown_summary(policies, out)
    output["underwriting_summary"] = summary_path

    logger.info("All artifacts written to %s", out)
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Generate Plaid tenant policy artifacts")
    parser.add_argument("--out-dir", default="artifacts/plaid_tenant",
                        help="Output directory (default: artifacts/plaid_tenant)")
    args = parser.parse_args()
    generate_all_artifacts(out_dir=args.out_dir)
