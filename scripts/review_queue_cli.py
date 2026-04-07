from __future__ import annotations

import argparse
import os
import sys
from datetime import timezone
from pathlib import Path

# Path bootstrap
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from decisioning.review_queue import ReviewQueue  # noqa: E402


_RED = "\033[31m"
_RESET = "\033[0m"


def _fmt(dt) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


def cmd_list(args: argparse.Namespace) -> int:
    q = ReviewQueue(db_url=args.db_url)
    breached = q.check_sla_breaches()
    pending = q.get_pending(limit=args.limit)

    if breached:
        print(f"{_RED}SLA BREACHED:{_RESET}")
        for it in breached:
            print(f"  {it.item_id}  app={it.application_id}  deadline={_fmt(it.sla_deadline)}  status={it.status}")

    if not pending:
        print("(no pending items)")
        return 0

    print("PENDING:")
    for it in pending:
        print(f"  {it.item_id}  app={it.application_id}  deadline={_fmt(it.sla_deadline)}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    q = ReviewQueue(db_url=args.db_url)
    it = q.assign(args.item_id, args.reviewer_id)
    print(f"Assigned {it.item_id} to {it.assigned_to} (status={it.status})")
    return 0


def cmd_complete(args: argparse.Namespace) -> int:
    q = ReviewQueue(db_url=args.db_url)
    it = q.complete(
        args.item_id,
        override_decision=args.override_decision,
        override_reason_code=args.override_reason_code,
        notes=args.notes or "",
    )
    print(f"Completed {it.item_id} with {it.override_decision} ({it.override_reason_code})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="HITL Review Queue CLI")
    parser.add_argument(
        "--db-url",
        default=os.getenv("REVIEW_QUEUE_DB_URL", "sqlite:///./audit/review_queue.db"),
        help="SQLAlchemy DB URL for the review queue",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List pending items")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_assign = sub.add_parser("assign", help="Assign an item to a reviewer")
    p_assign.add_argument("item_id")
    p_assign.add_argument("reviewer_id")
    p_assign.set_defaults(func=cmd_assign)

    p_complete = sub.add_parser("complete", help="Complete an item")
    p_complete.add_argument("item_id")
    p_complete.add_argument("override_decision")
    p_complete.add_argument("override_reason_code")
    p_complete.add_argument("--notes", default="")
    p_complete.set_defaults(func=cmd_complete)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
