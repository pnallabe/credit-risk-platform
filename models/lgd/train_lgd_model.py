"""
LGD (Loss Given Default) Model — Training Script
==================================================
Trains a LightGBM regressor to predict the realized LGD (Loss Given Default)
for each loan account.

Unlike PD models (classifiers), LGD is a regression:
  - Input : collateral, product, borrower, and macro features
  - Output: realized_lgd ∈ [0, 1]
  - Wrapped with a sigmoid to constrain output to [0, 1]

Registered in MLflow as "lgd_v1".

Usage
-----
    python models/lgd/train_lgd_model.py
    python models/lgd/train_lgd_model.py --no-tuning
"""

from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import optuna
import pandas as pd
from sklearn.model_selection import KFold
from sklearn.metrics import mean_squared_error, mean_absolute_error
import mlflow
import mlflow.lightgbm

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parents[2]
DATA_DIR     = PROJECT_ROOT / "data" / "raw" / "lgd"
DATA_PATH    = DATA_DIR / "lgd_training.parquet"
MODEL_DIR    = Path(__file__).parent
MODEL_PATH   = MODEL_DIR / "lgd_model_v1.pkl"
MLFLOW_URI   = str(PROJECT_ROOT / "mlruns")

N_SPLITS = 5
N_TRIALS = 20   # CI default

# ── Feature definitions ───────────────────────────────────────────────────────

FEATURES: list[str] = [
    "collateral_type_encoded",   # label-encoded collateral type
    "ltv",                       # loan-to-value at origination
    "loan_term_months",
    "product_type_encoded",      # label-encoded product type
    "borrower_segment_encoded",  # consumer / smb / commercial
    "fico_score",
    "dti",
    "months_on_book",
    "economic_cycle",            # 0=expansion, 1=contraction (config-injected)
]

TARGET = "realized_lgd"   # float in [0, 1]

# Default LGD used when model artefact is unavailable
DEFAULT_LGD: float = 0.40

# Collateral and product lookup tables for encoding
COLLATERAL_TYPES = [
    "Real Estate", "Vehicle", "Equipment", "Inventory",
    "Cash Collateral", "Unsecured", "Other",
]
PRODUCT_TYPES = [
    "credit_card", "personal_loan", "mortgage",
    "auto_loan", "smb_loan", "commercial_loan",
]
BORROWER_SEGMENTS = ["consumer", "smb", "commercial"]


# ── Synthetic data generator ──────────────────────────────────────────────────


def generate_synthetic_lgd_data(n: int = 4000, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic LGD training data.

    Secured loans follow beta(2, 8) → low loss (mean ~20%).
    Unsecured loans follow beta(5, 3) → higher loss (mean ~63%).
    20% noise is added.
    """
    from scipy.stats import beta as sp_beta

    rng = np.random.default_rng(seed)

    n_secured   = int(n * 0.60)
    n_unsecured = n - n_secured

    # Secured portion: collateral = Real Estate, Vehicle, Equipment
    secured_collateral = rng.choice([0, 1, 2], n_secured)       # RE, Vehicle, Equipment
    secured_lgd = sp_beta.rvs(2, 8, size=n_secured, random_state=seed)   # mean ~20%

    # Unsecured portion: collateral = Unsecured
    unsecured_collateral = np.full(n_unsecured, 5)  # "Unsecured"
    unsecured_lgd = sp_beta.rvs(5, 3, size=n_unsecured, random_state=seed + 1)  # mean ~63%

    collateral_enc = np.concatenate([secured_collateral, unsecured_collateral])
    raw_lgd        = np.concatenate([secured_lgd, unsecured_lgd])

    # Add noise
    noise = rng.normal(0, 0.08, n)
    realized_lgd = np.clip(raw_lgd + noise, 0.0, 1.0)

    product_enc = rng.integers(0, len(PRODUCT_TYPES), n)
    seg_enc     = rng.integers(0, len(BORROWER_SEGMENTS), n)

    df = pd.DataFrame({
        "collateral_type_encoded" : collateral_enc.astype(float),
        "ltv"                     : rng.uniform(0.0, 0.95, n),
        "loan_term_months"        : rng.choice([12, 24, 36, 60, 84, 120, 180, 240, 360], n).astype(float),
        "product_type_encoded"    : product_enc.astype(float),
        "borrower_segment_encoded": seg_enc.astype(float),
        "fico_score"              : np.clip(rng.normal(670, 80, n), 450, 850),
        "dti"                     : rng.uniform(0.10, 0.60, n),
        "months_on_book"          : rng.integers(1, 84, n).astype(float),
        "economic_cycle"          : rng.integers(0, 2, n).astype(float),
        TARGET                    : realized_lgd,
    })

    log.info("Generated synthetic LGD data: n=%d, mean_lgd=%.2f%%", n, realized_lgd.mean() * 100)
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────────


def load_and_prep(path: Path | None, sample: int | None = None) -> pd.DataFrame:
    if path is not None and path.exists():
        log.info("Loading %s …", path)
        df = pd.read_parquet(path)
    else:
        log.info("Real LGD data not found — using synthetic data.")
        df = generate_synthetic_lgd_data(n=4000)

    if sample and sample < len(df):
        df = df.sample(n=sample, random_state=42)

    log.info("  Rows: {:,}  |  mean LGD: {:.2f}%".format(len(df), df[TARGET].mean() * 100))
    return df


def feature_matrix(df: pd.DataFrame):
    X = df[FEATURES].values.astype(np.float32)
    y = df[TARGET].values.astype(np.float64)
    return X, y


# ── Sigmoid wrapper for output constraint ─────────────────────────────────────


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class SigmoidLGBMRegressor:
    """Wrap a LightGBM regressor with sigmoid output to constrain predictions to [0, 1]."""

    def __init__(self, model: lgb.LGBMRegressor):
        self._model = model

    def predict(self, X: np.ndarray) -> np.ndarray:
        raw = self._model.predict(X)
        return _sigmoid(raw).astype(np.float64)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self._model.feature_importances_

    def __getattr__(self, name: str):
        return getattr(self._model, name)


# ── Optuna objective ──────────────────────────────────────────────────────────


def _objective(trial, X, y):
    params = dict(
        n_estimators     = trial.suggest_int("n_estimators", 100, 800, step=100),
        learning_rate    = trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        max_depth        = trial.suggest_int("max_depth", 3, 7),
        num_leaves       = trial.suggest_int("num_leaves", 15, 127),
        min_child_samples= trial.suggest_int("min_child_samples", 10, 200),
        subsample        = trial.suggest_float("subsample", 0.6, 1.0),
        colsample_bytree = trial.suggest_float("colsample_bytree", 0.5, 1.0),
        reg_alpha        = trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        reg_lambda       = trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        objective        = "regression",
        random_state     = 42,
        verbose          = -1,
        n_jobs           = -1,
    )
    kf   = KFold(n_splits=3, shuffle=True, random_state=42)
    rmses = []
    for tr_idx, val_idx in kf.split(X):
        m = lgb.LGBMRegressor(**params)
        m.fit(X[tr_idx], y[tr_idx])
        preds = _sigmoid(m.predict(X[val_idx]))
        rmses.append(float(np.sqrt(mean_squared_error(y[val_idx], preds))))
    return float(np.mean(rmses))   # minimize RMSE


# ── Main ──────────────────────────────────────────────────────────────────────


def train(args) -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("lgd_model")

    n_trials = getattr(args, "trials", N_TRIALS)

    df = load_and_prep(DATA_PATH if DATA_PATH.exists() else None, sample=args.sample)
    X, y = feature_matrix(df)
    log.info("LGD feature matrix: %s", X.shape)

    if args.no_tuning:
        best_params = dict(
            n_estimators=400, learning_rate=0.05, max_depth=5, num_leaves=31,
            min_child_samples=30, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            objective="regression", random_state=42, verbose=-1, n_jobs=-1,
        )
    else:
        log.info("Optuna HPO (%d trials) …", n_trials)
        study = optuna.create_study(
            direction="minimize", sampler=optuna.samplers.TPESampler(seed=42)
        )
        study.optimize(
            lambda t: _objective(t, X, y),
            n_trials=n_trials, n_jobs=1, show_progress_bar=False,
        )
        best_params = study.best_params
        best_params.update({
            "objective": "regression", "random_state": 42, "verbose": -1, "n_jobs": -1
        })
        log.info("Best CV RMSE: %.4f", study.best_value)

    # ── 5-fold CV ──────────────────────────────────────────────────────────
    kf = KFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
    cv_rmse, cv_mae = [], []
    for fold, (tr_idx, val_idx) in enumerate(kf.split(X)):
        m = lgb.LGBMRegressor(**best_params)
        m.fit(X[tr_idx], y[tr_idx])
        preds = _sigmoid(m.predict(X[val_idx]))
        rmse = float(np.sqrt(mean_squared_error(y[val_idx], preds)))
        mae  = float(mean_absolute_error(y[val_idx], preds))
        cv_rmse.append(rmse)
        cv_mae.append(mae)
        log.info("  Fold %d → RMSE %.4f | MAE %.4f", fold + 1, rmse, mae)

    mean_rmse = float(np.mean(cv_rmse))
    mean_mae  = float(np.mean(cv_mae))
    log.info("CV → RMSE %.4f | MAE %.4f", mean_rmse, mean_mae)

    # ── Train final model ────────────────────────────────────────────────────
    final_raw = lgb.LGBMRegressor(**best_params)
    final_raw.fit(X, y)
    final_model = SigmoidLGBMRegressor(final_raw)

    # Verify output range
    preds_all = final_model.predict(X)
    assert preds_all.min() >= 0.0, "LGD predictions went below 0"
    assert preds_all.max() <= 1.0, "LGD predictions went above 1"
    log.info(
        "LGD predictions: min=%.4f, max=%.4f, mean=%.4f",
        preds_all.min(), preds_all.max(), preds_all.mean(),
    )

    # ── Persist ──────────────────────────────────────────────────────────────
    artefact = {
        "model"         : final_model,
        "feature_names" : FEATURES,
        "best_params"   : best_params,
        "cv_rmse"       : mean_rmse,
        "cv_mae"        : mean_mae,
        "n_train"       : int(len(y)),
        "mean_lgd"      : float(y.mean()),
        "collateral_types": COLLATERAL_TYPES,
        "product_types" : PRODUCT_TYPES,
        "borrower_segs" : BORROWER_SEGMENTS,
    }
    joblib.dump(artefact, MODEL_PATH)
    log.info("LGD model saved → %s", MODEL_PATH)

    # ── MLflow ───────────────────────────────────────────────────────────────
    with mlflow.start_run(run_name="lgd_v1"):
        mlflow.log_params(best_params)
        mlflow.log_metric("cv_rmse", mean_rmse)
        mlflow.log_metric("cv_mae",  mean_mae)
        mlflow.log_metric("mean_lgd", float(y.mean()))
        mlflow.log_artifact(str(MODEL_PATH))
        mlflow.set_tags({"model_name": "lgd_v1", "objective": "regression"})
        try:
            mlflow.lightgbm.log_model(final_raw, "lgd_lgbm", registered_model_name="lgd_v1")
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow registration failed (non-fatal): %s", exc)

    print("\nLGD Model Summary")
    print("-" * 40)
    print(f"  CV RMSE   : {mean_rmse:.4f}")
    print(f"  CV MAE    : {mean_mae:.4f}")
    print(f"  Mean LGD  : {y.mean():.2%}")
    print(f"  N Train   : {len(y):,}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train LGD regression model")
    ap.add_argument("--no-tuning", action="store_true")
    ap.add_argument("--sample",    type=int, default=None)
    ap.add_argument("--trials",    type=int, default=N_TRIALS)
    train(ap.parse_args())
