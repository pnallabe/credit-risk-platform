import pytest
import uuid
import sys
import os
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.main import app
from src.ai_audit_log import log_ai_turn

client = TestClient(app)

@pytest.mark.asyncio
async def test_verify_chain_api(tmp_path, monkeypatch):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_api.db"
    monkeypatch.setattr("src.main.DATABASE_URL", db_url)

    session_id = str(uuid.uuid4())

    # Insert some valid records
    for i in range(3):
        await log_ai_turn(
            db_url=db_url,
            session_id=session_id,
            turn_id=str(uuid.uuid4()),
            persona="data_analyst",
            query_text=f"SELECT {i}",
            answer_text="ok",
            plan_steps=[{"thought": "t", "action": "a", "action_input": "i", "observation": "o"}],
            tools_called=["sql_query_tool"],
            sql_executed=f"SELECT {i}",
            result_hash="abc",
            query_hash="def",
            code_artifact_ids=["art-1"],
            confidence_score=0.9,
            confidence_label="high",
            grounded=True,
        )

    # Call the API
    response = client.get(f"/api/v1/agent/audit/verify-chain?session_id={session_id}")
    assert response.status_code == 200

    data = response.json()
    assert "is_intact" in data
    assert data["is_intact"] is True
    assert data["total_records"] == 3
    assert data["verified_records"] == 3
