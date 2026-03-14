"""
Fraud Detection — Inference Module
====================================
Loads a trained fraud model and exposes predict_fraud() for use by the
decision API.

Threshold logic (from PRD)
--------------------------
  fraud_probability < 0.30  → "continue"       (proceed to credit risk)
  0.30 ≤ fraud_probability ≤ 0.60 → "manual_review"
  fraud_probability > 0.60  → "reject"

Usage
-----
    python models/fraud_detection/predict.py --model models/fraud_detection/fraud_model_v1.pkl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Union

import joblib
import pandas as pd

# Project root on path
sys.path.insert(0, str(Path(__file__).parents[2]))
from feature_pipeline.features import FeaturePipelineConfig, compute_features  # noqa: E402

MODEL_VERSION = "v1"
_FEATURE_CONFIG = FeaturePipelineConfig()
FEATURE_COLS = _FEATURE_CONFIG.feature_list

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
THRESHOLD_REJECT = 0.60
THRESHOLD_REVIEW = 0.30


def _apply_threshold(prob: float) -> str:
    """Map a fraud probability to a decision label."""
    if prob > THRESHOLD_REJECT:
        return "reject"
    if prob >= THRESHOLD_REVIEW:
        return "manual_review"
    return "continue"


def predict_fraud(
    features_df: pd.DataFrame,
    model_path: Union[str, Path, None] = None,
    _model=None,  # injected in tests to avoid I/O
) -> pd.DataFrame:
    """Run fraud inference on a features DataFrame.

    Parameters
    ----------
    features_df:
        DataFrame already passed through
        ``feature_pipeline.features.compute_features()``.
        Must contain all columns in ``FEATURE_COLS``.
    model_path:
        Path to a joblib-serialised GradientBoostingClassifier.
        Defaults to ``models/fraud_detection/fraud_model_v1.pkl``
        relative to the project root.
    _model:
        Pre-loaded model object (used in unit tests to skip disk I/O).

    Returns
    -------
    pd.DataFrame
        Original index preserved, with two new columns:
        - ``fraud_probability`` (float 0–1)
        - ``fraud_flag``  (str: "continue" | "manual_review" | "reject")
    """
    if _model is None:
        if model_path is None:
            model_path = Path(__file__).parents[2] / "models" / "fraud_detection" / "fraud_model_v1.pkl"
        model = joblib.load(model_path)
    else:
        model = _model

    X = features_df[FEATURE_COLS].values
    probabilities = model.predict_proba(X)[:, 1]

    result = features_df.copy()
    result["fraud_probability"] = probabilities
    result["fraud_flag"] = [_apply_threshold(p) for p in probabilities]
    return result[["fraud_probability", "fraud_flag"]]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run fraud detection inference")
    parser.add_argument(
        "--model",
        type=str,
        default=str(Path(__file__).parent / "fraud_model_v1.pkl"),
        help="Path to the serialised fraud detection model",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(Path(__file__).parents[2] / "data" / "raw" / "loan_applications_test.parquet"),
        help="Path to a Parquet file of raw loan applications",
    )
    args = parser.parse_args()

    df_raw = pd.read_parquet(args.input)
    df_features = compute_features(df_raw, _FEATURE_CONFIG)
    df_out = predict_fraud(df_features, model_path=args.model)
    print(df_out.head(20).to_string())
    print(f"\nFraud flag distribution:\n{df_out['fraud_flag'].value_counts()}")
