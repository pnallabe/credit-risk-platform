"""
Model Drift Monitor
===================
Compares a reference feature distribution (training data) against a production
batch using Population Stability Index (PSI) and Kolmogorov-Smirnov test.

PSI Thresholds
--------------
  PSI < 0.10   → stable    (green)
  0.10–0.25    → minor     (amber)
  > 0.25       → major     (red / alert)

Public API
----------
>>> from monitoring.drift_monitor import monitor_drift, DriftReport
>>> report = monitor_drift(reference_df, production_df, feature_list)
>>> print(report.overall_drift_status)
"""

from __future__ import annotations

import json
import logging
import warnings
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PSI thresholds
# ---------------------------------------------------------------------------

PSI_STABLE_THRESHOLD = 0.10
PSI_MINOR_THRESHOLD = 0.25

STATUS_STABLE = "stable"
STATUS_MINOR = "minor"
STATUS_MAJOR = "major"

DEFAULT_N_BINS = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class FeatureDriftResult:
    """Drift metrics for a single feature.

    Attributes
    ----------
    feature_name: str
    psi: float — Population Stability Index
    ks_statistic: float — KS test statistic
    ks_p_value: float — KS test p-value
    drift_status: str — one of 'stable', 'minor', 'major'
    reference_mean: float
    production_mean: float
    reference_std: float
    production_std: float
    """

    feature_name: str
    psi: float
    ks_statistic: float
    ks_p_value: float
    drift_status: str
    reference_mean: float
    production_mean: float
    reference_std: float
    production_std: float


@dataclass
class DriftReport:
    """Complete drift analysis report.

    Attributes
    ----------
    feature_results:   Per-feature drift metrics.
    overall_drift_status: Worst status across all features.
    features_with_major_drift: Names of features with PSI > 0.25.
    features_with_minor_drift: Names of features with 0.10 < PSI ≤ 0.25.
    report_timestamp: ISO timestamp of when the report was generated.
    n_reference_rows: Number of rows in the reference dataset.
    n_production_rows: Number of rows in the production dataset.
    """

    feature_results: List[FeatureDriftResult] = field(default_factory=list)
    overall_drift_status: str = STATUS_STABLE
    features_with_major_drift: List[str] = field(default_factory=list)
    features_with_minor_drift: List[str] = field(default_factory=list)
    report_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    n_reference_rows: int = 0
    n_production_rows: int = 0


# ---------------------------------------------------------------------------
# PSI implementation
# ---------------------------------------------------------------------------


def _compute_psi(
    reference: np.ndarray,
    production: np.ndarray,
    n_bins: int = DEFAULT_N_BINS,
    eps: float = 1e-6,
) -> float:
    """Compute the Population Stability Index between two distributions.

    Parameters
    ----------
    reference:
        1-D array of values from the reference (training) dataset.
    production:
        1-D array of values from the production dataset.
    n_bins:
        Number of bins used for the PSI histogram.
    eps:
        Small constant added to bin proportions to avoid log(0).

    Returns
    -------
    float — PSI value ≥ 0.
    """
    # Use reference quantiles as bin edges for consistent binning
    breakpoints = np.nanpercentile(reference, np.linspace(0, 100, n_bins + 1))
    # Remove duplicate edges (can happen with highly skewed data)
    breakpoints = np.unique(breakpoints)
    if len(breakpoints) < 2:
        return 0.0

    ref_counts, _ = np.histogram(reference, bins=breakpoints)
    prod_counts, _ = np.histogram(production, bins=breakpoints)

    ref_pct = ref_counts / (ref_counts.sum() + eps)
    prod_pct = prod_counts / (prod_counts.sum() + eps)

    # Clip to avoid zero fractions
    ref_pct = np.clip(ref_pct, eps, None)
    prod_pct = np.clip(prod_pct, eps, None)

    psi = float(np.sum((prod_pct - ref_pct) * np.log(prod_pct / ref_pct)))
    return round(psi, 6)


def _psi_status(psi: float) -> str:
    if psi < PSI_STABLE_THRESHOLD:
        return STATUS_STABLE
    if psi < PSI_MINOR_THRESHOLD:
        return STATUS_MINOR
    return STATUS_MAJOR


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def monitor_drift(
    reference_df: pd.DataFrame,
    production_df: pd.DataFrame,
    feature_list: List[str],
    n_bins: int = DEFAULT_N_BINS,
    output_dir: Optional[str] = None,
) -> DriftReport:
    """Compute per-feature PSI and KS drift statistics.

    Parameters
    ----------
    reference_df:
        DataFrame of training / baseline data (ground truth distribution).
    production_df:
        DataFrame of recent production data to compare against.
    feature_list:
        Column names to analyse.  Columns not present in either DataFrame
        are silently skipped with a warning.
    n_bins:
        Number of equi-quantile bins for PSI calculation.
    output_dir:
        If provided, saves the DriftReport as JSON to
        ``{output_dir}/drift_report_{timestamp}.json``.

    Returns
    -------
    DriftReport
    """
    available = [
        f for f in feature_list
        if f in reference_df.columns and f in production_df.columns
    ]
    skipped = set(feature_list) - set(available)
    if skipped:
        logger.warning("Skipping missing features for drift analysis: %s", skipped)

    report = DriftReport(
        n_reference_rows=len(reference_df),
        n_production_rows=len(production_df),
    )

    for feature in available:
        ref_vals = reference_df[feature].dropna().values.astype(float)
        prod_vals = production_df[feature].dropna().values.astype(float)

        if len(ref_vals) < 2 or len(prod_vals) < 2:
            logger.warning("Not enough data to compute drift for: %s", feature)
            continue

        psi = _compute_psi(ref_vals, prod_vals, n_bins=n_bins)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ks_stat, ks_p = ks_2samp(ref_vals, prod_vals)

        status = _psi_status(psi)

        result = FeatureDriftResult(
            feature_name=feature,
            psi=psi,
            ks_statistic=round(float(ks_stat), 6),
            ks_p_value=round(float(ks_p), 6),
            drift_status=status,
            reference_mean=round(float(np.nanmean(ref_vals)), 6),
            production_mean=round(float(np.nanmean(prod_vals)), 6),
            reference_std=round(float(np.nanstd(ref_vals)), 6),
            production_std=round(float(np.nanstd(prod_vals)), 6),
        )
        report.feature_results.append(result)

        if status == STATUS_MAJOR:
            report.features_with_major_drift.append(feature)
        elif status == STATUS_MINOR:
            report.features_with_minor_drift.append(feature)

    # Determine overall status
    if report.features_with_major_drift:
        report.overall_drift_status = STATUS_MAJOR
    elif report.features_with_minor_drift:
        report.overall_drift_status = STATUS_MINOR
    else:
        report.overall_drift_status = STATUS_STABLE

    logger.info(
        "Drift analysis complete: %s features, overall=%s, major=%s, minor=%s",
        len(report.feature_results),
        report.overall_drift_status,
        report.features_with_major_drift,
        report.features_with_minor_drift,
    )

    if output_dir:
        _save_report(report, output_dir)

    return report


def _save_report(report: DriftReport, output_dir: str) -> Path:
    """Serialise ``report`` as JSON and write to *output_dir*."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = out / f"drift_report_{ts}.json"
    data = asdict(report)
    path.write_text(json.dumps(data, indent=2))
    logger.info("Drift report saved to %s", path)
    return path
