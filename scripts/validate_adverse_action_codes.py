#!/usr/bin/env python3
"""
validate_adverse_action_codes.py — Section 23.5 / 23.12
=========================================================
CI gate: validates that config/adverse_action_codes.yaml contains an
entry for every DeclineReason enum value used in the codebase.

Quality gate (Section 23.12):
  [ ] CI blocks merge if any DeclineReason enum value is missing from
      config/adverse_action_codes.yaml.

Exits 0 if complete, 1 if any enum value is uncovered.
"""
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
AA_CODES_FILE = REPO_ROOT / "config" / "adverse_action_codes.yaml"
DECISION_ENGINE_DIRS = [
    REPO_ROOT / "decision_engine",
    REPO_ROOT / "compliance",
]


def load_adverse_action_codes() -> set[str]:
    """Parse adverse_action_codes.yaml and return set of code keys."""
    if not AA_CODES_FILE.exists():
        logger.error("adverse_action_codes.yaml not found at %s", AA_CODES_FILE)
        return set()

    try:
        import yaml  # type: ignore
    except ImportError:
        logger.warning("PyYAML not installed — using regex fallback.")
        text = AA_CODES_FILE.read_text()
        return set(re.findall(r"^\s{0,4}(\w+):", text, re.MULTILINE))

    with open(AA_CODES_FILE) as fh:
        data = yaml.safe_load(fh)

    codes: set[str] = set()
    if isinstance(data, dict):
        for section in data.values():
            if isinstance(section, dict):
                codes.update(section.keys())
            elif isinstance(section, list):
                for item in section:
                    if isinstance(item, str):
                        codes.add(item)
                    elif isinstance(item, dict):
                        codes.update(item.keys())
    return codes


def collect_decline_reasons_from_source() -> set[str]:
    """
    Scan Python source files for DeclineReason enum members.
    Matches patterns like:  INSUFFICIENT_INCOME = "INSUFFICIENT_INCOME"
    """
    members: set[str] = set()
    pattern = re.compile(r"\b([A-Z][A-Z0-9_]{3,})\s*=\s*[\"']([A-Z][A-Z0-9_]{3,})[\"']")

    for base_dir in DECISION_ENGINE_DIRS:
        for py_file in base_dir.rglob("*.py"):
            text = py_file.read_text(errors="replace")
            if "DeclineReason" not in text and "decline_reason" not in text.lower():
                continue
            for match in pattern.finditer(text):
                name, value = match.group(1), match.group(2)
                if name == value:  # enum member pattern
                    members.add(value)

    return members


def main() -> int:
    aa_codes = load_adverse_action_codes()
    decline_reasons = collect_decline_reasons_from_source()

    if not aa_codes:
        logger.error("No adverse action codes loaded — file missing or empty.")
        return 1

    missing = decline_reasons - aa_codes
    if missing:
        logger.error(
            "ADVERSE ACTION CODE COMPLETENESS FAILURE: %d DeclineReason value(s) "
            "not found in adverse_action_codes.yaml: %s",
            len(missing),
            sorted(missing),
        )
        logger.error(
            "Add these codes to %s before merging.", AA_CODES_FILE
        )
        return 1

    logger.info(
        "All %d DeclineReason values covered by adverse_action_codes.yaml — OK",
        len(decline_reasons),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
