"""
Massive synthetic TRANSACTIONS dataset generator.

Generates:
  - bank_accounts         (default 300 000)
  - transactions          (default 15 000 000, time-series partitioned)
  - ach_transfers         (~20% of debit transactions)
  - wire_transfers        (~2% of large transactions)
  - fraud_alerts          (triggered on fraud-flagged transactions)
  - daily_balance_snapshots (per account, ~3 years of history)

Usage:
    python data/generate_transactions_data.py \
        [--accounts N] [--transactions N] [--threads T]

Outputs (Parquet, gzip) in data/raw/transactions/:
    bank_accounts.parquet
    transactions_YYYY_QN.parquet  (quarterly shards)
    ach_transfers.parquet
    wire_transfers.parquet
    fraud_alerts.parquet
    daily_balance_snapshots.parquet
"""

import argparse
import hashlib
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker("en_US")
Faker.seed(42)

# ─── Constants ────────────────────────────────────────────────────────────────
TXN_TYPES = [
    "debit","credit","transfer_in","transfer_out",
    "ach_debit","ach_credit","wire_in","wire_out",
    "check_deposit","check_payment","atm_withdrawal",
    "atm_deposit","fee","interest","refund","reversal",
]
TXN_TYPE_PROBS = [
    0.30,0.25,0.05,0.05,
    0.08,0.08,0.005,0.005,
    0.03,0.03,0.04,
    0.01,0.02,0.01,0.01,0.005,
]
TXN_CATEGORIES = [
    "groceries","restaurants","gas","utilities","rent_mortgage",
    "insurance","healthcare","entertainment","shopping_retail",
    "travel","transportation","education","subscriptions",
    "investments","loan_payment","tax","payroll","government","charity","cash","other",
]
CAT_PROBS = [
    0.09,0.09,0.06,0.06,0.08,
    0.04,0.05,0.05,0.09,
    0.04,0.05,0.03,0.05,
    0.03,0.05,0.02,0.07,0.02,0.01,0.04,0.08,
]
CHANNELS = ["online","mobile","branch","atm","pos","phone","api"]
CHANNEL_PROBS = [0.30,0.28,0.08,0.08,0.18,0.04,0.04]
ACCOUNT_TYPES = ["checking","savings","money_market","cd","brokerage"]
ACCT_TYPE_PROBS = [0.55,0.28,0.08,0.05,0.04]
BANKS = [
    "JPMorgan Chase", "Bank of America", "Wells Fargo", "Citibank",
    "US Bank", "Truist", "PNC Bank", "Capital One", "TD Bank",
    "Regions Bank", "Citizens Bank", "Fifth Third", "Ally Bank",
    "Charles Schwab", "Discover Bank",
]
FRAUD_TYPES = [
    "velocity_breach","unusual_amount","geo_anomaly","device_anomaly",
    "time_anomaly","pattern_match","account_takeover","synthetic_identity",
]
MERCHANTS = [
    # Groceries
    "Whole Foods", "Kroger", "Publix", "Safeway", "Trader Joe's", "Costco", "Sam's Club",
    # Restaurants
    "McDonald's", "Chipotle", "Starbucks", "Subway", "Chick-fil-A", "Domino's", "Shake Shack",
    # Gas
    "Shell", "BP", "Exxon", "Chevron", "Sunoco", "Marathon",
    # Utilities
    "AT&T", "Verizon", "Comcast", "Duke Energy", "ConEd",
    # Retail
    "Amazon", "Walmart", "Target", "Best Buy", "Home Depot", "Lowe's", "IKEA", "Costco",
    # Healthcare
    "CVS Pharmacy", "Walgreens", "Rite Aid", "Kaiser Permanente",
    # Entertainment
    "Netflix", "Spotify", "Apple", "Google Play", "AMC Theatres",
    # Travel
    "Delta Air Lines", "United Airlines", "American Airlines", "Marriott", "Hilton", "Airbnb",
    # Transportation
    "Uber", "Lyft", "Enterprise Rent-A-Car",
]
MCC_MAP = {
    "groceries": "5411", "restaurants": "5812", "gas": "5541",
    "utilities": "4900", "shopping_retail": "5999", "travel": "4722",
    "transportation": "4111", "healthcare": "5912",
}
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY",
]
ACH_TYPES = ["PPD","CCD","WEB","TEL","CTX","IAT"]
ACH_RETURN_CODES = ["R01","R02","R03","R04","R07","R08","R09","R10","R29"]


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _hash_account(n_str: str) -> str:
    return hashlib.sha256(n_str.encode()).hexdigest()


# ─── Bank Accounts ────────────────────────────────────────────────────────────

def generate_bank_accounts(n: int, seed: int = 42) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    print(f"  Generating {n:,} bank accounts …")

    account_ids = [_uuid_str() for _ in range(n)]
    customer_ids = [_uuid_str() for _ in range(n)]
    acct_nums = [str(r.integers(1_000_000_000, 9_999_999_999)) for _ in range(n)]
    routing = r.choice(
        ["021000021","021000089","026009593","021200339","322271627","111000025","124303120"],
        size=n,
    )

    opened_days_ago = r.integers(30, 1825, size=n)
    open_date = (pd.Timestamp("2026-03-01") - pd.to_timedelta(opened_days_ago, unit="D")).dt.date

    current_balance = np.round(
        np.exp(r.normal(np.log(5000), 1.2, size=n)).clip(0, 500_000), 2
    )
    overdraft_limit = np.where(
        r.random(size=n) < 0.3,
        r.choice([100, 250, 500, 1000], size=n),
        0,
    )

    account_type = r.choice(ACCOUNT_TYPES, size=n, p=ACCT_TYPE_PROBS)
    status = r.choice(
        ["active","dormant","closed","frozen"],
        size=n, p=[0.85,0.07,0.05,0.03],
    )
    bank_name = r.choice(BANKS, size=n)

    df = pd.DataFrame({
        "account_id": account_ids,
        "customer_id": customer_ids,
        "account_number_hash": [_hash_account(n) for n in acct_nums],
        "account_number_last4": [n[-4:] for n in acct_nums],
        "routing_number": routing,
        "account_type": account_type,
        "account_status": status,
        "bank_name": bank_name,
        "currency_code": "USD",
        "current_balance": current_balance,
        "available_balance": np.round(current_balance * r.uniform(0.90, 1.0, size=n), 2),
        "overdraft_limit": overdraft_limit.astype(float),
        "overdraft_protection": overdraft_limit > 0,
        "opened_date": open_date,
        "overdraft_count_30d": r.integers(0, 4, size=n).astype(int),
        "nsf_count_90d": r.integers(0, 6, size=n).astype(int),
        "suspicious_activity_flag": r.random(size=n) < 0.005,
        "created_at": pd.Timestamp("2026-03-01", tz="UTC") - pd.to_timedelta(opened_days_ago, unit="D"),
        "updated_at": pd.Timestamp("2026-03-01", tz="UTC"),
    })
    return df


# ─── Transactions (chunked) ──────────────────────────────────────────────────

def _amount_for_category(category: str, r: np.random.Generator, n: int) -> np.ndarray:
    """Realistic amount distributions by category."""
    params = {
        "groceries": (0.0, 4.2, 10, 400),
        "restaurants": (0.0, 3.5, 5, 200),
        "gas": (0.0, 4.0, 20, 150),
        "utilities": (0.0, 5.0, 30, 400),
        "rent_mortgage": (0.0, 7.2, 500, 5000),
        "insurance": (0.0, 5.8, 100, 3000),
        "healthcare": (0.0, 5.5, 20, 2000),
        "entertainment": (0.0, 4.0, 5, 300),
        "shopping_retail": (0.0, 5.0, 10, 500),
        "travel": (0.0, 6.5, 50, 5000),
        "transportation": (0.0, 3.5, 5, 100),
        "education": (0.0, 6.0, 50, 5000),
        "subscriptions": (0.0, 3.5, 5, 100),
        "investments": (0.0, 7.5, 100, 50000),
        "loan_payment": (0.0, 6.5, 100, 5000),
        "payroll": (0.0, 8.5, 500, 20000),
        "other": (0.0, 4.5, 1, 1000),
    }
    mu, sigma, lo, hi = params.get(category, (0.0, 5.0, 5, 500))
    return np.round(np.exp(r.normal(mu + sigma * 0.6, sigma * 0.5, size=n)).clip(lo, hi), 2)


def generate_transactions_chunk(
    chunk_id: int,
    n: int,
    account_ids: list,
    customer_ids: list,
    start_ts: str,
    end_ts: str,
) -> pd.DataFrame:
    r = np.random.default_rng(chunk_id * 31337)

    txn_ids = [_uuid_str() for _ in range(n)]
    acct_idx = r.integers(0, len(account_ids), size=n)
    acct_arr = np.array(account_ids)[acct_idx]
    cust_arr = np.array(customer_ids)[acct_idx]

    categories = r.choice(TXN_CATEGORIES, size=n, p=CAT_PROBS)
    amounts = np.array([
        float(_amount_for_category(c, r, 1)[0]) for c in categories
    ])

    # Transaction type correlates loosely with category
    txn_types = r.choice(TXN_TYPES, size=n, p=TXN_TYPE_PROBS)
    channels = r.choice(CHANNELS, size=n, p=CHANNEL_PROBS)

    # Timestamps: biased toward business hours, weekdays
    s = pd.Timestamp(start_ts).value
    e = pd.Timestamp(end_ts).value
    initiated_ns = r.integers(s, e, size=n)
    initiated_at = pd.to_datetime(initiated_ns)

    # Fraud signals
    fraud_scores = r.beta(1, 18, size=n)  # heavy right-skew, most near 0
    fraud_flag = fraud_scores > 0.80
    # Bump fraud on night-time + large amounts
    is_night = (initiated_at.hour < 6) | (initiated_at.hour >= 23)
    is_large = amounts > 2000
    fraud_flag = fraud_flag | (is_night & is_large & (r.random(size=n) < 0.08))
    fraud_scores = np.where(fraud_flag, np.round(r.uniform(0.80, 1.0, size=n), 4), np.round(fraud_scores, 4))

    merchant_names = r.choice(MERCHANTS, size=n)
    merchant_states = r.choice(US_STATES, size=n)
    mccs = [MCC_MAP.get(c, "5999") for c in categories]

    posted_at = initiated_at + pd.to_timedelta(r.integers(0, 3, size=n), unit="D")
    status_arr = np.where(
        fraud_flag & (r.random(size=n) < 0.15), "reversed",
        np.where(r.random(size=n) < 0.03, "pending", "posted")
    )

    df = pd.DataFrame({
        "transaction_id": txn_ids,
        "account_id": acct_arr,
        "customer_id": cust_arr,
        "transaction_type": txn_types,
        "transaction_category": categories,
        "channel": channels,
        "amount": amounts,
        "currency_code": "USD",
        "amount_usd": amounts,
        "merchant_name": merchant_names,
        "merchant_category_code": mccs,
        "merchant_state": merchant_states,
        "merchant_country": "US",
        "description": [f"TXN-{t[:8].upper()}" for t in txn_ids],
        "transaction_status": status_arr,
        "initiated_at": initiated_at.tz_localize("UTC"),
        "posted_at": posted_at.tz_localize("UTC"),
        "fraud_score": fraud_scores,
        "fraud_flag": fraud_flag,
        "fraud_reason": np.where(fraud_flag, r.choice(FRAUD_TYPES, size=n), None),
        "is_unusual_amount": is_large & (r.random(size=n) < 0.3),
        "is_unusual_location": r.random(size=n) < 0.05,
        "reference_number": [f"REF{str(uuid.uuid4())[:8].upper()}" for _ in range(n)],
        "created_at": initiated_at.tz_localize("UTC"),
    })
    return df


# ─── ACH Transfers ────────────────────────────────────────────────────────────

def generate_ach_transfers(txn_df: pd.DataFrame, seed: int = 10) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    ach_mask = txn_df["transaction_type"].isin(["ach_debit","ach_credit"])
    src = txn_df[ach_mask].copy()
    n = len(src)
    print(f"  Generating {n:,} ACH transfers …")

    return_mask = r.random(size=n) < 0.04
    return pd.DataFrame({
        "ach_id": [_uuid_str() for _ in range(n)],
        "transaction_id": src["transaction_id"].values,
        "account_id": src["account_id"].values,
        "customer_id": src["customer_id"].values,
        "ach_type": r.choice(ACH_TYPES, size=n, p=[0.45,0.20,0.20,0.05,0.05,0.05]),
        "direction": np.where(src["transaction_type"].values == "ach_debit", "debit", "credit"),
        "amount": src["amount"].values,
        "effective_date": src["posted_at"].dt.date.values,
        "company_name": r.choice(["Employer Inc","Insurance Co","Utility LLC","Merchant Corp"], size=n),
        "ach_status": np.where(return_mask, "returned", "settled"),
        "return_code": np.where(return_mask, r.choice(ACH_RETURN_CODES, size=n), None),
        "trace_number": [f"{r.integers(1e11, 1e12-1):.0f}" for _ in range(n)],
        "created_at": src["initiated_at"].values,
    })


# ─── Wire Transfers ───────────────────────────────────────────────────────────

def generate_wire_transfers(txn_df: pd.DataFrame, seed: int = 20) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    wire_mask = txn_df["transaction_type"].isin(["wire_in","wire_out"]) | (txn_df["amount"] > 10000)
    wire_mask = wire_mask & (r.random(size=len(txn_df)) < 0.05)
    src = txn_df[wire_mask].copy()
    n = len(src)
    print(f"  Generating {n:,} wire transfers …")

    return pd.DataFrame({
        "wire_id": [_uuid_str() for _ in range(n)],
        "transaction_id": src["transaction_id"].values,
        "account_id": src["account_id"].values,
        "customer_id": src["customer_id"].values,
        "direction": np.where(src["transaction_type"].values == "wire_in", "incoming", "outgoing"),
        "amount": src["amount"].values,
        "currency_code": "USD",
        "amount_usd": src["amount"].values,
        "fx_rate": 1.0,
        "beneficiary_name": r.choice(["Corp LLC","Holdings Inc","Trading Co","Investments LP"], size=n),
        "beneficiary_country": r.choice(["US","GB","DE","SG","CA","JP"], size=n, p=[0.55,0.10,0.08,0.08,0.12,0.07]),
        "wire_status": r.choice(["settled","confirmed","failed"], size=n, p=[0.91,0.07,0.02]),
        "kyc_verified": r.random(size=n) < 0.90,
        "ofac_screened": True,
        "ofac_match": r.random(size=n) < 0.002,
        "initiated_at": src["initiated_at"].values,
        "created_at": src["initiated_at"].values,
    })


# ─── Fraud Alerts ─────────────────────────────────────────────────────────────

def generate_fraud_alerts(txn_df: pd.DataFrame, seed: int = 30) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    fraud_txns = txn_df[txn_df["fraud_flag"]].copy()
    n = len(fraud_txns)
    print(f"  Generating {n:,} fraud alerts …")

    statuses = r.choice(
        ["open","under_review","confirmed_fraud","false_positive","closed"],
        size=n, p=[0.25,0.20,0.20,0.25,0.10],
    )
    return pd.DataFrame({
        "alert_id": [_uuid_str() for _ in range(n)],
        "transaction_id": fraud_txns["transaction_id"].values,
        "account_id": fraud_txns["account_id"].values,
        "customer_id": fraud_txns["customer_id"].values,
        "alert_type": r.choice(FRAUD_TYPES, size=n),
        "severity": r.choice(["low","medium","high","critical"], size=n, p=[0.30,0.40,0.22,0.08]),
        "fraud_score": fraud_txns["fraud_score"].values,
        "model_version": "fraud-v2.1",
        "alert_status": statuses,
        "risk_signals": [{"amount": float(a), "velocity": int(v)} for a, v in
                         zip(fraud_txns["amount"].values, r.integers(1, 20, size=n))],
        "triggered_rules": [["RULE_VELOCITY","RULE_LARGE_AMOUNT"] if s > 0.9 else ["RULE_GEO"]
                            for s in fraud_txns["fraud_score"].values],
        "created_at": fraud_txns["initiated_at"].values,
    })


# ─── Daily Balance Snapshots ──────────────────────────────────────────────────

def generate_daily_snapshots_chunk(accounts_chunk: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 50)
    rows = []
    dates = pd.date_range("2023-01-01", "2026-03-01", freq="D")
    for _, acct in accounts_chunk.iterrows():
        balance = float(acct["current_balance"])
        # Work backwards ~90 days for each account to keep manageable
        sample_dates = r.choice(dates, size=min(90, len(dates)), replace=False)
        sample_dates = sorted(sample_dates)
        for d in sample_dates:
            daily_cr = round(max(0, r.exponential(500)), 2)
            daily_dr = round(max(0, r.exponential(300)), 2)
            rows.append({
                "account_id": acct["account_id"],
                "customer_id": acct["customer_id"],
                "snapshot_date": d.date(),
                "opening_balance": round(balance, 2),
                "closing_balance": round(balance + daily_cr - daily_dr, 2),
                "daily_credits": daily_cr,
                "daily_debits": daily_dr,
                "transaction_count": int(r.integers(0, 25)),
                "min_balance": round(balance - daily_dr * r.uniform(0.5, 1.0), 2),
                "max_balance": round(balance + daily_cr * r.uniform(0.5, 1.0), 2),
            })
            balance = round(balance + daily_cr - daily_dr, 2)
    return pd.DataFrame(rows)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate massive synthetic transactions dataset")
    parser.add_argument("--accounts", type=int, default=300_000)
    parser.add_argument("--transactions", type=int, default=15_000_000)
    parser.add_argument("--threads", type=int, default=6)
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "raw" / "transactions"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("TRANSACTIONS SYNTHETIC DATA GENERATOR")
    print(f"  Accounts:     {args.accounts:,}")
    print(f"  Transactions: {args.transactions:,}")
    print(f"  Threads:      {args.threads}")
    print("=" * 60)

    # 1. Bank Accounts
    print("\n[1/6] Bank Accounts …")
    accounts_df = generate_bank_accounts(args.accounts)
    accounts_df.to_parquet(out_dir / "bank_accounts.parquet", index=False, compression="gzip")
    print(f"  Saved {len(accounts_df):,} accounts")
    account_ids = accounts_df["account_id"].tolist()
    customer_ids = accounts_df["customer_id"].tolist()

    # 2. Transactions — chunked by quarter
    print(f"\n[2/6] Transactions ({args.transactions:,}) …")
    quarters = [
        ("2023-01-01","2023-04-01"), ("2023-04-01","2023-07-01"),
        ("2023-07-01","2023-10-01"), ("2023-10-01","2024-01-01"),
        ("2024-01-01","2024-04-01"), ("2024-04-01","2024-07-01"),
        ("2024-07-01","2024-10-01"), ("2024-10-01","2025-01-01"),
        ("2025-01-01","2025-04-01"), ("2025-04-01","2025-07-01"),
        ("2025-07-01","2025-10-01"), ("2025-10-01","2026-01-01"),
        ("2026-01-01","2026-03-01"),
    ]
    per_quarter = args.transactions // len(quarters)
    all_txn_parts = []

    with ProcessPoolExecutor(max_workers=args.threads) as exe:
        futs = {
            exe.submit(generate_transactions_chunk, qi, per_quarter,
                       account_ids, customer_ids, qs, qe): (qi, qs, qe)
            for qi, (qs, qe) in enumerate(quarters)
        }
        for fut in as_completed(futs):
            qi, qs, qe = futs[fut]
            chunk = fut.result()
            label = qs[:7].replace("-","_")
            fname = f"transactions_{label}.parquet"
            chunk.to_parquet(out_dir / fname, index=False, compression="gzip")
            all_txn_parts.append(chunk)
            print(f"  Quarter {qs[:7]}: {len(chunk):,} rows | fraud: {chunk['fraud_flag'].sum():,}")

    txn_df = pd.concat(all_txn_parts, ignore_index=True)

    # 3. ACH Transfers
    print("\n[3/6] ACH Transfers …")
    ach_df = generate_ach_transfers(txn_df)
    ach_df.to_parquet(out_dir / "ach_transfers.parquet", index=False, compression="gzip")

    # 4. Wire Transfers
    print("\n[4/6] Wire Transfers …")
    wire_df = generate_wire_transfers(txn_df)
    wire_df.to_parquet(out_dir / "wire_transfers.parquet", index=False, compression="gzip")

    # 5. Fraud Alerts
    print("\n[5/6] Fraud Alerts …")
    fraud_df = generate_fraud_alerts(txn_df)
    fraud_df.to_parquet(out_dir / "fraud_alerts.parquet", index=False, compression="gzip")

    # 6. Daily Snapshots (sample 10k accounts for speed)
    print("\n[6/6] Daily Balance Snapshots (sample 10k accounts) …")
    sample_accts = accounts_df.sample(min(10_000, len(accounts_df)), random_state=42)
    acct_chunks = np.array_split(sample_accts, args.threads)
    snap_parts = []
    with ProcessPoolExecutor(max_workers=args.threads) as exe:
        futs = {exe.submit(generate_daily_snapshots_chunk, c, i): i for i, c in enumerate(acct_chunks)}
        for fut in as_completed(futs):
            snap_parts.append(fut.result())
    snaps_df = pd.concat(snap_parts, ignore_index=True)
    snaps_df.to_parquet(out_dir / "daily_balance_snapshots.parquet", index=False, compression="gzip")
    print(f"  Saved {len(snaps_df):,} snapshots")

    print("\n" + "=" * 60)
    print("TRANSACTIONS GENERATION COMPLETE")
    print("=" * 60)
    total_mb = sum(f.stat().st_size for f in out_dir.glob("*.parquet")) / (1024 ** 2)
    print(f"  Total output: {total_mb:.1f} MB")
    for f in sorted(out_dir.glob("*.parquet")):
        size_mb = f.stat().st_size / (1024 ** 2)
        print(f"  {f.name:<50} {size_mb:>7.1f} MB")


if __name__ == "__main__":
    main()
