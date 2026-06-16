-- =============================================================================
-- Migration 004 — Tenant Config Registry
-- Phase 2 (P2.1) — Versioned, audited, rollback-capable configuration store
--
-- Tables introduced:
--   public.tenants            — one row per tenant
--   public.tenant_configs     — append-only version ledger
--   public.config_audit_events — every publish / rollback action
--
-- Design principles:
--   * tenant_configs rows are NEVER updated after insert — full audit trail
--   * active version is a pointer on the tenants row; rollbacks create new rows
--   * config_sha256 enables tamper detection without loading the JSON blob
--   * tenant_id + config_version has a UNIQUE constraint — prevents accidental
--     version collisions when two processes publish simultaneously
--
-- Run against the same PostgreSQL database as migrations 001-003.
-- For SQLite dev environments the equivalent DDL lives in
-- config_registry/service.py (_DDL string) and is applied automatically.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. tenants
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id             TEXT        PRIMARY KEY,
    name                  TEXT        NOT NULL,
    status                TEXT        NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'suspended', 'offboarded')),
    tier                  TEXT        NOT NULL DEFAULT 'standard'
                            CHECK (tier IN ('standard', 'enterprise')),
    active_config_version TEXT,       -- NULL until first config is published
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup by status (e.g. list active tenants)
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants (status);

COMMENT ON TABLE  tenants IS 'One row per tenant; active_config_version points to the live config snapshot.';
COMMENT ON COLUMN tenants.active_config_version IS
    'Version tag of the currently active tenant_configs row. NULL = use platform defaults.';

-- ---------------------------------------------------------------------------
-- 2. tenant_configs (append-only version ledger)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tenant_configs (
    id                       BIGSERIAL   PRIMARY KEY,
    tenant_id                TEXT        NOT NULL
                               REFERENCES tenants (tenant_id) ON DELETE RESTRICT,
    config_version           TEXT        NOT NULL,          -- e.g. "v1", "v2", "v12"
    config_sha256            TEXT        NOT NULL,          -- SHA-256 of canonical config_json
    approved_by              TEXT        NOT NULL,          -- email / user-id of approver
    approved_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config_json              JSONB       NOT NULL,          -- versioned config dictionary
    note                     TEXT        NOT NULL DEFAULT '',
    is_rollback              BOOLEAN     NOT NULL DEFAULT FALSE,
    rollback_source_version  TEXT,                          -- set only when is_rollback = TRUE
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_tenant_config_version UNIQUE (tenant_id, config_version)
);

-- Primary lookup: resolve active config for a tenant
CREATE INDEX IF NOT EXISTS idx_tc_tenant_version
    ON tenant_configs (tenant_id, config_version);

-- Allows listing version history ordered by creation time
CREATE INDEX IF NOT EXISTS idx_tc_tenant_created
    ON tenant_configs (tenant_id, created_at DESC);

-- Enables fast tenant-wide digest search (tamper detection scans)
CREATE INDEX IF NOT EXISTS idx_tc_sha256
    ON tenant_configs (config_sha256);

COMMENT ON TABLE  tenant_configs IS
    'Append-only version ledger. Every config change creates a new row; rows are never mutated.';
COMMENT ON COLUMN tenant_configs.config_json IS
    'JSONB config dictionary. May contain: policy_cutoffs, feature_toggles, pricing_overrides, rate_limits.';
COMMENT ON COLUMN tenant_configs.config_sha256 IS
    'SHA-256 hex digest of sort-key-normalised JSON. Used for tamper detection and de-duplication.';
COMMENT ON COLUMN tenant_configs.is_rollback IS
    'TRUE when this row was created by a rollback operation. rollback_source_version records what was restored.';

-- ---------------------------------------------------------------------------
-- 3. config_audit_events
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS config_audit_events (
    id          BIGSERIAL   PRIMARY KEY,
    tenant_id   TEXT        NOT NULL
                  REFERENCES tenants (tenant_id) ON DELETE RESTRICT,
    event_type  TEXT        NOT NULL
                  CHECK (event_type IN ('publish', 'activate', 'rollback', 'deactivate')),
    version_tag TEXT,
    actor       TEXT        NOT NULL,
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cae_tenant_created
    ON config_audit_events (tenant_id, created_at DESC);

COMMENT ON TABLE config_audit_events IS
    'Ordered log of every config lifecycle action for SR 11-7 defensibility.';

-- ---------------------------------------------------------------------------
-- 4. Helper function — auto-update tenants.updated_at on config activation
--    (optional; Decision API also sets this directly)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION fn_tenant_config_activated()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE tenants
       SET active_config_version = NEW.config_version,
           updated_at            = NOW()
     WHERE tenant_id = NEW.tenant_id;
    RETURN NEW;
END;
$$;

-- Trigger fires when a new tenant_config row is inserted and is_rollback = FALSE
-- (for rollbacks the service sets active_config_version directly; both paths
--  are handled but this trigger simplifies straight publishes.)
DROP TRIGGER IF EXISTS trg_activate_on_publish ON tenant_configs;
CREATE TRIGGER trg_activate_on_publish
    AFTER INSERT ON tenant_configs
    FOR EACH ROW
    WHEN (NEW.is_rollback = FALSE)
    EXECUTE FUNCTION fn_tenant_config_activated();

-- ---------------------------------------------------------------------------
-- 5. Seed — default platform tenant (used as fallback baseline)
-- ---------------------------------------------------------------------------

INSERT INTO tenants (tenant_id, name, status, tier, created_at, updated_at)
VALUES ('__platform__', 'Platform Defaults', 'active', 'enterprise', NOW(), NOW())
ON CONFLICT (tenant_id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- 6. Grant permissions (adjust role name to match your deployment)
-- ---------------------------------------------------------------------------

GRANT SELECT, INSERT ON tenant_configs        TO credit_user;
GRANT SELECT, INSERT, UPDATE ON tenants       TO credit_user;
GRANT SELECT, INSERT ON config_audit_events   TO credit_user;
GRANT USAGE, SELECT ON SEQUENCE tenant_configs_id_seq        TO credit_user;
GRANT USAGE, SELECT ON SEQUENCE config_audit_events_id_seq   TO credit_user;
