"""
FastAPI Ingestion API for AI Risk Workflow Platform
Handles transaction and application ingestion with GCS storage and Pub/Sub emission
"""

from fastapi import FastAPI, Depends, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from google.cloud import storage, pubsub_v1
from google.api_core import exceptions as gcp_exceptions
import json
import uuid
from datetime import datetime, timezone
from typing import List
import hashlib
import os
import logging
from contextlib import asynccontextmanager

# Import from same directory (for Docker deployment)
try:
    from models import TransactionBatch, ApplicationBatch, IngestionResponse
    from auth import verify_token
except ImportError:
    # Fallback for local development with src/ directory
    try:
        from src.models import TransactionBatch, ApplicationBatch, IngestionResponse
        from src.auth import verify_token
    except ImportError:
        print("ERROR: Could not import models and auth modules")
        raise

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log startup
logger.info("=" * 50)
logger.info("Starting AI Risk Workflow Ingestion API")
logger.info(f"Python version: {os.sys.version}")
logger.info(f"Working directory: {os.getcwd()}")
logger.info("=" * 50)

# Environment variables
GCS_BUCKET = os.getenv("GCS_RAW_BUCKET", "risk-raw-data")
PUBSUB_TOPIC = os.getenv("PUBSUB_TOPIC", "projects/YOUR_PROJECT/topics/ingestion-events")
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "YOUR_PROJECT")

# Global clients (initialized in lifespan)
storage_client = None
publisher_client = None

security = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup resources"""
    global storage_client, publisher_client
    
    try:
        logger.info("Initializing GCP clients...")
        storage_client = storage.Client(project=PROJECT_ID)
        publisher_client = pubsub_v1.PublisherClient()
        logger.info("✓ GCP clients initialized successfully")
        yield
    except Exception as e:
        logger.error(f"Failed to initialize GCP clients: {str(e)}")
        logger.warning("Application starting without GCP clients - health checks will work but API calls may fail")
        yield
    finally:
        # Cleanup if needed
        if publisher_client:
            try:
                # PublisherClient doesn't have close(), no cleanup needed
                logger.info("Publisher client cleanup complete")
            except Exception as e:
                logger.warning(f"Error during cleanup: {str(e)}")


app = FastAPI(
    title="Risk Workflow Ingestion API",
    description="Ingestion endpoints for transactions and loan applications",
    version="1.0.0",
    lifespan=lifespan
)


def write_to_gcs(data: dict, source: str, data_type: str) -> str:
    """
    Write raw data to GCS with proper path structure
    
    Args:
        data: Dictionary to write as JSON
        source: Source system identifier
        data_type: 'transactions' or 'applications'
        
    Returns:
        GCS URI of written object
    """
    try:
        bucket = storage_client.bucket(GCS_BUCKET)
        
        # Generate path: gs://risk-raw-data/{source}/{date}/{uuid}.json
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_uuid = str(uuid.uuid4())
        blob_path = f"{source}/{data_type}/{date_str}/{file_uuid}.json"
        
        blob = bucket.blob(blob_path)
        
        # Convert to JSON with Decimal and datetime handling
        from decimal import Decimal
        def json_serial(obj):
            """JSON serializer for objects not serializable by default json code"""
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, (datetime,)):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} not serializable")
        
        json_bytes = json.dumps(data, ensure_ascii=False, default=json_serial).encode('utf-8')
        blob.upload_from_string(
            json_bytes,
            content_type='application/json'
        )
        
        gcs_uri = f"gs://{GCS_BUCKET}/{blob_path}"
        logger.info(f"Written to GCS: {gcs_uri}")
        
        return gcs_uri
        
    except gcp_exceptions.GoogleAPIError as e:
        logger.error(f"GCS write failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Storage service error: {str(e)}"
        )


def emit_pubsub_message(gcs_uri: str, source: str, data_type: str, record_count: int) -> str:
    """
    Emit small Pub/Sub message with GCS URI reference
    
    Args:
        gcs_uri: GCS URI of stored data
        source: Source system identifier
        data_type: 'transactions' or 'applications'
        record_count: Number of records in batch
        
    Returns:
        Message ID from Pub/Sub
    """
    try:
        message_data = {
            "gcs_uri": gcs_uri,
            "source": source,
            "data_type": data_type,
            "record_count": record_count,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "event_type": "ingestion.completed"
        }
        
        # Publish message
        message_json = json.dumps(message_data)
        future = publisher_client.publish(
            PUBSUB_TOPIC,
            message_json.encode('utf-8'),
            source=source,
            data_type=data_type
        )
        
        message_id = future.result(timeout=10)
        logger.info(f"Published message {message_id} to Pub/Sub")
        
        return message_id
        
    except Exception as e:
        logger.error(f"Pub/Sub publish failed: {str(e)}")
        # Don't fail the request if Pub/Sub fails - data is already in GCS
        # Could implement retry logic or dead-letter queue here
        return None


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Risk Workflow Ingestion API",
        "status": "healthy",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    health_status = {
        "status": "healthy",
        "gcs_bucket": GCS_BUCKET,
        "pubsub_topic": PUBSUB_TOPIC
    }
    
    # Test GCS connection
    try:
        bucket = storage_client.bucket(GCS_BUCKET)
        bucket.exists()
        health_status["gcs_connection"] = "ok"
    except Exception as e:
        health_status["gcs_connection"] = f"error: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status


@app.post("/transactions", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def ingest_transactions(
    batch: TransactionBatch,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> IngestionResponse:
    """
    Ingest batch of transactions
    
    Args:
        batch: Validated transaction batch
        credentials: JWT token for authentication
        
    Returns:
        Ingestion response with GCS URI and message ID
    """
    # Verify authentication
    token_data = await verify_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    logger.info(f"Processing transaction batch from source: {batch.source}")
    
    try:
        # Convert to dict for storage
        batch_dict = batch.model_dump()
        
        # Write to GCS
        gcs_uri = write_to_gcs(
            data=batch_dict,
            source=batch.source,
            data_type="transactions"
        )
        
        # Emit Pub/Sub message
        message_id = emit_pubsub_message(
            gcs_uri=gcs_uri,
            source=batch.source,
            data_type="transactions",
            record_count=len(batch.transactions)
        )
        
        return IngestionResponse(
            status="success",
            gcs_uri=gcs_uri,
            message_id=message_id,
            record_count=len(batch.transactions),
            ingested_at=datetime.now(timezone.utc)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in transaction ingestion: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during ingestion"
        )


@app.post("/applications", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def ingest_applications(
    batch: ApplicationBatch,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> IngestionResponse:
    """
    Ingest batch of loan applications
    
    Args:
        batch: Validated application batch
        credentials: JWT token for authentication
        
    Returns:
        Ingestion response with GCS URI and message ID
    """
    # Verify authentication
    token_data = await verify_token(credentials.credentials)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token"
        )
    
    logger.info(f"Processing application batch from source: {batch.source}")
    
    try:
        # Convert to dict for storage
        batch_dict = batch.model_dump()
        
        # Write to GCS
        gcs_uri = write_to_gcs(
            data=batch_dict,
            source=batch.source,
            data_type="applications"
        )
        
        # Emit Pub/Sub message
        message_id = emit_pubsub_message(
            gcs_uri=gcs_uri,
            source=batch.source,
            data_type="applications",
            record_count=len(batch.applications)
        )
        
        return IngestionResponse(
            status="success",
            gcs_uri=gcs_uri,
            message_id=message_id,
            record_count=len(batch.applications),
            ingested_at=datetime.now(timezone.utc)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in application ingestion: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during ingestion"
        )


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": "error",
            "detail": "An unexpected error occurred"
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)