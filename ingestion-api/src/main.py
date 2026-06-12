"""
FastAPI Ingestion API for AI Risk Workflow Platform
Handles transaction and application ingestion with GCS storage and Pub/Sub emission.

P1.2 changes
------------
* GCS uploads and Pub/Sub publishes are offloaded to FastAPI BackgroundTasks so
  async endpoints do not block the event loop.
* Retries with exponential backoff for transient GCP errors (IOError / GoogleAPIError).
* Request-level deduplication: SHA-256 of the batch payload is stored in Redis with
  a configurable TTL; duplicate submissions return 200 immediately without re-uploading.
* Structured event envelopes include tenant_id extracted from the JWT.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, Security, UploadFile, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from google.api_core import exceptions as gcp_exceptions
from google.cloud import pubsub_v1, storage

# Import from same directory (for Docker deployment)
try:
    from models import ApplicationBatch, IngestionResponse, TransactionBatch
    from auth import verify_token
    from document_models import DocumentExtractionResult, DocumentType
    from document_pipeline import process_document
except ImportError:
    try:
        from src.models import ApplicationBatch, IngestionResponse, TransactionBatch
        from src.auth import verify_token
        from src.document_models import DocumentExtractionResult, DocumentType
        from src.document_pipeline import process_document
    except ImportError:
        print("ERROR: Could not import models and auth modules")
        raise

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("Starting AI Risk Workflow Ingestion API (P1.2)")
logger.info(f"Python version: {os.sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info("=" * 50)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GCS_BUCKET = os.getenv("GCS_RAW_BUCKET", "risk-raw-data")
PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC", "projects/YOUR_PROJECT/topics/ingestion-events")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "YOUR_PROJECT")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/1")
DEDUP_TTL = int(os.getenv("DEDUP_TTL_SECONDS", str(24 * 3600)))  # 24 h
MAX_RETRIES = int(os.getenv("GCP_MAX_RETRIES", "3"))
BASE_BACKOFF = float(os.getenv("GCP_BASE_BACKOFF_SECONDS", "0.5"))

# ---------------------------------------------------------------------------
# Global GCP clients (initialised in lifespan)
# ---------------------------------------------------------------------------
storage_client: Optional[storage.Client] = None
publisher_client: Optional[pubsub_v1.PublisherClient] = None

# ---------------------------------------------------------------------------
# Optional Redis client for deduplication
# ---------------------------------------------------------------------------
try:
    import redis.asyncio as aioredis  # type: ignore[import]

    _redis_client: Optional[aioredis.Redis] = None

    def _get_redis() -> aioredis.Redis:
        global _redis_client
        if _redis_client is None:
            _redis_client = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
            )
        return _redis_client

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False
    logger.warning("[dedup] redis-py not installed — batch deduplication is DISABLED.")

security = HTTPBearer()


# ---------------------------------------------------------------------------
# Redis startup health check
# ---------------------------------------------------------------------------

async def _check_redis_startup(url: str, timeout: float = 2.0) -> bool:
    """Return True if Redis responds to PING within *timeout* seconds."""
    if not _REDIS_AVAILABLE:
        return False
    try:
        import redis.asyncio as aioredis  # type: ignore[import]

        client = aioredis.from_url(
            url,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            decode_responses=True,
        )
        try:
            result = await asyncio.wait_for(client.ping(), timeout=timeout)
            return bool(result)
        finally:
            await client.aclose()
    except Exception as exc:
        logger.warning("Redis startup health check failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global storage_client, publisher_client
    try:
        logger.info("Initializing GCP clients...")
        storage_client = storage.Client(project=PROJECT_ID)
        publisher_client = pubsub_v1.PublisherClient()
        logger.info("✓ GCP clients initialized successfully")
        # CRIT-05 (ingestion): In production, Redis must be reachable before
        # accepting traffic.  Without Redis, batch deduplication is silently
        # disabled, allowing duplicate payloads to double-write to GCS/Pub/Sub.
        _environment = os.getenv("ENVIRONMENT", "dev")
        if _environment == "prod":
            _redis_ok = await _check_redis_startup(REDIS_URL)
            if not _redis_ok:
                raise RuntimeError(
                    "[CRIT-05] ENVIRONMENT=prod but Redis is unreachable at REDIS_URL. "
                    "Batch deduplication is non-functional. "
                    "Fix Redis connectivity or set ENVIRONMENT=dev to suppress this check."
                )
            logger.info("Redis connectivity verified at startup (ingestion-api).")
        yield
    except RuntimeError:
        raise
    except Exception as e:
        logger.error(f"Failed to initialize GCP clients: {str(e)}")
        logger.warning("Application starting without GCP clients — health checks will work but API calls may fail")
        yield
    finally:
        if publisher_client:
            logger.info("Publisher client cleanup complete")


app = FastAPI(
    title="Risk Workflow Ingestion API",
    description="Ingestion endpoints for transactions and loan applications",
    version="2.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------

_RETRYABLE_EXCEPTIONS = (
    gcp_exceptions.ServiceUnavailable,
    gcp_exceptions.InternalServerError,
    gcp_exceptions.DeadlineExceeded,
    gcp_exceptions.ResourceExhausted,
    IOError,
    TimeoutError,
)


async def _with_retry(coro_fn, *args, max_retries: int = MAX_RETRIES, base_backoff: float = BASE_BACKOFF, **kwargs):
    """Execute an async callable with exponential back-off on transient errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_fn(*args, **kwargs)
        except _RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt == max_retries:
                break
            wait = base_backoff * (2 ** attempt)
            logger.warning(
                "Transient error on attempt %d/%d, retrying in %.1fs: %s",
                attempt + 1, max_retries, wait, exc,
            )
            await asyncio.sleep(wait)
        except Exception as exc:
            # Non-retryable — re-raise immediately
            raise
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Content hash for deduplication
# ---------------------------------------------------------------------------

def _batch_hash(data: dict) -> str:
    """Return a SHA-256 hex digest of the canonicalised JSON payload."""
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


async def _is_duplicate(content_hash: str, tenant_id: str) -> Optional[str]:
    """Return cached GCS URI if this hash was already processed, else None."""
    if not _REDIS_AVAILABLE:
        return None
    try:
        key = f"ingest:dedup:{tenant_id}:{content_hash}"
        return await _get_redis().get(key)
    except Exception as exc:
        logger.warning("[dedup] Redis error during duplicate check: %s", exc)
        return None


async def _record_hash(content_hash: str, tenant_id: str, gcs_uri: str) -> None:
    """Store the content hash → GCS URI mapping with TTL."""
    if not _REDIS_AVAILABLE:
        return
    try:
        key = f"ingest:dedup:{tenant_id}:{content_hash}"
        await _get_redis().set(key, gcs_uri, ex=DEDUP_TTL)
    except Exception as exc:
        logger.warning("[dedup] Redis error recording hash: %s", exc)


# ---------------------------------------------------------------------------
# GCS / Pub/Sub helpers (called from background tasks)
# ---------------------------------------------------------------------------

def _json_serial(obj):
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


async def _write_to_gcs(data: dict, blob_path: str) -> str:
    """Write *data* as JSON to GCS and return the gs:// URI."""

    async def _upload():
        bucket = storage_client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_path)
        json_bytes = json.dumps(data, ensure_ascii=False, default=_json_serial).encode("utf-8")
        # storage client is synchronous — run in default thread-pool executor
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: blob.upload_from_string(json_bytes, content_type="application/json"),
        )
        return f"gs://{GCS_BUCKET}/{blob_path}"

    return await _with_retry(_upload)


async def _emit_pubsub(
    gcs_uri: str,
    source: str,
    data_type: str,
    record_count: int,
    tenant_id: str,
    batch_id: str,
) -> Optional[str]:
    """Publish a structured event envelope to Pub/Sub."""

    async def _publish():
        envelope = {
            "event_type": "ingestion.completed",
            "schema_version": "1.1",
            "gcs_uri": gcs_uri,
            "source": source,
            "data_type": data_type,
            "record_count": record_count,
            "tenant_id": tenant_id,
            "batch_id": batch_id,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        msg_bytes = json.dumps(envelope).encode("utf-8")
        loop = asyncio.get_event_loop()
        future = publisher_client.publish(
            PUBSUB_TOPIC,
            msg_bytes,
            source=source,
            data_type=data_type,
            tenant_id=tenant_id,
        )
        message_id = await loop.run_in_executor(None, lambda: future.result(timeout=10))
        logger.info("Published Pub/Sub message %s for tenant=%s", message_id, tenant_id)
        return message_id

    try:
        return await _with_retry(_publish)
    except Exception as exc:
        # Pub/Sub failure is non-fatal — data is already in GCS
        logger.error("[pubsub] Publish failed after retries: %s", exc)
        return None


def _background_upload_and_publish(
    data: dict,
    blob_path: str,
    source: str,
    data_type: str,
    record_count: int,
    tenant_id: str,
    batch_id: str,
    content_hash: str,
) -> None:
    """Sync wrapper for use with FastAPI BackgroundTasks (runs in thread-pool)."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            _do_upload_and_publish(
                data, blob_path, source, data_type, record_count, tenant_id, batch_id, content_hash
            )
        )
    finally:
        loop.close()


async def _do_upload_and_publish(
    data: dict,
    blob_path: str,
    source: str,
    data_type: str,
    record_count: int,
    tenant_id: str,
    batch_id: str,
    content_hash: str,
) -> None:
    try:
        gcs_uri = await _write_to_gcs(data, blob_path)
        logger.info("Background GCS write complete: %s", gcs_uri)
        await _record_hash(content_hash, tenant_id, gcs_uri)
        await _emit_pubsub(gcs_uri, source, data_type, record_count, tenant_id, batch_id)
    except Exception as exc:
        logger.error(
            "Background upload failed for tenant=%s batch=%s: %s",
            tenant_id, batch_id, exc,
        )


# ---------------------------------------------------------------------------
# Auth helper — extract tenant_id from token payload
# ---------------------------------------------------------------------------

async def _verify_and_get_tenant(credentials: HTTPAuthorizationCredentials) -> tuple[dict, str]:
    token_data = await verify_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
    tenant_id: str = str(token_data.get("tenant_id", token_data.get("sub", "unknown")))
    return token_data, tenant_id


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {"service": "Risk Workflow Ingestion API", "status": "healthy", "version": "2.0.0"}


@app.get("/health")
async def health_check():
    health_status: dict = {
        "status": "healthy",
        "gcs_bucket": GCS_BUCKET,
        "pubsub_topic": PUBSUB_TOPIC,
    }
    try:
        if storage_client:
            bucket = storage_client.bucket(GCS_BUCKET)
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, bucket.exists)
        health_status["gcs_connection"] = "ok"
    except Exception as e:
        health_status["gcs_connection"] = f"error: {str(e)}"
        health_status["status"] = "degraded"

    if _REDIS_AVAILABLE:
        try:
            await _get_redis().ping()
            health_status["redis_connection"] = "ok"
        except Exception as e:
            health_status["redis_connection"] = f"error: {str(e)}"
    else:
        health_status["redis_connection"] = "unavailable"

    return health_status


# ---------------------------------------------------------------------------
# Ingestion endpoints
# ---------------------------------------------------------------------------

@app.post("/transactions", response_model=IngestionResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_transactions(
    batch: TransactionBatch,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> IngestionResponse:
    """
    Ingest a batch of transactions.

    GCS upload and Pub/Sub publish happen asynchronously in a background task.
    Returns 202 Accepted immediately.  Duplicate batches (same SHA-256) within
    the dedup TTL are skipped and return 200 with the original GCS URI.
    """
    _, tenant_id = await _verify_and_get_tenant(credentials)

    logger.info("Processing transaction batch source=%s tenant=%s", batch.source, tenant_id)

    try:
        batch_dict = batch.model_dump()
        content_hash = _batch_hash(batch_dict)

        # Deduplication check
        cached_uri = await _is_duplicate(content_hash, tenant_id)
        if cached_uri:
            logger.info("Duplicate transaction batch detected, returning cached URI: %s", cached_uri)
            return IngestionResponse(
                status="duplicate",
                gcs_uri=cached_uri,
                message_id=None,
                record_count=len(batch.transactions),
                ingested_at=datetime.now(timezone.utc),
            )

        # Pre-compute deterministic GCS path (URI is valid before upload completes)
        batch_id = str(uuid.uuid4())
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        blob_path = f"{batch.source}/transactions/{date_str}/{batch_id}.json"
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_path}"

        # Offload I/O to background task
        background_tasks.add_task(
            _background_upload_and_publish,
            batch_dict, blob_path,
            batch.source, "transactions",
            len(batch.transactions),
            tenant_id, batch_id, content_hash,
        )

        return IngestionResponse(
            status="accepted",
            gcs_uri=gcs_uri,
            message_id=None,
            record_count=len(batch.transactions),
            ingested_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error in transaction ingestion: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during ingestion",
        )


@app.post("/applications", response_model=IngestionResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_applications(
    batch: ApplicationBatch,
    background_tasks: BackgroundTasks,
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> IngestionResponse:
    """
    Ingest a batch of loan applications.

    GCS upload and Pub/Sub publish happen asynchronously in a background task.
    Returns 202 Accepted immediately.  Duplicate batches (same SHA-256) within
    the dedup TTL are skipped.
    """
    _, tenant_id = await _verify_and_get_tenant(credentials)

    logger.info("Processing application batch source=%s tenant=%s", batch.source, tenant_id)

    try:
        batch_dict = batch.model_dump()
        content_hash = _batch_hash(batch_dict)

        # Deduplication check
        cached_uri = await _is_duplicate(content_hash, tenant_id)
        if cached_uri:
            logger.info("Duplicate application batch detected, returning cached URI: %s", cached_uri)
            return IngestionResponse(
                status="duplicate",
                gcs_uri=cached_uri,
                message_id=None,
                record_count=len(batch.applications),
                ingested_at=datetime.now(timezone.utc),
            )

        batch_id = str(uuid.uuid4())
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        blob_path = f"{batch.source}/applications/{date_str}/{batch_id}.json"
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_path}"

        background_tasks.add_task(
            _background_upload_and_publish,
            batch_dict, blob_path,
            batch.source, "applications",
            len(batch.applications),
            tenant_id, batch_id, content_hash,
        )

        return IngestionResponse(
            status="accepted",
            gcs_uri=gcs_uri,
            message_id=None,
            record_count=len(batch.applications),
            ingested_at=datetime.now(timezone.utc),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Unexpected error in application ingestion: %s", str(e), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during ingestion",
        )


# ---------------------------------------------------------------------------
# Sprint 5-B — LOS Webhook Receiver  (GAP-13)
# ---------------------------------------------------------------------------

# LOS field-name maps for common vendors (configurable via env vars)
# Each vendor maps: LOS field name → canonical LoanApplication field name
_LOS_FIELD_MAPS: dict[str, dict[str, str]] = {
    "encompass": {
        "LoanAmount": "loan_amount",
        "BorrowerFirstName": "first_name",
        "BorrowerLastName": "last_name",
        "AnnualIncome": "annual_income",
        "CreditScore": "credit_score",
        "LoanPurpose": "loan_purpose",
        "LoanTermMonths": "loan_term_months",
    },
    "blend": {
        "amount": "loan_amount",
        "annual_income": "annual_income",
        "fico_score": "credit_score",
        "purpose": "loan_purpose",
        "term": "loan_term_months",
    },
    "maxwell": {
        "requestedAmount": "loan_amount",
        "grossIncome": "annual_income",
        "creditScore": "credit_score",
        "loanPurpose": "loan_purpose",
        "loanTerm": "loan_term_months",
    },
    "besmartee": {
        "loan_amount_requested": "loan_amount",
        "borrower_income": "annual_income",
        "credit_score": "credit_score",
        "loan_purpose": "loan_purpose",
        "loan_term": "loan_term_months",
    },
    "floify": {
        "loanAmount": "loan_amount",
        "yearlyIncome": "annual_income",
        "ficoScore": "credit_score",
        "loanPurpose": "loan_purpose",
        "loanTermMonths": "loan_term_months",
    },
}

# Default (passthrough) map when vendor is unknown
_LOS_DEFAULT_MAP: dict[str, str] = {
    "loan_amount": "loan_amount",
    "annual_income": "annual_income",
    "credit_score": "credit_score",
    "loan_purpose": "loan_purpose",
    "loan_term_months": "loan_term_months",
}


class LOSWebhookPayload(BaseModel):
    """Inbound event from a Loan Origination System."""

    los_application_id: str
    event_type: str            # "APPLICATION_SUBMITTED" | "STATUS_UPDATED" | "DOCUMENT_UPLOADED"
    applicant: dict            # Raw applicant fields (vendor-specific)
    loan_request: dict         # Raw loan fields (vendor-specific)
    submitted_at: str          # ISO-8601 timestamp
    vendor: str = "default"    # LOS vendor identifier (e.g. "encompass")


def _map_los_to_decision(payload: LOSWebhookPayload) -> dict:
    """Map ``LOSWebhookPayload`` fields to the Decision API ``LoanApplicationRequest`` schema.

    Applies the per-vendor field map if recognised, otherwise falls back to the
    passthrough default map.
    """
    vendor = (payload.vendor or "default").lower()
    field_map = _LOS_FIELD_MAPS.get(vendor, _LOS_DEFAULT_MAP)

    # Merge applicant + loan_request fields
    combined = {**payload.applicant, **payload.loan_request}

    canonical: dict = {
        "application_id": payload.los_application_id,
        "loan_purpose": "personal",
        "loan_term_months": 36,
        "submitted_at": payload.submitted_at,
    }

    for vendor_key, canonical_key in field_map.items():
        if vendor_key in combined and combined[vendor_key] is not None:
            canonical[canonical_key] = combined[vendor_key]

    # Apply env-var overrides for custom field-name mappings
    # e.g. LOS_FIELD_loan_amount=myCustomLoanAmountField
    for env_key, env_val in os.environ.items():
        if env_key.startswith("LOS_FIELD_"):
            canonical_name = env_key[len("LOS_FIELD_"):].lower()
            if env_val in combined:
                canonical[canonical_name] = combined[env_val]

    return canonical


# ---------------------------------------------------------------------------
# GAP-18: Real-Time Credit Bureau Integration — BureauRouter replaces the
# old _MOCK_BUREAU_RESPONSE / single-call pattern.
# ---------------------------------------------------------------------------
try:
    from bureau_clients.router import BureauRouter
    from bureau_clients.models import BureauRequest, BureauPullError
except ImportError:
    from src.bureau_clients.router import BureauRouter          # type: ignore[no-redef]
    from src.bureau_clients.models import BureauRequest, BureauPullError  # type: ignore[no-redef]

_BUREAU_ROUTER: "BureauRouter | None" = None


def _get_bureau_router() -> BureauRouter:
    global _BUREAU_ROUTER
    if _BUREAU_ROUTER is None:
        _BUREAU_ROUTER = BureauRouter.from_env()
    return _BUREAU_ROUTER


async def enrich_with_bureau_data(
    application_id: str,
    applicant: dict,
) -> dict:
    """Enrich *applicant* with live bureau data via BureauRouter.

    Falls back to ``MockBureauClient`` automatically when no production
    credentials are configured (``BUREAU_PRIMARY`` defaults to ``"mock"``).

    Returns a merged dict of *applicant* + bureau feature fields.
    """
    router = _get_bureau_router()
    req = BureauRequest(
        application_id  =application_id,
        first_name      =applicant.get("first_name",    ""),
        last_name       =applicant.get("last_name",     ""),
        date_of_birth   =applicant.get("date_of_birth", "1970-01-01"),
        ssn_last4       =applicant.get("ssn_last4",     "0000"),
        address_line1   =applicant.get("address_line1", ""),
        city            =applicant.get("city",          ""),
        state           =applicant.get("state",         "CA"),
        zip_code        =applicant.get("zip_code",      "00000"),
        requested_amount=float(applicant.get("loan_amount",   0)),
        loan_purpose    =applicant.get("loan_purpose",  "personal"),
    )
    try:
        response = await router.pull(req)
        return {**applicant, **response.to_feature_dict(), "application_id": application_id}
    except BureauPullError as exc:
        logger.warning(
            "Bureau enrichment failed for application_id=%s — returning original applicant dict: %s",
            application_id, exc,
        )
        return {**applicant, "application_id": application_id}


# ---------------------------------------------------------------------------
# Document upload / OCR endpoint (GAP-17)
# ---------------------------------------------------------------------------

_MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "20")) * 1024 * 1024
_DOCUMENT_EVENTS_TOPIC = os.getenv("DOCUMENT_EVENTS_TOPIC", "document-extraction-results")


def _background_document_publish(
    application_id: str,
    doc_type: str,
    feature_dict: dict,
    tenant_id: str,
    pdf_bytes: bytes,
    blob_path: str,
) -> None:
    """Sync wrapper — runs in ThreadPool via BackgroundTasks."""
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            _do_document_upload_and_publish(
                application_id, doc_type, feature_dict, tenant_id, pdf_bytes, blob_path
            )
        )
    finally:
        loop.close()


async def _do_document_upload_and_publish(
    application_id: str,
    doc_type: str,
    feature_dict: dict,
    tenant_id: str,
    pdf_bytes: bytes,
    blob_path: str,
) -> None:
    try:
        # Upload raw PDF bytes to GCS
        if storage_client:
            loop = asyncio.get_event_loop()
            bucket = storage_client.bucket(GCS_BUCKET)
            blob = bucket.blob(blob_path)
            await loop.run_in_executor(
                None,
                lambda: blob.upload_from_string(pdf_bytes, content_type="application/pdf"),
            )
            logger.info("Document PDF uploaded to GCS: gs://%s/%s", GCS_BUCKET, blob_path)

        # Publish extraction-result event
        if publisher_client:
            topic = f"projects/{PROJECT_ID}/topics/{_DOCUMENT_EVENTS_TOPIC}"
            payload = {
                "event_type": "document.extraction.completed",
                "application_id": application_id,
                "doc_type": doc_type,
                "feature_dict": feature_dict,
                "tenant_id": tenant_id,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            msg_bytes = json.dumps(payload, default=str).encode("utf-8")
            loop = asyncio.get_event_loop()
            future = publisher_client.publish(topic, msg_bytes, tenant_id=tenant_id)
            await loop.run_in_executor(None, lambda: future.result(timeout=10))
            logger.info(
                "Document extraction event published for application_id=%s", application_id
            )
    except Exception as exc:
        logger.error(
            "Background document upload/publish failed for application_id=%s: %s",
            application_id, exc,
        )


@app.post(
    "/documents/{application_id}",
    response_model=DocumentExtractionResult,
    status_code=202,
    summary="Upload and OCR-process a document for a given application",
)
async def upload_document(
    application_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    document_type_hint: str = "unknown",
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> DocumentExtractionResult:
    """Accept a PDF document upload, run the OCR pipeline, and return extraction results.

    Steps:
    1. Authenticate via verify_and_get_tenant.
    2. Read file bytes; enforce 20 MB max (HTTP 413 if exceeded).
    3. Validate MIME type is application/pdf or application/octet-stream (HTTP 415 otherwise).
    4. SHA-256 deduplicate using ``doc:`` prefix.
    5. Run process_document pipeline.
    6. Background task: upload raw PDF to GCS.
    7. Background task: emit Pub/Sub extraction-result event.
    8. Return DocumentExtractionResult immediately.
    """
    _, tenant_id = await _verify_and_get_tenant(credentials)

    # --- Read file bytes ---
    file_bytes = await file.read()
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum allowed size is {_MAX_UPLOAD_BYTES // (1024*1024)} MB.",
        )

    # --- MIME type validation ---
    content_type = (file.content_type or "").lower()
    if content_type not in ("application/pdf", "application/octet-stream", ""):
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported media type '{content_type}'. Only application/pdf is accepted.",
        )

    # --- Deduplication ---
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    dedup_key = f"doc:{tenant_id}:{file_hash}"
    cached_uri = await _is_duplicate(file_hash, tenant_id)
    if cached_uri:
        logger.info(
            "Duplicate document upload detected for application_id=%s hash=%s",
            application_id, file_hash[:16],
        )
        duplicate_result = DocumentExtractionResult(
            application_id=application_id,
            document_type=DocumentType.UNKNOWN,
            filename=file.filename or "",
            page_count=0,
            extracted_fields=[],
            raw_text="",
            classification_confidence=0.0,
            processing_time_ms=0.0,
            errors=[],
            gcs_uri=cached_uri,
            feature_dict={"application_id": application_id, "duplicate": True},
        )
        return JSONResponse(
            content=duplicate_result.model_dump(mode="json"),
            status_code=200,
        )

    # --- Process document ---
    try:
        doc_type_hint: DocumentType | None = None
        if document_type_hint and document_type_hint != "unknown":
            try:
                doc_type_hint = DocumentType(document_type_hint)
            except ValueError:
                pass

        result = await process_document(
            file_bytes,
            application_id=application_id,
            filename=file.filename or "",
            client_document_type_hint=doc_type_hint,
            dpi=int(os.getenv("OCR_DPI", "300")),
            lang=os.getenv("OCR_LANG", "eng"),
        )
    except Exception as exc:
        logger.error(
            "process_document raised unexpectedly for application_id=%s: %s",
            application_id, exc, exc_info=True,
        )
        result = DocumentExtractionResult(
            application_id=application_id,
            document_type=DocumentType.UNKNOWN,
            filename=file.filename or "",
            page_count=0,
            extracted_fields=[],
            raw_text="",
            classification_confidence=0.0,
            processing_time_ms=0.0,
            errors=[str(exc)],
            gcs_uri=None,
            feature_dict={"application_id": application_id, "doc_type": "unknown"},
        )

    # --- Build GCS path and set on result ---
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blob_path = f"documents/{tenant_id}/{application_id}/{file.filename or 'document.pdf'}"
    gcs_uri = f"gs://{GCS_BUCKET}/{blob_path}"
    result = result.model_copy(update={"gcs_uri": gcs_uri})

    # --- Background tasks ---
    background_tasks.add_task(
        _background_document_publish,
        application_id,
        result.document_type.value,
        result.feature_dict,
        tenant_id,
        file_bytes,
        blob_path,
    )

    # Record hash for dedup (fire-and-forget)
    background_tasks.add_task(
        lambda: asyncio.run(_record_hash(file_hash, tenant_id, gcs_uri))
    )

    logger.info(
        "Document accepted: application_id=%s doc_type=%s pages=%d",
        application_id, result.document_type.value, result.page_count,
    )
    return result


@app.post("/webhook/los", status_code=202)
async def los_webhook(
    payload: LOSWebhookPayload,
    request: Request,
    x_los_signature: str = Header(default="", alias="X-LOS-Signature"),
) -> dict:
    """Receive an inbound event from a Loan Origination System.

    Steps:
    1. Validate HMAC-SHA256 signature using ``LOS_WEBHOOK_SECRET`` env var.
    2. Enrich applicant data with bureau information.
    3. Map ``LOSWebhookPayload`` to the Decision API schema.
    4. Forward to Decision API when ``event_type == APPLICATION_SUBMITTED``.
    5. Return ``{"received": True, "los_application_id": ...}``.
    """
    import hashlib as _hashlib
    import hmac as _hmac

    # Step 1 — Validate HMAC-SHA256 signature
    secret = os.getenv("LOS_WEBHOOK_SECRET", "")
    if secret:
        body = await request.body()
        expected_sig = _hmac.new(
            secret.encode(), msg=body, digestmod=_hashlib.sha256
        ).hexdigest()
        incoming_sig = x_los_signature.removeprefix("sha256=")
        if not _hmac.compare_digest(expected_sig, incoming_sig):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid LOS webhook signature",
            )

    logger.info(
        "LOS webhook received: los_application_id=%s event_type=%s vendor=%s",
        payload.los_application_id, payload.event_type, payload.vendor,
    )

    if payload.event_type == "APPLICATION_SUBMITTED":
        # Step 2 — Bureau enrichment
        enriched_applicant = await enrich_with_bureau_data(
            payload.los_application_id, payload.applicant
        )

        # Step 3 — Map to Decision API schema
        decision_payload = _map_los_to_decision(
            LOSWebhookPayload(
                los_application_id=payload.los_application_id,
                event_type=payload.event_type,
                applicant=enriched_applicant,
                loan_request=payload.loan_request,
                submitted_at=payload.submitted_at,
                vendor=payload.vendor,
            )
        )

        # Step 4 — Forward to Decision API
        decision_api_url = os.getenv("DECISION_API_URL", "http://decision-api:8000")
        internal_jwt = os.getenv("INTERNAL_JWT", "")
        try:
            import httpx as _httpx  # noqa: PLC0415

            async with _httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"{decision_api_url}/v1/decisions",
                    json=decision_payload,
                    headers={"Authorization": f"Bearer {internal_jwt}"},
                )
                resp.raise_for_status()
                logger.info(
                    "Forwarded LOS application to Decision API: %s → HTTP %s",
                    payload.los_application_id, resp.status_code,
                )
        except Exception as exc:
            logger.warning(
                "Decision API forward failed for %s: %s (application received but not scored)",
                payload.los_application_id, exc,
            )

    return {"received": True, "los_application_id": payload.los_application_id}


@app.post("/tenant/openbanking/sync")
async def sync_open_banking(credentials: HTTPAuthorizationCredentials = Security(security)):
    from auth import verify_token
    token_data = await verify_token(credentials.credentials)
    tenant_id = token_data.get("tenant_id")
    if tenant_id != "OPEN_BANKING_SBX":
        raise HTTPException(status_code=403, detail="Not authorized for Open Banking sync")
    return {"status": "success", "message": "Synced Open Banking Data"}

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"status": "error", "detail": "An unexpected error occurred"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
