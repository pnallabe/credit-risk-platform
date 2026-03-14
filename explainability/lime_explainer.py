"""
LIME Explainability Module
==========================
Alternative explainer using LIME (Local Interpretable Model-agnostic
Explanations) for cases where tree-specific SHAP explainers are not suitable.

Public API
----------
>>> from explainability.lime_explainer import explain_with_lime
>>> result = explain_with_lime(model, features_row, feature_names)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def explain_with_lime(
    model: Any,
    features_row: Any,
    feature_names: List[str],
    num_features: int = 10,
    num_samples: int = 1000,
    training_data: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Explain a single prediction using LIME.

    Parameters
    ----------
    model:
        A fitted model with a ``predict_proba`` method (scikit-learn API).
    features_row:
        A 1-D array-like (or single-row DataFrame) of feature values for
        the instance to explain.
    feature_names:
        Names of each feature column, in the same order as *features_row*.
    num_features:
        Maximum number of features to include in the explanation.
    num_samples:
        Number of random perturbations LIME generates to fit the local
        surrogate model.  Higher → more stable but slower.
    training_data:
        Optional 2-D array of training data for LIME's neighbourhood
        scaling.  If *None*, a simple zero-mean unit-variance fallback is
        used.

    Returns
    -------
    dict with keys:
        ``feature_contributions``   — list of ``{feature, weight, value}``
        ``prediction_probability``  — probability for the positive class
        ``intercept``               — LIME intercept term
        ``score``                   — local surrogate model R² score
        ``explanation_text``        — human-readable plain English summary
    """
    try:
        import lime  # noqa: PLC0415
        import lime.lime_tabular  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError("lime is required: pip install lime") from exc

    # Normalise input to 1-D numpy array
    if isinstance(features_row, pd.DataFrame):
        row_array = features_row.values.flatten().astype(float)
    else:
        row_array = np.asarray(features_row, dtype=float).flatten()

    if training_data is None:
        # Use a minimal synthetic reference dataset (mean=0, std=1 per feature)
        rng = np.random.RandomState(42)
        training_data = rng.randn(num_samples, len(feature_names))

    # Predict function: LIME requires a function that takes a 2-D array and
    # returns class probabilities shaped (n_samples, n_classes).
    if hasattr(model, "predict_proba"):
        predict_fn = lambda X: model.predict_proba(X)  # noqa: E731
    else:
        def predict_fn(X: np.ndarray) -> np.ndarray:
            preds = model.predict(X).reshape(-1, 1)
            return np.hstack([1 - preds, preds])

    explainer = lime.lime_tabular.LimeTabularExplainer(
        training_data=training_data,
        feature_names=feature_names,
        class_names=["no_default", "default"],
        mode="classification",
        verbose=False,
    )

    explanation = explainer.explain_instance(
        row_array,
        predict_fn,
        num_features=num_features,
        num_samples=num_samples,
        labels=(1,),
    )

    # Prediction probability for positive class
    pred_prob = float(predict_fn(row_array.reshape(1, -1))[0, -1])

    # Feature contributions sorted by absolute weight
    feature_contributions = [
        {
            "feature": feat,
            "weight": round(float(weight), 6),
            "value": float(row_array[feature_names.index(feat)]) if feat in feature_names else None,
        }
        for feat, weight in sorted(explanation.as_list(label=1), key=lambda x: abs(x[1]), reverse=True)
    ]

    # Plain-English summary
    lines = [
        f"LIME explanation (prediction probability = {pred_prob:.4f}):",
    ]
    for item in feature_contributions[:5]:
        sign = "+" if item["weight"] >= 0 else ""
        lines.append(f"  {sign}{item['weight']:.4f}  {item['feature']}")
    explanation_text = "\n".join(lines)

    return {
        "feature_contributions": feature_contributions,
        "prediction_probability": pred_prob,
        "intercept": float(explanation.intercept[1]),
        "score": float(explanation.score),
        "explanation_text": explanation_text,
    }
