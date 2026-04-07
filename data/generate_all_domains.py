#!/usr/bin/env python3
"""
Multi-Domain Synthetic Data Orchestrator
=========================================
Runs all three domain generators (Loans, Transactions, Credit Cards)
sequentially or in parallel, then optionally uploads to GCS.

Usage:
    # Generate everything with defaults
    python data/generate_all_domains.py

    # Quick smoke test (small counts)
    python data/generate_all_domains.py --mode small

    # Large-scale (production-like)
    python data/generate_all_domains.py --mode large --upload

    # Individual domains
    python data/generate_all_domains.py --domains loans transactions
    python data/generate_all_domains.py --domains credit_cards

    # Custom scale
    python data/generate_all_domains.py \\
        --loan-customers 1000000 \\
        --loan-applications 2000000 \\
        --txn-accounts 500000 \\
        --txn-count 30000000 \\
        --card-accounts 1000000 \\
        --card-txns 50000000 \\
        --threads 8

Summary of generated volumes (default):
┌─────────────────────────────────────────────────────┐
│  Domain       │  Table                 │  Rows       │
├───────────────┼────────────────────────┼─────────────┤
│  Loans DB     │  customers             │     500 000 │
│               │  loan_applications     │   1 000 000 │
│               │  loans (funded ~70%)   │     700 000 │
│               │  loan_payments         │  ~8 000 000 │
│               │  credit_bureau_pulls   │     600 000 │
│               │  loan_modifications    │      ~50 000│
├───────────────┼────────────────────────┼─────────────┤
│  Transactions │  bank_accounts         │     300 000 │
│               │  transactions          │  15 000 000 │
│               │  ach_transfers         │   ~1 200 000│
│               │  wire_transfers        │      ~75 000│
│               │  fraud_alerts          │     ~10 000 │
│               │  daily_balance_snaps   │     ~900 000│
├───────────────┼────────────────────────┼─────────────┤
│  Credit Cards │  card_accounts         │     500 000 │
│               │  card_transactions     │  25 000 000 │
│               │  card_statements       │   ~2 000 000│
│               │  card_disputes         │      ~25 000│
│               │  rewards_redemptions   │     ~450 000│
│               │  credit_limit_changes  │     ~225 000│
├───────────────┼────────────────────────┼─────────────┤
│  TOTAL                                 │ ~55 000 000 │
└─────────────────────────────────────────────────────┘
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# ─── Scale presets ───────────────────────────────────────────────────────────
PRESETS = {
    "small": dict(
        loan_customers=10_000,
        loan_applications=20_000,
        txn_accounts=5_000,
        txn_count=100_000,
        card_accounts=10_000,
        card_txns=200_000,
        threads=2,
        skip_payments=True,
        skip_statements=True,
    ),
    "medium": dict(
        loan_customers=100_000,
        loan_applications=200_000,
        txn_accounts=50_000,
        txn_count=2_000_000,
        card_accounts=100_000,
        card_txns=5_000_000,
        threads=4,
        skip_payments=False,
        skip_statements=False,
    ),
    "default": dict(
        loan_customers=500_000,
        loan_applications=1_000_000,
        txn_accounts=300_000,
        txn_count=15_000_000,
        card_accounts=500_000,
        card_txns=25_000_000,
        threads=6,
        skip_payments=False,
        skip_statements=False,
    ),
    "large": dict(
        loan_customers=2_000_000,
        loan_applications=5_000_000,
        txn_accounts=1_000_000,
        txn_count=50_000_000,
        card_accounts=2_000_000,
        card_txns=100_000_000,
        threads=8,
        skip_payments=False,
        skip_statements=False,
    ),
}


def run_generator(
    script: str,
    args: list[str],
    domain_name: str,
) -> tuple[bool, float]:
    start = time.time()
    cmd = [sys.executable, str(Path(__file__).parent / script)] + args
    print(f"\n{'='*60}")
    print(f"  STARTING: {domain_name}")
    print(f"  Command : {' '.join(cmd)}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, text=True)
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"\n❌  {domain_name} FAILED (exit code {result.returncode}) after {elapsed:.1f}s")
        return False, elapsed
    print(f"\n✅  {domain_name} completed in {elapsed:.1f}s")
    return True, elapsed


def upload_to_gcs(bucket: str, project: str, prefix: str, domain: str) -> bool:
    """Upload domain parquet files to GCS."""
    try:
        from google.cloud import storage  # type: ignore
    except ImportError:
        print("  google-cloud-storage not installed — skipping upload")
        return False

    domain_dir = Path(__file__).parent / "raw" / domain
    if not domain_dir.exists():
        print(f"  Directory not found: {domain_dir}")
        return False

    client = storage.Client(project=project)
    bkt = client.bucket(bucket)
    files = list(domain_dir.glob("**/*.parquet"))
    print(f"\n  Uploading {len(files)} parquet files for {domain} → gs://{bucket}/{prefix}/{domain}/")

    for f in files:
        blob_name = f"{prefix}/{domain}/{f.name}"
        blob = bkt.blob(blob_name)
        blob.upload_from_filename(str(f), content_type="application/octet-stream")
        size_mb = f.stat().st_size / (1024 ** 2)
        print(f"  ✓ {f.name} ({size_mb:.1f} MB) → {blob_name}")
    return True


def print_summary(results: dict[str, tuple[bool, float]], out_dir: Path) -> None:
    print(f"\n{'='*60}")
    print("  GENERATION SUMMARY")
    print(f"{'='*60}")
    total_ok = all(ok for ok, _ in results.values())
    for domain, (ok, elapsed) in results.items():
        status = "✅" if ok else "❌"
        print(f"  {status} {domain:<20} {elapsed:>7.1f}s")
    print(f"\n  Data directory: {out_dir}")
    total_bytes = 0
    for f in sorted(out_dir.glob("**/*.parquet")):
        size = f.stat().st_size
        total_bytes += size
        rel = f.relative_to(out_dir)
        print(f"    {str(rel):<60} {size/(1024**2):>7.1f} MB")
    print(f"\n  Total size: {total_bytes/(1024**3):.2f} GB")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Orchestrate all domain synthetic data generators",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--mode",
        choices=["small","medium","default","large"],
        default="default",
        help="Scale preset (default: %(default)s)",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=["loans","transactions","credit_cards"],
        default=["loans","transactions","credit_cards"],
        help="Which domains to generate (default: all)",
    )
    # Override individual counts
    parser.add_argument("--loan-customers", type=int)
    parser.add_argument("--loan-applications", type=int)
    parser.add_argument("--txn-accounts", type=int)
    parser.add_argument("--txn-count", type=int)
    parser.add_argument("--card-accounts", type=int)
    parser.add_argument("--card-txns", type=int)
    parser.add_argument("--threads", type=int)
    parser.add_argument("--skip-payments", action="store_true")
    parser.add_argument("--skip-statements", action="store_true")
    # GCS upload
    parser.add_argument("--upload", action="store_true", help="Upload generated data to GCS after generation")
    parser.add_argument("--bucket", default="", help="GCS bucket name (required if --upload)")
    parser.add_argument("--project", default="", help="GCP project ID (required if --upload)")
    parser.add_argument("--gcs-prefix", default="data", help="GCS object prefix (default: data)")
    args = parser.parse_args()

    # Build config from preset + overrides
    cfg = PRESETS[args.mode].copy()
    if args.loan_customers:   cfg["loan_customers"] = args.loan_customers
    if args.loan_applications: cfg["loan_applications"] = args.loan_applications
    if args.txn_accounts:     cfg["txn_accounts"] = args.txn_accounts
    if args.txn_count:        cfg["txn_count"] = args.txn_count
    if args.card_accounts:    cfg["card_accounts"] = args.card_accounts
    if args.card_txns:        cfg["card_txns"] = args.card_txns
    if args.threads:          cfg["threads"] = args.threads
    if args.skip_payments:    cfg["skip_payments"] = True
    if args.skip_statements:  cfg["skip_statements"] = True

    print("=" * 60)
    print("  CREDIT RISK PLATFORM — MULTI-DOMAIN DATA GENERATOR")
    print(f"  Mode   : {args.mode}")
    print(f"  Domains: {', '.join(args.domains)}")
    print(f"  Threads: {cfg['threads']}")
    print("=" * 60)
    print(f"  Loans    : {cfg['loan_customers']:>12,} customers | {cfg['loan_applications']:>12,} applications")
    print(f"  Txns     : {cfg['txn_accounts']:>12,} accounts  | {cfg['txn_count']:>12,} transactions")
    print(f"  Cards    : {cfg['card_accounts']:>12,} accounts  | {cfg['card_txns']:>12,} transactions")
    print()

    out_dir = Path(__file__).parent / "raw"
    results: dict[str, tuple[bool, float]] = {}

    # ── Loans ──────────────────────────────────────────────────────────────
    if "loans" in args.domains:
        loan_args = [
            "--customers", str(cfg["loan_customers"]),
            "--applications", str(cfg["loan_applications"]),
            "--threads", str(cfg["threads"]),
        ]
        if cfg.get("skip_payments"):
            loan_args.append("--skip-payments")
        ok, t = run_generator("generate_loans_data.py", loan_args, "LOANS DB")
        results["loans"] = (ok, t)

    # ── Transactions ───────────────────────────────────────────────────────
    if "transactions" in args.domains:
        txn_args = [
            "--accounts", str(cfg["txn_accounts"]),
            "--transactions", str(cfg["txn_count"]),
            "--threads", str(cfg["threads"]),
        ]
        ok, t = run_generator("generate_transactions_data.py", txn_args, "TRANSACTIONS DB")
        results["transactions"] = (ok, t)

    # ── Credit Cards ───────────────────────────────────────────────────────
    if "credit_cards" in args.domains:
        card_args = [
            "--accounts", str(cfg["card_accounts"]),
            "--transactions", str(cfg["card_txns"]),
            "--threads", str(cfg["threads"]),
        ]
        if cfg.get("skip_statements"):
            card_args.append("--skip-statements")
        ok, t = run_generator("generate_credit_cards_data.py", card_args, "CREDIT CARDS DB")
        results["credit_cards"] = (ok, t)

    # ── Print summary ──────────────────────────────────────────────────────
    print_summary(results, out_dir)

    # ── Upload to GCS ──────────────────────────────────────────────────────
    if args.upload:
        if not args.bucket or not args.project:
            print("\n⚠️  --upload requires --bucket and --project")
        else:
            print("\nUploading to GCS …")
            for domain in args.domains:
                upload_to_gcs(args.bucket, args.project, args.gcs_prefix, domain)

    total_ok = all(ok for ok, _ in results.values())
    sys.exit(0 if total_ok else 1)


if __name__ == "__main__":
    main()
