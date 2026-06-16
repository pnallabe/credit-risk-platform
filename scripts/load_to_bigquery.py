"""
scripts/load_to_bigquery.py
============================
Load all generated parquet files from data/raw/ into BigQuery.

Creates the dataset if it doesn't exist, then runs one BigQuery load job
per file using the native Parquet source format (free batch load, no
streaming charges).

Table mapping
-------------
  data/raw/loans/personal_loan_applications.parquet
      → <dataset>.personal_loan_applications
  data/raw/loans/personal_loans_funded.parquet
      → <dataset>.personal_loans_funded
  data/raw/loans/personal_loan_payments.parquet
      → <dataset>.personal_loan_payments
  data/raw/loans/personal_loan_credit_bureau_pulls.parquet
      → <dataset>.personal_loan_credit_bureau_pulls
  data/raw/loans/personal_loan_modifications.parquet
      → <dataset>.personal_loan_modifications
  data/raw/loans/mortgage_applications.parquet
      → <dataset>.mortgage_applications
  data/raw/loans/mortgages_funded.parquet
      → <dataset>.mortgages_funded
  data/raw/loans/mortgage_payments.parquet
      → <dataset>.mortgage_payments
  data/raw/cc_pd/origination_5m_with_decisions.parquet
      → <dataset>.cc_origination_with_decisions

Usage
-----
  python scripts/load_to_bigquery.py \\
      --project ai-risk-workflow \\
      --dataset credit_risk \\
      --location US \\
      --data-dir data/raw/ \\
      --write-disposition WRITE_TRUNCATE
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# ── GCP availability check ────────────────────────────────────────────────────
try:
    from google.cloud import bigquery
    from google.cloud.exceptions import NotFound, Conflict
except ImportError:
    print(
        "ERROR: google-cloud-bigquery is not installed.\n"
        "Install it with:  pip install google-cloud-bigquery pyarrow"
    )
    sys.exit(1)

# ── Table definitions ─────────────────────────────────────────────────────────
# Maps (relative-path-glob, bq_table_name)
# Files are loaded in the order defined here.
TABLE_MAP = [
    # Credit card
    ("cc_pd/origination_5m_with_decisions.parquet", "cc_origination_with_decisions"),
    # Personal loans
    ("loans/personal_loan_applications.parquet",        "personal_loan_applications"),
    ("loans/personal_loans_funded.parquet",             "personal_loans_funded"),
    ("loans/personal_loan_payments.parquet",            "personal_loan_payments"),
    ("loans/personal_loan_credit_bureau_pulls.parquet", "personal_loan_credit_bureau_pulls"),
    ("loans/personal_loan_modifications.parquet",       "personal_loan_modifications"),
    # Mortgages
    ("loans/mortgage_applications.parquet",  "mortgage_applications"),
    ("loans/mortgages_funded.parquet",       "mortgages_funded"),
    ("loans/mortgage_payments.parquet",      "mortgage_payments"),
    # Decision registry (cross-product)
    ("decisions/decision_registry.parquet",  "decision_registry"),
    # Phase 4 – Org financials
    ("financials/org_income_statement.parquet",        "org_income_statement"),
    ("financials/org_balance_sheet.parquet",           "org_balance_sheet"),
    # Phase 4 – Loan economics
    ("financials/loan_origination_economics.parquet",  "loan_origination_economics"),
    ("financials/loan_monthly_ledger.parquet",         "loan_monthly_ledger"),
    ("financials/cc_account_monthly_economics.parquet","cc_account_monthly_economics"),
]


def ensure_dataset(
    client: bigquery.Client,
    project: str,
    dataset_id: str,
    location: str,
) -> None:
    """Create the dataset if it doesn't exist."""
    full_id = f"{project}.{dataset_id}"
    try:
        client.get_dataset(full_id)
        print(f"  Dataset {full_id} already exists.")
    except NotFound:
        ds = bigquery.Dataset(full_id)
        ds.location = location
        ds.description = "Credit risk platform — generated synthetic datasets"
        client.create_dataset(ds, exists_ok=True)
        print(f"  Created dataset {full_id} (location={location})")


def load_parquet_to_bq(
    client: bigquery.Client,
    parquet_path: Path,
    project: str,
    dataset_id: str,
    table_id: str,
    write_disposition: str,
) -> tuple[int, float]:
    """
    Load a local parquet file into BigQuery using a load job.
    Returns (rows_loaded, elapsed_seconds).
    """
    table_ref = f"{project}.{dataset_id}.{table_id}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=write_disposition,
        autodetect=True,
    )
    # enable_list_inference available in bigquery>=3.4; set only if supported
    try:
        job_config.parquet_options = bigquery.ParquetOptions(enable_list_inference=True)
    except TypeError:
        pass  # older SDK — list inference not needed for flat parquet

    print(f"  Loading {parquet_path.name}  →  {table_ref}")
    file_size_mb = parquet_path.stat().st_size / (1024 * 1024)
    print(f"    File size: {file_size_mb:.1f} MB")

    t0 = time.time()
    with open(parquet_path, "rb") as fh:
        load_job = client.load_table_from_file(
            fh,
            table_ref,
            job_config=job_config,
        )

    print(f"    Job submitted: {load_job.job_id}")
    load_job.result()  # Wait for completion
    elapsed = time.time() - t0

    # Verify
    table = client.get_table(table_ref)
    rows = table.num_rows
    print(f"    Done in {elapsed:.1f}s — {rows:,} rows in {table_ref}")
    return rows, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Load parquet files into BigQuery")
    parser.add_argument("--project",  required=True,            help="GCP project ID")
    parser.add_argument("--dataset",  default="credit_risk",    help="BigQuery dataset ID")
    parser.add_argument("--location", default="US",             help="Dataset location")
    parser.add_argument("--data-dir", default="data/raw/",      help="Root of data/raw/")
    parser.add_argument(
        "--write-disposition",
        default="WRITE_TRUNCATE",
        choices=["WRITE_TRUNCATE", "WRITE_APPEND", "WRITE_EMPTY"],
        help="BigQuery write disposition (default: WRITE_TRUNCATE)",
    )
    parser.add_argument(
        "--tables",
        nargs="*",
        help="Subset of table names to load (default: all). "
             "E.g. --tables personal_loan_applications mortgages_funded",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    client = bigquery.Client(project=args.project)

    print("=" * 70)
    print("BIGQUERY PARQUET LOADER")
    print(f"  Project   : {args.project}")
    print(f"  Dataset   : {args.dataset}")
    print(f"  Location  : {args.location}")
    print(f"  Data dir  : {data_dir.resolve()}")
    print(f"  Disposition: {args.write_disposition}")
    print("=" * 70)

    # 1. Ensure dataset exists
    print("\n[1/2] Ensuring dataset exists …")
    ensure_dataset(client, args.project, args.dataset, args.location)

    # 2. Load each table
    print(f"\n[2/2] Loading tables …")
    total_rows = 0
    total_elapsed = 0.0
    skipped = 0
    failed = []

    for rel_path, table_name in TABLE_MAP:
        # Filter by --tables if provided
        if args.tables and table_name not in args.tables:
            continue

        parquet_path = data_dir / rel_path
        if not parquet_path.exists():
            print(f"  SKIP  {parquet_path} (file not found)")
            skipped += 1
            continue

        try:
            rows, elapsed = load_parquet_to_bq(
                client,
                parquet_path,
                args.project,
                args.dataset,
                table_name,
                args.write_disposition,
            )
            total_rows += rows
            total_elapsed += elapsed
        except Exception as exc:
            print(f"  ERROR loading {table_name}: {exc}")
            failed.append((table_name, str(exc)))

    print("\n" + "=" * 70)
    print("LOAD SUMMARY")
    tables_attempted = len([r for r in TABLE_MAP
                             if not args.tables or r[1] in args.tables]) - skipped
    print(f"  Tables loaded : {tables_attempted - len(failed)}")
    print(f"  Tables skipped: {skipped}")
    print(f"  Tables failed : {len(failed)}")
    print(f"  Total rows    : {total_rows:,}")
    print(f"  Total time    : {total_elapsed:.1f}s")
    if failed:
        print("\n  FAILURES:")
        for tbl, err in failed:
            print(f"    {tbl}: {err}")
        sys.exit(1)
    print(f"\n  All data available at:")
    print(f"  https://console.cloud.google.com/bigquery?project={args.project}")
    print("=" * 70)


if __name__ == "__main__":
    main()
