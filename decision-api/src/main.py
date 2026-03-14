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

# Make project root importable
ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

from audit.logger import get_audit_record, log_decision  # noqa: E402
from decision_engine.engine import (  # noqa: E402
    CreditResult,
    DecisionRequest,
    FraudResult,
    make_decision,
)
from feature_pipeline.features import FeaturePipelineConfig, compute_features  # noqa: E402
from models.credit_risk.predict import predict_pd  # noqa: E402
from models.fraud_detection.predict import predict_fraud  # noqa: E402
from models.pricing.engine import PricingConfig, calculate_pricing  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./decision_audit.db",
)
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
FRAUD_MODEL_PATH = os.getenv("FRAUD_MODEL_PATH", str(ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl"))
RISK_MODEL_PATH = os.getenv("RISK_MODEL_PATH", str(ROOT / "models" / "credit_risk" / "risk_model_v1.pkl"))

FEATURE_CONFIG = FeaturePipelineConfig()
PRICING_CONFIG = PricingConfig()

# Pre-load models at startup (best effort)
_fraud_model: Any = None
_risk_model: Any = None


def _load_models() -> None:
    global _fraud_model, _risk_model
    try:
        import joblib
        _fraud_model = joblib.load(FRAUD_MODEL_PATH)
        logger.info("Fraud model loaded from %s", FRAUD_MODEL_PATH)
    except Exception as exc:
        logger.warning("Could not load fraud model: %s", exc)
    try:
        import joblib
        _risk_model = joblib.load(RISK_MODEL_PATH)
        logger.info("Credit risk model loaded from %s", RISK_MODEL_PATH)
    except Exception as exc:
        logger.warning("Could not load credit risk model: %s", exc)


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    _load_models()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)


async def verify_bearer(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> Dict[str, Any]:
    """Verify Bearer JWT token.  Skips auth if JWT_SECRET is the default dev key."""
    if JWT_SECRET == "your-secret-key-change-in-production":  # pragma: allowlist secret
        return {"sub": "dev-user", "auth_type": "dev"}

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
        return payload
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
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
    """Convert a LoanApplicationRequest into a features DataFrame."""
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
    return compute_features(raw_df, FEATURE_CONFIG)


async def _run_pipeline(app_req: LoanApplicationRequest) -> DecisionResponse:
    """Execute the full underwriting pipeline for a single application."""
    start = time.perf_counter()

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

    # 4. Pricing
    pricing_result = calculate_pricing(
        pd_score=pd_score,
        fraud_flag=fraud_flag_str,
        loan_amount=float(app_req.loan_amount),
        config=PRICING_CONFIG,
    )

    # 5. Decision engine
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
    decision_result = make_decision(decision_req)

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
    response = await _run_pipeline(application)
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

    tasks = [_run_pipeline(app) for app in applications]
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
    record = await get_audit_record(application_id, DB_URL)
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
