"""
SQLAlchemy ORM models that mirror the Credit Risk Platform DB schema.

Usage (async engine example):

    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from db.orm_models import Base

    engine = create_async_engine("postgresql+asyncpg://user:pass@host/credit_risk")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """Shared base class for all ORM models."""


# ---------------------------------------------------------------------------
# Helper: UUID primary key default
# ---------------------------------------------------------------------------


def _uuid_pk() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# loan_applications
# ---------------------------------------------------------------------------


class LoanApplication(Base):
    """Raw loan application intake record."""

    __tablename__ = "loan_applications"
    __table_args__ = (
        CheckConstraint("loan_amount > 0", name="ck_loan_apps_loan_amount_positive"),
        CheckConstraint(
            "loan_term_months IN (12, 24, 36, 48, 60)",
            name="ck_loan_apps_loan_term",
        ),
        CheckConstraint(
            "employment_status IN ('employed','self-employed','unemployed','retired')",
            name="ck_loan_apps_employment_status",
        ),
        CheckConstraint(
            "credit_score BETWEEN 300 AND 850",
            name="ck_loan_apps_credit_score",
        ),
        CheckConstraint(
            "debt_to_income_ratio BETWEEN 0 AND 0.65",
            name="ck_loan_apps_dti",
        ),
    )

    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid_pk
    )
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    account_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)

    # Loan details
    loan_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    loan_purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    loan_term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    interest_rate: Mapped[Optional[float]] = mapped_column(Numeric(6, 4), nullable=True)

    # Applicant information
    annual_income: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    employment_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    employer_tenure_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Credit information
    credit_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    debt_to_income_ratio: Mapped[Optional[float]] = mapped_column(Numeric(5, 4), nullable=True)
    existing_debt_amount: Mapped[Optional[float]] = mapped_column(Numeric(14, 2), nullable=True)
    num_open_accounts: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    num_derogatory_marks: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    months_since_last_delinquency: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Geography
    state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    zip_code_prefix: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    # Metadata
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    channel: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    features: Mapped[List["Feature"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    predictions: Mapped[List["ModelPrediction"]] = relationship(back_populates="application", cascade="all, delete-orphan")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="application")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LoanApplication id={self.application_id} amount={self.loan_amount}>"


# ---------------------------------------------------------------------------
# features
# ---------------------------------------------------------------------------


class Feature(Base):
    """Feature store entry — computed features per application version."""

    __tablename__ = "features"
    __table_args__ = (
        UniqueConstraint(
            "application_id", "feature_set_version", name="uq_features_app_version"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_applications.application_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_set_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Engineered features
    credit_utilization: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)
    income_stability_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)
    repayment_capacity: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)
    debt_service_coverage_ratio: Mapped[Optional[float]] = mapped_column(Numeric(12, 4), nullable=True)
    credit_age_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_history_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)

    # Catch-all bucket for additional features
    feature_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships
    application: Mapped["LoanApplication"] = relationship(back_populates="features")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Feature app={self.application_id} "
            f"version={self.feature_set_version}>"
        )


# ---------------------------------------------------------------------------
# model_predictions
# ---------------------------------------------------------------------------


class ModelPrediction(Base):
    """One-row-per-model-inference record."""

    __tablename__ = "model_predictions"
    __table_args__ = (
        CheckConstraint("score BETWEEN 0 AND 1", name="ck_predictions_score"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_predictions_confidence"),
    )

    prediction_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid_pk
    )
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_applications.application_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    score: Mapped[float] = mapped_column(Numeric(8, 6), nullable=False)
    label: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)
    metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Relationships
    application: Mapped["LoanApplication"] = relationship(back_populates="predictions")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ModelPrediction id={self.prediction_id} "
            f"model={self.model_name}@{self.model_version} "
            f"score={self.score}>"
        )


# ---------------------------------------------------------------------------
# audit_log
# ---------------------------------------------------------------------------


class AuditLog(Base):
    """Append-only FCRA-compliant decision audit trail."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "decision_output IN ('APPROVE','REJECT','MANUAL_REVIEW')",
            name="ck_audit_decision_output",
        ),
    )

    log_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid_pk
    )
    application_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("loan_applications.application_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    logged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Versioning snapshot
    input_features: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Scores
    fraud_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)
    risk_score: Mapped[Optional[float]] = mapped_column(Numeric(8, 6), nullable=True)

    # Decision
    decision_output: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    decision_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Relationships
    application: Mapped["LoanApplication"] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AuditLog id={self.log_id} "
            f"decision={self.decision_output} "
            f"app={self.application_id}>"
        )


# ---------------------------------------------------------------------------
# model_registry
# ---------------------------------------------------------------------------


class ModelRegistry(Base):
    """ML model governance and lineage table."""

    __tablename__ = "model_registry"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','approved','deprecated')",
            name="ck_model_registry_status",
        ),
        UniqueConstraint(
            "model_name", "model_version", name="uq_model_registry_name_version"
        ),
    )

    model_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid_pk
    )
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate", index=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    performance_metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<ModelRegistry name={self.model_name} "
            f"version={self.model_version} "
            f"status={self.status}>"
        )
