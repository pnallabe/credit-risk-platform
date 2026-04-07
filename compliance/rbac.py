"""
RBAC & Separation of Duties — Section 23.8
===========================================
Implements the platform RBAC matrix and four-eyes enforcement rules.

Platform roles
--------------
  ml_developer        Model development; cannot access production approval workflows.
  ml_validator        Model validation; can promote to higher MLflow stages.
  compliance_officer  Compliance lifecycle; joint emergency-override authority.
  cro                 Final policy approval; joint emergency-override authority.
  data_engineer       Data pipeline; no model or audit access.
  system_service_acct Automated pipelines; append-only audit writes.
  auditor             Read-only access to all audit and compliance tables.
  legal_counsel       Regulatory threshold approval authority.

Four-eyes rules
---------------
Every privileged action requires two DISTINCT individuals.  The enforcer raises
SeparationOfDutiesViolation if actor_email == approver_email.

Access events
-------------
Every privileged action that passes (or fails) enforcement must be recorded to
audit.access_event_log via log_access_event().
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Literal, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# BigQuery optional import
# ---------------------------------------------------------------------------
try:
    from google.cloud import bigquery as _bq_lib  # type: ignore

    _BQ_AVAILABLE = True
except Exception:  # pragma: no cover
    _bq_lib = None  # type: ignore
    _BQ_AVAILABLE = False

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Role = Literal[
    "ml_developer",
    "ml_validator",
    "compliance_officer",
    "cro",
    "data_engineer",
    "system_service_acct",
    "auditor",
    "legal_counsel",
    "executive",
]

FourEyesCheck = Literal["REQUIRED", "PASSED", "WAIVED_AUDIT_ONLY"]
Outcome = Literal["ALLOWED", "DENIED"]

# ---------------------------------------------------------------------------
# Four-eyes rules registry
# ---------------------------------------------------------------------------

FOUR_EYES_RULES: dict[str, dict] = {
    "model_promote_to_production": {
        "developer_role": "ml_developer",
        "approver_role": "ml_validator",
        "prohibited_overlap": True,
    },
    "policy_stage_6_committee_approval": {
        "developer_role": "ml_developer",
        "approver_role": "cro",
        "prohibited_overlap": True,
    },
    "emergency_policy_override": {
        "first_approver_role": "cro",
        "second_approver_role": "compliance_officer",
        "prohibited_overlap": True,
    },
    "regulatory_threshold_update": {
        "author_role": "compliance_officer",
        "approver_role": "legal_counsel",
        "prohibited_overlap": True,
    },
    "model_champion_challenger_swap": {
        "developer_role": "ml_developer",
        "approver_role": "ml_validator",
        "prohibited_overlap": True,
    },
    "usury_cap_legal_signoff": {
        "author_role": "compliance_officer",
        "approver_role": "legal_counsel",
        "prohibited_overlap": True,
    },
}

# ---------------------------------------------------------------------------
# RBAC permission matrix
# ---------------------------------------------------------------------------
#
# Each role maps to allowed operations on platform resources.
# This is a declarative specification used for documentation and testing.
# Enforcement occurs at the FastAPI middleware / decorator layer.

RBAC_MATRIX: dict[Role, dict[str, list[str]]] = {
    "ml_developer": {
        "cc_origination_policy": ["READ"],
        "mlflow_registry": ["READ", "WRITE:Staging"],
        "audit_log": ["READ:own"],
        "compliance_events": ["READ"],
        "regulatory_thresholds": ["READ"],
        "policy_approval_log": [],
        "emergency_override": [],
    },
    "ml_validator": {
        "cc_origination_policy": ["READ"],
        "mlflow_registry": ["READ", "PROMOTE"],
        "audit_log": ["READ:all"],
        "compliance_events": ["READ"],
        "regulatory_thresholds": ["READ"],
        "policy_approval_log": ["WRITE:validator_email"],
        "emergency_override": [],
    },
    "compliance_officer": {
        "cc_origination_policy": ["READ"],
        "mlflow_registry": ["READ"],
        "audit_log": ["READ:all"],
        "compliance_events": ["READ", "WRITE"],
        "regulatory_thresholds": ["READ", "WRITE"],
        "policy_approval_log": ["WRITE:compliance_stages"],
        "emergency_override": ["YES:dual_approval"],
    },
    "cro": {
        "cc_origination_policy": ["READ"],
        "mlflow_registry": ["READ"],
        "audit_log": ["READ:all"],
        "compliance_events": ["READ"],
        "regulatory_thresholds": ["READ"],
        "policy_approval_log": ["WRITE:final_approval"],
        "emergency_override": ["YES:dual_approval"],
    },
    "data_engineer": {
        "cc_origination_policy": ["READ:DDL"],
        "mlflow_registry": [],
        "audit_log": [],
        "compliance_events": ["WRITE:ingest"],
        "regulatory_thresholds": [],
        "policy_approval_log": [],
        "emergency_override": [],
    },
    "system_service_acct": {
        "cc_origination_policy": ["EXECUTE"],
        "mlflow_registry": ["READ", "WRITE"],
        "audit_log": ["WRITE:append_only"],
        "compliance_events": ["WRITE:append_only"],
        "regulatory_thresholds": ["READ"],
        "policy_approval_log": ["WRITE:log_policy_stage"],
        "emergency_override": [],
    },
    "auditor": {
        "cc_origination_policy": ["READ:frozen_snapshot"],
        "mlflow_registry": ["READ"],
        "audit_log": ["READ:all"],
        "compliance_events": ["READ:all"],
        "regulatory_thresholds": ["READ"],
        "policy_approval_log": ["READ:all"],
        "emergency_override": [],
    },
}


# ---------------------------------------------------------------------------
# Core enforcement
# ---------------------------------------------------------------------------


class SeparationOfDutiesViolation(RuntimeError):
    """
    Raised when a four-eyes rule is violated.

    This exception must not be caught-and-continued by any calling code.
    It should propagate to the API layer and result in an HTTP 403 response
    with the violation details logged to audit.access_event_log.
    """


def enforce_four_eyes(
    action: str,
    actor_email: str,
    approver_email: str,
) -> None:
    """
    Enforce the four-eyes (dual-control) rule for a privileged action.

    Parameters
    ----------
    action : str
        Key from FOUR_EYES_RULES (e.g. ``"model_promote_to_production"``).
    actor_email : str
        Email of the person initiating the action.
    approver_email : str
        Email of the approving person.

    Raises
    ------
    SeparationOfDutiesViolation
        If actor_email == approver_email and the rule has prohibited_overlap=True.
    """
    rule = FOUR_EYES_RULES.get(action)
    if rule is None:
        logger.warning(
            "enforce_four_eyes called with unknown action '%s' — "
            "defaulting to PASS.  Add rule to FOUR_EYES_RULES if applicable.",
            action,
        )
        return

    if rule.get("prohibited_overlap") and actor_email == approver_email:
        raise SeparationOfDutiesViolation(
            f"Action '{action}' requires two distinct individuals.  "
            f"Actor and approver cannot be the same person ({actor_email}).  "
            "Ref: Section 23.8 RBAC matrix."
        )


def check_permission(role: Role, resource: str, operation: str) -> bool:
    """
    Return True if the role has the specified operation on the resource.
    Used for declarative permission checks in API middleware.
    """
    role_perms = RBAC_MATRIX.get(role, {})
    allowed_ops = role_perms.get(resource, [])
    return operation in allowed_ops or any(
        op.startswith(operation) for op in allowed_ops
    )


# ---------------------------------------------------------------------------
# Access event logging
# ---------------------------------------------------------------------------


def log_access_event(
    actor_email: str,
    action: str,
    target_resource: str,
    outcome: Outcome,
    four_eyes_check: FourEyesCheck,
    ip_address_hash: str,
    session_id: str,
    approver_email: Optional[str] = None,
    deny_reason: Optional[str] = None,
) -> str:
    """
    Append a privileged access event to audit.access_event_log.

    Returns
    -------
    str
        The generated event_id.
    """
    event_id = str(uuid.uuid4())

    logger.info(
        "[ACCESS_EVENT] actor=%s action=%s resource=%s outcome=%s four_eyes=%s",
        actor_email,
        action,
        target_resource,
        outcome,
        four_eyes_check,
    )

    if _BQ_AVAILABLE and _bq_lib is not None:
        try:
            _bq_lib.Client().insert_rows_json(
                "audit.access_event_log",
                [
                    {
                        "event_id": event_id,
                        "actor_email": actor_email,
                        "action": action,
                        "target_resource": target_resource,
                        "approver_email": approver_email,
                        "four_eyes_check": four_eyes_check,
                        "outcome": outcome,
                        "deny_reason": deny_reason,
                        "ip_address_hash": ip_address_hash,
                        "session_id": session_id,
                        "occurred_at": datetime.utcnow().isoformat(),
                    }
                ],
            )
        except Exception as exc:  # pragma: no cover
            logger.error("Failed to log access event: %s", exc)

    return event_id
