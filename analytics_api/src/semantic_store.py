"""
semantic_store.py — Prompt 19-B (GAP-19)
Append-only persistence for the tenant_semantic_registry table.
Supports four-eyes approval workflow for TABLE_SCHEMA entries.
PRD §4.7.3 (SEM-003, SEM-006)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text as _sa_text
from sqlalchemy.exc import IntegrityError as SAIntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from analytics_api.src.semantic_layer import EntryKind, GlossaryEntry, SemanticRegistry

# ---------------------------------------------------------------------------
# Engine cache (same pattern as ai_audit_log.py)
# ---------------------------------------------------------------------------
_ENGINE_CACHE: dict[str, AsyncEngine] = {}
_SCHEMA_DONE: set[str] = set()


def _normalize_url(url: str) -> str:
    if not url:
        raise ValueError("db_url must not be empty.")
    if "://" not in url:
        return f"sqlite+aiosqlite:///{url}"
    if url.startswith("sqlite:///") and not url.startswith("sqlite+"):
        return "sqlite+aiosqlite" + url[6:]
    return url


def _get_engine(db_url: str) -> AsyncEngine:
    norm = _normalize_url(db_url)
    if norm not in _ENGINE_CACHE:
        _ENGINE_CACHE[norm] = create_async_engine(norm, echo=False)
    return _ENGINE_CACHE[norm]


_CREATE_SEMANTIC_TABLE = """
CREATE TABLE IF NOT EXISTS tenant_semantic_registry (
    entry_id           TEXT    PRIMARY KEY,
    kind               TEXT    NOT NULL,
    name               TEXT    NOT NULL,
    tenant_id          TEXT,
    definition         TEXT    NOT NULL,
    sql_expression     TEXT,
    columns            TEXT,
    sha256             TEXT    NOT NULL,
    version            INTEGER NOT NULL DEFAULT 1,
    created_at         TEXT    NOT NULL,
    approved           INTEGER NOT NULL DEFAULT 0,
    approved_by        TEXT,
    approved_at        TEXT,
    second_approver    TEXT,
    second_approved_at TEXT
)
"""

_CREATE_UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS uq_semantic_name_tenant
    ON tenant_semantic_registry (name, tenant_id)
"""

_MIGRATION_STMTS = [
    "ALTER TABLE tenant_semantic_registry ADD COLUMN second_approver TEXT",
    "ALTER TABLE tenant_semantic_registry ADD COLUMN second_approved_at TEXT",
]


async def _ensure_schema(db_url: str) -> None:
    norm = _normalize_url(db_url)
    if norm in _SCHEMA_DONE:
        return
    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(_sa_text(_CREATE_SEMANTIC_TABLE))
        await conn.execute(_sa_text(_CREATE_UNIQUE_INDEX))
        for stmt in _MIGRATION_STMTS:
            try:
                await conn.execute(_sa_text(stmt))
            except Exception:
                pass  # Column already exists
    _SCHEMA_DONE.add(norm)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_entry(row: dict) -> GlossaryEntry:
    """Deserialise a DB row into a GlossaryEntry."""
    cols_raw = row.get("columns")
    columns = json.loads(cols_raw) if cols_raw else None
    return GlossaryEntry(
        entry_id=row["entry_id"],
        kind=EntryKind(row["kind"]),
        name=row["name"],
        tenant_id=row["tenant_id"],
        definition=row["definition"],
        sql_expression=row.get("sql_expression"),
        columns=columns,
        sha256=row["sha256"],
        version=row.get("version", 1),
        created_at=datetime.fromisoformat(row["created_at"]),
        approved=bool(row["approved"]),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------

# Module-level db_url used by standalone callers; can be overridden via _set_db_url()
_DB_URL: str = ""


def _set_db_url(url: str) -> None:
    """Configure the default DB URL for the semantic store."""
    global _DB_URL
    _DB_URL = url


async def insert_entry(entry: GlossaryEntry, db_session) -> GlossaryEntry:
    """
    Insert a new GlossaryEntry into tenant_semantic_registry.
    Auto-sets approved=True for TERM and METRIC; False for TABLE_SCHEMA.
    Computes sha256 via SemanticRegistry.compute_entry_hash().
    """
    # Determine approval status
    kind_val = entry.kind if isinstance(entry.kind, str) else entry.kind.value
    is_auto_approved = kind_val in (EntryKind.TERM.value, EntryKind.METRIC.value)

    # Build the canonical entry with computed hash
    entry_id = entry.entry_id if entry.entry_id else str(uuid.uuid4())
    created_at = entry.created_at if entry.created_at else datetime.now(timezone.utc)

    # Create a copy with set fields for hashing
    working = entry.model_copy(update={
        "entry_id": entry_id,
        "created_at": created_at,
        "approved": is_auto_approved,
    })
    sha = SemanticRegistry.compute_entry_hash(working)
    working = working.model_copy(update={"sha256": sha})

    columns_json = json.dumps(sorted(working.columns)) if working.columns else None

    db_url = _DB_URL
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        try:
            await conn.execute(
                _sa_text("""
                    INSERT INTO tenant_semantic_registry
                    (entry_id, kind, name, tenant_id, definition, sql_expression,
                     columns, sha256, version, created_at, approved)
                    VALUES
                    (:entry_id, :kind, :name, :tenant_id, :definition, :sql_expression,
                     :columns, :sha256, :version, :created_at, :approved)
                """),
                {
                    "entry_id": working.entry_id,
                    "kind": kind_val,
                    "name": working.name,
                    "tenant_id": working.tenant_id,
                    "definition": working.definition,
                    "sql_expression": working.sql_expression,
                    "columns": columns_json,
                    "sha256": sha,
                    "version": working.version,
                    "created_at": created_at.isoformat(),
                    "approved": 1 if is_auto_approved else 0,
                },
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "unique" in msg or "constraint" in msg or "duplicate" in msg:
                raise ValueError(
                    f"Entry with name='{working.name}' and tenant_id='{working.tenant_id}' already exists."
                ) from exc
            raise

    return working


async def get_entries(
    tenant_id: str,
    db_session,
    kind: Optional[EntryKind] = None,
) -> list[GlossaryEntry]:
    """
    Return all APPROVED entries for tenant_id plus all APPROVED platform entries.
    Never returns entries for other tenants.
    Verifies sha256 integrity on read.
    """
    db_url = _DB_URL
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    params: dict = {"tenant_id": tenant_id}
    kind_clause = ""
    if kind is not None:
        kind_val = kind if isinstance(kind, str) else kind.value
        kind_clause = " AND kind = :kind"
        params["kind"] = kind_val

    query = f"""
        SELECT * FROM tenant_semantic_registry
        WHERE approved = 1
          AND (tenant_id = :tenant_id OR tenant_id IS NULL)
          {kind_clause}
        ORDER BY created_at ASC
    """

    async with engine.connect() as conn:
        result = await conn.execute(_sa_text(query), params)
        rows = result.mappings().all()

    entries: list[GlossaryEntry] = []
    for row in rows:
        entry = _row_to_entry(dict(row))
        # Integrity check: recompute hash and compare
        recomputed = SemanticRegistry.compute_entry_hash(entry)
        if recomputed != entry.sha256:
            raise SAIntegrityError(
                statement=None,
                params=None,
                orig=ValueError(
                    f"SHA-256 mismatch for entry_id='{entry.entry_id}': "
                    f"stored={entry.sha256}, computed={recomputed}"
                ),
            )
        entries.append(entry)

    return entries


async def approve_entry(
    entry_id: str,
    approver: str,
    second_approver: str,
    db_session,
) -> GlossaryEntry:
    """
    Four-eyes approval for TABLE_SCHEMA entries.
    Raises ValueError if approver == second_approver.
    Raises LookupError if entry_id not found.
    Raises ValueError for non-TABLE_SCHEMA entries.
    """
    if approver == second_approver:
        raise ValueError("approver and second_approver must be different people (four-eyes requirement).")

    db_url = _DB_URL
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        result = await conn.execute(
            _sa_text("SELECT * FROM tenant_semantic_registry WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        row = result.mappings().fetchone()
        if row is None:
            raise LookupError(f"Entry '{entry_id}' not found.")

        row_dict = dict(row)
        if row_dict["kind"] != EntryKind.TABLE_SCHEMA.value:
            raise ValueError(
                f"approve_entry() is only valid for TABLE_SCHEMA entries; "
                f"got kind='{row_dict['kind']}'."
            )

        now = _now_iso()
        await conn.execute(
            _sa_text("""
                UPDATE tenant_semantic_registry
                SET approved = 1,
                    approved_by = :approver,
                    approved_at = :approved_at,
                    second_approver = :second_approver,
                    second_approved_at = :second_approved_at
                WHERE entry_id = :eid
            """),
            {
                "approver": approver,
                "approved_at": now,
                "second_approver": second_approver,
                "second_approved_at": now,
                "eid": entry_id,
            },
        )

        # Re-read updated row
        result2 = await conn.execute(
            _sa_text("SELECT * FROM tenant_semantic_registry WHERE entry_id = :eid"),
            {"eid": entry_id},
        )
        updated = result2.mappings().fetchone()

    return _row_to_entry(dict(updated))


async def get_pending_approvals(tenant_id: str, db_session) -> list[GlossaryEntry]:
    """Return TABLE_SCHEMA entries with approved=0 for the given tenant."""
    db_url = _DB_URL
    await _ensure_schema(db_url)
    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        result = await conn.execute(
            _sa_text("""
                SELECT * FROM tenant_semantic_registry
                WHERE approved = 0
                  AND kind = :kind
                  AND tenant_id = :tenant_id
                ORDER BY created_at ASC
            """),
            {"kind": EntryKind.TABLE_SCHEMA.value, "tenant_id": tenant_id},
        )
        rows = result.mappings().all()

    return [_row_to_entry(dict(r)) for r in rows]
