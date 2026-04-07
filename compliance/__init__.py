"""
Compliance package — Section 23
================================
Centralizes all compliance logic for the credit-risk-platform.

Exports
-------
- data_plane      : ComplianceDataPlane client (get_threshold, log_compliance_event)
- engine          : Real-Time Compliance Engine (ComplianceEngine, COMPLIANCE_ENGINE)
- regulatory_horizon : 60/90/180-day regulatory horizon scanner
- health_score    : Platform Compliance Health Score
- retention_policy: Data retention schedule enforcement
- erasure_request : CCPA / GLBA right-to-erasure handler
- rbac            : RBAC matrix + four-eyes enforcement
- third_party_model_registry : Third-party / vendor model compliance
"""
from .data_plane import (
    get_threshold,
    log_compliance_event,
    RegulatoryThreshold,
    ComplianceDataPlaneError,
)
from .engine import COMPLIANCE_ENGINE, ComplianceEngine, ComplianceGateResult
from .rbac import enforce_four_eyes, SeparationOfDutiesViolation

__all__ = [
    "get_threshold",
    "log_compliance_event",
    "RegulatoryThreshold",
    "ComplianceDataPlaneError",
    "COMPLIANCE_ENGINE",
    "ComplianceEngine",
    "ComplianceGateResult",
    "enforce_four_eyes",
    "SeparationOfDutiesViolation",
]
