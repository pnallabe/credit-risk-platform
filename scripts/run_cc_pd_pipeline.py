#!/usr/bin/env python3
"""
Credit Card PD — End-to-End Pipeline Runner
============================================
Orchestrates all four stages of the CC PD pipeline:

  Stage 1 — Data generation   (data/generate_cc_pd_dataset.py)
  Stage 2 — Model training    (models/credit_risk/train_cc_pd_model.py)
  Stage 3 — Policy evaluation (decision_engine/cc_origination_policy.py)
  Stage 4 — Monitoring report (monitoring/cc_pd_monitor.py)

Usage
-----
    python scripts/run_cc_pd_pipeline.py                     # full 5M run
    python scripts/run_cc_pd_pipeline.py --quick             # 100k smoke test
    python scripts/run_cc_pd_pipeline.py --stage gen         # data only
    python scripts/run_cc_pd_pipeline.py --stage train       # train only
    python scripts/run_cc_pd_pipeline.py --stage policy      # policy eval only
    python scripts/run_cc_pd_pipeline.py --stage monitor     # monitoring only
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
ROOT = Path(__file__).parent.parent


def _run(cmd: list[str], desc: str) -> None:
    log.info("▶  %s", desc)
    log.info("   %s", " ".join(cmd))
    t0  = time.time()
    ret = subprocess.run(cmd, cwd=str(ROOT))
    elapsed = time.time() - t0
    if ret.returncode != 0:
        log.error("✗  %s failed (exit %d)", desc, ret.returncode)
        sys.exit(ret.returncode)
    log.info("✔  %s completed in %.1f s", desc, elapsed)


def stage_gen(records: int, seed: int, chunk_size: int) -> None:
    _run(
        [sys.executable,
         str(ROOT / "data" / "generate_cc_pd_dataset.py"),
         "--records",    str(records),
         "--seed",       str(seed),
         "--chunk-size", str(chunk_size)],
        f"Stage 1 — Synthetic data generation ({records:,} records)",
    )


def stage_train(no_tuning: bool, sample: int | None) -> None:
    cmd = [sys.executable,
           str(ROOT / "models" / "credit_risk" / "train_cc_pd_model.py")]
    if no_tuning:
        cmd.append("--no-tuning")
    if sample:
        cmd += ["--sample", str(sample)]
    _run(cmd, "Stage 2 — PD model training")


def stage_policy() -> None:
    _run(
        [sys.executable,
         str(ROOT / "decision_engine" / "cc_origination_policy.py"),
         "--breakeven"],
        "Stage 3 — Origination policy / break-even analysis",
    )


def stage_monitor(sample: int) -> None:
    _run(
        [sys.executable,
         str(ROOT / "monitoring" / "cc_pd_monitor.py"),
         "--sample", str(sample),
         "--export", "xlsx"],
        "Stage 4 — Portfolio monitoring report",
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="CC PD pipeline runner")
    ap.add_argument("--stage",
                    choices=["gen", "train", "policy", "monitor", "all"],
                    default="all")
    ap.add_argument("--quick",       action="store_true",
                    help="Smoke test: 100k records, no HPO, 50k monitor sample")
    ap.add_argument("--records",     type=int,  default=5_000_000)
    ap.add_argument("--seed",        type=int,  default=42)
    ap.add_argument("--chunk-size",  type=int,  default=500_000)
    ap.add_argument("--no-tuning",   action="store_true")
    ap.add_argument("--train-sample",type=int,  default=None)
    ap.add_argument("--monitor-sample", type=int, default=200_000)
    args = ap.parse_args()

    # Quick override
    if args.quick:
        args.records      = 100_000
        args.chunk_size   = 100_000
        args.no_tuning    = True
        args.train_sample = 100_000
        args.monitor_sample = 50_000
        log.info("QUICK mode: 100k records, no HPO")

    t_total = time.time()
    log.info("=" * 60)
    log.info("Credit Card PD Pipeline  (stage=%s)", args.stage)
    log.info("=" * 60)

    run_all   = args.stage == "all"

    if run_all or args.stage == "gen":
        stage_gen(args.records, args.seed, args.chunk_size)

    if run_all or args.stage == "train":
        stage_train(args.no_tuning, args.train_sample)

    if run_all or args.stage == "policy":
        stage_policy()

    if run_all or args.stage == "monitor":
        stage_monitor(args.monitor_sample)

    log.info("=" * 60)
    log.info("Pipeline complete in %.1f s", time.time() - t_total)
    log.info("Outputs:")
    log.info("  Data     → data/raw/cc_pd/")
    log.info("  Model    → models/credit_risk/cc_pd_model_v1.pkl")
    log.info("  Scorecard→ models/credit_risk/cc_pd_scorecard.json")
    log.info("  Monitor  → monitoring/cc_pd_reports/")
    log.info("  MLflow   → mlruns/ (run: mlflow ui)")


if __name__ == "__main__":
    main()
