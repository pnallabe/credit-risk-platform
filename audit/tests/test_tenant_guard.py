"""
Tests for GAP-03-C: TenantContext, scoped_tenant, require_tenant_context,
admin_override, and @tenant_scoped decorator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from audit.tenant_guard import (
    TenantContext,
    admin_override,
    require_tenant_context,
    scoped_tenant,
    tenant_scoped,
)


class TestRequireTenantContext:
    """Tests for require_tenant_context() outside and inside scoped_tenant."""

    def test_raises_outside_context(self) -> None:
        """Calling require_tenant_context() outside a scoped_tenant block raises RuntimeError."""
        with pytest.raises(RuntimeError, match="No tenant context"):
            require_tenant_context()

    def test_returns_correct_tenant_inside_context(self) -> None:
        """Inside scoped_tenant(), require_tenant_context().tenant_id equals the configured value."""
        ctx = TenantContext(tenant_id="t1", source="jwt", authorized_by="user@example.com")
        with scoped_tenant(ctx):
            result = require_tenant_context()
        assert result.tenant_id == "t1"

    def test_raises_again_after_context_exits(self) -> None:
        """After the with scoped_tenant() block exits, require_tenant_context() raises again."""
        ctx = TenantContext(tenant_id="t1", source="jwt", authorized_by="user@example.com")
        with scoped_tenant(ctx):
            pass  # just enter and exit
        # Context must be reset on exit
        with pytest.raises(RuntimeError, match="No tenant context"):
            require_tenant_context()

    def test_nested_contexts_restore_on_exit(self) -> None:
        """Nested scoped_tenant blocks restore the outer context correctly."""
        outer = TenantContext(tenant_id="outer", source="jwt", authorized_by="outer@example.com")
        inner = TenantContext(tenant_id="inner", source="jwt", authorized_by="inner@example.com")
        with scoped_tenant(outer):
            assert require_tenant_context().tenant_id == "outer"
            with scoped_tenant(inner):
                assert require_tenant_context().tenant_id == "inner"
            # After inner exits, outer should be restored
            assert require_tenant_context().tenant_id == "outer"


class TestAdminOverride:
    """Tests for admin_override() context manager factory."""

    def test_source_is_admin_override(self) -> None:
        """admin_override() creates a TenantContext with source='admin_override'."""
        with admin_override("tenant-abc", authorized_by="data-eng-team"):
            ctx = require_tenant_context()
        assert ctx.source == "admin_override"

    def test_tenant_id_is_set(self) -> None:
        """admin_override() sets the correct tenant_id."""
        with admin_override("tenant-xyz", authorized_by="platform-ops"):
            ctx = require_tenant_context()
        assert ctx.tenant_id == "tenant-xyz"

    def test_authorized_by_is_set(self) -> None:
        """admin_override() stores the authorized_by value."""
        with admin_override("t1", authorized_by="alice@example.com"):
            ctx = require_tenant_context()
        assert ctx.authorized_by == "alice@example.com"

    def test_context_is_reset_after_override(self) -> None:
        """After admin_override() block exits, require_tenant_context() raises RuntimeError."""
        with admin_override("t1", authorized_by="alice@example.com"):
            pass
        with pytest.raises(RuntimeError, match="No tenant context"):
            require_tenant_context()


class TestTenantScopedDecorator:
    """Tests for @tenant_scoped decorator."""

    def test_raises_without_context(self) -> None:
        """@tenant_scoped raises RuntimeError when no context is set."""
        @tenant_scoped
        def my_func(tenant_id: str = "") -> str:
            return tenant_id

        with pytest.raises(RuntimeError, match="No tenant context"):
            my_func()

    def test_injects_tenant_id_from_context(self) -> None:
        """@tenant_scoped injects tenant_id from active context when not provided by caller."""
        @tenant_scoped
        def my_func(tenant_id: str = "") -> str:
            return tenant_id

        ctx = TenantContext(tenant_id="injected-tenant", source="jwt", authorized_by="system")
        with scoped_tenant(ctx):
            result = my_func()
        assert result == "injected-tenant"

    def test_caller_supplied_tenant_id_is_not_overridden(self) -> None:
        """@tenant_scoped does not override a tenant_id explicitly passed by the caller."""
        @tenant_scoped
        def my_func(tenant_id: str = "") -> str:
            return tenant_id

        ctx = TenantContext(tenant_id="context-tenant", source="jwt", authorized_by="system")
        with scoped_tenant(ctx):
            result = my_func(tenant_id="explicit-tenant")
        assert result == "explicit-tenant"

    def test_function_without_tenant_id_param_still_validates_context(self) -> None:
        """@tenant_scoped on a function without tenant_id still calls require_tenant_context()."""
        call_count = []

        @tenant_scoped
        def my_func() -> str:
            call_count.append(1)
            return "ok"

        # Must raise without context
        with pytest.raises(RuntimeError, match="No tenant context"):
            my_func()

        # Must succeed with context
        ctx = TenantContext(tenant_id="t1", source="jwt", authorized_by="system")
        with scoped_tenant(ctx):
            result = my_func()
        assert result == "ok"
        assert len(call_count) == 1
