-- =============================================================================
-- 005_tenant_portal.sql
-- Helix Decisions — tenant portal tables
-- Prompt 17: tenant_members (maps Firebase UIDs to tenant memberships)
-- Prompt 18: tenant_inquiries (pre-provisioning prospect staging — NO FK to tenants)
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- tenants
-- Central tenant registry (idempotent — skip if already exists).
-- =============================================================================
CREATE TABLE IF NOT EXISTS tenants (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        VARCHAR(100)    NOT NULL UNIQUE
                                    CHECK (slug ~ '^[a-z0-9][a-z0-9-]*[a-z0-9]$'),
    name        VARCHAR(255)    NOT NULL,
    status      VARCHAR(20)     NOT NULL DEFAULT 'active'
                                    CHECK (status IN ('active', 'suspended', 'deprovisioned')),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenants_slug    ON tenants (slug);
CREATE INDEX IF NOT EXISTS idx_tenants_status  ON tenants (status);

-- =============================================================================
-- tenant_members
-- Maps Firebase UIDs → tenant memberships.
-- A user may belong to multiple tenants (e.g., a consultant).
-- firebase_uid is stored as-is (not hashed) because it is a non-sensitive
-- opaque identifier issued by Firebase.
-- =============================================================================
CREATE TABLE IF NOT EXISTS tenant_members (
    id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID            NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    firebase_uid    VARCHAR(128)    NOT NULL,
    email           VARCHAR(255),
    role            VARCHAR(50)     NOT NULL DEFAULT 'member'
                                        CHECK (role IN ('owner', 'admin', 'analyst', 'member', 'readonly')),
    status          VARCHAR(20)     NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'suspended', 'revoked')),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_members_uid_tenant UNIQUE (firebase_uid, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_tenant_members_firebase_uid  ON tenant_members (firebase_uid);
CREATE INDEX IF NOT EXISTS idx_tenant_members_tenant_id     ON tenant_members (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_members_status        ON tenant_members (status);

-- =============================================================================
-- tenant_inquiries
-- Pre-provisioning staging table for prospect interest forms.
-- INTENTIONALLY has NO foreign key to the tenants table.
-- Submitting an inquiry grants zero system access until manual provisioning.
-- ip_hash: sha256 of the submitter's IP address — raw IPs are never stored.
-- =============================================================================
CREATE TABLE IF NOT EXISTS tenant_inquiries (
    id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(200)    NOT NULL,
    email       VARCHAR(320)    NOT NULL,
    company     VARCHAR(200)    NOT NULL,
    title       VARCHAR(200),
    use_case    TEXT            NOT NULL,
    volume      VARCHAR(50),
    referral    VARCHAR(500),
    created_at  TIMESTAMPTZ     NOT NULL DEFAULT now(),
    ip_hash     VARCHAR(64)     NOT NULL    -- sha256 hex digest; never raw IP
);

CREATE INDEX IF NOT EXISTS idx_tenant_inquiries_created_at  ON tenant_inquiries (created_at);
CREATE INDEX IF NOT EXISTS idx_tenant_inquiries_email       ON tenant_inquiries (email);
-- ip_hash index for rate-limit lookups
CREATE INDEX IF NOT EXISTS idx_tenant_inquiries_ip_hash     ON tenant_inquiries (ip_hash, created_at DESC);
