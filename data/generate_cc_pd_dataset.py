"""
Credit Card PD (Probability of Default) — Synthetic Dataset Generator
======================================================================
Generates 5 000 000 credit card origination records with rich behavioural
features and a calibrated default label, plus a linked transaction summary
spine (aggregated from ~80 M simulated transactions).

Output files (Parquet, gzip) written to  data/raw/cc_pd/:
  origination_5m.parquet       — application / underwriting snapshot
  txn_summary_5m.parquet       — 12-month behavioural aggregates
  pd_training_5m.parquet       — merged, model-ready feature matrix
  cost_assumptions.parquet     — per-account cost ledger for policy dev

All generation is vectorised (NumPy / Pandas) — no Python loops over 5 M rows.

Usage
-----
    python data/generate_cc_pd_dataset.py [--records 5_000_000] [--seed 42]
    python data/generate_cc_pd_dataset.py --records 100_000          # quick smoke test
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

OUT_DIR = Path(__file__).parent / "raw" / "cc_pd"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ─── Product catalogue ────────────────────────────────────────────────────────
PRODUCTS = {
    "secured":        dict(apr_base=24.99, annual_fee=35,  cl_min=200,  cl_max=1_000,   reward_rate=0.0),
    "student":        dict(apr_base=20.99, annual_fee=0,   cl_min=500,  cl_max=3_000,   reward_rate=0.01),
    "basic":          dict(apr_base=19.99, annual_fee=0,   cl_min=1_000, cl_max=7_500,  reward_rate=0.01),
    "rewards":        dict(apr_base=18.99, annual_fee=95,  cl_min=2_000, cl_max=20_000, reward_rate=0.015),
    "premium":        dict(apr_base=17.99, annual_fee=250, cl_min=5_000, cl_max=50_000, reward_rate=0.02),
    "ultra_premium":  dict(apr_base=16.99, annual_fee=550, cl_min=10_000, cl_max=100_000, reward_rate=0.03),
    "business":       dict(apr_base=18.49, annual_fee=95,  cl_min=3_000, cl_max=75_000, reward_rate=0.02),
}
PRODUCT_NAMES  = list(PRODUCTS.keys())
PRODUCT_PROBS  = [0.08, 0.10, 0.22, 0.28, 0.18, 0.06, 0.08]

RISK_GRADES = ["Super-Prime", "Prime-Plus", "Prime", "Near-Prime", "Sub-Prime"]
RISK_GRADE_PROBS = [0.15, 0.25, 0.30, 0.20, 0.10]

FICO_BANDS = {
    "Super-Prime" : (750, 850),
    "Prime-Plus"  : (720, 749),
    "Prime"       : (670, 719),
    "Near-Prime"  : (620, 669),
    "Sub-Prime"   : (300, 619),
}
BASE_PD = {          # annual PD by risk grade
    "Super-Prime" : 0.008,
    "Prime-Plus"  : 0.018,
    "Prime"       : 0.040,
    "Near-Prime"  : 0.095,
    "Sub-Prime"   : 0.220,
}

STATES = [
    "CA","TX","FL","NY","PA","IL","OH","GA","NC","MI","NJ","VA","WA","AZ",
    "MA","TN","IN","MO","MD","WI","CO","MN","SC","AL","LA","KY","OR","OK",
    "CT","UT","IA","NV","AR","MS","KS","NM","NE","ID","WV","HI","NH","ME",
    "MT","RI","DE","SD","ND","AK","VT","WY",
]
STATE_PROBS = [
    0.095,0.085,0.070,0.065,0.040,0.038,0.035,0.033,0.032,0.030,
    0.029,0.027,0.026,0.025,0.024,0.023,0.022,0.021,0.020,0.019,
    0.018,0.017,0.016,0.015,0.014,0.013,0.012,0.011,0.010,0.009,
    0.008,0.008,0.007,0.007,0.006,0.006,0.005,0.005,0.004,0.004,
    0.003,0.003,0.003,0.003,0.002,0.002,0.002,0.001,0.001,0.001,
]


# ─── Helper functions ─────────────────────────────────────────────────────────

def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _clip(arr: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return np.clip(arr, lo, hi)


def _bounded_normal(rng, mu, sigma, lo, hi, n):
    raw = rng.normal(mu, sigma, n)
    return _clip(raw, lo, hi)


def _categorical(rng, choices, probs, n):
    probs_arr = np.array(probs, dtype=float)
    probs_arr /= probs_arr.sum()
    idx = rng.choice(len(choices), size=n, p=probs_arr)
    return np.array(choices)[idx]


# ─── Step 1 : Origination attributes ─────────────────────────────────────────

def build_origination(n: int, rng: np.random.Generator) -> pd.DataFrame:
    log.info("  Generating origination features for %d accounts …", n)

    risk_grade = _categorical(rng, RISK_GRADES, RISK_GRADE_PROBS, n)
    product    = _categorical(rng, PRODUCT_NAMES, PRODUCT_PROBS, n)
    state      = _categorical(rng, STATES, STATE_PROBS, n)

    # FICO score — band-specific normal
    fico = np.empty(n, dtype=float)
    for grade, (lo, hi) in FICO_BANDS.items():
        mask = risk_grade == grade
        mu = (lo + hi) / 2
        fico[mask] = _bounded_normal(rng, mu, (hi - lo) / 4.5, lo, hi, mask.sum())
    fico = fico.round().astype(int)

    # Age 18–80, right-skewed
    age = _bounded_normal(rng, 38, 13, 18, 80, n).round().astype(int)

    # Annual income: log-normal, age-adjusted
    log_inc = rng.normal(10.8 + 0.01 * (age - 30), 0.6, n)
    annual_income = np.exp(log_inc).round(-2)  # round to hundreds
    annual_income = _clip(annual_income, 12_000, 5_000_000)

    # Monthly debt obligations
    monthly_debt = annual_income / 12 * _bounded_normal(rng, 0.18, 0.10, 0.0, 0.75, n)
    dti = monthly_debt / (annual_income / 12)
    dti = _clip(dti, 0.0, 0.75)

    # Employment
    emp_years = _bounded_normal(rng, 7, 6, 0, 45, n).round(1)
    employment_status = np.where(
        emp_years < 0.25, "unemployed",
        np.where(emp_years < 2, "employed_lt2yr", "employed_ge2yr")
    )

    # Bureau tradelines
    num_open_trades     = _bounded_normal(rng, 8,  4,  0, 40, n).round().astype(int)
    num_derog_marks     = rng.poisson(0.3 * np.log1p(1 - fico / 850 + 0.1) * 4, n).astype(int)
    num_derog_marks     = _clip(num_derog_marks, 0, 15).astype(int)
    months_oldest_trade = _bounded_normal(rng, 96, 60, 1, 360, n).round().astype(int)
    inq_last_6m         = rng.poisson(1.5 + 3 * (1 - fico / 850), n).astype(int)
    inq_last_6m         = _clip(inq_last_6m, 0, 20).astype(int)
    pct_rev_utilization = _bounded_normal(
        rng,
        0.20 + 0.50 * (1 - fico / 850),
        0.14, 0.0, 0.99, n
    )
    num_bk              = rng.binomial(1, 0.008 + 0.10 * (1 - fico / 850), n)
    months_since_last_delinq = rng.integers(1, 120, n) * (num_derog_marks > 0)

    # Product attributes
    apr_base   = np.array([PRODUCTS[p]["apr_base"]   for p in product])
    annual_fee = np.array([PRODUCTS[p]["annual_fee"] for p in product])
    cl_min     = np.array([PRODUCTS[p]["cl_min"]     for p in product])
    cl_max     = np.array([PRODUCTS[p]["cl_max"]     for p in product])

    # Approved credit limit — income + fico driven
    cl_factor  = 0.15 * (fico / 850) + 0.05 * (annual_income / 80_000)
    credit_limit = _clip(annual_income * cl_factor, cl_min, cl_max).round(-2)

    # APR = base + risk spread (higher for lower scores)
    apr_spread = 6 * (1 - fico / 850) ** 1.5
    apr = _clip(apr_base + apr_spread + rng.normal(0, 0.5, n), 8.99, 29.99).round(2)

    # Application channel
    app_channel = _categorical(
        rng,
        ["online", "branch", "phone", "mail", "partner"],
        [0.52, 0.20, 0.12, 0.06, 0.10], n
    )

    # Origination date (last 5 years)
    orig_days_ago   = rng.integers(0, 365 * 5, n)
    orig_date       = pd.Timestamp("2021-01-01") + pd.to_timedelta(orig_days_ago, "D")

    account_id = np.arange(1, n + 1, dtype=np.int64)

    return pd.DataFrame({
        "account_id"                : account_id,
        "orig_date"                 : orig_date,
        "product"                   : product,
        "risk_grade"                : risk_grade,
        "state"                     : state,
        "age"                       : age,
        "annual_income"             : annual_income.astype(int),
        "monthly_debt"              : monthly_debt.round(2),
        "dti"                       : dti.round(4),
        "employment_status"         : employment_status,
        "emp_years"                 : emp_years,
        "fico_score"                : fico,
        "num_open_trades"           : num_open_trades,
        "num_derog_marks"           : num_derog_marks,
        "months_oldest_trade"       : months_oldest_trade,
        "inq_last_6m"               : inq_last_6m,
        "pct_rev_utilization"       : pct_rev_utilization.round(4),
        "num_bankruptcy"            : num_bk,
        "months_since_last_delinq"  : months_since_last_delinq,
        "credit_limit"              : credit_limit.astype(int),
        "apr"                       : apr,
        "annual_fee"                : annual_fee.astype(int),
        "app_channel"               : app_channel,
    })


# ─── Step 2 : 12-month behavioural / transactional summary ───────────────────

def build_txn_summary(orig: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Simulates ~12 months of account behaviour.  All aggregates are vectorised —
    no transaction-level rows are materialised in RAM; the summary statistics are
    generated directly from calibrated distributions.
    """
    n   = len(orig)
    log.info("  Generating 12-month behavioural aggregates for %d accounts …", n)

    cl  = orig["credit_limit"].values.astype(float)
    fico = orig["fico_score"].values.astype(float)
    inc  = orig["annual_income"].values.astype(float)

    # Utilisation trajectory
    avg_utilization    = _clip(orig["pct_rev_utilization"].values + rng.normal(0, 0.08, n), 0.0, 1.0)
    max_utilization    = _clip(avg_utilization + rng.uniform(0.05, 0.30, n), 0.0, 1.0)
    end_utilization    = _clip(avg_utilization + rng.normal(0, 0.10, n), 0.0, 1.0)

    # Purchase behaviour
    monthly_spend      = inc / 12 * _bounded_normal(rng, 0.25, 0.15, 0.0, 1.5, n)
    total_purchases    = (monthly_spend * 12 * rng.uniform(0.6, 1.1, n)).round(2)
    num_purchase_txns  = _clip((total_purchases / 65).round().astype(int), 0, 2_500)

    # Cash advance — rare, higher default signal
    has_cash_advance   = rng.binomial(1, 0.08 + 0.15 * (1 - fico / 850), n)
    cash_advance_total = (cl * 0.08 * rng.uniform(0.1, 0.5, n) * has_cash_advance).round(2)
    num_cash_adv_txns  = (has_cash_advance * rng.integers(1, 8, n)).astype(int)

    # Payments
    num_missed_payments = rng.poisson(0.05 + 1.5 * (1 - fico / 850) ** 2, n).astype(int)
    num_missed_payments = _clip(num_missed_payments, 0, 12).astype(int)
    pct_ontime_payments = _clip(1 - num_missed_payments / 12 + rng.normal(0, 0.03, n), 0.0, 1.0)

    # Balance dynamics
    avg_balance        = cl * avg_utilization
    min_payment_ratio  = _bounded_normal(rng, 0.15, 0.10, 0.02, 1.0, n)

    # Overlimit events
    overlimit_months   = rng.binomial(12, 0.01 + 0.10 * avg_utilization, n)

    # Statements — payments history
    autopay_enroll     = rng.binomial(1, 0.38 + 0.25 * (fico / 850 - 0.5), n).astype(bool)

    # Fees
    late_fees          = (num_missed_payments * rng.choice([27, 38, 40], n)).round(2)
    overlimit_fees     = (overlimit_months * 25).astype(float)
    annual_fee_paid    = orig["annual_fee"].values.astype(float)
    interest_charged   = (avg_balance * orig["apr"].values / 100 * rng.uniform(0.7, 1.1, n)).round(2)

    # Revenue signals
    interchange_rev    = (total_purchases * 0.0155).round(2)  # ~1.55% interchange
    total_revenue      = (interchange_rev + interest_charged + late_fees
                          + overlimit_fees + annual_fee_paid).round(2)

    # Churn / early payoff
    attrition_flag     = rng.binomial(1, 0.06 + 0.10 * (1 - fico / 850), n)

    return pd.DataFrame({
        "account_id"            : orig["account_id"].values,
        "avg_utilization_12m"   : avg_utilization.round(4),
        "max_utilization_12m"   : max_utilization.round(4),
        "end_utilization_12m"   : end_utilization.round(4),
        "total_purchases_12m"   : total_purchases,
        "num_purchase_txns_12m" : num_purchase_txns,
        "has_cash_advance"      : has_cash_advance.astype(bool),
        "cash_advance_total_12m": cash_advance_total,
        "num_cash_adv_txns_12m" : num_cash_adv_txns,
        "num_missed_pmts_12m"   : num_missed_payments,
        "pct_ontime_pmts_12m"   : pct_ontime_payments.round(4),
        "avg_balance_12m"       : avg_balance.round(2),
        "min_payment_ratio_12m" : min_payment_ratio.round(4),
        "overlimit_months_12m"  : overlimit_months,
        "autopay_enrolled"      : autopay_enroll,
        "late_fees_12m"         : late_fees,
        "interest_charged_12m"  : interest_charged,
        "total_revenue_12m"     : total_revenue,
        "interchange_rev_12m"   : interchange_rev,
        "attrition_flag"        : attrition_flag.astype(bool),
    })


# ─── Step 3 : Default label (12-month forward default) ───────────────────────

def build_default_label(orig: pd.DataFrame, txn: pd.DataFrame,
                        rng: np.random.Generator) -> np.ndarray:
    """
    Calibrated logistic PD using 10 key risk drivers.
    Target: ~8.5% overall default rate (realistic US CC charge-off proxy).
    """
    log.info("  Computing calibrated PD / default labels …")

    fico  = orig["fico_score"].values.astype(float)
    dti   = orig["dti"].values.astype(float)
    util  = txn["avg_utilization_12m"].values.astype(float)
    miss  = txn["num_missed_pmts_12m"].values.astype(float)
    bk    = orig["num_bankruptcy"].values.astype(float)
    derog = orig["num_derog_marks"].values.astype(float)
    cash  = txn["has_cash_advance"].values.astype(float)
    inq   = orig["inq_last_6m"].values.astype(float)
    emp   = (orig["employment_status"].values == "unemployed").astype(float)
    over  = txn["overlimit_months_12m"].values.astype(float)

    # Logistic regression-style linear combination (coefficients calibrated
    # so that mean sigmoid ≈ 0.085)
    logit = (
        -3.80
        - 0.0060 * (fico - 700)        # FICO lift
        + 2.50  * dti                   # DTI penalty
        + 1.80  * util                  # revolving utilisation
        + 0.55  * miss                  # missed payments
        + 1.20  * bk                    # bankruptcy
        + 0.25  * derog                 # derogatory marks
        + 0.80  * cash                  # cash advance behaviour
        + 0.15  * inq                   # recent inquiries
        + 1.10  * emp                   # unemployment shock
        + 0.35  * (over > 0).astype(float)  # at least one overlimit
        + rng.normal(0, 0.40, len(orig))    # idiosyncratic noise
    )
    pd_score    = 1 / (1 + np.exp(-logit))
    default_flag = rng.binomial(1, pd_score, len(orig))

    log.info(
        "  Default rate: %.2f%%  |  mean PD: %.2f%%",
        default_flag.mean() * 100,
        pd_score.mean() * 100,
    )
    return default_flag.astype(np.int8), pd_score.astype(np.float32)


# ─── Step 4 : Cost ledger (origination + servicing + loss costs) ──────────────

def build_cost_ledger(orig: pd.DataFrame, txn: pd.DataFrame,
                      default_flag: np.ndarray,
                      rng: np.random.Generator) -> pd.DataFrame:
    """
    Per-account cost + revenue ledger used for policy development / cut-off analysis.

    Assumed unit economics (2024 US CC industry proxies):
      Acquisition cost      : $45–$180 depending on channel + product
      Annual servicing cost : $28–$55 per active account
      Capital cost          : 10 % capital requirement × expected loss × CoC 12 %
      Loss given default    : 75 % of balance at default (LGD)
      Expected loss         : PD × LGD × EAD
    """
    log.info("  Building cost ledger …")
    n   = len(orig)

    # Acquisition cost by channel
    acq_base = {
        "online": 45, "branch": 120, "phone": 95, "mail": 150, "partner": 180
    }
    acq_cost = np.array([acq_base[c] for c in orig["app_channel"].values], dtype=float)
    acq_cost += rng.uniform(-10, 10, n)

    # Servicing cost per account per year
    servicing_cost = rng.uniform(28, 55, n)

    # EAD  ≈  avg balance + 60% undrawn commitment (behavioural)
    cl          = orig["credit_limit"].values.astype(float)
    avg_bal     = txn["avg_balance_12m"].values.astype(float)
    undrawn_ccf = 0.60  # credit conversion factor
    ead         = avg_bal + undrawn_ccf * (cl - avg_bal)

    # LGD varies by product / collateral — unsecured CC ≈ 65–85%
    lgd_mean = np.where(orig["product"].values == "secured", 0.55, 0.75)
    lgd      = _clip(lgd_mean + rng.normal(0, 0.06, n), 0.30, 0.95)

    # Expected loss
    pd_proxy           = default_flag.astype(float)   # 1-year realised default
    expected_loss      = pd_proxy * lgd * ead

    # Capital cost  (Basel III RWA simplification)
    rwa                = ead * 0.75  # risk weight 75% for retail revolving
    capital_requirement= rwa * 0.10  # Tier-1 ratio
    cost_of_capital    = capital_requirement * 0.12  # 12% hurdle rate
    capital_cost       = cost_of_capital

    # Recovery for defaulted accounts
    recovery_rate      = np.where(default_flag == 1, rng.uniform(0.10, 0.30, n), 0.0)
    recovery_amount    = expected_loss * recovery_rate

    # Total cost
    total_cost = acq_cost + servicing_cost + expected_loss - recovery_amount + capital_cost

    # Net revenue (from txn step)
    revenue        = txn["total_revenue_12m"].values.astype(float)
    net_income     = revenue - total_cost
    risk_adj_return= net_income / _clip(capital_requirement, 1e-6, None)

    return pd.DataFrame({
        "account_id"            : orig["account_id"].values,
        "acquisition_cost"      : acq_cost.round(2),
        "servicing_cost_annual" : servicing_cost.round(2),
        "ead"                   : ead.round(2),
        "lgd"                   : lgd.round(4),
        "expected_loss"         : expected_loss.round(2),
        "recovery_amount"       : recovery_amount.round(2),
        "capital_requirement"   : capital_requirement.round(2),
        "capital_cost_annual"   : capital_cost.round(2),
        "total_cost_annual"     : total_cost.round(2),
        "total_revenue_12m"     : revenue,
        "net_income_12m"        : net_income.round(2),
        "risk_adj_return"       : risk_adj_return.round(4),
    })


# ─── Step 5 : Assemble model-ready feature matrix ─────────────────────────────

def assemble_training_set(
    orig: pd.DataFrame,
    txn: pd.DataFrame,
    default_flag: np.ndarray,
    pd_score: np.ndarray,
) -> pd.DataFrame:
    log.info("  Assembling model-ready feature matrix …")
    df = orig.merge(txn, on="account_id", how="inner")
    df["default_flag"]    = default_flag
    df["true_pd"]         = pd_score
    df["months_on_book"]  = ((pd.Timestamp.now() - df["orig_date"])
                             .dt.days / 30).round(1)

    # Derived / interaction features used by the PD model
    df["fico_dti_interaction"]     = df["fico_score"] * (1 - df["dti"])
    df["util_miss_interaction"]    = df["avg_utilization_12m"] * df["num_missed_pmts_12m"]
    df["log_income"]               = np.log1p(df["annual_income"])
    df["credit_limit_to_income"]   = df["credit_limit"] / df["annual_income"].clip(1)
    df["spend_to_income"]          = df["total_purchases_12m"] / df["annual_income"].clip(1)
    df["balance_to_limit"]         = df["avg_balance_12m"] / df["credit_limit"].clip(1)
    df["inq_per_trade"]            = df["inq_last_6m"] / df["num_open_trades"].clip(1)
    return df


# ─── Main ─────────────────────────────────────────────────────────────────────

def main(n: int = 5_000_000, seed: int = 42, chunk_size: int = 500_000) -> None:
    t0 = time.time()
    log.info("=" * 60)
    log.info("Credit Card PD Synthetic Dataset Generator")
    log.info("Target records : {:,}   |   seed : {}".format(n, seed))
    log.info("=" * 60)

    rng = _rng(seed)

    # ── Generate in chunks to keep RAM manageable ──────────────────────────
    orig_chunks  = []
    txn_chunks   = []
    cost_chunks  = []
    train_chunks = []

    account_offset = 0
    for i, chunk_start in enumerate(range(0, n, chunk_size)):
        chunk_n  = min(chunk_size, n - chunk_start)
        log.info("Chunk %d/%d  (%d records)", i + 1, -(-n // chunk_size), chunk_n)

        chunk_rng = _rng(seed + i * 1_000)

        orig = build_origination(chunk_n, chunk_rng)
        orig["account_id"] += account_offset

        txn  = build_txn_summary(orig, chunk_rng)

        default_flag, pd_score = build_default_label(orig, txn, chunk_rng)

        cost = build_cost_ledger(orig, txn, default_flag, chunk_rng)

        train = assemble_training_set(orig, txn, default_flag, pd_score)

        orig_chunks.append(orig)
        txn_chunks.append(txn)
        cost_chunks.append(cost)
        train_chunks.append(train)

        account_offset += chunk_n

    log.info("Concatenating %d chunks …", len(orig_chunks))
    df_orig  = pd.concat(orig_chunks,  ignore_index=True)
    df_txn   = pd.concat(txn_chunks,   ignore_index=True)
    df_cost  = pd.concat(cost_chunks,  ignore_index=True)
    df_train = pd.concat(train_chunks, ignore_index=True)

    # ── Write parquet ──────────────────────────────────────────────────────
    files = {
        "origination_5m.parquet"   : df_orig,
        "txn_summary_5m.parquet"   : df_txn,
        "cost_assumptions.parquet" : df_cost,
        "pd_training_5m.parquet"   : df_train,
    }
    for fname, df in files.items():
        fpath = OUT_DIR / fname
        df.to_parquet(fpath, index=False, compression="gzip")
        size_mb = fpath.stat().st_size / 1024 ** 2
        log.info("  Wrote %-40s  %8.1f MB  (%d rows)", fname, size_mb, len(df))

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("Done in %.1f s  (%.0f k rows/s)", elapsed, n / elapsed / 1_000)
    log.info("Output dir: %s", OUT_DIR)

    # ── Summary statistics ─────────────────────────────────────────────────
    log.info("\n── Dataset Summary ──────────────────────────────────────────")
    log.info("Records        : {:>12,}".format(len(df_train)))
    log.info("Default rate   : {:>11.2f}%%".format(df_train["default_flag"].mean() * 100))
    log.info("Mean FICO      : {:>12.0f}".format(df_train["fico_score"].mean()))
    log.info("Mean DTI       : {:>12.2%}".format(df_train["dti"].mean()))
    log.info("Mean util (12m): {:>12.2%}".format(df_train["avg_utilization_12m"].mean()))
    log.info("Mean credit lim: ${:>11,.0f}".format(df_train["credit_limit"].mean()))
    log.info("Mean EAD       : ${:>11,.0f}".format(df_cost["ead"].mean()))
    log.info("Mean exp. loss : ${:>11,.2f}".format(df_cost["expected_loss"].mean()))
    log.info("Mean net income: ${:>11,.2f}".format(df_cost["net_income_12m"].mean()))

    risk_grade_dr = (
        df_train.groupby("risk_grade")["default_flag"]
        .agg(["sum", "count", "mean"])
        .rename(columns={"sum": "defaults", "count": "accounts", "mean": "default_rate"})
    )
    log.info("\n── Default Rate by Risk Grade ───────────────────────────────")
    log.info("\n%s", risk_grade_dr.to_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate CC PD synthetic dataset")
    parser.add_argument("--records",    type=int, default=5_000_000)
    parser.add_argument("--seed",       type=int, default=42)
    parser.add_argument("--chunk-size", type=int, default=500_000)
    args = parser.parse_args()
    main(n=args.records, seed=args.seed, chunk_size=args.chunk_size)
