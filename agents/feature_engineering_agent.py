"""
Feature Engineering Agent
==========================
Domain Owner : ML Platform / Data Science
SR 11-7 Stage: Feature governance & lineage

Responsibilities
----------------
* Consume ValidatedRecord(s) from DataIngestionAgent
* Run the existing feature_pipeline (credit_utilization, income_stability, …)
* Apply thin-file alt-data boosts when standard bureau features absent
* Version-stamp each FeatureVector for model lineage tracking
* Optionally persist to the feature store (async, PostgreSQL or SQLite)

Inputs  : AgentResult.payload["validated"] from DataIngestionAgent
Outputs : AgentResult.payload["feature_vectors"] = List[FeatureVector]
          AgentResult.payload["feature_df"]      = pd.DataFrame (serialised)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from agents.base import AgentResult, AgentStatus, BaseAgent
from credit_core.features import compute_feature_matrix
from schemas.contracts import FeatureVector

logger = logging.getLogger(__name__)

# NOTE: Column alias normalisation (existing_debt → existing_debt_amount,
# dti → debt_to_income_ratio) is handled inside
# credit_core.features.compute_feature_matrix — no manual renaming needed here.


# ---------------------------------------------------------------------------
# FeatureEngineeringAgent
# ---------------------------------------------------------------------------


class FeatureEngineeringAgent(BaseAgent):
    """
    Transforms validated applicant records → typed FeatureVectors.

    Feature computation is delegated to ``credit_core.features.compute_feature_matrix``
    — the canonical implementation shared with the Decision API.  The agent-local
    ``build_feature_dataframe`` function has been removed to eliminate divergent pipelines.

    Config keys (from agent_config.yaml → feature_engineering):
      version, income_capacity_fraction, thin_file_boost, clip_bounds
    """

    name = "FeatureEngineeringAgent"

    FEATURE_COLS = [
        "credit_utilization",
        "income_stability_score",
        "repayment_capacity",
        "debt_service_coverage",
        "credit_age_score",
        "derogatory_penalty",
        "months_since_delinquency",
        "log_loan_amount",
        "log_annual_income",
        "dti_x_loan_amount",
        "employment_encoded",
        "thin_file_alt_score",
    ]

    def __init__(self, config: Dict[str, Any] | None = None):
        super().__init__(config)
        self._version: str = self.config.get("version", "1.0.0")

    def _run(self, inputs: Dict[str, Any]) -> AgentResult:
        """
        inputs expected keys:
          "validated" : List[dict]  — ValidatedRecord dicts from DataIngestionAgent
        """
        validated_dicts: List[Dict[str, Any]] = inputs.get("validated", [])
        if not validated_dicts:
            return AgentResult(
                agent_name=self.name,
                status=AgentStatus.FAILURE,
                errors=["No validated records provided"],
            )

        # Unpack raw_features from each ValidatedRecord
        raw_rows = [v["raw_features"] for v in validated_dicts]
        df_raw = pd.DataFrame(raw_rows)

        # --- Delegate to credit_core canonical feature pipeline ---
        alt_weights = self.config.get("thin_file_boost", None)
        df_features = compute_feature_matrix(
            df_raw,
            version=self._version,
            alt_weights=alt_weights,
        )

        # Build FeatureVector output list
        vectors: List[FeatureVector] = []
        tenant_id = inputs.get("tenant_id", "")
        for _, row in df_features.iterrows():
            feat_dict = {
                col: float(row[col])
                for col in self.FEATURE_COLS
                if col in row.index and pd.notna(row[col])
            }
            thin = pd.isna(row.get("credit_score"))
            vectors.append(
                FeatureVector(
                    application_id=str(row["application_id"]),
                    tenant_id=tenant_id,
                    features=feat_dict,
                    feature_version=self._version,
                    thin_file_signals_used=bool(thin),
                )
            )

        # Return serialisable feature matrix too (for scoring)
        feature_df_dict = df_features[
            ["application_id"] + [c for c in self.FEATURE_COLS if c in df_features.columns]
        ].to_dict(orient="records")

        self._log.info("Computed %d feature vectors (version=%s)", len(vectors), self._version)

        return AgentResult(
            agent_name=self.name,
            status=AgentStatus.SUCCESS,
            payload={
                "feature_vectors": [v.model_dump() for v in vectors],
                "feature_df": feature_df_dict,
                "feature_version": self._version,
                "features_computed": self.FEATURE_COLS,
            },
        )

    # ------------------------------------------------------------------
    # Convenience: accept a raw DataFrame directly
    # ------------------------------------------------------------------

    def transform(self, df_raw: pd.DataFrame) -> tuple[pd.DataFrame, List[FeatureVector]]:
        """Return (feature_df, vectors). Useful for offline batch scoring."""
        validated_dicts = [
            {"raw_features": row} for row in df_raw.to_dict(orient="records")
        ]
        result = self.execute({"validated": validated_dicts})
        result.raise_on_failure()
        df_out = pd.DataFrame(result.payload["feature_df"])
        vectors = [FeatureVector(**v) for v in result.payload["feature_vectors"]]
        return df_out, vectors
