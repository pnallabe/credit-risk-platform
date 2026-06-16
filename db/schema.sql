-- =============================================================================
-- Credit Risk Platform — PostgreSQL Schema
-- =============================================================================

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =============================================================================
-- 1. loan_applications
--    Mirrors the LoanApplication Pydantic model in ingestion-api/src/models.py
-- =============================================================================
CREATE TABLE IF NOT EXISTS loan_applications (
    tenant_id               VARCHAR(50)     NOT NULL,
    application_id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID            NOT NULL,
    account_id              UUID,

    -- Loan details
    loan_amount             NUMERIC(14, 2)  NOT NULL CHECK (loan_amount > 0),
    loan_purpose            VARCHAR(50)     NOT NULL,
    loan_term_months        SMALLINT        NOT NULL CHECK (loan_term_months IN (12, 24, 36, 48, 60)),
    interest_rate           NUMERIC(6, 4),

    -- Applicant information
    annual_income           NUMERIC(14, 2)  CHECK (annual_income >= 0),
    employment_status       VARCHAR(20)     CHECK (employment_status IN ('employed','self-employed','unemployed','retired')),
    employer_tenure_months  INT             CHECK (employer_tenure_months >= 0),

    -- Credit information
    credit_score            SMALLINT        CHECK (credit_score BETWEEN 300 AND 850),
    debt_to_income_ratio    NUMERIC(5, 4)   CHECK (debt_to_income_ratio BETWEEN 0 AND 0.65),
    existing_debt_amount    NUMERIC(14, 2)  CHECK (existing_debt_amount >= 0),
    num_open_accounts       SMALLINT        CHECK (num_open_accounts >= 0),
    num_derogatory_marks    SMALLINT        CHECK (num_derogatory_marks >= 0),
    months_since_last_delinquency INT,

    -- Geography
    state                   CHAR(2),
    zip_code_prefix         CHAR(3),

    -- Metadata
    applied_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    channel                 VARCHAR(30),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loan_apps_customer_id ON loan_applications (customer_id);
CREATE INDEX IF NOT EXISTS idx_loan_apps_applied_at  ON loan_applications (applied_at);


-- =============================================================================
-- 2. features
--    Feature store — one row per (application_id, feature_set_version, as_of_date)
--
--    Point-in-time correctness:
--      as_of_date  — the business date these features represent.  Use this
--                    for all backtesting queries to prevent look-ahead bias.
--      event_timestamp — UTC wall-clock moment features were computed.
--
--    The unique constraint is on (application_id, feature_set_version, as_of_date)
--    so that different historical snapshots for the same application co-exist.
-- =============================================================================
CREATE TABLE IF NOT EXISTS features (
    tenant_id               VARCHAR(50)     NOT NULL,
    id                          BIGSERIAL       PRIMARY KEY,
    application_id              UUID            NOT NULL REFERENCES loan_applications(application_id) ON DELETE CASCADE,
    feature_set_version         VARCHAR(50)     NOT NULL,
    event_timestamp             TIMESTAMPTZ     NOT NULL,
    as_of_date                  DATE            NOT NULL,
    computed_at                 TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Computed features
    credit_utilization          NUMERIC(8, 6),
    income_stability_score      NUMERIC(8, 6),
    repayment_capacity          NUMERIC(8, 6),
    debt_service_coverage_ratio NUMERIC(12, 4),
    credit_age_months           INT,
    payment_history_score       NUMERIC(8, 6),

    -- Overflow bucket for additional computed features
    feature_json                JSONB,

    CONSTRAINT uq_features_app_version_date UNIQUE (application_id, feature_set_version, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_features_application_id ON features (application_id);
CREATE INDEX IF NOT EXISTS idx_features_version        ON features (feature_set_version);
CREATE INDEX IF NOT EXISTS idx_features_as_of_date     ON features (as_of_date);
CREATE INDEX IF NOT EXISTS idx_features_computed_at    ON features (computed_at);

-- =============================================================================
-- 2b. feature_read_audit
--     Immutable append-only record of every read from the feature store.
--     Used to prove point-in-time correctness and detect look-ahead bias.
--     feature_hash = sha256(sorted JSON of all feature values for that row).
-- =============================================================================
CREATE TABLE IF NOT EXISTS feature_read_audit (
    tenant_id               VARCHAR(50)     NOT NULL,
    id                   BIGSERIAL    PRIMARY KEY,
    application_id       TEXT         NOT NULL,
    feature_set_version  VARCHAR(50)  NOT NULL,
    as_of_date           DATE         NOT NULL,
    event_timestamp      TIMESTAMPTZ  NOT NULL,
    feature_hash         TEXT         NOT NULL,
    read_at              TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feat_audit_app    ON feature_read_audit (application_id);
CREATE INDEX IF NOT EXISTS idx_feat_audit_read   ON feature_read_audit (read_at);


-- =============================================================================
-- 3. model_predictions
--    One row per model inference run
-- =============================================================================
CREATE TABLE IF NOT EXISTS model_predictions (
    tenant_id               VARCHAR(50)     NOT NULL,
    prediction_id   UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id  UUID            NOT NULL REFERENCES loan_applications(application_id) ON DELETE CASCADE,
    model_name      VARCHAR(100)    NOT NULL,
    model_version   VARCHAR(50)     NOT NULL,
    predicted_at    TIMESTAMPTZ     NOT NULL DEFAULT now(),
    score           NUMERIC(8, 6)   NOT NULL CHECK (score BETWEEN 0 AND 1),
    label           VARCHAR(30)     NOT NULL,
    confidence      NUMERIC(8, 6)   CHECK (confidence BETWEEN 0 AND 1),
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_predictions_application_id ON model_predictions (application_id);
CREATE INDEX IF NOT EXISTS idx_predictions_model_version  ON model_predictions (model_name, model_version);
CREATE INDEX IF NOT EXISTS idx_predictions_predicted_at   ON model_predictions (predicted_at);


-- =============================================================================
-- 4. audit_log
--    Append-only decision audit trail (FCRA / ECOA compliance)
-- =============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    tenant_id               VARCHAR(50)     NOT NULL,
    log_id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id          UUID            NOT NULL REFERENCES loan_applications(application_id) ON DELETE RESTRICT,
    logged_at               TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Snapshotted inputs and versioning
    input_features          JSONB           NOT NULL,
    model_version           VARCHAR(50)     NOT NULL,
    feature_version         VARCHAR(50)     NOT NULL,

    -- Scores
    fraud_score             NUMERIC(8, 6),
    risk_score              NUMERIC(8, 6),

    -- Decision output
    decision_output         VARCHAR(20)     NOT NULL CHECK (decision_output IN ('APPROVE','REJECT','MANUAL_REVIEW')),
    reason_codes            TEXT[],
    decision_latency_ms     INT
);

CREATE INDEX IF NOT EXISTS idx_audit_application_id ON audit_log (application_id);
CREATE INDEX IF NOT EXISTS idx_audit_logged_at      ON audit_log (logged_at);
CREATE INDEX IF NOT EXISTS idx_audit_model_version  ON audit_log (model_version);


-- =============================================================================
-- 5. model_registry
--    Governance / lineage table for all model versions
-- =============================================================================
CREATE TABLE IF NOT EXISTS model_registry (
    tenant_id               VARCHAR(50)     NOT NULL,
    model_id            UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name          VARCHAR(100)    NOT NULL,
    model_version       VARCHAR(50)     NOT NULL,
    status              VARCHAR(20)     NOT NULL DEFAULT 'candidate'
                            CHECK (status IN ('candidate','approved','deprecated')),
    approved_by         VARCHAR(255),
    approved_at         TIMESTAMPTZ,
    performance_metrics JSONB,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    CONSTRAINT uq_model_registry_name_version UNIQUE (model_name, model_version)
);

CREATE INDEX IF NOT EXISTS idx_model_registry_name    ON model_registry (model_name);
CREATE INDEX IF NOT EXISTS idx_model_registry_status  ON model_registry (status);
CREATE INDEX IF NOT EXISTS idx_model_registry_created ON model_registry (created_at);

-- =============================================================================
-- ROW LEVEL SECURITY (RLS) POLICIES
-- =============================================================================


ALTER TABLE loan_applications ENABLE ROW LEVEL SECURITY;

CREATE POLICY loan_applications_isolation_policy ON loan_applications
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY loan_applications_admin_bypass ON loan_applications
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');

ALTER TABLE features ENABLE ROW LEVEL SECURITY;

CREATE POLICY features_isolation_policy ON features
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY features_admin_bypass ON features
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');

ALTER TABLE feature_read_audit ENABLE ROW LEVEL SECURITY;

CREATE POLICY feature_read_audit_isolation_policy ON feature_read_audit
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY feature_read_audit_admin_bypass ON feature_read_audit
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');

ALTER TABLE model_predictions ENABLE ROW LEVEL SECURITY;

CREATE POLICY model_predictions_isolation_policy ON model_predictions
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY model_predictions_admin_bypass ON model_predictions
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

CREATE POLICY audit_log_isolation_policy ON audit_log
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY audit_log_admin_bypass ON audit_log
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');

ALTER TABLE model_registry ENABLE ROW LEVEL SECURITY;

CREATE POLICY model_registry_isolation_policy ON model_registry
    FOR ALL
    USING (tenant_id = current_setting('rls.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('rls.tenant_id', true));

CREATE POLICY model_registry_admin_bypass ON model_registry
    FOR ALL
    USING (current_setting('rls.tenant_id', true) = 'admin_override')
    WITH CHECK (current_setting('rls.tenant_id', true) = 'admin_override');
