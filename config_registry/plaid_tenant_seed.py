"""
config_registry/plaid_tenant_seed.py
======================================
Seed script — registers the ``plaid_data`` tenant and its initial versioned
configuration into the Config Registry (SQLite for local dev; swap DB_URL for
PostgreSQL in production).

Run once per environment:
    python -m config_registry.plaid_tenant_seed

Idempotent: re-running will detect that tenant already exists and skip.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from config_registry.models import TenantConfigVersion, TenantRecord
from config_registry.service import ConfigRegistryService

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

TENANT_ID = "plaid_data"
TENANT_NAME = "Plaid Data Open-Banking Tenant"
TIER = "enterprise"
APPROVED_BY = "system_seed_script"

# ---------------------------------------------------------------------------
# Full versioned config — v1
# ---------------------------------------------------------------------------

PLAID_CONFIG_V1: dict = {
    # ── Tenant meta ─────────────────────────────────────────────────────────
    "bureau_provider": "plaid",
    "plaid_env": os.getenv("PLAID_ENV", "sandbox"),
    "bank_lookback_days": 90,
    "income_verification_method": "plaid_income",
    "alt_data_signals": [
        "cash_flow_stability_score",
        "nsf_count_90d",
        "overdraft_count_90d",
        "avg_monthly_inflow",
        "net_monthly_cash_flow",
        "bank_account_age_months",
        "plaid_income_estimate",
        "income_source_count",
        "income_volatility",
        "savings_balance",
        "recurring_expense_ratio",
    ],

    # ── Feature toggles ──────────────────────────────────────────────────────
    "feature_toggles": {
        "plaid_cash_flow_underwriting": True,
        "plaid_income_verification": True,
        "plaid_realtime_balance_check": True,
        "thin_file_alt_data_path": True,
        "bureau_score_required": False,         # bureau score optional for thin files
        "manual_review_queue_enabled": True,
        "adverse_action_pdf_enabled": True,
        "explainability_shap_enabled": True,
        "regulatory_horizon_alerts": True,
    },

    # ── Product-level policy cutoffs ────────────────────────────────────────
    # These are the canonical values stored in the registry.
    # The decision engine merges these at runtime via apply_plaid_overrides().

    "product_policy.BNPL.pd_threshold_approve": 0.10,
    "product_policy.BNPL.pd_threshold_refer": 0.18,
    "product_policy.BNPL.max_dti": 0.70,
    "product_policy.BNPL.max_loan_amount_usd": 7500.0,

    "product_policy.PERSONAL_LOAN.pd_threshold_approve": 0.07,
    "product_policy.PERSONAL_LOAN.pd_threshold_refer": 0.14,
    "product_policy.PERSONAL_LOAN.max_dti": 0.55,
    "product_policy.PERSONAL_LOAN.min_open_accounts": 0,
    "product_policy.PERSONAL_LOAN.max_loan_amount_usd": 75000.0,
    "product_policy.PERSONAL_LOAN.base_apr": 9.99,

    "product_policy.SMB_SECURED_LOAN.pd_threshold_approve": 0.09,
    "product_policy.SMB_SECURED_LOAN.pd_threshold_refer": 0.17,
    "product_policy.SMB_SECURED_LOAN.max_dti": 0.65,
    "product_policy.SMB_SECURED_LOAN.max_loan_amount_usd": 500000.0,
    "product_policy.SMB_SECURED_LOAN.base_apr": 8.50,

    "product_policy.CREDIT_CARD.pd_threshold_approve": 0.06,
    "product_policy.CREDIT_CARD.pd_threshold_refer": 0.12,
    "product_policy.CREDIT_CARD.min_open_accounts": 0,
    "product_policy.CREDIT_CARD.base_apr": 14.99,

    "product_policy.CREDIT_BUILDER.pd_threshold_approve": 0.15,
    "product_policy.CREDIT_BUILDER.pd_threshold_refer": 0.25,
    "product_policy.CREDIT_BUILDER.max_dti": 0.80,

    "product_policy.OVERDRAFT_CASH_ADVANCE.pd_threshold_approve": 0.12,
    "product_policy.OVERDRAFT_CASH_ADVANCE.pd_threshold_refer": 0.20,
    "product_policy.OVERDRAFT_CASH_ADVANCE.max_dti": 0.85,

    # ── Pricing overrides ───────────────────────────────────────────────────
    "pricing_overrides": {
        "BNPL_promo_apr": 0.0,
        "PERSONAL_LOAN_spread_bps": 250,        # base rate + 250 bps
        "SMB_SECURED_LOAN_spread_bps": 300,
        "CREDIT_CARD_interchange_target_bps": 175,
    },

    # ── Rate limits ─────────────────────────────────────────────────────────
    "rate_limits": {
        "decisions_per_minute": 500,
        "plaid_link_tokens_per_hour": 1000,
        "batch_underwrite_max_size": 5000,
    },

    # ── Compliance gate config ───────────────────────────────────────────────
    "compliance_config": {
        "ecoa_adverse_action_window_days": 30,
        "fcra_permissible_purpose": "underwriting",
        "plaid_consent_required": True,
        "mla_mapr_cap_pct": 36.0,
        "state_usury_overrides": {},            # populated per state as needed
    },
}


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------


def seed_plaid_tenant(db_url: str | None = None) -> None:
    db = db_url or os.getenv("CONFIG_REGISTRY_DB", "config_registry.db")
    svc = ConfigRegistryService(db_url=db)

    # Check if tenant already exists
    existing = svc.get_active(TENANT_ID)
    if existing is not None:
        logger.info("Tenant '%s' already exists at version %s — skipping seed.",
                    TENANT_ID, existing.config_version)
        return

    # Register tenant
    tenant = TenantRecord(
        tenant_id=TENANT_ID,
        name=TENANT_NAME,
        status="active",
        tier=TIER,
        active_config_version="v1",
    )
    svc.register_tenant(tenant)
    logger.info("Registered tenant '%s'", TENANT_ID)

    # Publish v1 config
    config_json_str = json.dumps(PLAID_CONFIG_V1, sort_keys=True)
    sha = hashlib.sha256(config_json_str.encode()).hexdigest()

    version = TenantConfigVersion(
        tenant_id=TENANT_ID,
        config_version="v1",
        config_sha256=sha,
        approved_by=APPROVED_BY,
        config_json=PLAID_CONFIG_V1,
        is_rollback=False,
        rollback_source_version=None,
    )
    svc.publish(version)
    logger.info("Published plaid_data config v1 (sha256=%s...)", sha[:16])


if __name__ == "__main__":
    seed_plaid_tenant()
    logger.info("Plaid tenant seed complete.")
