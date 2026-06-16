#!/usr/bin/env python3
"""
Generate 10 million synthetic loan application records and upload them to
Google Cloud Storage as partitioned Parquet files.

Strategy
--------
- Generates data in chunks of CHUNK_SIZE rows (default 500 000) to keep
  peak RAM under ~4 GB on any machine.
- Writes each chunk directly to GCS as
    gs://<BUCKET>/data/loan_applications/train/part-NNNN.parquet
- Holds out 10 % of each chunk for the test split:
    gs://<BUCKET>/data/loan_applications/test/part-NNNN.parquet
- Uploads a manifest JSON with row counts, chunk list, and schema version.
- Also saves the first chunk locally to data/raw/ for fast local iteration.

Usage
-----
  # Defaults: 10M rows, us-central1, reads GCS_BUCKET from env
  python scripts/generate_and_upload_gcp.py

  # Custom
  python scripts/generate_and_upload_gcp.py \\
      --rows 10000000 \\
      --bucket my-credit-risk-bucket \\
      --project my-gcp-project \\
      --chunk-size 500000 \\
      --workers 4

Environment variables (fallback if flags are omitted)
------------------------------------------------------
  GCS_BUCKET      GCS bucket name
  GCP_PROJECT_ID  GCP project ID
  GCS_DATA_PREFIX Optional path prefix inside the bucket (default: data)
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from google.cloud import storage

# ---------------------------------------------------------------------------
# Make the project root importable so we can reuse generate_records()
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from data.generate_synthetic_data import generate_records  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_TOTAL_ROWS = 10_000_000
DEFAULT_CHUNK_SIZE = 500_000
TEST_FRACTION = 0.10
PARQUET_COMPRESSION = "snappy"
SCHEMA_VERSION = "v1.0"

# GCS path layout
TRAIN_PREFIX = "train"
TEST_PREFIX = "test"
MANIFEST_NAME = "manifest.json"


# ---------------------------------------------------------------------------
# GCS helpers
# ---------------------------------------------------------------------------

def _df_to_bytes(df: pd.DataFrame) -> bytes:
    """Serialise a DataFrame to a Parquet byte-string (in-memory)."""
    buf = io.BytesIO()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, buf, compression=PARQUET_COMPRESSION)
    return buf.getvalue()


def upload_blob(
    client: storage.Client,
    bucket_name: str,
    blob_name: str,
    data: bytes,
) -> str:
    """Upload *data* to GCS and return the gs:// URI."""
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(data, content_type="application/octet-stream")
    return f"gs://{bucket_name}/{blob_name}"


def upload_json(
    client: storage.Client,
    bucket_name: str,
    blob_name: str,
    obj: Any,
) -> str:
    raw = json.dumps(obj, indent=2, default=str).encode("utf-8")
    return upload_blob(client, bucket_name, blob_name, raw)


# ---------------------------------------------------------------------------
# Chunk generation + upload
# ---------------------------------------------------------------------------

def process_chunk(
    chunk_id: int,
    start_row: int,
    chunk_size: int,
    client: storage.Client,
    bucket_name: str,
    data_prefix: str,
    save_local_first: bool,
) -> Dict[str, Any]:
    """Generate one chunk, split into train/test, upload both to GCS."""
    t0 = time.perf_counter()

    # Use a deterministic seed per chunk so reruns are reproducible
    rng_buffer = np.random.default_rng(seed=chunk_id * 17 + 3)
    df = generate_records(chunk_size)

    # 10 % test split
    n_test = max(1, int(chunk_size * TEST_FRACTION))
    test_idx = rng_buffer.choice(chunk_size, size=n_test, replace=False)
    mask = np.zeros(chunk_size, dtype=bool)
    mask[test_idx] = True
    df_train = df[~mask].reset_index(drop=True)
    df_test = df[mask].reset_index(drop=True)

    part_name = f"part-{chunk_id:04d}.parquet"
    train_blob = f"{data_prefix}/{TRAIN_PREFIX}/{part_name}"
    test_blob = f"{data_prefix}/{TEST_PREFIX}/{part_name}"

    train_bytes = _df_to_bytes(df_train)
    test_bytes = _df_to_bytes(df_test)

    train_uri = upload_blob(client, bucket_name, train_blob, train_bytes)
    test_uri = upload_blob(client, bucket_name, test_blob, test_bytes)

    # Optionally persist first chunk locally for fast dev iteration
    if save_local_first:
        local_dir = PROJECT_ROOT / "data" / "raw"
        local_dir.mkdir(parents=True, exist_ok=True)
        df_train.to_parquet(local_dir / "loan_applications.parquet", index=False)
        df_test.to_parquet(local_dir / "loan_applications_test.parquet", index=False)
        log.info("First chunk also saved locally → data/raw/")

    elapsed = time.perf_counter() - t0
    log.info(
        "Chunk %04d  train=%d  test=%d  %.1fs  → %s",
        chunk_id, len(df_train), len(df_test), elapsed, train_uri,
    )
    return {
        "chunk_id": chunk_id,
        "train_uri": train_uri,
        "test_uri": test_uri,
        "train_rows": len(df_train),
        "test_rows": len(df_test),
        "duration_seconds": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate 10M synthetic rows and upload to GCS")
    p.add_argument("--rows", type=int, default=DEFAULT_TOTAL_ROWS,
                   help=f"Total rows to generate (default: {DEFAULT_TOTAL_ROWS:,})")
    p.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                   help=f"Rows per chunk (default: {DEFAULT_CHUNK_SIZE:,})")
    p.add_argument("--bucket", type=str, default=os.getenv("GCS_BUCKET", ""),
                   help="GCS bucket name (or set GCS_BUCKET env var)")
    p.add_argument("--project", type=str, default=os.getenv("GCP_PROJECT_ID", ""),
                   help="GCP project ID (or set GCP_PROJECT_ID env var)")
    p.add_argument("--prefix", type=str, default=os.getenv("GCS_DATA_PREFIX", "data"),
                   help="Path prefix inside the bucket (default: data)")
    p.add_argument("--workers", type=int, default=4,
                   help="Parallel upload threads (default: 4)")
    p.add_argument("--local-only", action="store_true",
                   help="Skip GCS upload — write all chunks to data/raw/ locally only")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.local_only:
        if not args.bucket:
            sys.exit("ERROR: --bucket / GCS_BUCKET is required (unless --local-only)")
        if not args.project:
            sys.exit("ERROR: --project / GCP_PROJECT_ID is required (unless --local-only)")

    total_rows = args.rows
    chunk_size = args.chunk_size
    n_chunks = (total_rows + chunk_size - 1) // chunk_size

    log.info("=" * 60)
    log.info("Credit Risk Platform — GCS Data Pipeline")
    log.info("  Total rows  : %s", f"{total_rows:,}")
    log.info("  Chunk size  : %s", f"{chunk_size:,}")
    log.info("  Chunks      : %d", n_chunks)
    log.info("  Workers     : %d", args.workers)
    if not args.local_only:
        log.info("  Destination : gs://%s/%s", args.bucket, args.prefix)
    else:
        log.info("  Mode        : local-only (no GCS upload)")
    log.info("=" * 60)

    if args.local_only:
        _run_local(total_rows, chunk_size, n_chunks)
        return

    gcs_client = storage.Client(project=args.project)

    manifest_parts: List[Dict[str, Any]] = []
    pipeline_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                process_chunk,
                chunk_id=i,
                start_row=i * chunk_size,
                chunk_size=min(chunk_size, total_rows - i * chunk_size),
                client=gcs_client,
                bucket_name=args.bucket,
                data_prefix=args.prefix,
                save_local_first=(i == 0),
            ): i
            for i in range(n_chunks)
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                manifest_parts.append(result)
            except Exception as exc:
                chunk_id = futures[future]
                log.error("Chunk %04d FAILED: %s", chunk_id, exc)
                raise

    manifest_parts.sort(key=lambda r: r["chunk_id"])
    total_train = sum(r["train_rows"] for r in manifest_parts)
    total_test = sum(r["test_rows"] for r in manifest_parts)
    total_elapsed = time.perf_counter() - pipeline_start

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "gcp_project": args.project,
        "bucket": args.bucket,
        "data_prefix": args.prefix,
        "total_rows": total_train + total_test,
        "train_rows": total_train,
        "test_rows": total_test,
        "n_chunks": n_chunks,
        "chunk_size": chunk_size,
        "test_fraction": TEST_FRACTION,
        "parquet_compression": PARQUET_COMPRESSION,
        "train_path": f"gs://{args.bucket}/{args.prefix}/{TRAIN_PREFIX}/part-*.parquet",
        "test_path": f"gs://{args.bucket}/{args.prefix}/{TEST_PREFIX}/part-*.parquet",
        "duration_seconds": round(total_elapsed, 2),
        "chunks": manifest_parts,
    }

    manifest_blob = f"{args.prefix}/{MANIFEST_NAME}"
    manifest_uri = upload_json(gcs_client, args.bucket, manifest_blob, manifest)

    log.info("=" * 60)
    log.info("Pipeline complete!")
    log.info("  Train rows  : %s", f"{total_train:,}")
    log.info("  Test rows   : %s", f"{total_test:,}")
    log.info("  Total time  : %.1f s", total_elapsed)
    log.info("  Manifest    : %s", manifest_uri)
    log.info("  Query train : gs://%s/%s/%s/*.parquet", args.bucket, args.prefix, TRAIN_PREFIX)
    log.info("  Query test  : gs://%s/%s/%s/*.parquet", args.bucket, args.prefix, TEST_PREFIX)
    log.info("")
    log.info("  Access with pandas:")
    log.info('    import pandas as pd')
    log.info('    df = pd.read_parquet("gs://%s/%s/%s/", storage_options={"project": "%s"})',
             args.bucket, args.prefix, TRAIN_PREFIX, args.project)
    log.info("=" * 60)


def _run_local(total_rows: int, chunk_size: int, n_chunks: int) -> None:
    """Local-only mode: generate all chunks and concatenate to data/raw/."""
    out_dir = PROJECT_ROOT / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)

    train_frames, test_frames = [], []
    for i in range(n_chunks):
        rows = min(chunk_size, total_rows - i * chunk_size)
        log.info("Generating chunk %d/%d (%s rows) …", i + 1, n_chunks, f"{rows:,}")
        df = generate_records(rows)
        n_test = max(1, int(rows * TEST_FRACTION))
        rng = np.random.default_rng(seed=i * 17 + 3)
        idx = rng.choice(rows, size=n_test, replace=False)
        mask = np.zeros(rows, dtype=bool)
        mask[idx] = True
        train_frames.append(df[~mask])
        test_frames.append(df[mask])

    log.info("Concatenating and saving …")
    pd.concat(train_frames, ignore_index=True).to_parquet(
        out_dir / "loan_applications.parquet", index=False
    )
    pd.concat(test_frames, ignore_index=True).to_parquet(
        out_dir / "loan_applications_test.parquet", index=False
    )
    log.info("Done. Files saved to %s", out_dir)


if __name__ == "__main__":
    main()
