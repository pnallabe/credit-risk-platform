"""
Credit Risk — Inference Module (Probability of Default)
=======================================================
Loads a trained LightGBM model and exposes predict_pd() for use by
the decision API.

PD bands (from PRD)
-------------------
  pd_score < 0.05         → "low"
  0.05 ≤ pd_score ≤ 0.10  → "medium"
  pd_score > 0.10         → "high"

Usage
-----
    python models/credit_risk/predict.py --model models/credit_risk/risk_model_v1.pkl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Union

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))
from feature_pipeline.features import FeaturePipelineConfig, compute_features  # noqa: E402

MODEL_VERSION = "v1"
_FEATURE_CONFIG = FeaturePipelineConfig()
FEATURE_COLS = _FEATURE_CONFIG.feature_list

# ---------------------------------------------------------------------------
# Band thresholds
# ---------------------------------------------------------------------------
BAND_LOW_MAX = 0.05
BAND_MEDIUM_MAX = 0.10


def _pd_band(score: float) -> str:
    if score < BAND_LOW_MAX:
        return "low"
    if score <= BAND_MEDIUM_MAX:
        return "medium"
    return "high"


def predict_pd(
    features_df: pd.DataFrame,
    model_path: Union[str, Path, None] = None,
    _model=None,
) -> pd.DataFrame:
    """Run probability-of-default inference on a features DataFrame.

    Parameters
    ----------
    features_df:
        DataFrame already passed through
        ``feature_pipeline.features.compute_features()``.
    model_path:
        Path to a joblib-serialised LightGBM model.
        Defaults to ``models/credit_risk/risk_model_v1.pkl``.
    _model:
        Pre-loaded model (used in unit tests to skip disk I/O).

    Returns
    -------
    pd.DataFrame
        Same index as *features_df*, with two columns:
        - ``pd_score``  (float 0–1) probability of default
        - ``pd_band``   (str: "low" | "medium" | "high")
    """
    if _model is None:
        if model_path is None:
            model_path = Path(__file__).parents[2] / "models" / "credit_risk" / "risk_model_v1.pkl"
        model = joblib.load(model_path)
    else:
        model = _model

    X = features_df[FEATURE_COLS].values
    pd_scores = model.predict_proba(X)[:, 1]

    result = features_df[[col for col in ["application_id"] if col in features_df.columns]].copy()
    result["pd_score"] = pd_scores
    result["pd_band"] = [_pd_band(s) for s in pd_scores]
    return result[["pd_score", "pd_band"]]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run credit risk (PD) inference")
    parser.add_argument(
        "--model",
        type=str,
        default=str(Path(__file__).parent / "risk_model_v1.pkl"),
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(Path(__file__).parents[2] / "data" / "raw" / "loan_applications_test.parquet"),
    )
    args = parser.parse_args()

    df_raw = pd.read_parquet(args.input)
    df_features = compute_features(df_raw, _FEATURE_CONFIG)
    df_out = predict_pd(df_features, model_path=args.model)
    print(df_out.head(20).to_string())
    print(f"\nPD band distribution:\n{df_out['pd_band'].value_counts()}")
    print(f"Mean PD score: {df_out['pd_score'].mean():.4f}")
