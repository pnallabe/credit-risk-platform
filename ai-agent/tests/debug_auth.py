import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/test.db"
os.environ["JWT_SECRET"] = "test-secret"  # pragma: allowlist secret

from src.main import app, JWT_SECRET, JWT_ALGORITHM, store_artifact, _get_engine
from fastapi.testclient import TestClient
import jwt
import asyncio

print(f"JWT_SECRET: {JWT_SECRET}")

token = jwt.encode({"tenant_id": "tenant1"}, JWT_SECRET, algorithm=JWT_ALGORITHM)
print(f"Token: {token}")

client = TestClient(app)

async def test_auth():
    from src.code_artifact_store import _ensure_schema
    await _ensure_schema("sqlite+aiosqlite:///:memory:")
    art = await store_artifact("sqlite+aiosqlite:///:memory:", "sess", "turn1", "sql", "SELECT 1", "tenant1")

    res = client.post(f"/api/v1/agent/artifacts/{art.artifact_id}/execute", headers={"Authorization": f"Bearer {token}"})
    print(res.status_code)
    print(res.json())

asyncio.run(test_auth())
