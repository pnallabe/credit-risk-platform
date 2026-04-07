"""
Massive synthetic LOANS dataset generator.

Generates a complete loans ecosystem:
  - customers           (default 500 000)
  - loan_products       (9 product types)
  - loan_applications   (default 1 000 000)
  - loans               (funded ~70%)
  - loan_payments       (full payment schedules)
  - loan_modifications  (5% of active loans)
  - credit_bureau_pulls (1-3 per application)

Usage:
    python data/generate_loans_data.py [--customers N] [--applications N] [--threads T]

Outputs (Parquet, gzip-compressed) in data/raw/loans/:
    customers.parquet
    loan_products.parquet
    loan_applications.parquet
    loans.parquet
    loan_payments.parquet
    loan_modifications.parquet
    credit_bureau_pulls.parquet
"""

import argparse
import hashlib
import math
import os
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

# ─── RNG & seeds ─────────────────────────────────────────────────────────────
rng = np.random.default_rng(42)
fake = Faker("en_US")
Faker.seed(42)

# ─── Constants ────────────────────────────────────────────────────────────────
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY",
]
STATE_WEIGHTS = [  # rough population weighting
    0.015,0.003,0.023,0.009,0.115,0.018,0.011,0.003,0.065,0.033,0.004,0.006,
    0.038,0.020,0.010,0.009,0.013,0.014,0.004,0.019,0.021,0.030,0.017,0.009,
    0.018,0.003,0.006,0.009,0.004,0.028,0.006,0.060,0.031,0.002,0.035,0.012,
    0.013,0.038,0.003,0.015,0.003,0.021,0.087,0.010,0.002,0.025,0.024,0.006,
    0.018,0.002,
]
EMPLOYMENT_STATUSES = ["employed","self-employed","unemployed","retired","student"]
EMP_PROBS = [0.55, 0.18, 0.10, 0.10, 0.07]
LOAN_TYPES = [
    "personal","auto","mortgage","student","small_business",
    "home_equity","medical","green_energy","debt_consolidation",
]
LOAN_TYPE_PROBS = [0.22,0.18,0.20,0.08,0.06,0.07,0.05,0.04,0.10]
CHANNELS = ["online","branch","mobile","partner","phone"]
CHANNEL_PROBS = [0.45,0.15,0.28,0.07,0.05]
LOAN_STATUSES = ["current","delinquent_30","delinquent_60","delinquent_90","default","charged_off","paid_off","in_forbearance"]
LOAN_STATUS_PROBS = [0.76,0.055,0.025,0.015,0.025,0.015,0.095,0.010]
MODIFICATION_TYPES = ["forbearance","deferral","rate_reduction","term_extension","principal_reduction","covid_relief"]
BUREAUS = ["Equifax","Experian","TransUnion"]
PAYMENT_METHODS = ["ach","wire","check","card","cash","auto_pay"]
PAYMENT_METHOD_PROBS = [0.55,0.02,0.10,0.08,0.05,0.20]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -20, 20)))


def _random_date_series(n: int, start: str, end: str, seed: int = 42) -> pd.Series:
    r = np.random.default_rng(seed)
    s = pd.Timestamp(start).value
    e = pd.Timestamp(end).value
    return pd.to_datetime(r.integers(s, e, size=n))


# ─── Product catalog ──────────────────────────────────────────────────────────

PRODUCT_CATALOG = [
    {
        "product_code": "PERS-STD", "product_name": "Personal Loan Standard",
        "loan_type": "personal", "min_amount": 1000, "max_amount": 50000,
        "min_term_months": 12, "max_term_months": 60, "base_interest_rate": 0.1199,
        "origination_fee_pct": 0.02, "min_credit_score": 620,
    },
    {
        "product_code": "AUTO-NEW", "product_name": "Auto Loan – New Vehicle",
        "loan_type": "auto", "min_amount": 5000, "max_amount": 100000,
        "min_term_months": 24, "max_term_months": 84, "base_interest_rate": 0.0599,
        "origination_fee_pct": 0.0, "min_credit_score": 580,
    },
    {
        "product_code": "MORT-30", "product_name": "30-Year Fixed Mortgage",
        "loan_type": "mortgage", "min_amount": 50000, "max_amount": 2000000,
        "min_term_months": 360, "max_term_months": 360, "base_interest_rate": 0.0699,
        "origination_fee_pct": 0.01, "min_credit_score": 640,
    },
    {
        "product_code": "STUD-FED", "product_name": "Student Loan – Federal",
        "loan_type": "student", "min_amount": 1000, "max_amount": 50000,
        "min_term_months": 120, "max_term_months": 120, "base_interest_rate": 0.0499,
        "origination_fee_pct": 0.01, "min_credit_score": 0,
    },
    {
        "product_code": "SBL-STD", "product_name": "Small Business Loan",
        "loan_type": "small_business", "min_amount": 10000, "max_amount": 500000,
        "min_term_months": 12, "max_term_months": 84, "base_interest_rate": 0.0899,
        "origination_fee_pct": 0.025, "min_credit_score": 660,
    },
    {
        "product_code": "HELOC-VAR", "product_name": "Home Equity Line of Credit",
        "loan_type": "home_equity", "min_amount": 10000, "max_amount": 500000,
        "min_term_months": 60, "max_term_months": 120, "base_interest_rate": 0.0799,
        "origination_fee_pct": 0.0, "min_credit_score": 640,
    },
    {
        "product_code": "MED-FIN", "product_name": "Medical Financing",
        "loan_type": "medical", "min_amount": 500, "max_amount": 50000,
        "min_term_months": 12, "max_term_months": 60, "base_interest_rate": 0.0899,
        "origination_fee_pct": 0.01, "min_credit_score": 600,
    },
    {
        "product_code": "GREEN-SOLAR", "product_name": "Green Energy – Solar",
        "loan_type": "green_energy", "min_amount": 5000, "max_amount": 100000,
        "min_term_months": 60, "max_term_months": 144, "base_interest_rate": 0.0499,
        "origination_fee_pct": 0.005, "min_credit_score": 620,
    },
    {
        "product_code": "DEBT-CONS", "product_name": "Debt Consolidation",
        "loan_type": "debt_consolidation", "min_amount": 2000, "max_amount": 75000,
        "min_term_months": 24, "max_term_months": 60, "base_interest_rate": 0.1399,
        "origination_fee_pct": 0.03, "min_credit_score": 600,
    },
]


def generate_loan_products() -> pd.DataFrame:
    rows = []
    for p in PRODUCT_CATALOG:
        rows.append({
            "product_id": str(uuid.uuid4()),
            **p,
            "max_dti_ratio": 0.50,
            "prepayment_penalty": False,
            "is_active": True,
            "created_at": pd.Timestamp("2021-01-01", tz="UTC"),
        })
    return pd.DataFrame(rows)


# ─── Customers ────────────────────────────────────────────────────────────────

def generate_customers(n: int, seed: int = 42) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    print(f"  Generating {n:,} customers …")

    customer_ids = [str(uuid.uuid4()) for _ in range(n)]
    dob = pd.to_datetime(
        r.integers(
            pd.Timestamp("1950-01-01").value,
            pd.Timestamp("2000-12-31").value,
            size=n,
        )
    ).normalize()

    employment_status = r.choice(EMPLOYMENT_STATUSES, size=n, p=EMP_PROBS)
    annual_income = np.round(np.exp(r.normal(np.log(68_000), 0.65, size=n)), 2).clip(12_000, 800_000)
    credit_score = (
        np.clip(
            r.normal(680, 95, size=n).astype(int),
            300, 850,
        )
    )
    num_open_accounts = r.integers(0, 22, size=n)
    num_derogatory_marks = r.choice([0,1,2,3,4,5], size=n, p=[0.55,0.22,0.12,0.06,0.03,0.02])
    total_existing_debt = np.round(annual_income * r.uniform(0.0, 1.2, size=n), 2).clip(0)
    state_arr = r.choice(US_STATES, size=n, p=STATE_WEIGHTS)
    bankruptcy = r.random(size=n) < 0.02

    tenure = np.where(
        np.isin(employment_status, ["employed","self-employed"]),
        r.integers(1, 361, size=n),
        0,
    )
    score_date = pd.Timestamp("2025-01-01") - pd.to_timedelta(r.integers(0, 365, size=n), unit="D")

    df = pd.DataFrame({
        "customer_id": customer_ids,
        "date_of_birth": dob.date,
        "employment_status": employment_status,
        "annual_income": annual_income,
        "employer_tenure_months": tenure.astype(int),
        "credit_score": credit_score.astype(int),
        "credit_score_model": r.choice(["FICO8","FICO9","VantageScore4"], size=n, p=[0.70,0.20,0.10]),
        "credit_score_date": score_date.date,
        "num_open_accounts": num_open_accounts.astype(int),
        "num_derogatory_marks": num_derogatory_marks.astype(int),
        "total_existing_debt": total_existing_debt,
        "bankruptcy_flag": bankruptcy,
        "state": state_arr,
        "created_at": pd.Timestamp("2020-01-01", tz="UTC")
            + pd.to_timedelta(r.integers(0, 1460, size=n), unit="D"),
        "updated_at": pd.Timestamp("2025-01-01", tz="UTC"),
    })
    return df


# ─── Loan Applications ────────────────────────────────────────────────────────

def generate_applications_chunk(
    chunk_id: int, n: int, customer_ids: list, product_df: pd.DataFrame
) -> pd.DataFrame:
    r = np.random.default_rng(chunk_id * 9999)
    cust = r.choice(customer_ids, size=n)
    products = product_df.set_index("loan_type")
    loan_types = r.choice(LOAN_TYPES, size=n, p=LOAN_TYPE_PROBS)

    amounts = []
    terms = []
    product_ids = []
    for lt in loan_types:
        prod = products.loc[lt]
        if isinstance(prod, pd.DataFrame):
            prod = prod.iloc[0]
        lo, hi = float(prod["min_amount"]), float(prod["max_amount"])
        amt = r.uniform(lo, hi)
        tlo, thi = int(prod["min_term_months"]), int(prod["max_term_months"])
        term = r.integers(tlo // 12, thi // 12 + 1) * 12
        amounts.append(round(amt, 2))
        terms.append(int(term))
        product_ids.append(str(prod["product_id"]))

    amounts = np.array(amounts)
    terms = np.array(terms)

    applied_at = _random_date_series(n, "2022-01-01", "2026-03-01", seed=chunk_id)

    # Decision model
    cust_df = pd.DataFrame({"customer_id": cust})
    income_factor = r.lognormal(11.0, 0.7, size=n)
    credit_factor = r.normal(680, 95, size=n).clip(300, 850)

    log_odds_approve = (
        -1.5
        + 0.005 * (credit_factor - 600)
        - 0.2 * np.log1p(amounts / income_factor)
        + 0.001 * r.normal(0, 1, size=n)
    )
    approve_prob = _sigmoid(log_odds_approve).clip(0.30, 0.92)
    approved_mask = r.random(size=n) < approve_prob
    funded_mask = approved_mask & (r.random(size=n) < 0.72)

    statuses = np.where(
        funded_mask, "funded",
        np.where(approved_mask, r.choice(["approved","withdrawn"], size=n, p=[0.3,0.7]),
                 r.choice(["rejected","withdrawn","under_review"], size=n, p=[0.75,0.15,0.10]))
    )

    approved_rates = np.where(
        approved_mask,
        np.round(r.uniform(0.045, 0.28, size=n), 4),
        np.nan,
    )

    df = pd.DataFrame({
        "application_id": [str(uuid.uuid4()) for _ in range(n)],
        "customer_id": cust,
        "product_id": product_ids,
        "loan_amount": amounts,
        "loan_type": loan_types,
        "loan_purpose": r.choice(
            ["home","car","education","business","medical","travel","other"],
            size=n, p=[0.20,0.18,0.12,0.10,0.12,0.08,0.20]
        ),
        "loan_term_months": terms.astype(int),
        "credit_score_at_app": credit_factor.astype(int),
        "dti_at_app": np.round(r.beta(2, 5, size=n) * 0.65, 4),
        "annual_income_at_app": np.round(income_factor, 2),
        "status": statuses,
        "approved_amount": np.where(approved_mask, amounts * r.uniform(0.80, 1.0, size=n), np.nan),
        "approved_rate": approved_rates,
        "approved_term_months": np.where(approved_mask, terms, np.nan),
        "decision_at": np.where(approved_mask, applied_at + pd.to_timedelta(r.integers(1,15,size=n), unit="D"), pd.NaT),
        "channel": r.choice(CHANNELS, size=n, p=CHANNEL_PROBS),
        "applied_at": applied_at,
        "created_at": applied_at,
        "updated_at": applied_at,
        "_funded": funded_mask,
    })
    return df


# ─── Loans ────────────────────────────────────────────────────────────────────

def generate_loans_from_applications(apps_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 1)
    funded = apps_df[apps_df["_funded"]].copy()
    n = len(funded)
    print(f"  Generating {n:,} funded loans …")

    orig_date = funded["applied_at"] + pd.to_timedelta(r.integers(14, 60, size=n), unit="D")
    term_m = funded["approved_term_months"].fillna(funded["loan_term_months"]).astype(int).values
    maturity = orig_date + pd.to_timedelta(term_m * 30, unit="D")
    principal = funded["approved_amount"].fillna(funded["loan_amount"]).values
    rate = funded["approved_rate"].fillna(0.12).values

    # Monthly payment (annuity formula)
    r_m = rate / 12.0
    payment = np.where(
        r_m > 0,
        principal * r_m / (1 - (1 + r_m) ** (-term_m)),
        principal / term_m,
    )
    payment = np.round(payment, 2)

    # How many payments have been made?
    months_elapsed = ((pd.Timestamp("2026-03-01") - orig_date.dt.tz_localize(None)) / np.timedelta64(1, "M")).astype(int)
    months_elapsed = np.minimum(months_elapsed, term_m)
    months_elapsed = np.maximum(months_elapsed, 0)

    # Rough amortization
    principal_paid = np.minimum(
        np.round(months_elapsed * payment * 0.55, 2),  # rough split
        principal,
    )
    interest_paid = np.round(months_elapsed * payment * 0.45, 2)
    current_balance = np.maximum(principal - principal_paid, 0)

    loan_status = r.choice(LOAN_STATUSES, size=n, p=LOAN_STATUS_PROBS)
    # paid off → zero balance
    current_balance = np.where(loan_status == "paid_off", 0.0, current_balance)

    days_past_due = np.where(
        loan_status == "current", 0,
        np.where(loan_status == "delinquent_30", r.integers(30, 60, size=n),
        np.where(loan_status == "delinquent_60", r.integers(60, 90, size=n),
        np.where(loan_status == "delinquent_90", r.integers(90, 180, size=n),
        np.where(loan_status.isin(["default","charged_off"]) if hasattr(loan_status,"isin")
                 else np.isin(loan_status,["default","charged_off"]),
                 r.integers(90, 365, size=n), 0))))
    )

    last_pmt_date = orig_date + pd.to_timedelta(np.maximum(months_elapsed - 1, 0) * 30, unit="D")

    df = pd.DataFrame({
        "loan_id": [str(uuid.uuid4()) for _ in range(n)],
        "application_id": funded["application_id"].values,
        "customer_id": funded["customer_id"].values,
        "product_id": funded["product_id"].values,
        "principal_amount": np.round(principal, 2),
        "interest_rate": np.round(rate, 4),
        "annual_percentage_rate": np.round(rate + r.uniform(0.001, 0.01, size=n), 4),
        "loan_term_months": term_m.astype(int),
        "monthly_payment": payment,
        "origination_date": orig_date.dt.date,
        "first_payment_date": (orig_date + pd.DateOffset(months=1)).dt.date,
        "maturity_date": maturity.dt.date,
        "current_balance": np.round(current_balance, 2),
        "principal_paid": np.round(principal_paid, 2),
        "interest_paid": np.round(interest_paid, 2),
        "total_paid": np.round(principal_paid + interest_paid, 2),
        "loan_status": loan_status,
        "days_past_due": days_past_due.astype(int),
        "times_30dpd": r.integers(0, 4, size=n).astype(int),
        "times_60dpd": r.integers(0, 2, size=n).astype(int),
        "times_90dpd": r.integers(0, 2, size=n).astype(int),
        "last_payment_date": last_pmt_date.dt.date,
        "last_payment_amount": np.round(payment * r.uniform(0.98, 1.02, size=n), 2),
        "created_at": orig_date.dt.tz_localize("UTC"),
        "updated_at": pd.Timestamp("2026-03-01", tz="UTC"),
    })
    return df


# ─── Loan Payments ────────────────────────────────────────────────────────────

def generate_payments_for_chunk(loans_chunk: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 2)
    rows = []
    for _, row in loans_chunk.iterrows():
        months_paid = max(int(row["total_paid"] / row["monthly_payment"]), 0) if row["monthly_payment"] > 0 else 0
        months_paid = min(months_paid, int(row["loan_term_months"]))
        if months_paid == 0:
            continue

        balance = float(row["principal_amount"])
        r_m = float(row["interest_rate"]) / 12.0
        orig = pd.Timestamp(row["origination_date"])

        for m in range(1, months_paid + 1):
            due_date = orig + pd.DateOffset(months=m)
            days_shift = int(r.integers(-3, 20))
            pmt_date = due_date + timedelta(days=days_shift)
            days_late = max(days_shift, 0)

            interest_portion = round(balance * r_m, 2)
            payment_amount = float(row["monthly_payment"])
            principal_portion = round(payment_amount - interest_portion, 2)
            balance = max(balance - principal_portion, 0.0)

            rows.append({
                "payment_id": str(uuid.uuid4()),
                "loan_id": row["loan_id"],
                "customer_id": row["customer_id"],
                "payment_date": pmt_date.date(),
                "due_date": due_date.date(),
                "payment_amount": round(payment_amount, 2),
                "principal_portion": principal_portion,
                "interest_portion": interest_portion,
                "fees_portion": 0.0,
                "payment_status": "returned" if days_late > 15 and r.random() < 0.02 else "posted",
                "payment_method": r.choice(PAYMENT_METHODS, p=PAYMENT_METHOD_PROBS),
                "days_late": days_late,
                "is_prepayment": False,
                "remaining_balance": round(balance, 2),
                "created_at": pd.Timestamp(pmt_date, tz="UTC"),
            })
    return pd.DataFrame(rows)


# ─── Bureau Pulls ─────────────────────────────────────────────────────────────

def generate_bureau_pulls(apps_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 5)
    rows = []
    for _, row in apps_df.iterrows():
        n_pulls = r.integers(1, 4)
        for _ in range(n_pulls):
            rows.append({
                "pull_id": str(uuid.uuid4()),
                "customer_id": row["customer_id"],
                "application_id": row["application_id"],
                "bureau": r.choice(BUREAUS),
                "pull_type": "hard" if row["status"] in ["approved","funded","rejected"] else "soft",
                "pull_date": (pd.Timestamp(row["applied_at"]) - timedelta(days=int(r.integers(0, 5)))).date(),
                "score_returned": int(r.integers(300, 851)),
                "created_at": pd.Timestamp(row["applied_at"], tz="UTC"),
            })
    return pd.DataFrame(rows)


# ─── Modifications ────────────────────────────────────────────────────────────

def generate_modifications(loans_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 6)
    candidates = loans_df[
        loans_df["loan_status"].isin(["in_forbearance","modified","delinquent_60","delinquent_90"])
    ]
    rows = []
    for _, row in candidates.iterrows():
        rows.append({
            "modification_id": str(uuid.uuid4()),
            "loan_id": row["loan_id"],
            "modification_type": r.choice(MODIFICATION_TYPES),
            "effective_date": pd.Timestamp(row["origination_date"]) + pd.DateOffset(months=int(r.integers(3, 24))),
            "end_date": None,
            "original_rate": row["interest_rate"],
            "modified_rate": round(float(row["interest_rate"]) * r.uniform(0.7, 0.95), 4),
            "months_deferred": int(r.integers(1, 7)),
            "reason": r.choice(["job_loss","medical","covid","divorce","natural_disaster"]),
            "created_at": pd.Timestamp("2026-03-01", tz="UTC"),
        })
    return pd.DataFrame(rows)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate massive synthetic loans dataset")
    parser.add_argument("--customers", type=int, default=500_000, help="Number of customer records")
    parser.add_argument("--applications", type=int, default=1_000_000, help="Number of loan applications")
    parser.add_argument("--threads", type=int, default=4, help="Parallel threads for chunked generation")
    parser.add_argument("--skip-payments", action="store_true", help="Skip payment schedule generation (much faster)")
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "raw" / "loans"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LOANS SYNTHETIC DATA GENERATOR")
    print("=" * 60)

    # 1. Products
    print("\n[1/7] Loan Products …")
    products_df = generate_loan_products()
    products_df.to_parquet(out_dir / "loan_products.parquet", index=False, compression="gzip")
    print(f"  Saved {len(products_df):,} products → {out_dir}/loan_products.parquet")

    # 2. Customers
    print(f"\n[2/7] Customers ({args.customers:,}) …")
    customers_df = generate_customers(args.customers)
    customers_df.to_parquet(out_dir / "customers.parquet", index=False, compression="gzip")
    print(f"  Saved → {out_dir}/customers.parquet")
    customer_ids = customers_df["customer_id"].tolist()

    # 3. Applications (chunked parallel)
    print(f"\n[3/7] Loan Applications ({args.applications:,}, {args.threads} threads) …")
    chunk_size = args.applications // args.threads
    chunks = []
    with ProcessPoolExecutor(max_workers=args.threads) as exe:
        futs = {
            exe.submit(generate_applications_chunk, i, chunk_size if i < args.threads - 1
                       else args.applications - chunk_size * (args.threads - 1),
                       customer_ids, products_df): i
            for i in range(args.threads)
        }
        for fut in as_completed(futs):
            chunks.append(fut.result())
            print(f"  Chunk {futs[fut]+1}/{args.threads} done")

    apps_df = pd.concat(chunks, ignore_index=True)
    funded_pct = (apps_df["_funded"].sum() / len(apps_df)) * 100
    print(f"  Total apps: {len(apps_df):,} | Funded: {apps_df['_funded'].sum():,} ({funded_pct:.1f}%)")
    apps_out = apps_df.drop(columns=["_funded"])
    apps_out.to_parquet(out_dir / "loan_applications.parquet", index=False, compression="gzip")
    print(f"  Saved → {out_dir}/loan_applications.parquet")

    # 4. Loans
    print(f"\n[4/7] Funded Loans …")
    loans_df = generate_loans_from_applications(apps_df)
    loans_df.to_parquet(out_dir / "loans.parquet", index=False, compression="gzip")
    print(f"  Saved {len(loans_df):,} loans → {out_dir}/loans.parquet")

    # 5. Payments (chunked)
    if not args.skip_payments:
        print(f"\n[5/7] Loan Payments (parallel, {args.threads} threads) …")
        loan_chunks = np.array_split(loans_df, args.threads)
        pmt_parts = []
        with ProcessPoolExecutor(max_workers=args.threads) as exe:
            futs = {exe.submit(generate_payments_for_chunk, c, i): i for i, c in enumerate(loan_chunks)}
            for fut in as_completed(futs):
                pmt_parts.append(fut.result())
                print(f"  Payment chunk {futs[fut]+1}/{args.threads} done")
        payments_df = pd.concat(pmt_parts, ignore_index=True)
        payments_df.to_parquet(out_dir / "loan_payments.parquet", index=False, compression="gzip")
        print(f"  Saved {len(payments_df):,} payments → {out_dir}/loan_payments.parquet")
    else:
        print("\n[5/7] Skipped payment generation (--skip-payments)")

    # 6. Bureau Pulls (sample 200k apps)
    print(f"\n[6/7] Credit Bureau Pulls (sampled) …")
    sample_apps = apps_df.sample(min(200_000, len(apps_df)), random_state=42)
    bureau_df = generate_bureau_pulls(sample_apps)
    bureau_df.to_parquet(out_dir / "credit_bureau_pulls.parquet", index=False, compression="gzip")
    print(f"  Saved {len(bureau_df):,} pulls → {out_dir}/credit_bureau_pulls.parquet")

    # 7. Modifications
    print(f"\n[7/7] Loan Modifications …")
    mods_df = generate_modifications(loans_df)
    mods_df.to_parquet(out_dir / "loan_modifications.parquet", index=False, compression="gzip")
    print(f"  Saved {len(mods_df):,} modifications → {out_dir}/loan_modifications.parquet")

    print("\n" + "=" * 60)
    print("LOANS GENERATION COMPLETE")
    print("=" * 60)
    for f in sorted(out_dir.glob("*.parquet")):
        size_mb = f.stat().st_size / (1024 ** 2)
        print(f"  {f.name:<45} {size_mb:>7.1f} MB")


if __name__ == "__main__":
    main()
