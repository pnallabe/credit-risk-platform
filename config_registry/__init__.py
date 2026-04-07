"""
config_registry — Tenant Config Registry (Phase 2, P2.1)
=========================================================
Versioned, audited, and rollback-capable configuration store for per-tenant
policy cutoffs and feature toggles.

Exports
-------
    TenantRecord          — ORM-backed tenant row model
    TenantConfigVersion   — single versioned config snapshot
    ConfigRegistryService — resolution, activation, rollback, audit
"""

from .models import TenantConfigVersion, TenantRecord
from .service import ConfigRegistryService

__all__ = ["TenantRecord", "TenantConfigVersion", "ConfigRegistryService"]
