"""
data/generate_personal_loans_simulated.py
==========================================
Generate 750,000 personal loan applications (2015–2026) using epoch-based
policy lookup and the personal loan origination engine.

Outputs (gzip-compressed Parquet) in data/raw/loans/:
    personal_loan_applications.parquet
    personal_loans_funded.parquet
    personal_loan_payments.parquet
    personal_loan_credit_bureau_pulls.parquet
    personal_loan_modifications.parquet

Usage:
    python data/generate_personal_loans_simulated.py
    python data/generate_personal_loans_simulated.py \\
        --applications 750000 --threads 8 \\
        --db-path policy_versions.db --output-dir data/raw/loans/
"""
from __future__ import annotations

import argparse
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.personal_loan_origination_policy import evaluate_batch as pl_evaluate_batch
from decision_engine.policy_version_store import PolicyVersionStore, PolicyVersionNotFoundError

# ── Constants ─────────────────────────────────────────────────────────────────

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY",
]
STATE_WEIGHTS = [
    0.015,0.003,0.023,0.009,0.115,0.018,0.011,0.003,0.065,0.033,0.004,0.006,
    0.038,0.020,0.010,0.009,0.013,0.014,0.004,0.019,0.021,0.030,0.017,0.009,
    0.018,0.003,0.006,0.009,0.004,0.028,0.006,0.060,0.031,0.002,0.035,0.012,
    0.013,0.038,0.003,0.015,0.003,0.021,0.087,0.010,0.002,0.025,0.024,0.006,
    0.018,0.002,
]
CHANNELS = ["online", "branch", "mobile", "partner", "phone"]
CHANNEL_PROBS = [0.52, 0.20, 0.15, 0.10, 0.03]
EMPLOYMENT_STATUSES = ["employed", "self_employed", "unemployed", "retired", "student"]
EMP_PROBS = [0.65, 0.15, 0.05, 0.10, 0.05]
LOAN_PURPOSES = ["debt_consolidation", "medical", "home_improvement", "other"]
LOAN_PURPOSE_PROBS = [0.35, 0.20, 0.25, 0.20]
PRODUCTS = ["PERS-STD", "DEBT-CONS"]
PRODUCT_PROBS = [0.65, 0.35]
TERM_OPTIONS = [24, 36, 48, 60, 72]
BUREAUS = ["Equifax", "Experian", "TransUnion"]
PAYMENT_METHODS = ["ach", "wire", "check", "card", "cash", "auto_pay"]
PAYMENT_METHOD_PROBS = [0.55, 0.02, 0.10, 0.08, 0.05, 0.20]
MODIFICATION_TYPES = [
    "forbearance", "deferral", "rate_reduction", "term_extension",
    "principal_reduction", "covid_relief"
]
MODIFICATION_REASONS = [
    "job_loss", "medical", "covid", "divorce", "natural_disaster"
]

# Loan status distribution (similar to generate_loans_data.py but with in_forbearance/modified)
LOAN_STATUSES = [
    "current", "30dpd", "60dpd", "90dpd", "default",
    "charged_off", "paid_off", "in_forbearance", "modified",
]
LOAN_STATUS_PROBS = [0.76, 0.04, 0.02, 0.015, 0.02, 0.015, 0.10, 0.02, 0.01]

# Year distribution weights — peak 2017-2022
YEAR_WEIGHTS = {
    2015: 0.04, 2016: 0.05, 2017: 0.08, 2018: 0.09, 2019: 0.09,
    2020: 0.09, 2021: 0.12, 2022: 0.14, 2023: 0.12, 2024: 0.11,
    2025: 0.05, 2026: 0.02,
}

TODAY = pd.Timestamp("2026-04-23")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _weighted_random_dates(n: int, rng: np.random.Generator) -> pd.DatetimeIndex:
    """Generate n application dates weighted toward 2017-2022 peak years."""
    years = np.array(list(YEAR_WEIGHTS.keys()))
    weights = np.array(list(YEAR_WEIGHTS.values()))
    weights = weights / weights.sum()
    chosen_years = rng.choice(years, size=n, p=weights)

    # Random day within each year
    day_of_year = rng.integers(0, 365, size=n)
    dates = pd.to_datetime(chosen_years * 10000 + 101, format="%Y%m%d") + pd.to_timedelta(day_of_year, unit="D")
    # Clip to not exceed TODAY
    offsets = pd.to_timedelta(rng.integers(1, 30, size=n), unit="D")
    fallback = TODAY - offsets
    dates = pd.DatetimeIndex(
        [d if d <= TODAY else fallback[i] for i, d in enumerate(dates)]
    )
    return dates


def _get_policy_cache(db_path: str, dates: pd.DatetimeIndex) -> dict:
    """Build a {period_str -> params_dict} cache, one lookup per month bucket."""
    try:
        store = PolicyVersionStore(db_path=Path(db_path))
    except Exception:
        return {}

    months = pd.DatetimeIndex(dates).to_period("M").unique()
    cache: dict = {}
    for period in months:
        dt = datetime(period.year, period.month, 1, tzinfo=timezone.utc)
        try:
            pv = store.get_as_of(dt)
            cache[str(period)] = pv.parameters.get("PERSONAL_LOAN", pv.parameters)
        except PolicyVersionNotFoundError:
            cache[str(period)] = None
    return cache


def _monthly_payment(principal: np.ndarray, annual_rate: np.ndarray, term: np.ndarray) -> np.ndarray:
    r = annual_rate / 100.0 / 12.0
    with np.errstate(divide="ignore", invalid="ignore"):
        pmt = np.where(
            r == 0,
            principal / np.maximum(term, 1),
            principal * r * (1 + r) ** term / ((1 + r) ** term - 1),
        )
    return np.round(np.nan_to_num(pmt, nan=0.0), 2)


# ── Application generation ────────────────────────────────────────────────────

def generate_applications(n: int, db_path: str, seed: int = 42) -> pd.DataFrame:
    """Generate n personal loan applications with policy-aware decisions."""
    rng = np.random.default_rng(seed)
    print(f"  Generating {n:,} application features …")

    # Demographics
    fico = np.clip(rng.normal(680, 95, n).astype(int), 300, 850)
    annual_income = np.round(np.exp(rng.normal(np.log(65_000), 0.65, n)), 2).clip(12_000, 600_000)
    dti = np.round(rng.beta(2, 5, n) * 0.65, 4).clip(0.05, 0.70)
    num_derog = rng.choice([0, 1, 2, 3, 4, 5], n, p=[0.55, 0.22, 0.12, 0.06, 0.03, 0.02])
    emp_status = rng.choice(EMPLOYMENT_STATUSES, n, p=EMP_PROBS)
    sw = np.array(STATE_WEIGHTS); sw /= sw.sum()
    state = rng.choice(US_STATES, n, p=sw)
    channel = rng.choice(CHANNELS, n, p=CHANNEL_PROBS)
    age = rng.integers(20, 75, n)

    # Product & loan terms
    products = rng.choice(PRODUCTS, n, p=PRODUCT_PROBS)
    purposes = np.where(
        products == "DEBT-CONS",
        "debt_consolidation",
        rng.choice(LOAN_PURPOSES, n, p=LOAN_PURPOSE_PROBS),
    )
    terms = rng.choice(TERM_OPTIONS, n)
    requested_amounts = np.round(rng.uniform(2_000, 55_000, n), -2)

    # Fraud & PD scores
    pd_score = np.clip(rng.beta(1.5, 12, n), 0.001, 0.999)
    fraud_score = np.clip(rng.beta(1, 50, n), 0.0, 0.999)

    # Application dates
    applied_at = _weighted_random_dates(n, rng)
    customer_ids = [str(uuid.uuid4()) for _ in range(n)]
    application_ids = [str(uuid.uuid4()) for _ in range(n)]

    df = pd.DataFrame({
        "application_id": application_ids,
        "customer_id": customer_ids,
        "applied_at": applied_at,
        "product_code": products,
        "loan_purpose": purposes,
        "fico_score": fico,
        "annual_income": annual_income,
        "dti": dti,
        "num_derog_marks": num_derog,
        "employment_status": emp_status,
        "state": state,
        "channel": channel,
        "age": age,
        "requested_amount": requested_amounts,
        "term_months": terms,
        "pd_score": pd_score,
        "fraud_score": fraud_score,
    })

    # Policy-aware evaluation: group by month bucket
    print("  Running policy-aware batch evaluation …")
    policy_cache = _get_policy_cache(db_path, applied_at)

    month_period = pd.DatetimeIndex(df["applied_at"]).to_period("M").astype(str)
    df["_month_bucket"] = month_period

    result_frames = []
    for bucket, group in df.groupby("_month_bucket", sort=True):
        params = policy_cache.get(bucket)  # None → use defaults
        eval_result = pl_evaluate_batch(group, policy_params=params)
        result_frames.append(eval_result)

    df_evaluated = pd.concat(result_frames, ignore_index=True)

    # Extract decision columns back into the main frame (align by index)
    decision_cols = [
        "decision_outcome", "fico_tier", "dti_tier", "verification_required",
        "approved_amount", "approved_rate", "term_months_out",
        "monthly_payment", "apr", "fcra_reason_codes",
    ]
    for col in decision_cols:
        if col in df_evaluated.columns:
            df[col] = df_evaluated[col].values

    # Rename term_months_out to avoid clash
    if "term_months_out" in df.columns:
        df["approved_term_months"] = df["term_months_out"]
        df.drop(columns=["term_months_out"], inplace=True)

    # policy_version_id: look up by month bucket
    try:
        store = PolicyVersionStore(db_path=Path(db_path))
        pv_id_map: dict = {}
        pv_tag_map: dict = {}
        for bucket in df["_month_bucket"].unique():
            dt = datetime(
                int(bucket[:4]), int(bucket[5:7]), 1, tzinfo=timezone.utc
            )
            try:
                pv = store.get_as_of(dt)
                pv_id_map[bucket] = pv.id
                pv_tag_map[bucket] = pv.version_tag
            except PolicyVersionNotFoundError:
                pv_id_map[bucket] = None
                pv_tag_map[bucket] = None
        df["policy_version_id"] = df["_month_bucket"].map(pv_id_map)
        df["policy_version_tag"] = df["_month_bucket"].map(pv_tag_map)
    except Exception:
        df["policy_version_id"] = None
        df["policy_version_tag"] = None

    df.drop(columns=["_month_bucket"], inplace=True)
    return df


# ── Funded loans ──────────────────────────────────────────────────────────────

def generate_funded_loans(apps_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Extract approved applications and create funded loan records."""
    rng = np.random.default_rng(seed + 1)

    approved = apps_df[apps_df["decision_outcome"].isin(["APPROVE", "COUNTER_OFFER"])].copy()
    n = len(approved)
    print(f"  Generating {n:,} funded loans …")

    applied_at = pd.DatetimeIndex(approved["applied_at"])
    # Origination: 5-30 days after application
    orig_days = rng.integers(5, 31, n)
    orig_date = applied_at + pd.to_timedelta(orig_days, unit="D")
    orig_date = orig_date.where(orig_date <= TODAY, TODAY)

    principal = approved["approved_amount"].fillna(approved["requested_amount"]).values
    rate = approved["approved_rate"].values
    term = approved["approved_term_months"].fillna(approved["term_months"]).fillna(36).astype(int).values
    payment = _monthly_payment(principal, rate, term)

    maturity = orig_date + pd.to_timedelta(term * 30, unit="D")

    # Loan status with realistic distribution
    loan_status = rng.choice(LOAN_STATUSES, n, p=LOAN_STATUS_PROBS)

    # Balance calculation
    orig_date_naive = pd.DatetimeIndex([d.tz_localize(None) if hasattr(d, "tz") and d.tz is not None else d for d in orig_date])
    months_elapsed = np.clip(
        ((TODAY - orig_date_naive).days / 30.0).astype(int),
        0, term,
    )
    r_m = rate / 100.0 / 12.0
    # Precise amortization: remaining balance
    with np.errstate(divide="ignore", invalid="ignore"):
        remaining_bal = np.where(
            r_m == 0,
            principal - payment * months_elapsed,
            principal * (1 + r_m) ** term / ((1 + r_m) ** term - 1)
            * ((1 + r_m) ** term - (1 + r_m) ** months_elapsed) / r_m,
        )
    remaining_bal = np.clip(np.round(np.nan_to_num(remaining_bal, nan=0.0), 2), 0, principal)
    remaining_bal = np.where(loan_status == "paid_off", 0.0, remaining_bal)
    remaining_bal = np.where(
        np.isin(loan_status, ["charged_off", "default"]),
        remaining_bal * rng.uniform(0.2, 0.8, n),
        remaining_bal,
    )

    df = pd.DataFrame({
        "loan_id": [str(uuid.uuid4()) for _ in range(n)],
        "application_id": approved["application_id"].values,
        "customer_id": approved["customer_id"].values,
        "product_code": approved["product_code"].values,
        "loan_purpose": approved["loan_purpose"].values,
        "principal_amount": np.round(principal, 2),
        "interest_rate": np.round(rate / 100.0, 6),
        "annual_percentage_rate": np.round(rate / 100.0 + rng.uniform(0.001, 0.01, n), 6),
        "loan_term_months": term,
        "monthly_payment": payment,
        "origination_date": orig_date.date,
        "maturity_date": maturity.date,
        "current_balance": np.round(remaining_bal, 2),
        "loan_status": loan_status,
        "fico_score_at_origination": approved["fico_score"].values,
        "dti_at_origination": approved["dti"].values,
        "annual_income_at_origination": approved["annual_income"].values,
        "state": approved["state"].values,
        "channel": approved["channel"].values,
        "policy_version_id": approved["policy_version_id"].values
            if "policy_version_id" in approved.columns else None,
        "policy_version_tag": approved["policy_version_tag"].values
            if "policy_version_tag" in approved.columns else None,
        "fico_tier": approved["fico_tier"].values if "fico_tier" in approved.columns else None,
        "dti_tier": approved["dti_tier"].values if "dti_tier" in approved.columns else None,
        "apr": approved["apr"].values if "apr" in approved.columns else rate / 100.0,
        "verification_required": approved["verification_required"].values
            if "verification_required" in approved.columns else None,
    })
    return df


# ── Payments (per-chunk worker) ───────────────────────────────────────────────

def _payments_for_chunk(loans_chunk_records: list, seed: int = 0) -> list:
    """Generate payment schedules for a chunk of loans. Returns list of dicts."""
    rng = np.random.default_rng(seed + 2)
    rows = []
    for rec in loans_chunk_records:
        loan_id    = rec["loan_id"]
        customer_id = rec["customer_id"]
        principal  = float(rec["principal_amount"])
        rate       = float(rec["interest_rate"])   # already decimal
        term       = int(rec["loan_term_months"])
        payment    = float(rec["monthly_payment"])
        status     = str(rec["loan_status"])
        orig_date  = pd.Timestamp(rec["origination_date"])

        # How many payments to generate
        months_paid = int(
            ((TODAY - orig_date) / pd.Timedelta(days=30))
        )
        months_paid = max(0, min(months_paid, term))
        if status == "paid_off":
            months_paid = term
        elif status in ("charged_off", "default"):
            months_paid = min(months_paid, max(int(rng.integers(6, term)), 3))

        if months_paid == 0 or payment <= 0:
            continue

        balance = principal
        r_m = rate / 12.0

        for m in range(1, months_paid + 1):
            due_date = orig_date + pd.DateOffset(months=m)
            # Late probability by status
            late_prob = 0.05 if status == "current" else 0.25
            days_shift = int(rng.integers(-3, 5)) if rng.random() > late_prob else int(rng.integers(1, 25))
            pmt_date = due_date + timedelta(days=days_shift)
            days_late = max(days_shift, 0)

            interest_p = round(balance * r_m, 2)
            principal_p = round(payment - interest_p, 2)
            balance = max(balance - principal_p, 0.0)
            fees = round(float(rng.choice([0, 25, 35], p=[0.95, 0.03, 0.02])), 2)

            rows.append({
                "payment_id":       str(uuid.uuid4()),
                "loan_id":          loan_id,
                "customer_id":      customer_id,
                "payment_date":     pmt_date.date(),
                "due_date":         due_date.date(),
                "payment_amount":   round(payment + fees, 2),
                "principal_portion": principal_p,
                "interest_portion": interest_p,
                "fees_portion":     fees,
                "days_late":        days_late,
                "remaining_balance": round(balance, 2),
                "payment_status":   "returned" if days_late > 15 and rng.random() < 0.02 else "posted",
                "payment_method":   str(rng.choice(PAYMENT_METHODS, p=PAYMENT_METHOD_PROBS)),
                "is_prepayment":    False,
            })
    return rows


def generate_payments(funded_df: pd.DataFrame, n_workers: int = 4, seed: int = 42) -> pd.DataFrame:
    """Generate payment histories in parallel."""
    print(f"  Generating payment schedules ({n_workers} workers) …")
    records = funded_df.to_dict("records")
    chunks = np.array_split(np.arange(len(records)), n_workers)

    all_rows: list = []
    with ProcessPoolExecutor(max_workers=n_workers) as exe:
        futures = {
            exe.submit(_payments_for_chunk, [records[i] for i in chunk], seed + j): j
            for j, chunk in enumerate(chunks)
            if len(chunk) > 0
        }
        for fut in as_completed(futures):
            chunk_rows = fut.result()
            all_rows.extend(chunk_rows)
            print(f"    Payment chunk {futures[fut]+1}/{len(futures)} done "
                  f"({len(chunk_rows):,} payments)")

    return pd.DataFrame(all_rows)


# ── Bureau pulls ──────────────────────────────────────────────────────────────

def generate_bureau_pulls(apps_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Generate credit bureau pulls for a sample of applications."""
    rng = np.random.default_rng(seed + 5)
    # Sample at most 200K to keep file manageable
    sample = apps_df.sample(min(len(apps_df), 200_000), random_state=seed)
    rows = []
    for _, row in sample.iterrows():
        n_pulls = int(rng.integers(1, 4))
        for _ in range(n_pulls):
            applied = pd.Timestamp(row["applied_at"])
            rows.append({
                "pull_id":        str(uuid.uuid4()),
                "customer_id":    row["customer_id"],
                "application_id": row["application_id"],
                "bureau":         str(rng.choice(BUREAUS)),
                "pull_type":      "hard" if row.get("decision_outcome") in ("APPROVE", "COUNTER_OFFER", "DECLINE") else "soft",
                "pull_date":      (applied - timedelta(days=int(rng.integers(0, 5)))).date(),
                "score_returned": int(rng.integers(300, 851)),
                "created_at":     applied,
            })
    return pd.DataFrame(rows)


# ── Modifications ─────────────────────────────────────────────────────────────

def generate_modifications(funded_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Generate loan modification records for in_forbearance and modified loans."""
    rng = np.random.default_rng(seed + 6)
    candidates = funded_df[funded_df["loan_status"].isin(["in_forbearance", "modified"])]
    rows = []
    for _, row in candidates.iterrows():
        rows.append({
            "modification_id":  str(uuid.uuid4()),
            "loan_id":          row["loan_id"],
            "modification_type": str(rng.choice(MODIFICATION_TYPES)),
            "effective_date":   (
                pd.Timestamp(row["origination_date"]) + pd.DateOffset(months=int(rng.integers(3, 24)))
            ).date(),
            "reason":           str(rng.choice(MODIFICATION_REASONS)),
            "original_rate":    row["interest_rate"],
            "modified_rate":    round(float(row["interest_rate"]) * float(rng.uniform(0.70, 0.95)), 6),
            "months_deferred":  int(rng.integers(1, 7)),
        })
    return pd.DataFrame(rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate personal loan simulated dataset")
    parser.add_argument("--applications", type=int, default=750_000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--db-path", default="policy_versions.db")
    parser.add_argument("--output-dir", default="data/raw/loans/")
    parser.add_argument("--skip-payments", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("PERSONAL LOAN SYNTHETIC DATA GENERATOR")
    print(f"  Applications: {args.applications:,} | Threads: {args.threads}")
    print("=" * 65)

    # 1. Applications
    print("\n[1/5] Applications …")
    apps_df = generate_applications(args.applications, args.db_path, seed=args.seed)
    outcome_counts = apps_df["decision_outcome"].value_counts()
    print(f"  Decision outcomes:\n{outcome_counts.to_string()}")

    app_out = out_dir / "personal_loan_applications.parquet"
    apps_df.to_parquet(app_out, index=False, compression="gzip")
    print(f"  Saved {len(apps_df):,} applications → {app_out}")

    # 2. Funded loans
    print("\n[2/5] Funded Loans …")
    funded_df = generate_funded_loans(apps_df, seed=args.seed)
    funded_out = out_dir / "personal_loans_funded.parquet"
    funded_df.to_parquet(funded_out, index=False, compression="gzip")
    print(f"  Saved {len(funded_df):,} funded loans → {funded_out}")

    # 3. Payments
    if not args.skip_payments:
        print("\n[3/5] Payment Schedules …")
        payments_df = generate_payments(funded_df, n_workers=args.threads, seed=args.seed)
        pay_out = out_dir / "personal_loan_payments.parquet"
        payments_df.to_parquet(pay_out, index=False, compression="gzip")
        print(f"  Saved {len(payments_df):,} payments → {pay_out}")
    else:
        print("\n[3/5] Skipped (--skip-payments)")

    # 4. Bureau pulls
    print("\n[4/5] Credit Bureau Pulls …")
    bureau_df = generate_bureau_pulls(apps_df, seed=args.seed)
    bureau_out = out_dir / "personal_loan_credit_bureau_pulls.parquet"
    bureau_df.to_parquet(bureau_out, index=False, compression="gzip")
    print(f"  Saved {len(bureau_df):,} bureau pulls → {bureau_out}")

    # 5. Modifications
    print("\n[5/5] Loan Modifications …")
    mod_df = generate_modifications(funded_df, seed=args.seed)
    mod_out = out_dir / "personal_loan_modifications.parquet"
    mod_df.to_parquet(mod_out, index=False, compression="gzip")
    print(f"  Saved {len(mod_df):,} modifications → {mod_out}")

    print("\n" + "=" * 65)
    print("DONE")
    print(f"  Applications : {len(apps_df):,}")
    print(f"  Funded loans : {len(funded_df):,} ({len(funded_df)/len(apps_df)*100:.1f}% approval)")
    if not args.skip_payments:
        print(f"  Payments     : {len(payments_df):,}")
    print(f"  Bureau pulls : {len(bureau_df):,}")
    print(f"  Modifications: {len(mod_df):,}")
    print("=" * 65)


if __name__ == "__main__":
    main()
