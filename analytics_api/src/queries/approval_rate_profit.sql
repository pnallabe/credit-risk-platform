-- =============================================================================
-- approval_rate_profit.sql (BigQuery dialect)
-- Returns approval rate and expected profit by segment for the tenant.
--
-- Parameters:
--   @tenant_id       STRING
--   @segment_col     STRING   — 'pd_band' | 'loan_purpose' | 'employment_status'
--                               (selected in application layer; query uses pd_band)
--   @months_back     INT64    — lookback window in months (default 12)
--   @min_applications INT64   — minimum cohort size to show segment (default 10)
-- =============================================================================

WITH decisions AS (
  SELECT
    cd.application_id,
    cd.tenant_id,
    cd.decision,
    cd.decided_at,
    ms.pd_score,
    ms.pd_band,
    la.loan_amount,
    la.loan_purpose,
    la.employment_status,
    la.annual_income,
    la.loan_term_months
  FROM `@dataset`.credit_decisions  cd
  JOIN `@dataset`.model_scores      ms  USING (application_id, tenant_id)
  JOIN `@dataset`.loan_applications la  USING (application_id, tenant_id)
  WHERE cd.tenant_id = @tenant_id
    AND cd.decided_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(),
                           INTERVAL @months_back MONTH)
),

segment_stats AS (
  SELECT
    pd_band                                             AS segment,
    'pd_band'                                          AS segment_type,
    COUNT(*)                                           AS total_applications,
    COUNTIF(decision = 'APPROVE')                      AS approved_count,
    COUNTIF(decision = 'REJECT')                       AS rejected_count,
    COUNTIF(decision = 'MANUAL_REVIEW')                AS manual_review_count,
    ROUND(SAFE_DIVIDE(
      COUNTIF(decision = 'APPROVE'), COUNT(*)), 4)     AS approval_rate,
    ROUND(AVG(CASE WHEN decision = 'APPROVE'
              THEN loan_amount END), 2)                AS avg_approved_amount,
    ROUND(SUM(CASE WHEN decision = 'APPROVE'
              THEN loan_amount END), 2)                AS total_approved_amount,
    ROUND(AVG(CASE WHEN decision = 'APPROVE'
              THEN pd_score END), 6)                   AS avg_pd_score_approved,

    -- Expected Profit = loan_amount × (1 - pd_score) × assumed_margin - loan_amount × pd_score × LGD
    -- Simplified: assumed_margin=0.05, LGD=0.60
    ROUND(SUM(
      CASE WHEN decision = 'APPROVE' THEN
        (loan_amount * (1 - pd_score) * 0.05)
        - (loan_amount * pd_score * 0.60)
      END
    ), 2)                                              AS expected_profit_usd

  FROM decisions
  GROUP BY 1, 2
  HAVING COUNT(*) >= @min_applications
)

SELECT
  segment,
  segment_type,
  total_applications,
  approved_count,
  rejected_count,
  manual_review_count,
  approval_rate,
  avg_approved_amount,
  total_approved_amount,
  avg_pd_score_approved,
  expected_profit_usd,
  SAFE_DIVIDE(expected_profit_usd, NULLIF(total_approved_amount, 0)) AS expected_return_rate
FROM segment_stats
ORDER BY total_approved_amount DESC
LIMIT @page_size
OFFSET @page_offset
