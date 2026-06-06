"""
WoE Scorecard Builder
======================
Converts a trained LightGBM model's feature importance + binned data into
a Weight-of-Evidence (WoE) / Information Value (IV) scorecard table.

The scorecard maps each feature bin to an integer point contribution,
suitable for regulatory review and champion/challenger comparison.

Usage (standalone):
    from models.credit_risk.woe_scorecard import build_woe_scorecard
    sc_df = build_woe_scorecard(model, X, y, feat_names)
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# IV thresholds for quality labelling
IV_NEGLIGIBLE = 0.02   # IV < 0.02 → negligible / likely useless
IV_WEAK       = 0.10   # 0.02–0.10 → weak predictor
IV_MEDIUM     = 0.30   # 0.10–0.30 → medium predictor
# IV >= 0.30 → strong predictor

# Laplace smoothing constant for WoE to avoid log(0)
_SMOOTH = 0.5


# ── Core builder ─────────────────────────────────────────────────────────────


def build_woe_scorecard(
    model,
    X: np.ndarray,
    y: np.ndarray,
    feat_names: list[str],
    n_bins: int = 10,
    pdo: int = 20,
    base_score: int = 600,
    base_odds: float = 50.0,
) -> pd.DataFrame:
    """Compute WoE / IV scorecard and scale to integer points.

    Parameters
    ----------
    model:
        Trained LightGBM classifier (or CalibratedClassifierCV wrapping one).
    X:
        Feature matrix aligned to ``feat_names`` (float32, shape N×M).
    y:
        Binary target array (0=good, 1=bad/default).
    feat_names:
        Ordered list of feature names matching X columns.
    n_bins:
        Number of equal-frequency bins per numeric feature.
    pdo:
        Points-to-Double-Odds.  Common values: 20 (retail), 15 (commercial).
    base_score:
        Score assigned when odds equal ``base_odds``.
    base_odds:
        Good : Bad odds at ``base_score`` (e.g. 50 means 50 goods per 1 bad).

    Returns
    -------
    pd.DataFrame with columns:
        feature, bin_label, bin_lower, bin_upper,
        count, event_count, nonevent_count, event_rate,
        woe, iv, points, low_iv
    """
    total_events     = int(y.sum())
    total_nonevents  = int(len(y) - total_events)

    if total_events == 0 or total_nonevents == 0:
        raise ValueError("y must contain both classes to compute WoE.")

    # Scaling factors
    factor = pdo / math.log(2)
    offset = base_score - factor * math.log(base_odds)

    # Normalised gain importance (sum to 1)
    raw_imp = _get_feature_importance(model, feat_names)
    imp_sum = max(raw_imp.sum(), 1e-9)
    norm_imp = raw_imp / imp_sum

    rows: list[dict[str, Any]] = []

    for i, feat in enumerate(feat_names):
        col_vals = X[:, i].astype(float)
        coef_i   = float(norm_imp[i])

        # Skip constant features
        if np.nanstd(col_vals) < 1e-9:
            log.debug("Feature %s has near-zero variance — skipping WoE.", feat)
            continue

        try:
            bins = _equal_freq_bins(col_vals, n_bins)
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not bin feature %s: %s — skipping.", feat, exc)
            continue

        feat_iv = 0.0
        for bin_lower, bin_upper, mask in bins:
            cnt       = int(mask.sum())
            evt_cnt   = int(y[mask].sum())
            nonevt_cnt = cnt - evt_cnt

            # Laplace smoothing
            evt_rate   = (evt_cnt   + _SMOOTH) / (total_events   + _SMOOTH)
            nonevt_rate= (nonevt_cnt+ _SMOOTH) / (total_nonevents+ _SMOOTH)

            woe  = math.log(nonevt_rate / evt_rate)
            iv_i = (nonevt_rate - evt_rate) * woe
            feat_iv += iv_i

            # Scale to integer points
            points = round(-(woe * coef_i * factor))

            rows.append({
                "feature"      : feat,
                "bin_label"    : f"[{bin_lower:.4g}, {bin_upper:.4g})",
                "bin_lower"    : bin_lower,
                "bin_upper"    : bin_upper,
                "count"        : cnt,
                "event_count"  : evt_cnt,
                "nonevent_count": nonevt_cnt,
                "event_rate"   : evt_cnt / max(cnt, 1),
                "woe"          : round(woe, 6),
                "iv"           : round(iv_i, 6),
                "points"       : int(points),
                "feature_iv"   : round(feat_iv, 6),
                "low_iv"       : False,  # updated below after totalling
            })

        # Back-fill feature_iv and low_iv for all bins of this feature
        feat_iv_rounded = round(feat_iv, 6)
        for row in rows:
            if row["feature"] == feat:
                row["feature_iv"] = feat_iv_rounded
                row["low_iv"]     = feat_iv_rounded < IV_NEGLIGIBLE

    if not rows:
        return pd.DataFrame(columns=[
            "feature", "bin_label", "bin_lower", "bin_upper",
            "count", "event_count", "nonevent_count", "event_rate",
            "woe", "iv", "points", "feature_iv", "low_iv",
        ])

    df = pd.DataFrame(rows)

    # Add IV quality label
    def _iv_label(iv: float) -> str:
        if iv < IV_NEGLIGIBLE: return "Negligible"
        if iv < IV_WEAK:       return "Weak"
        if iv < IV_MEDIUM:     return "Medium"
        return "Strong"

    df["iv_label"] = df["feature_iv"].apply(_iv_label)

    # Sort: features by IV desc, then bins ascending within each feature
    feat_order = (
        df.groupby("feature")["feature_iv"]
          .first()
          .sort_values(ascending=False)
          .index.tolist()
    )
    df["_feat_rank"] = df["feature"].map({f: i for i, f in enumerate(feat_order)})
    df = df.sort_values(["_feat_rank", "bin_lower"]).drop(columns=["_feat_rank"])
    df = df.reset_index(drop=True)

    return df


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_feature_importance(model, feat_names: list[str]) -> np.ndarray:
    """Extract feature importance (gain) from model, aligned to feat_names."""
    # CalibratedClassifierCV wraps a base estimator
    base = getattr(model, "estimator", None) or getattr(model, "base_estimator", None)
    if base is None:
        # Try calibrated classifiers list (sklearn >= 1.0)
        calibrated_list = getattr(model, "calibrated_classifiers_", None)
        if calibrated_list:
            base = getattr(calibrated_list[0], "estimator", None)

    target = base if base is not None else model

    if hasattr(target, "feature_importances_"):
        imp = target.feature_importances_.astype(float)
        if len(imp) == len(feat_names):
            return imp

    # Fallback: uniform importance
    log.warning("Could not extract feature importances — using uniform weights.")
    return np.ones(len(feat_names), dtype=float)


def _equal_freq_bins(
    col: np.ndarray, n_bins: int
) -> list[tuple[float, float, np.ndarray]]:
    """Return list of (lower, upper, bool_mask) for equal-frequency bins."""
    finite = col[np.isfinite(col)]
    if len(finite) == 0:
        return []

    # pd.qcut to get quantile-based edges
    try:
        _, edges = pd.qcut(finite, q=n_bins, retbins=True, duplicates="drop")
    except ValueError:
        # Fewer than n_bins unique values — use unique values as edges
        edges = np.unique(finite)

    edges = np.unique(edges)
    if len(edges) < 2:
        return []

    bins: list[tuple[float, float, np.ndarray]] = []
    for j in range(len(edges) - 1):
        lo = float(edges[j])
        hi = float(edges[j + 1])
        if j == 0:
            mask = (col >= lo) & (col <= hi)
        else:
            mask = (col > lo) & (col <= hi)
        # Include NaN in last bin
        if j == len(edges) - 2:
            mask = mask | ~np.isfinite(col)
        bins.append((lo, hi, mask))

    return bins


# ── Persistence helpers ────────────────────────────────────────────────────────


def save_woe_scorecard(
    df: pd.DataFrame,
    base_path: Path,
    log_to_mlflow: bool = True,
    mlflow_artifact_name: str = "woe_scorecard",
) -> Path:
    """Serialize WoE scorecard to JSON and optionally log to MLflow."""
    out_path = Path(str(base_path).replace(".json", "_woe.json"))
    out_path.write_text(
        df.to_json(orient="records", indent=2, default_handler=str),
        encoding="utf-8",
    )
    log.info("WoE scorecard written → %s", out_path)

    if log_to_mlflow:
        try:
            import mlflow
            mlflow.log_artifact(str(out_path), artifact_path=mlflow_artifact_name)
            log.info("WoE scorecard logged to MLflow artifact '%s'", mlflow_artifact_name)
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow WoE artifact log failed (non-fatal): %s", exc)

    return out_path


def load_woe_scorecard(path: Path) -> pd.DataFrame:
    """Load a saved WoE scorecard JSON into a DataFrame."""
    return pd.read_json(path, orient="records")


def scorecard_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Return a summary dict of feature IV statistics."""
    if df.empty:
        return {}
    feat_iv = df.groupby("feature")["feature_iv"].first()
    return {
        "n_features"    : len(feat_iv),
        "n_strong"      : int((feat_iv >= IV_MEDIUM).sum()),
        "n_medium"      : int(((feat_iv >= IV_WEAK) & (feat_iv < IV_MEDIUM)).sum()),
        "n_weak"        : int(((feat_iv >= IV_NEGLIGIBLE) & (feat_iv < IV_WEAK)).sum()),
        "n_negligible"  : int((feat_iv < IV_NEGLIGIBLE).sum()),
        "top_5_features": feat_iv.sort_values(ascending=False).head(5).to_dict(),
        "total_iv"      : float(feat_iv.sum()),
    }
