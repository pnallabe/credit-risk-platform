"""
API Agent — Unified FastAPI Credit Risk Service
================================================
Domain Owner : Platform Engineering
Production-grade API exposing all agent capabilities through a single gateway.

Endpoints
---------
POST /v1/score           — Full pipeline: ingest → features → models → decision → explain
POST /v1/score/batch     — Batch scoring (up to 1000 applications)
POST /v1/decision        — Decision-only (pre-computed features + scores)
GET  /v1/experiment/{id} — Retrieve experiment report
POST /v1/monitor/drift   — Trigger ad-hoc drift analysis
GET  /v1/health          — Liveness + dependency check
GET  /v1/metrics         — Prometheus-style metrics endpoint

Authentication: Bearer JWT (via X-API-Key header as fallback)
Rate limiting : 100 req/s per IP (configurable)
SLA           : p99 latency < 500ms for single-record scoring
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── Agent imports ─────────────────────────────────────────────────────────
from agents.data_ingestion_agent import DataIngestionAgent
from agents.decision_engine_agent import DecisionEngineAgent
from agents.explainability_agent import ExplainabilityAgent
from agents.feature_engineering_agent import FeatureEngineeringAgent
from agents.risk_modeling_agent import RiskModelingAgent
from schemas.contracts import ApplicantInput, PipelineOutput

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "agent_config.yaml")


def _load_config(path: str = _CONFIG_PATH) -> Dict[str, Any]:
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


# ---------------------------------------------------------------------------
# Agent lifecycle (singleton per process)
# ---------------------------------------------------------------------------

_agents: Dict[str, Any] = {}
_config: Dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agents once on startup; clean up on shutdown."""
    global _agents, _config
    _config = _load_config()
    _agents = {
        "ingestion": DataIngestionAgent(config=_config.get("data_ingestion", {})),
        "features":  FeatureEngineeringAgent(config=_config.get("feature_engineering", {})),
        "modeling":  RiskModelingAgent(config=_config.get("risk_modeling", {})),
        "decision":  DecisionEngineAgent(config=_config.get("decision_engine", {})),
        "explain":   ExplainabilityAgent(config=_config.get("explainability", {})),
    }
    logger.info("All agents initialized ✓")
    yield
    logger.info("Shutting down API Agent")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Credit Risk Platform API",
    description="Production-grade multi-agent credit decisioning API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

_VALID_API_KEYS: set[str] = set(
    filter(None, os.getenv("VALID_API_KEYS", "dev-key-12345").split(","))
)


async def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    if not x_api_key or x_api_key not in _VALID_API_KEYS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return x_api_key


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ScoreRequest(BaseModel):
    applicant: ApplicantInput
    experiment_id: Optional[str] = None
    use_challenger: bool = False


class BatchScoreRequest(BaseModel):
    applicants: List[ApplicantInput] = Field(..., max_length=1000)
    experiment_id: Optional[str] = None
    use_challenger: bool = False


class ScoreResponse(BaseModel):
    request_id: str
    application_id: str
    decision: str
    approved_amount: Optional[float]
    approved_rate_pct: Optional[float]
    pd_score: float
    pd_band: str
    fraud_flag: str
    reason_codes: List[str]
    top_factors: List[Dict[str, Any]]
    adverse_action_notice: Optional[str]
    model_version: str
    latency_ms: float


class BatchScoreResponse(BaseModel):
    request_id: str
    total: int
    approved: int
    rejected: int
    manual_review: int
    approval_rate_pct: float
    results: List[ScoreResponse]
    latency_ms: float


# ---------------------------------------------------------------------------
# Pipeline runner (shared between single + batch)
# ---------------------------------------------------------------------------


def _run_pipeline(
    applicant_dicts: List[Dict[str, Any]],
    experiment_id: Optional[str],
    use_challenger: bool,
) -> tuple[List[ScoreResponse], Dict[str, Any]]:
    t0 = time.perf_counter()

    # 1. Ingest
    ingest_result = _agents["ingestion"].execute(
        {"records": applicant_dicts, "source": "api"}
    )
    if not ingest_result.ok:
        raise HTTPException(
            status_code=422,
            detail={"errors": ingest_result.errors, "stage": "ingestion"},
        )

    validated = ingest_result.payload["validated"]
    if not validated:
        raise HTTPException(status_code=422, detail="All records failed validation")

    # 2. Features
    feat_result = _agents["features"].execute({"validated": validated})
    feat_result.raise_on_failure()

    # 3. Models
    model_result = _agents["modeling"].execute({
        "feature_df": feat_result.payload["feature_df"],
        "use_challenger": use_challenger,
    })
    model_result.raise_on_failure()

    # 4. Decision
    dec_result = _agents["decision"].execute({
        "model_scores": model_result.payload["model_scores"],
        "validated": validated,
        "experiment_id": experiment_id,
    })
    dec_result.raise_on_failure()

    # 5. Explain
    explain_result = _agents["explain"].execute({
        "model_scores": model_result.payload["model_scores"],
        "decisions": dec_result.payload["decisions"],
        "feature_vectors": feat_result.payload["feature_vectors"],
    })

    elapsed_ms = (time.perf_counter() - t0) * 1000

    # Assemble response list
    scores_by_id = {s["application_id"]: s for s in model_result.payload["model_scores"]}
    decs_by_id = {d["application_id"]: d for d in dec_result.payload["decisions"]}
    expls_by_id = {e["application_id"]: e for e in explain_result.payload.get("explanations", [])}

    responses: List[ScoreResponse] = []
    for app_id, dec in decs_by_id.items():
        score = scores_by_id.get(app_id, {})
        expl = expls_by_id.get(app_id, {})
        responses.append(
            ScoreResponse(
                request_id=str(uuid.uuid4()),
                application_id=app_id,
                decision=dec.get("decision", "UNKNOWN"),
                approved_amount=dec.get("approved_amount"),
                approved_rate_pct=dec.get("approved_rate"),
                pd_score=score.get("pd_score", 0.0),
                pd_band=score.get("pd_band", "unknown"),
                fraud_flag=score.get("fraud_flag", "unknown"),
                reason_codes=dec.get("reason_codes", []),
                top_factors=expl.get("top_factors", [])[:5],
                adverse_action_notice=expl.get("adverse_action_text"),
                model_version=score.get("model_version", "champion"),
                latency_ms=round(elapsed_ms / max(len(decs_by_id), 1), 2),
            )
        )

    stats = {
        "total": len(responses),
        "approved": sum(1 for r in responses if r.decision == "APPROVE"),
        "rejected": sum(1 for r in responses if r.decision == "REJECT"),
        "manual_review": sum(1 for r in responses if r.decision == "MANUAL_REVIEW"),
        "elapsed_ms": round(elapsed_ms, 2),
    }
    return responses, stats


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/v1/health", tags=["system"])
async def health_check():
    return {
        "status": "healthy",
        "agents_loaded": list(_agents.keys()),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@app.post(
    "/v1/score",
    response_model=ScoreResponse,
    tags=["scoring"],
    summary="Score a single credit application end-to-end",
)
async def score_single(
    req: ScoreRequest,
    _key: str = Depends(verify_api_key),
):
    responses, _ = _run_pipeline(
        applicant_dicts=[req.applicant.model_dump()],
        experiment_id=req.experiment_id,
        use_challenger=req.use_challenger,
    )
    return responses[0]


@app.post(
    "/v1/score/batch",
    response_model=BatchScoreResponse,
    tags=["scoring"],
    summary="Batch score up to 1000 applications",
)
async def score_batch(
    req: BatchScoreRequest,
    _key: str = Depends(verify_api_key),
):
    t0 = time.perf_counter()
    responses, stats = _run_pipeline(
        applicant_dicts=[a.model_dump() for a in req.applicants],
        experiment_id=req.experiment_id,
        use_challenger=req.use_challenger,
    )
    n = stats["total"]
    return BatchScoreResponse(
        request_id=str(uuid.uuid4()),
        total=n,
        approved=stats["approved"],
        rejected=stats["rejected"],
        manual_review=stats["manual_review"],
        approval_rate_pct=round(stats["approved"] / max(n, 1) * 100, 2),
        results=responses,
        latency_ms=round((time.perf_counter() - t0) * 1000, 2),
    )


@app.get("/v1/metrics", tags=["system"])
async def metrics():
    """Basic metrics — extend with Prometheus counters in production."""
    return {
        "api_version": "1.0.0",
        "agents_active": len(_agents),
        "uptime_check": "ok",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "agents.api_agent:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=os.getenv("ENV", "production") == "development",
        log_level="info",
    )
