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

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Security, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.api_core import exceptions as gcp_exceptions
from google.cloud import pubsub_v1, storage

# Import from same directory (for Docker deployment)
try:
    from models import ApplicationBatch, IngestionResponse, TransactionBatch
    from auth import verify_token
except ImportError:
    try:
        from src.models import ApplicationBatch, IngestionResponse, TransactionBatch
        from src.auth import verify_token
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
        yield
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
# Global exception handler
# ---------------------------------------------------------------------------

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
