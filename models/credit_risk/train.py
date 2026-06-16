"""
Credit Risk Model — Training Script (Probability of Default)
=============================================================
Trains a LightGBM classifier to predict default_flag, using
5-fold stratified cross-validation and Optuna hyperparameter tuning.
Logs all metrics and feature importances to MLflow.
Saves the model to models/credit_risk/risk_model_v1.pkl.

Usage
-----
    python models/credit_risk/train.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import joblib
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")  # non-interactive backend for CI
import matplotlib.pyplot as plt
import mlflow
import mlflow.lightgbm
import numpy as np
import optuna
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold

sys.path.insert(0, str(Path(__file__).parents[2]))
from feature_pipeline.features import FeaturePipelineConfig, compute_features  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parents[2]
DATA_DIR = PROJECT_ROOT / "data" / "raw"
MODEL_DIR = Path(__file__).parent
MODEL_PATH = MODEL_DIR / "risk_model_v1.pkl"
KS_PLOT_PATH = MODEL_DIR / "ks_plot.png"

FEATURE_CONFIG = FeaturePipelineConfig()
FEATURE_COLS = FEATURE_CONFIG.feature_list
N_SPLITS = 5
N_TRIALS = 20


# ---------------------------------------------------------------------------
# KS plot
# ---------------------------------------------------------------------------

def save_ks_plot(y_true: np.ndarray, y_prob: np.ndarray, path: Path) -> None:
    """Generate and save a KS (Kolmogorov–Smirnov) separation plot."""
    thresholds = np.linspace(0, 1, 200)
    tpr = [np.mean(y_prob[y_true == 1] <= t) for t in thresholds]
    fpr = [np.mean(y_prob[y_true == 0] <= t) for t in thresholds]

    ks_val = max(abs(np.array(tpr) - np.array(fpr)))
    ks_thresh = thresholds[np.argmax(np.abs(np.array(tpr) - np.array(fpr)))]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(thresholds, tpr, label="Default (TPR)", color="red")
    ax.plot(thresholds, fpr, label="Non-default (FPR)", color="blue")
    ax.axvline(ks_thresh, color="green", linestyle="--", label=f"KS = {ks_val:.3f}")
    ax.fill_between(thresholds, tpr, fpr, alpha=0.1, color="green")
    ax.set_xlabel("Score threshold")
    ax.set_ylabel("Cumulative distribution")
    ax.set_title("KS Curve — Credit Risk Model")
    ax.legend()
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=120)
    plt.close(fig)
    logger.info("KS plot saved to %s", path)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    logger.info("Loading datasets …")
    df_train = pd.read_parquet(DATA_DIR / "loan_applications.parquet")
    df_test = pd.read_parquet(DATA_DIR / "loan_applications_test.parquet")

    df_train = compute_features(df_train, FEATURE_CONFIG)
    df_test = compute_features(df_test, FEATURE_CONFIG)

    # Ensure boolean target is int
    df_train["default_flag"] = df_train["default_flag"].astype(int)
    df_test["default_flag"] = df_test["default_flag"].astype(int)

    logger.info(
        "Train: %d rows (default rate %.2f%%)  |  Test: %d rows",
        len(df_train),
        df_train["default_flag"].mean() * 100,
        len(df_test),
    )
    return df_train, df_test


def _cv_auc(params: dict, X: np.ndarray, y: np.ndarray) -> float:
    """Return mean stratified CV AUC for the given LightGBM params."""
    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
    aucs = []
    for fold, (tr_idx, val_idx) in enumerate(skf.split(X, y)):
        model = lgb.LGBMClassifier(**params, verbose=-1)
        model.fit(X[tr_idx], y[tr_idx])
        prob = model.predict_proba(X[val_idx])[:, 1]
        fold_auc = roc_auc_score(y[val_idx], prob)
        aucs.append(fold_auc)
    return float(np.mean(aucs))


def _objective(trial: optuna.Trial, X: np.ndarray, y: np.ndarray) -> float:
    params = {
        "n_estimators": trial.suggest_int("n_estimators", 100, 600),
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
        "reg_alpha": trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        "reg_lambda": trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        "class_weight": "balanced",
        "random_state": 42,
    }
    return _cv_auc(params, X, y)


def train() -> None:
    mlflow.set_experiment("credit_risk")

    df_train, df_test = load_data()

    X_train = df_train[FEATURE_COLS].values
    y_train = df_train["default_flag"].values
    X_test = df_test[FEATURE_COLS].values
    y_test = df_test["default_flag"].values

    logger.info("Starting Optuna hyperparameter search (%d trials) …", N_TRIALS)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
    )
    study.optimize(lambda t: _objective(t, X_train, y_train), n_trials=N_TRIALS)

    best_params = study.best_params
    best_params.update({"class_weight": "balanced", "random_state": 42, "verbose": -1})
    logger.info("Best params: %s (CV AUC=%.4f)", best_params, study.best_value)

    logger.info("Training final model on full train set …")
    final_model = lgb.LGBMClassifier(**best_params)
    final_model.fit(X_train, y_train)

    # ── Evaluation ──────────────────────────────────────────────────────────
    y_prob = final_model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    ks_stat, _ = ks_2samp(y_prob[y_test == 1], y_prob[y_test == 0])

    feature_importances = dict(zip(FEATURE_COLS, final_model.feature_importances_))

    print(f"\n===  Credit Risk — Test Set Metrics  ===")
    print(f"  AUC : {auc:.4f}")
    print(f"  KS  : {ks_stat:.4f}")
    for feat, imp in sorted(feature_importances.items(), key=lambda x: -x[1]):
        print(f"  {feat:<35} {imp:.1f}")

    assert auc > 0.75, f"AUC {auc:.4f} < 0.75"
    assert ks_stat > 0.35, f"KS {ks_stat:.4f} < 0.35"
    logger.info("All performance assertions passed.")

    # ── KS plot ───────────────────────────────────────────────────────────
    save_ks_plot(y_test, y_prob, KS_PLOT_PATH)

    # ── MLflow logging ────────────────────────────────────────────────────
    with mlflow.start_run():
        mlflow.log_params(best_params)
        mlflow.log_metrics({"auc": auc, "ks_statistic": ks_stat})
        mlflow.log_metrics({f"importance_{k}": v for k, v in feature_importances.items()})
        mlflow.log_artifact(str(KS_PLOT_PATH))
        mlflow.lightgbm.log_model(final_model, artifact_path="risk_model")

    # ── Save model ─────────────────────────────────────────────────────────
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(final_model, MODEL_PATH)
    logger.info("Model saved to %s", MODEL_PATH)


if __name__ == "__main__":
    train()
