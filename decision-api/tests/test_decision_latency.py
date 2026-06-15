import time
import json
import pytest
import os
import jwt
from fastapi.testclient import TestClient

os.environ["JWT_SECRET"] = "test-secret-key-12345"
from src.main import app

client = TestClient(app)

def test_decision_latency():
    """Loose sanity check for decision latency. The real benchmark uses k6."""
    with open("data/sample_applicant.json") as f:
        payload = json.load(f)

    # Generate a valid JWT token
    token = jwt.encode({"tenant_id": "test-tenant"}, "test-secret-key-12345", algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}

    latencies = []
    for _ in range(10):
        start = time.perf_counter()
        response = client.post("/v1/decisions", json=payload, headers=headers)
        end = time.perf_counter()

        # We only care that it successfully completed
        if response.status_code != 200:
            print(response.json())
        assert response.status_code == 200
        latencies.append(end - start)

    mean_latency = sum(latencies) / len(latencies)

    # Very loose sanity check, since this runs sequentially and in a test environment
    # where model loading etc. might be cached or take long the first time.
    assert mean_latency < 2.0, f"Mean latency {mean_latency} is too high (>2s)"
