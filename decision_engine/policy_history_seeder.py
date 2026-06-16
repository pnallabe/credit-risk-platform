"""
decision_engine/policy_history_seeder.py
==========================================
Seeds 22 versioned policy snapshots (2015–2026) into ``policy_versions.db``
covering 9 macro-cycle epochs for CREDIT_CARD, PERSONAL_LOAN, and MORTGAGE.

Usage
-----
    python decision_engine/policy_history_seeder.py                        # seed to default DB
    python decision_engine/policy_history_seeder.py --db-path custom.db   # custom path
    python decision_engine/policy_history_seeder.py --dry-run              # preview without writing
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running directly from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decision_engine.policy_version_store import PolicyVersionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy snapshot definitions — 22 rows covering 2015-01-01 → 2026-07-01
# ---------------------------------------------------------------------------

def _make_cc_params(
    fico_floor: int,
    max_dti: float,
    max_pd_hard: float = 0.25,
    max_pd_review: float = 0.14,
    apr_floor: float = 17.99,
    max_credit_limit: int = 20_000,
) -> dict[str, Any]:
    return {
        "fico_floor": fico_floor,
        "max_dti": max_dti,
        "max_pd_hard": max_pd_hard,
        "max_pd_review": max_pd_review,
        "apr_floor": apr_floor,
        "max_credit_limit": max_credit_limit,
    }


def _make_pl_params(
    fico_floor_hard_decline: int,
    fico_floor_soft_decline: int,
    fico_floor_near_prime: int,
    max_dti_preferred: float,
    max_dti_standard: float,
    max_loan_amount: int = 50_000,
    base_rate: float = 11.99,
) -> dict[str, Any]:
    return {
        "fico_floor_hard_decline": fico_floor_hard_decline,
        "fico_floor_soft_decline": fico_floor_soft_decline,
        "fico_floor_near_prime": fico_floor_near_prime,
        "max_dti_preferred": max_dti_preferred,
        "max_dti_standard": max_dti_standard,
        "max_loan_amount": max_loan_amount,
        "base_rate": base_rate,
    }


def _make_mort_params(
    fico_floor_conforming: int,
    max_dti_qm: float,
    jumbo_enabled: bool = True,
    fico_floor_fha: int = 580,
    fico_floor_jumbo: int = 700,
    max_ltv_standard: float = 0.97,
    conforming_loan_limit: int = 726_200,
) -> dict[str, Any]:
    return {
        "fico_floor_fha": fico_floor_fha,
        "fico_floor_conforming": fico_floor_conforming,
        "fico_floor_jumbo": fico_floor_jumbo,
        "max_dti_qm": max_dti_qm,
        "max_ltv_standard": max_ltv_standard,
        "conforming_loan_limit": conforming_loan_limit,
        "jumbo_enabled": jumbo_enabled,
    }


# Each entry: (suffix, effective_from, cc_fico, pl_fico_hard, mort_fico_conform,
#              cc_max_dti, pl_max_dti_standard, mort_max_dti_qm, jumbo_enabled, note)
_EPOCH_TABLE = [
    ("2015-expansion",           "2015-01-01", 620, 580, 640, 0.50, 0.50, 0.43, True,  "Post-GFC expansion"),
    ("2016-steady",              "2016-01-01", 620, 580, 640, 0.50, 0.50, 0.43, True,  "Steady growth"),
    ("2017-tighten",             "2017-07-01", 640, 600, 660, 0.47, 0.47, 0.41, True,  "Rate hike cycle begins"),
    ("2018-tighten",             "2018-01-01", 660, 620, 680, 0.45, 0.45, 0.40, True,  "+125bps cumulative"),
    ("2019-cautious",            "2019-01-01", 660, 620, 680, 0.43, 0.43, 0.40, True,  "Late-cycle caution"),
    ("2020q1-covid-tighten",     "2020-03-15", 690, 650, 700, 0.40, 0.40, 0.38, True,  "COVID-19 shock"),
    ("2020q2-covid-hard",        "2020-04-01", 700, 660, 720, 0.38, 0.38, 0.36, False, "Jumbo halted"),
    ("2020q3-forbearance",       "2020-07-01", 680, 640, 700, 0.40, 0.42, 0.40, True,  "Relief overlay"),
    ("2021-stimulus",            "2021-01-01", 660, 620, 680, 0.45, 0.48, 0.43, True,  "Normalization"),
    ("2021-expand",              "2021-07-01", 640, 600, 660, 0.47, 0.50, 0.43, True,  "Limits expanded"),
    ("2022q1-hike",              "2022-03-01", 660, 620, 680, 0.45, 0.47, 0.41, True,  "Fed hike +25bps"),
    ("2022q2-emergency",         "2022-06-01", 680, 650, 700, 0.42, 0.44, 0.39, True,  "Emergency repricing"),
    ("2022q3-tighten",           "2022-09-01", 700, 660, 720, 0.40, 0.42, 0.38, True,  "Refi shutdown"),
    ("2022q4-hold",              "2022-12-01", 700, 660, 720, 0.40, 0.42, 0.38, True,  "Policy hold"),
    ("2023-stable",              "2023-01-01", 700, 660, 720, 0.40, 0.43, 0.38, True,  "High-rate stable"),
    ("2023-near-prime-tighten",  "2023-07-01", 700, 660, 720, 0.40, 0.43, 0.38, True,  "Near-prime selective"),
    ("2024-hold",                "2024-01-01", 700, 660, 720, 0.40, 0.43, 0.38, True,  "2024 hold"),
    ("2024-selective",           "2024-07-01", 695, 655, 715, 0.41, 0.44, 0.39, True,  "Selective easing"),
    ("2025-ease",                "2025-01-01", 680, 640, 700, 0.43, 0.46, 0.41, True,  "Easing cycle begins"),
    ("2025-expand",              "2025-07-01", 660, 620, 680, 0.45, 0.48, 0.43, True,  "Expansion"),
    ("2026-expand",              "2026-01-01", 650, 610, 670, 0.47, 0.50, 0.43, True,  "Continued expansion"),
    ("2026-current",             "2026-07-01", 640, 600, 660, 0.48, 0.50, 0.43, True,  "Projected"),
]

# PL derived floors: soft_decline = hard_decline + 20, near_prime = hard_decline + 40
# derived max_dti_preferred is always hard_decline_floor-based; use 0.36 as default floor
_PL_MAX_DTI_PREFERRED = 0.36


def _build_snapshots() -> list[dict]:
    """Build the 22 policy snapshot dicts from _EPOCH_TABLE."""
    snapshots = []
    for (
        suffix, effective_from,
        cc_fico, pl_fico_hard, mort_fico_conform,
        cc_max_dti, pl_max_dti_standard, mort_max_dti_qm,
        jumbo_enabled, note,
    ) in _EPOCH_TABLE:
        # Derive PL soft / near-prime floors from hard floor
        pl_fico_soft = pl_fico_hard + 20
        pl_fico_near = pl_fico_hard + 40

        # Adjust mort FHA floor: typically conforming - 60, minimum 580
        mort_fico_fha = max(580, mort_fico_conform - 60)

        # Jumbo FICO floor: conforming + 20 when enabled
        mort_fico_jumbo = mort_fico_conform + 20 if jumbo_enabled else mort_fico_conform + 40

        # CC max_pd_hard tightens with FICO floor: higher FICO = tighter PD threshold
        pd_hard = round(0.30 - (cc_fico - 620) * 0.0005, 4)
        pd_review = round(pd_hard * 0.56, 4)  # ~56% of hard threshold

        # CC apr_floor adjusts with rate cycle
        apr_floor = 17.99 if cc_fico <= 640 else (18.99 if cc_fico <= 680 else 19.99)

        # CC max credit limit loosens in expansion, tightens in crisis
        max_credit_limit = 25_000 if cc_max_dti >= 0.47 else (20_000 if cc_max_dti >= 0.43 else 15_000)

        # PL max_loan_amount
        pl_max_loan = 50_000 if pl_fico_hard <= 620 else (40_000 if pl_fico_hard <= 650 else 35_000)

        # PL base_rate: rises with tightening
        pl_base_rate = 11.99 if pl_max_dti_standard >= 0.48 else (
            12.99 if pl_max_dti_standard >= 0.44 else 13.99
        )

        parameters = {
            "CREDIT_CARD": _make_cc_params(
                fico_floor=cc_fico,
                max_dti=cc_max_dti,
                max_pd_hard=pd_hard,
                max_pd_review=pd_review,
                apr_floor=apr_floor,
                max_credit_limit=max_credit_limit,
            ),
            "PERSONAL_LOAN": _make_pl_params(
                fico_floor_hard_decline=pl_fico_hard,
                fico_floor_soft_decline=pl_fico_soft,
                fico_floor_near_prime=pl_fico_near,
                max_dti_preferred=_PL_MAX_DTI_PREFERRED,
                max_dti_standard=pl_max_dti_standard,
                max_loan_amount=pl_max_loan,
                base_rate=pl_base_rate,
            ),
            "MORTGAGE": _make_mort_params(
                fico_floor_conforming=mort_fico_conform,
                max_dti_qm=mort_max_dti_qm,
                jumbo_enabled=jumbo_enabled,
                fico_floor_fha=mort_fico_fha,
                fico_floor_jumbo=mort_fico_jumbo,
            ),
        }

        snapshots.append({
            "version_tag": f"multi-v1-{suffix}",
            "effective_from": effective_from,
            "author": "policy_seeder_v1",
            "note": note,
            "parameters": parameters,
        })

    return snapshots


# ---------------------------------------------------------------------------
# Seeder entry point
# ---------------------------------------------------------------------------


def seed(db_path: str = "policy_versions.db", dry_run: bool = False) -> list[int]:
    """Seed all 22 policy snapshots. Returns list of version_ids created.

    Parameters
    ----------
    db_path :
        Path to the SQLite database file.
    dry_run :
        If True, compute snapshots and print but do not write to the database.

    Returns
    -------
    list[int]
        IDs of newly published versions (empty list on dry_run or if all skipped).
    """
    snapshots = _build_snapshots()
    assert len(snapshots) == 22, f"Expected 22 snapshots, got {len(snapshots)}"

    if dry_run:
        log.info("DRY-RUN — would seed %d policy snapshots:", len(snapshots))
        _print_summary_table(snapshots)
        _verify_no_date_gaps(snapshots)
        return []

    store = PolicyVersionStore(db_path=Path(db_path))

    # Build set of existing version_tags for idempotency
    existing_tags = {v.version_tag for v in store.list_versions(limit=200)}
    log.info("Existing version tags in DB: %d", len(existing_tags))

    created_ids: list[int] = []
    for snap in snapshots:
        tag = snap["version_tag"]
        if tag in existing_tags:
            log.info("  SKIP  %s (already exists)", tag)
            continue

        effective_from_dt = datetime.fromisoformat(snap["effective_from"]).replace(
            tzinfo=timezone.utc
        )
        version_id = store.publish(
            parameters=snap["parameters"],
            author=snap["author"],
            note=snap["note"],
            version_tag=tag,
            effective_from=effective_from_dt,
        )
        created_ids.append(version_id)
        log.info("  SEED  %s  (id=%d, effective=%s)", tag, version_id, snap["effective_from"])

    # Verification
    all_versions = store.list_versions(limit=200)
    total = len(all_versions)
    if total < 22:
        log.warning(
            "Verification: expected ≥22 versions in DB, found %d. "
            "Some may have been pre-existing under different tags.",
            total,
        )
    else:
        log.info("Verification PASSED: %d versions found in DB (≥22).", total)

    _print_summary_table(snapshots, created_ids=created_ids)
    _verify_no_date_gaps(snapshots)
    return created_ids


def _print_summary_table(
    snapshots: list[dict], created_ids: list[int] | None = None
) -> None:
    """Print a formatted summary of all 22 policy snapshots."""
    header = (
        f"{'version_tag':<42} {'effective_from':<14} "
        f"{'CC FICO':<8} {'PL FICO':<8} {'Mort FICO':<10} "
        f"{'CC DTI':<8} {'PL DTI':<8} {'QM DTI':<8} {'Jumbo'}"
    )
    print()
    print("─" * len(header))
    print(header)
    print("─" * len(header))

    for snap in snapshots:
        cc = snap["parameters"]["CREDIT_CARD"]
        pl = snap["parameters"]["PERSONAL_LOAN"]
        mo = snap["parameters"]["MORTGAGE"]
        status = " *" if (created_ids and any(snap["version_tag"])) else ""
        print(
            f"{snap['version_tag']:<42} {snap['effective_from']:<14} "
            f"{cc['fico_floor']:<8} {pl['fico_floor_hard_decline']:<8} "
            f"{mo['fico_floor_conforming']:<10} "
            f"{cc['max_dti']:<8.2f} {pl['max_dti_standard']:<8.2f} "
            f"{mo['max_dti_qm']:<8.2f} "
            f"{'Y' if mo['jumbo_enabled'] else 'N'}"
        )

    print("─" * len(header))
    print(f"  Total: {len(snapshots)} snapshots")
    print()


def _verify_no_date_gaps(snapshots: list[dict]) -> None:
    """Verify snapshots are in chronological order and cover 2015-2026."""
    dates = [snap["effective_from"] for snap in snapshots]
    for i in range(1, len(dates)):
        if dates[i] <= dates[i - 1]:
            log.warning(
                "Date ordering issue: %s ≤ %s", dates[i], dates[i - 1]
            )
    first, last = dates[0], dates[-1]
    if first != "2015-01-01":
        log.warning("First epoch expected 2015-01-01, got %s", first)
    if last < "2026-07-01":
        log.warning("Last epoch expected ≥2026-07-01, got %s", last)
    log.info("Date coverage: %s → %s (%d snapshots)", first, last, len(snapshots))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Seed 22 versioned policy snapshots into policy_versions.db"
    )
    parser.add_argument(
        "--db-path",
        default="policy_versions.db",
        help="Path to the SQLite database file (default: policy_versions.db)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview snapshots without writing to the database",
    )
    args = parser.parse_args()

    ids = seed(db_path=args.db_path, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"\nSeeded {len(ids)} new version(s): {ids}")
