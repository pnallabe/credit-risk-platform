import os
import sys
import uuid
import pytest
import jwt

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:////tmp/test_{uuid.uuid4().hex}.db"
os.environ["JWT_SECRET"] = "test-secret"

from fastapi.testclient import TestClient
import src.main
src.main.DATABASE_URL = os.environ["DATABASE_URL"]
from src.main import app, JWT_SECRET, JWT_ALGORITHM
from src.code_artifact_store import store_artifact, _get_engine

client = TestClient(app)

def create_token(tenant_id: str) -> str:
    return jwt.encode({"tenant_id": tenant_id}, JWT_SECRET, algorithm=JWT_ALGORITHM)

@pytest.fixture
async def setup_db():
    from src.main import DATABASE_URL
    from src.code_artifact_store import _ensure_schema
    await _ensure_schema(DATABASE_URL)
    from src.ai_audit_log import _ensure_schema as audit_schema
    await audit_schema(DATABASE_URL)
    yield DATABASE_URL

@pytest.mark.asyncio
async def test_execute_wrong_tenant(setup_db):
    db_url = setup_db
    # Store artifact as tenant1
    art = await store_artifact(db_url, "sess", "turn1", "sql", "SELECT 1", "tenant1")

    # Try to execute as tenant2
    token = create_token("tenant2")
    res = client.post(f"/api/v1/agent/artifacts/{art.artifact_id}/execute", headers={"Authorization": f"Bearer {token}"})
    if res.status_code != 403:
        print(f"FAILED with {res.status_code}: {res.json()}")
    assert res.status_code == 403

@pytest.mark.asyncio
async def test_execute_python_artifact(setup_db):
    db_url = setup_db
    art = await store_artifact(db_url, "sess", "turn2", "python", "print('hello')", "tenant1")

    token = create_token("tenant1")
    res = client.post(f"/api/v1/agent/artifacts/{art.artifact_id}/execute", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422
    assert "Python execution sandbox is out of scope" in res.json()["detail"]

@pytest.mark.asyncio
async def test_execute_prohibited_variable(setup_db):
    db_url = setup_db
    art = await store_artifact(db_url, "sess", "turn3", "sql", "SELECT race FROM my_table", "tenant1")

    token = create_token("tenant1")
    res = client.post(f"/api/v1/agent/artifacts/{art.artifact_id}/execute", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422
    assert "prohibited variables" in res.json()["detail"]

@pytest.mark.asyncio
async def test_execute_sql_success(setup_db):
    db_url = setup_db
    import uuid
    from src.ai_audit_log import log_ai_turn
    turn_id = str(uuid.uuid4())

    # Pre-populate audit log to match
    import json, hashlib
    rows = [{"1": 1}]
    result_hash = hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()

    await log_ai_turn(
        db_url=db_url,
        session_id="sess",
        turn_id=turn_id,
        persona="persona",
        query_text="test",
        answer_text="ans",
        plan_steps=[],
        tools_called=[],
        sql_executed="SELECT 1",
        result_hash=result_hash,
        query_hash="",
        code_artifact_ids=[],
        confidence_score=1.0,
        confidence_label="high",
        grounded=True,
        tenant_id="tenant1"
    )
    art = await store_artifact(db_url, "sess", turn_id, "sql", "SELECT 1", "tenant1")

    token = create_token("tenant1")
    res = client.post(f"/api/v1/agent/artifacts/{art.artifact_id}/execute", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["hashes_match"] is True
    assert data["original_result_hash"] == result_hash
    assert data["reexecution_result_hash"] == result_hash
    assert data["row_count"] == 1
