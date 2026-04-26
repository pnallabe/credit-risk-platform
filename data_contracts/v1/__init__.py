"""
data_contracts.v1
==================
Version 1 of all credit-risk-platform data contracts.

Import any contract directly from this package:

    from data_contracts.v1 import CreditDecisionV1, PortfolioSummaryV1

All models are Pydantic v2 BaseModels with:
  - ``schema_version = "1.0.0"`` (fixed Literal)
  - ``contract_name`` (fixed Literal on every concrete model)
  - ``model_config = ConfigDict(extra="ignore")`` — tolerates unknown fields
    from future minor versions
"""

from data_contracts.v1.application import (
    LoanProductType,
    EmploymentStatusV1,
    LoanPurposeV1,
    OriginationChannelV1,
    ApplicantProfileV1,
    ApplicationSubmittedV1,
    ApplicationValidatedV1,
)

from data_contracts.v1.decisions import (
    DecisionLabelV1,
    FraudFlagV1,
    PDBandV1,
    PricingTermsV1,
    ShapFactorV1,
    DecisionExplanationV1,
    CreditDecisionV1,
    DecisionRecordV1,
)

from data_contracts.v1.features import (
    DriftStatusV1,
    ModelVariantV1,
    FeatureVectorV1,
    FeatureDriftResultV1,
    FeatureDriftReportV1,
    ModelPerformanceSnapshotV1,
)

from data_contracts.v1.portfolio import (
    ProductTypeV1,
    DelinquencyBucketV1,
    FicoBandV1,
    DtiBandV1,
    VintageDataPointV1,
    VintageCohortV1,
    RollRateTransitionV1,
    RollRateBucketV1,
    SegmentMetricV1,
    SegmentBreakdownV1,
    PortfolioSummaryV1,
)

from data_contracts.v1.compliance import (
    ActionTakenV1,
    DenialReasonV1,
    RaceCodeV1,
    EthnicityCodeV1,
    SexCodeV1,
    Metro2AccountStatusV1,
    DisparateImpactStatusV1,
    AdverseActionNoticeV1,
    HMDARecordV1,
    Metro2TradelineV1,
    FairLendingFlagV1,
)

from data_contracts.v1.audit import (
    AuditActionV1,
    PolicyChangeTypeV1,
    ModelDeploymentActionV1,
    ReviewOutcomeV1,
    PipelineStepAuditV1,
    DecisionAuditRecordV1,
    PolicyChangeAuditV1,
    ModelDeploymentAuditV1,
    ManualReviewRecordV1,
)

from data_contracts.v1.events import (
    EventTypeV1,
    DataContractEvent,
    ApplicationSubmittedPayloadV1,
    ApplicationValidatedPayloadV1,
    DecisionMadePayloadV1,
    BatchCompletePayloadV1,
    BatchFailedPayloadV1,
    DriftAlertPayloadV1,
    ModelPromotedPayloadV1,
    PolicyChangedPayloadV1,
    AdverseActionGeneratedPayloadV1,
    FairLendingFlagPayloadV1,
    ApplicationSubmittedEvent,
    DecisionMadeEvent,
    BatchCompleteEvent,
    DriftAlertEvent,
    PolicyChangedEvent,
)

__all__ = [
    # Application
    "LoanProductType",
    "EmploymentStatusV1",
    "LoanPurposeV1",
    "OriginationChannelV1",
    "ApplicantProfileV1",
    "ApplicationSubmittedV1",
    "ApplicationValidatedV1",
    # Decisions
    "DecisionLabelV1",
    "FraudFlagV1",
    "PDBandV1",
    "PricingTermsV1",
    "ShapFactorV1",
    "DecisionExplanationV1",
    "CreditDecisionV1",
    "DecisionRecordV1",
    # Features
    "DriftStatusV1",
    "ModelVariantV1",
    "FeatureVectorV1",
    "FeatureDriftResultV1",
    "FeatureDriftReportV1",
    "ModelPerformanceSnapshotV1",
    # Portfolio
    "ProductTypeV1",
    "DelinquencyBucketV1",
    "FicoBandV1",
    "DtiBandV1",
    "VintageDataPointV1",
    "VintageCohortV1",
    "RollRateTransitionV1",
    "RollRateBucketV1",
    "SegmentMetricV1",
    "SegmentBreakdownV1",
    "PortfolioSummaryV1",
    # Compliance
    "ActionTakenV1",
    "DenialReasonV1",
    "RaceCodeV1",
    "EthnicityCodeV1",
    "SexCodeV1",
    "Metro2AccountStatusV1",
    "DisparateImpactStatusV1",
    "AdverseActionNoticeV1",
    "HMDARecordV1",
    "Metro2TradelineV1",
    "FairLendingFlagV1",
    # Audit
    "AuditActionV1",
    "PolicyChangeTypeV1",
    "ModelDeploymentActionV1",
    "ReviewOutcomeV1",
    "PipelineStepAuditV1",
    "DecisionAuditRecordV1",
    "PolicyChangeAuditV1",
    "ModelDeploymentAuditV1",
    "ManualReviewRecordV1",
    # Events
    "EventTypeV1",
    "DataContractEvent",
    "ApplicationSubmittedPayloadV1",
    "ApplicationValidatedPayloadV1",
    "DecisionMadePayloadV1",
    "BatchCompletePayloadV1",
    "BatchFailedPayloadV1",
    "DriftAlertPayloadV1",
    "ModelPromotedPayloadV1",
    "PolicyChangedPayloadV1",
    "AdverseActionGeneratedPayloadV1",
    "FairLendingFlagPayloadV1",
    "ApplicationSubmittedEvent",
    "DecisionMadeEvent",
    "BatchCompleteEvent",
    "DriftAlertEvent",
    "PolicyChangedEvent",
]
