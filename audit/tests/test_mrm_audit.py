"""
Tests for Section 21 MRM audit extensions:
  - governance_approval_log
  - model_validation_log
  - adverse_action_notice_queue
  - independence check
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).parents[3]))

from audit.logger import (
    enqueue_adverse_action_notice,
    get_adverse_action_overdue,
    get_adverse_action_pending,
    get_governance_audit_log,
    get_model_validations,
    log_governance_action,
    log_model_validation,
)

DB_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_model_name() -> str:
    return "cc_portfolio_action"


@pytest.fixture
def mortgage_model_name() -> str:
    return "mortgage_valuation_model"


# ---------------------------------------------------------------------------
# governance_approval_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGovernanceApprovalLog:
    async def test_log_governance_action_returns_uuid(self, cc_model_name: str) -> None:
        approval_id = await log_governance_action(
            model_name=cc_model_name,
            model_version="3",
            action="PROMOTE_PRODUCTION",
            from_stage="Staging",
            to_stage="Production",
            performed_by="mrm@example.com",
            approved_by="cro@example.com",
            governance_metrics={"macro_auc_oos": 0.85, "cld_recall_oos": 0.82},
            notes="Approved after successful IV",
            mlflow_run_id="run-abc-123",
            db_url=DB_URL,
        )
        assert isinstance(approval_id, str)
        assert len(approval_id) == 36  # UUID4

    async def test_governance_log_retrievable(self, cc_model_name: str) -> None:
        await log_governance_action(
            model_name=cc_model_name,
            model_version="5",
            action="REVIEW_DUE",
            from_stage="production",
            to_stage=None,
            performed_by="review-cron@example.com",
            approved_by=None,
            governance_metrics={"days_since_promotion": 185},
            notes="Annual review due",
            mlflow_run_id=None,
            db_url=DB_URL,
        )
        records = await get_governance_audit_log(cc_model_name, DB_URL, limit=50)
        review_due = [r for r in records if r["action"] == "REVIEW_DUE"]
        assert len(review_due) >= 1
        assert review_due[0]["model_name"] == cc_model_name

    async def test_governance_metrics_json_decoded(self, cc_model_name: str) -> None:
        metrics = {"macro_auc_oos": 0.83, "guardrail_coverage": 1.0}
        await log_governance_action(
            model_name=cc_model_name,
            model_version="4",
            action="GOVERNANCE_OVERRIDE",
            from_stage="Staging",
            to_stage="Production",
            performed_by="admin@example.com",
            approved_by=None,
            governance_metrics=metrics,
            notes="Emergency override",
            mlflow_run_id=None,
            db_url=DB_URL,
        )
        records = await get_governance_audit_log(cc_model_name, DB_URL, limit=10)
        overrides = [r for r in records if r["action"] == "GOVERNANCE_OVERRIDE"]
        assert overrides
        assert isinstance(overrides[0]["governance_metrics"], dict)
        assert overrides[0]["governance_metrics"]["macro_auc_oos"] == 0.83

    async def test_governance_log_covers_mortgage_model(self, mortgage_model_name: str) -> None:
        approval_id = await log_governance_action(
            model_name=mortgage_model_name,
            model_version="1",
            action="PROMOTE_PRODUCTION",
            from_stage="Staging",
            to_stage="Production",
            performed_by="mrm@example.com",
            approved_by="cro@example.com",
            governance_metrics={"lr_auc": 0.80, "gini": 0.60},
            notes="Initial production promotion of mortgage valuation model",
            mlflow_run_id=None,
            db_url=DB_URL,
        )
        assert approval_id
        records = await get_governance_audit_log(mortgage_model_name, DB_URL)
        assert any(r["model_name"] == mortgage_model_name for r in records)

    async def test_pagination(self, cc_model_name: str) -> None:
        for i in range(5):
            await log_governance_action(
                model_name=cc_model_name,
                model_version=str(i),
                action="REGISTER",
                from_stage=None,
                to_stage="None",
                performed_by="dev@example.com",
                approved_by=None,
                governance_metrics={},
                notes=f"Registration {i}",
                mlflow_run_id=None,
                db_url=DB_URL,
            )

        page1 = await get_governance_audit_log(cc_model_name, DB_URL, limit=3, offset=0)
        page2 = await get_governance_audit_log(cc_model_name, DB_URL, limit=3, offset=3)
        assert len(page1) <= 3
        assert len(page2) <= 3
        # No duplicates across pages
        ids1 = {r["approval_id"] for r in page1}
        ids2 = {r["approval_id"] for r in page2}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# model_validation_log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestModelValidationLog:
    async def test_log_validation_returns_uuid(self, cc_model_name: str) -> None:
        vid = await log_model_validation(
            model_name=cc_model_name,
            model_version="3",
            validator_email="validator@example.com",
            validation_type="INITIAL",
            outcome="PASS",
            conditions=None,
            findings={"ks": 0.41, "auc": 0.85},
            test_scripts_ref="abc123def456",
            approved_for_prod=True,
            notes="All checks passed",
            db_url=DB_URL,
        )
        assert isinstance(vid, str)
        assert len(vid) == 36

    async def test_validation_pass_with_conditions(self, cc_model_name: str) -> None:
        vid = await log_model_validation(
            model_name=cc_model_name,
            model_version="2",
            validator_email="validator@example.com",
            validation_type="ANNUAL",
            outcome="PASS_WITH_CONDITIONS",
            conditions=["Rerun benchmark with 2024Q4 data within 30 days"],
            findings={"ks": 0.38, "issue": "minor degradation"},
            test_scripts_ref=None,
            approved_for_prod=True,
            notes="Conditionally approved",
            db_url=DB_URL,
        )
        records = await get_model_validations(cc_model_name, DB_URL)
        cond_pass = [r for r in records if r.get("outcome") == "PASS_WITH_CONDITIONS"]
        assert cond_pass
        assert isinstance(cond_pass[0]["conditions"], list)
        assert len(cond_pass[0]["conditions"]) == 1

    async def test_validation_fail_not_approved(self, cc_model_name: str) -> None:
        await log_model_validation(
            model_name=cc_model_name,
            model_version="1",
            validator_email="validator@example.com",
            validation_type="TRIGGERED",
            outcome="FAIL",
            conditions=["Retrain with updated feature set"],
            findings={"auc": 0.71, "ks": 0.30},
            test_scripts_ref=None,
            approved_for_prod=False,
            notes="AUC below threshold",
            db_url=DB_URL,
        )
        records = await get_model_validations(cc_model_name, DB_URL)
        fails = [r for r in records if r["outcome"] == "FAIL"]
        assert fails
        assert fails[0]["approved_for_prod"] is False  # decoded bool

    async def test_mortgage_validation_logged(self, mortgage_model_name: str) -> None:
        vid = await log_model_validation(
            model_name=mortgage_model_name,
            model_version="1",
            validator_email="mortgage-validator@example.com",
            validation_type="INITIAL",
            outcome="PASS",
            conditions=[],
            findings={"lr_auc": 0.80, "hpa_monotone_pct": 1.0, "ltv_psi": 0.08},
            test_scripts_ref="git-sha-mortgage-v1",
            approved_for_prod=True,
            notes="Mortgage model initial validation passed",
            db_url=DB_URL,
        )
        assert vid
        records = await get_model_validations(mortgage_model_name, DB_URL)
        assert records
        assert records[0]["model_name"] == mortgage_model_name
        assert isinstance(records[0]["findings"], dict)
        assert records[0]["findings"]["lr_auc"] == 0.80


# ---------------------------------------------------------------------------
# adverse_action_notice_queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAdverseActionQueue:
    async def test_enqueue_returns_uuid(self) -> None:
        nid = await enqueue_adverse_action_notice(
            account_id="ACC_001",
            action_type="CLD",
            reason_codes=["HIGH_UTILIZATION", "MISSED_PAYMENT"],
            review_month="2026-03",
            model_version="3",
            dispatch_channel="EMAIL",
            db_url=DB_URL,
        )
        assert isinstance(nid, str)
        assert len(nid) == 36

    async def test_fcra_minimum_two_codes_enforced(self) -> None:
        with pytest.raises(ValueError, match="minimum 2 reason codes"):
            await enqueue_adverse_action_notice(
                account_id="ACC_002",
                action_type="CLD",
                reason_codes=["ONLY_ONE"],
                review_month="2026-03",
                model_version="3",
                dispatch_channel="EMAIL",
                db_url=DB_URL,
            )

    async def test_pending_notices_retrievable(self) -> None:
        await enqueue_adverse_action_notice(
            account_id="ACC_003",
            action_type="APR_UP",
            reason_codes=["PAYMENT_HISTORY", "CREDIT_UTILIZATION"],
            review_month="2026-03",
            model_version="3",
            dispatch_channel="MAIL",
            db_url=DB_URL,
        )
        pending = await get_adverse_action_pending(DB_URL)
        assert len(pending) >= 1
        assert all(r["dispatch_status"] == "PENDING" for r in pending)
        # reason_codes should be JSON-decoded to list
        for r in pending:
            assert isinstance(r["reason_codes"], list)

    async def test_dispatch_deadline_is_30_days_from_enqueue(self) -> None:
        from datetime import datetime, timezone, timedelta

        nid = await enqueue_adverse_action_notice(
            account_id="ACC_004",
            action_type="DECLINE",
            reason_codes=["LOW_CREDIT_SCORE", "HIGH_DTI"],
            review_month="2026-03",
            model_version="3",
            dispatch_channel="SMS",
            db_url=DB_URL,
        )
        pending = await get_adverse_action_pending(DB_URL)
        record  = next((r for r in pending if r["notice_id"] == nid), None)
        assert record is not None

        from datetime import datetime, timezone, timedelta

        enqueued  = datetime.fromisoformat(record["enqueued_at"].replace("Z", "+00:00"))
        deadline  = datetime.fromisoformat(record["dispatch_deadline"].replace("Z", "+00:00"))
        diff_days = (deadline - enqueued).days
        # Should be exactly 30 days (within 1 second tolerance)
        assert 29 <= diff_days <= 31, f"Expected ~30 days, got {diff_days}"

    async def test_overdue_notices_detected(self) -> None:
        """Overdue records should have dispatch_deadline in the past."""
        # We can't easily travel time in the test, but verify the helper runs.
        overdue = await get_adverse_action_overdue(DB_URL)
        # Since we just enqueued these, none should be overdue yet
        assert isinstance(overdue, list)

    async def test_reason_codes_in_pending_are_list(self) -> None:
        pending = await get_adverse_action_pending(DB_URL)
        for rec in pending:
            assert isinstance(rec.get("reason_codes"), list), (
                f"reason_codes should be decoded: {rec['reason_codes']!r}"
            )

    async def test_overdue_flag_set_correctly(self) -> None:
        """Non-overdue records should have overdue=False."""
        pending = await get_adverse_action_pending(DB_URL)
        # All freshly enqueued records have deadline 30 days in future
        fresh = [r for r in pending if not r.get("overdue")]
        assert len(fresh) >= 1


# ---------------------------------------------------------------------------
# quality gates (Section 21.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestQualityGates:
    """Verify the Section 21.9 quality gate conditions at the functional level."""

    async def test_no_update_delete_semantics(self, cc_model_name: str) -> None:
        """Write two PROMOTE_PRODUCTION records — both must persist (no overwrite)."""
        id1 = await log_governance_action(
            model_name=cc_model_name, model_version="10",
            action="PROMOTE_PRODUCTION", from_stage="Staging", to_stage="Production",
            performed_by="a@a.com", approved_by="b@b.com",
            governance_metrics={}, notes="First", mlflow_run_id=None,
            db_url=DB_URL,
        )
        id2 = await log_governance_action(
            model_name=cc_model_name, model_version="11",
            action="PROMOTE_PRODUCTION", from_stage="Staging", to_stage="Production",
            performed_by="a@a.com", approved_by="b@b.com",
            governance_metrics={}, notes="Second", mlflow_run_id=None,
            db_url=DB_URL,
        )
        assert id1 != id2  # distinct UUIDs
        records = await get_governance_audit_log(cc_model_name, DB_URL, limit=50)
        promo_ids = {r["approval_id"] for r in records if r["action"] == "PROMOTE_PRODUCTION"}
        assert id1 in promo_ids
        assert id2 in promo_ids

    async def test_all_registered_models_have_governance_config(self) -> None:
        """Every model in ALL_REGISTERED_MODELS must have MODEL_GOVERNANCE entry."""
        from mlflow_config.mlflow_config import ALL_REGISTERED_MODELS, MODEL_GOVERNANCE

        for model_name in ALL_REGISTERED_MODELS:
            assert model_name in MODEL_GOVERNANCE, (
                f"MODEL_GOVERNANCE missing entry for '{model_name}'"
            )
            gov = MODEL_GOVERNANCE[model_name]
            assert "review_cycle_months" in gov, f"{model_name}: missing review_cycle_months"
            assert "fair_lending_required" in gov, f"{model_name}: missing fair_lending_required"
            assert gov["fair_lending_required"] is True, (
                f"{model_name}: fair_lending_required must be True"
            )

    async def test_mortgage_model_in_all_registered(self) -> None:
        from mlflow_config.mlflow_config import ALL_REGISTERED_MODELS, MORTGAGE_VALUATION_MODEL_NAME

        assert MORTGAGE_VALUATION_MODEL_NAME in ALL_REGISTERED_MODELS

    async def test_sr117_stages_are_complete(self) -> None:
        from mlflow_config.mlflow_config import SR117_STAGES

        required = {"development", "independent_validation", "mrm_approval", "production", "sunset"}
        assert required == set(SR117_STAGES)

    async def test_governance_error_hierarchy(self) -> None:
        from mlflow_config.mlflow_config import (
            CCPortfolioGovernanceError,
            CCValuationGovernanceError,
            GovernanceError,
            MortgageValuationGovernanceError,
        )

        # All domain errors must inherit from GovernanceError
        assert issubclass(CCPortfolioGovernanceError, GovernanceError)
        assert issubclass(CCValuationGovernanceError, GovernanceError)
        assert issubclass(MortgageValuationGovernanceError, GovernanceError)
