"""
Orchestration Pipeline
=======================
Prefect-style DAG orchestrator for the credit risk platform.
Runs agents in the correct topological order with:
  - Configurable retry logic
  - Per-stage timeouts
  - Result checkpointing
  - Structured logging for every stage

Pipeline DAG:
  DataIngestionAgent
       ↓
  FeatureEngineeringAgent
       ↓
  RiskModelingAgent ──────────────────── ExperimentationAgent (if active)
       ↓
  DecisionEngineAgent
       ↓
  ExplainabilityAgent
       ↓
  [Output: PipelineRun record]
       ↓ (async / scheduled)
  MonitoringAgent

Usage
-----
    from orchestration.pipeline import CreditRiskPipeline
    pipeline = CreditRiskPipeline.from_config()
    result = pipeline.run(applicant_dicts=[{...}])
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml

from agents.base import AgentResult, AgentStatus
from agents.data_ingestion_agent import DataIngestionAgent
from agents.decision_engine_agent import DecisionEngineAgent
from agents.explainability_agent import ExplainabilityAgent
from agents.experimentation_agent import ExperimentationAgent
from agents.feature_engineering_agent import FeatureEngineeringAgent
from agents.bq_writer_agent import BQWriterAgent
from agents.monitoring_agent import MonitoringAgent
from agents.risk_modeling_agent import RiskModelingAgent
from config_registry.service import ConfigRegistryService  # P2.1 — tenant config

logger = logging.getLogger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "agent_config.yaml")

# P2.1 — Shared config registry for tenant policy resolution
_CONFIG_REGISTRY = ConfigRegistryService()


# ---------------------------------------------------------------------------
# Pipeline run record
# ---------------------------------------------------------------------------


@dataclass
class StageResult:
    stage: str
    status: str
    duration_seconds: float
    payload_summary: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


@dataclass
class PipelineRun:
    run_id: str
    started_at: str
    completed_at: Optional[str]
    status: str                         # "success" | "failure" | "partial"
    tenant_id: str = ""
    stages: List[StageResult] = field(default_factory=list)
    final_payload: Dict[str, Any] = field(default_factory=dict)
    total_duration_seconds: float = 0.0

    def add_stage(self, result: AgentResult) -> None:
        summary: Dict[str, Any] = {}
        p = result.payload
        if "stats" in p:
            summary["stats"] = p["stats"]
        if "feature_version" in p:
            summary["feature_version"] = p["feature_version"]
        if "model_version" in p:
            summary["model_version"] = p["model_version"]
        self.stages.append(
            StageResult(
                stage=result.agent_name,
                status=result.status.value,
                duration_seconds=round(result.duration_seconds, 4),
                payload_summary=summary,
                errors=result.errors,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tenant_id": self.tenant_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "stages": [
                {
                    "stage": s.stage,
                    "status": s.status,
                    "duration_s": s.duration_seconds,
                    "summary": s.payload_summary,
                    "errors": s.errors,
                }
                for s in self.stages
            ],
            "total_duration_seconds": round(self.total_duration_seconds, 3),
        }


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------


def with_retry(fn, attempts: int = 3, backoff: float = 2.0):
    """Retry a callable up to `attempts` times with exponential backoff."""
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts - 1:
                raise
            wait = backoff ** attempt
            logger.warning("Attempt %d failed: %s. Retrying in %.1fs…", attempt + 1, exc, wait)
            time.sleep(wait)


# ---------------------------------------------------------------------------
# CreditRiskPipeline
# ---------------------------------------------------------------------------


class CreditRiskPipeline:
    """
    Orchestrates all agents in a linear pipeline with retry + timeout support.
    Designed for both online (single record) and offline (batch) execution.
    """

    def __init__(
        self,
        ingestion_agent: DataIngestionAgent,
        feature_agent: FeatureEngineeringAgent,
        modeling_agent: RiskModelingAgent,
        decision_agent: DecisionEngineAgent,
        explain_agent: ExplainabilityAgent,
        monitoring_agent: Optional[MonitoringAgent] = None,
        experimentation_agent: Optional[ExperimentationAgent] = None,
        bq_writer_agent: Optional[BQWriterAgent] = None,
        orchestration_config: Optional[Dict[str, Any]] = None,
    ):
        self._ingestion = ingestion_agent
        self._features = feature_agent
        self._modeling = modeling_agent
        self._decision = decision_agent
        self._explain = explain_agent
        self._monitoring = monitoring_agent
        self._experimentation = experimentation_agent
        self._bq_writer = bq_writer_agent
        self._orch_cfg = orchestration_config or {}
        self._retry = self._orch_cfg.get("retry_attempts", 3)
        self._backoff = self._orch_cfg.get("retry_backoff_seconds", 2.0)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config_path: str = _CONFIG_PATH) -> "CreditRiskPipeline":
        """Instantiate the full pipeline from agent_config.yaml."""
        cfg: Dict[str, Any] = {}
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f) or {}

        bq_cfg = cfg.get("bigquery", {})
        bq_writer: Optional[BQWriterAgent] = None
        if bq_cfg.get("enabled", True):
            bq_writer = BQWriterAgent(config=cfg)

        pipeline = cls(
            ingestion_agent=DataIngestionAgent(config=cfg.get("data_ingestion", {})),
            feature_agent=FeatureEngineeringAgent(config=cfg.get("feature_engineering", {})),
            modeling_agent=RiskModelingAgent(config=cfg.get("risk_modeling", {})),
            decision_agent=DecisionEngineAgent(config=cfg.get("decision_engine", {})),
            explain_agent=ExplainabilityAgent(config=cfg.get("explainability", {})),
            monitoring_agent=MonitoringAgent(config=cfg.get("monitoring", {})),
            experimentation_agent=ExperimentationAgent(config=cfg.get("experimentation", {})),
            bq_writer_agent=bq_writer,
            orchestration_config=cfg.get("orchestration", {}),
        )
        # G3-A: Store default_tenant_id from YAML for batch callers.
        # Callers must still pass tenant_id explicitly — this is only a convenience
        # accessor so they can do pipeline.run(..., tenant_id=pipeline._default_tenant_id).
        pipeline._default_tenant_id: Optional[str] = cfg.get("default_tenant_id", None)
        return pipeline

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        applicant_dicts: List[Dict[str, Any]],
        tenant_id: str,                          # now required, no default
        experiment_id: Optional[str] = None,
        use_challenger: bool = False,
        source: str = "pipeline",
    ) -> PipelineRun:
        """
        Execute the full pipeline for a list of applicant records.

        Returns a PipelineRun with per-stage timing and the final merged payload.

        Parameters
        ----------
        tenant_id : str
            Required. The tenant ID extracted from the request JWT.  Used to
            scope all audit writes and to resolve per-tenant policy config.
        """
        # G3-A: Guard — tenant_id is required for all pipeline runs
        if not tenant_id or not tenant_id.strip():
            raise ValueError(
                "tenant_id is required for all pipeline runs. "
                "Pass the tenant_id extracted from the request JWT."
            )

        # P2.1 — Resolve per-tenant config for this run
        tenant_cfg: Dict[str, Any] = _CONFIG_REGISTRY.resolve(tenant_id, fallback={})
        if tenant_cfg:
            logger.info(
                "Pipeline run using tenant config for tenant=%s "
                "policy_cutoffs=%s feature_toggles=%s",
                tenant_id,
                list(tenant_cfg.get("policy_cutoffs", {}).keys()),
                list(tenant_cfg.get("feature_toggles", {}).keys()),
            )

        run_id = str(uuid.uuid4())
        pipeline_run = PipelineRun(
            run_id=run_id,
            tenant_id=tenant_id,
            started_at=datetime.utcnow().isoformat(),
            completed_at=None,
            status="running",
        )
        t_pipeline_start = time.perf_counter()

        logger.info("Pipeline run %s started — %d records", run_id, len(applicant_dicts))

        try:
            # ── Stage 1: Data Ingestion ──────────────────────────────────
            ingest_result = with_retry(
                lambda: self._ingestion.execute({"records": applicant_dicts, "source": source}),
                attempts=self._retry,
                backoff=self._backoff,
            )
            pipeline_run.add_stage(ingest_result)
            if ingest_result.status == AgentStatus.FAILURE:
                raise RuntimeError(f"DataIngestionAgent failed: {ingest_result.errors}")

            validated = ingest_result.payload["validated"]
            if not validated:
                raise RuntimeError("Zero records passed ingestion validation")

            # ── Stage 2: Feature Engineering (pass feature_toggles if configured) ──
            feat_payload: Dict[str, Any] = {"validated": validated}
            if tenant_cfg.get("feature_toggles"):
                feat_payload["feature_toggles"] = tenant_cfg["feature_toggles"]
            feat_result = with_retry(
                lambda: self._features.execute(feat_payload),
                attempts=self._retry,
                backoff=self._backoff,
            )
            pipeline_run.add_stage(feat_result)
            feat_result.raise_on_failure()

            # ── Stage 3: Risk Modeling ───────────────────────────────────
            model_result = with_retry(
                lambda: self._modeling.execute({
                    "feature_df": feat_result.payload["feature_df"],
                    "use_challenger": use_challenger,
                }),
                attempts=self._retry,
                backoff=self._backoff,
            )
            pipeline_run.add_stage(model_result)
            model_result.raise_on_failure()

            # ── Stage 4: Decision Engine (pass tenant policy_cutoffs) ────
            dec_payload: Dict[str, Any] = {
                "model_scores": model_result.payload["model_scores"],
                "validated": validated,
                "experiment_id": experiment_id,
            }
            if tenant_cfg.get("policy_cutoffs"):
                dec_payload["policy_overrides"] = tenant_cfg["policy_cutoffs"]
            dec_payload["tenant_id"] = tenant_id
            dec_result = with_retry(
                lambda: self._decision.execute(dec_payload),
                attempts=self._retry,
                backoff=self._backoff,
            )
            pipeline_run.add_stage(dec_result)
            dec_result.raise_on_failure()

            # ── Stage 5: Explainability ──────────────────────────────────
            explain_result = self._explain.execute({
                "model_scores": model_result.payload["model_scores"],
                "decisions": dec_result.payload["decisions"],
                "feature_vectors": feat_result.payload["feature_vectors"],
            })
            pipeline_run.add_stage(explain_result)

            # ── Assemble final payload ───────────────────────────────────
            pipeline_run.final_payload = {
                "run_id": run_id,
                "ingestion_stats": ingest_result.payload.get("stats", {}),
                "feature_version": feat_result.payload.get("feature_version"),
                "model_version": model_result.payload.get("model_version"),
                "decision_stats": dec_result.payload.get("stats", {}),
                "decisions": dec_result.payload.get("decisions", []),
                "model_scores": model_result.payload.get("model_scores", []),
                "feature_vectors": feat_result.payload.get("feature_vectors", []),
                "explanations": explain_result.payload.get("explanations", []),
                "adverse_action_notices": explain_result.payload.get("adverse_action_notices", []),
                "quarantined": ingest_result.payload.get("quarantined", []),
            }

            pipeline_run.status = "success"
            logger.info(
                "Pipeline run %s SUCCESS — approved=%d, rejected=%d, review=%d",
                run_id,
                dec_result.payload["stats"]["approved"],
                dec_result.payload["stats"]["rejected"],
                dec_result.payload["stats"]["manual_review"],
            )

            # ── Stage 6: BigQuery write (fire-and-forget, non-blocking) ──
            if self._bq_writer is not None:
                try:
                    bq_payload = dict(pipeline_run.final_payload)
                    bq_payload["features"] = feat_result.payload.get("feature_vectors", [])
                    bq_payload["scores"]   = model_result.payload.get("model_scores", [])
                    bq_payload["decisions"] = dec_result.payload.get("decisions", [])
                    bq_payload["explanations"] = explain_result.payload.get("explanations", [])
                    bq_payload["tenant_id"] = tenant_id
                    bq_result = self._bq_writer.execute(bq_payload)
                    pipeline_run.add_stage(bq_result)
                    if bq_result.ok:
                        logger.info(
                            "[BQWriter] Wrote to tables: %s",
                            bq_result.payload.get("tables_written", []),
                        )
                    else:
                        logger.warning("[BQWriter] Write completed with warnings: %s", bq_result.warnings)
                except Exception as bq_exc:  # noqa: BLE001
                    logger.warning("[BQWriter] Non-fatal write failure: %s", bq_exc)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Pipeline run %s FAILED", run_id)
            pipeline_run.status = "failure"
            pipeline_run.final_payload = {"error": str(exc)}

        finally:
            pipeline_run.total_duration_seconds = time.perf_counter() - t_pipeline_start
            pipeline_run.completed_at = datetime.utcnow().isoformat()

        return pipeline_run

    # ------------------------------------------------------------------
    # Batch mode (chunked)
    # ------------------------------------------------------------------

    def run_batch(
        self,
        applicant_dicts: List[Dict[str, Any]],
        chunk_size: int = 1000,
        **kwargs,
    ) -> List[PipelineRun]:
        """Split a large batch into chunks and run each as a pipeline."""
        runs: List[PipelineRun] = []
        for i in range(0, len(applicant_dicts), chunk_size):
            chunk = applicant_dicts[i : i + chunk_size]
            logger.info(
                "Batch chunk %d/%d (%d records)",
                i // chunk_size + 1,
                (len(applicant_dicts) - 1) // chunk_size + 1,
                len(chunk),
            )
            run = self.run(chunk, **kwargs)
            runs.append(run)
        return runs
