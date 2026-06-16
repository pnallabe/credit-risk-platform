from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from models.credit_risk.reject_inference import (
    RejectInferenceConfig,
    run_reject_inference,
    save_summary,
)


class _StubModel:
    def __init__(self, p: float) -> None:
        self._p = float(p)

    def predict_proba(self, X):  # noqa: ANN001
        n = len(X)
        p = np.full(n, self._p, dtype=float)
        return np.stack([1.0 - p, p], axis=1)


def test_augmentation_increases_training_size() -> None:
    approved = pd.DataFrame({"f1": [1, 2, 3], "default_flag": [0, 0, 1]})
    rejected = pd.DataFrame({"f1": [4, 5]})

    cfg = RejectInferenceConfig(method="augmentation", augmentation_weight=0.5, random_seed=1)
    combined, summary = run_reject_inference(approved, rejected, _StubModel(0.4), cfg)

    assert len(combined) > len(approved)
    assert summary.total_count == len(combined)


def test_parceling_produces_binary_labels() -> None:
    approved = pd.DataFrame({"f1": [1, 2, 3], "default_flag": [0, 0, 1]})
    rejected = pd.DataFrame({"f1": [4, 5, 6]})

    cfg = RejectInferenceConfig(method="parceling", augmentation_weight=0.5, parceling_threshold_bad=0.5)
    combined, _ = run_reject_inference(approved, rejected, _StubModel(0.9), cfg)

    assert set(combined["default_flag"].unique()).issubset({0, 1})


def test_bias_adjustment_factor_gt_1() -> None:
    approved = pd.DataFrame({"f1": [1, 2, 3, 4], "default_flag": [0, 0, 0, 1]})
    rejected = pd.DataFrame({"f1": [5, 6, 7, 8]})

    cfg = RejectInferenceConfig(method="parceling", augmentation_weight=1.0, parceling_threshold_bad=0.5)
    _, summary = run_reject_inference(approved, rejected, _StubModel(0.9), cfg)

    assert summary.bias_adjustment_factor >= 1.0


def test_summary_is_json_serializable(tmp_path: Path) -> None:
    approved = pd.DataFrame({"f1": [1, 2], "default_flag": [0, 1]})
    rejected = pd.DataFrame({"f1": [3, 4]})

    cfg = RejectInferenceConfig(method="augmentation", augmentation_weight=0.5, random_seed=123)
    _, summary = run_reject_inference(approved, rejected, _StubModel(0.2), cfg)

    out = tmp_path / "reject_inference_summary.json"
    save_summary(summary, out)

    payload = json.loads(out.read_text())
    assert payload["method"] == cfg.method
    assert payload["approved_count"] == 2
    assert payload["rejected_count"] == 2
    assert "generated_at" in payload
