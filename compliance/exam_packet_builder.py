"""
compliance/exam_packet_builder.py
===================================
Exam Packet Builder for regulatory examination preparation.

Implements the Adverse Action Summary component fully; all other components
return stubs to be filled in subsequent sprints.

CLI Usage
---------
python -m compliance.exam_packet_builder \\
    --tenant-id <id> \\
    --from 2026-01-01 \\
    --to 2026-03-31 \\
    --components adverse_actions \\
    --format json

Public API
----------
>>> from compliance.exam_packet_builder import (
...     ExamPacketSpec,
...     ExamPacket,
...     build_exam_packet,
... )
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExamPacketSpec:
    """Specification for a regulatory exam packet."""

    tenant_id: str
    from_date: str
    to_date: str
    components: List[str]
    format: Literal["json", "pdf_zip"]
    template: str = "OCC_EXAMINATION"


@dataclass
class ExamPacketComponent:
    """A single component of an exam packet."""

    name: str
    status: Literal["complete", "stub", "error"]
    data: Optional[Dict[str, Any]]
    error_message: Optional[str] = None


@dataclass
class ExamPacket:
    """A complete regulatory exam packet."""

    packet_id: str
    tenant_id: str
    generated_at: str
    from_date: str
    to_date: str
    template: str
    components: List[ExamPacketComponent]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "packet_id":    self.packet_id,
            "tenant_id":    self.tenant_id,
            "generated_at": self.generated_at,
            "from_date":    self.from_date,
            "to_date":      self.to_date,
            "template":     self.template,
            "components": [
                {
                    "name":          c.name,
                    "status":        c.status,
                    "data":          c.data,
                    "error_message": c.error_message,
                }
                for c in self.components
            ],
        }

    def summary_text(self) -> str:
        """Return a human-readable summary of what's included."""
        lines = [
            f"Exam Packet: {self.packet_id}",
            f"Tenant:      {self.tenant_id}",
            f"Period:      {self.from_date} – {self.to_date}",
            f"Template:    {self.template}",
            f"Generated:   {self.generated_at}",
            "",
            "Components:",
        ]
        for comp in self.components:
            lines.append(f"  [{comp.status.upper():8s}] {comp.name}")
            if comp.error_message:
                lines.append(f"               Error: {comp.error_message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------


async def build_adverse_action_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Adverse Action Summary component.

    Queries ``adverse_action_log`` and computes delivery compliance metrics.
    """
    try:
        from compliance.adverse_action_store import list_notices

        page_size = 1000
        page = 1
        all_records: List[Dict[str, Any]] = []

        while True:
            records, total = await list_notices(
                db_url,
                spec.tenant_id,
                from_date=spec.from_date,
                to_date=spec.to_date,
                page=page,
                per_page=page_size,
            )
            all_records.extend(records)
            if len(all_records) >= total or not records:
                break
            page += 1

        total_notices = len(all_records)
        delivered  = sum(1 for r in all_records if r.get("delivery_status") == "DELIVERED")
        pending    = sum(1 for r in all_records if r.get("delivery_status") == "PENDING")
        failed     = sum(1 for r in all_records if r.get("delivery_status") == "FAILED")

        today = date.today().isoformat()
        overdue = sum(
            1 for r in all_records
            if r.get("delivery_status") == "PENDING"
            and r.get("deadline_date", "9999-12-31") < today
        )

        delivery_compliance_rate = (delivered / total_notices * 100) if total_notices else 0.0

        # Reason code distribution
        code_counts: Dict[str, int] = {}
        for r in all_records:
            codes = r.get("reason_codes", [])
            if isinstance(codes, str):
                try:
                    codes = json.loads(codes)
                except Exception:
                    codes = []
            for code in codes:
                code_counts[code] = code_counts.get(code, 0) + 1

        return ExamPacketComponent(
            name="adverse_actions",
            status="complete",
            data={
                "total_notices":           total_notices,
                "delivered_count":         delivered,
                "pending_count":           pending,
                "failed_count":            failed,
                "delivery_compliance_rate": round(delivery_compliance_rate, 2),
                "overdue_count":           overdue,
                "reason_code_distribution": code_counts,
            },
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="adverse_actions",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_exam_packet(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacket:
    """Build a full exam packet per the given spec.

    The ``adverse_actions`` component is fully implemented.
    All other requested components return stubs.
    """
    components: List[ExamPacketComponent] = []

    for component_name in spec.components:
        if component_name == "adverse_actions":
            comp = await build_adverse_action_component(spec, db_url)
        else:
            comp = ExamPacketComponent(
                name=component_name,
                status="stub",
                data=None,
            )
        components.append(comp)

    return ExamPacket(
        packet_id=str(uuid.uuid4()),
        tenant_id=spec.tenant_id,
        generated_at=datetime.now(timezone.utc).isoformat(),
        from_date=spec.from_date,
        to_date=spec.to_date,
        template=spec.template,
        components=components,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a regulatory exam packet for a tenant."
    )
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--from", dest="from_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to", dest="to_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument(
        "--components",
        nargs="+",
        default=["adverse_actions"],
        help="Components to include",
    )
    parser.add_argument(
        "--format",
        default="json",
        choices=["json", "pdf_zip"],
        dest="fmt",
    )
    parser.add_argument(
        "--db-url",
        default="sqlite+aiosqlite:///./decision_audit.db",
    )
    return parser


async def _async_main(args: argparse.Namespace) -> int:
    spec = ExamPacketSpec(
        tenant_id=args.tenant_id,
        from_date=args.from_date,
        to_date=args.to_date,
        components=args.components,
        format=args.fmt,
    )
    packet = await build_exam_packet(spec, args.db_url)
    print(json.dumps(packet.to_dict(), indent=2))
    return 0


def main() -> None:  # pragma: no cover
    parser = _build_arg_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
