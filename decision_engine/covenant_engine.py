"""
Covenant Engine — S4-B
========================
Generates applicable loan covenants based on product type and industry risk tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class Covenant:
    covenant_type: str
    description: str
    threshold: Optional[float]
    frequency: Literal["Quarterly", "Annual", "At-Origination"]
    consequence: str


# ---------------------------------------------------------------------------
# Covenant matrix: product_type → risk_tier → covenants
# ---------------------------------------------------------------------------

_COVENANT_MATRIX: Dict[str, Dict[str, List[Covenant]]] = {
    "commercial_loan": {
        "_any": [
            Covenant(
                covenant_type="DSCR_MAINTENANCE",
                description="Maintain debt service coverage ratio ≥ 1.25 on a quarterly basis.",
                threshold=1.25,
                frequency="Quarterly",
                consequence="Loan placed on watchlist; remediation plan required within 30 days.",
            ),
            Covenant(
                covenant_type="MAX_LTV",
                description="Loan-to-value ratio must not exceed 75% at origination.",
                threshold=0.75,
                frequency="At-Origination",
                consequence="Approval conditioned on independent appraisal confirming LTV ≤ 75%.",
            ),
            Covenant(
                covenant_type="FINANCIAL_REPORTING",
                description="Borrower must provide annual audited financial statements.",
                threshold=None,
                frequency="Annual",
                consequence="Event of default if annual financials are not provided within 120 days of fiscal year-end.",
            ),
        ]
    },
    "smb_loan": {
        "High": [
            Covenant(
                covenant_type="PERSONAL_GUARANTEE",
                description="Personal guarantee from primary owner(s) required.",
                threshold=None,
                frequency="At-Origination",
                consequence="Required for approval; loan cannot be funded without executed guarantee.",
            ),
            Covenant(
                covenant_type="ANNUAL_TAX_RETURNS",
                description="Borrower must provide annual business tax returns.",
                threshold=None,
                frequency="Annual",
                consequence="Event of default if tax returns are not provided within 30 days of request.",
            ),
            Covenant(
                covenant_type="REVENUE_COVENANT",
                description="Annual revenue must remain at ≥ 80% of projected amount at origination.",
                threshold=0.80,
                frequency="Annual",
                consequence="Loan placed on watchlist; lender may require additional collateral.",
            ),
        ],
        "Elevated": [
            Covenant(
                covenant_type="PERSONAL_GUARANTEE",
                description="Personal guarantee from primary owner(s) required.",
                threshold=None,
                frequency="At-Origination",
                consequence="Required for approval; loan cannot be funded without executed guarantee.",
            ),
            Covenant(
                covenant_type="ANNUAL_TAX_RETURNS",
                description="Borrower must provide annual business tax returns.",
                threshold=None,
                frequency="Annual",
                consequence="Event of default if tax returns are not provided within 30 days of request.",
            ),
            Covenant(
                covenant_type="REVENUE_COVENANT",
                description="Annual revenue must remain at ≥ 80% of projected amount at origination.",
                threshold=0.80,
                frequency="Annual",
                consequence="Loan placed on watchlist; lender may require additional collateral.",
            ),
        ],
        "Low": [
            Covenant(
                covenant_type="ANNUAL_TAX_RETURNS",
                description="Borrower must provide annual business tax returns.",
                threshold=None,
                frequency="Annual",
                consequence="Event of default if tax returns are not provided within 30 days of request.",
            ),
        ],
        "Medium": [
            Covenant(
                covenant_type="ANNUAL_TAX_RETURNS",
                description="Borrower must provide annual business tax returns.",
                threshold=None,
                frequency="Annual",
                consequence="Event of default if tax returns are not provided within 30 days of request.",
            ),
        ],
    },
    "mortgage": {
        "_any": [
            Covenant(
                covenant_type="LTV_LIMIT",
                description="LTV must not exceed 80% at origination.",
                threshold=0.80,
                frequency="At-Origination",
                consequence="Conditional approval at LTV > 80%; PMI required or loan restructured.",
            ),
            Covenant(
                covenant_type="LIEN_SEARCH",
                description="Full lien search required before funding.",
                threshold=None,
                frequency="At-Origination",
                consequence="Loan cannot be funded until clear title is confirmed.",
            ),
        ]
    },
    "auto_loan": {
        "_any": [
            Covenant(
                covenant_type="LTV_LIMIT",
                description="LTV must not exceed 80% of vehicle book value at origination.",
                threshold=0.80,
                frequency="At-Origination",
                consequence="Conditional approval at LTV > 80%.",
            ),
            Covenant(
                covenant_type="LIEN_SEARCH",
                description="Lien search on vehicle title required before funding.",
                threshold=None,
                frequency="At-Origination",
                consequence="Loan cannot be funded until clear title is confirmed.",
            ),
        ]
    },
    "credit_card": {"_any": []},
    "personal_loan": {"_any": []},
}


def get_covenants(
    product_type: str,
    industry_risk_tier: str,
    dscr: Optional[float] = None,
    ltv: Optional[float] = None,
    loan_amount: float = 0.0,
) -> List[Covenant]:
    """Return applicable covenants for a given product and risk tier.

    Parameters
    ----------
    product_type:
        One of commercial_loan, smb_loan, mortgage, auto_loan, credit_card, personal_loan.
    industry_risk_tier:
        One of Low, Medium, High, Elevated.
    dscr, ltv, loan_amount:
        Numeric values used for covenant threshold checks (informational only).

    Returns
    -------
    List[Covenant]
    """
    product_map = _COVENANT_MATRIX.get(product_type.lower(), {})

    if "_any" in product_map:
        return list(product_map["_any"])

    # Tier-specific lookup
    tier_key = industry_risk_tier.capitalize()
    return list(product_map.get(tier_key, []))
