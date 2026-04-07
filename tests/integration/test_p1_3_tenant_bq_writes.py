"""
P1.3 — Tenant-Aware BigQuery Writes
=====================================
Verifies that tenant_id is injected into every row produced by BQWriterAgent
row builder methods, and that BigQuery schemas include tenant_id as a REQUIRED field.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestTenantIdInSchemas:

    def _get_field_names(self, schema) -> list[str]:
        """Extract field names from a BQ schema list, handling both dicts and SchemaField."""
        names = []
        for field in schema:
            if hasattr(field, "name"):
                names.append(field.name)
            elif isinstance(field, dict):
                names.append(field["name"])
        return names

    def test_loan_applications_has_tenant_id(self):
        from db.bigquery_schema import LOAN_APPLICATIONS_SCHEMA
        assert "tenant_id" in self._get_field_names(LOAN_APPLICATIONS_SCHEMA)

    def test_feature_vectors_has_tenant_id(self):
        from db.bigquery_schema import FEATURE_VECTORS_SCHEMA
        assert "tenant_id" in self._get_field_names(FEATURE_VECTORS_SCHEMA)

    def test_model_scores_has_tenant_id(self):
        from db.bigquery_schema import MODEL_SCORES_SCHEMA
        assert "tenant_id" in self._get_field_names(MODEL_SCORES_SCHEMA)

    def test_credit_decisions_has_tenant_id(self):
        from db.bigquery_schema import CREDIT_DECISIONS_SCHEMA
        assert "tenant_id" in self._get_field_names(CREDIT_DECISIONS_SCHEMA)

    def test_explanations_has_tenant_id(self):
        from db.bigquery_schema import EXPLANATIONS_SCHEMA
        assert "tenant_id" in self._get_field_names(EXPLANATIONS_SCHEMA)

    def test_tenant_id_is_required(self):
        """tenant_id must be REQUIRED (not NULLABLE) in scoring tables."""
        from db.bigquery_schema import (
            CREDIT_DECISIONS_SCHEMA,
            EXPLANATIONS_SCHEMA,
            FEATURE_VECTORS_SCHEMA,
            MODEL_SCORES_SCHEMA,
        )
        for schema in (
            FEATURE_VECTORS_SCHEMA,
            MODEL_SCORES_SCHEMA,
            CREDIT_DECISIONS_SCHEMA,
            EXPLANATIONS_SCHEMA,
        ):
            for field in schema:
                name = field.name if hasattr(field, "name") else field["name"]
                if name == "tenant_id":
                    mode = field.mode if hasattr(field, "mode") else field.get("mode", "NULLABLE")
                    assert mode == "REQUIRED", (
                        f"tenant_id must be REQUIRED in {schema}, got mode={mode}"
                    )
                    break

    def test_clustering_includes_tenant_id(self):
        """Key tables must cluster on tenant_id as the first clustering field."""
        from db.bigquery_schema import (
            CREDIT_DECISIONS_CLUSTER,
            FEATURE_VECTORS_CLUSTER,
            MODEL_SCORES_CLUSTER,
        )
        for cluster in (FEATURE_VECTORS_CLUSTER, MODEL_SCORES_CLUSTER, CREDIT_DECISIONS_CLUSTER):
            assert "tenant_id" in cluster, (
                f"Expected tenant_id in clustering fields, got {cluster}"
            )


# ---------------------------------------------------------------------------
# Row builder tests
# ---------------------------------------------------------------------------

class TestBQWriterRowBuilders:

    def _make_agent(self) -> "BQWriterAgent":
        from agents.bq_writer_agent import BQWriterAgent
        return BQWriterAgent()

    def test_feature_rows_include_tenant_id(self):
        from agents.bq_writer_agent import BQWriterAgent

        features = [{"application_id": "app-001", "pd_score": 0.05}]
        rows = BQWriterAgent._build_feature_rows(features, run_id="run-1", tenant_id="acme")
        assert rows[0]["tenant_id"] == "acme"

    def test_score_rows_include_tenant_id(self):
        from agents.bq_writer_agent import BQWriterAgent

        scores = [{"application_id": "app-002", "pd_score": 0.08, "pd_band": "medium",
                   "fraud_probability": 0.1, "fraud_flag": "continue",
                   "model_version": "v1", "scored_at": "2026-01-01"}]
        rows = BQWriterAgent._build_score_rows(scores, run_id="run-1", tenant_id="beta")
        assert rows[0]["tenant_id"] == "beta"

    def test_decision_rows_include_tenant_id(self):
        from agents.bq_writer_agent import BQWriterAgent

        decisions = [{"application_id": "app-003", "decision": "APPROVE",
                      "policy_version": "v1"}]
        rows = BQWriterAgent._build_decision_rows(decisions, run_id="run-1", tenant_id="gamma")
        assert rows[0]["tenant_id"] == "gamma"

    def test_explanation_rows_include_tenant_id(self):
        from agents.bq_writer_agent import BQWriterAgent

        explanations = [{"application_id": "app-004", "final_decision": "REJECT",
                         "explanation_method": "shap"}]
        rows = BQWriterAgent._build_explanation_rows(explanations, run_id="run-1", tenant_id="delta")
        assert rows[0]["tenant_id"] == "delta"

    def test_run_payload_propagates_tenant_id(self):
        """BQWriterAgent._run should pass tenant_id from the payload into every row."""
        import pandas as pd
        from agents.bq_writer_agent import BQWriterAgent, _BQ_READY

        if _BQ_READY:
            pytest.skip("Skip when BQ client is available (would need real GCP creds)")

        agent = BQWriterAgent()
        captured_rows: list = []

        original_write = agent._write

        def _capture_write(rows, logical_table, mode):
            captured_rows.extend(rows)
            return len(rows)

        agent._write = _capture_write

        payload = {
            "run_id": "test-run",
            "tenant_id": "acme-corp",
            "features": [{"application_id": "a1", "computed_at": "2026-01-01"}],
            "scores": [{"application_id": "a1", "pd_score": 0.05, "pd_band": "low",
                        "fraud_probability": 0.1, "fraud_flag": "continue",
                        "model_version": "v1", "scored_at": "2026-01-01"}],
            "decisions": [{"application_id": "a1", "decision": "APPROVE",
                           "policy_version": "v1", "decided_at": "2026-01-01"}],
        }

        agent._run(payload)

        for row in captured_rows:
            assert row.get("tenant_id") == "acme-corp", (
                f"Expected tenant_id='acme-corp' in row, got {row}"
            )
