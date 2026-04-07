"""
config_registry.models — Domain models for the Tenant Config Registry
======================================================================
Data classes that represent the two core tables introduced in migration 004:

    tenants            — one row per tenant; carries status and tier metadata
    tenant_configs     — append-only version ledger; every config change is a
                         new row.  A pointer (active_config_version) on the
                         tenants row indicates the live version.

These classes are deliberately free of any ORM dependency so they can be
serialised / deserialised cleanly and used in tests without a database.

SQLAlchemy ORM declarations are in ``config_registry/orm.py`` if you need
to persist using SQLAlchemy Core / async sessions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------


@dataclass
class TenantRecord:
    """Represents a row in the ``tenants`` table.

    Attributes
    ----------
    tenant_id : str
        Globally unique tenant identifier (UUID or slug).
    name : str
        Human-readable display name.
    status : str
        One of ``"active"`` | ``"suspended"`` | ``"offboarded"``.
    tier : str
        Service tier, e.g. ``"standard"`` | ``"enterprise"``.
    active_config_version : Optional[str]
        Version tag of the currently active ``TenantConfigVersion``.
        NULL means no config has been published yet — fall back to defaults.
    created_at : datetime
        UTC timestamp of tenant creation.
    updated_at : datetime
        UTC timestamp of the last metadata update.
    """

    tenant_id: str
    name: str
    status: str = "active"                      # active | suspended | offboarded
    tier: str = "standard"                      # standard | enterprise
    active_config_version: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def is_active(self) -> bool:
        return self.status == "active"


# ---------------------------------------------------------------------------
# Tenant Config Version
# ---------------------------------------------------------------------------


@dataclass
class TenantConfigVersion:
    """Represents a row in the ``tenant_configs`` table.

    Every configuration change for a tenant produces a *new* row.
    Rows are never mutated after creation — this gives an immutable audit
    trail and makes point-in-time replay straightforward.

    Attributes
    ----------
    id : Optional[int]
        Auto-incremented primary key (None until persisted).
    tenant_id : str
        Foreign key → ``tenants.tenant_id``.
    config_version : str
        Monotonic version tag, e.g. ``"v1"``, ``"v2"``, etc.
    config_sha256 : str
        SHA-256 hex digest of ``config_json`` for tamper detection.
    approved_by : str
        Identity of the approver (email, user_id, or service account).
    approved_at : datetime
        UTC timestamp when the config was approved.
    config_json : Dict[str, Any]
        Versioned configuration dictionary.  May contain:
          - ``policy_cutoffs``    : per-model score thresholds
          - ``feature_toggles``   : enabled feature flags
          - ``pricing_overrides`` : tenant-specific pricing params
          - ``rate_limits``       : per-route token-bucket settings
        The exact schema is intentionally open so tenants can store any
        key they need without requiring a DDL migration.
    note : str
        Free-text rationale for the change (required for audit trail).
    is_rollback : bool
        True when this version was created by a rollback operation.
    rollback_source_version : Optional[str]
        For rollback rows, the version tag that was restored.
    created_at : datetime
        UTC timestamp of insert.
    """

    tenant_id: str
    config_version: str
    config_json: Dict[str, Any]
    approved_by: str
    note: str
    id: Optional[int] = None
    config_sha256: str = ""
    approved_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    is_rollback: bool = False
    rollback_source_version: Optional[str] = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def __post_init__(self) -> None:
        # Always compute the digest from canonical JSON so callers don't have
        # to pass it explicitly.
        if not self.config_sha256:
            self.config_sha256 = _sha256_of(self.config_json)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "config_version": self.config_version,
            "config_sha256": self.config_sha256,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat(),
            "config_json": self.config_json,
            "note": self.note,
            "is_rollback": self.is_rollback,
            "rollback_source_version": self.rollback_source_version,
            "created_at": self.created_at.isoformat(),
        }

    def get_policy_cutoffs(self) -> Dict[str, Any]:
        return self.config_json.get("policy_cutoffs", {})

    def get_feature_toggles(self) -> Dict[str, bool]:
        return self.config_json.get("feature_toggles", {})

    def get_pricing_overrides(self) -> Dict[str, Any]:
        return self.config_json.get("pricing_overrides", {})

    def get_rate_limits(self) -> Dict[str, Any]:
        return self.config_json.get("rate_limits", {})


# ---------------------------------------------------------------------------
# Rollback intent record (returned by ConfigRegistryService.rollback)
# ---------------------------------------------------------------------------


@dataclass
class RollbackEvent:
    """Describes the result of a rollback operation.

    Attributes
    ----------
    tenant_id : str
        Tenant whose config was rolled back.
    from_version : str
        Active version at the time rollback was initiated.
    to_version : str
        Version that was restored (now the new active version).
    new_version_tag : str
        Version tag of the newly created row that represents the rollback.
    rolled_back_by : str
        Identity of who triggered the rollback.
    note : str
        Rationale stored in the new config row's note field.
    timestamp : datetime
        UTC timestamp of the rollback.
    """

    tenant_id: str
    from_version: str
    to_version: str
    new_version_tag: str
    rolled_back_by: str
    note: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Config diff (utility used by the service when comparing versions)
# ---------------------------------------------------------------------------


@dataclass
class ConfigDiff:
    """Key-level diff between two config versions.

    Attributes
    ----------
    added : List[str]
        Keys present in ``new`` but not in ``old``.
    removed : List[str]
        Keys present in ``old`` but not in ``new``.
    changed : Dict[str, tuple]
        Keys whose values changed; ``{key: (old_value, new_value)}``.
    """

    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    changed: Dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


def diff_configs(
    old: Dict[str, Any],
    new: Dict[str, Any],
) -> ConfigDiff:
    """Return a shallow key-level diff between two config dicts."""
    old_keys = set(old)
    new_keys = set(new)
    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    changed = {
        k: (old[k], new[k])
        for k in old_keys & new_keys
        if old[k] != new[k]
    }
    return ConfigDiff(added=added, removed=removed, changed=changed)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_of(obj: Dict[str, Any]) -> str:
    """Return the SHA-256 hex-digest of the canonical (sorted-keys) JSON."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
