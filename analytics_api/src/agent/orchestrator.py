"""
orchestrator.py — DomainExpertAgent

The main entry point for the Semantic Intelligence pipeline.

10-stage pipeline for each question:
  1. IntentParser          — LLM extracts QueryIntent (~250 tokens)
  2. IntentNormalizer      — synonym resolution on the metric name
  3. SemanticResolver      — QueryIntent → ResolvedIntent (deterministic)
  4. ConstraintValidator   — validate filter values
  5. QueryPlanner          — ResolvedIntent → QueryPlan
  6. SQLGenerator          — QueryPlan → parameterized BQ SQL
  7. Validator pre-check   — block DML / schema-snooping
  8. BQ execution          — run SQL against BigQuery (or SQLite in dev)
  9. Validator post-check  — BusinessRuleEngine on result rows
 10. Explainer + Lineage   — format answer and record lineage trace

Returns an ``AgentResponse`` that can be sent directly as a FastAPI response.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from analytics_api.src.agent.config import AgentConfig
from analytics_api.src.agent.explainer import Explainer
from analytics_api.src.agent.intent_parser import IntentParser
from analytics_api.src.agent.models import QueryIntent
from analytics_api.src.agent.query_planner import QueryPlanner
from analytics_api.src.agent.semantic_resolver import SemanticResolver
from analytics_api.src.agent.sql_generator import SQLGenerator
from analytics_api.src.agent.validator import PreExecutionError, QueryValidator
from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
from analytics_api.src.domain_ontology.ontology_parser import get_ontology
from analytics_api.src.knowledge_graph.lineage_tracker import LineageTracker
from analytics_api.src.semantic.exceptions import SQLInjectionGuardError
from analytics_api.src.semantic.loader import get_loader

logger = logging.getLogger(__name__)

BQ_PROJECT = "ai-risk-workflow"


def _bq_type(value: Any) -> str:
    if isinstance(value, bool):
        return "BOOL"
    if isinstance(value, int):
        return "INT64"
    if isinstance(value, float):
        return "FLOAT64"
    if isinstance(value, date):
        return "DATE"
    return "STRING"


@dataclass
class AgentResponse:
    request_id: str
    question: str
    answer: str
    sql: Optional[str]
    rows: List[Dict[str, Any]]
    row_count: int
    metric: Optional[str]
    source: Optional[str]
    clarification_needed: bool
    clarification_reason: Optional[str]
    rule_violations: List[Dict[str, str]]
    execution_ms: int
    error: Optional[str] = None


class DomainExpertAgent:
    """Credit-risk domain expert agent.

    Example::

        agent = DomainExpertAgent()
        response = await agent.ask(
            question="What is the 90 DPD delinquency rate for personal loans?",
            tenant_id="tenant_abc",
        )
    """

    def __init__(self, config: Optional[AgentConfig] = None) -> None:
        self._config = config or AgentConfig()
        loader = get_loader()
        ontology = get_ontology()

        self._intent_parser = IntentParser(config=self._config, loader=loader)
        self._normalizer = IntentNormalizer(loader=loader, ontology=ontology)
        self._resolver = SemanticResolver(loader=loader, ontology=ontology)
        self._planner = QueryPlanner(loader=loader)
        self._sql_gen = SQLGenerator(loader=loader)
        self._validator = QueryValidator()
        self._explainer = Explainer()
        self._lineage = LineageTracker()

        # BQ client — lazy init
        self._bq_client: Optional[Any] = None
        self._use_bq: Optional[bool] = None

    async def ask(
        self,
        question: str,
        tenant_id: str = "default",
        request_id: Optional[str] = None,
        clarifications: Optional[Dict[str, Any]] = None,
    ) -> AgentResponse:
        """Run the full 10-stage pipeline and return an AgentResponse."""
        if request_id is None:
            request_id = str(uuid.uuid4())

        start_ms = int(time.time() * 1000)

        try:
            return await self._run_pipeline(
                question=question,
                tenant_id=tenant_id,
                request_id=request_id,
                clarifications=clarifications or {},
                start_ms=start_ms,
            )
        except Exception as exc:
            logger.exception("DomainExpertAgent: unhandled error for question %r", question)
            return AgentResponse(
                request_id=request_id,
                question=question,
                answer=f"An error occurred while processing your question: {exc}",
                sql=None,
                rows=[],
                row_count=0,
                metric=None,
                source=None,
                clarification_needed=False,
                clarification_reason=None,
                rule_violations=[],
                execution_ms=int(time.time() * 1000) - start_ms,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    async def _run_pipeline(
        self,
        question: str,
        tenant_id: str,
        request_id: str,
        clarifications: Dict[str, Any],
        start_ms: int,
    ) -> AgentResponse:
        # Stage 1 — LLM intent extraction
        intent: QueryIntent = await self._intent_parser.parse(question)

        # Apply any user-supplied clarifications to override intent fields
        if clarifications:
            if "product_type" in clarifications:
                intent.product_type = clarifications["product_type"]
            if "metric" in clarifications:
                intent.metric = clarifications["metric"]

        # Stage 2 — synonym resolution on metric name
        if intent.metric:
            norm = self._normalizer.normalize(intent.metric)
            if norm.metric_name:
                intent.metric = norm.metric_name

        # Stage 3 — semantic resolution
        resolved = self._resolver.resolve(intent)

        # Stage 4 — constraint violations → ask for clarification
        if resolved.clarification_needed:
            return AgentResponse(
                request_id=request_id,
                question=question,
                answer=f"Could you clarify your question? {resolved.clarification_reason}",
                sql=None,
                rows=[],
                row_count=0,
                metric=intent.metric,
                source=None,
                clarification_needed=True,
                clarification_reason=resolved.clarification_reason,
                rule_violations=[],
                execution_ms=int(time.time() * 1000) - start_ms,
            )

        if resolved.resolved_metric is None:
            return AgentResponse(
                request_id=request_id,
                question=question,
                answer=(
                    "I could not determine which metric you're asking about. "
                    "Try asking about: delinquency rate, charge-off rate, approval rate, "
                    "loan exposure, or utilization rate."
                ),
                sql=None,
                rows=[],
                row_count=0,
                metric=None,
                source=None,
                clarification_needed=True,
                clarification_reason="Metric not recognized",
                rule_violations=[],
                execution_ms=int(time.time() * 1000) - start_ms,
            )

        # Stage 5 — query planning
        plan = self._planner.plan(resolved)

        # Stage 6 — SQL generation
        try:
            sql, params = self._sql_gen.generate(plan)
        except SQLInjectionGuardError as exc:
            logger.error("SQLInjectionGuardError: %s", exc)
            return AgentResponse(
                request_id=request_id,
                question=question,
                answer="The query could not be generated safely and was blocked.",
                sql=None,
                rows=[],
                row_count=0,
                metric=intent.metric,
                source=None,
                clarification_needed=False,
                clarification_reason=None,
                rule_violations=[],
                execution_ms=int(time.time() * 1000) - start_ms,
                error=str(exc),
            )

        # Stage 7 — pre-execution validation
        try:
            self._validator.pre_execute(sql)
        except PreExecutionError as exc:
            logger.error("PreExecutionError: %s", exc)
            return AgentResponse(
                request_id=request_id,
                question=question,
                answer="The query failed pre-execution validation and was blocked.",
                sql=sql,
                rows=[],
                row_count=0,
                metric=intent.metric,
                source=None,
                clarification_needed=False,
                clarification_reason=None,
                rule_violations=[],
                execution_ms=int(time.time() * 1000) - start_ms,
                error=str(exc),
            )

        # Stage 8 — BQ execution
        bq_start = int(time.time() * 1000)
        rows = self._execute_query(sql, params)
        bq_ms = int(time.time() * 1000) - bq_start

        # Stage 9 — post-execution validation
        violations = self._validator.post_execute(intent=resolved, rows=rows)

        # Stage 10 — explain + lineage
        answer = self._explainer.explain(
            intent=resolved, rows=rows, violations=violations
        )

        rm = resolved.resolved_metric
        metric_name = rm.metric.name if rm else None
        source_name = rm.source.source_name if rm else None

        if self._config.enable_lineage:
            try:
                self._lineage.record(
                    question=question,
                    metric=metric_name,
                    concept=rm.concept.name if rm and rm.concept else None,
                    variant=rm.variant if rm else None,
                    resolved_source=source_name,
                    generated_sql=sql,
                    row_count=len(rows),
                    execution_ms=bq_ms,
                    filters={f.field: f.value for f in resolved.filters},
                    dimensions=[d.canonical_name for d in resolved.dimensions],
                    rule_violations=[{"rule": v.rule_id, "reason": v.description} for v in violations],
                    error=None,
                    tenant_id=tenant_id,
                    request_id=request_id,
                )
            except Exception as exc:
                logger.warning("LineageTracker.record failed: %s", exc)

        return AgentResponse(
            request_id=request_id,
            question=question,
            answer=answer,
            sql=sql,
            rows=rows[: self._config.max_result_rows],
            row_count=len(rows),
            metric=metric_name,
            source=source_name,
            clarification_needed=False,
            clarification_reason=None,
            rule_violations=[{"rule": v.rule_id, "reason": v.description} for v in violations],
            execution_ms=int(time.time() * 1000) - start_ms,
        )

    # ------------------------------------------------------------------
    # BQ execution (mirrors the pattern in analytics_api/src/main.py)
    # ------------------------------------------------------------------

    def _init_bq(self) -> None:
        if self._use_bq is not None:
            return
        try:
            from google.cloud import bigquery  # type: ignore[import]

            self._bq_client = bigquery.Client(project=BQ_PROJECT)
            self._use_bq = True
            logger.info("DomainExpertAgent: BigQuery backend ready (project=%s)", BQ_PROJECT)
        except Exception as exc:
            logger.warning("DomainExpertAgent: BigQuery unavailable (%s) — offline mode", exc)
            self._use_bq = False

    def _execute_query(
        self, sql: str, params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        self._init_bq()
        if not self._use_bq:
            logger.warning("DomainExpertAgent: No BQ client — returning empty result set")
            return []

        from google.cloud import bigquery  # type: ignore[import]

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter(k, _bq_type(v), v)
                for k, v in params.items()
            ]
        )
        query_job = self._bq_client.query(sql, job_config=job_config)
        rows = query_job.result()
        return [dict(row) for row in rows]
