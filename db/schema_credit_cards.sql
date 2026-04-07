-- =============================================================================
-- Credit Risk Platform — CREDIT CARDS Database Schema  (PostgreSQL)
-- Database: credit_risk_cards
-- Covers: card accounts, card transactions, statements, rewards, disputes
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================================
-- 1. card_products
--    Credit card product catalog
-- =============================================================================
CREATE TABLE IF NOT EXISTS card_products (
    product_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    product_code            VARCHAR(20)     UNIQUE NOT NULL,
    product_name            VARCHAR(100)    NOT NULL,
    card_network            VARCHAR(20)     NOT NULL CHECK (card_network IN ('Visa','Mastercard','Amex','Discover')),
    card_tier               VARCHAR(20)     CHECK (card_tier IN ('basic','standard','premium','ultra_premium','secured','student','business')),

    -- APR structure
    purchase_apr            NUMERIC(6, 4)   NOT NULL,
    cash_advance_apr        NUMERIC(6, 4),
    balance_transfer_apr    NUMERIC(6, 4),
    penalty_apr             NUMERIC(6, 4),
    intro_apr               NUMERIC(6, 4)   DEFAULT 0.0,
    intro_apr_months        SMALLINT        DEFAULT 0,

    -- Fees
    annual_fee              NUMERIC(8, 2)   DEFAULT 0,
    late_fee                NUMERIC(8, 2)   DEFAULT 29,
    returned_payment_fee    NUMERIC(8, 2)   DEFAULT 29,
    foreign_transaction_fee_pct NUMERIC(4,3) DEFAULT 0.03,
    cash_advance_fee_pct    NUMERIC(4, 3)   DEFAULT 0.05,
    balance_transfer_fee_pct NUMERIC(4, 3)  DEFAULT 0.03,

    -- Credit limits
    min_credit_limit        NUMERIC(10, 2)  DEFAULT 300,
    max_credit_limit        NUMERIC(10, 2)  DEFAULT 100000,
    min_credit_score        SMALLINT        DEFAULT 580,

    -- Rewards
    rewards_type            VARCHAR(30)     CHECK (rewards_type IN ('cashback','points','miles','none')),
    base_rewards_rate       NUMERIC(5, 3)   DEFAULT 0.01,
    sign_up_bonus_amount    NUMERIC(10, 2)  DEFAULT 0,
    sign_up_spend_requirement NUMERIC(10, 2) DEFAULT 0,
    sign_up_months          SMALLINT        DEFAULT 3,

    is_active               BOOLEAN         DEFAULT TRUE,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);


-- =============================================================================
-- 2. card_accounts
--    Individual credit card account for each customer
-- =============================================================================
CREATE TABLE IF NOT EXISTS card_accounts (
    card_account_id         UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id             UUID            NOT NULL,   -- FK -> loans_db.customers
    product_id              UUID            NOT NULL REFERENCES card_products(product_id),

    -- Card identifiers
    card_number_hash        VARCHAR(64)     NOT NULL,   -- SHA-256
    card_number_last4       CHAR(4)         NOT NULL,
    card_number_bin         VARCHAR(8)      NOT NULL,   -- Bank Identification Number
    card_network            VARCHAR(20)     NOT NULL,
    card_type               VARCHAR(10)     NOT NULL CHECK (card_type IN ('physical','virtual','both')),

    -- Account status
    account_status          VARCHAR(20)     NOT NULL DEFAULT 'active'
                                CHECK (account_status IN ('pending_activation','active','suspended',
                                                          'closed','charged_off','fraud_hold',
                                                          'credit_hold','deceased')),
    account_open_date       DATE            NOT NULL,
    account_close_date      DATE,
    card_expiry_date        DATE            NOT NULL,
    card_activation_date    DATE,

    -- Credit and utilization
    credit_limit            NUMERIC(10, 2)  NOT NULL CHECK (credit_limit >= 0),
    temporary_limit_increase NUMERIC(10, 2) DEFAULT 0,
    cash_advance_limit      NUMERIC(10, 2),
    current_balance         NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    available_credit        NUMERIC(12, 2)  GENERATED ALWAYS AS
                                (credit_limit + COALESCE(temporary_limit_increase,0) - current_balance) STORED,
    cash_advance_balance    NUMERIC(12, 2)  DEFAULT 0,
    pending_balance         NUMERIC(12, 2)  DEFAULT 0,
    statement_balance       NUMERIC(12, 2)  DEFAULT 0,
    minimum_payment_due     NUMERIC(10, 2)  DEFAULT 0,
    credit_utilization      NUMERIC(5, 4)   GENERATED ALWAYS AS
                                (CASE WHEN credit_limit > 0 THEN current_balance / credit_limit ELSE 0 END) STORED,

    -- Payment and cycle
    payment_due_date        DATE,
    last_payment_date       DATE,
    last_payment_amount     NUMERIC(12, 2),
    closing_date_day        SMALLINT        CHECK (closing_date_day BETWEEN 1 AND 31),
    autopay_enrolled        BOOLEAN         DEFAULT FALSE,
    autopay_type            VARCHAR(20)     CHECK (autopay_type IN ('minimum','statement_balance','fixed_amount','full_balance')),

    -- Performance / risk
    months_on_book          SMALLINT        DEFAULT 0,
    times_30dpd             SMALLINT        DEFAULT 0,
    times_60dpd             SMALLINT        DEFAULT 0,
    times_90dpd             SMALLINT        DEFAULT 0,
    current_delinquency_days SMALLINT       DEFAULT 0,
    overlimit_count         SMALLINT        DEFAULT 0,
    returned_payments       SMALLINT        DEFAULT 0,

    -- Rewards
    rewards_balance_points  INT             DEFAULT 0,
    rewards_balance_dollars NUMERIC(10, 2)  DEFAULT 0,
    lifetime_rewards_earned NUMERIC(12, 2)  DEFAULT 0,

    -- Authorization controls
    domestic_transactions   BOOLEAN         DEFAULT TRUE,
    international_transactions BOOLEAN      DEFAULT FALSE,
    online_transactions     BOOLEAN         DEFAULT TRUE,
    contactless_enabled     BOOLEAN         DEFAULT TRUE,
    daily_spend_limit       NUMERIC(10, 2),

    interest_rate_apr       NUMERIC(6, 4),
    promotional_rate        NUMERIC(6, 4),
    promotional_end_date    DATE,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_card_accts_customer_id  ON card_accounts (customer_id);
CREATE INDEX IF NOT EXISTS idx_card_accts_status       ON card_accounts (account_status);
CREATE INDEX IF NOT EXISTS idx_card_accts_balance      ON card_accounts (current_balance);
CREATE INDEX IF NOT EXISTS idx_card_accts_utilization  ON card_accounts (credit_utilization);
CREATE INDEX IF NOT EXISTS idx_card_accts_dpd          ON card_accounts (current_delinquency_days);
CREATE INDEX IF NOT EXISTS idx_card_accts_open_date    ON card_accounts (account_open_date);


-- =============================================================================
-- 3. card_transactions
--    All card purchase, cash advance, fee, and adjustment transactions
--    Partitioned by month for performance
-- =============================================================================
CREATE TABLE IF NOT EXISTS card_transactions (
    card_txn_id             UUID            NOT NULL,
    card_account_id         UUID            NOT NULL REFERENCES card_accounts(card_account_id),
    customer_id             UUID            NOT NULL,

    -- Classification
    txn_type                VARCHAR(30)     NOT NULL CHECK (txn_type IN
                                ('purchase','cash_advance','balance_transfer','payment',
                                 'refund','fee','interest_charge','adjustment','dispute_credit',
                                 'reward_redemption','foreign_transaction')),
    txn_category            VARCHAR(50)     CHECK (txn_category IN
                                ('groceries','restaurants','gas','utilities','rent_mortgage',
                                 'insurance','healthcare','entertainment','shopping_retail',
                                 'travel_airlines','travel_hotels','travel_other','transportation',
                                 'education','subscriptions','electronics','home_garden',
                                 'beauty_personal_care','sports_outdoors','government','other')),

    -- Amount
    amount                  NUMERIC(12, 2)  NOT NULL CHECK (amount > 0),
    currency_code           CHAR(3)         DEFAULT 'USD',
    billing_amount          NUMERIC(12, 2)  NOT NULL,
    fx_rate                 NUMERIC(10, 6)  DEFAULT 1.0,
    running_balance         NUMERIC(12, 2),

    -- Merchant
    merchant_name           VARCHAR(255),
    merchant_dba            VARCHAR(255),
    merchant_category_code  CHAR(4),
    merchant_id             VARCHAR(50),
    merchant_city           VARCHAR(100),
    merchant_state          CHAR(2),
    merchant_country        CHAR(2)         DEFAULT 'US',
    merchant_zip            VARCHAR(10),
    merchant_latitude       NUMERIC(9, 6),
    merchant_longitude      NUMERIC(9, 6),

    -- Authorization
    authorization_code      VARCHAR(10),
    authorization_at        TIMESTAMPTZ     NOT NULL,
    posted_at               TIMESTAMPTZ,
    settlement_date         DATE,
    is_pending              BOOLEAN         DEFAULT FALSE,

    -- Status
    txn_status              VARCHAR(20)     NOT NULL DEFAULT 'posted'
                                CHECK (txn_status IN ('authorized','posted','settled','declined',
                                                      'reversed','disputed','fraud')),
    decline_reason          VARCHAR(100),

    -- Card presentation
    card_present            BOOLEAN         DEFAULT TRUE,
    entry_mode              VARCHAR(20)     CHECK (entry_mode IN ('chip','swipe','contactless',
                                                                   'manual','online','token')),
    is_international        BOOLEAN         DEFAULT FALSE,
    is_recurring            BOOLEAN         DEFAULT FALSE,

    -- Fraud / risk
    fraud_score             NUMERIC(5, 4),
    fraud_flag              BOOLEAN         DEFAULT FALSE,
    fraud_type              VARCHAR(50),
    dispute_flag            BOOLEAN         DEFAULT FALSE,
    dispute_id              UUID,

    -- Rewards
    rewards_multiplier      NUMERIC(5, 3)   DEFAULT 1.0,
    rewards_points_earned   INT             DEFAULT 0,
    rewards_dollars_earned  NUMERIC(8, 4)   DEFAULT 0,

    -- Device / channel
    channel                 VARCHAR(20)     CHECK (channel IN ('in_store','online','mobile_app',
                                                                'phone','atm','contactless')),
    ip_address              INET,
    device_type             VARCHAR(30),

    PRIMARY KEY (card_txn_id, authorization_at),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
) PARTITION BY RANGE (authorization_at);

-- Quarterly partitions
CREATE TABLE IF NOT EXISTS card_txns_2023_q1 PARTITION OF card_transactions
    FOR VALUES FROM ('2023-01-01') TO ('2023-04-01');
CREATE TABLE IF NOT EXISTS card_txns_2023_q2 PARTITION OF card_transactions
    FOR VALUES FROM ('2023-04-01') TO ('2023-07-01');
CREATE TABLE IF NOT EXISTS card_txns_2023_q3 PARTITION OF card_transactions
    FOR VALUES FROM ('2023-07-01') TO ('2023-10-01');
CREATE TABLE IF NOT EXISTS card_txns_2023_q4 PARTITION OF card_transactions
    FOR VALUES FROM ('2023-10-01') TO ('2024-01-01');
CREATE TABLE IF NOT EXISTS card_txns_2024_q1 PARTITION OF card_transactions
    FOR VALUES FROM ('2024-01-01') TO ('2024-04-01');
CREATE TABLE IF NOT EXISTS card_txns_2024_q2 PARTITION OF card_transactions
    FOR VALUES FROM ('2024-04-01') TO ('2024-07-01');
CREATE TABLE IF NOT EXISTS card_txns_2024_q3 PARTITION OF card_transactions
    FOR VALUES FROM ('2024-07-01') TO ('2024-10-01');
CREATE TABLE IF NOT EXISTS card_txns_2024_q4 PARTITION OF card_transactions
    FOR VALUES FROM ('2024-10-01') TO ('2025-01-01');
CREATE TABLE IF NOT EXISTS card_txns_2025_q1 PARTITION OF card_transactions
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
CREATE TABLE IF NOT EXISTS card_txns_2025_q2 PARTITION OF card_transactions
    FOR VALUES FROM ('2025-04-01') TO ('2025-07-01');
CREATE TABLE IF NOT EXISTS card_txns_2025_q3 PARTITION OF card_transactions
    FOR VALUES FROM ('2025-07-01') TO ('2025-10-01');
CREATE TABLE IF NOT EXISTS card_txns_2025_q4 PARTITION OF card_transactions
    FOR VALUES FROM ('2025-10-01') TO ('2026-01-01');
CREATE TABLE IF NOT EXISTS card_txns_2026_q1 PARTITION OF card_transactions
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE IF NOT EXISTS card_txns_default PARTITION OF card_transactions DEFAULT;

CREATE INDEX IF NOT EXISTS idx_card_txn_account_id  ON card_transactions (card_account_id, authorization_at DESC);
CREATE INDEX IF NOT EXISTS idx_card_txn_customer_id ON card_transactions (customer_id, authorization_at DESC);
CREATE INDEX IF NOT EXISTS idx_card_txn_type        ON card_transactions (txn_type);
CREATE INDEX IF NOT EXISTS idx_card_txn_category    ON card_transactions (txn_category);
CREATE INDEX IF NOT EXISTS idx_card_txn_fraud       ON card_transactions (fraud_flag) WHERE fraud_flag = TRUE;
CREATE INDEX IF NOT EXISTS idx_card_txn_merchant    ON card_transactions (merchant_name);
CREATE INDEX IF NOT EXISTS idx_card_txn_amount      ON card_transactions (amount);
CREATE INDEX IF NOT EXISTS idx_card_txn_posted      ON card_transactions (posted_at DESC);


-- =============================================================================
-- 4. card_statements
--    Monthly billing statement records
-- =============================================================================
CREATE TABLE IF NOT EXISTS card_statements (
    statement_id            UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    card_account_id         UUID            NOT NULL REFERENCES card_accounts(card_account_id),
    customer_id             UUID            NOT NULL,

    -- Cycle dates
    statement_date          DATE            NOT NULL,
    payment_due_date        DATE            NOT NULL,
    cycle_start_date        DATE            NOT NULL,
    cycle_end_date          DATE            NOT NULL,

    -- Balances
    opening_balance         NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    closing_balance         NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    statement_balance       NUMERIC(12, 2)  NOT NULL DEFAULT 0,
    minimum_payment_due     NUMERIC(10, 2)  NOT NULL DEFAULT 0,

    -- Activity
    total_purchases         NUMERIC(12, 2)  DEFAULT 0,
    total_cash_advances     NUMERIC(12, 2)  DEFAULT 0,
    total_balance_transfers NUMERIC(12, 2)  DEFAULT 0,
    total_payments          NUMERIC(12, 2)  DEFAULT 0,
    total_credits           NUMERIC(12, 2)  DEFAULT 0,
    total_fees              NUMERIC(10, 2)  DEFAULT 0,
    total_interest          NUMERIC(12, 2)  DEFAULT 0,
    purchase_count          SMALLINT        DEFAULT 0,
    payment_count           SMALLINT        DEFAULT 0,

    -- Rate information
    purchase_apr            NUMERIC(6, 4),
    cash_advance_apr        NUMERIC(6, 4),
    balance_transfer_apr    NUMERIC(6, 4),
    days_in_cycle           SMALLINT,

    -- Payment outcome
    payment_received_date   DATE,
    payment_received_amount NUMERIC(12, 2),
    paid_in_full            BOOLEAN         DEFAULT FALSE,
    was_delinquent          BOOLEAN         DEFAULT FALSE,
    late_fee_charged        NUMERIC(8, 2)   DEFAULT 0,

    -- Rewards earned this period
    rewards_points_earned   INT             DEFAULT 0,
    rewards_dollars_earned  NUMERIC(8, 4)   DEFAULT 0,

    credit_limit_at_close   NUMERIC(10, 2),
    utilization_at_close    NUMERIC(5, 4),

    CONSTRAINT uq_card_stmt UNIQUE (card_account_id, statement_date)
);

CREATE INDEX IF NOT EXISTS idx_stmt_account_id   ON card_statements (card_account_id, statement_date DESC);
CREATE INDEX IF NOT EXISTS idx_stmt_due_date     ON card_statements (payment_due_date);
CREATE INDEX IF NOT EXISTS idx_stmt_delinquent   ON card_statements (was_delinquent) WHERE was_delinquent = TRUE;


-- =============================================================================
-- 5. card_disputes
--    Dispute / chargeback case management
-- =============================================================================
CREATE TABLE IF NOT EXISTS card_disputes (
    dispute_id              UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    card_account_id         UUID            NOT NULL REFERENCES card_accounts(card_account_id),
    card_txn_id             UUID            NOT NULL,
    customer_id             UUID            NOT NULL,

    dispute_reason          VARCHAR(50)     NOT NULL CHECK (dispute_reason IN
                                ('not_authorized','item_not_received','item_not_as_described',
                                 'duplicate_charge','incorrect_amount','credit_not_processed',
                                 'subscription_cancelled','fraud','atm_dispute','other')),
    dispute_amount          NUMERIC(12, 2)  NOT NULL,
    dispute_status          VARCHAR(20)     NOT NULL DEFAULT 'filed'
                                CHECK (dispute_status IN ('filed','under_review','provisional_credit',
                                                          'resolved_cardholder','resolved_merchant',
                                                          'withdrawn','escalated')),

    filed_date              DATE            NOT NULL,
    resolution_date         DATE,
    provisional_credit_date DATE,
    provisional_credit_amount NUMERIC(12, 2),
    final_outcome           VARCHAR(30),
    merchant_response       TEXT,
    case_notes              TEXT,

    chargeback_cycle        SMALLINT        DEFAULT 1,
    arbitration_flag        BOOLEAN         DEFAULT FALSE,

    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_disputes_account ON card_disputes (card_account_id);
CREATE INDEX IF NOT EXISTS idx_disputes_status  ON card_disputes (dispute_status);
CREATE INDEX IF NOT EXISTS idx_disputes_filed   ON card_disputes (filed_date);


-- =============================================================================
-- 6. rewards_redemptions
--    Rewards points / cashback redemption events
-- =============================================================================
CREATE TABLE IF NOT EXISTS rewards_redemptions (
    redemption_id           UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    card_account_id         UUID            NOT NULL REFERENCES card_accounts(card_account_id),
    customer_id             UUID            NOT NULL,

    redemption_type         VARCHAR(30)     NOT NULL CHECK (redemption_type IN
                                ('statement_credit','gift_card','travel','merchandise',
                                 'cashback_check','charity','transfer_to_partner')),
    points_redeemed         INT             DEFAULT 0,
    dollars_redeemed        NUMERIC(10, 2)  DEFAULT 0,
    redemption_value        NUMERIC(10, 2)  NOT NULL,
    redemption_status       VARCHAR(20)     DEFAULT 'completed'
                                CHECK (redemption_status IN ('pending','completed','reversed','expired')),
    partner_name            VARCHAR(100),
    redeemed_at             TIMESTAMPTZ     NOT NULL DEFAULT now(),
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rewards_account  ON rewards_redemptions (card_account_id);
CREATE INDEX IF NOT EXISTS idx_rewards_redeemed ON rewards_redemptions (redeemed_at);


-- =============================================================================
-- 7. credit_limit_changes
--    History of credit limit increases and decreases
-- =============================================================================
CREATE TABLE IF NOT EXISTS credit_limit_changes (
    change_id               UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    card_account_id         UUID            NOT NULL REFERENCES card_accounts(card_account_id),
    customer_id             UUID            NOT NULL,

    change_type             VARCHAR(20)     NOT NULL CHECK (change_type IN
                                ('increase_customer_request','increase_auto','decrease_risk',
                                 'decrease_regulatory','line_suspension','line_reinstatement')),
    previous_limit          NUMERIC(10, 2)  NOT NULL,
    new_limit               NUMERIC(10, 2)  NOT NULL,
    change_reason           TEXT,
    credit_score_at_change  SMALLINT,
    effective_date          DATE            NOT NULL,
    approved_by             VARCHAR(50)     DEFAULT 'system',
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_limit_changes_account ON credit_limit_changes (card_account_id, effective_date DESC);
