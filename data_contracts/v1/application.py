"""
data_contracts.v1.application
==============================
Contracts for credit application intake and validation.

Consumers
---------
* LucidCredit  — uses ApplicationSubmittedV1 as RAG ingestion source
* ThinFile     — submits ApplicationSubmittedV1 to the decisioning API
* AgentHiveHQ  — reads ApplicationValidatedV1 from the event bus

Breaking-change policy
----------------------
Adding optional fields is non-breaking (minor bump).
Removing, renaming, or changing types requires a new major version.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LoanProductType(str, Enum):
    CREDIT_CARD = "credit_card"
    PERSONAL_LOAN = "personal_loan"
    MORTGAGE = "mortgage"
    AUTO = "auto"


class EmploymentStatusV1(str, Enum):
    EMPLOYED = "employed"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"
    STUDENT = "student"


class LoanPurposeV1(str, Enum):
    DEBT_CONSOLIDATION = "debt_consolidation"
    HOME_IMPROVEMENT = "home_improvement"
    BUSINESS = "business"
    PERSONAL = "personal"
    AUTO = "auto"
    EDUCATION = "education"
    MEDICAL = "medical"
    OTHER = "other"


class OriginationChannelV1(str, Enum):
    API = "api"
    WEB = "web"
    MOBILE = "mobile"
    BRANCH = "branch"
    PARTNER = "partner"
    BATCH = "batch"


# ---------------------------------------------------------------------------
# Base model — every v1 contract inherits this
# ---------------------------------------------------------------------------


class _ContractBaseV1(BaseModel):
    """Shared metadata fields for all v1 contracts."""

    model_config = ConfigDict(
        extra="ignore",       # tolerate unknown fields from future versions
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal["1.0.0"] = Field(
        "1.0.0",
        description="Contract spec version — must not be changed by consumers.",
    )
    contract_name: str = Field(
        ...,
        description="Canonical contract identifier e.g. 'ApplicationSubmittedV1'.",
    )


# ---------------------------------------------------------------------------
# ApplicantProfileV1 — core demographics and financial snapshot
# ---------------------------------------------------------------------------


class ApplicantProfileV1(_ContractBaseV1):
    """
    Canonical applicant profile used by all underwriting products.

    PII fields are annotated in ``json_schema_extra`` with ``"pii": true``
    so downstream ETL pipelines can apply field-level redaction before
    storing to data warehouses.
    """

    contract_name: Literal["ApplicantProfileV1"] = "ApplicantProfileV1"

    # Identity (PII)
    applicant_id: str = Field(
        ...,
        description="Stable pseudonymous identifier — NOT a SSN or name.",
        json_schema_extra={"pii": False},
    )
    borrower_state: Optional[str] = Field(
        None,
        max_length=2,
        description="2-letter US state code.",
        json_schema_extra={"pii": False},
    )

    # Financial profile
    annual_income: float = Field(
        ..., gt=0, description="Gross annual income in USD."
    )
    employment_status: EmploymentStatusV1
    employer_tenure_months: Optional[float] = Field(
        None, ge=0, description="Months at current employer."
    )
    existing_debt: Optional[float] = Field(
        None, ge=0, description="Total outstanding debt in USD."
    )
    dti: Optional[float] = Field(
        None, ge=0, le=1.0,
        description="Debt-to-income ratio [0, 1]. Derived if not supplied."
    )

    # Credit bureau signals
    credit_score: Optional[float] = Field(
        None, ge=300, le=850, description="VantageScore 3.0 or FICO 8."
    )
    num_open_accounts: Optional[int] = Field(None, ge=0)
    num_derogatory_marks: Optional[int] = Field(None, ge=0)
    months_since_last_delinquency: Optional[float] = Field(None, ge=0)

    # Thin-file alternative data signals
    rent_payment_months: Optional[int] = Field(
        None, ge=0,
        description="Consecutive months of on-time rent payments."
    )
    utility_payment_months: Optional[int] = Field(
        None, ge=0,
        description="Consecutive months of on-time utility payments."
    )
    bank_account_age_months: Optional[int] = Field(None, ge=0)
    avg_monthly_cash_inflow: Optional[float] = Field(None, ge=0)
    avg_monthly_cash_outflow: Optional[float] = Field(None, ge=0)
    mobile_data_score: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Normalised mobile-usage behavioural signal [0, 1]."
    )

    @field_validator("borrower_state")
    @classmethod
    def _state_upper(cls, v: Optional[str]) -> Optional[str]:
        return v.upper() if v else v

    @model_validator(mode="after")
    def _derive_dti(self) -> "ApplicantProfileV1":
        if self.dti is None and self.existing_debt is not None and self.annual_income:
            self.dti = min(self.existing_debt / max(self.annual_income, 1), 1.0)
        return self


# ---------------------------------------------------------------------------
# ApplicationSubmittedV1 — event emitted when an application is received
# ---------------------------------------------------------------------------


class ApplicationSubmittedV1(_ContractBaseV1):
    """
    Emitted by the Decision API (or batch ingestor) immediately after an
    application is received and assigned an ``application_id``.

    This is the entry point for the underwriting pipeline. All downstream
    contracts reference the same ``application_id``.
    """

    contract_name: Literal["ApplicationSubmittedV1"] = "ApplicationSubmittedV1"

    # Routing context
    application_id: str = Field(..., description="Globally unique application identifier.")
    tenant_id: str = Field(
        ...,
        description="Tenant identifier derived from JWT claims — never from request body."
    )
    product_type: LoanProductType
    channel: OriginationChannelV1 = OriginationChannelV1.API
    submitted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the application was received.",
    )

    # Loan request
    loan_amount: float = Field(..., gt=100, lt=500_000, description="Requested loan amount in USD.")
    loan_purpose: LoanPurposeV1
    loan_term_months: int = Field(..., ge=6, le=360)

    # Applicant snapshot
    applicant: ApplicantProfileV1

    # Idempotency
    idempotency_key: Optional[str] = Field(
        None,
        description="Client-supplied key; duplicate submissions with the same key "
                    "are rejected with HTTP 409 rather than double-processed.",
    )


# ---------------------------------------------------------------------------
# ApplicationValidatedV1 — emitted after DataIngestionAgent validates the record
# ---------------------------------------------------------------------------


class ApplicationValidatedV1(_ContractBaseV1):
    """
    Emitted by the data ingestion / validation step. Signals downstream
    agents that the application passed (or failed) quality checks and is
    ready for feature engineering.
    """

    contract_name: Literal["ApplicationValidatedV1"] = "ApplicationValidatedV1"

    application_id: str
    tenant_id: str
    product_type: LoanProductType
    validation_passed: bool
    validation_warnings: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)

    # Enrichment applied during ingestion
    derived_features: Dict[str, Any] = Field(
        default_factory=dict,
        description="Scalar features computed during ingestion (e.g. derived DTI).",
    )
    data_completeness_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of expected feature fields that are non-null.",
    )
    thin_file_flag: bool = Field(
        False,
        description="True when credit_score is absent or <580 and fewer than "
                    "3 bureau trade lines are present — triggers alt-data path.",
    )

    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = Field("api", description="Origination source system.")
