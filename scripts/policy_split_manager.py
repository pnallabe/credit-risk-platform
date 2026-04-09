"""Policy Split Manager CLI.

Subcommands:
  check-rollback   — Run auto_rollback_if_regressed(); exit 2 if rollback executed, 0 otherwise.
  promote-challenger — Promote the current challenger to champion.
  status           — Print the active split configuration (or "no split configured").

Usage:
  python scripts/policy_split_manager.py check-rollback  --tenant-id <id> [options]
  python scripts/policy_split_manager.py promote-challenger --tenant-id <id> [options]
  python scripts/policy_split_manager.py status --tenant-id <id> [options]

Options:
  --tenant-id       Tenant ID (required)
  --db-url          SQLAlchemy URL for the policy split store
                    (default: env POLICY_SPLIT_DB_URL or sqlite:///./policy_challenger.db)
  --lookback-days   Window for comparison report (default: 7, used by check-rollback)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Make project root importable when running as a script
ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from decision_engine.policy_challenger import PolicyChallengerRouter, PolicySplitStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s — %(message)s",
)
logger = logging.getLogger("policy_split_manager")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_store(db_url: str) -> PolicySplitStore:
    return PolicySplitStore(db_url=db_url)


def _build_router(store: PolicySplitStore) -> PolicyChallengerRouter:
    return PolicyChallengerRouter(store=store)


def _default_db_url() -> str:
    return os.getenv("POLICY_SPLIT_DB_URL", "sqlite:///./policy_challenger.db")


# ---------------------------------------------------------------------------
# Subcommand: check-rollback
# ---------------------------------------------------------------------------


def cmd_check_rollback(args: argparse.Namespace) -> int:
    """Run auto_rollback_if_regressed.  Exit 2 if rolled back, 0 otherwise."""
    store = _build_store(args.db_url)
    router = _build_router(store)

    result = router.auto_rollback_if_regressed(
        args.tenant_id, lookback_days=args.lookback_days
    )
    report = result["report"]

    output = {
        "tenant_id": args.tenant_id,
        "rolled_back": result["rolled_back"],
        "recommendation": report.recommendation,
        "approval_rate_delta": round(report.approval_rate_delta, 4),
        "sample_size_champion": report.sample_size_champion,
        "sample_size_challenger": report.sample_size_challenger,
    }
    print(json.dumps(output, indent=2))

    if result["rolled_back"]:
        logger.warning(
            "Auto-rollback executed for tenant=%s (recommendation=%s)",
            args.tenant_id,
            report.recommendation,
        )
        return 2  # non-zero exit so CI pipelines can detect rollbacks

    return 0


# ---------------------------------------------------------------------------
# Subcommand: promote-challenger
# ---------------------------------------------------------------------------


def cmd_promote_challenger(args: argparse.Namespace) -> int:
    """Promote the current challenger to champion."""
    store = _build_store(args.db_url)
    router = _build_router(store)

    try:
        new_champ, placeholder = router.promote_challenger(args.tenant_id)
    except ValueError as exc:
        logger.error("promote-challenger failed: %s", exc)
        return 1

    output = {
        "tenant_id": args.tenant_id,
        "new_champion_version_tag": new_champ.version_tag,
        "new_champion_version_id": new_champ.version_id,
        "status": "promoted",
    }
    print(json.dumps(output, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: status
# ---------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """Print the active split configuration."""
    store = _build_store(args.db_url)
    split = store.get_active_split(args.tenant_id)

    if split is None:
        output = {"tenant_id": args.tenant_id, "status": "no split configured"}
    else:
        champ, chall = split
        output = {
            "tenant_id": args.tenant_id,
            "status": "active",
            "champion": {
                "version_id": champ.version_id,
                "version_tag": champ.version_tag,
                "traffic_pct": champ.traffic_pct,
            },
            "challenger": {
                "version_id": chall.version_id,
                "version_tag": chall.version_tag,
                "traffic_pct": chall.traffic_pct,
            },
        }

    print(json.dumps(output, indent=2))
    return 0


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="policy_split_manager",
        description="Manage policy-level champion/challenger A/B splits.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared parent parser for common flags
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tenant-id", required=True, help="Tenant identifier")
    common.add_argument(
        "--db-url",
        default=None,
        help="SQLAlchemy URL for the policy split store (default: env POLICY_SPLIT_DB_URL)",
    )

    # check-rollback
    p_cr = sub.add_parser(
        "check-rollback",
        parents=[common],
        help="Check for challenger regression and roll back if necessary.",
    )
    p_cr.add_argument(
        "--lookback-days",
        type=int,
        default=7,
        help="Number of days to include in the comparison window (default: 7)",
    )

    # promote-challenger
    sub.add_parser(
        "promote-challenger",
        parents=[common],
        help="Promote the current challenger to champion.",
    )

    # status
    sub.add_parser(
        "status",
        parents=[common],
        help="Print the active split configuration for a tenant.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Resolve db_url (argument > env > default)
    if not args.db_url:
        args.db_url = _default_db_url()

    dispatch = {
        "check-rollback": cmd_check_rollback,
        "promote-challenger": cmd_promote_challenger,
        "status": cmd_status,
    }
    fn = dispatch.get(args.command)
    if fn is None:  # pragma: no cover
        parser.print_help()
        return 1

    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
