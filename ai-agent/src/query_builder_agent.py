"""
query_builder_agent.py — Prompt 20-B (GAP-20)
Wraps LLM-generated SQL with schema context injection, tenant-id injection,
and DB dry-run validation.
PRD §4.6.4 (mandatory schema injection + dry-run)
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import create_engine, text as _sa_text
from sqlalchemy.ext.asyncio import create_async_engine

from analytics_api.src.semantic_layer import GlossaryEntry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class QueryCandidate(BaseModel):
    sql: str
    injected_tenant_id: str
    schema_context_used: list[str]    # names of GlossaryEntries used in prompt
    dry_run_passed: bool
    dry_run_error: Optional[str]


class QueryBuildError(Exception):
    """Raised when QueryBuilderAgent.build() fails dry-run validation."""

    def __init__(self, message: str, dry_run_output: str) -> None:
        super().__init__(message)
        self.dry_run_output = dry_run_output


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class QueryBuilderAgent:
    """Validates and enriches LLM-generated SQL before execution."""

    def __init__(self, db_url: str, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self._db_url = db_url
        # Build a dedicated read-only sync engine for dry-runs
        self._sync_url = self._to_sync_url(db_url)
        self._engine = create_engine(self._sync_url, echo=False, pool_pre_ping=False)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_sync_url(url: str) -> str:
        if "://" not in url:
            return f"sqlite:///{url}"
        return (
            url
            .replace("sqlite+aiosqlite:///", "sqlite:///")
            .replace("postgresql+asyncpg://", "postgresql://")
        )

    @staticmethod
    def _to_async_url(url: str) -> str:
        if "://" not in url:
            return f"sqlite+aiosqlite:///{url}"
        if url.startswith("sqlite:///") and not url.startswith("sqlite+"):
            return "sqlite+aiosqlite" + url[6:]
        return url

    def _dialect(self) -> str:
        """Return the DB dialect name (sqlite, postgresql, bigquery)."""
        try:
            return self._engine.dialect.name
        except Exception:
            return "sqlite"

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def inject_schema_context(
        self,
        base_prompt: str,
        registry_entries: list[GlossaryEntry],
    ) -> str:
        """Append a schema context block to base_prompt."""
        lines = [
            "",
            "--- SCHEMA CONTEXT ---",
            "Available metrics and terms:",
        ]
        for entry in registry_entries:
            line = f"  - {entry.name}: {entry.definition}"
            if entry.sql_expression:
                line += f"  [SQL: {entry.sql_expression}]"
            lines.append(line)
        lines.append(f"Tenant ID filter: All queries MUST include WHERE tenant_id = '{self.tenant_id}'")
        lines.append("----------------------")
        return base_prompt + "\n".join(lines)

    def inject_tenant_id(self, sql: str) -> str:
        """
        Inject WHERE tenant_id = '<tenant_id>' into the SQL if not already present.
        Uses simple string manipulation (TODO: replace with sqlglot for complex queries).
        """
        # If tenant_id already in SQL, return unchanged
        if "tenant_id" in sql.lower():
            return sql

        # Check for existing WHERE clause (case-insensitive)
        where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
        from_match = re.search(r'\bFROM\b', sql, re.IGNORECASE)

        tid_clause = f"tenant_id = '{self.tenant_id}'"

        if where_match:
            # Append to existing WHERE clause
            pos = where_match.end()
            return sql[:pos] + f" {tid_clause} AND" + sql[pos:]
        elif from_match:
            # Find end of FROM clause to insert WHERE
            # Append WHERE before GROUP BY / ORDER BY / LIMIT / end
            insert_keywords = re.search(
                r'\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|UNION|EXCEPT|INTERSECT)\b',
                sql, re.IGNORECASE,
            )
            if insert_keywords:
                pos = insert_keywords.start()
                return sql[:pos].rstrip() + f" WHERE {tid_clause} " + sql[pos:]
            else:
                return sql.rstrip() + f" WHERE {tid_clause}"
        else:
            return sql

    async def dry_run(self, sql: str) -> tuple[bool, Optional[str]]:
        """
        Validate SQL via EXPLAIN (SQLite/PostgreSQL) or LIMIT 0 (BigQuery).
        Returns (passed, error_message).
        """
        dialect = self._dialect()

        if dialect == "bigquery":
            dry_sql = f"SELECT * FROM ({sql}) AS _dry_run LIMIT 0"
        else:
            dry_sql = "EXPLAIN " + sql

        try:
            # Run synchronously in a thread-safe way (dry-run engine is sync)
            with self._engine.connect() as conn:
                conn.execute(_sa_text(dry_sql))
            return True, None
        except Exception as exc:
            return False, str(exc)

    async def build(
        self,
        raw_sql: str,
        registry_entries: list[GlossaryEntry],
    ) -> QueryCandidate:
        """
        1. Inject tenant_id.
        2. Dry-run the SQL.
        3. Raise QueryBuildError on failure.
        4. Return QueryCandidate.
        """
        injected_sql = self.inject_tenant_id(raw_sql)
        passed, error = await self.dry_run(injected_sql)

        if not passed:
            raise QueryBuildError(
                f"SQL dry-run failed: {error}",
                dry_run_output=error or "",
            )

        schema_context_used = [e.name for e in registry_entries]
        return QueryCandidate(
            sql=injected_sql,
            injected_tenant_id=self.tenant_id,
            schema_context_used=schema_context_used,
            dry_run_passed=True,
            dry_run_error=None,
        )
