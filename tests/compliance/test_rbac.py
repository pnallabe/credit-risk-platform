"""
tests/compliance/test_rbac.py — Section 23.12
==============================================
Unit tests for compliance.rbac module.

Contracts verified:
  - enforce_four_eyes() raises SeparationOfDutiesViolation when
    actor_email == approver_email for a prohibited_overlap action.
  - enforce_four_eyes() passes when emails are distinct.
  - Unknown action logs a warning but does NOT raise.
  - check_permission() reflects the RBAC_MATRIX correctly.
  - log_access_event() returns a UUID and does not raise when BQ
    is unavailable.
"""
from __future__ import annotations

import pytest

from compliance.rbac import (
    FOUR_EYES_RULES,
    RBAC_MATRIX,
    SeparationOfDutiesViolation,
    check_permission,
    enforce_four_eyes,
    log_access_event,
)


class TestFourEyesEnforcement:
    @pytest.mark.parametrize("action", list(FOUR_EYES_RULES.keys()))
    def test_same_person_raises_violation(self, action: str):
        with pytest.raises(SeparationOfDutiesViolation) as exc_info:
            enforce_four_eyes(
                action=action,
                actor_email="alice@bank.com",
                approver_email="alice@bank.com",
            )
        assert action in str(exc_info.value)
        assert "alice@bank.com" in str(exc_info.value)

    @pytest.mark.parametrize("action", list(FOUR_EYES_RULES.keys()))
    def test_distinct_people_pass(self, action: str):
        # Should not raise
        enforce_four_eyes(
            action=action,
            actor_email="alice@bank.com",
            approver_email="bob@bank.com",
        )

    def test_unknown_action_no_raise(self, caplog):
        import logging

        with caplog.at_level(logging.WARNING, logger="compliance.rbac"):
            enforce_four_eyes(
                action="unknown_action_xyz",
                actor_email="same@bank.com",
                approver_email="same@bank.com",
            )
        assert "unknown" in caplog.text.lower() or "unknown_action_xyz" in caplog.text

    def test_violation_message_contains_action_and_email(self):
        with pytest.raises(SeparationOfDutiesViolation) as exc_info:
            enforce_four_eyes(
                action="model_promote_to_production",
                actor_email="devops@bank.com",
                approver_email="devops@bank.com",
            )
        msg = str(exc_info.value)
        assert "model_promote_to_production" in msg
        assert "devops@bank.com" in msg


class TestRbacMatrix:
    def test_ml_developer_cannot_do_emergency_override(self):
        overrides = RBAC_MATRIX.get("ml_developer", {}).get("emergency_override", [])
        assert overrides == []

    def test_compliance_officer_can_emergency_override(self):
        overrides = RBAC_MATRIX.get("compliance_officer", {}).get("emergency_override", [])
        assert any("YES" in op for op in overrides)

    def test_auditor_has_read_access_to_all_relevant_resources(self):
        auditor = RBAC_MATRIX.get("auditor", {})
        for resource in ("audit_log", "compliance_events", "regulatory_thresholds", "policy_approval_log"):
            ops = auditor.get(resource, [])
            assert any("READ" in op for op in ops), (
                f"Auditor should have READ access to {resource}"
            )

    def test_data_engineer_no_mlflow_access(self):
        engineer = RBAC_MATRIX.get("data_engineer", {})
        assert engineer.get("mlflow_registry", []) == []

    def test_system_service_acct_append_only_audit_log(self):
        service = RBAC_MATRIX.get("system_service_acct", {})
        ops = service.get("audit_log", [])
        assert any("append_only" in op.lower() or "WRITE" in op for op in ops)
        assert not any("DELETE" in op or "UPDATE" in op for op in ops)


class TestCheckPermission:
    def test_ml_developer_can_read_policy(self):
        assert check_permission("ml_developer", "cc_origination_policy", "READ")

    def test_ml_developer_cannot_promote_to_prod_via_matrix(self):
        # ml_developer can only write to Staging in mlflow
        perms = RBAC_MATRIX["ml_developer"]["mlflow_registry"]
        assert not any(p == "PROMOTE" for p in perms)

    def test_cro_can_do_final_approval(self):
        assert check_permission("cro", "policy_approval_log", "WRITE")


class TestLogAccessEvent:
    @pytest.fixture(autouse=True)
    def no_bq(self, monkeypatch):
        monkeypatch.setattr("compliance.rbac._BQ_AVAILABLE", False)

    def test_returns_uuid(self):
        event_id = log_access_event(
            actor_email="alice@bank.com",
            action="model_promote_to_production",
            target_resource="cc_pd_model@v3",
            outcome="ALLOWED",
            four_eyes_check="PASSED",
            ip_address_hash="aabbcc",
            session_id="sess-001",
        )
        assert len(event_id) == 36
        assert event_id.count("-") == 4

    def test_does_not_raise_without_bq(self):
        # Should silently succeed when BQ is unavailable
        log_access_event(
            actor_email="bob@bank.com",
            action="emergency_policy_override",
            target_resource="cc_origination_policy@v5",
            outcome="DENIED",
            four_eyes_check="REQUIRED",
            ip_address_hash="112233",
            session_id="sess-002",
            deny_reason="SeparationOfDutiesViolation",
        )
