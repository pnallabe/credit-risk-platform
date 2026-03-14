"""
Synthetic loan application dataset generator.

Usage:
    python data/generate_synthetic_data.py [--rows N]

Outputs:
    data/raw/loan_applications.parquet       (train set, 90%)
    data/raw/loan_applications_test.parquet  (held-out test set, 10%)
"""

import argparse
import os
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker("en_US")
rng = np.random.default_rng(42)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMPLOYMENT_STATUSES = ["employed", "self-employed", "unemployed", "retired"]
LOAN_PURPOSES = [
    "personal",
    "auto",
    "home_improvement",
    "medical",
    "education",
    "debt_consolidation",
]
LOAN_TERMS = [12, 24, 36, 48, 60]
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def generate_records(n: int) -> pd.DataFrame:
    """Generate *n* synthetic loan application records."""

    # ── Demographic / identity ──────────────────────────────────────────────
    application_ids = [str(uuid.uuid4()) for _ in range(n)]
    customer_ids = [str(uuid.uuid4()) for _ in range(n)]
    submitted_at = pd.to_datetime(
        rng.integers(
            pd.Timestamp("2022-01-01").value,
            pd.Timestamp("2025-12-31").value,
            size=n,
        )
    )

    # ── Credit / financial ──────────────────────────────────────────────────
    credit_score = rng.integers(300, 851, size=n)
    annual_income = np.round(
        np.exp(rng.normal(np.log(65_000), 0.6, size=n)), 2
    ).clip(15_000, 500_000)

    employment_status = rng.choice(
        EMPLOYMENT_STATUSES,
        size=n,
        p=[0.60, 0.20, 0.12, 0.08],
    )

    # Tenure: employed/self-employed get real values; others 0
    employer_tenure_months = np.where(
        np.isin(employment_status, ["employed", "self-employed"]),
        rng.integers(1, 361, size=n),
        0,
    ).astype(int)

    debt_to_income_ratio = np.round(
        rng.beta(2, 5, size=n) * 0.65, 4
    ).clip(0.0, 0.65)

    existing_debt_amount = np.round(annual_income * debt_to_income_ratio * rng.uniform(0.8, 1.2, size=n), 2)

    # ── Loan details ────────────────────────────────────────────────────────
    loan_amount = np.round(
        rng.uniform(1_000, 100_000, size=n), 2
    )
    loan_purpose = rng.choice(LOAN_PURPOSES, size=n)
    loan_term_months = rng.choice(LOAN_TERMS, size=n)

    # ── Credit history ──────────────────────────────────────────────────────
    num_open_accounts = rng.integers(0, 21, size=n)
    num_derogatory_marks = rng.choice(
        [0, 1, 2, 3, 4, 5],
        size=n,
        p=[0.55, 0.22, 0.12, 0.06, 0.03, 0.02],
    )

    # ~30 % of records have no recent delinquency (null)
    months_since_last_delinquency = np.where(
        rng.random(size=n) < 0.30,
        np.nan,
        rng.integers(1, 121, size=n).astype(float),
    )

    # ── Geography ───────────────────────────────────────────────────────────
    state = rng.choice(US_STATES, size=n)
    zip_code_prefix = [f"{rng.integers(100, 999):03d}" for _ in range(n)]

    # ── Target: default_flag ────────────────────────────────────────────────
    # Logistic formula; target ~12 % overall default rate
    log_odds = (
        -4.5
        + (-0.005) * (credit_score - 600)          # higher score → lower default
        + 3.5 * debt_to_income_ratio                # higher DTI → higher default
        + (-0.000005) * annual_income               # higher income → lower default
        + 0.003 * (loan_term_months - 36)           # longer term → higher default
        + 0.15 * num_derogatory_marks               # more marks → higher default
    )
    default_prob = _sigmoid(log_odds)
    # Calibrate to ~12 % mean
    default_prob = default_prob / default_prob.mean() * 0.12
    default_prob = default_prob.clip(0.0, 1.0)
    default_flag = rng.random(size=n) < default_prob

    df = pd.DataFrame(
        {
            "application_id": application_ids,
            "customer_id": customer_ids,
            "submitted_at": submitted_at,
            "credit_score": credit_score,
            "annual_income": annual_income,
            "employment_status": employment_status,
            "employer_tenure_months": employer_tenure_months,
            "debt_to_income_ratio": debt_to_income_ratio,
            "existing_debt_amount": existing_debt_amount,
            "loan_amount": loan_amount,
            "loan_purpose": loan_purpose,
            "loan_term_months": loan_term_months.astype(int),
            "num_open_accounts": num_open_accounts,
            "num_derogatory_marks": num_derogatory_marks,
            "months_since_last_delinquency": months_since_last_delinquency,
            "state": state,
            "zip_code_prefix": zip_code_prefix,
            "default_flag": default_flag,
        }
    )

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic loan application data")
    parser.add_argument(
        "--rows",
        type=int,
        default=100_000,
        help="Total number of records to generate (default: 100,000; max recommended: 10,000,000)",
    )
    args = parser.parse_args()

    n = args.rows
    print(f"Generating {n:,} synthetic loan application records …")

    df = generate_records(n)

    # ── Split 90 / 10 ────────────────────────────────────────────────────────
    test_size = max(1, int(n * 0.10))
    test_idx = rng.choice(len(df), size=test_size, replace=False)
    mask = np.zeros(len(df), dtype=bool)
    mask[test_idx] = True

    df_train = df[~mask].reset_index(drop=True)
    df_test = df[mask].reset_index(drop=True)

    # ── Save ─────────────────────────────────────────────────────────────────
    out_dir = Path(__file__).parent / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)

    train_path = out_dir / "loan_applications.parquet"
    test_path = out_dir / "loan_applications_test.parquet"

    df_train.to_parquet(train_path, index=False)
    df_test.to_parquet(test_path, index=False)

    default_rate = df["default_flag"].mean()
    print(f"  Train rows : {len(df_train):,}")
    print(f"  Test rows  : {len(df_test):,}")
    print(f"  Default rate: {default_rate:.2%}")
    print(f"  Saved train → {train_path}")
    print(f"  Saved test  → {test_path}")


if __name__ == "__main__":
    main()
