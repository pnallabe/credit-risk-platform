"""
Pydantic models for ingestion API validation
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import List, Optional
from datetime import datetime
from decimal import Decimal


class Transaction(BaseModel):
    """Individual transaction model"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    transaction_id: str = Field(..., description="Unique transaction identifier")
    account_id: str = Field(..., description="Account identifier")
    customer_id: Optional[str] = Field(None, description="Customer identifier")
    
    amount: Decimal = Field(..., description="Transaction amount")
    currency: str = Field(default="USD", description="Currency code (ISO 4217)")
    
    posted_at: datetime = Field(..., description="Transaction posting timestamp")
    description: Optional[str] = Field(None, max_length=500, description="Transaction description")
    
    mcc: Optional[str] = Field(None, description="Merchant Category Code")
    counterparty: Optional[str] = Field(None, max_length=200, description="Counterparty name")
    
    transaction_type: str = Field(..., description="Type: debit, credit, transfer, etc.")
    channel: Optional[str] = Field(None, description="Channel: online, atm, branch, etc.")
    
    @field_validator('currency')
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency code"""
        if len(v) != 3:
            raise ValueError('Currency must be 3-character ISO code')
        return v.upper()
    
    @field_validator('transaction_type')
    @classmethod
    def validate_transaction_type(cls, v: str) -> str:
        """Validate transaction type"""
        valid_types = {'debit', 'credit', 'transfer', 'fee', 'interest', 'adjustment'}
        if v.lower() not in valid_types:
            raise ValueError(f'Transaction type must be one of: {valid_types}')
        return v.lower()


class TransactionBatch(BaseModel):
    """Batch of transactions from a source system"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    source: str = Field(..., description="Source system identifier")
    batch_id: Optional[str] = Field(None, description="Source system batch identifier")
    transactions: List[Transaction] = Field(..., min_length=1, description="List of transactions")
    
    @field_validator('transactions')
    @classmethod
    def validate_transaction_count(cls, v: List[Transaction]) -> List[Transaction]:
        """Validate batch size"""
        if len(v) > 10000:
            raise ValueError('Batch size cannot exceed 10,000 transactions')
        return v


class LoanApplication(BaseModel):
    """Individual loan application model"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    application_id: str = Field(..., description="Unique application identifier")
    customer_id: str = Field(..., description="Customer identifier")
    account_id: Optional[str] = Field(None, description="Linked account identifier")
    
    # Loan details
    loan_amount: Decimal = Field(..., gt=0, description="Requested loan amount")
    loan_purpose: str = Field(..., description="Purpose of loan")
    loan_term_months: int = Field(..., gt=0, le=360, description="Loan term in months")
    interest_rate: Optional[Decimal] = Field(None, ge=0, le=100, description="Interest rate percentage")
    
    # Applicant information
    annual_income: Optional[Decimal] = Field(None, ge=0, description="Annual income")
    employment_status: Optional[str] = Field(None, description="Employment status")
    employment_length_months: Optional[int] = Field(None, ge=0, description="Months with current employer")
    
    # Credit information
    credit_score: Optional[int] = Field(None, ge=300, le=850, description="Credit score")
    existing_debt: Optional[Decimal] = Field(None, ge=0, description="Existing debt amount")
    
    # Application metadata
    applied_at: datetime = Field(..., description="Application submission timestamp")
    channel: Optional[str] = Field(None, description="Application channel")
    
    @field_validator('loan_purpose')
    @classmethod
    def validate_loan_purpose(cls, v: str) -> str:
        """Validate loan purpose"""
        valid_purposes = {
            'personal', 'business', 'home_improvement', 'debt_consolidation',
            'auto', 'education', 'medical', 'other'
        }
        v_lower = v.lower().replace(' ', '_')
        if v_lower not in valid_purposes:
            raise ValueError(f'Loan purpose must be one of: {valid_purposes}')
        return v_lower


class ApplicationBatch(BaseModel):
    """Batch of loan applications from a source system"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    source: str = Field(..., description="Source system identifier")
    batch_id: Optional[str] = Field(None, description="Source system batch identifier")
    applications: List[LoanApplication] = Field(..., min_length=1, description="List of applications")
    
    @field_validator('applications')
    @classmethod
    def validate_application_count(cls, v: List[LoanApplication]) -> List[LoanApplication]:
        """Validate batch size"""
        if len(v) > 1000:
            raise ValueError('Batch size cannot exceed 1,000 applications')
        return v


class IngestionResponse(BaseModel):
    """Response model for successful ingestion"""
    model_config = ConfigDict(str_strip_whitespace=True)
    
    status: str = Field(..., description="Status: success or error")
    gcs_uri: str = Field(..., description="GCS URI where data was stored")
    message_id: Optional[str] = Field(None, description="Pub/Sub message ID")
    record_count: int = Field(..., description="Number of records ingested")
    ingested_at: datetime = Field(..., description="Ingestion timestamp")