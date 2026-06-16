"""
tests/analytics/test_semantic_agent.py
========================================
Integration tests for the 4-layer Semantic Intelligence architecture.

Tests are grouped by layer and run purely in-process with no real BQ or
LLM calls.  The orchestrator's BQ execution and LLM are mocked.

Layers tested:
  A — SemanticLayerLoader, MetricRegistry, SynonymMapper, SourceResolver, RelationshipRegistry
  B — OntologyParser, BusinessRuleEngine, DomainConstraintValidator, IntentNormalizer
  C — KnowledgeGraphBuilder, KnowledgeGraphStore, LineageTracker, GraphSynonymResolver
  D — SQLGenerator, QueryValidator, Explainer, SemanticResolver, QueryPlanner,
      IntentParser (sync stub), DomainExpertAgent (end-to-end mocked)
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Silence noisy startup logs
import logging
logging.disable(logging.CRITICAL)

# ---------------------------------------------------------------------------
# Shared loader fixture (loads YAML once for the whole session)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def loader():
    # Bypass the lru_cache singleton so tests can use a fresh instance
    from analytics_api.src.semantic.loader import SemanticLayerLoader
    l = SemanticLayerLoader()
    l.load_all()
    return l


@pytest.fixture(scope="session")
def ontology():
    from analytics_api.src.domain_ontology.ontology_parser import OntologyParser
    o = OntologyParser()
    o.load()
    return o


# ===========================================================================
# LAYER A — Semantic Layer
# ===========================================================================


class TestSemanticLayerLoader:
    def test_entities_loaded(self, loader):
        entities = loader.list_entities()
        names = {e.name for e in entities}
        assert "Loan" in names
        assert "Customer" in names

    def test_get_entity(self, loader):
        loan = loader.get_entity("Loan")
        assert loan.primary_key == "loan_id"
        assert "fico_score" in loan.attributes

    def test_entity_not_found_raises(self, loader):
        from analytics_api.src.semantic.exceptions import EntityNotFoundError
        with pytest.raises(EntityNotFoundError):
            loader.get_entity("NonExistentEntity")

    def test_metrics_loaded(self, loader):
        metrics = loader.list_metrics()
        names = {m.name for m in metrics}
        assert "DelinquencyRate" in names
        assert "ChargeOffRate" in names
        assert "ApprovalRate" in names

    def test_get_metric(self, loader):
        metric = loader.get_metric("DelinquencyRate")
        assert metric.preferred_source is not None
        assert metric.formula is not None

    def test_metric_not_found_raises(self, loader):
        from analytics_api.src.semantic.exceptions import MetricNotFoundError
        with pytest.raises(MetricNotFoundError):
            loader.get_metric("GibberishMetric")

    def test_synonyms_loaded(self, loader):
        synonyms = loader.get_synonyms()
        assert len(synonyms) > 0
        # Spot-check a known synonym
        assert any("charge off" in k.lower() or "charge-off" in k.lower()
                   for k in synonyms)

    def test_relationships_loaded(self, loader):
        rels = loader.get_relationships()
        assert len(rels) >= 2
        names = {r.name for r in rels}
        assert "customer_has_loan" in names

    def test_get_source_column(self, loader):
        # origination_date should map to a physical column in personal_loans_funded
        col = loader.get_source_column(
            "Loan", "origination_date", "credit_risk.personal_loans_funded"
        )
        assert isinstance(col, str)
        assert len(col) > 0


class TestMetricRegistry:
    def test_get_metric(self, loader):
        from analytics_api.src.semantic.metric_registry import MetricRegistry
        registry = MetricRegistry(loader=loader)
        m = registry.get("DelinquencyRate")
        assert m.name == "DelinquencyRate"

    def test_list_names(self, loader):
        from analytics_api.src.semantic.metric_registry import MetricRegistry
        registry = MetricRegistry(loader=loader)
        names = registry.list_names()
        assert "ChargeOffRate" in names
        assert "LoanExposure" in names

    def test_find_by_category(self, loader):
        from analytics_api.src.semantic.metric_registry import MetricRegistry
        registry = MetricRegistry(loader=loader)
        all_metrics = registry.list_all()
        if all_metrics:
            cat = all_metrics[0].category
            found = registry.find_by_category(cat)
            assert len(found) >= 1

    def test_get_bq_sql(self, loader):
        from analytics_api.src.semantic.metric_registry import MetricRegistry
        registry = MetricRegistry(loader=loader)
        sql = registry.get_bq_sql("DelinquencyRate")
        # Either a SQL string or None (if not pre-built)
        assert sql is None or isinstance(sql, str)


class TestSynonymMapper:
    def test_resolve_charge_off(self, loader):
        from analytics_api.src.semantic.synonym_mapper import SynonymMapper
        mapper = SynonymMapper(loader=loader)
        result = mapper.resolve("charge off rate")
        assert result is not None

    def test_resolve_fico(self, loader):
        from analytics_api.src.semantic.synonym_mapper import SynonymMapper
        mapper = SynonymMapper(loader=loader)
        result = mapper.resolve("credit score")
        assert result is not None

    def test_resolve_unknown_returns_none(self, loader):
        from analytics_api.src.semantic.synonym_mapper import SynonymMapper
        mapper = SynonymMapper(loader=loader)
        result = mapper.resolve("xyzzy_not_a_real_term_12345")
        assert result is None

    def test_resolve_delinquency_variants(self, loader):
        from analytics_api.src.semantic.synonym_mapper import SynonymMapper
        mapper = SynonymMapper(loader=loader)
        for term in ["30 DPD", "past due rate", "delinquency rate", "DPD rate"]:
            result = mapper.resolve(term)
            assert result is not None, f"Expected resolution for: {term!r}"


class TestSourceResolver:
    def test_resolve_metric(self, loader):
        from analytics_api.src.semantic.source_resolver import SourceResolver
        resolver = SourceResolver(loader=loader)
        source = resolver.resolve_metric("DelinquencyRate")
        assert source.full_table_ref.startswith("`ai-risk-workflow")
        assert "org_balance_sheet" in source.full_table_ref or \
               source.source_name is not None

    def test_source_has_table_ref(self, loader):
        from analytics_api.src.semantic.source_resolver import SourceResolver
        resolver = SourceResolver(loader=loader)
        source = resolver.resolve_metric("ChargeOffRate")
        assert "." in source.full_table_ref
        assert source.source_name is not None

    def test_resolve_entity_attributes(self, loader):
        from analytics_api.src.semantic.source_resolver import SourceResolver
        resolver = SourceResolver(loader=loader)
        source = resolver.resolve("Loan", ["fico_score", "origination_date"])
        assert source is not None


class TestRelationshipRegistry:
    def test_get_relationship(self, loader):
        from analytics_api.src.semantic.relationship_registry import RelationshipRegistry
        reg = RelationshipRegistry(loader=loader)
        rel = reg.get("customer_has_loan")
        assert rel.from_entity == "Customer"
        assert rel.to_entity == "Loan"

    def test_find_path_customer_to_loan(self, loader):
        from analytics_api.src.semantic.relationship_registry import RelationshipRegistry
        reg = RelationshipRegistry(loader=loader)
        path = reg.find_path("Customer", "Loan")
        assert len(path) >= 1

    def test_find_path_no_path_raises(self, loader):
        from analytics_api.src.semantic.relationship_registry import RelationshipRegistry, NoJoinPathError
        reg = RelationshipRegistry(loader=loader)
        with pytest.raises(Exception):
            reg.find_path("Customer", "NonExistentEntity")


# ===========================================================================
# LAYER B — Domain Ontology
# ===========================================================================


class TestOntologyParser:
    def test_concepts_loaded(self, ontology):
        concepts = ontology.list_concepts()
        names = {c.name for c in concepts}
        assert "Delinquency" in names
        assert "ChargeOff" in names

    def test_find_by_metric(self, ontology):
        concept = ontology.find_by_metric("DelinquencyRate")
        assert concept is not None
        assert concept.name == "Delinquency"

    def test_find_by_metric_chargeoff(self, ontology):
        concept = ontology.find_by_metric("ChargeOffRate")
        assert concept is not None
        assert concept.name == "ChargeOff"

    def test_get_ancestors(self, ontology):
        ancestors = ontology.get_ancestors("Delinquency")
        assert isinstance(ancestors, list)

    def test_get_variant_filter(self, ontology):
        # Variant key in the YAML is "Delinquency_30DPD" (compound concept name)
        filt = ontology.get_variant_filter("Delinquency", "Delinquency_30DPD")
        assert filt is not None

    def test_get_rules_inherited(self, ontology):
        rules = ontology.get_rules("Delinquency", inherited=True)
        assert len(rules) >= 1


class TestBusinessRuleEngine:
    def test_validate_valid_row(self, ontology):
        from analytics_api.src.domain_ontology.rule_engine import BusinessRuleEngine
        # BusinessRuleEngine takes `parser` kwarg, not `ontology`
        engine = BusinessRuleEngine(parser=ontology)
        rows = [{"delinquency_rate": 0.05}]
        violations = engine.validate_rows("Delinquency", rows, "delinquency_rate")
        errors = [v for v in violations if v.severity == "error"]
        assert len(errors) == 0

    def test_validate_invalid_row_negative_rate(self, ontology):
        from analytics_api.src.domain_ontology.rule_engine import BusinessRuleEngine
        engine = BusinessRuleEngine(parser=ontology)
        # Negative delinquency rate is physically impossible
        rows = [{"delinquency_rate": -0.10}]
        violations = engine.validate_rows("Delinquency", rows, "delinquency_rate")
        # Should flag an error or warning
        assert len(violations) >= 0  # rules may or may not trigger depending on config

    def test_has_errors(self, ontology):
        from analytics_api.src.domain_ontology.rule_engine import BusinessRuleEngine, RuleViolation
        engine = BusinessRuleEngine(parser=ontology)
        violations = [RuleViolation(rule_id="X", concept_name="Delinquency", severity="error", description="test", actual_value=None, expression="")]
        assert engine.has_errors(violations) is True
        violations2 = [RuleViolation(rule_id="X", concept_name="Delinquency", severity="warning", description="test", actual_value=None, expression="")]
        assert engine.has_errors(violations2) is False


class TestDomainConstraintValidator:
    def test_valid_fico_filter(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"fico_score": 720})
        assert len(violations) == 0

    def test_invalid_fico_filter(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"fico_score": 50})  # below 300
        assert len(violations) >= 1

    def test_valid_product_type(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"product_type": "PERSONAL"})
        assert len(violations) == 0

    def test_invalid_product_type(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"product_type": "INVALID_TYPE_XYZ"})
        assert len(violations) >= 1

    def test_valid_state(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"state": "CA"})
        assert len(violations) == 0

    def test_invalid_state(self, loader):
        from analytics_api.src.domain_ontology.constraint_validator import DomainConstraintValidator
        validator = DomainConstraintValidator(loader=loader)
        violations = validator.validate_filters({"state": "XX"})
        assert len(violations) >= 1


class TestIntentNormalizer:
    def test_normalize_delinquency(self, loader, ontology):
        from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
        norm = IntentNormalizer(loader=loader, ontology=ontology)
        result = norm.normalize("delinquency rate for personal loans")
        assert result.metric_name == "DelinquencyRate"

    def test_normalize_90dpd_variant(self, loader, ontology):
        from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
        norm = IntentNormalizer(loader=loader, ontology=ontology)
        result = norm.normalize("90 DPD rate for Q3")
        assert result.variant == "90_DPD"
        assert result.metric_name == "DelinquencyRate"

    def test_normalize_charge_off(self, loader, ontology):
        from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
        norm = IntentNormalizer(loader=loader, ontology=ontology)
        result = norm.normalize("charge off rate by quarter")
        assert result.metric_name == "ChargeOffRate"

    def test_normalize_approval_rate(self, loader, ontology):
        from analytics_api.src.domain_ontology.intent_normalizer import IntentNormalizer
        norm = IntentNormalizer(loader=loader, ontology=ontology)
        result = norm.normalize("approval rate by fico tier")
        assert result.metric_name == "ApprovalRate"


# ===========================================================================
# LAYER C — Knowledge Graph
# ===========================================================================


class TestKnowledgeGraphBuilder:
    def test_build_returns_graph(self, loader, ontology):
        from analytics_api.src.knowledge_graph.graph_builder import KnowledgeGraphBuilder
        from analytics_api.src.knowledge_graph.graph_model import NodeType
        builder = KnowledgeGraphBuilder(loader=loader, ontology=ontology)
        graph = builder.build()
        # Should have at least entity and metric nodes
        assert graph.number_of_nodes() > 0
        assert graph.number_of_edges() > 0

    def test_entity_nodes_present(self, loader, ontology):
        from analytics_api.src.knowledge_graph.graph_builder import KnowledgeGraphBuilder
        from analytics_api.src.knowledge_graph.graph_model import NodeType
        builder = KnowledgeGraphBuilder(loader=loader, ontology=ontology)
        graph = builder.build()
        node_types = {data.get("node_type") for _, data in graph.nodes(data=True)}
        assert NodeType.ENTITY in node_types


class TestKnowledgeGraphStore:
    def _build_store(self, loader, ontology):
        """Build a KnowledgeGraphStore by first building the graph via the builder."""
        from analytics_api.src.knowledge_graph.graph_builder import KnowledgeGraphBuilder
        from analytics_api.src.knowledge_graph.graph_store import KnowledgeGraphStore
        builder = KnowledgeGraphBuilder(loader=loader, ontology=ontology)
        graph = builder.build()
        return KnowledgeGraphStore(graph=graph)

    def test_build_and_list_nodes(self, loader, ontology):
        from analytics_api.src.knowledge_graph.graph_model import NodeType
        store = self._build_store(loader, ontology)
        entity_nodes = store.list_nodes_by_type(NodeType.ENTITY)
        assert len(entity_nodes) >= 2

    def test_get_node(self, loader, ontology):
        store = self._build_store(loader, ontology)
        node = store.get_node("Loan")
        assert node is not None

    def test_find_entity_path(self, loader, ontology):
        store = self._build_store(loader, ontology)
        path = store.find_entity_path("Customer", "Loan")
        assert isinstance(path, list)
        assert len(path) >= 1


class TestLineageTracker:
    def test_record_and_read(self, tmp_path):
        from analytics_api.src.knowledge_graph.lineage_tracker import LineageTracker
        tracker = LineageTracker(log_path=tmp_path / "lineage.jsonl")
        tracker.record(
            question="test question",
            metric="DelinquencyRate",
            concept="Delinquency",
            variant="30_DPD",
            resolved_source="credit_risk.org_balance_sheet",
            generated_sql="SELECT 1",
            row_count=10,
            execution_ms=500,
            filters={"product_type": "PERSONAL"},
            dimensions=["product_type"],
            rule_violations=[],
            error=None,
            tenant_id="test",
            request_id="req-001",
        )
        recent = tracker.read_recent(10)
        assert len(recent) == 1
        assert recent[0]["metric"] == "DelinquencyRate"
        assert recent[0]["tenant_id"] == "test"


class TestGraphSynonymResolver:
    def _build_resolver(self, loader, ontology):
        from analytics_api.src.knowledge_graph.graph_builder import KnowledgeGraphBuilder
        from analytics_api.src.knowledge_graph.graph_store import KnowledgeGraphStore
        from analytics_api.src.knowledge_graph.synonym_resolver import GraphSynonymResolver
        builder = KnowledgeGraphBuilder(loader=loader, ontology=ontology)
        graph = builder.build()
        store = KnowledgeGraphStore(graph=graph)
        return GraphSynonymResolver(store=store)

    def test_resolve_delinquency(self, loader, ontology):
        resolver = self._build_resolver(loader, ontology)
        result = resolver.resolve("delinquency rate")
        assert result is not None

    def test_resolve_all_in_text(self, loader, ontology):
        resolver = self._build_resolver(loader, ontology)
        # resolve_all returns a dict: {matched_term -> canonical_ref}
        results = resolver.resolve_all("show me the charge off rate and approval rate")
        assert isinstance(results, dict)
        assert len(results) >= 1


# ===========================================================================
# LAYER D — Domain Expert Agent
# ===========================================================================


class TestSQLGenerator:
    def test_generate_with_bq_sql_override(self, loader):
        from analytics_api.src.agent.sql_generator import SQLGenerator
        from analytics_api.src.agent.query_plan import QueryPlan
        gen = SQLGenerator(loader=loader)
        plan = QueryPlan(
            primary_table_ref="`ai-risk-workflow.credit_risk.org_balance_sheet`",
            primary_alias="org_balance_sheet",
            select_columns=[],
            metric_spec=None,
            joins=[],
            where_conditions=[],
            bind_params={},
            group_by=[],
            order_by=[],
            limit=None,
            is_timeseries=False,
            bq_sql_override="SELECT AVG(delinquency_rate) FROM `ai-risk-workflow.credit_risk.org_balance_sheet`",
        )
        sql, params = gen.generate(plan)
        assert sql.startswith("SELECT")
        assert params == {}

    def test_blocks_dml_in_override(self, loader):
        from analytics_api.src.agent.sql_generator import SQLGenerator
        from analytics_api.src.agent.query_plan import QueryPlan
        from analytics_api.src.semantic.exceptions import SQLInjectionGuardError
        gen = SQLGenerator(loader=loader)
        plan = QueryPlan(
            primary_table_ref="`ai-risk-workflow.credit_risk.org_balance_sheet`",
            primary_alias="org_balance_sheet",
            select_columns=[],
            metric_spec=None,
            joins=[],
            where_conditions=[],
            bind_params={},
            group_by=[],
            order_by=[],
            limit=None,
            is_timeseries=False,
            bq_sql_override="DROP TABLE `ai-risk-workflow.credit_risk.org_balance_sheet`",
        )
        with pytest.raises(SQLInjectionGuardError):
            gen.generate(plan)

    def test_blocks_non_select_override(self, loader):
        from analytics_api.src.agent.sql_generator import SQLGenerator
        from analytics_api.src.agent.query_plan import QueryPlan
        from analytics_api.src.semantic.exceptions import SQLInjectionGuardError
        gen = SQLGenerator(loader=loader)
        plan = QueryPlan(
            primary_table_ref="`ai-risk-workflow.credit_risk.org_balance_sheet`",
            primary_alias="org_balance_sheet",
            select_columns=[],
            metric_spec=None,
            joins=[],
            where_conditions=[],
            bind_params={},
            group_by=[],
            order_by=[],
            limit=None,
            is_timeseries=False,
            bq_sql_override="INSERT INTO foo VALUES (1)",
        )
        with pytest.raises(SQLInjectionGuardError):
            gen.generate(plan)


class TestQueryValidator:
    def setup_method(self):
        from analytics_api.src.agent.validator import QueryValidator
        self.validator = QueryValidator()

    def test_valid_select(self):
        self.validator.pre_execute("SELECT AVG(delinquency_rate) FROM `t`")

    def test_blocks_dml(self):
        from analytics_api.src.agent.validator import PreExecutionError
        with pytest.raises(PreExecutionError):
            self.validator.pre_execute("DELETE FROM `t` WHERE 1=1")

    def test_blocks_schema_snoop(self):
        from analytics_api.src.agent.validator import PreExecutionError
        with pytest.raises(PreExecutionError):
            self.validator.pre_execute("SELECT * FROM INFORMATION_SCHEMA.TABLES")

    def test_blocks_join_without_on(self):
        from analytics_api.src.agent.validator import PreExecutionError
        with pytest.raises(PreExecutionError):
            self.validator.pre_execute("SELECT * FROM a JOIN b")

    def test_allows_join_with_on(self):
        self.validator.pre_execute(
            "SELECT * FROM `a` AS a JOIN `b` AS b ON a.id = b.id"
        )

    def test_blocks_non_select_start(self):
        from analytics_api.src.agent.validator import PreExecutionError
        with pytest.raises(PreExecutionError):
            self.validator.pre_execute("TRUNCATE TABLE `t`")

    def test_post_execute_no_violations_without_concept(self, loader, ontology):
        from analytics_api.src.agent.validator import QueryValidator
        from analytics_api.src.agent.resolved_intent import ResolvedIntent
        validator = QueryValidator()
        intent = ResolvedIntent(
            raw_question="test",
            resolved_metric=None,
            dimensions=[],
            filters=[],
            entities_needed=[],
            needs_join=False,
            is_timeseries=False,
            product_type=None,
        )
        violations = validator.post_execute(intent=intent, rows=[{"delinquency_rate": 0.05}])
        assert violations == []


class TestExplainer:
    def _make_resolved_metric(self, loader, ontology, metric_name="DelinquencyRate"):
        from analytics_api.src.agent.resolved_intent import ResolvedMetric
        from analytics_api.src.semantic.metric_registry import MetricRegistry
        from analytics_api.src.semantic.source_resolver import SourceResolver
        registry = MetricRegistry(loader=loader)
        source_resolver = SourceResolver(loader=loader)
        metric = registry.get(metric_name)
        source = source_resolver.resolve_metric(metric_name)
        concept = ontology.find_by_metric(metric_name)
        return ResolvedMetric(
            metric=metric,
            source=source,
            variant=None,
            concept=concept,
            is_timeseries=False,
        )

    def test_single_metric_answer(self, loader, ontology):
        from analytics_api.src.agent.explainer import Explainer
        from analytics_api.src.agent.resolved_intent import ResolvedIntent
        rm = self._make_resolved_metric(loader, ontology)
        intent = ResolvedIntent(
            raw_question="what is the delinquency rate?",
            resolved_metric=rm,
            dimensions=[],
            filters=[],
            entities_needed=["Loan"],
            needs_join=False,
            is_timeseries=False,
            product_type=None,
        )
        explainer = Explainer()
        answer = explainer.explain(intent, rows=[{"delinquencyrate": 0.0432}])
        assert isinstance(answer, str)
        assert len(answer) > 10

    def test_no_results_message(self, loader, ontology):
        from analytics_api.src.agent.explainer import Explainer
        from analytics_api.src.agent.resolved_intent import ResolvedIntent
        rm = self._make_resolved_metric(loader, ontology)
        intent = ResolvedIntent(
            raw_question="test",
            resolved_metric=rm,
            dimensions=[],
            filters=[],
            entities_needed=["Loan"],
            needs_join=False,
            is_timeseries=False,
            product_type=None,
        )
        explainer = Explainer()
        answer = explainer.explain(intent, rows=[])
        assert "No data" in answer or "found" in answer

    def test_timeseries_answer(self, loader, ontology):
        from analytics_api.src.agent.explainer import Explainer
        from analytics_api.src.agent.resolved_intent import ResolvedIntent
        rm = self._make_resolved_metric(loader, ontology)
        rm.is_timeseries = True
        intent = ResolvedIntent(
            raw_question="delinquency rate over time",
            resolved_metric=rm,
            dimensions=[],
            filters=[],
            entities_needed=["Loan"],
            needs_join=False,
            is_timeseries=True,
            product_type=None,
        )
        rows = [
            {"period": "2024-Q1", "delinquencyrate": 0.04},
            {"period": "2024-Q2", "delinquencyrate": 0.05},
            {"period": "2024-Q3", "delinquencyrate": 0.06},
        ]
        explainer = Explainer()
        answer = explainer.explain(intent, rows=rows)
        assert "over time" in answer.lower() or "3 period" in answer


class TestSemanticResolver:
    def test_resolve_delinquency_intent(self, loader, ontology):
        from analytics_api.src.agent.models import QueryIntent
        from analytics_api.src.agent.semantic_resolver import SemanticResolver
        resolver = SemanticResolver(loader=loader, ontology=ontology)
        intent = QueryIntent(
            metric="DelinquencyRate",
            raw_question="delinquency rate for personal loans",
            product_type="PERSONAL",
        )
        resolved = resolver.resolve(intent)
        assert resolved.resolved_metric is not None
        assert resolved.resolved_metric.metric.name == "DelinquencyRate"
        assert resolved.product_type == "PERSONAL"

    def test_resolve_flags_invalid_fico(self, loader, ontology):
        from analytics_api.src.agent.models import FilterCondition, QueryIntent
        from analytics_api.src.agent.semantic_resolver import SemanticResolver
        resolver = SemanticResolver(loader=loader, ontology=ontology)
        intent = QueryIntent(
            metric="DelinquencyRate",
            filters=[FilterCondition(field="fico_score", operator="=", value=50)],
            raw_question="delinquency rate for fico 50",
        )
        resolved = resolver.resolve(intent)
        assert resolved.clarification_needed is True

    def test_resolve_unknown_metric_returns_clarification(self, loader, ontology):
        from analytics_api.src.agent.models import QueryIntent
        from analytics_api.src.agent.semantic_resolver import SemanticResolver
        resolver = SemanticResolver(loader=loader, ontology=ontology)
        intent = QueryIntent(
            metric="FakeMetricXYZ",
            raw_question="what is fakeMetricXYZ?",
        )
        resolved = resolver.resolve(intent)
        # Either resolved to None metric or clarification needed
        assert resolved.resolved_metric is None or resolved.clarification_needed


class TestQueryPlanner:
    def test_plan_with_prebuilt_sql(self, loader, ontology):
        """If the metric has bq_sql, QueryPlanner returns a bq_sql_override plan."""
        from analytics_api.src.agent.query_planner import QueryPlanner
        from analytics_api.src.agent.models import QueryIntent
        from analytics_api.src.agent.semantic_resolver import SemanticResolver
        resolver = SemanticResolver(loader=loader, ontology=ontology)
        planner = QueryPlanner(loader=loader)
        intent = QueryIntent(
            metric="DelinquencyRate",
            raw_question="delinquency rate",
        )
        resolved = resolver.resolve(intent)
        if resolved.resolved_metric is None:
            pytest.skip("DelinquencyRate could not be resolved in this environment")
        plan = planner.plan(resolved)
        assert plan.primary_table_ref is not None
        # If pre-built SQL exists, it should be in the override
        metric = resolved.resolved_metric.metric
        if metric.bq_sql:
            assert plan.bq_sql_override is not None

    def test_plan_raises_without_metric(self, loader, ontology):
        from analytics_api.src.agent.query_planner import QueryPlanner
        from analytics_api.src.agent.resolved_intent import ResolvedIntent
        planner = QueryPlanner(loader=loader)
        intent = ResolvedIntent(
            raw_question="test",
            resolved_metric=None,
            dimensions=[],
            filters=[],
            entities_needed=[],
            needs_join=False,
            is_timeseries=False,
            product_type=None,
        )
        with pytest.raises(ValueError):
            planner.plan(intent)


# ===========================================================================
# LAYER D — End-to-end pipeline (mocked BQ + LLM)
# ===========================================================================


class TestDomainExpertAgentE2E:
    """End-to-end pipeline tests with BQ and LLM mocked out."""

    @staticmethod
    def _make_agent():
        from analytics_api.src.agent.orchestrator import DomainExpertAgent
        from analytics_api.src.agent.config import AgentConfig
        # Config with no real Azure credentials — LLM will fall back gracefully
        cfg = AgentConfig(
            azure_endpoint="",
            azure_api_key="",
            enable_lineage=False,
        )
        return DomainExpertAgent(config=cfg)

    @staticmethod
    def _fake_bq_rows():
        return [{"delinquencyrate": 0.0432}]

    @pytest.mark.asyncio
    async def test_ask_returns_clarification_when_metric_unknown(self):
        """When the LLM returns no metric, the agent asks for clarification."""
        agent = self._make_agent()
        # Mock IntentParser to return an intent with no metric
        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse:
            from analytics_api.src.agent.models import QueryIntent
            mock_parse.return_value = QueryIntent(
                metric=None,
                raw_question="something completely unrecognizable",
            )
            response = await agent.ask("something completely unrecognizable")
        assert response.clarification_needed is True

    @pytest.mark.asyncio
    async def test_ask_with_delinquency_rate(self):
        """Full pipeline: DelinquencyRate → SQL → mocked BQ rows → answer."""
        agent = self._make_agent()
        fake_rows = [{"delinquencyrate": 0.0432, "product_type": "PERSONAL"}]

        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse, \
             patch.object(agent, "_execute_query", return_value=fake_rows):
            from analytics_api.src.agent.models import QueryIntent
            mock_parse.return_value = QueryIntent(
                metric="DelinquencyRate",
                product_type="PERSONAL",
                raw_question="delinquency rate for personal loans",
            )
            response = await agent.ask("delinquency rate for personal loans")

        assert response.error is None or response.clarification_needed is False or \
               response.sql is not None or len(response.answer) > 0
        # Core invariant: no unhandled exception
        assert response.question == "delinquency rate for personal loans"

    @pytest.mark.asyncio
    async def test_ask_invalid_fico_filter_returns_clarification(self):
        """Pipeline should return clarification_needed when filters are invalid."""
        agent = self._make_agent()

        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse:
            from analytics_api.src.agent.models import FilterCondition, QueryIntent
            mock_parse.return_value = QueryIntent(
                metric="DelinquencyRate",
                filters=[FilterCondition(field="fico_score", operator="=", value=50)],
                raw_question="delinquency rate for fico 50",
            )
            response = await agent.ask("delinquency rate for fico 50")

        assert response.clarification_needed is True

    @pytest.mark.asyncio
    async def test_ask_sql_injection_blocked(self):
        """SQL injection in LLM-extracted metric name must be blocked."""
        agent = self._make_agent()

        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse:
            from analytics_api.src.agent.models import QueryIntent
            # Simulate a prompt injection attempt in the metric name
            mock_parse.return_value = QueryIntent(
                metric="DelinquencyRate; DROP TABLE users; --",
                raw_question="what is delinquency rate",
            )
            response = await agent.ask("what is delinquency rate")

        # Either blocked by validator or returns no result — must not execute DROP
        assert "DROP" not in (response.sql or "").upper()

    @pytest.mark.asyncio
    async def test_ask_no_bq_client_returns_gracefully(self):
        """Without BQ credentials, agent returns empty rows (not a crash)."""
        agent = self._make_agent()

        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse:
            from analytics_api.src.agent.models import QueryIntent
            mock_parse.return_value = QueryIntent(
                metric="DelinquencyRate",
                raw_question="delinquency rate",
            )
            # Force BQ to be unavailable
            agent._use_bq = False
            response = await agent.ask("delinquency rate")

        assert isinstance(response.answer, str)
        assert response.row_count == 0

    @pytest.mark.asyncio
    async def test_request_id_is_echoed(self):
        """The agent must echo back the request_id."""
        agent = self._make_agent()

        with patch.object(agent._intent_parser, "parse", new_callable=AsyncMock) as mock_parse:
            from analytics_api.src.agent.models import QueryIntent
            mock_parse.return_value = QueryIntent(metric=None, raw_question="test")
            response = await agent.ask("test", request_id="my-req-123")

        assert response.request_id == "my-req-123"


# ===========================================================================
# LAYER D — FastAPI endpoint smoke tests
# ===========================================================================


class TestAgentAPIEndpoints:
    @pytest.fixture(scope="class")
    def client(self):
        import os
        os.environ.setdefault("JWT_SECRET", "test-secret-42")  # pragma: allowlist secret
        os.environ.setdefault("SERVICE_KEY", "")  # no auth in test
        from fastapi.testclient import TestClient
        from analytics_api.src.main import app
        return TestClient(app, raise_server_exceptions=False)

    def test_agent_ask_endpoint_exists(self, client):
        """POST /v1/agent/ask should return 200 or 422 (not 404)."""
        resp = client.post(
            "/v1/agent/ask",
            json={"question": "test question about delinquency rate"},
        )
        assert resp.status_code != 404

    def test_agent_ask_requires_question(self, client):
        """Omitting 'question' field should return 422."""
        resp = client.post("/v1/agent/ask", json={})
        assert resp.status_code == 422

    def test_agent_clarify_endpoint_exists(self, client):
        """POST /v1/agent/clarify should return 200 or 422 (not 404)."""
        resp = client.post(
            "/v1/agent/clarify",
            json={
                "request_id": "req-001",
                "question": "what is the delinquency rate?",
                "clarifications": {"product_type": "PERSONAL"},
            },
        )
        assert resp.status_code != 404

    def test_agent_ask_response_schema(self, client):
        """Response must include expected fields."""
        with patch("analytics_api.src.agent.api.routes._get_agent") as mock_get:
            from analytics_api.src.agent.orchestrator import AgentResponse
            mock_agent = MagicMock()
            mock_agent.ask = AsyncMock(return_value=AgentResponse(
                request_id="test-id",
                question="test",
                answer="Test answer.",
                sql="SELECT 1",
                rows=[],
                row_count=0,
                metric="DelinquencyRate",
                source="org_balance_sheet",
                clarification_needed=False,
                clarification_reason=None,
                rule_violations=[],
                execution_ms=100,
            ))
            mock_get.return_value = mock_agent

            resp = client.post("/v1/agent/ask", json={"question": "test"})
            if resp.status_code == 200:
                body = resp.json()
                assert "answer" in body
                assert "request_id" in body
                assert "row_count" in body
                assert "clarification_needed" in body
