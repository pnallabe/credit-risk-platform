"""Feature store writer — persists computed features to PostgreSQL.

Public API
----------
>>> import asyncio
>>> from feature_pipeline.feature_store import write_features
>>> result = asyncio.run(
...     write_features(df_with_features, config, db_url="postgresql+asyncpg://...")
... )
>>> print(result)  # {"rows_written": 1000, "duration_seconds": 0.42, "feature_version": "1.0.0"}
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from feature_pipeline.features import FeaturePipelineConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNK_SIZE = 1_000

# Columns written to the `features` table.  Must match db/schema.sql.
_FEATURE_COLUMNS = [
    "credit_utilization",
    "income_stability_score",
    "repayment_capacity",
    "debt_service_coverage",   # stored as debt_service_coverage_ratio in DB
    "credit_age_months",       # mapped from credit_age_score * 10 (nullable int)
    "payment_history_score",   # derived from months_since_delinquency
    "feature_json",            # remaining engineered features as JSONB
]

# Features stored in the dedicated scalar columns; the rest go into feature_json.
_SCALAR_FEATURE_MAP: Dict[str, str] = {
    "credit_utilization": "credit_utilization",
    "income_stability_score": "income_stability_score",
    "repayment_capacity": "repayment_capacity",
    "debt_service_coverage": "debt_service_coverage_ratio",
}

_ADDITIONAL_FEATURES = [
    "credit_age_score",
    "derogatory_penalty",
    "months_since_delinquency",
    "log_loan_amount",
    "log_annual_income",
    "dti_x_loan_amount",
    "employment_encoded",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_row(row: pd.Series, version: str) -> Dict[str, Any]:
    """Convert a single DataFrame row into an insert-ready dict."""
    feature_json = {col: row[col] for col in _ADDITIONAL_FEATURES if col in row.index}

    return {
        "application_id": row["application_id"],
        "feature_set_version": version,
        "credit_utilization": float(row.get("credit_utilization", 0.0)),
        "income_stability_score": float(row.get("income_stability_score", 0.0)),
        "repayment_capacity": float(row.get("repayment_capacity", 0.0)),
        "debt_service_coverage_ratio": float(row.get("debt_service_coverage", 0.0)),
        "credit_age_months": None,  # not used in v1; populated from feature_json
        "payment_history_score": None,  # populated from feature_json
        "feature_json": feature_json,
    }


def _build_upsert_sql(dialect: str) -> str:
    """Return the upsert SQL for the target dialect."""
    if dialect == "sqlite":
        # SQLite does not support ON CONFLICT DO UPDATE with named columns
        # in the same way — use INSERT OR REPLACE.
        return """
            INSERT OR REPLACE INTO features
                (application_id, feature_set_version, computed_at,
                 credit_utilization, income_stability_score, repayment_capacity,
                 debt_service_coverage_ratio, credit_age_months,
                 payment_history_score, feature_json)
            VALUES
                (:application_id, :feature_set_version, CURRENT_TIMESTAMP,
                 :credit_utilization, :income_stability_score, :repayment_capacity,
                 :debt_service_coverage_ratio, :credit_age_months,
                 :payment_history_score, :feature_json)
        """
    return """
        INSERT INTO features
            (application_id, feature_set_version, computed_at,
             credit_utilization, income_stability_score, repayment_capacity,
             debt_service_coverage_ratio, credit_age_months,
             payment_history_score, feature_json)
        VALUES
            (:application_id, :feature_set_version, now(),
             :credit_utilization, :income_stability_score, :repayment_capacity,
             :debt_service_coverage_ratio, :credit_age_months,
             :payment_history_score, CAST(:feature_json AS jsonb))
        ON CONFLICT (application_id, feature_set_version) DO UPDATE SET
            computed_at               = EXCLUDED.computed_at,
            credit_utilization        = EXCLUDED.credit_utilization,
            income_stability_score    = EXCLUDED.income_stability_score,
            repayment_capacity        = EXCLUDED.repayment_capacity,
            debt_service_coverage_ratio = EXCLUDED.debt_service_coverage_ratio,
            credit_age_months         = EXCLUDED.credit_age_months,
            payment_history_score     = EXCLUDED.payment_history_score,
            feature_json              = EXCLUDED.feature_json
    """


def _df_to_rows(df: pd.DataFrame, version: str) -> List[Dict[str, Any]]:
    """Convert a DataFrame to a list of insert dicts."""
    return [_build_row(row, version) for _, row in df.iterrows()]


# ---------------------------------------------------------------------------
# SQLite compatibility shim (feature_json as plain JSON text)
# ---------------------------------------------------------------------------


def _serialize_feature_json(rows: List[Dict[str, Any]], dialect: str) -> List[Dict[str, Any]]:
    """For SQLite we serialise feature_json dicts to a JSON string."""
    if dialect != "sqlite":
        return rows
    import json  # noqa: PLC0415

    return [
        {**r, "feature_json": json.dumps(r["feature_json"])} for r in rows
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def write_features(
    df: pd.DataFrame,
    config: FeaturePipelineConfig,
    db_url: str,
    engine: AsyncEngine | None = None,
) -> Dict[str, Any]:
    """Persist computed features to the ``features`` PostgreSQL table.

    Parameters
    ----------
    df:
        DataFrame that is the output of
        ``feature_pipeline.features.compute_features()``.
        Must include ``application_id`` and all engineered feature columns.
    config:
        The ``FeaturePipelineConfig`` used to compute the features.
        Its ``version`` string is stored as ``feature_set_version``.
    db_url:
        SQLAlchemy async connection URL.  For PostgreSQL use
        ``postgresql+asyncpg://...``; for in-memory CI use
        ``sqlite+aiosqlite:///:memory:``
    engine:
        Optional pre-constructed ``AsyncEngine``.  If provided, *db_url*
        is ignored.  Useful for injecting a test engine.

    Returns
    -------
    dict with keys:
        rows_written     (int)
        duration_seconds (float)
        feature_version  (str)
    """
    if engine is None:
        engine = create_async_engine(db_url, echo=False)
        _owned = True
    else:
        _owned = False

    # Detect dialect for SQL branching
    dialect_name = engine.dialect.name  # "postgresql" | "sqlite"

    rows = _df_to_rows(df, config.version)
    rows = _serialize_feature_json(rows, dialect_name)

    upsert_sql = _build_upsert_sql(dialect_name)

    start = time.perf_counter()
    rows_written = 0

    async with engine.begin() as conn:
        for i in range(0, len(rows), CHUNK_SIZE):
            chunk = rows[i : i + CHUNK_SIZE]
            await conn.execute(text(upsert_sql), chunk)
            rows_written += len(chunk)
            logger.debug("Wrote chunk %d–%d", i, i + len(chunk))

    elapsed = time.perf_counter() - start

    if _owned:
        await engine.dispose()

    result = {
        "rows_written": rows_written,
        "duration_seconds": round(elapsed, 4),
        "feature_version": config.version,
    }
    logger.info(
        "write_features complete: %d rows in %.3fs (version=%s)",
        rows_written,
        elapsed,
        config.version,
    )
    return result
