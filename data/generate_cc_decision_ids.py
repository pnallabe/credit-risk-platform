"""
data/generate_cc_decision_ids.py
==================================
Augment origination_5m.parquet with deterministic decision metadata.

Reads:
    data/raw/cc_pd/origination_5m.parquet   (5 M rows, 23 columns)

Adds 5 columns:
    decision_id          — deterministic UUID5 (NAMESPACE_OID, account_id:date)
    policy_version_id    — int, from PolicyVersionStore.get_as_of(month_start)
    policy_version_tag   — str, version tag from that policy snapshot
    decision_outcome     — APPROVE | REJECT | REFER
    decision_reason_codes — pipe-separated FCRA codes (or "")

Writes:
    data/raw/cc_pd/origination_5m_with_decisions.parquet

Usage:
    python data/generate_cc_decision_ids.py
    python data/generate_cc_decision_ids.py \\
        --input data/raw/cc_pd/origination_5m.parquet \\
        --output data/raw/cc_pd/origination_5m_with_decisions.parquet \\
        --db-path policy_versions.db
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.policy_version_store import PolicyVersionStore, PolicyVersionNotFoundError


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_uuid5_array(account_ids: np.ndarray, orig_dates: pd.Series) -> np.ndarray:
    """Vectorised UUID5 generation using deterministic keys."""
    date_strs = pd.to_datetime(orig_dates).dt.date.astype(str).values
    return np.array([
        str(uuid.uuid5(uuid.NAMESPACE_OID, f"{aid}:{ds}"))
        for aid, ds in zip(account_ids, date_strs)
    ])


def _build_policy_cache(db_path: str, orig_dates: pd.Series) -> dict:
    """
    Return {year_month_str -> (pv_id, pv_tag, cc_params)} for each unique month.
    year_month_str format: "2021-03"
    """
    try:
        store = PolicyVersionStore(db_path=Path(db_path))
    except Exception as exc:
        print(f"  [WARN] Could not open PolicyVersionStore ({exc}); policy columns will be null.")
        return {}

    months = pd.to_datetime(orig_dates).dt.to_period("M").unique()
    cache: dict = {}
    for period in months:
        dt = datetime(period.year, period.month, 1, tzinfo=timezone.utc)
        try:
            pv = store.get_as_of(dt)
            # Extract CC params (may be keyed as "CREDIT_CARD" or top-level)
            params = pv.parameters
            cc_params = params.get("CREDIT_CARD", params)
            cache[str(period)] = (pv.id, pv.version_tag, cc_params)
        except PolicyVersionNotFoundError:
            cache[str(period)] = (None, None, {})

    covered = sum(1 for v in cache.values() if v[0] is not None)
    print(f"  Policy cache: {covered}/{len(cache)} months have a version.")
    return cache


def _derive_outcome(
    fico: np.ndarray,
    dti: np.ndarray,
    pd_score_col: np.ndarray | None,
    month_periods: np.ndarray,
    policy_cache: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Derive decision_outcome and decision_reason_codes for each row.

    Rules (per epoch policy):
        REJECT  if fico < cc_params["fico_floor"]         → AA01
        REJECT  if dti  > cc_params["max_dti"]            → AA04
        REFER   if fico is within 20pts of floor           → AA90
        APPROVE otherwise
    """
    n = len(fico)
    outcomes = np.full(n, "APPROVE", dtype=object)
    reason_codes = np.full(n, "", dtype=object)

    # Group by unique month to apply epoch-specific thresholds
    unique_months = np.unique(month_periods)
    for m in unique_months:
        mask = month_periods == m
        entry = policy_cache.get(str(m), (None, None, {}))
        cc_params = entry[2] if entry else {}

        fico_floor = float(cc_params.get("fico_floor", 620))
        max_dti = float(cc_params.get("max_dti", 0.45))
        near_prime_floor = fico_floor + 20

        f = fico[mask]
        d = dti[mask]

        # Reject: FICO too low
        reject_fico = f < fico_floor
        # Reject: DTI too high
        reject_dti = d > max_dti
        # Borderline REFER
        refer_fico = (f >= fico_floor) & (f < near_prime_floor) & ~reject_dti

        outcomes_m = np.where(reject_fico, "REJECT",
                      np.where(reject_dti, "REJECT",
                       np.where(refer_fico, "REFER", "APPROVE")))
        codes_m = np.where(reject_fico, "AA01",
                   np.where(reject_dti, "AA04",
                    np.where(refer_fico, "AA90", "")))

        # Compound reject: both FICO + DTI bad
        both_bad = reject_fico & reject_dti
        codes_m = np.where(both_bad, "AA01|AA04", codes_m)

        outcomes[mask] = outcomes_m
        reason_codes[mask] = codes_m

    return outcomes, reason_codes


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Add decision metadata to CC origination dataset")
    parser.add_argument(
        "--input", default="data/raw/cc_pd/origination_5m.parquet",
        help="Path to origination_5m.parquet",
    )
    parser.add_argument(
        "--output", default="data/raw/cc_pd/origination_5m_with_decisions.parquet",
        help="Output parquet path",
    )
    parser.add_argument("--db-path", default="policy_versions.db")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("CC DECISION ID GENERATOR")
    print(f"  Input : {in_path}")
    print(f"  Output: {out_path}")
    print("=" * 65)

    # 1. Load
    print("\n[1/5] Loading origination data …")
    df = pd.read_parquet(in_path)
    n_before = len(df)
    print(f"  Loaded {n_before:,} rows, {len(df.columns)} columns")

    # 2. Validate: no duplicate (account_id, orig_date)
    print("\n[2/5] Validating uniqueness …")
    dup_count = df.duplicated(subset=["account_id", "orig_date"]).sum()
    if dup_count > 0:
        raise ValueError(
            f"Found {dup_count:,} duplicate (account_id, orig_date) pairs — "
            "cannot generate deterministic unique UUIDs."
        )
    print(f"  OK — no duplicate (account_id, orig_date) pairs.")

    # 3. Policy cache
    print("\n[3/5] Building policy cache …")
    policy_cache = _build_policy_cache(args.db_path, df["orig_date"])

    # Resolve month buckets per row
    month_periods = pd.to_datetime(df["orig_date"]).dt.to_period("M")
    pv_id_series = month_periods.map(
        lambda p: policy_cache.get(str(p), (None, None, {}))[0]
    )
    pv_tag_series = month_periods.map(
        lambda p: policy_cache.get(str(p), (None, None, {}))[1]
    )

    # 4. UUID5 — deterministic
    print("\n[4/5] Generating decision_id (UUID5) …")
    decision_ids = _make_uuid5_array(
        df["account_id"].values, df["orig_date"]
    )
    unique_id_count = len(set(decision_ids))
    if unique_id_count != n_before:
        raise RuntimeError(
            f"UUID5 collision detected: {n_before:,} rows but only "
            f"{unique_id_count:,} unique decision_ids."
        )
    print(f"  Generated {unique_id_count:,} unique decision IDs.")

    # 5. Derive decision outcomes
    print("\n[5/5] Deriving decision outcomes …")
    fico_arr = df["fico_score"].values.astype(float)
    dti_arr = df["dti"].values.astype(float)
    month_arr = month_periods.values

    outcomes, reason_codes = _derive_outcome(
        fico_arr, dti_arr, None, month_arr, policy_cache
    )

    # Attach new columns (preserve all originals)
    df["decision_id"] = decision_ids
    df["policy_version_id"] = pv_id_series.values
    df["policy_version_tag"] = pv_tag_series.values
    df["decision_outcome"] = outcomes
    df["decision_reason_codes"] = reason_codes

    # Write
    df.to_parquet(out_path, index=False, compression="gzip")

    # Verification summary
    n_after = len(df)
    pct_pv_covered = (df["policy_version_id"].notna().sum() / n_after) * 100
    outcome_counts = df["decision_outcome"].value_counts()

    print("\n" + "=" * 65)
    print("VERIFICATION SUMMARY")
    print(f"  Rows before : {n_before:,}")
    print(f"  Rows after  : {n_after:,}")
    print(f"  Unique decision_id : {len(df['decision_id'].unique()):,} (must == {n_after:,})")
    print(f"  policy_version_id coverage: {pct_pv_covered:.1f}%")
    print(f"  Decision outcomes:\n{outcome_counts.to_string()}")
    print(f"\n  Output: {out_path}")
    print("=" * 65)


if __name__ == "__main__":
    main()
