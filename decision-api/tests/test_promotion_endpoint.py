"""Integration tests for POST /v1/models/{run_id}/promote — GAP-09 acceptance
criteria."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

# JWT_SECRET must be set before importing main
os.environ.setdefault("JWT_SECRET", "test-secret-pytest")  # nosec B105

import jwt as _jwt  # noqa: E402


def _make_token(tenant_id: str = "tenant-x", role: str = "admin") -> str:
    return _jwt.encode(
        {"sub": "user", "tenant_id": tenant_id, "role": role},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


ADMIN_HEADERS = {"Authorization": f"Bearer {_make_token(role='admin')}"}
MRO_HEADERS   = {"Authorization": f"Bearer {_make_token(role='model_risk_officer')}"}
USER_HEADERS  = {"Authorization": f"Bearer {_make_token(role='analyst')}"}


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient with mock models loaded."""
    from unittest.mock import MagicMock
    import numpy as np
    import src.main as api_module
    from fastapi.testclient import TestClient

    mock_model = MagicMock()
    mock_model.predict_proba = MagicMock(return_value=np.array([[0.95, 0.05]]))
    mock_model.predict = MagicMock(return_value=np.array([0]))
    api_module._fraud_model = mock_model
    api_module._risk_model  = mock_model

    from src.main import app
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test 1: admin token → 200, promotion record returned
# ---------------------------------------------------------------------------

def test_promote_model_admin_returns_200(client, tmp_path) -> None:
    """POST /v1/models/{run_id}/promote with admin role must return 200."""
    with patch.dict("sys.modules", {"mlflow": None}):
        resp = client.post(
            "/v1/models/abc123runxyz/promote",
            json={"docs_output_dir": str(tmp_path)},
            headers=ADMIN_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "promoted"
    assert data["promotion_record"]["promoted_run_id"] == "abc123runxyz"


# ---------------------------------------------------------------------------
# Test 2: model_risk_officer role → 200
# ---------------------------------------------------------------------------

def test_promote_model_mro_returns_200(client, tmp_path) -> None:
    with patch.dict("sys.modules", {"mlflow": None}):
        resp = client.post(
            "/v1/models/mro_runid123/promote",
            json={"docs_output_dir": str(tmp_path)},
            headers=MRO_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["promotion_record"]["promoted_run_id"] == "mro_runid123"


# ---------------------------------------------------------------------------
# Test 3: non-admin/non-mro role → 403
# ---------------------------------------------------------------------------

def test_promote_model_non_admin_returns_403(client) -> None:
    resp = client.post(
        "/v1/models/somerun123/promote",
        json={},
        headers=USER_HEADERS,
    )
    assert resp.status_code == 403
    assert "role" in resp.json().get("error", "").lower() or "insufficient" in resp.json().get("error", "").lower()


# ---------------------------------------------------------------------------
# Test 4: MDR file is written under docs_output_dir
# ---------------------------------------------------------------------------

def test_promote_model_writes_mdr_file(client, tmp_path) -> None:
    with patch.dict("sys.modules", {"mlflow": None}):
        resp = client.post(
            "/v1/models/filecheck01/promote",
            json={"docs_output_dir": str(tmp_path)},
            headers=ADMIN_HEADERS,
        )

    assert resp.status_code == 200, resp.text
    # At least a .md file should be present
    md_files = list(tmp_path.glob("*.md"))
    assert md_files, f"No MDR markdown written under {tmp_path}"
