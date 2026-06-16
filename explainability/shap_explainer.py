"""
SHAP Explainability Module
==========================
Computes SHAP (SHapley Additive exPlanations) values for any scikit-learn
or LightGBM model and converts them into human-readable adverse-action
explanation text suitable for FCRA notices.

Public API
----------
>>> from explainability.shap_explainer import explain_prediction, ExplanationResult
>>> result = explain_prediction(model, features_row_df)
>>> print(result.explanation_text)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExplanationResult:
    """Output of an explainability run for a single prediction.

    Attributes
    ----------
    top_positive_factors:
        List of dicts ``{feature, shap_value, direction}`` ordered by
        magnitude (descending), where ``direction == "positive"``.
    top_negative_factors:
        Same but ``direction == "negative"``.
    base_value:
        SHAP expected value / base value for the model.
    predicted_value:
        Model's raw predicted probability for this row.
    explanation_text:
        Human-readable FCRA-style summary (approved/declined + top factors).
    shap_values:
        Full array of SHAP values for every feature (internal use / storage).
    feature_names:
        Names of features in the same order as ``shap_values``.
    """

    top_positive_factors: List[Dict[str, Any]] = field(default_factory=list)
    top_negative_factors: List[Dict[str, Any]] = field(default_factory=list)
    base_value: float = 0.0
    predicted_value: float = 0.0
    explanation_text: str = ""
    shap_values: Optional[np.ndarray] = field(default=None, repr=False)
    feature_names: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_explainer(model: Any, features_df: pd.DataFrame) -> Any:
    """Return the most appropriate SHAP explainer for *model*."""
    try:
        import shap  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError("shap is required: pip install shap") from exc

    model_class = type(model).__name__
    tree_classes = {
        "RandomForestClassifier",
        "RandomForestRegressor",
        "GradientBoostingClassifier",
        "GradientBoostingRegressor",
        "ExtraTreesClassifier",
        "ExtraTreesRegressor",
        "DecisionTreeClassifier",
        "DecisionTreeRegressor",
        "XGBClassifier",
        "XGBRegressor",
        "LGBMClassifier",
        "LGBMRegressor",
        "CatBoostClassifier",
        "CatBoostRegressor",
    }

    if model_class in tree_classes:
        logger.debug("Using SHAP TreeExplainer for %s", model_class)
        return shap.TreeExplainer(model)

    if hasattr(model, "steps"):  # sklearn Pipeline
        last_step = model.steps[-1][1]
        if type(last_step).__name__ in tree_classes:
            return shap.TreeExplainer(model)

    logger.debug("Using SHAP LinearExplainer for %s", model_class)
    try:
        return shap.LinearExplainer(model, features_df)
    except Exception:
        logger.debug("LinearExplainer failed, falling back to KernelExplainer")
        return shap.KernelExplainer(
            model.predict_proba if hasattr(model, "predict_proba") else model.predict,
            shap.sample(features_df, min(50, len(features_df))),
        )


def _build_factor_list(
    shap_values_row: np.ndarray,
    feature_names: List[str],
    direction: str,
    top_n: int = 5,
) -> List[Dict[str, Any]]:
    """Extract top *top_n* factors in *direction* ('positive'/'negative')."""
    assert direction in ("positive", "negative")
    result = []
    for name, val in zip(feature_names, shap_values_row):
        val_float = float(val)
        if direction == "positive" and val_float > 0:
            result.append({"feature": name, "shap_value": round(val_float, 4), "direction": "positive"})
        elif direction == "negative" and val_float < 0:
            result.append({"feature": name, "shap_value": round(val_float, 4), "direction": "negative"})

    result.sort(key=lambda d: abs(d["shap_value"]), reverse=True)
    return result[:top_n]


def _build_explanation_text(
    decision_label: str,
    positive_factors: List[Dict[str, Any]],
    negative_factors: List[Dict[str, Any]],
) -> str:
    """Build FCRA-style plain-English explanation text."""
    lines = [f"Your application was {decision_label.lower()} primarily due to:"]
    for factor in positive_factors[:3]:
        lines.append(f"  (+) {factor['feature'].replace('_', ' ').title()} (+{factor['shap_value']:.4f})")
    for factor in negative_factors[:3]:
        lines.append(f"  (-) {factor['feature'].replace('_', ' ').title()} ({factor['shap_value']:.4f})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def explain_prediction(
    model: Any,
    features_row_df: pd.DataFrame,
    decision_label: str = "reviewed",
    output_path: Optional[Union[str, Path]] = None,
    top_n: int = 5,
) -> ExplanationResult:
    """Compute SHAP values and build an explanation for a single prediction.

    Parameters
    ----------
    model:
        A fitted scikit-learn or LightGBM model with a ``predict_proba``
        method.  Must be one that SHAP supports with TreeExplainer or
        LinearExplainer.
    features_row_df:
        A single-row DataFrame whose columns are the model's feature names.
    decision_label:
        Decision string for the explanation text (e.g. ``"approved"`` or
        ``"declined"``).  Defaults to ``"reviewed"``.
    output_path:
        If provided, a SHAP waterfall plot is saved to this path as a PNG.
    top_n:
        Number of top positive and negative factors to include.

    Returns
    -------
    ExplanationResult
    """
    try:
        import shap  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise ImportError("shap is required: pip install shap") from exc

    feature_names = list(features_row_df.columns)
    explainer = _get_explainer(model, features_row_df)

    # Compute SHAP values
    shap_values_raw = explainer.shap_values(features_row_df)

    # Handle multiple SHAP output formats across library versions:
    # 1. Old SHAP (<0.42): list of [class0, class1] arrays — take class-1
    if isinstance(shap_values_raw, list):
        shap_values_raw = shap_values_raw[-1]

    shap_arr = np.array(shap_values_raw)

    # 2. New SHAP (>=0.42): 3-D array (n_samples, n_features, n_classes) — take class-1
    if shap_arr.ndim == 3:
        shap_arr = shap_arr[:, :, 1]

    # Flatten to 1-D for a single row
    shap_row: np.ndarray = shap_arr.flatten()

    # 3. Guard: some versions concat both classes → 2*n_features; take class-1 (second half)
    n_features = len(feature_names)
    if len(shap_row) == 2 * n_features:
        shap_row = shap_row[n_features:]

    # Base value
    base_value: float = float(
        explainer.expected_value[-1]
        if hasattr(explainer.expected_value, "__len__")
        else explainer.expected_value
    )

    # Predicted probability
    predicted_value: float = 0.0
    if hasattr(model, "predict_proba"):
        predicted_value = float(model.predict_proba(features_row_df)[0, -1])
    elif hasattr(model, "predict"):
        predicted_value = float(model.predict(features_row_df)[0])

    positive_factors = _build_factor_list(shap_row, feature_names, "positive", top_n)
    negative_factors = _build_factor_list(shap_row, feature_names, "negative", top_n)
    explanation_text = _build_explanation_text(decision_label, positive_factors, negative_factors)

    # Optional waterfall plot
    if output_path is not None:
        _save_waterfall_plot(
            explainer,
            shap_row,
            base_value,
            feature_names,
            features_row_df,
            output_path,
        )

    return ExplanationResult(
        top_positive_factors=positive_factors,
        top_negative_factors=negative_factors,
        base_value=base_value,
        predicted_value=predicted_value,
        explanation_text=explanation_text,
        shap_values=shap_row,
        feature_names=feature_names,
    )


def _save_waterfall_plot(
    explainer: Any,
    shap_row: np.ndarray,
    base_value: float,
    feature_names: List[str],
    features_row_df: pd.DataFrame,
    output_path: Union[str, Path],
) -> None:
    """Save a SHAP waterfall plot as a PNG file."""
    try:
        import matplotlib  # noqa: PLC0415

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # noqa: PLC0415
        import shap  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        logger.warning("Could not generate SHAP plot: %s", exc)
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        sv_obj = shap.Explanation(
            values=shap_row,
            base_values=base_value,
            data=features_row_df.values.flatten(),
            feature_names=feature_names,
        )
        fig, ax = plt.subplots(figsize=(10, max(4, len(feature_names) // 2)))
        shap.waterfall_plot(sv_obj, show=False)
        plt.tight_layout()
        plt.savefig(output_path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info("SHAP waterfall plot saved to %s", output_path)
    except Exception as exc:
        logger.warning("Could not save SHAP waterfall: %s", exc)
