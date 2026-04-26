"""
data_contracts.v1.portfolio
=============================
Contracts for portfolio analytics: vintage curves, roll rates, approval/profit
by segment, and aggregate portfolio summaries.

Consumers
---------
* LucidCredit  — ingests portfolio summaries for analyst Q&A
* AgentHiveHQ  — reads PortfolioSummaryV1 for executive dashboards
* ThinFile     — uses VintageCohortV1 for model backtesting

Data source
-----------
These contracts mirror the analytics served by ``analytics_api/src/main.py``
endpoints:
  GET /v1/analytics/vintage-curves
  GET /v1/analytics/roll-rates
  GET /v1/analytics/approval-profit
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ProductTypeV1(str, Enum):
    CREDIT_CARD = "credit_card"
    PERSONAL_LOAN = "personal_loan"
    MORTGAGE = "mortgage"
    AUTO = "auto"
    ALL = "all"


class DelinquencyBucketV1(str, Enum):
    CURRENT = "current"          # 0 DPD
    DPD_1_29 = "1-29"           # 1–29 days past due
    DPD_30_59 = "30-59"         # 30–59 DPD
    DPD_60_89 = "60-89"         # 60–89 DPD
    DPD_90_119 = "90-119"       # 90–119 DPD
    DPD_120_PLUS = "120+"       # 120+ DPD
    CHARGED_OFF = "charged_off"  # written off


class FicoBandV1(str, Enum):
    SUB_580 = "sub_580"
    BAND_580_619 = "580-619"
    BAND_620_659 = "620-659"
    BAND_660_719 = "660-719"
    BAND_720_PLUS = "720+"


class DtiBandV1(str, Enum):
    BAND_0_20 = "0-20%"
    BAND_20_36 = "20-36%"
    BAND_36_50 = "36-50%"
    BAND_50_PLUS = "50%+"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ContractBaseV1(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract_name: str = Field(...)


# ---------------------------------------------------------------------------
# VintageCohortV1 — performance for a single origination cohort over time
# ---------------------------------------------------------------------------


class VintageDataPointV1(BaseModel):
    """One performance observation for a cohort at a given months-on-book age."""

    model_config = ConfigDict(extra="ignore")

    mob: int = Field(..., ge=0, description="Months on book.")
    calendar_date: date = Field(..., description="Calendar date of this observation.")

    n_accounts: int = Field(..., ge=0)
    n_defaults: int = Field(..., ge=0)
    cumulative_default_rate: float = Field(..., ge=0.0, le=1.0)
    net_loss_rate: float = Field(..., ge=0.0, description="Net loss rate = net charge-offs / avg outstanding balance.")
    avg_balance_usd: Optional[float] = Field(None, ge=0.0)


class VintageCohortV1(_ContractBaseV1):
    """
    Cumulative default and loss performance for a single origination month cohort.

    A 'vintage' is all accounts originated in a given calendar month.
    Curves are indexed by months-on-book (MOB) to allow cross-vintage comparison.
    """

    contract_name: Literal["VintageCohortV1"] = "VintageCohortV1"

    tenant_id: str
    product_type: ProductTypeV1
    vintage_month: date = Field(
        ...,
        description="First day of the origination month (e.g. 2023-01-01).",
    )
    fico_band: Optional[FicoBandV1] = Field(
        None,
        description="If set, this cohort is scoped to a single FICO band.",
    )

    n_originated: int = Field(..., ge=0, description="Total accounts originated in this vintage.")
    total_originated_usd: float = Field(..., ge=0.0, description="Total originated balance in USD.")
    avg_credit_score: Optional[float] = Field(None, ge=300.0, le=850.0)
    avg_dti: Optional[float] = Field(None, ge=0.0, le=1.0)

    data_points: List[VintageDataPointV1] = Field(
        default_factory=list,
        description="Time series of performance by MOB.",
    )

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# RollRateBucketV1 — monthly delinquency transition matrix
# ---------------------------------------------------------------------------


class RollRateTransitionV1(BaseModel):
    """Transition counts and rate for one bucket pair in a roll-rate matrix."""

    model_config = ConfigDict(extra="ignore")

    from_bucket: DelinquencyBucketV1
    to_bucket: DelinquencyBucketV1
    n_accounts: int = Field(..., ge=0)
    transition_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of 'from_bucket' accounts that moved to 'to_bucket'.",
    )


class RollRateBucketV1(_ContractBaseV1):
    """
    Monthly roll-rate matrix showing delinquency bucket transitions.

    Used to monitor early warning signals for portfolio deterioration.
    Specifically: forward roll rates (current → delinquent) and
    cure rates (delinquent → current).
    """

    contract_name: Literal["RollRateBucketV1"] = "RollRateBucketV1"

    tenant_id: str
    product_type: ProductTypeV1
    observation_month: date = Field(
        ...,
        description="First day of the month for which transitions were observed.",
    )

    n_accounts_observed: int = Field(..., ge=0)
    transitions: List[RollRateTransitionV1] = Field(default_factory=list)

    # Headline roll rates for quick monitoring
    forward_roll_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description="Current-to-delinquent roll rate: fraction of current accounts "
                    "that became 30+ DPD in this month.",
    )
    cure_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of 30–89 DPD accounts that returned to current.",
    )
    charge_off_rate: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of 120+ DPD accounts that were charged off.",
    )

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# SegmentBreakdownV1 — approval rate and expected profit by segment
# ---------------------------------------------------------------------------


class SegmentMetricV1(BaseModel):
    """Metrics for one segment slice (e.g. FICO 660-719, DTI 20-36%)."""

    model_config = ConfigDict(extra="ignore")

    segment_dimension: str = Field(
        ...,
        description="Dimension name: 'fico_band', 'dti_band', 'product_type', 'channel', etc.",
    )
    segment_value: str = Field(..., description="Value within the dimension.")

    n_applications: int = Field(..., ge=0)
    n_approved: int = Field(..., ge=0)
    approval_rate: float = Field(..., ge=0.0, le=1.0)

    avg_approved_amount: Optional[float] = Field(None, ge=0.0)
    avg_approved_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    avg_pd_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    avg_expected_loss_usd: Optional[float] = Field(None, ge=0.0)
    avg_expected_profit_usd: Optional[float] = None
    total_expected_profit_usd: Optional[float] = None


class SegmentBreakdownV1(_ContractBaseV1):
    """
    Approval rate and profitability breakdown by segment.

    Segments are orthogonal slices (not cross-tabs). Consumers that need
    cross-tab analysis should query the analytics API directly.
    """

    contract_name: Literal["SegmentBreakdownV1"] = "SegmentBreakdownV1"

    tenant_id: str
    product_type: ProductTypeV1
    reporting_period_start: date
    reporting_period_end: date

    segments: List[SegmentMetricV1] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# PortfolioSummaryV1 — aggregate portfolio health snapshot
# ---------------------------------------------------------------------------


class PortfolioSummaryV1(_ContractBaseV1):
    """
    Aggregate portfolio health snapshot for a given reporting period.

    This is the top-level contract for portfolio-level consumers.
    It bundles headline metrics and links to detail contracts.

    Published by the analytics job on a configurable cadence
    (daily for operational, monthly for regulatory).
    """

    contract_name: Literal["PortfolioSummaryV1"] = "PortfolioSummaryV1"

    tenant_id: str
    product_type: ProductTypeV1
    reporting_period_start: date
    reporting_period_end: date

    # Volume metrics
    n_applications: int = Field(..., ge=0)
    n_approved: int = Field(..., ge=0)
    n_rejected: int = Field(..., ge=0)
    n_manual_review: int = Field(..., ge=0)
    approval_rate: float = Field(..., ge=0.0, le=1.0)

    # Balance metrics
    total_originated_usd: float = Field(..., ge=0.0)
    avg_loan_size_usd: Optional[float] = Field(None, ge=0.0)
    avg_approved_rate: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Risk metrics
    avg_pd_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    avg_credit_score: Optional[float] = Field(None, ge=300.0, le=850.0)
    avg_dti: Optional[float] = Field(None, ge=0.0, le=1.0)
    thin_file_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Fraction of approved accounts with thin-file flag.",
    )

    # Performance (trailing)
    bad_rate_30dpd: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Fraction of active accounts ≥30 DPD.",
    )
    bad_rate_90dpd: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Fraction of active accounts ≥90 DPD.",
    )
    net_charge_off_rate: Optional[float] = Field(None, ge=0.0)

    # Profitability
    total_expected_profit_usd: Optional[float] = None
    total_expected_loss_usd: Optional[float] = Field(None, ge=0.0)

    # Policy metadata
    policy_version: str = "v1"
    model_version: str = "champion"

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Breakdown references (IDs of companion SegmentBreakdownV1 records)
    segment_breakdown_ids: List[str] = Field(
        default_factory=list,
        description="IDs of companion SegmentBreakdownV1 records for drill-down.",
    )
