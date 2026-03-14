"""
MLflow Experiment Tracking Configuration
=========================================
Configures MLflow for local SQLite (dev) or remote URI (production),
and provides a ModelRegistry class for model governance.

Governance check
----------------
Promotion from Staging → Production requires:
  ``auc >= 0.75`` AND ``ks >= 0.35``
Any violation raises ``GovernanceError``.

Public API
----------
>>> from mlflow_config.mlflow_config import ModelRegistry, configure_mlflow
>>> configure_mlflow()
>>> registry = ModelRegistry()
>>> version = registry.register_model("credit_risk", "models/credit_risk/risk_model_v1.pkl", metrics, params)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LOCAL_SQLITE_URI = "sqlite:///./mlflow/mlruns.db"

# Governance thresholds for production promotion
MIN_AUC_FOR_PRODUCTION = 0.75
MIN_KS_FOR_PRODUCTION = 0.35


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GovernanceError(Exception):
    """Raised when a model fails the governance check for Production promotion."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def configure_mlflow(tracking_uri: Optional[str] = None) -> str:
    """Configure MLflow tracking URI.

    Parameters
    ----------
    tracking_uri:
        Override tracking URI.  If *None*, reads ``MLFLOW_TRACKING_URI``
        env var.  Falls back to the local SQLite backend.

    Returns
    -------
    str — the active tracking URI.
    """
    try:
        import mlflow
    except ImportError as exc:
        raise ImportError("mlflow is required: pip install mlflow") from exc

    uri = tracking_uri or os.getenv("MLFLOW_TRACKING_URI", LOCAL_SQLITE_URI)

    # Create local SQLite directory if needed
    if uri.startswith("sqlite:///"):
        db_path = uri.replace("sqlite:///", "")
        if db_path and not db_path.startswith(":"):
            import pathlib
            pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    mlflow.set_tracking_uri(uri)
    logger.info("MLflow tracking URI set to: %s", uri)
    return uri


# ---------------------------------------------------------------------------
# ModelRegistry
# ---------------------------------------------------------------------------


class ModelRegistry:
    """High-level wrapper around MLflow Model Registry with governance checks.

    Parameters
    ----------
    tracking_uri:
        MLflow tracking URI (defaults to ``MLFLOW_TRACKING_URI`` env var
        or local SQLite).
    """

    def __init__(self, tracking_uri: Optional[str] = None) -> None:
        self._uri = configure_mlflow(tracking_uri)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_model(
        self,
        model_name: str,
        model_path: str,
        metrics: Dict[str, float],
        params: Dict[str, Any],
        experiment_name: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
    ) -> str:
        """Log a model run and register it in the MLflow Model Registry.

        Parameters
        ----------
        model_name:
            Name to use in the model registry.
        model_path:
            Path to a joblib-serialised model file OR an MLflow artifact URI.
        metrics:
            Dict of metric name → value (e.g., ``{"auc": 0.82, "ks": 0.40}``).
        params:
            Dict of hyperparameter name → value.
        experiment_name:
            MLflow experiment to log to.  Defaults to *model_name*.
        tags:
            Optional MLflow tags.

        Returns
        -------
        str — The registered model version string.
        """
        import mlflow
        import mlflow.sklearn

        exp_name = experiment_name or model_name
        mlflow.set_experiment(exp_name)

        with mlflow.start_run(tags=tags or {}):
            # Log params and metrics
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)

            # Log the model artifact
            import pathlib
            path = pathlib.Path(model_path)
            if path.exists():
                try:
                    import joblib
                    model_obj = joblib.load(path)
                    mlflow.sklearn.log_model(model_obj, artifact_path="model")
                except Exception as exc:
                    logger.warning("Could not log model artifact: %s", exc)
                    mlflow.log_artifact(str(path))
            else:
                logger.warning("Model file not found, skipping artifact logging: %s", path)

            run_id = mlflow.active_run().info.run_id

        # Register the model
        try:
            model_uri = f"runs:/{run_id}/model"
            result = mlflow.register_model(model_uri, model_name)
            version = result.version
        except Exception as exc:
            logger.warning("Model registration failed (registry may not be available): %s", exc)
            version = "unregistered"

        logger.info("Registered model '%s' version=%s", model_name, version)
        return str(version)

    # ------------------------------------------------------------------
    # Promotion
    # ------------------------------------------------------------------

    def promote_model(
        self,
        model_name: str,
        version: str,
        stage: str,
    ) -> None:
        """Transition a model version to a new stage.

        Promotion to ``Production`` requires governance checks:
          - ``auc >= 0.75`` AND ``ks >= 0.35``

        Parameters
        ----------
        model_name:
            Registered model name.
        version:
            Model version string.
        stage:
            Target stage: ``"Staging"`` | ``"Production"`` | ``"Archived"``.

        Raises
        ------
        GovernanceError
            If promoting to Production and metrics fail governance.
        """
        import mlflow
        from mlflow.tracking import MlflowClient

        client = MlflowClient()

        if stage.lower() == "production":
            self._governance_check(client, model_name, version)

        client.transition_model_version_stage(
            name=model_name,
            version=version,
            stage=stage,
            archive_existing_versions=True,
        )
        logger.info("Promoted model '%s' v%s → %s", model_name, version, stage)

    def _governance_check(
        self, client: Any, model_name: str, version: str
    ) -> None:
        """Verify AUC and KS metrics before Production promotion."""
        mv = client.get_model_version(model_name, version)
        run_id = mv.run_id

        if not run_id:
            raise GovernanceError(
                f"Model '{model_name}' v{version} has no associated run_id; "
                "cannot verify governance metrics."
            )

        import mlflow

        run = mlflow.get_run(run_id)
        metrics = run.data.metrics

        auc = metrics.get("auc", None)
        ks = metrics.get("ks", None)

        errors = []
        if auc is None:
            errors.append("'auc' metric not found in run")
        elif auc < MIN_AUC_FOR_PRODUCTION:
            errors.append(f"auc={auc:.4f} < required {MIN_AUC_FOR_PRODUCTION}")

        if ks is None:
            errors.append("'ks' metric not found in run")
        elif ks < MIN_KS_FOR_PRODUCTION:
            errors.append(f"ks={ks:.4f} < required {MIN_KS_FOR_PRODUCTION}")

        if errors:
            raise GovernanceError(
                f"Model '{model_name}' v{version} failed production governance check: "
                + "; ".join(errors)
            )

        logger.info(
            "Governance check PASSED for '%s' v%s: auc=%.4f, ks=%.4f",
            model_name, version, auc, ks,
        )

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_production_model(
        self, model_name: str
    ) -> Tuple[Any, Dict[str, Any]]:
        """Load the current Production model.

        Returns
        -------
        (model_object, metadata_dict)
        """
        import mlflow
        import mlflow.sklearn
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        versions = client.get_latest_versions(model_name, stages=["Production"])
        if not versions:
            raise ValueError(f"No Production version found for model '{model_name}'")

        mv = versions[0]
        model_uri = f"models:/{model_name}/Production"
        model = mlflow.sklearn.load_model(model_uri)

        metadata = {
            "model_name": model_name,
            "version": mv.version,
            "stage": mv.current_stage,
            "run_id": mv.run_id,
            "creation_timestamp": mv.creation_timestamp,
        }
        return model, metadata

    def list_model_versions(self, model_name: str) -> List[Dict[str, Any]]:
        """List all registered versions for a model.

        Returns
        -------
        List of dicts with version metadata.
        """
        from mlflow.tracking import MlflowClient

        client = MlflowClient()
        versions = client.search_model_versions(f"name='{model_name}'")
        return [
            {
                "version": mv.version,
                "stage": mv.current_stage,
                "run_id": mv.run_id,
                "status": mv.status,
                "creation_timestamp": mv.creation_timestamp,
            }
            for mv in versions
        ]
