"""
query_planner.py — QueryPlanner

Converts a ResolvedIntent into a QueryPlan that SQLGenerator can render
into a parameterized BigQuery SELECT statement.

Decision logic:
  1. If the metric has a pre-built ``bq_sql`` template → use bq_sql_override
     (timeseries queries use ``bq_sql_timeseries`` if available)
  2. Otherwise, build a QueryPlan from first principles using the resolved
     source, columns, filters, and dimensions.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

from analytics_api.src.agent.query_plan import (
    ColumnRef,
    JoinPath,
    MetricComputationSpec,
    QueryPlan,
)
from analytics_api.src.agent.resolved_intent import ResolvedIntent
from analytics_api.src.knowledge_graph.join_path_resolver import JoinPathResolver
from analytics_api.src.semantic.loader import SemanticLayerLoader, get_loader

logger = logging.getLogger(__name__)


class QueryPlanner:
    """Build a QueryPlan from a ResolvedIntent.

    Example::

        planner = QueryPlanner()
        plan = planner.plan(resolved_intent)
    """

    def __init__(self, loader: Optional[SemanticLayerLoader] = None) -> None:
        self._loader = loader or get_loader()
        self._join_resolver = JoinPathResolver(loader=self._loader)

    def plan(self, intent: ResolvedIntent) -> QueryPlan:
        """Convert ResolvedIntent → QueryPlan."""
        rm = intent.resolved_metric

        if rm is None:
            raise ValueError("Cannot plan a query without a resolved metric")

        metric = rm.metric
        source = rm.source

        # Step 1: Check for pre-built SQL shortcut
        if rm.is_timeseries and metric.bq_sql_timeseries:
            return self._plan_with_override(intent, metric.bq_sql_timeseries)
        if metric.bq_sql:
            plan = self._plan_with_override(intent, metric.bq_sql)
            # Append product_type filter if specified and not timeseries
            if intent.product_type and intent.product_type.upper() != "ALL":
                plan.where_conditions.append("product_type = :product_type")
                plan.bind_params["product_type"] = intent.product_type.upper()
            return plan

        # Step 2: Build from scratch
        table_alias = source.source_name.split(".")[-1]
        table_ref = source.full_table_ref

        select_cols: List[ColumnRef] = []
        group_by: List[str] = []

        # Dimension columns
        for dim in intent.dimensions:
            col = dim.physical_column
            select_cols.append(ColumnRef(table_alias=table_alias, column=col))
            group_by.append(f"{table_alias}.{col}")

        # Metric aggregation
        formula = metric.formula
        agg = formula.numerator_aggregation
        metric_spec = MetricComputationSpec(
            aggregation_sql=agg,
            result_alias=metric.name.lower(),
            multiply_by=formula.multiply_by,
        )
        select_cols.append(
            ColumnRef(
                table_alias=table_alias,
                column=agg,
                alias=metric.name.lower(),
            )
        )

        # WHERE conditions from filters
        where: List[str] = []
        params: Dict[str, object] = {}
        for rf in intent.filters:
            param_key = rf.field.replace(".", "_")
            where.append(f"{table_alias}.{rf.physical_column} {rf.operator} :{param_key}")
            params[param_key] = rf.value

        if intent.product_type and intent.product_type.upper() != "ALL":
            where.append("product_type = :product_type")
            params["product_type"] = intent.product_type.upper()

        # Join paths (if multi-entity)
        joins: List[JoinPath] = []
        if intent.needs_join and len(intent.entities_needed) > 1:
            source_map = {
                e: self._default_source(e)
                for e in intent.entities_needed
                if self._default_source(e)
            }
            try:
                resolved_joins = self._join_resolver.resolve(
                    from_entity=intent.entities_needed[0],
                    to_entities=intent.entities_needed[1:],
                    source_map=source_map,
                )
                for rj in resolved_joins:
                    joins.append(
                        JoinPath(
                            from_table_ref=rj.from_table_ref,
                            from_alias=rj.from_table_ref.strip("`").split(".")[-1],
                            from_column=rj.from_column,
                            to_table_ref=rj.to_table_ref,
                            to_alias=rj.to_table_ref.strip("`").split(".")[-1],
                            to_column=rj.to_column,
                            join_type=rj.join_type,
                        )
                    )
            except Exception as exc:
                logger.warning("QueryPlanner: join resolution failed — %s", exc)

        return QueryPlan(
            primary_table_ref=table_ref,
            primary_alias=table_alias,
            select_columns=select_cols,
            metric_spec=metric_spec,
            joins=joins,
            where_conditions=where,
            bind_params=params,
            group_by=group_by,
            order_by=[],
            limit=None,
            is_timeseries=intent.is_timeseries,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _plan_with_override(self, intent: ResolvedIntent, sql: str) -> QueryPlan:
        source = intent.resolved_metric.source  # type: ignore[union-attr]
        table_alias = source.source_name.split(".")[-1]
        return QueryPlan(
            primary_table_ref=source.full_table_ref,
            primary_alias=table_alias,
            select_columns=[],
            metric_spec=None,
            joins=[],
            where_conditions=[],
            bind_params={},
            group_by=[],
            order_by=[],
            limit=None,
            is_timeseries=intent.is_timeseries,
            bq_sql_override=sql,
        )

    def _default_source(self, entity_name: str) -> Optional[str]:
        try:
            entity = self._loader.get_entity(entity_name)
            if entity.sources:
                return entity.sources[0].name
        except Exception:
            pass
        return None
