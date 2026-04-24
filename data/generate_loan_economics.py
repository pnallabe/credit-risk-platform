#!/usr/bin/env python3
"""
data/generate_loan_economics.py
================================
Phase 4.2 — Per-loan / per-account itemized economics.

Outputs
-------
  data/raw/financials/loan_origination_economics.parquet   (~291K rows)
  data/raw/financials/loan_monthly_ledger.parquet          (~16M rows, chunked)
  data/raw/financials/cc_account_monthly_economics.parquet (~60M rows, chunked)

Usage
-----
  python data/generate_loan_economics.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fed Funds Rate schedule (step function) — mirrors generate_org_financials.py
# ---------------------------------------------------------------------------

_FED_FUNDS = [
    ("2015-01-01", 0.0025), ("2015-12-16", 0.0050), ("2016-12-14", 0.0075),
    ("2017-03-15", 0.0100), ("2017-06-14", 0.0125), ("2017-12-13", 0.0150),
    ("2018-03-21", 0.0175), ("2018-06-13", 0.0200), ("2018-09-26", 0.0225),
    ("2018-12-19", 0.0250), ("2019-07-31", 0.0225), ("2019-09-18", 0.0200),
    ("2019-10-30", 0.0175), ("2020-03-03", 0.0125), ("2020-03-16", 0.0025),
    ("2022-03-16", 0.0050), ("2022-05-04", 0.0100), ("2022-06-15", 0.0175),
    ("2022-07-27", 0.0250), ("2022-09-21", 0.0325), ("2022-11-02", 0.0400),
    ("2022-12-14", 0.0450), ("2023-02-01", 0.0475), ("2023-03-22", 0.0500),
    ("2023-05-03", 0.0525), ("2024-09-18", 0.0500), ("2024-11-07", 0.0475),
    ("2024-12-18", 0.0450), ("2025-03-19", 0.0425), ("2025-05-07", 0.0400),
]
_FFR_NS = pd.to_datetime([r[0] for r in _FED_FUNDS]).values.astype("datetime64[ns]")
_FFR_RATES = np.array([r[1] for r in _FED_FUNDS])


def _cof_vec(dates_ns: np.ndarray) -> np.ndarray:
    """Vectorised cost of funds: numpy datetime64[ns] array → float array."""
    idx = np.searchsorted(_FFR_NS, dates_ns, side="right") - 1
    return _FFR_RATES[np.clip(idx, 0, len(_FFR_RATES) - 1)] + 0.015


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STATUS_STAGE: dict[str, int] = {
    "current": 1, "paid_off": 1, "modified": 2, "in_forbearance": 2,
    "30dpd": 2, "60dpd": 2, "90dpd": 3, "default": 3,
    "charged_off": 3, "in_foreclosure": 3,
}
_PROV_MONTHLY = {1: 0.005 / 12, 2: 0.03 / 12, 3: 0.15 / 12}
_SVC_MONTHLY  = {"personal_loan": 120.0 / 12, "mortgage": 400.0 / 12}

# Chunk sizes for PyArrow ParquetWriter
_LEDGER_CHUNK = 500_000
_CC_CHUNK_ACCOUNTS = 250_000   # accounts per CC batch → 3M rows/batch


# ---------------------------------------------------------------------------
# 4.2.1  Loan origination economics
# ---------------------------------------------------------------------------

def _pl_orig_fee_rate(fico: np.ndarray) -> np.ndarray:
    """PL origination fee: inversely proportional to FICO (1.5 – 5%)."""
    return np.where(fico >= 750, 0.015,
           np.where(fico >= 700, 0.025,
           np.where(fico >= 650, 0.035, 0.050)))


def generate_origination_economics(
    pl_f: pd.DataFrame,
    mort_f: pd.DataFrame,
    output_path: Path,
) -> None:
    log.info("Generating loan origination economics …")

    # ── Personal loan ─────────────────────────────────────────────────────────
    fico_pl  = pl_f["fico_score_at_origination"].values
    fee_rate = _pl_orig_fee_rate(fico_pl)
    fee_amt  = np.round(pl_f["principal_amount"].values * fee_rate, 2)

    pl_econ = pd.DataFrame({
        "loan_id":                   pl_f["loan_id"].values,
        "product_type":              "personal_loan",
        "origination_date":          pd.to_datetime(pl_f["origination_date"]),
        "principal_amount":          pl_f["principal_amount"].values,
        "fico_score_at_origination": fico_pl,
        "state":                     pl_f["state"].values,
        "channel":                   pl_f["channel"].values,
        "origination_fee_rate":      np.round(fee_rate, 4),
        "origination_fee_amount":    fee_amt,
        "processing_fee":            250.0,
        "doc_prep_fee":              50.0,
        "appraisal_fee":             0.0,
        "title_insurance_fee":       0.0,
        "recording_fee":             0.0,
        "escrow_fee":                0.0,
        "broker_commission":         0.0,
    })
    pl_econ["total_upfront_fees"] = (
        pl_econ["origination_fee_amount"]
        + pl_econ["processing_fee"]
        + pl_econ["doc_prep_fee"]
    )
    pl_econ["net_funded_amount"] = (
        pl_f["principal_amount"].values - pl_econ["total_upfront_fees"].values
    )

    # ── Mortgage ──────────────────────────────────────────────────────────────
    principal = mort_f["principal_amount"].values
    appraisal = np.where(principal < 500_000, 400.0, 600.0)
    title_ins = np.round(principal * 0.005, 2)
    broker    = np.where(
        mort_f["channel"].values == "partner",
        np.round(principal * 0.01, 2),
        0.0,
    )

    mo_econ = pd.DataFrame({
        "loan_id":                   mort_f["loan_id"].values,
        "product_type":              "mortgage",
        "origination_date":          pd.to_datetime(mort_f["origination_date"]),
        "principal_amount":          principal,
        "fico_score_at_origination": mort_f["fico_score_at_origination"].values,
        "state":                     mort_f["state"].values,
        "channel":                   mort_f["channel"].values,
        "origination_fee_rate":      0.0,
        "origination_fee_amount":    0.0,
        "processing_fee":            0.0,
        "doc_prep_fee":              0.0,
        "appraisal_fee":             appraisal,
        "title_insurance_fee":       title_ins,
        "recording_fee":             125.0,
        "escrow_fee":                350.0,
        "broker_commission":         broker,
    })
    mo_econ["total_upfront_fees"] = (
        mo_econ["appraisal_fee"]
        + mo_econ["title_insurance_fee"]
        + mo_econ["recording_fee"]
        + mo_econ["escrow_fee"]
        + mo_econ["broker_commission"]
    )
    mo_econ["net_funded_amount"] = principal - mo_econ["total_upfront_fees"].values

    # ── Combine + write ───────────────────────────────────────────────────────
    combined = pd.concat([pl_econ, mo_econ], ignore_index=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, engine="pyarrow", index=False)
    log.info("Wrote %s  (%d rows)", output_path, len(combined))


# ---------------------------------------------------------------------------
# 4.2.2  Loan monthly ledger
# ---------------------------------------------------------------------------

_LEDGER_OUT_COLS = [
    "loan_id", "product_type", "payment_id", "period_month", "payment_date",
    "principal_portion", "interest_portion", "fees_portion", "remaining_balance",
    "stage", "credit_loss_provision", "cost_of_funds_monthly",
    "net_interest_income", "operating_expense_monthly", "net_income_before_tax",
]


def _enrich_payments(
    pay: pd.DataFrame,
    funded: pd.DataFrame,
    product_type: str,
) -> pd.DataFrame:
    """Join payments with funded data and compute derived P&L columns."""
    stage_lkp = (
        funded[["loan_id", "loan_status"]]
        .assign(stage=funded["loan_status"].str.lower()
                .map(_STATUS_STAGE).fillna(1).astype(int))
        [["loan_id", "stage"]]
    )

    df = pay.merge(stage_lkp, on="loan_id", how="left")
    df["stage"]        = df["stage"].fillna(1).astype(int)
    df["product_type"] = product_type
    df["payment_date"] = pd.to_datetime(df["payment_date"])
    df["period_month"] = df["payment_date"].dt.to_period("M").dt.to_timestamp()

    pay_ns = df["payment_date"].values.astype("datetime64[ns]")
    cof_r  = _cof_vec(pay_ns)
    rb     = df["remaining_balance"].values.astype(float)
    sv     = df["stage"].values

    prov_r = np.where(sv == 1, _PROV_MONTHLY[1],
             np.where(sv == 2, _PROV_MONTHLY[2], _PROV_MONTHLY[3]))

    df["cost_of_funds_monthly"]   = np.round(rb * cof_r / 12, 4)
    df["credit_loss_provision"]   = np.round(rb * prov_r, 4)
    df["net_interest_income"]     = np.round(
        df["interest_portion"].values - df["cost_of_funds_monthly"].values, 4
    )
    df["operating_expense_monthly"] = _SVC_MONTHLY[product_type]
    df["net_income_before_tax"]   = np.round(
        df["net_interest_income"].values
        + df["fees_portion"].values
        - df["credit_loss_provision"].values
        - _SVC_MONTHLY[product_type],
        4,
    )

    return df[_LEDGER_OUT_COLS]


def generate_loan_monthly_ledger(
    pl_f: pd.DataFrame,
    pl_p: pd.DataFrame,
    mort_f: pd.DataFrame,
    mort_p: pd.DataFrame,
    output_path: Path,
) -> None:
    log.info("Generating loan monthly ledger …")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None = None
    total_rows = 0

    for product_type, funded, payments in [
        ("personal_loan", pl_f, pl_p),
        ("mortgage",      mort_f, mort_p),
    ]:
        log.info("  [%s] Enriching %d payment rows …", product_type, len(payments))
        df = _enrich_payments(payments, funded, product_type)
        n  = len(df)
        log.info("  [%s] Writing %d rows in chunks of %d …", product_type, n, _LEDGER_CHUNK)

        for start in range(0, n, _LEDGER_CHUNK):
            chunk = df.iloc[start : start + _LEDGER_CHUNK]
            tbl   = pa.Table.from_pandas(chunk, preserve_index=False)
            if writer is None:
                schema = tbl.schema
                writer = pq.ParquetWriter(output_path, schema)
            writer.write_table(tbl)

        total_rows += n
        del df

    if writer:
        writer.close()

    log.info("Wrote %s  (%d total rows)", output_path, total_rows)


# ---------------------------------------------------------------------------
# 4.2.3  CC account monthly economics
# ---------------------------------------------------------------------------

_CC_OUT_COLS = [
    "account_id", "period_month",
    "interest_income", "late_fee_income", "interchange_income", "annual_fee_income",
    "avg_balance", "utilization_rate",
    "cost_of_funds_monthly", "provision_monthly", "operating_expense_monthly",
    "net_income_before_tax",
]


def generate_cc_monthly_economics(
    cc_orig: pd.DataFrame,
    cc_txn:  pd.DataFrame,
    cc_cost: pd.DataFrame,
    output_path: Path,
) -> None:
    log.info("Generating CC account monthly economics (5M × 12 = 60M rows) …")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    m = (
        cc_orig[["account_id", "orig_date", "annual_fee"]]
        .merge(
            cc_txn[[
                "account_id", "avg_balance_12m", "interest_charged_12m",
                "late_fees_12m", "interchange_rev_12m", "avg_utilization_12m",
            ]],
            on="account_id", how="left",
        )
        .merge(
            cc_cost[["account_id", "expected_loss", "servicing_cost_annual"]],
            on="account_id", how="left",
        )
    )
    m["orig_date"] = pd.to_datetime(m["orig_date"])

    n = len(m)
    writer: pq.ParquetWriter | None = None
    schema: pa.Schema | None = None
    total_rows = 0

    for start in range(0, n, _CC_CHUNK_ACCOUNTS):
        end    = min(start + _CC_CHUNK_ACCOUNTS, n)
        cm     = m.iloc[start:end].reset_index(drop=True)
        nc     = len(cm)

        # ── Generate 12 period_months per account via numpy datetime arithmetic ──
        # orig_date[M] + {1..12} months = period_months
        orig_M    = cm["orig_date"].values.astype("datetime64[M]")
        orig_rep  = np.repeat(orig_M, 12)                                  # nc×12
        mo_off    = np.tile(np.arange(1, 13), nc).astype("timedelta64[M]") # nc×12
        period_ns = (orig_rep + mo_off).astype("datetime64[ns]")

        def _rep(col: str, fill: float = 0.0) -> np.ndarray:
            return np.repeat(cm[col].fillna(fill).values, 12)

        int_mo   = _rep("interest_charged_12m") / 12
        late_mo  = _rep("late_fees_12m")         / 12
        ic_mo    = _rep("interchange_rev_12m")    / 12
        afee_mo  = _rep("annual_fee")             / 12
        avg_bal  = _rep("avg_balance_12m")
        util     = _rep("avg_utilization_12m")
        prov_mo  = _rep("expected_loss")          / 12
        svc_mo   = _rep("servicing_cost_annual")  / 12

        cof_r    = _cof_vec(period_ns)
        cof_mo   = avg_bal * cof_r / 12
        net_inc  = int_mo + late_mo + ic_mo + afee_mo - cof_mo - prov_mo - svc_mo

        chunk_df = pd.DataFrame({
            "account_id":               np.repeat(cm["account_id"].values, 12),
            "period_month":             period_ns,
            "interest_income":          np.round(int_mo,  4),
            "late_fee_income":          np.round(late_mo, 4),
            "interchange_income":       np.round(ic_mo,   4),
            "annual_fee_income":        np.round(afee_mo, 4),
            "avg_balance":              np.round(avg_bal, 2),
            "utilization_rate":         np.round(util,    4),
            "cost_of_funds_monthly":    np.round(cof_mo,  4),
            "provision_monthly":        np.round(prov_mo, 4),
            "operating_expense_monthly":np.round(svc_mo,  4),
            "net_income_before_tax":    np.round(net_inc, 4),
        })

        tbl = pa.Table.from_pandas(chunk_df, preserve_index=False)
        if writer is None:
            schema = tbl.schema
            writer = pq.ParquetWriter(output_path, schema)
        writer.write_table(tbl)

        total_rows += len(chunk_df)
        if (end % (5 * _CC_CHUNK_ACCOUNTS) == 0) or (end == n):
            log.info("  CC progress: %d/%d accounts written", end, n)

        del chunk_df

    if writer:
        writer.close()

    log.info("Wrote %s  (%d total rows)", output_path, total_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Generate loan & CC monthly economics")
    p.add_argument("--data-dir",   default="data/raw")
    p.add_argument("--output-dir", default="data/raw/financials")
    a = p.parse_args()

    data_dir   = PROJECT_ROOT / a.data_dir
    output_dir = PROJECT_ROOT / a.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Loading funded loans …")
    pl_f  = pd.read_parquet(data_dir / "loans/personal_loans_funded.parquet",  engine="pyarrow")
    mo_f  = pd.read_parquet(data_dir / "loans/mortgages_funded.parquet",       engine="pyarrow")

    log.info("Loading payment histories …")
    pl_p  = pd.read_parquet(data_dir / "loans/personal_loan_payments.parquet", engine="pyarrow")
    mo_p  = pd.read_parquet(data_dir / "loans/mortgage_payments.parquet",      engine="pyarrow")

    log.info("Loading CC data …")
    cc_o  = pd.read_parquet(data_dir / "cc_pd/origination_5m.parquet",         engine="pyarrow")
    cc_t  = pd.read_parquet(data_dir / "cc_pd/txn_summary_5m.parquet",         engine="pyarrow")
    cc_c  = pd.read_parquet(data_dir / "cc_pd/cost_assumptions.parquet",       engine="pyarrow")

    generate_origination_economics(
        pl_f, mo_f,
        output_dir / "loan_origination_economics.parquet",
    )
    generate_loan_monthly_ledger(
        pl_f, pl_p, mo_f, mo_p,
        output_dir / "loan_monthly_ledger.parquet",
    )
    generate_cc_monthly_economics(
        cc_o, cc_t, cc_c,
        output_dir / "cc_account_monthly_economics.parquet",
    )

    log.info("Phase 4.2 complete.")


if __name__ == "__main__":
    main()
