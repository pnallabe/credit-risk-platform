"""Reject inference (closed-loop) for PD model training.

The PD model is typically trained on booked/approved accounts only. Reject
inference augments training data with imputed outcomes for rejected applicants
based on the current model's predicted PD.

This implementation supports two common approaches:
- augmentation: probabilistic label assignment using predicted PD
- parceling: hard assignment based on PD threshold

All methods add a `sample_weight` column to downweight rejected records.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Tuple

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class RejectInferenceConfig:
    method: Literal["augmentation", "parceling"]
    augmentation_weight: float = 0.5
    parceling_threshold_bad: float = 0.5
    random_seed: int = 42
    document_bias_adjustment: bool = True


@dataclass(frozen=True)
class RejectInferenceSummary:
    method: str
    approved_count: int
    rejected_count: int
    total_count: int
    approved_default_rate: float
    rejected_imputed_default_rate: float
    combined_default_rate: float
    bias_adjustment_factor: float
    generated_at: datetime


def augmentation_method(
    approved_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    model: Any,
    config: RejectInferenceConfig,
) -> pd.DataFrame:
    if "default_flag" not in approved_df.columns:
        raise ValueError("approved_df must contain default_flag")
    if "default_flag" in rejected_df.columns:
        raise ValueError("rejected_df must NOT contain default_flag")

    rng = np.random.default_rng(int(config.random_seed))

    # Predict PD for rejected applicants.
    pd_scores = model.predict_proba(rejected_df)[:, 1]
    pd_scores = np.clip(pd_scores.astype(float), 0.0, 1.0)

    labels = rng.binomial(1, pd_scores).astype(int)

    rej = rejected_df.copy()
    rej["default_flag"] = labels
    rej["sample_weight"] = float(config.augmentation_weight)

    app = approved_df.copy()
    if "sample_weight" not in app.columns:
        app["sample_weight"] = 1.0

    combined = pd.concat([app, rej], axis=0, ignore_index=True)
    return combined


def parceling_method(
    approved_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    model: Any,
    config: RejectInferenceConfig,
) -> pd.DataFrame:
    if "default_flag" not in approved_df.columns:
        raise ValueError("approved_df must contain default_flag")
    if "default_flag" in rejected_df.columns:
        raise ValueError("rejected_df must NOT contain default_flag")

    pd_scores = model.predict_proba(rejected_df)[:, 1]
    pd_scores = np.clip(pd_scores.astype(float), 0.0, 1.0)

    labels = (pd_scores >= float(config.parceling_threshold_bad)).astype(int)

    rej = rejected_df.copy()
    rej["default_flag"] = labels
    rej["sample_weight"] = float(config.augmentation_weight)

    app = approved_df.copy()
    if "sample_weight" not in app.columns:
        app["sample_weight"] = 1.0

    combined = pd.concat([app, rej], axis=0, ignore_index=True)
    return combined


def run_reject_inference(
    approved_df: pd.DataFrame,
    rejected_df: pd.DataFrame,
    model: Any,
    config: RejectInferenceConfig,
) -> Tuple[pd.DataFrame, RejectInferenceSummary]:
    method = str(config.method)
    if method == "augmentation":
        combined = augmentation_method(approved_df, rejected_df, model, config)
    elif method == "parceling":
        combined = parceling_method(approved_df, rejected_df, model, config)
    else:
        raise ValueError(f"Unknown reject inference method: {method}")

    approved_count = int(len(approved_df))
    rejected_count = int(len(rejected_df))

    approved_default_rate = float(pd.Series(approved_df["default_flag"]).mean()) if approved_count else 0.0

    combined_rejected = combined.iloc[approved_count:]
    rejected_imputed_default_rate = float(pd.Series(combined_rejected["default_flag"]).mean()) if rejected_count else 0.0

    weights = pd.Series(combined.get("sample_weight", 1.0)).astype(float)
    combined_default_rate = float((weights * combined["default_flag"].astype(float)).sum() / weights.sum()) if len(combined) else 0.0

    if approved_default_rate <= 0:
        bias_adjustment_factor = float("inf") if combined_default_rate > 0 else 1.0
    else:
        bias_adjustment_factor = float(combined_default_rate / approved_default_rate)

    summary = RejectInferenceSummary(
        method=method,
        approved_count=approved_count,
        rejected_count=rejected_count,
        total_count=int(len(combined)),
        approved_default_rate=round(approved_default_rate, 6),
        rejected_imputed_default_rate=round(rejected_imputed_default_rate, 6),
        combined_default_rate=round(combined_default_rate, 6),
        bias_adjustment_factor=round(bias_adjustment_factor, 6) if bias_adjustment_factor != float("inf") else float("inf"),
        generated_at=datetime.now(timezone.utc),
    )

    return combined, summary


def save_summary(summary: RejectInferenceSummary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(summary)
    payload["generated_at"] = summary.generated_at.isoformat()

    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
