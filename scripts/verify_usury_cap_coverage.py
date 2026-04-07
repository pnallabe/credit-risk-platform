#!/usr/bin/env python3
"""
verify_usury_cap_coverage.py — Section 23.5 / 23.12
=====================================================
CI gate: verifies that config/usury_caps.yaml contains an entry for every
US state, territory, and DC (52 jurisdictions total).

Quality gate (Section 23.12):
  [ ] CI blocks merge if any US state or territory missing from usury_caps.yaml.

Usage:
    python scripts/verify_usury_cap_coverage.py --require-all-states
    python scripts/verify_usury_cap_coverage.py  # just prints coverage
"""
import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
USURY_CAPS_FILE = REPO_ROOT / "config" / "usury_caps.yaml"

# All 50 states + DC + 2 territories (PR, VI) commonly subject to federal
# consumer lending law oversight
ALL_JURISDICTIONS: frozenset[str] = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR", "VI",
    }
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--require-all-states",
        action="store_true",
        help="Exit 1 if any jurisdiction is missing coverage.",
    )
    return p.parse_args()


def load_covered_jurisdictions() -> set[str]:
    if not USURY_CAPS_FILE.exists():
        logger.warning("usury_caps.yaml not found at %s", USURY_CAPS_FILE)
        return set()

    try:
        import yaml  # type: ignore

        with open(USURY_CAPS_FILE) as fh:
            data = yaml.safe_load(fh) or {}
    except ImportError:
        import re

        text = USURY_CAPS_FILE.read_text()
        # Regex: two-letter uppercase keys
        return set(re.findall(r"^\s{0,2}([A-Z]{2}):", text, re.MULTILINE))

    covered: set[str] = set()
    for key in (data if isinstance(data, dict) else {}):
        if isinstance(key, str) and len(key) == 2 and key.isupper():
            covered.add(key)
        if isinstance(data[key], dict):
            for sub_key in data[key]:
                if isinstance(sub_key, str) and len(sub_key) == 2 and sub_key.isupper():
                    covered.add(sub_key)
    return covered


def main() -> int:
    args = parse_args()
    covered = load_covered_jurisdictions()
    missing = ALL_JURISDICTIONS - covered

    logger.info(
        "Usury cap coverage: %d / %d jurisdictions", len(covered), len(ALL_JURISDICTIONS)
    )

    if missing:
        logger.warning(
            "Missing usury cap coverage for %d jurisdiction(s): %s",
            len(missing),
            sorted(missing),
        )
        if args.require_all_states:
            logger.error(
                "COVERAGE FAILURE: Add usury cap entries for all missing "
                "jurisdictions to %s before merging.",
                USURY_CAPS_FILE,
            )
            return 1
    else:
        logger.info("All %d jurisdictions covered — OK", len(ALL_JURISDICTIONS))

    return 0


if __name__ == "__main__":
    sys.exit(main())
