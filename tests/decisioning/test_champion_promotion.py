"""Unit tests for ChampionChallengerRouter.promote_champion() — GAP-09 acceptance
criteria."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from decisioning.champion_challenger import (
    CCDecisionStore,
    ChampionChallengerRouter,
    ModelConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(db_url: str = "sqlite+pysqlite:///:memory:") -> ChampionChallengerRouter:
    store = CCDecisionStore(db_url=db_url)
    champ = ModelConfig(
        role="CHAMPION",
        model_registry_name="cc_pd",
        model_version="v1",
        traffic_pct=1.0,
    )
    chall = ModelConfig(
        role="CHALLENGER",
        model_registry_name="cc_pd",
        model_version="v2",
        traffic_pct=0.1,
    )
    return ChampionChallengerRouter(champion=champ, challenger=chall, store=store)


# ---------------------------------------------------------------------------
# Test 1: promote_champion completes without raising when mlflow is absent
# ---------------------------------------------------------------------------

def test_promote_champion_no_mlflow() -> None:
    """promote_champion must complete without raising even if mlflow is absent."""
    router = _make_router()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("sys.modules", {"mlflow": None}):
            record = router.promote_champion(
                new_champion_run_id="mlflow_absent_run",
                docs_output_dir=tmpdir,
            )

    assert isinstance(record, dict)
    assert record["promoted_run_id"] == "mlflow_absent_run"
    assert record["event"] == "CHAMPION_PROMOTED"


# ---------------------------------------------------------------------------
# Test 2: MDR files are written to docs_output_dir
# ---------------------------------------------------------------------------

def test_promote_champion_writes_mdr_files() -> None:
    """promote_champion must write both .md and .json MDR files."""
    router = _make_router()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("sys.modules", {"mlflow": None}):
            record = router.promote_champion(
                new_champion_run_id="abc12345678",
                docs_output_dir=tmpdir,
            )

        slug = "abc12345"
        md_file   = Path(tmpdir) / f"mdr_{slug}.md"
        json_file = Path(tmpdir) / f"mdr_{slug}.json"

        assert md_file.exists(),   f"Expected MDR markdown at {md_file}"
        assert json_file.exists(), f"Expected MDR JSON at {json_file}"

        # Verify JSON is valid
        mdr_json = json.loads(json_file.read_text(encoding="utf-8"))
        assert "model_name" in mdr_json

    # Record should point to the files
    assert record["mdr_md_path"] is not None
    assert record["mdr_json_path"] is not None


# ---------------------------------------------------------------------------
# Test 3: audit_logger.log_portfolio_action is called when provided
# ---------------------------------------------------------------------------

def test_promote_champion_calls_audit_logger() -> None:
    """promote_champion must call audit_logger.log_portfolio_action with the record."""
    router = _make_router()
    mock_logger = MagicMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("sys.modules", {"mlflow": None}):
            record = router.promote_champion(
                new_champion_run_id="auditrun001",
                docs_output_dir=tmpdir,
                audit_logger=mock_logger,
            )

    mock_logger.log_portfolio_action.assert_called_once()
    call_args = mock_logger.log_portfolio_action.call_args[0][0]
    assert call_args["promoted_run_id"] == "auditrun001"
    assert call_args["event"] == "CHAMPION_PROMOTED"


# ---------------------------------------------------------------------------
# Test 4: generate_mdr() raising still returns a promotion record with error key
# ---------------------------------------------------------------------------

def test_promote_champion_mdr_error_still_returns_record() -> None:
    """If generate_mdr() raises, promote_champion must return a record with
    'mdr_write_error' key rather than propagating the exception."""
    router = _make_router()

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch.dict("sys.modules", {"mlflow": None}),
            patch(
                "compliance.generate_model_doc.generate_mdr",
                side_effect=RuntimeError("MLflow store unavailable"),
            ),
        ):
            record = router.promote_champion(
                new_champion_run_id="failrun001",
                docs_output_dir=tmpdir,
            )

    assert "mdr_write_error" in record
    assert record["promoted_run_id"] == "failrun001"
    # Files should NOT exist since MDR generation failed
    slug = "failrun0"
    assert not (Path(tmpdir) / f"mdr_{slug}.md").exists()


# ---------------------------------------------------------------------------
# Test 5: promoted_at is a UTC ISO-8601 string
# ---------------------------------------------------------------------------

def test_promote_champion_audit_record_keys() -> None:
    """The returned audit record must contain all required keys."""
    router = _make_router()

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("sys.modules", {"mlflow": None}):
            record = router.promote_champion(
                new_champion_run_id="keycheck01",
                docs_output_dir=tmpdir,
            )

    required_keys = {"event", "promoted_run_id", "promoted_at", "mdr_completeness_passed"}
    missing = required_keys - set(record.keys())
    assert not missing, f"Missing keys in promotion record: {missing}"
    assert record["promoted_at"].endswith("Z"), "promoted_at must end with Z (UTC)"
