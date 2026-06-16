"""
scripts/validate_bigquery.py
=============================
Validates that all generated data was uploaded correctly to BigQuery.
Checks: row counts, schema completeness, data quality constraints, date ranges.

Usage:
    python scripts/validate_bigquery.py
    python scripts/validate_bigquery.py --project ai-risk-workflow --dataset credit_risk
"""
from __future__ import annotations
import argparse
import sys
import warnings
warnings.filterwarnings("ignore")

try:
    from google.cloud import bigquery
except ImportError:
    print("ERROR: google-cloud-bigquery not installed.")
    sys.exit(1)

# ── Expected row counts (from generation run) ─────────────────────────────────
EXPECTED_ROWS = {
    "cc_origination_with_decisions":       5_000_000,
    "personal_loan_applications":            750_000,
    "personal_loans_funded":                 202_112,
    "personal_loan_credit_bureau_pulls":     400_156,
    "personal_loan_modifications":             6_118,
    "mortgage_applications":                 200_000,
    "mortgages_funded":                       89_217,
}


def run_query(client, sql: str) -> list[dict]:
    return [dict(row) for row in client.query(sql).result()]


def validate(project: str, dataset: str) -> bool:
    client = bigquery.Client(project=project)
    D = f"`{project}.{dataset}`"
    all_passed = True

    def fail(msg):
        nonlocal all_passed
        all_passed = False
        print(f"    ✗  {msg}")

    def ok(msg):
        print(f"    ✓  {msg}")

    # ── 1. Row counts ─────────────────────────────────────────────────────────
    print("=" * 72)
    print(f"BIGQUERY VALIDATION  —  {project}.{dataset}")
    print("=" * 72)
    print(f"\n{'Table':<47} {'Expected':>10} {'Actual':>10}  Status")
    print("-" * 80)

    for table, expected in EXPECTED_ROWS.items():
        rows = run_query(client, f"SELECT COUNT(*) AS n FROM {D}.`{table}`")
        actual = rows[0]["n"]
        status = "✓ MATCH" if actual == expected else f"✗ DIFF {actual - expected:+,}"
        if actual != expected:
            all_passed = False
        print(f"  {table:<45} {expected:>10,} {actual:>10,}  {status}")

    # ── 2. CC origination ─────────────────────────────────────────────────────
    print("\n\n[1] cc_origination_with_decisions")
    table = f"{D}.`cc_origination_with_decisions`"

    r = run_query(client,
        f"SELECT COUNT(DISTINCT decision_id) AS uniq, COUNT(*) AS total FROM {table}")[0]
    if r["uniq"] == r["total"]:
        ok(f"decision_id unique: {r['uniq']:,}")
    else:
        fail(f"UUID collisions: {r['total'] - r['uniq']:,}")

    r = run_query(client,
        f"SELECT COUNTIF(policy_version_id IS NULL) AS null_pv FROM {table}")[0]
    if r["null_pv"] == 0:
        ok("policy_version_id 100% populated")
    else:
        fail(f"policy_version_id nulls: {r['null_pv']:,}")

    r = run_query(client,
        f"SELECT COUNTIF(decision_outcome NOT IN ('APPROVE','REJECT','REFER')) AS bad FROM {table}")[0]
    if r["bad"] == 0:
        ok("decision_outcome values valid")
    else:
        fail(f"invalid decision_outcome rows: {r['bad']:,}")

    r = run_query(client,
        f"SELECT COUNTIF(fico_score < 300 OR fico_score > 850) AS bad FROM {table}")[0]
    if r["bad"] == 0:
        ok("fico_score in [300, 850]")
    else:
        fail(f"fico_score out of range: {r['bad']:,} rows")

    r = run_query(client,
        f"SELECT COUNTIF(decision_outcome='APPROVE') AS a, "
        f"COUNTIF(decision_outcome='REJECT') AS r, "
        f"COUNTIF(decision_outcome='REFER') AS rf FROM {table}")[0]
    total = r["a"] + r["r"] + r["rf"]
    ok(f"Outcomes — APPROVE:{r['a']:,} ({r['a']/total*100:.1f}%)  "
       f"REJECT:{r['r']:,} ({r['r']/total*100:.1f}%)  "
       f"REFER:{r['rf']:,} ({r['rf']/total*100:.1f}%)")

    r = run_query(client,
        f"SELECT MIN(orig_date) AS min_d, MAX(orig_date) AS max_d FROM {table}")[0]
    ok(f"orig_date range: {r['min_d']} → {r['max_d']}")

    # ── 3. Personal loan applications ─────────────────────────────────────────
    print("\n[2] personal_loan_applications")
    table = f"{D}.`personal_loan_applications`"

    r = run_query(client,
        f"SELECT COUNTIF(fico_score < 300 OR fico_score > 850) AS bad_fico, "
        f"COUNTIF(dti <= 0 OR dti > 1) AS bad_dti, "
        f"COUNTIF(decision_outcome IS NULL) AS null_dec, "
        f"COUNTIF(annual_income <= 0) AS bad_income FROM {table}")[0]
    if r["bad_fico"] == 0: ok("fico_score in [300, 850]")
    else: fail(f"bad fico_score: {r['bad_fico']:,}")
    if r["bad_dti"] == 0: ok("dti in (0, 1]")
    else: fail(f"bad dti: {r['bad_dti']:,}")
    if r["null_dec"] == 0: ok("decision_outcome 100% populated")
    else: fail(f"null decision_outcome: {r['null_dec']:,}")
    if r["bad_income"] == 0: ok("annual_income > 0")
    else: fail(f"non-positive annual_income: {r['bad_income']:,}")

    r = run_query(client,
        f"SELECT decision_outcome, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC")[0]
    rows2 = run_query(client,
        f"SELECT decision_outcome, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC")
    ok("Decision outcomes: " + "  ".join(f"{x['decision_outcome']}:{x['n']:,}" for x in rows2))

    r = run_query(client,
        f"SELECT MIN(applied_at) AS min_d, MAX(applied_at) AS max_d FROM {table}")[0]
    ok(f"applied_at range: {r['min_d']} → {r['max_d']}")

    # ── 4. Personal loans funded ──────────────────────────────────────────────
    print("\n[3] personal_loans_funded")
    table = f"{D}.`personal_loans_funded`"

    r = run_query(client,
        f"SELECT COUNTIF(current_balance < 0) AS neg_bal, "
        f"COUNTIF(interest_rate <= 0) AS zero_rate, "
        f"COUNTIF(monthly_payment <= 0) AS zero_pmt, "
        f"COUNT(DISTINCT loan_status) AS n_statuses FROM {table}")[0]
    if r["neg_bal"] == 0: ok("current_balance ≥ 0")
    else: fail(f"negative current_balance: {r['neg_bal']:,}")
    if r["zero_rate"] == 0: ok("interest_rate > 0")
    else: fail(f"zero/negative interest_rate: {r['zero_rate']:,}")
    if r["zero_pmt"] == 0: ok("monthly_payment > 0")
    else: fail(f"zero monthly_payment: {r['zero_pmt']:,}")
    ok(f"distinct loan_status values: {r['n_statuses']}")

    r = run_query(client,
        f"SELECT loan_status, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC")
    ok("Loan statuses: " + "  ".join(f"{x['loan_status']}:{x['n']:,}" for x in r))

    r = run_query(client,
        f"SELECT COUNTIF(origination_date > maturity_date) AS inv FROM {table}")[0]
    if r["inv"] == 0: ok("origination_date < maturity_date for all loans")
    else: fail(f"origination_date >= maturity_date: {r['inv']:,} rows")

    # ── 5. Mortgage applications ──────────────────────────────────────────────
    print("\n[4] mortgage_applications")
    table = f"{D}.`mortgage_applications`"

    r = run_query(client,
        f"SELECT COUNTIF(ltv_at_origination <= 0 OR ltv_at_origination > 1.1) AS bad_ltv, "
        f"COUNTIF(appraised_value <= 0) AS bad_av, "
        f"COUNTIF(loan_amount <= 0) AS bad_la, "
        f"COUNTIF(decision_outcome IS NULL) AS null_dec FROM {table}")[0]
    if r["bad_ltv"] == 0: ok("ltv_at_origination in (0, 1.1]")
    else: fail(f"bad ltv: {r['bad_ltv']:,}")
    if r["bad_av"] == 0: ok("appraised_value > 0")
    else: fail(f"bad appraised_value: {r['bad_av']:,}")
    if r["bad_la"] == 0: ok("loan_amount > 0")
    else: fail(f"bad loan_amount: {r['bad_la']:,}")
    if r["null_dec"] == 0: ok("decision_outcome 100% populated")
    else: fail(f"null decision_outcome: {r['null_dec']:,}")

    rows3 = run_query(client,
        f"SELECT decision_outcome, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC")
    ok("Decisions: " + "  ".join(f"{x['decision_outcome']}:{x['n']:,}" for x in rows3))

    r = run_query(client,
        f"SELECT MIN(applied_at) AS min_d, MAX(applied_at) AS max_d FROM {table}")[0]
    ok(f"applied_at range: {r['min_d']} → {r['max_d']}")

    # ── 6. Mortgages funded — QM constraint ───────────────────────────────────
    print("\n[5] mortgages_funded")
    table = f"{D}.`mortgages_funded`"

    r = run_query(client,
        f"SELECT "
        f"COUNTIF(current_balance < 0) AS neg_bal, "
        f"COUNTIF(NOT is_qm AND dti_at_origination <= 0.43) AS qm_violations, "
        f"COUNTIF(pmi_required AND ltv_at_origination <= 0.80) AS pmi_low_ltv, "
        f"AVG(ltv_at_origination) AS avg_ltv "
        f"FROM {table}")[0]
    if r["neg_bal"] == 0: ok("current_balance ≥ 0")
    else: fail(f"negative balance: {r['neg_bal']:,}")

    # QM constraint: ≥95% of loans with DTI ≤ 0.43 must be QM
    r2 = run_query(client,
        f"SELECT "
        f"COUNTIF(dti_at_origination <= 0.43) AS low_dti_count, "
        f"COUNTIF(is_qm AND dti_at_origination <= 0.43) AS qm_low_dti "
        f"FROM {table}")[0]
    if r2["low_dti_count"] > 0:
        qm_rate = r2["qm_low_dti"] / r2["low_dti_count"] * 100
        if qm_rate >= 95.0:
            ok(f"is_qm rate for DTI≤0.43: {qm_rate:.1f}% (target ≥95%)")
        else:
            fail(f"is_qm rate for DTI≤0.43: {qm_rate:.1f}% (target ≥95%)")

    ok(f"avg LTV at origination: {r['avg_ltv']:.3f}")

    rows4 = run_query(client,
        f"SELECT loan_status, COUNT(*) AS n FROM {table} GROUP BY 1 ORDER BY 2 DESC")
    ok("Loan statuses: " + "  ".join(f"{x['loan_status']}:{x['n']:,}" for x in rows4))

    # ── 7. Bureau pulls & modifications ──────────────────────────────────────
    print("\n[6] personal_loan_credit_bureau_pulls")
    table = f"{D}.`personal_loan_credit_bureau_pulls`"
    r = run_query(client,
        f"SELECT COUNTIF(score_returned < 300 OR score_returned > 850) AS bad_score, "
        f"COUNT(DISTINCT bureau) AS n_bureaus FROM {table}")[0]
    if r["bad_score"] == 0: ok("score_returned in [300, 850]")
    else: fail(f"out-of-range scores: {r['bad_score']:,}")
    ok(f"bureaus covered: {r['n_bureaus']}")

    print("\n[7] personal_loan_modifications")
    table = f"{D}.`personal_loan_modifications`"
    r = run_query(client,
        f"SELECT COUNTIF(modified_rate <= 0) AS bad_rate, "
        f"COUNT(DISTINCT modification_type) AS n_types FROM {table}")[0]
    if r["bad_rate"] == 0: ok("modified_rate > 0")
    else: fail(f"non-positive modified_rate: {r['bad_rate']:,}")
    ok(f"modification types: {r['n_types']}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("VALIDATION SUMMARY")
    if all_passed:
        print("  ALL CHECKS PASSED ✓")
    else:
        print("  ONE OR MORE CHECKS FAILED — see ✗ above")
    print("=" * 72)
    return all_passed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="ai-risk-workflow")
    parser.add_argument("--dataset", default="credit_risk")
    args = parser.parse_args()
    ok = validate(args.project, args.dataset)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
