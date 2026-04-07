#!/usr/bin/env python3
"""
Freddie Mac SFLLD → BigQuery Loader
=====================================
Loads Parquet files from GCS (crt/sflld/**) into BigQuery tables:

  <dataset>.freddie_origination   — loan-level origination data
  <dataset>.freddie_performance   — monthly performance / time-series data

The BigQuery dataset is created if it does not exist.
All existing table data is replaced on each run (WRITE_TRUNCATE) unless
--append is passed.

Usage
------
  python scripts/load_freddie_to_bigquery.py

  # Append instead of replace
  python scripts/load_freddie_to_bigquery.py --append

  # Dry-run: list GCS URIs that would be loaded
  python scripts/load_freddie_to_bigquery.py --dry-run

Environment variables (loaded from .env automatically)
--------------------------------------------------------
  GCP_PROJECT_ID   GCP project
  GCS_BUCKET       GCS bucket
  GCS_CRT_PREFIX   GCS prefix under bucket (default: crt/sflld)
  BQ_DATASET       BigQuery dataset name (default: freddie_mac_sflld)
  GCP_REGION       BigQuery dataset location (default: US)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# ── Auto-load .env ────────────────────────────────────────────────────────────
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                _v = _v.split("#")[0].strip().strip('"').strip("'")
                os.environ.setdefault(_k.strip(), _v)

from google.cloud import bigquery, storage  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Freddie Mac SFLLD BigQuery schemas ────────────────────────────────────────
ORIG_SCHEMA = [
    bigquery.SchemaField("credit_score",                  "INTEGER"),
    bigquery.SchemaField("first_payment_date",            "INTEGER"),
    bigquery.SchemaField("first_time_homebuyer_flag",     "STRING"),
    bigquery.SchemaField("maturity_date",                 "INTEGER"),
    bigquery.SchemaField("msa",                           "STRING"),
    bigquery.SchemaField("mi_pct",                        "FLOAT"),
    bigquery.SchemaField("number_of_units",               "INTEGER"),
    bigquery.SchemaField("occupancy_status",              "STRING"),
    bigquery.SchemaField("ocltv",                         "FLOAT"),
    bigquery.SchemaField("odti",                          "FLOAT"),
    bigquery.SchemaField("original_upb",                  "FLOAT"),
    bigquery.SchemaField("oltv",                          "FLOAT"),
    bigquery.SchemaField("original_interest_rate",        "FLOAT"),
    bigquery.SchemaField("channel",                       "STRING"),
    bigquery.SchemaField("ppm_flag",                      "STRING"),
    bigquery.SchemaField("product_type",                  "STRING"),
    bigquery.SchemaField("property_state",                "STRING"),
    bigquery.SchemaField("property_type",                 "STRING"),
    bigquery.SchemaField("postal_code",                   "STRING"),
    bigquery.SchemaField("loan_sequence_number",          "STRING"),
    bigquery.SchemaField("loan_purpose",                  "STRING"),
    bigquery.SchemaField("original_loan_term",            "INTEGER"),
    bigquery.SchemaField("number_of_borrowers",           "INTEGER"),
    bigquery.SchemaField("seller_name",                   "STRING"),
    bigquery.SchemaField("servicer_name",                 "STRING"),
    bigquery.SchemaField("super_conforming_flag",         "STRING"),
    bigquery.SchemaField("pre_harp_loan_sequence_number", "STRING"),
    bigquery.SchemaField("program_indicator",             "STRING"),
    bigquery.SchemaField("harp_indicator",                "STRING"),
    bigquery.SchemaField("property_valuation_method",     "STRING"),
    bigquery.SchemaField("io_indicator",                  "STRING"),
    bigquery.SchemaField("mi_cancellation_indicator",     "STRING"),
]

PERF_SCHEMA = [
    bigquery.SchemaField("loan_sequence_number",          "STRING"),
    bigquery.SchemaField("monthly_reporting_period",      "INTEGER"),
    bigquery.SchemaField("current_actual_upb",            "FLOAT"),
    bigquery.SchemaField("current_delinquency_status",    "STRING"),
    bigquery.SchemaField("loan_age",                      "INTEGER"),
    bigquery.SchemaField("remaining_months_to_maturity",  "FLOAT"),
    bigquery.SchemaField("defect_settlement_date",        "STRING"),
    bigquery.SchemaField("modifications_flag",            "STRING"),
    bigquery.SchemaField("zero_balance_code",             "STRING"),
    bigquery.SchemaField("zero_balance_effective_date",   "STRING"),
    bigquery.SchemaField("current_interest_rate",         "FLOAT"),
    bigquery.SchemaField("current_non_interest_bearing_upb", "FLOAT"),
    bigquery.SchemaField("due_date_of_last_paid_installment", "STRING"),
    bigquery.SchemaField("mi_recoveries",                 "FLOAT"),
    bigquery.SchemaField("net_sales_proceeds",            "FLOAT"),
    bigquery.SchemaField("non_mi_recoveries",             "FLOAT"),
    bigquery.SchemaField("expenses",                      "FLOAT"),
    bigquery.SchemaField("legal_costs",                   "FLOAT"),
    bigquery.SchemaField("maintenance_costs",             "FLOAT"),
    bigquery.SchemaField("taxes_and_insurance",           "FLOAT"),
    bigquery.SchemaField("misc_expenses",                 "FLOAT"),
    bigquery.SchemaField("actual_loss",                   "FLOAT"),
    bigquery.SchemaField("modification_cost",             "FLOAT"),
    bigquery.SchemaField("step_modification_flag",        "STRING"),
    bigquery.SchemaField("deferred_payment_plan",         "STRING"),
    bigquery.SchemaField("estimated_ltv",                 "FLOAT"),
    bigquery.SchemaField("zero_balance_removal_upb",      "FLOAT"),
    bigquery.SchemaField("delinquent_accrued_interest",   "FLOAT"),
    bigquery.SchemaField("delinquency_due_to_disaster",   "STRING"),
    bigquery.SchemaField("borrower_assistance_status_code", "STRING"),
    bigquery.SchemaField("current_month_modification_cost", "FLOAT"),
    bigquery.SchemaField("interest_bearing_upb",          "FLOAT"),
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Load Freddie Mac SFLLD parquet from GCS → BigQuery")
    p.add_argument("--project",   default=os.getenv("GCP_PROJECT_ID", ""))
    p.add_argument("--bucket",    default=os.getenv("GCS_BUCKET", ""))
    p.add_argument("--prefix",    default=os.getenv("GCS_CRT_PREFIX", "crt/sflld"))
    p.add_argument("--dataset",   default=os.getenv("BQ_DATASET", "freddie_mac_sflld"))
    p.add_argument("--location",  default=os.getenv("GCP_REGION", "US"))
    p.add_argument("--append",    action="store_true",
                   help="WRITE_APPEND instead of WRITE_TRUNCATE")
    p.add_argument("--dry-run",   action="store_true",
                   help="List GCS URIs that would be loaded; do not touch BigQuery")
    return p.parse_args()


def ensure_dataset(client: bigquery.Client, dataset_id: str, location: str) -> None:
    full = f"{client.project}.{dataset_id}"
    try:
        client.get_dataset(full)
        log.info("Dataset already exists: %s", full)
    except Exception:
        ds = bigquery.Dataset(full)
        ds.location = location
        client.create_dataset(ds)
        log.info("Created dataset: %s  (location=%s)", full, location)


def list_parquet_uris(
    gcs: storage.Client,
    bucket_name: str,
    prefix: str,
    pattern: str,  # "origination" or "performance"
) -> list[str]:
    """Return gs:// URIs for parquet files matching the pattern (orig vs time)."""
    bucket = gcs.bucket(bucket_name)
    uris = []
    for blob in bucket.list_blobs(prefix=prefix):
        name = blob.name.lower()
        if not name.endswith(".parquet"):
            continue
        filename = name.split("/")[-1]
        if pattern == "origination":
            # origination files: historical_data_YYYYQ{n}_part*.parquet
            # NOT time files which contain "_time_"
            if "_time_" not in filename:
                uris.append(f"gs://{bucket_name}/{blob.name}")
        else:
            # performance / time-series files
            if "_time_" in filename:
                uris.append(f"gs://{bucket_name}/{blob.name}")
    return sorted(uris)


def load_table(
    bq: bigquery.Client,
    dataset_id: str,
    table_name: str,
    uris: list[str],
    schema: list[bigquery.SchemaField],
    write_disposition: str,
    dry_run: bool,
) -> None:
    table_ref = f"{bq.project}.{dataset_id}.{table_name}"
    log.info("")
    log.info("══ %s ══", table_ref)
    log.info("   URIs : %d parquet file(s)", len(uris))
    log.info("   Mode : %s", write_disposition)

    if dry_run:
        for u in uris[:5]:
            log.info("   [dry] %s", u)
        if len(uris) > 5:
            log.info("   [dry] ... and %d more", len(uris) - 5)
        return

    if not uris:
        log.warning("   No files found — skipping.")
        return

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        schema=schema,
        write_disposition=write_disposition,
        schema_update_options=[
            bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
        ],
    )

    job = bq.load_table_from_uri(uris, table_ref, job_config=job_config)
    log.info("   Job  : %s  (running…)", job.job_id)
    job.result()  # wait

    tbl = bq.get_table(table_ref)
    log.info("   ✓ Done — %s rows in %s", f"{tbl.num_rows:,}", table_ref)


def main() -> None:
    args = parse_args()

    for var, name in [(args.project, "--project / GCP_PROJECT_ID"),
                      (args.bucket,  "--bucket / GCS_BUCKET")]:
        if not var:
            sys.exit(f"ERROR: {name} is required.")

    log.info("═" * 65)
    log.info("Freddie Mac SFLLD → BigQuery")
    log.info("  Project : %s", args.project)
    log.info("  Bucket  : gs://%s/%s", args.bucket, args.prefix)
    log.info("  Dataset : %s.%s", args.project, args.dataset)
    log.info("  Location: %s", args.location)
    log.info("═" * 65)

    bq_client  = bigquery.Client(project=args.project)
    gcs_client = storage.Client(project=args.project)

    write_disp = (bigquery.WriteDisposition.WRITE_APPEND
                  if args.append
                  else bigquery.WriteDisposition.WRITE_TRUNCATE)

    if not args.dry_run:
        ensure_dataset(bq_client, args.dataset, args.location)

    # ── Origination table ─────────────────────────────────────────────────────
    orig_uris = list_parquet_uris(gcs_client, args.bucket, args.prefix, "origination")
    log.info("Found %d origination parquet file(s).", len(orig_uris))
    load_table(bq_client, args.dataset, "freddie_origination",
               orig_uris, ORIG_SCHEMA, write_disp, args.dry_run)

    # ── Performance table ─────────────────────────────────────────────────────
    perf_uris = list_parquet_uris(gcs_client, args.bucket, args.prefix, "performance")
    log.info("Found %d performance parquet file(s).", len(perf_uris))
    load_table(bq_client, args.dataset, "freddie_performance",
               perf_uris, PERF_SCHEMA, write_disp, args.dry_run)

    log.info("")
    log.info("═" * 65)
    log.info("BigQuery load complete!")
    log.info("  bq query --project=%s \\", args.project)
    log.info("    'SELECT COUNT(*) FROM `%s.%s.freddie_origination`'",
             args.project, args.dataset)
    log.info("═" * 65)


if __name__ == "__main__":
    main()
