"""
data_contracts.v1.features
============================
Contracts for feature vectors, model drift reports, and model performance
snapshots.

Consumers
---------
* ThinFile         — consumes FeatureVectorV1 for offline model training
* AgentHiveHQ      — subscribes to DriftAlertEvent (wraps FeatureDriftReportV1)
* LucidCredit      — reads ModelPerformanceSnapshotV1 to surface AUC/Gini metrics

Versioning note
---------------
``feature_version`` within FeatureVectorV1 tracks the FeaturePipelineConfig
version in ``feature_pipeline/features.py``.  A bump here does NOT require a
contract version bump unless the schema of the ``features`` dict changes shape
(e.g. a feature is renamed or removed).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DriftStatusV1(str, Enum):
    STABLE = "stable"    # PSI < 0.10
    MINOR = "minor"      # 0.10 ≤ PSI < 0.25
    MAJOR = "major"      # PSI ≥ 0.25


class ModelVariantV1(str, Enum):
    CHAMPION = "champion"
    CHALLENGER = "challenger"
    SHADOW = "shadow"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class _ContractBaseV1(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        populate_by_name=True,
        str_strip_whitespace=True,
    )
    schema_version: Literal["1.0.0"] = "1.0.0"
    contract_name: str = Field(...)


# ---------------------------------------------------------------------------
# FeatureVectorV1 — point-in-time feature snapshot for one application
# ---------------------------------------------------------------------------


class FeatureVectorV1(_ContractBaseV1):
    """
    Point-in-time feature snapshot produced by the FeatureEngineeringAgent.

    ``as_of_date`` enforces look-ahead-bias prevention: consumers querying
    historical features must supply this date so only features known at that
    time are returned.  See ``feature_pipeline/feature_store.py`` for the
    underlying read semantics.

    The ``features`` dict uses the canonical feature names defined in
    ``feature_pipeline/features.py``.  All values are float-castable.
    Unknown keys in ``features`` must be tolerated by consumers.
    """

    contract_name: Literal["FeatureVectorV1"] = "FeatureVectorV1"

    application_id: str
    tenant_id: str

    # Point-in-time correctness
    event_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Wall-clock UTC moment when features were computed.",
    )
    as_of_date: date = Field(
        ...,
        description="Business date the features represent. Use this for "
                    "historical queries to prevent look-ahead bias.",
    )

    # Feature payload
    features: Dict[str, float] = Field(
        ...,
        description="Canonical feature name → value mapping. "
                    "All values are float. Missing features are absent (not 0).",
    )
    feature_version: str = Field(
        "1.0.0",
        description="FeaturePipelineConfig version that produced these features.",
    )

    # Alt-data metadata
    thin_file_signals_used: bool = Field(
        False,
        description="True when at least one alt-data feature contributed to the vector.",
    )
    completeness_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Fraction of canonical features that are non-null.",
    )

    # Provenance
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    feature_hash: Optional[str] = Field(
        None,
        description="SHA-256 of sorted JSON of all feature values — for audit "
                    "deduplication and look-ahead bias detection.",
    )


# ---------------------------------------------------------------------------
# FeatureDriftResultV1 — drift metrics for a single feature
# ---------------------------------------------------------------------------


class FeatureDriftResultV1(BaseModel):
    """Drift metrics for a single feature in a drift monitoring run."""

    model_config = ConfigDict(extra="ignore")

    feature_name: str
    psi: float = Field(..., ge=0.0, description="Population Stability Index.")
    ks_statistic: float = Field(..., ge=0.0, le=1.0, description="KS test statistic.")
    ks_p_value: float = Field(..., ge=0.0, le=1.0, description="KS test p-value.")
    drift_status: DriftStatusV1

    # Distribution summaries
    reference_mean: float
    production_mean: float
    reference_std: float
    production_std: float
    mean_shift_pct: float = Field(
        ...,
        description="Percentage shift in mean relative to reference std: "
                    "(production_mean - reference_mean) / reference_std × 100.",
    )


# ---------------------------------------------------------------------------
# FeatureDriftReportV1 — aggregate drift report for a production batch
# ---------------------------------------------------------------------------


class FeatureDriftReportV1(_ContractBaseV1):
    """
    Aggregate drift report produced by the drift monitor for a production
    batch compared to a reference (training) distribution.

    PSI thresholds used by the platform:
      < 0.10  → stable  (no action)
      0.10–0.25 → minor (amber alert)
      > 0.25  → major  (red alert, page on-call)

    Emitted as a ``DriftAlertEvent`` when ``overall_drift_status == 'major'``.
    """

    contract_name: Literal["FeatureDriftReportV1"] = "FeatureDriftReportV1"

    tenant_id: str
    model_variant: ModelVariantV1 = ModelVariantV1.CHAMPION

    # Batch metadata
    batch_id: str = Field(..., description="Identifier of the scored production batch.")
    reference_window_start: date
    reference_window_end: date
    production_window_start: date
    production_window_end: date
    n_reference_records: int = Field(..., ge=0)
    n_production_records: int = Field(..., ge=0)

    # Per-feature drift results
    feature_results: List[FeatureDriftResultV1] = Field(default_factory=list)

    # Aggregate verdict
    overall_drift_status: DriftStatusV1
    n_features_stable: int = Field(..., ge=0)
    n_features_minor_drift: int = Field(..., ge=0)
    n_features_major_drift: int = Field(..., ge=0)

    # Metadata
    feature_version: str = "1.0.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    alert_dispatched: bool = Field(
        False,
        description="True if a DriftAlertEvent was emitted for this report.",
    )


# ---------------------------------------------------------------------------
# ModelPerformanceSnapshotV1 — champion/challenger model metrics
# ---------------------------------------------------------------------------


class ModelPerformanceSnapshotV1(_ContractBaseV1):
    """
    Periodic snapshot of model discrimination and calibration metrics.

    Published by the model monitoring job. Consumed by:
    - LucidCredit (surfaces AUC/Gini to credit analysts)
    - AgentHiveHQ (triggers champion/challenger promotion workflows)
    - ThinFile (model registry + retraining triggers)
    """

    contract_name: Literal["ModelPerformanceSnapshotV1"] = "ModelPerformanceSnapshotV1"

    tenant_id: str
    model_id: str = Field(..., description="Model registry identifier.")
    model_variant: ModelVariantV1
    model_version: str
    product_type: str = Field(..., description="Product line: credit_card, personal_loan, mortgage.")

    # Evaluation window
    eval_window_start: date
    eval_window_end: date
    n_evaluated: int = Field(..., ge=0, description="Number of records in the eval set.")

    # Discrimination metrics
    auc_roc: float = Field(..., ge=0.0, le=1.0, description="AUROC.")
    gini_coefficient: float = Field(
        ..., ge=-1.0, le=1.0,
        description="Gini = 2 × AUROC − 1.",
    )
    ks_statistic: float = Field(
        ..., ge=0.0, le=1.0,
        description="KS statistic between PD distributions of defaulters vs. non-defaulters.",
    )

    # Calibration metrics
    brier_score: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Brier score (lower is better).",
    )
    log_loss: Optional[float] = Field(None, ge=0.0)

    # Business metrics
    approval_rate: Optional[float] = Field(None, ge=0.0, le=1.0)
    bad_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Observed default rate in the evaluation window.",
    )
    expected_bad_rate: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="Model-predicted default rate — compare to bad_rate for calibration check.",
    )

    # Status
    champion_promotion_eligible: bool = Field(
        False,
        description="True when this challenger outperforms the current champion "
                    "on AUC and passes the statistical significance gate.",
    )
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
