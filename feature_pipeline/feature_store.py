"""Feature store writer — persists computed features to PostgreSQL.

Public API
----------
>>> import asyncio
>>> from datetime import date, datetime, timezone
>>> from feature_pipeline.feature_store import write_features, read_features_as_of
>>> result = asyncio.run(
...     write_features(
...         df_with_features, config, db_url="postgresql+asyncpg://...",
...         event_timestamp=datetime.now(timezone.utc), as_of_date=date.today()
...     )
... )
>>> print(result)  # {"rows_written": 1000, "duration_seconds": 0.42, "feature_version": "1.0.0"}

Point-in-time correctness
--------------------------
Every feature row is stamped with:
  - ``event_timestamp``: wall-clock UTC moment the features were computed.
  - ``as_of_date``: the business date the features represent (the "as-of" date
    that must be used when querying for backtesting — prevents look-ahead bias).

Use ``read_features_as_of(application_ids, as_of_date, version, engine)`` to
retrieve features keyed to a historical date. The function returns the latest
row WHERE as_of_date <= requested_date, so future feature values are never
returned for a historical query.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from feature_pipeline.features import FeaturePipelineConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit proof dataclass
# ---------------------------------------------------------------------------

@dataclass
class FeatureStoreAuditProof:
    """Immutable record of every feature read — enables look-ahead bias detection.

    Written to the ``feature_read_audit`` table on every ``read_features_as_of``
    call.  The ``feature_hash`` is sha256(sorted JSON of all returned feature
    values) — deterministic across identical reads.
    """
    application_id: str
    feature_set_version: str
    as_of_date: date
    event_timestamp: datetime
    feature_hash: str


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


def _build_row(row: Dict[str, Any], version: str, event_timestamp: datetime, as_of_date: date) -> Dict[str, Any]:
    """Convert a single DataFrame row (plain dict) into an insert-ready dict."""
    feature_json = {col: row[col] for col in _ADDITIONAL_FEATURES if col in row}

    return {
        "application_id": row["application_id"],
        "feature_set_version": version,
        "event_timestamp": event_timestamp.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "credit_utilization": float(row.get("credit_utilization", 0.0)),
        "income_stability_score": float(row.get("income_stability_score", 0.0)),
        "repayment_capacity": float(row.get("repayment_capacity", 0.0)),
        "debt_service_coverage_ratio": float(row.get("debt_service_coverage", 0.0)),
        "credit_age_months": None,  # not used in v1; populated from feature_json
        "payment_history_score": None,  # populated from feature_json
        "feature_json": feature_json,
    }


def _build_upsert_sql(dialect: str) -> str:
    """Return the upsert SQL for the target dialect.

    Conflict key is (application_id, feature_set_version, as_of_date) so that
    different business-date snapshots for the same application co-exist.
    This is the foundation of point-in-time correctness.
    """
    if dialect == "sqlite":
        return """
            INSERT OR REPLACE INTO features
                (application_id, feature_set_version, event_timestamp, as_of_date,
                 computed_at, credit_utilization, income_stability_score,
                 repayment_capacity, debt_service_coverage_ratio, credit_age_months,
                 payment_history_score, feature_json)
            VALUES
                (:application_id, :feature_set_version, :event_timestamp, :as_of_date,
                 CURRENT_TIMESTAMP, :credit_utilization, :income_stability_score,
                 :repayment_capacity, :debt_service_coverage_ratio, :credit_age_months,
                 :payment_history_score, :feature_json)
        """
    return """
        INSERT INTO features
            (application_id, feature_set_version, event_timestamp, as_of_date,
             computed_at, credit_utilization, income_stability_score, repayment_capacity,
             debt_service_coverage_ratio, credit_age_months,
             payment_history_score, feature_json)
        VALUES
            (:application_id, :feature_set_version, :event_timestamp ::timestamptz,
             :as_of_date ::date, now(),
             :credit_utilization, :income_stability_score, :repayment_capacity,
             :debt_service_coverage_ratio, :credit_age_months,
             :payment_history_score, CAST(:feature_json AS jsonb))
        ON CONFLICT (application_id, feature_set_version, as_of_date) DO UPDATE SET
            event_timestamp             = EXCLUDED.event_timestamp,
            computed_at                 = EXCLUDED.computed_at,
            credit_utilization          = EXCLUDED.credit_utilization,
            income_stability_score      = EXCLUDED.income_stability_score,
            repayment_capacity          = EXCLUDED.repayment_capacity,
            debt_service_coverage_ratio = EXCLUDED.debt_service_coverage_ratio,
            credit_age_months           = EXCLUDED.credit_age_months,
            payment_history_score       = EXCLUDED.payment_history_score,
            feature_json                = EXCLUDED.feature_json
    """


def _df_to_rows(df: pd.DataFrame, version: str, event_timestamp: datetime, as_of_date: date) -> List[Dict[str, Any]]:
    """Convert a DataFrame to a list of insert dicts.

    Uses ``df.to_dict("records")`` for a single-pass O(n) conversion — 10–50×
    faster than ``iterrows()`` because it avoids per-row Python object boxing.
    """
    return [_build_row(row, version, event_timestamp, as_of_date) for row in df.to_dict("records")]


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
    event_timestamp: datetime,
    as_of_date: date,
    engine: AsyncEngine | None = None,
    lineage_client: "LineageClient | None" = None,
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
    event_timestamp:
        UTC wall-clock moment the features were computed.  Required for
        point-in-time auditability.  Must be timezone-aware.
    as_of_date:
        The business date these features represent.  Backtesting queries use
        this date to prevent look-ahead bias — ``read_features_as_of`` will
        never return a row whose ``as_of_date`` exceeds the requested date.
    engine:
        Optional pre-constructed ``AsyncEngine``.  If provided, *db_url*
        is ignored.  Useful for injecting a test engine.

    Returns
    -------
    dict with keys:
        rows_written     (int)
        duration_seconds (float)
        feature_version  (str)
        as_of_date       (str — ISO format)
    """
    if engine is None:
        engine = create_async_engine(db_url, echo=False)
        _owned = True
    else:
        _owned = False

    # Detect dialect for SQL branching
    dialect_name = engine.dialect.name  # "postgresql" | "sqlite"

    rows_raw = _df_to_rows(df, config.version, event_timestamp, as_of_date)
    rows = _serialize_feature_json(rows_raw, dialect_name)

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

    # Optional: emit OpenLineage COMPLETE event (best-effort).
    if lineage_client is not None:
        try:
            from feature_pipeline.lineage import feature_store_dataset

            dataset_hash = _compute_dataset_hash(rows_raw)
            lineage_client.emit_dataset_event(
                run_id=lineage_client.new_run_id(),
                job_name="feature_store.write_features",
                inputs=[],
                outputs=[feature_store_dataset(config.version, as_of_date.isoformat())],
                event_type="COMPLETE",
                run_facets={"rowCount": int(rows_written), "feature_hash": dataset_hash},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lineage emission failed (suppressed): %s", exc)

    if _owned:
        await engine.dispose()

    result = {
        "rows_written": rows_written,
        "duration_seconds": round(elapsed, 4),
        "feature_version": config.version,
        "as_of_date": as_of_date.isoformat(),
    }
    logger.info(
        "write_features complete: %d rows in %.3fs (version=%s, as_of_date=%s)",
        rows_written,
        elapsed,
        config.version,
        as_of_date.isoformat(),
    )
    return result


def _compute_feature_hash(row_dict: Dict[str, Any]) -> str:
    """Deterministic sha256 of feature values (sorted keys, stable JSON)."""
    # Exclude metadata columns; hash only the feature payload
    exclude = {"application_id", "feature_set_version", "event_timestamp",
               "as_of_date", "computed_at", "id"}
    payload = {k: v for k, v in row_dict.items() if k not in exclude}
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _compute_dataset_hash(rows: List[Dict[str, Any]]) -> str:
    """Deterministic sha256 hash for a batch of rows.

    Used for lineage run facets. We hash the per-row feature_hash values,
    sorted by application_id to keep the aggregate deterministic.
    """
    per_row = []
    for r in rows:
        app_id = str(r.get("application_id", ""))
        per_row.append({"application_id": app_id, "feature_hash": _compute_feature_hash(r)})

    per_row_sorted = sorted(per_row, key=lambda x: x["application_id"])
    canonical = json.dumps(per_row_sorted, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def read_features_as_of(
    application_ids: List[str],
    as_of_date: date,
    feature_set_version: str,
    engine: AsyncEngine,
) -> pd.DataFrame:
    """Return feature rows as they existed on or before *as_of_date*.

    For each application_id, returns the single row with the highest
    ``as_of_date`` that is still <= the requested date — preventing
    look-ahead bias in backtesting.

    Also writes one ``FeatureStoreAuditProof`` record per returned row to the
    ``feature_read_audit`` table so that every read is traceable.

    Parameters
    ----------
    application_ids:
        List of application IDs to look up.
    as_of_date:
        Historical reference date.  Only rows with as_of_date <= this value
        are eligible.
    feature_set_version:
        Feature set version string (e.g., ``"1.0.0"``).
    engine:
        Pre-constructed ``AsyncEngine``.

    Returns
    -------
    pd.DataFrame with one row per requested application_id that has a matching
    feature row.  Missing application_ids are silently omitted.
    """
    if not application_ids:
        return pd.DataFrame()

    dialect_name = engine.dialect.name

    # Use a window function to get the latest-as_of_date row per application
    if dialect_name == "sqlite":
        # SQLite window function equivalent via subquery
        select_sql = """
            SELECT f.*
            FROM features f
            INNER JOIN (
                SELECT application_id, MAX(as_of_date) AS max_aod
                FROM features
                WHERE feature_set_version = :version
                  AND as_of_date <= :as_of_date
                  AND application_id IN :app_ids
                GROUP BY application_id
            ) latest
              ON f.application_id = latest.application_id
             AND f.as_of_date = latest.max_aod
             AND f.feature_set_version = :version
        """
    else:
        select_sql = """
            SELECT DISTINCT ON (f.application_id) f.*
            FROM features f
            WHERE f.feature_set_version = :version
              AND f.as_of_date <= :as_of_date
              AND f.application_id = ANY(:app_ids)
            ORDER BY f.application_id, f.as_of_date DESC
        """

    params: Dict[str, Any] = {
        "version": feature_set_version,
        "as_of_date": as_of_date.isoformat(),
    }

    async with engine.begin() as conn:
        if dialect_name == "sqlite":
            params["app_ids"] = tuple(application_ids)
            result = await conn.execute(text(select_sql), params)
        else:
            params["app_ids"] = application_ids
            result = await conn.execute(text(select_sql), params)
        rows = result.mappings().all()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([dict(r) for r in rows])

    # Write audit proof records
    now_utc = datetime.now(timezone.utc)
    audit_rows = []
    for r in rows:
        r_dict = dict(r)
        proof = FeatureStoreAuditProof(
            application_id=str(r_dict["application_id"]),
            feature_set_version=feature_set_version,
            as_of_date=as_of_date,
            event_timestamp=now_utc,
            feature_hash=_compute_feature_hash(r_dict),
        )
        audit_rows.append({
            "application_id": proof.application_id,
            "feature_set_version": proof.feature_set_version,
            "as_of_date": proof.as_of_date.isoformat(),
            "event_timestamp": proof.event_timestamp.isoformat(),
            "feature_hash": proof.feature_hash,
        })

    if audit_rows:
        audit_sql = _build_audit_insert_sql(dialect_name)
        async with engine.begin() as conn:
            await conn.execute(text(audit_sql), audit_rows)

    logger.info(
        "read_features_as_of: returned %d rows (version=%s, as_of=%s)",
        len(df), feature_set_version, as_of_date.isoformat(),
    )
    return df


def _build_audit_insert_sql(dialect: str) -> str:
    """INSERT SQL for the feature_read_audit table."""
    return """
        INSERT INTO feature_read_audit
            (application_id, feature_set_version, as_of_date,
             event_timestamp, feature_hash)
        VALUES
            (:application_id, :feature_set_version, :as_of_date,
             :event_timestamp, :feature_hash)
    """
