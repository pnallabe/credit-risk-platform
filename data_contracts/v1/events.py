"""
data_contracts.v1.events
==========================
Event streaming contracts for the credit-risk-platform.

These contracts define the envelope and payloads for all events published to:
  * Webhooks (``webhooks/dispatcher.py``)
  * Internal event bus / message queue
  * Change-data-capture (CDC) streams consumed by external products

Event envelope
--------------
Every event shares a ``DataContractEvent`` envelope that carries:
  - ``event_id``      — UUID; consumers use this for deduplication
  - ``event_type``    — identifies the payload type
  - ``tenant_id``     — all events are tenant-scoped
  - ``schema_version``
  - ``emitted_at``    — UTC timestamp

Consumers
---------
* LucidCredit  — subscribes to DecisionMadeEvent for RAG ingest
* ThinFile     — subscribes to ApplicationSubmittedEvent + BatchCompleteEvent
* AgentHiveHQ  — subscribes to all events via the webhook registration API

Delivery guarantees
-------------------
Events are delivered at-least-once.  Consumers MUST be idempotent on
``event_id``.  Ordering is best-effort within a tenant; use ``emitted_at``
for sequencing.

HMAC verification
-----------------
Webhook deliveries are signed with HMAC-SHA256 over the JSON body.
The signature is in the ``X-CreditRisk-Signature`` request header
(format: ``sha256=<hex>``) using the secret registered in WebhookRegistration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Event type registry
# ---------------------------------------------------------------------------


class EventTypeV1(str, Enum):
    # Application lifecycle
    APPLICATION_SUBMITTED = "application.submitted"
    APPLICATION_VALIDATED = "application.validated"

    # Decision lifecycle
    DECISION_APPROVED = "decision.approved"
    DECISION_REJECTED = "decision.rejected"
    DECISION_MANUAL_REVIEW = "decision.manual_review"
    DECISION_AMENDED = "decision.amended"
    MANUAL_REVIEW_RESOLVED = "decision.manual_review.resolved"

    # Batch
    BATCH_STARTED = "batch.started"
    BATCH_COMPLETE = "batch.complete"
    BATCH_FAILED = "batch.failed"

    # Model / feature monitoring
    DRIFT_ALERT = "model.drift_alert"
    MODEL_PROMOTED = "model.champion_promoted"

    # Policy
    POLICY_CHANGED = "policy.changed"
    POLICY_ACTIVATED = "policy.activated"

    # Compliance
    ADVERSE_ACTION_GENERATED = "compliance.adverse_action_generated"
    FAIR_LENDING_FLAG_RAISED = "compliance.fair_lending_flag_raised"


# ---------------------------------------------------------------------------
# Base event envelope
# ---------------------------------------------------------------------------


class DataContractEvent(BaseModel):
    """
    Base envelope shared by all events.

    Consumers should pattern-match on ``event_type`` to determine which
    typed sub-class to deserialise the ``payload`` into.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    event_id: str = Field(..., description="UUID; use for deduplication.")
    event_type: EventTypeV1
    schema_version: Literal["1.0.0"] = "1.0.0"
    tenant_id: str
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Correlation / causation chain
    correlation_id: Optional[str] = Field(
        None,
        description="Traces a chain of events back to the originating request.",
    )
    causation_id: Optional[str] = Field(
        None,
        description="ID of the event that directly caused this event.",
    )

    payload: Dict[str, Any] = Field(
        ...,
        description="Typed payload. Deserialise using the contract matching event_type.",
    )


# ---------------------------------------------------------------------------
# Typed event payloads
# ---------------------------------------------------------------------------


class ApplicationSubmittedPayloadV1(BaseModel):
    """Payload for event_type == 'application.submitted'."""

    model_config = ConfigDict(extra="ignore")

    application_id: str
    tenant_id: str
    product_type: str
    channel: str
    submitted_at: datetime
    loan_amount: float
    loan_purpose: str
    idempotency_key: Optional[str] = None


class ApplicationValidatedPayloadV1(BaseModel):
    """Payload for event_type == 'application.validated'."""

    model_config = ConfigDict(extra="ignore")

    application_id: str
    tenant_id: str
    validation_passed: bool
    validation_error_count: int = 0
    validation_warning_count: int = 0
    data_completeness_score: float
    thin_file_flag: bool
    validated_at: datetime


class DecisionMadePayloadV1(BaseModel):
    """Payload for decision.approved | decision.rejected | decision.manual_review."""

    model_config = ConfigDict(extra="ignore")

    application_id: str
    tenant_id: str
    product_type: str
    decision: str = Field(..., description="APPROVE | REJECT | MANUAL_REVIEW")
    reason_codes: List[str] = Field(default_factory=list)
    pd_score: float
    pd_band: str
    fraud_flag: str
    policy_version: str
    model_version: str
    experiment_id: Optional[str] = None
    decided_at: datetime
    decision_latency_ms: Optional[float] = None

    # Populated on APPROVE only
    approved_amount: Optional[float] = None
    approved_rate: Optional[float] = None
    approved_term_months: Optional[int] = None
    credit_limit: Optional[float] = None


class BatchCompletePayloadV1(BaseModel):
    """Payload for event_type == 'batch.complete'."""

    model_config = ConfigDict(extra="ignore")

    batch_id: str
    tenant_id: str
    product_type: str
    n_submitted: int
    n_approved: int
    n_rejected: int
    n_manual_review: int
    n_errors: int
    approval_rate: float
    avg_pd_score: Optional[float] = None
    total_approved_amount_usd: Optional[float] = None
    processing_duration_seconds: float
    started_at: datetime
    completed_at: datetime
    output_location: Optional[str] = Field(
        None,
        description="Storage path (GCS / S3 URI) of the batch result parquet file.",
    )


class BatchFailedPayloadV1(BaseModel):
    """Payload for event_type == 'batch.failed'."""

    model_config = ConfigDict(extra="ignore")

    batch_id: str
    tenant_id: str
    error_code: str
    error_message: str
    n_processed_before_failure: int = 0
    failed_at: datetime


class DriftAlertPayloadV1(BaseModel):
    """Payload for event_type == 'model.drift_alert'."""

    model_config = ConfigDict(extra="ignore")

    report_id: str = Field(..., description="Links to FeatureDriftReportV1.batch_id.")
    tenant_id: str
    model_variant: str
    overall_drift_status: str = Field(..., description="stable | minor | major")
    n_features_major_drift: int
    n_features_minor_drift: int
    top_drifted_features: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Top 5 features by PSI, each with {feature_name, psi, drift_status}.",
    )
    production_window_start: str
    production_window_end: str
    generated_at: datetime


class ModelPromotedPayloadV1(BaseModel):
    """Payload for event_type == 'model.champion_promoted'."""

    model_config = ConfigDict(extra="ignore")

    model_id: str
    tenant_id: str
    product_type: str
    new_champion_version: str
    previous_champion_version: str
    auc_improvement_pct: float
    promoted_by: str
    promoted_at: datetime


class PolicyChangedPayloadV1(BaseModel):
    """Payload for event_type == 'policy.changed' | 'policy.activated'."""

    model_config = ConfigDict(extra="ignore")

    policy_version: str
    previous_policy_version: Optional[str] = None
    product_type: str
    tenant_id: str
    change_type: str
    changed_parameters: Dict[str, Any] = Field(default_factory=dict)
    effective_date: datetime
    changed_by: str
    change_summary: Optional[str] = None


class AdverseActionGeneratedPayloadV1(BaseModel):
    """Payload for event_type == 'compliance.adverse_action_generated'."""

    model_config = ConfigDict(extra="ignore")

    notice_id: str
    application_id: str
    tenant_id: str
    reason_codes: List[str]
    delivery_method: str
    delivery_deadline: str  # ISO date string
    generated_at: datetime


class FairLendingFlagPayloadV1(BaseModel):
    """Payload for event_type == 'compliance.fair_lending_flag_raised'."""

    model_config = ConfigDict(extra="ignore")

    flag_id: str
    tenant_id: str
    product_type: str
    protected_class: str
    status: str = Field(..., description="pass | warn | fail | insufficient_data")
    approval_rate_ratio: float
    review_required: bool
    analysis_period_start: str
    analysis_period_end: str
    generated_at: datetime


# ---------------------------------------------------------------------------
# Typed event wrappers — strongly-typed convenience classes
# ---------------------------------------------------------------------------


class ApplicationSubmittedEvent(DataContractEvent):
    """Strongly-typed wrapper: event_type is fixed to application.submitted."""

    event_type: Literal[EventTypeV1.APPLICATION_SUBMITTED] = EventTypeV1.APPLICATION_SUBMITTED
    payload: ApplicationSubmittedPayloadV1  # type: ignore[assignment]


class DecisionMadeEvent(DataContractEvent):
    """
    Strongly-typed wrapper for the three decision outcomes.

    ``event_type`` is one of:
      - decision.approved
      - decision.rejected
      - decision.manual_review
    """

    event_type: Literal[
        EventTypeV1.DECISION_APPROVED,
        EventTypeV1.DECISION_REJECTED,
        EventTypeV1.DECISION_MANUAL_REVIEW,
    ]
    payload: DecisionMadePayloadV1  # type: ignore[assignment]


class BatchCompleteEvent(DataContractEvent):
    """Strongly-typed wrapper for batch.complete events."""

    event_type: Literal[EventTypeV1.BATCH_COMPLETE] = EventTypeV1.BATCH_COMPLETE
    payload: BatchCompletePayloadV1  # type: ignore[assignment]


class DriftAlertEvent(DataContractEvent):
    """Strongly-typed wrapper for model.drift_alert events."""

    event_type: Literal[EventTypeV1.DRIFT_ALERT] = EventTypeV1.DRIFT_ALERT
    payload: DriftAlertPayloadV1  # type: ignore[assignment]


class PolicyChangedEvent(DataContractEvent):
    """Strongly-typed wrapper for policy.changed | policy.activated events."""

    event_type: Literal[
        EventTypeV1.POLICY_CHANGED,
        EventTypeV1.POLICY_ACTIVATED,
    ]
    payload: PolicyChangedPayloadV1  # type: ignore[assignment]
