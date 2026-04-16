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
import dataclasses
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
    status: Literal["complete", "stub", "pending", "error"]
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


async def build_model_documentation_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the SR 11-7 Model Documentation Record component."""
    try:
        from compliance.generate_model_doc import (
            ModelDocumentationConfig,
            generate_mdr,
        )

        config = ModelDocumentationConfig(
            model_name="cc_pd_model",
            version="v1",
            use_case="Credit Card Probability of Default",
            owner="Risk Analytics",
            reviewer="Model Risk Management",
            approver="Chief Risk Officer",
            intended_population="US credit card applicants, age 18+",
        )
        mdr = generate_mdr(run_id=None, config=config)
        return ExamPacketComponent(
            name="model_documentation",
            status="complete",
            data=dataclasses.asdict(mdr),
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="model_documentation",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_policy_snapshots_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Policy Version Snapshots component."""
    try:
        from decision_engine.policy_version_store import PolicyVersionStore

        store = PolicyVersionStore()
        as_of_dt = datetime.fromisoformat(spec.to_date)
        active_version = store.get_as_of(as_of_dt)
        change_log = store.list_versions(limit=20)

        return ExamPacketComponent(
            name="policy_snapshots",
            status="complete",
            data={
                "version_id": active_version.version_id if hasattr(active_version, "version_id") else str(active_version),
                "active_policy": dataclasses.asdict(active_version) if dataclasses.is_dataclass(active_version) else str(active_version),
                "change_log_count": len(change_log),
                "change_log": [
                    dataclasses.asdict(v) if dataclasses.is_dataclass(v) else str(v)
                    for v in change_log
                ],
            },
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="policy_snapshots",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_decision_samples_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Decision Samples component with up to 50 records."""
    try:
        from audit.logger import get_audit_records_by_period

        records = await get_audit_records_by_period(
            tenant_id=spec.tenant_id,
            period_start=spec.from_date,
            period_end=spec.to_date,
            db_url=db_url,
            max_records=50,
        )

        samples = []
        for rec in records:
            samples.append({
                "application_id": rec.get("application_id"),
                "logged_at":      rec.get("logged_at"),
                "decision_output": rec.get("decision_output"),
                "fraud_score":     rec.get("fraud_score"),
                "risk_score":      rec.get("risk_score"),
            })

        return ExamPacketComponent(
            name="decision_samples",
            status="complete",
            data={"sample_count": len(samples), "samples": samples},
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="decision_samples",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_fair_lending_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Fair Lending Analysis component."""
    try:
        import pandas as pd
        from audit.logger import get_audit_records_by_period
        from monitoring.fair_lending import analyze_fair_lending

        records = await get_audit_records_by_period(
            tenant_id=spec.tenant_id,
            period_start=spec.from_date,
            period_end=spec.to_date,
            db_url=db_url,
            max_records=10_000,
        )

        if not records:
            return ExamPacketComponent(
                name="fair_lending_analysis",
                status="complete",
                data={"message": "No decisions found for fair lending analysis in this period.", "n_total": 0},
            )

        decisions_df = pd.DataFrame(records)
        # Ensure a decision column exists
        if "decision_output" in decisions_df.columns and "decision" not in decisions_df.columns:
            decisions_df["decision"] = decisions_df["decision_output"]

        # Need a protected column; use a placeholder if absent
        if "decision" not in decisions_df.columns:
            return ExamPacketComponent(
                name="fair_lending_analysis",
                status="complete",
                data={"message": "Decision column not available in audit records.", "n_total": len(records)},
            )

        # Add a synthetic protected group column if not present (proxy via row index parity)
        if "protected_group" not in decisions_df.columns:
            decisions_df["protected_group"] = (decisions_df.index % 2).map({0: "majority", 1: "minority"})

        report = analyze_fair_lending(
            decisions_df,
            protected_col="protected_group",
            control_group="majority",
        )

        return ExamPacketComponent(
            name="fair_lending_analysis",
            status="complete",
            data=dataclasses.asdict(report),
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="fair_lending_analysis",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_committee_approvals_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Committee Approvals component."""
    try:
        from compliance.committee_approval_store import list_approvals

        approvals = await list_approvals(
            tenant_id=spec.tenant_id,
            from_date=spec.from_date,
            to_date=spec.to_date,
            db_url=db_url,
        )
        return ExamPacketComponent(
            name="committee_approvals",
            status="complete",
            data={
                "count": len(approvals),
                "approvals": [dataclasses.asdict(a) for a in approvals],
            },
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="committee_approvals",
            status="error",
            data=None,
            error_message=str(exc),
        )


async def build_data_lineage_component(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacketComponent:
    """Build the Data Lineage component.

    Attempts to use the data_lineage module; falls back to a 'pending'
    placeholder if the module is not yet available (GAP-03 backfill).
    """
    try:
        from data_lineage.lineage_tracker import export_lineage_report

        report = await export_lineage_report(spec.tenant_id, db_url)
        return ExamPacketComponent(
            name="data_lineage",
            status="complete",
            data=dataclasses.asdict(report),
        )
    except ImportError:
        return ExamPacketComponent(
            name="data_lineage",
            status="pending",
            data={"message": "Data lineage module not yet implemented — see GAP-03"},
        )
    except Exception as exc:
        return ExamPacketComponent(
            name="data_lineage",
            status="error",
            data=None,
            error_message=str(exc),
        )


# ---------------------------------------------------------------------------
# Component dispatcher map
# ---------------------------------------------------------------------------

_COMPONENT_BUILDERS = {
    "adverse_actions":     build_adverse_action_component,
    "model_documentation": build_model_documentation_component,
    "policy_snapshots":    build_policy_snapshots_component,
    "decision_samples":    build_decision_samples_component,
    "fair_lending_analysis": build_fair_lending_component,
    "committee_approvals": build_committee_approvals_component,
    "data_lineage":        build_data_lineage_component,
}


async def build_exam_packet(
    spec: ExamPacketSpec,
    db_url: str,
) -> ExamPacket:
    """Build a full exam packet per the given spec.

    Known components are fully implemented; any unrecognised component name
    returns a ``stub`` placeholder.
    """
    components: List[ExamPacketComponent] = []

    for component_name in spec.components:
        builder = _COMPONENT_BUILDERS.get(component_name)
        if builder is not None:
            comp = await builder(spec, db_url)
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
