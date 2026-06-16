"""
Tests for the P1.3 data quality enforcement module.

Coverage
--------
- All 11 CC_PD_TRAINING_RULES trigger correctly on bad data
- All rules pass on a well-formed dataset
- assert_quality_gate raises DataQualityGateError on ERROR failures
- assert_quality_gate is silent on WARNING-only failures
- save_report writes valid JSON
- DataQualityReport fields are correctly populated
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from data_quality import (
    CC_PD_TRAINING_RULES,
    DataQualityGateError,
    DataQualityReport,
    DataQualityRule,
    assert_quality_gate,
    run_expectations,
    save_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _good_df(n: int = 200) -> pd.DataFrame:
    """Return a minimal, passing DataFrame for the CC PD suite."""
    import numpy as np

    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "application_id": [f"APP{i:06d}" for i in range(n)],
            "fico_score": rng.integers(600, 780, size=n).astype(float),
            "dti": rng.uniform(0.05, 0.45, size=n),
            "annual_income": rng.uniform(30_000, 200_000, size=n),
            "num_derog_marks": rng.integers(0, 3, size=n).astype(float),
            "inq_last_6m": rng.integers(0, 5, size=n).astype(float),
            "pct_rev_utilization": rng.uniform(0.0, 0.8, size=n),
            "num_bankruptcy": rng.integers(0, 1, size=n).astype(float),
            "months_since_last_delinq": rng.uniform(12, 120, size=n),
            "credit_limit": rng.uniform(500, 25_000, size=n),
            "apr": rng.uniform(0.10, 0.30, size=n),
            "default_flag": rng.choice([0, 1], size=n, p=[0.88, 0.12]).astype(float),
            "product": rng.choice(["standard", "rewards"], size=n),
            "annual_fee": [0.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# Smoke: full suite passes on good data
# ---------------------------------------------------------------------------


def test_all_rules_pass_on_clean_data():
    df = _good_df()
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test_clean")
    assert report.gate_passed, f"Unexpected ERROR failures: {report.errors}"
    assert report.passed == report.total_rules or report.warnings  # warnings allowed
    assert report.quality_score > 0.8


# ---------------------------------------------------------------------------
# Schema / null checks
# ---------------------------------------------------------------------------


def test_required_columns_missing_triggers_error():
    df = _good_df().drop(columns=["fico_score"])
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    error_names = [e["rule_name"] for e in report.errors]
    assert "required_columns_present" in error_names


def test_fico_null_triggers_error():
    df = _good_df()
    df.loc[:5, "fico_score"] = float("nan")
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "fico_score_zero_null_rate" for e in report.errors)


def test_application_id_null_triggers_error():
    df = _good_df()
    df.loc[0, "application_id"] = None
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "application_id_zero_null" for e in report.errors)


def test_default_flag_null_triggers_error():
    df = _good_df()
    df.loc[0, "default_flag"] = float("nan")
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "default_flag_zero_null" for e in report.errors)


# ---------------------------------------------------------------------------
# Range checks
# ---------------------------------------------------------------------------


def test_fico_out_of_range_triggers_error():
    df = _good_df()
    df.loc[0, "fico_score"] = 999.0  # > 850
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "fico_score_range" for e in report.errors)


def test_negative_dti_triggers_error():
    df = _good_df()
    df.loc[0, "dti"] = -0.1
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "dti_range_error" for e in report.errors)


def test_dti_above_200pct_triggers_error():
    df = _good_df()
    df.loc[0, "dti"] = 2.5  # > 2.0
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "dti_range_error" for e in report.errors)


def test_high_dti_p99_triggers_warning():
    import numpy as np

    df = _good_df(n=500)
    df.loc[:25, "dti"] = 1.1  # 5% with dti > 1  → p99 > 1.0
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    warn_names = [w["rule_name"] for w in report.warnings]
    assert "dti_range_warning" in warn_names


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------


def test_duplicate_application_id_triggers_error():
    df = _good_df()
    df.loc[1, "application_id"] = df.loc[0, "application_id"]
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "application_id_unique" for e in report.errors)


# ---------------------------------------------------------------------------
# Target distribution
# ---------------------------------------------------------------------------


def test_non_binary_default_flag_triggers_error():
    df = _good_df()
    df.loc[0, "default_flag"] = 2.0
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "default_flag_binary" for e in report.errors)


def test_implausible_default_rate_triggers_warning():
    df = _good_df()
    df["default_flag"] = 0.0  # 0 % default rate → implausible
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    warn_names = [w["rule_name"] for w in report.warnings]
    assert "default_rate_plausible" in warn_names


# ---------------------------------------------------------------------------
# Cross-field consistency
# ---------------------------------------------------------------------------


def test_annual_fee_on_standard_product_triggers_error():
    df = _good_df()
    df.loc[0, "product"] = "standard"
    df.loc[0, "annual_fee"] = 95.0  # fee on standard product → violation
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert any(e["rule_name"] == "annual_fee_product_consistency" for e in report.errors)


def test_annual_fee_on_premium_product_passes():
    df = _good_df()
    df.loc[0, "product"] = "premium"
    df.loc[0, "annual_fee"] = 95.0
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    # rule should not appear in errors
    error_names = [e["rule_name"] for e in report.errors]
    assert "annual_fee_product_consistency" not in error_names


# ---------------------------------------------------------------------------
# Gate / exception behaviour
# ---------------------------------------------------------------------------


def test_assert_quality_gate_raises_on_error():
    df = _good_df()
    df.loc[0, "fico_score"] = 999.0  # triggers fico_score_range ERROR
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    with pytest.raises(DataQualityGateError) as exc_info:
        assert_quality_gate(report)
    assert "fico_score_range" in str(exc_info.value)


def test_assert_quality_gate_silent_on_warning_only():
    """Gate must stay open when only WARNING rules fail."""
    df = _good_df()
    df["default_flag"] = 0.0  # only triggers warning
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    # Should NOT raise
    assert_quality_gate(report)


def test_gate_passed_field_false_on_error():
    df = _good_df().drop(columns=["fico_score"])
    report = run_expectations(df, CC_PD_TRAINING_RULES, "test")
    assert not report.gate_passed


# ---------------------------------------------------------------------------
# Report fields and save_report
# ---------------------------------------------------------------------------


def test_report_fields_are_populated():
    df = _good_df()
    report = run_expectations(df, CC_PD_TRAINING_RULES, "my_dataset")
    assert report.dataset_name == "my_dataset"
    assert report.run_at  # ISO timestamp
    assert report.total_rules == len(CC_PD_TRAINING_RULES)
    assert report.passed + report.failed == report.total_rules
    assert 0.0 <= report.quality_score <= 1.0


def test_save_report_writes_valid_json():
    df = _good_df()
    report = run_expectations(df, CC_PD_TRAINING_RULES, "save_test")
    with tempfile.TemporaryDirectory() as tmp:
        out_path = save_report(report, Path(tmp))
        assert out_path.exists()
        payload = json.loads(out_path.read_text())
        assert payload["dataset_name"] == "save_test"
        assert "quality_score" in payload
        assert "errors" in payload
        assert isinstance(payload["errors"], list)


def test_save_report_creates_directory():
    df = _good_df()
    report = run_expectations(df, CC_PD_TRAINING_RULES, "mkdirtest")
    with tempfile.TemporaryDirectory() as tmp:
        nested = Path(tmp) / "reports" / "data_quality"
        out_path = save_report(report, nested)
        assert out_path.exists()


# ---------------------------------------------------------------------------
# Custom rule behaviour
# ---------------------------------------------------------------------------


def test_rule_exception_counts_as_failure():
    """A rule that raises an exception should be counted as a failure."""

    def bad_check(df: pd.DataFrame) -> bool:
        raise RuntimeError("intentional failure")

    rule = DataQualityRule(
        name="boom",
        description="Always explodes.",
        column=None,
        check=bad_check,
        severity="ERROR",
        expected="never passes",
    )
    report = run_expectations(_good_df(), [rule], "test")
    assert not report.gate_passed
    assert any(e["rule_name"] == "boom" for e in report.errors)


def test_quality_score_calculation():
    df = _good_df()
    all_pass = [
        DataQualityRule("r1", "", None, lambda _: True, "ERROR", ""),
        DataQualityRule("r2", "", None, lambda _: True, "ERROR", ""),
        DataQualityRule("r3", "", None, lambda _: False, "WARNING", ""),
        DataQualityRule("r4", "", None, lambda _: False, "WARNING", ""),
    ]
    report = run_expectations(df, all_pass, "score_test")
    assert report.passed == 2
    assert report.failed == 2
    assert abs(report.quality_score - 0.5) < 0.001
