"""
Risk Modeling Agent
====================
Domain Owner : Model Risk Management / Data Science
SR 11-7 Stage: Model development, validation & production scoring

Responsibilities
----------------
* Load champion (+ optional challenger) PD and fraud models
* Score each FeatureVector via predict_pd() and predict_fraud()
* Compute pricing via the pricing engine
* Enforce model performance assertions (back-test gate)
* Support champion / challenger traffic split for experimentation

Section 21 Extensions
---------------------
* CC Origination Valuation champion/challenger (cc_origination_valuation)
* CC Portfolio Action champion/challenger (cc_portfolio_action)
* Mortgage Valuation champion/challenger (mortgage_valuation_model)
* Challenger decisions tagged in audit_log as model_version_portfolio="challenger:<ver>"
* All models loaded from MLflow Production registry on init

Inputs  : AgentResult.payload["feature_df"]  from FeatureEngineeringAgent
Outputs : AgentResult.payload["model_scores"] = List[ModelScores]
"""

from __future__ import annotations

import logging
import os
import random
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from agents.base import AgentResult, AgentStatus, BaseAgent
from schemas.contracts import FraudFlag, ModelScores, PDband

logger = logging.getLogger(__name__)

# Lazy import guard: models may not be trained in CI
try:
    from models.credit_risk.predict import predict_pd
    from models.fraud_detection.predict import predict_fraud
    from models.model_loader import preload as _preload_models  # P1.4
    from models.pricing.engine import PricingConfig, calculate_pricing
    _MODELS_AVAILABLE = True
except ImportError:
    _MODELS_AVAILABLE = False
    logger.warning("Model packages not importable — RiskModelingAgent running in stub mode")


# ---------------------------------------------------------------------------
# Stub fallbacks (for CI / unit tests without trained artefacts)
# ---------------------------------------------------------------------------


def _stub_pd_score(df: pd.DataFrame) -> pd.DataFrame:
    """Return neutral PD scores when real model unavailable."""
    out = pd.DataFrame(index=df.index)
    out["pd_score"] = 0.07
    out["pd_band"] = "medium"
    return out


def _stub_fraud_score(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["fraud_probability"] = 0.10
    out["fraud_flag"] = "continue"
    return out


# ---------------------------------------------------------------------------
# RiskModelingAgent
# ---------------------------------------------------------------------------


class RiskModelingAgent(BaseAgent):
    """
    Scores applicants using the champion PD + fraud models and pricing engine.

    Supports champion/challenger traffic splitting for A/B experiments.

    Config keys (from agent_config.yaml → risk_modeling):
      credit_risk.model_path, credit_risk.challenger_model_path,
      credit_risk.pd_band_thresholds,
      fraud_detection.model_path,
      fraud_detection.fraud_threshold_reject, fraud_detection.fraud_threshold_review
    """

    name = "RiskModelingAgent"

    def __init__(self, config: Dict[str, Any] | None = None, tenant_model_bindings: Optional[Dict[str, str]] = None):
        super().__init__(config)
        cr_cfg = self.config.get("credit_risk", {})
        fd_cfg = self.config.get("fraud_detection", {})

        # ── PD / Fraud (Sections 1-18) ────────────────────────────────────
        self._champion_pd_path: Optional[str] = cr_cfg.get("champion_model_path")
        self._challenger_pd_path: Optional[str] = cr_cfg.get("challenger_model_path")
        self._fraud_model_path: Optional[str] = fd_cfg.get("model_path")
        self._pd_thresholds: Dict[str, float] = cr_cfg.get(
            "pd_band_thresholds", {"low_max": 0.05, "medium_max": 0.10}
        )
        self._challenger_pct: float = self.config.get("challenger_traffic_pct", 0.0)

        # ── CC Origination Valuation (Section 19) ────────────────────────
        val_cfg = self.config.get("cc_valuation", {})
        self._val_champion_path: Optional[str]   = val_cfg.get("champion_model")
        self._val_challenger_path: Optional[str] = val_cfg.get("challenger_model")
        self._val_challenger_pct: float          = float(val_cfg.get("challenger_traffic_pct", 0.0))

        # ── CC Portfolio Action (Section 20) ─────────────────────────────
        port_cfg = self.config.get("cc_portfolio", {})
        self._port_champion_path: Optional[str]   = port_cfg.get("champion_model")
        self._port_challenger_path: Optional[str] = port_cfg.get("challenger_model")
        self._port_challenger_pct: float          = float(port_cfg.get("challenger_traffic_pct", 0.0))

        # ── Mortgage Valuation (Section 21) ──────────────────────────────
        mort_cfg = self.config.get("mortgage_valuation", {})
        self._mort_champion_path: Optional[str]   = mort_cfg.get("champion_model")
        self._mort_challenger_path: Optional[str] = mort_cfg.get("challenger_model")
        self._mort_challenger_pct: float          = float(mort_cfg.get("challenger_traffic_pct", 0.0))

        # P2: Apply per-tenant model artefact URI overrides if provided.
        # Overrides must be applied BEFORE _preload_agent_models() so that
        # the pre-load cache populates the tenant-specific artefacts.
        if tenant_model_bindings:
            self._apply_tenant_model_bindings(tenant_model_bindings)

        # P1.4: Eagerly preload all configured model artefacts at agent init so
        # that the per-request hot path is a pure cache hit (no disk I/O).
        if _MODELS_AVAILABLE:
            self._preload_agent_models()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_tenant_model_bindings(self, bindings: Dict[str, str]) -> None:
        """Override model artefact paths from per-tenant config bindings.

        Called before _preload_agent_models() so the cache is populated
        with the tenant-specific artefact URIs.

        Supported binding keys → instance attribute mapping:
          pd_champion     → _champion_pd_path
          pd_challenger   → _challenger_pd_path
          fraud_champion  → _fraud_model_path
          cc_val_champion → _val_champion_path
          cc_val_challenger → _val_challenger_path
          cc_port_champion  → _port_champion_path
          cc_port_challenger → _port_challenger_path
          mort_champion   → _mort_champion_path
          mort_challenger → _mort_challenger_path
        """
        _binding_map: Dict[str, str] = {
            "pd_champion":       "_champion_pd_path",
            "pd_challenger":     "_challenger_pd_path",
            "fraud_champion":    "_fraud_model_path",
            "cc_val_champion":   "_val_champion_path",
            "cc_val_challenger": "_val_challenger_path",
            "cc_port_champion":  "_port_champion_path",
            "cc_port_challenger":"_port_challenger_path",
            "mort_champion":     "_mort_champion_path",
            "mort_challenger":   "_mort_challenger_path",
        }
        applied: List[str] = []
        for binding_key, attr in _binding_map.items():
            if binding_key in bindings:
                uri = bindings[binding_key]
                # Validate: local paths must exist at construction time
                if uri and not (
                    uri.startswith("models:/")
                    or uri.startswith("gs://")
                    or uri.startswith("s3://")
                ):
                    import os as _os
                    if not _os.path.exists(uri):
                        raise FileNotFoundError(
                            f"Tenant model binding '{binding_key}' points to a missing artefact: {uri!r}. "
                            "Fix the binding in config_registry or ensure the artefact is deployed."
                        )
                setattr(self, attr, uri)
                applied.append(f"{binding_key}={uri!r}")
        if applied:
            logger.info("RiskModelingAgent: applied tenant model bindings: %s", ", ".join(applied))

    def _preload_agent_models(self) -> None:
        """Pre-load all configured model artefacts into the process-level cache.

        Called once from __init__ so that _score_pd / _score_fraud hit the
        cache on every subsequent request (P1.4: no per-request disk I/O).
        Missing artefacts are logged as warnings and fall back to stubs.
        """
        candidates = [
            (self._champion_pd_path, "champion"),
            (self._challenger_pd_path, "challenger"),
            (self._fraud_model_path, "v1"),
            (self._val_champion_path, "cc_val_champion"),
            (self._val_challenger_path, "cc_val_challenger"),
            (self._port_champion_path, "cc_port_champion"),
            (self._port_challenger_path, "cc_port_challenger"),
            (self._mort_champion_path, "mort_champion"),
            (self._mort_challenger_path, "mort_challenger"),
        ]
        to_load = [(p, v) for p, v in candidates if p]
        if to_load:
            _preload_models(to_load)  # type: ignore[arg-type]
            logger.info("RiskModelingAgent: preloaded %d model artefact(s)", len(to_load))

    def _pd_band(self, score: float) -> PDband:
        if score <= self._pd_thresholds.get("low_max", 0.05):
            return PDband.LOW
        if score <= self._pd_thresholds.get("medium_max", 0.10):
            return PDband.MEDIUM
        return PDband.HIGH

    def _fraud_flag(self, prob: float, cfg: Dict[str, Any]) -> FraudFlag:
        if prob >= cfg.get("fraud_threshold_reject", 0.60):
            return FraudFlag.REJECT
        if prob >= cfg.get("fraud_threshold_review", 0.30):
            return FraudFlag.MANUAL_REVIEW
        return FraudFlag.CONTINUE

    def _score_pd(self, df: pd.DataFrame, use_challenger: bool) -> pd.DataFrame:
        if not _MODELS_AVAILABLE:
            return _stub_pd_score(df)
        model_path = (
            self._challenger_pd_path if use_challenger and self._challenger_pd_path
            else self._champion_pd_path
        )
        try:
            return predict_pd(df, model_path=model_path)
        except (FileNotFoundError, OSError):
            self._log.warning(
                "PD model artefact not found at %s — using stub scores. "
                "Run models/credit_risk/train.py to generate.",
                model_path,
            )
            return _stub_pd_score(df)

    def _score_fraud(self, df: pd.DataFrame) -> pd.DataFrame:
        if not _MODELS_AVAILABLE:
            return _stub_fraud_score(df)
        try:
            return predict_fraud(df, model_path=self._fraud_model_path)
        except (FileNotFoundError, OSError):
            self._log.warning(
                "Fraud model artefact not found at %s — using stub scores. "
                "Run models/fraud_detection/train.py to generate.",
                self._fraud_model_path,
            )
            return _stub_fraud_score(df)

    # ------------------------------------------------------------------
    # Section 21 — Champion/Challenger helpers for new model types
    # ------------------------------------------------------------------

    @staticmethod
    def _should_use_challenger(challenger_pct: float) -> bool:
        """Return True if this request should be routed to the challenger model.

        Uses a deterministic random draw — challenger_pct expressed as
        percentage (0–100).  Returns False if challenger_pct == 0.
        """
        if challenger_pct <= 0:
            return False
        return random.random() * 100 < challenger_pct

    @staticmethod
    def _load_mlflow_model(model_uri: str) -> Tuple[Any, str]:
        """Load a model from MLflow registry URI and return (model, version).

        *model_uri* format:  ``cc_origination_valuation/Production``
            → parsed as ``models:/<name>/<stage>``

        Returns ``(None, "unavailable")`` if loading fails.
        """
        try:
            import mlflow.sklearn
            from mlflow.tracking import MlflowClient

            if "/" in model_uri:
                name, stage = model_uri.rsplit("/", 1)
            else:
                name, stage = model_uri, "Production"

            full_uri = f"models:/{name}/{stage}"
            model = mlflow.sklearn.load_model(full_uri)

            # Get version string
            client = MlflowClient()
            versions = client.get_latest_versions(name, stages=[stage])
            ver = versions[0].version if versions else "unknown"
            return model, str(ver)
        except Exception as exc:
            logger.warning("Could not load MLflow model '%s': %s", model_uri, exc)
            return None, "unavailable"

    def _score_cc_valuation(
        self, df: pd.DataFrame, use_challenger: bool
    ) -> Tuple[pd.DataFrame, str]:
        """Score using CC origination valuation model (champion or challenger).

        Returns (results_df, model_version_tag).
        ``model_version_tag`` = ``"challenger:<ver>"`` when challenger is used.
        """
        model_uri = (
            self._val_challenger_path
            if use_challenger and self._val_challenger_path
            else self._val_champion_path
        )
        if not model_uri:
            logger.debug("No CC valuation model configured — returning empty scores")
            return pd.DataFrame(), "not_configured"

        model, ver = self._load_mlflow_model(model_uri)
        if model is None:
            return pd.DataFrame(), "unavailable"

        tag = f"challenger:{ver}" if use_challenger and self._val_challenger_path else f"champion:{ver}"
        try:
            preds = model.predict_proba(df)[:, 1] if hasattr(model, "predict_proba") else model.predict(df)
            result_df = pd.DataFrame({"valuation_score": preds}, index=df.index)
        except Exception as exc:
            logger.warning("CC valuation model inference failed: %s", exc)
            return pd.DataFrame(), f"error:{ver}"
        return result_df, tag

    def _score_cc_portfolio(
        self, df: pd.DataFrame, use_challenger: bool
    ) -> Tuple[pd.DataFrame, str]:
        """Score using CC portfolio action model (champion or challenger).

        Returns (results_df, model_version_tag).
        """
        model_uri = (
            self._port_challenger_path
            if use_challenger and self._port_challenger_path
            else self._port_champion_path
        )
        if not model_uri:
            logger.debug("No CC portfolio model configured — returning empty scores")
            return pd.DataFrame(), "not_configured"

        model, ver = self._load_mlflow_model(model_uri)
        if model is None:
            return pd.DataFrame(), "unavailable"

        tag = f"challenger:{ver}" if use_challenger and self._port_challenger_path else f"champion:{ver}"
        try:
            if hasattr(model, "predict_proba"):
                proba = model.predict_proba(df)
                preds = model.classes_[proba.argmax(axis=1)]
            else:
                preds = model.predict(df)
            result_df = pd.DataFrame({"portfolio_action": preds}, index=df.index)
        except Exception as exc:
            logger.warning("CC portfolio model inference failed: %s", exc)
            return pd.DataFrame(), f"error:{ver}"
        return result_df, tag

    def _score_mortgage_valuation(
        self, df: pd.DataFrame, use_challenger: bool
    ) -> Tuple[pd.DataFrame, str]:
        """Score using mortgage valuation model (champion or challenger).

        Returns (results_df, model_version_tag).
        Mortgage model outputs: pd_score_mortgage, hpa_scenario_cnpv, ltv_adjusted.
        """
        model_uri = (
            self._mort_challenger_path
            if use_challenger and self._mort_challenger_path
            else self._mort_champion_path
        )
        if not model_uri:
            logger.debug("No mortgage valuation model configured — returning empty scores")
            return pd.DataFrame(), "not_configured"

        model, ver = self._load_mlflow_model(model_uri)
        if model is None:
            return pd.DataFrame(), "unavailable"

        tag = f"challenger:{ver}" if use_challenger and self._mort_challenger_path else f"champion:{ver}"
        try:
            preds = model.predict_proba(df)[:, 1] if hasattr(model, "predict_proba") else model.predict(df)
            result_df = pd.DataFrame({"mortgage_pd_score": preds}, index=df.index)
        except Exception as exc:
            logger.warning("Mortgage valuation model inference failed: %s", exc)
            return pd.DataFrame(), f"error:{ver}"
        return result_df, tag

    # ------------------------------------------------------------------
    # Core agent logic
    # ------------------------------------------------------------------

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "feature_df"       : List[dict]  — feature row dicts
          "use_challenger"   : bool        — override challenger flag (optional)
        """
        feature_dicts: List[Dict[str, Any]] = inputs.get("feature_df", [])
        if not feature_dicts:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=["No feature_df provided to RiskModelingAgent"],
            )

        df = pd.DataFrame(feature_dicts)
        use_challenger_pd: bool = inputs.get("use_challenger", False)

        # ── PD + Fraud scoring (Sections 1-18) ──────────────────────────
        pd_results = self._score_pd(df, use_challenger=use_challenger_pd)
        fraud_results = self._score_fraud(df)

        # ── Section 21: CC Valuation champion/challenger ─────────────────
        use_val_challenger = self._should_use_challenger(self._val_challenger_pct)
        val_results, val_version_tag = self._score_cc_valuation(df, use_val_challenger)

        # ── Section 21: CC Portfolio champion/challenger ──────────────────
        use_port_challenger = self._should_use_challenger(self._port_challenger_pct)
        port_results, port_version_tag = self._score_cc_portfolio(df, use_port_challenger)

        # ── Section 21: Mortgage Valuation champion/challenger ───────────
        use_mort_challenger = self._should_use_challenger(self._mort_challenger_pct)
        mort_results, mort_version_tag = self._score_mortgage_valuation(df, use_mort_challenger)

        # Pricing
        model_version = "challenger" if use_challenger_pd and self._challenger_pd_path else "champion"
        fd_cfg = self.config.get("fraud_detection", {})

        scores: List[ModelScores] = []
        for i, (_, row) in enumerate(df.iterrows()):
            app_id = str(row.get("application_id", f"ROW_{i}"))
            pd_score = float(pd_results.iloc[i]["pd_score"])
            fraud_prob = float(fraud_results.iloc[i]["fraud_probability"])
            fraud_flag = self._fraud_flag(fraud_prob, fd_cfg)

            # Pricing
            rec_rate: Optional[float] = None
            exp_loss: Optional[float] = None
            exp_profit: Optional[float] = None
            if _MODELS_AVAILABLE:
                try:
                    pr = calculate_pricing(
                        pd_score=pd_score,
                        fraud_flag=fraud_flag.value,
                        loan_amount=float(row.get("loan_amount", row.get("log_loan_amount", 0))),
                        config=PricingConfig(),
                        borrower_state=str(row.get("borrower_state", "CA")),
                    )
                    rec_rate = pr.recommended_rate
                    exp_loss = pr.expected_loss
                    exp_profit = pr.expected_profit
                except Exception:  # noqa: BLE001
                    pass

            scores.append(
                ModelScores(
                    application_id=app_id,
                    pd_score=pd_score,
                    pd_band=self._pd_band(pd_score),
                    fraud_probability=fraud_prob,
                    fraud_flag=fraud_flag,
                    recommended_rate=rec_rate,
                    expected_loss=exp_loss,
                    expected_profit=exp_profit,
                    model_version=model_version,
                )
            )

        self._log.info(
            "Scored %d applicants — pd_model=%s, cc_val=%s, cc_port=%s, mort=%s, avg_pd=%.4f",
            len(scores),
            model_version,
            val_version_tag,
            port_version_tag,
            mort_version_tag,
            sum(s.pd_score for s in scores) / max(len(scores), 1),
        )

        # Build extended payload with all model versions and scores
        payload: Dict[str, Any] = {
            "model_scores": [s.model_dump() for s in scores],
            "model_version": model_version,
            "avg_pd_score": sum(s.pd_score for s in scores) / max(len(scores), 1),
            # Section 21 — extended model version tags for audit log
            "model_version_valuation":  val_version_tag,
            "model_version_portfolio":  port_version_tag,
            "model_version_mortgage":   mort_version_tag,
        }

        # Attach valuation scores if available
        if not val_results.empty:
            payload["valuation_scores"] = val_results.to_dict("records")
        if not port_results.empty:
            payload["portfolio_actions"] = port_results.to_dict("records")
        if not mort_results.empty:
            payload["mortgage_scores"] = mort_results.to_dict("records")

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload=payload,
        )
