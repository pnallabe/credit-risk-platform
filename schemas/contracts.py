"""
Agent I/O Data Contracts
=========================
Pydantic models define the typed interface between agents.
No agent may pass raw dicts across boundaries — it must use these schemas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Tenant context (P0.1 — multi-tenant isolation)
# ---------------------------------------------------------------------------


class TenantContext(BaseModel):
    """Mandatory tenant scoping attached to every API request and pipeline run.

    ``tenant_id`` is derived exclusively from the JWT claims — it MUST NOT
    be accepted from the request body to prevent tenant spoofing.
    ``request_id`` is a client-supplied idempotency identifier.
    """

    tenant_id: str = Field(..., description="Opaque tenant identifier from JWT claims")
    environment: Literal["dev", "staging", "prod"] = Field(
        "dev", description="Deployment environment"
    )
    request_id: str = Field(..., description="Client-supplied idempotency / correlation id")


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class EmploymentStatus(str, Enum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"
    STUDENT = "student"


class LoanPurpose(str, Enum):
    DEBT_CONSOLIDATION = "debt_consolidation"
    HOME_IMPROVEMENT = "home_improvement"
    BUSINESS = "business"
    PERSONAL = "personal"
    AUTO = "auto"
    EDUCATION = "education"
    MEDICAL = "medical"
    OTHER = "other"


class DecisionLabel(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class FraudFlag(str, Enum):
    CONTINUE = "continue"
    MANUAL_REVIEW = "manual_review"
    REJECT = "reject"


class PDband(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# 1. Applicant Input — canonical thin-file schema
# ---------------------------------------------------------------------------


class ApplicantInput(BaseModel):
    """
    Canonical input for a thin-file credit applicant.
    Sparse by design — many fields optional to support alt-data underwriting.
    """

    application_id: str = Field(..., description="Unique application identifier")
    loan_amount: float = Field(..., gt=100, lt=500_000)
    loan_purpose: LoanPurpose
    loan_term_months: int = Field(..., ge=6, le=360)
    annual_income: float = Field(..., gt=0)
    employment_status: EmploymentStatus
    employer_tenure_months: Optional[float] = Field(None, ge=0)
    dti: Optional[float] = Field(None, ge=0, le=1.0, description="Debt-to-income ratio")
    existing_debt: Optional[float] = Field(None, ge=0)
    credit_score: Optional[float] = Field(None, ge=300, le=850)
    num_open_accounts: Optional[int] = Field(None, ge=0)
    num_derogatory_marks: Optional[int] = Field(None, ge=0)
    months_since_last_delinquency: Optional[float] = Field(None, ge=0)
    borrower_state: Optional[str] = Field(None, max_length=2)
    channel: Optional[str] = Field("api", description="origination channel")

    # Thin-file alt-data signals
    rent_payment_months: Optional[int] = Field(None, ge=0, description="Months of on-time rent")
    utility_payment_months: Optional[int] = Field(None, ge=0, description="Months of on-time utilities")
    mobile_data_score: Optional[float] = Field(None, ge=0, le=1.0, description="Normalised mobile usage signal")
    bank_account_age_months: Optional[int] = Field(None, ge=0)
    avg_monthly_cash_inflow: Optional[float] = Field(None, ge=0, description="Average monthly bank inflow (USD)")
    avg_monthly_cash_outflow: Optional[float] = Field(None, ge=0, description="Average monthly bank outflow (USD)")

    # --- Enriched cash-flow fields (from open-banking enrichment layer) ---
    monthly_net_income: Optional[float] = Field(
        None, ge=0, description="Net monthly income from open-banking enrichment (USD)"
    )
    avg_monthly_end_balance: Optional[float] = Field(
        None, ge=0, description="Average end-of-month balance over lookback window (USD)"
    )
    min_balance_90d: Optional[float] = Field(
        None, description="Minimum balance observed in last 90 days (USD); can be negative (overdraft)"
    )
    nsfv_last_90_days: Optional[int] = Field(
        None, ge=0, description="NSF / insufficient-funds events in last 90 days"
    )
    returned_payment_count: Optional[int] = Field(
        None, ge=0, description="Number of returned payments in lookback window"
    )
    gambling_transaction_count: Optional[int] = Field(
        None, ge=0, description="Number of gambling-category transactions detected"
    )
    payday_loan_detected: Optional[bool] = Field(
        None, description="Whether a payday loan transaction was detected"
    )
    large_unusual_deposit_count: Optional[int] = Field(
        None, ge=0, description="Number of large or unusual deposit events (>3x avg monthly inflow)"
    )
    income_confidence: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Confidence score for income estimation (0–1)"
    )
    bank_enrichment_provider: Optional[str] = Field(
        None, max_length=64, description="Provider used for bank enrichment (plaid, obp, mock, etc.)"
    )

    @field_validator("nsfv_last_90_days", "returned_payment_count",
                     "gambling_transaction_count", "large_unusual_deposit_count")
    @classmethod
    def non_negative_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Field must be >= 0")
        return v

    @field_validator("borrower_state")
    @classmethod
    def state_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v

    @model_validator(mode="after")
    def derive_dti(self) -> "ApplicantInput":
        """Derive DTI from existing_debt / annual_income when not supplied."""
        if self.dti is None and self.existing_debt is not None and self.annual_income:
            self.dti = min(self.existing_debt / max(self.annual_income, 1), 1.0)
        return self


# ---------------------------------------------------------------------------
# 2. Validated Ingestion Record — output of DataIngestionAgent
# ---------------------------------------------------------------------------


class ValidatedRecord(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    raw_features: Dict[str, Any]
    validation_passed: bool
    validation_warnings: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "api"


# ---------------------------------------------------------------------------
# 3. Feature Vector — output of FeatureEngineeringAgent
# ---------------------------------------------------------------------------


class FeatureVector(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    features: Dict[str, float]
    feature_version: str = "1.0.0"
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    thin_file_signals_used: bool = False


# ---------------------------------------------------------------------------
# 4. Model Scores — output of RiskModelingAgent
# ---------------------------------------------------------------------------


class ModelScores(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    pd_score: float = Field(..., ge=0.0, le=1.0)
    pd_band: PDband
    fraud_probability: float = Field(..., ge=0.0, le=1.0)
    fraud_flag: FraudFlag
    recommended_rate: Optional[float] = Field(None, ge=0.0)
    expected_loss: Optional[float] = Field(None, ge=0.0)
    expected_profit: Optional[float] = None
    model_version: str = "champion"
    scored_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 5. Credit Decision — output of DecisionEngineAgent
# ---------------------------------------------------------------------------


class CreditDecision(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    decision: DecisionLabel
    reason_codes: List[str] = Field(default_factory=list)
    approved_amount: Optional[float] = None
    approved_rate: Optional[float] = None
    approved_term_months: Optional[int] = None
    experiment_id: Optional[str] = None
    policy_version: str = "v1"
    decided_at: datetime = Field(default_factory=datetime.utcnow)
    decision_latency_ms: Optional[float] = None


# ---------------------------------------------------------------------------
# 6. Explanation Record — output of ExplainabilityAgent
# ---------------------------------------------------------------------------


class ExplanationRecord(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    decision: DecisionLabel
    top_factors: List[Dict[str, Any]] = Field(default_factory=list)
    adverse_action_text: Optional[str] = None
    shap_values: Optional[Dict[str, float]] = None
    method: str = "shap"
    explainer_version: str = "1.0.0"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# 7. End-to-end Decision Output — pipeline final output
# ---------------------------------------------------------------------------


class PipelineOutput(BaseModel):
    application_id: str
    tenant_id: str = Field(..., description="Tenant identifier propagated from TenantContext")
    input: ApplicantInput
    scores: ModelScores
    decision: CreditDecision
    explanation: ExplanationRecord
    pipeline_run_id: str
    total_latency_ms: float
    completed_at: datetime = Field(default_factory=datetime.utcnow)
