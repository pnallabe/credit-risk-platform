#!/usr/bin/env python3
"""
data/generate_decision_registry.py
====================================
Build the unified cross-product decision registry by combining:
  - CC origination data (5M rows)   from data/raw/cc_pd/origination_5m_with_decisions.parquet
  - Personal loan applications       from data/raw/loans/personal_loan_applications.parquet
  - Mortgage applications            from data/raw/loans/mortgage_applications.parquet

Output: data/raw/decisions/decision_registry.parquet

Schema: decision_id, product_type, application_id, customer_id, decision_outcome,
        decision_timestamp, policy_version_id, policy_version_tag, model_version_id,
        underwriter_type, override_flag, override_reason, override_author,
        fcra_reason_codes, credit_score_at_decision, dti_at_decision,
        pd_score, fraud_score, approved_amount, approved_rate, channel, state

Usage:
    python data/generate_decision_registry.py [--db-path policy_versions.db]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Project root on sys.path ─────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from decision_engine.policy_version_store import PolicyVersionStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DECISION_NS = uuid.NAMESPACE_OID

MODEL_VERSION_MAP: dict[str, str] = {
    "credit_card": "cc_pd_v1",
    "personal_loan": "pl_pd_v1",
    "mortgage": "mortgage_pd_v1",
}

CHANNEL_CHOICES = ["online", "branch", "mobile", "partner", "phone"]
CHANNEL_WEIGHTS = [0.52, 0.20, 0.15, 0.10, 0.03]

UNDERWRITER_AUTHORS = [f"UW{str(i).zfill(4)}" for i in range(1, 51)]

# Canonical outcome vocabulary
_OUTCOME_NORMALISE: dict[str, str] = {
    "DECLINE": "REJECT",
    "APPROVE_QM": "APPROVE",
    "APPROVE_NON_QM": "APPROVE",
    "REFER_FHA": "REFER",
}


# ── PII masking ───────────────────────────────────────────────────────────────

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _sha256_series(s: pd.Series) -> pd.Series:
    """Vectorise SHA-256 over a string Series."""
    return s.astype(str).apply(_sha256)


# ── UUID helpers ──────────────────────────────────────────────────────────────

def _uuid5_series(prefix: str, id_series: pd.Series) -> pd.Series:
    """Generate UUID5 strings from a prefix + id_series (no iterrows)."""
    return pd.Series(
        [str(uuid.uuid5(DECISION_NS, f"{prefix}:{aid}")) for aid in id_series.astype(str)],
        index=id_series.index,
    )


# ── Outcome normalisation ─────────────────────────────────────────────────────

def _normalise_outcomes(s: pd.Series) -> pd.Series:
    upper = s.str.upper()
    return upper.map(lambda x: _OUTCOME_NORMALISE.get(x, x))


# ── CC preparation ────────────────────────────────────────────────────────────

def prepare_cc(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """
    Map CC origination frame to registry schema.
    CC source lacks pd_score and fraud_score — synthetic values are generated
    using a deterministic FICO-correlated model.
    """
    out: dict[str, object] = {}

    out["decision_id"] = df["decision_id"].astype(str).values
    out["product_type"] = "credit_card"
    out["application_id"] = df["account_id"].astype(str).values
    out["customer_id"] = _sha256_series(df["account_id"].astype(str)).values

    raw_outcome = df["decision_outcome"].str.upper()
    out["decision_outcome"] = _normalise_outcomes(df["decision_outcome"]).values

    out["decision_timestamp"] = pd.to_datetime(df["orig_date"], utc=True).values
    out["policy_version_id"] = df["policy_version_id"].astype("Int64").values
    out["policy_version_tag"] = df["policy_version_tag"].astype(str).values
    out["model_version_id"] = MODEL_VERSION_MAP["credit_card"]

    out["fcra_reason_codes"] = df["decision_reason_codes"].astype(str).values
    out["credit_score_at_decision"] = df["fico_score"].astype(int).values
    out["dti_at_decision"] = df["dti"].astype(float).values

    # ── Synthetic pd_score & fraud_score ────────────────────────────────────
    n = len(df)
    fico_norm = (df["fico_score"].values.astype(float) - 300.0) / 550.0  # [0, 1]
    base_pd = np.clip(0.35 - 0.28 * fico_norm, 0.01, 0.80)
    reject_mask = raw_outcome.values == "REJECT"
    refer_mask = raw_outcome.values == "REFER"
    base_pd[reject_mask] += 0.12
    base_pd[refer_mask] += 0.05
    pd_noise = rng.normal(0, 0.015, n)
    out["pd_score"] = np.clip(base_pd + pd_noise, 0.005, 0.95).round(4)

    fraud_base = rng.beta(1.2, 25, n)
    fraud_base[reject_mask] *= 2.0
    fraud_base[refer_mask] *= 1.4
    out["fraud_score"] = np.clip(fraud_base, 0.001, 0.99).round(4)

    # ── Approved fields ──────────────────────────────────────────────────────
    approve_mask = raw_outcome.values == "APPROVE"
    out["approved_amount"] = np.where(approve_mask, df["credit_limit"].astype(float).values, np.nan)
    out["approved_rate"] = np.where(approve_mask, df["apr"].astype(float).values, np.nan)

    out["channel"] = df["app_channel"].astype(str).values
    out["state"] = df["state"].astype(str).values

    return pd.DataFrame(out)


# ── Personal Loan preparation ─────────────────────────────────────────────────

def prepare_pl(df: pd.DataFrame) -> pd.DataFrame:
    """Map personal loan applications to registry schema."""
    out: dict[str, object] = {}

    out["decision_id"] = _uuid5_series("pl", df["application_id"]).values
    out["product_type"] = "personal_loan"
    out["application_id"] = df["application_id"].astype(str).values
    out["customer_id"] = _sha256_series(df["customer_id"].astype(str)).values

    out["decision_outcome"] = _normalise_outcomes(df["decision_outcome"]).values

    out["decision_timestamp"] = pd.to_datetime(df["applied_at"], utc=True).values
    out["policy_version_id"] = df["policy_version_id"].astype("Int64").values
    out["policy_version_tag"] = df["policy_version_tag"].astype(str).values
    out["model_version_id"] = MODEL_VERSION_MAP["personal_loan"]

    out["fcra_reason_codes"] = df["fcra_reason_codes"].astype(str).values
    out["credit_score_at_decision"] = df["fico_score"].astype(int).values
    out["dti_at_decision"] = df["dti"].astype(float).values
    out["pd_score"] = df["pd_score"].astype(float).values
    out["fraud_score"] = df["fraud_score"].astype(float).values

    approve_mask = df["decision_outcome"].str.upper() == "APPROVE"
    out["approved_amount"] = np.where(
        approve_mask, df["approved_amount"].astype(float).values, np.nan
    )
    out["approved_rate"] = np.where(
        approve_mask, df["approved_rate"].astype(float).values, np.nan
    )

    out["channel"] = df["channel"].astype(str).values
    out["state"] = df["state"].astype(str).values

    return pd.DataFrame(out)


# ── Mortgage preparation ──────────────────────────────────────────────────────

def prepare_mortgage(df: pd.DataFrame) -> pd.DataFrame:
    """Map mortgage applications to registry schema."""
    out: dict[str, object] = {}

    out["decision_id"] = _uuid5_series("mort", df["application_id"]).values
    out["product_type"] = "mortgage"
    out["application_id"] = df["application_id"].astype(str).values
    out["customer_id"] = _sha256_series(df["customer_id"].astype(str)).values

    out["decision_outcome"] = _normalise_outcomes(df["decision_outcome"]).values

    out["decision_timestamp"] = pd.to_datetime(df["applied_at"], utc=True).values
    out["policy_version_id"] = df["policy_version_id"].astype("Int64").values
    out["policy_version_tag"] = df["policy_version_tag"].astype(str).values
    out["model_version_id"] = MODEL_VERSION_MAP["mortgage"]

    # atr_factors_failed contains ATR factor names for declined mortgages
    out["fcra_reason_codes"] = df["atr_factors_failed"].astype(str).values
    out["credit_score_at_decision"] = df["fico_score"].astype(int).values
    out["dti_at_decision"] = df["dti"].astype(float).values
    out["pd_score"] = df["pd_score"].astype(float).values
    out["fraud_score"] = df["fraud_score"].astype(float).values

    approve_mask = df["decision_outcome"].str.upper().isin(
        {"APPROVE_QM", "APPROVE_NON_QM", "APPROVE"}
    )
    out["approved_amount"] = np.where(
        approve_mask, df["approved_amount"].astype(float).values, np.nan
    )
    out["approved_rate"] = np.where(
        approve_mask, df["approved_rate"].astype(float).values, np.nan
    )

    out["channel"] = df["channel"].astype(str).values
    out["state"] = df["state"].astype(str).values

    return pd.DataFrame(out)


# ── Underwriter type ──────────────────────────────────────────────────────────

def derive_underwriter_type(df: pd.DataFrame) -> np.ndarray:
    """
    Classify each row as automated / hybrid / human_underwriter.

    Rules (first match wins):
      1. APPROVE + FICO ≥ 720 + fraud_score < 0.05  → automated
      2. APPROVE + 620 ≤ FICO < 720                 → hybrid
      3. MANUAL_REVIEW or REFER outcome              → human_underwriter
      4. COUNTER_OFFER                               → hybrid
      5. All other APPROVE / REJECT                  → automated
    """
    outcome = df["decision_outcome"].str.upper().values
    fico = df["credit_score_at_decision"].values.astype(float)
    fraud = df["fraud_score"].values.astype(float)

    result = np.full(len(df), "automated", dtype=object)

    # Evaluate in reverse priority order (later = higher priority)
    result[outcome == "COUNTER_OFFER"] = "hybrid"
    result[np.isin(outcome, ["MANUAL_REVIEW", "REFER"])] = "human_underwriter"
    result[(outcome == "APPROVE") & (fico >= 620) & (fico < 720)] = "hybrid"
    result[(outcome == "APPROVE") & (fico >= 720) & (fraud < 0.05)] = "automated"

    return result


# ── Channel fill ──────────────────────────────────────────────────────────────

def fill_missing_channels(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Replace unknown/null channel values with randomly sampled ones."""
    df = df.copy()
    unknown_mask = df["channel"].isin({"nan", "None", "unknown", "", "NaN"})
    n_unknown = unknown_mask.sum()
    if n_unknown > 0:
        df.loc[unknown_mask, "channel"] = rng.choice(
            CHANNEL_CHOICES, size=n_unknown, p=CHANNEL_WEIGHTS
        )
        log.info("Assigned random channels to %d rows", n_unknown)
    return df


# ── Override flags ────────────────────────────────────────────────────────────

def assign_overrides(
    df: pd.DataFrame,
    policy_snapshot: dict[int, dict],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Mark 2% of APPROVE rows where the applicant's FICO was below the product's
    policy floor as underwriter overrides (simulate exception approvals).
    """
    df = df.copy()
    df["override_flag"] = False
    df["override_reason"] = pd.NA
    df["override_author"] = pd.NA

    # Build (version_id, product_type) → fico_floor lookup
    floor_map: dict[tuple, int] = {}
    for vid, params in policy_snapshot.items():
        floor_map[(vid, "credit_card")] = (
            params.get("CREDIT_CARD", {}).get("fico_floor", 0) or 0
        )
        floor_map[(vid, "personal_loan")] = (
            params.get("PERSONAL_LOAN", {}).get("fico_floor_hard_decline", 0) or 0
        )
        floor_map[(vid, "mortgage")] = (
            params.get("MORTGAGE", {}).get("fico_floor_conforming", 0) or 0
        )

    # Vectorise the floor lookup
    vid_arr = df["policy_version_id"].astype(object).values  # nullable Int64 → object
    prod_arr = df["product_type"].values
    fico_floors = np.array(
        [floor_map.get((vid, pt), 0) or 0 for vid, pt in zip(vid_arr, prod_arr)],
        dtype=float,
    )

    approve_mask = df["decision_outcome"].values == "APPROVE"
    below_floor_mask = df["credit_score_at_decision"].values.astype(float) < fico_floors
    eligible_idx = np.where(approve_mask & below_floor_mask)[0]

    if len(eligible_idx) > 0:
        n_override = max(1, int(len(eligible_idx) * 0.02))
        chosen = rng.choice(eligible_idx, size=n_override, replace=False)
        df.iloc[chosen, df.columns.get_loc("override_flag")] = True
        df.iloc[chosen, df.columns.get_loc("override_reason")] = (
            "Underwriter exception — compensating factors"
        )
        df.iloc[chosen, df.columns.get_loc("override_author")] = rng.choice(
            UNDERWRITER_AUTHORS, size=n_override
        )
        log.info(
            "Override flags: %d eligible rows → %d flagged (2%%)",
            len(eligible_idx),
            n_override,
        )
    else:
        log.warning("No override-eligible rows found (APPROVE + FICO < floor).")

    return df


# ── Referential integrity check ───────────────────────────────────────────────

def check_referential_integrity(
    df: pd.DataFrame,
    store: PolicyVersionStore,
) -> float:
    """
    Verify every row's decision_timestamp falls within its policy version's
    [effective_from, superseded_at) window.  Logs warnings for discrepancies.
    Returns pass rate as a float in [0, 1].
    """
    audit_raw = store.export_audit_trail(limit=200)
    versions = json.loads(audit_raw)

    # Build lookup: version_id → (effective_from UTC, superseded_at UTC | max)
    _max_ts = pd.Timestamp.max.tz_localize("UTC")
    window_lookup: dict[int, tuple[pd.Timestamp, pd.Timestamp]] = {}
    for v in versions:
        eff = pd.Timestamp(v["effective_from"]).tz_localize("UTC") if pd.Timestamp(v["effective_from"]).tzinfo is None else pd.Timestamp(v["effective_from"]).tz_convert("UTC")
        sup_raw = v.get("superseded_at")
        if sup_raw:
            sup = pd.Timestamp(sup_raw)
            sup = sup.tz_localize("UTC") if sup.tzinfo is None else sup.tz_convert("UTC")
        else:
            sup = _max_ts
        window_lookup[int(v["id"])] = (eff, sup)

    n_total = len(df)
    n_pass = 0
    n_fail = 0
    n_missing = 0

    # Ensure decision_timestamp is UTC-aware
    ts_col = pd.to_datetime(df["decision_timestamp"], utc=True)

    for version_id, group_idx in df.groupby("policy_version_id").groups.items():
        if pd.isna(version_id):
            n_missing += len(group_idx)
            log.warning("%d rows have null policy_version_id", len(group_idx))
            continue

        vid = int(version_id)
        if vid not in window_lookup:
            log.warning(
                "policy_version_id %d not found in audit trail (%d rows affected)",
                vid,
                len(group_idx),
            )
            n_fail += len(group_idx)
            continue

        eff_from, eff_to = window_lookup[vid]
        ts = ts_col.iloc[group_idx] if isinstance(group_idx, list) else ts_col.loc[group_idx]
        in_window = (ts >= eff_from) & (ts < eff_to)
        n_pass += int(in_window.sum())
        bad = int((~in_window).sum())
        n_fail += bad
        if bad:
            sup_str = eff_to.date() if eff_to != _max_ts else "∞"
            log.warning(
                "policy_version_id %d: %d rows outside window [%s, %s)",
                vid,
                bad,
                eff_from.date(),
                sup_str,
            )

    denominator = n_total - n_missing
    pass_rate = n_pass / denominator if denominator > 0 else 0.0
    log.info(
        "Referential integrity: %d/%d rows pass (%.2f%%) — %d with null policy_version_id",
        n_pass,
        denominator,
        100.0 * pass_rate,
        n_missing,
    )
    return pass_rate


# ── Main pipeline ─────────────────────────────────────────────────────────────

def build_registry(
    cc_path: Path,
    pl_path: Path,
    mort_path: Path,
    output_path: Path,
    db_path: Path,
) -> None:
    rng = np.random.default_rng(42)

    # ── Load sources ─────────────────────────────────────────────────────────
    log.info("Loading CC origination data from %s …", cc_path)
    cc_df = pd.read_parquet(cc_path, engine="pyarrow")
    log.info("  CC rows: %d", len(cc_df))

    log.info("Loading personal loan applications from %s …", pl_path)
    pl_df = pd.read_parquet(pl_path, engine="pyarrow")
    log.info("  PL rows: %d", len(pl_df))

    log.info("Loading mortgage applications from %s …", mort_path)
    mort_df = pd.read_parquet(mort_path, engine="pyarrow")
    log.info("  Mortgage rows: %d", len(mort_df))

    # ── Transform ────────────────────────────────────────────────────────────
    log.info("Transforming CC data …")
    cc_reg = prepare_cc(cc_df, rng)
    del cc_df

    log.info("Transforming personal loan data …")
    pl_reg = prepare_pl(pl_df)
    del pl_df

    log.info("Transforming mortgage data …")
    mort_reg = prepare_mortgage(mort_df)
    del mort_df

    # ── Combine ──────────────────────────────────────────────────────────────
    log.info("Combining all sources …")
    registry = pd.concat([cc_reg, pl_reg, mort_reg], ignore_index=True)
    log.info("Combined registry: %d rows", len(registry))

    # ── Derive underwriter type ───────────────────────────────────────────────
    log.info("Deriving underwriter types …")
    registry["underwriter_type"] = derive_underwriter_type(registry)

    # ── Fill missing channels ─────────────────────────────────────────────────
    registry = fill_missing_channels(registry, rng)

    # ── Load policy store & assign overrides ──────────────────────────────────
    log.info("Loading policy version store from %s …", db_path)
    store = PolicyVersionStore(db_path=db_path)
    versions_json = json.loads(store.export_audit_trail(limit=200))
    policy_snapshot: dict[int, dict] = {v["id"]: v["parameters"] for v in versions_json}

    log.info("Assigning override flags …")
    registry = assign_overrides(registry, policy_snapshot, rng)

    # ── Enforce column order ──────────────────────────────────────────────────
    COLUMN_ORDER = [
        "decision_id", "product_type", "application_id", "customer_id",
        "decision_outcome", "decision_timestamp", "policy_version_id",
        "policy_version_tag", "model_version_id", "underwriter_type",
        "override_flag", "override_reason", "override_author",
        "fcra_reason_codes", "credit_score_at_decision", "dti_at_decision",
        "pd_score", "fraud_score", "approved_amount", "approved_rate",
        "channel", "state",
    ]
    registry = registry[COLUMN_ORDER]

    # ── Write output ──────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Writing registry to %s …", output_path)
    registry.to_parquet(output_path, engine="pyarrow", index=False)

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Decision Registry Summary")
    print("=" * 60)
    print(f"Total rows: {len(registry):,}")

    print("\nBy product_type:")
    for product, cnt in registry["product_type"].value_counts().items():
        print(f"  {product:<20} {cnt:>10,}")

    print("\nBy decision_outcome:")
    for outcome, cnt in registry["decision_outcome"].value_counts().items():
        print(f"  {outcome:<25} {cnt:>10,}")

    print("\nBy underwriter_type:")
    for utype, cnt in registry["underwriter_type"].value_counts().items():
        print(f"  {utype:<22} {cnt:>10,}")

    override_count = int(registry["override_flag"].sum())
    print(f"\nOverride flags: {override_count:,} rows ({100 * override_count / len(registry):.3f}%)")

    # ── Referential integrity ─────────────────────────────────────────────────
    log.info("Running referential integrity check …")
    pass_rate = check_referential_integrity(registry, store)
    print(f"\nReferential integrity pass rate: {100 * pass_rate:.2f}%")

    file_size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"\nOutput: {output_path}")
    print(f"File size: {file_size_mb:.1f} MB")
    print("=" * 60)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate unified cross-product decision registry parquet"
    )
    parser.add_argument(
        "--cc-path",
        default="data/raw/cc_pd/origination_5m_with_decisions.parquet",
        help="CC origination file with decision metadata",
    )
    parser.add_argument(
        "--pl-path",
        default="data/raw/loans/personal_loan_applications.parquet",
        help="Personal loan applications parquet",
    )
    parser.add_argument(
        "--mort-path",
        default="data/raw/loans/mortgage_applications.parquet",
        help="Mortgage applications parquet",
    )
    parser.add_argument(
        "--output",
        default="data/raw/decisions/decision_registry.parquet",
        help="Output path for decision registry parquet",
    )
    parser.add_argument(
        "--db-path",
        default="policy_versions.db",
        help="Path to policy_versions.db SQLite database",
    )
    args = parser.parse_args()

    build_registry(
        cc_path=PROJECT_ROOT / args.cc_path,
        pl_path=PROJECT_ROOT / args.pl_path,
        mort_path=PROJECT_ROOT / args.mort_path,
        output_path=PROJECT_ROOT / args.output,
        db_path=PROJECT_ROOT / args.db_path,
    )


if __name__ == "__main__":
    main()
