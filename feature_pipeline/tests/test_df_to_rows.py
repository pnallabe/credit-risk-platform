"""Tests for the vectorised _df_to_rows implementation (PROMPT-01).

Two test categories:
1. Correctness: both old (iterrows) and new (to_dict) implementations produce
   identical output for a 10-row sample.
2. Benchmark: the new implementation is at least 2× faster than the old one
   on a 100 000-row DataFrame.
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List

import pandas as pd
import pytest

from feature_pipeline.feature_store import _build_row, _df_to_rows, _ADDITIONAL_FEATURES


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VERSION = "1.0.0"
_TS = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_AOD = date(2024, 1, 15)


def _make_df(n: int) -> pd.DataFrame:
    """Create a minimal feature DataFrame of *n* rows."""
    return pd.DataFrame(
        {
            "application_id": [str(uuid.uuid4()) for _ in range(n)],
            "credit_utilization": [0.3 + (i % 10) * 0.01 for i in range(n)],
            "income_stability_score": [0.7 + (i % 5) * 0.01 for i in range(n)],
            "repayment_capacity": [0.5 + (i % 7) * 0.01 for i in range(n)],
            "debt_service_coverage": [1.2 + (i % 3) * 0.1 for i in range(n)],
            "credit_age_score": [0.4 + (i % 4) * 0.05 for i in range(n)],
            "derogatory_penalty": [0.0 + (i % 2) * 0.1 for i in range(n)],
            "months_since_delinquency": [i % 24 for i in range(n)],
            "log_loan_amount": [10.0 + (i % 6) * 0.2 for i in range(n)],
            "log_annual_income": [11.0 + (i % 8) * 0.1 for i in range(n)],
            "dti_x_loan_amount": [0.4 + (i % 5) * 0.02 for i in range(n)],
            "employment_encoded": [i % 3 for i in range(n)],
        }
    )


# ---------------------------------------------------------------------------
# Old (iterrows-based) reference implementation — reproduced inline so we can
# benchmark it even after the production code has been updated.
# ---------------------------------------------------------------------------

def _build_row_old(row: pd.Series, version: str, event_timestamp: datetime, as_of_date: date) -> Dict[str, Any]:
    """Verbatim copy of the pre-fix _build_row using pd.Series.index."""
    feature_json = {col: row[col] for col in _ADDITIONAL_FEATURES if col in row.index}
    return {
        "application_id": row["application_id"],
        "feature_set_version": version,
        "event_timestamp": event_timestamp.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "credit_utilization": float(row.get("credit_utilization", 0.0)),
        "income_stability_score": float(row.get("income_stability_score", 0.0)),
        "repayment_capacity": float(row.get("repayment_capacity", 0.0)),
        "debt_service_coverage_ratio": float(row.get("debt_service_coverage", 0.0)),
        "credit_age_months": None,
        "payment_history_score": None,
        "feature_json": feature_json,
    }


def _df_to_rows_old(
    df: pd.DataFrame,
    version: str,
    event_timestamp: datetime,
    as_of_date: date,
) -> List[Dict[str, Any]]:
    """Verbatim copy of the pre-fix _df_to_rows using iterrows()."""
    return [_build_row_old(row, version, event_timestamp, as_of_date) for _, row in df.iterrows()]


# ---------------------------------------------------------------------------
# Correctness test
# ---------------------------------------------------------------------------

def test_df_to_rows_correctness():
    """New vectorised implementation produces identical output to iterrows for 10 rows."""
    df = _make_df(10)

    old_rows = _df_to_rows_old(df, _VERSION, _TS, _AOD)
    new_rows = _df_to_rows(df, _VERSION, _TS, _AOD)

    assert len(new_rows) == len(old_rows), (
        f"Row count mismatch: old={len(old_rows)}, new={len(new_rows)}"
    )

    for i, (old, new) in enumerate(zip(old_rows, new_rows)):
        # Compare every key individually for clearer failure messages.
        for key in old:
            assert key in new, f"Row {i}: key '{key}' missing from new output"
            assert old[key] == new[key], (
                f"Row {i}, key '{key}': old={old[key]!r}, new={new[key]!r}"
            )
        # Ensure no extra keys in the new output.
        extra = set(new) - set(old)
        assert not extra, f"Row {i}: new output has unexpected extra keys: {extra}"


# ---------------------------------------------------------------------------
# Benchmark test
# ---------------------------------------------------------------------------

def test_benchmark_df_to_rows():
    """Vectorised _df_to_rows is at least 2× faster than iterrows on 100 000 rows."""
    df = _make_df(100_000)

    # Warm up (avoid import/JIT noise on first call)
    _df_to_rows_old(df.head(10), _VERSION, _TS, _AOD)
    _df_to_rows(df.head(10), _VERSION, _TS, _AOD)

    t0 = time.perf_counter()
    _df_to_rows_old(df, _VERSION, _TS, _AOD)
    old_elapsed = time.perf_counter() - t0

    t1 = time.perf_counter()
    _df_to_rows(df, _VERSION, _TS, _AOD)
    new_elapsed = time.perf_counter() - t1

    speedup = old_elapsed / new_elapsed if new_elapsed > 0 else float("inf")
    assert speedup >= 2.0, (
        f"Expected new implementation to be >= 2× faster than iterrows, "
        f"but got {speedup:.2f}× "
        f"(old={old_elapsed:.3f}s, new={new_elapsed:.3f}s on 100k rows)"
    )
