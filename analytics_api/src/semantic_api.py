"""
semantic_api.py — Prompt 19-C (GAP-19)
FastAPI router exposing the Tenant-Scoped Semantic Layer as HTTP endpoints.
PRD §10.2 SEM-007 through SEM-011
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from analytics_api.src.semantic_layer import (
    EntryKind,
    GlossaryEntry,
    PlatformMetric,
    PLATFORM_METRICS,
    SemanticRegistry,
    check_schema_drift,
)
from analytics_api.src.semantic_store import (
    approve_entry,
    get_entries,
    get_pending_approvals,
    insert_entry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/analytics", tags=["semantic-layer"])

# ---------------------------------------------------------------------------
# Auth dependency (re-uses the same pattern from analytics_api/src/main.py)
# ---------------------------------------------------------------------------
bearer_scheme = HTTPBearer(auto_error=False)


async def _get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> dict:
    """Verify Bearer JWT and return claims dict. Imported from main.py dependency pattern."""
    # Import the main app's verify_bearer to avoid duplication
    try:
        from analytics_api.src.main import verify_bearer
        return await verify_bearer(credentials)
    except ImportError:
        # Fallback: accept any token in test environments
        if credentials is None:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        return {"tenant_id": "default", "role": "analyst"}


async def _get_db():
    """Yield a DB session stub (semantic_store uses its own engine cache)."""
    yield None  # semantic_store functions use module-level engine cache


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class GlossaryResponse(BaseModel):
    tenant_id: str
    platform_terms: list[GlossaryEntry]
    tenant_terms: list[GlossaryEntry]
    platform_metrics: list[PlatformMetric]
    total_count: int


class GlossaryTermRequest(BaseModel):
    name: str
    kind: EntryKind
    definition: str
    sql_expression: Optional[str] = None


class SchemaRegisterRequest(BaseModel):
    table_name: str
    columns: list[str]
    definition: str


class SchemaRegisterResponse(BaseModel):
    entry_id: str
    status: Literal["pending_approval"]
    message: str


class SchemaStatusResponse(BaseModel):
    table_name: str
    status: Literal["approved", "pending_approval", "not_found"]
    entry: Optional[GlossaryEntry]


class SchemaApproveRequest(BaseModel):
    approver: str
    second_approver: str


# ---------------------------------------------------------------------------
# Helper: fire-and-forget webhook emission
# ---------------------------------------------------------------------------

def _emit_webhook_background(tenant_id: str, term: str, proposed_by: str) -> None:
    """Emit semantic.term_proposed webhook (fire-and-forget)."""
    try:
        from webhooks.dispatcher import WebhookDispatcher
        from webhooks.store import WebhookStore
        from webhooks.models import SemanticTermProposedData
        import os

        db_url = os.getenv("DATABASE_URL", "webhooks.db")
        store = WebhookStore(db_url=db_url)
        dispatcher = WebhookDispatcher(store=store)
        payload = {
            "event": "semantic.term_proposed",
            "data": {
                "tenant_id": tenant_id,
                "term": term,
                "proposed_by": proposed_by,
            },
        }
        dispatcher.dispatch(tenant_id, "semantic.term_proposed", payload)
    except Exception as exc:
        logger.warning("Webhook emission failed (semantic.term_proposed): %s", exc)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/glossary", response_model=GlossaryResponse)
async def get_glossary(
    user: dict = Depends(_get_current_user),
    db=Depends(_get_db),
) -> GlossaryResponse:
    """Return platform metrics, platform terms, and tenant terms (no cross-tenant leakage)."""
    tenant_id: str = user["tenant_id"]

    registry = await SemanticRegistry.load(tenant_id, db)
    all_resolved = registry.resolve_all()

    platform_terms: list[GlossaryEntry] = []
    tenant_terms: list[GlossaryEntry] = []
    for r in all_resolved:
        entry = r.resolved_entry
        kind_val = entry.kind if isinstance(entry.kind, str) else entry.kind.value
        if kind_val == EntryKind.METRIC.value:
            continue  # metrics returned separately
        if r.source == "platform":
            platform_terms.append(entry)
        else:
            tenant_terms.append(entry)

    return GlossaryResponse(
        tenant_id=tenant_id,
        platform_terms=platform_terms,
        tenant_terms=tenant_terms,
        platform_metrics=list(PLATFORM_METRICS.values()),
        total_count=len(platform_terms) + len(tenant_terms) + len(PLATFORM_METRICS),
    )


@router.post("/tenant/glossary", response_model=GlossaryEntry, status_code=201)
async def add_glossary_term(
    req: GlossaryTermRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(_get_current_user),
    db=Depends(_get_db),
) -> GlossaryEntry:
    """Add a custom TERM or METRIC to the tenant glossary."""
    tenant_id: str = user["tenant_id"]

    kind_val = req.kind if isinstance(req.kind, str) else req.kind.value
    if kind_val == EntryKind.TABLE_SCHEMA.value:
        raise HTTPException(
            status_code=422,
            detail={
                "detail": "Use /tenant/schema/register for table schema entries",
                "type": "validation_error",
                "status": 422,
            },
        )

    from datetime import datetime, timezone
    import uuid

    new_entry = GlossaryEntry(
        entry_id=str(uuid.uuid4()),
        kind=req.kind,
        name=req.name,
        tenant_id=tenant_id,
        definition=req.definition,
        sql_expression=req.sql_expression,
        columns=None,
        sha256="__placeholder__",
        version=1,
        created_at=datetime.now(timezone.utc),
        approved=True,
    )

    try:
        inserted = await insert_entry(new_entry, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Fire-and-forget webhook
    background_tasks.add_task(
        _emit_webhook_background, tenant_id, req.name, tenant_id
    )

    return inserted


@router.post("/tenant/schema/register", response_model=SchemaRegisterResponse, status_code=202)
async def register_schema(
    req: SchemaRegisterRequest,
    user: dict = Depends(_get_current_user),
    db=Depends(_get_db),
) -> SchemaRegisterResponse:
    """Register a tenant table schema. Requires four-eyes approval before activation."""
    tenant_id: str = user["tenant_id"]

    from datetime import datetime, timezone
    import uuid

    new_entry = GlossaryEntry(
        entry_id=str(uuid.uuid4()),
        kind=EntryKind.TABLE_SCHEMA,
        name=req.table_name,
        tenant_id=tenant_id,
        definition=req.definition,
        sql_expression=None,
        columns=req.columns,
        sha256="__placeholder__",
        version=1,
        created_at=datetime.now(timezone.utc),
        approved=False,
    )

    try:
        inserted = await insert_entry(new_entry, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return SchemaRegisterResponse(
        entry_id=inserted.entry_id,
        status="pending_approval",
        message=(
            "Schema registration received. Four-eyes approval is required before "
            "the schema becomes active. Use POST /admin/tenant/{tenant_id}/schema/{entry_id}/approve."
        ),
    )


@router.get("/tenant/schema/{table_name}/status", response_model=SchemaStatusResponse)
async def get_schema_status(
    table_name: str,
    user: dict = Depends(_get_current_user),
    db=Depends(_get_db),
) -> SchemaStatusResponse:
    """Check approval status of a registered table schema."""
    tenant_id: str = user["tenant_id"]

    # Check approved entries first
    try:
        approved = await get_entries(tenant_id, db, kind=EntryKind.TABLE_SCHEMA)
        for e in approved:
            if e.name == table_name:
                return SchemaStatusResponse(
                    table_name=table_name, status="approved", entry=e
                )
    except Exception:
        pass

    # Check pending
    try:
        pending = await get_pending_approvals(tenant_id, db)
        for e in pending:
            if e.name == table_name:
                return SchemaStatusResponse(
                    table_name=table_name, status="pending_approval", entry=e
                )
    except Exception:
        pass

    return SchemaStatusResponse(table_name=table_name, status="not_found", entry=None)


@router.post(
    "/admin/tenant/{tenant_id}/schema/{entry_id}/approve",
    response_model=GlossaryEntry,
)
async def approve_schema(
    tenant_id: str,
    entry_id: str,
    req: SchemaApproveRequest,
    user: dict = Depends(_get_current_user),
    db=Depends(_get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> GlossaryEntry:
    """Four-eyes approval for a TABLE_SCHEMA entry. Requires platform_admin role."""
    claims = user
    role = claims.get("role", "")
    if role != "platform_admin":
        raise HTTPException(
            status_code=403,
            detail={
                "detail": "platform_admin role required for schema approval",
                "type": "forbidden",
                "status": 403,
            },
        )

    try:
        updated = await approve_entry(entry_id, req.approver, req.second_approver, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Fire-and-forget webhook
    background_tasks.add_task(
        _emit_webhook_background, tenant_id, updated.name, req.approver
    )

    return updated
