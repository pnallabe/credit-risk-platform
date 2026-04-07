"""
BigQuery Client — Reusable GCP/BigQuery Wrapper
================================================
Provides a single, authenticated BigQuery client used by all agents
for reading training data, writing scoring results, and serving the
model registry.

Design principles:
  - Single client per process (lazy singleton)
  - Auth via GOOGLE_APPLICATION_CREDENTIALS (service account JSON)
    or Application Default Credentials (Cloud Run / GKE)
  - All read operations return pd.DataFrame
  - All write operations use streaming inserts (< 10 MB) or
    load_table_from_dataframe for larger batches
  - Schema-on-write: tables are auto-created from BigQuerySchema definitions
  - Full retry logic via google-api-core

Environment variables
---------------------
  GCP_PROJECT_ID                 — GCP project
  BQ_DATASET_MODEL_DEV           — dataset for model development tables
                                   (default: credit_risk_model_dev)
  GOOGLE_APPLICATION_CREDENTIALS — path to SA JSON key (optional)
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

try:
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound
    from google.api_core import retry as bq_retry
    _BQ_AVAILABLE = True
except ImportError:
    _BQ_AVAILABLE = False
    logger.warning("google-cloud-bigquery not installed — BigQuery features disabled")


# ---------------------------------------------------------------------------
# Auto-load .env
# ---------------------------------------------------------------------------

_ENV_PATH = Path(__file__).parents[1] / ".env"
if _ENV_PATH.exists():
    with open(_ENV_PATH) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.split("#")[0].strip().strip('"').strip("'")
                os.environ.setdefault(_k.strip(), _v)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_PROJECT = os.environ.get("GCP_PROJECT_ID", "ai-risk-workflow")
DEFAULT_DATASET = os.environ.get("BQ_DATASET_MODEL_DEV", "credit_risk_model_dev")
DEFAULT_LOCATION = os.environ.get("GCP_REGION", "US")
WRITE_APPEND = "WRITE_APPEND"
WRITE_TRUNCATE = "WRITE_TRUNCATE"


# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_bq_client(project: str = DEFAULT_PROJECT) -> Any:
    """Return a cached BigQuery client. Raises if BQ package unavailable."""
    if not _BQ_AVAILABLE:
        raise RuntimeError(
            "google-cloud-bigquery is not installed. "
            "Run: pip install google-cloud-bigquery pyarrow"
        )
    sa_key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if sa_key and os.path.exists(sa_key):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            sa_key,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        client = bigquery.Client(project=project, credentials=creds)
    else:
        # Falls back to Application Default Credentials (Cloud Run / gcloud auth)
        client = bigquery.Client(project=project)
    logger.info("BigQuery client initialised — project=%s", project)
    return client


# ---------------------------------------------------------------------------
# Dataset management
# ---------------------------------------------------------------------------


def ensure_dataset(
    dataset_id: str = DEFAULT_DATASET,
    project: str = DEFAULT_PROJECT,
    location: str = DEFAULT_LOCATION,
) -> None:
    """Create the dataset if it doesn't already exist."""
    if not _BQ_AVAILABLE:
        return
    client = get_bq_client(project)
    full_id = f"{project}.{dataset_id}"
    try:
        client.get_dataset(full_id)
        logger.debug("Dataset %s already exists", full_id)
    except NotFound:
        ds = bigquery.Dataset(full_id)
        ds.location = location
        ds.description = "Credit Risk Platform — model development & scoring outputs"
        client.create_dataset(ds, timeout=30)
        logger.info("Created BigQuery dataset: %s", full_id)


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------


def ensure_table(
    table_id: str,
    schema: List[Any],
    dataset_id: str = DEFAULT_DATASET,
    project: str = DEFAULT_PROJECT,
    partition_field: Optional[str] = None,
    clustering_fields: Optional[List[str]] = None,
    description: str = "",
) -> None:
    """
    Create a BigQuery table from a schema list if it doesn't exist.
    Preserves existing data — never truncates on creation.
    """
    if not _BQ_AVAILABLE:
        return
    client = get_bq_client(project)
    full_id = f"{project}.{dataset_id}.{table_id}"
    try:
        client.get_table(full_id)
        logger.debug("Table %s already exists", full_id)
        return
    except NotFound:
        pass

    table = bigquery.Table(full_id, schema=schema)
    table.description = description

    if partition_field:
        table.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )
    if clustering_fields:
        table.clustering_fields = clustering_fields

    client.create_table(table)
    logger.info("Created BigQuery table: %s", full_id)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def query_to_df(
    sql: str,
    project: str = DEFAULT_PROJECT,
    job_config: Optional[Any] = None,
) -> pd.DataFrame:
    """
    Execute a SQL query and return results as a pandas DataFrame.
    Automatically retries transient errors.
    """
    if not _BQ_AVAILABLE:
        raise RuntimeError("google-cloud-bigquery not available")
    client = get_bq_client(project)
    logger.debug("BQ query: %s…", sql[:120].replace("\n", " "))
    return client.query(sql, job_config=job_config).to_dataframe(
        progress_bar_type=None
    )


def read_table(
    table_id: str,
    dataset_id: str = DEFAULT_DATASET,
    project: str = DEFAULT_PROJECT,
    columns: Optional[List[str]] = None,
    where: Optional[str] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Read a full table (or filtered subset) into a DataFrame.

    ``table_id`` may be either:
      - a bare table name, e.g. ``"loan_applications"``
      - a fully-qualified name, e.g. ``"project.dataset.table"``

    In both cases the resulting SQL will use the fully-qualified form.
    """
    col_clause = ", ".join(columns) if columns else "*"
    # Accept both bare names and already-qualified "project.dataset.table" IDs
    if table_id.count(".") >= 2:
        full_ref = table_id
    else:
        full_ref = f"{project}.{dataset_id}.{table_id}"
    sql = f"SELECT {col_clause} FROM `{full_ref}`"
    if where:
        sql += f" WHERE {where}"
    if limit:
        sql += f" LIMIT {limit}"
    return query_to_df(sql, project=project)


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def write_dataframe(
    df: pd.DataFrame,
    table_id: str,
    schema: Optional[List[Any]] = None,
    dataset_id: str = DEFAULT_DATASET,
    project: str = DEFAULT_PROJECT,
    write_disposition: str = WRITE_APPEND,
    partition_field: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write a pandas DataFrame to BigQuery using load_table_from_dataframe.
    Suitable for batches of any size (uses GCS streaming internally).

    Returns {"rows_written": int, "table": str, "billed_bytes": int}
    """
    if not _BQ_AVAILABLE:
        logger.warning("BQ unavailable — skipping write of %d rows to %s", len(df), table_id)
        return {"rows_written": 0, "table": table_id, "billed_bytes": 0, "stub": True}

    client = get_bq_client(project)
    full_id = f"{project}.{dataset_id}.{table_id}"

    cfg = bigquery.LoadJobConfig(
        write_disposition=write_disposition,
        autodetect=schema is None,
        schema=schema or [],
    )
    if partition_field:
        cfg.time_partitioning = bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field=partition_field,
        )

    job = client.load_table_from_dataframe(df, full_id, job_config=cfg)
    job.result()  # wait

    billed = getattr(job, "output_bytes", 0) or 0
    logger.info(
        "Wrote %d rows to %s (disposition=%s)", len(df), full_id, write_disposition
    )
    return {
        "rows_written": len(df),
        "table": full_id,
        "billed_bytes": billed,
        "job_id": job.job_id,
    }


def stream_rows(
    rows: List[Dict[str, Any]],
    table_id: str,
    dataset_id: str = DEFAULT_DATASET,
    project: str = DEFAULT_PROJECT,
) -> Dict[str, Any]:
    """
    Stream insert individual rows (< 10 MB payload, near-real-time).
    Use for online scoring where each decision must be queryable immediately.
    Errors are returned as a list; does NOT raise on partial failures.
    """
    if not _BQ_AVAILABLE:
        logger.warning("BQ unavailable — skipping stream of %d rows to %s", len(rows), table_id)
        return {"inserted": 0, "errors": [], "stub": True}

    client = get_bq_client(project)
    full_id = f"{project}.{dataset_id}.{table_id}"
    errors = client.insert_rows_json(full_id, rows)
    if errors:
        logger.error("BQ streaming insert errors for %s: %s", full_id, errors[:3])
    else:
        logger.debug("Streamed %d rows to %s", len(rows), full_id)
    return {"inserted": len(rows) - len(errors), "errors": errors}
