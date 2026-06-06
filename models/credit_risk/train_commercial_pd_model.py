"""
Commercial Real Estate / Commercial RE PD Model — Training Script
=================================================================
Trains a LightGBM PD model for commercial real estate and commercial loans.
Mirrors the structure of train_smb_pd_model.py and train_cc_pd_model.py.

Features: NOI, cap rate, LTV, DSCR, occupancy, sponsor metrics, etc.
Registered in MLflow as "commercial_pd_v1".

Usage
-----
    python models/credit_risk/train_commercial_pd_model.py
    python models/credit_risk/train_commercial_pd_model.py --no-tuning
"""

from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path

import joblib
import lightgbm as lgb
import matplotlib
matplotlib.use("Agg")
import mlflow
import mlflow.lightgbm
import numpy as np
import optuna
import pandas as pd
from scipy.stats import ks_2samp
from sklearn.calibration import CalibratedClassifierCV
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
DATA_DIR       = PROJECT_ROOT / "data" / "raw" / "commercial_pd"
DATA_PATH      = DATA_DIR / "commercial_pd_training.parquet"
MODEL_DIR      = Path(__file__).parent
MODEL_PATH     = MODEL_DIR / "commercial_pd_model_v1.pkl"
SCORECARD_PATH = MODEL_DIR / "commercial_pd_scorecard.json"
MLFLOW_URI     = str(PROJECT_ROOT / "mlruns")

N_SPLITS = 5
N_TRIALS = 20   # CI default; set --trials 200 for production

# ── Feature sets ─────────────────────────────────────────────────────────────

NUMERIC_COLS: list[str] = [
    "noi",                       # Net Operating Income
    "cap_rate",                  # Capitalisation rate
    "ltv",                       # Loan-to-Value
    "dscr",
    "loan_amount",
    "property_age_years",
    "occupancy_rate",            # % leased (0–100)
    "market_vacancy_rate",       # metro market vacancy rate (0–100)
    "sponsor_net_worth",
    "guarantor_fico",
    "amortization_period_years",
    "loan_term_years",
    "num_prior_commercial_loans",
    "prior_default_count",
]

CATEGORICAL_COLS: list[str] = [
    "property_type",
    "state",
    "market_tier",
    "loan_purpose",
    "recourse_type",
]

BOOL_COLS: list[str] = [
    "cross_collateralized",
    "interest_only_period",
    "environmental_flag",
]

TARGET = "default_flag"

# ── Monotone constraint map ────────────────────────────────────────────────────

MONOTONE_CONSTRAINT_MAP: dict[str, int] = {
    "noi"                        :  1,   # higher NOI → lower PD
    "cap_rate"                   :  0,   # higher cap = higher yield but can signal risk
    "ltv"                        : -1,   # higher LTV → higher PD
    "dscr"                       :  1,   # higher DSCR → lower PD
    "loan_amount"                :  0,   # ambiguous
    "property_age_years"         :  0,   # non-directional (older can be well-located or distressed)
    "occupancy_rate"             :  1,   # higher occupancy → lower PD
    "market_vacancy_rate"        : -1,   # higher vacancy in market → higher PD
    "sponsor_net_worth"          :  1,   # stronger sponsor → lower PD
    "guarantor_fico"             :  1,   # better guarantor credit → lower PD
    "amortization_period_years"  :  0,   # longer amortization reduces payment but extends duration
    "loan_term_years"            :  0,
    "num_prior_commercial_loans" :  1,   # more experience → lower PD (all else equal)
    "prior_default_count"        : -1,   # prior defaults → higher PD
    # Categoricals / booleans
    "property_type"              :  0,
    "state"                      :  0,
    "market_tier"                :  0,
    "loan_purpose"               :  0,
    "recourse_type"              :  0,
    "cross_collateralized"       :  0,
    "interest_only_period"       : -1,   # interest-only = no principal reduction → higher risk
    "environmental_flag"         : -1,   # environmental flag → higher PD
}


# ── Synthetic data generator ──────────────────────────────────────────────────


def generate_synthetic_commercial_data(n: int = 3000, seed: int = 42) -> pd.DataFrame:
    """Generate realistic synthetic commercial RE data for CI.

    Default rate ~8% (lower than SMB, typical for CRE lending).
    """
    rng = np.random.default_rng(seed)

    states = ["CA", "TX", "NY", "FL", "IL", "WA", "MA", "GA", "CO", "AZ"]
    property_types = ["Office", "Retail", "Multifamily", "Industrial", "Hotel", "Mixed-Use"]
    market_tiers   = ["Tier1", "Tier2", "Tier3"]
    loan_purposes  = ["Acquisition", "Refinance", "Construction", "Bridge", "Permanent"]
    recourse_types = ["Full Recourse", "Partial Recourse", "Non-Recourse"]

    occupancy_rate = np.clip(rng.beta(8, 2, n) * 100, 20, 100)
    ltv = rng.uniform(0.40, 0.95, n)
    dscr = rng.uniform(0.80, 2.50, n)
    noi  = rng.lognormal(mean=12.0, sigma=1.0, size=n)  # ~$160K median NOI

    df = pd.DataFrame({
        "noi"                       : noi,
        "cap_rate"                  : rng.uniform(0.04, 0.10, n),
        "ltv"                       : ltv,
        "dscr"                      : dscr,
        "loan_amount"               : noi / rng.uniform(0.05, 0.12, n),
        "property_age_years"        : rng.uniform(0, 60, n),
        "occupancy_rate"            : occupancy_rate,
        "market_vacancy_rate"       : rng.uniform(3.0, 25.0, n),
        "sponsor_net_worth"         : rng.lognormal(mean=14.5, sigma=1.5, size=n),
        "guarantor_fico"            : np.clip(rng.normal(700, 60, n), 500, 850),
        "amortization_period_years" : rng.choice([20, 25, 30], n),
        "loan_term_years"           : rng.choice([5, 7, 10, 15], n),
        "num_prior_commercial_loans": rng.integers(0, 20, n),
        "prior_default_count"       : rng.integers(0, 3, n),
        "property_type"             : rng.choice(property_types, n),
        "state"                     : rng.choice(states, n),
        "market_tier"               : rng.choice(market_tiers, n, p=[0.30, 0.45, 0.25]),
        "loan_purpose"              : rng.choice(loan_purposes, n),
        "recourse_type"             : rng.choice(recourse_types, n, p=[0.40, 0.30, 0.30]),
        "cross_collateralized"      : rng.integers(0, 2, n),
        "interest_only_period"      : rng.integers(0, 2, n),
        "environmental_flag"        : (rng.uniform(size=n) < 0.05).astype(int),
    })

    # Synthetic default logic (~8% base rate)
    default_score = (
         2.0 * (ltv - 0.70)
        - 1.5 * (dscr - 1.25)
        - 0.02 * (occupancy_rate - 85)
        + 0.5 * df["prior_default_count"]
        + rng.normal(0, 0.7, n)
    )
    prob = 1 / (1 + np.exp(-default_score + 1.5))
    df[TARGET] = (prob > rng.uniform(size=n)).astype(int)

    log.info(
        "Generated synthetic commercial data: n=%d, default_rate=%.2f%%",
        n, df[TARGET].mean() * 100,
    )
    return df


# ── Preprocessing ─────────────────────────────────────────────────────────────


def load_and_prep(path: Path | None, sample: int | None = None) -> tuple[pd.DataFrame, dict]:
    if path is not None and path.exists():
        log.info("Loading %s …", path)
        df = pd.read_parquet(path)
    else:
        log.info("Real data not found — generating synthetic commercial data.")
        df = generate_synthetic_commercial_data(n=3000)

    if sample and sample < len(df):
        from sklearn.model_selection import train_test_split
        df, _ = train_test_split(df, train_size=sample, stratify=df[TARGET], random_state=42)

    log.info("  Rows: {:,}  |  default rate: {:.2f}%".format(len(df), df[TARGET].mean() * 100))

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


# ── Optuna objective ──────────────────────────────────────────────────────────


def _objective(trial, X, y, feat_names):
    constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    params = dict(
        n_estimators     = trial.suggest_int("n_estimators", 200, 1000, step=100),
        learning_rate    = trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        max_depth        = trial.suggest_int("max_depth", 4, 8),
        num_leaves       = trial.suggest_int("num_leaves", 15, 127),
        min_child_samples= trial.suggest_int("min_child_samples", 10, 200),
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


def verify_monotonicity(model, X, feat_names, tolerance=1e-5):
    from models.credit_risk.train_cc_pd_model import MonotonicityCheckResult
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
    log.info("Monotonicity check passed for %d constrained commercial features.", len(results))
    return results


# ── Main ──────────────────────────────────────────────────────────────────────


def train(args) -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("commercial_pd_model")

    n_trials = getattr(args, "trials", N_TRIALS)

    df, encoders = load_and_prep(DATA_PATH if DATA_PATH.exists() else None, sample=args.sample)
    X, y, feat_names = feature_matrix(df)
    log.info("Feature matrix: %s  |  default rate: %.2f%%", X.shape, y.mean() * 100)

    monotone_constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    n_constrained = sum(1 for c in monotone_constraints if c != 0)

    if args.no_tuning:
        best_params = dict(
            n_estimators=400, learning_rate=0.05, max_depth=6, num_leaves=31,
            min_child_samples=20, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            monotone_constraints=monotone_constraints,
            class_weight="balanced", random_state=42, verbose=-1, n_jobs=-1,
        )
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

    skf = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
    cv_metrics: dict[str, list] = {"auc": [], "ks": [], "brier": []}

    for fold, (tr_idx, val_idx) in enumerate(skf.split(X, y)):
        m = lgb.LGBMClassifier(**best_params)
        m.fit(X[tr_idx], y[tr_idx])
        prob = m.predict_proba(X[val_idx])[:, 1]
        cv_metrics["auc"].append(roc_auc_score(y[val_idx], prob))
        cv_metrics["ks"].append(ks_2samp(prob[y[val_idx] == 1], prob[y[val_idx] == 0]).statistic)
        cv_metrics["brier"].append(brier_score_loss(y[val_idx], prob))
        log.info("  Fold %d → AUC %.4f | KS %.4f", fold + 1, cv_metrics["auc"][-1], cv_metrics["ks"][-1])

    mean_auc   = float(np.mean(cv_metrics["auc"]))
    mean_ks    = float(np.mean(cv_metrics["ks"]))
    mean_brier = float(np.mean(cv_metrics["brier"]))

    final_model = lgb.LGBMClassifier(**best_params)
    final_model.fit(X, y)
    cal_model = CalibratedClassifierCV(final_model, method="isotonic", cv="prefit")
    cal_model.fit(X, y)
    y_prob_cal = cal_model.predict_proba(X)[:, 1]

    try:
        mono_results = verify_monotonicity(cal_model, X, feat_names)
        mono_ok = True
    except ValueError as exc:
        log.error("Monotonicity FAILED: %s", exc)
        mono_ok = False

    scorecard = build_scorecard(y, y_prob_cal)
    scorecard.to_json(SCORECARD_PATH, orient="records", indent=2)

    try:
        from models.credit_risk.woe_scorecard import build_woe_scorecard, save_woe_scorecard
        woe_df = build_woe_scorecard(cal_model, X, y, feat_names)
        save_woe_scorecard(woe_df, SCORECARD_PATH, log_to_mlflow=False)
        log.info("WoE scorecard → %d rows", len(woe_df))
    except Exception as exc:  # noqa: BLE001
        log.warning("WoE scorecard failed (non-fatal): %s", exc)

    artefact = {
        "model": cal_model, "feature_names": feat_names,
        "encoders": encoders, "best_params": best_params,
        "cv_metrics": {k: float(np.mean(v)) for k, v in cv_metrics.items()},
        "default_rate": float(y.mean()), "n_train": int(len(y)),
    }
    joblib.dump(artefact, MODEL_PATH)
    log.info("Model saved → %s", MODEL_PATH)

    with mlflow.start_run(run_name="commercial_pd_v1"):
        mlflow.log_metric("cv_auc",   mean_auc)
        mlflow.log_metric("cv_ks",    mean_ks)
        mlflow.log_metric("cv_brier", mean_brier)
        mlflow.log_artifact(str(MODEL_PATH))
        mlflow.set_tags({
            "model_name": "commercial_pd_v1",
            "monotone_verification_passed": str(mono_ok).lower(),
        })
        try:
            mlflow.lightgbm.log_model(final_model, "commercial_pd_lgbm", registered_model_name="commercial_pd_v1")
        except Exception as exc:  # noqa: BLE001
            log.warning("MLflow model registration failed (non-fatal): %s", exc)

    gini = 2 * mean_auc - 1
    print("\nCommercial PD Model Summary")
    print("-" * 40)
    print(f"  AUC-ROC : {mean_auc:.4f}")
    print(f"  Gini    : {gini:.4f}")
    print(f"  KS      : {mean_ks:.4f}")
    print(f"  Brier   : {mean_brier:.4f}")
    print(f"  N Train : {len(y):,}")
    print(f"  Def Rate: {y.mean():.2%}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Train Commercial PD model")
    ap.add_argument("--no-tuning", action="store_true")
    ap.add_argument("--sample",    type=int, default=None)
    ap.add_argument("--trials",    type=int, default=N_TRIALS)
    train(ap.parse_args())
