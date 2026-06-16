# AI Risk Workflow Platform - Ingestion API
## Complete Project Structure & Implementation Guide

## 📁 Project Structure

```
ingestion-api/
│
├── src/                          # Source code (production ready)
│   ├── main.py                   # FastAPI application entry point
│   ├── models.py                 # Pydantic validation models
│   └── auth.py                   # JWT authentication logic
│
├── tests/                        # Test suite
│   ├── test_main.py             # Unit tests
│   └── conftest.py              # Pytest configuration
│
├── deployment/                   # Deployment configurations
│   ├── cloudbuild.yaml          # Cloud Build CI/CD pipeline
│   ├── Dockerfile               # Container image definition
│   └── deploy.sh                # Manual deployment script
│
├── examples/                     # Example data and scripts
│   └── example_payloads.json    # Sample API requests
│
├── docs/                         # Documentation
│   ├── README.md                # Main documentation
│   └── PROJECT_STRUCTURE.md     # This file
│
├── requirements.txt              # Python dependencies
├── .env.example                 # Environment variables template
├── .gitignore                   # Git ignore rules
├── Makefile                     # Development commands
├── setup.sh                     # Quick setup script
└── pytest.ini                   # Pytest configuration

```

## 🏗️ Architecture Components

### 1. **API Layer** (`main.py`)
- **FastAPI Application**: Async web framework
- **Endpoints**: `/transactions`, `/applications`
- **Authentication**: JWT bearer token verification
- **Error Handling**: Global exception handlers
- **Logging**: Structured Cloud Logging compatible

### 2. **Data Models** (`models.py`)
- **Transaction**: Individual transaction with validation
- **TransactionBatch**: Batch of up to 10,000 transactions
- **LoanApplication**: Loan application with business rules
- **ApplicationBatch**: Batch of up to 1,000 applications
- **IngestionResponse**: Standard API response format

### 3. **Authentication** (`auth.py`)
- **JWT Token Verification**: RS256/HS256 support
- **API Key Support**: Simple key-based auth (dev)
- **GCP IAM Integration**: Production-ready (commented)

### 4. **Storage Layer**
- **GCS**: Raw data storage with versioning
- **Path Structure**: `{source}/{type}/{date}/{uuid}.json`
- **Lifecycle**: 90-day retention policy
- **Pub/Sub**: Event-driven trigger for downstream

## 🔄 Data Flow

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /transactions or /applications
       │ Authorization: Bearer <token>
       ▼
┌─────────────────────────────────────┐
│     FastAPI Ingestion API           │
│  ┌─────────────────────────────┐   │
│  │  1. Verify JWT Token        │   │
│  │  2. Validate with Pydantic  │   │
│  │  3. Write to GCS            │   │
│  │  4. Emit Pub/Sub message    │   │
│  │  5. Return response         │   │
│  └─────────────────────────────┘   │
└───────┬──────────────────┬──────────┘
        │                  │
        ▼                  ▼
┌──────────────┐   ┌──────────────┐
│  GCS Bucket  │   │   Pub/Sub    │
│              │   │    Topic     │
│ gs://risk-   │   │              │
│ raw-data/    │   │ → Dataflow   │
└──────────────┘   └──────────────┘
```

## 🚀 Deployment Options

### Option 1: Cloud Build (Recommended)
Automated CI/CD pipeline triggered by Git push:
```bash
git push origin dev   # Auto-deploys to dev
git push origin main  # Auto-deploys to prod
```

**Pipeline Steps**:
1. Install dependencies
2. Run linting (black, flake8, mypy)
3. Run unit tests with coverage
4. Build Docker image
5. Push to Artifact Registry
6. Deploy to Cloud Run
7. Run smoke tests

### Option 2: Manual Deployment
Using the deployment script:
```bash
./deploy.sh dev   # Deploy to development
./deploy.sh prod  # Deploy to production
```

### Option 3: Local Development
Run locally with hot-reload:
```bash
make run
# or
uvicorn main:app --reload --port 8080
```

## 🧪 Testing Strategy

### Unit Tests
- **Coverage Target**: ≥80%
- **Framework**: pytest
- **Mocking**: unittest.mock for GCP clients
- **Run**: `make test`

### Integration Tests
- Test GCS write operations
- Test Pub/Sub publish
- Test end-to-end flow
- **Run**: `pytest -m integration`

### Load Tests
- Use Locust or Apache Bench
- Target: 1000 req/s sustained
- Monitor: latency, error rate, resource usage

### Test Pyramid
```
        /\
       /  \      E2E Tests (Few)
      /────\
     /      \    Integration Tests (Some)
    /────────\
   /          \  Unit Tests (Many)
  /____________\
```

## 🔐 Security Considerations

### Authentication & Authorization
- ✅ JWT token validation with expiry
- ✅ HTTPS only (Cloud Run enforced)
- ✅ Service account least-privilege
- ✅ Secrets in Secret Manager
- ✅ API Gateway rate limiting (optional)

### Data Protection
- ✅ Input validation (Pydantic)
- ✅ Encryption at rest (GCS default)
- ✅ Encryption in transit (TLS 1.3)
- ✅ CMEK support (optional)
- ✅ VPC-SC perimeter (optional)

### Audit & Compliance
- ✅ Structured logging
- ✅ Request/response tracking
- ✅ Data lineage (GCS URI tracking)
- ✅ Immutable raw data storage

## 📊 Monitoring & Observability

### Key Metrics
- **Request Rate**: requests/second
- **Latency**: p50, p95, p99
- **Error Rate**: 4xx, 5xx percentages
- **GCS Write Latency**: time to write
- **Pub/Sub Publish Success**: percentage

### Dashboards
Create Cloud Monitoring dashboard:
```bash
# Request rate
sum(rate(run_request_count[5m]))

# Error rate
sum(rate(run_request_count{response_code_class="5xx"}[5m]))

# Latency
histogram_quantile(0.95, run_request_latencies)
```

### Alerts
Configure alerting policies:
- Error rate > 5% for 5 minutes
- Latency p95 > 1000ms
- Instance count at max

## 🔧 Configuration Management

### Environment Variables
Managed in three layers:
1. **`.env`** - Local development
2. **Cloud Run env vars** - Non-sensitive config
3. **Secret Manager** - Sensitive data (JWT secrets, API keys)

### Feature Flags
Implement using environment variables:
```python
ENABLE_FRAUD_CHECK = os.getenv("ENABLE_FRAUD_CHECK", "true").lower() == "true"
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "10000"))
```

## 📈 Performance Optimization

### Request Processing
- **Async I/O**: FastAPI async handlers
- **Connection Pooling**: GCP client reuse
- **Batch Processing**: Handle up to 10K transactions
- **Timeouts**: 300s Cloud Run timeout

### Resource Limits
```yaml
Memory: 1Gi
CPU: 2 vCPU
Concurrency: 100 requests/instance
Max Instances: 10 (auto-scaling)
Min Instances: 0 (scale to zero)
```

### Optimization Tips
1. **Batch Writes**: Write entire batch to GCS at once
2. **Async Pub/Sub**: Don't wait for publish confirmation
3. **Efficient Serialization**: Use orjson for faster JSON
4. **Connection Reuse**: Keep GCP clients in global scope

## 🐛 Troubleshooting Guide

### Common Issues

#### 1. 401 Unauthorized
**Symptoms**: All requests return 401
**Causes**:
- Invalid JWT token
- Token expired
- JWT_SECRET mismatch
**Solution**:
```bash
# Generate new token
make token
# Check secret matches
echo $JWT_SECRET
```

#### 2. 503 Service Unavailable
**Symptoms**: 503 errors on POST requests
**Causes**:
- GCS bucket doesn't exist
- Service account lacks permissions
- Pub/Sub topic not found
**Solution**:
```bash
# Check bucket exists
gsutil ls gs://${GCS_RAW_BUCKET}

# Check service account permissions
gcloud projects get-iam-policy ${GCP_PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:ingestion-api@*"
```

#### 3. 422 Validation Error
**Symptoms**: Request rejected with validation errors
**Causes**:
- Invalid data format
- Missing required fields
- Invalid field values
**Solution**:
```bash
# Validate payload against example
diff your_payload.json example_payloads.json

# Check API docs for field requirements
curl http://localhost:8080/docs
```

#### 4. High Latency
**Symptoms**: Requests taking > 1 second
**Causes**:
- Large batch size
- Cold start (first request)
- Network issues
**Solution**:
```bash
# Enable min instances to prevent cold starts
gcloud run services update ingestion-api-prod \
  --min-instances=1

# Monitor GCS write time
gcloud logging read "resource.type=cloud_run_revision" \
  --format=json | jq '.[] | select(.jsonPayload.message | contains("GCS"))'
```

## 🔄 Development Workflow

### Daily Development
```bash
# 1. Pull latest changes
git pull origin dev

# 2. Activate environment
source venv/bin/activate

# 3. Run tests
make test

# 4. Start development server
make run

# 5. Make changes and test
# Edit code...
pytest test_main.py::TestTransactionIngestion -v

# 6. Format and lint
make format
make lint

# 7. Commit changes
git add .
git commit -m "feat: add new validation rule"
git push origin feature/new-validation
```

### Release Process
```bash
# 1. Create release branch
git checkout -b release/v1.1.0

# 2. Update version numbers
# Edit version in main.py, README.md

# 3. Run full test suite
make validate

# 4. Merge to main
git checkout main
git merge release/v1.1.0

# 5. Tag release
git tag -a v1.1.0 -m "Release v1.1.0"
git push origin main --tags

# 6. Cloud Build auto-deploys to prod
```

## 📚 API Usage Examples

### Example 1: Ingest Transactions
```bash
# Generate token
TOKEN=$(python -c "from auth import create_access_token; print(create_access_token('api-user'))")

# Send request
curl -X POST https://ingestion-api-prod-xyz.run.app/transactions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "banking-core",
    "transactions": [
      {
        "transaction_id": "txn_001",
        "account_id": "acc_001",
        "amount": 100.00,
        "currency": "USD",
        "posted_at": "2025-09-29T12:00:00Z",
        "transaction_type": "debit"
      }
    ]
  }'
```

### Example 2: Ingest Applications
```bash
curl -X POST https://ingestion-api-prod-xyz.run.app/applications \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "loan-platform",
    "applications": [
      {
        "application_id": "app_001",
        "customer_id": "cust_001",
        "loan_amount": 50000.00,
        "loan_purpose": "personal",
        "loan_term_months": 60,
        "applied_at": "2025-09-29T12:00:00Z"
      }
    ]
  }'
```

### Example 3: Health Check
```bash
curl https://ingestion-api-prod-xyz.run.app/health
```

## 🎯 Next Implementation Steps

### Phase 1: Foundation Complete ✅
- [x] FastAPI ingestion API
- [x] Pydantic models
- [x] Authentication
- [x] GCS storage
- [x] Pub/Sub emission
- [x] Tests & CI/CD

### Phase 2: Data Pipeline (Next)
- [ ] Dataflow job (Landing → Bronze)
- [ ] Fingerprint calculation
- [ ] Deduplication logic
- [ ] BigQuery Bronze tables
- [ ] Monitoring & alerting

### Phase 3: dbt Transformations
- [ ] Bronze → Silver models
- [ ] Data enrichment
- [ ] Silver → Gold features
- [ ] dbt tests
- [ ] Documentation

### Phase 4: Feature Store
- [ ] Vertex AI Feature Store setup
- [ ] Feature definitions
- [ ] Offline/online serving
- [ ] Feature monitoring

### Phase 5: AI Agents
- [ ] Transaction classification
- [ ] Credit scoring
- [ ] Fraud detection
- [ ] Decision engine

### Phase 6: HITL Dashboard
- [ ] Streamlit/Next.js frontend
- [ ] Review workflow
- [ ] Override logic
- [ ] Audit logging

## 🔗 Useful Links

### Documentation
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Pydantic Docs](https://docs.pydantic.dev/)
- [Cloud Run Docs](https://cloud.google.com/run/docs)
- [GCS Docs](https://cloud.google.com/storage/docs)
- [Pub/Sub Docs](https://cloud.google.com/pubsub/docs)

### Tools
- [API Testing](http://localhost:8080/docs) - Swagger UI
- [Cloud Console](https://console.cloud.google.com)
- [Artifact Registry](https://console.cloud.google.com/artifacts)
- [Cloud Logging](https://console.cloud.google.com/logs)

## 💡 Best Practices

### Code Quality
- ✅ Use type hints everywhere
- ✅ Write docstrings for functions
- ✅ Keep functions under 50 lines
- ✅ Follow PEP 8 style guide
- ✅ Use meaningful variable names

### Testing
- ✅ Write tests before code (TDD)
- ✅ Mock external dependencies
- ✅ Test edge cases
- ✅ Maintain >80% coverage
- ✅ Run tests before committing

### Security
- ✅ Never commit secrets
- ✅ Use Secret Manager
- ✅ Validate all inputs
- ✅ Use least-privilege IAM
- ✅ Enable audit logging

### Performance
- ✅ Use async/await
- ✅ Pool connections
- ✅ Implement caching
- ✅ Monitor metrics
- ✅ Optimize slow queries

## 📞 Support & Contact

### Getting Help
1. Check this documentation
2. Review API docs at `/docs`
3. Check Cloud Logging for errors
4. Review test cases for examples
5. Contact platform team

### Contributing
1. Fork repository
2. Create feature branch
3. Make changes with tests
4. Submit pull request
5. Wait for review

---

**Last Updated**: 2025-09-29  
**Version**: 1.0.0  
**Maintained By**: AI Risk Platform Team