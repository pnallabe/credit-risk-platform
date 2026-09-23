-- Migration 007: Add portfolio fields to decision_audit_log (audit_log in SQLite)
-- This migration allows real data to flow into the portfolio concentration and dashboard endpoints.

ALTER TABLE audit_log ADD COLUMN naics_2d TEXT;
ALTER TABLE audit_log ADD COLUMN borrower_state TEXT;
ALTER TABLE audit_log ADD COLUMN loan_amount REAL;
