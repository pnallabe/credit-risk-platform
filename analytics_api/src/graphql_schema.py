"""
graphql_schema.py — Prompt 24-A (GAP-24)
GraphQL Analytics API backed by the same data sources as the REST endpoints.

PRD Reference: §10.1

Mount point: /graphql (wired in analytics_api/src/main.py)

TODO: Add JWT authentication middleware in v2. The endpoint is currently unauthenticated.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import List, Optional

import strawberry
from strawberry.fastapi import GraphQLRouter

# Make project root importable
ROOT = Path(__file__).parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Strawberry types
# ---------------------------------------------------------------------------


@strawberry.type
class PortfolioSummary:
    total_applications: int
    approval_rate: float
    average_credit_score: float
    charge_off_rate: float
    tenant_id: str


@strawberry.type
class VintageCurvePoint:
    cohort_month: str
    dpd30_rate: float
    dpd60_rate: float
    dpd90_rate: float
    loan_count: int


@strawberry.type
class RollRateCell:
    from_bucket: str
    to_bucket: str
    rate: float


@strawberry.type
class GlossaryTermGQL:
    name: str
    definition: str
    kind: str
    tenant_id: Optional[str]
    approved: bool


@strawberry.type
class AgentInsight:
    query_id: str
    session_id: str
    answer_text: str
    confidence: str
    created_at: str


# ---------------------------------------------------------------------------
# Helper: access the shared _backend and _load_sql from main module
# ---------------------------------------------------------------------------


def _get_backend():
    """Return the shared _QueryBackend instance from analytics_api.src.main."""
    try:
        from analytics_api.src.main import _backend, _load_sql, DATABASE_URL
        return _backend, _load_sql, DATABASE_URL
    except Exception:
        return None, None, None


# ---------------------------------------------------------------------------
# Query resolvers
# ---------------------------------------------------------------------------


@strawberry.type
class Query:

    @strawberry.field
    async def portfolio_summary(
        self,
        tenant_id: str,
        info: strawberry.types.Info,
    ) -> PortfolioSummary:
        """
        Return a portfolio summary for *tenant_id* using data from the audit DB.
        Reuses the same SQLite/BigQuery backend as the REST endpoints.
        """
        try:
            backend, _load_sql, db_url = _get_backend()
            if backend is None:
                raise RuntimeError("backend unavailable")

            # Simple aggregation query — works on both SQLite and BigQuery
            sql = (
                "SELECT "
                "  COUNT(*) AS total_applications, "
                "  CAST(SUM(CASE WHEN decision='APPROVED' THEN 1 ELSE 0 END) AS FLOAT) / "
                "    NULLIF(COUNT(*), 0) AS approval_rate, "
                "  AVG(credit_score) AS average_credit_score "
                "FROM credit_decisions "
                "WHERE tenant_id = @tenant_id"
            )
            rows = backend.run_sql(sql, {"tenant_id": tenant_id})
            row = rows[0] if rows else {}
        except Exception as exc:
            logger.warning("portfolio_summary resolver failed: %s", exc)
            row = {}

        return PortfolioSummary(
            total_applications=int(row.get("total_applications") or 0),
            approval_rate=float(row.get("approval_rate") or 0.0),
            average_credit_score=float(row.get("average_credit_score") or 0.0),
            charge_off_rate=0.0,  # TODO: compute from charge_off_events table
            tenant_id=tenant_id,
        )

    @strawberry.field
    async def vintage_curves(
        self,
        tenant_id: str,
        cohort_start: Optional[str] = None,
        info: strawberry.types.Info = strawberry.UNSET,
    ) -> List[VintageCurvePoint]:
        """
        Reuse the same query logic as GET /v1/analytics/vintage-curves.
        Returns an empty list if the underlying query fails (graceful degradation).
        """
        try:
            backend, _load_sql_fn, db_url = _get_backend()
            if backend is None or _load_sql_fn is None:
                return []

            sql = _load_sql_fn("cohort_vintage_curves.sql")
            params = {
                "tenant_id": tenant_id,
                "months_back": 24,
                "page_size": 200,
                "page_offset": 0,
            }
            rows = backend.run_sql(sql, params)
        except Exception as exc:
            logger.warning("vintage_curves resolver failed: %s", exc)
            return []

        result = []
        for r in rows:
            try:
                result.append(
                    VintageCurvePoint(
                        cohort_month=str(r.get("origination_month") or ""),
                        dpd30_rate=float(r.get("cumulative_default_rate") or 0.0),
                        dpd60_rate=float(r.get("net_loss_rate") or 0.0),
                        dpd90_rate=float(r.get("decline_rate") or 0.0),
                        loan_count=int(r.get("cohort_count") or 0),
                    )
                )
            except Exception:
                continue
        return result

    @strawberry.field
    async def roll_rates(
        self,
        tenant_id: str,
        info: strawberry.types.Info,
    ) -> List[RollRateCell]:
        """
        Reuse the same query logic as GET /v1/analytics/roll-rates.
        Returns an empty list if the underlying query fails (graceful degradation).
        """
        try:
            backend, _load_sql_fn, db_url = _get_backend()
            if backend is None or _load_sql_fn is None:
                return []

            from datetime import date
            sql = _load_sql_fn("roll_rates_delinquency.sql")
            params = {
                "tenant_id": tenant_id,
                "as_of_date": date.today().isoformat(),
                "months_back": 12,
                "page_size": 200,
                "page_offset": 0,
            }
            rows = backend.run_sql(sql, params)
        except Exception as exc:
            logger.warning("roll_rates resolver failed: %s", exc)
            return []

        result = []
        for r in rows:
            try:
                result.append(
                    RollRateCell(
                        from_bucket=str(r.get("dpd_bucket") or ""),
                        to_bucket=str(r.get("pd_band") or ""),
                        rate=float(r.get("roll_rate_to_next_bucket") or 0.0),
                    )
                )
            except Exception:
                continue
        return result

    @strawberry.field
    async def semantic_glossary(
        self,
        tenant_id: str,
        info: strawberry.types.Info,
    ) -> List[GlossaryTermGQL]:
        """
        Load the merged semantic glossary for *tenant_id* from the SemanticRegistry.
        Returns an empty list if the semantic layer is not seeded (graceful degradation).
        """
        try:
            from analytics_api.src.semantic_layer import (
                SemanticRegistry,
                EntryKind,
            )

            registry = await SemanticRegistry.load(tenant_id, db_session=None)
            results = registry.resolve_all()
        except Exception as exc:
            logger.warning("semantic_glossary resolver failed: %s", exc)
            return []

        output = []
        for r in results:
            try:
                entry = r.resolved_entry
                output.append(
                    GlossaryTermGQL(
                        name=entry.name,
                        definition=entry.definition,
                        kind=entry.kind.value,
                        tenant_id=entry.tenant_id,
                        approved=entry.approved,
                    )
                )
            except Exception:
                continue
        return output

    @strawberry.field
    async def agent_insights(
        self,
        session_id: str,
        tenant_id: str,
        info: strawberry.types.Info,
    ) -> List[AgentInsight]:
        """
        Return AI agent audit records for the given session_id (scoped to tenant_id).
        Returns an empty list if the audit log is unavailable (graceful degradation).
        """
        try:
            from ai_agent.src.ai_audit_log import get_ai_audit_records

            records = await get_ai_audit_records(session_id, db_session=None)
        except Exception:
            # Try alternative import path
            try:
                sys.path.insert(0, str(ROOT / "ai-agent"))
                from src.ai_audit_log import get_ai_audit_records  # type: ignore[no-redef]

                records = await get_ai_audit_records(session_id, db_session=None)
            except Exception as exc:
                logger.warning("agent_insights resolver failed: %s", exc)
                return []

        output = []
        for rec in records:
            # Only return records that belong to this tenant
            if str(rec.get("tenant_id", "")) not in ("", tenant_id):
                continue
            try:
                output.append(
                    AgentInsight(
                        query_id=str(rec.get("query_id") or rec.get("id") or ""),
                        session_id=str(rec.get("session_id") or session_id),
                        answer_text=str(rec.get("answer_text") or ""),
                        confidence=str(rec.get("confidence_score") or ""),
                        created_at=str(rec.get("created_at") or ""),
                    )
                )
            except Exception:
                continue
        return output


# ---------------------------------------------------------------------------
# Schema + context injection
# ---------------------------------------------------------------------------

schema = strawberry.Schema(query=Query)


async def get_graphql_context() -> dict:
    """
    Inject context for resolvers.
    TODO: Inject authenticated DB session and tenant from JWT middleware in v2.
    """
    return {}


graphql_app = GraphQLRouter(schema, context_getter=get_graphql_context)
