#!/usr/bin/env python3
"""
data/generate_org_financials.py
================================
Generate quarterly org-level P&L (income statement) + balance sheet for
48 quarters: Q1 2015 to Q4 2026.

Outputs
-------
  data/raw/financials/org_income_statement.parquet
  data/raw/financials/org_balance_sheet.parquet
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

FED_FUNDS_SCHEDULE = [
    ("2015-01-01",0.0025),("2015-12-16",0.0050),("2016-12-14",0.0075),
    ("2017-03-15",0.0100),("2017-06-14",0.0125),("2017-12-13",0.0150),
    ("2018-03-21",0.0175),("2018-06-13",0.0200),("2018-09-26",0.0225),
    ("2018-12-19",0.0250),("2019-07-31",0.0225),("2019-09-18",0.0200),
    ("2019-10-30",0.0175),("2020-03-03",0.0125),("2020-03-16",0.0025),
    ("2022-03-16",0.0050),("2022-05-04",0.0100),("2022-06-15",0.0175),
    ("2022-07-27",0.0250),("2022-09-21",0.0325),("2022-11-02",0.0400),
    ("2022-12-14",0.0450),("2023-02-01",0.0475),("2023-03-22",0.0500),
    ("2023-05-03",0.0525),("2024-09-18",0.0500),("2024-11-07",0.0475),
    ("2024-12-18",0.0450),("2025-03-19",0.0425),("2025-05-07",0.0400),
]
_FFR_DATES = pd.to_datetime([r[0] for r in FED_FUNDS_SCHEDULE])
_FFR_RATES = np.array([r[1] for r in FED_FUNDS_SCHEDULE])

def get_cost_of_funds(date) -> float:
    ts = pd.Timestamp(date)
    idx = int(np.searchsorted(_FFR_DATES.values.astype("datetime64[ns]"),
                               np.datetime64(ts), side="right")) - 1
    return float(_FFR_RATES[max(0, min(idx, len(_FFR_RATES)-1))]) + 0.015

_STATUS_STAGE = {"current":1,"paid_off":1,"modified":2,"in_forbearance":2,
                 "30dpd":2,"60dpd":2,"90dpd":3,"default":3,"charged_off":3,"in_foreclosure":3}
_ACL_RATE   = {1:0.015, 2:0.05, 3:0.15}
_PROV_RATE  = {1:0.005, 2:0.03,  3:0.15}
_SVC_COST   = {"personal_loan":120.0, "mortgage":400.0, "credit_card":60.0}

def _qlabel(qe): return f"{qe.year}-Q{qe.quarter}"
def _quarter_ends(): return pd.date_range("2015-03-31","2026-12-31",freq="QE")

def _build_loan_quarterly(funded, payments, product, period_ends):
    funded = funded.copy()
    funded["origination_date"] = pd.to_datetime(funded["origination_date"])
    funded["stage"] = funded["loan_status"].str.lower().map(_STATUS_STAGE).fillna(1).astype(int)
    payments = payments.copy()
    payments["payment_date"] = pd.to_datetime(payments["payment_date"])

    bins = pd.DatetimeIndex(["2014-12-31"]).append(period_ends)
    pay_cat = pd.cut(payments["payment_date"], bins=bins, labels=period_ends, right=True)
    payments["qe"] = pay_cat.astype("datetime64[ns]")
    pay_agg = (payments.dropna(subset=["qe"])
               .groupby("qe",observed=True)
               .agg(interest_income=("interest_portion","sum"),
                    fee_income=("fees_portion","sum"))
               .reindex(period_ends, fill_value=0.0))

    orig_ns   = funded["origination_date"].values.astype("datetime64[ns]")
    status_v  = funded["loan_status"].values
    bal_v     = funded["current_balance"].values.astype(float)
    stage_v   = funded["stage"].values.astype(int)
    q_ns      = period_ends.values.astype("datetime64[ns]")

    inc_rows, bal_rows = [], []
    for qi, qe in enumerate(period_ends):
        label = _qlabel(qe); yr, q = qe.year, qe.quarter
        mask  = orig_ns <= q_ns[qi]
        omask = mask & (status_v != "paid_off")
        n_act = int(omask.sum())
        gross = float(bal_v[omask].sum())

        ii = float(pay_agg.loc[qe,"interest_income"])
        fi = float(pay_agg.loc[qe,"fee_income"])
        cof_r = get_cost_of_funds(qe)
        cof   = gross * cof_r * 0.25
        nii   = ii - cof

        sv = stage_v[omask]; bv = bal_v[omask]
        pr_arr = np.where(sv==1,_PROV_RATE[1],np.where(sv==2,_PROV_RATE[2],_PROV_RATE[3]))
        base_prov = float((bv * pr_arr / 4).sum())
        mult = 2.5 if (yr==2020 and q==2) or (yr==2022 and q==1) else 1.0
        prov = base_prov * mult

        b3 = float(bv[sv==3].sum())
        cor = (b3*0.15/4) / max(gross,1e-6)
        op  = n_act * _SVC_COST[product] / 4
        nim = (nii / max(gross,1e-6)) * 4

        inc_rows.append({"period_end_date":qe,"quarter":label,"product_type":product,
            "interest_income":round(ii,2),"fee_income":round(fi,2),
            "cost_of_funds":round(cof,2),"net_interest_income":round(nii,2),
            "provision_for_credit_losses":round(prov,2),"net_credit_income":round(nii-prov,2),
            "operating_expenses":round(op,2),"net_income_before_tax":round(nii-prov-op,2),
            "net_interest_margin":round(nim,6),"cost_of_funds_rate":round(cof_r,6),
            "charge_off_rate":round(cor,6),"recovery_rate":0.0,"net_charge_off_rate":round(cor,6),
            "avg_outstanding":round(gross,2)})

        ar_arr = np.where(sv==1,_ACL_RATE[1],np.where(sv==2,_ACL_RATE[2],_ACL_RATE[3]))
        acl = float((bv*ar_arr).sum())
        n30=int((status_v[omask]=="30dpd").sum()); n60=int((status_v[omask]=="60dpd").sum())
        n90=int((status_v[omask]=="90dpd").sum()); nt=max(n_act,1)
        bal_rows.append({"period_end_date":qe,"quarter":label,"product_type":product,
            "gross_loan_portfolio_outstanding":round(gross,2),"allowance_for_credit_losses":round(acl,2),
            "net_loan_portfolio":round(gross-acl,2),"number_of_active_accounts":n_act,
            "average_loan_balance":round(gross/nt,2),"portfolio_yield":round((ii*4)/max(gross,1e-6),6),
            "30dpd_rate":round(n30/nt,6),"60dpd_rate":round(n60/nt,6),
            "90dpd_rate":round(n90/nt,6),"delinquency_rate":round((n30+n60+n90)/nt,6)})

    inc_df = pd.DataFrame(inc_rows)
    inc_df["recovery_rate"] = inc_df["charge_off_rate"].shift(2).fillna(0.0)*0.30
    inc_df["net_charge_off_rate"] = (inc_df["charge_off_rate"]-inc_df["recovery_rate"]).clip(lower=0)
    return inc_df, pd.DataFrame(bal_rows)

def _build_cc_quarterly(orig, txn, cost, period_ends):
    m = (orig[["account_id","orig_date","credit_limit","apr","annual_fee"]]
         .merge(txn[["account_id","avg_balance_12m","interest_charged_12m",
                      "late_fees_12m","interchange_rev_12m"]], on="account_id", how="left")
         .merge(cost[["account_id","expected_loss"]], on="account_id", how="left"))
    m["orig_date"] = pd.to_datetime(m["orig_date"])
    od  = m["orig_date"].values.astype("datetime64[ns]")
    ab  = m["avg_balance_12m"].fillna(0).values.astype(float)
    ic  = m["interest_charged_12m"].fillna(0).values.astype(float)
    lf  = m["late_fees_12m"].fillna(0).values.astype(float)
    af  = m["annual_fee"].fillna(0).values.astype(float)
    irv = m["interchange_rev_12m"].fillna(0).values.astype(float)
    el  = m["expected_loss"].fillna(0).values.astype(float)
    q_ns = period_ends.values.astype("datetime64[ns]")

    inc_rows, bal_rows = [], []
    for qi, qe in enumerate(period_ends):
        label = _qlabel(qe); yr, q = qe.year, qe.quarter
        mask  = od <= q_ns[qi]
        n     = int(mask.sum())
        cof_r = get_cost_of_funds(qe)
        if n==0:
            inc_rows.append({"period_end_date":qe,"quarter":label,"product_type":"credit_card",
                "interest_income":0,"fee_income":0,"cost_of_funds":0,"net_interest_income":0,
                "provision_for_credit_losses":0,"net_credit_income":0,"operating_expenses":0,
                "net_income_before_tax":0,"net_interest_margin":0,"cost_of_funds_rate":cof_r,
                "charge_off_rate":0,"recovery_rate":0,"net_charge_off_rate":0,"avg_outstanding":0})
            bal_rows.append({"period_end_date":qe,"quarter":label,"product_type":"credit_card",
                "gross_loan_portfolio_outstanding":0,"allowance_for_credit_losses":0,
                "net_loan_portfolio":0,"number_of_active_accounts":0,"average_loan_balance":0,
                "portfolio_yield":0,"30dpd_rate":0,"60dpd_rate":0,"90dpd_rate":0,"delinquency_rate":0})
            continue
        avg_bal = float(ab[mask].mean())*n
        ii = float(ic[mask].sum())/4
        fi = (float(lf[mask].sum())/4 + float(af[mask].sum())/4)
        iq = float(irv[mask].sum())/4
        cof = avg_bal*cof_r*0.25; nii = ii-cof
        bp = float(el[mask].sum())/4
        mult = 2.5 if (yr==2020 and q==2) or (yr==2022 and q==1) else 1.0
        prov = bp*mult
        op = n*_SVC_COST["credit_card"]/4
        cor = float(el[mask].mean())/max(avg_bal/max(n,1),1e-6)*0.25
        nim = (nii/max(avg_bal,1e-6))*4
        inc_rows.append({"period_end_date":qe,"quarter":label,"product_type":"credit_card",
            "interest_income":round(ii,2),"fee_income":round(fi+iq,2),
            "cost_of_funds":round(cof,2),"net_interest_income":round(nii,2),
            "provision_for_credit_losses":round(prov,2),"net_credit_income":round(nii-prov,2),
            "operating_expenses":round(op,2),"net_income_before_tax":round(nii-prov-op,2),
            "net_interest_margin":round(nim,6),"cost_of_funds_rate":round(cof_r,6),
            "charge_off_rate":round(cor,6),"recovery_rate":0.0,"net_charge_off_rate":round(cor,6),
            "avg_outstanding":round(avg_bal,2)})
        acl = float(el[mask].sum())*0.015
        bal_rows.append({"period_end_date":qe,"quarter":label,"product_type":"credit_card",
            "gross_loan_portfolio_outstanding":round(avg_bal,2),"allowance_for_credit_losses":round(acl,2),
            "net_loan_portfolio":round(avg_bal-acl,2),"number_of_active_accounts":n,
            "average_loan_balance":round(avg_bal/max(n,1),2),"portfolio_yield":round((ii*4)/max(avg_bal,1e-6),6),
            "30dpd_rate":0.040,"60dpd_rate":0.020,"90dpd_rate":0.015,"delinquency_rate":0.075})

    inc_df = pd.DataFrame(inc_rows)
    inc_df["recovery_rate"] = inc_df["charge_off_rate"].shift(2).fillna(0.0)*0.30
    inc_df["net_charge_off_rate"] = (inc_df["charge_off_rate"]-inc_df["recovery_rate"]).clip(lower=0)
    return inc_df, pd.DataFrame(bal_rows)

def _add_totals(df, vcols):
    tots = (df[df["product_type"]!="total"].groupby("period_end_date")[vcols]
            .sum().reset_index())
    tots["quarter"]      = tots["period_end_date"].apply(_qlabel)
    tots["product_type"] = "total"
    return pd.concat([df,tots],ignore_index=True).sort_values(["period_end_date","product_type"])

def _assert_provision_spikes(inc):
    t = inc[inc["product_type"]=="total"].set_index("quarter")
    if "2019-Q4" not in t.index: return
    base = float(t.loc["2019-Q4","provision_for_credit_losses"])
    if base <= 0: return
    for q in ["2020-Q2","2022-Q1"]:
        if q not in t.index: continue
        v = float(t.loc[q,"provision_for_credit_losses"])
        tag = "PASS" if v >= 2*base else "WARN"
        log.info("PRD §8 check 5 %s: %s provision $%.0f (baseline $%.0f)", tag, q, v, base)

def build_financials(data_dir: Path, output_dir: Path):
    period_ends = _quarter_ends()
    log.info("Quarters: %d  (%s → %s)", len(period_ends), period_ends[0].date(), period_ends[-1].date())

    log.info("Loading data …")
    pl_f  = pd.read_parquet(data_dir/"loans/personal_loans_funded.parquet",   engine="pyarrow")
    mo_f  = pd.read_parquet(data_dir/"loans/mortgages_funded.parquet",        engine="pyarrow")
    pl_p  = pd.read_parquet(data_dir/"loans/personal_loan_payments.parquet",  engine="pyarrow")
    mo_p  = pd.read_parquet(data_dir/"loans/mortgage_payments.parquet",       engine="pyarrow")
    cc_o  = pd.read_parquet(data_dir/"cc_pd/origination_5m.parquet",          engine="pyarrow")
    cc_t  = pd.read_parquet(data_dir/"cc_pd/txn_summary_5m.parquet",          engine="pyarrow")
    cc_c  = pd.read_parquet(data_dir/"cc_pd/cost_assumptions.parquet",        engine="pyarrow")

    log.info("Personal loan quarterly P&L …")
    pl_inc, pl_bal = _build_loan_quarterly(pl_f, pl_p, "personal_loan", period_ends)
    log.info("Mortgage quarterly P&L …")
    mo_inc, mo_bal = _build_loan_quarterly(mo_f, mo_p, "mortgage", period_ends)
    log.info("Credit card quarterly P&L …")
    cc_inc, cc_bal = _build_cc_quarterly(cc_o, cc_t, cc_c, period_ends)

    INC_V = ["interest_income","fee_income","cost_of_funds","net_interest_income",
             "provision_for_credit_losses","net_credit_income","operating_expenses",
             "net_income_before_tax","avg_outstanding"]
    BAL_V = ["gross_loan_portfolio_outstanding","allowance_for_credit_losses",
             "net_loan_portfolio","number_of_active_accounts"]

    inc = _add_totals(pd.concat([pl_inc,mo_inc,cc_inc],ignore_index=True), INC_V)
    bal = _add_totals(pd.concat([pl_bal,mo_bal,cc_bal],ignore_index=True), BAL_V)

    tm = inc["product_type"]=="total"
    inc.loc[tm,"cost_of_funds_rate"]   = inc.loc[tm,"period_end_date"].apply(get_cost_of_funds)
    inc.loc[tm,"net_interest_margin"]  = (inc.loc[tm,"net_interest_income"]
                                           /inc.loc[tm,"avg_outstanding"].clip(lower=1e-6)*4)
    inc.loc[tm,"recovery_rate"]        = inc.loc[tm,"charge_off_rate"].shift(2).fillna(0)*0.30
    inc.loc[tm,"net_charge_off_rate"]  = (inc.loc[tm,"charge_off_rate"]-inc.loc[tm,"recovery_rate"]).clip(lower=0)

    tbm = bal["product_type"]=="total"
    bal.loc[tbm,"average_loan_balance"] = (bal.loc[tbm,"gross_loan_portfolio_outstanding"]
                                            /bal.loc[tbm,"number_of_active_accounts"].clip(lower=1))

    _assert_provision_spikes(inc)

    output_dir.mkdir(parents=True, exist_ok=True)
    ip = output_dir/"org_income_statement.parquet"
    bp = output_dir/"org_balance_sheet.parquet"
    inc.to_parquet(ip, engine="pyarrow", index=False)
    bal.to_parquet(bp, engine="pyarrow", index=False)
    log.info("Wrote %s  (%d rows)", ip, len(inc))
    log.info("Wrote %s  (%d rows)", bp, len(bal))

    print("\n" + "="*60)
    print("ORG FINANCIALS SUMMARY")
    print("="*60)
    ti = inc[inc["product_type"]=="total"].copy()
    ti["year"] = ti["period_end_date"].dt.year
    print(f"Income Statement: {len(inc)} rows | Balance Sheet: {len(bal)} rows")
    print("\nAnnual Net Income Before Tax (total):")
    for yr, grp in ti.groupby("year"):
        print(f"  {yr}: ${grp['net_income_before_tax'].sum()/1e6:,.1f}M")
    print("\nProvision check:")
    for q in ["2019-Q4","2020-Q2","2022-Q1"]:
        row = ti[ti["quarter"]==q]
        if not row.empty:
            print(f"  {q}: ${row['provision_for_credit_losses'].iloc[0]/1e6:,.2f}M")
    print("="*60)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir",   default="data/raw")
    p.add_argument("--output-dir", default="data/raw/financials")
    a = p.parse_args()
    build_financials(PROJECT_ROOT/a.data_dir, PROJECT_ROOT/a.output_dir)

if __name__ == "__main__":
    main()
