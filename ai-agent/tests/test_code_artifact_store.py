"""
Tests for ai-agent/src/code_artifact_store.py
"""
from __future__ import annotations

import hashlib
import importlib
import os
import pytest
import pytest_asyncio

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.code_artifact_store import (
    store_artifact,
    get_artifacts_for_turn,
    get_artifacts_for_session,
)
import src.code_artifact_store as code_artifact_store_module


@pytest.mark.asyncio
async def test_store_and_retrieve_sql_artifact(tmp_path):
    db_url = str(tmp_path / "test.db")
    sql = "SELECT id, score FROM decisions WHERE tenant_id = 'abc'"
    artifact = await store_artifact(
        db_url=db_url,
        session_id="sess-1",
        turn_id="turn-1",
        artifact_type="sql",
        content=sql,
    )
    # content_hash must be SHA-256 of content
    expected_hash = hashlib.sha256(sql.encode()).hexdigest()
    assert artifact.content_hash == expected_hash

    # artifact_id must be a UUID4 string
    import uuid
    parsed = uuid.UUID(artifact.artifact_id, version=4)
    assert str(parsed) == artifact.artifact_id

    # Retrieval by turn
    results = await get_artifacts_for_turn(db_url, "turn-1")
    assert len(results) == 1
    assert results[0].artifact_id == artifact.artifact_id


@pytest.mark.asyncio
async def test_store_python_artifact(tmp_path):
    db_url = str(tmp_path / "test.db")
    artifact = await store_artifact(
        db_url=db_url,
        session_id="sess-1",
        turn_id="turn-2",
        artifact_type="python",
        content="df = pd.read_sql('SELECT 1', conn)",
    )
    assert artifact.artifact_type == "python"


@pytest.mark.asyncio
async def test_invalid_artifact_type_raises(tmp_path):
    db_url = str(tmp_path / "test.db")
    with pytest.raises(ValueError):
        await store_artifact(
            db_url=db_url,
            session_id="sess-1",
            turn_id="turn-3",
            artifact_type="bash",  # type: ignore[arg-type]
            content="echo hello",
        )


@pytest.mark.asyncio
async def test_get_artifacts_for_session_date_filter(tmp_path):
    db_url = str(tmp_path / "test.db")

    # Store first artifact with an early created_at by monkeypatching datetime
    from datetime import timezone
    import src.code_artifact_store as cas

    # Store artifact 1 (session-level, turn A)
    art1 = await store_artifact(
        db_url=db_url,
        session_id="sess-filter",
        turn_id="turn-A",
        artifact_type="sql",
        content="SELECT 1",
    )
    # Store artifact 2 (session-level, turn B) - will have a later created_at
    art2 = await store_artifact(
        db_url=db_url,
        session_id="sess-filter",
        turn_id="turn-B",
        artifact_type="sql",
        content="SELECT 2",
    )

    # Filter from art2's created_at
    results = await get_artifacts_for_session(
        db_url, "sess-filter", from_date=art2.created_at
    )
    assert any(r.artifact_id == art2.artifact_id for r in results)


@pytest.mark.asyncio
async def test_source_table_extraction(tmp_path):
    db_url = str(tmp_path / "test.db")
    artifact = await store_artifact(
        db_url=db_url,
        session_id="sess-1",
        turn_id="turn-table",
        artifact_type="sql",
        content="SELECT * FROM audit_log WHERE tenant_id = ?",
    )
    assert artifact.source_table == "audit_log"


def test_no_delete_method():
    assert not hasattr(code_artifact_store_module, "delete_artifact"), \
        "delete_artifact should not exist"
    assert not hasattr(code_artifact_store_module, "update_artifact"), \
        "update_artifact should not exist"
