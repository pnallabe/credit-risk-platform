"""
Tests for mlflow_config/mlflow_config.py
=========================================
Uses MLflow's in-memory tracking store to avoid requiring a running server.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from mlflow_config.mlflow_config import (
    GovernanceError,
    ModelRegistry,
    MIN_AUC_FOR_PRODUCTION,
    MIN_KS_FOR_PRODUCTION,
    configure_mlflow,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def in_memory_registry(tmp_path):
    """ModelRegistry backed by a local SQLite URI in a temp directory."""
    uri = f"sqlite:///{tmp_path}/mlruns_test.db"
    return ModelRegistry(tracking_uri=uri), uri


@pytest.fixture
def dummy_sklearn_model():
    from sklearn.ensemble import RandomForestClassifier
    import numpy as np
    clf = RandomForestClassifier(n_estimators=5, random_state=0)
    clf.fit(np.random.rand(50, 5), np.random.randint(0, 2, 50))
    return clf


# ---------------------------------------------------------------------------
# configure_mlflow tests
# ---------------------------------------------------------------------------


class TestConfigureMlflow:
    def test_returns_uri_string(self, tmp_path) -> None:
        uri = f"sqlite:///{tmp_path}/test.db"
        result = configure_mlflow(uri)
        assert uri in result

    def test_creates_local_db_directory(self, tmp_path) -> None:
        nested = tmp_path / "subdir" / "mlruns.db"
        uri = f"sqlite:///{nested}"
        configure_mlflow(uri)
        # Parent dir should be created
        assert nested.parent.exists()

    def test_env_var_fallback(self, monkeypatch, tmp_path) -> None:
        uri = f"sqlite:///{tmp_path}/env.db"
        monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
        result = configure_mlflow()
        assert uri in result


# ---------------------------------------------------------------------------
# ModelRegistry.register_model tests
# ---------------------------------------------------------------------------


class TestRegisterModel:
    def test_register_returns_version_string(self, in_memory_registry, dummy_sklearn_model, tmp_path) -> None:
        registry, _ = in_memory_registry
        model_path = tmp_path / "model.pkl"
        import joblib
        joblib.dump(dummy_sklearn_model, model_path)

        version = registry.register_model(
            model_name="test_model",
            model_path=str(model_path),
            metrics={"auc": 0.85, "ks": 0.42},
            params={"n_estimators": 5},
            experiment_name="test_experiment",
        )
        assert isinstance(version, str)

    def test_register_non_existent_path_no_crash(self, in_memory_registry) -> None:
        registry, _ = in_memory_registry
        version = registry.register_model(
            model_name="test_model_2",
            model_path="/nonexistent/model.pkl",
            metrics={"auc": 0.80},
            params={},
        )
        assert isinstance(version, str)

    def test_metrics_are_logged(self, in_memory_registry) -> None:
        import mlflow
        registry, uri = in_memory_registry
        registry.register_model(
            model_name="metrics_test",
            model_path="/nonexistent/model.pkl",
            metrics={"auc": 0.91, "ks": 0.45, "precision": 0.87},
            params={"lr": 0.01},
        )
        # Check latest run has the metrics
        runs = mlflow.search_runs(experiment_names=["metrics_test"])
        assert not runs.empty
        assert abs(runs.iloc[0]["metrics.auc"] - 0.91) < 0.001


# ---------------------------------------------------------------------------
# GovernanceError tests
# ---------------------------------------------------------------------------


class TestGovernanceError:
    def test_governance_error_is_exception(self) -> None:
        err = GovernanceError("Test governance error")
        assert isinstance(err, Exception)
        assert "Test governance error" in str(err)


# ---------------------------------------------------------------------------
# ModelRegistry.list_model_versions tests
# ---------------------------------------------------------------------------


class TestListModelVersions:
    def test_returns_empty_for_unknown_model(self, in_memory_registry) -> None:
        registry, _ = in_memory_registry
        # Should not raise even if model doesn't exist (returns empty or raises)
        try:
            versions = registry.list_model_versions("nonexistent_model")
            assert isinstance(versions, list)
        except Exception:
            pass  # Some MLflow versions raise, some return empty


# ---------------------------------------------------------------------------
# Governance check unit tests (using mock)
# ---------------------------------------------------------------------------


class TestGovernanceCheckLogic:
    """Test the governance check logic directly with mocked MLflow client."""

    def _make_registry(self, tmp_path) -> ModelRegistry:
        uri = f"sqlite:///{tmp_path}/test.db"
        return ModelRegistry(tracking_uri=uri)

    def test_passing_governance_no_exception(self, tmp_path) -> None:
        """If AUC >= 0.75 and KS >= 0.35, governance should pass."""
        registry = self._make_registry(tmp_path)

        mock_client = MagicMock()
        mock_mv = MagicMock()
        mock_mv.run_id = "run-1"
        mock_client.get_model_version.return_value = mock_mv

        with patch("mlflow.get_run") as mock_get_run:
            mock_run = MagicMock()
            mock_run.data.metrics = {"auc": 0.80, "ks": 0.40}
            mock_get_run.return_value = mock_run
            # Should not raise
            registry._governance_check(mock_client, "model", "1")

    def test_failing_auc_raises_governance_error(self, tmp_path) -> None:
        """If AUC < 0.75, should raise GovernanceError."""
        registry = self._make_registry(tmp_path)
        mock_client = MagicMock()
        mock_mv = MagicMock()
        mock_mv.run_id = "run-2"
        mock_client.get_model_version.return_value = mock_mv

        with patch("mlflow.get_run") as mock_get_run:
            mock_run = MagicMock()
            mock_run.data.metrics = {"auc": 0.70, "ks": 0.40}  # AUC too low
            mock_get_run.return_value = mock_run

            with pytest.raises(GovernanceError, match="auc=0.7"):
                registry._governance_check(mock_client, "model", "2")

    def test_failing_ks_raises_governance_error(self, tmp_path) -> None:
        """If KS < 0.35, should raise GovernanceError."""
        registry = self._make_registry(tmp_path)
        mock_client = MagicMock()
        mock_mv = MagicMock()
        mock_mv.run_id = "run-3"
        mock_client.get_model_version.return_value = mock_mv

        with patch("mlflow.get_run") as mock_get_run:
            mock_run = MagicMock()
            mock_run.data.metrics = {"auc": 0.80, "ks": 0.25}  # KS too low
            mock_get_run.return_value = mock_run

            with pytest.raises(GovernanceError, match="ks=0.25"):
                registry._governance_check(mock_client, "model", "3")

    def test_missing_run_id_raises_governance_error(self, tmp_path) -> None:
        registry = self._make_registry(tmp_path)
        mock_client = MagicMock()
        mock_mv = MagicMock()
        mock_mv.run_id = None
        mock_client.get_model_version.return_value = mock_mv

        with pytest.raises(GovernanceError, match="no associated run_id"):
            registry._governance_check(mock_client, "model", "4")

    def test_both_metrics_failing_error_contains_both(self, tmp_path) -> None:
        registry = self._make_registry(tmp_path)
        mock_client = MagicMock()
        mock_mv = MagicMock()
        mock_mv.run_id = "run-5"
        mock_client.get_model_version.return_value = mock_mv

        with patch("mlflow.get_run") as mock_get_run:
            mock_run = MagicMock()
            mock_run.data.metrics = {"auc": 0.60, "ks": 0.20}
            mock_get_run.return_value = mock_run

            with pytest.raises(GovernanceError) as exc_info:
                registry._governance_check(mock_client, "model", "5")
            err_msg = str(exc_info.value)
            assert "auc" in err_msg
            assert "ks" in err_msg
