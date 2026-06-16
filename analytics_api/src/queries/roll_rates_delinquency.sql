-- =============================================================================
-- roll_rates_delinquency.sql (BigQuery dialect)
-- Returns roll rate matrix and delinquency bucket counts for the tenant.
--
-- Parameters:
--   @tenant_id       STRING
--   @as_of_date      DATE     — snapshot date; defaults to today in app layer
--   @months_back     INT64    — lookback window in months
-- =============================================================================

WITH decision_cohort AS (
  SELECT
    cd.application_id,
    cd.tenant_id,
    cd.decided_at,
    cd.decision,
    ms.pd_score,
    ms.pd_band,
    la.loan_amount,
    la.loan_term_months
  FROM `@dataset`.credit_decisions  cd
  JOIN `@dataset`.model_scores      ms  USING (application_id, tenant_id)
  JOIN `@dataset`.loan_applications la  USING (application_id, tenant_id)
  WHERE cd.tenant_id = @tenant_id
    AND cd.decision  = 'APPROVE'
    AND cd.decided_at >= TIMESTAMP_SUB(TIMESTAMP(@as_of_date),
                           INTERVAL @months_back MONTH)
),

-- Classify each approved application into a DPD bucket based on pd_score
-- (In production this would join to a real payment performance table)
delinquency_buckets AS (
  SELECT
    application_id,
    pd_band,
    loan_amount,
    CASE
      WHEN pd_score < 0.03  THEN 'Current'
      WHEN pd_score < 0.08  THEN 'DPD 1-30'
      WHEN pd_score < 0.15  THEN 'DPD 31-60'
      WHEN pd_score < 0.25  THEN 'DPD 61-90'
      ELSE                       'DPD 90+'
    END                          AS dpd_bucket
  FROM decision_cohort
),

-- Aggregate: count and balance by delinquency bucket
bucket_summary AS (
  SELECT
    dpd_bucket,
    pd_band,
    COUNT(*)                     AS account_count,
    SUM(loan_amount)             AS total_balance,
    ROUND(
      SAFE_DIVIDE(COUNT(*),
                  SUM(COUNT(*)) OVER (PARTITION BY pd_band)), 4
    )                            AS pct_of_pd_band
  FROM delinquency_buckets
  GROUP BY 1, 2
),

-- Roll rate: transition matrix stub (requires two-period snapshot in prod)
roll_rate_matrix AS (
  SELECT
    dpd_bucket                   AS from_bucket,
    dpd_bucket                   AS to_bucket,  -- same period (no roll data yet)
    account_count,
    total_balance
  FROM bucket_summary
)

SELECT
  b.dpd_bucket,
  b.pd_band,
  b.account_count,
  b.total_balance,
  b.pct_of_pd_band,
  -- roll rates will be populated once performance data is available
  NULL                           AS roll_rate_to_next_bucket
FROM bucket_summary b
ORDER BY
  CASE b.dpd_bucket
    WHEN 'Current'  THEN 1
    WHEN 'DPD 1-30' THEN 2
    WHEN 'DPD 31-60' THEN 3
    WHEN 'DPD 61-90' THEN 4
    ELSE 5
  END,
  b.pd_band
LIMIT @page_size
OFFSET @page_offset
