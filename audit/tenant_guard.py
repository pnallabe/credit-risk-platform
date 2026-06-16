"""
Tenant Guard
============
Context-variable based tenant isolation for scripts and background processes.

 Usage
-----
    from audit.tenant_guard import TenantContext, scoped_tenant, require_tenant_context, admin_override

    # Normal usage — bind tenant from request context
    with scoped_tenant(TenantContext(tenant_id="t1", source="jwt", authorized_by="user@example.com")):
        ctx = require_tenant_context()
        run_query(tenant_id=ctx.tenant_id)

    # Admin override — explicit and grep-able
    with admin_override("tenant-abc", authorized_by="data-eng-team"):
        run_migration_query()

    # Decorator usage
    @tenant_scoped
    def run_report(*, tenant_id: str, ...):
        ...

    with scoped_tenant(TenantContext(tenant_id="t1", source="batch_job", authorized_by="cli")):
        run_report()   # tenant_id injected automatically
"""

from __future__ import annotations

import contextvars
import inspect
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Generator, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TenantContext:
    """Immutable tenant context for a bounded operation.

    Attributes
    ----------
    tenant_id :
        The tenant identifier.
    source :
        How this context was established. Examples: ``"jwt"``, ``"admin_override"``,
        ``"batch_job"``.
    authorized_by :
        Identity of the caller or service account that established this context.
        Used in audit logs to trace privilege escalations.
    """

    tenant_id: str
    source: str              # e.g. "jwt", "admin_override", "batch_job"
    authorized_by: str       # e.g. caller identity / service account name


# ---------------------------------------------------------------------------
# Context variable
# ---------------------------------------------------------------------------

_CURRENT_TENANT: contextvars.ContextVar[Optional[TenantContext]] = \
    contextvars.ContextVar("current_tenant", default=None)


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


@contextmanager
def scoped_tenant(ctx: TenantContext) -> Generator[TenantContext, None, None]:
    """Set ``_CURRENT_TENANT`` for the duration of a ``with`` block.

    The previous value is restored on exit, even if an exception is raised.

    Parameters
    ----------
    ctx :
        The :class:`TenantContext` to install as the current tenant.

    Yields
    ------
    TenantContext
        The same ``ctx`` that was passed in (for convenience in ``as`` clauses).
    """
    token = _CURRENT_TENANT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT_TENANT.reset(token)


# ---------------------------------------------------------------------------
# Guard function
# ---------------------------------------------------------------------------


def require_tenant_context() -> TenantContext:
    """Return the current :class:`TenantContext` or raise.

    Raises
    ------
    RuntimeError
        If no tenant context has been established with :func:`scoped_tenant`.
    """
    ctx = _CURRENT_TENANT.get()
    if ctx is None:
        raise RuntimeError(
            "No tenant context — call scoped_tenant() before executing tenant-scoped queries"
        )
    return ctx


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tenant_scoped(fn: Callable) -> Callable:
    """Decorator: call ``require_tenant_context()`` at the start of the function.

    If the decorated function's signature accepts a ``tenant_id`` parameter
    **and** the caller did not supply one, the ``tenant_id`` from the current
    :class:`TenantContext` is injected into the keyword arguments automatically.

    Raises
    ------
    RuntimeError
        If no tenant context is active when the decorated function is called.
    """
    sig = inspect.signature(fn)
    accepts_tenant_id = "tenant_id" in sig.parameters

    @wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        ctx = require_tenant_context()
        if accepts_tenant_id and "tenant_id" not in kwargs:
            # Only inject if the caller didn't already pass tenant_id
            kwargs["tenant_id"] = ctx.tenant_id  # type: ignore[assignment]
        return fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Admin override helper
# ---------------------------------------------------------------------------


def admin_override(tenant_id: str, *, authorized_by: str) -> "contextmanager":
    """Return a :func:`scoped_tenant` context manager pre-filled for admin access.

    Using this function makes admin bypasses **explicit and grep-able** in code
    review and audit tooling.  Every use of ``admin_override`` is a potential
    privilege escalation and must be justified.

    Parameters
    ----------
    tenant_id :
        The tenant whose data will be accessed.
    authorized_by :
        Identity of the caller / service account authorising the elevated access.

    Examples
    --------
    ::

        with admin_override("tenant-abc", authorized_by="data-eng-team"):
            # access is scoped to tenant-abc but admin-elevated
            run_migration(tenant_id="tenant-abc")
    """
    logger.info(
        "admin_override: elevated access to tenant=%s authorized_by=%s",
        tenant_id,
        authorized_by,
    )
    ctx = TenantContext(
        tenant_id=tenant_id,
        source="admin_override",
        authorized_by=authorized_by,
    )
    return scoped_tenant(ctx)
