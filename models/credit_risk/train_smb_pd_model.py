"""
SMB (Small & Medium Business) PD Model — Training Script
=========================================================
Trains a LightGBM Probability-of-Default model for small and medium business
credit applications.

Pipeline mirrors train_cc_pd_model.py:
  1.  Load / generate synthetic SMB data
  2.  Feature engineering + encoding
  3.  Stratified 5-fold CV with Optuna HPO
  4.  Full-data final model + isotonic calibration
  5.  Monotonicity verification
  6.  Decile scorecard + WoE scorecard
  7.  MLflow experiment logging + model registration as "smb_pd_v1"

Usage
-----
    python models/credit_risk/train_smb_pd_model.py
    python models/credit_risk/train_smb_pd_model.py --no-tuning
    python models/credit_risk/train_smb_pd_model.py --sample 1000
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings
from pathlib import Path

import joblib
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import mlflow.lightgbm
import numpy as np
import optuna
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import LabelEncoder

optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings("ignore")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

PROJECT_ROOT   = Path(__file__).parents[2]
DATA_DIR       = PROJECT_ROOT / "data" / "raw" / "smb_pd"
DATA_PATH      = DATA_DIR / "smb_pd_training.parquet"
MODEL_DIR      = Path(__file__).parent
MODEL_PATH     = MODEL_DIR / "smb_pd_model_v1.pkl"
SCORECARD_PATH = MODEL_DIR / "smb_pd_scorecard.json"
MLFLOW_URI     = str(PROJECT_ROOT / "mlruns")

N_SPLITS = 5
N_TRIALS = 20   # CI default; set --trials 200 for production

# ── Feature sets ─────────────────────────────────────────────────────────────

NUMERIC_COLS: list[str] = [
    "business_age_years",
    "annual_revenue",
    "dscr",
    "debt_to_equity",
    "owner_fico",
    "num_employees",
    "trade_line_count",
    "months_oldest_trade",
    "num_derog_marks",
    "num_missed_pmts_12m",
    "inq_last_6m",
    "operating_cash_flow",
    "accounts_receivable_days",
    "inventory_days",
    "gross_margin",
    "net_profit_margin",
]

CATEGORICAL_COLS: list[str] = [
    "industry_naics_2d",
    "state",
    "legal_entity_type",
    "collateral_type",
    "loan_purpose",
]

BOOL_COLS: list[str] = [
    "personal_guarantee",
    "owner_bankruptcy_history",
    "revolving_credit_line_exists",
]

TARGET = "default_flag"

# ── Monotone constraint map ────────────────────────────────────────────────────

MONOTONE_CONSTRAINT_MAP: dict[str, int] = {
    "business_age_years"        :  1,   # older business → lower PD
    "annual_revenue"            :  1,   # higher revenue → lower PD
    "dscr"                      :  1,   # higher DSCR → lower PD
    "debt_to_equity"            : -1,   # more leverage → higher PD
    "owner_fico"                :  1,   # better personal credit → lower PD
    "num_employees"             :  0,   # ambiguous
    "trade_line_count"          :  1,   # more trade lines → better credit history
    "months_oldest_trade"       :  1,   # longer history → lower PD
    "num_derog_marks"           : -1,   # more derogatory marks → higher PD
    "num_missed_pmts_12m"       : -1,   # more missed payments → higher PD
    "inq_last_6m"               : -1,   # more inquiries → higher PD
    "operating_cash_flow"       :  1,   # higher OCF → lower PD
    "accounts_receivable_days"  : -1,   # longer AR collection → cash flow risk
    "inventory_days"            : -1,   # more inventory days → liquidity risk
    "gross_margin"              :  1,   # higher margin → lower PD
    "net_profit_margin"         :  1,   # profitable → lower PD
    # Categoricals / booleans: no monotone direction
    "industry_naics_2d"         :  0,
    "state"                     :  0,
    "legal_entity_type"         :  0,
    "collateral_type"           :  0,
    "loan_purpose"              :  0,
    "personal_guarantee"        :  0,
    "owner_bankruptcy_history"  : -1,   # prior bankruptcy → higher PD
    "revolving_credit_line_exists": 0,
}


# ── Synthetic data generator ──────────────────────────────────────────────────


def generate_synthetic_smb_data(n: int = 5000, seed: int = 42) -> pd.DataFrame:
    """Generate a realistic synthetic SMB dataset for CI testing.

    Default rate ~12% (higher than consumer, typical for SMB lending).
    """
    rng = np.random.default_rng(seed)

    states = [
        "CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
        "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
    ]
    naics_codes = ["23", "31", "44", "48", "52", "53", "54", "56", "62", "72"]
    legal_types = ["LLC", "S-Corp", "C-Corp", "Sole-Prop"]
    collateral_types = ["Real Estate", "Equipment", "Inventory", "Unsecured", "Vehicle"]
    loan_purposes = ["Working Capital", "Equipment Purchase", "Expansion", "Refinance", "Acquisition"]

    df = pd.DataFrame({
        "business_age_years"       : rng.uniform(0.5, 25.0, n),
        "annual_revenue"           : rng.lognormal(mean=12.5, sigma=1.2, size=n),  # ~$270K median
        "dscr"                     : rng.uniform(0.5, 3.0, n),
        "debt_to_equity"           : rng.lognormal(mean=0.5, sigma=0.8, size=n),
        "owner_fico"               : np.clip(rng.normal(680, 70, n), 450, 850),
        "num_employees"            : rng.integers(1, 200, n),
        "trade_line_count"         : rng.integers(1, 25, n),
        "months_oldest_trade"      : rng.integers(6, 180, n),
        "num_derog_marks"          : rng.integers(0, 6, n),
        "num_missed_pmts_12m"      : rng.integers(0, 8, n),
        "inq_last_6m"              : rng.integers(0, 10, n),
        "operating_cash_flow"      : rng.normal(50_000, 80_000, n),
        "accounts_receivable_days" : rng.uniform(10, 120, n),
        "inventory_days"           : rng.uniform(0, 90, n),
        "gross_margin"             : rng.uniform(0.05, 0.70, n),
        "net_profit_margin"        : rng.uniform(-0.10, 0.30, n),
        "industry_naics_2d"        : rng.choice(naics_codes, n),
        "state"                    : rng.choice(states, n),
        "legal_entity_type"        : rng.choice(legal_types, n, p=[0.45, 0.25, 0.20, 0.10]),
        "collateral_type"          : rng.choice(collateral_types, n),
        "loan_purpose"             : rng.choice(loan_purposes, n),
        "personal_guarantee"       : rng.integers(0, 2, n),
        "owner_bankruptcy_history" : rng.integers(0, 2, n),
        "revolving_credit_line_exists": rng.integers(0, 2, n),
    })

    # Synthetic default logic (~12% base rate, correlated with risk drivers)
    default_score = (
        -0.3 * (df["dscr"] - 1.5)
        + 0.2 * (df["debt_to_equity"] - 2.0)
        - 0.01 * (df["owner_fico"] - 680) / 10
        + 0.15 * df["num_missed_pmts_12m"]
        + 0.15 * df["num_derog_marks"]
        - 0.02 * df["business_age_years"]
        + rng.normal(0, 0.8, n)
    )
    # Offset calibrated so default rate ≈ 12% with this feature distribution
    prob = 1 / (1 + np.exp(-default_score + 3.2))
    df[TARGET] = (prob > rng.uniform(size=n)).astype(int)

    log.info(
        "Generated synthetic SMB data: n=%d, default_rate=%.2f%%",
        n, df[TARGET].mean() * 100,
    )
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────────


def load_and_prep(
    path: Path | None, sample: int | None = None
) -> tuple[pd.DataFrame, dict]:
    if path is not None and path.exists():
        log.info("Loading %s …", path)
        df = pd.read_parquet(path)
    else:
        log.info("Real data not found — generating synthetic SMB data for training.")
        df = generate_synthetic_smb_data(n=5000)

    if sample and sample < len(df):
        from sklearn.model_selection import train_test_split
        df, _ = train_test_split(
            df, train_size=sample, stratify=df[TARGET], random_state=42
        )

    log.info("  Rows: {:,}  |  default rate: {:.2f}%".format(
        len(df), df[TARGET].mean() * 100
    ))

    encoders: dict[str, LabelEncoder] = {}
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        encoders[col] = le

    for col in BOOL_COLS:
        df[col] = df[col].astype(int)

    return df, encoders


def feature_matrix(df: pd.DataFrame):
    all_cols = NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS
    X = df[[c for c in all_cols if c in df.columns]].values.astype(np.float32)
    y = df[TARGET].values.astype(int)
    return X, y, [c for c in all_cols if c in df.columns]


# ── Reuse monotonicity checker from cc model ──────────────────────────────────

def verify_monotonicity(model, X, feat_names, tolerance=1e-5):
    from models.credit_risk.train_cc_pd_model import (
        MonotonicityCheckResult,
        MONOTONE_CONSTRAINT_MAP as _CC_MAP,
    )
    results = []
    medians = np.nanmedian(X, axis=0)
    for i, feat in enumerate(feat_names):
        direction = MONOTONE_CONSTRAINT_MAP.get(feat, 0)
        if direction == 0:
            continue
        p5  = float(np.nanpercentile(X[:, i], 5))
        p95 = float(np.nanpercentile(X[:, i], 95))
        if abs(p95 - p5) < 1e-9:
            continue
        sweep = np.linspace(p5, p95, 30)
        mat   = np.tile(medians, (30, 1))
        mat[:, i] = sweep.astype(np.float32)
        preds = model.predict_proba(mat.astype(np.float32))[:, 1]
        deltas = np.diff(preds)
        if direction == 1:
            passes = bool(np.min(deltas) >= -tolerance)
        else:
            passes = bool(np.max(deltas) <= tolerance)
        results.append(MonotonicityCheckResult(
            feature=feat, constraint_dir=direction, passes=passes,
            min_delta=float(np.min(deltas)), max_delta=float(np.max(deltas)),
        ))
    failures = [r for r in results if not r.passes]
    if failures:
        msg = "Monotonicity violations:\n" + "\n".join(
            f"  {r.feature}: min_delta={r.min_delta:.6f}, max_delta={r.max_delta:.6f}"
            for r in failures
        )
        raise ValueError(msg)
    log.info("Monotonicity check passed for %d constrained SMB features.", len(results))
    return results


# ── Optuna objective ──────────────────────────────────────────────────────────


def _objective(trial, X, y, feat_names):
    constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    params = dict(
        n_estimators     = trial.suggest_int("n_estimators", 200, 1200, step=100),
        learning_rate    = trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        max_depth        = trial.suggest_int("max_depth", 4, 9),
        num_leaves       = trial.suggest_int("num_leaves", 31, 255),
        min_child_samples= trial.suggest_int("min_child_samples", 20, 300),
        subsample        = trial.suggest_float("subsample", 0.6, 1.0),
        colsample_bytree = trial.suggest_float("colsample_bytree", 0.5, 1.0),
        reg_alpha        = trial.suggest_float("reg_alpha", 1e-4, 10.0, log=True),
        reg_lambda       = trial.suggest_float("reg_lambda", 1e-4, 10.0, log=True),
        monotone_constraints = constraints,
        class_weight     = "balanced",
        random_state     = 42,
        verbose          = -1,
        n_jobs           = -1,
    )
    skf  = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    aucs = []
    for tr_idx, val_idx in skf.split(X, y):
        m = lgb.LGBMClassifier(**params)
        m.fit(X[tr_idx], y[tr_idx])
        aucs.append(roc_auc_score(y[val_idx], m.predict_proba(X[val_idx])[:, 1]))
    return float(np.mean(aucs))


# ── Build decile scorecard (mirrors cc model) ─────────────────────────────────


def build_scorecard(y_true, y_prob, n_bins=20):
    df = pd.DataFrame({"prob": y_prob, "default": y_true})
    df["score_band"] = pd.qcut(df["prob"], q=n_bins, duplicates="drop", labels=False)
    df["score_band"] = n_bins - df["score_band"]
    tbl = (
        df.groupby("score_band")
          .agg(accounts=("default", "count"), defaults=("default", "sum"),
               min_prob=("prob", "min"), max_prob=("prob", "max"))
          .reset_index()
    )
    tbl["default_rate"] = tbl["defaults"] / tbl["accounts"]
    tbl["cum_def_pct"]  = tbl["defaults"].cumsum() / tbl["defaults"].sum() * 100
    tbl["cum_acct_pct"] = tbl["accounts"].cumsum() / tbl["accounts"].sum() * 100
    tbl["odds"]   = (1 - tbl["default_rate"]) / tbl["default_rate"].clip(1e-6)
    tbl["ln_odds"] = np.log(tbl["odds"].clip(1e-6))
    tbl["pct_of_book"] = tbl["accounts"] / tbl["accounts"].sum() * 100
    return tbl


# ── Main training routine ─────────────────────────────────────────────────────


def train(args) -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("smb_pd_model")

    n_trials = getattr(args, "trials", N_TRIALS)

    df, encoders = load_and_prep(DATA_PATH if DATA_PATH.exists() else None, sample=args.sample)
    X, y, feat_names = feature_matrix(df)
    log.info("Feature matrix: %s  |  default rate: %.2f%%", X.shape, y.mean() * 100)

    monotone_constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    n_constrained = sum(1 for c in monotone_constraints if c != 0)

    # ── HPO ────────────────────────────────────────────────────────────────
    if args.no_tuning:
        best_params = dict(
            n_estimators=600, learning_rate=0.05, max_depth=7, num_leaves=63,
            min_child_samples=50, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            monotone_constraints=monotone_constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=-1,
        )
        log.info("Skipping Optuna — using default params.")
    else:
        log.info("Running Optuna HPO (%d trials) …", n_trials)
        study = optuna.create_study(
            direction="maximize", sampler=optuna.samplers.TPESampler(seed=42)
        )
        study.optimize(
            lambda t: _objective(t, X, y, feat_names),
            n_trials=n_trials, n_jobs=1, show_progress_bar=False,
        )
        best_params = study.best_params
        best_params.update({
            "monotone_constraints": monotone_constraints,
            "class_weight": "balanced", "random_state": 42,
            "verbose": -1, "n_jobs": -1,
        })
        log.info("Best CV AUC: %.4f", study.best_value)

    # ── 5-fold CV ──────────────────────────────────────────────────────────
    log.info("5-fold CV …")
    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
    cv_metrics: dict[str, list] = {"auc": [], "ks": [], "brier": [], "logloss": [], "ap": []}

    for fold, (tr_idx, val_idx) in enumerate(skf.split(X, y)):
        m = lgb.LGBMClassifier(**best_params)
        m.fit(X[tr_idx], y[tr_idx])
        prob = m.predict_proba(X[val_idx])[:, 1]
        cv_metrics["auc"].append(roc_auc_score(y[val_idx], prob))
        cv_metrics["ks"].append(ks_2samp(prob[y[val_idx] == 1], prob[y[val_idx] == 0]).statistic)
        cv_metrics["brier"].append(brier_score_loss(y[val_idx], prob))
        cv_metrics["logloss"].append(log_loss(y[val_idx], prob))
        cv_metrics["ap"].append(average_precision_score(y[val_idx], prob))
        log.info("  Fold %d → AUC %.4f | KS %.4f", fold + 1, cv_metrics["auc"][-1], cv_metrics["ks"][-1])

    mean_auc   = float(np.mean(cv_metrics["auc"]))
    mean_ks    = float(np.mean(cv_metrics["ks"]))
    mean_brier = float(np.mean(cv_metrics["brier"]))
    log.info("CV → AUC %.4f | KS %.4f | Brier %.4f", mean_auc, mean_ks, mean_brier)

    # ── Final model + calibration ──────────────────────────────────────────
    log.info("Training final model …")
    final_model = lgb.LGBMClassifier(**best_params)
    final_model.fit(X, y)

    log.info("Isotonic calibration …")
    cal_model = CalibratedClassifierCV(final_model, method="isotonic", cv="prefit")
    cal_model.fit(X, y)
    y_prob_cal = cal_model.predict_proba(X)[:, 1]

    # ── Monotonicity ────────────────────────────────────────────────────────
    try:
        mono_results = verify_monotonicity(cal_model, X, feat_names)
        mono_ok = True
    except ValueError as exc:
        log.error("Monotonicity FAILED: %s", exc)
        mono_ok = False
        mono_results = []

    # ── Decile scorecard ────────────────────────────────────────────────────
    scorecard = build_scorecard(y, y_prob_cal)
    scorecard.to_json(SCORECARD_PATH, orient="records", indent=2)
    log.info("Decile scorecard → %s", SCORECARD_PATH)

    # ── WoE scorecard ────────────────────────────────────────────────────────
    try:
        from models.credit_risk.woe_scorecard import build_woe_scorecard, save_woe_scorecard
        woe_df  = build_woe_scorecard(cal_model, X, y, feat_names)
        woe_path = save_woe_scorecard(woe_df, SCORECARD_PATH, log_to_mlflow=False)
        log.info("WoE scorecard → %s  (%d rows)", woe_path, len(woe_df))
    except Exception as exc:  # noqa: BLE001
        log.warning("WoE scorecard build failed (non-fatal): %s", exc)

    # ── Persist artefact ────────────────────────────────────────────────────
    artefact = {
        "model": cal_model,
        "feature_names": feat_names,
        "encoders": encoders,
        "best_params": best_params,
        "cv_metrics": {k: float(np.mean(v)) for k, v in cv_metrics.items()},
        "default_rate": float(y.mean()),
        "n_train": int(len(y)),
    }
    joblib.dump(artefact, MODEL_PATH)
    log.info("Model saved → %s", MODEL_PATH)

    # ── MLflow ──────────────────────────────────────────────────────────────
    log.info("Logging to MLflow …")
    with mlflow.start_run(run_name="smb_pd_v1"):
        mlflow.log_params(best_params)
        mlflow.log_metric("cv_auc",   mean_auc)
        mlflow.log_metric("cv_ks",    mean_ks)
        mlflow.log_metric("cv_brier", mean_brier)
        mlflow.log_metric("n_train",  len(y))
        mlflow.log_metric("default_rate", float(y.mean()))
        mlflow.log_artifact(str(MODEL_PATH))
        mlflow.log_artifact(str(SCORECARD_PATH))
        mlflow.set_tags({
            "model_name": "smb_pd_v1",
            "dataset": "smb_pd_synthetic",
            "monotone_verification_passed": str(mono_ok).lower(),
            "n_constrained_features": str(n_constrained),
        })
        # Register model
        try:
            mlflow.lightgbm.log_model(final_model, "smb_pd_lgbm", registered_model_name="smb_pd_v1")
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow model registration failed (non-fatal): %s", exc)

    # ── Print summary ───────────────────────────────────────────────────────
    gini = 2 * mean_auc - 1
    log.info("=" * 60)
    log.info("SMB PD Model Training Complete")
    log.info("  AUC  : %.4f", mean_auc)
    log.info("  Gini : %.4f", gini)
    log.info("  KS   : %.4f", mean_ks)
    log.info("  Brier: %.4f", mean_brier)
    log.info("  Model: %s", MODEL_PATH)

    print("\nSMB PD Model Summary")
    print("-" * 40)
    print(f"  AUC-ROC : {mean_auc:.4f}")
    print(f"  Gini    : {gini:.4f}")
    print(f"  KS      : {mean_ks:.4f}")
    print(f"  Brier   : {mean_brier:.4f}")
    print(f"  N Train : {len(y):,}")
    print(f"  Def Rate: {y.mean():.2%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train SMB PD model")
    ap.add_argument("--no-tuning", action="store_true", help="Skip Optuna")
    ap.add_argument("--sample",    type=int, default=None, help="Sub-sample N rows")
    ap.add_argument("--trials",    type=int, default=N_TRIALS, help="Optuna trials")
    train(ap.parse_args())
