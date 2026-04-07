"""
generate_and_upload_gcp_multi.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Upload all three synthetic data domains (loans, transactions, credit cards)
to a GCS bucket, preserving the data/raw/<domain>/ folder structure.

Usage
-----
    python scripts/generate_and_upload_gcp_multi.py \
        --bucket my-crp-bucket \
        --project my-gcp-project \
        --prefix data \
        --domains loans transactions credit_cards \
        --workers 8

The script:
  1. Scans data/raw/<domain>/ for *.parquet files.
  2. Uploads them in parallel to gs://<bucket>/<prefix>/<domain>/<filename>.
  3. Prints a summary table with file counts and total bytes.

Authentication
--------------
  - Workload Identity (GKE / Cloud Run): automatic.
  - Local: run `gcloud auth application-default login`.
  - Service account key: set GOOGLE_APPLICATION_CREDENTIALS env var.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Optional GCS dependency ──────────────────────────────────────────────────
try:
    from google.cloud import storage
    from google.api_core.exceptions import GoogleAPICallError
except ImportError:
    print(
        "[ERROR] google-cloud-storage not installed.\n"
        "        Run: pip install google-cloud-storage",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Constants ─────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = REPO_ROOT / "data" / "raw"
SUPPORTED_DOMAINS = ["loans", "transactions", "credit_cards"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _collect_files(domain: str) -> list[Path]:
    """Return sorted list of parquet files for a domain."""
    domain_dir = RAW_DATA_DIR / domain
    if not domain_dir.exists():
        print(f"  [WARN] {domain_dir} does not exist — skipping {domain}")
        return []
    files = sorted(domain_dir.glob("**/*.parquet"))
    return files


def _upload_one(
    client: storage.Client,
    bucket_name: str,
    gcs_prefix: str,
    local_path: Path,
) -> tuple[str, int]:
    """Upload a single file; returns (gcs_uri, bytes_uploaded)."""
    relative = local_path.relative_to(RAW_DATA_DIR)           # e.g. loans/customers.parquet
    blob_name = f"{gcs_prefix}/{relative}" if gcs_prefix else str(relative)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(local_path), timeout=300)
    return f"gs://{bucket_name}/{blob_name}", local_path.stat().st_size


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


# ── Main ──────────────────────────────────────────────────────────────────────

def upload_domains(
    bucket_name: str,
    project_id: str,
    gcs_prefix: str,
    domains: list[str],
    workers: int,
) -> None:
    print(f"\nConnecting to GCS project '{project_id}' …")
    client = storage.Client(project=project_id)

    # Verify bucket exists
    try:
        bucket = client.get_bucket(bucket_name)
    except GoogleAPICallError as exc:
        print(f"[ERROR] Cannot access bucket '{bucket_name}': {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Bucket    : gs://{bucket.name}")
    print(f"Prefix    : {gcs_prefix or '(root)'}")
    print(f"Domains   : {', '.join(domains)}")
    print(f"Workers   : {workers}\n")

    grand_total_files = 0
    grand_total_bytes = 0

    for domain in domains:
        files = _collect_files(domain)
        if not files:
            continue

        domain_bytes = 0
        domain_files = 0
        errors: list[str] = []

        print(f"  ┌─ {domain.upper()}: {len(files)} files")
        t0 = time.monotonic()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_upload_one, client, bucket_name, gcs_prefix, f): f
                for f in files
            }
            for fut in as_completed(futures):
                src = futures[fut]
                try:
                    uri, size = fut.result()
                    domain_bytes += size
                    domain_files += 1
                    print(f"  │  ✓  {src.name:<50s}  →  {uri}")
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{src}: {exc}")
                    print(f"  │  ✗  {src.name}: {exc}")

        elapsed = time.monotonic() - t0
        print(
            f"  └─ {domain_files}/{len(files)} uploaded  "
            f"({_fmt_bytes(domain_bytes)})  in {elapsed:.1f}s"
        )
        if errors:
            print(f"     Errors ({len(errors)}):")
            for e in errors:
                print(f"       • {e}")

        grand_total_files += domain_files
        grand_total_bytes += domain_bytes
        print()

    print("=" * 60)
    print(f"DONE — {grand_total_files} files  /  {_fmt_bytes(grand_total_bytes)} total")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Upload multi-domain synthetic data to GCS",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--bucket", required=True, help="GCS bucket name (no gs:// prefix)")
    p.add_argument("--project", required=True, help="GCP project ID")
    p.add_argument("--prefix", default="data", help="GCS object prefix (folder)")
    p.add_argument(
        "--domains",
        nargs="+",
        default=SUPPORTED_DOMAINS,
        choices=SUPPORTED_DOMAINS,
        help="Which domains to upload",
    )
    p.add_argument("--workers", type=int, default=8, help="Parallel upload threads")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    upload_domains(
        bucket_name=args.bucket,
        project_id=args.project,
        gcs_prefix=args.prefix.rstrip("/"),
        domains=args.domains,
        workers=args.workers,
    )
