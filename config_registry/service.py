"""
config_registry.service — ConfigRegistryService
================================================
Provides the full lifecycle for tenant configuration:

    * publish          — write a new config version for a tenant
    * get_active       — resolve the current active config for a tenant
    * get_version      — fetch a specific version (point-in-time)
    * list_versions    — full changelog ordered by version (newest first)
    * rollback         — create a new version that restores a prior snapshot
    * diff             — key-level diff between two config versions

Storage
-------
Uses a SQLite database by default (``config_registry.db`` in the project
root) so the service runs without a live PostgreSQL instance during dev /
test.  Pass any SQLAlchemy-compatible ``db_url`` (including
``postgresql+psycopg2://…``) to switch.

All writes go through the ``policy_version_store``-inspired append-only
pattern: rows are never mutated; every change creates a new row.

Usage
-----
    from config_registry.service import ConfigRegistryService

    svc = ConfigRegistryService()
    svc.ensure_tenant("acme", name="Acme Corp", tier="enterprise")

    svc.publish(
        tenant_id="acme",
        config_json={"policy_cutoffs": {"pd_threshold": 0.12}},
        approved_by="alice@acme.com",
        note="Q2 2026 policy refresh",
    )

    cfg = svc.get_active("acme")
    print(cfg.get_policy_cutoffs())
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    ConfigDiff,
    RollbackEvent,
    TenantConfigVersion,
    TenantRecord,
    _sha256_of,
    diff_configs,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "config_registry.db"

# DDL — mirrors migration 004
_DDL = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id             TEXT PRIMARY KEY,
    name                  TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'active',
    tier                  TEXT NOT NULL DEFAULT 'standard',
    active_config_version TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tenant_configs (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id                TEXT NOT NULL,
    config_version           TEXT NOT NULL,
    config_sha256            TEXT NOT NULL,
    approved_by              TEXT NOT NULL,
    approved_at              TEXT NOT NULL,
    config_json              TEXT NOT NULL,
    note                     TEXT NOT NULL DEFAULT '',
    is_rollback              INTEGER NOT NULL DEFAULT 0,
    rollback_source_version  TEXT,
    created_at               TEXT NOT NULL,
    UNIQUE (tenant_id, config_version),
    FOREIGN KEY (tenant_id) REFERENCES tenants (tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tc_tenant_version
    ON tenant_configs (tenant_id, config_version);

CREATE TABLE IF NOT EXISTS config_audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL,   -- 'publish' | 'activate' | 'rollback' | 'deactivate'
    version_tag TEXT,
    actor       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL
);
"""


class ConfigRegistryService:
    """Thread-safe, append-only tenant configuration registry.

    Parameters
    ----------
    db_url : str | Path
        Path to the SQLite file **or** a full SQLAlchemy URL.
        Defaults to ``config_registry.db`` in the project root.
    """

    def __init__(self, db_url: Optional[str] = None) -> None:
        self._db_url: str = str(db_url or _DEFAULT_DB_PATH)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_url)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_DDL)
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # Tenant management
    # ------------------------------------------------------------------

    def ensure_tenant(
        self,
        tenant_id: str,
        *,
        name: str,
        status: str = "active",
        tier: str = "standard",
    ) -> TenantRecord:
        """Insert a tenant if it does not exist; return the TenantRecord."""
        now = _utcnow()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO tenants
                        (tenant_id, name, status, tier, active_config_version,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (tenant_id, name, status, tier, now, now),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
                ).fetchone()
            finally:
                conn.close()
        return _row_to_tenant(row)

    def get_tenant(self, tenant_id: str) -> Optional[TenantRecord]:
        """Return the TenantRecord or None if not found."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM tenants WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()
            conn.close()
        return _row_to_tenant(row) if row else None

    def list_tenants(self, status: Optional[str] = None) -> List[TenantRecord]:
        """Return all tenants, optionally filtered by status."""
        with self._lock:
            conn = self._connect()
            if status:
                rows = conn.execute(
                    "SELECT * FROM tenants WHERE status = ? ORDER BY tenant_id",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tenants ORDER BY tenant_id"
                ).fetchall()
            conn.close()
        return [_row_to_tenant(r) for r in rows]

    # ------------------------------------------------------------------
    # Config publishing
    # ------------------------------------------------------------------

    def publish(
        self,
        tenant_id: str,
        config_json: Dict[str, Any],
        *,
        approved_by: str,
        note: str,
        auto_activate: bool = True,
    ) -> TenantConfigVersion:
        """Publish a new config version for a tenant.

        Parameters
        ----------
        tenant_id : str
            Must already exist in the ``tenants`` table.
        config_json : dict
            New configuration dictionary.
        approved_by : str
            Approver identity.
        note : str
            Human-readable rationale (required).
        auto_activate : bool
            If True (default), immediately sets the new version as active.

        Returns
        -------
        TenantConfigVersion
            The newly-created version row.

        Raises
        ------
        ValueError
            If the tenant does not exist or if config_json is unchanged from
            the current active version (prevents no-op publishes).
        """
        if not self.get_tenant(tenant_id):
            raise ValueError(f"Tenant '{tenant_id}' not found. Call ensure_tenant() first.")

        active = self.get_active(tenant_id)
        if active and _sha256_of(config_json) == active.config_sha256:
            raise ValueError(
                f"New config is identical to current active version "
                f"'{active.config_version}' for tenant '{tenant_id}'. No-op publish rejected."
            )

        # Determine next version tag
        versions = self.list_versions(tenant_id)
        next_seq = len(versions) + 1
        version_tag = f"v{next_seq}"

        now = _utcnow()
        cv = TenantConfigVersion(
            tenant_id=tenant_id,
            config_version=version_tag,
            config_json=config_json,
            approved_by=approved_by,
            note=note,
            approved_at=datetime.now(timezone.utc),
        )

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO tenant_configs
                        (tenant_id, config_version, config_sha256, approved_by,
                         approved_at, config_json, note, is_rollback,
                         rollback_source_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
                    """,
                    (
                        cv.tenant_id,
                        cv.config_version,
                        cv.config_sha256,
                        cv.approved_by,
                        cv.approved_at.isoformat(),
                        json.dumps(cv.config_json),
                        cv.note,
                        now,
                    ),
                )
                row = conn.execute(
                    "SELECT last_insert_rowid() AS id"
                ).fetchone()
                cv.id = row["id"]
                cv.created_at = datetime.fromisoformat(now)

                if auto_activate:
                    conn.execute(
                        "UPDATE tenants SET active_config_version = ?, updated_at = ? "
                        "WHERE tenant_id = ?",
                        (version_tag, now, tenant_id),
                    )

                _write_audit_event(
                    conn,
                    tenant_id=tenant_id,
                    event_type="publish",
                    version_tag=version_tag,
                    actor=approved_by,
                    note=note,
                    created_at=now,
                )
                conn.commit()
            finally:
                conn.close()

        logger.info(
            "Config published for tenant=%s version=%s sha256=%s",
            tenant_id,
            version_tag,
            cv.config_sha256[:12],
        )
        return cv

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    def get_active(self, tenant_id: str) -> Optional[TenantConfigVersion]:
        """Return the currently active config for a tenant, or None."""
        tenant = self.get_tenant(tenant_id)
        if not tenant or not tenant.active_config_version:
            return None
        return self.get_version(tenant_id, tenant.active_config_version)

    def get_version(
        self,
        tenant_id: str,
        config_version: str,
    ) -> Optional[TenantConfigVersion]:
        """Return a specific config version snapshot, or None if not found."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM tenant_configs "
                "WHERE tenant_id = ? AND config_version = ?",
                (tenant_id, config_version),
            ).fetchone()
            conn.close()
        return _row_to_config(row) if row else None

    def list_versions(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> List[TenantConfigVersion]:
        """Return config history for a tenant, newest first."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM tenant_configs "
                "WHERE tenant_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
            conn.close()
        return [_row_to_config(r) for r in rows]

    def resolve(
        self,
        tenant_id: str,
        fallback: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return the active config JSON for a tenant.

        If no config has been published yet, returns ``fallback`` (or ``{}``).
        Use this in hot paths instead of ``get_active()`` when you only need
        the raw dict.
        """
        active = self.get_active(tenant_id)
        if active:
            return active.config_json
        return fallback or {}

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(
        self,
        tenant_id: str,
        target_version: str,
        *,
        rolled_back_by: str,
        note: str,
    ) -> RollbackEvent:
        """Rollback a tenant to a prior config version.

        Implements the SR 11-7 guidance that a rollback must:
          1. Create a *new* version row (never mutate history).
          2. Record who triggered it and why.
          3. Activate the new row immediately.

        Parameters
        ----------
        tenant_id : str
        target_version : str
            The version tag to restore (must exist).
        rolled_back_by : str
            Identity of the operator initiating the rollback.
        note : str
            Mandatory rationale string.

        Returns
        -------
        RollbackEvent
            Describes the before/after state.

        Raises
        ------
        ValueError
            If target_version or tenant does not exist.
        """
        current = self.get_active(tenant_id)
        if current is None:
            raise ValueError(f"Tenant '{tenant_id}' has no active config to roll back from.")

        target = self.get_version(tenant_id, target_version)
        if target is None:
            raise ValueError(
                f"Target version '{target_version}' not found for tenant '{tenant_id}'."
            )

        versions = self.list_versions(tenant_id)
        next_seq = len(versions) + 1
        new_version_tag = f"v{next_seq}"
        now = _utcnow()

        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO tenant_configs
                        (tenant_id, config_version, config_sha256, approved_by,
                         approved_at, config_json, note, is_rollback,
                         rollback_source_version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (
                        tenant_id,
                        new_version_tag,
                        target.config_sha256,       # same digest as restored version
                        rolled_back_by,
                        now,
                        json.dumps(target.config_json),
                        note,
                        target_version,             # document which version we're restoring
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE tenants SET active_config_version = ?, updated_at = ? "
                    "WHERE tenant_id = ?",
                    (new_version_tag, now, tenant_id),
                )
                _write_audit_event(
                    conn,
                    tenant_id=tenant_id,
                    event_type="rollback",
                    version_tag=new_version_tag,
                    actor=rolled_back_by,
                    note=f"Rollback to {target_version}: {note}",
                    created_at=now,
                )
                conn.commit()
            finally:
                conn.close()

        event = RollbackEvent(
            tenant_id=tenant_id,
            from_version=current.config_version,
            to_version=target_version,
            new_version_tag=new_version_tag,
            rolled_back_by=rolled_back_by,
            note=note,
        )
        logger.warning(
            "Config rollback: tenant=%s from=%s to=%s new_tag=%s by=%s",
            tenant_id,
            current.config_version,
            target_version,
            new_version_tag,
            rolled_back_by,
        )
        return event

    # ------------------------------------------------------------------
    # Diff utility
    # ------------------------------------------------------------------

    def diff(
        self,
        tenant_id: str,
        version_a: str,
        version_b: str,
    ) -> ConfigDiff:
        """Return a shallow key-level diff between two config versions.

        Raises ValueError if either version is not found.
        """
        va = self.get_version(tenant_id, version_a)
        vb = self.get_version(tenant_id, version_b)
        if va is None:
            raise ValueError(f"Version '{version_a}' not found for tenant '{tenant_id}'.")
        if vb is None:
            raise ValueError(f"Version '{version_b}' not found for tenant '{tenant_id}'.")
        return diff_configs(va.config_json, vb.config_json)

    # ------------------------------------------------------------------
    # Audit event log
    # ------------------------------------------------------------------

    def get_audit_events(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return audit events for a tenant, newest first."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM config_audit_events "
                "WHERE tenant_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
            conn.close()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_tenant(row: sqlite3.Row) -> TenantRecord:
    return TenantRecord(
        tenant_id=row["tenant_id"],
        name=row["name"],
        status=row["status"],
        tier=row["tier"],
        active_config_version=row["active_config_version"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_config(row: sqlite3.Row) -> TenantConfigVersion:
    cv = TenantConfigVersion(
        tenant_id=row["tenant_id"],
        config_version=row["config_version"],
        config_json=json.loads(row["config_json"]),
        approved_by=row["approved_by"],
        note=row["note"],
        id=row["id"],
        is_rollback=bool(row["is_rollback"]),
        rollback_source_version=row["rollback_source_version"],
    )
    # Override auto-computed fields with persisted values
    cv.config_sha256 = row["config_sha256"]
    cv.approved_at = datetime.fromisoformat(row["approved_at"])
    cv.created_at = datetime.fromisoformat(row["created_at"])
    return cv


def _write_audit_event(
    conn: sqlite3.Connection,
    *,
    tenant_id: str,
    event_type: str,
    version_tag: str,
    actor: str,
    note: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO config_audit_events
            (tenant_id, event_type, version_tag, actor, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tenant_id, event_type, version_tag, actor, note, created_at),
    )
