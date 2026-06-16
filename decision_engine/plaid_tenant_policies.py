"""
decision_engine/plaid_tenant_policies.py
=========================================
Plaid Data Tenant — Product Policy Overrides (PRD §4.2.1, §4.2.2)

When the tenant uses Plaid as the primary bank-data connector, underwriting
can rely on real-time cash-flow signals in addition to (or in lieu of)
traditional bureau attributes.  This module defines:

  1. Plaid-specific feature requirements per product (bank-data enriched).
  2. Tighter-than-default approval thresholds where Plaid data reduces
     uncertainty, and relaxed guardrails for thin-file applicants who have
     strong cash-flow signals.
  3. A ``plaid_tenant_policy_overrides()`` function that returns a dict of
     ProductPolicy overrides ready to be registered into the Config Registry.
  4. A ``apply_plaid_overrides(base_policy, tenant_config)`` helper used by
     the decision engine at runtime to merge tenant overrides.

Plaid Bank-Data Features Referenced
--------------------------------------
These features are produced by ingestion-api/src/plaid_connector.py and
normalized into the canonical feature matrix by credit_core/features.py:

  avg_monthly_inflow          – rolling 90-day average monthly deposits (USD)
  avg_monthly_outflow         – rolling 90-day average monthly debits (USD)
  net_monthly_cash_flow       – avg_monthly_inflow - avg_monthly_outflow
  cash_flow_stability_score   – coefficient of variation of monthly inflows (0-1,
                                 higher = more stable)
  income_source_count         – distinct payroll/deposit source count
  income_volatility           – std_dev(monthly_income) / mean(monthly_income)
  bank_account_age_months     – age of oldest linked account
  nsf_count_90d               – non-sufficient-fund events (last 90 days)
  overdraft_count_90d         – overdraft events (last 90 days)
  savings_balance             – current savings/checking balance snapshot
  recurring_expense_ratio     – recurring fixed expenses / total outflow
  plaid_income_estimate       – Plaid Income product annualised income estimate

Adjustment Logic
----------------
For applicants with strong Plaid signals (cash_flow_stability_score ≥ 0.7,
nsf_count_90d == 0), approval PD thresholds are relaxed by up to 20% to
extend credit to thin-bureau but cash-flow-healthy applicants.

For applicants with weak Plaid signals (nsf_count_90d ≥ 3 or
cash_flow_stability_score < 0.3), thresholds are tightened by 15%.
"""

from __future__ import annotations

import copy
import dataclasses
import logging
from typing import Any, Dict, List, Optional

from decision_engine.product_policies import (
    ALL_PRODUCT_TYPES,
    ProductPolicy,
    ProductType,
    _DEFAULT_POLICIES,
)

logger = logging.getLogger(__name__)

PLAID_TENANT_ID = "plaid_data"

# ---------------------------------------------------------------------------
# Plaid-specific feature requirements appended to each product
# ---------------------------------------------------------------------------

_PLAID_BASE_FEATURES = [
    "avg_monthly_inflow",
    "avg_monthly_outflow",
    "net_monthly_cash_flow",
    "cash_flow_stability_score",
    "nsf_count_90d",
    "bank_account_age_months",
]

_PLAID_EXTENDED_FEATURES = _PLAID_BASE_FEATURES + [
    "income_source_count",
    "income_volatility",
    "savings_balance",
    "plaid_income_estimate",
]

# ---------------------------------------------------------------------------
# Per-product Plaid overrides
# (only fields that differ from defaults are specified)
# ---------------------------------------------------------------------------

# Keys mirror ProductPolicy field names.  Missing keys mean "keep default".
_PLAID_PRODUCT_OVERRIDES: Dict[ProductType, Dict[str, Any]] = {
    # ------------------------------------------------------------------
    # BNPL — primary Wave 1 product, Plaid enables thin-file approvals
    # ------------------------------------------------------------------
    "BNPL": {
        "pd_threshold_approve": 0.10,   # relaxed (+25%) — strong cash flow reduces bureau reliance
        "pd_threshold_refer": 0.18,
        "fraud_reject_threshold": 0.70,
        "fraud_review_threshold": 0.45,
        "max_dti": 0.70,                # bank-verified income reduces need for tight DTI gate
        "min_open_accounts": 0,
        "max_loan_amount_usd": 7_500.0, # raised ceiling given income verification
        "base_apr": 0.0,
        "max_apr": 36.0,
        "required_features": [
            "payment_history",
            "avg_monthly_inflow",
            "net_monthly_cash_flow",
            "cash_flow_stability_score",
            "nsf_count_90d",
            "bank_account_age_months",
        ],
        "extra_rules": [
            "max_concurrent_bnpl_plans_4",
            "merchant_category_check",
            "plaid_nsf_gate_3",         # reject if nsf_count_90d >= 3
            "plaid_min_inflow_200",     # require avg_monthly_inflow >= 200 USD
        ],
        "description": (
            "BNPL installment plan — Plaid-data tenant.  "
            "Bureau score de-emphasised; cash-flow stability is primary underwriting signal."
        ),
        "regulatory_notes": (
            "CFPB 2024 interpretive rule: BNPL = credit card under TILA. "
            "Plaid income data must satisfy FCRA permissible purpose "
            "(underwriting) with applicant consent (Plaid Link OAuth). "
            "Adverse action must cite specific data attributes per ECOA Reg B §202.9."
        ),
    },

    # ------------------------------------------------------------------
    # PERSONAL_LOAN — Wave 1 product, Plaid income replaces pay stubs
    # ------------------------------------------------------------------
    "PERSONAL_LOAN": {
        "pd_threshold_approve": 0.07,   # slightly relaxed — income verified via Plaid
        "pd_threshold_refer": 0.14,
        "fraud_reject_threshold": 0.60,
        "fraud_review_threshold": 0.32,
        "max_dti": 0.55,
        "min_open_accounts": 0,         # Plaid bank data substitutes for tradeline requirement
        "min_loan_amount_usd": 500.0,
        "max_loan_amount_usd": 75_000.0,
        "base_apr": 9.99,
        "max_apr": 36.0,
        "required_features": _PLAID_EXTENDED_FEATURES + [
            "credit_score",
            "debt_to_income",
            "annual_income",
        ],
        "extra_rules": [
            "income_verification_required",
            "plaid_income_estimate_consistency_check",  # plaid_income vs stated income < 30% gap
            "plaid_nsf_gate_3",
            "plaid_bank_age_min_3_months",
            "plaid_min_net_cashflow_positive",
        ],
        "description": (
            "Unsecured personal installment loan — Plaid-data tenant.  "
            "Plaid Income estimate replaces manual pay-stub income verification."
        ),
        "regulatory_notes": (
            "TILA Reg Z, ECOA Reg B, FCRA. "
            "Plaid data accessed under FCRA §604(a)(3)(A) permissible purpose. "
            "MLA ≤36% MAPR for covered borrowers. "
            "Plaid account linking consent logged as FCRA authorization record."
        ),
    },

    # ------------------------------------------------------------------
    # SMB_SECURED_LOAN — Wave 1, DSCR driven by Plaid cash-flow
    # ------------------------------------------------------------------
    "SMB_SECURED_LOAN": {
        "pd_threshold_approve": 0.09,
        "pd_threshold_refer": 0.17,
        "fraud_reject_threshold": 0.55,
        "fraud_review_threshold": 0.28,
        "max_dti": 0.65,
        "min_open_accounts": 0,
        "min_loan_amount_usd": 5_000.0,
        "max_loan_amount_usd": 500_000.0,
        "base_apr": 8.50,
        "max_apr": 35.0,
        "required_features": _PLAID_BASE_FEATURES + [
            "annual_revenue",
            "years_in_business",
            "debt_service_coverage_ratio",
            "business_type",
            "collateral_value_usd",
            "collateral_type",
            "plaid_income_estimate",
            "income_source_count",
        ],
        "extra_rules": [
            "years_in_business_min_1",
            "dscr_min_1_20",            # slightly relaxed vs 1.25 default — Plaid DSCR is real-time
            "personal_guarantee_required_under_250k",
            "cra_small_business_tracking",
            "collateral_lien_search_required",
            "plaid_business_revenue_min_3_months",
            "plaid_nsf_gate_2",         # stricter for SMB — 2 NSF events trigger review
        ],
        "description": (
            "SMB secured term loan — Plaid-data tenant.  "
            "Business cash-flow from Plaid replaces 2-year tax return requirement "
            "for companies < 24 months operating history."
        ),
        "regulatory_notes": (
            "ECOA Reg B (business credit). CRA small-business reporting. "
            "UCC-1 fixture filing required for collateral. "
            "Plaid business account access requires separate OAuth consent from "
            "authorized signer (controller). "
            "SBA 7(a) eligibility check if loan ≤ $5M."
        ),
    },

    # ------------------------------------------------------------------
    # CREDIT_CARD — Wave 2, cash-flow supplements bureau score
    # ------------------------------------------------------------------
    "CREDIT_CARD": {
        "pd_threshold_approve": 0.06,
        "pd_threshold_refer": 0.12,
        "fraud_reject_threshold": 0.65,
        "fraud_review_threshold": 0.38,
        "max_dti": 0.48,
        "min_open_accounts": 0,         # Plaid bank data replaces tradeline minimum
        "max_loan_amount_usd": 40_000.0,
        "base_apr": 14.99,
        "max_apr": 29.99,
        "required_features": _PLAID_BASE_FEATURES + [
            "credit_score",
            "debt_to_income",
            "num_open_accounts",
        ],
        "extra_rules": [
            "revolving_utilization_check",
            "min_credit_age_6_months",
            "plaid_nsf_gate_3",
            "plaid_savings_balance_min_100",
            "plaid_min_net_cashflow_positive",
        ],
        "description": "Revolving credit card — Plaid-data tenant.",
        "regulatory_notes": (
            "CARD Act, TILA Reg Z. "
            "Plaid data used as supplemental underwriting signal under FCRA. "
            "Adverse action reason codes must reference Plaid data attributes where dispositive."
        ),
    },

    # ------------------------------------------------------------------
    # CREDIT_BUILDER — Wave 2, almost entirely cash-flow underwritten
    # ------------------------------------------------------------------
    "CREDIT_BUILDER": {
        "pd_threshold_approve": 0.15,   # very relaxed — product designed for high-risk thin files
        "pd_threshold_refer": 0.25,
        "fraud_reject_threshold": 0.80,
        "fraud_review_threshold": 0.55,
        "max_dti": 0.80,
        "min_open_accounts": 0,
        "min_loan_amount_usd": 300.0,
        "max_loan_amount_usd": 2_500.0,
        "base_apr": 0.0,               # fee-based product, not APR-based
        "max_apr": 36.0,
        "required_features": _PLAID_BASE_FEATURES + [
            "bank_account_age_months",
        ],
        "extra_rules": [
            "plaid_nsf_gate_5",                         # more lenient — building credit
            "plaid_bank_age_min_1_month",
            "plaid_min_inflow_100",
            "plaid_recurring_expense_ratio_max_90pct",  # ensure some free cash
        ],
        "description": (
            "Credit-builder / secured installment loan — Plaid-data tenant.  "
            "Bureau score NOT required; Plaid bank signals are the sole underwriting basis."
        ),
        "regulatory_notes": (
            "TILA Reg Z disclosures required (installment structure). "
            "ECOA Reg B adverse action if denied. "
            "CFPB credit-builder account guidance (2020): "
            "loan proceeds held in savings account until paid off."
        ),
    },

    # ------------------------------------------------------------------
    # OVERDRAFT_CASH_ADVANCE — Wave 2, near-real-time Plaid balance check
    # ------------------------------------------------------------------
    "OVERDRAFT_CASH_ADVANCE": {
        "pd_threshold_approve": 0.12,
        "pd_threshold_refer": 0.20,
        "fraud_reject_threshold": 0.80,
        "fraud_review_threshold": 0.60,
        "max_dti": 0.85,
        "min_open_accounts": 0,
        "min_loan_amount_usd": 20.0,
        "max_loan_amount_usd": 500.0,
        "base_apr": 0.0,               # fee-based advance
        "max_apr": 36.0,
        "required_features": [
            "avg_monthly_inflow",
            "net_monthly_cash_flow",
            "nsf_count_90d",
            "overdraft_count_90d",
            "savings_balance",
            "bank_account_age_months",
        ],
        "extra_rules": [
            "plaid_balance_realtime_check",     # fetch live balance before disbursement
            "plaid_nsf_gate_5",
            "plaid_bank_age_min_2_months",
            "plaid_min_inflow_500_monthly",
            "overdraft_count_gate_10_90d",      # reject if >10 overdrafts in 90 days
        ],
        "description": (
            "Overdraft / cash advance — Plaid-data tenant.  "
            "Real-time Plaid balance check required at disbursement."
        ),
        "regulatory_notes": (
            "CFPB overdraft fee guidance 2024: fee-based overdraft = TILA credit if systematic. "
            "UDAAP risk if fee not clearly disclosed. "
            "Plaid balance check consent must be included in account-linking agreement."
        ),
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def plaid_tenant_policy_overrides() -> Dict[ProductType, ProductPolicy]:
    """Return full ProductPolicy objects for all Plaid-tenant products.

    For products without explicit Plaid overrides the default policy is
    returned unchanged (AUTO_LOAN, MORTGAGE, SMALL_BUSINESS_LOAN).
    """
    overrides: Dict[ProductType, ProductPolicy] = {}
    for product_type in ALL_PRODUCT_TYPES:
        base = copy.deepcopy(_DEFAULT_POLICIES.get(product_type))
        if base is None:
            logger.warning("No default policy found for %s — skipping", product_type)
            continue
        patch = _PLAID_PRODUCT_OVERRIDES.get(product_type, {})
        for field_name, value in patch.items():
            object.__setattr__(base, field_name, value) if dataclasses.is_dataclass(base) \
                else setattr(base, field_name, value)
        overrides[product_type] = base
    return overrides


def apply_plaid_overrides(
    base_policy: ProductPolicy,
    tenant_config: Dict[str, Any],
) -> ProductPolicy:
    """Merge runtime tenant_config overrides on top of the Plaid base policy.

    Args:
        base_policy: The Plaid-base ProductPolicy (from plaid_tenant_policy_overrides()).
        tenant_config: Config Registry config_json for this tenant version.
            Expected keys: ``product_policy.<product_type>.<param>``.

    Returns:
        A new ProductPolicy with tenant-specific overrides applied.
    """
    merged = copy.deepcopy(base_policy)
    prefix = f"product_policy.{base_policy.product_type}."
    for key, value in tenant_config.items():
        if key.startswith(prefix):
            param = key[len(prefix):]
            if hasattr(merged, param):
                setattr(merged, param, value)
                logger.debug("Plaid tenant override applied: %s=%s", param, value)
            else:
                logger.warning("Unknown ProductPolicy field in tenant config: %s", param)
    return merged


def get_plaid_cash_flow_pd_adjustment(
    cash_flow_stability_score: float,
    nsf_count_90d: int,
) -> float:
    """Return a multiplicative adjustment to PD thresholds based on Plaid signals.

    Strong cash flow → relax threshold (multiply by factor > 1).
    Weak cash flow   → tighten threshold (multiply by factor < 1).

    Usage:
        adjusted_threshold = base_threshold * get_plaid_cash_flow_pd_adjustment(...)
    """
    if cash_flow_stability_score >= 0.70 and nsf_count_90d == 0:
        return 1.20   # relax by 20%
    if cash_flow_stability_score >= 0.50 and nsf_count_90d <= 1:
        return 1.10   # relax by 10%
    if nsf_count_90d >= 5 or cash_flow_stability_score < 0.20:
        return 0.80   # tighten by 20%
    if nsf_count_90d >= 3 or cash_flow_stability_score < 0.35:
        return 0.85   # tighten by 15%
    return 1.00       # no adjustment


def plaid_policy_summary_rows() -> List[Dict[str, Any]]:
    """Return a list of dicts suitable for tabular display in dashboards / docs."""
    policies = plaid_tenant_policy_overrides()
    rows = []
    for pt, pol in policies.items():
        rows.append({
            "Product": pt,
            "Approve PD ≤": f"{pol.pd_threshold_approve:.0%}",
            "Refer PD ≤": f"{pol.pd_threshold_refer:.0%}",
            "Max DTI": f"{pol.max_dti:.0%}",
            "Loan Range (USD)": f"${pol.min_loan_amount_usd:,.0f} – ${pol.max_loan_amount_usd:,.0f}",
            "Base APR": f"{pol.base_apr:.2f}%",
            "Max APR": f"{pol.max_apr:.2f}%",
            "Plaid Features": len([f for f in pol.required_features if f in _PLAID_BASE_FEATURES
                                    or f in _PLAID_EXTENDED_FEATURES]),
            "Description": pol.description,
        })
    return rows
