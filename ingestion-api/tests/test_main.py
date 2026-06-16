"""
Unit tests for ingestion API
Run with: pytest test_main.py -v --cov=main
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import json

from main import app
from models import Transaction, TransactionBatch, LoanApplication, ApplicationBatch
from auth import create_access_token


@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)


@pytest.fixture
def valid_token():
    """Generate valid JWT token for testing"""
    return create_access_token(subject="test-user", expires_delta=3600)


@pytest.fixture
def sample_transaction():
    """Sample transaction data"""
    return Transaction(
        transaction_id="txn_123",
        account_id="acc_456",
        customer_id="cust_789",
        amount=Decimal("100.50"),
        currency="USD",
        posted_at=datetime.now(timezone.utc),
        description="Test transaction",
        mcc="5411",
        counterparty="Test Store",
        transaction_type="debit",
        channel="online"
    )


@pytest.fixture
def sample_transaction_batch(sample_transaction):
    """Sample transaction batch"""
    return TransactionBatch(
        source="test-system",
        batch_id="batch_001",
        transactions=[sample_transaction]
    )


@pytest.fixture
def sample_application():
    """Sample loan application"""
    return LoanApplication(
        application_id="app_123",
        customer_id="cust_789",
        account_id="acc_456",
        loan_amount=Decimal("50000.00"),
        loan_purpose="debt_consolidation",
        loan_term_months=60,
        interest_rate=Decimal("7.5"),
        annual_income=Decimal("75000.00"),
        employment_status="full_time",
        employment_length_months=36,
        credit_score=720,
        existing_debt=Decimal("15000.00"),
        applied_at=datetime.now(timezone.utc),
        channel="online"
    )


@pytest.fixture
def sample_application_batch(sample_application):
    """Sample application batch"""
    return ApplicationBatch(
        source="test-system",
        batch_id="batch_001",
        applications=[sample_application]
    )


class TestHealthEndpoints:
    """Test health check endpoints"""
    
    def test_ingest_transactions_unauthorized(self, client, sample_transaction_batch):
        """Test transaction ingestion without auth token"""
        response = client.post(
            "/transactions",
            json=sample_transaction_batch.model_dump(mode='json')
        )
        assert response.status_code == 403
    
    def test_ingest_transactions_invalid_token(self, client, sample_transaction_batch):
        """Test transaction ingestion with invalid token"""
        response = client.post(
            "/transactions",
            json=sample_transaction_batch.model_dump(mode='json'),
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401
    
    def test_ingest_transactions_validation_error(self, client, valid_token):
        """Test transaction ingestion with invalid data"""
        invalid_batch = {
            "source": "test-system",
            "transactions": [
                {
                    "transaction_id": "txn_123",
                    "account_id": "acc_456",
                    "amount": "not_a_number",  # Invalid
                    "posted_at": "invalid_date",  # Invalid
                    "transaction_type": "debit"
                }
            ]
        }
        
        response = client.post(
            "/transactions",
            json=invalid_batch,
            headers={"Authorization": f"Bearer {valid_token}"}
        )
        assert response.status_code == 422
    
    def test_ingest_transactions_empty_batch(self, client, valid_token):
        """Test transaction ingestion with empty batch"""
        empty_batch = {
            "source": "test-system",
            "transactions": []
        }
        
        response = client.post(
            "/transactions",
            json=empty_batch,
            headers={"Authorization": f"Bearer {valid_token}"}
        )
        assert response.status_code == 422


class TestApplicationIngestion:
    """Test loan application ingestion endpoint"""
    
    @patch('main.storage_client')
    @patch('main.publisher_client')
    def test_ingest_applications_success(
        self, mock_publisher, mock_storage, client,
        sample_application_batch, valid_token
    ):
        """Test successful application ingestion"""
        # Mock GCS
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_storage.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        
        # Mock Pub/Sub
        mock_future = Mock()
        mock_future.result.return_value = "msg_456"
        mock_publisher.publish.return_value = mock_future
        
        # Make request
        response = client.post(
            "/applications",
            json=sample_application_batch.model_dump(mode='json'),
            headers={"Authorization": f"Bearer {valid_token}"}
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["record_count"] == 1
        assert "gcs_uri" in data
        
        # Verify GCS write was called
        mock_blob.upload_from_string.assert_called_once()
    
    def test_ingest_applications_unauthorized(self, client, sample_application_batch):
        """Test application ingestion without auth token"""
        response = client.post(
            "/applications",
            json=sample_application_batch.model_dump(mode='json')
        )
        assert response.status_code == 403


class TestModels:
    """Test Pydantic models"""
    
    def test_transaction_validation_valid(self):
        """Test valid transaction passes validation"""
        txn = Transaction(
            transaction_id="txn_123",
            account_id="acc_456",
            amount=Decimal("100.00"),
            currency="USD",
            posted_at=datetime.now(timezone.utc),
            transaction_type="debit"
        )
        assert txn.transaction_id == "txn_123"
        assert txn.currency == "USD"
    
    def test_transaction_validation_currency_normalized(self):
        """Test currency code is normalized to uppercase"""
        txn = Transaction(
            transaction_id="txn_123",
            account_id="acc_456",
            amount=Decimal("100.00"),
            currency="usd",  # lowercase
            posted_at=datetime.now(timezone.utc),
            transaction_type="debit"
        )
        assert txn.currency == "USD"
    
    def test_transaction_validation_invalid_currency(self):
        """Test invalid currency code raises error"""
        with pytest.raises(ValueError):
            Transaction(
                transaction_id="txn_123",
                account_id="acc_456",
                amount=Decimal("100.00"),
                currency="US",  # Too short
                posted_at=datetime.now(timezone.utc),
                transaction_type="debit"
            )
    
    def test_transaction_validation_invalid_type(self):
        """Test invalid transaction type raises error"""
        with pytest.raises(ValueError):
            Transaction(
                transaction_id="txn_123",
                account_id="acc_456",
                amount=Decimal("100.00"),
                currency="USD",
                posted_at=datetime.now(timezone.utc),
                transaction_type="invalid_type"
            )
    
    def test_transaction_batch_size_limit(self):
        """Test transaction batch size limit"""
        transactions = [
            Transaction(
                transaction_id=f"txn_{i}",
                account_id="acc_456",
                amount=Decimal("100.00"),
                currency="USD",
                posted_at=datetime.now(timezone.utc),
                transaction_type="debit"
            )
            for i in range(10001)  # Exceeds limit
        ]
        
        with pytest.raises(ValueError):
            TransactionBatch(
                source="test-system",
                transactions=transactions
            )
    
    def test_loan_application_validation_valid(self):
        """Test valid loan application passes validation"""
        app = LoanApplication(
            application_id="app_123",
            customer_id="cust_789",
            loan_amount=Decimal("50000.00"),
            loan_purpose="personal",
            loan_term_months=60,
            applied_at=datetime.now(timezone.utc)
        )
        assert app.application_id == "app_123"
        assert app.loan_purpose == "personal"
    
    def test_loan_application_invalid_credit_score(self):
        """Test invalid credit score raises error"""
        with pytest.raises(ValueError):
            LoanApplication(
                application_id="app_123",
                customer_id="cust_789",
                loan_amount=Decimal("50000.00"),
                loan_purpose="personal",
                loan_term_months=60,
                credit_score=900,  # Too high
                applied_at=datetime.now(timezone.utc)
            )
    
    def test_loan_application_purpose_normalized(self):
        """Test loan purpose is normalized"""
        app = LoanApplication(
            application_id="app_123",
            customer_id="cust_789",
            loan_amount=Decimal("50000.00"),
            loan_purpose="Debt Consolidation",  # Mixed case with space
            loan_term_months=60,
            applied_at=datetime.now(timezone.utc)
        )
        assert app.loan_purpose == "debt_consolidation"


class TestAuthentication:
    """Test authentication module"""
    
    def test_create_access_token(self):
        """Test JWT token creation"""
        token = create_access_token(subject="test-user")
        assert isinstance(token, str)
        assert len(token) > 0
    
    @pytest.mark.asyncio
    async def test_verify_valid_token(self):
        """Test verification of valid token"""
        from auth import verify_token
        
        token = create_access_token(subject="test-user")
        payload = await verify_token(token)
        
        assert payload is not None
        assert payload["sub"] == "test-user"
    
    @pytest.mark.asyncio
    async def test_verify_invalid_token(self):
        """Test verification of invalid token"""
        from auth import verify_token
        from fastapi import HTTPException
        
        with pytest.raises(HTTPException) as exc_info:
            await verify_token("invalid_token")
        
        assert exc_info.value.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=main", "--cov-report=html"]) test_root_endpoint(self, client):
        """Test root endpoint returns service info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Risk Workflow Ingestion API"
        assert data["status"] == "healthy"
    
    def test_health_endpoint(self, client):
        """Test health check endpoint"""
        with patch('main.storage_client') as mock_storage:
            mock_bucket = Mock()
            mock_bucket.exists.return_value = True
            mock_storage.bucket.return_value = mock_bucket
            
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "gcs_connection" in data


class TestTransactionIngestion:
    """Test transaction ingestion endpoint"""
    
    @patch('main.storage_client')
    @patch('main.publisher_client')
    def test_ingest_transactions_success(
        self, mock_publisher, mock_storage, client, 
        sample_transaction_batch, valid_token
    ):
        """Test successful transaction ingestion"""
        # Mock GCS
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_storage.bucket.return_value = mock_bucket
        mock_bucket.blob.return_value = mock_blob
        
        # Mock Pub/Sub
        mock_future = Mock()
        mock_future.result.return_value = "msg_123"
        mock_publisher.publish.return_value = mock_future
        
        # Make request
        response = client.post(
            "/transactions",
            json=sample_transaction_batch.model_dump(mode='json'),
            headers={"Authorization": f"Bearer {valid_token}"}
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "success"
        assert data["record_count"] == 1
        assert "gcs_uri" in data
        assert "message_id" in data
        
        # Verify GCS write was called
        mock_blob.upload_from_string.assert_called_once()
        
        # Verify Pub/Sub publish was called
        mock_publisher.publish.assert_called_once()
    
    def test_ingest_transactions_unauthorized(self, client, sample_transaction_batch):
        """Test transaction ingestion without auth token"""
        response = client.post(
            "/transactions",
            json=sample_transaction_batch.model_dump(mode='json')
        )
        assert response.status_code == 403