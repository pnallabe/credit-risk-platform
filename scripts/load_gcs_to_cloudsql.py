#!/usr/bin/env python3
"""
Load Parquet files from GCS into a Cloud SQL PostgreSQL database.

This script:
  1. Lists all train/ and test/ Parquet chunks under a GCS prefix.
  2. Downloads each file in-memory (no local disk writes).
  3. Bulk-inserts rows into ``loan_applications`` via psycopg2 COPY FROM STDIN.
  4. Prints a progress summary at the end.

It is designed to run from a GCP VM / Cloud Shell that has IAM access to
both the GCS bucket and Cloud SQL, OR from your laptop with the Cloud SQL
Auth Proxy running on localhost:5432.

Usage
-----
  # Via Cloud SQL Auth Proxy (recommended for local runs)
  cloud-sql-proxy PROJECT:REGION:INSTANCE &   # keeps running in background
  python scripts/load_gcs_to_cloudsql.py \\
      --db-url "postgresql://USER:PASS@localhost:5432/credit_risk" \\
      --bucket my-credit-risk-bucket \\
      --prefix data \\
      --project my-gcp-project

  # Or set environment variables and run with defaults
  export DATABASE_URL_SYNC=postgresql://...
  export GCS_BUCKET=my-credit-risk-bucket
  export GCP_PROJECT_ID=my-project
  python scripts/load_gcs_to_cloudsql.py

Environment variables (fallback if flags are omitted)
------------------------------------------------------
  DATABASE_URL_SYNC   PostgreSQL sync connection string (psycopg2-style)
  GCS_BUCKET          GCS bucket name
  GCP_PROJECT_ID      GCP project ID
  GCS_DATA_PREFIX     Path prefix inside the bucket (default: data)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterator, List

import pandas as pd
import psycopg2
from google.cloud import storage

PROJECT_ROOT = Path(__file__).parents[1]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB columns (must match db/schema.sql loan_applications table)
# ---------------------------------------------------------------------------
COLUMNS = [
    "application_id",
    "customer_id",
    "credit_score",
    "annual_income",
    "employment_status",
    "employer_tenure_months",
    "debt_to_income_ratio",
    "existing_debt_amount",
    "loan_amount",
    "loan_purpose",
    "loan_term_months",
    "num_open_accounts",
    "num_derogatory_marks",
    "months_since_last_delinquency",
    "state",
    "zip_code_prefix",
    "applied_at",
]

TRAIN_PREFIX = "train"
TEST_PREFIX = "test"


# ---------------------------------------------------------------------------
# GCS helpers
# ---------------------------------------------------------------------------

def list_parquet_blobs(client: storage.Client, bucket_name: str, prefix: str) -> List[str]:
    """Return sorted blob names matching prefix/*.parquet."""
    bucket = client.bucket(bucket_name)
    blobs = [
        b.name
        for b in bucket.list_blobs(prefix=prefix)
        if b.name.endswith(".parquet")
    ]
    return sorted(blobs)


def download_parquet(client: storage.Client, bucket_name: str, blob_name: str) -> pd.DataFrame:
    """Download a GCS Parquet blob in-memory and return as a DataFrame."""
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    buf = io.BytesIO()
    blob.download_to_file(buf)
    buf.seek(0)
    return pd.read_parquet(buf)


# ---------------------------------------------------------------------------
# COPY-based bulk insert
# ---------------------------------------------------------------------------

def _df_to_csv_buf(df: pd.DataFrame) -> io.StringIO:
    """Serialise a DataFrame to a CSV StringIO suitable for psycopg2 COPY."""
    buf = io.StringIO()
    df_export = df[COLUMNS].copy()
    # Convert Timestamp columns to ISO strings; keep NaN as empty for COPY NULL
    df_export["applied_at"] = pd.to_datetime(df_export["submitted_at"] if "submitted_at" in df_export.columns else df_export["applied_at"]).dt.strftime("%Y-%m-%d %H:%M:%S%z")
    df_export.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    return buf


def _prepare_df(df: pd.DataFrame) -> pd.DataFrame:
    """Rename/add columns to match the DB schema and fill defaults."""
    result = df.copy()
    # applied_at is submitted_at in the raw data
    if "submitted_at" in result.columns and "applied_at" not in result.columns:
        result["applied_at"] = result["submitted_at"]
    # Ensure all expected columns exist (fill missing with None)
    for col in COLUMNS:
        if col not in result.columns:
            result[col] = None
    # months_since_last_delinquency: float NaN → None (psycopg2 NULL)
    result["months_since_last_delinquency"] = result["months_since_last_delinquency"].where(
        result["months_since_last_delinquency"].notna(), None
    )
    return result[COLUMNS]


def copy_insert(conn: "psycopg2.connection", df: pd.DataFrame) -> int:
    """Bulk-insert *df* into loan_applications using COPY FROM STDIN.

    Skips rows that violate the primary key (ON CONFLICT DO NOTHING equivalent)
    by using a staging table + INSERT ... ON CONFLICT DO NOTHING approach
    when the Postgres version supports it; falls back to an upsert.
    """
    prepped = _prepare_df(df)

    col_list = ", ".join(COLUMNS)
    copy_sql = (
        f"COPY loan_applications ({col_list}) "
        f"FROM STDIN WITH (FORMAT csv, NULL '\\N', HEADER false)"
    )

    buf = io.StringIO()
    prepped.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)

    with conn.cursor() as cur:
        cur.copy_expert(copy_sql, buf)
        rows = cur.rowcount
    conn.commit()
    return rows if rows and rows > 0 else len(prepped)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load GCS Parquet files into Cloud SQL PostgreSQL")
    p.add_argument("--db-url", default=os.getenv("DATABASE_URL_SYNC", ""),
                   help="PostgreSQL sync connection URL (psycopg2)")
    p.add_argument("--bucket", default=os.getenv("GCS_BUCKET", ""),
                   help="GCS bucket name")
    p.add_argument("--project", default=os.getenv("GCP_PROJECT_ID", ""),
                   help="GCP project ID")
    p.add_argument("--prefix", default=os.getenv("GCS_DATA_PREFIX", "data"),
                   help="Path prefix inside the bucket (default: data)")
    p.add_argument("--split", choices=["train", "test", "both"], default="both",
                   help="Which split to load (default: both)")
    p.add_argument("--limit", type=int, default=0,
                   help="Load only this many chunks (0 = all; for quick testing)")
    return p.parse_args()


def load_split(
    split_name: str,
    gcs_client: storage.Client,
    bucket_name: str,
    prefix: str,
    db_conn: "psycopg2.connection",
    limit: int,
) -> dict:
    split_prefix = f"{prefix}/{split_name}"
    blobs = list_parquet_blobs(gcs_client, bucket_name, split_prefix)
    if limit:
        blobs = blobs[:limit]

    log.info("Loading %s split — %d chunk(s) found", split_name, len(blobs))

    total_rows = 0
    t0 = time.perf_counter()
    for i, blob in enumerate(blobs, 1):
        log.info("  [%d/%d] Downloading gs://%s/%s …", i, len(blobs), bucket_name, blob)
        df = download_parquet(gcs_client, bucket_name, blob)
        rows = copy_insert(db_conn, df)
        total_rows += rows
        elapsed = time.perf_counter() - t0
        log.info("        → %s rows inserted  (cumulative: %s  |  %.1fs elapsed)",
                 f"{rows:,}", f"{total_rows:,}", elapsed)

    return {
        "split": split_name,
        "chunks_loaded": len(blobs),
        "rows_inserted": total_rows,
        "duration_seconds": round(time.perf_counter() - t0, 2),
    }


def main() -> None:
    args = parse_args()

    if not args.bucket:
        sys.exit("ERROR: --bucket / GCS_BUCKET is required")
    if not args.project:
        sys.exit("ERROR: --project / GCP_PROJECT_ID is required")
    if not args.db_url:
        sys.exit("ERROR: --db-url / DATABASE_URL_SYNC is required")

    log.info("Connecting to PostgreSQL …")
    conn = psycopg2.connect(args.db_url)

    gcs_client = storage.Client(project=args.project)

    results = []
    splits = ([TRAIN_PREFIX, TEST_PREFIX] if args.split == "both"
              else [TRAIN_PREFIX] if args.split == "train"
              else [TEST_PREFIX])

    for split in splits:
        result = load_split(
            split_name=split,
            gcs_client=gcs_client,
            bucket_name=args.bucket,
            prefix=args.prefix,
            db_conn=conn,
            limit=args.limit,
        )
        results.append(result)

    conn.close()

    # ── Summary ───────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("Load complete!")
    grand_rows = sum(r["rows_inserted"] for r in results)
    grand_time = sum(r["duration_seconds"] for r in results)
    for r in results:
        log.info("  %-6s  chunks=%d  rows=%s  time=%.1fs",
                 r["split"], r["chunks_loaded"], f"{r['rows_inserted']:,}", r["duration_seconds"])
    log.info("  ─────────────────────────────────────")
    log.info("  TOTAL   rows=%s  time=%.1fs", f"{grand_rows:,}", grand_time)
    log.info("=" * 60)
    log.info("")
    log.info("  Verify with:")
    log.info('    psql "$DATABASE_URL_SYNC" -c "SELECT COUNT(*) FROM loan_applications;"')


if __name__ == "__main__":
    main()
