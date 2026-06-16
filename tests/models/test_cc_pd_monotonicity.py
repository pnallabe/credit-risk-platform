"""
P1.2 — Monotonicity verification tests for the CC PD model.

Loads the trained model artifact and verifies that every constrained feature
moves PD in the expected direction across its p5–p95 range.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

MODEL_DIR = Path(__file__).parents[2] / "models" / "credit_risk"
MODEL_PATH = MODEL_DIR / "cc_pd_model_v1.pkl"
MODEL_CARD = MODEL_DIR / "cc_pd_model_card.json"


@pytest.fixture(scope="module")
def model_artefact():
    """Load the trained model artefact (skip if not built yet)."""
    if not MODEL_PATH.exists():
        pytest.skip(f"Model artefact not found: {MODEL_PATH}")
    import joblib
    return joblib.load(MODEL_PATH)


@pytest.fixture(scope="module")
def synthetic_X(model_artefact):
    """Generate a synthetic feature matrix for monotonicity sweeps."""
    feat_names = model_artefact["feature_names"]
    rng = np.random.default_rng(42)
    X = rng.random((2_000, len(feat_names))).astype(np.float32)
    return X, feat_names


def test_verify_monotonicity_passes_on_trained_model(model_artefact, synthetic_X):
    """All constrained features must pass the monotonicity sweep on the trained model."""
    from models.credit_risk.train_cc_pd_model import verify_monotonicity

    model = model_artefact["model"]
    X, feat_names = synthetic_X

    # Should not raise — all constrained features must pass
    results = verify_monotonicity(model, X, feat_names, tolerance=1e-4)

    failed = [r for r in results if not r.passes]
    assert not failed, (
        "Monotonicity violations: " +
        ", ".join(f"{r.feature}(dir={r.constraint_dir},min={r.min_delta:.5f})"
                  for r in failed)
    )


def test_constraint_map_covers_all_feature_names(model_artefact):
    """Every feature name used in training must appear in MONOTONE_CONSTRAINT_MAP."""
    from models.credit_risk.train_cc_pd_model import MONOTONE_CONSTRAINT_MAP

    feat_names = model_artefact["feature_names"]
    missing = [f for f in feat_names if f not in MONOTONE_CONSTRAINT_MAP]
    assert not missing, (
        f"Features missing from MONOTONE_CONSTRAINT_MAP: {missing}\n"
        "Add them with an explicit constraint (0 if direction is ambiguous)."
    )


def test_model_card_records_constraints(model_artefact):
    """The model card JSON must contain monotone_constraints section."""
    if not MODEL_CARD.exists():
        pytest.skip("Model card not generated yet")
    card = json.loads(MODEL_CARD.read_text())
    assert "monotone_constraints" in card
    assert "feature_map" in card["monotone_constraints"]
    assert "verification_passed" in card["monotone_constraints"]


def test_protective_features_have_positive_constraint():
    """Sanity check: known protective features must be +1."""
    from models.credit_risk.train_cc_pd_model import MONOTONE_CONSTRAINT_MAP

    for feat in ("fico_score", "annual_income", "pct_ontime_pmts_12m", "months_oldest_trade"):
        assert MONOTONE_CONSTRAINT_MAP.get(feat) == 1, (
            f"Expected +1 constraint for '{feat}' (higher → lower PD)"
        )


def test_risk_features_have_negative_constraint():
    """Sanity check: known risk-increasing features must be -1."""
    from models.credit_risk.train_cc_pd_model import MONOTONE_CONSTRAINT_MAP

    for feat in ("dti", "num_derog_marks", "num_missed_pmts_12m", "overlimit_months_12m"):
        assert MONOTONE_CONSTRAINT_MAP.get(feat) == -1, (
            f"Expected -1 constraint for '{feat}' (higher → higher PD)"
        )
