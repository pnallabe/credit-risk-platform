"""
Tests for Sprint 8-B: TenantBrandingStore (config_registry/tenant_branding.py)
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from config_registry.tenant_branding import (
    FEATURE_FLAG_CATALOGUE,
    TenantBranding,
    TenantBrandingStore,
    _validate_hex_colour,
    _validate_url,
)

DB_URL = "sqlite+aiosqlite:///:memory:"


def _branding(**kwargs) -> TenantBranding:
    defaults = dict(
        tenant_id="acme",
        display_name="ACME Bank",
        primary_color="#2563EB",
        secondary_color="#64748B",
        accent_color="#F59E0B",
    )
    defaults.update(kwargs)
    return TenantBranding(**defaults)


@pytest.fixture
async def store():
    s = TenantBrandingStore(db_url=DB_URL)
    await s.initialise()
    return s


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def test_valid_hex_colour():
    assert _validate_hex_colour("#2563EB", "x") == "#2563EB"


def test_valid_short_hex():
    assert _validate_hex_colour("#FFF", "x") == "#FFF"


def test_invalid_hex_raises():
    with pytest.raises(ValueError, match="hex colour"):
        _validate_hex_colour("not-a-colour", "x")


def test_valid_url():
    assert _validate_url("https://cdn.acme.com/logo.png", "x") is not None


def test_invalid_url_raises():
    with pytest.raises(ValueError, match="http"):
        _validate_url("cdn.acme.com/logo.png", "x")


# ---------------------------------------------------------------------------
# TenantBranding validation
# ---------------------------------------------------------------------------

def test_branding_invalid_primary_color_raises():
    with pytest.raises(ValueError):
        TenantBranding(tenant_id="x", display_name="X", primary_color="red")


def test_branding_invalid_custom_domain_raises():
    with pytest.raises(ValueError, match="FQDN"):
        TenantBranding(tenant_id="x", display_name="X", custom_domain="not a domain!")


def test_branding_invalid_api_key_prefix_raises():
    with pytest.raises(ValueError, match="api_key_prefix"):
        TenantBranding(tenant_id="x", display_name="X", api_key_prefix="IN VALID!")


def test_branding_invalid_feature_flag_value_raises():
    with pytest.raises(ValueError, match="boolean"):
        TenantBranding(tenant_id="x", display_name="X", feature_flags={"show_audit_log": "yes"})


# ---------------------------------------------------------------------------
# CRUD — get_branding returns None for unknown tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_branding_unknown_tenant_returns_none(store):
    result = await store.get_branding("nonexistent")
    assert result is None


# ---------------------------------------------------------------------------
# CRUD — upsert creates and can be fetched
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_then_get(store):
    b = _branding()
    await store.upsert_branding(b, changed_by="admin")
    fetched = await store.get_branding("acme")
    assert fetched is not None
    assert fetched.display_name == "ACME Bank"
    assert fetched.primary_color == "#2563EB"


# ---------------------------------------------------------------------------
# CRUD — upsert updates existing record
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_updates_existing(store):
    await store.upsert_branding(_branding(display_name="ACME v1"))
    await store.upsert_branding(_branding(display_name="ACME v2"))
    fetched = await store.get_branding("acme")
    assert fetched.display_name == "ACME v2"


# ---------------------------------------------------------------------------
# patch_branding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_updates_only_specified_fields(store):
    await store.upsert_branding(_branding())
    updated = await store.patch_branding("acme", {"display_name": "ACME Corp"})
    assert updated is not None
    assert updated.display_name == "ACME Corp"
    assert updated.primary_color == "#2563EB"  # unchanged


@pytest.mark.asyncio
async def test_patch_nonexistent_tenant_returns_none(store):
    result = await store.patch_branding("ghost", {"display_name": "Ghost"})
    assert result is None


# ---------------------------------------------------------------------------
# delete_branding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_removes_record(store):
    await store.upsert_branding(_branding())
    deleted = await store.delete_branding("acme")
    assert deleted is True
    assert await store.get_branding("acme") is None


@pytest.mark.asyncio
async def test_delete_nonexistent_returns_false(store):
    result = await store.delete_branding("ghost")
    assert result is False


# ---------------------------------------------------------------------------
# list_tenants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_tenants_returns_all(store):
    await store.upsert_branding(_branding(tenant_id="acme", display_name="ACME"))
    await store.upsert_branding(_branding(tenant_id="betabank", display_name="Beta Bank"))
    tenants = await store.list_tenants()
    assert len(tenants) == 2
    names = {t["display_name"] for t in tenants}
    assert names == {"ACME", "Beta Bank"}


# ---------------------------------------------------------------------------
# get_audit_history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_history_created_on_upsert(store):
    await store.upsert_branding(_branding())
    history = await store.get_audit_history("acme")
    assert len(history) == 1
    assert history[0]["change_type"] == "CREATED"


@pytest.mark.asyncio
async def test_audit_history_updated_entry(store):
    await store.upsert_branding(_branding())
    await store.upsert_branding(_branding(display_name="New Name"))
    history = await store.get_audit_history("acme")
    change_types = [h["change_type"] for h in history]
    assert "UPDATED" in change_types


@pytest.mark.asyncio
async def test_audit_history_delete_entry(store):
    await store.upsert_branding(_branding())
    await store.delete_branding("acme")
    history = await store.get_audit_history("acme")
    change_types = [h["change_type"] for h in history]
    assert "DELETED" in change_types


# ---------------------------------------------------------------------------
# get_css_variables
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_css_variables_with_branding(store):
    await store.upsert_branding(_branding(primary_color="#123456"))
    css = await store.get_css_variables("acme")
    assert "--color-primary: #123456" in css
    assert ":root" in css


@pytest.mark.asyncio
async def test_get_css_variables_defaults_for_unknown_tenant(store):
    css = await store.get_css_variables("nobody")
    assert "--color-primary: #2563EB" in css


# ---------------------------------------------------------------------------
# Feature flag catalogue
# ---------------------------------------------------------------------------

def test_feature_flag_catalogue_non_empty():
    assert len(FEATURE_FLAG_CATALOGUE) >= 10


def test_feature_flag_entries_are_strings():
    for k, v in FEATURE_FLAG_CATALOGUE.items():
        assert isinstance(k, str)
        assert isinstance(v, str)
