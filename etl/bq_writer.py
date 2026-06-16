"""
etl/bq_writer.py
================
BigQuery writer using the BigQuery Storage Write API for streaming rows into
bronze and silver tables with rejected-row side-table handling.

Why Storage Write API?
----------------------
The legacy streaming insert (``insertAll``) charges per-row, has ~1-minute
settlement delay, and does not support exactly-once semantics.  The Storage
Write API supports at-least-once delivery, has lower cost, and settles
immediately for downstream queries.

Usage
-----
    from etl.bq_writer import write_batch

    n_written = write_batch(
        rows=bronze_rows,
        project="my-gcp-project",
        dataset="credit_risk",
        table="loan_applications_bronze",
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional GCP dependency — graceful degradation for local / unit-test runs
# ---------------------------------------------------------------------------

try:
    from google.cloud import bigquery
    _BQ_AVAILABLE = True
except ImportError:
    bigquery = None  # type: ignore[assignment]
    _BQ_AVAILABLE = False
    logger.warning(
        "google-cloud-bigquery not installed — BQ writes are stubbed. "
        "Install google-cloud-bigquery>=3.11 for production use."
    )

try:
    from google.cloud.bigquery_storage_v1 import (
        BigQueryWriteClient,
        types as _bq_storage_types,
    )
    _BQ_STORAGE_AVAILABLE = True
except ImportError:
    BigQueryWriteClient = None  # type: ignore[assignment]
    _bq_storage_types = None  # type: ignore[assignment]
    _BQ_STORAGE_AVAILABLE = False
    logger.warning(
        "google-cloud-bigquery-storage not installed — falling back to "
        "legacy streaming insert."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _split_valid_rejected(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split rows into (valid_rows, rejected_rows) by presence of 'rejection_reason'."""
    valid: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for row in rows:
        if "rejection_reason" in row:
            rejected.append(row)
        else:
            valid.append(row)
    return valid, rejected


def _clean_row_for_bq(row: Dict[str, Any]) -> Dict[str, Any]:
    """Strip internal metadata keys (starting with '_') before writing to BQ."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# BigQuery write implementations
# ---------------------------------------------------------------------------


def _write_via_storage_api(
    rows: List[Dict[str, Any]],
    project: str,
    dataset: str,
    table: str,
) -> int:
    """Write *rows* using the BigQuery Storage Write API (default stream, at-least-once)."""
    if not _BQ_STORAGE_AVAILABLE or not rows:
        return 0

    client = BigQueryWriteClient()
    write_stream = _bq_storage_types.WriteStream()
    write_stream.type_ = _bq_storage_types.WriteStream.Type.COMMITTED

    parent = client.table_path(project, dataset, table)
    write_stream = client.create_write_stream(
        parent=parent, write_stream=write_stream
    )

    # Build proto rows request
    proto_rows = _bq_storage_types.ProtoRows()
    # For simplicity we use JSON serialisation — in production use proto schema
    # derived from the BigQuery table descriptor.
    request = _bq_storage_types.AppendRowsRequest()
    request.write_stream = write_stream.name

    # Serialise rows as JSON bytes in the proto payload
    import google.protobuf.descriptor_pb2 as _desc_pb2  # noqa: PLC0415
    import struct

    json_rows = [json.dumps(r).encode("utf-8") for r in rows]
    # Use JSON type AppendRowsRequest
    json_request = _bq_storage_types.AppendRowsRequest()
    json_request.write_stream = write_stream.name
    json_request.json_rows.rows.serialized_rows.extend(json_rows)

    responses = client.append_rows(iter([json_request]))
    for resp in responses:
        if resp.error.code:
            logger.error("BQ Storage Write API error: %s", resp.error.message)
            return 0

    client.finalize_write_stream(name=write_stream.name)
    return len(rows)


def _write_via_insert_all(
    rows: List[Dict[str, Any]],
    project: str,
    dataset: str,
    table: str,
) -> int:
    """Fallback: write *rows* using legacy BigQuery streaming insertAll."""
    if not _BQ_AVAILABLE or not rows:
        return 0

    bq_client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"
    errors = bq_client.insert_rows_json(table_ref, rows)
    if errors:
        for err in errors:
            logger.error("BQ insert_rows_json error: %s", err)
        return 0
    return len(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_batch(
    rows: List[Dict[str, Any]],
    project: str,
    dataset: str,
    table: str,
) -> int:
    """Write *rows* to ``project.dataset.table`` using the best available API.

    Rows that contain a ``rejection_reason`` key are routed to
    ``<table>_rejected`` instead of the main table.

    Parameters
    ----------
    rows:
        List of dicts to write.  Each row must conform to the target table's
        schema.  Rows with a ``rejection_reason`` field are written to the
        corresponding ``<table>_rejected`` table.
    project:
        GCP project ID.
    dataset:
        BigQuery dataset ID.
    table:
        BigQuery table name (without project/dataset prefix).

    Returns
    -------
    int
        Number of rows successfully written to the primary table.
    """
    if not rows:
        return 0

    valid_rows, rejected_rows = _split_valid_rejected(rows)
    clean_valid = [_clean_row_for_bq(r) for r in valid_rows]
    clean_rejected = [_clean_row_for_bq(r) for r in rejected_rows]

    n_written = 0

    if clean_valid:
        if _BQ_STORAGE_AVAILABLE:
            try:
                n_written = _write_via_storage_api(clean_valid, project, dataset, table)
            except Exception as exc:
                logger.warning(
                    "Storage Write API failed (%s), falling back to insert_rows_json", exc
                )
                n_written = _write_via_insert_all(clean_valid, project, dataset, table)
        elif _BQ_AVAILABLE:
            n_written = _write_via_insert_all(clean_valid, project, dataset, table)
        else:
            # Neither GCP library is available — log and return 0
            logger.error(
                "No BigQuery client available.  Install google-cloud-bigquery>=3.11 "
                "and google-cloud-bigquery-storage."
            )

    # Write rejected rows to side table
    if clean_rejected:
        rejected_table = f"{table}_rejected"
        try:
            if _BQ_STORAGE_AVAILABLE:
                _write_via_storage_api(clean_rejected, project, dataset, rejected_table)
            elif _BQ_AVAILABLE:
                _write_via_insert_all(clean_rejected, project, dataset, rejected_table)
        except Exception as exc:
            logger.error("Failed to write %d rejected rows to %s: %s",
                         len(clean_rejected), rejected_table, exc)

    return n_written
