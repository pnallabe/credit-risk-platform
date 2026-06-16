"""
BigQuery Writer Agent
======================
Writes all pipeline outputs to BigQuery after each scoring run.

Supported modes
---------------
  streaming  — uses BQ Storage Write API insert_rows for near-real-time latency.
               Best for online / single-application scoring.
  batch      — uses a load job via load_table_from_dataframe.
               Best for nightly batch runs (lower cost, higher throughput).

Input payload contract
----------------------
The agent expects to receive the aggregated outputs from all upstream agents:

  {
    "run_id"      : str,
    "mode"        : "streaming" | "batch"       # optional, falls back to config
    "features"    : List[dict],                  # from FeatureEngineeringAgent
    "scores"      : List[dict],                  # from RiskModelingAgent
    "decisions"   : List[dict],                  # from DecisionEngineAgent
    "explanations": List[dict],                  # from ExplainabilityAgent
    "raw_records" : List[dict],                  # optional, from DataIngestionAgent
    "drift_report": dict | None,                 # optional, from MonitoringAgent
    "fair_lending" : dict | None,                # optional, from MonitoringAgent
    "experiment"  : dict | None,                 # optional, from ExperimentationAgent
  }

Output payload
--------------
  {
    "tables_written"  : List[str],
    "rows_written"    : Dict[str, int],
    "write_mode"      : str,
    "bq_dataset"      : str,
    "bq_project"      : str,
  }
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.base import AgentResult, AgentStatus, BaseAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional BQ imports — agent degrades gracefully when unavailable
# ---------------------------------------------------------------------------
try:
    from db.bigquery_client import (
        DEFAULT_DATASET,
        DEFAULT_PROJECT,
        ensure_dataset,
        ensure_table,
        stream_rows,
        write_dataframe,
    )
    from db.bigquery_schema import TABLE_CATALOGUE
    import pandas as pd
    _BQ_READY = True
except ImportError as _e:
    _BQ_READY = False
    DEFAULT_PROJECT = os.getenv("GCP_PROJECT_ID", "ai-risk-workflow")
    DEFAULT_DATASET = os.getenv("BQ_DATASET_MODEL_DEV", "credit_risk_model_dev")
    logger.warning("BigQuery writer unavailable: %s", _e)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_json_safe(obj: Any) -> Any:
    """Recursively convert non-serializable types (datetime, Decimal, etc.) to JSON-safe forms."""
    if isinstance(obj, dict):
        return {k: _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_json_safe(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    try:
        import decimal
        if isinstance(obj, decimal.Decimal):
            return float(obj)
    except ImportError:
        pass
    return obj


def _safe_list(obj: Any) -> List[dict]:
    """Return obj as a list of dicts, tolerating None / Pydantic objects."""
    if not obj:
        return []
    result = []
    for item in obj:
        if hasattr(item, "model_dump"):
            result.append(item.model_dump())
        elif hasattr(item, "__dict__"):
            result.append(vars(item))
        elif isinstance(item, dict):
            result.append(item)
    return result


class BQWriterAgent(BaseAgent):
    """
    Writes all pipeline artefacts to BigQuery.
    Designed to execute as the final stage in the CreditRiskPipeline.
    """

    name = "BQWriterAgent"

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        project: Optional[str] = None,
        dataset: Optional[str] = None,
    ) -> None:
        super().__init__(config=config)
        bq_cfg = self.config.get("bigquery", {})
        self.project = project or bq_cfg.get("project", DEFAULT_PROJECT)
        self.dataset = dataset or bq_cfg.get("dataset", DEFAULT_DATASET)
        self.default_mode: str = bq_cfg.get("write_mode", "streaming")
        self.tables: Dict[str, str] = bq_cfg.get("tables", {})
        self._ensure_infra_done: bool = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _table_id(self, logical_name: str) -> str:
        """Resolve logical name → full BQ table ID."""
        physical = self.tables.get(logical_name, logical_name)
        return f"{self.project}.{self.dataset}.{physical}"

    def _ensure_infra(self) -> None:
        """Create dataset + all tables once per process lifetime."""
        if self._ensure_infra_done or not _BQ_READY:
            return
        ensure_dataset(self.dataset, project=self.project)
        for logical_name, meta in TABLE_CATALOGUE.items():
            # Resolve to the physical (bare) table name — not the fully qualified ID
            physical = self.tables.get(logical_name, logical_name)
            ensure_table(
                table_id=physical,
                schema=meta["schema"],
                dataset_id=self.dataset,
                project=self.project,
                partition_field=meta.get("partition_field"),
                clustering_fields=meta.get("clustering_fields"),
                description=meta.get("description", ""),
            )
        self._ensure_infra_done = True

    def _write(
        self,
        rows: List[dict],
        logical_table: str,
        mode: str,
    ) -> int:
        """Write rows to a BQ table; returns row count written."""
        if not rows or not _BQ_READY:
            return 0
        # Use bare physical name — bigquery_client functions add project.dataset prefix
        physical = self.tables.get(logical_table, logical_table)
        if mode == "streaming":
            stream_rows(rows, table_id=physical, dataset_id=self.dataset, project=self.project)
        else:
            import pandas as pd  # noqa: F401
            df = pd.DataFrame(rows)
            write_dataframe(
                df,
                table_id=physical,
                dataset_id=self.dataset,
                project=self.project,
                write_disposition="WRITE_APPEND",
            )
        return len(rows)

    # ------------------------------------------------------------------
    # Row builders — conform rows to BQ schema column names
    # ------------------------------------------------------------------

    @staticmethod
    def _build_feature_rows(features: List[dict], run_id: str, tenant_id: str = "") -> List[dict]:
        ts = _now()
        rows = []
        for f in features:
            row = dict(f)
            row["tenant_id"] = tenant_id
            row.setdefault("pipeline_run_id", run_id)
            row.setdefault("computed_at", ts)
            rows.append(row)
        return rows

    @staticmethod
    def _build_score_rows(scores: List[dict], run_id: str, tenant_id: str = "") -> List[dict]:
        ts = _now()
        rows = []
        for s in scores:
            row = dict(s)
            row["tenant_id"] = tenant_id
            row.setdefault("pipeline_run_id", run_id)
            row.setdefault("scored_at", ts)
            rows.append(row)
        return rows

    @staticmethod
    def _build_decision_rows(decisions: List[dict], run_id: str, tenant_id: str = "") -> List[dict]:
        ts = _now()
        rows = []
        for d in decisions:
            row = dict(d)
            row["tenant_id"] = tenant_id
            row.setdefault("pipeline_run_id", run_id)
            row.setdefault("decided_at", ts)
            rows.append(row)
        return rows

    @staticmethod
    def _build_explanation_rows(explanations: List[dict], run_id: str, tenant_id: str = "") -> List[dict]:
        ts = _now()
        rows = []
        for ex in explanations:
            row: Dict[str, Any] = {
                "tenant_id": tenant_id,
                "application_id": ex.get("application_id", "unknown"),
                "decision": ex.get("final_decision", ex.get("decision", "")),
                "method": ex.get("explanation_method", "stub"),
                "adverse_action_text": ex.get("adverse_action_text"),
                "explainer_version": ex.get("explainer_version"),
                "pipeline_run_id": run_id,
                "generated_at": ts,
            }
            # Flatten top_factors list → top_factor_N_name / _shap columns
            factors: List[dict] = ex.get("top_factors", [])
            for i, fac in enumerate(factors[:3], start=1):
                row[f"top_factor_{i}_name"] = fac.get("feature", fac.get("name"))
                row[f"top_factor_{i}_shap"] = fac.get("shap_value", fac.get("value"))
            rows.append(row)
        return rows

    @staticmethod
    def _build_drift_rows(drift: dict, run_id: str) -> List[dict]:
        if not drift:
            return []
        import json
        ts = _now()
        return [{
            "report_id": str(uuid.uuid4()),
            "pipeline_run_id": run_id,
            "overall_drift_status": drift.get("overall_drift_status", "unknown"),
            "features_with_major_drift": json.dumps(
                drift.get("features_with_major_drift", [])
            ),
            "features_with_minor_drift": json.dumps(
                drift.get("features_with_minor_drift", [])
            ),
            "psi_summary_json": json.dumps(drift.get("psi_scores", {})),
            "alert_triggered": bool(drift.get("alerts")),
            "report_timestamp": ts,
        }]

    @staticmethod
    def _build_fair_lending_rows(fl: dict, run_id: str) -> List[dict]:
        if not fl:
            return []
        import json
        ts = _now()
        rows = []
        for attr, result in fl.get("results_by_attribute", {fl.get("protected_attribute", "unknown"): fl}).items():
            rows.append({
                "report_id": str(uuid.uuid4()),
                "protected_col": attr,
                "control_group": result.get("control_group", ""),
                "protected_group": result.get("protected_group"),
                "dir_score": result.get("dir_score", 0.0),
                "dir_flag": bool(result.get("dir_flag", False)),
                "protected_approval_rate": result.get("protected_approval_rate"),
                "control_approval_rate": result.get("control_approval_rate"),
                "approval_parity_p_value": result.get("approval_parity", {}).get("p_value"),
                "approval_parity_flag": result.get("approval_parity", {}).get("flag"),
                "geographic_flags_json": json.dumps(result.get("geographic_flags", [])),
                "n_total": result.get("n_total"),
                "n_approved": result.get("n_approved"),
                "summary_text": result.get("summary"),
                "report_timestamp": ts,
            })
        return rows

    @staticmethod
    def _build_experiment_rows(exp: dict, run_id: str) -> List[dict]:
        if not exp:
            return []
        ts = _now()
        return [{
            "experiment_id": exp.get("experiment_id", str(uuid.uuid4())),
            "status": exp.get("status", "unknown"),
            "recommendation": exp.get("recommendation", "inconclusive"),
            "primary_metric": exp.get("primary_metric", "approval_rate"),
            "control_model_version": exp.get("control_model_version", "champion"),
            "treatment_model_version": exp.get("treatment_model_version", "challenger"),
            "control_n": exp.get("control_n"),
            "treatment_n": exp.get("treatment_n"),
            "control_approval_rate": exp.get("control_approval_rate"),
            "treatment_approval_rate": exp.get("treatment_approval_rate"),
            "approval_rate_lift_pct": exp.get("approval_rate_lift_pct"),
            "profit_lift_pct": exp.get("profit_lift_pct"),
            "chi2_stat": exp.get("chi2_stat"),
            "p_value": exp.get("p_value"),
            "is_significant": exp.get("is_significant"),
            "recommendation_rationale": exp.get("recommendation_rationale"),
            "started_at": exp.get("started_at"),
            "ended_at": exp.get("ended_at"),
            "recorded_at": ts,
        }]

    # ------------------------------------------------------------------
    # Core run
    # ------------------------------------------------------------------

    def _run(self, payload: Dict[str, Any]) -> AgentResult:
        run_id: str = payload.get("run_id") or str(uuid.uuid4())
        mode: str = payload.get("mode", self.default_mode)
        tenant_id: str = str(payload.get("tenant_id", ""))

        if not _BQ_READY:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.SUCCESS,
                payload={
                    "tables_written": [],
                    "rows_written": {},
                    "write_mode": mode,
                    "bq_dataset": self.dataset,
                    "bq_project": self.project,
                },
                warnings=["google-cloud-bigquery not available — writes skipped"],
            )

        self._ensure_infra()

        # Materialise rows for each table
        tasks: List[tuple[str, List[dict]]] = [
            ("feature_vectors",     self._build_feature_rows(
                _safe_list(payload.get("features", [])), run_id, tenant_id)),
            ("model_scores",        self._build_score_rows(
                _safe_list(payload.get("scores", [])), run_id, tenant_id)),
            ("credit_decisions",    self._build_decision_rows(
                _safe_list(payload.get("decisions", [])), run_id, tenant_id)),
            ("explanations",        self._build_explanation_rows(
                _safe_list(payload.get("explanations", [])), run_id, tenant_id)),
            ("drift_reports",       self._build_drift_rows(
                payload.get("drift_report") or {}, run_id)),
            ("fair_lending_reports", self._build_fair_lending_rows(
                payload.get("fair_lending") or {}, run_id)),
            ("experiment_results",  self._build_experiment_rows(
                payload.get("experiment") or {}, run_id)),
        ]

        tables_written: List[str] = []
        rows_written: Dict[str, int] = {}
        write_errors: List[str] = []

        for logical_table, rows in tasks:
            if not rows:
                continue
            # Sanitise all values to JSON-safe types before streaming
            safe_rows = [_to_json_safe(r) for r in rows]
            try:
                n = self._write(safe_rows, logical_table, mode)
                tables_written.append(logical_table)
                rows_written[logical_table] = n
                logger.info("[BQWriterAgent] Wrote %d rows → %s (%s)", n, logical_table, mode)
            except Exception as exc:  # noqa: BLE001
                msg = f"Failed to write {logical_table}: {exc}"
                logger.error("[BQWriterAgent] %s", msg)
                write_errors.append(msg)

        status = AgentStatus.PARTIAL if write_errors else AgentStatus.SUCCESS
        return AgentResult(
            agent_name=self.name,
            status=status,
            payload={
                "tables_written": tables_written,
                "rows_written": rows_written,
                "write_mode": mode,
                "bq_dataset": self.dataset,
                "bq_project": self.project,
            },
            errors=write_errors,
        )
