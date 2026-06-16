#!/usr/bin/env python
"""
Train Credit Risk Models from BigQuery
=======================================
Reads loan application data from BigQuery, computes features, trains
LightGBM PD and fraud models, evaluates them, logs to MLflow, and
registers the metadata in the BQ model_registry table.

Usage
-----
    # Train on last 12 months of data
    python scripts/train_from_bigquery.py

    # Custom date range
    python scripts/train_from_bigquery.py --start-date 2022-01-01 --end-date 2023-12-31

    # Override model output paths
    python scripts/train_from_bigquery.py --pd-model-path models/credit_risk/risk_model_v2.pkl

    # Dry-run (no BQ writes, no MLflow)
    python scripts/train_from_bigquery.py --dry-run

Options
-------
  --start-date        Training window start (YYYY-MM-DD). Default: 12 months ago.
  --end-date          Training window end   (YYYY-MM-DD). Default: today.
  --pd-model-path     Output path for trained PD model .pkl
  --fraud-model-path  Output path for trained fraud model .pkl
  --test-size         Fraction reserved for evaluation (default 0.20)
  --n-trials          Optuna hyperparameter search trials (default 30)
  --dry-run           Parse data, run training, but skip BQ writes and MLflow pushes
  --bq-dataset        BigQuery dataset (default: credit_risk_model_dev)
  --bq-project        GCP project ID   (default: ai-risk-workflow)
  --data-split        Filter on data_split column (train | None = all)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.metrics import (
    roc_auc_score,
    f1_score,
    precision_score,
    recall_score,
    average_precision_score,
)
from scipy.stats import ks_2samp

# ---------------------------------------------------------------------------
# Import project modules
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from agents.feature_engineering_agent import build_feature_dataframe

# BQ and MLflow are optional — script degrades gracefully
try:
    from db.bigquery_client import read_table, write_dataframe
    from db.bigquery_schema import MODEL_REGISTRY_SCHEMA
    _BQ_AVAILABLE = True
except ImportError:
    _BQ_AVAILABLE = False

try:
    import mlflow
    import mlflow.lightgbm
    _MLFLOW_AVAILABLE = True
except ImportError:
    _MLFLOW_AVAILABLE = False

try:
    import lightgbm as lgb
    _LGB_AVAILABLE = True
except ImportError:
    _LGB_AVAILABLE = False
    lgb = None  # type: ignore[assignment]

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    _OPTUNA_AVAILABLE = True
except ImportError:
    _OPTUNA_AVAILABLE = False


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("train_from_bigquery")

DEFAULT_PROJECT = os.getenv("GCP_PROJECT_ID", "ai-risk-workflow")
DEFAULT_DATASET = os.getenv("BQ_DATASET_MODEL_DEV", "credit_risk_model_dev")
DEFAULT_PD_MODEL_PATH    = str(_ROOT / "models" / "credit_risk" / "risk_model_v1.pkl")
DEFAULT_FRAUD_MODEL_PATH = str(_ROOT / "models" / "fraud_detection" / "fraud_model_v1.pkl")

DEFAULT_LGB_PARAMS: Dict[str, Any] = {
    "objective": "binary",
    "metric": "auc",
    "boosting_type": "gbdt",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "max_depth": -1,
    "min_child_samples": 20,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "n_estimators": 500,
    "n_jobs": -1,
    "verbose": -1,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_training_data(
    start_date: str,
    end_date: str,
    project: str,
    dataset: str,
    data_split: Optional[str] = None,
) -> pd.DataFrame:
    """Pull raw application data from BQ for the training window."""
    if not _BQ_AVAILABLE:
        raise RuntimeError("google-cloud-bigquery not installed. Cannot load from BQ.")

    # Pass bare table name — read_table will prepend project.dataset
    table_ref = "loan_applications"
    where_clauses = [
        f"submitted_at >= TIMESTAMP('{start_date}')",
        f"submitted_at <  TIMESTAMP('{end_date}')",
    ]
    if data_split:
        where_clauses.append(f"data_split = '{data_split}'")

    where = " AND ".join(where_clauses)
    logger.info("Loading training data from %s.%s.%s WHERE %s", project, dataset, table_ref, where)
    df = read_table(
        table_id=table_ref,
        dataset_id=dataset,
        project=project,
        where=where,
    )
    logger.info("Loaded %d rows from BigQuery", len(df))
    return df


def add_synthetic_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    If 'default_label' column is missing, synthesise pseudo-labels from
    bureau signals + DTI for demonstration purposes only.
    Remove this function once real outcome data is available.
    """
    if "default_label" in df.columns:
        return df

    logger.warning(
        "No 'default_label' column found — synthesising labels from bureau signals. "
        "Replace with real 12-month outcome data for production."
    )
    rng = np.random.RandomState(42)
    pd_est = (
        0.30 * (df.get("dti", pd.Series(0.3, index=df.index)).fillna(0.3) / 0.6).clip(0, 1)
        + 0.25 * (1 - df.get("credit_score", pd.Series(650, index=df.index)).fillna(650).clip(300, 850).sub(300).div(550))
        + 0.20 * (df.get("num_derogatory_marks", pd.Series(0, index=df.index)).fillna(0) / 3).clip(0, 1)
        + 0.15 * (30 / (df.get("months_since_last_delinquency", pd.Series(99, index=df.index)).fillna(99).clip(1, 60) + 1))
        + 0.10 * rng.uniform(0, 1, len(df))
    ).clip(0, 1)
    df["default_label"] = (rng.uniform(0, 1, len(df)) < pd_est).astype(int)

    fraud_est = (
        0.50 * rng.uniform(0, 1, len(df))
        + 0.30 * (df.get("num_derogatory_marks", pd.Series(0, index=df.index)).fillna(0) / 3).clip(0, 1)
        + 0.20 * (df.get("dti", pd.Series(0.3, index=df.index)).fillna(0.3) / 0.6).clip(0, 1)
    ).clip(0, 1)
    df["fraud_label"] = (rng.uniform(0, 1, len(df)) < fraud_est * 0.05).astype(int)
    return df


# ---------------------------------------------------------------------------
# Feature engineering on raw DataFrame rows
# ---------------------------------------------------------------------------

def engineer_features(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Convert raw BQ/synthetic records into the feature matrix used by the models.
    Calls the same build_feature_dataframe() used by the live pipeline to ensure
    train/serve consistency.

    raw_df must contain at minimum: application_id, loan_amount, annual_income,
    employment_status, loan_term_months, dti (or NaN).  All other columns are
    optional and fall back to NaN-safe defaults inside build_feature_dataframe.
    """
    import yaml as _yaml
    import os as _os

    # Load feature config so training uses identical hyperparameters to inference
    _cfg_path = _ROOT / "config" / "agent_config.yaml"
    feat_cfg: Dict[str, Any] = {}
    if _cfg_path.exists():
        with open(_cfg_path) as _f:
            _full = _yaml.safe_load(_f) or {}
            feat_cfg = _full.get("feature_engineering", {})

    feat_df = build_feature_dataframe(raw_df.copy(), feat_cfg)

    if feat_df.empty:
        raise ValueError("No valid records after feature engineering — check schema alignment")

    return feat_df


FEATURE_COLS = [
    "credit_utilization",
    "income_stability_score",
    "repayment_capacity",
    "debt_service_coverage",
    "credit_age_score",
    "derogatory_penalty",
    "months_since_delinquency",
    "log_loan_amount",
    "log_annual_income",
    "dti_x_loan_amount",
    "employment_encoded",
    "thin_file_alt_score",
]


# ---------------------------------------------------------------------------
# Hyperparameter tuning
# ---------------------------------------------------------------------------

def _objective_factory(X_tr, y_tr, n_splits: int = 5):
    """Return an Optuna objective function for LightGBM binary classification."""
    def objective(trial):
        params = {
            "objective": "binary",
            "metric": "auc",
            "verbosity": -1,
            "boosting_type": "gbdt",
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 16, 256),
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 10),
            "lambda_l1": trial.suggest_float("lambda_l1", 1e-4, 10.0, log=True),
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-4, 10.0, log=True),
            "n_estimators": 500,
            "n_jobs": -1,
        }
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        aucs = []
        for tr_idx, val_idx in cv.split(X_tr, y_tr):
            X_fold_tr, X_fold_val = X_tr.iloc[tr_idx], X_tr.iloc[val_idx]
            y_fold_tr, y_fold_val = y_tr.iloc[tr_idx], y_tr.iloc[val_idx]
            model = lgb.LGBMClassifier(**params)
            model.fit(
                X_fold_tr, y_fold_tr,
                eval_set=[(X_fold_val, y_fold_val)],
                callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(-1)],
            )
            aucs.append(roc_auc_score(y_fold_val, model.predict_proba(X_fold_val)[:, 1]))
        return float(np.mean(aucs))
    return objective


def tune_hyperparams(X_tr, y_tr, n_trials: int = 30) -> Dict[str, Any]:
    """Run Optuna search. Falls back to defaults if Optuna unavailable."""
    if not _OPTUNA_AVAILABLE or not _LGB_AVAILABLE:
        logger.warning("Optuna/LightGBM not available — using default hyperparameters")
        return DEFAULT_LGB_PARAMS

    logger.info("Starting Optuna hyperparameter search (%d trials)...", n_trials)
    study = optuna.create_study(direction="maximize")
    study.optimize(_objective_factory(X_tr, y_tr), n_trials=n_trials, show_progress_bar=False)
    best = study.best_params
    best.update({"objective": "binary", "metric": "auc", "verbosity": -1,
                 "n_estimators": 500, "n_jobs": -1})
    logger.info("Best CV AUC: %.4f | params: %s", study.best_value, best)
    return best


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def train_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_test: pd.DataFrame,
    y_test: pd.Series,
    params: Dict[str, Any],
    model_name: str,
) -> Tuple[Any, Dict[str, float]]:
    """Train a LightGBM binary classifier and return (model, metrics)."""
    if not _LGB_AVAILABLE:
        raise RuntimeError("lightgbm is not installed — run: pip install lightgbm")

    logger.info("Training %s on %d rows...", model_name, len(X_train))
    model = lgb.LGBMClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        callbacks=[lgb.early_stopping(50, verbose=False), lgb.log_evaluation(50)],
    )

    y_prob = model.predict_proba(X_test)[:, 1]
    y_pred = (y_prob >= 0.5).astype(int)

    # KS statistic
    pos_scores = y_prob[y_test == 1]
    neg_scores = y_prob[y_test == 0]
    ks = ks_2samp(pos_scores, neg_scores).statistic if len(pos_scores) and len(neg_scores) else 0.0

    auc  = roc_auc_score(y_test, y_prob)
    gini = 2 * auc - 1
    metrics = {
        "auc":       round(auc, 4),
        "ks_stat":   round(ks, 4),
        "gini":      round(gini, 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall":    round(recall_score(y_test, y_pred, zero_division=0), 4),
        "f1_score":  round(f1_score(y_test, y_pred, zero_division=0), 4),
        "avg_precision": round(average_precision_score(y_test, y_prob), 4),
    }
    logger.info("%s metrics: %s", model_name, json.dumps(metrics))
    return model, metrics


def save_model(model: Any, path: str) -> str:
    """Serialize model to disk and return the absolute path."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(model, f)
    logger.info("Saved model → %s", path)
    return str(Path(path).resolve())


# ---------------------------------------------------------------------------
# MLflow logging
# ---------------------------------------------------------------------------

def log_to_mlflow(
    model_name: str,
    model: Any,
    metrics: Dict[str, float],
    params: Dict[str, Any],
    artifact_path: str,
    tags: Optional[Dict[str, str]] = None,
) -> str:
    """Log model + metrics to MLflow. Returns run_id."""
    if not _MLFLOW_AVAILABLE:
        logger.warning("MLflow not installed — skipping experiment tracking")
        return "no-mlflow"

    mlflow.set_experiment(f"credit_risk/{model_name}")
    with mlflow.start_run(run_name=f"{model_name}_{datetime.now().strftime('%Y%m%d_%H%M')}") as run:
        mlflow.log_params({k: v for k, v in params.items() if k not in ("n_jobs", "verbose", "verbosity")})
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(artifact_path)
        if tags:
            mlflow.set_tags(tags)
        return run.info.run_id


# ---------------------------------------------------------------------------
# BQ model registry write
# ---------------------------------------------------------------------------

def register_in_bigquery(
    model_name: str,
    model_version: str,
    metrics: Dict[str, float],
    artifact_path: str,
    mlflow_run_id: str,
    training_rows: int,
    bq_training_table: str,
    project: str,
    dataset: str,
    feature_version: str = "1.0.0",
    dry_run: bool = False,
) -> None:
    """Write a model_registry row to BigQuery."""
    if dry_run or not _BQ_AVAILABLE:
        logger.info("[DRY-RUN] Would register %s v%s in BQ model_registry", model_name, model_version)
        return

    ts = datetime.now(timezone.utc).isoformat()
    row = {
        "model_id":           str(uuid.uuid4()),
        "model_name":         model_name,
        "model_version":      model_version,
        "status":             "candidate",
        "auc_cv":             metrics.get("auc"),
        "ks_stat":            metrics.get("ks_stat"),
        "gini":               metrics.get("gini"),
        "precision":          metrics.get("precision"),
        "recall":             metrics.get("recall"),
        "f1_score":           metrics.get("f1_score"),
        "training_rows":      training_rows,
        "feature_version":    feature_version,
        "bq_training_table":  bq_training_table,
        "artifact_path":      artifact_path,
        "mlflow_run_id":      mlflow_run_id,
        "trained_at":         ts,
        "promoted_at":        None,
        "retired_at":         None,
    }
    df = pd.DataFrame([row])
    table_id = f"{project}.{dataset}.model_registry"
    write_dataframe(df, table_id=table_id, write_disposition="WRITE_APPEND")
    logger.info("Registered %s v%s in BQ model_registry", model_name, model_version)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start-date",       default=None,
                   help="Training window start YYYY-MM-DD (default: 12 months ago)")
    p.add_argument("--end-date",         default=None,
                   help="Training window end YYYY-MM-DD (default: today)")
    p.add_argument("--pd-model-path",    default=DEFAULT_PD_MODEL_PATH)
    p.add_argument("--fraud-model-path", default=DEFAULT_FRAUD_MODEL_PATH)
    p.add_argument("--test-size",        type=float, default=0.20)
    p.add_argument("--n-trials",         type=int,   default=30)
    p.add_argument("--dry-run",          action="store_true",
                   help="Skip BQ writes and MLflow — useful for CI/testing")
    p.add_argument("--bq-dataset",       default=DEFAULT_DATASET)
    p.add_argument("--bq-project",       default=DEFAULT_PROJECT)
    p.add_argument("--data-split",       default="train",
                   help="Filter on data_split column (pass '' to skip filter)")
    p.add_argument("--no-tuning",        action="store_true",
                   help="Skip Optuna tuning, use default LightGBM params")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve date window
    today = datetime.now(timezone.utc).date()
    end_date   = args.end_date   or today.isoformat()
    start_date = args.start_date or (today - timedelta(days=365)).isoformat()

    bq_table = f"{args.bq_project}.{args.bq_dataset}.loan_applications"
    data_split = args.data_split if args.data_split else None

    # ── 1. Load data ─────────────────────────────────────────────────────
    if _BQ_AVAILABLE and not args.dry_run:
        raw_df = load_training_data(
            start_date=start_date,
            end_date=end_date,
            project=args.bq_project,
            dataset=args.bq_dataset,
            data_split=data_split,
        )
    else:
        logger.warning("BQ unavailable or dry-run — synthesising 10 000 training rows")
        sys.path.insert(0, str(_ROOT / "data"))
        try:
            from generate_synthetic_data import generate_records  # type: ignore[import]
            raw_df = pd.DataFrame(generate_records(10_000))
        except ImportError:
            rng = np.random.RandomState(42)
            n = 10_000
            annual_income = rng.uniform(20000, 200000, n)
            raw_df = pd.DataFrame({
                "application_id": [str(uuid.uuid4()) for _ in range(n)],
                "loan_amount":    rng.uniform(1000, 50000, n),
                "loan_purpose":   rng.choice(["personal", "auto", "home_improvement"], n),
                "loan_term_months": rng.choice([12, 24, 36, 60], n),
                "annual_income":  annual_income,
                "employment_status": rng.choice(["employed", "self_employed", "part_time"], n),
                "employer_tenure_months": rng.uniform(0, 120, n),
                "dti":            rng.uniform(0.05, 0.60, n),
                "existing_debt":  annual_income * rng.uniform(0.1, 2.5, n),
                "credit_score":   np.where(rng.uniform(0, 1, n) < 0.15, np.nan, rng.uniform(300, 850, n)),
                "num_open_accounts": rng.randint(0, 20, n).astype(float),
                "num_derogatory_marks": rng.randint(0, 5, n).astype(float),
                "months_since_last_delinquency": np.where(rng.uniform(0, 1, n) < 0.3, np.nan, rng.uniform(1, 120, n)),
                "avg_monthly_cash_inflow":  rng.uniform(1000, 20000, n),
                "avg_monthly_cash_outflow": rng.uniform(500, 15000, n),
                "rent_payment_months":    rng.randint(0, 60, n).astype(float),
                "utility_payment_months": rng.randint(0, 60, n).astype(float),
                "mobile_data_score":      rng.uniform(0, 1, n),
                "bank_account_age_months": rng.randint(0, 120, n).astype(float),
                "borrower_state": rng.choice(["CA", "TX", "NY", "FL", "WA"], n),
                "channel": rng.choice(["online", "branch", "partner"], n),
            })

    if raw_df.empty:
        logger.error("No training data loaded — aborting")
        sys.exit(1)

    # ── 2. Synthesise labels if needed ───────────────────────────────────
    # Normalise column names from generate_synthetic_data (which uses slightly
    # different naming conventions) to match the feature agent's expectations.
    raw_df = raw_df.rename(columns={
        "existing_debt_amount": "existing_debt",
        "debt_to_income_ratio": "dti",
        "employment_length_months": "employer_tenure_months",
        "monthly_cash_inflow": "avg_monthly_cash_inflow",
        "monthly_cash_outflow": "avg_monthly_cash_outflow",
    })
    raw_df = add_synthetic_labels(raw_df)

    # ── 3. Feature engineering ────────────────────────────────────────────
    # build_feature_dataframe adds new feature columns to a copy of raw_df,
    # so feat_df already carries default_label / fraud_label from raw_df.
    feat_df = engineer_features(raw_df)

    # If somehow labels aren't present (e.g. came from a real BQ table without
    # them), fall back to a left-merge on application_id.
    for lbl in ("default_label", "fraud_label"):
        if lbl not in feat_df.columns and "application_id" in feat_df.columns:
            feat_df = feat_df.merge(
                raw_df[["application_id", lbl]],
                on="application_id",
                how="left",
            )

    feat_df = feat_df.dropna(subset=["default_label"])

    available_cols = [c for c in FEATURE_COLS if c in feat_df.columns]
    logger.info("Feature columns used: %s", available_cols)

    X = feat_df[available_cols].fillna(0.0)
    y_default = feat_df["default_label"].astype(int)
    y_fraud   = feat_df["fraud_label"].fillna(0).astype(int)

    X_train, X_test, y_pd_train, y_pd_test = train_test_split(
        X, y_default, test_size=args.test_size, random_state=42, stratify=y_default
    )
    _, _, y_fr_train, y_fr_test = train_test_split(
        X, y_fraud, test_size=args.test_size, random_state=42, stratify=y_fraud
    )

    logger.info(
        "Train/test split: %d / %d rows | default_rate=%.2f%% | fraud_rate=%.2f%%",
        len(X_train), len(X_test),
        100 * y_pd_train.mean(), 100 * y_fr_train.mean(),
    )

    # ── 4. Hyperparameter search ──────────────────────────────────────────
    if args.no_tuning or not _OPTUNA_AVAILABLE:
        pd_params    = DEFAULT_LGB_PARAMS.copy()
        fraud_params = DEFAULT_LGB_PARAMS.copy()
    else:
        pd_params    = tune_hyperparams(X_train, y_pd_train, n_trials=args.n_trials)
        fraud_params = tune_hyperparams(X_train, y_fr_train, n_trials=max(args.n_trials // 2, 5))

    # ── 5. Train PD model ─────────────────────────────────────────────────
    pd_model, pd_metrics = train_model(
        X_train, y_pd_train, X_test, y_pd_test, pd_params, "credit_risk_pd"
    )
    pd_path = save_model(pd_model, args.pd_model_path)

    # ── 6. Train fraud model ──────────────────────────────────────────────
    fraud_model, fraud_metrics = train_model(
        X_train, y_fr_train, X_test, y_fr_test, fraud_params, "fraud_detection"
    )
    fraud_path = save_model(fraud_model, args.fraud_model_path)

    # ── 7. MLflow logging ─────────────────────────────────────────────────
    run_id_pd    = "no-mlflow"
    run_id_fraud = "no-mlflow"
    if not args.dry_run:
        run_id_pd = log_to_mlflow(
            "credit_risk_pd", pd_model, pd_metrics, pd_params, pd_path,
            tags={"training_window": f"{start_date}/{end_date}", "bq_table": bq_table},
        )
        run_id_fraud = log_to_mlflow(
            "fraud_detection", fraud_model, fraud_metrics, fraud_params, fraud_path,
            tags={"training_window": f"{start_date}/{end_date}", "bq_table": bq_table},
        )

    # ── 8. BQ model registry ──────────────────────────────────────────────
    model_version = datetime.now().strftime("v%Y%m%d")
    register_in_bigquery(
        model_name="credit_risk_pd", model_version=model_version,
        metrics=pd_metrics, artifact_path=pd_path, mlflow_run_id=run_id_pd,
        training_rows=len(X_train), bq_training_table=bq_table,
        project=args.bq_project, dataset=args.bq_dataset, dry_run=args.dry_run,
    )
    register_in_bigquery(
        model_name="fraud_detection", model_version=model_version,
        metrics=fraud_metrics, artifact_path=fraud_path, mlflow_run_id=run_id_fraud,
        training_rows=len(X_train), bq_training_table=bq_table,
        project=args.bq_project, dataset=args.bq_dataset, dry_run=args.dry_run,
    )

    # ── Summary ───────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Training complete. Summary:")
    logger.info("  PD model      AUC=%.4f  KS=%.4f  → %s", pd_metrics["auc"], pd_metrics["ks_stat"], pd_path)
    logger.info("  Fraud model   AUC=%.4f  KS=%.4f  → %s", fraud_metrics["auc"], fraud_metrics["ks_stat"], fraud_path)
    logger.info("  Model version: %s", model_version)
    if not args.dry_run:
        logger.info("  MLflow PD run:    %s", run_id_pd)
        logger.info("  MLflow fraud run: %s", run_id_fraud)
        logger.info("  BQ registry:      %s.%s.model_registry", args.bq_project, args.bq_dataset)
    logger.info("=" * 60)
    logger.info(
        "Next steps: promote to champion via:\n"
        "  UPDATE `%s.%s.model_registry`\n"
        "  SET status='champion', promoted_at=CURRENT_TIMESTAMP()\n"
        "  WHERE model_version='%s' AND status='candidate'",
        args.bq_project, args.bq_dataset, model_version,
    )


if __name__ == "__main__":
    main()
