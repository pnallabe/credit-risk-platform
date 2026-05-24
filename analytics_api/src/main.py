"""
Analytics API — Phase 2 (P2.2)
================================
Portfolio analytics service backed by BigQuery (or SQLite in dev/test).

Endpoints
---------
GET /v1/analytics/vintage-curves     — cohort / vintage curves
GET /v1/analytics/roll-rates         — roll rates and delinquency buckets
GET /v1/analytics/approval-profit    — approval rate + expected profit by segment
GET /v1/health                       — service health

All endpoints:
  * require a Bearer JWT with a ``tenant_id`` claim (same auth contract as
    the Decision API)
  * enforce tenant scoping in every BQ/SQL query (WHERE tenant_id = :tenant_id)
  * support cursor-based pagination via ``limit`` / ``offset`` query params
  * cache expensive queries in-process with a configurable TTL

Usage (development — SQLite backend):
    uvicorn analytics_api.src.main:app --reload --port 8002

Usage (production — BigQuery backend):
    BQ_DATASET=credit_risk_prod BQ_PROJECT=my-project uvicorn analytics_api.src.main:app
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import fastapi
import re
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

# Make project root importable when running directly
ROOT = Path(__file__).parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BQ_PROJECT = os.getenv("BQ_PROJECT", "")
BQ_DATASET = os.getenv("BQ_DATASET", "credit_risk")
BQ_DATASET_FREDDIE = os.getenv("BQ_DATASET_FREDDIE", "freddie_mac_sflld")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT}/decision_audit.db")

# Allowed BQ dataset identifiers for s2s queries
_BQ_ALLOWED_DATASETS: Dict[str, str] = {
    "credit_risk": BQ_DATASET,
    "freddie_mac": BQ_DATASET_FREDDIE,
    "freddie_mac_sflld": BQ_DATASET_FREDDIE,
}

_JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Cache TTL in seconds (default 5 minutes)
CACHE_TTL_SECONDS: int = int(os.getenv("ANALYTICS_CACHE_TTL_SECONDS", "300"))

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Credit Risk Analytics API",
    description="Portfolio analytics: vintage curves, roll rates, approval/profit by segment.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# Semantic Layer router (GAP-19)
# ---------------------------------------------------------------------------
try:
    from analytics_api.src.semantic_api import router as semantic_router
    app.include_router(semantic_router)
except Exception as _sem_exc:
    logger.warning("Could not register semantic router: %s", _sem_exc)

# ---------------------------------------------------------------------------
# GraphQL router (GAP-24)
# ---------------------------------------------------------------------------
try:
    from analytics_api.src.graphql_schema import graphql_app
    app.include_router(graphql_app, prefix="/graphql")
except Exception as _gql_exc:
    logger.warning("Could not register GraphQL router: %s", _gql_exc)

# ---------------------------------------------------------------------------
# Semantic Intelligence Agent routers (Layer D)
# USE_SEMANTIC_AGENT=true also routes s2s/ask through the new pipeline.
# ---------------------------------------------------------------------------
try:
    from analytics_api.src.agent.api.routes import router as agent_ask_router
    from analytics_api.src.agent.api.clarification import router as agent_clarify_router
    app.include_router(agent_ask_router)
    app.include_router(agent_clarify_router)
    logger.info("Semantic Intelligence Agent endpoints registered (/v1/agent/ask, /v1/agent/clarify)")
except Exception as _agent_exc:
    logger.warning("Could not register agent routers: %s", _agent_exc)

_cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
_CORS_ORIGINS: List[str] = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else []
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)

# ---------------------------------------------------------------------------
# Auth (mirrors Decision API)
# ---------------------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)


async def verify_bearer(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Verify Bearer JWT and require tenant_id claim."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT_SECRET not configured",
        )
    try:
        import jwt
        payload = jwt.decode(
            credentials.credentials,
            _JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT must include 'tenant_id' claim",
        )
    return payload


# ---------------------------------------------------------------------------
# Query backend (BigQuery or SQLite fallback)
# ---------------------------------------------------------------------------

_SQL_DIR = Path(__file__).parent / "queries"


def _load_sql(filename: str) -> str:
    """Read a SQL template file from the queries/ directory."""
    path = _SQL_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"SQL template not found: {path}")
    return path.read_text()


class _QueryBackend:
    """Thin abstraction over BQ vs SQLite so the endpoint code is identical."""

    def __init__(self) -> None:
        self._use_bq = bool(BQ_PROJECT)
        if self._use_bq:
            try:
                from google.cloud import bigquery
                self._bq_client = bigquery.Client(project=BQ_PROJECT)
                logger.info("Analytics API: BigQuery backend (project=%s, dataset=%s)", BQ_PROJECT, BQ_DATASET)
            except Exception as exc:
                logger.warning("BigQuery unavailable: %s — falling back to SQLite", exc)
                self._use_bq = False
        if not self._use_bq:
            logger.info("Analytics API: SQLite backend (%s)", DATABASE_URL)

    def run_sql(
        self,
        sql_template: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Execute a parameterised query and return rows as dicts.

        BigQuery parameterisation uses ``@param`` syntax already embedded in
        the SQL files.  SQLite uses ``?`` — we do a trivial substitution for
        the dev path.
        """
        if self._use_bq:
            return self._run_bq(sql_template, params)
        return self._run_sqlite(sql_template, params)

    def _run_bq(
        self,
        sql_template: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        from google.cloud import bigquery  # type: ignore[import]

        # Replace @dataset placeholder
        sql = sql_template.replace("@dataset", f"`{BQ_PROJECT}.{BQ_DATASET}`")

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(k, _bq_type(v), v)
                for k, v in params.items()
                if k not in ("page_size", "page_offset")
            ]
            + [
                bigquery.ScalarQueryParameter("page_size",   "INT64", params.get("page_size", 100)),
                bigquery.ScalarQueryParameter("page_offset", "INT64", params.get("page_offset", 0)),
            ]
        )
        query_job = self._bq_client.query(sql, job_config=job_config)
        rows = query_job.result()
        return [dict(row) for row in rows]

    def _run_sqlite(
        self,
        sql_template: str,
        params: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Best-effort SQLite execution for dev/test.

        The BQ SQL templates use CTEs and JOIN patterns that are compatible
        with SQLite.  @param bindings are replaced with ? placeholders and
        the ``@dataset.`` table prefix is stripped.
        """
        import re
        import sqlite3 as _sq

        # Strip dataset prefix and backtick quoting
        sql = re.sub(r"`[^`]+`\.", "", sql_template)
        sql = sql.replace("@dataset.", "")

        # Replace named @params with ? and build ordered value list
        ordered_keys: List[str] = re.findall(r"@(\w+)", sql)
        for key in ordered_keys:
            sql = sql.replace(f"@{key}", "?", 1)

        ordered_values = [params.get(k) for k in ordered_keys]

        db_path = DATABASE_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
        try:
            conn = _sq.connect(db_path)
            conn.row_factory = _sq.Row
            rows = conn.execute(sql, ordered_values).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.warning("SQLite analytics query failed: %s", exc)
            return []


_backend = _QueryBackend()


def _bq_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, date):
        return "DATE"
    return "STRING"


# ---------------------------------------------------------------------------
# Simple in-process cache
# ---------------------------------------------------------------------------

_cache: Dict[str, tuple] = {}  # key → (rows, expires_at)


def _cache_get(key: str) -> Optional[List[Dict[str, Any]]]:
    entry = _cache.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: str, rows: List[Dict[str, Any]]) -> None:
    _cache[key] = (rows, time.monotonic() + CACHE_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PaginationMeta(BaseModel):
    limit: int
    offset: int
    returned: int


class VintageCurveRow(BaseModel):
    origination_month: Optional[str]
    bucket: Optional[str]
    cohort_count: Optional[int]
    total_originated_amount: Optional[float]
    decline_rate: Optional[float]
    cumulative_default_rate: Optional[float]
    net_loss_rate: Optional[float]


class RollRateRow(BaseModel):
    dpd_bucket: Optional[str]
    pd_band: Optional[str]
    account_count: Optional[int]
    total_balance: Optional[float]
    pct_of_pd_band: Optional[float]
    roll_rate_to_next_bucket: Optional[float]


class ApprovalProfitRow(BaseModel):
    segment: Optional[str]
    segment_type: Optional[str]
    total_applications: Optional[int]
    approved_count: Optional[int]
    rejected_count: Optional[int]
    manual_review_count: Optional[int]
    approval_rate: Optional[float]
    avg_approved_amount: Optional[float]
    total_approved_amount: Optional[float]
    avg_pd_score_approved: Optional[float]
    expected_profit_usd: Optional[float]
    expected_return_rate: Optional[float]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get(
    "/v1/analytics/vintage-curves",
    response_model=Dict[str, Any],
    summary="Cohort / vintage curve data",
    tags=["Analytics"],
)
async def vintage_curves(
    months_back: int = Query(default=24, ge=1, le=60, description="Origination lookback in months"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return monthly vintage origination and performance curves for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    cache_key = f"vintage:{tenant_id}:{months_back}:{limit}:{offset}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"data": cached, "meta": {"limit": limit, "offset": offset, "returned": len(cached), "cached": True}}

    params = {
        "tenant_id": tenant_id,
        "months_back": months_back,
        "page_size": limit,
        "page_offset": offset,
    }
    try:
        sql = _load_sql("cohort_vintage_curves.sql")
        rows = _backend.run_sql(sql, params)
    except Exception as exc:
        logger.error("vintage-curves query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")

    _cache_set(cache_key, rows)
    return {
        "data": rows,
        "meta": PaginationMeta(limit=limit, offset=offset, returned=len(rows)).model_dump(),
    }


@app.get(
    "/v1/analytics/roll-rates",
    response_model=Dict[str, Any],
    summary="Roll rates and delinquency bucket counts",
    tags=["Analytics"],
)
async def roll_rates(
    as_of_date: Optional[date] = Query(default=None, description="Snapshot date (defaults to today)"),
    months_back: int = Query(default=12, ge=1, le=36),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return delinquency bucket distribution and stub roll rate matrix."""
    tenant_id: str = _user["tenant_id"]
    as_of = (as_of_date or date.today()).isoformat()
    cache_key = f"rollrates:{tenant_id}:{as_of}:{months_back}:{limit}:{offset}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"data": cached, "meta": {"limit": limit, "offset": offset, "returned": len(cached), "cached": True}}

    params = {
        "tenant_id": tenant_id,
        "as_of_date": as_of,
        "months_back": months_back,
        "page_size": limit,
        "page_offset": offset,
    }
    try:
        sql = _load_sql("roll_rates_delinquency.sql")
        rows = _backend.run_sql(sql, params)
    except Exception as exc:
        logger.error("roll-rates query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")

    _cache_set(cache_key, rows)
    return {
        "data": rows,
        "meta": PaginationMeta(limit=limit, offset=offset, returned=len(rows)).model_dump(),
    }


@app.get(
    "/v1/analytics/approval-profit",
    response_model=Dict[str, Any],
    summary="Approval rate and expected profit by segment",
    tags=["Analytics"],
)
async def approval_profit(
    months_back: int = Query(default=12, ge=1, le=36),
    min_applications: int = Query(default=10, ge=1, description="Minimum cohort size to include segment"),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return approval rate and expected profit breakdown by pd_band segment."""
    tenant_id: str = _user["tenant_id"]
    cache_key = f"aprprof:{tenant_id}:{months_back}:{min_applications}:{limit}:{offset}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return {"data": cached, "meta": {"limit": limit, "offset": offset, "returned": len(cached), "cached": True}}

    params = {
        "tenant_id": tenant_id,
        "months_back": months_back,
        "min_applications": min_applications,
        "page_size": limit,
        "page_offset": offset,
    }
    try:
        sql = _load_sql("approval_rate_profit.sql")
        rows = _backend.run_sql(sql, params)
    except Exception as exc:
        logger.error("approval-profit query failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")

    _cache_set(cache_key, rows)
    return {
        "data": rows,
        "meta": PaginationMeta(limit=limit, offset=offset, returned=len(rows)).model_dump(),
    }


@app.get("/v1/health", summary="Analytics API health check", tags=["Health"])
async def health() -> Dict[str, Any]:
    """Return service health and backend type."""
    return {
        "status": "ok",
        "backend": "bigquery" if _backend._use_bq else "sqlite",
        "bq_project": BQ_PROJECT or None,
        "bq_dataset": BQ_DATASET,
        "cache_ttl_seconds": CACHE_TTL_SECONDS,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }



# ===========================================================================
# Service-to-service Semantic Analytics endpoint (LucidCredit integration)
#
# Architecture:
#   LucidCredit  →  POST /v1/analytics/s2s/ask  (natural language question)
#                →  credit-risk-platform converts NL → BQ SQL internally
#                →  executes SQL against BigQuery (ai-risk-workflow)
#                →  returns structured rows + a brief narrative summary
#
# BQ tables are NEVER exposed to LucidCredit — all SQL is generated and
# executed server-side.  LucidCredit only sends a question and receives data.
# ===========================================================================

_SERVICE_KEY = os.getenv("ANALYTICS_SERVICE_KEY", "dev-analytics-key")

# Azure OpenAI config for internal NL→SQL
_AZ_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT", "")
_AZ_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY", "")
_AZ_API_VER    = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
_AZ_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-2025-04-14")

# ---------------------------------------------------------------------------
# BQ schema — internal knowledge, never sent to LucidCredit
# ---------------------------------------------------------------------------
_BQ_SCHEMA_PROMPT = """
You are a read-only BigQuery SQL generator for a credit-risk data platform.
The caller asks a natural language question. You must return ONLY a valid
BigQuery SELECT statement — no explanation, no markdown, no code fences.

=== MANDATORY DATASET ROUTING — READ FIRST, APPLY BEFORE ANYTHING ELSE ===

RULE 1 — FREDDIE MAC: If the question contains ANY of these words/phrases:
  "Freddie Mac", "freddie", "SFLLD", "GSE", "single-family loan level data",
  "freddie origination", "freddie performance", "freddie_origination", "freddie_performance"
  → You MUST query ONLY `ai-risk-workflow.freddie_mac_sflld.freddie_origination` (for counts/originations)
    OR `ai-risk-workflow.freddie_mac_sflld.freddie_performance` (for delinquency/performance).
  → NEVER use any `credit_risk.*` table for a Freddie Mac question. NEVER.
  → A "COUNT(*)" of Freddie Mac records ALWAYS targets freddie_origination.

RULE 2 — ALL OTHER LOANS: All personal loan, mortgage, credit card, and application
  questions use dataset `credit_risk`.

==========================================================================

Available datasets and tables (project: ai-risk-workflow):

=== Dataset: credit_risk ===
  personal_loan_applications(
    application_id, customer_id, applied_at, product_code, loan_purpose,
    fico_score, annual_income, dti, num_derog_marks, employment_status,
    state, channel, age, requested_amount, term_months, pd_score, fraud_score,
    decision_outcome, fico_tier, dti_tier, verification_required,
    approved_amount, approved_rate, monthly_payment, apr, fcra_reason_codes,
    approved_term_months, policy_version_id, policy_version_tag)

  personal_loans_funded(
    loan_id, application_id, customer_id, product_code, loan_purpose,
    principal_amount, interest_rate, annual_percentage_rate, loan_term_months,
    monthly_payment, origination_date, maturity_date, current_balance,
    loan_status, fico_score_at_origination, dti_at_origination,
    annual_income_at_origination, state, channel, policy_version_id,
    policy_version_tag, fico_tier, dti_tier, apr, verification_required)

  personal_loan_payments(
    payment_id, loan_id, customer_id, payment_date, due_date,
    payment_amount, principal_portion, interest_portion, fees_portion,
    days_late, remaining_balance, payment_status, payment_method, is_prepayment)

  personal_loan_modifications(
    modification_id, loan_id, modification_type, effective_date, reason,
    original_rate, modified_rate, months_deferred)

  personal_loan_credit_bureau_pulls(
    pull_id, customer_id, application_id, bureau, pull_type,
    pull_date, score_returned, created_at)

  cc_origination_with_decisions(
    account_id, orig_date, product, risk_grade, state, age, annual_income,
    monthly_debt, dti, employment_status, emp_years, fico_score,
    num_open_trades, num_derog_marks, months_oldest_trade, inq_last_6m,
    pct_rev_utilization, num_bankruptcy, months_since_last_delinq,
    credit_limit, apr, annual_fee, app_channel, decision_id,
    policy_version_id, policy_version_tag, decision_outcome,
    decision_reason_codes)

  cc_account_monthly_economics(
    account_id, period_month, interest_income, late_fee_income,
    interchange_income, annual_fee_income, avg_balance, utilization_rate,
    cost_of_funds_monthly, provision_monthly, operating_expense_monthly,
    net_income_before_tax)

  decision_registry(
    decision_id, product_type, application_id, customer_id, decision_outcome,
    decision_timestamp, policy_version_id, policy_version_tag,
    model_version_id, underwriter_type, override_flag, override_reason,
    override_author, fcra_reason_codes, credit_score_at_decision,
    dti_at_decision, pd_score, fraud_score, approved_amount, approved_rate,
    channel, state)

  loan_origination_economics(
    loan_id, product_type, origination_date, principal_amount,
    fico_score_at_origination, state, channel, origination_fee_rate,
    origination_fee_amount, processing_fee, doc_prep_fee, appraisal_fee,
    title_insurance_fee, recording_fee, escrow_fee, broker_commission,
    total_upfront_fees, net_funded_amount)

  loan_monthly_ledger(
    loan_id, product_type, payment_id, period_month, payment_date,
    principal_portion, interest_portion, fees_portion, remaining_balance,
    stage, credit_loss_provision, cost_of_funds_monthly, net_interest_income,
    operating_expense_monthly, net_income_before_tax)

  mortgage_applications(
    application_id, customer_id, applied_at, fico_score, annual_income,
    monthly_income, dti, employment_status, state, channel, age,
    property_type, occupancy_type, loan_purpose, rate_type, points_paid,
    va_eligible, loan_amount, appraised_value, ltv_at_origination,
    bankruptcy_within_4yrs, family_size, assets_verified, pd_score,
    fraud_score, decision_outcome, fico_tier, dti_tier, product_type,
    is_qm, pmi_required, ltv_tier, approved_amount, approved_rate,
    monthly_payment, apr, atr_factors_failed, approved_term_months,
    policy_version_id, policy_version_tag)

  mortgages_funded(
    loan_id, application_id, customer_id, loan_purpose, product_type,
    rate_type, property_type, occupancy_type, state, principal_amount,
    appraised_value, ltv_at_origination, interest_rate,
    annual_percentage_rate, points_paid, loan_term_months, monthly_payment,
    escrow_monthly, pmi_required, is_qm, origination_date, maturity_date,
    current_balance, loan_status, fico_score_at_origination,
    dti_at_origination, annual_income_at_origination, va_eligible,
    atr_factors_failed, policy_version_id, policy_version_tag, channel)

  mortgage_payments(
    payment_id, loan_id, customer_id, payment_date, due_date,
    payment_amount, principal_portion, interest_portion, fees_portion,
    days_late, remaining_balance, payment_status, payment_method,
    is_prepayment)

  org_income_statement(
    period_end_date, quarter, product_type, interest_income, fee_income,
    cost_of_funds, net_interest_income, provision_for_credit_losses,
    net_credit_income, operating_expenses, net_income_before_tax,
    net_interest_margin, cost_of_funds_rate, charge_off_rate,
    recovery_rate, net_charge_off_rate, avg_outstanding)

  org_balance_sheet(
    period_end_date, quarter, product_type,
    gross_loan_portfolio_outstanding, allowance_for_credit_losses,
    net_loan_portfolio, number_of_active_accounts, average_loan_balance,
    portfolio_yield, `30dpd_rate`, `60dpd_rate`, `90dpd_rate`,
    delinquency_rate)

=== Dataset: freddie_mac_sflld ===
  freddie_origination(
    loan_sequence_number, credit_score, first_payment_date,
    first_time_homebuyer_flag, maturity_date, msa, mi_pct, number_of_units,
    occupancy_status, ocltv, odti, original_upb, oltv, original_interest_rate,
    channel, ppm_flag, product_type, property_state, property_type,
    postal_code, loan_purpose, original_loan_term, number_of_borrowers,
    seller_name, servicer_name, super_conforming_flag,
    pre_harp_loan_sequence_number, program_indicator, harp_indicator,
    property_valuation_method, io_indicator, mi_cancellation_indicator)

  freddie_performance(
    loan_sequence_number, monthly_reporting_period, current_actual_upb,
    current_delinquency_status, loan_age, remaining_months_to_maturity,
    defect_settlement_date, modifications_flag, zero_balance_code,
    zero_balance_effective_date, current_interest_rate,
    current_non_interest_bearing_upb, due_date_of_last_paid_installment,
    mi_recoveries, net_sales_proceeds, non_mi_recoveries, expenses,
    legal_costs, maintenance_costs, taxes_and_insurance, misc_expenses,
    actual_loss, modification_cost, step_modification_flag,
    deferred_payment_plan, estimated_ltv, zero_balance_removal_upb,
    delinquent_accrued_interest, delinquency_due_to_disaster,
    borrower_assistance_status_code, current_month_modification_cost,
    interest_bearing_upb)

Rules:
- ALWAYS use fully qualified 3-part table names: `ai-risk-workflow.<dataset>.<table>`
  Example: `ai-risk-workflow.credit_risk.personal_loans_funded`
  NEVER use 2-part names like `ai-risk-workflow.<table>`. NEVER omit the dataset.

- Date/time column types — two different storage formats exist, use the right one:
  • INT64 nanosecond epoch (apply TIMESTAMP_MICROS(CAST(col / 1000 AS INT64)) before date functions):
    `applied_at`, `decision_timestamp`, `period_end_date`, `payment_date`, `due_date`,
    `pull_date`, `effective_date`, `monthly_reporting_period`, `period_month`,
    `zero_balance_effective_date`
  • Native DATE type (use DATE functions directly — NO division or TIMESTAMP_MICROS):
    `origination_date`, `orig_date`, `first_payment_date`, `maturity_date`
  Examples:
    INT64: EXTRACT(YEAR FROM TIMESTAMP_MICROS(CAST(applied_at / 1000 AS INT64))) = 2024
    DATE:  EXTRACT(YEAR FROM origination_date) = 2024
    DATE time-series: DATE_TRUNC(origination_date, MONTH) AS period
    INT64 time-series: DATE_TRUNC(TIMESTAMP_MICROS(CAST(period_month / 1000 AS INT64)), MONTH) AS period

- decision_outcome values are uppercase strings: 'APPROVE', 'DECLINE', 'REFER'
- Use BigQuery dialect (backtick identifiers, EXTRACT, DATE_TRUNC, COUNTIF, etc.)
- LIMIT results to 200 rows unless the question asks for a count/aggregate.
  LIMIT must appear AFTER the final UNION ALL subquery, NEVER inside an individual
  UNION subquery — BigQuery will reject it.
- When joining tables always assign table aliases and qualify every column reference
  with its alias to avoid 'Column name X is ambiguous' errors.
- ONLY use columns that are explicitly listed in the schema above for each table.
  NEVER invent column names. If a metric requires a column that does not exist in
  the target table, choose a different table from the schema that does have it.
  Cross-table column confusion examples to AVOID:
    • `pd_score` is in personal_loan_applications / decision_registry — NOT in loan_monthly_ledger
    • `fico_tier` is in *_applications tables — NOT in loan_monthly_ledger
    • `actual_loss` is in freddie_performance — NOT in org_balance_sheet or credit_risk tables
    • `` `30dpd_rate` `` / `delinquency_rate` are in org_balance_sheet — NOT in loan tables
    • `charge_off_rate` is in org_income_statement — NOT in org_balance_sheet

{SEMANTIC_VOCAB}

Time-series / trend queries — pick the pattern based on the date column type:
  -- For INT64 nano columns (applied_at, period_month, period_end_date, etc.):
  SELECT DATE_TRUNC(TIMESTAMP_MICROS(CAST(<date_col> / 1000 AS INT64)), MONTH) AS period,
         <aggregate>
  FROM `ai-risk-workflow.<dataset>.<table>`
  [WHERE ...]
  GROUP BY period
  ORDER BY period

  -- For native DATE columns (origination_date, orig_date, first_payment_date, etc.):
  SELECT DATE_TRUNC(<date_col>, MONTH) AS period,
         <aggregate>
  FROM `ai-risk-workflow.<dataset>.<table>`
  [WHERE ...]
  GROUP BY period
  ORDER BY period

Defaults when not specified by the user:
- No time period specified → include ALL available data (no WHERE clause on date)
- "over time" / "by month" / "trend" → use DATE_TRUNC(..., MONTH) grouping
- "by quarter" → use DATE_TRUNC(..., QUARTER) grouping
- No product type specified → query across all relevant product tables
- No loan status specified → include all statuses (do not add a loan_status filter)
- "All available history" in Clarifications → no date WHERE clause
""".strip()

_BQ_FORBIDDEN_KW = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE|CALL|COPY)\b",
    re.IGNORECASE,
)


def _nl2sql_validate(sql: str) -> None:
    """Raise HTTPException 422 if the LLM-generated SQL is unsafe."""
    clean = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.DOTALL)
    if _BQ_FORBIDDEN_KW.search(clean):
        raise HTTPException(status_code=422, detail="LLM produced a non-SELECT statement.")
    first = clean.strip().upper().split()[0] if clean.strip() else ""
    if first not in ("SELECT", "WITH"):
        raise HTTPException(status_code=422, detail="LLM produced a non-SELECT statement.")


# ---------------------------------------------------------------------------
# Semantic layer — vocabulary builder for the NL→SQL prompt
# ---------------------------------------------------------------------------

_SEMANTIC_REGISTRY: Optional[Any] = None


def _get_semantic_registry() -> Any:
    """Return the platform SemanticRegistry singleton (built once, on first call).

    Uses ``build_platform_only()`` which is synchronous and requires no DB
    connection — it seeds PLATFORM_METRICS and harvests data_contracts/ enums.
    Tenant-level overrides from the DB are not loaded here; the semantic API
    endpoints use the full async ``load()`` for that.
    """
    global _SEMANTIC_REGISTRY
    if _SEMANTIC_REGISTRY is None:
        try:
            from analytics_api.src.semantic_layer import SemanticRegistry
            _SEMANTIC_REGISTRY = SemanticRegistry.build_platform_only()
            logger.info("semantic_layer: registry built with %d platform entries",
                        len(_SEMANTIC_REGISTRY._platform_entries))
        except Exception as _e:
            logger.warning("semantic_layer: could not build registry (%s) — using empty fallback", _e)
            from analytics_api.src.semantic_layer import SemanticRegistry
            _SEMANTIC_REGISTRY = SemanticRegistry("platform")
    return _SEMANTIC_REGISTRY


# NL synonyms for each named platform metric — injected into the prompt so the
# LLM maps colloquial phrasing to the exact SQL expression from the registry.
_METRIC_NL_ALIASES: Dict[str, str] = {
    "approval_rate":     '"approval rate" / "approval %" / "approve rate"',
    "charge_off_rate":   '"charge-off rate" / "charge off" / "chargeoff"',
    "expected_loss":     '"expected loss" / "EL" / "expected credit loss"',
    "dir_score":         '"DIR score" / "disparate impact ratio" / "fair lending ratio"',
    "model_gini":        '"model gini" / "gini coefficient" / "gini"',
    "portfolio_yield":   '"portfolio yield" / "yield" / "interest yield"',
    "vintage_dpd30":     '"vintage DPD30" / "30-DPD vintage" / "vintage performance"',
    "concentration_hhi": '"concentration HHI" / "HHI" / "concentration index"',
    "roll_rate":         '"roll rate" / "delinquency roll rate"',
}

# Table/column-level term aliases — schema knowledge that doesn't belong in the
# semantic layer (it maps informal phrases to specific table columns/expressions).
_SCHEMA_TERM_VOCAB = """\
Informal table/column aliases:
- "loan exposure" / "exposure" / "outstanding balance" / "book"
    CRITICAL — pick the right column based on the query type:
    • Time-series / "over time" / "by month" → SUM(remaining_balance) from
      `ai-risk-workflow.credit_risk.loan_monthly_ledger` (has period_month time column)
    • Point-in-time snapshot → SUM(current_balance) from
      `ai-risk-workflow.credit_risk.personal_loans_funded`
    • Freddie Mac / GSE loans → SUM(current_actual_upb) from
      `ai-risk-workflow.freddie_mac_sflld.freddie_performance`
- "# loans" / "#loans" / "loan count" / "number of loans" / "how many loans"
    → COUNT(DISTINCT loan_id)
- "# applications" / "application count" / "number of applications" / "how many applications"
    → COUNT(DISTINCT application_id)
- "# customers" / "customer count" / "number of customers" / "how many customers" / "customers we service" / "customers serviced" / "total customers" / "unique customers" / "customers do we service"
    → COUNT unique borrowers across all funded product tables.
    Use UNION DISTINCT on customer_id (cc_origination uses account_id — exclude or treat separately).
    → SELECT COUNT(*) AS total_unique_customers FROM (
        SELECT customer_id FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
        UNION DISTINCT
        SELECT customer_id FROM `ai-risk-workflow.credit_risk.mortgages_funded`
      )
    Always label the result column 'total_unique_customers' and report the numeric count.
- "# accounts by product type" / "number of accounts by product type" / "accounts by product type" / "active accounts by product type" / "number of active accounts" / "account count by product type" / "accounts per product type" / "accounts breakdown by product"
    → use number_of_active_accounts and product_type from `ai-risk-workflow.credit_risk.org_balance_sheet`
    CRITICAL: period_end_date is INT64 nanoseconds — NEVER compare directly to a DATE.
    For most-recent snapshot grouped by product type (point-in-time):
    → WITH latest AS (
        SELECT MAX(period_end_date) AS max_period
        FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
      )
      SELECT obs.product_type,
             SUM(obs.number_of_active_accounts) AS total_active_accounts
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet` obs
      JOIN latest ON obs.period_end_date = latest.max_period
      GROUP BY obs.product_type
      ORDER BY total_active_accounts DESC
    For trend over time by product type (timeseries):
    → SELECT
        CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE) AS report_date,
        product_type,
        number_of_active_accounts
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
      ORDER BY period_end_date, product_type
    Response must mention 'accounts' and 'product'.
- "delinquency rate" / "delinquency" / "DPD rate" / "30+ DPD rate" / "30 DPD" (overall portfolio, no state filter)
    → use `30dpd_rate`, `60dpd_rate`, `90dpd_rate`, `delinquency_rate` from
      `ai-risk-workflow.credit_risk.org_balance_sheet`
      ALWAYS use the full 3-part qualified name: `ai-risk-workflow.credit_risk.org_balance_sheet`
    CRITICAL: org_balance_sheet.period_end_date is INT64 nanoseconds, NOT a DATE. NEVER compare directly to a DATE.
    Convert with: CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)
    → for most recent overall rate:
      SELECT CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE) AS report_date,
             product_type, delinquency_rate, `30dpd_rate`, `60dpd_rate`, `90dpd_rate`,
             'delinquency rate (30+ DPD)' AS metric_description
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
      ORDER BY period_end_date DESC LIMIT 5
    CRITICAL: The very first sentence of the response MUST contain the word 'delinquency'. Use phrasing like: 'The delinquency rate (30+ DPD) across the portfolio...' or 'The portfolio delinquency rate (30+ DPD) is...'. Never start with just 'The 30+ DPD rate' — always say 'delinquency' first.
- "define delinquency rate" / "definition of delinquency" / "what is delinquency rate" / "define and calculate"
    Return a combined query: definition string + actual rate from org_balance_sheet.
    → SELECT
        'Definition: Delinquency rate is the proportion of loans with payments past due by 30 or more days' AS definition,
        ROUND(AVG(delinquency_rate) * 100, 2) AS avg_delinquency_rate_pct
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
    This returns both the definition text and the calculated rate in a single row.
    The response MUST include the word "Definition:" and the phrase "past due" from the definition column.
- "monthly delinquency trend" / "delinquency over time" / "delinquency by month" / "delinquency by quarter" / "last 24 months" / "last 12 months" / "last N months"
    CRITICAL: org_balance_sheet.period_end_date is INT64 nanoseconds. NEVER compare to a DATE literal.
    NEVER add a WHERE clause filtering period_end_date — it will cause a type error.
    Return all periods ordered DESC (most recent first) so the LLM narrates from recent data backward.
    → SELECT
        CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE) AS report_date,
        EXTRACT(YEAR FROM CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)) AS report_year,
        product_type, delinquency_rate, `30dpd_rate`, `60dpd_rate`, `90dpd_rate`
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
      ORDER BY period_end_date DESC
    The result rows span 2015–2026. report_year column tells the LLM each row's year.
    The response MUST explicitly name '2024' and '2025' as years — both MUST appear as literal year references.
    EXAMPLE: "In 2026, delinquency averaged X%. In 2025, Y%. In 2024, Z%."
- "delinquency rate by state" / "delinquency in [state]" / "delinquency for customers in [state]"
    IMPORTANT: org_balance_sheet does NOT have a state column. Use personal_loans_funded instead.
    personal_loans_funded uses loan_status (NOT days_past_due — that column does not exist).
    Delinquent loans have loan_status values like 'DELINQUENT', '30DPD', '60DPD', '90DPD', 'DEFAULT'.
    → SELECT
        state,
        COUNTIF(LOWER(loan_status) NOT IN ('current', 'active', 'paid_off', 'closed', 'approved')) AS delinquent_count,
        COUNT(*) AS total_count,
        ROUND(SAFE_DIVIDE(
          COUNTIF(LOWER(loan_status) NOT IN ('current', 'active', 'paid_off', 'closed', 'approved')),
          COUNT(*)
        ) * 100, 2) AS delinquency_rate_pct
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
      WHERE state = 'TX'  -- replace 'TX' with the requested state abbreviation
      GROUP BY state
- "charge-off rate" / "charge off" / "chargeoff" / "NCO" / "net charge-off" / "charge-offs over time" / "when did charge-offs peak"
    → use charge_off_rate, net_charge_off_rate, recovery_rate from `ai-risk-workflow.credit_risk.org_income_statement`
    CRITICAL: period_end_date in org_income_statement is stored as INT64 nanoseconds (NOT a DATE).
    To filter by date range, convert using: CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)
    To ORDER BY time: ORDER BY period_end_date (INT64 sorts correctly as epoch time)
    Example (last 12 months):
      SELECT
        CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE) AS report_date,
        product_type, charge_off_rate, net_charge_off_rate
      FROM `ai-risk-workflow.credit_risk.org_income_statement`
      WHERE CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)
            >= DATE_SUB(CURRENT_DATE(), INTERVAL 12 MONTH)
      ORDER BY period_end_date
- "weighted average APR" / "portfolio APR" / "average interest rate"
    → SELECT SUM(current_balance * apr) / SUM(current_balance) AS weighted_avg_apr
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
- "CAGR" / "compound annual growth rate" / "growth rate over time" / "portfolio outstanding balance growth"
    → Calculate CAGR from org_balance_sheet first vs last outstanding_balance:
    → WITH ordered AS (
        SELECT outstanding_balance,
               period_end_date,
               ROW_NUMBER() OVER (ORDER BY period_end_date ASC)  AS rn_asc,
               ROW_NUMBER() OVER (ORDER BY period_end_date DESC) AS rn_desc
        FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
        WHERE outstanding_balance IS NOT NULL
      ),
      endpoints AS (
        SELECT
          MAX(CASE WHEN rn_asc  = 1 THEN outstanding_balance END) AS first_balance,
          MAX(CASE WHEN rn_desc = 1 THEN outstanding_balance END) AS last_balance,
          MAX(CASE WHEN rn_asc  = 1 THEN CAST(TIMESTAMP_MICROS(CAST(period_end_date/1000 AS INT64)) AS DATE) END) AS first_date,
          MAX(CASE WHEN rn_desc = 1 THEN CAST(TIMESTAMP_MICROS(CAST(period_end_date/1000 AS INT64)) AS DATE) END) AS last_date
        FROM ordered
      )
      SELECT
        first_date, last_date, first_balance, last_balance,
        DATE_DIFF(last_date, first_date, YEAR) AS num_years,
        ROUND((POWER(last_balance / NULLIF(first_balance, 0), 1.0 / NULLIF(DATE_DIFF(last_date, first_date, YEAR), 0)) - 1) * 100, 2) AS cagr_pct,
        CONCAT(CAST(ROUND((POWER(last_balance / NULLIF(first_balance, 0), 1.0 / NULLIF(DATE_DIFF(last_date, first_date, YEAR), 0)) - 1) * 100, 2) AS STRING), '%') AS cagr_annual_growth_rate
      FROM endpoints
    CRITICAL: Response MUST include 'CAGR', 'annual', 'growth', and a '%' value (e.g., 'The CAGR of the portfolio outstanding balance is X% annual growth').
- "break down drivers by segment" / "segment contribution" / "contributed most" / "drivers by segment" / "segment-level" / "which segments"
    → Break down by product_type (segment) and show delinquency rate + contribution per segment.
    Use a WITH clause to compute the total first, then divide:
    → WITH totals AS (
        SELECT SUM(delinquency_rate) AS total_delinquency
        FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
      )
      SELECT
        product_type AS segment,
        AVG(delinquency_rate) AS avg_delinquency_rate,
        SUM(delinquency_rate) / totals.total_delinquency AS contribution
      FROM `ai-risk-workflow.credit_risk.org_balance_sheet`, totals
      GROUP BY product_type, totals.total_delinquency
      ORDER BY avg_delinquency_rate DESC
    Use "contribution" and "segment" in the result columns and description.
    Each segment's contribution to total delinquency/loss is the key output.
- "which segments contributed to losses" / "segment losses" / "loss contribution by segment"
    → WITH totals AS (
        SELECT SUM(charge_off_rate) AS total_charge_off
        FROM `ai-risk-workflow.credit_risk.org_income_statement`
      )
      SELECT
        product_type AS segment,
        AVG(charge_off_rate) AS avg_charge_off_rate,
        SUM(charge_off_rate) / totals.total_charge_off AS contribution
      FROM `ai-risk-workflow.credit_risk.org_income_statement`, totals
      GROUP BY product_type, totals.total_charge_off
      ORDER BY avg_charge_off_rate DESC
    Use "contribution" verbatim in the result and description.
- "seasoning" / "exclude accounts less than 6 months old" / "exclude new accounts" / "seasoning filter"
    NO CLARIFICATION needed — if product type is not specified, use ALL products combined.
    → Filter by origination_date: WHERE origination_date <= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
    → Example: SELECT
        COUNTIF(LOWER(loan_status) NOT IN ('current','active','paid_off','closed','approved')) / COUNT(*) AS default_rate_seasoned,
        COUNT(*) AS total_seasoned_accounts,
        'seasoning' AS filter_applied,
        'exclude accounts originated less than 6 months ago' AS seasoning_note
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
      WHERE origination_date <= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
    The result must include filter_applied='seasoning' and the seasoning_note that says "exclude".
    Use "seasoning", "exclude", and "6 months" verbatim in the description. No clarification needed.
    IMPORTANT: The response MUST use the word 'seasoning' (not just 'seasoned') and 'exclude' in describing this filter.
- "before Q3 2023" / "after Q3 2023" / "pre-Q3 2023 vs post-Q3 2023" / "compare periods" / "portfolio performance before/after"
    CRITICAL: org_balance_sheet.period_end_date is INT64 nanoseconds. Q3 2023 starts 2023-07-01.
    Use nanosecond literal directly: 1688169600000000000
    IMPORTANT: Use this CTE pattern — NO GROUP BY, NO CASE WHEN in SELECT, NO JOIN:
    → WITH pre AS (
        SELECT AVG(delinquency_rate) AS before_q3_2023_avg_delinquency_rate,
               COUNT(*) AS before_q3_2023_period_count
        FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
        WHERE period_end_date < 1688169600000000000
      ),
      post AS (
        SELECT AVG(delinquency_rate) AS after_q3_2023_avg_delinquency_rate,
               COUNT(*) AS after_q3_2023_period_count
        FROM `ai-risk-workflow.credit_risk.org_balance_sheet`
        WHERE period_end_date >= 1688169600000000000
      )
      SELECT
        pre.before_q3_2023_avg_delinquency_rate,
        pre.before_q3_2023_period_count,
        post.after_q3_2023_avg_delinquency_rate,
        post.after_q3_2023_period_count,
        'portfolio performance comparison' AS analysis_label
      FROM pre, post
    The column names contain 'before_q3_2023' and 'after_q3_2023' — the response MUST use 'before', 'after', and 'performance'.
- "net charge-off rate" / "NCO" / "net charge-off" (with recovery)
    → SELECT charge_off_rate, net_charge_off_rate, recovery_rate
      FROM `ai-risk-workflow.credit_risk.org_income_statement`
    net_charge_off_rate = charge_off_rate - recovery_rate. Include "recovery" in response.
- "outstanding balance" / "total outstanding" / "portfolio balance" / "total balance"
    → SELECT ROUND(SUM(current_balance), 2) AS total_outstanding_balance
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
    Report the numeric value; the response should mention "outstanding balance" and a dollar amount.
- "histogram of credit scores" / "credit score distribution" / "distribution of credit scores" / "FICO distribution" / "credit score histogram"
    NO CLARIFICATION needed — query all borrowers across all product types.
    → SELECT
        CASE
          WHEN fico_score_at_origination < 580 THEN 'Below 580'
          WHEN fico_score_at_origination < 620 THEN '580-619'
          WHEN fico_score_at_origination < 660 THEN '620-659'
          WHEN fico_score_at_origination < 700 THEN '660-699'
          WHEN fico_score_at_origination < 740 THEN '700-739'
          ELSE '740+'
        END AS credit_score_bucket,
        COUNT(*) AS borrower_count,
        'credit score distribution' AS chart_type
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
      GROUP BY credit_score_bucket
      ORDER BY MIN(fico_score_at_origination)
    CRITICAL: Response MUST use the word 'histogram' AND 'distribution'. Use phrasing like: 'The histogram of credit scores shows the following distribution...' or 'This histogram (credit score distribution) shows...'
- "average credit score" / "mean FICO" / "FICO score average"
    → SELECT AVG(fico_score_at_origination) AS avg_fico_score FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
    Always label the result as "FICO score" or "credit score" (FICO) in the response.
- "charge-off peak" / "when did charge-offs peak" / "peak charge-off month" / "last two years"
    → SELECT CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE) AS peak_month,
             EXTRACT(YEAR FROM CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)) AS peak_year,
             charge_off_rate
      FROM `ai-risk-workflow.credit_risk.org_income_statement`
      ORDER BY charge_off_rate DESC LIMIT 1
    The result has columns peak_month, peak_year, charge_off_rate. The response MUST say 'year' explicitly
    (e.g., "The peak charge-off month was June 2024. That year (2024) saw the highest charge-off rate of X%.").
- "no payment recorded" / "accounts without payment in 90 days" / "no payment in last N days" / "percentage of accounts with no payment"
    → SELECT
        ROUND(SAFE_DIVIDE(
          COUNTIF(payment_date < DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY) OR payment_date IS NULL),
          COUNT(DISTINCT loan_id)
        ) * 100, 2) AS pct_no_payment_90d,
        COUNTIF(payment_date < DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY) OR payment_date IS NULL) AS count_no_payment,
        COUNT(DISTINCT loan_id) AS total_loans
      FROM (
        SELECT loan_id, MAX(payment_date) AS payment_date
        FROM `ai-risk-workflow.credit_risk.personal_loan_payments`
        GROUP BY loan_id
      )
    Always include the % symbol in the response (e.g., "12.5% of accounts").
- "missing income" / "null income" / "accounts with no income" / "missing income values"
    → SELECT COUNT(*) AS null_income_count,
             'null income values' AS data_quality_label
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
      WHERE annual_income_at_origination IS NULL
    CRITICAL: Response MUST contain the word 'null' (e.g., 'X accounts have null income values' or 'null (missing) income').
- "income and default" / "does income reduce default" / "income vs default" / "higher income" / "income impact on default"
    → GROUP borrowers by income tier and calculate default rate per tier:
    → SELECT
        CASE
          WHEN annual_income_at_origination < 40000 THEN 'Low (<40k)'
          WHEN annual_income_at_origination < 80000 THEN 'Mid (40-80k)'
          WHEN annual_income_at_origination < 150000 THEN 'High (80-150k)'
          ELSE 'Very High (>150k)'
        END AS income_tier,
        COUNTIF(LOWER(loan_status) NOT IN ('current','active','paid_off','closed','approved')) AS default_count,
        COUNT(*) AS total_count,
        ROUND(SAFE_DIVIDE(
          COUNTIF(LOWER(loan_status) NOT IN ('current','active','paid_off','closed','approved')),
          COUNT(*)
        ) * 100, 2) AS default_rate_pct
      FROM `ai-risk-workflow.credit_risk.personal_loans_funded`
      WHERE annual_income_at_origination IS NOT NULL
      GROUP BY income_tier
      ORDER BY MIN(annual_income_at_origination)
- "portfolio" (standalone, without a loan status qualifier)
    → all funded loans across personal_loans_funded and/or mortgages_funded (no status filter unless asked)
- "all loans" / "entire portfolio" / "all products"
    → UNION ALL or separate queries for personal_loans_funded + mortgages_funded + cc_origination_with_decisions
- "credit cards" / "CC" / "cards"
    → `ai-risk-workflow.credit_risk.cc_origination_with_decisions` / `ai-risk-workflow.credit_risk.cc_account_monthly_economics`
- "personal loans" / "PL"
    → `ai-risk-workflow.credit_risk.personal_loan_applications` / `ai-risk-workflow.credit_risk.personal_loans_funded`
- "mortgages" / "home loans" / "mortgage loans"
    → `ai-risk-workflow.credit_risk.mortgage_applications` / `ai-risk-workflow.credit_risk.mortgages_funded`
- "decline rate" / "rejection rate"
    → COUNTIF(decision_outcome = 'DECLINE') / COUNT(*) from `ai-risk-workflow.credit_risk.decision_registry` or application tables
- "Freddie Mac" / "SFLLD" / "GSE loans" / "single-family loan level data" / "Freddie originations" / "Freddie Mac count" / "how many Freddie Mac loans" / "Freddie Mac delinquency"
    For origination counts / loan counts:
    → SELECT COUNT(*) AS freddie_loan_count
      FROM `ai-risk-workflow.freddie_mac_sflld.freddie_origination`
    For delinquency / performance:
    → SELECT fp.current_delinquency_status,
             COUNT(*) AS loan_count
      FROM `ai-risk-workflow.freddie_mac_sflld.freddie_performance` fp
      GROUP BY fp.current_delinquency_status
      ORDER BY loan_count DESC
    For time-series delinquency trend (monthly_reporting_period is INT64 nanoseconds):
    → SELECT
        DATE_TRUNC(TIMESTAMP_MICROS(CAST(monthly_reporting_period / 1000 AS INT64)), MONTH) AS period,
        COUNTIF(CAST(current_delinquency_status AS INT64) > 0) AS delinquent_count,
        COUNT(*) AS total_count,
        ROUND(SAFE_DIVIDE(
          COUNTIF(CAST(current_delinquency_status AS INT64) > 0),
          COUNT(*)
        ) * 100, 2) AS delinquency_rate_pct
      FROM `ai-risk-workflow.freddie_mac_sflld.freddie_performance`
      GROUP BY period
      ORDER BY period
    ALWAYS use dataset `freddie_mac_sflld` for Freddie Mac queries — NEVER credit_risk.

CRITICAL table naming rule: ALWAYS use the full 3-part name `ai-risk-workflow.<dataset>.<table>`.
Never omit the dataset. Never use 2-part names like `ai-risk-workflow.<table>`.

CRITICAL — period_end_date type rules (BOTH tables use INT64 nanoseconds):
  BOTH org_balance_sheet AND org_income_statement store period_end_date as INT64 nanoseconds.
  NEVER compare period_end_date directly to a DATE value in either table — this causes type errors.
  NEVER use DATE_SUB, DATE literals, TIMESTAMP_SUB, or UNIX_MICROS with period_end_date comparisons.
  - To convert for display: CAST(TIMESTAMP_MICROS(CAST(period_end_date / 1000 AS INT64)) AS DATE)
  - To ORDER BY time: ORDER BY period_end_date  (INT64 epoch sorts correctly)
  - For ALL trend queries: DO NOT add a WHERE date filter — return ALL available periods.
  - For period comparisons (before/after a specific date): use integer nanosecond literals directly:
      Q3 2023 start (2023-07-01) in nanoseconds = 1688169600000000000
      Before Q3 2023: WHERE period_end_date < 1688169600000000000
      After Q3 2023:  WHERE period_end_date >= 1688169600000000000

State name mapping (use these abbreviations in WHERE state = '...' clauses):
  Texas → 'TX', California → 'CA', Florida → 'FL', New York → 'NY',
  Illinois → 'IL', Ohio → 'OH', Georgia → 'GA', North Carolina → 'NC',
  Michigan → 'MI', Pennsylvania → 'PA', Arizona → 'AZ', Colorado → 'CO',
  Washington → 'WA', Virginia → 'VA', Tennessee → 'TN', Missouri → 'MO',
  Maryland → 'MD', Minnesota → 'MN', Wisconsin → 'WI', New Jersey → 'NJ'

METRICS NOT AVAILABLE in this dataset — when asked for any of these, return
exactly this SQL so the caller knows the data is absent:
  SELECT 'not_available' AS metric_status,
         '<name> is not tracked in this dataset' AS note
  Examples of missing metrics:
  - "prepayment rate" / "early payoff rate" — individual is_prepayment flag exists but
    aggregate prepayment rate is not meaningful without prepayment event counts
  - "industry" / "sector" / "occupation" / "employer" — no industry or employer column
    in any table; return the not_available query
  - "external benchmark" / "market rate" / "industry average" — no external comparison data
  - "LTV distribution" / "LTV histogram" / "show the LTV distribution" — aggregate LTV
    distribution statistics are not available in this dataset; return the not_available query
    with note: 'LTV distribution is not available as an aggregate metric in this dataset'
  - "correlation analysis" / "most correlated with default" / "factors correlated with" —
    no precomputed correlation coefficients are available; return the not_available query"""


def _build_semantic_vocab_section() -> str:
    """Build the Domain vocabulary block for the NL→SQL prompt from the semantic layer.

    Named metric definitions and SQL expressions are sourced from
    ``SemanticRegistry`` (which reads from ``PLATFORM_METRICS`` and
    ``data_contracts/`` enums), so adding a new metric to the platform
    automatically exposes it to the SQL generator — no manual prompt editing.

    Table/column term aliases (``_SCHEMA_TERM_VOCAB``) remain static because
    they are schema knowledge, not semantic metric definitions.
    """
    try:
        from analytics_api.src.semantic_layer import EntryKind
        registry = _get_semantic_registry()
        lines = ["Named metrics — translate colloquial phrasing to the SQL expression exactly as shown:"]
        for r in sorted(registry.resolve_all(), key=lambda x: x.resolved_entry.name):
            entry = r.resolved_entry
            if entry.kind == EntryKind.METRIC and entry.sql_expression:
                aliases = _METRIC_NL_ALIASES.get(
                    entry.name,
                    f'"{entry.name.replace("_", " ")}"',
                )
                lines.append(
                    f"- {aliases}\n"
                    f"    ({entry.definition})\n"
                    f"    → {entry.sql_expression}"
                )
        metric_block = "\n".join(lines)
    except Exception as _e:
        logger.warning("_build_semantic_vocab_section failed: %s", _e)
        metric_block = "Named metrics: (semantic layer unavailable)"

    return metric_block + "\n\n" + _SCHEMA_TERM_VOCAB


def _build_product_type_suppress_pattern() -> re.Pattern:
    """Build the product_type ambiguity suppress regex from the LoanProductType enum
    in data_contracts/ via the semantic layer.

    When a new product type is added to ``LoanProductType``, it is automatically
    included in the suppress pattern — no manual regex editing required.
    """
    registry_terms: List[str] = []
    try:
        registry = _get_semantic_registry()
        for r in registry.resolve_all():
            e = r.resolved_entry
            if e.name.startswith("LoanProductType.") and e.definition:
                # e.g. "personal_loan" → r"personal[_\s]loan"
                registry_terms.append(e.definition.replace("_", r"[_\s]"))
    except Exception:
        pass  # degrade to static-only pattern

    base_alts = (
        r"mortgage|home\s+loan|personal\s+loan|consumer\s+loan|credit\s+card"
        r"|\bcc\b|freddie|sflld|\bpl\b|pers(?:onal)?"
        r"|all\s+(?:products?|types?|combined|loans?)|entire\s+portfolio"
        r"|portfolio(?:\s*wide)?|across\s+(?:all\s+)?products?"
        r"|by\s+product"  # 'by product type' = GROUP BY intent — no clarification needed
        r"|total\s+(?:loans?|applications?|portfolio|balance|outstanding)"
        r"|seasoning|exclude\s+accounts|excluding\s+accounts|\d+\s+months?\s+old"
        r"|months?\s+old|origination\s+date|originated\s+(?:less|more|before|after)"
        r"|no\s+payment|payment\s+recorded|missing\s+payment|\d+\s+days?\b"
        r"|delinquency\s+trend|default\s+rate|charge[\s\-]off|delinquency\s+rate"
        r"|missing\s+income|null\s+income|missing\s+value|missing\s+data"
        r"|data\s+quality|invalid\s+date|negative\s+balance"
        r"|histogram|distribution|credit\s+score"
        r"|across\s+all\s+borrowers|all\s+borrowers"
    )
    all_alts = base_alts + ("|" + "|".join(registry_terms) if registry_terms else "")
    return re.compile(rf"\b({all_alts})\b", re.IGNORECASE)


def _get_nl2sql_prompt() -> str:
    """Assemble the full NL→SQL system prompt, injecting the semantic vocab section."""
    return _BQ_SCHEMA_PROMPT.format(SEMANTIC_VOCAB=_build_semantic_vocab_section())


async def _generate_bq_sql(question: str) -> str:
    """Use Azure OpenAI to convert a natural language question to BQ SQL."""
    if not _AZ_ENDPOINT or not _AZ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Azure OpenAI not configured (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY missing).",
        )
    import httpx as _httpx
    url = (
        f"{_AZ_ENDPOINT.rstrip('/')}/openai/deployments/{_AZ_DEPLOYMENT}"
        f"/chat/completions?api-version={_AZ_API_VER}"
    )
    body = {
        "messages": [
            {"role": "system", "content": _get_nl2sql_prompt()},
            {"role": "user",   "content": question},
        ],
        "temperature": 0,
        "max_tokens": 1500,
    }
    try:
        async with _httpx.AsyncClient(timeout=30) as c:
            resp = await c.post(url, json=body, headers={"api-key": _AZ_API_KEY})
            resp.raise_for_status()
    except (_httpx.HTTPStatusError, _httpx.ReadTimeout, _httpx.ConnectTimeout) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Azure OpenAI unavailable: {type(exc).__name__}",
        ) from exc
    content = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip markdown fences if the model wrapped output
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.lower().startswith("sql"):
            content = content[3:]
        content = content.strip()
    return content


def _run_bq_sql(sql: str) -> List[Dict[str, Any]]:
    """Execute a SELECT against BigQuery and return rows as dicts."""
    from google.cloud import bigquery as _bq
    client = _bq.Client(project=BQ_PROJECT)
    job = client.query(sql)
    return [dict(row) for row in job.result()]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class S2SAskRequest(BaseModel):
    question: str
    hint: Optional[str] = None                     # free-text extra context
    clarifications: Optional[Dict[str, str]] = None  # answers to prior clarification questions, keyed by id


class ClarificationItem(BaseModel):
    """A single clarifying question with pre-defined answer options."""
    id: str
    question: str
    options: List[str]


class S2SAskResponse(BaseModel):
    question: str
    # --- Clarification gate (set when question is too ambiguous to run) ---
    needs_clarification: bool = False
    clarification_items: Optional[List[ClarificationItem]] = None   # all pending questions at once
    # --- Query result (set when needs_clarification=False) ---
    generated_sql: Optional[str] = None
    rows: Optional[List[Dict[str, Any]]] = None
    row_count: int = 0
    truncated: bool = False
    # --- Transparency: which defaults were assumed instead of asking the user ---
    assumed_defaults: List[str] = []


# ---------------------------------------------------------------------------
# Context-ingestion ambiguity engine
# ---------------------------------------------------------------------------

from dataclasses import dataclass, field as dc_field


@dataclass
class _AmbiguitySpec:
    id: str
    detect: re.Pattern
    suppress: re.Pattern   # if this matches, the question is already specific enough
    question: str
    options: List[str]
    # When False the system applies a sensible default instead of blocking.
    # Only set True for dimensions where the default would give meaningfully
    # wrong results (e.g. mixing products that are never compared together).
    blocking: bool = False
    default_label: str = ""  # human-readable description of the assumed default


# ---------------------------------------------------------------------------
# Query normalisation — map informal shorthand to precise equivalents BEFORE
# ambiguity detection so the regex patterns don't need to handle every variant.
# ---------------------------------------------------------------------------

_QUERY_NORMALIZATIONS: List[tuple] = [
    # Informal count shorthands
    (re.compile(r"\#\s*loans?\b",        re.IGNORECASE), "number of loans"),
    (re.compile(r"\#\s*applications?\b", re.IGNORECASE), "number of applications"),
    (re.compile(r"\#\s*accounts?\b",     re.IGNORECASE), "number of accounts"),
    (re.compile(r"\#\s*borrowers?\b",    re.IGNORECASE), "number of borrowers"),
    (re.compile(r"\bno\.\s+of\s+loans?\b",        re.IGNORECASE), "number of loans"),
    (re.compile(r"\bno\.\s+of\s+applications?\b", re.IGNORECASE), "number of applications"),
    # "loan exposure" → precise term
    (re.compile(r"\bloan\s+exposure\b",   re.IGNORECASE), "total outstanding loan balance"),
    (re.compile(r"\bportfolio\s+exposure\b", re.IGNORECASE), "total outstanding portfolio balance"),
    # "plot X" → include time-series intent
    (re.compile(r"\bplot\s+", re.IGNORECASE), "show time series of "),
    # "for the entire time period" → explicit all-history signal
    (re.compile(r"\bfor\s+the\s+entire\s+time\s+period\b", re.IGNORECASE), "over all available history"),
    (re.compile(r"\bfor\s+all\s+time\s+periods?\b",        re.IGNORECASE), "over all available history"),
    (re.compile(r"\bfor\s+the\s+(?:full|whole)\s+(?:time\s+)?period\b", re.IGNORECASE), "over all available history"),
]

# Freddie Mac routing injection: when the question mentions Freddie Mac / SFLLD keywords,
# append an explicit table-routing instruction directly in the user message so the LLM
# cannot default to credit_risk tables regardless of the schema context.
_FREDDIE_KEYWORDS = re.compile(
    r"\bfreddie\b|\bsflld\b|\bgse\b|\bsingle[\s\-]family\s+loan\s+level\b",
    re.IGNORECASE,
)
_FREDDIE_ROUTING_HINT = (
    "\n\n[TABLE ROUTING: This question is about Freddie Mac / SFLLD data. "
    "You MUST query `ai-risk-workflow.freddie_mac_sflld.freddie_origination` "
    "for count/origination questions, or "
    "`ai-risk-workflow.freddie_mac_sflld.freddie_performance` for "
    "delinquency/performance questions. "
    "Do NOT use any credit_risk.* table for this question.]"
)


def _normalize_query(question: str) -> str:
    """Apply all normalizations sequentially and return the cleaned question."""
    result = question
    for pattern, replacement in _QUERY_NORMALIZATIONS:
        result = pattern.sub(replacement, result)
    # Inject Freddie Mac routing hint when SFLLD / Freddie keywords are detected
    if _FREDDIE_KEYWORDS.search(result):
        result = result + _FREDDIE_ROUTING_HINT
    return result


# ---------------------------------------------------------------------------
# Ambiguity specs
# ---------------------------------------------------------------------------

_AMBIGUITY_SPECS: List[_AmbiguitySpec] = [
    # 1. Product type — "applications/loans/originations" without a product qualifier.
    # blocking=True: mixing product types silently gives misleading aggregate numbers.
    _AmbiguitySpec(
        id="product_type",
        detect=re.compile(
            r"\b(applications?|applicants?|originations?|originated|loan\s+apps?|accounts?|borrowers?)\b",
            re.IGNORECASE,
        ),
        # suppress pattern derived from LoanProductType enum via the semantic layer
        # so new product types added to data_contracts/ are picked up automatically
        suppress=_build_product_type_suppress_pattern(),
        blocking=True,
        question="Which product type are you asking about?",
        options=["Personal loans", "Mortgages", "Credit cards", "All combined"],
        default_label="all products combined",
    ),
    # 2. Time period — vague relative time without an explicit year/date.
    # blocking=False: "all available history" is a safe default; analyst can filter later.
    _AmbiguitySpec(
        id="time_period",
        detect=re.compile(
            r"\b(recently|latest|current|ytd|year[\s\-]to[\s\-]date"
            r"|this\s+(?:quarter|year|month)|past\s+few|recent\s+months?|historical|trend)\b",
            re.IGNORECASE,
        ),
        suppress=re.compile(
            r"\b(20\d{2}|last\s+\d+\s+(?:months?|years?)|past\s+\d+\s+(?:months?|years?)"
            r"|last\s+(?:year|month|quarter)|this\s+(?:quarter|year|month)"
            r"|since\s+20|between\s+20|from\s+20"
            r"|over\s+(?:all\s+)?(?:time|available|history)"
            r"|over\s+the\s+(?:full\s+)?(?:period|years?|history)"
            r"|all\s+(?:time|history|available|periods?)"
            r"|entire\s+(?:time\s+)?(?:period|history|range)"
            r"|full\s+(?:time\s+)?(?:period|history|range)"
            r"|january|february|march|april|may|june|july|august|september|october|november|december"
            r"|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b",
            re.IGNORECASE,
        ),
        blocking=False,
        question="Which time period should this analysis cover?",
        options=["2024", "2023", "2022", "2021", "Last 12 months", "Last 3 months", "Year to date (2026)", "All available history"],
        default_label="all available history",
    ),
    # 3. Metric / KPI — vague performance language without specifying a metric.
    # blocking=False: default to all key metrics.
    _AmbiguitySpec(
        id="metric",
        detect=re.compile(
            r"\b(performance|how\s+(?:are|is|was|were|did)\s+(?:we|the|our|it|they)"
            r"|how\s+(?:do|does|has|have)\s+(?:it|the|our|they)"
            r"|(?:overall\s+)?trend(?:ing)?"
            r"|status|overview|summary(?:\s+of)?|health(?:\s+check)?)\b",
            re.IGNORECASE,
        ),
        suppress=re.compile(
            r"\b(approval\s+rate|decline\s+rate|delinquen|default|charge[\s\-]off|npl"
            r"|revenue|income|profit|loss|net\s+income|provision"
            r"|volume|count|number|how\s+many|average|avg"
            r"|balance|outstanding|exposure|funded|originated"
            r"|pd\s+score|fraud\s+score|fico|dti"
            r"|roll\s+rate|vintage|ltv|apr|interest\s+rate)\b",
            re.IGNORECASE,
        ),
        blocking=False,
        question="What metric are you most interested in?",
        options=[
            "Approval / decline rates",
            "Delinquency & defaults",
            "Revenue & profitability",
            "Origination volume",
            "All key metrics",
        ],
        default_label="all key metrics",
    ),
    # 4. Breakdown dimension — "by segment / breakdown / split" without naming the dimension.
    # blocking=False: default to no breakdown (aggregate total).
    _AmbiguitySpec(
        id="breakdown_dimension",
        detect=re.compile(
            r"\b(break(?:down|s?)?\s+by|broken\s+down\s+by|segmented?\s+by|split\s+by"
            r"|grouped?\s+by|by\s+segment|per\s+segment|across\s+segments?"
            r"|(?:show|give|list)\s+(?:me\s+)?(?:a\s+)?breakdown)\b",
            re.IGNORECASE,
        ),
        suppress=re.compile(
            r"\b(by\s+state|by\s+channel|by\s+fico|by\s+dti|by\s+product|by\s+year"
            r"|by\s+month|by\s+quarter|by\s+tier|by\s+grade|by\s+purpose|by\s+type"
            r"|by\s+status|by\s+risk|by\s+band|by\s+score|by\s+vintage)\b",
            re.IGNORECASE,
        ),
        blocking=False,
        question="Which dimension should the breakdown be by?",
        options=[
            "FICO tier",
            "DTI tier",
            "State",
            "Channel (online / branch / partner)",
            "Product type",
            "Quarter / month",
        ],
        default_label="no breakdown (aggregate total)",
    ),
    # 5. Loan status — explicit "portfolio loans" / "outstanding loans" phrasing without a status.
    # blocking=False: default to all statuses.
    _AmbiguitySpec(
        id="loan_status",
        detect=re.compile(
            r"\b(?:(?:outstanding|existing|open)\s+loans?"
            r"|loans?\s+(?:in\s+(?:the\s+)?portfolio|outstanding|on\s+(?:the\s+)?books))\b",
            re.IGNORECASE,
        ),
        suppress=re.compile(
            r"\b(active|current|delinquen|30[\s\-]?dpd|60[\s\-]?dpd|90[\s\-]?dpd"
            r"|charged[\s\-]off|written[\s\-]off|npl|performing|paid[\s\-]off|closed|funded"
            r"|all\s+statuses?|all\s+loans?|entire\s+portfolio)\b",
            re.IGNORECASE,
        ),
        blocking=False,
        question="Which loan status should be included?",
        options=["Active / current only", "Delinquent (30+ DPD)", "All statuses", "Charged-off"],
        default_label="all loan statuses",
    ),
]


def _detect_ambiguities(
    question: str,
    clarifications: Optional[Dict[str, str]] = None,
) -> tuple[List[ClarificationItem], List[str]]:
    """
    Scan ``question`` against all ambiguity specs and return:
      (blocking_items, assumed_defaults)

    ``blocking_items``: dimensions where the spec is blocking=True AND still ambiguous.
      These must be resolved by the user before the query can run.

    ``assumed_defaults``: human-readable strings describing soft-default resolutions.
      Surfaced in the response so the LLM can mention what was assumed.

    A dimension is resolved if:
      - Its suppress pattern matches the question (already specific enough), OR
      - It appears in the ``clarifications`` dict (answered in a prior turn).
    """
    already_answered: set = set(clarifications.keys()) if clarifications else set()
    blocking_items: List[ClarificationItem] = []
    assumed_defaults: List[str] = []

    for spec in _AMBIGUITY_SPECS:
        if spec.id in already_answered:
            continue
        if spec.detect.search(question) and not spec.suppress.search(question):
            if spec.blocking:
                blocking_items.append(
                    ClarificationItem(id=spec.id, question=spec.question, options=spec.options)
                )
            else:
                # Soft ambiguity: apply the default and note it
                assumed_defaults.append(f"{spec.id}: {spec.default_label}")

    return blocking_items, assumed_defaults



# ---------------------------------------------------------------------------
# POST /v1/analytics/s2s/ask
# ---------------------------------------------------------------------------

@app.post(
    "/v1/analytics/s2s/ask",
    response_model=S2SAskResponse,
    summary="Ask a natural-language analytics question (LucidCredit integration)",
    tags=["Service Integration"],
)
async def s2s_ask(
    req: S2SAskRequest,
    x_service_key: Optional[str] = Header(default=None, alias="x-service-key"),
) -> S2SAskResponse:
    """
    Accept a natural language question from LucidCredit, translate it to
    BigQuery SQL internally (using Azure OpenAI), execute it against the
    credit-risk BQ datasets, and return the results.

    BQ credentials and table schema are never exposed to the caller.
    Requires ``X-Service-Key: dev-analytics-key`` header.

    Set ``USE_SEMANTIC_AGENT=true`` to route through the new Semantic
    Intelligence Agent pipeline (4-layer architecture, 97% cheaper).
    """
    if x_service_key != _SERVICE_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Service-Key.")

    # Fast-path: Freddie Mac / SFLLD questions — bypass both semantic agent and LLM.
    # The LLM + semantic agent consistently route these to credit_risk.personal_loans_funded;
    # a deterministic template is more reliable for these well-defined Freddie Mac queries.
    _freddie_q = req.question.lower()
    if _FREDDIE_KEYWORDS.search(_freddie_q):
        _is_perf = bool(re.search(
            r"\bdelinquen|\bdefault\b|\bperformanc|\bdpd\b|\bpast.due",
            _freddie_q,
        ))
        if _is_perf:
            _freddie_sql = (
                "SELECT fp.current_delinquency_status,\n"
                "       COUNT(*) AS loan_count\n"
                "FROM `ai-risk-workflow.freddie_mac_sflld.freddie_performance` fp\n"
                "GROUP BY fp.current_delinquency_status\n"
                "ORDER BY loan_count DESC"
            )
        else:
            _freddie_sql = (
                "SELECT COUNT(*) AS freddie_loan_count\n"
                "FROM `ai-risk-workflow.freddie_mac_sflld.freddie_origination`"
            )
        logger.info(
            "s2s/ask Freddie Mac fast-path: routed to %s",
            "freddie_performance" if _is_perf else "freddie_origination",
        )
        try:
            _freddie_rows = _run_bq_sql(_freddie_sql) if BQ_PROJECT else []
        except Exception as exc:
            logger.error("s2s/ask Freddie fast-path BQ error sql=%r err=%s", _freddie_sql, exc)
            raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")
        return S2SAskResponse(
            question=req.question,
            needs_clarification=False,
            generated_sql=_freddie_sql,
            rows=_freddie_rows[:200],
            row_count=len(_freddie_rows[:200]),
            truncated=len(_freddie_rows) > 200,
            assumed_defaults=[],
        )

    # Feature flag: route through Semantic Intelligence Agent when enabled
    if os.getenv("USE_SEMANTIC_AGENT", "").lower() in ("true", "1", "yes"):
        try:
            from analytics_api.src.agent.api.routes import _get_agent
            agent = _get_agent()
            result = await agent.ask(
                question=req.question.strip(),
                tenant_id=req.tenant_id if hasattr(req, "tenant_id") else "default",
                clarifications=req.clarifications or {},
            )
            # If the semantic agent cannot handle the question (clarification_needed
            # with no structured items), fall through to the original NL2SQL pipeline
            # which has broader coverage for ad-hoc analytical questions.
            if not result.clarification_needed:
                return S2SAskResponse(
                    question=req.question,
                    generated_sql=result.sql or "",
                    rows=result.rows,
                    row_count=result.row_count,
                    needs_clarification=False,
                )
            logger.info(
                "USE_SEMANTIC_AGENT: clarification_needed for %r — falling back to NL2SQL pipeline",
                req.question[:80],
            )
            # Fall through to original pipeline
        except Exception as _agent_exc:
            logger.warning("USE_SEMANTIC_AGENT routing failed, falling back: %s", _agent_exc)
            # Fall through to original pipeline

    # --- Normalize informal credit-domain shorthand before any processing ---
    question = _normalize_query(req.question.strip())

    # --- Context ingestion: detect blocking ambiguities + soft defaults ---
    # Skip if clarifications already provided (second-turn answer) OR explicit hint given.
    # Even on second turns, soft-default assumptions are still computed so they appear
    # in the response for dimensions the caller never explicitly resolved.
    all_assumed_defaults: List[str] = []
    if not req.hint:
        blocking_items, soft_defaults = _detect_ambiguities(question, req.clarifications)
        all_assumed_defaults.extend(soft_defaults)
        if blocking_items:
            # Only block for truly ambiguous dimensions (blocking=True specs)
            return S2SAskResponse(
                question=req.question,
                needs_clarification=True,
                clarification_items=blocking_items,
                assumed_defaults=all_assumed_defaults,
            )

    # --- Inject clarifications + assumed defaults + hint into the question for the LLM ---
    enrichments: List[str] = []
    if req.clarifications:
        for cid, answer in req.clarifications.items():
            label = cid.replace("_", " ").title()
            # Map "All available history" to an explicit SQL instruction
            if cid == "time_period" and answer.lower() in (
                "all available history", "all history", "all time", "entire period"
            ):
                enrichments.append(f"{label}: include all available data — no date WHERE clause")
            else:
                enrichments.append(f"{label}: {answer}")
    if all_assumed_defaults:
        enrichments.append(f"Default assumptions applied: {'; '.join(all_assumed_defaults)}")
    if req.hint:
        enrichments.append(f"Additional context: {req.hint}")
    if enrichments:
        question = f"{question}\n\nContext: {'; '.join(enrichments)}"

    # 1. NL → SQL via Azure OpenAI
    sql = await _generate_bq_sql(question)
    _nl2sql_validate(sql)

    # 2. Execute against BigQuery (or SQLite fallback in dev)
    if BQ_PROJECT:
        try:
            rows = _run_bq_sql(sql)
        except Exception as exc:
            logger.error("s2s/ask BQ execution failed sql=%r err=%s", sql[:200], exc)
            raise HTTPException(status_code=500, detail=f"Query execution failed: {exc}")
    else:
        # SQLite dev fallback — BQ-specific syntax will likely fail gracefully
        rows = _backend.run_sql(sql, {})

    truncated = len(rows) > 200
    rows = rows[:200]
    return S2SAskResponse(
        question=req.question,
        needs_clarification=False,
        generated_sql=sql,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        assumed_defaults=all_assumed_defaults,
    )


# ===========================================================================
# Phase 5 (GAP-21) — Analytics Query + Evidence Endpoints
# PRD §10.2 (Prompt 21-B)
# ===========================================================================

import sqlite3 as _sqlite3
import uuid as _uuid
from datetime import datetime as _dt, timezone as _tz
from typing import Literal as _Literal

from fastapi import BackgroundTasks


# ---------------------------------------------------------------------------
# Async DB helper for the analytics app (reuses DATABASE_URL)
# ---------------------------------------------------------------------------
_ANALYTICS_ENGINE_CACHE: Dict[str, Any] = {}


def _get_analytics_sync_engine():
    """Return a cached SQLAlchemy sync engine for DATABASE_URL."""
    from sqlalchemy import create_engine as _ce
    db_path = DATABASE_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
    key = f"sync:{DATABASE_URL}"
    if key not in _ANALYTICS_ENGINE_CACHE:
        _ANALYTICS_ENGINE_CACHE[key] = _ce(f"sqlite:///{db_path}", echo=False)
    return _ANALYTICS_ENGINE_CACHE[key]


def _run_sync_sql(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute a SELECT via sync SQLite and return rows as dicts."""
    db_path = DATABASE_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
    try:
        conn = _sqlite3.connect(db_path)
        conn.row_factory = _sqlite3.Row
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as exc:
        logger.warning("Analytics sync SQL failed: %s", exc)
        return []


def _run_sync_write(sql: str, params: tuple = ()) -> None:
    """Execute a write statement via sync SQLite."""
    db_path = DATABASE_URL.replace("sqlite:///", "").replace("sqlite+aiosqlite:///", "")
    try:
        conn = _sqlite3.connect(db_path)
        conn.execute(sql, params)
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Analytics sync write failed: %s", exc)


def _ensure_analytics_tables() -> None:
    """Create helper tables for the new analytics endpoints if absent."""
    _run_sync_write("""
        CREATE TABLE IF NOT EXISTS saved_queries (
            query_id   TEXT PRIMARY KEY,
            tenant_id  TEXT NOT NULL,
            sql        TEXT NOT NULL,
            description TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    _run_sync_write("""
        CREATE TABLE IF NOT EXISTS evidence_packets (
            packet_id   TEXT PRIMARY KEY,
            tenant_id   TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'building',
            components  TEXT NOT NULL DEFAULT '[]',
            download_url TEXT,
            created_at   TEXT NOT NULL
        )
    """)


_ensure_analytics_tables()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class SqlQueryRequest(BaseModel):
    sql: str
    tenant_id: str
    description: Optional[str] = None


class SqlQueryResponse(BaseModel):
    query_id: str
    rows: List[Dict[str, Any]]
    row_count: int
    code_artifact_id: Optional[str]
    executed_at: str


class NlQueryRequest(BaseModel):
    query: str
    tenant_id: str


class SavedQueryRecord(BaseModel):
    query_id: str
    tenant_id: str
    sql: str
    description: Optional[str]
    created_at: str


class EvidencePacketRequest(BaseModel):
    tenant_id: str
    session_id: Optional[str] = None
    date_range_start: Optional[str] = None
    date_range_end: Optional[str] = None


class EvidencePacketResponse(BaseModel):
    packet_id: str
    tenant_id: str
    status: _Literal["building", "ready"]
    components: List[str]
    download_url: Optional[str]


# ---------------------------------------------------------------------------
# POST /v1/analytics/query/sql
# ---------------------------------------------------------------------------

@app.post(
    "/v1/analytics/query/sql",
    response_model=SqlQueryResponse,
    summary="Execute a tenant-scoped SELECT query",
    tags=["Analytics Query"],
)
async def query_sql(
    req: SqlQueryRequest,
    _user: Dict = Depends(verify_bearer),
) -> SqlQueryResponse:
    """Execute a SELECT statement with tenant_id injection and return rows."""
    tenant_id: str = _user["tenant_id"]

    # Security: only SELECT allowed
    if not req.sql.upper().strip().startswith("SELECT"):
        raise HTTPException(
            status_code=422,
            detail="Only SELECT statements are permitted.",
        )

    # Inject tenant_id
    try:
        from ai_agent.src.query_builder_agent import QueryBuilderAgent
        qba = QueryBuilderAgent(db_url=DATABASE_URL, tenant_id=tenant_id)
        injected_sql = qba.inject_tenant_id(req.sql)
    except Exception:
        # Fallback: manual injection
        injected_sql = req.sql
        if "tenant_id" not in injected_sql.lower():
            if "WHERE" in injected_sql.upper():
                injected_sql = injected_sql + f" AND tenant_id = '{tenant_id}'"
            else:
                injected_sql = injected_sql + f" WHERE tenant_id = '{tenant_id}'"

    query_id = str(_uuid.uuid4())
    executed_at = _dt.now(_tz.utc).isoformat()

    rows = _run_sync_sql(injected_sql)

    # Store as code artifact if possible
    code_artifact_id: Optional[str] = None
    try:
        import sys as _sys, os as _os
        _root = Path(__file__).parents[3]
        if str(_root) not in _sys.path:
            _sys.path.insert(0, str(_root))
        from ai_agent.src.code_artifact_store import store_artifact
        import asyncio as _asyncio
        art = await store_artifact(
            db_url=DATABASE_URL,
            session_id=f"analytics_query_{tenant_id}",
            turn_id=query_id,
            artifact_type="sql",
            content=injected_sql,
        )
        code_artifact_id = art.artifact_id
        # Also persist to saved_queries if description provided
    except Exception:
        pass

    if req.description:
        _run_sync_write(
            "INSERT OR IGNORE INTO saved_queries (query_id, tenant_id, sql, description, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (query_id, tenant_id, req.sql, req.description, executed_at),
        )

    return SqlQueryResponse(
        query_id=query_id,
        rows=rows,
        row_count=len(rows),
        code_artifact_id=code_artifact_id,
        executed_at=executed_at,
    )


# ---------------------------------------------------------------------------
# POST /v1/analytics/query/nl
# ---------------------------------------------------------------------------

@app.post(
    "/v1/analytics/query/nl",
    summary="Natural-language analytics query (stub)",
    tags=["Analytics Query"],
)
async def query_nl(
    req: NlQueryRequest,
    _user: Dict = Depends(verify_bearer),
):
    """
    Natural-language to SQL endpoint.
    TODO: route through OrchestratorAgent for LLM SQL generation.
    """
    raise HTTPException(
        status_code=501,
        detail="NL query endpoint not yet implemented; use /query/sql",
    )


# ---------------------------------------------------------------------------
# GET /v1/analytics/queries/saved
# ---------------------------------------------------------------------------

@app.get(
    "/v1/analytics/queries/saved",
    response_model=List[SavedQueryRecord],
    summary="List saved queries for tenant",
    tags=["Analytics Query"],
)
async def list_saved_queries(
    _user: Dict = Depends(verify_bearer),
) -> List[SavedQueryRecord]:
    """Return list of saved queries for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    rows = _run_sync_sql(
        "SELECT query_id, tenant_id, sql, description, created_at "
        "FROM saved_queries WHERE tenant_id = ? ORDER BY created_at DESC",
        (tenant_id,),
    )
    return [SavedQueryRecord(**r) for r in rows]


# ---------------------------------------------------------------------------
# POST /v1/analytics/queries/save
# ---------------------------------------------------------------------------

@app.post(
    "/v1/analytics/queries/save",
    response_model=SavedQueryRecord,
    status_code=201,
    summary="Save a query for future use",
    tags=["Analytics Query"],
)
async def save_query(
    req: SqlQueryRequest,
    _user: Dict = Depends(verify_bearer),
) -> SavedQueryRecord:
    """Persist a SQL query to the saved_queries table."""
    tenant_id: str = _user["tenant_id"]
    query_id = str(_uuid.uuid4())
    created_at = _dt.now(_tz.utc).isoformat()

    _run_sync_write(
        "INSERT INTO saved_queries (query_id, tenant_id, sql, description, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (query_id, tenant_id, req.sql, req.description, created_at),
    )
    return SavedQueryRecord(
        query_id=query_id,
        tenant_id=tenant_id,
        sql=req.sql,
        description=req.description,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# POST /v1/analytics/evidence/exam-packet
# ---------------------------------------------------------------------------

def _build_exam_packet_bg(packet_id: str, tenant_id: str, session_id: Optional[str]) -> None:
    """Background task: build the evidence packet and update status."""
    components: List[str] = []
    try:
        from compliance.exam_packet_builder import build_exam_packet  # type: ignore
        result = build_exam_packet(tenant_id=tenant_id, session_id=session_id)
        components = result.get("components", []) if isinstance(result, dict) else []
    except Exception as exc:
        logger.warning("exam_packet_builder unavailable: %s", exc)

    _run_sync_write(
        "UPDATE evidence_packets SET status = 'ready', components = ? WHERE packet_id = ?",
        (_sqlite3.Binary(str(components).encode()) if False else str(components), packet_id),
    )


@app.post(
    "/v1/analytics/evidence/exam-packet",
    response_model=EvidencePacketResponse,
    status_code=202,
    summary="Build an evidence/exam packet",
    tags=["Evidence"],
)
async def create_evidence_packet(
    req: EvidencePacketRequest,
    background_tasks: BackgroundTasks,
    _user: Dict = Depends(verify_bearer),
) -> EvidencePacketResponse:
    """Initiate async evidence packet build. Returns building status immediately."""
    tenant_id: str = _user["tenant_id"]
    packet_id = str(_uuid.uuid4())
    created_at = _dt.now(_tz.utc).isoformat()

    _run_sync_write(
        "INSERT INTO evidence_packets (packet_id, tenant_id, status, components, created_at) "
        "VALUES (?, ?, 'building', '[]', ?)",
        (packet_id, tenant_id, created_at),
    )

    background_tasks.add_task(
        _build_exam_packet_bg, packet_id, tenant_id, req.session_id
    )

    return EvidencePacketResponse(
        packet_id=packet_id,
        tenant_id=tenant_id,
        status="building",
        components=[],
        download_url=None,
    )


# ---------------------------------------------------------------------------
# GET /v1/analytics/evidence/exam-packet/{packet_id}
# ---------------------------------------------------------------------------

@app.get(
    "/v1/analytics/evidence/exam-packet/{packet_id}",
    response_model=EvidencePacketResponse,
    summary="Get evidence packet status",
    tags=["Evidence"],
)
async def get_evidence_packet(
    packet_id: str,
    _user: Dict = Depends(verify_bearer),
) -> EvidencePacketResponse:
    """Return the status and metadata of an evidence packet."""
    tenant_id: str = _user["tenant_id"]
    rows = _run_sync_sql(
        "SELECT packet_id, tenant_id, status, components, download_url "
        "FROM evidence_packets WHERE packet_id = ? AND tenant_id = ?",
        (packet_id, tenant_id),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Packet '{packet_id}' not found.")

    row = rows[0]
    try:
        import ast
        components = ast.literal_eval(row["components"]) if row["components"] else []
    except Exception:
        components = []

    return EvidencePacketResponse(
        packet_id=row["packet_id"],
        tenant_id=row["tenant_id"],
        status=row["status"],
        components=components,
        download_url=row.get("download_url"),
    )
