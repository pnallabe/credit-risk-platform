-- =============================================================================
-- Migration 003 — Multi-Domain Database Setup
-- Creates the three logical "databases" as separate PostgreSQL schemas
-- within the same instance (or run against separate PG instances in prod)
--
-- Schemas:
--   loans         → all tables from schema_loans.sql
--   transactions  → all tables from schema_transactions.sql
--   credit_cards  → all tables from schema_credit_cards.sql
-- =============================================================================

-- Create schemas (logical namespaces within one PG instance)
CREATE SCHEMA IF NOT EXISTS loans;
CREATE SCHEMA IF NOT EXISTS transactions;
CREATE SCHEMA IF NOT EXISTS credit_cards;

-- Grant to app user (replace credit_user with your actual user)
GRANT ALL ON SCHEMA loans        TO credit_user;
GRANT ALL ON SCHEMA transactions TO credit_user;
GRANT ALL ON SCHEMA credit_cards TO credit_user;

-- Set default search paths for easy cross-schema queries
COMMENT ON SCHEMA loans        IS 'Loans domain: customers, applications, funded loans, payments';
COMMENT ON SCHEMA transactions IS 'Transactions domain: bank accounts, payment transactions, wire, ACH, fraud';
COMMENT ON SCHEMA credit_cards IS 'Credit cards domain: card accounts, transactions, statements, disputes, rewards';

-- Cross-domain view: unified customer 360 (joins across schemas)
-- Run this after all tables are created:
/*
CREATE OR REPLACE VIEW public.customer_360 AS
SELECT
    c.customer_id,
    c.credit_score,
    c.annual_income,
    c.employment_status,
    c.total_existing_debt,
    c.bankruptcy_flag,
    COUNT(DISTINCT la.application_id)              AS loan_application_count,
    COUNT(DISTINCT l.loan_id)                      AS active_loans,
    SUM(l.current_balance)                         AS total_loan_balance,
    COUNT(DISTINCT ba.account_id)                  AS bank_account_count,
    SUM(ba.current_balance)                        AS total_bank_balance,
    COUNT(DISTINCT ca.card_account_id)             AS credit_card_count,
    SUM(ca.current_balance)                        AS total_card_balance,
    SUM(ca.credit_limit)                           AS total_credit_limit,
    ROUND(SUM(ca.current_balance) / NULLIF(SUM(ca.credit_limit),0), 4) AS overall_utilization
FROM loans.customers c
LEFT JOIN loans.loan_applications la USING (customer_id)
LEFT JOIN loans.loans l USING (customer_id)
LEFT JOIN transactions.bank_accounts ba USING (customer_id)
LEFT JOIN credit_cards.card_accounts ca USING (customer_id)
GROUP BY 1, 2, 3, 4, 5, 6;
*/
