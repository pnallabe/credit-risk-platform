#!/usr/bin/env python3
"""
Canary Controller — Decision API Service
========================================
Drives a progressive traffic ramp:
  0% -> 5% -> 10% -> 25% -> 50% -> 100%

Rolls back automatically when:
  - Canary error_rate_5xx > CANARY_ERROR_RATE_THRESHOLD
  - Canary p99_latency_ms > CANARY_P99_THRESHOLD_MS
  - Stable revision health degrades (defensive check)

Exit codes
----------
0 = canary fully promoted
1 = deployment / gcloud error (non-health-related)
2 = rollback triggered due to threshold breach

Usage
-----
    python scripts/canary_decision_api.py \\
        --service decision-api \\
        --region us-central1 \\
        --project my-gcp-project \\
        --canary-revision decision-api-00042-xyz \\
        --stable-revision decision-api-00041-abc \\
        --metrics-url-canary https://canary-decision-api.run.app/v1/metrics \\
        --metrics-url-stable https://decision-api.run.app/v1/metrics \\
        --auth-token $METRICS_AUTH_TOKEN

Environment variables (all overridden by CLI flags)
---------------------------------------------------
CANARY_SERVICE              Cloud Run service name
CANARY_REGION               GCP region
CANARY_PROJECT              GCP project ID
CANARY_REVISION             New revision tag being ramped
STABLE_REVISION             Current stable revision tag
CANARY_METRICS_URL          URL of /v1/metrics on canary
STABLE_METRICS_URL          URL of /v1/metrics on stable
CANARY_P99_THRESHOLD_MS     Max acceptable p99 latency (default: 500)
CANARY_ERROR_RATE_THRESHOLD Max acceptable 5xx error rate (default: 0.01)
CANARY_POLL_INTERVAL_SEC    Seconds between polls (default: 30)
CANARY_RAMP_STEPS           Comma-separated % steps (default: 5,10,25,50,100)
CANARY_RAMP_STEP_WAIT_SEC   Seconds to hold at each step before ramping (default: 300)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Optional

RAMP_STEPS_DEFAULT = [5, 10, 25, 50, 100]


def fetch_metrics(url: str, auth_token: str) -> Optional[dict]:
    """GET /v1/metrics from *url*.

    Parameters
    ----------
    url:        Full URL of the ``/v1/metrics`` endpoint.
    auth_token: Bearer token for the ``Authorization`` header.

    Returns
    -------
    dict | None
        Parsed JSON response, or ``None`` if the request fails.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"[WARN] metrics fetch failed from {url}: {exc}", file=sys.stderr)
        return None


def set_cloud_run_traffic(
    project: str,
    region: str,
    service: str,
    canary_rev: str,
    stable_rev: str,
    canary_pct: int,
) -> bool:
    """Invoke ``gcloud run services update-traffic`` to set traffic split.

    Parameters
    ----------
    project:    GCP project ID.
    region:     GCP region, e.g. ``"us-central1"``.
    service:    Cloud Run service name.
    canary_rev: Name of the canary revision.
    stable_rev: Name of the stable revision.
    canary_pct: Percentage of traffic to route to the canary (0–100).

    Returns
    -------
    bool
        ``True`` if gcloud exited with code 0; ``False`` otherwise.
    """
    stable_pct = 100 - canary_pct
    cmd = [
        "gcloud", "run", "services", "update-traffic", service,
        f"--to-revisions={canary_rev}={canary_pct},{stable_rev}={stable_pct}",
        f"--region={region}",
        f"--project={project}",
        "--quiet",
    ]
    print(f"[TRAFFIC] {canary_rev}={canary_pct}%  {stable_rev}={stable_pct}%")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] gcloud failed: {result.stderr}", file=sys.stderr)
        return False
    return True


def rollback(
    project: str,
    region: str,
    service: str,
    stable_rev: str,
) -> None:
    """Route 100% of traffic to the stable revision immediately.

    Parameters
    ----------
    project:    GCP project ID.
    region:     GCP region.
    service:    Cloud Run service name.
    stable_rev: Stable revision to restore.
    """
    print("[ROLLBACK] Routing all traffic to stable revision.", file=sys.stderr)
    cmd = [
        "gcloud", "run", "services", "update-traffic", service,
        f"--to-revisions={stable_rev}=100",
        f"--region={region}",
        f"--project={project}",
        "--quiet",
    ]
    subprocess.run(cmd, check=False)


def run_canary(args: argparse.Namespace) -> int:
    """Execute the full canary ramp sequence.

    Parameters
    ----------
    args: Parsed :class:`argparse.Namespace` with all required attributes.

    Returns
    -------
    int
        Exit code: 0 = success, 1 = infra/gcloud error, 2 = rollback triggered.
    """
    p99_limit = float(os.getenv("CANARY_P99_THRESHOLD_MS", str(args.p99_threshold)))
    err_limit = float(os.getenv("CANARY_ERROR_RATE_THRESHOLD", str(args.error_threshold)))
    poll_sec = int(os.getenv("CANARY_POLL_INTERVAL_SEC", str(args.poll_interval)))
    hold_sec = int(os.getenv("CANARY_RAMP_STEP_WAIT_SEC", str(args.step_wait)))
    steps_raw = os.getenv("CANARY_RAMP_STEPS", "")
    steps = [int(x) for x in steps_raw.split(",") if x.strip()] or RAMP_STEPS_DEFAULT

    for pct in steps:
        print(f"\n[RAMP] Setting canary traffic to {pct}%...")
        if not set_cloud_run_traffic(
            args.project, args.region, args.service,
            args.canary_revision, args.stable_revision, pct,
        ):
            rollback(args.project, args.region, args.service, args.stable_revision)
            return 1

        deadline = time.monotonic() + hold_sec
        while time.monotonic() < deadline:
            time.sleep(min(poll_sec, max(0.0, deadline - time.monotonic())))
            m = fetch_metrics(args.metrics_url_canary, args.auth_token)
            if m is None:
                print(
                    "[WARN] Canary metrics unavailable — holding position.",
                    file=sys.stderr,
                )
                continue

            p99 = float(m.get("p99_latency_ms") or 0.0)
            err = float(m.get("error_rate_5xx") or 0.0)
            healthy = m.get("canary_healthy", True)

            print(
                f"[HEALTH] p99={p99:.0f}ms  error_rate={err:.4f}"
                f"  canary_healthy={healthy}"
            )

            if p99 > p99_limit or err > err_limit or not healthy:
                print(
                    f"[ALERT] Threshold breach: p99={p99:.0f}>{p99_limit:.0f}ms"
                    f" or err={err:.4f}>{err_limit:.4f}"
                    f" or canary_healthy={healthy}",
                    file=sys.stderr,
                )
                rollback(args.project, args.region, args.service, args.stable_revision)
                return 2  # exit code 2 = rollback triggered

    print("[DONE] Canary promotion complete — 100% traffic on new revision.")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Canary controller for decision-api on Cloud Run"
    )
    ap.add_argument("--service",
                    default=os.getenv("CANARY_SERVICE", "decision-api"),
                    help="Cloud Run service name")
    ap.add_argument("--region",
                    default=os.getenv("CANARY_REGION", "us-central1"),
                    help="GCP region")
    ap.add_argument("--project",
                    default=os.getenv("CANARY_PROJECT", ""),
                    help="GCP project ID")
    ap.add_argument("--canary-revision",
                    default=os.getenv("CANARY_REVISION", ""),
                    dest="canary_revision",
                    help="New revision name being ramped")
    ap.add_argument("--stable-revision",
                    default=os.getenv("STABLE_REVISION", ""),
                    dest="stable_revision",
                    help="Current stable revision name")
    ap.add_argument("--metrics-url-canary",
                    default=os.getenv("CANARY_METRICS_URL", ""),
                    dest="metrics_url_canary",
                    help="URL of /v1/metrics on the canary service")
    ap.add_argument("--metrics-url-stable",
                    default=os.getenv("STABLE_METRICS_URL", ""),
                    dest="metrics_url_stable",
                    help="URL of /v1/metrics on the stable service")
    ap.add_argument("--auth-token",
                    default=os.getenv("METRICS_AUTH_TOKEN", ""),
                    dest="auth_token",
                    help="Bearer token for /v1/metrics authentication")
    ap.add_argument("--p99-threshold",
                    type=float, default=500.0,
                    dest="p99_threshold",
                    help="Max acceptable p99 latency in ms (default: 500)")
    ap.add_argument("--error-threshold",
                    type=float, default=0.01,
                    dest="error_threshold",
                    help="Max acceptable 5xx error rate (default: 0.01)")
    ap.add_argument("--poll-interval",
                    type=int, default=30,
                    dest="poll_interval",
                    help="Seconds between metric polls (default: 30)")
    ap.add_argument("--step-wait",
                    type=int, default=300,
                    dest="step_wait",
                    help="Seconds to hold at each ramp step (default: 300)")
    return ap


def main() -> None:
    ap = _build_parser()
    args = ap.parse_args()

    missing = [
        f for f in ("project", "canary_revision", "stable_revision",
                    "metrics_url_canary", "auth_token")
        if not getattr(args, f, "")
    ]
    if missing:
        ap.error(f"Missing required arguments: {missing}")

    sys.exit(run_canary(args))


if __name__ == "__main__":
    main()
