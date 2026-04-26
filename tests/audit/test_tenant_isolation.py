"""
P0.1 — Tenant Isolation Tests
==============================
Verify that audit log reads and writes are strictly scoped to tenant_id.

Rules enforced:
  1. A tenant CANNOT read another tenant's audit record.
  2. Same application_id under two different tenant_ids creates two isolated records.
  3. log_decision() without tenant_id raises ValueError.
  4. get_audit_record() without tenant_id raises ValueError.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest

from audit.logger import get_audit_record, log_decision

DB_URL = "sqlite+aiosqlite:///:memory:"

# ---------------------------------------------------------------------------
# Minimal decision result stub
# ---------------------------------------------------------------------------


@dataclass
class _StubDecision:
    application_id: str
    decision: str = "REJECT"
    reason_codes: List[str] = field(default_factory=list)
    decision_latency_ms: int = 5


def _input_features(application_id: str) -> Dict[str, Any]:
    return {
        "application_id": application_id,
        "pd_score": 0.12,
        "fraud_probability": 0.02,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro: Any) -> Any:
    """Run an async coroutine synchronously (works in pytest without asyncio plugin)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Write two records with the same application_id but different tenant_ids;
    verify that each tenant can only read its own record."""

    _SHARED_APP_ID = "app-shared-" + str(uuid.uuid4())[:8]
    _TENANT_A = "tenant-alpha"
    _TENANT_B = "tenant-beta"

    # Use a single in-memory DB URL shared across all methods in this class
    _DB_URL = "sqlite+aiosqlite:///:memory:"

    def _write_for_tenant(self, tenant_id: str) -> str:
        return _run(
            log_decision(
                decision_result=_StubDecision(application_id=self._SHARED_APP_ID),
                feature_version="1.0.0",
                model_versions={"fraud": "v1", "credit_risk": "v1"},
                input_features=_input_features(self._SHARED_APP_ID),
                db_url=self._DB_URL,
                tenant_id=tenant_id,
            )
        )

    def test_each_tenant_reads_own_record(self) -> None:
        """Tenant A and B each write a record; each can read back only its own."""
        log_id_a = self._write_for_tenant(self._TENANT_A)
        log_id_b = self._write_for_tenant(self._TENANT_B)

        # Tenant A reads its record
        rec_a = _run(
            get_audit_record(
                application_id=self._SHARED_APP_ID,
                db_url=self._DB_URL,
                tenant_id=self._TENANT_A,
            )
        )
        assert rec_a is not None, "Tenant A should find its own record"
        assert rec_a["log_id"] == log_id_a
        assert rec_a["tenant_id"] == self._TENANT_A

        # Tenant B reads its record
        rec_b = _run(
            get_audit_record(
                application_id=self._SHARED_APP_ID,
                db_url=self._DB_URL,
                tenant_id=self._TENANT_B,
            )
        )
        assert rec_b is not None, "Tenant B should find its own record"
        assert rec_b["log_id"] == log_id_b
        assert rec_b["tenant_id"] == self._TENANT_B

    def test_tenant_cannot_read_other_tenants_record(self) -> None:
        """A tenant querying with a different tenant_id gets None."""
        self._write_for_tenant(self._TENANT_A)

        # Tenant C has never written anything — cannot see A's record
        rec = _run(
            get_audit_record(
                application_id=self._SHARED_APP_ID,
                db_url=self._DB_URL,
                tenant_id="tenant-other",
            )
        )
        assert rec is None, "A different tenant must not see Tenant A's record"


class TestTenantIdRequired:
    """Missing or empty tenant_id must raise ValueError at both write and read."""

    _APP_ID = "app-" + str(uuid.uuid4())[:8]

    def test_log_decision_requires_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="tenant_id is required"):
            _run(
                log_decision(
                    decision_result=_StubDecision(application_id=self._APP_ID),
                    feature_version="1.0.0",
                    model_versions={},
                    input_features=_input_features(self._APP_ID),
                    db_url="sqlite+aiosqlite:///:memory:",
                    tenant_id="",  # empty — must fail
                )
            )

    def test_log_decision_requires_nonempty_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="tenant_id is required"):
            _run(
                log_decision(
                    decision_result=_StubDecision(application_id=self._APP_ID),
                    feature_version="1.0.0",
                    model_versions={},
                    input_features=_input_features(self._APP_ID),
                    db_url="sqlite+aiosqlite:///:memory:",
                    tenant_id="   ",  # whitespace-only — must fail
                )
            )

    def test_get_audit_record_requires_tenant_id(self) -> None:
        with pytest.raises(ValueError, match="tenant_id is required"):
            _run(
                get_audit_record(
                    application_id=self._APP_ID,
                    db_url="sqlite+aiosqlite:///:memory:",
                    tenant_id="",
                )
            )


# ---------------------------------------------------------------------------
# TenantContext / tenant_guard tests
# ---------------------------------------------------------------------------

class TestTenantGuard:
    """Tests for audit.tenant_guard — scoped_tenant, require_tenant_context, etc."""

    def test_scoped_tenant_sets_and_clears_context(self) -> None:
        from audit.tenant_guard import TenantContext, require_tenant_context, scoped_tenant
        ctx = TenantContext(tenant_id="t1", source="jwt", authorized_by="user@example.com")
        with scoped_tenant(ctx) as active:
            assert active.tenant_id == "t1"
            result = require_tenant_context()
            assert result.tenant_id == "t1"
        # After exiting, context should be cleared
        import pytest
        with pytest.raises(RuntimeError):
            require_tenant_context()

    def test_require_tenant_context_raises_without_context(self) -> None:
        from audit.tenant_guard import require_tenant_context
        import pytest
        with pytest.raises(RuntimeError, match="No tenant context"):
            require_tenant_context()

    def test_tenant_scoped_decorator_injects_tenant_id(self) -> None:
        from audit.tenant_guard import TenantContext, scoped_tenant, tenant_scoped

        @tenant_scoped
        def my_func(*, tenant_id: str = "") -> str:
            return tenant_id

        ctx = TenantContext(tenant_id="t-injected", source="test", authorized_by="pytest")
        with scoped_tenant(ctx):
            result = my_func()
        assert result == "t-injected"

    def test_tenant_scoped_decorator_raises_without_context(self) -> None:
        from audit.tenant_guard import tenant_scoped
        import pytest

        @tenant_scoped
        def my_func(*, tenant_id: str = "") -> str:
            return tenant_id

        with pytest.raises(RuntimeError):
            my_func()

    def test_admin_override_sets_source(self) -> None:
        from audit.tenant_guard import admin_override, require_tenant_context

        with admin_override("tenant-admin", authorized_by="data-eng-team"):
            ctx = require_tenant_context()
            assert ctx.tenant_id == "tenant-admin"
            assert ctx.source == "admin_override"
            assert ctx.authorized_by == "data-eng-team"
