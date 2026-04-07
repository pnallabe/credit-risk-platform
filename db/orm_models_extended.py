"""
SQLAlchemy ORM models — Extended multi-domain schema.

Covers three logical databases:
  - Loans DB      : Customer, LoanProduct, LoanApplication, Loan,
                    LoanPayment, LoanModification, CreditBureauPull
  - Transactions DB: BankAccount, Transaction, AchTransfer,
                    WireTransfer, FraudAlert, DailyBalanceSnapshot
  - Credit Cards DB: CardProduct, CardAccount, CardTransaction,
                    CardStatement, CardDispute, RewardsRedemption,
                    CreditLimitChange

Each "database" maps to a separate SQLAlchemy MetaData / Base so
the models can be used with separate engine connections.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, POINT, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid_pk() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# LOANS DATABASE BASE
# ─────────────────────────────────────────────────────────────────────────────

class LoansBase(DeclarativeBase):
    """Shared base for all Loans-domain ORM models."""


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: Customer
# ─────────────────────────────────────────────────────────────────────────────

class Customer(LoansBase):
    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    ssn_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True, index=True)
    zip_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    annual_income: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True, index=True)
    employment_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    employer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    employer_tenure_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    credit_score: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True, index=True)
    credit_score_model: Mapped[Optional[str]] = mapped_column(String(50), default="FICO8")
    credit_score_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    num_open_accounts: Mapped[Optional[int]] = mapped_column(SmallInteger, default=0)
    num_derogatory_marks: Mapped[Optional[int]] = mapped_column(SmallInteger, default=0)
    total_existing_debt: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), default=0)
    bankruptcy_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    loan_applications: Mapped[List["LoanApplication"]] = relationship(back_populates="customer")
    loans: Mapped[List["Loan"]] = relationship(back_populates="customer")
    bureau_pulls: Mapped[List["CreditBureauPull"]] = relationship(back_populates="customer")

    def __repr__(self) -> str:
        return f"<Customer id={self.customer_id} name={self.first_name} {self.last_name}>"


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: LoanProduct
# ─────────────────────────────────────────────────────────────────────────────

class LoanProduct(LoansBase):
    __tablename__ = "loan_products"
    __table_args__ = (
        CheckConstraint(
            "loan_type IN ('personal','auto','mortgage','student','small_business',"
            "'home_equity','medical','green_energy','debt_consolidation')",
            name="ck_loan_product_type",
        ),
    )

    product_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    product_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    loan_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    min_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    max_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    min_term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    max_term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    base_interest_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    origination_fee_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=0.0)
    prepayment_penalty: Mapped[bool] = mapped_column(Boolean, default=False)
    min_credit_score: Mapped[Optional[int]] = mapped_column(SmallInteger, default=580)
    max_dti_ratio: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), default=0.50)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loan_applications: Mapped[List["LoanApplication"]] = relationship(back_populates="product")
    loans: Mapped[List["Loan"]] = relationship(back_populates="product")


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: LoanApplication
# ─────────────────────────────────────────────────────────────────────────────

class LoanApplication(LoansBase):
    __tablename__ = "loan_applications"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted','under_review','approved','conditionally_approved',"
            "'rejected','withdrawn','funded','closed')",
            name="ck_loan_app_status",
        ),
        CheckConstraint("loan_amount > 0", name="ck_loan_app_amount"),
    )

    application_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.customer_id"), nullable=False, index=True)
    product_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("loan_products.product_id"), nullable=True)
    loan_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, index=True)
    loan_purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    loan_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    loan_term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    requested_interest_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    collateral_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    collateral_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    credit_score_at_app: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    dti_at_app: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    annual_income_at_app: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    existing_debt_at_app: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted", index=True)
    approved_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    approved_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    approved_term_months: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    decision_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_reason_codes: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    channel: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    referral_source: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="loan_applications")
    product: Mapped[Optional["LoanProduct"]] = relationship(back_populates="loan_applications")
    loan: Mapped[Optional["Loan"]] = relationship(back_populates="application")
    bureau_pulls: Mapped[List["CreditBureauPull"]] = relationship(back_populates="application")


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: Loan (funded / active / closed)
# ─────────────────────────────────────────────────────────────────────────────

class Loan(LoansBase):
    __tablename__ = "loans"
    __table_args__ = (
        CheckConstraint(
            "loan_status IN ('current','delinquent_30','delinquent_60','delinquent_90',"
            "'default','charged_off','paid_off','in_forbearance','modified')",
            name="ck_loan_status",
        ),
        CheckConstraint("principal_amount > 0", name="ck_loan_principal"),
        CheckConstraint("interest_rate > 0", name="ck_loan_rate"),
    )

    loan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    application_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("loan_applications.application_id"), unique=True, nullable=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.customer_id"), nullable=False, index=True)
    product_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("loan_products.product_id"), nullable=True)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    interest_rate: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    annual_percentage_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    loan_term_months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    monthly_payment: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    origination_fee: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), default=0)
    origination_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    first_payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    paid_off_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, index=True)
    principal_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    interest_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    loan_status: Mapped[str] = mapped_column(String(30), nullable=False, default="current", index=True)
    days_past_due: Mapped[int] = mapped_column(SmallInteger, default=0, index=True)
    times_30dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    times_60dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    times_90dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    last_payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_payment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    next_payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    application: Mapped[Optional["LoanApplication"]] = relationship(back_populates="loan")
    customer: Mapped["Customer"] = relationship(back_populates="loans")
    product: Mapped[Optional["LoanProduct"]] = relationship(back_populates="loans")
    payments: Mapped[List["LoanPayment"]] = relationship(back_populates="loan", cascade="all, delete-orphan")
    modifications: Mapped[List["LoanModification"]] = relationship(back_populates="loan", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Loan id={self.loan_id} status={self.loan_status} balance={self.current_balance}>"


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: LoanPayment
# ─────────────────────────────────────────────────────────────────────────────

class LoanPayment(LoansBase):
    __tablename__ = "loan_payments"
    __table_args__ = (
        CheckConstraint("payment_amount > 0", name="ck_loan_pmt_amount"),
        CheckConstraint(
            "payment_status IN ('scheduled','posted','returned','reversed','partial')",
            name="ck_loan_pmt_status",
        ),
    )

    payment_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    loan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("loans.loan_id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    principal_portion: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    interest_portion: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    fees_portion: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), default=0)
    payment_status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    days_late: Mapped[int] = mapped_column(SmallInteger, default=0)
    is_prepayment: Mapped[bool] = mapped_column(Boolean, default=False)
    remaining_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    transaction_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loan: Mapped["Loan"] = relationship(back_populates="payments")


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: LoanModification
# ─────────────────────────────────────────────────────────────────────────────

class LoanModification(LoansBase):
    __tablename__ = "loan_modifications"

    modification_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    loan_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("loans.loan_id"), nullable=False, index=True)
    modification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    original_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    modified_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    months_deferred: Mapped[int] = mapped_column(SmallInteger, default=0)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    loan: Mapped["Loan"] = relationship(back_populates="modifications")


# ─────────────────────────────────────────────────────────────────────────────
# LOANS: CreditBureauPull
# ─────────────────────────────────────────────────────────────────────────────

class CreditBureauPull(LoansBase):
    __tablename__ = "credit_bureau_pulls"
    __table_args__ = (
        CheckConstraint("bureau IN ('Equifax','Experian','TransUnion')", name="ck_bureau_name"),
        CheckConstraint("pull_type IN ('hard','soft')", name="ck_pull_type"),
    )

    pull_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("customers.customer_id"), nullable=False, index=True)
    application_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), ForeignKey("loan_applications.application_id"), nullable=True)
    bureau: Mapped[str] = mapped_column(String(20), nullable=False)
    pull_type: Mapped[str] = mapped_column(String(10), nullable=False)
    pull_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    score_returned: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    report_reference: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="bureau_pulls")
    application: Mapped[Optional["LoanApplication"]] = relationship(back_populates="bureau_pulls")


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS DATABASE BASE
# ─────────────────────────────────────────────────────────────────────────────

class TransactionsBase(DeclarativeBase):
    """Shared base for all Transactions-domain ORM models."""


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS: BankAccount
# ─────────────────────────────────────────────────────────────────────────────

class BankAccount(TransactionsBase):
    __tablename__ = "bank_accounts"
    __table_args__ = (
        CheckConstraint(
            "account_type IN ('checking','savings','money_market','cd','brokerage')",
            name="ck_bank_acct_type",
        ),
        CheckConstraint(
            "account_status IN ('active','dormant','closed','frozen','restricted')",
            name="ck_bank_acct_status",
        ),
    )

    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    account_number_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    account_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    routing_number: Mapped[str] = mapped_column(String(9), nullable=False)
    account_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), default="USD")
    current_balance: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0, index=True)
    available_balance: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    overdraft_limit: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    opened_date: Mapped[date] = mapped_column(Date, nullable=False)
    closed_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_activity_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    overdraft_count_30d: Mapped[int] = mapped_column(SmallInteger, default=0)
    nsf_count_90d: Mapped[int] = mapped_column(SmallInteger, default=0)
    suspicious_activity_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<BankAccount id={self.account_id} type={self.account_type} status={self.account_status}>"


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS: Transaction
# ─────────────────────────────────────────────────────────────────────────────

class Transaction(TransactionsBase):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_txn_amount"),
        CheckConstraint(
            "transaction_status IN ('pending','posted','failed','reversed','disputed')",
            name="ck_txn_status",
        ),
        {"postgresql_partition_by": "RANGE (initiated_at)"},
    )

    transaction_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("bank_accounts.account_id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    transaction_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    transaction_category: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    channel: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, index=True)
    currency_code: Mapped[str] = mapped_column(String(3), default="USD")
    amount_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    running_balance: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 2), nullable=True)
    counterparty_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    merchant_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    merchant_category_code: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    merchant_state: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    transaction_status: Mapped[str] = mapped_column(String(20), nullable=False, default="posted")
    initiated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fraud_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    fraud_flag: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    fraud_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reference_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    linked_loan_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    linked_card_id: Mapped[Optional[str]] = mapped_column(UUID(as_uuid=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<Transaction id={self.transaction_id} type={self.transaction_type} amount={self.amount}>"


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS: FraudAlert
# ─────────────────────────────────────────────────────────────────────────────

class FraudAlert(TransactionsBase):
    __tablename__ = "fraud_alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_fraud_severity"),
        CheckConstraint(
            "alert_status IN ('open','under_review','confirmed_fraud','false_positive','closed')",
            name="ck_fraud_status",
        ),
    )

    alert_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    fraud_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    model_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    alert_status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    risk_signals: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    triggered_rules: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    def __repr__(self) -> str:
        return f"<FraudAlert id={self.alert_id} type={self.alert_type} severity={self.severity}>"


# ─────────────────────────────────────────────────────────────────────────────
# CREDIT CARDS DATABASE BASE
# ─────────────────────────────────────────────────────────────────────────────

class CardsBase(DeclarativeBase):
    """Shared base for all Credit-Cards-domain ORM models."""


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: CardProduct
# ─────────────────────────────────────────────────────────────────────────────

class CardProduct(CardsBase):
    __tablename__ = "card_products"
    __table_args__ = (
        CheckConstraint("card_network IN ('Visa','Mastercard','Amex','Discover')", name="ck_card_network"),
    )

    product_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    product_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    product_name: Mapped[str] = mapped_column(String(100), nullable=False)
    card_network: Mapped[str] = mapped_column(String(20), nullable=False)
    card_tier: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    purchase_apr: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    cash_advance_apr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    annual_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    late_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=29)
    min_credit_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=300)
    max_credit_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=100000)
    min_credit_score: Mapped[Optional[int]] = mapped_column(SmallInteger, default=580)
    rewards_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    base_rewards_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 3), default=0.01)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    card_accounts: Mapped[List["CardAccount"]] = relationship(back_populates="product")


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: CardAccount
# ─────────────────────────────────────────────────────────────────────────────

class CardAccount(CardsBase):
    __tablename__ = "card_accounts"
    __table_args__ = (
        CheckConstraint(
            "account_status IN ('pending_activation','active','suspended','closed',"
            "'charged_off','fraud_hold','credit_hold','deceased')",
            name="ck_card_acct_status",
        ),
        CheckConstraint("credit_limit >= 0", name="ck_card_limit"),
    )

    card_account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("card_products.product_id"), nullable=False)
    card_number_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    card_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    card_number_bin: Mapped[str] = mapped_column(String(8), nullable=False)
    card_network: Mapped[str] = mapped_column(String(20), nullable=False)
    card_type: Mapped[str] = mapped_column(String(10), nullable=False)
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    account_open_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    account_close_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    card_expiry_date: Mapped[date] = mapped_column(Date, nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, index=True)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, index=True)
    statement_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    minimum_payment_due: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    payment_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_payment_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_payment_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    autopay_enrolled: Mapped[bool] = mapped_column(Boolean, default=False)
    months_on_book: Mapped[int] = mapped_column(SmallInteger, default=0)
    times_30dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    times_60dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    times_90dpd: Mapped[int] = mapped_column(SmallInteger, default=0)
    current_delinquency_days: Mapped[int] = mapped_column(SmallInteger, default=0, index=True)
    rewards_balance_points: Mapped[int] = mapped_column(Integer, default=0)
    rewards_balance_dollars: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    interest_rate_apr: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    product: Mapped["CardProduct"] = relationship(back_populates="card_accounts")
    statements: Mapped[List["CardStatement"]] = relationship(back_populates="card_account", cascade="all, delete-orphan")
    disputes: Mapped[List["CardDispute"]] = relationship(back_populates="card_account", cascade="all, delete-orphan")
    limit_changes: Mapped[List["CreditLimitChange"]] = relationship(back_populates="card_account", cascade="all, delete-orphan")
    redemptions: Mapped[List["RewardsRedemption"]] = relationship(back_populates="card_account", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<CardAccount id={self.card_account_id} status={self.account_status} limit={self.credit_limit}>"


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: CardStatement
# ─────────────────────────────────────────────────────────────────────────────

class CardStatement(CardsBase):
    __tablename__ = "card_statements"
    __table_args__ = (
        UniqueConstraint("card_account_id", "statement_date", name="uq_card_stmt"),
    )

    statement_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    card_account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("card_accounts.card_account_id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    statement_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    cycle_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    cycle_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    closing_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    statement_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    minimum_payment_due: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total_purchases: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_payments: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total_fees: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    total_interest: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    purchase_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    paid_in_full: Mapped[bool] = mapped_column(Boolean, default=False)
    was_delinquent: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    late_fee_charged: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    rewards_points_earned: Mapped[int] = mapped_column(Integer, default=0)
    credit_limit_at_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2), nullable=True)
    utilization_at_close: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)

    card_account: Mapped["CardAccount"] = relationship(back_populates="statements")


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: CardDispute
# ─────────────────────────────────────────────────────────────────────────────

class CardDispute(CardsBase):
    __tablename__ = "card_disputes"
    __table_args__ = (
        CheckConstraint(
            "dispute_status IN ('filed','under_review','provisional_credit',"
            "'resolved_cardholder','resolved_merchant','withdrawn','escalated')",
            name="ck_dispute_status",
        ),
    )

    dispute_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    card_account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("card_accounts.card_account_id"), nullable=False, index=True)
    card_txn_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    dispute_reason: Mapped[str] = mapped_column(String(50), nullable=False)
    dispute_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    dispute_status: Mapped[str] = mapped_column(String(20), nullable=False, default="filed", index=True)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    resolution_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    final_outcome: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    card_account: Mapped["CardAccount"] = relationship(back_populates="disputes")


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: CreditLimitChange
# ─────────────────────────────────────────────────────────────────────────────

class CreditLimitChange(CardsBase):
    __tablename__ = "credit_limit_changes"

    change_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    card_account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("card_accounts.card_account_id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    change_type: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    new_limit: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credit_score_at_change: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    card_account: Mapped["CardAccount"] = relationship(back_populates="limit_changes")


# ─────────────────────────────────────────────────────────────────────────────
# CARDS: RewardsRedemption
# ─────────────────────────────────────────────────────────────────────────────

class RewardsRedemption(CardsBase):
    __tablename__ = "rewards_redemptions"

    redemption_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid_pk)
    card_account_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("card_accounts.card_account_id"), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False)
    redemption_type: Mapped[str] = mapped_column(String(30), nullable=False)
    points_redeemed: Mapped[int] = mapped_column(Integer, default=0)
    dollars_redeemed: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    redemption_value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    redemption_status: Mapped[str] = mapped_column(String(20), default="completed")
    partner_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    card_account: Mapped["CardAccount"] = relationship(back_populates="redemptions")
