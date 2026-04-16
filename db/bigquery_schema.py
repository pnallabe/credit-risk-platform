"""
BigQuery Table Schemas
=======================
Defines the BQ schema for every table used by the credit risk platform.

Dataset: credit_risk_model_dev  (configurable via BQ_DATASET_MODEL_DEV)

Tables
------
  loan_applications     — raw applicant inputs (source of truth for training + scoring)
  feature_vectors       — computed feature engineering output (versioned)
  model_scores          — PD score, fraud flag, pricing (per application)
  credit_decisions      — final approve/reject/review + reason codes (audit trail)
  explanations          — SHAP top factors + adverse action text
  model_registry        — model metadata: version, AUC, KS, training date
  drift_reports         — PSI feature drift snapshots (per monitoring run)
  fair_lending_reports  — DIR / approval parity snapshots
  experiment_results    — champion/challenger experiment outcomes

Partitioning  : DAY on scored_at / decided_at / created_at
Clustering    : application_id, model_version for fast per-application lookups
"""

from __future__ import annotations

try:
    from google.cloud import bigquery
    _BQ = bigquery
    _AVAILABLE = True
except ImportError:
    _BQ = None  # type: ignore[assignment]
    _AVAILABLE = False


def _f(name: str, ftype: str, mode: str = "NULLABLE", desc: str = "") -> Any:
    """Shorthand BigQuery SchemaField factory."""
    if not _AVAILABLE:
        return {"name": name, "type": ftype, "mode": mode, "description": desc}
    return _BQ.SchemaField(name, ftype, mode=mode, description=desc)


from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# loan_applications
# ---------------------------------------------------------------------------

LOAN_APPLICATIONS_SCHEMA: List[Any] = [
    _f("tenant_id",                    "STRING",    "REQUIRED", "Tenant identifier for multi-tenant isolation"),
    _f("application_id",               "STRING",    "REQUIRED", "Unique application UUID"),
    _f("submitted_at",                 "TIMESTAMP", "REQUIRED", "Application submission timestamp"),
    _f("loan_amount",                  "FLOAT64",   "REQUIRED", "Requested loan amount (USD)"),
    _f("loan_purpose",                 "STRING",    "REQUIRED", "Loan purpose category"),
    _f("loan_term_months",             "INT64",     "REQUIRED", "Requested term in months"),
    _f("annual_income",                "FLOAT64",   "REQUIRED", "Self-reported annual income (USD)"),
    _f("employment_status",            "STRING",    "REQUIRED", "Employment status"),
    _f("employer_tenure_months",       "FLOAT64",   "NULLABLE", "Months at current employer"),
    _f("dti",                          "FLOAT64",   "NULLABLE", "Debt-to-income ratio"),
    _f("existing_debt",                "FLOAT64",   "NULLABLE", "Total existing debt (USD)"),
    _f("credit_score",                 "FLOAT64",   "NULLABLE", "Bureau credit score (null = thin file)"),
    _f("num_open_accounts",            "INT64",     "NULLABLE", "Open trade lines"),
    _f("num_derogatory_marks",         "INT64",     "NULLABLE", "Derogatory marks on bureau"),
    _f("months_since_last_delinquency","FLOAT64",   "NULLABLE", "Months since last delinquency"),
    _f("borrower_state",               "STRING",    "NULLABLE", "US state (ISO 3166-2)"),
    _f("channel",                      "STRING",    "NULLABLE", "Origination channel"),
    # Alt-data / thin-file signals
    _f("rent_payment_months",          "INT64",     "NULLABLE", "Months of on-time rent payments"),
    _f("utility_payment_months",       "INT64",     "NULLABLE", "Months of on-time utility payments"),
    _f("mobile_data_score",            "FLOAT64",   "NULLABLE", "Normalised mobile usage score [0,1]"),
    _f("bank_account_age_months",      "INT64",     "NULLABLE", "Bank account age in months"),
    _f("avg_monthly_cash_inflow",      "FLOAT64",   "NULLABLE", "Average monthly cash inflow (USD)"),
    _f("avg_monthly_cash_outflow",     "FLOAT64",   "NULLABLE", "Average monthly cash outflow (USD)"),
    _f("is_thin_file",                 "BOOL",      "NULLABLE", "True if no bureau score available"),
    _f("data_split",                   "STRING",    "NULLABLE", "train / test / validation"),
    _f("schema_version",               "STRING",    "NULLABLE", "Schema version tag"),
    _f("inserted_at",                  "TIMESTAMP", "REQUIRED", "Row insert timestamp"),
]

LOAN_APPLICATIONS_PARTITION = "submitted_at"
LOAN_APPLICATIONS_CLUSTER   = ["tenant_id", "borrower_state", "employment_status"]


# ---------------------------------------------------------------------------
# feature_vectors
# ---------------------------------------------------------------------------

FEATURE_VECTORS_SCHEMA: List[Any] = [
    _f("tenant_id",                "STRING",    "REQUIRED", "Tenant identifier for multi-tenant isolation"),
    _f("application_id",           "STRING",    "REQUIRED", "FK → loan_applications"),
    _f("feature_version",          "STRING",    "REQUIRED", "Feature pipeline version e.g. 1.0.0"),
    _f("credit_utilization",       "FLOAT64",   "NULLABLE", "Existing debt / income capacity"),
    _f("income_stability_score",   "FLOAT64",   "NULLABLE", "Sigmoid of employer tenure"),
    _f("repayment_capacity",       "FLOAT64",   "NULLABLE", "1 − DTI, clipped [0,1]"),
    _f("debt_service_coverage",    "FLOAT64",   "NULLABLE", "Annual income / (existing_debt + 1)"),
    _f("credit_age_score",         "FLOAT64",   "NULLABLE", "num_open_accounts / 10, clipped [0,1]"),
    _f("derogatory_penalty",       "FLOAT64",   "NULLABLE", "num_derogatory_marks × 0.05"),
    _f("months_since_delinquency", "FLOAT64",   "NULLABLE", "Capped at 999"),
    _f("log_loan_amount",          "FLOAT64",   "NULLABLE", "log1p(loan_amount)"),
    _f("log_annual_income",        "FLOAT64",   "NULLABLE", "log1p(annual_income)"),
    _f("dti_x_loan_amount",        "FLOAT64",   "NULLABLE", "DTI × loan_amount interaction"),
    _f("employment_encoded",       "FLOAT64",   "NULLABLE", "Ordinal encoding of employment_status"),
    _f("thin_file_alt_score",      "FLOAT64",   "NULLABLE", "Alt-data composite score [0,1]"),
    _f("thin_file_signals_used",   "BOOL",      "NULLABLE", "True if alt-data boosted score"),
    _f("computed_at",              "TIMESTAMP", "REQUIRED", "Computation timestamp"),
]

FEATURE_VECTORS_PARTITION = "computed_at"
FEATURE_VECTORS_CLUSTER   = ["tenant_id", "feature_version", "application_id"]


# ---------------------------------------------------------------------------
# model_scores
# ---------------------------------------------------------------------------

MODEL_SCORES_SCHEMA: List[Any] = [
    _f("tenant_id",           "STRING",    "REQUIRED", "Tenant identifier for multi-tenant isolation"),
    _f("application_id",      "STRING",    "REQUIRED", "FK → loan_applications"),
    _f("pd_score",            "FLOAT64",   "REQUIRED", "Probability of Default [0,1]"),
    _f("pd_band",             "STRING",    "REQUIRED", "low / medium / high"),
    _f("fraud_probability",   "FLOAT64",   "REQUIRED", "Fraud score [0,1]"),
    _f("fraud_flag",          "STRING",    "REQUIRED", "continue / manual_review / reject"),
    _f("recommended_rate",    "FLOAT64",   "NULLABLE", "Recommended APR (%)"),
    _f("expected_loss",       "FLOAT64",   "NULLABLE", "Expected loss (USD)"),
    _f("expected_profit",     "FLOAT64",   "NULLABLE", "Expected profit (USD)"),
    _f("model_version",       "STRING",    "REQUIRED", "champion / challenger / version tag"),
    _f("feature_version",     "STRING",    "NULLABLE", "Feature pipeline version used"),
    _f("pipeline_run_id",     "STRING",    "NULLABLE", "Parent pipeline run ID"),
    _f("scored_at",           "TIMESTAMP", "REQUIRED", "Scoring timestamp"),
]

MODEL_SCORES_PARTITION = "scored_at"
MODEL_SCORES_CLUSTER   = ["tenant_id", "model_version", "pd_band"]


# ---------------------------------------------------------------------------
# credit_decisions
# ---------------------------------------------------------------------------

CREDIT_DECISIONS_SCHEMA: List[Any] = [
    _f("tenant_id",            "STRING",    "REQUIRED", "Tenant identifier for multi-tenant isolation"),
    _f("application_id",       "STRING",    "REQUIRED", "FK → loan_applications"),
    _f("decision",             "STRING",    "REQUIRED", "APPROVE / REJECT / MANUAL_REVIEW"),
    _f("reason_codes",         "STRING",    "NULLABLE", "Comma-separated FCRA reason codes"),
    _f("approved_amount",      "FLOAT64",   "NULLABLE", "Approved loan amount if APPROVE"),
    _f("approved_rate",        "FLOAT64",   "NULLABLE", "Approved APR (%) if APPROVE"),
    _f("approved_term_months", "INT64",     "NULLABLE", "Approved term if APPROVE"),
    _f("policy_version",       "STRING",    "REQUIRED", "Decision policy version"),
    _f("experiment_id",        "STRING",    "NULLABLE", "A/B experiment ID if applicable"),
    _f("decision_latency_ms",  "FLOAT64",   "NULLABLE", "Engine latency in milliseconds"),
    _f("pipeline_run_id",      "STRING",    "NULLABLE", "Parent pipeline run ID"),
    _f("decided_at",           "TIMESTAMP", "REQUIRED", "Decision timestamp"),
]

CREDIT_DECISIONS_PARTITION  = "decided_at"
CREDIT_DECISIONS_CLUSTER    = ["tenant_id", "decision", "policy_version"]


# ---------------------------------------------------------------------------
# explanations
# ---------------------------------------------------------------------------

EXPLANATIONS_SCHEMA: List[Any] = [
    _f("tenant_id",             "STRING",    "REQUIRED", "Tenant identifier for multi-tenant isolation"),
    _f("application_id",        "STRING",    "REQUIRED", "FK → loan_applications"),
    _f("decision",              "STRING",    "REQUIRED", "Decision label"),
    _f("method",                "STRING",    "REQUIRED", "shap / lime / stub"),
    _f("top_factor_1_name",     "STRING",    "NULLABLE", "Top SHAP factor name"),
    _f("top_factor_1_shap",     "FLOAT64",   "NULLABLE", "Top SHAP value"),
    _f("top_factor_2_name",     "STRING",    "NULLABLE"),
    _f("top_factor_2_shap",     "FLOAT64",   "NULLABLE"),
    _f("top_factor_3_name",     "STRING",    "NULLABLE"),
    _f("top_factor_3_shap",     "FLOAT64",   "NULLABLE"),
    _f("adverse_action_text",   "STRING",    "NULLABLE", "Full FCRA adverse action notice"),
    _f("explainer_version",     "STRING",    "NULLABLE"),
    _f("pipeline_run_id",       "STRING",    "NULLABLE"),
    _f("generated_at",          "TIMESTAMP", "REQUIRED", "Explanation generation timestamp"),
]

EXPLANATIONS_PARTITION = "generated_at"
EXPLANATIONS_CLUSTER   = ["tenant_id", "decision", "method"]


# ---------------------------------------------------------------------------
# model_registry
# ---------------------------------------------------------------------------

MODEL_REGISTRY_SCHEMA: List[Any] = [
    _f("model_id",          "STRING",    "REQUIRED", "Unique model run ID (MLflow run_id)"),
    _f("model_name",        "STRING",    "REQUIRED", "credit_risk / fraud_detection / pricing"),
    _f("model_version",     "STRING",    "REQUIRED", "Version tag e.g. v1, champion, challenger"),
    _f("status",            "STRING",    "REQUIRED", "champion / challenger / retired / candidate"),
    _f("auc_cv",            "FLOAT64",   "NULLABLE", "Cross-validated AUC"),
    _f("ks_stat",           "FLOAT64",   "NULLABLE", "Kolmogorov-Smirnov statistic"),
    _f("gini",              "FLOAT64",   "NULLABLE", "Gini coefficient (2×AUC − 1)"),
    _f("precision",         "FLOAT64",   "NULLABLE", "Precision at operating threshold"),
    _f("recall",            "FLOAT64",   "NULLABLE", "Recall at operating threshold"),
    _f("f1_score",          "FLOAT64",   "NULLABLE", "F1 at operating threshold"),
    _f("training_rows",     "INT64",     "NULLABLE", "Number of training rows"),
    _f("feature_version",   "STRING",    "NULLABLE", "Feature pipeline version used"),
    _f("bq_training_table", "STRING",    "NULLABLE", "BigQuery table used for training data"),
    _f("artifact_path",     "STRING",    "NULLABLE", "GCS / local path to model .pkl"),
    _f("mlflow_run_id",     "STRING",    "NULLABLE", "MLflow run ID for full params/metrics"),
    _f("notes",             "STRING",    "NULLABLE", "Free-text MRM notes"),
    _f("trained_at",        "TIMESTAMP", "REQUIRED", "Training completion timestamp"),
    _f("promoted_at",       "TIMESTAMP", "NULLABLE", "Champion promotion timestamp"),
    _f("retired_at",        "TIMESTAMP", "NULLABLE", "Retirement timestamp"),
]

MODEL_REGISTRY_PARTITION = "trained_at"
MODEL_REGISTRY_CLUSTER   = ["model_name", "status"]


# ---------------------------------------------------------------------------
# drift_reports
# ---------------------------------------------------------------------------

DRIFT_REPORTS_SCHEMA: List[Any] = [
    _f("report_id",                  "STRING",    "REQUIRED", "Unique drift report UUID"),
    _f("pipeline_run_id",            "STRING",    "NULLABLE", "Pipeline run that triggered report"),
    _f("overall_drift_status",       "STRING",    "REQUIRED", "stable / minor / major"),
    _f("features_with_major_drift",  "STRING",    "NULLABLE", "JSON array of feature names"),
    _f("features_with_minor_drift",  "STRING",    "NULLABLE", "JSON array of feature names"),
    _f("n_reference_rows",           "INT64",     "NULLABLE", "Reference window size"),
    _f("n_production_rows",          "INT64",     "NULLABLE", "Production window size"),
    _f("psi_summary_json",           "STRING",    "NULLABLE", "Full PSI values as JSON"),
    _f("alert_triggered",            "BOOL",      "NULLABLE", "True if alert was fired"),
    _f("report_timestamp",           "TIMESTAMP", "REQUIRED", "Report generation timestamp"),
]

DRIFT_REPORTS_PARTITION = "report_timestamp"


# ---------------------------------------------------------------------------
# fair_lending_reports
# ---------------------------------------------------------------------------

FAIR_LENDING_REPORTS_SCHEMA: List[Any] = [
    _f("report_id",                 "STRING",    "REQUIRED", "Unique report UUID"),
    _f("protected_col",             "STRING",    "REQUIRED", "Protected attribute analysed"),
    _f("control_group",             "STRING",    "REQUIRED", "Reference demographic"),
    _f("protected_group",           "STRING",    "NULLABLE", "Protected demographic"),
    _f("dir_score",                 "FLOAT64",   "REQUIRED", "Disparate Impact Ratio"),
    _f("dir_flag",                  "BOOL",      "REQUIRED", "True if DIR < 0.80"),
    _f("protected_approval_rate",   "FLOAT64",   "NULLABLE", "Approval rate for protected group"),
    _f("control_approval_rate",     "FLOAT64",   "NULLABLE", "Approval rate for control group"),
    _f("approval_parity_p_value",   "FLOAT64",   "NULLABLE", "Chi-squared p-value"),
    _f("approval_parity_flag",      "BOOL",      "NULLABLE", "True if p < 0.05"),
    _f("geographic_flags_json",     "STRING",    "NULLABLE", "States with geo bias as JSON"),
    _f("n_total",                   "INT64",     "NULLABLE", "Total decisions analysed"),
    _f("n_approved",                "INT64",     "NULLABLE", "Total approvals"),
    _f("summary_text",              "STRING",    "NULLABLE", "Human-readable summary"),
    _f("report_timestamp",          "TIMESTAMP", "REQUIRED", "Report generation timestamp"),
]

FAIR_LENDING_REPORTS_PARTITION = "report_timestamp"


# ---------------------------------------------------------------------------
# experiment_results
# ---------------------------------------------------------------------------

EXPERIMENT_RESULTS_SCHEMA: List[Any] = [
    _f("experiment_id",              "STRING",    "REQUIRED", "Unique experiment UUID"),
    _f("status",                     "STRING",    "REQUIRED", "active / concluded / insufficient_data"),
    _f("recommendation",             "STRING",    "REQUIRED", "promote / keep / inconclusive"),
    _f("primary_metric",             "STRING",    "REQUIRED", "approval_rate or custom"),
    _f("control_model_version",      "STRING",    "REQUIRED"),
    _f("treatment_model_version",    "STRING",    "REQUIRED"),
    _f("control_n",                  "INT64",     "NULLABLE", "Control arm application count"),
    _f("treatment_n",                "INT64",     "NULLABLE", "Treatment arm application count"),
    _f("control_approval_rate",      "FLOAT64",   "NULLABLE"),
    _f("treatment_approval_rate",    "FLOAT64",   "NULLABLE"),
    _f("approval_rate_lift_pct",     "FLOAT64",   "NULLABLE"),
    _f("profit_lift_pct",            "FLOAT64",   "NULLABLE"),
    _f("chi2_stat",                  "FLOAT64",   "NULLABLE"),
    _f("p_value",                    "FLOAT64",   "NULLABLE"),
    _f("is_significant",             "BOOL",      "NULLABLE"),
    _f("recommendation_rationale",   "STRING",    "NULLABLE"),
    _f("started_at",                 "TIMESTAMP", "NULLABLE"),
    _f("ended_at",                   "TIMESTAMP", "NULLABLE"),
    _f("recorded_at",                "TIMESTAMP", "REQUIRED", "BQ insert timestamp"),
]

EXPERIMENT_RESULTS_PARTITION = "recorded_at"
EXPERIMENT_RESULTS_CLUSTER   = ["recommendation", "status"]


# ---------------------------------------------------------------------------
# Master table catalogue
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# P3-ETL — Bronze rejected side-tables (PROMPT-07)
#
# One "_rejected" schema per bronze fact table.  Same columns as the parent
# table plus ``rejection_reason`` (the silver-layer validation error message).
# Partition / cluster on ``inserted_at`` / ``tenant_id`` for cheap
# time-windowed rejection audits.
# ---------------------------------------------------------------------------

def _add_rejection_reason(schema: List[Any]) -> List[Any]:
    """Return *schema* with an appended ``rejection_reason`` NULLABLE STRING column."""
    return list(schema) + [
        _f("rejection_reason", "STRING", "NULLABLE", "Silver-layer validation rejection reason"),
    ]


LOAN_APPLICATIONS_BRONZE_REJECTED_SCHEMA: List[Any] = _add_rejection_reason(LOAN_APPLICATIONS_SCHEMA)
FEATURE_VECTORS_BRONZE_REJECTED_SCHEMA: List[Any]    = _add_rejection_reason(FEATURE_VECTORS_SCHEMA)
MODEL_SCORES_BRONZE_REJECTED_SCHEMA: List[Any]        = _add_rejection_reason(MODEL_SCORES_SCHEMA)
CREDIT_DECISIONS_BRONZE_REJECTED_SCHEMA: List[Any]    = _add_rejection_reason(CREDIT_DECISIONS_SCHEMA)
EXPLANATIONS_BRONZE_REJECTED_SCHEMA: List[Any]        = _add_rejection_reason(EXPLANATIONS_SCHEMA)


TABLE_CATALOGUE: Dict[str, Dict] = {
    "loan_applications": {
        "schema": LOAN_APPLICATIONS_SCHEMA,
        "partition_field": LOAN_APPLICATIONS_PARTITION,
        "clustering_fields": LOAN_APPLICATIONS_CLUSTER,
        "description": "Raw loan application inputs — source of truth for model training and batch scoring",
    },
    "feature_vectors": {
        "schema": FEATURE_VECTORS_SCHEMA,
        "partition_field": FEATURE_VECTORS_PARTITION,
        "clustering_fields": FEATURE_VECTORS_CLUSTER,
        "description": "Versioned feature engineering outputs",
    },
    "model_scores": {
        "schema": MODEL_SCORES_SCHEMA,
        "partition_field": MODEL_SCORES_PARTITION,
        "clustering_fields": MODEL_SCORES_CLUSTER,
        "description": "PD / fraud / pricing model outputs per application",
    },
    "credit_decisions": {
        "schema": CREDIT_DECISIONS_SCHEMA,
        "partition_field": CREDIT_DECISIONS_PARTITION,
        "clustering_fields": CREDIT_DECISIONS_CLUSTER,
        "description": "Final credit decisions with FCRA reason codes — full audit trail",
    },
    "explanations": {
        "schema": EXPLANATIONS_SCHEMA,
        "partition_field": EXPLANATIONS_PARTITION,
        "clustering_fields": EXPLANATIONS_CLUSTER,
        "description": "SHAP-based explanations and adverse action notices",
    },
    "model_registry": {
        "schema": MODEL_REGISTRY_SCHEMA,
        "partition_field": MODEL_REGISTRY_PARTITION,
        "clustering_fields": MODEL_REGISTRY_CLUSTER,
        "description": "Model metadata, performance metrics, and promotion history",
    },
    "drift_reports": {
        "schema": DRIFT_REPORTS_SCHEMA,
        "partition_field": DRIFT_REPORTS_PARTITION,
        "clustering_fields": None,
        "description": "PSI feature drift monitoring snapshots",
    },
    "fair_lending_reports": {
        "schema": FAIR_LENDING_REPORTS_SCHEMA,
        "partition_field": FAIR_LENDING_REPORTS_PARTITION,
        "clustering_fields": None,
        "description": "Fair lending (DIR / approval parity) compliance snapshots",
    },
    "experiment_results": {
        "schema": EXPERIMENT_RESULTS_SCHEMA,
        "partition_field": EXPERIMENT_RESULTS_PARTITION,
        "clustering_fields": EXPERIMENT_RESULTS_CLUSTER,
        "description": "Champion/challenger A/B experiment outcomes",
    },
    # -----------------------------------------------------------------------
    # P3-ETL rejected side-tables (PROMPT-07)
    # -----------------------------------------------------------------------
    "loan_applications_bronze_rejected": {
        "schema": LOAN_APPLICATIONS_BRONZE_REJECTED_SCHEMA,
        "partition_field": "inserted_at",
        "clustering_fields": ["tenant_id"],
        "description": "Bronze rows that failed silver-layer validation",
    },
    "feature_vectors_bronze_rejected": {
        "schema": FEATURE_VECTORS_BRONZE_REJECTED_SCHEMA,
        "partition_field": "computed_at",
        "clustering_fields": ["tenant_id"],
        "description": "Feature vector rows that failed silver-layer validation",
    },
    "model_scores_bronze_rejected": {
        "schema": MODEL_SCORES_BRONZE_REJECTED_SCHEMA,
        "partition_field": "scored_at",
        "clustering_fields": ["tenant_id"],
        "description": "Model score rows that failed silver-layer validation",
    },
    "credit_decisions_bronze_rejected": {
        "schema": CREDIT_DECISIONS_BRONZE_REJECTED_SCHEMA,
        "partition_field": "decided_at",
        "clustering_fields": ["tenant_id"],
        "description": "Credit decision rows that failed silver-layer validation",
    },
    "explanations_bronze_rejected": {
        "schema": EXPLANATIONS_BRONZE_REJECTED_SCHEMA,
        "partition_field": "generated_at",
        "clustering_fields": ["tenant_id"],
        "description": "Explanation rows that failed silver-layer validation",
    },
}
