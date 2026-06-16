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
# Section 21 — Unified Model Registry (all registered models)
# ---------------------------------------------------------------------------

CC_PD_MODEL_NAME            = "cc_pd_model"
MORTGAGE_VALUATION_MODEL_NAME = "mortgage_valuation_model"

# All registered models covered by MRM governance
ALL_CC_MODELS: List[str] = [
    CC_PD_MODEL_NAME,
    "cc_origination_valuation",
    "cc_portfolio_action",
]

ALL_REGISTERED_MODELS: List[str] = ALL_CC_MODELS + [MORTGAGE_VALUATION_MODEL_NAME]

# ── SR 11-7 lifecycle stages ─────────────────────────────────────────────────
SR117_STAGES: List[str] = [
    "development",
    "independent_validation",
    "mrm_approval",
    "production",
    "sunset",
]

# ── Unified governance thresholds (model_name → thresholds dict) ─────────────
MODEL_GOVERNANCE: Dict[str, Dict] = {
    CC_PD_MODEL_NAME: {
        "min_auc":               0.75,
        "min_ks":                0.35,
        "max_brier_score":       0.10,
        "max_psi_score":         0.20,
        "fair_lending_required": True,
        "review_cycle_months":   12,
        "model_owner_email":     "ds-team@example.com",
    },
    "cc_origination_valuation": {
        "min_cnpv_realised_ratio":  0.70,
        "max_ftp_psi":             0.15,
        "min_monotone_pct":        0.99,
        "fair_lending_required":   True,
        "review_cycle_months":     12,
        "model_owner_email":       "ds-team@example.com",
    },
    "cc_portfolio_action": {
        "min_cli_precision":      0.72,
        "min_cld_recall":         0.80,
        "min_macro_auc":          0.82,
        "max_feature_psi":        0.20,
        "min_guardrail_coverage": 1.00,
        "fair_lending_required":  True,
        "review_cycle_months":    6,
        "model_owner_email":      "ds-team@example.com",
    },
    # ── Mortgage Valuation Model ─────────────────────────────────────────────
    MORTGAGE_VALUATION_MODEL_NAME: {
        # Loan-level logistic regression AUC (90-day DPD)
        "min_lr_auc":            0.78,
        # Gini coefficient (2 * AUC - 1)
        "min_gini":              0.56,
        # LTV distribution PSI vs training baseline
        "max_ltv_psi":           0.15,
        # HPA scenario monotonicity: recession CNPV < worsening < base
        "min_hpa_monotone_pct":  0.99,
        # CNPV backtesting ratio (realised 12m NPV vs predicted)
        "min_cnpv_realised_ratio": 0.70,
        # Disparate impact ratio ECOA (must satisfy 4/5ths rule)
        "min_di_ratio":          0.80,
        "fair_lending_required": True,
        "review_cycle_months":   12,
        "model_owner_email":     "mortgage-ds@example.com",
    },
}

# ── Champion/Challenger configuration (agent_config.yaml keys) ───────────────
# These keys are read by RiskModelingAgent at runtime.
# Example agent_config.yaml section:
#   cc_valuation:
#     champion_model: cc_origination_valuation/Production
#     challenger_model: cc_origination_valuation/Staging   # optional
#     challenger_traffic_pct: 10
#   cc_portfolio:
#     champion_model: cc_portfolio_action/Production
#     challenger_model: cc_portfolio_action/Staging
#     challenger_traffic_pct: 5
#   mortgage_valuation:
#     champion_model: mortgage_valuation_model/Production
#     challenger_model: mortgage_valuation_model/Staging
#     challenger_traffic_pct: 5

# ---------------------------------------------------------------------------
# Section 19 — CC Originations Valuation governance
# ---------------------------------------------------------------------------

CC_VALUATION_MODEL_NAME = "cc_origination_valuation"

CC_VALUATION_GOVERNANCE: Dict[str, float] = {
    # Backtesting: realised 12-month revenue vs predicted CNPV (ratio)
    "min_cnpv_realised_ratio":    0.70,   # realised/predicted >= 70 %
    # FTP model stability: max allowed PSI on FTP spread distribution
    "max_ftp_psi":                0.15,
    # Scenario monotonicity (recession CNPV < worsening CNPV < base CNPV) hold rate
    "min_monotone_pct":           0.99,   # >= 99 % of applications
    # Approval rate deviation vs challenger (red flag if > 5 pp)
    "max_approval_rate_delta_pp": 5.0,
}

# MLflow experiment tags for every cc_valuation training run
CC_VALUATION_REQUIRED_TAGS: List[str] = [
    "model_type",        # cnpv_valuation
    "scenario_set",      # base,industry_worsening,recession
    "bq_dataset",        # ai-risk-workflow.credit_risk_model_dev
    "ftp_benchmark_rate", # e.g. 5.30
    "capital_cet1_target", # e.g. 12.5
    "sr11_7_stage",      # development → validation → production
    "validator",         # <email>
    "approved_by",       # <email>
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GovernanceError(Exception):
    """Raised when a model fails the governance check for Production promotion."""


class CCValuationGovernanceError(GovernanceError):
    """Raised when cc_origination_valuation fails its production governance check."""


# ---------------------------------------------------------------------------
# Section 20 — CC Portfolio Action governance
# ---------------------------------------------------------------------------

CC_PORTFOLIO_MODEL_NAME = "cc_portfolio_action"

CC_PORTFOLIO_GOVERNANCE: dict = {
    # OOS 2023-2024 (cc_credit_limit_events held out)
    "min_cli_precision":        0.72,
    "min_cld_recall":           0.80,
    "min_macro_auc":            0.82,
    # Feature stability
    "max_feature_psi":          0.20,    # any single feature PSI
    # Guardrail coverage: % of DPD60+ accounts receiving CLD/HOLD
    "min_guardrail_coverage":   1.00,    # must be 100 %
}

# Required MLflow experiment tags for every cc_portfolio_action training run
CC_PORTFOLIO_REQUIRED_TAGS: list = [
    "model_type",          # gbc_action_classifier
    "feature_version",     # portfolio_features_v<n>
    "training_period",     # 2015-01-01_to_2022-12-31
    "oos_period",          # 2023-01-01_to_2024-12-31
    "class_weight",        # balanced
    "sr11_7_stage",        # development → validation → production
    "validator",           # <email>
    "approved_by",         # <email>
    "fair_lending_reviewed",  # true/false
]


class CCPortfolioGovernanceError(GovernanceError):
    """Raised when cc_portfolio_action fails production governance check."""


class MortgageValuationGovernanceError(GovernanceError):
    """Raised when mortgage_valuation_model fails production governance check."""


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
            # Unified governance dispatch — runs model-specific checks then
            # falls back to base AUC/KS for any unrecognised model.
            _run_model_governance(client, model_name, version, base_check_fn=self._governance_check)
        elif stage.lower() == "archived":
            # Tag sunset stage in MLflow for SR 11-7 traceability
            try:
                client.set_model_version_tag(
                    name=model_name, version=version,
                    key="sr11_7_stage", value="sunset",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not set sunset tag on %s v%s: %s", model_name, version, exc)

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

# ---------------------------------------------------------------------------
# Section 19 — CC Originations Valuation governance check (module-level)
# ---------------------------------------------------------------------------


def _cc_valuation_governance_check(client: Any, model_name: str, version: str) -> None:
    """CNPV-specific governance checks before Production promotion.

    Validates:
      - cnpv_realised_ratio >= 0.70
      - ftp_psi <= 0.15
      - monotone_pct >= 0.99

    Raises
    ------
    CCValuationGovernanceError
        If any governance threshold is violated.
    """
    import mlflow

    mv  = client.get_model_version(model_name, version)
    if not mv.run_id:
        raise CCValuationGovernanceError(
            f"{model_name} v{version} has no associated run_id; cannot verify governance."
        )
    run = mlflow.get_run(mv.run_id)
    m   = run.data.metrics
    errors: list[str] = []

    ratio = m.get("cnpv_realised_ratio")
    if ratio is None or ratio < CC_VALUATION_GOVERNANCE["min_cnpv_realised_ratio"]:
        errors.append(
            f"cnpv_realised_ratio={ratio} < required "
            f"{CC_VALUATION_GOVERNANCE['min_cnpv_realised_ratio']}"
        )

    psi = m.get("ftp_psi")
    if psi is not None and psi > CC_VALUATION_GOVERNANCE["max_ftp_psi"]:
        errors.append(
            f"ftp_psi={psi} > allowed {CC_VALUATION_GOVERNANCE['max_ftp_psi']}"
        )

    mono = m.get("monotone_pct")
    if mono is None or mono < CC_VALUATION_GOVERNANCE["min_monotone_pct"]:
        errors.append(
            f"monotone_pct={mono} < required "
            f"{CC_VALUATION_GOVERNANCE['min_monotone_pct']}"
        )

    if errors:
        raise CCValuationGovernanceError(
            f"{CC_VALUATION_MODEL_NAME} v{version} failed governance: "
            + "; ".join(errors)
        )

    logger.info(
        "CC Valuation governance PASSED for '%s' v%s",
        model_name, version,
    )


# ---------------------------------------------------------------------------
# Section 20 — CC Portfolio Action governance check (module-level)
# ---------------------------------------------------------------------------


def _cc_portfolio_governance_check(client: Any, model_name: str, version: str) -> None:
    """OOS governance checks before Production promotion of cc_portfolio_action.

    Validates:
      - cli_precision_oos  >= 0.72
      - cld_recall_oos     >= 0.80
      - macro_auc_oos      >= 0.82
      - guardrail_coverage == 1.00

    Raises
    ------
    CCPortfolioGovernanceError
        If any governance threshold is violated.
    """
    import mlflow

    mv = client.get_model_version(model_name, version)
    if not mv.run_id:
        raise CCPortfolioGovernanceError(
            f"{model_name} v{version} has no associated run_id; cannot verify governance."
        )
    run = mlflow.get_run(mv.run_id)
    m   = run.data.metrics
    errors: list = []

    checks = [
        ("cli_precision_oos",  CC_PORTFOLIO_GOVERNANCE["min_cli_precision"],  ">="),
        ("cld_recall_oos",     CC_PORTFOLIO_GOVERNANCE["min_cld_recall"],      ">="),
        ("macro_auc_oos",      CC_PORTFOLIO_GOVERNANCE["min_macro_auc"],       ">="),
        ("guardrail_coverage", CC_PORTFOLIO_GOVERNANCE["min_guardrail_coverage"], ">="),
    ]

    for metric_key, threshold, op in checks:
        val = m.get(metric_key)
        if val is None:
            errors.append(f"'{metric_key}' metric missing from MLflow run")
        elif val < threshold:
            errors.append(
                f"{metric_key}={val:.4f} < required {threshold}"
            )

    if errors:
        raise CCPortfolioGovernanceError(
            f"{CC_PORTFOLIO_MODEL_NAME} v{version} failed governance: "
            + "; ".join(errors)
        )

    logger.info(
        "CC Portfolio Action governance PASSED for '%s' v%s",
        model_name, version,
    )


# ---------------------------------------------------------------------------
# Section 21 — Mortgage Valuation governance check (module-level)
# ---------------------------------------------------------------------------


def _mortgage_valuation_governance_check(
    client: Any, model_name: str, version: str
) -> None:
    """Mortgage valuation model governance checks before Production promotion.

    Validates:
      - lr_auc          >= 0.78  (loan-level 90-day DPD AUC)
      - gini            >= 0.56
      - ltv_psi         <= 0.15  (LTV distribution stability)
      - hpa_monotone_pct >= 0.99 (HPA scenario monotonicity)
      - cnpv_realised_ratio >= 0.70  (12m NPV backtesting)

    Raises
    ------
    MortgageValuationGovernanceError
        If any governance threshold is violated.
    """
    import mlflow

    mv = client.get_model_version(model_name, version)
    if not mv.run_id:
        raise MortgageValuationGovernanceError(
            f"{model_name} v{version} has no associated run_id; cannot verify governance."
        )
    run = mlflow.get_run(mv.run_id)
    m   = run.data.metrics
    thresh = MODEL_GOVERNANCE.get(MORTGAGE_VALUATION_MODEL_NAME, {})
    errors: list[str] = []

    # AUC check
    lr_auc = m.get("lr_auc")
    min_lr_auc = thresh.get("min_lr_auc", 0.78)
    if lr_auc is None or lr_auc < min_lr_auc:
        errors.append(f"lr_auc={lr_auc} < required {min_lr_auc}")

    # Gini check
    gini = m.get("gini")
    min_gini = thresh.get("min_gini", 0.56)
    if gini is None or gini < min_gini:
        errors.append(f"gini={gini} < required {min_gini}")

    # LTV PSI check
    ltv_psi = m.get("ltv_psi")
    max_ltv_psi = thresh.get("max_ltv_psi", 0.15)
    if ltv_psi is not None and ltv_psi > max_ltv_psi:
        errors.append(f"ltv_psi={ltv_psi} > allowed {max_ltv_psi}")

    # HPA monotonicity check
    hpa_mono = m.get("hpa_monotone_pct")
    min_hpa_mono = thresh.get("min_hpa_monotone_pct", 0.99)
    if hpa_mono is None or hpa_mono < min_hpa_mono:
        errors.append(f"hpa_monotone_pct={hpa_mono} < required {min_hpa_mono}")

    # CNPV backtesting check
    cnpv_ratio = m.get("cnpv_realised_ratio")
    min_cnpv = thresh.get("min_cnpv_realised_ratio", 0.70)
    if cnpv_ratio is None or cnpv_ratio < min_cnpv:
        errors.append(f"cnpv_realised_ratio={cnpv_ratio} < required {min_cnpv}")

    if errors:
        raise MortgageValuationGovernanceError(
            f"{MORTGAGE_VALUATION_MODEL_NAME} v{version} failed governance: "
            + "; ".join(errors)
        )

    logger.info(
        "Mortgage Valuation governance PASSED for '%s' v%s",
        model_name, version,
    )


# ---------------------------------------------------------------------------
# Section 21 — Unified _run_model_governance dispatcher
# ---------------------------------------------------------------------------


def _run_model_governance(
    client: Any,
    model_name: str,
    version: str,
    base_check_fn: Any = None,
) -> None:
    """Dispatch to per-model governance check before Production promotion.

    Routing table:
      cc_pd_model                → base AUC/KS check
      cc_origination_valuation   → _cc_valuation_governance_check
      cc_portfolio_action        → _cc_portfolio_governance_check
      mortgage_valuation_model   → _mortgage_valuation_governance_check
      <any other>                → base AUC/KS check (if base_check_fn provided)

    After the governance check passes, tags the MLflow run with
    ``sr11_7_stage = "production"`` for audit traceability.
    """
    dispatch = {
        CC_VALUATION_MODEL_NAME:      _cc_valuation_governance_check,
        CC_PORTFOLIO_MODEL_NAME:      _cc_portfolio_governance_check,
        MORTGAGE_VALUATION_MODEL_NAME: _mortgage_valuation_governance_check,
    }

    check_fn = dispatch.get(model_name)
    if check_fn:
        check_fn(client, model_name, version)
    elif base_check_fn is not None:
        # For CC PD model and any future models: use base AUC/KS check
        base_check_fn(client, model_name, version)
    else:
        logger.warning(
            "No governance check registered for model '%s' — skipping.", model_name
        )

    # Tag MLflow run with SR 11-7 stage for audit trail
    try:
        mv = client.get_model_version(model_name, version)
        if mv.run_id:
            import mlflow
            mlflow_client = mlflow.tracking.MlflowClient()
            mlflow_client.set_tag(mv.run_id, "sr11_7_stage", "production")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not set sr11_7_stage tag: %s", exc)
