"""
data_contracts
==============
Versioned, typed data contracts for the credit-risk-platform.

These contracts define the canonical shape of every data asset that the
platform exposes to external products (LucidCredit, ThinFile, AgentHiveHQ, etc.).

Usage
-----
>>> from data_contracts.v1 import (
...     ApplicationSubmittedV1,
...     CreditDecisionV1,
...     FeatureVectorV1,
...     PortfolioSummaryV1,
...     DecisionAuditRecordV1,
...     DataContractEvent,
... )

>>> from data_contracts.registry import DataContractRegistry
>>> registry = DataContractRegistry()
>>> json_schema = registry.export_json_schema("CreditDecisionV1")

Design principles
-----------------
1. **Immutable once published** — a published version is never mutated.
   Additive changes land in a new minor; breaking changes bump the major.
2. **Tenant-scoped** — every top-level record carries ``tenant_id``.
3. **Self-describing** — every record carries ``schema_version`` and
   ``contract_name`` so consumers can validate without out-of-band metadata.
4. **No PII in logs** — sensitive fields are annotated with ``pii=True``
   in the ``json_schema_extra`` so downstream ETL can redact them.
5. **Forward-compatible** — optional fields default to ``None``; consumers
   must tolerate unknown fields (``model_config = ConfigDict(extra="ignore")``
   on read models).
"""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("credit-risk-platform")
except PackageNotFoundError:
    __version__ = "0.0.0"

CONTRACTS_SPEC_VERSION = "1.0.0"

from data_contracts.v1 import (  # noqa: E402  (re-export for convenience)
    # Application
    LoanProductType,
    ApplicantProfileV1,
    ApplicationSubmittedV1,
    ApplicationValidatedV1,
    # Decisions
    DecisionLabelV1,
    PricingTermsV1,
    DecisionExplanationV1,
    CreditDecisionV1,
    DecisionRecordV1,
    # Features
    FeatureVectorV1,
    FeatureDriftReportV1,
    ModelPerformanceSnapshotV1,
    # Portfolio
    VintageCohortV1,
    RollRateBucketV1,
    SegmentBreakdownV1,
    PortfolioSummaryV1,
    # Compliance
    AdverseActionNoticeV1,
    HMDARecordV1,
    Metro2TradelineV1,
    FairLendingFlagV1,
    # Features (additional)
    DriftStatusV1,
    ModelVariantV1,
    # Audit
    DecisionAuditRecordV1,
    PolicyChangeAuditV1,
    ModelDeploymentAuditV1,
    ManualReviewRecordV1,
    # Events
    DataContractEvent,
    ApplicationSubmittedEvent,
    DecisionMadeEvent,
    BatchCompleteEvent,
    DriftAlertEvent,
    PolicyChangedEvent,
)

__all__ = [
    "CONTRACTS_SPEC_VERSION",
    "LoanProductType",
    "ApplicantProfileV1",
    "ApplicationSubmittedV1",
    "ApplicationValidatedV1",
    "DecisionLabelV1",
    "PricingTermsV1",
    "DecisionExplanationV1",
    "CreditDecisionV1",
    "DecisionRecordV1",
    "DriftStatusV1",
    "ModelVariantV1",
    "FeatureVectorV1",
    "FeatureDriftReportV1",
    "ModelPerformanceSnapshotV1",
    "VintageCohortV1",
    "RollRateBucketV1",
    "SegmentBreakdownV1",
    "PortfolioSummaryV1",
    "AdverseActionNoticeV1",
    "HMDARecordV1",
    "Metro2TradelineV1",
    "FairLendingFlagV1",
    "DecisionAuditRecordV1",
    "PolicyChangeAuditV1",
    "ModelDeploymentAuditV1",
    "ManualReviewRecordV1",
    "DataContractEvent",
    "ApplicationSubmittedEvent",
    "DecisionMadeEvent",
    "BatchCompleteEvent",
    "DriftAlertEvent",
    "PolicyChangedEvent",
]
