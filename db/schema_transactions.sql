-- =============================================================================
-- Credit Risk Platform — TRANSACTIONS Database Schema  (PostgreSQL)
-- Database: credit_risk_transactions
-- Covers: bank accounts, payment transactions, ACH/wire transfers, fraud signals
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- 1. bank_accounts
--    Customer bank account registry
-- =============================================================================
CREATE TABLE IF NOT EXISTS bank_accounts (
    account_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID            NOT NULL,  -- FK -> loans_db.customers
    account_number_hash     VARCHAR(64)     NOT NULL,  -- SHA-256 of actual acct#
    account_number_last4    CHAR(4)         NOT NULL,
    routing_number          CHAR(9)         NOT NULL,
    account_type            VARCHAR(20)     NOT NULL CHECK (account_type IN
                                ('checking','savings','money_market','cd','brokerage')),
    account_status          VARCHAR(20)     NOT NULL DEFAULT 'active'
                                CHECK (account_status IN ('active','dormant','closed','frozen','restricted')),
    bank_name               VARCHAR(100),
    bank_code               VARCHAR(20),
    currency_code           CHAR(3)         DEFAULT 'USD',

    -- Balances
    current_balance         NUMERIC(16, 2)  DEFAULT 0,
    available_balance       NUMERIC(16, 2)  DEFAULT 0,
    pending_balance         NUMERIC(16, 2)  DEFAULT 0,
    average_daily_balance   NUMERIC(16, 2),
    overdraft_limit         NUMERIC(14, 2)  DEFAULT 0,
    overdraft_protection    BOOLEAN         DEFAULT FALSE,

    -- Account dates
    opened_date             DATE            NOT NULL,
    closed_date             DATE,
    last_activity_date      DATE,

    -- Risk signals
    overdraft_count_30d     SMALLINT        DEFAULT 0,
    nsf_count_90d           SMALLINT        DEFAULT 0,
    suspicious_activity_flag BOOLEAN        DEFAULT FALSE,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bank_accts_customer_id    ON bank_accounts (customer_id);
CREATE INDEX IF NOT EXISTS idx_bank_accts_status         ON bank_accounts (account_status);
CREATE INDEX IF NOT EXISTS idx_bank_accts_type           ON bank_accounts (account_type);
CREATE INDEX IF NOT EXISTS idx_bank_accts_balance        ON bank_accounts (current_balance);


-- =============================================================================
-- 2. transactions
--    Core ledger of all financial transactions (high-volume, time-series)
-- =============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id          UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id              UUID            NOT NULL REFERENCES bank_accounts(account_id),
    customer_id             UUID            NOT NULL,

    -- Transaction classification
    transaction_type        VARCHAR(30)     NOT NULL CHECK (transaction_type IN
                                ('debit','credit','transfer_in','transfer_out',
                                 'ach_debit','ach_credit','wire_in','wire_out',
                                 'check_deposit','check_payment','atm_withdrawal',
                                 'atm_deposit','fee','interest','refund','reversal')),
    transaction_category    VARCHAR(50)     CHECK (transaction_category IN
                                ('groceries','restaurants','gas','utilities','rent_mortgage',
                                 'insurance','healthcare','entertainment','shopping_retail',
                                 'travel','transportation','education','subscriptions',
                                 'investments','loan_payment','tax','payroll','government',
                                 'charity','cash','other')),
    channel                 VARCHAR(20)     CHECK (channel IN ('online','mobile','branch','atm','pos','phone','api')),

    -- Amounts
    amount                  NUMERIC(14, 2)  NOT NULL CHECK (amount > 0),
    currency_code           CHAR(3)         DEFAULT 'USD',
    fx_rate                 NUMERIC(10, 6)  DEFAULT 1.0,
    amount_usd              NUMERIC(14, 2),
    running_balance         NUMERIC(16, 2),

    -- Counterparty
    counterparty_name       VARCHAR(255),
    counterparty_account    VARCHAR(100),
    counterparty_routing    CHAR(9),
    description             VARCHAR(500),
    merchant_name           VARCHAR(255),
    merchant_category_code  CHAR(4),
    merchant_city           VARCHAR(100),
    merchant_state          CHAR(2),
    merchant_country        CHAR(2)         DEFAULT 'US',

    -- Status and timing
    transaction_status      VARCHAR(20)     NOT NULL DEFAULT 'posted'
                                CHECK (transaction_status IN ('pending','posted','failed','reversed','disputed')),
    initiated_at            TIMESTAMPTZ     NOT NULL,
    posted_at               TIMESTAMPTZ,
    value_date              DATE,
    settlement_date         DATE,

    -- Fraud / risk signals
    fraud_score             NUMERIC(5, 4),
    fraud_flag              BOOLEAN         DEFAULT FALSE,
    fraud_reason            VARCHAR(100),
    is_unusual_amount       BOOLEAN         DEFAULT FALSE,
    is_unusual_location     BOOLEAN         DEFAULT FALSE,
    ip_address              INET,
    device_fingerprint      VARCHAR(128),
    geolocation             POINT,

    -- References
    reference_number        VARCHAR(100),
    check_number            VARCHAR(20),
    trace_number            VARCHAR(50),
    parent_transaction_id   UUID            REFERENCES transactions(transaction_id),
    linked_loan_id          UUID,
    linked_card_id          UUID,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
) PARTITION BY RANGE (initiated_at);

-- Monthly partitions for high-volume time-series performance
CREATE TABLE IF NOT EXISTS transactions_2023_01 PARTITION OF transactions
    FOR VALUES FROM ('2023-01-01') TO ('2023-02-01');
CREATE TABLE IF NOT EXISTS transactions_2023_q2 PARTITION OF transactions
    FOR VALUES FROM ('2023-04-01') TO ('2023-07-01');
CREATE TABLE IF NOT EXISTS transactions_2023_q3 PARTITION OF transactions
    FOR VALUES FROM ('2023-07-01') TO ('2023-10-01');
CREATE TABLE IF NOT EXISTS transactions_2023_q4 PARTITION OF transactions
    FOR VALUES FROM ('2023-10-01') TO ('2024-01-01');
CREATE TABLE IF NOT EXISTS transactions_2024_q1 PARTITION OF transactions
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');
CREATE TABLE IF NOT EXISTS transactions_2024_q2 PARTITION OF transactions
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');
CREATE TABLE IF NOT EXISTS transactions_2024_q3 PARTITION OF transactions
    FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');
CREATE TABLE IF NOT EXISTS transactions_2024_q4 PARTITION OF transactions
    FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS transactions_2025_q1 PARTITION OF transactions
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE IF NOT EXISTS transactions_2025_q2 PARTITION OF transactions
    FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
CREATE TABLE IF NOT EXISTS transactions_2025_q3 PARTITION OF transactions
    FOR VALUES FROM ('2025-07-01') TO ('2025-10-01');
CREATE TABLE IF NOT EXISTS transactions_2025_q4 PARTITION OF transactions
    FOR VALUES FROM ('2025-10-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS transactions_2026_q1 PARTITION OF transactions
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS transactions_default PARTITION OF transactions DEFAULT;

CREATE INDEX IF NOT EXISTS idx_txn_account_id     ON transactions (account_id, initiated_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_customer_id    ON transactions (customer_id, initiated_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_type           ON transactions (transaction_type);
CREATE INDEX IF NOT EXISTS idx_txn_category       ON transactions (transaction_category);
CREATE INDEX IF NOT EXISTS idx_txn_fraud_flag     ON transactions (fraud_flag) WHERE fraud_flag = TRUE;
CREATE INDEX IF NOT EXISTS idx_txn_amount         ON transactions (amount);
CREATE INDEX IF NOT EXISTS idx_txn_posted_at      ON transactions (posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_txn_merchant       ON transactions (merchant_name);


-- =============================================================================
-- 3. ach_transfers
--    ACH batch origination and return tracking
-- =============================================================================
CREATE TABLE IF NOT EXISTS ach_transfers (
    ach_id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id          UUID            REFERENCES transactions(transaction_id),
    account_id              UUID            NOT NULL REFERENCES bank_accounts(account_id),
    customer_id             UUID            NOT NULL,

    -- ACH details
    ach_type                VARCHAR(10)     NOT NULL CHECK (ach_type IN ('PPD','CCD','WEB','TEL','CTX','IAT')),
    direction               VARCHAR(10)     NOT NULL CHECK (direction IN ('debit','credit')),
    amount                  NUMERIC(14, 2)  NOT NULL,
    effective_date          DATE            NOT NULL,
    company_name            VARCHAR(100),
    company_id              VARCHAR(20),
    individual_name         VARCHAR(100),

    -- Status
    ach_status              VARCHAR(20)     NOT NULL DEFAULT 'initiated'
                                CHECK (ach_status IN ('initiated','pending','settled','returned','reversed')),
    return_code             CHAR(3),        -- R01, R02, etc.
    return_reason           VARCHAR(100),
    return_date             DATE,
    trace_number            VARCHAR(15),
    batch_number            VARCHAR(10),

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ach_account_id  ON ach_transfers (account_id);
CREATE INDEX IF NOT EXISTS idx_ach_status      ON ach_transfers (ach_status);
CREATE INDEX IF NOT EXISTS idx_ach_date        ON ach_transfers (effective_date);


-- =============================================================================
-- 4. wire_transfers
--    Domestic and international wire transfers
-- =============================================================================
CREATE TABLE IF NOT EXISTS wire_transfers (
    wire_id                 UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id          UUID            REFERENCES transactions(transaction_id),
    account_id              UUID            NOT NULL REFERENCES bank_accounts(account_id),
    customer_id             UUID            NOT NULL,

    direction               VARCHAR(10)     NOT NULL CHECK (direction IN ('outgoing','incoming')),
    amount                  NUMERIC(14, 2)  NOT NULL,
    currency_code           CHAR(3)         DEFAULT 'USD',
    amount_usd              NUMERIC(14, 2),
    fx_rate                 NUMERIC(10, 6)  DEFAULT 1.0,

    -- Beneficiary
    beneficiary_name        VARCHAR(255),
    beneficiary_account     VARCHAR(100),
    beneficiary_bank_name   VARCHAR(255),
    beneficiary_bank_swift  VARCHAR(11),
    beneficiary_routing     CHAR(9),
    beneficiary_country     CHAR(2)         DEFAULT 'US',
    beneficiary_city        VARCHAR(100),

    -- Status
    wire_status             VARCHAR(20)     NOT NULL DEFAULT 'initiated'
                                CHECK (wire_status IN ('initiated','pending','confirmed','settled','returned','failed')),
    imad                    VARCHAR(50),    -- Input Message Accountability Data
    omad                    VARCHAR(50),    -- Output Message Accountability Data
    initiated_at            TIMESTAMPTZ     NOT NULL DEFAULT now(),
    settled_at              TIMESTAMPTZ,
    failure_reason          VARCHAR(255),

    -- Compliance
    kyc_verified            BOOLEAN         DEFAULT FALSE,
    ofac_screened           BOOLEAN         DEFAULT FALSE,
    ofac_match              BOOLEAN         DEFAULT FALSE,
    purpose_code            VARCHAR(30),

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wire_account_id ON wire_transfers (account_id);
CREATE INDEX IF NOT EXISTS idx_wire_status     ON wire_transfers (wire_status);
CREATE INDEX IF NOT EXISTS idx_wire_initiated  ON wire_transfers (initiated_at);
CREATE INDEX IF NOT EXISTS idx_wire_ofac       ON wire_transfers (ofac_match) WHERE ofac_match = TRUE;


-- =============================================================================
-- 5. fraud_alerts
--    Real-time fraud detection signals and case management
-- =============================================================================
CREATE TABLE IF NOT EXISTS fraud_alerts (
    alert_id                UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    transaction_id          UUID            REFERENCES transactions(transaction_id),
    account_id              UUID            NOT NULL REFERENCES bank_accounts(account_id),
    customer_id             UUID            NOT NULL,

    alert_type              VARCHAR(50)     NOT NULL CHECK (alert_type IN
                                ('velocity_breach','unusual_amount','geo_anomaly',
                                 'device_anomaly','time_anomaly','pattern_match',
                                 'mule_account','synthetic_identity','account_takeover',
                                 'card_not_present','merchant_fraud','money_laundering')),
    severity                VARCHAR(10)     NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    fraud_score             NUMERIC(5, 4)   CHECK (fraud_score BETWEEN 0 AND 1),
    model_version           VARCHAR(50),

    -- Investigation
    alert_status            VARCHAR(20)     NOT NULL DEFAULT 'open'
                                CHECK (alert_status IN ('open','under_review','confirmed_fraud',
                                                        'false_positive','closed')),
    investigator_id         UUID,
    investigation_notes     TEXT,
    resolved_at             TIMESTAMPTZ,

    -- Risk signals JSON (flexible)
    risk_signals            JSONB,
    triggered_rules         TEXT[],

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_fraud_alerts_account_id  ON fraud_alerts (account_id);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_status      ON fraud_alerts (alert_status);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_severity    ON fraud_alerts (severity);
CREATE INDEX IF NOT EXISTS idx_fraud_alerts_created     ON fraud_alerts (created_at DESC);


-- =============================================================================
-- 6. daily_balance_snapshots
--    End-of-day balance history for trend analysis
-- =============================================================================
CREATE TABLE IF NOT EXISTS daily_balance_snapshots (
    snapshot_id             BIGSERIAL       PRIMARY KEY,
    account_id              UUID            NOT NULL REFERENCES bank_accounts(account_id),
    customer_id             UUID            NOT NULL,
    snapshot_date           DATE            NOT NULL,
    opening_balance         NUMERIC(16, 2),
    closing_balance         NUMERIC(16, 2),
    daily_credits           NUMERIC(14, 2)  DEFAULT 0,
    daily_debits            NUMERIC(14, 2)  DEFAULT 0,
    transaction_count       INT             DEFAULT 0,
    min_balance             NUMERIC(16, 2),
    max_balance             NUMERIC(16, 2),

    CONSTRAINT uq_daily_snapshot UNIQUE (account_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_snap_account   ON daily_balance_snapshots (account_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_snap_date      ON daily_balance_snapshots (snapshot_date);
