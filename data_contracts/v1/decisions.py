"""
data_contracts.v1.decisions
=============================
Contracts for credit decisions, explanations, and pricing terms.

Consumers
---------
* LucidCredit  — ingests CreditDecisionV1 + DecisionExplanationV1 into RAG store
* ThinFile     — receives CreditDecisionV1 as the final underwriting output
* AgentHiveHQ  — subscribes to DecisionMadeEvent which wraps DecisionRecordV1

Versioning note
---------------
``reason_codes`` follows the FCRA/Reg B codeset defined in
``compliance/adverse_action.py``.  Codes AA01–AA06 are stable.
SHAP-derived codes (SHAP_*) may be extended without a version bump.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DecisionLabelV1(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FraudFlagV1(str, Enum):
    CONTINUE = "continue"
    MANUAL_REVIEW = "manual_review"
    REJECT = "reject"


class PDBandV1(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LoanProductTypeV1(str, Enum):
    CREDIT_CARD = "credit_card"
    PERSONAL_LOAN = "personal_loan"
    MORTGAGE = "mortgage"
    AUTO = "auto"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ContractBaseV1(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["1.0.0"] = "1.0.0"
    contract_name: str = Field(...)


# ---------------------------------------------------------------------------
# PricingTermsV1 — approved loan terms offered to a borrower
# ---------------------------------------------------------------------------


class PricingTermsV1(_ContractBaseV1):
    """
    The economic terms attached to an approved credit decision.

    ``None`` values indicate the field was not applicable or not yet set
    (e.g. credit cards do not have a fixed ``approved_term_months``).
    """

    contract_name: Literal["PricingTermsV1"] = "PricingTermsV1"

    approved_amount: Optional[float] = Field(
        None, ge=0,
        description="Approved principal in USD."
    )
    approved_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Annual percentage rate [0, 1] e.g. 0.1899 = 18.99%."
    )
    approved_term_months: Optional[int] = Field(
        None, ge=1, le=360,
        description="Loan tenor in months. None for revolving products."
    )
    monthly_payment: Optional[float] = Field(
        None, ge=0,
        description="Estimated monthly payment in USD (installment products only)."
    )
    origination_fee_rate: Optional[float] = Field(
        None, ge=0.0, le=0.10,
        description="Origination fee as a fraction of loan amount [0, 0.10]."
    )
    credit_limit: Optional[float] = Field(
        None, ge=0,
        description="Approved credit limit in USD (revolving products only)."
    )

    # Risk economics
    expected_loss: Optional[float] = Field(
        None, ge=0.0,
        description="EL = PD × LGD × EAD in USD."
    )
    expected_profit: Optional[float] = Field(
        None,
        description="Revenue − EL − cost of funds, in USD."
    )
    risk_based_pricing_tier: Optional[str] = Field(
        None,
        description="Internal pricing tier label (e.g. 'prime', 'near-prime').",
    )


# ---------------------------------------------------------------------------
# DecisionExplanationV1 — SHAP + Reg B adverse action narrative
# ---------------------------------------------------------------------------


class ShapFactorV1(BaseModel):
    """Single SHAP-based explanatory factor."""

    model_config = ConfigDict(extra="ignore")

    feature_name: str
    shap_value: float = Field(
        ...,
        description="Raw SHAP value — positive increases default probability, "
                    "negative decreases it.",
    )
    feature_value: Optional[Any] = Field(
        None,
        description="Actual value of the feature for this application.",
    )
    direction: Literal["positive_risk", "negative_risk"] = Field(
        ...,
        description="Whether this factor increased or decreased credit risk.",
    )
    reg_b_code: Optional[str] = Field(
        None,
        description="FCRA/Reg B reason code mapped from this factor (AA01-AA06 or SHAP_*).",
    )
    reg_b_text: Optional[str] = Field(
        None,
        description="Human-readable Reg B disclosure text.",
    )


class DecisionExplanationV1(_ContractBaseV1):
    """
    SHAP-based explanation record for a single credit decision.

    Produced by the ExplainabilityAgent and consumed by:
    - Adverse action letter generators (Reg B compliance)
    - LucidCredit RAG store (for analyst Q&A)
    - Audit trail (immutable record of why a decision was made)
    """

    contract_name: Literal["DecisionExplanationV1"] = "DecisionExplanationV1"

    application_id: str
    tenant_id: str

    decision: DecisionLabelV1

    # Top factors (ordered by |SHAP value| descending)
    top_factors: List[ShapFactorV1] = Field(
        default_factory=list,
        description="Top contributing factors, ranked by absolute SHAP value.",
    )

    # Reg B adverse action narrative (populated only for non-approvals)
    adverse_action_codes: List[str] = Field(
        default_factory=list,
        description="Up to 4 FCRA principal reason codes per Reg B C-1 form.",
    )
    adverse_action_text: Optional[str] = Field(
        None,
        description="Full Reg B adverse action notice text.",
    )

    # Model internals
    pd_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Predicted probability of default [0, 1].",
    )
    pd_band: PDBandV1
    fraud_probability: float = Field(
        ..., ge=0.0, le=1.0,
        description="Model-estimated fraud probability [0, 1].",
    )

    explainer_version: str = "1.0.0"
    model_version: str = Field(
        "champion",
        description="Model variant used: 'champion', 'challenger', or a tag.",
    )
    method: Literal["shap", "lime", "rule_based"] = "shap"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# CreditDecisionV1 — final underwriting verdict
# ---------------------------------------------------------------------------


class CreditDecisionV1(_ContractBaseV1):
    """
    The final credit underwriting decision for one application.

    This is the primary contract consumed by downstream lending products.
    It is immutable once written — any amendment creates a new record with
    a linked ``supersedes_decision_id``.
    """

    contract_name: Literal["CreditDecisionV1"] = "CreditDecisionV1"

    application_id: str = Field(
        ...,
        description="Links back to ApplicationSubmittedV1.application_id.",
    )
    tenant_id: str
    product_type: LoanProductTypeV1

    # Verdict
    decision: DecisionLabelV1
    reason_codes: List[str] = Field(
        default_factory=list,
        description="FCRA reason codes (AA01-AA06 or SHAP_*). "
                    "Max 4 codes per Reg B when decision != APPROVE.",
    )

    # Approved terms (None when decision == REJECT)
    approved_terms: Optional[PricingTermsV1] = None

    # Model metadata
    pd_score: float = Field(..., ge=0.0, le=1.0)
    pd_band: PDBandV1
    fraud_flag: FraudFlagV1

    # Experiment tracking
    experiment_id: Optional[str] = Field(
        None,
        description="A/B test or champion-challenger experiment identifier.",
    )
    policy_version: str = Field(
        "v1",
        description="Policy snapshot used for this decision.",
    )
    model_version: str = "champion"

    # Operational metadata
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    decision_latency_ms: Optional[float] = Field(
        None, ge=0,
        description="End-to-end decisioning latency in milliseconds.",
    )
    supersedes_decision_id: Optional[str] = Field(
        None,
        description="Set when this record amends a prior decision.",
    )


# ---------------------------------------------------------------------------
# DecisionRecordV1 — full decision bundle (decision + explanation + pricing)
# ---------------------------------------------------------------------------


class DecisionRecordV1(_ContractBaseV1):
    """
    Composite bundle of a decision, its explanation, and approved terms.

    Designed for consumers that need the full picture in one payload,
    such as LucidCredit's RAG ingestor or AgentHiveHQ's webhook handler.
    """

    contract_name: Literal["DecisionRecordV1"] = "DecisionRecordV1"

    application_id: str
    tenant_id: str
    product_type: LoanProductTypeV1

    decision: CreditDecisionV1
    explanation: DecisionExplanationV1

    # Pipeline run metadata
    pipeline_run_id: str = Field(
        ...,
        description="Unique identifier for the agent pipeline run that produced this record.",
    )
    total_latency_ms: float = Field(..., ge=0)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
