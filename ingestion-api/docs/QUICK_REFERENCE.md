# Quick Reference Guide - Ingestion API

## 🚀 Setup Commands

```bash
# Initial setup
./setup.sh

# Activate virtual environment
source venv/bin/activate

# Install dependencies
make install

# Setup GCP resources
make setup-gcp
```

## 🧪 Development Commands

```bash
# Run locally
make run                    # Development mode with hot-reload
make run-prod              # Production mode

# Testing
make test                  # Run tests with coverage
make test-fast             # Run tests without coverage
make lint                  # Check code quality
make format                # Auto-format code
make validate              # Run all checks

# Generate test token
make token
```

## 🐳 Docker Commands

```bash
# Build image
make docker-build

# Run container
make docker-run

# Test in Docker
make docker-test
```

## ☁️ Deployment Commands

```bash
# Deploy to environments
make deploy-dev            # Deploy to dev
make deploy-prod           # Deploy to prod

# View logs
make logs-dev              # Tail dev logs
make logs-prod             # Tail prod logs
```

## 📡 API Testing

```bash
# Health check
curl http://localhost:8080/health

# Generate token
export TOKEN=$(make token)

# Test transaction ingestion
curl -X POST http://localhost:8080/transactions \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @example_payloads.json

# Test application ingestion
curl -X POST http://localhost:8080/applications \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d @example_payloads.json
```

## 🔍 Debugging Commands

```bash
# View local logs
tail -f logs/app.log

# View Cloud Run logs
gcloud logging tail "resource.type=cloud_run_revision" --limit 50

# Check service status
gcloud run services describe ingestion-api-dev --region us-central1

# Test GCS access
gsutil ls gs://risk-raw-data-dev/

# Test Pub/Sub
gcloud pubsub topics list
```

## 🔐 Authentication

```bash
# Create JWT token (Python)
python -c "from auth import create_access_token; print(create_access_token('user@example.com', 3600))"

# Decode JWT token
python -c "import jwt; print(jwt.decode('YOUR_TOKEN', options={'verify_signature': False}))"
```

## 📊 Monitoring

```bash
# Check service metrics
gcloud monitoring dashboards list

# View error logs
gcloud logging read "severity>=ERROR" --limit 20

# Check instance count
gcloud run services describe ingestion-api-prod \
  --format="value(status.traffic[0].latestRevision)"
```

## 🛠️ Troubleshooting

```bash
# Restart service
gcloud run services update ingestion-api-dev --region us-central1

# Check service account permissions
gcloud projects get-iam-policy ${GCP_PROJECT_ID} \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:ingestion-api@*"

# Verify secrets
gcloud secrets versions access latest --secret="jwt-secret"

# Test connectivity to GCS
gsutil ls gs://risk-raw-data-dev/ || echo "No access"
```

## 📝 Git Workflow

```bash
# Create feature branch
git checkout -b feature/new-feature

# Make changes and test
make validate

# Commit changes
git add .
git commit -m "feat: add new feature"

# Push and create PR
git push origin feature/new-feature

# Merge to dev (auto-deploys)
git checkout dev
git merge feature/new-feature
git push origin dev
```

## 🔄 Common Workflows

### Add New Field to Transaction
1. Update `models.py` - Add field to `Transaction` class
2. Add validation logic if needed
3. Update tests in `test_main.py`
4. Update `example_payloads.json`
5. Run `make validate`
6. Deploy

### Update Authentication
1. Edit `auth.py`
2. Update tests
3. Update environment variables
4. Redeploy service
5. Update clients with new tokens

### Scale Service
```bash
# Increase max instances
gcloud run services update ingestion-api-prod \
  --max-instances=20

# Set min instances (prevent cold starts)
gcloud run services update ingestion-api-prod \
  --min-instances=2

# Increase memory/CPU
gcloud run services update ingestion-api-prod \
  --memory=2Gi --cpu=4
```

## 📚 Useful Queries

### BigQuery (after pipeline setup)
```sql
-- Count transactions by source
SELECT source, COUNT(*) as count
FROM `bronze.transactions`
WHERE DATE(posted_at) = CURRENT_DATE()
GROUP BY source;

-- Find duplicates
SELECT fingerprint, COUNT(*) as count
FROM `bronze.transactions`
GROUP BY fingerprint
HAVING count > 1;
```

### Cloud Logging
```bash
# Errors in last hour
gcloud logging read "timestamp>=\"$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%S')\" AND severity>=ERROR"

# Slow requests (>1s)
gcloud logging read "jsonPayload.latency_ms>1000"

# Failed GCS writes
gcloud logging read "jsonPayload.message:\"GCS write failed\""
```

## 🎯 Performance Tuning

```bash
# Load test with Apache Bench
ab -n 1000 -c 10 -H "Authorization: Bearer ${TOKEN}" \
  -p payload.json -T "application/json" \
  http://localhost:8080/transactions

# Monitor during load test
watch -n 1 'curl -s http://localhost:8080/health | jq'

# Profile application
python -m cProfile -o profile.stats main.py
python -m pstats profile.stats
```

## 📞 Emergency Procedures

### Service Down
```bash
# 1. Check status
gcloud run services describe ingestion-api-prod

# 2. View recent logs
make logs-prod

# 3. Rollback to previous version
gcloud run services update-traffic ingestion-api-prod \
  --to-revisions=PREVIOUS_REVISION=100

# 4. Notify team
echo "Service restored to previous version" | mail -s "Alert: Rollback" team@example.com
```

### High Error Rate
```bash
# 1. Identify errors
gcloud logging read "severity=ERROR" --limit 100

# 2. Check external dependencies
gsutil ls gs://risk-raw-data-prod/  # GCS check
gcloud pubsub topics list            # Pub/Sub check

# 3. Scale down if needed
gcloud run services update ingestion-api-prod --max-instances=5
```

---

**Pro Tip**: Add these aliases to your `.bashrc` or `.zshrc`:
```bash
alias api-dev='gcloud run services describe ingestion-api-dev'
alias api-logs='gcloud logging tail "resource.type=cloud_run_revision"'
alias api-deploy='make deploy-dev'
```