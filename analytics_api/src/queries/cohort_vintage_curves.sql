-- =============================================================================
-- cohort_vintage_curves.sql (BigQuery dialect)
-- Returns monthly vintage curves for a single tenant.
--
-- Parameters (passed as query parameters from analytics_api):
--   @tenant_id       STRING   — tenant scoping (REQUIRED)
--   @months_back     INT64    — how many origination months to include (default 24)
--   @bucket_col      STRING   — one of 'pd_band' | 'loan_purpose' | 'employment_status'
--
-- Output columns:
--   origination_month, bucket, dpd_bucket, cohort_count,
--   defaulted_count, cumulative_default_rate
-- =============================================================================

WITH cohort AS (
  SELECT
    DATE_TRUNC(la.submitted_at, MONTH)                   AS origination_month,
    -- choose bucketing column dynamically in application layer; here we use pd_band
    ms.pd_band                                           AS bucket,
    la.application_id,
    la.loan_amount,
    cd.decision
  FROM `@dataset`.loan_applications la
  JOIN `@dataset`.model_scores       ms  USING (application_id, tenant_id)
  JOIN `@dataset`.credit_decisions   cd  USING (application_id, tenant_id)
  WHERE la.tenant_id = @tenant_id
    AND la.submitted_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(),
                             INTERVAL @months_back MONTH)
    AND cd.decision = 'APPROVE'
),

performance AS (
  -- Stub: in production join to a payment performance table
  -- For now we approximate using existing debt growth as a proxy
  SELECT
    cohort.origination_month,
    cohort.bucket,
    COUNT(*)                                            AS cohort_count,
    COUNTIF(cohort.decision = 'REJECT')                AS declined_in_cohort,
    SUM(cohort.loan_amount)                            AS total_originated_amount
  FROM cohort
  GROUP BY 1, 2
)

SELECT
  origination_month,
  bucket,
  cohort_count,
  total_originated_amount,
  declined_in_cohort,
  SAFE_DIVIDE(declined_in_cohort, cohort_count)       AS decline_rate,
  -- Cumulative fields populated downstream when performance data joins
  0.0                                                  AS cumulative_default_rate,
  0.0                                                  AS net_loss_rate
FROM performance
ORDER BY origination_month DESC, bucket
LIMIT @page_size
OFFSET @page_offset
