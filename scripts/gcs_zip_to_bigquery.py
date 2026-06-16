#!/usr/bin/env python3
"""
GCS ZIP → BigQuery Pipeline  (Freddie Mac SFLLD)
=================================================
Streams ZIP files directly from the GCS bucket prefix ``crt/`` (or any
sub-prefix), extracts the pipe-delimited text files inside each ZIP in
memory, parses them in chunks and loads them into two BigQuery tables:

  <dataset>.freddie_origination    — loan-level origination data
  <dataset>.freddie_performance    — monthly performance / time-series data

Every ZIP is processed at most once.  A lightweight checkpoint file
(``processed_zips.txt``) is written to the same GCS prefix so restarts
skip already-loaded ZIPs.

Usage
-----
  python scripts/gcs_zip_to_bigquery.py [OPTIONS]

  Options
  -------
  --project   GCP project id   (env: GCP_PROJECT_ID)
  --bucket    GCS bucket name  (env: GCS_BUCKET, default: ai-risk-workflow-credit-risk-data-dev)
  --prefix    GCS prefix       (env: GCS_CRT_PREFIX_RAW, default: crt/)
  --dataset   BQ dataset       (env: BQ_DATASET, default: freddie_mac_sflld)
  --location  BQ region        (env: GCP_REGION, default: US)
  --chunk     Rows per BQ insert batch (default: 50000)
  --append    WRITE_APPEND instead of WRITE_TRUNCATE on first run
  --dry-run   List ZIPs that would be processed; do not write to BigQuery
  --reset     Ignore existing checkpoint; reprocess all ZIPs
  --zip       Process only this specific ZIP blob name (path inside bucket)

Environment variables (auto-loaded from .env)
---------------------------------------------
  GCP_PROJECT_ID  GCS_BUCKET  GCS_CRT_PREFIX_RAW  BQ_DATASET  GCP_REGION
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import sys
import zipfile
from pathlib import Path
from typing import Iterator

import pandas as pd
from google.cloud import bigquery, storage
from google.api_core.exceptions import NotFound
from google.oauth2 import service_account as sa_module

# ── auto-load .env ────────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.split("#")[0].strip().strip('"').strip("'")
                os.environ.setdefault(_k.strip(), _v)

# ── logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Freddie Mac SFLLD — column definitions ────────────────────────────────────
#  Pipe-delimited, NO header row in the raw text files.
#  After the last field Freddie Mac adds a trailing pipe ⇒ we drop the last
#  empty column that results from the split.

ORIG_COLS = [
    "credit_score", "first_payment_date", "first_time_homebuyer_flag",
    "maturity_date", "msa", "mi_pct", "number_of_units", "occupancy_status",
    "ocltv", "odti", "original_upb", "oltv", "original_interest_rate",
    "channel", "ppm_flag", "product_type", "property_state", "property_type",
    "postal_code", "loan_sequence_number", "loan_purpose", "original_loan_term",
    "number_of_borrowers", "seller_name", "servicer_name",
    "super_conforming_flag", "pre_harp_loan_sequence_number",
    "program_indicator", "harp_indicator", "property_valuation_method",
    "io_indicator", "mi_cancellation_indicator",
]

PERF_COLS = [
    "loan_sequence_number", "monthly_reporting_period", "current_actual_upb",
    "current_delinquency_status", "loan_age", "remaining_months_to_maturity",
    "defect_settlement_date", "modifications_flag", "zero_balance_code",
    "zero_balance_effective_date", "current_interest_rate",
    "current_non_interest_bearing_upb", "due_date_of_last_paid_installment",
    "mi_recoveries", "net_sales_proceeds", "non_mi_recoveries", "expenses",
    "legal_costs", "maintenance_costs", "taxes_and_insurance", "misc_expenses",
    "actual_loss", "modification_cost", "step_modification_flag",
    "deferred_payment_plan", "estimated_ltv", "zero_balance_removal_upb",
    "delinquent_accrued_interest", "delinquency_due_to_disaster",
    "borrower_assistance_status_code", "current_month_modification_cost",
    "interest_bearing_upb",
]

# BigQuery schemas
ORIG_SCHEMA = [
    bigquery.SchemaField("credit_score",                      "INTEGER"),
    bigquery.SchemaField("first_payment_date",                "INTEGER"),
    bigquery.SchemaField("first_time_homebuyer_flag",         "STRING"),
    bigquery.SchemaField("maturity_date",                     "INTEGER"),
    bigquery.SchemaField("msa",                               "STRING"),
    bigquery.SchemaField("mi_pct",                            "FLOAT"),
    bigquery.SchemaField("number_of_units",                   "INTEGER"),
    bigquery.SchemaField("occupancy_status",                  "STRING"),
    bigquery.SchemaField("ocltv",                             "FLOAT"),
    bigquery.SchemaField("odti",                              "FLOAT"),
    bigquery.SchemaField("original_upb",                      "FLOAT"),
    bigquery.SchemaField("oltv",                              "FLOAT"),
    bigquery.SchemaField("original_interest_rate",            "FLOAT"),
    bigquery.SchemaField("channel",                           "STRING"),
    bigquery.SchemaField("ppm_flag",                          "STRING"),
    bigquery.SchemaField("product_type",                      "STRING"),
    bigquery.SchemaField("property_state",                    "STRING"),
    bigquery.SchemaField("property_type",                     "STRING"),
    bigquery.SchemaField("postal_code",                       "STRING"),
    bigquery.SchemaField("loan_sequence_number",              "STRING"),
    bigquery.SchemaField("loan_purpose",                      "STRING"),
    bigquery.SchemaField("original_loan_term",                "INTEGER"),
    bigquery.SchemaField("number_of_borrowers",               "INTEGER"),
    bigquery.SchemaField("seller_name",                       "STRING"),
    bigquery.SchemaField("servicer_name",                     "STRING"),
    bigquery.SchemaField("super_conforming_flag",             "STRING"),
    bigquery.SchemaField("pre_harp_loan_sequence_number",     "STRING"),
    bigquery.SchemaField("program_indicator",                 "STRING"),
    bigquery.SchemaField("harp_indicator",                    "STRING"),
    bigquery.SchemaField("property_valuation_method",         "STRING"),
    bigquery.SchemaField("io_indicator",                      "STRING"),
    bigquery.SchemaField("mi_cancellation_indicator",         "STRING"),
    # provenance
    bigquery.SchemaField("_source_zip",                       "STRING"),
    bigquery.SchemaField("_source_file",                      "STRING"),
]

PERF_SCHEMA = [
    bigquery.SchemaField("loan_sequence_number",              "STRING"),
    bigquery.SchemaField("monthly_reporting_period",          "INTEGER"),
    bigquery.SchemaField("current_actual_upb",                "FLOAT"),
    bigquery.SchemaField("current_delinquency_status",        "STRING"),
    bigquery.SchemaField("loan_age",                          "INTEGER"),
    bigquery.SchemaField("remaining_months_to_maturity",      "FLOAT"),
    bigquery.SchemaField("defect_settlement_date",            "STRING"),
    bigquery.SchemaField("modifications_flag",                "STRING"),
    bigquery.SchemaField("zero_balance_code",                 "STRING"),
    bigquery.SchemaField("zero_balance_effective_date",       "STRING"),
    bigquery.SchemaField("current_interest_rate",             "FLOAT"),
    bigquery.SchemaField("current_non_interest_bearing_upb",  "FLOAT"),
    bigquery.SchemaField("due_date_of_last_paid_installment", "STRING"),
    bigquery.SchemaField("mi_recoveries",                     "FLOAT"),
    bigquery.SchemaField("net_sales_proceeds",                "FLOAT"),
    bigquery.SchemaField("non_mi_recoveries",                 "FLOAT"),
    bigquery.SchemaField("expenses",                          "FLOAT"),
    bigquery.SchemaField("legal_costs",                       "FLOAT"),
    bigquery.SchemaField("maintenance_costs",                 "FLOAT"),
    bigquery.SchemaField("taxes_and_insurance",               "FLOAT"),
    bigquery.SchemaField("misc_expenses",                     "FLOAT"),
    bigquery.SchemaField("actual_loss",                       "FLOAT"),
    bigquery.SchemaField("modification_cost",                 "FLOAT"),
    bigquery.SchemaField("step_modification_flag",            "STRING"),
    bigquery.SchemaField("deferred_payment_plan",             "STRING"),
    bigquery.SchemaField("estimated_ltv",                     "FLOAT"),
    bigquery.SchemaField("zero_balance_removal_upb",          "FLOAT"),
    bigquery.SchemaField("delinquent_accrued_interest",       "FLOAT"),
    bigquery.SchemaField("delinquency_due_to_disaster",       "STRING"),
    bigquery.SchemaField("borrower_assistance_status_code",   "STRING"),
    bigquery.SchemaField("current_month_modification_cost",   "FLOAT"),
    bigquery.SchemaField("interest_bearing_upb",              "FLOAT"),
    # provenance
    bigquery.SchemaField("_source_zip",                       "STRING"),
    bigquery.SchemaField("_source_file",                      "STRING"),
]

CHECKPOINT_BLOB = "crt/processed_zips.txt"


# ── helpers ───────────────────────────────────────────────────────────────────

def load_checkpoint(gcs: storage.Client, bucket_name: str) -> set[str]:
    bucket = gcs.bucket(bucket_name)
    blob = bucket.blob(CHECKPOINT_BLOB)
    if blob.exists():
        return set(blob.download_as_text().splitlines())
    return set()


def save_checkpoint(gcs: storage.Client, bucket_name: str, done: set[str]) -> None:
    bucket = gcs.bucket(bucket_name)
    blob = bucket.blob(CHECKPOINT_BLOB)
    blob.upload_from_string("\n".join(sorted(done)))
    log.info("Checkpoint saved  (%d ZIPs recorded).", len(done))


def list_zips(gcs: storage.Client, bucket_name: str, prefix: str) -> list[str]:
    bucket = gcs.bucket(bucket_name)
    blobs = [b.name for b in bucket.list_blobs(prefix=prefix)
             if b.name.lower().endswith(".zip")]
    log.info("Found %d ZIP file(s) under gs://%s/%s", len(blobs), bucket_name, prefix)
    return sorted(blobs)


def download_zip_bytes(gcs: storage.Client, bucket_name: str, blob_name: str) -> bytes:
    log.info("  ↓ Downloading gs://%s/%s …", bucket_name, blob_name)
    bucket = gcs.bucket(bucket_name)
    data = bucket.blob(blob_name).download_as_bytes()
    log.info("    %.1f MB downloaded.", len(data) / 1_048_576)
    return data


def detect_file_type(filename: str) -> str | None:
    """Return 'origination', 'performance', or None."""
    name = filename.lower()
    if not name.endswith(".txt"):
        return None
    if "_time_" in name or "time_" in name:
        return "performance"
    if "historical_data" in name or "origination" in name:
        return "origination"
    return None


def parse_txt_chunks(
    raw_bytes: bytes,
    cols: list[str],
    chunk_size: int,
    source_zip: str,
    source_file: str,
) -> Iterator[pd.DataFrame]:
    """Parse a pipe-delimited Freddie Mac text file in streaming chunks."""
    n_cols = len(cols)
    chunk: list[list] = []

    text_io = io.TextIOWrapper(io.BytesIO(raw_bytes), encoding="latin-1")
    for line in text_io:
        line = line.rstrip("\n\r")
        if not line:
            continue
        parts = line.split("|")
        # Freddie Mac adds a trailing pipe ⇒ last element is ''
        if parts and parts[-1] == "":
            parts = parts[:-1]
        # Pad / trim to expected width
        if len(parts) < n_cols:
            parts.extend([""] * (n_cols - len(parts)))
        else:
            parts = parts[:n_cols]
        # Replace blank strings with None so pandas uses NaN
        parts = [v if v.strip() else None for v in parts]
        parts.append(source_zip)
        parts.append(source_file)
        chunk.append(parts)
        if len(chunk) >= chunk_size:
            yield pd.DataFrame(chunk, columns=cols + ["_source_zip", "_source_file"])
            chunk = []

    if chunk:
        yield pd.DataFrame(chunk, columns=cols + ["_source_zip", "_source_file"])


def coerce_dtypes(df: pd.DataFrame, schema: list[bigquery.SchemaField]) -> pd.DataFrame:
    """Coerce DataFrame columns to match BigQuery schema types."""
    type_map = {f.name: f.field_type for f in schema}
    for col in df.columns:
        bq_type = type_map.get(col, "STRING")
        if bq_type == "INTEGER":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        elif bq_type == "FLOAT":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = df[col].fillna("").astype(str)
            df[col] = df[col].replace("", None)
    return df


def ensure_dataset(bq: bigquery.Client, dataset_id: str, location: str) -> None:
    full = f"{bq.project}.{dataset_id}"
    try:
        bq.get_dataset(full)
        log.info("BQ dataset exists: %s", full)
    except NotFound:
        ds = bigquery.Dataset(full)
        ds.location = location
        bq.create_dataset(ds, exists_ok=True)
        log.info("BQ dataset created: %s  (location=%s)", full, location)


def ensure_table(
    bq: bigquery.Client,
    dataset_id: str,
    table_name: str,
    schema: list[bigquery.SchemaField],
) -> str:
    table_ref = f"{bq.project}.{dataset_id}.{table_name}"
    try:
        bq.get_table(table_ref)
        log.info("BQ table exists: %s", table_ref)
    except NotFound:
        table = bigquery.Table(table_ref, schema=schema)
        bq.create_table(table, exists_ok=True)
        log.info("Created BQ table: %s", table_ref)
    return table_ref


def load_to_bq(
    bq: bigquery.Client,
    table_ref: str,
    df: pd.DataFrame,
    schema: list[bigquery.SchemaField],
) -> None:
    """Load a DataFrame into BigQuery using a load job (no 10 MB streaming limit)."""
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
    )
    job = bq.load_table_from_dataframe(df, table_ref, job_config=job_config)
    job.result()  # wait for job; raises on error
    log.info("      Load job %s — %d rows appended", job.job_id, job.output_rows)


def _process_members(
    zf: zipfile.ZipFile,
    outer_blob: str,
    bq: bigquery.Client,
    dataset_id: str,
    chunk_size: int,
    dry_run: bool,
    counts: dict[str, int],
    depth: int = 0,
) -> None:
    """Recursively process members of a ZipFile, handling nested ZIPs."""
    indent = "  " + "  " * depth
    members = zf.namelist()
    log.info("%sZIP contains %d member(s): %s", indent, len(members), members)

    for member in members:
        lower = member.lower()

        # Nested ZIP — recurse one level
        if lower.endswith(".zip"):
            log.info("%s→ Nested ZIP: %s — extracting…", indent, member)
            inner_bytes = zf.read(member)
            try:
                with zipfile.ZipFile(io.BytesIO(inner_bytes)) as inner_zf:
                    _process_members(
                        inner_zf, outer_blob, bq, dataset_id,
                        chunk_size, dry_run, counts, depth + 1,
                    )
            except zipfile.BadZipFile as exc:
                log.warning("%s  Bad inner ZIP %s: %s — skipping", indent, member, exc)
            continue

        ftype = detect_file_type(member)
        if ftype is None:
            log.info("%s  Skipping non-data member: %s", indent, member)
            continue

        log.info("%s  Processing %s  → %s table", indent, member, ftype)
        raw = zf.read(member)

        if ftype == "origination":
            cols, schema, table = ORIG_COLS, ORIG_SCHEMA, "freddie_origination"
        else:
            cols, schema, table = PERF_COLS, PERF_SCHEMA, "freddie_performance"

        table_ref = f"{bq.project}.{dataset_id}.{table}"

        # Accumulate all chunks into one DataFrame, then do a single load job
        chunks: list[pd.DataFrame] = []
        total_rows = 0
        for chunk_df in parse_txt_chunks(raw, cols, chunk_size, outer_blob, member):
            chunk_df = coerce_dtypes(chunk_df, schema)
            total_rows += len(chunk_df)
            chunks.append(chunk_df)

        counts[ftype] += total_rows
        log.info("%s  Parsed %d rows from %s", indent, total_rows, member)

        if not dry_run and chunks:
            combined = pd.concat(chunks, ignore_index=True)
            log.info("%s  Loading %d rows → %s …", indent, len(combined), table_ref)
            load_to_bq(bq, table_ref, combined, schema)


def process_zip(
    gcs: storage.Client,
    bq: bigquery.Client,
    bucket_name: str,
    blob_name: str,
    dataset_id: str,
    chunk_size: int,
    dry_run: bool,
) -> dict[str, int]:
    """Download a ZIP, extract text files (recursing into nested ZIPs), parse
    and load to BigQuery.  Returns dict: {'origination': N, 'performance': N}.
    """
    zip_bytes = download_zip_bytes(gcs, bucket_name, blob_name)
    counts = {"origination": 0, "performance": 0}

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        _process_members(zf, blob_name, bq, dataset_id, chunk_size, dry_run, counts)

    return counts


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Load Freddie Mac SFLLD ZIP files (GCS crt/) → BigQuery"
    )
    p.add_argument("--project", default=os.getenv("GCP_PROJECT_ID", ""),
                   help="GCP project id")
    p.add_argument("--bucket",  default=os.getenv("GCS_BUCKET",
                   "ai-risk-workflow-credit-risk-data-dev"),
                   help="GCS bucket name")
    p.add_argument("--prefix",  default=os.getenv("GCS_CRT_PREFIX_RAW", "crt/"),
                   help="GCS prefix (folder) containing ZIP files")
    p.add_argument("--dataset", default=os.getenv("BQ_DATASET", "freddie_mac_sflld"),
                   help="BigQuery dataset name")
    p.add_argument("--location", default=os.getenv("GCP_REGION", "US"),
                   help="BigQuery dataset location")
    p.add_argument("--chunk",   type=int, default=50_000,
                   help="Rows per streaming insert batch (default: 50000)")
    p.add_argument("--append",  action="store_true",
                   help="WRITE_APPEND — do not truncate tables before loading")
    p.add_argument("--dry-run", action="store_true",
                   help="Discover ZIPs and parse but do not write to BigQuery")
    p.add_argument("--reset",   action="store_true",
                   help="Ignore checkpoint; reprocess all ZIPs")
    p.add_argument("--zip",     default=None,
                   help="Process only this specific ZIP blob name (full GCS path "
                        "inside bucket, e.g. crt/historical_2023.zip)")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.project:
        sys.exit("ERROR: --project / GCP_PROJECT_ID is required.")
    if not args.bucket:
        sys.exit("ERROR: --bucket / GCS_BUCKET is required.")

    log.info("═" * 65)
    log.info("GCS ZIP → BigQuery  (Freddie Mac SFLLD)")
    log.info("  Project : %s", args.project)
    log.info("  Bucket  : gs://%s/%s", args.bucket, args.prefix)
    log.info("  Dataset : %s.%s", args.project, args.dataset)
    log.info("  Location: %s", args.location)
    log.info("  Chunk   : %d rows/batch", args.chunk)
    log.info("  Dry-run : %s", args.dry_run)
    log.info("═" * 65)

    # ── Build credentials ─────────────────────────────────────────────────────
    # Prefer explicit SA key (bypasses the ADC metadata-server probe which can
    # fail in some Compute Engine environments with HTTPS routing issues).
    creds_file = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    log.info("GOOGLE_APPLICATION_CREDENTIALS: %r  (exists=%s)",
             creds_file, os.path.isfile(creds_file) if creds_file else "n/a")
    if creds_file and os.path.isfile(creds_file):
        log.info("Using service-account credentials from: %s", creds_file)
        creds = sa_module.Credentials.from_service_account_file(
            creds_file,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        gcs = storage.Client(project=args.project, credentials=creds)
        bq  = bigquery.Client(project=args.project, credentials=creds)
    else:
        log.info("GOOGLE_APPLICATION_CREDENTIALS not set — using ADC.")
        gcs = storage.Client(project=args.project)
        bq  = bigquery.Client(project=args.project)

    if not args.dry_run:
        ensure_dataset(bq, args.dataset, args.location)
        ensure_table(bq, args.dataset, "freddie_origination", ORIG_SCHEMA)
        ensure_table(bq, args.dataset, "freddie_performance",  PERF_SCHEMA)

    # ── Determine which ZIPs to process ───────────────────────────────────────
    if args.zip:
        all_zips = [args.zip]
    else:
        all_zips = list_zips(gcs, args.bucket, args.prefix)

    if not all_zips:
        log.warning("No ZIP files found — nothing to do.")
        return

    checkpoint: set[str] = set()
    if not args.reset and not args.dry_run:
        checkpoint = load_checkpoint(gcs, args.bucket)
        log.info("Checkpoint: %d ZIP(s) already processed.", len(checkpoint))

    to_process = [z for z in all_zips if z not in checkpoint]
    log.info("%d ZIP(s) to process (skipping %d already done).",
             len(to_process), len(all_zips) - len(to_process))

    if args.dry_run:
        for z in to_process:
            log.info("  [dry-run] would process: gs://%s/%s", args.bucket, z)
        return

    # ── Process each ZIP ───────────────────────────────────────────────────────
    total_orig = total_perf = 0
    failed: list[str] = []

    for idx, blob_name in enumerate(to_process, 1):
        log.info("")
        log.info("── [%d/%d] %s ──", idx, len(to_process), blob_name)
        try:
            counts = process_zip(
                gcs, bq,
                args.bucket, blob_name,
                args.dataset, args.chunk,
                args.dry_run,
            )
            total_orig += counts["origination"]
            total_perf += counts["performance"]
            checkpoint.add(blob_name)
            save_checkpoint(gcs, args.bucket, checkpoint)
            log.info(
                "  ✓ Done — orig rows: %d, perf rows: %d",
                counts["origination"], counts["performance"],
            )
        except Exception as exc:
            log.error("  ✗ FAILED: %s — %s", blob_name, exc)
            failed.append(blob_name)

    log.info("")
    log.info("═" * 65)
    log.info("Pipeline complete!")
    log.info("  Origination rows loaded : %d", total_orig)
    log.info("  Performance rows loaded : %d", total_perf)
    if failed:
        log.error("  Failed ZIPs (%d): %s", len(failed), failed)
        sys.exit(1)
    log.info("  bq query --project=%s \\", args.project)
    log.info("    'SELECT COUNT(*) FROM `%s.%s.freddie_origination`'",
             args.project, args.dataset)
    log.info("═" * 65)


if __name__ == "__main__":
    main()
