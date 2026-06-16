"""
Massive synthetic CREDIT CARDS dataset generator.

Generates:
  - card_products          (7 product tiers)
  - card_accounts          (default 500 000)
  - card_transactions      (default 25 000 000, quarterly shards)
  - card_statements        (monthly statements per account)
  - card_disputes          (~1% of accounts have disputes)
  - rewards_redemptions    (~30% of active accounts)
  - credit_limit_changes   (historical limit changes)

Usage:
    python data/generate_credit_cards_data.py \
        [--accounts N] [--transactions N] [--threads T]

Outputs (Parquet, gzip) in data/raw/credit_cards/:
"""

import argparse
import hashlib
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import date

import numpy as np
import pandas as pd
from faker import Faker

fake = Faker("en_US")
Faker.seed(42)

# ─── Constants ────────────────────────────────────────────────────────────────
NETWORKS = ["Visa","Mastercard","Amex","Discover"]
NETWORK_PROBS = [0.40, 0.35, 0.15, 0.10]
CARD_TIERS = ["basic","standard","premium","ultra_premium","secured","student","business"]
TIER_PROBS = [0.15, 0.35, 0.25, 0.05, 0.08, 0.08, 0.04]
TXN_TYPES = [
    "purchase","cash_advance","balance_transfer","payment",
    "refund","fee","interest_charge","adjustment",
]
TXN_TYPE_PROBS = [0.68, 0.025, 0.015, 0.22, 0.03, 0.02, 0.025, 0.005]
TXN_CATEGORIES = [
    "groceries","restaurants","gas","utilities","rent_mortgage",
    "insurance","healthcare","entertainment","shopping_retail",
    "travel_airlines","travel_hotels","travel_other","transportation",
    "education","subscriptions","electronics","home_garden",
    "beauty_personal_care","sports_outdoors","government","other",
]
CAT_PROBS = [
    0.08,0.09,0.05,0.05,0.07,
    0.03,0.05,0.05,0.10,
    0.04,0.03,0.02,0.04,
    0.03,0.06,0.04,0.04,
    0.04,0.03,0.02,0.10,
]
ENTRY_MODES = ["chip","swipe","contactless","manual","online","token"]
ENTRY_MODE_PROBS = [0.40,0.10,0.20,0.02,0.22,0.06]
CHANNELS = ["in_store","online","mobile_app","phone","atm","contactless"]
CHANNEL_PROBS = [0.30,0.28,0.22,0.04,0.06,0.10]
DISPUTE_REASONS = [
    "not_authorized","item_not_received","item_not_as_described",
    "duplicate_charge","incorrect_amount","credit_not_processed",
    "subscription_cancelled","fraud","atm_dispute","other",
]
REDEMPTION_TYPES = ["statement_credit","gift_card","travel","merchandise","cashback_check","charity"]
LIMIT_CHANGE_TYPES = ["increase_customer_request","increase_auto","decrease_risk","decrease_regulatory"]
ACCOUNT_STATUSES = ["active","suspended","closed","charged_off","fraud_hold","credit_hold"]
ACCT_STATUS_PROBS = [0.82,0.04,0.06,0.02,0.02,0.04]
MERCHANTS = [
    "Amazon", "Walmart", "Target", "Costco", "Best Buy", "Apple Store",
    "McDonald's", "Starbucks", "Chipotle", "Chick-fil-A", "Panera Bread",
    "Shell", "BP", "Exxon", "Chevron",
    "Delta Air Lines", "United Airlines", "American Airlines",
    "Marriott", "Hilton", "Airbnb", "Hyatt",
    "Uber", "Lyft", "Hertz", "Enterprise",
    "Netflix", "Spotify", "Disney+", "Hulu", "Apple",
    "Whole Foods", "Kroger", "Publix", "Trader Joe's", "Safeway",
    "CVS", "Walgreens", "Rite Aid",
    "Home Depot", "Lowe's", "IKEA",
    "Nike", "Adidas", "Nordstrom", "Macy's", "Gap",
    "Zara", "H&M", "Forever 21",
    "Chase Bank", "Wells Fargo", "Bank of America",
    "Verizon", "AT&T", "T-Mobile",
]
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY",
]
MCC_MAP = {
    "groceries":"5411","restaurants":"5812","gas":"5541","utilities":"4900",
    "shopping_retail":"5999","travel_airlines":"3001","travel_hotels":"3501",
    "transportation":"4111","healthcare":"5912","electronics":"5732",
    "entertainment":"7999","subscriptions":"5999",
}

PRODUCT_CATALOG = [
    {"product_code":"VISA-BASIC","product_name":"Visa Classic","card_network":"Visa","card_tier":"basic",
     "purchase_apr":0.2499,"cash_advance_apr":0.2999,"annual_fee":0,"late_fee":29,
     "min_credit_limit":300,"max_credit_limit":5000,"min_credit_score":580,
     "rewards_type":"cashback","base_rewards_rate":0.01},
    {"product_code":"VISA-STD","product_name":"Visa Rewards","card_network":"Visa","card_tier":"standard",
     "purchase_apr":0.1999,"cash_advance_apr":0.2499,"annual_fee":0,"late_fee":39,
     "min_credit_limit":1000,"max_credit_limit":20000,"min_credit_score":640,
     "rewards_type":"cashback","base_rewards_rate":0.015},
    {"product_code":"MC-PREM","product_name":"Mastercard Platinum","card_network":"Mastercard","card_tier":"premium",
     "purchase_apr":0.1799,"cash_advance_apr":0.2299,"annual_fee":95,"late_fee":39,
     "min_credit_limit":5000,"max_credit_limit":50000,"min_credit_score":700,
     "rewards_type":"points","base_rewards_rate":0.02},
    {"product_code":"AMEX-GOLD","product_name":"Amex Gold Card","card_network":"Amex","card_tier":"ultra_premium",
     "purchase_apr":0.2799,"cash_advance_apr":0.2999,"annual_fee":250,"late_fee":39,
     "min_credit_limit":10000,"max_credit_limit":100000,"min_credit_score":720,
     "rewards_type":"points","base_rewards_rate":0.04},
    {"product_code":"VISA-SECURED","product_name":"Visa Secured Card","card_network":"Visa","card_tier":"secured",
     "purchase_apr":0.2299,"cash_advance_apr":0.2499,"annual_fee":35,"late_fee":25,
     "min_credit_limit":200,"max_credit_limit":2500,"min_credit_score":300,
     "rewards_type":"none","base_rewards_rate":0.0},
    {"product_code":"DISC-STUDENT","product_name":"Discover it Student","card_network":"Discover","card_tier":"student",
     "purchase_apr":0.1999,"cash_advance_apr":0.2499,"annual_fee":0,"late_fee":0,
     "min_credit_limit":500,"max_credit_limit":5000,"min_credit_score":580,
     "rewards_type":"cashback","base_rewards_rate":0.01},
    {"product_code":"MC-BIZ","product_name":"Mastercard Business","card_network":"Mastercard","card_tier":"business",
     "purchase_apr":0.1599,"cash_advance_apr":0.2199,"annual_fee":99,"late_fee":39,
     "min_credit_limit":2000,"max_credit_limit":150000,"min_credit_score":660,
     "rewards_type":"cashback","base_rewards_rate":0.02},
]


def _uuid_str() -> str:
    return str(uuid.uuid4())


def _hash_card(n_str: str) -> str:
    return hashlib.sha256(n_str.encode()).hexdigest()


# ─── Products ─────────────────────────────────────────────────────────────────

def generate_card_products() -> pd.DataFrame:
    rows = []
    for p in PRODUCT_CATALOG:
        rows.append({
            "product_id": _uuid_str(),
            **p,
            "foreign_transaction_fee_pct": 0.03 if "Amex" not in p["card_network"] else 0.0,
            "cash_advance_fee_pct": 0.05,
            "balance_transfer_fee_pct": 0.03,
            "sign_up_bonus_amount": {"basic":0,"standard":200,"premium":500,"ultra_premium":750,"secured":0,"student":100,"business":750}.get(p["card_tier"],0),
            "sign_up_spend_requirement": {"standard":1500,"premium":4000,"ultra_premium":6000,"student":500,"business":5000}.get(p["card_tier"],0),
            "sign_up_months": 3,
            "intro_apr": 0.0,
            "intro_apr_months": {"standard":15,"premium":12,"ultra_premium":0}.get(p["card_tier"],0),
            "is_active": True,
            "created_at": pd.Timestamp("2020-01-01", tz="UTC"),
        })
    return pd.DataFrame(rows)


# ─── Card Accounts ────────────────────────────────────────────────────────────

def generate_card_accounts(n: int, products_df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    r = np.random.default_rng(seed)
    print(f"  Generating {n:,} card accounts …")

    account_ids = [_uuid_str() for _ in range(n)]
    customer_ids = [_uuid_str() for _ in range(n)]

    # Assign product by tier weights
    product_ids = r.choice(products_df["product_id"].values, size=n,
                           p=[1/len(products_df)]*len(products_df))
    prod_lookup = products_df.set_index("product_id")

    networks = [str(prod_lookup.loc[p,"card_network"]) for p in product_ids]
    tiers = [str(prod_lookup.loc[p,"card_tier"]) for p in product_ids]
    min_limits = np.array([float(prod_lookup.loc[p,"min_credit_limit"]) for p in product_ids])
    max_limits = np.array([float(prod_lookup.loc[p,"max_credit_limit"]) for p in product_ids])
    aprs = np.array([float(prod_lookup.loc[p,"purchase_apr"]) for p in product_ids])

    credit_limits = np.round(
        np.exp(r.uniform(np.log(min_limits), np.log(max_limits))),
        -2,  # round to nearest 100
    ).clip(min_limits, max_limits)

    open_days_ago = r.integers(30, 1825, size=n)
    open_date = (pd.Timestamp("2026-03-01") - pd.to_timedelta(open_days_ago, unit="D")).dt.date
    expiry_date = (pd.Timestamp("2026-03-01") + pd.to_timedelta(r.integers(180, 1825, size=n), unit="D")).dt.date

    # Balance — logistic relative to credit limit
    utilization = r.beta(1.5, 3, size=n)  # right-skewed, avg ~33%
    current_balance = np.round(credit_limits * utilization, 2)

    status = r.choice(ACCOUNT_STATUSES, size=n, p=ACCT_STATUS_PROBS)
    months_on_book = (open_days_ago // 30).astype(int)

    card_nums = [f"{r.integers(4000000000000000,4999999999999999)}" for _ in range(n)]
    bins_arr = [c[:8] for c in card_nums]

    # Delinquency
    dpd = np.where(
        status == "active", r.choice([0,0,0,30,60,90], size=n, p=[0.70,0.10,0.08,0.06,0.04,0.02]),
        np.where(status.isin(["charged_off"]) if hasattr(status,"isin") else np.isin(status,["charged_off"]),
                 r.integers(90, 365, size=n), 0)
    )

    last_pmt_days_ago = r.integers(1, 45, size=n)
    last_pmt_date = (pd.Timestamp("2026-03-01") - pd.to_timedelta(last_pmt_days_ago, unit="D")).dt.date

    df = pd.DataFrame({
        "card_account_id": account_ids,
        "customer_id": customer_ids,
        "product_id": product_ids,
        "card_number_hash": [_hash_card(c) for c in card_nums],
        "card_number_last4": [c[-4:] for c in card_nums],
        "card_number_bin": bins_arr,
        "card_network": networks,
        "card_type": r.choice(["physical","virtual","both"], size=n, p=[0.60,0.20,0.20]),
        "account_status": status,
        "account_open_date": open_date,
        "card_expiry_date": expiry_date,
        "card_activation_date": (pd.Timestamp("2026-03-01") - pd.to_timedelta(open_days_ago - r.integers(1,10,size=n), unit="D")).dt.date,
        "credit_limit": np.round(credit_limits, 2),
        "current_balance": current_balance,
        "cash_advance_balance": np.round(current_balance * r.uniform(0, 0.1, size=n), 2),
        "statement_balance": np.round(current_balance * r.uniform(0.90, 1.10, size=n), 2),
        "minimum_payment_due": np.round(np.maximum(current_balance * 0.02, 25), 2),
        "payment_due_date": (pd.Timestamp("2026-03-01") + pd.to_timedelta(r.integers(1, 30, size=n), unit="D")).dt.date,
        "last_payment_date": last_pmt_date,
        "last_payment_amount": np.round(current_balance * r.uniform(0.02, 1.1, size=n), 2),
        "autopay_enrolled": r.random(size=n) < 0.45,
        "autopay_type": r.choice(["minimum","statement_balance","full_balance","fixed_amount"], size=n, p=[0.30,0.35,0.20,0.15]),
        "months_on_book": months_on_book,
        "times_30dpd": r.integers(0, 5, size=n).astype(int),
        "times_60dpd": r.integers(0, 3, size=n).astype(int),
        "times_90dpd": r.integers(0, 2, size=n).astype(int),
        "current_delinquency_days": dpd.astype(int),
        "rewards_balance_points": r.integers(0, 100_000, size=n).astype(int),
        "rewards_balance_dollars": np.round(r.uniform(0, 500, size=n), 2),
        "lifetime_rewards_earned": np.round(r.uniform(0, 2000, size=n), 2),
        "interest_rate_apr": np.round(aprs, 4),
        "closing_date_day": r.integers(1, 29, size=n).astype(int),
        "domestic_transactions": True,
        "international_transactions": r.random(size=n) < 0.25,
        "online_transactions": True,
        "contactless_enabled": r.random(size=n) < 0.80,
        "created_at": pd.Timestamp("2026-03-01", tz="UTC") - pd.to_timedelta(open_days_ago, unit="D"),
        "updated_at": pd.Timestamp("2026-03-01", tz="UTC"),
    })
    return df


# ─── Card Transactions (chunked) ─────────────────────────────────────────────

def generate_card_txns_chunk(
    chunk_id: int,
    n: int,
    account_ids: list,
    customer_ids: list,
    credit_limits: np.ndarray,
    start_ts: str,
    end_ts: str,
) -> pd.DataFrame:
    r = np.random.default_rng(chunk_id * 77777)

    acct_idx = r.integers(0, len(account_ids), size=n)
    acct_arr = np.array(account_ids)[acct_idx]
    cust_arr = np.array(customer_ids)[acct_idx]
    limits_arr = credit_limits[acct_idx]

    txn_types = r.choice(TXN_TYPES, size=n, p=TXN_TYPE_PROBS)
    categories = r.choice(TXN_CATEGORIES, size=n, p=CAT_PROBS)
    is_purchase = txn_types == "purchase"

    # Amounts correlated to credit limit tier
    base_amounts = np.exp(r.normal(4.5, 1.1, size=n)).clip(1, 5000)
    amounts = np.round(
        np.where(is_purchase, base_amounts,
                 np.where(txn_types == "cash_advance", base_amounts * r.uniform(2, 5, size=n),
                          np.where(txn_types == "payment", base_amounts * r.uniform(5, 20, size=n),
                                   base_amounts))),
        2,
    ).clip(1, 50000)

    s = pd.Timestamp(start_ts).value
    e = pd.Timestamp(end_ts).value
    auth_ns = r.integers(s, e, size=n)
    auth_at = pd.to_datetime(auth_ns)

    # Fraud
    fraud_scores = r.beta(1, 25, size=n)
    is_large = amounts > limits_arr * 0.5
    fraud_flag = (fraud_scores > 0.82) | (is_large & (r.random(size=n) < 0.04))
    fraud_scores = np.where(fraud_flag, r.uniform(0.82, 1.0, size=n), fraud_scores)

    merchants_arr = r.choice(MERCHANTS, size=n)
    mccs_arr = [MCC_MAP.get(c, "5999") for c in categories]
    states_arr = r.choice(US_STATES, size=n)

    # Rewards
    rewards_mult = np.where(
        np.isin(categories, ["travel_airlines","travel_hotels"]), r.uniform(2.0, 5.0, size=n),
        np.where(np.isin(categories, ["restaurants","groceries"]), r.uniform(2.0, 3.0, size=n), 1.0)
    )
    points_earned = np.where(is_purchase, (amounts * rewards_mult * 100).astype(int), 0)
    dollars_earned = np.round(np.where(is_purchase, amounts * rewards_mult * 0.01, 0.0), 4)

    is_intl = r.random(size=n) < 0.06
    is_recurring = np.isin(categories, ["subscriptions","utilities","insurance"]) & (r.random(size=n) < 0.7)

    txn_status = np.where(
        fraud_flag & (r.random(size=n) < 0.20), "fraud",
        np.where(r.random(size=n) < 0.02, "authorized",
                 np.where(r.random(size=n) < 0.005, "reversed", "posted"))
    )

    df = pd.DataFrame({
        "card_txn_id": [_uuid_str() for _ in range(n)],
        "card_account_id": acct_arr,
        "customer_id": cust_arr,
        "txn_type": txn_types,
        "txn_category": categories,
        "amount": amounts,
        "currency_code": "USD",
        "billing_amount": amounts,
        "fx_rate": 1.0,
        "merchant_name": merchants_arr,
        "merchant_category_code": mccs_arr,
        "merchant_state": states_arr,
        "merchant_country": np.where(is_intl, r.choice(["GB","DE","FR","JP","CA","MX","AU"], size=n), "US"),
        "authorization_code": [f"{r.integers(100000,999999)}" for _ in range(n)],
        "authorization_at": auth_at.tz_localize("UTC"),
        "posted_at": (auth_at + pd.to_timedelta(r.integers(0, 3, size=n), unit="D")).tz_localize("UTC"),
        "is_pending": r.random(size=n) < 0.04,
        "txn_status": txn_status,
        "card_present": ~np.isin(categories,["subscriptions","entertainment","travel_airlines"]),
        "entry_mode": r.choice(ENTRY_MODES, size=n, p=ENTRY_MODE_PROBS),
        "is_international": is_intl,
        "is_recurring": is_recurring,
        "fraud_score": np.round(fraud_scores, 4),
        "fraud_flag": fraud_flag,
        "dispute_flag": fraud_flag & (r.random(size=n) < 0.20),
        "channel": r.choice(CHANNELS, size=n, p=CHANNEL_PROBS),
        "rewards_multiplier": np.round(rewards_mult, 3),
        "rewards_points_earned": points_earned.astype(int),
        "rewards_dollars_earned": dollars_earned,
        "device_type": r.choice(["iPhone","Android","Desktop","Tablet","Unknown"], size=n),
        "created_at": auth_at.tz_localize("UTC"),
    })
    return df


# ─── Statements ───────────────────────────────────────────────────────────────

def generate_statements_chunk(accounts_chunk: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 100)
    rows = []
    months = pd.date_range("2023-01-01", "2026-03-01", freq="MS")

    for _, acct in accounts_chunk.iterrows():
        open_date = pd.Timestamp(acct["account_open_date"])
        balance = 0.0
        limit = float(acct["credit_limit"])

        for stmt_date in months:
            if stmt_date < open_date:
                continue
            purchases = round(limit * r.uniform(0.01, 0.35), 2)
            payments = round(purchases * r.uniform(0.50, 1.50), 2)
            interest = round(max(balance * float(acct["interest_rate_apr"]) / 12, 0), 2)
            fees = round(r.choice([0, 0, 0, 29, 39], p=[0.85,0.05,0.04,0.04,0.02]), 2)

            statement_balance = round(balance + purchases + interest + fees - payments, 2)
            statement_balance = max(statement_balance, 0)
            min_payment = round(max(statement_balance * 0.02, 25 if statement_balance > 0 else 0), 2)
            paid_full = payments >= balance
            delinquent = r.random() < 0.04

            rows.append({
                "statement_id": _uuid_str(),
                "card_account_id": acct["card_account_id"],
                "customer_id": acct["customer_id"],
                "statement_date": stmt_date.date(),
                "payment_due_date": (stmt_date + pd.DateOffset(days=25)).date(),
                "cycle_start_date": (stmt_date - pd.DateOffset(months=1)).date(),
                "cycle_end_date": stmt_date.date(),
                "opening_balance": round(balance, 2),
                "closing_balance": round(statement_balance, 2),
                "statement_balance": round(statement_balance, 2),
                "minimum_payment_due": min_payment,
                "total_purchases": purchases,
                "total_payments": payments,
                "total_fees": fees,
                "total_interest": interest,
                "purchase_count": int(r.integers(0, 40)),
                "payment_count": int(r.integers(0, 3)),
                "purchase_apr": acct["interest_rate_apr"],
                "paid_in_full": paid_full,
                "was_delinquent": delinquent,
                "late_fee_charged": 29.0 if delinquent else 0.0,
                "rewards_points_earned": int(purchases * 100 * r.uniform(1, 4)),
                "rewards_dollars_earned": round(purchases * r.uniform(0.01, 0.04), 4),
                "credit_limit_at_close": limit,
                "utilization_at_close": round(statement_balance / limit if limit > 0 else 0, 4),
            })
            balance = statement_balance
    return pd.DataFrame(rows)


# ─── Disputes ─────────────────────────────────────────────────────────────────

def generate_disputes(accounts_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 200)
    candidates = accounts_df.sample(frac=0.01, random_state=seed)
    rows = []
    for _, acct in candidates.iterrows():
        n_disp = r.integers(1, 4)
        for _ in range(n_disp):
            filed = pd.Timestamp(acct["account_open_date"]) + pd.DateOffset(months=int(r.integers(1, 24)))
            status = r.choice(
                ["filed","under_review","provisional_credit","resolved_cardholder","resolved_merchant","withdrawn"],
                p=[0.10,0.15,0.20,0.30,0.20,0.05],
            )
            rows.append({
                "dispute_id": _uuid_str(),
                "card_account_id": acct["card_account_id"],
                "card_txn_id": _uuid_str(),
                "customer_id": acct["customer_id"],
                "dispute_reason": r.choice(DISPUTE_REASONS),
                "dispute_amount": round(float(r.uniform(10, 500)), 2),
                "dispute_status": status,
                "filed_date": filed.date(),
                "resolution_date": (filed + pd.DateOffset(days=int(r.integers(30, 90)))).date()
                    if status in ["resolved_cardholder","resolved_merchant","withdrawn"] else None,
                "final_outcome": r.choice(["cardholder_wins","merchant_wins","split"]) if "resolved" in status else None,
                "chargeback_cycle": int(r.integers(1, 3)),
                "arbitration_flag": r.random() < 0.05,
                "created_at": pd.Timestamp(filed, tz="UTC"),
                "updated_at": pd.Timestamp("2026-03-01", tz="UTC"),
            })
    return pd.DataFrame(rows)


# ─── Rewards Redemptions ──────────────────────────────────────────────────────

def generate_redemptions(accounts_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 300)
    redeemers = accounts_df[
        (accounts_df["account_status"] == "active") &
        (accounts_df["rewards_balance_points"] > 1000)
    ].sample(frac=0.30, random_state=seed)
    rows = []
    for _, acct in redeemers.iterrows():
        n_redemp = r.integers(1, 6)
        for _ in range(n_redemp):
            rtype = r.choice(REDEMPTION_TYPES)
            pts = int(r.integers(500, min(int(acct["rewards_balance_points"]) + 1, 100_001)))
            val = round(pts * 0.01, 2)
            rows.append({
                "redemption_id": _uuid_str(),
                "card_account_id": acct["card_account_id"],
                "customer_id": acct["customer_id"],
                "redemption_type": rtype,
                "points_redeemed": pts,
                "dollars_redeemed": val,
                "redemption_value": val,
                "redemption_status": r.choice(["completed","pending","reversed"], p=[0.90,0.07,0.03]),
                "partner_name": r.choice(["Amazon","Delta","Marriott","Target",None], p=[0.15,0.10,0.10,0.10,0.55]),
                "redeemed_at": pd.Timestamp("2026-03-01", tz="UTC") - pd.to_timedelta(int(r.integers(1, 730)), unit="D"),
                "created_at": pd.Timestamp("2026-03-01", tz="UTC") - pd.to_timedelta(int(r.integers(1, 730)), unit="D"),
            })
    return pd.DataFrame(rows)


# ─── Credit Limit Changes ─────────────────────────────────────────────────────

def generate_limit_changes(accounts_df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    r = np.random.default_rng(seed + 400)
    candidates = accounts_df.sample(frac=0.15, random_state=seed)
    rows = []
    for _, acct in candidates.iterrows():
        n_changes = r.integers(1, 4)
        prev_limit = float(acct["credit_limit"]) * r.uniform(0.5, 0.9)
        for i in range(n_changes):
            change_type = r.choice(LIMIT_CHANGE_TYPES)
            new_limit = round(prev_limit * r.uniform(1.1, 2.0) if "increase" in change_type else prev_limit * r.uniform(0.5, 0.9), -2)
            eff_date = pd.Timestamp(acct["account_open_date"]) + pd.DateOffset(months=int(r.integers(1, 36)))
            rows.append({
                "change_id": _uuid_str(),
                "card_account_id": acct["card_account_id"],
                "customer_id": acct["customer_id"],
                "change_type": change_type,
                "previous_limit": round(prev_limit, 2),
                "new_limit": round(new_limit, 2),
                "change_reason": r.choice(["good_payment_history","income_increase","risk_review","request"]),
                "credit_score_at_change": int(r.integers(580, 820)),
                "effective_date": eff_date.date(),
                "approved_by": r.choice(["system","analyst","manager"]),
                "created_at": pd.Timestamp(eff_date, tz="UTC"),
            })
            prev_limit = new_limit
    return pd.DataFrame(rows)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate massive credit cards dataset")
    parser.add_argument("--accounts", type=int, default=500_000)
    parser.add_argument("--transactions", type=int, default=25_000_000)
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--skip-statements", action="store_true")
    args = parser.parse_args()

    out_dir = Path(__file__).parent / "raw" / "credit_cards"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("CREDIT CARDS SYNTHETIC DATA GENERATOR")
    print(f"  Accounts:     {args.accounts:,}")
    print(f"  Transactions: {args.transactions:,}")
    print(f"  Threads:      {args.threads}")
    print("=" * 60)

    # 1. Products
    print("\n[1/7] Card Products …")
    products_df = generate_card_products()
    products_df.to_parquet(out_dir / "card_products.parquet", index=False, compression="gzip")
    print(f"  Saved {len(products_df)} products")

    # 2. Card Accounts
    print(f"\n[2/7] Card Accounts ({args.accounts:,}) …")
    accounts_df = generate_card_accounts(args.accounts, products_df)
    accounts_df.to_parquet(out_dir / "card_accounts.parquet", index=False, compression="gzip")
    print(f"  Saved {len(accounts_df):,} accounts")
    account_ids = accounts_df["card_account_id"].tolist()
    customer_ids = accounts_df["customer_id"].tolist()
    credit_limits = accounts_df["credit_limit"].values

    # 3. Card Transactions — quarterly shards
    print(f"\n[3/7] Card Transactions ({args.transactions:,}) …")
    quarters = [
        ("2023-01-01","2023-04-01","2023_q1"), ("2023-04-01","2023-07-01","2023_q2"),
        ("2023-07-01","2023-10-01","2023_q3"), ("2023-10-01","2024-01-01","2023_q4"),
        ("2024-01-01","2024-04-01","2024_q1"), ("2024-04-01","2024-07-01","2024_q2"),
        ("2024-07-01","2024-10-01","2024_q3"), ("2024-10-01","2025-01-01","2024_q4"),
        ("2025-01-01","2025-04-01","2025_q1"), ("2025-04-01","2025-07-01","2025_q2"),
        ("2025-07-01","2025-10-01","2025_q3"), ("2025-10-01","2026-01-01","2025_q4"),
        ("2026-01-01","2026-03-17","2026_q1"),
    ]
    per_quarter = args.transactions // len(quarters)

    with ProcessPoolExecutor(max_workers=args.threads) as exe:
        futs = {
            exe.submit(generate_card_txns_chunk, qi, per_quarter,
                       account_ids, customer_ids, credit_limits, qs, qe): label
            for qi, (qs, qe, label) in enumerate(quarters)
        }
        for fut in as_completed(futs):
            label = futs[fut]
            chunk = fut.result()
            fname = f"card_transactions_{label}.parquet"
            chunk.to_parquet(out_dir / fname, index=False, compression="gzip")
            fraud_ct = chunk["fraud_flag"].sum()
            print(f"  {label}: {len(chunk):,} txns | fraud: {fraud_ct:,} ({fraud_ct/len(chunk)*100:.2f}%)")

    # 4. Statements
    if not args.skip_statements:
        print(f"\n[4/7] Card Statements (sample 50k accounts) …")
        sample_accts = accounts_df.sample(min(50_000, len(accounts_df)), random_state=42)
        acct_chunks = np.array_split(sample_accts, args.threads)
        stmt_parts = []
        with ProcessPoolExecutor(max_workers=args.threads) as exe:
            futs = {exe.submit(generate_statements_chunk, c, i): i for i, c in enumerate(acct_chunks)}
            for fut in as_completed(futs):
                stmt_parts.append(fut.result())
        stmts_df = pd.concat(stmt_parts, ignore_index=True)
        stmts_df.to_parquet(out_dir / "card_statements.parquet", index=False, compression="gzip")
        print(f"  Saved {len(stmts_df):,} statements")
    else:
        print("\n[4/7] Skipped statement generation")

    # 5. Disputes
    print(f"\n[5/7] Card Disputes …")
    disputes_df = generate_disputes(accounts_df)
    disputes_df.to_parquet(out_dir / "card_disputes.parquet", index=False, compression="gzip")
    print(f"  Saved {len(disputes_df):,} disputes")

    # 6. Rewards Redemptions
    print(f"\n[6/7] Rewards Redemptions …")
    redemp_df = generate_redemptions(accounts_df)
    redemp_df.to_parquet(out_dir / "rewards_redemptions.parquet", index=False, compression="gzip")
    print(f"  Saved {len(redemp_df):,} redemptions")

    # 7. Credit Limit Changes
    print(f"\n[7/7] Credit Limit Changes …")
    limit_df = generate_limit_changes(accounts_df)
    limit_df.to_parquet(out_dir / "credit_limit_changes.parquet", index=False, compression="gzip")
    print(f"  Saved {len(limit_df):,} limit changes")

    print("\n" + "=" * 60)
    print("CREDIT CARDS GENERATION COMPLETE")
    print("=" * 60)
    total_mb = sum(f.stat().st_size for f in out_dir.glob("*.parquet")) / (1024 ** 2)
    print(f"  Total output: {total_mb:.1f} MB")
    for f in sorted(out_dir.glob("*.parquet")):
        size_mb = f.stat().st_size / (1024 ** 2)
        print(f"  {f.name:<55} {size_mb:>7.1f} MB")


if __name__ == "__main__":
    main()
