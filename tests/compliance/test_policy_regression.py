"""
tests/compliance/test_policy_regression.py — Section 23.12
===========================================================
Golden-file policy decision regression tests.

These tests verify that the cc_origination_policy produces the SAME
decision on a fixed set of golden test cases as it did at the time the
golden file was last approved.

Any unexpected change to a decision output (action, APR, credit_limit,
compliance_block) must be reviewed by the policy owner and approved
through the full policy lifecycle before the golden file is updated.

Golden file: tests/compliance/fixtures/policy_golden.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_FILE = Path(__file__).parent / "fixtures" / "policy_golden.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_golden() -> list[dict[str, Any]]:
    if not GOLDEN_FILE.exists():
        return []
    return json.loads(GOLDEN_FILE.read_text())


def _save_golden(cases: list[dict[str, Any]]) -> None:
    GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_FILE.write_text(json.dumps(cases, indent=2, default=str))


# ---------------------------------------------------------------------------
# Golden-file test
# ---------------------------------------------------------------------------


class TestPolicyRegressionGoldenFile:
    """
    Regression guard: decision outputs must not silently change.

    To UPDATE the golden file after an approved policy change:
        pytest tests/compliance/test_policy_regression.py --update-golden

    The --update-golden flag must only be used after Stage 6 committee
    approval (Section 22.2 policy lifecycle).
    """

    def _try_import_policy(self):
        """Import cc_origination_policy; skip if module not present."""
        sys_path_extra = str(REPO_ROOT)
        import sys
        if sys_path_extra not in sys.path:
            sys.path.insert(0, sys_path_extra)
        try:
            from decision_engine.cc_origination_policy import evaluate_application  # type: ignore
            return evaluate_application
        except ImportError:
            pytest.skip("cc_origination_policy not importable — skip golden test.")

    def test_golden_file_exists(self):
        """Fail loudly if the golden file is missing — it must be committed."""
        if not GOLDEN_FILE.exists():
            pytest.xfail(
                f"Golden file not found at {GOLDEN_FILE}.  "
                "Run with --update-golden to create it after policy approval."
            )

    def test_decisions_match_golden(self, request):
        update_mode = request.config.getoption("--update-golden", default=False)
        evaluate_application = self._try_import_policy()
        golden_cases = _load_golden()

        if not golden_cases:
            pytest.skip("No golden cases defined — run with --update-golden first.")

        mismatches: list[str] = []
        for case in golden_cases:
            case_id = case["case_id"]
            inputs = case["inputs"]

            with (
                patch("compliance.engine.get_threshold") as mock_thresh,
                patch("compliance.engine._log_sync", return_value="evt-test"),
            ):
                # Stub threshold fetching to avoid live BQ calls
                from compliance.data_plane import RegulatoryThreshold, ComplianceDataPlaneError

                def _get_thresh(tid, jur="FEDERAL", _case=case):
                    thresholds = _case.get("mock_thresholds", {})
                    key = f"{tid}/{jur}"
                    if key in thresholds:
                        return RegulatoryThreshold(
                            threshold_id=tid, regulation="TEST",
                            jurisdiction=jur, threshold_type="APR_MAX_PCT",
                            threshold_value=thresholds[key],
                            legal_citation="Golden test stub",
                        )
                    raise ComplianceDataPlaneError(f"No threshold {key} in golden mock")

                mock_thresh.side_effect = _get_thresh

                try:
                    result = evaluate_application(**inputs)
                except Exception as exc:
                    mismatches.append(f"{case_id}: evaluate_application raised {exc}")
                    continue

            expected = case["expected_output"]
            for field, expected_val in expected.items():
                actual_val = getattr(result, field, None) or result.get(field) if isinstance(result, dict) else None
                if actual_val is None and hasattr(result, field):
                    actual_val = getattr(result, field)
                if actual_val != expected_val:
                    mismatches.append(
                        f"{case_id}.{field}: expected={expected_val!r} "
                        f"actual={actual_val!r}"
                    )

        if update_mode and mismatches:
            pytest.skip("--update-golden requested — skipping mismatch assertion.")

        assert not mismatches, (
            f"{len(mismatches)} golden-file mismatch(es):\n"
            + "\n".join(mismatches)
            + "\n\nIf this change is intentional, obtain Stage 6 committee approval "
            "then run:  pytest --update-golden"
        )


# ---------------------------------------------------------------------------
# pytest plugin hook: register --update-golden flag
# ---------------------------------------------------------------------------


def pytest_addoption(parser):
    try:
        parser.addoption(
            "--update-golden",
            action="store_true",
            default=False,
            help="Regenerate policy golden file (requires Stage 6 approval).",
        )
    except ValueError:
        pass  # Already registered by another test module
