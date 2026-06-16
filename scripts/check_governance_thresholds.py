#!/usr/bin/env python3
"""
check_governance_thresholds.py — Section 23.5 / 23.12
=======================================================
CI gate: validates that MODEL_GOVERNANCE thresholds (AUC, KS, PSI) have
NOT been relaxed compared to the baseline captured in
.governance-baseline.json.

A relaxation is defined as: new_threshold < baseline_threshold.

Exits 0 if no threshold has been relaxed, 1 otherwise.

Usage:
    python scripts/check_governance_thresholds.py \
        --baseline-file .governance-baseline.json
"""
import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--baseline-file",
        default=str(REPO_ROOT / ".governance-baseline.json"),
        help="Path to the governance baseline JSON file.",
    )
    return p.parse_args()


def load_current_governance() -> dict:
    """
    Load MODEL_GOVERNANCE from mlflow_config.mlflow_config.
    Falls back to reading governance_config.json if the module is absent.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from mlflow_config.mlflow_config import MODEL_GOVERNANCE  # type: ignore

        return {
            model: {
                "min_auc": cfg.get("min_auc"),
                "min_ks": cfg.get("min_ks"),
                "max_psi": cfg.get("max_psi"),
            }
            for model, cfg in MODEL_GOVERNANCE.items()
        }
    except ImportError:
        pass

    governance_file = REPO_ROOT / "config" / "governance_config.json"
    if governance_file.exists():
        return json.loads(governance_file.read_text())

    logger.error("Cannot load MODEL_GOVERNANCE — no module or config file found.")
    return {}


def main() -> int:
    args = parse_args()
    baseline_file = Path(args.baseline_file)

    if not baseline_file.exists():
        logger.warning(
            "Baseline file not found at %s — creating from current governance.",
            baseline_file,
        )
        current = load_current_governance()
        baseline_file.write_text(json.dumps(current, indent=2))
        logger.info("Baseline written — run again on next PR to enforce thresholds.")
        return 0

    baseline: dict = json.loads(baseline_file.read_text())
    current: dict = load_current_governance()

    if not current:
        logger.error("Could not load current governance thresholds — aborting.")
        return 2

    relaxations: list[str] = []
    for model, base_thresholds in baseline.items():
        curr_thresholds = current.get(model, {})
        for metric, base_val in base_thresholds.items():
            if base_val is None:
                continue
            curr_val = curr_thresholds.get(metric)
            if curr_val is None:
                relaxations.append(
                    f"{model}.{metric}: baseline={base_val}, current=MISSING"
                )
                continue
            # AUC, KS: higher is better -> relaxation = lower current
            # PSI: lower is better -> relaxation = higher current
            if metric in ("min_auc", "min_ks") and curr_val < base_val:
                relaxations.append(
                    f"{model}.{metric}: relaxed from {base_val} -> {curr_val}"
                )
            elif metric == "max_psi" and curr_val > base_val:
                relaxations.append(
                    f"{model}.{metric}: relaxed from {base_val} -> {curr_val} (PSI cap increased)"
                )

    if relaxations:
        logger.error(
            "GOVERNANCE THRESHOLD RELAXATION DETECTED (%d):", len(relaxations)
        )
        for r in relaxations:
            logger.error("  %s", r)
        logger.error(
            "Thresholds may not be relaxed without a full policy lifecycle approval "
            "(Section 22.2 / 23.5 quality gate)."
        )
        return 1

    logger.info("All governance thresholds at or above baseline — OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
