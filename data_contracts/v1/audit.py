"""
data_contracts.v1.audit
=========================
Immutable audit trail contracts for decisions, policy changes, and model
deployments.

Design principles
-----------------
* All audit records are write-once (no UPDATE or DELETE).
* Every record has a ``record_hash`` that is SHA-256(sorted JSON of payload)
  so consumers can detect tampering.
* Audit records must be retained for the period required by applicable
  regulation (typically 25 months for FCRA, 5 years for BSA/AML).

Consumers
---------
* LucidCredit  — surfaces audit records for examiner Q&A workflows
* AgentHiveHQ  — drives the decision review queue in ``decisioning/review_queue.py``
* Regulators   — exam packet builder in ``compliance/exam_packet_builder.py``
                 pulls these records to assemble examination packages
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class AuditActionV1(str, Enum):
    """Audit action types for decision audit records."""
    SUBMITTED = "submitted"
    VALIDATED = "validated"
    FEATURES_COMPUTED = "features_computed"
    SCORED = "scored"
    DECIDED = "decided"
    EXPLAINED = "explained"
    ADVERSE_ACTION_GENERATED = "adverse_action_generated"
    MANUAL_REVIEW_OPENED = "manual_review_opened"
    MANUAL_REVIEW_CLOSED = "manual_review_closed"
    AMENDED = "amended"


class PolicyChangeTypeV1(str, Enum):
    """Types of policy changes tracked in the audit trail."""
    PUBLISHED = "published"
    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    SUPERSEDED = "superseded"
    ROLLBACK = "rollback"


class ModelDeploymentActionV1(str, Enum):
    """Model lifecycle actions."""
    REGISTERED = "registered"
    SHADOW_DEPLOYED = "shadow_deployed"
    CHALLENGER_DEPLOYED = "challenger_deployed"
    CHAMPION_PROMOTED = "champion_promoted"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


class ReviewOutcomeV1(str, Enum):
    """Outcome of a manual review."""
    APPROVE = "approve"
    REJECT = "reject"
    ESCALATE = "escalate"
    DEFER = "defer"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ContractBaseV1(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract_name: str = Field(...)


# ---------------------------------------------------------------------------
# DecisionAuditRecordV1 — immutable record of every pipeline step for one application
# ---------------------------------------------------------------------------


class PipelineStepAuditV1(BaseModel):
    """Audit entry for a single step in the underwriting pipeline."""

    model_config = ConfigDict(extra="ignore")

    step_name: str = Field(..., description="e.g. 'DataIngestionAgent', 'RiskModelingAgent'.")
    action: AuditActionV1
    actor: str = Field(
        ...,
        description="System component or user that performed the action.",
    )
    input_hash: Optional[str] = Field(
        None,
        description="SHA-256 of the step's input payload.",
    )
    output_hash: Optional[str] = Field(
        None,
        description="SHA-256 of the step's output payload.",
    )
    outcome: str = Field(..., description="'success', 'failure', 'skipped'.")
    error_message: Optional[str] = None
    latency_ms: Optional[float] = Field(None, ge=0)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionAuditRecordV1(_ContractBaseV1):
    """
    Immutable, end-to-end audit trail for one credit application.

    Written by the pipeline orchestrator as each step completes. Once
    ``is_complete`` is True no further steps should be appended — amendments
    create a new record referencing ``supersedes_audit_id``.

    The ``record_hash`` is computed over the full ``steps`` payload so any
    post-write tampering is detectable. It is recomputed on read and compared
    to the stored value by the audit reader.
    """

    contract_name: Literal["DecisionAuditRecordV1"] = "DecisionAuditRecordV1"

    audit_id: str = Field(..., description="UUID for this audit record.")
    application_id: str
    tenant_id: str
    pipeline_run_id: str

    # Pipeline steps in chronological order
    steps: List[PipelineStepAuditV1] = Field(default_factory=list)

    # Final verdict (denormalised for quick querying)
    final_decision: Optional[str] = Field(
        None,
        description="APPROVE | REJECT | MANUAL_REVIEW — copied from CreditDecisionV1.",
    )
    policy_version: str = "v1"
    model_version: str = "champion"

    # Integrity
    is_complete: bool = Field(
        False,
        description="True when the pipeline has reached a terminal state.",
    )
    record_hash: Optional[str] = Field(
        None,
        description="SHA-256 of sorted JSON of all steps. Computed on write.",
    )

    # Amendment linkage
    supersedes_audit_id: Optional[str] = Field(
        None,
        description="Set when this record amends a prior audit trail.",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _compute_record_hash(self) -> "DecisionAuditRecordV1":
        """Compute record_hash if steps are present and hash is not already set."""
        if self.steps and not self.record_hash:
            steps_payload = json.dumps(
                [s.model_dump(mode="json") for s in self.steps],
                sort_keys=True,
                default=str,
            )
            self.record_hash = hashlib.sha256(steps_payload.encode()).hexdigest()
        return self


# ---------------------------------------------------------------------------
# PolicyChangeAuditV1 — immutable log of every policy version transition
# ---------------------------------------------------------------------------


class PolicyChangeAuditV1(_ContractBaseV1):
    """
    Immutable record of every credit policy version change.

    Stored by ``decision_engine/policy_version_store.py``.
    Required for examination readiness — regulators can reconstruct
    the exact policy in effect on any given date.
    """

    contract_name: Literal["PolicyChangeAuditV1"] = "PolicyChangeAuditV1"

    audit_id: str
    tenant_id: str
    product_type: str = Field(..., description="credit_card | personal_loan | mortgage.")

    # Version identifiers
    policy_version: str = Field(..., description="New policy version identifier.")
    previous_policy_version: Optional[str] = None
    change_type: PolicyChangeTypeV1

    # What changed (diff summary)
    changed_parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Dict of {parameter_name: {old_value, new_value}} for each changed field.",
    )
    change_summary: Optional[str] = Field(
        None,
        description="Human-readable description of what changed and why.",
    )
    regulatory_basis: Optional[str] = Field(
        None,
        description="Regulatory or business justification (e.g. 'Rate hike response Q1-2022').",
    )

    # Approvals
    submitted_by: str = Field(..., description="User or system that submitted the change.")
    approved_by: Optional[str] = Field(
        None,
        description="Compliance officer or committee that approved the change.",
    )
    committee_approval_id: Optional[str] = Field(
        None,
        description="References committee_approval_store record for formal approvals.",
    )
    effective_date: datetime = Field(
        ...,
        description="Date/time the policy version became active.",
    )

    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    record_hash: Optional[str] = Field(
        None,
        description="SHA-256 of the changed_parameters payload.",
    )

    @model_validator(mode="after")
    def _compute_hash(self) -> "PolicyChangeAuditV1":
        if self.changed_parameters and not self.record_hash:
            payload = json.dumps(self.changed_parameters, sort_keys=True, default=str)
            self.record_hash = hashlib.sha256(payload.encode()).hexdigest()
        return self


# ---------------------------------------------------------------------------
# ModelDeploymentAuditV1 — champion/challenger model lifecycle record
# ---------------------------------------------------------------------------


class ModelDeploymentAuditV1(_ContractBaseV1):
    """
    Immutable record of every model deployment and promotion event.

    Stored alongside model artefacts in the model registry.
    Provides the full chain of custody from training through champion promotion
    to retirement.
    """

    contract_name: Literal["ModelDeploymentAuditV1"] = "ModelDeploymentAuditV1"

    audit_id: str
    tenant_id: str
    product_type: str
    model_id: str = Field(..., description="Model registry identifier.")
    model_version: str
    model_variant: Literal["champion", "challenger", "shadow"]

    action: ModelDeploymentActionV1

    # Performance gate (populated on CHAMPION_PROMOTED actions)
    champion_auc_before: Optional[float] = Field(None, ge=0.0, le=1.0)
    challenger_auc: Optional[float] = Field(None, ge=0.0, le=1.0)
    auc_improvement_pct: Optional[float] = None
    statistical_significance_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    promotion_gate_passed: Optional[bool] = None

    # Provenance
    training_dataset_id: Optional[str] = None
    training_row_count: Optional[int] = Field(None, ge=0)
    training_period_start: Optional[str] = None
    training_period_end: Optional[str] = None
    feature_version: str = "1.0.0"

    # Approvals
    deployed_by: str
    approved_by: Optional[str] = None
    rollback_reason: Optional[str] = Field(
        None,
        description="Required when action == ROLLED_BACK.",
    )

    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# ManualReviewRecordV1 — outcome of a human credit analyst review
# ---------------------------------------------------------------------------


class ManualReviewRecordV1(_ContractBaseV1):
    """
    Record produced when a credit analyst manually reviews a MANUAL_REVIEW
    application from the review queue.

    Linked to ``DecisionAuditRecordV1`` via ``application_id``.
    """

    contract_name: Literal["ManualReviewRecordV1"] = "ManualReviewRecordV1"

    review_id: str = Field(..., description="UUID for this review record.")
    application_id: str
    tenant_id: str
    queue_entry_id: str = Field(
        ...,
        description="Review queue entry ID from decisioning/review_queue.py.",
    )

    # Review outcome
    outcome: ReviewOutcomeV1
    override_decision: Optional[str] = Field(
        None,
        description="If APPROVE or REJECT override: the final decision label.",
    )
    override_rationale: Optional[str] = Field(
        None,
        description="Required free-text rationale when overriding the model decision.",
    )
    approved_amount_override: Optional[float] = Field(None, ge=0)
    approved_rate_override: Optional[float] = Field(None, ge=0.0, le=1.0)

    # Reviewer metadata
    reviewer_id: str
    reviewer_role: str = Field(..., description="e.g. 'credit_analyst', 'credit_manager'.")
    review_duration_seconds: Optional[float] = Field(None, ge=0)

    # Escalation chain
    escalated_to: Optional[str] = None
    escalation_reason: Optional[str] = None

    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
