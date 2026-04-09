"""
Decision API — FastAPI service that orchestrates the full underwriting pipeline.

POST /v1/decisions                        — Run full pipeline, return DecisionResponse
POST /v1/decisions/batch                  — Batch scoring (up to 1000 applications)
GET  /v1/decisions/{id}/audit             — Full audit record for regulators
GET  /v1/decisions/{id}/explanation       — G10-B: Counterfactual + SHAP + NLG explanation
GET  /v1/health                           — Returns model versions and DB status
GET  /v1/metrics                          — G12-A: Live service metrics (latency, error rate)
POST /v1/config/stage                     — G11-B: Stage a new config for four-eyes approval
POST /v1/config/approve                   — G11-B: Approve a staged config (four-eyes)
POST /v1/config/reject                    — G11-B: Reject a staged config
POST /v1/portal/token                     — G13-B: Issue a borrower portal JWT
GET  /v1/portal/applications/{id}/status  — G13-B: Borrower portal decision status
GET  /v1/portal/applications/{id}/explanation — G13-B: Borrower portal explanation
POST /v1/batch/underwrite                 — G14-B: CSV batch underwriting job submission
GET  /v1/batch/{id}/status               — G14-B: Batch job status
GET  /v1/batch/{id}/results              — G14-B: Batch job results download
POST /v1/stress-test/run                  — G15-B: Run Monte Carlo stress test
GET  /v1/stress-test/results              — G15-B: List stress test results
GET  /v1/stress-test/compare              — G15-B: Compare two quarters
POST /v1/webhooks                         — G16-B: Register a webhook endpoint
GET  /v1/webhooks                         — G16-B: List webhook registrations
GET  /v1/webhooks/{id}/deliveries         — G16-B: Webhook delivery log
DELETE /v1/webhooks/{id}                  — G16-B: Deactivate a webhook
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, Security, UploadFile, status
from fastapi.responses import JSONResponse
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
from decision_engine.policy_challenger import (  # noqa: E402  (G4-C)
    PolicyChallengerConfig,
    PolicyChallengerRouter,
    PolicySplitStore,
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

# G4-C — Policy-level champion/challenger A/B store + router
_POLICY_SPLIT_STORE: PolicySplitStore = PolicySplitStore(
    db_url=os.getenv("POLICY_SPLIT_DB_URL", "sqlite:///./policy_challenger.db")
)
_POLICY_ROUTER: PolicyChallengerRouter = PolicyChallengerRouter(store=_POLICY_SPLIT_STORE)

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

# ---------------------------------------------------------------------------
# G12-A — Service metrics (thread-safe rolling window)
# ---------------------------------------------------------------------------

import collections as _collections
import threading as _threading

_METRICS_WINDOW = int(os.getenv("METRICS_WINDOW_SIZE", "1000"))  # rolling window size


class _ServiceMetrics:
    """Thread-safe in-process service metrics collector (GAP-12).

    Stores latency samples in a fixed-size rolling deque and counts
    error/request totals since last restart.
    """

    def __init__(self, window: int = _METRICS_WINDOW) -> None:
        self._lock = _threading.Lock()
        self._latencies: _collections.deque = _collections.deque(maxlen=window)
        self._total_requests: int = 0
        self._total_5xx: int = 0
        self._started_at: str = datetime.utcnow().isoformat() + "Z"

    def record(self, latency_ms: float, is_error: bool = False) -> None:
        with self._lock:
            self._latencies.append(latency_ms)
            self._total_requests += 1
            if is_error:
                self._total_5xx += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            lats = list(self._latencies)
            total = self._total_requests
            errors = self._total_5xx

        import numpy as _np
        if lats:
            arr = _np.array(lats)
            p50 = float(_np.percentile(arr, 50))
            p95 = float(_np.percentile(arr, 95))
            p99 = float(_np.percentile(arr, 99))
            mean = float(_np.mean(arr))
        else:
            p50 = p95 = p99 = mean = 0.0

        error_rate = (errors / total) if total > 0 else 0.0
        return {
            "p50_latency_ms": round(p50, 2),
            "p95_latency_ms": round(p95, 2),
            "p99_latency_ms": round(p99, 2),
            "mean_latency_ms": round(mean, 2),
            "total_requests": total,
            "total_5xx": errors,
            "error_rate_5xx": round(error_rate, 6),
            "canary_healthy": error_rate < float(os.getenv("CANARY_ERROR_RATE_THRESHOLD", "0.01"))
                              and p99 < float(os.getenv("CANARY_P99_THRESHOLD_MS", "500")),
            "window_size": len(lats),
            "started_at": self._started_at,
        }


_METRICS = _ServiceMetrics()

# ---------------------------------------------------------------------------
# G16-B — Webhook singletons
# ---------------------------------------------------------------------------
import sys as _sys2  # noqa: E402

_project_root = str(Path(__file__).parents[3])
if _project_root not in _sys2.path:
    _sys2.path.insert(0, _project_root)

from webhooks.store import WebhookStore as _WebhookStore          # noqa: E402
from webhooks.dispatcher import WebhookDispatcher as _WebhookDispatcher  # noqa: E402

_WEBHOOK_STORE = _WebhookStore(
    db_path=os.getenv("WEBHOOK_DB_PATH", "./webhooks.db")
)
_WEBHOOK_DISPATCH = _WebhookDispatcher(store=_WEBHOOK_STORE)

# ---------------------------------------------------------------------------
# G14-B — Batch job store singleton
# ---------------------------------------------------------------------------
from batch_job_store import BatchJobStore as _BatchJobStore  # noqa: E402

_BATCH_JOB_STORE = _BatchJobStore(
    db_path=os.getenv("BATCH_JOB_DB_PATH", "./batch_jobs.db")
)


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


@app.middleware("http")
async def _metrics_middleware(request, call_next):
    """G12-A: Record per-request latency and 5xx rate for /v1/metrics."""
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - start) * 1000
    is_error = response.status_code >= 500
    _METRICS.record(latency_ms, is_error=is_error)
    return response


@app.on_event("startup")
async def startup_event() -> None:
    # CRIT-03: raises RuntimeError → service refuses to start if models absent
    _load_models()
    # CRIT-04: create semaphore inside the running event loop
    global _batch_semaphore
    _batch_semaphore = asyncio.Semaphore(BATCH_CONCURRENCY_LIMIT)
    logger.info("Batch concurrency limit: %d concurrent pipelines", BATCH_CONCURRENCY_LIMIT)
    # P1-E: Run hash-chain schema migration at startup
    try:
        from audit.logger import migrate_audit_schema
        await migrate_audit_schema(DB_URL)
        logger.info("Audit schema migration complete (hash chain columns ensured)")
    except Exception as _mig_exc:
        logger.error("Audit schema migration failed (non-fatal): %s", _mig_exc)
    # G11-A: Run config registry schema migration (adds status column idempotently)
    try:
        from config_registry.service import migrate_config_schema
        migrate_config_schema(DB_URL.replace("+aiosqlite", "").replace("sqlite:///", "sqlite:///"))
        logger.info("Config registry schema migration complete")
    except Exception as _cfg_mig_exc:
        logger.warning("Config registry schema migration failed (non-fatal): %s", _cfg_mig_exc)


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


def _assert_tenant_owns_record(
    record: Optional[Dict[str, Any]],
    expected_tenant_id: str,
    resource_type: str,
    resource_id: str,
) -> None:
    """Raise HTTP 403 if the record's tenant_id does not match the JWT tenant.
    Raise HTTP 404 if the record is None.

    G3-B: Defence-in-depth application-layer tenant re-verification.
    This check is in addition to, not instead of, the DB-layer WHERE predicate.
    """
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_type} not found: {resource_id}",
        )
    record_tenant = record.get("tenant_id")
    if record_tenant != expected_tenant_id:
        logger.warning(
            "SECURITY: %s tenant_id %s does not match JWT tenant_id %s "
            "for %s=%s — possible mis-routed query",
            resource_type,
            record_tenant,
            expected_tenant_id,
            resource_type,
            resource_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: {resource_type} does not belong to this tenant",
        )


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
    notice_id: Optional[str] = None  # P2-E: populated for REJECT decisions
    # G06: NLG narratives
    explanation_narrative: Optional[str] = None
    applicant_narrative: Optional[str] = None
    adverse_action_body: Optional[str] = None
    adverse_action_reasons: Optional[List[str]] = None


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

    # G4-C — Policy-level A/B routing.  Determine which policy version is active
    # for this application and merge challenger policy_cutoffs when routed there.
    _policy_role = _POLICY_ROUTER.route(app_req.application_id, tenant_id)
    _active_split = _POLICY_SPLIT_STORE.get_active_split(tenant_id)
    _policy_version_id: int = 0
    _policy_version_tag: str = "default"
    if _active_split is not None:
        _policy_cfg = _active_split[0] if _policy_role == "CHAMPION" else _active_split[1]
        _policy_version_id = _policy_cfg.version_id
        _policy_version_tag = _policy_cfg.version_tag

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
    shap_result = None  # P2-E: retained for adverse action notice generation
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

    # G06 — NLG Decision Summary (best-effort; uses template fallback if LLM unavailable)
    nlg_loan_officer_narrative = ""
    nlg_applicant_narrative = ""
    nlg_adverse_action_body = ""
    nlg_adverse_action_reasons: List[str] = []
    try:
        from explainability.nlg_summarizer import generate_decision_summary  # noqa: PLC0415
        if shap_result is not None:
            _nlg_summary = generate_decision_summary(
                explanation=shap_result,
                decision=decision_result.decision,
                application_id=app_req.application_id,
                applicant_name=getattr(app_req, "applicant_name", "Applicant"),
                model_version="v1",
                creditor_name=os.getenv("CREDITOR_NAME", "Creditor"),
                creditor_phone=os.getenv("CREDITOR_PHONE", "1-800-000-0000"),
            )
            nlg_loan_officer_narrative  = _nlg_summary.loan_officer_narrative
            nlg_applicant_narrative     = _nlg_summary.applicant_narrative
            nlg_adverse_action_body     = _nlg_summary.adverse_action_body
            nlg_adverse_action_reasons  = _nlg_summary.top_reasons
    except Exception as _nlg_exc:
        logger.warning("NLG summary generation failed: %s", _nlg_exc)

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

    # P2-E: Generate adverse action notice for REJECT decisions
    notice_id: Optional[str] = None
    if decision_result.decision == "REJECT":
        try:
            from compliance.adverse_action_generator import generate_notice, render_c1_text
            from compliance.adverse_action_store import save_notice

            shap_result_for_notice = None
            if explanation_factors:
                shap_result_for_notice = shap_result

            aa_notice = generate_notice(
                application_id=app_req.application_id,
                tenant_id=tenant_id,
                decision_result=decision_result,
                explanation_result=shap_result_for_notice,
                tenant_config=tenant_cfg,
            )
            notice_text = render_c1_text(aa_notice)
            notice_id = await save_notice(aa_notice, notice_text, DB_URL)
            logger.info("Adverse action notice generated: notice_id=%s", notice_id)
        except Exception as _aa_exc:
            logger.error("Adverse action notice generation failed: %s", _aa_exc)
            # Do NOT raise — notice failure must not block the decision response

    # G4-C — Record policy split outcome (best-effort; never blocks response).
    try:
        _POLICY_ROUTER.record_outcome(
            application_id=app_req.application_id,
            tenant_id=tenant_id,
            role=_policy_role,
            version_id=_policy_version_id,
            version_tag=_policy_version_tag,
            outcome={
                "decision": decision_result.decision,
                "apr": decision_result.recommended_rate,
                "credit_limit": (
                    decision_result.loan_terms.get("credit_limit")
                    if decision_result.loan_terms
                    else None
                ),
            },
        )
    except Exception as _pr_exc:
        logger.warning("Policy split record_outcome failed: %s", _pr_exc)

    _response = DecisionResponse(
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
        notice_id=notice_id,
        # G06: NLG narratives
        explanation_narrative=nlg_loan_officer_narrative or None,
        applicant_narrative=nlg_applicant_narrative or None,
        adverse_action_body=nlg_adverse_action_body or None,
        adverse_action_reasons=nlg_adverse_action_reasons or None,
    )

    # G16-B: Fire-and-forget webhook dispatch (never blocks response).
    try:
        _event_type_map = {
            "APPROVE":       "decision.approved",
            "REJECT":        "decision.rejected",
            "MANUAL_REVIEW": "decision.manual_review",
        }
        _wh_event = _event_type_map.get(decision_result.decision, "decision.manual_review")
        _wh_payload = {
            "application_id": app_req.application_id,
            "decision":        decision_result.decision,
            "pd_score":        pd_score,
            "notice_id":       notice_id,
            "audit_log_id":    audit_log_id,
            "tenant_id":       tenant_id,
            "event_type":      _wh_event,
            "occurred_at":     datetime.utcnow().isoformat() + "Z",
        }
        _loop = asyncio.get_event_loop()
        _loop.run_in_executor(
            None,
            lambda: _WEBHOOK_DISPATCH.dispatch(tenant_id, _wh_event, _wh_payload),
        )
    except Exception as _wh_exc:
        logger.warning("Webhook dispatch failed (non-fatal): %s", _wh_exc)

    return _response


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
    request: "Request",
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Publish a versioned config for the calling tenant. Auto-activates immediately.

    .. deprecated::
        Prefer ``POST /v1/config/stage`` + ``POST /v1/config/approve`` for production
        environments.  This endpoint bypasses the four-eyes gate and is retained for
        development convenience only.

    Requires header ``X-Allow-Bypass-Four-Eyes: true`` — returns HTTP 428 without it.
    """
    bypass = request.headers.get("X-Allow-Bypass-Four-Eyes", "")
    if bypass.lower() != "true":
        raise HTTPException(
            status_code=428,
            detail={
                "error": (
                    "Direct config publish requires X-Allow-Bypass-Four-Eyes: true header. "
                    "Use POST /v1/config/stage + POST /v1/config/approve in production."
                )
            },
        )
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


@app.post(
    "/v1/decisions",
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
    tags=["Audit & Compliance"],
)
async def get_audit(
    application_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return the complete audit record for a given application ID, with chain integrity."""
    tenant_id: str = _user["tenant_id"]
    record = await get_audit_record(application_id, DB_URL, tenant_id=tenant_id)
    # G3-B: Defence-in-depth — re-verify tenant at application layer
    _assert_tenant_owns_record(record, tenant_id, "audit record", application_id)
    # P1-D: Attach chain integrity to the response
    try:
        from audit.chain_verifier import verify_chain
        chain_result = await verify_chain(
            db_url=DB_URL,
            tenant_id=tenant_id,
            from_logged_at=record.get("logged_at"),
            to_logged_at=record.get("logged_at"),
        )
        record["chain_integrity"] = {
            "verified": chain_result.verified,
            "record_hash": record.get("record_hash"),
            "previous_hash": record.get("previous_hash"),
            "hash_algorithm": record.get("hash_algorithm"),
        }
    except Exception as _ci_exc:
        logger.warning("Chain integrity check failed: %s", _ci_exc)
        record["chain_integrity"] = {
            "verified": None,
            "record_hash": None,
            "previous_hash": None,
            "hash_algorithm": None,
        }
    return record


# ---------------------------------------------------------------------------
# G10-B — Explanation endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/v1/decisions/{application_id}/explanation",
    summary="Full explanation: SHAP + counterfactual + NLG narrative",
    tags=["Decisions"],
)
async def get_decision_explanation(
    application_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return a rich explanation for a past decision.

    Keys in response:
    - ``shap``: list of {feature, shap_value, direction} objects
    - ``counterfactual``: dict with minimum changes to flip the decision
    - ``narrative``: NLG loan-officer narrative text
    """
    tenant_id: str = _user["tenant_id"]

    record = await get_audit_record(application_id, DB_URL, tenant_id=tenant_id)
    _assert_tenant_owns_record(record, tenant_id, "decision", application_id)

    # 1. SHAP factors already stored in audit record
    stored_shap = record.get("explanation") or []

    # 2. Counterfactual (best-effort)
    counterfactual: Dict[str, Any] = {}
    if record.get("decision") == "REJECT":
        try:
            from explainability.counterfactual import generate_counterfactual  # noqa: PLC0415
            import pandas as _pd  # noqa: PLC0415

            raw_features = {
                k: v for k, v in record.items()
                if k not in {"application_id", "decision", "tenant_id",
                              "audit_log_id", "logged_at", "chain_integrity",
                              "explanation"}
                and isinstance(v, (int, float))
            }
            if raw_features:
                feat_df = _pd.DataFrame([raw_features])
                cf_result = generate_counterfactual(
                    features_df=feat_df,
                    model=_risk_model,
                    application_id=application_id,
                    original_decision="REJECT",
                )
                counterfactual = {
                    "feature_changes": cf_result.feature_changes,
                    "counterfactual_decision": cf_result.counterfactual_decision,
                    "feasibility_note": cf_result.feasibility_note,
                }
        except Exception as _cf_exc:
            logger.warning("Counterfactual generation failed: %s", _cf_exc)
            counterfactual = {"error": "Counterfactual generation unavailable"}
    else:
        counterfactual = {"note": "Counterfactuals generated for REJECT decisions only"}

    # 3. NLG narrative (best-effort)
    narrative: str = ""
    try:
        from explainability.nlg_summarizer import generate_decision_summary  # noqa: PLC0415
        from explainability.shap_explainer import ExplanationResult  # noqa: PLC0415

        if stored_shap and _risk_model is not None:
            _pos = [f for f in stored_shap if f.get("shap_value", 0) > 0][:3]
            _neg = [f for f in stored_shap if f.get("shap_value", 0) < 0][:3]
            import numpy as _np_nlg  # noqa: PLC0415
            _shap_result = ExplanationResult(
                top_positive_factors=_pos,
                top_negative_factors=_neg,
                base_value=0.0,
                predicted_value=float(record.get("pd_score") or 0.0),
                feature_names=[f["feature"] for f in stored_shap],
                shap_values=_np_nlg.array([f.get("shap_value", 0.0) for f in stored_shap]),
            )
            _nlg = generate_decision_summary(
                explanation=_shap_result,
                decision=record.get("decision", "UNKNOWN"),
                application_id=application_id,
                applicant_name="Applicant",
                model_version="v1",
                creditor_name=os.getenv("CREDITOR_NAME", "Creditor"),
                creditor_phone=os.getenv("CREDITOR_PHONE", "1-800-000-0000"),
            )
            narrative = _nlg.loan_officer_narrative
    except Exception as _nlg_exc:
        logger.warning("NLG narrative failed in explanation endpoint: %s", _nlg_exc)

    return {
        "application_id": application_id,
        "decision": record.get("decision"),
        "shap": stored_shap,
        "counterfactual": counterfactual,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# G11-B — Four-eyes config staging endpoints
# ---------------------------------------------------------------------------

class StageConfigRequest(BaseModel):
    config_json: Dict[str, Any] = Field(...)
    note: str = Field(..., min_length=1)
    authored_by: str = Field(..., description="Email of the person staging this config")


class ApproveConfigRequest(BaseModel):
    approver_email: str = Field(..., description="Email of the approving officer")
    note: str = Field(default="")


class RejectConfigRequest(BaseModel):
    rejected_by: str = Field(..., description="Email of reviewee rejecting the config")
    reason: str = Field(..., min_length=1)


@app.post(
    "/v1/config/stage",
    status_code=202,
    summary="Stage a new config for four-eyes review (does not activate)",
    tags=["Config Registry"],
)
async def stage_tenant_config(
    body: StageConfigRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Stage a new config version.  Does NOT activate it.
    Activation requires a separate ``POST /v1/config/approve`` from a different user.
    """
    tenant_id: str = _user["tenant_id"]
    _CONFIG_REGISTRY.ensure_tenant(tenant_id, name=tenant_id)
    try:
        staged = _CONFIG_REGISTRY.stage_config(
            tenant_id=tenant_id,
            config_json=body.config_json,
            authored_by=body.authored_by,
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return staged.as_dict()


@app.post(
    "/v1/config/approve",
    summary="Approve a staged config (four-eyes: approver must differ from author)",
    tags=["Config Registry"],
)
async def approve_staged_config(
    body: ApproveConfigRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Activate a staged config.  Enforces SOC 2 four-eyes separation of duties:
    the approver and the author may not be the same person.
    """
    from compliance.rbac import SeparationOfDutiesViolation  # noqa: PLC0415

    tenant_id: str = _user["tenant_id"]
    actor_email: str = _user.get("sub", _user.get("email", _user.get("tenant_id", "")))

    try:
        staged = _CONFIG_REGISTRY.get_staged(tenant_id)
        if staged is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No staged config found for this tenant.",
            )
        activated = _CONFIG_REGISTRY.approve_staged_config(
            tenant_id=tenant_id,
            staged_version_tag=staged.version_tag,
            approver_email=body.approver_email,
            actor_email=actor_email,
        )
    except SeparationOfDutiesViolation as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return activated.as_dict()


@app.post(
    "/v1/config/reject",
    summary="Reject a staged config",
    tags=["Config Registry"],
)
async def reject_staged_config(
    body: RejectConfigRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Reject (and remove) a staged config without activating it."""
    tenant_id: str = _user["tenant_id"]
    staged = _CONFIG_REGISTRY.get_staged(tenant_id)
    if staged is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No staged config found for this tenant.",
        )
    _CONFIG_REGISTRY.reject_staged_config(
        tenant_id=tenant_id,
        staged_version_tag=staged.version_tag,
        rejected_by=body.rejected_by,
        reason=body.reason,
    )
    return {"tenant_id": tenant_id, "status": "rejected", "version_tag": staged.version_tag}


# ---------------------------------------------------------------------------
# G12-A — Service metrics endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/v1/metrics",
    summary="Live service metrics (latency percentiles, error rate)",
    tags=["Observability"],
)
async def get_service_metrics(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Return rolling metrics snapshot.

    Accessible with either a tenant JWT or the ``METRICS_AUTH_TOKEN`` env var,
    supporting the canary controller script.
    """
    metrics_token = os.getenv("METRICS_AUTH_TOKEN", "")
    if credentials is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token_val = credentials.credentials
    # Accept both metrics-dedicated token and valid tenant JWT
    if metrics_token and token_val == metrics_token:
        pass  # canary controller using METRICS_AUTH_TOKEN
    else:
        # Require valid tenant JWT otherwise
        try:
            import jwt
            jwt.decode(token_val, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

    snap = _METRICS.snapshot()
    return snap


# ---------------------------------------------------------------------------
# G13-B — Borrower portal endpoints
# ---------------------------------------------------------------------------

@app.post(
    "/v1/portal/token",
    summary="Issue a borrower portal JWT",
    tags=["Borrower Portal"],
)
async def portal_issue_token(
    body: Dict[str, Any] = Body(...),
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Issue a borrower-scoped JWT from a tenant context.

    Required body fields:
    - ``borrower_id``: str
    - ``application_ids``: list[str]
    - ``ttl_hours``: int (optional, default 72)
    """
    from borrower_auth import issue_borrower_token  # noqa: PLC0415

    tenant_id: str = _user["tenant_id"]
    borrower_id = body.get("borrower_id", "")
    application_ids = body.get("application_ids", [])
    ttl_hours = int(body.get("ttl_hours", 72))

    if not borrower_id:
        raise HTTPException(status_code=422, detail="borrower_id is required")
    if not isinstance(application_ids, list):
        raise HTTPException(status_code=422, detail="application_ids must be a list")

    token = issue_borrower_token(
        borrower_id=borrower_id,
        tenant_id=tenant_id,
        application_ids=application_ids,
        ttl_hours=ttl_hours,
    )
    return {"token": token, "token_type": "borrower", "expires_in_hours": ttl_hours}


@app.get(
    "/v1/portal/applications/{application_id}/status",
    summary="Borrower portal: application decision status (no sensitive scores)",
    tags=["Borrower Portal"],
)
async def portal_application_status(
    application_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Return plain-language decision status for a borrower.

    Access: borrower JWT only (issues via ``POST /v1/portal/token``).
    Excludes: pd_score, fraud_probability (PII/model-internal fields).
    """
    from borrower_auth import get_borrower, verify_borrower_token  # noqa: PLC0415

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    borrower = verify_borrower_token(credentials.credentials)

    if application_id not in borrower.application_ids:
        raise HTTPException(
            status_code=403,
            detail="Application not accessible with this token",
        )

    record = await get_audit_record(application_id, DB_URL, tenant_id=borrower.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Application not found: {application_id}")

    # Return borrower-safe subset — omit internal model scores
    return {
        "application_id": application_id,
        "decision": record.get("decision"),
        "reason_codes": record.get("reason_codes") or [],
        "recommended_rate": record.get("recommended_rate"),
        "loan_terms": record.get("loan_terms") or {},
        "logged_at": record.get("logged_at"),
    }


@app.get(
    "/v1/portal/applications/{application_id}/explanation",
    summary="Borrower portal: plain-language explanation",
    tags=["Borrower Portal"],
)
async def portal_application_explanation(
    application_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Return the applicant_narrative NLG text for the borrower.

    Access: borrower JWT only.
    Excludes: SHAP values, pd_score, fraud_probability.
    """
    from borrower_auth import verify_borrower_token  # noqa: PLC0415

    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    borrower = verify_borrower_token(credentials.credentials)

    if application_id not in borrower.application_ids:
        raise HTTPException(
            status_code=403,
            detail="Application not accessible with this token",
        )

    record = await get_audit_record(application_id, DB_URL, tenant_id=borrower.tenant_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Application not found: {application_id}")

    applicant_narrative = record.get("applicant_narrative") or record.get("explanation_narrative") or ""
    adverse_action_body = record.get("adverse_action_body") or ""
    reason_codes = record.get("reason_codes") or []

    return {
        "application_id": application_id,
        "decision": record.get("decision"),
        "applicant_narrative": applicant_narrative,
        "adverse_action_body": adverse_action_body,
        "reason_codes": reason_codes,
    }


# ---------------------------------------------------------------------------
# G14-B — Batch underwriting upload endpoints
# ---------------------------------------------------------------------------

import csv as _csv  # noqa: E402
import io as _io    # noqa: E402
import uuid as _uuid  # noqa: E402

_REQUIRED_BATCH_COLS = {
    "application_id", "customer_id", "credit_score", "annual_income",
    "employment_status", "employer_tenure_months", "debt_to_income_ratio",
    "existing_debt_amount", "loan_amount", "loan_purpose", "loan_term_months",
    "num_open_accounts", "num_derogatory_marks",
}
_BATCH_MAX_ROWS = 10_000


async def _process_batch_job(job_id: str, tenant_id: str, rows: List[Dict[str, Any]]) -> None:
    """Background coroutine that processes batch rows and updates job state."""
    _BATCH_JOB_STORE.mark_running(job_id)
    approved = rejected = review = 0
    results = []
    try:
        for i, row in enumerate(rows):
            try:
                app_req = LoanApplicationRequest(**row)
                resp = await _run_pipeline(app_req, tenant_id=tenant_id)
                results.append(resp.model_dump())
                if resp.decision == "APPROVE":
                    approved += 1
                elif resp.decision == "REJECT":
                    rejected += 1
                else:
                    review += 1
            except Exception as _row_exc:
                logger.warning("Batch row %d error: %s", i, _row_exc)
                rejected += 1
            _BATCH_JOB_STORE.update_progress(
                job_id, processed=i + 1,
                approved=approved, rejected=rejected, review=review,
            )

        import json as _json
        results_path = f"./batch_results_{job_id}.json"
        with open(results_path, "w") as _f:
            _json.dump(results, _f)
        _BATCH_JOB_STORE.mark_complete(job_id, results_path=results_path)

        # G16-B: dispatch batch.complete webhook event
        try:
            _WEBHOOK_DISPATCH.dispatch(tenant_id, "batch.complete", {
                "job_id": job_id, "tenant_id": tenant_id,
                "total": len(rows), "approved": approved,
                "rejected": rejected, "review": review,
            })
        except Exception:
            pass

    except Exception as exc:
        _BATCH_JOB_STORE.mark_failed(job_id, error_message=str(exc))
        try:
            _WEBHOOK_DISPATCH.dispatch(tenant_id, "batch.failed", {
                "job_id": job_id, "tenant_id": tenant_id, "error": str(exc),
            })
        except Exception:
            pass


@app.post(
    "/v1/batch/underwrite",
    status_code=202,
    summary="Submit a CSV batch underwriting job (async)",
    tags=["Batch Underwriting"],
)
async def submit_batch_underwrite(
    file: UploadFile = File(..., description="CSV file with loan applications"),
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Accept a CSV file with up to 10,000 applications; return job_id immediately.

    Required columns (see _REQUIRED_BATCH_COLS).
    Responds 413 if row count > 10,000; 422 if required columns missing.
    """
    tenant_id: str = _user["tenant_id"]
    content = await file.read()
    text = content.decode("utf-8", errors="replace")
    reader = _csv.DictReader(_io.StringIO(text))
    rows = list(reader)

    if len(rows) > _BATCH_MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"CSV exceeds maximum row limit of {_BATCH_MAX_ROWS}.",
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CSV file is empty.",
        )

    missing_cols = _REQUIRED_BATCH_COLS - set(rows[0].keys())
    if missing_cols:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required columns: {sorted(missing_cols)}",
        )

    # Coerce numeric columns
    _INT_COLS = {"credit_score", "employer_tenure_months", "loan_term_months",
                  "num_open_accounts", "num_derogatory_marks"}
    _FLOAT_COLS = {"annual_income", "debt_to_income_ratio", "existing_debt_amount", "loan_amount"}
    coerced_rows = []
    for row in rows:
        r = dict(row)
        for c in _INT_COLS:
            if c in r:
                try:
                    r[c] = int(r[c])
                except (ValueError, TypeError):
                    pass
        for c in _FLOAT_COLS:
            if c in r:
                try:
                    r[c] = float(r[c])
                except (ValueError, TypeError):
                    pass
        coerced_rows.append(r)

    job_id = str(_uuid.uuid4())
    _BATCH_JOB_STORE.create_job(job_id, tenant_id=tenant_id, total_rows=len(coerced_rows))
    asyncio.create_task(_process_batch_job(job_id, tenant_id, coerced_rows))

    return {
        "job_id": job_id,
        "status": "PENDING",
        "total_rows": len(coerced_rows),
        "accepted_at": datetime.utcnow().isoformat() + "Z",
    }


@app.get(
    "/v1/batch/{job_id}/status",
    summary="Get batch job status",
    tags=["Batch Underwriting"],
)
async def get_batch_status(
    job_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return the current status and progress of a batch job."""
    tenant_id: str = _user["tenant_id"]
    job = _BATCH_JOB_STORE.get_job(job_id)
    if job is None or job.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail=f"Batch job not found: {job_id}")
    return job


@app.get(
    "/v1/batch/{job_id}/results",
    summary="Download batch job results as JSON",
    tags=["Batch Underwriting"],
)
async def get_batch_results(
    job_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Any:
    """Return the JSON results file for a completed batch job."""
    import json as _json

    tenant_id: str = _user["tenant_id"]
    job = _BATCH_JOB_STORE.get_job(job_id)
    if job is None or job.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=404, detail=f"Batch job not found: {job_id}")
    if job.get("status") != "COMPLETE":
        raise HTTPException(
            status_code=409,
            detail=f"Job not yet complete (status={job.get('status')}).",
        )
    results_path = job.get("results_path")
    if not results_path or not Path(results_path).exists():
        raise HTTPException(status_code=404, detail="Results file not found")
    with open(results_path) as f:
        return _json.load(f)


# ---------------------------------------------------------------------------
# G15-B — Stress test endpoints
# ---------------------------------------------------------------------------

import functools as _functools  # noqa: E402

_stress_runner_cache: Any = None
_stress_runner_lock = _threading.Lock()


def _get_stress_runner() -> Any:
    """Lazy-initialise StressTestRunner with the live risk model."""
    global _stress_runner_cache
    if _stress_runner_cache is None:
        with _stress_runner_lock:
            if _stress_runner_cache is None:
                from risk_models.stress_test import StressTestRunner  # noqa: PLC0415
                store_path = os.getenv("STRESS_TEST_DB_PATH", "./stress_test_results.db")
                if _risk_model is not None:
                    _stress_runner_cache = StressTestRunner(
                        model=_risk_model,
                        feature_names=FEATURE_CONFIG.feature_list,
                        store_path=store_path,
                    )
    return _stress_runner_cache


class StressTestRunRequest(BaseModel):
    quarter: str = Field(default="", description="Quarter label, e.g. '2026-Q1'")
    severity: str = Field(default="moderate", description="mild|moderate|severe|tail")
    n_scenarios: int = Field(default=1000, ge=10, le=10_000)
    seed: int = Field(default=42)
    run_label: str = Field(default="")


@app.post(
    "/v1/stress-test/run",
    status_code=202,
    summary="Run a Monte Carlo portfolio stress test (async)",
    tags=["Stress Testing"],
)
async def run_stress_test(
    body: StressTestRunRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Trigger a new Monte Carlo stress test run.  Returns run_id immediately.

    Access: role must be 'cro', 'credit_risk', or 'admin'.
    """
    role = _user.get("role", "")
    if role not in {"cro", "credit_risk", "admin", "model_risk_officer"}:
        raise HTTPException(
            status_code=403,
            detail="Insufficient role for stress test execution (requires cro|credit_risk|admin)",
        )

    runner = _get_stress_runner()
    if runner is None:
        raise HTTPException(
            status_code=503,
            detail="Stress test runner unavailable (risk model not loaded)",
        )

    from risk_models.stress_test import StressTestSummary  # noqa: PLC0415
    import pandas as _pd

    # Build a synthetic portfolio from audit DB if available; otherwise dummy
    async def _get_portfolio() -> "pd.DataFrame":
        try:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text as _text
            eng = create_async_engine(DB_URL, echo=False)
            async with eng.connect() as conn:
                rows_result = await conn.execute(
                    _text("SELECT * FROM audit_log WHERE tenant_id = :tid LIMIT 5000"),
                    {"tid": _user["tenant_id"]},
                )
                col_names = list(rows_result.keys())
                records = [dict(zip(col_names, r)) for r in rows_result.fetchall()]
            await eng.dispose()
            if records:
                return _pd.DataFrame(records)
        except Exception as _pe:
            logger.warning("Could not load portfolio from DB: %s", _pe)
        # Fallback: empty/dummy
        return _pd.DataFrame(
            {f: [0.0] for f in FEATURE_CONFIG.feature_list}
        )

    portfolio_df = await _get_portfolio()

    run_id_holder: Dict[str, Any] = {}

    def _run_sync():
        summary = runner.run(
            portfolio_df=portfolio_df,
            n_scenarios=body.n_scenarios,
            severity=body.severity,
            run_label=body.run_label,
            quarter=body.quarter,
            seed=body.seed,
        )
        run_id_holder["summary"] = summary

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _run_sync)
    summary = run_id_holder.get("summary")

    return {
        "run_id": summary.run_id if summary else "unknown",
        "status": "COMPLETE",
        "quarter": body.quarter,
        "severity": body.severity,
        "n_scenarios": body.n_scenarios,
    }


@app.get(
    "/v1/stress-test/results",
    summary="List stress test run results",
    tags=["Stress Testing"],
)
async def list_stress_results(
    quarter: Optional[str] = None,
    limit: int = 10,
    _user: Dict = Depends(verify_bearer),
) -> List[Dict[str, Any]]:
    """Return recent stress test runs, optionally filtered by quarter."""
    runner = _get_stress_runner()
    if runner is None:
        return []
    return runner.get_results(quarter=quarter, limit=limit)


@app.get(
    "/v1/stress-test/compare",
    summary="Compare stress test results between two quarters",
    tags=["Stress Testing"],
)
async def compare_stress_quarters(
    quarter_a: str,
    quarter_b: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return delta metrics between the most-recent runs of two quarters."""
    runner = _get_stress_runner()
    if runner is None:
        raise HTTPException(status_code=503, detail="Stress runner not available")
    return runner.compare_quarters(quarter_a, quarter_b)


# ---------------------------------------------------------------------------
# G16-B — Webhook CRUD endpoints
# ---------------------------------------------------------------------------

class WebhookCreateRequest(BaseModel):
    target_url: str = Field(..., description="HTTPS URL to POST events to")
    events: List[str] = Field(default=["*"], description="Event types or ['*'] for all")
    description: str = Field(default="")


@app.post(
    "/v1/webhooks",
    status_code=201,
    summary="Register a new webhook endpoint",
    tags=["Webhooks"],
)
async def create_webhook(
    body: WebhookCreateRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Register a webhook.  Returns the registration including the one-time
    plaintext secret — the caller MUST save it as it is not stored in plain text.
    """
    tenant_id: str = _user["tenant_id"]
    import secrets as _sec  # noqa: PLC0415
    secret = _sec.token_hex(32)
    reg = _WEBHOOK_STORE.register(
        tenant_id=tenant_id,
        target_url=body.target_url,
        secret=secret,
        events=body.events,
        description=body.description,
    )
    return {
        "webhook_id": reg.webhook_id,
        "tenant_id": reg.tenant_id,
        "target_url": reg.target_url,
        "events": reg.events,
        "is_active": reg.is_active,
        "description": reg.description,
        "created_at": reg.created_at,
        "secret": secret,  # returned once; NOT stored in plaintext
    }


@app.get(
    "/v1/webhooks",
    summary="List all webhook registrations for this tenant",
    tags=["Webhooks"],
)
async def list_webhooks(
    _user: Dict = Depends(verify_bearer),
) -> List[Dict[str, Any]]:
    """Return all active webhook registrations for the calling tenant."""
    tenant_id: str = _user["tenant_id"]
    regs = _WEBHOOK_STORE.list_for_tenant(tenant_id)
    return [
        {
            "webhook_id": r.webhook_id,
            "target_url": r.target_url,
            "events": r.events,
            "is_active": r.is_active,
            "description": r.description,
            "created_at": r.created_at,
        }
        for r in regs
    ]


@app.get(
    "/v1/webhooks/{webhook_id}/deliveries",
    summary="Get delivery log for a specific webhook",
    tags=["Webhooks"],
)
async def get_webhook_deliveries(
    webhook_id: str,
    limit: int = 50,
    _user: Dict = Depends(verify_bearer),
) -> List[Dict[str, Any]]:
    """Return the delivery attempt log for a webhook (last *limit* entries)."""
    tenant_id: str = _user["tenant_id"]
    reg = _WEBHOOK_STORE.get(webhook_id)
    if reg is None or reg.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail=f"Webhook not found: {webhook_id}")
    attempts = _WEBHOOK_STORE.get_delivery_log(webhook_id, limit=limit)
    return [
        {
            "attempt_id": a.attempt_id,
            "event_type": a.event_type,
            "response_status": a.response_status,
            "success": a.success,
            "attempt_number": a.attempt_number,
            "duration_ms": a.duration_ms,
            "delivered_at": a.delivered_at,
            "error_message": a.error_message,
        }
        for a in attempts
    ]


@app.delete(
    "/v1/webhooks/{webhook_id}",
    status_code=204,
    summary="Deactivate (soft-delete) a webhook registration",
    tags=["Webhooks"],
)
async def delete_webhook(
    webhook_id: str,
    _user: Dict = Depends(verify_bearer),
) -> None:
    """Soft-delete a webhook registration.  Returns 204 on success, 404 if not found."""
    tenant_id: str = _user["tenant_id"]
    removed = _WEBHOOK_STORE.deactivate(webhook_id, tenant_id=tenant_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Webhook not found: {webhook_id}")



    from_logged_at: Optional[str] = None
    to_logged_at: Optional[str] = None
    table: str = "audit_log"


@app.post(
    "/v1/audit/verify-chain",
    summary="Verify audit log hash chain integrity for this tenant",
    tags=["Audit & Compliance"],
)
async def verify_chain_endpoint(
    body: VerifyChainRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Verify the cryptographic hash chain for the calling tenant.

    For large date ranges (> 100K rows), returns 202 Accepted with a job_id.
    """
    from datetime import timezone as _tz
    from audit.chain_verifier import verify_chain
    from sqlalchemy import text as _text
    from sqlalchemy.ext.asyncio import create_async_engine

    tenant_id: str = _user["tenant_id"]
    table = body.table if body.table in (
        "audit_log", "portfolio_audit_log", "adverse_action_log"
    ) else "audit_log"

    # COUNT guard: respond with 202 if > 100K rows
    try:
        _eng = create_async_engine(DB_URL, echo=False)
        _where = "WHERE tenant_id = :tid"
        _params: Dict[str, Any] = {"tid": tenant_id}
        if body.from_logged_at:
            _where += " AND logged_at >= :fr"
            _params["fr"] = body.from_logged_at
        if body.to_logged_at:
            _where += " AND logged_at <= :to"
            _params["to"] = body.to_logged_at
        async with _eng.connect() as _conn:
            count_result = await _conn.execute(
                _text(f"SELECT COUNT(*) FROM {table} {_where}"), _params
            )
            row_count = count_result.scalar() or 0
        await _eng.dispose()
        if row_count > 100_000:
            import uuid as _uuid
            return JSONResponse(
                content={"job_id": str(_uuid.uuid4()), "status": "queued",
                         "message": "Verification queued asynchronously (>100K rows)"},
                status_code=202,
            )
    except Exception as _cnt_exc:
        logger.warning("Row count check failed: %s", _cnt_exc)

    result = await verify_chain(
        db_url=DB_URL,
        tenant_id=tenant_id,
        from_logged_at=body.from_logged_at,
        to_logged_at=body.to_logged_at,
        table=table,
    )
    now_utc = datetime.utcnow().replace(tzinfo=None).isoformat() + "Z"
    return {
        "tenant_id": tenant_id,
        "verified": result.verified,
        "rows_checked": result.rows_checked,
        "first_tampered_log_id": result.first_tampered_log_id,
        "gap_detected": result.gap_detected,
        "verified_at": now_utc,
    }


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

    # P1-E: Detect audit schema version
    audit_chain_enabled = False
    _audit_schema_ver = "v1-no-chain"
    try:
        from audit.logger import audit_schema_version
        _audit_schema_ver = await audit_schema_version(DB_URL)
        audit_chain_enabled = _audit_schema_ver == "v2-hash-chain"
    except Exception as _av_exc:
        logger.debug("audit_schema_version check failed: %s", _av_exc)

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
        "audit_chain_enabled": audit_chain_enabled,
        "audit_schema_version": _audit_schema_ver,
    }


# ---------------------------------------------------------------------------
# P2-E — Adverse Action endpoints
# ---------------------------------------------------------------------------


class DeliverNoticeRequest(BaseModel):
    delivery_channel: str = Field(..., description="email | mail | portal")
    delivered_at: str = Field(..., description="ISO-8601 timestamp of delivery")


@app.get(
    "/v1/adverse-actions/pending-deadlines",
    summary="List adverse action notices approaching their 30-day delivery deadline",
    tags=["Adverse Actions"],
)
async def list_pending_deadlines(
    warn_days_before: int = 5,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return PENDING notices with deadline within warn_days_before days."""
    from compliance.adverse_action_store import get_pending_deadline_notices

    tenant_id: str = _user["tenant_id"]
    notices = await get_pending_deadline_notices(DB_URL, tenant_id, warn_days_before)
    return {"notices": notices, "count": len(notices)}


@app.get(
    "/v1/adverse-actions/{notice_id}",
    summary="Retrieve a single adverse action notice",
    tags=["Adverse Actions"],
)
async def get_adverse_action_notice(
    notice_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return a notice by ID (scoped to calling tenant)."""
    from compliance.adverse_action_store import get_notice

    tenant_id: str = _user["tenant_id"]
    record = await get_notice(notice_id, DB_URL, tenant_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Notice not found: {notice_id}",
        )
    return record


@app.get(
    "/v1/adverse-actions",
    summary="List adverse action notices for this tenant",
    tags=["Adverse Actions"],
)
async def list_adverse_action_notices(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    notice_status: Optional[str] = None,
    page: int = 1,
    per_page: int = 100,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return paginated list of adverse action notices."""
    from compliance.adverse_action_store import list_notices

    tenant_id: str = _user["tenant_id"]
    records, total = await list_notices(
        DB_URL, tenant_id, from_date, to_date, notice_status, page, per_page
    )
    return {"notices": records, "total": total, "page": page, "per_page": per_page}


@app.post(
    "/v1/adverse-actions/{notice_id}/deliver",
    summary="Mark an adverse action notice as delivered",
    tags=["Adverse Actions"],
)
async def deliver_adverse_action_notice(
    notice_id: str,
    body: DeliverNoticeRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Record delivery of an adverse action notice."""
    from compliance.adverse_action_store import mark_delivered

    tenant_id: str = _user["tenant_id"]
    try:
        await mark_delivered(notice_id, body.delivery_channel, body.delivered_at, DB_URL, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"notice_id": notice_id, "delivery_status": "DELIVERED"}


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


# ---------------------------------------------------------------------------
# G4-C — Policy Split admin endpoints
# ---------------------------------------------------------------------------


class PolicySplitRequest(BaseModel):
    """Request body for POST /v1/admin/policy-split/{tenant_id}."""

    champion_version_id: int = Field(..., description="Policy version ID for the champion role")
    champion_version_tag: str = Field(..., description="Human-readable tag for champion version")
    champion_traffic_pct: float = Field(default=0.9, ge=0.0, le=1.0, description="Traffic fraction for champion (0–1)")
    challenger_version_id: int = Field(..., description="Policy version ID for the challenger role")
    challenger_version_tag: str = Field(..., description="Human-readable tag for challenger version")
    challenger_traffic_pct: float = Field(default=0.1, ge=0.0, le=1.0, description="Traffic fraction for challenger (0–1)")


@app.post(
    "/v1/admin/policy-split/{tenant_id}",
    summary="Configure or replace a policy A/B split for a tenant",
    tags=["Admin – Policy Split"],
)
def set_policy_split(
    tenant_id: str,
    body: PolicySplitRequest,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Activate a champion/challenger policy split for *tenant_id*.

    If a split already exists it is deactivated before the new one is stored.
    """
    champion = PolicyChallengerConfig(
        role="CHAMPION",
        version_id=body.champion_version_id,
        version_tag=body.champion_version_tag,
        traffic_pct=body.champion_traffic_pct,
        tenant_id=tenant_id,
    )
    challenger = PolicyChallengerConfig(
        role="CHALLENGER",
        version_id=body.challenger_version_id,
        version_tag=body.challenger_version_tag,
        traffic_pct=body.challenger_traffic_pct,
        tenant_id=tenant_id,
    )
    try:
        _POLICY_SPLIT_STORE.set_split(champion, challenger)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    logger.info(
        "Policy split configured for tenant=%s champion=%s challenger=%s",
        tenant_id,
        body.champion_version_tag,
        body.challenger_version_tag,
    )
    return {
        "tenant_id": tenant_id,
        "champion_version_tag": body.champion_version_tag,
        "challenger_version_tag": body.challenger_version_tag,
        "status": "activated",
    }


@app.delete(
    "/v1/admin/policy-split/{tenant_id}",
    summary="Deactivate the current policy A/B split for a tenant",
    tags=["Admin – Policy Split"],
)
def delete_policy_split(
    tenant_id: str,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Deactivate all active policy split rows for *tenant_id*."""
    from sqlalchemy import text as _text

    with _POLICY_SPLIT_STORE._engine.begin() as conn:
        conn.execute(
            _text("UPDATE policy_splits SET active = 0 WHERE tenant_id = :tid AND active = 1"),
            {"tid": tenant_id},
        )
    logger.info("Policy split deactivated for tenant=%s", tenant_id)
    return {"tenant_id": tenant_id, "status": "deactivated"}


@app.get(
    "/v1/admin/policy-split/{tenant_id}/report",
    summary="Generate a champion/challenger comparison report for a tenant",
    tags=["Admin – Policy Split"],
)
def get_policy_split_report(
    tenant_id: str,
    lookback_days: int = 7,
    _user: Dict = Depends(verify_bearer),
) -> Dict[str, Any]:
    """Return a ``PolicyComparisonReport`` for the last *lookback_days* days."""
    report = _POLICY_SPLIT_STORE.generate_comparison_report(tenant_id, lookback_days)
    return {
        "tenant_id": tenant_id,
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "champion_version_tag": report.champion_version_tag,
        "challenger_version_tag": report.challenger_version_tag,
        "champion_approval_rate": report.champion_approval_rate,
        "challenger_approval_rate": report.challenger_approval_rate,
        "approval_rate_delta": report.approval_rate_delta,
        "sample_size_champion": report.sample_size_champion,
        "sample_size_challenger": report.sample_size_challenger,
        "recommendation": report.recommendation,
    }


# ---------------------------------------------------------------------------
# G09 — Champion Promotion Endpoint (SR 11-7 MDR auto-generation)
# ---------------------------------------------------------------------------

@app.post(
    "/v1/models/{run_id}/promote",
    summary="Promote a challenger model to champion and auto-generate its SR 11-7 MDR",
    tags=["Model Management"],
)
async def promote_model(
    run_id: str,
    body: Dict[str, Any] = Body(default={}),
    token_data: Dict[str, Any] = Depends(verify_bearer),
) -> JSONResponse:
    """Promote a challenger model to champion and auto-generate its SR 11-7 MDR.

    Required JWT claims
    -------------------
    role: "model_risk_officer" or "admin"

    Request body (all optional)
    ---------------------------
    {
      "model_name":          "cc_pd_model",
      "use_case":            "Credit Card PD",
      "owner":               "Risk Analytics",
      "reviewer":            "Model Risk",
      "approver":            "CRO",
      "intended_population": "US credit card applicants",
      "docs_output_dir":     "docs/mdr"
    }

    Response
    --------
    {
      "status": "promoted",
      "promotion_record": { ...dict returned by promote_champion()... }
    }
    """
    from decisioning.champion_challenger import CCDecisionStore, ChampionChallengerRouter, ModelConfig  # noqa: PLC0415
    from compliance.generate_model_doc import ModelDocumentationConfig  # noqa: PLC0415

    # RBAC: only model_risk_officer or admin may promote
    role = token_data.get("role", "")
    if role not in {"model_risk_officer", "admin"}:
        return JSONResponse(
            status_code=403,
            content={"error": "Insufficient role for model promotion."},
        )

    config = ModelDocumentationConfig(
        model_name=body.get("model_name", "cc_pd_model"),
        version=run_id[:8],
        use_case=body.get("use_case", "Credit Card PD"),
        owner=body.get("owner", "Risk Analytics"),
        reviewer=body.get("reviewer", "Model Risk Management"),
        approver=body.get("approver", "Chief Risk Officer"),
        intended_population=body.get("intended_population", "US credit card applicants"),
    )

    # Build a minimal router (routing state loaded from DB in production)
    _store = CCDecisionStore(db_url=DB_URL.replace("+aiosqlite", "")) if DB_URL.startswith("sqlite") else CCDecisionStore()
    _champ = ModelConfig(
        role="CHAMPION",
        model_registry_name=body.get("model_name", "cc_pd_model"),
        model_version=run_id,
        traffic_pct=1.0,
    )
    router = ChampionChallengerRouter(
        champion=_champ,
        challenger=None,
        store=_store,
    )

    docs_output_dir = body.get("docs_output_dir", "docs/mdr")
    record = router.promote_champion(
        new_champion_run_id=run_id,
        model_doc_config=config,
        docs_output_dir=docs_output_dir,
    )

    return JSONResponse(content={"status": "promoted", "promotion_record": record})


# ---------------------------------------------------------------------------
# G08 — Feature Lineage Query API
# ---------------------------------------------------------------------------

@app.get(
    "/v1/lineage/{run_id}",
    summary="Return all OpenLineage events for a run_id",
    tags=["Lineage"],
)
async def get_lineage(
    run_id: str,
    token_data: Dict[str, Any] = Depends(verify_bearer),
) -> JSONResponse:
    """Return all OpenLineage events for *run_id*.

    Response schema
    ---------------
    {
      "run_id": "...",
      "tenant_id": "...",
      "event_count": 3,
      "events": [ { ...OpenLineage event dict... }, ... ]
    }

    Errors
    ------
    404 — run_id not found in the lineage store
    503 — lineage store not configured (LINEAGE_STORE_PATH not set)
    """
    from feature_pipeline.lineage import LineageStore as _LineageStore  # noqa: PLC0415

    store_path = os.getenv("LINEAGE_STORE_PATH")
    if not store_path:
        return JSONResponse(
            status_code=503,
            content={"error": "Lineage store not configured. Set LINEAGE_STORE_PATH."},
        )

    store = _LineageStore(store_path)
    try:
        events = store.get_by_run_id(run_id)
    finally:
        store.close()

    if not events:
        return JSONResponse(
            status_code=404,
            content={"error": f"No lineage events found for run_id={run_id}"},
        )

    return JSONResponse(content={
        "run_id": run_id,
        "tenant_id": token_data.get("tenant_id"),
        "event_count": len(events),
        "events": events,
    })


@app.get(
    "/v1/lineage/job/{job_name}",
    summary="Return recent OpenLineage events for a job name",
    tags=["Lineage"],
)
async def get_lineage_by_job(
    job_name: str,
    limit: int = 100,
    token_data: Dict[str, Any] = Depends(verify_bearer),
) -> JSONResponse:
    """Return the most recent *limit* events for *job_name*.

    Errors
    ------
    503 — lineage store not configured (LINEAGE_STORE_PATH not set)
    404 — no events found for job_name
    """
    from feature_pipeline.lineage import LineageStore as _LineageStore  # noqa: PLC0415

    store_path = os.getenv("LINEAGE_STORE_PATH")
    if not store_path:
        return JSONResponse(
            status_code=503,
            content={"error": "Lineage store not configured. Set LINEAGE_STORE_PATH."},
        )

    store = _LineageStore(store_path)
    try:
        events = store.get_by_job(job_name, limit=limit)
    finally:
        store.close()

    if not events:
        return JSONResponse(
            status_code=404,
            content={"error": f"No lineage events found for job_name={job_name}"},
        )

    return JSONResponse(content={
        "job_name": job_name,
        "tenant_id": token_data.get("tenant_id"),
        "event_count": len(events),
        "events": events,
    })
