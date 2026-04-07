"""Automated model validation suite (MVR).

Produces a signed Model Validation Report (MVR) suitable for evidentiary audit.

Notes
-----
- This suite is intentionally self-contained and uses only existing dependencies
  (sklearn, pandas, mlflow).
- The report signature is deterministic over report content (excluding timestamps
  and random identifiers) so the report cannot be silently altered after signing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import brier_score_loss, roc_auc_score, roc_curve

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValidationConfig:
    model_registry_name: str
    model_version: str
    mlflow_run_id: str
    holdout_data_path: Path
    feature_cols: List[str]
    target_col: str
    auc_floor: float = 0.75
    gini_floor: float = 0.50
    ks_floor: float = 0.30
    brier_ceiling: float = 0.15
    calibration_slope_range: Tuple[float, float] = (0.90, 1.10)
    dir_floor: float = 0.80
    demographic_col: str | None = None


@dataclass(frozen=True)
class ModelValidationReport:
    report_id: str
    generated_at: datetime
    model_version: str
    mlflow_run_id: str
    model_artifact_sha256: str
    holdout_size: int
    holdout_default_rate: float
    auc: float
    gini: float
    ks: float
    brier_score: float
    calibration_slope: float
    calibration_intercept: float
    dir_result: float | None
    monotonicity_check_passed: bool
    all_gates_passed: bool
    gate_failures: List[str]
    report_signature: str


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_path(path: Path) -> str:
    if path.is_file():
        return _sha256_bytes(path.read_bytes())

    # Directory: hash file paths + contents in a deterministic order.
    h = hashlib.sha256()
    for p in sorted([x for x in path.rglob("*") if x.is_file()], key=lambda x: str(x)):
        rel = str(p.relative_to(path)).encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _load_holdout(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _load_model_from_mlflow(
    model_registry_name: str,
    model_version: str,
    mlflow_tracking_uri: str,
) -> tuple[Any, str]:
    """Best-effort MLflow model loader.

    Returns (model, artifact_sha256). Model must support predict_proba.

    This function is structured to be monkeypatched in tests.
    """

    import mlflow
    from mlflow.tracking import MlflowClient

    mlflow.set_tracking_uri(mlflow_tracking_uri)
    client = MlflowClient(tracking_uri=mlflow_tracking_uri)

    mv = client.get_model_version(model_registry_name, str(model_version))
    if not mv.source:
        raise RuntimeError("MLflow model version has no source URI")

    local_path_str = mlflow.artifacts.download_artifacts(mv.source)
    local_path = Path(local_path_str)

    # Try to locate a pickle artifact.
    artifact_path = local_path
    if local_path.is_dir():
        pkl_files = list(local_path.rglob("*.pkl"))
        if not pkl_files:
            raise RuntimeError(f"No .pkl artifact found under {local_path}")
        artifact_path = pkl_files[0]

    artifact_sha = _sha256_path(artifact_path)

    import joblib

    loaded = joblib.load(artifact_path)
    model = loaded.get("model") if isinstance(loaded, dict) and "model" in loaded else loaded

    if not hasattr(model, "predict_proba"):
        raise RuntimeError("Loaded model does not support predict_proba")

    return model, artifact_sha


def _compute_ks(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    return float(np.max(tpr - fpr))


def _compute_calibration(y_true: np.ndarray, y_prob: np.ndarray) -> tuple[float, float]:
    lr = LinearRegression()
    lr.fit(y_prob.reshape(-1, 1), y_true.astype(float))
    return float(lr.coef_[0]), float(lr.intercept_)


def _compute_report_signature(content: dict) -> str:
    """Deterministic sha256 over report content.

    Excludes timestamps and random identifiers; depends on metrics + artifact hash.
    """

    canonical = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_validation_suite(config: ValidationConfig, mlflow_tracking_uri: str) -> ModelValidationReport:
    holdout = _load_holdout(Path(config.holdout_data_path))

    missing = set(config.feature_cols + [config.target_col]) - set(holdout.columns)
    if missing:
        raise ValueError(f"Holdout data missing columns: {sorted(missing)}")

    X = holdout[config.feature_cols]
    y_true = holdout[config.target_col].astype(int).to_numpy()

    model, artifact_sha = _load_model_from_mlflow(
        model_registry_name=config.model_registry_name,
        model_version=str(config.model_version),
        mlflow_tracking_uri=mlflow_tracking_uri,
    )

    y_prob = model.predict_proba(X.to_numpy(dtype=float))[:, 1]
    y_prob = np.clip(y_prob.astype(float), 0.0, 1.0)

    auc = float(roc_auc_score(y_true, y_prob))
    gini = float(2.0 * auc - 1.0)
    ks = float(_compute_ks(y_true, y_prob))
    brier = float(brier_score_loss(y_true, y_prob))
    cal_slope, cal_intercept = _compute_calibration(y_true, y_prob)

    dir_result: float | None = None
    if config.demographic_col:
        try:
            decisions_df = holdout[[config.demographic_col]].copy()
            # Approval is a low PD; this is a validation proxy only.
            decisions_df["decision"] = np.where(y_prob < 0.5, "APPROVE", "REJECT")
            control_group = str(decisions_df[config.demographic_col].mode().iloc[0])
            from monitoring.fair_lending import analyze_fair_lending

            fl = analyze_fair_lending(
                decisions_df,
                protected_col=str(config.demographic_col),
                control_group=control_group,
                decision_col="decision",
            )
            dir_result = None if fl.dir_score is None else float(fl.dir_score)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DIR computation failed (suppressed): %s", exc)
            dir_result = None

    monotonicity_ok = True
    try:
        from models.credit_risk.train_cc_pd_model import verify_monotonicity

        verify_monotonicity(model, X.to_numpy(dtype=np.float32), config.feature_cols)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Monotonicity check failed: %s", exc)
        monotonicity_ok = False

    gate_failures: List[str] = []
    if auc < float(config.auc_floor):
        gate_failures.append(f"AUC below floor: {auc:.2f} < {float(config.auc_floor):.2f}")
    if gini < float(config.gini_floor):
        gate_failures.append(f"Gini below floor: {gini:.2f} < {float(config.gini_floor):.2f}")
    if ks < float(config.ks_floor):
        gate_failures.append(f"KS below floor: {ks:.2f} < {float(config.ks_floor):.2f}")
    if brier > float(config.brier_ceiling):
        gate_failures.append(f"Brier above ceiling: {brier:.2f} > {float(config.brier_ceiling):.2f}")

    slope_lo, slope_hi = config.calibration_slope_range
    if not (float(slope_lo) <= float(cal_slope) <= float(slope_hi)):
        gate_failures.append(
            f"calibration_slope outside range: {cal_slope:.2f} not in [{float(slope_lo):.2f},{float(slope_hi):.2f}]"
        )

    if config.demographic_col and dir_result is not None and dir_result < float(config.dir_floor):
        gate_failures.append(f"DIR below floor: {dir_result:.2f} < {float(config.dir_floor):.2f}")

    if not monotonicity_ok:
        gate_failures.append("monotonicity_check_failed")

    all_gates_passed = len(gate_failures) == 0

    report_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc)

    signature_content = {
        "model_version": str(config.model_version),
        "mlflow_run_id": str(config.mlflow_run_id),
        "model_artifact_sha256": artifact_sha,
        "holdout_size": int(len(y_true)),
        "holdout_default_rate": float(np.mean(y_true)) if len(y_true) else 0.0,
        "auc": auc,
        "gini": gini,
        "ks": ks,
        "brier_score": brier,
        "calibration_slope": cal_slope,
        "calibration_intercept": cal_intercept,
        "dir_result": dir_result,
        "monotonicity_check_passed": bool(monotonicity_ok),
        "all_gates_passed": bool(all_gates_passed),
        "gate_failures": list(gate_failures),
    }

    signature = _compute_report_signature(signature_content)

    return ModelValidationReport(
        report_id=report_id,
        generated_at=generated_at,
        model_version=str(config.model_version),
        mlflow_run_id=str(config.mlflow_run_id),
        model_artifact_sha256=str(artifact_sha),
        holdout_size=int(len(y_true)),
        holdout_default_rate=float(np.mean(y_true)) if len(y_true) else 0.0,
        auc=float(auc),
        gini=float(gini),
        ks=float(ks),
        brier_score=float(brier),
        calibration_slope=float(cal_slope),
        calibration_intercept=float(cal_intercept),
        dir_result=dir_result,
        monotonicity_check_passed=bool(monotonicity_ok),
        all_gates_passed=bool(all_gates_passed),
        gate_failures=gate_failures,
        report_signature=str(signature),
    )


def save_validation_report(
    report: ModelValidationReport,
    output_dir: Path,
    commit_to_mlflow: bool = True,
    mlflow_tracking_uri: str | None = None,
    model_registry_name: str | None = None,
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"mvr_{report.model_version}_{report.report_id[:8]}.json"

    payload = asdict(report)
    payload["generated_at"] = report.generated_at.isoformat()

    # Atomic write
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(output_dir), prefix=".mvr_tmp_", suffix=".json") as tmp:
        tmp.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
        tmp_path = Path(tmp.name)

    tmp_path.replace(out_path)

    if commit_to_mlflow:
        if not mlflow_tracking_uri:
            raise ValueError("mlflow_tracking_uri is required when commit_to_mlflow=True")
        if not model_registry_name:
            raise ValueError("model_registry_name is required when commit_to_mlflow=True")

        from mlflow.tracking import MlflowClient
        import mlflow

        mlflow.set_tracking_uri(mlflow_tracking_uri)
        client = MlflowClient(tracking_uri=mlflow_tracking_uri)
        client.set_model_version_tag(model_registry_name, str(report.model_version), "mvr_report_path", str(out_path))
        client.set_model_version_tag(
            model_registry_name,
            str(report.model_version),
            "mvr_all_gates_passed",
            str(bool(report.all_gates_passed)).lower(),
        )

    return out_path


__all__ = [
    "ValidationConfig",
    "ModelValidationReport",
    "run_validation_suite",
    "save_validation_report",
]
