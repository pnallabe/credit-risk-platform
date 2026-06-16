from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from validation.automated_suite import ValidationConfig, run_validation_suite


class _PerfectModel:
    def predict_proba(self, X):  # noqa: ANN001
        # X is an ndarray with a single feature x in {0,1}
        x = np.asarray(X)[:, 0].astype(float)
        p = np.clip(x, 0.0, 1.0)
        return np.stack([1.0 - p, p], axis=1)


class _ConstantModel:
    def __init__(self, p: float = 0.5) -> None:
        self._p = float(p)

    def predict_proba(self, X):  # noqa: ANN001
        n = len(X)
        p = np.full(n, self._p, dtype=float)
        return np.stack([1.0 - p, p], axis=1)


def test_perfect_model_passes_all_gates(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"x": [0, 1] * 50, "default_flag": [0, 1] * 50})
    holdout = tmp_path / "holdout.parquet"
    df.to_parquet(holdout)

    def fake_loader(*args, **kwargs):  # noqa: ANN001
        return _PerfectModel(), "artifact_sha"

    monkeypatch.setattr("validation.automated_suite._load_model_from_mlflow", fake_loader)

    cfg = ValidationConfig(
        model_registry_name="cc_pd_model",
        model_version="1",
        mlflow_run_id="run",
        holdout_data_path=holdout,
        feature_cols=["x"],
        target_col="default_flag",
    )

    report = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")
    assert report.all_gates_passed is True
    assert report.gate_failures == []


def test_low_auc_fails_gate(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"x": [0, 1] * 50, "default_flag": [0, 1] * 50})
    holdout = tmp_path / "holdout.parquet"
    df.to_parquet(holdout)

    def fake_loader(*args, **kwargs):  # noqa: ANN001
        return _ConstantModel(0.5), "artifact_sha"

    monkeypatch.setattr("validation.automated_suite._load_model_from_mlflow", fake_loader)

    cfg = ValidationConfig(
        model_registry_name="cc_pd_model",
        model_version="1",
        mlflow_run_id="run",
        holdout_data_path=holdout,
        feature_cols=["x"],
        target_col="default_flag",
        auc_floor=0.75,
    )

    report = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")
    assert report.all_gates_passed is False
    assert any("AUC below floor" in s for s in report.gate_failures)


def test_report_signature_is_deterministic(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"x": [0, 1] * 50, "default_flag": [0, 1] * 50})
    holdout = tmp_path / "holdout.parquet"
    df.to_parquet(holdout)

    def fake_loader(*args, **kwargs):  # noqa: ANN001
        return _PerfectModel(), "artifact_sha"

    monkeypatch.setattr("validation.automated_suite._load_model_from_mlflow", fake_loader)

    cfg = ValidationConfig(
        model_registry_name="cc_pd_model",
        model_version="1",
        mlflow_run_id="run",
        holdout_data_path=holdout,
        feature_cols=["x"],
        target_col="default_flag",
    )

    r1 = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")
    r2 = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")
    assert r1.report_signature == r2.report_signature


def test_signature_changes_on_different_artifact_hash(tmp_path, monkeypatch) -> None:
    df = pd.DataFrame({"x": [0, 1] * 50, "default_flag": [0, 1] * 50})
    holdout = tmp_path / "holdout.parquet"
    df.to_parquet(holdout)

    def loader_a(*args, **kwargs):  # noqa: ANN001
        return _PerfectModel(), "artifact_sha_a"

    def loader_b(*args, **kwargs):  # noqa: ANN001
        return _PerfectModel(), "artifact_sha_b"

    cfg = ValidationConfig(
        model_registry_name="cc_pd_model",
        model_version="1",
        mlflow_run_id="run",
        holdout_data_path=holdout,
        feature_cols=["x"],
        target_col="default_flag",
    )

    monkeypatch.setattr("validation.automated_suite._load_model_from_mlflow", loader_a)
    r1 = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")

    monkeypatch.setattr("validation.automated_suite._load_model_from_mlflow", loader_b)
    r2 = run_validation_suite(cfg, mlflow_tracking_uri="sqlite:///ignored")

    assert r1.report_signature != r2.report_signature


def test_promotion_blocked_without_mvr(monkeypatch) -> None:
    import scripts.mrm_lifecycle as mrm

    class _StubMv:
        def __init__(self):
            self.current_stage = "Staging"
            self.run_id = "run"
            self.tags = {}  # missing mvr_all_gates_passed

    class _StubClient:
        def get_model_version(self, model_name, version):  # noqa: ANN001
            return _StubMv()

        def search_model_versions(self, q):  # noqa: ANN001
            return []

    monkeypatch.setattr(mrm, "_get_mlflow_client", lambda: _StubClient())

    args = SimpleNamespace(
        model="cc_pd_model",
        version="1",
        stage="Production",
        approved_by="cro@example.com",
        performed_by="mrm@example.com",
        notes="",
    )

    with pytest.raises(SystemExit) as exc:
        mrm.cmd_promote(args)
    assert exc.value.code == 1
