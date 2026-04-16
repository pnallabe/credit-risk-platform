"""
Tenant Branding / White-Label OEM — Sprint 8-B
================================================
Stores and serves per-tenant branding configuration so OEM partners and
white-label customers can present the credit-risk platform under their own
brand identity.

Configurable elements
---------------------
- Company name & display name
- Logo URL (light + dark variants)
- Primary / secondary / accent hex colours
- Custom domain (CNAME)
- API key prefix (e.g. "acme_live_…")
- Favicon URL
- Email sender name and reply-to address
- Custom footer / legal disclaimer text
- Feature flags (hide/show specific platform sections)

Public API
----------
>>> from config_registry.tenant_branding import TenantBrandingStore
>>> store = TenantBrandingStore()
>>> await store.initialise()
>>> branding = await store.get_branding("acme")
>>> updated = await store.upsert_branding(TenantBranding(tenant_id="acme", display_name="ACME Credit"))
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./credit_risk.db",
)

_DDL_TENANT_BRANDING = """
CREATE TABLE IF NOT EXISTS tenant_branding (
    tenant_id            TEXT PRIMARY KEY,
    display_name         TEXT NOT NULL,
    logo_url_light       TEXT,
    logo_url_dark        TEXT,
    favicon_url          TEXT,
    primary_color        TEXT DEFAULT '#2563EB',
    secondary_color      TEXT DEFAULT '#64748B',
    accent_color         TEXT DEFAULT '#F59E0B',
    custom_domain        TEXT,
    api_key_prefix       TEXT,
    email_sender_name    TEXT,
    email_reply_to       TEXT,
    footer_text          TEXT,
    feature_flags        TEXT DEFAULT '{}',   -- JSON object
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    updated_by           TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS tenant_branding_audit (
    audit_id             TEXT PRIMARY KEY,
    tenant_id            TEXT NOT NULL,
    changed_at           TEXT NOT NULL,
    changed_by           TEXT NOT NULL,
    change_type          TEXT NOT NULL,   -- CREATED | UPDATED | DELETED
    previous_snapshot    TEXT,            -- JSON of previous state
    new_snapshot         TEXT NOT NULL    -- JSON of new state
);
"""

# ---------------------------------------------------------------------------
# Colour / URL validators
# ---------------------------------------------------------------------------

_HEX_COLOUR_RE = re.compile(r"^#([A-Fa-f0-9]{3}|[A-Fa-f0-9]{6})$")
_DOMAIN_RE = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")
_API_KEY_PREFIX_RE = re.compile(r"^[a-z0-9_]{3,20}$")


def _validate_hex_colour(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not _HEX_COLOUR_RE.match(value):
        raise ValueError(f"{field_name} must be a valid hex colour (e.g. #2563EB), got: {value!r}")
    return value.upper()


def _validate_url(value: Optional[str], field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"{field_name} must be an http(s) URL, got: {value!r}")
    return value


def _validate_feature_flags(flags: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure all flag values are booleans."""
    invalid = {k: v for k, v in flags.items() if not isinstance(v, bool)}
    if invalid:
        raise ValueError(f"Feature flag values must be booleans, invalid keys: {list(invalid)}")
    return flags


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TenantBranding:
    """
    Full branding configuration for a single tenant / OEM partner.

    Parameters
    ----------
    tenant_id       Unique identifier matching the JWT tenant_id claim.
    display_name    Human-readable brand name shown in the UI header.
    """

    tenant_id: str
    display_name: str
    logo_url_light: Optional[str] = None   # Logo for light-mode backgrounds
    logo_url_dark: Optional[str] = None    # Logo for dark-mode backgrounds
    favicon_url: Optional[str] = None
    primary_color: str = "#2563EB"         # Main action / button colour
    secondary_color: str = "#64748B"       # Muted text / secondary controls
    accent_color: str = "#F59E0B"          # Highlights / warnings
    custom_domain: Optional[str] = None    # e.g. "risk.acme.com"
    api_key_prefix: Optional[str] = None   # e.g. "acme" → keys like "acme_live_…"
    email_sender_name: Optional[str] = None
    email_reply_to: Optional[str] = None
    footer_text: Optional[str] = None
    feature_flags: Dict[str, bool] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_by: str = "system"

    def __post_init__(self) -> None:
        _validate_hex_colour(self.primary_color, "primary_color")
        _validate_hex_colour(self.secondary_color, "secondary_color")
        _validate_hex_colour(self.accent_color, "accent_color")
        _validate_url(self.logo_url_light, "logo_url_light")
        _validate_url(self.logo_url_dark, "logo_url_dark")
        _validate_url(self.favicon_url, "favicon_url")
        if self.custom_domain and not _DOMAIN_RE.match(self.custom_domain):
            raise ValueError(
                f"custom_domain must be a valid FQDN, got: {self.custom_domain!r}"
            )
        if self.api_key_prefix and not _API_KEY_PREFIX_RE.match(self.api_key_prefix):
            raise ValueError(
                "api_key_prefix must be 3–20 lowercase alphanumeric/underscore chars, "
                f"got: {self.api_key_prefix!r}"
            )
        _validate_feature_flags(self.feature_flags)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "TenantBranding":
        """Construct from a SQLAlchemy result mapping."""
        flags_raw = row.get("feature_flags", "{}")
        flags = json.loads(flags_raw) if isinstance(flags_raw, str) else flags_raw
        return cls(
            tenant_id=row["tenant_id"],
            display_name=row["display_name"],
            logo_url_light=row.get("logo_url_light"),
            logo_url_dark=row.get("logo_url_dark"),
            favicon_url=row.get("favicon_url"),
            primary_color=row.get("primary_color", "#2563EB"),
            secondary_color=row.get("secondary_color", "#64748B"),
            accent_color=row.get("accent_color", "#F59E0B"),
            custom_domain=row.get("custom_domain"),
            api_key_prefix=row.get("api_key_prefix"),
            email_sender_name=row.get("email_sender_name"),
            email_reply_to=row.get("email_reply_to"),
            footer_text=row.get("footer_text"),
            feature_flags=flags,
            created_at=row.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=row.get("updated_at", datetime.now(timezone.utc).isoformat()),
            updated_by=row.get("updated_by", "system"),
        )


# ---------------------------------------------------------------------------
# Supported feature flags with descriptions
# ---------------------------------------------------------------------------

FEATURE_FLAG_CATALOGUE: Dict[str, str] = {
    "show_ai_explainability":   "Show AI explanation panel on decision detail pages",
    "show_fair_lending_tab":    "Show Fair Lending monitoring tab in analytics dashboard",
    "show_audit_log":           "Show raw audit log tab to compliance users",
    "show_model_health":        "Show model health metrics panel",
    "show_ab_testing":          "Show A/B experiment management panel (data scientists)",
    "show_executive_summary":   "Show NLG executive summary widget on dashboard",
    "enable_adverse_action_pdf": "Generate PDF adverse action notices",
    "enable_plaid_enrichment":  "Enable Plaid/Finicity bank data enrichment at origination",
    "enable_multi_product":     "Enable multi-product policy selection at origination",
    "enable_soc2_export":       "Allow compliance team to generate SOC 2 evidence packages",
    "dark_mode_default":        "Default dashboard theme to dark mode",
    "hide_score_raw":           "Hide raw model score from loan-officer view (show band only)",
    "require_mfa":              "Require MFA for all user logins to this tenant",
    "allow_override_without_approval": "Allow policy override without second approver (⚠️ not recommended)",
}


# ---------------------------------------------------------------------------
# TenantBrandingStore
# ---------------------------------------------------------------------------


class TenantBrandingStore:
    """
    Async CRUD store for tenant branding configurations.

    Usage
    -----
    >>> store = TenantBrandingStore()
    >>> await store.initialise()
    >>> branding = TenantBranding(tenant_id="acme", display_name="ACME Bank")
    >>> await store.upsert_branding(branding, changed_by="admin@acme.com")
    >>> fetched = await store.get_branding("acme")
    """

    def __init__(self, db_url: str = _DEFAULT_DB_URL) -> None:
        self._db_url = db_url
        self._engine: Optional[AsyncEngine] = None

    # ------------------------------------------------------------------ #
    async def initialise(self) -> None:
        """Create async engine and apply DDL migrations."""
        self._engine = create_async_engine(self._db_url, echo=False)
        async with self._engine.begin() as conn:
            for stmt in _DDL_TENANT_BRANDING.strip().split(";\n\n"):
                stmt = stmt.strip()
                if stmt:
                    await conn.execute(text(stmt))
        logger.info("TenantBrandingStore initialised")

    # ------------------------------------------------------------------ #
    async def get_branding(self, tenant_id: str) -> Optional[TenantBranding]:
        """
        Fetch branding config for *tenant_id*.  Returns None if not found.
        """
        if self._engine is None:
            return None
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM tenant_branding WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            row = result.fetchone()
        if row is None:
            return None
        return TenantBranding.from_row(dict(row._mapping))

    # ------------------------------------------------------------------ #
    async def upsert_branding(
        self,
        branding: TenantBranding,
        changed_by: str = "system",
    ) -> TenantBranding:
        """
        Create or fully replace the branding config for a tenant.
        Writes an audit trail entry for the change.
        """
        if self._engine is None:
            raise RuntimeError("Store not initialised — call await store.initialise() first")

        now = datetime.now(timezone.utc).isoformat()
        branding.updated_at = now
        branding.updated_by = changed_by

        async with self._engine.begin() as conn:
            # Snapshot previous state for audit
            prev_result = await conn.execute(
                text("SELECT * FROM tenant_branding WHERE tenant_id = :tid"),
                {"tid": branding.tenant_id},
            )
            prev_row = prev_result.fetchone()
            change_type = "UPDATED" if prev_row else "CREATED"
            previous_snapshot = json.dumps(dict(prev_row._mapping)) if prev_row else None

            await conn.execute(
                text("""
                    INSERT OR REPLACE INTO tenant_branding
                    (tenant_id, display_name, logo_url_light, logo_url_dark, favicon_url,
                     primary_color, secondary_color, accent_color, custom_domain,
                     api_key_prefix, email_sender_name, email_reply_to, footer_text,
                     feature_flags, created_at, updated_at, updated_by)
                    VALUES
                    (:tenant_id, :display_name, :logo_url_light, :logo_url_dark, :favicon_url,
                     :primary_color, :secondary_color, :accent_color, :custom_domain,
                     :api_key_prefix, :email_sender_name, :email_reply_to, :footer_text,
                     :feature_flags, :created_at, :updated_at, :updated_by)
                """),
                {
                    "tenant_id": branding.tenant_id,
                    "display_name": branding.display_name,
                    "logo_url_light": branding.logo_url_light,
                    "logo_url_dark": branding.logo_url_dark,
                    "favicon_url": branding.favicon_url,
                    "primary_color": branding.primary_color,
                    "secondary_color": branding.secondary_color,
                    "accent_color": branding.accent_color,
                    "custom_domain": branding.custom_domain,
                    "api_key_prefix": branding.api_key_prefix,
                    "email_sender_name": branding.email_sender_name,
                    "email_reply_to": branding.email_reply_to,
                    "footer_text": branding.footer_text,
                    "feature_flags": json.dumps(branding.feature_flags),
                    "created_at": branding.created_at if change_type == "CREATED" else (
                        json.loads(previous_snapshot or "{}").get("created_at", now)
                    ),
                    "updated_at": now,
                    "updated_by": changed_by,
                },
            )

            # Write audit trail
            await conn.execute(
                text("""
                    INSERT INTO tenant_branding_audit
                    (audit_id, tenant_id, changed_at, changed_by, change_type,
                     previous_snapshot, new_snapshot)
                    VALUES (:aid, :tid, :at, :by, :ct, :prev, :new)
                """),
                {
                    "aid": str(uuid.uuid4()),
                    "tid": branding.tenant_id,
                    "at": now,
                    "by": changed_by,
                    "ct": change_type,
                    "prev": previous_snapshot,
                    "new": branding.to_json(),
                },
            )

        logger.info(
            "Upserted branding for tenant=%s (type=%s, by=%s)",
            branding.tenant_id,
            change_type,
            changed_by,
        )
        return branding

    # ------------------------------------------------------------------ #
    async def patch_branding(
        self,
        tenant_id: str,
        updates: Dict[str, Any],
        changed_by: str = "system",
    ) -> Optional[TenantBranding]:
        """
        Partially update branding fields.  Only keys present in *updates* are altered.
        Returns the updated *TenantBranding*, or None if tenant not found.
        """
        existing = await self.get_branding(tenant_id)
        if existing is None:
            return None
        existing_dict = existing.to_dict()
        existing_dict.update(updates)
        # Re-construct to trigger validation
        updated = TenantBranding(
            tenant_id=existing_dict["tenant_id"],
            display_name=existing_dict["display_name"],
            logo_url_light=existing_dict.get("logo_url_light"),
            logo_url_dark=existing_dict.get("logo_url_dark"),
            favicon_url=existing_dict.get("favicon_url"),
            primary_color=existing_dict.get("primary_color", "#2563EB"),
            secondary_color=existing_dict.get("secondary_color", "#64748B"),
            accent_color=existing_dict.get("accent_color", "#F59E0B"),
            custom_domain=existing_dict.get("custom_domain"),
            api_key_prefix=existing_dict.get("api_key_prefix"),
            email_sender_name=existing_dict.get("email_sender_name"),
            email_reply_to=existing_dict.get("email_reply_to"),
            footer_text=existing_dict.get("footer_text"),
            feature_flags=existing_dict.get("feature_flags", {}),
            created_at=existing.created_at,
        )
        return await self.upsert_branding(updated, changed_by=changed_by)

    # ------------------------------------------------------------------ #
    async def delete_branding(
        self,
        tenant_id: str,
        deleted_by: str = "system",
    ) -> bool:
        """
        Soft-delete branding config by recording a DELETED audit entry
        then removing the row.  Returns True if a row was deleted.
        """
        if self._engine is None:
            return False
        async with self._engine.begin() as conn:
            prev_result = await conn.execute(
                text("SELECT * FROM tenant_branding WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
            prev_row = prev_result.fetchone()
            if prev_row is None:
                return False

            prev_json = json.dumps(dict(prev_row._mapping))
            now = datetime.now(timezone.utc).isoformat()

            await conn.execute(
                text("""
                    INSERT INTO tenant_branding_audit
                    (audit_id, tenant_id, changed_at, changed_by, change_type,
                     previous_snapshot, new_snapshot)
                    VALUES (:aid, :tid, :at, :by, 'DELETED', :prev, :new)
                """),
                {
                    "aid": str(uuid.uuid4()),
                    "tid": tenant_id,
                    "at": now,
                    "by": deleted_by,
                    "prev": prev_json,
                    "new": json.dumps({"deleted": True, "deleted_by": deleted_by, "at": now}),
                },
            )
            await conn.execute(
                text("DELETE FROM tenant_branding WHERE tenant_id = :tid"),
                {"tid": tenant_id},
            )
        logger.info("Deleted branding for tenant=%s (by=%s)", tenant_id, deleted_by)
        return True

    # ------------------------------------------------------------------ #
    async def list_tenants(self) -> List[Dict[str, str]]:
        """Return a lightweight list of all tenants with branding records."""
        if self._engine is None:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("""
                    SELECT tenant_id, display_name, custom_domain,
                           updated_at, updated_by
                    FROM tenant_branding
                    ORDER BY display_name
                """)
            )
            return [dict(r._mapping) for r in rows.fetchall()]

    # ------------------------------------------------------------------ #
    async def get_audit_history(
        self,
        tenant_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return the last *limit* audit entries for *tenant_id*."""
        if self._engine is None:
            return []
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("""
                    SELECT audit_id, tenant_id, changed_at, changed_by,
                           change_type, previous_snapshot, new_snapshot
                    FROM tenant_branding_audit
                    WHERE tenant_id = :tid
                    ORDER BY changed_at DESC
                    LIMIT :lim
                """),
                {"tid": tenant_id, "lim": limit},
            )
            return [dict(r._mapping) for r in rows.fetchall()]

    # ------------------------------------------------------------------ #
    async def get_css_variables(self, tenant_id: str) -> str:
        """
        Return a CSS custom-properties block for the tenant's brand colours.
        Returns default colours if tenant has no branding record.

        Example output::

            :root {
              --color-primary: #2563EB;
              --color-secondary: #64748B;
              --color-accent: #F59E0B;
            }
        """
        branding = await self.get_branding(tenant_id)
        if branding is None:
            primary, secondary, accent = "#2563EB", "#64748B", "#F59E0B"
        else:
            primary = branding.primary_color
            secondary = branding.secondary_color
            accent = branding.accent_color

        return (
            ":root {\n"
            f"  --color-primary: {primary};\n"
            f"  --color-secondary: {secondary};\n"
            f"  --color-accent: {accent};\n"
            "}\n"
        )
