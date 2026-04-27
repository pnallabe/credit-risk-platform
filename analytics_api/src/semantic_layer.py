"""
semantic_layer.py — Prompt 19-A (GAP-19)
Tenant-Scoped Semantic Layer: platform metric definitions, enum harvesting from
data_contracts/, per-tenant glossary, two-tier resolution, SHA-256 tamper
detection, and schema drift detection.
PRD §4.7, §5.1–5.2 (Layer 1)
"""
from __future__ import annotations

import enum
import hashlib
import importlib
import json
import pkgutil
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Enums & Data Models
# ---------------------------------------------------------------------------

class EntryKind(str, enum.Enum):
    METRIC = "metric"
    TERM = "term"
    TABLE_SCHEMA = "table_schema"


class GlossaryEntry(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    entry_id: str
    kind: EntryKind
    name: str
    tenant_id: Optional[str]       # None = platform-level entry
    definition: str
    sql_expression: Optional[str] = None   # For metrics
    columns: Optional[list[str]] = None   # For table_schema entries
    sha256: str
    version: int = 1
    created_at: datetime
    approved: bool                 # Four-eyes required for table_schema entries


class PlatformMetric(BaseModel):
    name: str
    definition: str
    sql_expression: str


class TwoTierResolutionResult(BaseModel):
    resolved_entry: GlossaryEntry
    source: Literal["tenant", "platform"]
    tenant_id: Optional[str]


# ---------------------------------------------------------------------------
# Platform Metrics (9 named metrics per PRD)
# ---------------------------------------------------------------------------

PLATFORM_METRICS: dict[str, PlatformMetric] = {
    "approval_rate": PlatformMetric(
        name="approval_rate",
        definition="Percentage of loan applications approved in the period",
        sql_expression="COUNTIF(decision='APPROVED') / COUNT(*)",
    ),
    "charge_off_rate": PlatformMetric(
        name="charge_off_rate",
        definition="Percentage of outstanding balances charged off in the period",
        sql_expression="SUM(charge_off_amount) / SUM(outstanding_balance)",
    ),
    "expected_loss": PlatformMetric(
        name="expected_loss",
        definition="Probability of default multiplied by loss given default multiplied by exposure at default",
        sql_expression="SUM(pd * lgd * ead)",
    ),
    "dir_score": PlatformMetric(
        name="dir_score",
        definition="Disparity Impact Ratio — approval rate for protected class divided by approval rate for control class",
        sql_expression=(
            "SAFE_DIVIDE("
            "COUNTIF(decision='APPROVED' AND protected_class=1) / COUNTIF(protected_class=1), "
            "COUNTIF(decision='APPROVED' AND protected_class=0) / COUNTIF(protected_class=0)"
            ")"
        ),
    ),
    "model_gini": PlatformMetric(
        name="model_gini",
        definition="Gini coefficient of the credit scoring model on the evaluation window",
        sql_expression="2 * AUC - 1",
    ),
    "portfolio_yield": PlatformMetric(
        name="portfolio_yield",
        definition="Interest income divided by average outstanding balance",
        sql_expression="SUM(interest_income) / AVG(outstanding_balance)",
    ),
    "vintage_dpd30": PlatformMetric(
        name="vintage_dpd30",
        definition="Percentage of loans in a vintage cohort that have gone 30+ DPD",
        sql_expression="COUNTIF(dpd >= 30) / COUNT(*)",
    ),
    "concentration_hhi": PlatformMetric(
        name="concentration_hhi",
        definition="Herfindahl-Hirschman Index of industry segment concentration",
        sql_expression="SUM(POWER(segment_share, 2))",
    ),
    "roll_rate": PlatformMetric(
        name="roll_rate",
        definition="Percentage of current accounts that roll into the next delinquency bucket in the next period",
        sql_expression="COUNTIF(next_bucket > current_bucket) / COUNTIF(current_bucket < 5)",
    ),
}


# ---------------------------------------------------------------------------
# Platform Glossary Harvesting (from data_contracts/ enums)
# ---------------------------------------------------------------------------

def harvest_platform_glossary() -> list[GlossaryEntry]:
    """Harvest platform glossary terms by scanning data_contracts/ for enum members."""
    entries: list[GlossaryEntry] = []
    _now = datetime.now(timezone.utc)

    try:
        import data_contracts as _dc_root
        package_path = getattr(_dc_root, "__path__", None)
        if package_path is None:
            return entries

        # Walk all modules under data_contracts
        modules_to_scan: list[Any] = [_dc_root]
        for _importer, modname, _ispkg in pkgutil.walk_packages(
            path=package_path,
            prefix=_dc_root.__name__ + ".",
            onerror=lambda _: None,
        ):
            try:
                mod = importlib.import_module(modname)
                modules_to_scan.append(mod)
            except Exception:
                continue

        seen: set[str] = set()
        for mod in modules_to_scan:
            for attr_name in dir(mod):
                try:
                    attr = getattr(mod, attr_name)
                except Exception:
                    continue
                if (
                    isinstance(attr, type)
                    and issubclass(attr, enum.Enum)
                    and attr is not enum.Enum
                ):
                    for member in attr:
                        entry_name = f"{attr.__name__}.{member.name}"
                        if entry_name in seen:
                            continue
                        seen.add(entry_name)
                        entry_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, entry_name))
                        stub = GlossaryEntry(
                            entry_id=entry_id,
                            kind=EntryKind.TERM,
                            name=entry_name,
                            tenant_id=None,
                            definition=str(member.value),
                            sql_expression=None,
                            columns=None,
                            sha256="__placeholder__",
                            version=1,
                            created_at=_now,
                            approved=True,
                        )
                        sha = SemanticRegistry.compute_entry_hash(stub)
                        entries.append(stub.model_copy(update={"sha256": sha}))
    except Exception:
        pass  # Degrade gracefully if data_contracts is absent

    return entries


# ---------------------------------------------------------------------------
# SemanticRegistry
# ---------------------------------------------------------------------------

class SemanticRegistry:
    """Two-tier semantic registry: tenant entries win over platform defaults."""

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self._platform_entries: dict[str, GlossaryEntry] = {}
        self._tenant_entries: dict[str, GlossaryEntry] = {}

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    async def load(cls, tenant_id: str, db_session: Any) -> "SemanticRegistry":
        """Load platform glossary + tenant entries from DB via semantic_store."""
        registry = cls(tenant_id)

        # Seed platform metrics as GlossaryEntries
        _now = datetime.now(timezone.utc)
        for metric in PLATFORM_METRICS.values():
            stub = GlossaryEntry(
                entry_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"platform.metric.{metric.name}")),
                kind=EntryKind.METRIC,
                name=metric.name,
                tenant_id=None,
                definition=metric.definition,
                sql_expression=metric.sql_expression,
                columns=None,
                sha256="__placeholder__",
                version=1,
                created_at=_now,
                approved=True,
            )
            sha = cls.compute_entry_hash(stub)
            entry = stub.model_copy(update={"sha256": sha})
            registry._platform_entries[metric.name] = entry

        # Harvest data_contracts enums
        for harvested in harvest_platform_glossary():
            registry._platform_entries[harvested.name] = harvested

        # Load tenant entries from DB
        try:
            from analytics_api.src.semantic_store import get_entries
            tenant_db_entries = await get_entries(tenant_id, db_session)
            for entry in tenant_db_entries:
                if entry.tenant_id is None:
                    registry._platform_entries[entry.name] = entry
                else:
                    registry._tenant_entries[entry.name] = entry
        except Exception:
            pass  # DB unavailable — fall back to platform-only glossary

        return registry

    @classmethod
    def build_platform_only(cls, tenant_id: str = "platform") -> "SemanticRegistry":
        """Synchronously build a platform-only registry without a DB connection.

        Seeds ``PLATFORM_METRICS`` and harvests ``data_contracts/`` enums — the
        same two steps that ``load()`` performs before touching the database.
        Suitable for use at server startup or in sync contexts where the async
        ``load()`` cannot be awaited.  Tenant-level overrides stored in the DB
        are *not* included; call ``load()`` inside an async request handler for
        full two-tier resolution.
        """
        registry = cls(tenant_id)
        _now = datetime.now(timezone.utc)

        # Seed named platform metrics
        for metric in PLATFORM_METRICS.values():
            stub = GlossaryEntry(
                entry_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"platform.metric.{metric.name}")),
                kind=EntryKind.METRIC,
                name=metric.name,
                tenant_id=None,
                definition=metric.definition,
                sql_expression=metric.sql_expression,
                columns=None,
                sha256="__placeholder__",
                version=1,
                created_at=_now,
                approved=True,
            )
            sha = cls.compute_entry_hash(stub)
            registry._platform_entries[metric.name] = stub.model_copy(update={"sha256": sha})

        # Harvest enum values from data_contracts/
        for harvested in harvest_platform_glossary():
            registry._platform_entries[harvested.name] = harvested

        return registry

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    def resolve(self, name: str) -> TwoTierResolutionResult:
        """Tenant entry wins over platform if both exist. Raises KeyError if neither found."""
        if name in self._tenant_entries:
            return TwoTierResolutionResult(
                resolved_entry=self._tenant_entries[name],
                source="tenant",
                tenant_id=self.tenant_id,
            )
        if name in self._platform_entries:
            return TwoTierResolutionResult(
                resolved_entry=self._platform_entries[name],
                source="platform",
                tenant_id=None,
            )
        raise KeyError(f"Semantic entry '{name}' not found for tenant '{self.tenant_id}'")

    def resolve_all(self) -> list[TwoTierResolutionResult]:
        """Return merged view: all platform entries + all tenant entries (tenant wins on conflict)."""
        results: dict[str, TwoTierResolutionResult] = {}
        for name, entry in self._platform_entries.items():
            results[name] = TwoTierResolutionResult(
                resolved_entry=entry,
                source="platform",
                tenant_id=None,
            )
        for name, entry in self._tenant_entries.items():
            results[name] = TwoTierResolutionResult(
                resolved_entry=entry,
                source="tenant",
                tenant_id=self.tenant_id,
            )
        return list(results.values())

    # ------------------------------------------------------------------
    # Hash utilities
    # ------------------------------------------------------------------
    @staticmethod
    def compute_entry_hash(entry: GlossaryEntry) -> str:
        """SHA-256 of canonical JSON of key fields (deterministic)."""
        payload: dict[str, Any] = {
            "kind": entry.kind if isinstance(entry.kind, str) else entry.kind.value,
            "name": entry.name,
            "tenant_id": entry.tenant_id,
            "definition": entry.definition,
            "sql_expression": entry.sql_expression,
            "columns": sorted(entry.columns) if entry.columns else None,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Schema Drift Detection
# ---------------------------------------------------------------------------

async def check_schema_drift(
    registered_entry: GlossaryEntry,
    live_columns: list[str],
) -> tuple[bool, str, str]:
    """
    Compare SHA-256 of sorted registered columns vs sorted live_columns.
    Returns (drift_detected, registered_hash, live_hash).
    """
    registered_cols = sorted(registered_entry.columns or [])
    live_cols = sorted(live_columns)

    registered_hash = hashlib.sha256(
        json.dumps(registered_cols, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    live_hash = hashlib.sha256(
        json.dumps(live_cols, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    drift_detected = registered_hash != live_hash
    return drift_detected, registered_hash, live_hash
