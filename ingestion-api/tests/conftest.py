"""
Pytest configuration and shared fixtures
"""

import pytest
import os
from unittest.mock import Mock, MagicMock


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Setup test environment variables"""
    os.environ["GCS_RAW_BUCKET"] = "test-bucket"
    os.environ["PUBSUB_TOPIC"] = "projects/test/topics/test"
    os.environ["GCP_PROJECT_ID"] = "test-project"
    os.environ["JWT_SECRET"] = "test-secret-key"
    os.environ["JWT_ISSUER"] = "risk-platform"
    

@pytest.fixture(autouse=True)
def mock_gcp_clients(monkeypatch):
    """Mock GCP clients for all tests"""
    # Mock storage client
    mock_storage = Mock()
    mock_bucket = Mock()
    mock_blob = Mock()
    mock_storage.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    mock_bucket.exists.return_value = True
    
    # Mock publisher client
    mock_publisher = Mock()
    mock_future = Mock()
    mock_future.result.return_value = "test-message-id"
    mock_publisher.publish.return_value = mock_future
    
    # Patch the global clients
    import main
    main.storage_client = mock_storage
    main.publisher_client = mock_publisher
    
    return {
        "storage": mock_storage,
        "publisher": mock_publisher,
        "bucket": mock_bucket,
        "blob": mock_blob
    }


def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "gcp: mark test as requiring GCP credentials"
    )