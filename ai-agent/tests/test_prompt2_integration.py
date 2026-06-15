import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from src.main import app, _CONFIG_REGISTRY
from config_registry.service import migrate_config_schema

migrate_config_schema(_CONFIG_REGISTRY._db_url)


client = TestClient(app)

def test_config_endpoint_default():
    response = client.get("/api/v1/agent/config?tenant_id=unknown_tenant")
    assert response.status_code == 200
    data = response.json()
    assert data["refusal_threshold"] == 0.10
    assert data["source"] == "default"

def test_config_endpoint_override():
    # Setup the registry
    _CONFIG_REGISTRY.ensure_tenant("test_tenant_xyz", name="Test Tenant XYZ")
    try:
        _CONFIG_REGISTRY.publish(
            tenant_id="test_tenant_xyz",
            config_json={"ai_agent.refusal_threshold": 0.16},
            approved_by="tester",
            note="testing threshold override"
        )
    except ValueError:
        pass

    response = client.get("/api/v1/agent/config?tenant_id=test_tenant_xyz")
    assert response.status_code == 200
    data = response.json()
    assert data["refusal_threshold"] == 0.16
    assert data["source"] == "tenant_override"

# The test below is an integration test simulating a query that returns score=0.35 but threshold=0.40
# To fully test the query endpoint, it's best to mock compute_confidence to return 0.35
