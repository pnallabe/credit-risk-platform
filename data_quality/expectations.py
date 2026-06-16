"""
Data Quality Enforcement Module
================================
Pure-Python expectation suite for credit risk datasets.
No Great Expectations dependency — uses pandas + standard library only.

Design principles
-----------------
- A ``DataQualityRule`` is a named check with a Callable receiving the full
  DataFrame and returning bool (True = rule passes).
- Rules are classified as "ERROR" (gate-blocking) or "WARNING" (informational).
- ``run_expectations()`` runs all rules, catching exceptions per rule so a
  single bad rule cannot abort the entire suite.
- ``assert_quality_gate()`` raises ``DataQualityGateError`` if any ERROR-level
  rule failed — this is designed to abort model training.
- All report artifacts are JSON-serializable (standard Python types only).

Usage
-----
    from data_quality import run_expectations, assert_quality_gate
    from data_quality import CC_PD_TRAINING_RULES, save_report

    report = run_expectations(raw_df, CC_PD_TRAINING_RULES, "cc_pd_training")
    save_report(report, Path("reports/data_quality/"))
    assert_quality_gate(report)   # raises if any ERROR rule failed
"""
from __future__ import annotations

import dataclasses
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List, Literal, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DataQualityRule:
    """A single data quality expectation.

    Attributes
    ----------
    name :
        Short identifier, e.g. ``"null_fico_score"``.
    description :
        Human-readable description shown in the report.
    column :
        The column being tested, or None for dataset-level rules.
    check :
        Callable receiving the full DataFrame; returns True if the rule passes.
    severity :
        ``"ERROR"`` blocks training; ``"WARNING"`` is informational only.
    expected :
        Short string describing the passing condition (for the report).
    """
    name: str
    description: str
    column: Optional[str]
    check: Callable[[pd.DataFrame], bool]
    severity: Literal["ERROR", "WARNING"]
    expected: str


@dataclasses.dataclass
class DataQualityReport:
    """Result of running a full expectation suite.

    Attributes
    ----------
    dataset_name :
        Logical name of the dataset being validated.
    run_at :
        ISO-8601 UTC timestamp of the run.
    total_rules :
        Number of rules executed.
    passed :
        Rules that returned True.
    failed :
        Rules that returned False or raised an exception.
    errors :
        List of dicts for ERROR-severity failures.
    warnings :
        List of dicts for WARNING-severity failures.
    quality_score :
        Fraction of rules that passed (0.0–1.0).
    gate_passed :
        True only when zero ERROR-severity failures occurred.
    """
    dataset_name: str
    run_at: str
    total_rules: int
    passed: int
    failed: int
    errors: List[dict]
    warnings: List[dict]
    quality_score: float
    gate_passed: bool


class DataQualityGateError(Exception):
    """Raised by ``assert_quality_gate`` when ERROR rules fail."""

    def __init__(self, report: DataQualityReport) -> None:
        self.report = report
        names = [e["rule_name"] for e in report.errors]
        super().__init__(
            f"Data quality gate FAILED — {len(names)} ERROR rule(s) failed: "
            + ", ".join(names)
        )


# ---------------------------------------------------------------------------
# Standard expectation suite for the CC PD training dataset
# ---------------------------------------------------------------------------

# Required columns for the CC PD training set
_REQUIRED_NUMERIC_COLS = [
    "fico_score", "dti", "annual_income", "num_derog_marks",
    "inq_last_6m", "pct_rev_utilization", "num_bankruptcy",
    "months_since_last_delinq", "credit_limit", "apr",
]
_REQUIRED_COLS = _REQUIRED_NUMERIC_COLS + ["application_id", "default_flag"]

# Product values that may carry an annual fee
_FEE_BEARING_PRODUCTS = {"premium", "secured"}


def _pct_null(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or len(df) == 0:
        return 1.0
    return float(df[col].isna().mean())


CC_PD_TRAINING_RULES: List[DataQualityRule] = [
    # ── Schema checks ──────────────────────────────────────────────────────
    DataQualityRule(
        name="required_columns_present",
        description="All required columns must exist in the training dataset.",
        column=None,
        check=lambda df: all(c in df.columns for c in _REQUIRED_COLS),
        severity="ERROR",
        expected=f"Columns present: {_REQUIRED_COLS}",
    ),
    # ── Null rate checks ───────────────────────────────────────────────────
    DataQualityRule(
        name="fico_score_zero_null_rate",
        description="fico_score must have no null values — it is a primary underwriting input.",
        column="fico_score",
        check=lambda df: _pct_null(df, "fico_score") == 0.0,
        severity="ERROR",
        expected="null rate = 0%",
    ),
    DataQualityRule(
        name="months_since_last_delinq_null_rate",
        description="months_since_last_delinq null rate must be < 15% (common for no-delinquency).",
        column="months_since_last_delinq",
        check=lambda df: _pct_null(df, "months_since_last_delinq") < 0.15,
        severity="WARNING",
        expected="null rate < 15%",
    ),
    DataQualityRule(
        name="application_id_zero_null",
        description="application_id must never be null.",
        column="application_id",
        check=lambda df: _pct_null(df, "application_id") == 0.0,
        severity="ERROR",
        expected="null rate = 0%",
    ),
    DataQualityRule(
        name="default_flag_zero_null",
        description="Target column default_flag must never be null.",
        column="default_flag",
        check=lambda df: _pct_null(df, "default_flag") == 0.0,
        severity="ERROR",
        expected="null rate = 0%",
    ),
    # ── Range / dtype checks ───────────────────────────────────────────────
    DataQualityRule(
        name="fico_score_range",
        description="fico_score must be in the valid FICO range [300, 850].",
        column="fico_score",
        check=lambda df: (
            "fico_score" not in df.columns
            or bool(
                pd.to_numeric(df["fico_score"], errors="coerce")
                .dropna()
                .between(300, 850)
                .all()
            )
        ),
        severity="ERROR",
        expected="300 <= fico_score <= 850",
    ),
    DataQualityRule(
        name="dti_range_error",
        description="dti must be between 0.0 and 2.0 (no negative or implausible values).",
        column="dti",
        check=lambda df: (
            "dti" not in df.columns
            or bool(
                pd.to_numeric(df["dti"], errors="coerce")
                .dropna()
                .between(0.0, 2.0)
                .all()
            )
        ),
        severity="ERROR",
        expected="0.0 <= dti <= 2.0",
    ),
    DataQualityRule(
        name="dti_range_warning",
        description="99th percentile of dti should be < 1.0 (dti>1 is unusual for CC applicants).",
        column="dti",
        check=lambda df: (
            "dti" not in df.columns
            or float(
                pd.to_numeric(df["dti"], errors="coerce").quantile(0.99)
            ) < 1.0
        ),
        severity="WARNING",
        expected="p99(dti) < 1.0",
    ),
    # ── Uniqueness ─────────────────────────────────────────────────────────
    DataQualityRule(
        name="application_id_unique",
        description="application_id must be unique — no duplicate rows.",
        column="application_id",
        check=lambda df: (
            "application_id" not in df.columns
            or int(df["application_id"].duplicated().sum()) == 0
        ),
        severity="ERROR",
        expected="zero duplicate application_id values",
    ),
    # ── Target distribution ────────────────────────────────────────────────
    DataQualityRule(
        name="default_flag_binary",
        description="default_flag must contain only 0 and 1 values.",
        column="default_flag",
        check=lambda df: (
            "default_flag" not in df.columns
            or set(df["default_flag"].dropna().unique()).issubset({0, 1, 0.0, 1.0})
        ),
        severity="ERROR",
        expected="default_flag in {0, 1}",
    ),
    DataQualityRule(
        name="default_rate_plausible",
        description=(
            "Default rate must be between 1% and 25%."
            " Outside this range suggests data leakage or sampling error."
        ),
        column="default_flag",
        check=lambda df: (
            "default_flag" not in df.columns
            or 0.01 <= float(df["default_flag"].mean()) <= 0.25
        ),
        severity="WARNING",
        expected="1% <= default_rate <= 25%",
    ),
    # ── Cross-field consistency ────────────────────────────────────────────
    DataQualityRule(
        name="annual_fee_product_consistency",
        description=(
            "annual_fee > 0 is only valid for fee-bearing products (premium, secured)."
            " All other product types must have annual_fee = 0."
        ),
        column="annual_fee",
        check=lambda df: (
            "annual_fee" not in df.columns
            or "product" not in df.columns
            or bool(
                df.loc[
                    (pd.to_numeric(df["annual_fee"], errors="coerce").fillna(0) > 0)
                    & (~df["product"].isin(_FEE_BEARING_PRODUCTS)),
                ].empty
            )
        ),
        severity="ERROR",
        expected=(
            "annual_fee > 0 only when product in"
            f" {sorted(_FEE_BEARING_PRODUCTS)}"
        ),
    ),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_expectations(
    df: pd.DataFrame,
    rules: List[DataQualityRule],
    dataset_name: str,
) -> DataQualityReport:
    """Run all rules against *df* and return a ``DataQualityReport``.

    Each rule is executed inside a try/except so a single broken rule does not
    abort the entire suite.  Exceptions are recorded as failures.

    Parameters
    ----------
    df :
        DataFrame to validate.
    rules :
        List of ``DataQualityRule`` objects.
    dataset_name :
        Logical name used in the report (e.g. ``"cc_pd_training"``).

    Returns
    -------
    DataQualityReport
    """
    run_at = datetime.now(timezone.utc).isoformat()
    errors: List[dict] = []
    warnings: List[dict] = []
    passed_count = 0

    for rule in rules:
        try:
            result = rule.check(df)
        except Exception as exc:
            result = False
            logger.warning("Rule '%s' raised an exception: %s", rule.name, exc)
            failure_detail: dict[str, Any] = {
                "rule_name": rule.name,
                "description": rule.description,
                "column": rule.column,
                "expected": rule.expected,
                "exception": str(exc),
            }
        else:
            failure_detail = {
                "rule_name": rule.name,
                "description": rule.description,
                "column": rule.column,
                "expected": rule.expected,
                "exception": None,
            }

        if result:
            passed_count += 1
            logger.debug("PASS  [%s] %s", rule.severity, rule.name)
        else:
            logger.warning("FAIL  [%s] %s — %s", rule.severity, rule.name, rule.description)
            if rule.severity == "ERROR":
                errors.append(failure_detail)
            else:
                warnings.append(failure_detail)

    failed_count = len(errors) + len(warnings)
    total = len(rules)
    quality_score = round(passed_count / total, 4) if total else 1.0

    report = DataQualityReport(
        dataset_name=dataset_name,
        run_at=run_at,
        total_rules=total,
        passed=passed_count,
        failed=failed_count,
        errors=errors,
        warnings=warnings,
        quality_score=quality_score,
        gate_passed=len(errors) == 0,
    )

    logger.info(
        "Data quality run complete — %s: %d/%d rules passed (score=%.2f, gate=%s)",
        dataset_name, passed_count, total, quality_score,
        "PASS" if report.gate_passed else "FAIL",
    )
    return report


def assert_quality_gate(report: DataQualityReport) -> None:
    """Raise ``DataQualityGateError`` if any ERROR rule failed.

    This is the hard-stop guard placed before model training or data ingestion.
    The exception message lists every failing ERROR rule by name.

    Parameters
    ----------
    report :
        Result from ``run_expectations()``.
    """
    if not report.gate_passed:
        raise DataQualityGateError(report)


def save_report(report: DataQualityReport, output_dir: Path) -> Path:
    """Serialise *report* to a timestamped JSON file in *output_dir*.

    Parameters
    ----------
    report :
        Result from ``run_expectations()``.
    output_dir :
        Directory to write the report to.  Created if it does not exist.

    Returns
    -------
    Path to the written file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Use run_at timestamp for the filename (replace colons for filesystem safety)
    ts = report.run_at.replace(":", "-").replace("+", "").split(".")[0]
    path = output_dir / f"{report.dataset_name}_dq_{ts}.json"

    path.write_text(
        json.dumps(dataclasses.asdict(report), indent=2),
        encoding="utf-8",
    )
    logger.info("Data quality report saved → %s", path)
    return path
