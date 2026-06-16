"""
decision_engine/product_policies.py
=====================================
Multi-Product Policy Engine (PRD §4.2.1, Phase 3)

Extends the core decision engine to support distinct credit policies for
multiple loan product types:
  - CREDIT_CARD
  - PERSONAL_LOAN
  - AUTO_LOAN
  - BNPL (Buy Now Pay Later)
  - MORTGAGE
  - SMALL_BUSINESS_LOAN

Each product type has its own:
  - PD thresholds (low / medium / high risk)
  - Fraud-flag routing
  - DTI limit
  - Minimum/maximum loan amount
  - Minimum open accounts requirement
  - Maximum APR cap (state-level caps enforced separately in compliance/engine.py)
  - Required features (some products need more fields like LTV, collateral type)

Policy parameters can be overridden per-tenant via the Config Registry (four-eyes
approved) using the key ``product_policy.<product_type>.<param>``.

Public API
----------
>>> from decision_engine.product_policies import (
...     ProductPolicy, get_product_policy, evaluate_product_policy
... )
>>> policy = get_product_policy("AUTO_LOAN")
>>> result = evaluate_product_policy(decision_request, policy)
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Product type literal
# ---------------------------------------------------------------------------

ProductType = Literal[
    "CREDIT_CARD",
    "PERSONAL_LOAN",
    "AUTO_LOAN",
    "BNPL",
    "MORTGAGE",
    "SMALL_BUSINESS_LOAN",
    "SMB_SECURED_LOAN",
    "CREDIT_BUILDER",
    "OVERDRAFT_CASH_ADVANCE",
]

ALL_PRODUCT_TYPES: List[ProductType] = [
    "CREDIT_CARD",
    "PERSONAL_LOAN",
    "AUTO_LOAN",
    "BNPL",
    "MORTGAGE",
    "SMALL_BUSINESS_LOAN",
    "SMB_SECURED_LOAN",
    "CREDIT_BUILDER",
    "OVERDRAFT_CASH_ADVANCE",
]


# ---------------------------------------------------------------------------
# ProductPolicy dataclass
# ---------------------------------------------------------------------------


@dataclass
class ProductPolicy:
    """Credit policy parameters for a specific loan product type.

    Attributes note the PRD requirement they satisfy where applicable.
    """

    product_type: ProductType

    # Risk thresholds (PD-based)
    pd_threshold_approve: float       # PD below this → APPROVE
    pd_threshold_refer: float         # PD in [approve, refer] → APPROVE at risk-priced rate
    # PD above pd_threshold_refer → REJECT

    # Fraud routing
    fraud_reject_threshold: float     # fraud_probability above this → REJECT
    fraud_review_threshold: float     # above this but below reject → MANUAL_REVIEW

    # Underwriting guardrails
    max_dti: float                    # debt-to-income ceiling (e.g. 0.45 for 45%)
    min_open_accounts: int            # minimum number of open tradelines
    min_loan_amount_usd: float
    max_loan_amount_usd: float

    # APR bounds (state-level MLA/usury cap enforcement is separate)
    base_apr: float                   # base annual rate (%)
    max_apr: float                    # product APR cap (%)

    # Required features (validation)
    required_features: List[str] = field(default_factory=list)

    # Product-specific rules (evaluated after PD/fraud)
    extra_rules: List[str] = field(default_factory=list)

    # Human-readable notes
    description: str = ""
    regulatory_notes: str = ""


# ---------------------------------------------------------------------------
# Default policy catalogue
# ---------------------------------------------------------------------------

_DEFAULT_POLICIES: Dict[ProductType, ProductPolicy] = {
    "CREDIT_CARD": ProductPolicy(
        product_type="CREDIT_CARD",
        pd_threshold_approve=0.05,
        pd_threshold_refer=0.10,
        fraud_reject_threshold=0.70,
        fraud_review_threshold=0.40,
        max_dti=0.45,
        min_open_accounts=1,
        min_loan_amount_usd=500.0,
        max_loan_amount_usd=50_000.0,
        base_apr=12.99,
        max_apr=29.99,
        required_features=["credit_score", "debt_to_income", "num_open_accounts"],
        extra_rules=["revolving_utilization_check", "min_credit_age_6_months"],
        description="Standard revolving credit card policy",
        regulatory_notes="Subject to CARD Act (Credit Card Accountability Responsibility and Disclosure Act). "
                         "Regulation Z (Truth in Lending) disclosure required.",
    ),
    "PERSONAL_LOAN": ProductPolicy(
        product_type="PERSONAL_LOAN",
        pd_threshold_approve=0.06,
        pd_threshold_refer=0.12,
        fraud_reject_threshold=0.65,
        fraud_review_threshold=0.35,
        max_dti=0.50,
        min_open_accounts=1,
        min_loan_amount_usd=1_000.0,
        max_loan_amount_usd=100_000.0,
        base_apr=8.99,
        max_apr=36.0,
        required_features=["credit_score", "debt_to_income", "annual_income", "num_open_accounts"],
        extra_rules=["income_verification_required"],
        description="Unsecured personal installment loan policy",
        regulatory_notes="Subject to TILA Reg Z, ECOA Reg B, FCRA adverse action requirements. "
                         "MLA compliance required for covered borrowers (≤36% MAPR).",
    ),
    "AUTO_LOAN": ProductPolicy(
        product_type="AUTO_LOAN",
        pd_threshold_approve=0.07,
        pd_threshold_refer=0.14,
        fraud_reject_threshold=0.60,
        fraud_review_threshold=0.30,
        max_dti=0.55,
        min_open_accounts=0,          # subprime auto may have thin files
        min_loan_amount_usd=3_000.0,
        max_loan_amount_usd=120_000.0,
        base_apr=5.99,
        max_apr=24.99,
        required_features=["credit_score", "debt_to_income", "vehicle_ltv", "vehicle_age_years"],
        extra_rules=["ltv_check_max_125pct", "vehicle_age_max_10_years", "odometer_max_150k"],
        description="Retail auto loan (direct and dealer-originated)",
        regulatory_notes="Subject to TILA Reg Z, ECOA Reg B, FCRA. "
                         "FTC Holder Rule applies for dealer-originated loans. "
                         "State lemon law compliance required.",
    ),
    "BNPL": ProductPolicy(
        product_type="BNPL",
        pd_threshold_approve=0.08,
        pd_threshold_refer=0.15,
        fraud_reject_threshold=0.75,   # higher fraud tolerance for small-ticket BNPL
        fraud_review_threshold=0.50,
        max_dti=0.65,                  # BNPL often thin-file, relax DTI
        min_open_accounts=0,
        min_loan_amount_usd=10.0,
        max_loan_amount_usd=5_000.0,
        base_apr=0.0,                  # often 0% promotional
        max_apr=36.0,
        required_features=["credit_score", "payment_history"],
        extra_rules=["max_concurrent_bnpl_plans_4", "merchant_category_check"],
        description="Buy Now Pay Later short-term installment plan",
        regulatory_notes="CFPB interpretive rule (2024-present): BNPL products are credit cards under TILA. "
                         "Periodic statements, dispute rights, and Reg Z disclosures required. "
                         "Watch for state-level mini-CFPB regulations.",
    ),
    "MORTGAGE": ProductPolicy(
        product_type="MORTGAGE",
        pd_threshold_approve=0.04,
        pd_threshold_refer=0.08,
        fraud_reject_threshold=0.50,
        fraud_review_threshold=0.25,
        max_dti=0.43,                  # CFPB Qualified Mortgage (QM) safe harbor
        min_open_accounts=2,
        min_loan_amount_usd=50_000.0,
        max_loan_amount_usd=3_500_000.0,   # FHFA conforming + jumbo
        base_apr=6.50,
        max_apr=14.99,                 # HOEPA high-cost threshold trigger
        required_features=[
            "credit_score", "debt_to_income", "ltv", "annual_income",
            "property_type", "occupancy_type", "appraisal_value"
        ],
        extra_rules=[
            "qm_ability_to_repay_check",
            "ltv_max_97pct_conforming",
            "ltv_max_80pct_no_pmi",
            "hmda_reporting_required",
            "cra_activity_tracking",
            "min_credit_score_620",
        ],
        description="1-4 family residential mortgage — conforming and jumbo",
        regulatory_notes="RESPA, TILA-RESPA Integrated Disclosure (TRID), HMDA, "
                         "QM / Ability-to-Repay rule (12 CFR 1026.43), "
                         "CRA community reinvestment tracking required. "
                         "HOEPA triggers apply at APR + 1.5pp over APOR for first liens.",
    ),
    "SMALL_BUSINESS_LOAN": ProductPolicy(
        product_type="SMALL_BUSINESS_LOAN",
        pd_threshold_approve=0.08,
        pd_threshold_refer=0.16,
        fraud_reject_threshold=0.55,
        fraud_review_threshold=0.30,
        max_dti=0.60,                  # global cash flow DTI for SBL
        min_open_accounts=0,
        min_loan_amount_usd=5_000.0,
        max_loan_amount_usd=5_000_000.0,
        base_apr=7.50,
        max_apr=40.0,                  # MCA / revenue-based financing has no federal APR cap
        required_features=[
            "credit_score", "annual_revenue", "years_in_business",
            "debt_service_coverage_ratio", "business_type"
        ],
        extra_rules=[
            "years_in_business_min_1",
            "dscr_min_1_25",
            "personal_guarantee_required_under_250k",
            "cra_small_business_tracking",
        ],
        description="Small business term loan, line of credit, or SBA-guaranteed loan",
        regulatory_notes="ECOA / Reg B applies. CRA small business activity reporting. "
                         "Dodd-Frank §1071 small business lending data collection (CFPB Final Rule 2023). "
                         "SBA 7(a) / 504 programs have additional eligibility and use-of-proceeds rules.",
    ),
    "SMB_SECURED_LOAN": ProductPolicy(
        product_type="SMB_SECURED_LOAN",
        pd_threshold_approve=0.10,
        pd_threshold_refer=0.20,
        fraud_reject_threshold=0.55,
        fraud_review_threshold=0.30,
        max_dti=0.55,                  # tighter DTI for secured lending
        min_open_accounts=0,
        min_loan_amount_usd=25_000.0,
        max_loan_amount_usd=10_000_000.0,
        base_apr=6.50,
        max_apr=30.0,
        required_features=[
            "annual_revenue", "years_in_business",
            "debt_service_coverage_ratio", "business_type",
            "collateral_type", "collateral_value", "collateral_ltv",
        ],
        extra_rules=[
            "years_in_business_min_1",
            "dscr_min_1_25",
            "collateral_ltv_max_80pct",
            "collateral_adequacy_check",
            "cra_small_business_tracking",
        ],
        description="SMB secured term loan backed by real estate, equipment, or inventory collateral",
        regulatory_notes="ECOA / Reg B applies. UCC-1 filing required for non-real-estate collateral. "
                         "Dodd-Frank §1071 data collection required. "
                         "Environmental review required for real-estate collateral ≥$500k.",
    ),
    "CREDIT_BUILDER": ProductPolicy(
        product_type="CREDIT_BUILDER",
        pd_threshold_approve=0.15,        # elevated tolerance for no/thin credit
        pd_threshold_refer=0.25,
        fraud_reject_threshold=0.65,
        fraud_review_threshold=0.40,
        max_dti=0.55,
        min_open_accounts=0,              # by design — for applicants with no tradelines
        min_loan_amount_usd=200.0,
        max_loan_amount_usd=3_000.0,      # conservative limit
        base_apr=0.0,                     # typically fee-based or 0% for secured card
        max_apr=28.99,
        required_features=["annual_income"],
        extra_rules=[
            "deposit_secured_limit_check",
            "no_active_bankruptcy_check",
            "manual_review_if_no_bureau_signal",
        ],
        description="Credit builder loan or secured card for thin-file / no-credit applicants",
        regulatory_notes="Subject to TILA Reg Z, ECOA Reg B, FCRA adverse action. "
                         "Secured card: must disclose security deposit terms. "
                         "CFPB guidance: avoid fee harvesting products (fees > 25% of credit limit).",
    ),
    "OVERDRAFT_CASH_ADVANCE": ProductPolicy(
        product_type="OVERDRAFT_CASH_ADVANCE",
        pd_threshold_approve=0.12,
        pd_threshold_refer=0.20,
        fraud_reject_threshold=0.70,
        fraud_review_threshold=0.45,
        max_dti=0.60,
        min_open_accounts=0,
        min_loan_amount_usd=50.0,
        max_loan_amount_usd=1_000.0,      # small-dollar cap
        base_apr=0.0,                     # flat-fee model; APR disclosure still required
        max_apr=36.0,                     # MAPR cap for MLA covered borrowers
        required_features=["annual_income", "avg_monthly_cash_inflow"],
        extra_rules=[
            "overdraft_frequency_check",
            "net_inflow_adequacy_check",
            "no_active_bankruptcy_check",
            "repayment_cadence_check",
        ],
        description="Short-term cash advance or overdraft protection using payroll / cash-flow signals",
        regulatory_notes="CFPB small-dollar lending rule applies. "
                         "TILA Reg Z APR disclosure required even for flat-fee products. "
                         "State small-loan act limits vary; confirm per-state before origination. "
                         "MLA ≤36% MAPR required for covered borrowers.",
    ),
}


# ---------------------------------------------------------------------------
# Policy evaluation result
# ---------------------------------------------------------------------------


@dataclass
class ProductPolicyResult:
    """Output of evaluating a loan application against a product policy."""

    application_id: str
    product_type: ProductType

    # Final gatekeeping outcome (before the PD model)
    pre_qualification_passed: bool
    pre_qualification_flags: List[str]   # e.g. ["DTI_TOO_HIGH", "LOAN_BELOW_MINIMUM"]

    # Individual rule outcomes
    fraud_verdict: Literal["APPROVE", "REJECT", "MANUAL_REVIEW"]
    dti_passed: bool
    loan_amount_passed: bool
    open_accounts_passed: bool
    extra_rule_results: Dict[str, bool]  # rule_name → passed

    # Aggregated override suggestion
    policy_decline_codes: List[str]       # FCRA reason codes triggered by policy rules

    # Which policy was evaluated (for audit)
    policy_version_tag: str = "default"


@dataclass
class ProductPolicyEvaluationInput:
    """Input to `evaluate_product_policy()`.  All fields except application_id are optional
    but missing required features for the chosen product will generate a flag."""

    application_id: str
    product_type: ProductType
    fraud_probability: float = 0.0
    fraud_flag: str = "continue"
    pd_score: float = 0.0
    loan_amount_usd: float = 0.0
    annual_income_usd: float = 0.0
    debt_to_income_ratio: float = 0.0
    num_open_accounts: int = 0
    credit_score: Optional[int] = None  # None = not provided / thin-file
    # Auto / Mortgage specific
    vehicle_ltv: Optional[float] = None
    vehicle_age_years: Optional[int] = None
    ltv: Optional[float] = None
    property_type: Optional[str] = None
    occupancy_type: Optional[str] = None
    # SBL specific
    annual_revenue: Optional[float] = None
    years_in_business: Optional[int] = None
    debt_service_coverage_ratio: Optional[float] = None
    business_type: Optional[str] = None
    # BNPL specific
    payment_history: Optional[str] = None
    concurrent_bnpl_plans: Optional[int] = None   # active BNPL plans at time of application
    merchant_category: Optional[str] = None       # merchant category for BNPL gating
    # SMB Secured Loan specific
    collateral_type: Optional[str] = None         # e.g. "real_estate", "equipment", "inventory"
    collateral_value: Optional[float] = None
    collateral_ltv: Optional[float] = None        # loan / collateral value ratio (0–1+)
    # Credit Builder specific
    security_deposit_amount: Optional[float] = None  # secured-card deposit (equals credit limit)
    has_active_bankruptcy: Optional[bool] = None
    has_bureau_signal: Optional[bool] = None      # False = truly no-file
    # Overdraft / Cash Advance specific
    avg_monthly_cash_inflow: Optional[float] = None   # monthly inflow from open-banking
    overdraft_events_90d: Optional[int] = None        # NSF / overdraft events last 90 days
    paycheck_cadence: Optional[str] = None        # "weekly", "biweekly", "monthly", "irregular"
    # Feature override map (e.g. from policy simulator)
    feature_overrides: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation / rules engine
# ---------------------------------------------------------------------------

# Maps policy required_features field names to their corresponding attribute
# on ProductPolicyEvaluationInput (or None if same name).
_REQUIRED_FEATURE_ATTR_MAP: Dict[str, str] = {
    "credit_score": "credit_score",
    "debt_to_income": "debt_to_income_ratio",
    "num_open_accounts": "num_open_accounts",
    "annual_income": "annual_income_usd",
    "annual_revenue": "annual_revenue",
    "years_in_business": "years_in_business",
    "debt_service_coverage_ratio": "debt_service_coverage_ratio",
    "business_type": "business_type",
    "vehicle_ltv": "vehicle_ltv",
    "vehicle_age_years": "vehicle_age_years",
    "ltv": "ltv",
    "property_type": "property_type",
    "occupancy_type": "occupancy_type",
    "payment_history": "payment_history",
    "collateral_type": "collateral_type",
    "collateral_value": "collateral_value",
    "collateral_ltv": "collateral_ltv",
    "avg_monthly_cash_inflow": "avg_monthly_cash_inflow",
}


def validate_required_features(
    product_type: ProductType,
    inp: "ProductPolicyEvaluationInput",
    policy: Optional["ProductPolicy"] = None,
) -> List[str]:
    """Return a list of missing required-feature flag strings for *product_type*.

    Flags are formatted as ``"MISSING_REQUIRED_FIELD:<field_name>"`` so they
    can be included in ``pre_qualification_flags`` and FCRA reason codes.

    Parameters
    ----------
    product_type:
        The product being evaluated.
    inp:
        The evaluation input (populated fields are checked against None / zero).
    policy:
        Optional pre-fetched policy; if None the default policy is used.

    Returns
    -------
    List[str]
        Empty list if all required fields are present.
    """
    if policy is None:
        policy = get_product_policy(product_type)

    missing: List[str] = []
    for field_name in policy.required_features:
        attr = _REQUIRED_FEATURE_ATTR_MAP.get(field_name, field_name)
        value = getattr(inp, attr, None)
        # Treat None and zero as "missing" for numeric required fields
        # (0.0 annual income / 0.0 inflow is not a valid supplied value)
        is_missing = value is None or (isinstance(value, (int, float)) and value == 0 and attr not in {"num_open_accounts"})
        if is_missing:
            missing.append(f"MISSING_REQUIRED_FIELD:{field_name}")
            logger.info(
                "validate_required_features: product=%s missing field=%s",
                product_type,
                field_name,
            )
    return missing


def _check_extra_rules(
    rule_names: List[str],
    inp: ProductPolicyEvaluationInput,
) -> Dict[str, bool]:
    """Evaluate product-specific extra rules. Returns rule_name → passed mapping."""
    results: Dict[str, bool] = {}

    for rule in rule_names:
        if rule == "revolving_utilization_check":
            # Would use credit bureau utilization; default pass if not provided
            results[rule] = True

        elif rule == "min_credit_age_6_months":
            results[rule] = True  # Requires credit bureau data; default pass

        elif rule == "income_verification_required":
            results[rule] = inp.annual_income_usd > 0

        elif rule == "ltv_check_max_125pct":
            if inp.vehicle_ltv is not None:
                results[rule] = inp.vehicle_ltv <= 1.25
            else:
                results[rule] = True  # not provided → pass (flag separately)

        elif rule == "vehicle_age_max_10_years":
            if inp.vehicle_age_years is not None:
                results[rule] = inp.vehicle_age_years <= 10
            else:
                results[rule] = True

        elif rule == "odometer_max_150k":
            results[rule] = True   # Requires vehicle data

        elif rule == "max_concurrent_bnpl_plans_4":
            if inp.concurrent_bnpl_plans is not None:
                results[rule] = inp.concurrent_bnpl_plans <= 4
            else:
                results[rule] = inp.num_open_accounts <= 20  # proxy when explicit count absent

        elif rule == "merchant_category_check":
            blocked_categories = {"gambling", "adult", "firearms", "crypto_exchange"}
            if inp.merchant_category:
                results[rule] = inp.merchant_category.lower() not in blocked_categories
            else:
                results[rule] = True

        elif rule == "qm_ability_to_repay_check":
            results[rule] = inp.debt_to_income_ratio <= 0.43

        elif rule == "ltv_max_97pct_conforming":
            if inp.ltv is not None:
                results[rule] = inp.ltv <= 0.97
            else:
                results[rule] = True

        elif rule == "ltv_max_80pct_no_pmi":
            # This rule notes PMI requirement, not a hard decline rule itself
            results[rule] = True

        elif rule == "hmda_reporting_required":
            results[rule] = True   # governance check, not a hard decline

        elif rule == "cra_activity_tracking":
            results[rule] = True

        elif rule == "min_credit_score_620":
            results[rule] = inp.credit_score is not None and inp.credit_score >= 620

        elif rule == "years_in_business_min_1":
            if inp.years_in_business is not None:
                results[rule] = inp.years_in_business >= 1
            else:
                results[rule] = True

        elif rule == "dscr_min_1_25":
            if inp.debt_service_coverage_ratio is not None:
                results[rule] = inp.debt_service_coverage_ratio >= 1.25
            else:
                results[rule] = True

        elif rule == "personal_guarantee_required_under_250k":
            results[rule] = True   # Documentation requirement, not a hard decline

        elif rule == "cra_small_business_tracking":
            results[rule] = True

        elif rule == "collateral_ltv_max_80pct":
            if inp.collateral_ltv is not None:
                results[rule] = inp.collateral_ltv <= 0.80
            else:
                results[rule] = True  # Not provided → pass (flagged by required-field check)

        elif rule == "collateral_adequacy_check":
            # Collateral must cover at least 100% of loan amount
            if inp.collateral_value is not None and inp.loan_amount_usd > 0:
                results[rule] = inp.collateral_value >= inp.loan_amount_usd
            else:
                results[rule] = True  # Deferred to required-field check

        elif rule == "deposit_secured_limit_check":
            # Security deposit must equal or exceed loan/credit limit amount
            if inp.security_deposit_amount is not None and inp.loan_amount_usd > 0:
                results[rule] = inp.security_deposit_amount >= inp.loan_amount_usd
            else:
                results[rule] = True  # Not provided → pass (no deposit product)

        elif rule == "no_active_bankruptcy_check":
            # Active bankruptcy → hard decline
            if inp.has_active_bankruptcy is not None:
                results[rule] = not inp.has_active_bankruptcy
            else:
                results[rule] = True  # Not known → pass (flag separately if needed)

        elif rule == "manual_review_if_no_bureau_signal":
            # No bureau signal → route to manual review (soft rule, not hard decline)
            # Returns True so pre_qual_passed is unaffected; caller checks fraud_verdict
            results[rule] = True

        elif rule == "overdraft_frequency_check":
            # More than 3 overdraft events in last 90 days → decline
            if inp.overdraft_events_90d is not None:
                results[rule] = inp.overdraft_events_90d <= 3
            else:
                results[rule] = True

        elif rule == "net_inflow_adequacy_check":
            # Net inflow must cover at least 1.5× the requested advance amount
            if inp.avg_monthly_cash_inflow is not None and inp.loan_amount_usd > 0:
                results[rule] = inp.avg_monthly_cash_inflow >= inp.loan_amount_usd * 1.5
            else:
                results[rule] = True

        elif rule == "repayment_cadence_check":
            # Irregular paycheck cadence → refer to manual review (soft rule)
            results[rule] = True  # Hard decline not triggered; fraud_verdict may escalate

        else:
            logger.debug("Unknown extra rule '%s'; defaulting to passed", rule)
            results[rule] = True

    return results


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------


def evaluate_product_policy(
    inp: ProductPolicyEvaluationInput,
    policy: Optional[ProductPolicy] = None,
) -> ProductPolicyResult:
    """Evaluate a loan application against the product policy.

    Parameters
    ----------
    inp : ProductPolicyEvaluationInput
        Application features and model scores.
    policy : ProductPolicy, optional
        Policy to evaluate against.  If None, the default policy for
        ``inp.product_type`` is used.

    Returns
    -------
    ProductPolicyResult
    """
    if policy is None:
        policy = get_product_policy(inp.product_type)

    flags: List[str] = []
    policy_codes: List[str] = []

    # --- Required-field validation (Prompt-06) ---
    missing_flags = validate_required_features(inp.product_type, inp, policy)
    if missing_flags:
        flags.extend(missing_flags)
        policy_codes.append("AA09")   # "Incomplete application — required information missing"
        logger.info(
            "evaluate_product_policy: application=%s product=%s missing_fields=%s",
            inp.application_id,
            inp.product_type,
            missing_flags,
        )

    # --- Fraud routing ---
    fp = inp.fraud_probability
    if fp >= policy.fraud_reject_threshold:
        fraud_verdict: Literal["APPROVE", "REJECT", "MANUAL_REVIEW"] = "REJECT"
        flags.append(f"FRAUD_REJECT (prob={fp:.3f} ≥ {policy.fraud_reject_threshold})")
        policy_codes.append("AA02")
    elif fp >= policy.fraud_review_threshold:
        fraud_verdict = "MANUAL_REVIEW"
        flags.append(f"FRAUD_REVIEW (prob={fp:.3f} ≥ {policy.fraud_review_threshold})")
        policy_codes.append("AA05")
    else:
        fraud_verdict = "APPROVE"

    # --- DTI check ---
    dti = inp.debt_to_income_ratio
    dti_passed = dti <= policy.max_dti
    if not dti_passed:
        flags.append(f"DTI_TOO_HIGH ({dti:.2%} > {policy.max_dti:.2%})")
        policy_codes.append("AA04")

    # --- Loan amount check ---
    amount = inp.loan_amount_usd
    amount_passed = policy.min_loan_amount_usd <= amount <= policy.max_loan_amount_usd
    if not amount_passed:
        if amount < policy.min_loan_amount_usd:
            flags.append(f"LOAN_BELOW_MINIMUM (${amount:,.0f} < ${policy.min_loan_amount_usd:,.0f})")
        else:
            flags.append(f"LOAN_ABOVE_MAXIMUM (${amount:,.0f} > ${policy.max_loan_amount_usd:,.0f})")

    # --- Open accounts check ---
    accounts_passed = inp.num_open_accounts >= policy.min_open_accounts
    if not accounts_passed:
        flags.append(f"INSUFFICIENT_TRADELINES ({inp.num_open_accounts} < {policy.min_open_accounts})")
        policy_codes.append("AA03")

    # --- Extra product-specific rules ---
    extra_results = _check_extra_rules(policy.extra_rules, inp)
    for rule_name, passed in extra_results.items():
        if not passed:
            flags.append(f"RULE_FAILED:{rule_name}")

    # --- Pre-qualification gate ---
    pre_qual_passed = (
        not missing_flags
        and fraud_verdict != "REJECT"
        and dti_passed
        and amount_passed
        and accounts_passed
        and all(extra_results.values())
    )

    return ProductPolicyResult(
        application_id=inp.application_id,
        product_type=inp.product_type,
        pre_qualification_passed=pre_qual_passed,
        pre_qualification_flags=flags,
        fraud_verdict=fraud_verdict,
        dti_passed=dti_passed,
        loan_amount_passed=amount_passed,
        open_accounts_passed=accounts_passed,
        extra_rule_results=extra_results,
        policy_decline_codes=list(dict.fromkeys(policy_codes)),   # deduplicated, preserving order
        policy_version_tag="default",
    )


# ---------------------------------------------------------------------------
# Registry accessors
# ---------------------------------------------------------------------------


def get_product_policy(
    product_type: ProductType,
    tenant_overrides: Optional[Dict[str, Any]] = None,
) -> ProductPolicy:
    """Return the policy for *product_type*, optionally merged with tenant overrides.

    Parameters
    ----------
    product_type : ProductType
        The loan product type.
    tenant_overrides : dict, optional
        Mapping of policy field names to override values (from Config Registry).
        Example: ``{"pd_threshold_approve": 0.04, "max_dti": 0.40}``

    Returns
    -------
    ProductPolicy
    """
    base = _DEFAULT_POLICIES.get(product_type)
    if base is None:
        raise ValueError(
            f"Unknown product_type {product_type!r}. "
            f"Valid values: {', '.join(ALL_PRODUCT_TYPES)}"
        )
    if not tenant_overrides:
        return base

    overrides_applied = {}
    for k, v in tenant_overrides.items():
        if hasattr(base, k):
            overrides_applied[k] = v
        else:
            logger.warning("ProductPolicy has no field '%s'; ignoring tenant override", k)

    if not overrides_applied:
        return base

    return dataclasses.replace(base, **overrides_applied)


def list_product_types() -> List[ProductType]:
    """Return all supported product type identifiers."""
    return list(ALL_PRODUCT_TYPES)


def get_all_policies() -> Dict[ProductType, ProductPolicy]:
    """Return a copy of the default policy catalogue."""
    return dict(_DEFAULT_POLICIES)
