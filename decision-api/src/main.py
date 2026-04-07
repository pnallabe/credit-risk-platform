"""
Decision API — FastAPI service that orchestrates the full underwriting pipeline.

POST /v1/decisions          — Run full pipeline, return DecisionResponse
POST /v1/decisions/batch    — Batch scoring (up to 1000 applications)
GET  /v1/decisions/{id}/audit — Full audit record for regulators
GET  /v1/health             — Returns model versions and DB status
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# Middleware (P1.1: rate-limiting and idempotency)
# Use sys.path-relative imports — decision-api/src is on sys.path at runtime
import sys as _sys
_src_dir = str(Path(__file__).parent)
if _src_dir not in _sys.path:
    _sys.path.insert(0, _src_dir)

from middleware.idempotency import IdempotencyMiddleware  # noqa: E402
from middleware.rate_limit import RateLimitMiddleware  # noqa: E402

# Make project root importable
ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from audit.logger import get_audit_record, log_decision  # noqa: E402
from config_registry.service import ConfigRegistryService  # noqa: E402  (P2.1)
from credit_core.features import compute_feature_matrix  # noqa: E402
from credit_core.policy import evaluate_policy  # noqa: E402
from decision_engine.engine import (  # noqa: E402
    CreditResult,
    DecisionRequest,
    FraudResult,
    make_decision,
)
from feature_pipeline.features import FeaturePipelineConfig  # noqa: E402
from models.credit_risk.predict import predict_pd  # noqa: E402
from models.fraud_detection.predict import predict_fraud  # noqa: E402
from models.model_loader import cache_info as _model_cache_info  # noqa: E402
from models.model_loader import load_model as _load_model_cached  # noqa: E402
from models.pricing.engine import PricingConfig, calculate_pricing  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./decision_audit.db",
)

# ---------------------------------------------------------------------------
# CRIT-01: JWT_SECRET must be explicitly set to a non-default strong secret.
# The API will refuse to start if the variable is absent or left as the
# dev placeholder — preventing an authentication bypass in misconfigured envs.
# ---------------------------------------------------------------------------
_JWT_SECRET_RAW = os.getenv("JWT_SECRET", "")
_JWT_SECRET_DEV_PLACEHOLDER = "your-secret-key-change-in-production"  # pragma: allowlist secret
if not _JWT_SECRET_RAW:
    raise RuntimeError(
        "[CRIT-01] JWT_SECRET environment variable is not set. "
        "Generate a strong secret and configure it via Secret Manager or .env "
        "before starting this service."
    )
if _JWT_SECRET_RAW == _JWT_SECRET_DEV_PLACEHOLDER:
    raise RuntimeError(
        "[CRIT-01] JWT_SECRET is still the development placeholder value. "
        "Generate a strong, unique secret and set JWT_SECRET before deploying."
    )
JWT_SECRET: str = _JWT_SECRET_RAW

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
FRAUD_MODEL_PATH = os.getenv("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
RISK_MODEL_PATH = os.getenv("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

FEATURE_CONFIG = FeaturePipelineConfig()
PRICING_CONFIG = PricingConfig()

# P2.1 — Process-level config registry (resolves active tenant config at request time)
_CONFIG_REGISTRY: ConfigRegistryService = ConfigRegistryService()

# ---------------------------------------------------------------------------
# CRIT-04: Semaphore cap for the batch endpoint.  Without this, a 1000-item
# batch launches 1000 concurrent pipelines, exhausting DB connections and
# Python threadpool workers and cascading into 500s for real-time traffic.
# Adjust BATCH_CONCURRENCY_LIMIT via env; default is 50 concurrent pipelines.
# ---------------------------------------------------------------------------
BATCH_CONCURRENCY_LIMIT: int = int(os.getenv("BATCH_CONCURRENCY_LIMIT", "50"))
_batch_semaphore: Optional[asyncio.Semaphore] = None

# Pre-load models at startup (fail-hard — see CRIT-03)
_fraud_model: Any = None
_risk_model: Any = None


def _load_models() -> None:
    """Load both models at startup.  Raises RuntimeError if either fails.

    CRIT-03: The API must not start — or serve any traffic — when a required
    model artifact is unavailable.  Swallowing load errors allows the service
    to pass health checks while silently returning junk (or 500s) for every
    real decision request.

    P1.4: Delegates to models.model_loader so models are stored in the
    process-level cache.  Per-request hot paths are then pure cache hits.
    """
    global _fraud_model, _risk_model

    try:
        _fraud_model = _load_model_cached(FRAUD_MODEL_PATH, version="v1")
        logger.info("Fraud model loaded from %s", FRAUD_MODEL_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"[CRIT-03] Failed to load fraud model from '{FRAUD_MODEL_PATH}': {exc}. "
            "Verify the artifact path and set FRAUD_MODEL_PATH if needed."
        ) from exc

    try:
        _risk_model = _load_model_cached(RISK_MODEL_PATH, version="v1")
        logger.info("Credit risk model loaded from %s", RISK_MODEL_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"[CRIT-03] Failed to load credit risk model from '{RISK_MODEL_PATH}': {exc}. "
            "Verify the artifact path and set RISK_MODEL_PATH if needed."
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Credit Risk Decision API",
    description="Orchestrates fraud detection, credit risk scoring, pricing, and decision engine.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CRIT-02: Restrict CORS to explicitly allow-listed origins.
# allow_origins=["*"] on a financial decisioning API allows any website to
# make authenticated cross-origin requests and read PD scores / reason codes.
# Set CORS_ALLOWED_ORIGINS to a comma-separated list of trusted origins,
# e.g. "https://app.yourdomain.com,https://analytics.yourdomain.com".
# ---------------------------------------------------------------------------
_cors_raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
_CORS_ORIGINS: List[str] = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if _cors_raw
    else []
)
if not _CORS_ORIGINS:
    logger.warning(
        "[CRIT-02] CORS_ALLOWED_ORIGINS is not configured — "
        "cross-origin requests will be blocked for all origins. "
        "Set CORS_ALLOWED_ORIGINS to allow your front-end domains."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=None,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    allow_credentials=False,
)

# P1.1 — Rate limiting (token-bucket, scoped by tenant_id × route)
app.add_middleware(RateLimitMiddleware)
# P1.1 — Idempotency (replay guard for POST /v1/decisions*)
app.add_middleware(IdempotencyMiddleware)


@app.on_event("startup")
async def startup_event() -> None:
    # CRIT-03: raises RuntimeError → service refuses to start if models absent
    _load_models()
    # CRIT-04: create semaphore inside the running event loop
    global _batch_semaphore
    _batch_semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)
    logger.info("Batch concurrency limit: %d concurrent pipelines", BATCH_CONCURRENCY_LIMIT)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)


async def verify_bearer(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Verify Bearer JWT token and require 'tenant_id' claim.

    CRIT-01: The development bypass (skipping auth when JWT_SECRET matches the
    placeholder) has been removed.  The secret is now validated at startup so
    this function always enforces authentication.

    P0.1 (tenant isolation): tenant_id must be present in the JWT payload and
    is NEVER accepted from the request body.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        import jwt
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not payload.get("tenant_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT must include 'tenant_id' claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoanApplicationRequest(BaseModel):
    """Input payload for a single loan underwriting decision."""

    application_id: str = Field(..., description="UUID identifying the application")
    customer_id: str
    credit_score: int = Field(..., ge=300, le=850)
    annual_income: float = Field(..., gt=0)
    employment_status: str = Field(..., pattern="^(employed|self-employed|unemployed|retired)$")
    employer_tenure_months: int = Field(default=0, ge=0)
    debt_to_income_ratio: float = Field(..., ge=0.0, le=0.65)
    existing_debt_amount: float = Field(..., ge=0.0)
    loan_amount: float = Field(..., ge=1000.0, le=100000.0)
    loan_purpose: str
    loan_term_months: Literal[12, 24, 36, 48, 60]
    num_open_accounts: int = Field(default=0, ge=0)
    num_derogatory_marks: int = Field(default=0, ge=0)
    months_since_last_delinquency: Optional[int] = None
    # CRIT-05: borrower state is required to enforce state-level APR caps.
    # Use ISO 3166-2 two-letter state/territory codes (e.g. "CA", "IL", "CO").
    borrower_state: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=2,
        pattern="^[A-Z]{2}$",
        description="ISO 3166-2 two-letter US state code used for APR cap enforcement.",
    )


class ExplanationFactor(BaseModel):
    feature: str
    shap_value: float
    direction: str


class DecisionResponse(BaseModel):
    """Full decision response including explanation and audit metadata."""

    application_id: str
    decision: str
    recommended_rate: Optional[float]
    loan_terms: Dict[str, Any]
    reason_codes: List[str]
    explanation: List[ExplanationFactor]
    decision_latency_ms: int
    audit_log_id: str
    fraud_probability: float
    pd_score: float


class BatchSummary(BaseModel):
    total: int
    approved: int
    rejected: int
    manual_review: int
    avg_latency_ms: float


class BatchDecisionResponse(BaseModel):
    results: List[DecisionResponse]
    batch_summary: BatchSummary


# ---------------------------------------------------------------------------
# Pipeline helper
# ---------------------------------------------------------------------------

import pandas as pd  # noqa: E402


def _build_feature_df(app_req: LoanApplicationRequest) -> pd.DataFrame:
    """Convert a LoanApplicationRequest into a features DataFrame.

    Delegates to ``credit_core.features.compute_feature_matrix`` — the
    canonical implementation shared with the agent pipeline.
    """
    raw = {
        "credit_score": [app_req.credit_score],
        "annual_income": [float(app_req.annual_income)],
        "employment_status": [app_req.employment_status],
        "employer_tenure_months": [app_req.employer_tenure_months],
        "debt_to_income_ratio": [float(app_req.debt_to_income_ratio)],
        "existing_debt_amount": [float(app_req.existing_debt_amount)],
        "loan_amount": [float(app_req.loan_amount)],
        "loan_term_months": [int(app_req.loan_term_months)],
        "num_open_accounts": [app_req.num_open_accounts],
        "num_derogatory_marks": [app_req.num_derogatory_marks],
        "months_since_last_delinquency": [app_req.months_since_last_delinquency],
    }
    raw_df = pd.DataFrame(raw)
    return compute_feature_matrix(raw_df, version=FEATURE_CONFIG.version)


async def _run_pipeline(
    app_req: LoanApplicationRequest,
    tenant_id: str,
) -> DecisionResponse:
    """Execute the full underwriting pipeline for a single application."""
    start = time.perf_counter()

    # P2.1 — Resolve active tenant config (policy cutoffs + feature toggles).
    # Falls back to an empty dict (platform defaults) when no config published.
    tenant_cfg = _CONFIG_REGISTRY.resolve(tenant_id, fallback={})
    policy_cutoffs = tenant_cfg.get("policy_cutoffs", {})

    # 1. Build features
    features_df = _build_feature_df(app_req)

    # 2. Fraud detection
    fraud_df = predict_fraud(features_df, _model=_fraud_model)
    fraud_prob = float(fraud_df["fraud_probability"].iloc[0])
    fraud_flag_str = str(fraud_df["fraud_flag"].iloc[0])

    # 3. Credit risk
    credit_df = predict_pd(features_df, _model=_risk_model)
    pd_score = float(credit_df["pd_score"].iloc[0])
    pd_band = str(credit_df["pd_band"].iloc[0])

    # 4. Pricing (CRIT-05: pass borrower_state so state APR cap is applied)
    pricing_result = calculate_pricing(
        pd_score=pd_score,
        fraud_flag=fraud_flag_str,
        loan_amount=float(app_req.loan_amount),
        config=PRICING_CONFIG,
        borrower_state=app_req.borrower_state,
    )

    # 5. Decision engine — pass tenant policy_cutoffs so per-tenant thresholds apply
    from models.fraud_detection.predict import THRESHOLD_REJECT, THRESHOLD_REVIEW
    decision_req = DecisionRequest(
        application_id=app_req.application_id,
        fraud_result=FraudResult(fraud_probability=fraud_prob, fraud_flag=fraud_flag_str),
        credit_result=CreditResult(pd_score=pd_score, pd_band=pd_band),
        pricing_result=pricing_result,
        loan_amount=float(app_req.loan_amount),
        loan_term_months=int(app_req.loan_term_months),
        debt_to_income_ratio=float(app_req.debt_to_income_ratio),
        num_open_accounts=app_req.num_open_accounts,
        annual_income=float(app_req.annual_income),
    )
    # Merge tenant cutoffs into the engine call when supported
    decision_result = make_decision(decision_req, policy_overrides=policy_cutoffs or None)

    # 6. SHAP explanation (best effort)
    explanation_factors: List[ExplanationFactor] = []
    try:
        from explainability.shap_explainer import explain_prediction
        decision_label = decision_result.decision.lower()
        shap_result = explain_prediction(
            _risk_model if _risk_model is not None else _fraud_model,
            features_df[FEATURE_CONFIG.feature_list],
            decision_label=decision_label,
            top_n=3,
        )
        for f in shap_result.top_positive_factors[:2] + shap_result.top_negative_factors[:1]:
            explanation_factors.append(
                ExplanationFactor(
                    feature=f["feature"],
                    shap_value=f["shap_value"],
                    direction=f["direction"],
                )
            )
    except Exception as exc:
        logger.warning("SHAP explanation failed: %s", exc)

    latency_ms = int((time.perf_counter() - start) * 1000)

    # 7. Audit log
    input_features_dict = {
        "customer_id": app_req.customer_id,
        "pd_score": pd_score,
        "fraud_probability": fraud_prob,
        **features_df[FEATURE_CONFIG.feature_list].iloc[0].to_dict(),
    }
    audit_log_id = await log_decision(
        decision_result=decision_result,
        feature_version=FEATURE_CONFIG.version,
        model_versions={"fraud": "v1", "credit_risk": "v1"},
        input_features=input_features_dict,
        db_url=DB_URL,
        tenant_id=tenant_id,
    )

    return DecisionResponse(
        application_id=app_req.application_id,
        decision=decision_result.decision,
        recommended_rate=decision_result.recommended_rate,
        loan_terms=decision_result.loan_terms,
        reason_codes=decision_result.reason_codes,
        explanation=explanation_factors,
        decision_latency_ms=latency_ms,
        audit_log_id=audit_log_id,
        fraud_probability=fraud_prob,
        pd_score=pd_score,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


# ── P2.1 Config Registry endpoints ─────────────────────────────────────────

class PublishConfigRequest(BaseModel):
    config_json: Dict[str, Any] = Field(
        ...,
        description="Versioned config dict (policy_cutoffs, feature_toggles, etc.)",
    )
    note: str = Field(..., min_length=1, description="Mandatory change rationale")


class RollbackConfigRequest(BaseModel):
    target_version: str = Field(..., description="Version tag to restore, e.g. 'v2'")
    note: str = Field(..., min_length=1, description="Mandatory rollback rationale")


@app.post(
    "/v1/config",
    status_code=201,
    summary="Publish a new tenant config version",
    tags=["Config Registry"],
)
async def publish_tenant_config(
    body: PublishConfigRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Publish a versioned config for the calling tenant. Auto-activates immediately."""
    tenant_id: str = _user["tenant_id"]
    _CONFIG_REGISTRY.ensure_tenant(tenant_id, name=tenant_id)
    try:
        cv = _CONFIG_REGISTRY.publish(
            tenant_id=tenant_id,
            config_json=body.config_json,
            approved_by=_user.get("sub", _user.get("email", tenant_id)),
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return cv.as_dict()


@app.get(
    "/v1/config",
    summary="Get active tenant config",
    tags=["Config Registry"],
)
async def get_active_config(
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return the currently active config for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    active = _CONFIG_REGISTRY.get_active(tenant_id)
    if active is None:
        return {"tenant_id": tenant_id, "active_config_version": None, "config_json": {}}
    return active.as_dict()


@app.get(
    "/v1/config/history",
    summary="List tenant config version history",
    tags=["Config Registry"],
)
async def list_config_history(
    limit: int = 20,
    _user: Dict = Depends(verify_bearer),
) -> List[Dict[str, Any]]:
    """Return config version history for the calling tenant, newest first."""
    tenant_id: str = _user["tenant_id"]
    versions = _CONFIG_REGISTRY.list_versions(tenant_id, limit=limit)
    return [v.as_dict() for v in versions]


@app.get(
    "/v1/config/{version}",
    summary="Get a specific config version snapshot",
    tags=["Config Registry"],
)
async def get_config_version(
    version: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return a specific config version for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    cv = _CONFIG_REGISTRY.get_version(tenant_id, version)
    if cv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Config version '{version}' not found for tenant '{tenant_id}'.",
        )
    return cv.as_dict()


@app.post(
    "/v1/config/rollback",
    summary="Rollback to a prior config version",
    tags=["Config Registry"],
)
async def rollback_config(
    body: RollbackConfigRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Create a new config row restoring a prior snapshot and activate it immediately."""
    tenant_id: str = _user["tenant_id"]
    try:
        event = _CONFIG_REGISTRY.rollback(
            tenant_id=tenant_id,
            target_version=body.target_version,
            rolled_back_by=_user.get("sub", _user.get("email", tenant_id)),
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {
        "tenant_id": event.tenant_id,
        "from_version": event.from_version,
        "to_version": event.to_version,
        "new_version_tag": event.new_version_tag,
        "rolled_back_by": event.rolled_back_by,
        "note": event.note,
        "timestamp": event.timestamp.isoformat(),
    }


@app.get(
    "/v1/config/audit-log",
    summary="List config audit events for this tenant",
    tags=["Config Registry"],
)
async def get_config_audit_log(
    limit: int = 50,
    _user: Dict = Depends(verify_bearer),
) -> List[Dict[str, Any]]:
    """Return the config lifecycle audit trail for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    return _CONFIG_REGISTRY.get_audit_events(tenant_id, limit=limit)



    response_model=DecisionResponse,
    status_code=200,
    summary="Run full underwriting pipeline for a single application",
    responses={
        200: {"description": "Approved or Rejected decision"},
        202: {"description": "Manual review required"},
        422: {"description": "Validation error"},
        401: {"description": "Unauthorized"},
    },
)
async def create_decision(
    application: LoanApplicationRequest,
    _user: Dict = Depends(verify_bearer),
) -> DecisionResponse:
    """Execute the full underwriting pipeline and return a decision."""
    tenant_id: str = _user["tenant_id"]
    response = await _run_pipeline(application, tenant_id=tenant_id)
    if response.decision == "MANUAL_REVIEW":
        # Return 202 Accepted for manual review — requires custom response
        from fastapi.responses import JSONResponse
        return JSONResponse(content=response.model_dump(), status_code=202)
    return response


@app.post(
    "/v1/decisions/batch",
    response_model=BatchDecisionResponse,
    summary="Score a batch of up to 1000 loan applications",
)
async def batch_decisions(
    applications: List[LoanApplicationRequest],
    _user: Dict = Depends(verify_bearer),
) -> BatchDecisionResponse:
    """Run the full pipeline for each application concurrently."""
    tenant_id: str = _user["tenant_id"]
    if len(applications) > 1000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Batch size cannot exceed 1000 applications.",
        )
    if not applications:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Batch must contain at least 1 application.",
        )

    # CRIT-04: Gate each pipeline invocation through the module-level semaphore
    # so that at most BATCH_CONCURRENCY_LIMIT pipelines run simultaneously,
    # protecting the DB connection pool and model inference threads.
    async def _bounded(app_req: LoanApplicationRequest) -> DecisionResponse:
        async with _batch_semaphore:  # type: ignore[union-attr]
            return await _run_pipeline(app_req, tenant_id=tenant_id)

    tasks = [_bounded(app) for app in applications]
    results: List[DecisionResponse] = await asyncio.gather(*tasks)

    approved = sum(1 for r in results if r.decision == "APPROVE")
    rejected = sum(1 for r in results if r.decision == "REJECT")
    manual = sum(1 for r in results if r.decision == "MANUAL_REVIEW")
    avg_latency = sum(r.decision_latency_ms for r in results) / len(results)

    return BatchDecisionResponse(
        results=results,
        batch_summary=BatchSummary(
            total=len(results),
            approved=approved,
            rejected=rejected,
            manual_review=manual,
            avg_latency_ms=round(avg_latency, 1),
        ),
    )


@app.get(
    "/v1/decisions/{application_id}/audit",
    summary="Retrieve full audit record for regulators",
)
async def get_audit(
    application_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return the complete audit record for a given application ID."""
    tenant_id: str = _user["tenant_id"]
    record = await get_audit_record(application_id, DB_URL, tenant_id=tenant_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No audit record found for application_id={application_id}",
        )
    return record


@app.get("/v1/health", summary="Health check with model and DB status")
async def health_check() -> Dict[str, Any]:
    """Return API health, model load status, and DB connectivity."""
    import importlib.metadata as meta

    db_status = "unknown"
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text

        eng = create_async_engine(DB_URL, echo=False)
        async with eng.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "ok"
        await eng.dispose()
    except Exception as exc:
        db_status = f"error: {exc}"

    return {
        "status": "ok",
        "models": {
            "fraud_detection": {
                "version": "v1",
                "loaded": _fraud_model is not None,
                "path": FRAUD_MODEL_PATH,
            },
            "credit_risk": {
                "version": "v1",
                "loaded": _risk_model is not None,
                "path": RISK_MODEL_PATH,
            },
        },
        "model_cache": _model_cache_info(),
        "feature_pipeline": {"version": FEATURE_CONFIG.version},
        "database": db_status,
    }


# ---------------------------------------------------------------------------
# Notification endpoints (Phase 13 – AI Agent scheduler)
# ---------------------------------------------------------------------------
@app.get("/v1/notifications", summary="List unread notifications")
async def list_notifications(
    limit: int = 50,
    category: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent notifications created by the AI scheduler."""
    import sqlite3

    db_path = DB_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_path.startswith("postgresql"):
        return []  # Only implemented for SQLite dev env

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM notifications"
        params: list = []
        if category:
            query += " WHERE category = ?"
            params.append(category)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


@app.patch("/v1/notifications/{notification_id}/read", summary="Mark notification as read")
async def mark_notification_read(notification_id: int) -> Dict[str, Any]:
    """Mark a single notification as read."""
    import sqlite3

    db_path = DB_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_path.startswith("postgresql"):
        return {"ok": False, "reason": "not implemented for postgres"}

    try:
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
        conn.commit()
        conn.close()
        return {"ok": True, "id": notification_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.patch("/v1/notifications/read-all", summary="Mark all notifications as read")
async def mark_all_notifications_read() -> Dict[str, Any]:
    """Mark all notifications as read."""
    import sqlite3

    db_path = DB_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_path.startswith("postgresql"):
        return {"ok": False, "reason": "not implemented for postgres"}

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("UPDATE notifications SET read = 1 WHERE read = 0")
        conn.commit()
        updated = cur.rowcount
        conn.close()
        return {"ok": True, "updated": updated}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
