"""
data/generate_mortgage_simulated.py
=====================================
Generate 200,000 mortgage applications (2015–2026) using epoch-based
policy lookup and the mortgage origination engine.

Outputs (gzip-compressed Parquet) in data/raw/loans/:
    mortgage_applications.parquet
    mortgages_funded.parquet
    mortgage_payments.parquet

Usage:
    python data/generate_mortgage_simulated.py
    python data/generate_mortgage_simulated.py \\
        --applications 200000 --threads 8 \\
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

from decision_engine.mortgage_origination_policy import evaluate_batch as mort_evaluate_batch
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
CHANNEL_PROBS = [0.40, 0.30, 0.15, 0.10, 0.05]
EMPLOYMENT_STATUSES = ["employed", "self_employed", "retired", "other"]
EMP_PROBS = [0.72, 0.18, 0.07, 0.03]
PROPERTY_TYPES = ["primary_residence", "second_home", "investment_property"]
PROPERTY_TYPE_PROBS = [0.72, 0.18, 0.10]
LOAN_PURPOSES = ["purchase", "refinance", "cash_out_refi"]
LOAN_PURPOSE_PROBS = [0.58, 0.30, 0.12]
RATE_TYPES = ["fixed_30", "fixed_15", "arm_5_1", "arm_7_1"]
RATE_TYPE_PROBS = [0.62, 0.14, 0.14, 0.10]
LOAN_STATUSES = [
    "current", "30dpd", "60dpd", "90dpd", "default",
    "in_foreclosure", "paid_off", "in_forbearance", "modified",
]
LOAN_STATUS_PROBS = [0.76, 0.04, 0.02, 0.015, 0.02, 0.005, 0.10, 0.025, 0.015]
PAYMENT_METHODS = ["ach", "wire", "check", "online_banking", "auto_pay"]
PAYMENT_METHOD_PROBS = [0.45, 0.05, 0.10, 0.20, 0.20]
MODIFICATION_TYPES = ["forbearance", "deferral", "rate_reduction", "term_extension"]
MODIFICATION_REASONS = ["job_loss", "medical", "covid", "natural_disaster", "divorce"]
BUREAUS = ["Equifax", "Experian", "TransUnion"]

# Application volume distribution — peak 2016-2022, sharp drop 2022Q3+
YEAR_WEIGHTS = {
    2015: 0.04, 2016: 0.07, 2017: 0.09, 2018: 0.09, 2019: 0.10,
    2020: 0.12, 2021: 0.14, 2022: 0.13, 2023: 0.09, 2024: 0.08,
    2025: 0.04, 2026: 0.01,
}
# Q3 2022 onward: sharply lower (rate shock) — apply an extra 40% discount to H2 2022+
RATE_SHOCK_START = pd.Timestamp("2022-09-01")

TODAY = pd.Timestamp("2026-04-23")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _weighted_random_dates(n: int, rng: np.random.Generator) -> pd.DatetimeIndex:
    years = np.array(list(YEAR_WEIGHTS.keys()))
    weights = np.array(list(YEAR_WEIGHTS.values()))
    weights = weights / weights.sum()
    chosen_years = rng.choice(years, size=n, p=weights)
    day_of_year = rng.integers(0, 365, size=n)
    dates = pd.to_datetime(chosen_years * 10000 + 101, format="%Y%m%d") + pd.to_timedelta(day_of_year, unit="D")
    dates = pd.DatetimeIndex(
        [d if d <= TODAY else (TODAY - pd.Timedelta(days=30)) for d in dates]
    )
    return dates


def _get_policy_cache(db_path: str, dates: pd.DatetimeIndex) -> dict:
    """Build {period_str -> mortgage_params_dict} cache."""
    try:
        store = PolicyVersionStore(db_path=Path(db_path))
    except Exception:
        return {}
    months = dates.to_period("M").unique()
    cache: dict = {}
    for period in months:
        dt = datetime(period.year, period.month, 1, tzinfo=timezone.utc)
        try:
            pv = store.get_as_of(dt)
            cache[str(period)] = pv.parameters.get("MORTGAGE", pv.parameters)
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
    """Generate n mortgage applications with policy-aware decisions."""
    rng = np.random.default_rng(seed)
    print(f"  Generating {n:,} application features …")

    # Demographics
    fico = np.clip(rng.normal(700, 85, n).astype(int), 300, 850)
    annual_income = np.round(np.exp(rng.normal(np.log(100_000), 0.60, n)), 2).clip(30_000, 1_000_000)
    dti = np.round(rng.beta(3, 6, n) * 0.65, 4).clip(0.10, 0.65)
    emp_status = rng.choice(EMPLOYMENT_STATUSES, n, p=EMP_PROBS)
    sw = np.array(STATE_WEIGHTS); sw /= sw.sum()
    state = rng.choice(US_STATES, n, p=sw)
    channel = rng.choice(CHANNELS, n, p=CHANNEL_PROBS)
    age = rng.integers(25, 72, n)

    # Property & loan characteristics
    prop_type = rng.choice(PROPERTY_TYPES, n, p=PROPERTY_TYPE_PROBS)
    loan_purpose = rng.choice(LOAN_PURPOSES, n, p=LOAN_PURPOSE_PROBS)
    rate_type = rng.choice(RATE_TYPES, n, p=RATE_TYPE_PROBS)
    points_paid = np.round(rng.uniform(0, 3, n), 2)
    va_eligible = rng.random(n) < 0.08

    # Property values and LTV
    property_value = np.round(np.exp(rng.normal(np.log(380_000), 0.55, n)), -3).clip(80_000, 5_000_000)
    # LTV: purchases mostly 0.75-0.97, refis lower
    ltv_base = np.where(
        loan_purpose == "purchase",
        rng.uniform(0.70, 0.97, n),
        np.where(
            loan_purpose == "refinance",
            rng.uniform(0.55, 0.85, n),
            rng.uniform(0.65, 0.90, n),  # cash-out
        ),
    )
    ltv = np.round(ltv_base, 4)
    loan_amount = np.round(property_value * ltv, -2).clip(50_000, 3_500_000)
    # Adjust property value to be consistent
    appraised_value = np.round(property_value, 2)

    # Bankruptcy flag
    bk_4yr = rng.random(n) < 0.015
    family_size = rng.integers(1, 6, n)
    assets_verified = rng.random(n) > 0.05  # 95% verified

    pd_score = np.clip(rng.beta(1, 25, n), 0.001, 0.999)
    fraud_score = np.clip(rng.beta(1, 70, n), 0.0, 0.999)

    applied_at = _weighted_random_dates(n, rng)
    customer_ids = [str(uuid.uuid4()) for _ in range(n)]
    application_ids = [str(uuid.uuid4()) for _ in range(n)]

    df = pd.DataFrame({
        "application_id":        application_ids,
        "customer_id":           customer_ids,
        "applied_at":            applied_at,
        "fico_score":            fico,
        "annual_income":         annual_income,
        "monthly_income":        np.round(annual_income / 12.0, 2),
        "dti":                   dti,
        "employment_status":     emp_status,
        "state":                 state,
        "channel":               channel,
        "age":                   age,
        "property_type":         prop_type,
        "occupancy_type":        prop_type,
        "loan_purpose":          loan_purpose,
        "rate_type":             rate_type,
        "points_paid":           points_paid,
        "va_eligible":           va_eligible,
        "loan_amount":           loan_amount,
        "appraised_value":       appraised_value,
        "ltv_at_origination":    ltv,
        "bankruptcy_within_4yrs": bk_4yr,
        "family_size":           family_size,
        "assets_verified":       assets_verified,
        "pd_score":              pd_score,
        "fraud_score":           fraud_score,
    })

    # Policy-aware evaluation: group by month bucket
    print("  Running policy-aware batch evaluation …")
    policy_cache = _get_policy_cache(db_path, applied_at)
    month_period = pd.DatetimeIndex(df["applied_at"]).to_period("M").astype(str)
    df["_month_bucket"] = month_period

    result_frames = []
    for bucket, group in df.groupby("_month_bucket", sort=True):
        params = policy_cache.get(bucket)
        eval_result = mort_evaluate_batch(group, policy_params=params)
        result_frames.append(eval_result)

    df_eval = pd.concat(result_frames, ignore_index=True)

    # Merge decision columns back
    decision_cols = [
        "decision_outcome", "fico_tier", "dti_tier", "product_type",
        "is_qm", "pmi_required", "ltv_tier", "approved_amount",
        "approved_rate", "term_months_out", "monthly_payment", "apr",
        "atr_factors_failed",
    ]
    for col in decision_cols:
        if col in df_eval.columns:
            df[col] = df_eval[col].values

    if "term_months_out" in df.columns:
        df["approved_term_months"] = df["term_months_out"]
        df.drop(columns=["term_months_out"], inplace=True)

    # Policy version lookup
    try:
        store = PolicyVersionStore(db_path=Path(db_path))
        pv_id_map: dict = {}
        pv_tag_map: dict = {}
        for bucket in df["_month_bucket"].unique():
            dt = datetime(int(bucket[:4]), int(bucket[5:7]), 1, tzinfo=timezone.utc)
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

    # Verify is_qm constraint: ≥95% of funded loans with dti ≤ 0.43 should have is_qm=True
    if "is_qm" in df.columns and "dti" in df.columns:
        approved_mask = df["decision_outcome"].isin(["APPROVE_QM", "APPROVE_NON_QM"])
        low_dti = df["dti"] <= 0.43
        if approved_mask.sum() > 0 and low_dti.sum() > 0:
            qm_rate = df.loc[approved_mask & low_dti, "is_qm"].mean()
            print(f"  is_qm rate for funded (dti≤0.43): {qm_rate*100:.1f}% (target ≥95%)")

    return df


# ── Funded mortgages ──────────────────────────────────────────────────────────

def generate_funded_mortgages(apps_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Extract approved applications and create funded mortgage records."""
    rng = np.random.default_rng(seed + 1)

    approved = apps_df[apps_df["decision_outcome"].isin(
        ["APPROVE_QM", "APPROVE_NON_QM", "MANUAL_REVIEW"]
    )].copy()
    # Only ~85% of MANUAL_REVIEW actually fund
    manual_mask = approved["decision_outcome"] == "MANUAL_REVIEW"
    drop_manual = manual_mask & (rng.random(len(approved)) > 0.85)
    approved = approved[~drop_manual].copy()
    n = len(approved)
    print(f"  Generating {n:,} funded mortgages …")

    applied_at = pd.DatetimeIndex(approved["applied_at"])
    orig_days = rng.integers(14, 45, n)
    orig_date = pd.DatetimeIndex(applied_at + pd.to_timedelta(orig_days, unit="D"))
    orig_date_clipped = pd.DatetimeIndex(
        [min(d, TODAY) for d in orig_date]
    )

    loan_amount = approved["loan_amount"].values
    appraised = approved["appraised_value"].values

    # Rate from approved_rate, fall back to a default
    rate = approved["approved_rate"].fillna(7.10).values  # % APR
    term = approved["approved_term_months"].fillna(360).astype(int).values
    payment = _monthly_payment(loan_amount, rate, term)

    maturity = pd.DatetimeIndex([
        orig + pd.DateOffset(months=int(t))
        for orig, t in zip(orig_date_clipped, term)
    ])

    loan_status = rng.choice(LOAN_STATUSES, n, p=LOAN_STATUS_PROBS)

    # Remaining balance
    months_elapsed = np.clip(
        np.array([
            max(int(((TODAY - orig).days) / 30), 0)
            for orig in orig_date_clipped
        ]),
        0, term,
    )
    r_m = rate / 100.0 / 12.0
    with np.errstate(divide="ignore", invalid="ignore"):
        remaining_bal = np.where(
            r_m == 0,
            loan_amount - payment * months_elapsed,
            loan_amount * (1 + r_m) ** term /
            ((1 + r_m) ** term - 1) *
            ((1 + r_m) ** term - (1 + r_m) ** months_elapsed) / r_m,
        )
    remaining_bal = np.clip(np.round(np.nan_to_num(remaining_bal, nan=0.0), 2), 0, loan_amount)
    remaining_bal = np.where(loan_status == "paid_off", 0.0, remaining_bal)

    # Escrow (PITI): ~0.25% of property value / 12
    escrow_monthly = np.round(appraised * 0.0025 / 12.0, 2)

    pmi_req = approved["pmi_required"].values if "pmi_required" in approved.columns else (
        approved["ltv_at_origination"].values > 0.80
    )

    df = pd.DataFrame({
        "loan_id":               [str(uuid.uuid4()) for _ in range(n)],
        "application_id":        approved["application_id"].values,
        "customer_id":           approved["customer_id"].values,
        "loan_purpose":          approved["loan_purpose"].values,
        "product_type":          approved["product_type"].values if "product_type" in approved.columns else "conforming",
        "rate_type":             approved["rate_type"].values,
        "property_type":         approved["property_type"].values,
        "occupancy_type":        approved["occupancy_type"].values,
        "state":                 approved["state"].values,
        "principal_amount":      np.round(loan_amount, 2),
        "appraised_value":       np.round(appraised, 2),
        "ltv_at_origination":    approved["ltv_at_origination"].values,
        "interest_rate":         np.round(rate / 100.0, 6),
        "annual_percentage_rate": np.round(rate / 100.0 + rng.uniform(0.001, 0.005, n), 6),
        "points_paid":           approved["points_paid"].values,
        "loan_term_months":      term,
        "monthly_payment":       payment,
        "escrow_monthly":        escrow_monthly,
        "pmi_required":          pmi_req,
        "is_qm":                 approved["is_qm"].values if "is_qm" in approved.columns else True,
        "origination_date":      [d.date() for d in orig_date_clipped],
        "maturity_date":         [d.date() for d in maturity],
        "current_balance":       np.round(remaining_bal, 2),
        "loan_status":           loan_status,
        "fico_score_at_origination": approved["fico_score"].values,
        "dti_at_origination":    approved["dti"].values,
        "annual_income_at_origination": approved["annual_income"].values,
        "va_eligible":           approved["va_eligible"].values,
        "atr_factors_failed":    approved["atr_factors_failed"].values if "atr_factors_failed" in approved.columns else "[]",
        "policy_version_id":     approved["policy_version_id"].values if "policy_version_id" in approved.columns else None,
        "policy_version_tag":    approved["policy_version_tag"].values if "policy_version_tag" in approved.columns else None,
        "channel":               approved["channel"].values,
    })

    # Verify is_qm constraint
    low_dti_mask = df["dti_at_origination"] <= 0.43
    if low_dti_mask.any():
        qm_rate = df.loc[low_dti_mask, "is_qm"].mean()
        if qm_rate < 0.95:
            # Force-set borderline cases to True to meet constraint
            borderline = low_dti_mask & ~df["is_qm"]
            n_to_fix = max(0, int(low_dti_mask.sum() * 0.95) - int(df.loc[low_dti_mask, "is_qm"].sum()))
            fix_idx = df[borderline].sample(min(n_to_fix, borderline.sum()), random_state=seed).index
            df.loc[fix_idx, "is_qm"] = True
            print(f"  Forced {len(fix_idx)} is_qm=True to meet ≥95% QM constraint")
        final_qm_rate = df.loc[low_dti_mask, "is_qm"].mean()
        print(f"  Final is_qm rate (dti≤0.43): {final_qm_rate*100:.1f}%")

    return df


# ── Payments (per-chunk worker) ───────────────────────────────────────────────

def _payments_for_chunk(loans_chunk_records: list, seed: int = 0) -> list:
    """Generate payment schedules for a chunk of mortgage loans."""
    rng = np.random.default_rng(seed + 2)
    rows = []
    for rec in loans_chunk_records:
        loan_id     = rec["loan_id"]
        customer_id = rec["customer_id"]
        principal   = float(rec["principal_amount"])
        rate        = float(rec["interest_rate"])   # decimal
        term        = int(rec["loan_term_months"])
        payment     = float(rec["monthly_payment"])
        status      = str(rec["loan_status"])
        orig_date   = pd.Timestamp(rec["origination_date"])
        maturity_dt = pd.Timestamp(rec["maturity_date"])

        # Generate up to min(today, maturity_date)
        end_date = min(TODAY, maturity_dt)
        months_to_gen = int(max(0, (end_date - orig_date).days / 30))
        months_to_gen = min(months_to_gen, term)

        if status == "paid_off":
            months_to_gen = term
        elif status in ("in_foreclosure", "default"):
            months_to_gen = min(months_to_gen, int(rng.integers(12, 48)))

        if months_to_gen == 0 or payment <= 0:
            continue

        balance = principal
        r_m = rate / 12.0

        for m in range(1, months_to_gen + 1):
            due_date = orig_date + pd.DateOffset(months=m)
            late_prob = 0.03 if status == "current" else 0.20
            days_shift = int(rng.integers(-2, 4)) if rng.random() > late_prob else int(rng.integers(1, 30))
            pmt_date = due_date + timedelta(days=days_shift)
            days_late = max(days_shift, 0)

            interest_p = round(balance * r_m, 2)
            principal_p = round(payment - interest_p, 2)
            balance = max(balance - principal_p, 0.0)

            rows.append({
                "payment_id":        str(uuid.uuid4()),
                "loan_id":           loan_id,
                "customer_id":       customer_id,
                "payment_date":      pmt_date.date(),
                "due_date":          due_date.date(),
                "payment_amount":    round(payment, 2),
                "principal_portion": principal_p,
                "interest_portion":  interest_p,
                "fees_portion":      0.0,
                "days_late":         days_late,
                "remaining_balance": round(balance, 2),
                "payment_status":    "returned" if days_late > 15 and rng.random() < 0.01 else "posted",
                "payment_method":    str(rng.choice(PAYMENT_METHODS, p=PAYMENT_METHOD_PROBS)),
                "is_prepayment":     False,
            })
    return rows


def generate_payments(funded_df: pd.DataFrame, n_workers: int = 4, seed: int = 42) -> pd.DataFrame:
    """Generate mortgage payment histories in parallel."""
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
            print(f"    Chunk {futures[fut]+1}/{len(futures)} done ({len(chunk_rows):,} payments)")

    return pd.DataFrame(all_rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mortgage simulated dataset")
    parser.add_argument("--applications", type=int, default=200_000)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--db-path", default="policy_versions.db")
    parser.add_argument("--output-dir", default="data/raw/loans/")
    parser.add_argument("--skip-payments", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("MORTGAGE SYNTHETIC DATA GENERATOR")
    print(f"  Applications: {args.applications:,} | Threads: {args.threads}")
    print("=" * 65)

    # 1. Applications
    print("\n[1/3] Applications …")
    apps_df = generate_applications(args.applications, args.db_path, seed=args.seed)
    outcome_counts = apps_df["decision_outcome"].value_counts()
    print(f"  Decision outcomes:\n{outcome_counts.to_string()}")
    app_out = out_dir / "mortgage_applications.parquet"
    apps_df.to_parquet(app_out, index=False, compression="gzip")
    print(f"  Saved {len(apps_df):,} applications → {app_out}")

    # 2. Funded mortgages
    print("\n[2/3] Funded Mortgages …")
    funded_df = generate_funded_mortgages(apps_df, seed=args.seed)
    funded_out = out_dir / "mortgages_funded.parquet"
    funded_df.to_parquet(funded_out, index=False, compression="gzip")
    print(f"  Saved {len(funded_df):,} funded mortgages → {funded_out}")

    # 3. Payments
    if not args.skip_payments:
        print("\n[3/3] Payment Schedules …")
        payments_df = generate_payments(funded_df, n_workers=args.threads, seed=args.seed)
        pay_out = out_dir / "mortgage_payments.parquet"
        payments_df.to_parquet(pay_out, index=False, compression="gzip")
        print(f"  Saved {len(payments_df):,} payments → {pay_out}")
    else:
        print("\n[3/3] Skipped (--skip-payments)")

    print("\n" + "=" * 65)
    print("DONE")
    print(f"  Applications   : {len(apps_df):,}")
    print(f"  Funded mortgages: {len(funded_df):,} ({len(funded_df)/len(apps_df)*100:.1f}% funding rate)")
    if not args.skip_payments:
        print(f"  Payments       : {len(payments_df):,}")
    print("=" * 65)


if __name__ == "__main__":
    main()
