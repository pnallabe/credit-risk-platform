"""
LGD Model — Inference Module
==============================
Loads the trained LGD regressor and exposes predict_lgd() for use by
the RiskModelingAgent and ECL engine.

LGD bands:
  lgd_score < 0.20  → "Low"
  lgd_score < 0.45  → "Medium"
  lgd_score < 0.70  → "High"
  lgd_score >= 0.70 → "Severe"
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MODEL_DIR  = Path(__file__).parent
MODEL_PATH = MODEL_DIR / "lgd_model_v1.pkl"

# Band thresholds
_BAND_LOW    = 0.20
_BAND_MEDIUM = 0.45
_BAND_HIGH   = 0.70

# Default LGD when model is unavailable (Basel-floor-inspired conservative estimate)
DEFAULT_LGD = 0.40

_CACHED_ARTEFACT: dict | None = None


def _load_artefact(model_path: Union[str, Path, None] = None) -> dict | None:
    global _CACHED_ARTEFACT
    if _CACHED_ARTEFACT is not None:
        return _CACHED_ARTEFACT
    path = Path(model_path) if model_path else MODEL_PATH
    if not path.exists():
        log.warning("LGD model artefact not found at %s — using default LGD %.2f", path, DEFAULT_LGD)
        return None
    try:
        import joblib
        _CACHED_ARTEFACT = joblib.load(path)
        log.info("LGD model loaded from %s", path)
        return _CACHED_ARTEFACT
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to load LGD model: %s — using default", exc)
        return None


def _lgd_band(score: float) -> str:
    if score < _BAND_LOW:    return "Low"
    if score < _BAND_MEDIUM: return "Medium"
    if score < _BAND_HIGH:   return "High"
    return "Severe"


def predict_lgd(
    feature_df: pd.DataFrame,
    model_path: Union[str, Path, None] = None,
) -> pd.DataFrame:
    """Predict LGD for each row in feature_df.

    Parameters
    ----------
    feature_df:
        DataFrame with any subset of the LGD feature columns.
        Missing columns are filled with sensible defaults (0.0 / median).
    model_path:
        Optional override for the model artefact path.

    Returns
    -------
    pd.DataFrame with columns:
        lgd_score (float 0–1), lgd_band (str)
    """
    from models.lgd.train_lgd_model import FEATURES, DEFAULT_LGD

    artefact = _load_artefact(model_path)

    if artefact is None:
        # Model unavailable — return conservative default for all rows
        n = len(feature_df)
        return pd.DataFrame({
            "lgd_score": np.full(n, DEFAULT_LGD),
            "lgd_band" : [_lgd_band(DEFAULT_LGD)] * n,
        }, index=feature_df.index)

    model = artefact["model"]
    feat_names: list[str] = artefact.get("feature_names", FEATURES)

    # Align feature_df to expected feature columns (fill missing with 0)
    aligned = feature_df.reindex(columns=feat_names, fill_value=0.0).astype(np.float32)

    try:
        scores = model.predict(aligned.values)
        scores = np.clip(scores, 0.0, 1.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("LGD model inference error: %s — using default", exc)
        n = len(feature_df)
        scores = np.full(n, DEFAULT_LGD)

    return pd.DataFrame({
        "lgd_score": scores.astype(float),
        "lgd_band" : [_lgd_band(float(s)) for s in scores],
    }, index=feature_df.index)


def predict_lgd_single(features: dict, model_path: Union[str, Path, None] = None) -> tuple[float, str]:
    """Convenience wrapper for scoring a single applicant feature dict.

    Returns (lgd_score, lgd_band).
    """
    df = pd.DataFrame([features])
    result = predict_lgd(df, model_path=model_path)
    score = float(result.iloc[0]["lgd_score"])
    band  = str(result.iloc[0]["lgd_band"])
    return score, band
