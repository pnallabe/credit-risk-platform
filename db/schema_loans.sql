-- =============================================================================
-- Credit Risk Platform — LOANS Database Schema  (PostgreSQL)
-- Database: credit_risk_loans
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- 1. customers
--    Central customer master for the loans domain
-- =============================================================================
CREATE TABLE IF NOT EXISTS customers (
    customer_id             UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    first_name              VARCHAR(100)    NOT NULL,
    last_name               VARCHAR(100)    NOT NULL,
    date_of_birth           DATE            NOT NULL,
    ssn_last4               CHAR(4),
    email                   VARCHAR(255)    UNIQUE,
    phone                   VARCHAR(20),
    address_line1           VARCHAR(255),
    address_line2           VARCHAR(100),
    city                    VARCHAR(100),
    state                   CHAR(2),
    zip_code                VARCHAR(10),
    annual_income           NUMERIC(14, 2)  CHECK (annual_income >= 0),
    employment_status       VARCHAR(20)     CHECK (employment_status IN ('employed','self-employed','unemployed','retired','student')),
    employer_name           VARCHAR(255),
    employer_tenure_months  INT             CHECK (employer_tenure_months >= 0),
    credit_score            SMALLINT        CHECK (credit_score BETWEEN 300 AND 850),
    credit_score_model      VARCHAR(50)     DEFAULT 'FICO8',
    credit_score_date       DATE,
    num_open_accounts       SMALLINT        DEFAULT 0,
    num_derogatory_marks    SMALLINT        DEFAULT 0,
    total_existing_debt     NUMERIC(14, 2)  DEFAULT 0,
    bankruptcy_flag         BOOLEAN         DEFAULT FALSE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_customers_email    ON customers (email);
CREATE INDEX IF NOT EXISTS idx_customers_state    ON customers (state);
CREATE INDEX IF NOT EXISTS idx_customers_score    ON customers (credit_score);
CREATE INDEX IF NOT EXISTS idx_customers_income   ON customers (annual_income);


-- =============================================================================
-- 2. loan_products
--    Product catalog for loan types offered
-- =============================================================================
CREATE TABLE IF NOT EXISTS loan_products (
    product_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code            VARCHAR(20)     UNIQUE NOT NULL,
    product_name            VARCHAR(100)    NOT NULL,
    loan_type               VARCHAR(30)     NOT NULL CHECK (loan_type IN
                                ('personal','auto','mortgage','student','small_business',
                                 'home_equity','medical','green_energy','debt_consolidation')),
    min_amount              NUMERIC(14, 2)  NOT NULL,
    max_amount              NUMERIC(14, 2)  NOT NULL,
    min_term_months         SMALLINT        NOT NULL,
    max_term_months         SMALLINT        NOT NULL,
    base_interest_rate      NUMERIC(6, 4)   NOT NULL,
    origination_fee_pct     NUMERIC(5, 4)   DEFAULT 0.0,
    prepayment_penalty      BOOLEAN         DEFAULT FALSE,
    min_credit_score        SMALLINT        DEFAULT 580,
    max_dti_ratio           NUMERIC(5, 4)   DEFAULT 0.50,
    is_active               BOOLEAN         DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);


-- =============================================================================
-- 3. loan_applications
--    All loan application submissions (extended from original schema)
-- =============================================================================
CREATE TABLE IF NOT EXISTS loan_applications (
    application_id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID            NOT NULL REFERENCES customers(customer_id),
    product_id              UUID            REFERENCES loan_products(product_id),

    -- Loan details
    loan_amount             NUMERIC(14, 2)  NOT NULL CHECK (loan_amount > 0),
    loan_purpose            VARCHAR(80)     NOT NULL,
    loan_type               VARCHAR(30)     NOT NULL,
    loan_term_months        SMALLINT        NOT NULL,
    requested_interest_rate NUMERIC(6, 4),
    collateral_type         VARCHAR(50),
    collateral_value        NUMERIC(14, 2),

    -- Snapshot of credit at time of application
    credit_score_at_app     SMALLINT        CHECK (credit_score_at_app BETWEEN 300 AND 850),
    dti_at_app              NUMERIC(5, 4)   CHECK (dti_at_app BETWEEN 0 AND 1),
    annual_income_at_app    NUMERIC(14, 2),
    existing_debt_at_app    NUMERIC(14, 2),

    -- Application status
    status                  VARCHAR(30)     NOT NULL DEFAULT 'submitted'
                                CHECK (status IN ('submitted','under_review','approved',
                                                  'conditionally_approved','rejected',
                                                  'withdrawn','funded','closed')),
    underwriter_id          UUID,
    review_notes            TEXT,

    -- Decisioning
    approved_amount         NUMERIC(14, 2),
    approved_rate           NUMERIC(6, 4),
    approved_term_months    SMALLINT,
    decision_at             TIMESTAMPTZ,
    decision_reason_codes   TEXT[],

    -- Metadata
    channel                 VARCHAR(30)     CHECK (channel IN ('online','branch','mobile','partner','phone')),
    referral_source         VARCHAR(100),
    ip_address              INET,
    applied_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loan_apps_customer_id  ON loan_applications (customer_id);
CREATE INDEX IF NOT EXISTS idx_loan_apps_status       ON loan_applications (status);
CREATE INDEX IF NOT EXISTS idx_loan_apps_applied_at   ON loan_applications (applied_at);
CREATE INDEX IF NOT EXISTS idx_loan_apps_loan_type    ON loan_applications (loan_type);
CREATE INDEX IF NOT EXISTS idx_loan_apps_amount       ON loan_applications (loan_amount);


-- =============================================================================
-- 4. loans
--    Funded, active, and closed loans (origination records)
-- =============================================================================
CREATE TABLE IF NOT EXISTS loans (
    loan_id                 UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id          UUID            UNIQUE REFERENCES loan_applications(application_id),
    customer_id             UUID            NOT NULL REFERENCES customers(customer_id),
    product_id              UUID            REFERENCES loan_products(product_id),

    -- Loan terms
    principal_amount        NUMERIC(14, 2)  NOT NULL CHECK (principal_amount > 0),
    interest_rate           NUMERIC(6, 4)   NOT NULL CHECK (interest_rate > 0),
    annual_percentage_rate  NUMERIC(6, 4),
    loan_term_months        SMALLINT        NOT NULL,
    monthly_payment         NUMERIC(12, 2)  NOT NULL,
    origination_fee         NUMERIC(10, 2)  DEFAULT 0,

    -- Dates
    origination_date        DATE            NOT NULL,
    first_payment_date      DATE            NOT NULL,
    maturity_date           DATE            NOT NULL,
    paid_off_date           DATE,

    -- Balance tracking
    current_balance         NUMERIC(14, 2)  NOT NULL,
    principal_paid          NUMERIC(14, 2)  DEFAULT 0,
    interest_paid           NUMERIC(14, 2)  DEFAULT 0,
    fees_paid               NUMERIC(10, 2)  DEFAULT 0,
    total_paid              NUMERIC(14, 2)  DEFAULT 0,

    -- Performance
    loan_status             VARCHAR(30)     NOT NULL DEFAULT 'current'
                                CHECK (loan_status IN ('current','delinquent_30','delinquent_60',
                                                       'delinquent_90','default','charged_off',
                                                       'paid_off','in_forbearance','modified')),
    days_past_due           SMALLINT        DEFAULT 0 CHECK (days_past_due >= 0),
    times_30dpd             SMALLINT        DEFAULT 0,
    times_60dpd             SMALLINT        DEFAULT 0,
    times_90dpd             SMALLINT        DEFAULT 0,
    last_payment_date       DATE,
    last_payment_amount     NUMERIC(12, 2),
    next_payment_date       DATE,

    -- Servicer info
    servicer_id             UUID,
    servicing_transferred   BOOLEAN         DEFAULT FALSE,
    loan_pool_id            VARCHAR(50),

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loans_customer_id      ON loans (customer_id);
CREATE INDEX IF NOT EXISTS idx_loans_status           ON loans (loan_status);
CREATE INDEX IF NOT EXISTS idx_loans_origination_date ON loans (origination_date);
CREATE INDEX IF NOT EXISTS idx_loans_dpd              ON loans (days_past_due);
CREATE INDEX IF NOT EXISTS idx_loans_balance          ON loans (current_balance);


-- =============================================================================
-- 5. loan_payments
--    Payment history — every payment event against a loan
-- =============================================================================
CREATE TABLE IF NOT EXISTS loan_payments (
    payment_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id                 UUID            NOT NULL REFERENCES loans(loan_id) ON DELETE CASCADE,
    customer_id             UUID            NOT NULL REFERENCES customers(customer_id),

    -- Payment details
    payment_date            DATE            NOT NULL,
    due_date                DATE            NOT NULL,
    payment_amount          NUMERIC(12, 2)  NOT NULL CHECK (payment_amount > 0),
    principal_portion       NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    interest_portion        NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    fees_portion            NUMERIC(10, 2)  DEFAULT 0,
    escrow_portion          NUMERIC(10, 2)  DEFAULT 0,

    -- Status
    payment_status          VARCHAR(20)     NOT NULL
                                CHECK (payment_status IN ('scheduled','posted','returned','reversed','partial')),
    payment_method          VARCHAR(20)     CHECK (payment_method IN ('ach','wire','check','card','cash','auto_pay')),
    days_late               SMALLINT        DEFAULT 0,
    is_prepayment           BOOLEAN         DEFAULT FALSE,
    remaining_balance       NUMERIC(14, 2),

    -- Transaction reference
    transaction_reference   VARCHAR(100),
    bank_account_last4      CHAR(4),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loan_pmts_loan_id      ON loan_payments (loan_id);
CREATE INDEX IF NOT EXISTS idx_loan_pmts_customer_id  ON loan_payments (customer_id);
CREATE INDEX IF NOT EXISTS idx_loan_pmts_date         ON loan_payments (payment_date);
CREATE INDEX IF NOT EXISTS idx_loan_pmts_status       ON loan_payments (payment_status);


-- =============================================================================
-- 6. loan_modifications
--    Forbearance, deferral, and restructuring events
-- =============================================================================
CREATE TABLE IF NOT EXISTS loan_modifications (
    modification_id         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    loan_id                 UUID            NOT NULL REFERENCES loans(loan_id),
    modification_type       VARCHAR(30)     NOT NULL
                                CHECK (modification_type IN ('forbearance','deferral',
                                                             'rate_reduction','term_extension',
                                                             'principal_reduction','covid_relief')),
    effective_date          DATE            NOT NULL,
    end_date                DATE,
    original_rate           NUMERIC(6, 4),
    modified_rate           NUMERIC(6, 4),
    original_payment        NUMERIC(12, 2),
    modified_payment        NUMERIC(12, 2),
    months_deferred         SMALLINT        DEFAULT 0,
    reason                  TEXT,
    approved_by             UUID,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_loan_mods_loan_id ON loan_modifications (loan_id);


-- =============================================================================
-- 7. credit_bureau_pulls
--    Hard and soft inquiry log
-- =============================================================================
CREATE TABLE IF NOT EXISTS credit_bureau_pulls (
    pull_id                 UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID            NOT NULL REFERENCES customers(customer_id),
    application_id          UUID            REFERENCES loan_applications(application_id),
    bureau                  VARCHAR(20)     NOT NULL CHECK (bureau IN ('Equifax','Experian','TransUnion')),
    pull_type               VARCHAR(10)     NOT NULL CHECK (pull_type IN ('hard','soft')),
    pull_date               DATE            NOT NULL,
    score_returned          SMALLINT        CHECK (score_returned BETWEEN 300 AND 850),
    report_reference        VARCHAR(100),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bureau_pulls_customer    ON credit_bureau_pulls (customer_id);
CREATE INDEX IF NOT EXISTS idx_bureau_pulls_date        ON credit_bureau_pulls (pull_date);
