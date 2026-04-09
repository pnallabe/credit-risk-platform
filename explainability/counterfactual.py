"""
Counterfactual Explanation Generator
=====================================
Generates the minimum feature perturbation required to flip a REJECT decision
to APPROVE (a "nearest counterfactual") using a greedy single-feature descent.

Public API
----------
>>> from explainability.counterfactual import generate_counterfactual, CounterfactualResult
>>> result = generate_counterfactual(features_df, model, decision_threshold=0.5)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class CounterfactualResult:
    """Output of a counterfactual analysis for a single prediction.

    Attributes
    ----------
    application_id:
        Opaque identifier for the application (pass-through from caller).
    original_decision:
        Decision label under the original features: "APPROVE", "REJECT", or "MANUAL_REVIEW".
    counterfactual_decision:
        Decision label under the proposed feature changes.
    feature_changes:
        List of dicts ``{feature, original_value, suggested_value, delta}`` for modified features.
    feasibility_note:
        Plain-language description of changes required (or why no flip was found).
    generated_at:
        ISO-8601 UTC timestamp.
    """

    application_id: str
    original_decision: str
    counterfactual_decision: str
    feature_changes: List[dict] = field(default_factory=list)
    feasibility_note: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_probability(model: Any, features_df: pd.DataFrame) -> float:
    """Return predicted default probability for the single-row DataFrame."""
    try:
        proba = model.predict_proba(features_df)
        return float(proba[0, 1])
    except AttributeError:
        # Regressors: treat raw prediction as probability
        try:
            pred = model.predict(features_df)
            return float(pred[0])
        except Exception as exc:
            logger.warning("Model predict() failed: %s", exc)
            return 0.0


def _rank_features(
    model: Any,
    features_df: pd.DataFrame,
    max_features: int,
) -> List[str]:
    """Rank features by absolute importance (SHAP → feature_importances_ → alphabetical)."""
    try:
        import shap  # noqa: PLC0415

        model_class = type(model).__name__
        tree_classes = {
            "RandomForestClassifier",
            "RandomForestRegressor",
            "GradientBoostingClassifier",
            "GradientBoostingRegressor",
            "LGBMClassifier",
            "LGBMRegressor",
            "XGBClassifier",
            "XGBRegressor",
            "CatBoostClassifier",
            "CatBoostRegressor",
        }
        if model_class in tree_classes:
            explainer = shap.TreeExplainer(model)
        else:
            explainer = shap.LinearExplainer(model, features_df)

        shap_values = explainer.shap_values(features_df)

        # For classifiers, shap_values may be a list; use class-1 values
        if isinstance(shap_values, list):
            sv = np.array(shap_values[1]).flatten()
        else:
            sv = np.array(shap_values).flatten()

        indices = np.argsort(np.abs(sv))[::-1]
        cols = list(features_df.columns)
        return [cols[i] for i in indices[:max_features]]

    except ImportError:
        logger.warning("shap not installed — falling back to feature_importances_")
    except Exception as exc:
        logger.warning("SHAP ranking failed: %s — falling back", exc)

    # Fallback: model.feature_importances_
    try:
        importances = model.feature_importances_
        cols = list(features_df.columns)
        indices = np.argsort(importances)[::-1]
        return [cols[i] for i in indices[:max_features]]
    except AttributeError:
        pass

    # Last resort: alphabetical
    return sorted(list(features_df.columns))[:max_features]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_counterfactual(
    features_df: pd.DataFrame,
    model: Any,
    decision_threshold: float = 0.5,
    max_features_to_change: int = 3,
    step_pct: float = 0.05,
    max_iterations: int = 200,
    application_id: str = "",
    original_decision: str = "REJECT",
) -> CounterfactualResult:
    """Generate the nearest counterfactual for a REJECT decision.

    Uses a greedy single-feature descent: for each of the top
    *max_features_to_change* features, nudge the value in the direction
    that reduces the predicted probability until it drops below
    *decision_threshold*.

    Parameters
    ----------
    features_df:
        Single-row DataFrame with model input features.
    model:
        Fitted scikit-learn or LightGBM model.
    decision_threshold:
        PD cutoff above which decision == REJECT.
    max_features_to_change:
        Limit perturbations to the top-N most important features.
    step_pct:
        Step size as percentage of each feature's range.
    max_iterations:
        Maximum nudging iterations per feature.
    application_id:
        Pass-through identifier for the result.
    original_decision:
        Original decision label (caller-supplied).

    Returns
    -------
    CounterfactualResult
        Contains the modified features and a feasibility note.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # Guard: nothing to flip if already approved
    try:
        base_prob = _get_probability(model, features_df)
    except Exception as exc:
        logger.error("Error computing base probability: %s", exc)
        return CounterfactualResult(
            application_id=application_id,
            original_decision=original_decision,
            counterfactual_decision=original_decision,
            feature_changes=[],
            feasibility_note=f"Could not compute base probability: {exc}",
            generated_at=now_iso,
        )

    if base_prob < decision_threshold:
        return CounterfactualResult(
            application_id=application_id,
            original_decision=original_decision,
            counterfactual_decision="APPROVE",
            feature_changes=[],
            feasibility_note=(
                "Application is already below the decision threshold. "
                "No changes required for approval."
            ),
            generated_at=now_iso,
        )

    # Rank features by importance
    try:
        ranked_features = _rank_features(model, features_df, max_features_to_change)
    except Exception as exc:
        logger.error("Feature ranking failed: %s", exc)
        ranked_features = sorted(list(features_df.columns))[:max_features_to_change]

    # Work on a mutable copy
    working_df = features_df.copy()
    feature_changes: list[dict] = []

    for feature in ranked_features:
        if feature not in working_df.columns:
            continue

        original_value = float(working_df[feature].iloc[0])
        current_prob = _get_probability(model, working_df)

        if current_prob < decision_threshold:
            break

        # Determine feature range for step calculation
        try:
            feat_min = float(working_df[feature].min())
            feat_max = float(working_df[feature].max())
            feat_range = feat_max - feat_min
            if feat_range == 0:
                feat_range = abs(original_value) * 2 if original_value != 0 else 1.0
        except Exception:
            feat_range = abs(original_value) * 2 if original_value != 0 else 1.0

        step = step_pct * feat_range if feat_range > 0 else step_pct * abs(original_value or 1.0)

        # Determine direction: try decreasing first (lower PD)
        # Try decreasing by step
        test_df = working_df.copy()
        test_df.at[test_df.index[0], feature] = original_value - step
        prob_down = _get_probability(model, test_df)

        # Try increasing by step
        test_df_up = working_df.copy()
        test_df_up.at[test_df_up.index[0], feature] = original_value + step
        prob_up = _get_probability(model, test_df_up)

        # Pick direction that most reduces PD
        if prob_down <= prob_up:
            direction = -1.0
        else:
            direction = 1.0

        # Iterative nudge
        best_value = original_value
        for _ in range(max_iterations):
            new_value = best_value + direction * step
            test_df = working_df.copy()
            test_df.at[test_df.index[0], feature] = new_value
            new_prob = _get_probability(model, test_df)
            best_value = new_value
            working_df.at[working_df.index[0], feature] = new_value

            if new_prob < decision_threshold:
                break

        suggested_value = float(working_df[feature].iloc[0])
        delta = suggested_value - original_value

        if abs(delta) > 1e-10:  # only record actual changes
            feature_changes.append(
                {
                    "feature": feature,
                    "original_value": round(original_value, 6),
                    "suggested_value": round(suggested_value, 6),
                    "delta": round(delta, 6),
                }
            )

    # Evaluate final probability after all perturbations
    final_prob = _get_probability(model, working_df)
    if final_prob < decision_threshold:
        counterfactual_decision = "APPROVE"
        if feature_changes:
            parts = []
            for ch in feature_changes:
                parts.append(
                    f"changing {ch['feature']} from {ch['original_value']:.4f} "
                    f"to {ch['suggested_value']:.4f}"
                )
            feasibility_note = (
                "The following changes would be sufficient to obtain approval under "
                "current policy: " + "; ".join(parts) + "."
            )
        else:
            feasibility_note = "Application meets approval criteria with minimal changes."
    else:
        counterfactual_decision = original_decision
        feasibility_note = (
            f"No feasible counterfactual was found within the search budget "
            f"(max_features={max_features_to_change}, max_iterations={max_iterations}). "
            f"PD after perturbations: {final_prob:.4f} (threshold: {decision_threshold})."
        )
        feature_changes = []  # Don't suggest partial changes if flip failed

    return CounterfactualResult(
        application_id=application_id,
        original_decision=original_decision,
        counterfactual_decision=counterfactual_decision,
        feature_changes=feature_changes,
        feasibility_note=feasibility_note,
        generated_at=now_iso,
    )
