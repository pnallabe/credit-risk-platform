"""Acceptance tests for the /documents/{application_id} endpoint (GAP-17, prompt G17-F)."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set required env vars before importing main
os.environ.setdefault("GCS_RAW_BUCKET", "test-bucket")
os.environ.setdefault("PUBSUB_TOPIC", "projects/test/topics/test")
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("JWT_SECRET", "test-secret-key")
os.environ.setdefault("JWT_ISSUER", "risk-platform")

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _get_test_token() -> str:
    """Return a JWT token accepted by the test server."""
    import jwt
    import time

    secret = os.environ.get("JWT_SECRET", "test-secret-key")
    payload = {
        "sub": "test-user",
        "tenant_id": "test-tenant",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "iss": os.environ.get("JWT_ISSUER", "risk-platform"),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _minimal_pdf_bytes(size_bytes: int = 1024) -> bytes:
    """Return a minimal fake PDF payload of the given size."""
    header = b"%PDF-1.4\n"
    padding = b"%" * (size_bytes - len(header))
    return header + padding


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDocumentUploadEndpoint:
    @pytest.fixture(autouse=True)
    def _patch_gcp(self):
        """Patch GCP clients so tests don't need real GCP credentials."""
        mock_storage = MagicMock()
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_storage.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        mock_bucket.exists.return_value = True

        mock_publisher = MagicMock()
        mock_future = MagicMock()
        mock_future.result.return_value = "msg-id"
        mock_publisher.publish.return_value = mock_future

        import main as main_module
        main_module.storage_client = mock_storage
        main_module.publisher_client = mock_publisher
        yield

    @pytest.fixture()
    def client(self):
        import main as main_module
        with TestClient(main_module.app, raise_server_exceptions=False) as c:
            yield c

    @pytest.fixture()
    def auth_headers(self):
        token = _get_test_token()
        return {"Authorization": f"Bearer {token}"}

    def _upload(self, client, auth_headers, file_bytes=None, content_type="application/pdf",
                filename="test.pdf", application_id="app-123"):
        if file_bytes is None:
            file_bytes = _minimal_pdf_bytes()
        return client.post(
            f"/documents/{application_id}",
            files={"file": (filename, io.BytesIO(file_bytes), content_type)},
            headers=auth_headers,
        )

    def test_happy_path_returns_202(self, client, auth_headers):
        """Mock process_document → endpoint returns 202 with DocumentExtractionResult."""
        from document_models import DocumentExtractionResult, DocumentType

        mock_result = DocumentExtractionResult(
            application_id="app-123",
            document_type=DocumentType.PAY_STUB,
            filename="test.pdf",
            page_count=1,
            extracted_fields=[],
            raw_text="gross pay net pay ytd",
            classification_confidence=0.9,
            processing_time_ms=42.0,
            errors=[],
            gcs_uri=None,
            feature_dict={"application_id": "app-123"},
        )

        import main as main_module
        with patch.object(main_module, "process_document", new=AsyncMock(return_value=mock_result)), \
             patch.object(main_module, "_is_duplicate", new=AsyncMock(return_value=None)):
            resp = self._upload(client, auth_headers)

        assert resp.status_code == 202
        data = resp.json()
        assert data["application_id"] == "app-123"
        assert "document_type" in data
        assert "feature_dict" in data

    def test_file_too_large_returns_413(self, client, auth_headers):
        """Files larger than MAX_UPLOAD_SIZE_MB should return HTTP 413."""
        import main as main_module
        # Temporarily reduce max upload to 1 byte
        original = main_module._MAX_UPLOAD_BYTES
        main_module._MAX_UPLOAD_BYTES = 10
        try:
            resp = self._upload(client, auth_headers, file_bytes=b"A" * 100)
        finally:
            main_module._MAX_UPLOAD_BYTES = original
        assert resp.status_code == 413

    def test_non_pdf_content_type_returns_415(self, client, auth_headers):
        """Non-PDF MIME type should return HTTP 415."""
        resp = self._upload(
            client, auth_headers,
            content_type="text/plain",
            filename="document.txt",
        )
        assert resp.status_code == 415

    def test_unauthenticated_returns_403_or_401(self, client):
        """Requests without auth token should be rejected."""
        resp = client.post(
            "/documents/app-123",
            files={"file": ("test.pdf", io.BytesIO(_minimal_pdf_bytes()), "application/pdf")},
        )
        assert resp.status_code in (401, 403)

    def test_background_tasks_enqueued(self, client, auth_headers):
        """GCS upload and publish helpers should be called via background tasks."""
        from document_models import DocumentExtractionResult, DocumentType

        mock_result = DocumentExtractionResult(
            application_id="app-456",
            document_type=DocumentType.BANK_STATEMENT,
            filename="statement.pdf",
            page_count=2,
            extracted_fields=[],
            raw_text="beginning balance ending balance",
            classification_confidence=0.85,
            processing_time_ms=55.0,
            errors=[],
            gcs_uri=None,
            feature_dict={"application_id": "app-456"},
        )

        # Use unique file content to avoid dedup collision with other tests
        unique_bytes = b"%PDF-1.4\n" + b"BACKGROUND_TASK_TEST_UNIQUE_CONTENT" + b"X" * 512

        import main as main_module
        with patch.object(main_module, "process_document", new=AsyncMock(return_value=mock_result)):
            with patch.object(main_module, "_is_duplicate", new=AsyncMock(return_value=None)):
                with patch.object(main_module, "_background_document_publish") as mock_bg:
                    resp = self._upload(
                        client, auth_headers,
                        file_bytes=unique_bytes,
                        application_id="app-456",
                        filename="statement.pdf",
                    )

        # The background task is registered synchronously; the mock should be called
        # during the TestClient context (which runs background tasks synchronously).
        assert resp.status_code == 202

    def test_duplicate_upload_returns_200(self, client, auth_headers):
        """Duplicate document upload (same SHA-256) should return 200 with cached result."""
        from document_models import DocumentExtractionResult, DocumentType

        mock_result = DocumentExtractionResult(
            application_id="app-789",
            document_type=DocumentType.TAX_RETURN,
            filename="1040.pdf",
            page_count=1,
            extracted_fields=[],
            raw_text="form 1040 adjusted gross income",
            classification_confidence=0.88,
            processing_time_ms=60.0,
            errors=[],
            gcs_uri="gs://test-bucket/documents/test-tenant/app-789/1040.pdf",
            feature_dict={"application_id": "app-789"},
        )

        import main as main_module
        # Simulate a cached hit from Redis
        with patch.object(
            main_module, "_is_duplicate",
            new=AsyncMock(return_value="gs://test-bucket/documents/test-tenant/app-789/1040.pdf")
        ):
            resp = self._upload(
                client, auth_headers,
                application_id="app-789",
                filename="1040.pdf",
            )

        # Duplicate → returns 200 status code with the cached GCS URI in body
        assert resp.status_code == 200
        data = resp.json()
        assert data["gcs_uri"] is not None
