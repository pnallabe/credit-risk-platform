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

from fastapi import Depends, FastAPI, HTTPException, Query, Security, status
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
BQ_DATASET = os.getenv("BQ_DATASET", "credit_risk_model_dev")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT}/decision_audit.db")

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
