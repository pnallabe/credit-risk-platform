"""
Credit Card PD Model — Training Script
=======================================
Trains a LightGBM Probability-of-Default model on the 5 M-record
synthetic credit card dataset.

Pipeline
--------
  1.  Load  data/raw/cc_pd/pd_training_5m.parquet
  2.  Feature engineering + encoding
  3.  Stratified 5-fold cross-validation with Optuna HPO
  4.  Full-data final model
  5.  Score card binning (20 score bands)
  6.  MLflow experiment logging
  7.  Artefact export → models/credit_risk/cc_pd_model_v1.pkl

Usage
-----
    python models/credit_risk/train_cc_pd_model.py
    python models/credit_risk/train_cc_pd_model.py --no-tuning
    python models/credit_risk/train_cc_pd_model.py --sample 200_000
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
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

PROJECT_ROOT = Path(__file__).parents[2]
DATA_PATH    = PROJECT_ROOT / "data" / "raw" / "cc_pd" / "pd_training_5m.parquet"
MODEL_DIR    = Path(__file__).parent
MODEL_PATH   = MODEL_DIR / "cc_pd_model_v1.pkl"
SCORECARD_PATH = MODEL_DIR / "cc_pd_scorecard.json"
IMPORTANCE_PLOT = MODEL_DIR / "cc_pd_feature_importance.png"
KS_PLOT         = MODEL_DIR / "cc_pd_ks_curve.png"
CALIB_PLOT      = MODEL_DIR / "cc_pd_calibration.png"
MLFLOW_URI      = str(PROJECT_ROOT / "mlruns")

N_SPLITS = 5
N_TRIALS = 40          # Optuna trials; reduce with --no-tuning

# ── Feature sets ─────────────────────────────────────────────────────────────

CATEGORICAL_COLS = [
    "product", "risk_grade", "state", "employment_status", "app_channel",
]

NUMERIC_COLS = [
    # Bureau / underwriting
    "fico_score", "dti", "annual_income", "emp_years",
    "num_open_trades", "num_derog_marks", "months_oldest_trade",
    "inq_last_6m", "pct_rev_utilization", "num_bankruptcy",
    "months_since_last_delinq", "credit_limit", "apr", "annual_fee", "age",
    # Behavioural (12-month)
    "avg_utilization_12m", "max_utilization_12m", "end_utilization_12m",
    "total_purchases_12m", "num_purchase_txns_12m",
    "cash_advance_total_12m", "num_cash_adv_txns_12m",
    "num_missed_pmts_12m", "pct_ontime_pmts_12m",
    "avg_balance_12m", "min_payment_ratio_12m", "overlimit_months_12m",
    "late_fees_12m", "interest_charged_12m",
    # Derived interactions
    "fico_dti_interaction", "util_miss_interaction",
    "log_income", "credit_limit_to_income", "spend_to_income",
    "balance_to_limit", "inq_per_trade", "months_on_book",
]

BOOL_COLS = ["has_cash_advance", "autopay_enrolled", "attrition_flag"]

TARGET = "default_flag"


# ── Monotone constraint map ────────────────────────────────────────────────────
# Maps each feature name to its expected monotone direction w.r.t. PD:
#   +1 = higher value → lower  PD (protective)
#   -1 = higher value → higher PD (risk-increasing)
#    0 = no constraint (categoricals encoded as int, interactions, or ambiguous)
#
# Enforcing these constraints prevents the model from producing non-intuitive
# regions (e.g., higher FICO → higher PD) that would be challenged in a CFPB
# examination for potential proxy discrimination.
MONOTONE_CONSTRAINT_MAP: dict[str, int] = {
    # Bureau / underwriting
    "fico_score":              1,     # higher FICO → lower PD
    "dti":                    -1,     # higher DTI → higher PD
    "annual_income":           1,     # higher income → lower PD
    "emp_years":               1,     # more employment history → lower PD
    "num_open_trades":         0,     # ambiguous (more trades can mean more exposure)
    "num_derog_marks":        -1,     # more derogatory marks → higher PD
    "months_oldest_trade":     1,     # older credit history (seasoning) → lower PD
    "inq_last_6m":            -1,     # more recent inquiries → higher PD
    "pct_rev_utilization":    -1,     # higher revolving utilization → higher PD
    "num_bankruptcy":         -1,     # more bankruptcies → higher PD
    "months_since_last_delinq": 1,    # more months since delinq → lower PD
    "credit_limit":            1,     # higher approved limit → better quality → lower PD
    "apr":                    -1,     # risk-priced APR — higher rate signals higher risk tier
    "annual_fee":              0,     # product-tier driven, not pure risk directional
    "age":                     0,     # U-shaped with PD; no clean monotone direction
    # Behavioural (12-month)
    "avg_utilization_12m":    -1,     # higher average utilization → higher PD
    "max_utilization_12m":    -1,     # higher peak utilization → higher PD
    "end_utilization_12m":    -1,     # higher ending utilization → higher PD
    "total_purchases_12m":     0,     # high spend: can be engagement or stress
    "num_purchase_txns_12m":   0,     # ambiguous
    "cash_advance_total_12m": -1,     # cash advances signal liquidity stress → higher PD
    "num_cash_adv_txns_12m":  -1,     # frequent cash advances → higher PD
    "num_missed_pmts_12m":    -1,     # more missed payments → higher PD (direct signal)
    "pct_ontime_pmts_12m":     1,     # higher on-time payment rate → lower PD
    "avg_balance_12m":         0,     # high balance: high usage or high risk (ambiguous)
    "min_payment_ratio_12m":   1,     # paying above minimum → lower PD
    "overlimit_months_12m":   -1,     # months over credit limit → higher PD
    "late_fees_12m":          -1,     # more late fees → higher PD
    "interest_charged_12m":    0,     # high interest: high balance or high APR (ambiguous)
    # Derived interactions (no clean single direction)
    "fico_dti_interaction":    0,
    "util_miss_interaction":   0,
    "log_income":              1,     # higher log-income → lower PD
    "credit_limit_to_income":  1,     # higher CL-to-income → better credit quality
    "spend_to_income":         0,     # high spend-to-income: engagement or stress (ambiguous)
    "balance_to_limit":       -1,     # higher balance-to-limit → higher utilization risk
    "inq_per_trade":          -1,     # more inquiries per trade → higher risk signal
    "months_on_book":          1,     # longer relationship (seasoning) → lower PD
    # Categorical (label-encoded; ordinal direction undefined)
    "product":                 0,
    "risk_grade":              0,
    "state":                   0,
    "employment_status":       0,
    "app_channel":             0,
    # Boolean features
    "has_cash_advance":       -1,     # using cash advances → higher PD
    "autopay_enrolled":        1,     # autopay enrolled → lower PD (payment discipline)
    "attrition_flag":          0,     # attrition direction is ambiguous w.r.t. PD
}


# ── Monotonicity verification ─────────────────────────────────────────────────

from dataclasses import dataclass as _dc  # noqa: E402

@_dc
class MonotonicityCheckResult:
    """Result of sweeping one feature across its range while holding others at median."""
    feature: str
    constraint_dir: int        # +1 or -1
    passes: bool
    min_delta: float           # smallest step in expected direction (negative = violation)
    max_delta: float


def verify_monotonicity(
    model,
    X: np.ndarray,
    feat_names: list[str],
    tolerance: float = 1e-5,
) -> list[MonotonicityCheckResult]:
    """Sweep each constrained feature from p5 to p95, others held at median.

    Raises ValueError if any constrained feature violates monotonicity.
    Returns list of MonotonicityCheckResult for all constrained features.
    """
    results: list[MonotonicityCheckResult] = []

    # Baseline row: all features at their column-wise median
    medians = np.nanmedian(X, axis=0)

    for i, feat in enumerate(feat_names):
        direction = MONOTONE_CONSTRAINT_MAP.get(feat, 0)
        if direction == 0:
            continue

        p5 = float(np.nanpercentile(X[:, i], 5))
        p95 = float(np.nanpercentile(X[:, i], 95))

        if abs(p95 - p5) < 1e-9:
            # Feature has no variance in this dataset — skip silently
            continue

        sweep_values = np.linspace(p5, p95, 30)
        sweep_matrix = np.tile(medians, (len(sweep_values), 1))
        sweep_matrix[:, i] = sweep_values.astype(np.float32)

        preds = model.predict_proba(sweep_matrix.astype(np.float32))[:, 1]
        deltas = np.diff(preds)  # positive = PD increases as feature increases

        if direction == 1:
            # Expect PD to decrease as feature increases → deltas should be <= tolerance
            min_d = float(np.min(deltas))
            max_d = float(np.max(deltas))
            passes = bool(min_d >= -tolerance)
        else:  # direction == -1
            # Expect PD to increase as feature increases → deltas should be >= -tolerance
            min_d = float(np.min(deltas))
            max_d = float(np.max(deltas))
            passes = bool(max_d <= tolerance)

        results.append(MonotonicityCheckResult(
            feature=feat,
            constraint_dir=direction,
            passes=passes,
            min_delta=min_d,
            max_delta=max_d,
        ))

    failures = [r for r in results if not r.passes]
    if failures:
        msg = "Monotonicity violations detected:\n" + "\n".join(
            f"  {r.feature} (dir={r.constraint_dir}): min_delta={r.min_delta:.6f}, max_delta={r.max_delta:.6f}"
            for r in failures
        )
        raise ValueError(msg)

    log.info("Monotonicity check passed for %d constrained features.", len(results))
    return results


# ── Data loading + preprocessing ──────────────────────────────────────────────

def load_and_prep(path: Path, sample: int | None = None) -> tuple[pd.DataFrame, dict]:
    log.info("Loading %s …", path)
    df = pd.read_parquet(path)

    if sample and sample < len(df):
        log.info("  Sampling %d rows (stratified) …", sample)
        from sklearn.model_selection import train_test_split
        df, _ = train_test_split(df, train_size=sample, stratify=df[TARGET], random_state=42)

    log.info("  Rows: {:,}  |  default rate: {:.2f}%"
             .format(len(df), df[TARGET].mean() * 100))

    # Label-encode categoricals
    encoders: dict[str, LabelEncoder] = {}
    for col in CATEGORICAL_COLS:
        le = LabelEncoder()
        df[col] = le.fit_transform(df[col].astype(str))
        encoders[col] = le

    # Boolean → int
    for col in BOOL_COLS:
        df[col] = df[col].astype(int)

    # Drop non-feature columns
    drop_cols = [
        "account_id", "orig_date", "true_pd",
        "total_revenue_12m", "interchange_rev_12m",
    ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    return df, encoders


def feature_matrix(df: pd.DataFrame):
    all_cols = NUMERIC_COLS + CATEGORICAL_COLS + BOOL_COLS
    X = df[[c for c in all_cols if c in df.columns]].values.astype(np.float32)
    y = df[TARGET].values.astype(int)
    return X, y, [c for c in all_cols if c in df.columns]


# ── Optuna objective ──────────────────────────────────────────────────────────

def _objective(trial, X, y, feat_names: list[str]):
    constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    params = dict(
        n_estimators     = trial.suggest_int("n_estimators", 400, 2000, step=100),
        learning_rate    = trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
        max_depth        = trial.suggest_int("max_depth", 4, 9),
        num_leaves       = trial.suggest_int("num_leaves", 31, 255),
        min_child_samples= trial.suggest_int("min_child_samples", 50, 500),
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


# ── Score card binning ────────────────────────────────────────────────────────

def build_scorecard(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 20) -> pd.DataFrame:
    """
    Produce a scorecard table mapping score band → volume, default rate,
    cumulative default capture, odds, and LN(odds) for regulatory review.
    """
    df = pd.DataFrame({"prob": y_prob, "default": y_true})
    df["score_band"] = pd.qcut(df["prob"], q=n_bins, duplicates="drop", labels=False)
    df["score_band"] = n_bins - df["score_band"]  # invert so band 1 = lowest risk

    tbl = (
        df.groupby("score_band")
          .agg(
              accounts    = ("default", "count"),
              defaults    = ("default", "sum"),
              min_prob    = ("prob",    "min"),
              max_prob    = ("prob",    "max"),
          )
          .reset_index()
    )
    tbl["default_rate"]   = tbl["defaults"] / tbl["accounts"]
    tbl["cum_def_pct"]    = tbl["defaults"].cumsum() / tbl["defaults"].sum() * 100
    tbl["cum_acct_pct"]   = tbl["accounts"].cumsum() / tbl["accounts"].sum() * 100
    tbl["odds"]           = (1 - tbl["default_rate"]) / tbl["default_rate"].clip(1e-6)
    tbl["ln_odds"]        = np.log(tbl["odds"].clip(1e-6))
    tbl["pct_of_book"]    = tbl["accounts"] / tbl["accounts"].sum() * 100
    return tbl


# ── Diagnostics plots ─────────────────────────────────────────────────────────

def plot_ks(y_true, y_prob, path: Path) -> float:
    thresholds = np.linspace(0, 1, 300)
    tpr = [np.mean(y_prob[y_true == 1] <= t) for t in thresholds]
    fpr = [np.mean(y_prob[y_true == 0] <= t) for t in thresholds]
    ks  = float(np.max(np.abs(np.array(tpr) - np.array(fpr))))
    idx = int(np.argmax(np.abs(np.array(tpr) - np.array(fpr))))

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(thresholds, tpr, color="red",  label="Default (CDF)")
    ax.plot(thresholds, fpr, color="blue", label="Non-default (CDF)")
    ax.axvline(thresholds[idx], color="green", linestyle="--",
               label=f"KS = {ks:.3f}")
    ax.fill_between(thresholds, tpr, fpr, alpha=0.12, color="green")
    ax.set_xlabel("PD Score")
    ax.set_ylabel("Cumulative proportion")
    ax.set_title("KS Curve — CC PD Model v1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return ks


def plot_feature_importance(model, feat_names: list[str], path: Path) -> None:
    imp = pd.Series(model.feature_importances_, index=feat_names).sort_values(ascending=True)
    top = imp.tail(30)
    fig, ax = plt.subplots(figsize=(10, 9))
    top.plot(kind="barh", ax=ax, color="steelblue")
    ax.set_title("Top-30 Feature Importances — CC PD Model v1")
    ax.set_xlabel("Importance (gain)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_calibration(y_true, y_prob, path: Path) -> None:
    frac_pos, mean_pred = calibration_curve(y_true, y_prob, n_bins=20, strategy="quantile")
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(mean_pred, frac_pos, "s-", label="Model", color="steelblue")
    ax.plot([0, 1], [0, 1], "k--", label="Perfect calibration")
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Fraction of positives")
    ax.set_title("Calibration Plot — CC PD Model v1")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ── Main training routine ─────────────────────────────────────────────────────

def train(args) -> None:
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment("cc_pd_model")

    df, encoders = load_and_prep(DATA_PATH, sample=args.sample)

    # ── P1.3: Data quality gate — must pass before feature engineering ─────
    from data_quality import run_expectations, assert_quality_gate, save_report
    from data_quality import CC_PD_TRAINING_RULES
    dq_report = run_expectations(df, CC_PD_TRAINING_RULES, "cc_pd_training")
    dq_report_path = save_report(dq_report, PROJECT_ROOT / "reports" / "data_quality")
    log.info("Data quality report: %s", dq_report_path)
    assert_quality_gate(dq_report)   # aborts training if ERROR rules fail
    # ──────────────────────────────────────────────────────────────────────

    X, y, feat_names = feature_matrix(df)
    log.info("Feature matrix: %s  |  positive rate: %.2f%%", X.shape, y.mean() * 100)

    # ── Build monotone constraint vector (aligned to feat_names) ──────────
    monotone_constraints = [MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names]
    n_constrained = sum(1 for c in monotone_constraints if c != 0)
    log.info(
        "Monotone constraints: %d/%d features constrained (%d protective, %d risk-increasing)",
        n_constrained, len(feat_names),
        sum(1 for c in monotone_constraints if c == 1),
        sum(1 for c in monotone_constraints if c == -1),
    )

    # ── Hyperparameter search ──────────────────────────────────────────────
    if args.no_tuning:
        best_params = dict(
            n_estimators=800, learning_rate=0.05, max_depth=7, num_leaves=127,
            min_child_samples=200, subsample=0.8, colsample_bytree=0.8,
            reg_alpha=0.1, reg_lambda=1.0,
            monotone_constraints=monotone_constraints,
            class_weight="balanced",
            random_state=42, verbose=-1, n_jobs=-1,
        )
        log.info("Skipping Optuna — using default params.")
    else:
        log.info("Running Optuna HPO (%d trials) …", N_TRIALS)
        study = optuna.create_study(direction="maximize",
                                    sampler=optuna.samplers.TPESampler(seed=42))
        study.optimize(lambda t: _objective(t, X, y, feat_names), n_trials=N_TRIALS,
                       n_jobs=1, show_progress_bar=False)
        best_params = study.best_params
        best_params.update({
            "monotone_constraints": monotone_constraints,
            "class_weight": "balanced", "random_state": 42,
            "verbose": -1, "n_jobs": -1,
        })
        log.info("Best CV AUC: %.4f  |  params: %s", study.best_value, best_params)

    # ── P3.4: Optional reject inference augmentation ─────────────────────
    sample_weight = None
    reject_inference_method = None
    bias_adjustment_factor = None

    if getattr(args, "reject_inference", False):
        if not getattr(args, "rejected_data_path", None):
            raise SystemExit("--rejected-data-path is required when --reject-inference is enabled")

        rejected_path = Path(str(args.rejected_data_path))
        if not rejected_path.exists():
            raise SystemExit(f"Rejected data path not found: {rejected_path}")

        if rejected_path.suffix.lower() in {".parquet", ".pq"}:
            rejected_df = pd.read_parquet(rejected_path)
        else:
            rejected_df = pd.read_csv(rejected_path)

        if TARGET in rejected_df.columns:
            raise SystemExit("rejected_df must NOT contain default_flag")

        # Apply the training encoders to the rejected dataset.
        def _encode_with_existing(le: LabelEncoder, series: pd.Series) -> pd.Series:
            mapping = {cls: i for i, cls in enumerate(le.classes_)}
            return series.astype(str).map(mapping).fillna(-1).astype(int)

        rej = rejected_df.copy()
        for col, le in encoders.items():
            if col not in rej.columns:
                rej[col] = "unknown"
            rej[col] = _encode_with_existing(le, rej[col])

        for col in BOOL_COLS:
            if col not in rej.columns:
                rej[col] = 0
            rej[col] = rej[col].astype(int)

        for col in NUMERIC_COLS:
            if col not in rej.columns:
                rej[col] = 0.0

        drop_cols = [
            "account_id", "orig_date", "true_pd",
            "total_revenue_12m", "interchange_rev_12m",
        ]
        rej.drop(columns=[c for c in drop_cols if c in rej.columns], inplace=True)

        # Fit a "current" model on approved/booked data to score rejects.
        scorer = lgb.LGBMClassifier(**best_params)
        scorer.fit(X, y)

        class _DFModelWrapper:
            def __init__(self, model, feature_cols: list[str]):
                self._model = model
                self._cols = list(feature_cols)

            def predict_proba(self, df_like):  # noqa: ANN001
                if isinstance(df_like, pd.DataFrame):
                    X_local = df_like.reindex(columns=self._cols, fill_value=0.0).values.astype(np.float32)
                else:
                    X_local = df_like
                return self._model.predict_proba(X_local)

        wrapper = _DFModelWrapper(scorer, feat_names)

        from models.credit_risk.reject_inference import (
            RejectInferenceConfig,
            run_reject_inference,
            save_summary,
        )

        ri_cfg = RejectInferenceConfig(
            method=str(args.reject_inference_method),
            augmentation_weight=float(args.augmentation_weight),
            parceling_threshold_bad=float(args.parceling_threshold_bad),
            random_seed=42,
        )

        approved_for_ri = df.reindex(columns=feat_names + [TARGET]).copy()
        rejected_for_ri = rej.reindex(columns=feat_names).copy()

        augmented_df, ri_summary = run_reject_inference(approved_for_ri, rejected_for_ri, wrapper, ri_cfg)
        save_summary(ri_summary, PROJECT_ROOT / "reports" / "reject_inference_summary.json")
        log.info(
            "Reject inference applied: method=%s bias_adjustment_factor=%.4f",
            ri_summary.method,
            ri_summary.bias_adjustment_factor if ri_summary.bias_adjustment_factor != float("inf") else -1,
        )

        reject_inference_method = ri_summary.method
        bias_adjustment_factor = ri_summary.bias_adjustment_factor

        df = augmented_df
        X, y, feat_names = feature_matrix(df)
        sample_weight = df["sample_weight"].values.astype(float)

    # ── 5-fold cross-validation ────────────────────────────────────────────
    log.info("5-fold CV evaluation …")
    skf  = StratifiedKFold(n_splits=N_SPLITS, shuffle=True, random_state=42)
    cv_metrics: dict[str, list] = {"auc": [], "ks": [], "brier": [], "logloss": [], "ap": []}
    oof_prob = np.zeros(len(y), dtype=np.float32)

    for fold, (tr_idx, val_idx) in enumerate(skf.split(X, y)):
        m = lgb.LGBMClassifier(**best_params)
        if sample_weight is None:
            m.fit(X[tr_idx], y[tr_idx])
        else:
            m.fit(X[tr_idx], y[tr_idx], sample_weight=sample_weight[tr_idx])
        prob = m.predict_proba(X[val_idx])[:, 1]
        oof_prob[val_idx] = prob

        auc  = roc_auc_score(y[val_idx], prob)
        ks   = ks_2samp(prob[y[val_idx] == 1], prob[y[val_idx] == 0]).statistic
        br   = brier_score_loss(y[val_idx], prob)
        ll   = log_loss(y[val_idx], prob)
        ap   = average_precision_score(y[val_idx], prob)

        cv_metrics["auc"].append(auc)
        cv_metrics["ks"].append(ks)
        cv_metrics["brier"].append(br)
        cv_metrics["logloss"].append(ll)
        cv_metrics["ap"].append(ap)
        log.info("  Fold %d → AUC %.4f | KS %.4f | Brier %.4f | AP %.4f",
                 fold + 1, auc, ks, br, ap)

    mean_auc    = float(np.mean(cv_metrics["auc"]))
    mean_ks     = float(np.mean(cv_metrics["ks"]))
    mean_brier  = float(np.mean(cv_metrics["brier"]))
    mean_logloss= float(np.mean(cv_metrics["logloss"]))
    mean_ap     = float(np.mean(cv_metrics["ap"]))
    log.info("CV Summary → AUC %.4f ± %.4f | KS %.4f | Brier %.4f",
             mean_auc, np.std(cv_metrics["auc"]), mean_ks, mean_brier)

    # ── Train final model on full data ────────────────────────────────────
    log.info("Training final model on full dataset …")
    final_model = lgb.LGBMClassifier(**best_params)
    if sample_weight is None:
        final_model.fit(X, y)
    else:
        final_model.fit(X, y, sample_weight=sample_weight)

    # Isotonic calibration for well-calibrated PD output
    log.info("Isotonic calibration …")
    cal_model = CalibratedClassifierCV(final_model, method="isotonic", cv="prefit")
    if sample_weight is None:
        cal_model.fit(X, y)
    else:
        cal_model.fit(X, y, sample_weight=sample_weight)

    y_prob_cal = cal_model.predict_proba(X)[:, 1]

    # ── Monotonicity verification ──────────────────────────────────────────
    log.info("Verifying monotonic constraints …")
    try:
        mono_results = verify_monotonicity(cal_model, X, feat_names)
        mono_ok = True
    except ValueError as exc:
        log.error("Monotonicity check FAILED: %s", exc)
        mono_ok = False
        mono_results = []

    # ── Score card ─────────────────────────────────────────────────────────
    log.info("Generating scorecard …")
    scorecard = build_scorecard(y, y_prob_cal)
    scorecard.to_json(SCORECARD_PATH, orient="records", indent=2)
    log.info("  Scorecard written → %s", SCORECARD_PATH)

    # ── Plots ──────────────────────────────────────────────────────────────
    ks_val = plot_ks(y, y_prob_cal, KS_PLOT)
    plot_feature_importance(final_model, feat_names, IMPORTANCE_PLOT)
    plot_calibration(y, y_prob_cal, CALIB_PLOT)
    log.info("  Plots saved to %s", MODEL_DIR)

    # ── Persist artefact ───────────────────────────────────────────────────
    artefact = {
        "model"           : cal_model,
        "feature_names"   : feat_names,
        "encoders"        : encoders,
        "best_params"     : best_params,
        "cv_metrics"      : {k: float(np.mean(v)) for k, v in cv_metrics.items()},
        "default_rate"    : float(y.mean()),
        "n_train"         : int(len(y)),
        "monotone_constraints": monotone_constraints,
        "monotone_constraint_map": {f: MONOTONE_CONSTRAINT_MAP.get(f, 0) for f in feat_names},
    }
    joblib.dump(artefact, MODEL_PATH)
    log.info("Model saved → %s", MODEL_PATH)

    # ── Write model card JSON ──────────────────────────────────────────────
    model_card = {
        "model_id": "cc_pd_model_v1",
        "model_name": "Credit Card Probability of Default",
        "model_type": "Classification — Binary (Default / No Default)",
        "feature_count": len(feat_names),
        "cv_metrics": artefact["cv_metrics"],
        "default_rate": artefact["default_rate"],
        "n_train": artefact["n_train"],
        "monotone_constraints": {
            "vector": monotone_constraints,
            "feature_map": artefact["monotone_constraint_map"],
            "n_constrained": n_constrained,
            "verification_passed": mono_ok,
            "verification_results": [
                {
                    "feature": r.feature,
                    "constraint_dir": r.constraint_dir,
                    "passes": r.passes,
                    "min_delta": r.min_delta,
                    "max_delta": r.max_delta,
                }
                for r in mono_results
            ],
        },
        "reject_inference": {
            "enabled": bool(reject_inference_method is not None),
            "method": reject_inference_method,
            "bias_adjustment_factor": bias_adjustment_factor,
        },
        "limitations": [
            "Trained on synthetic data; real-world performance may differ.",
            "Reject inference not applied; may underestimate risk in declined segments."
            if reject_inference_method is None
            else "Reject inference applied to reduce booked-only training bias.",
            "Does not incorporate macroeconomic covariates.",
        ],
        "assumptions": [
            {
                "id": "A001",
                "description": "LGD assumed 65–85% based on industry benchmarks (hardcoded in policy).",
                "sensitivity": "HIGH — 20pp LGD change shifts break-even PD by ~3pp",
                "review_trigger": "Annual / on significant rate environment change",
            },
            {
                "id": "A002",
                "description": "Cost of funds assumed 4% fixed in origination policy.",
                "sensitivity": "MEDIUM — 100bps rate change shifts break-even PD by ~1pp",
                "review_trigger": "Quarterly for institutions with floating-rate funding",
            },
        ],
    }
    MODEL_CARD_PATH = MODEL_DIR / "cc_pd_model_card.json"
    MODEL_CARD_PATH.write_text(json.dumps(model_card, indent=2))
    log.info("Model card written → %s", MODEL_CARD_PATH)

    # ── MLflow run ─────────────────────────────────────────────────────────
    log.info("Logging to MLflow …")
    with mlflow.start_run(run_name="cc_pd_model_v1") as run:
        # ── P3.3: OpenLineage START emission (best-effort) ───────────────
        try:
            from feature_pipeline.lineage import LineageClient, feature_store_dataset, model_training_dataset

            feature_version = os.getenv("FEATURE_SET_VERSION", "unknown")
            feature_as_of_date = os.getenv("FEATURE_AS_OF_DATE", "unknown")
            lc = LineageClient(
                transport=os.getenv("OPENLINEAGE_TRANSPORT", "console"),
                endpoint=os.getenv("OPENLINEAGE_ENDPOINT"),
                api_key=os.getenv("OPENLINEAGE_API_KEY"),
            )
            lc.emit_dataset_event(
                run_id=str(run.info.run_id),
                job_name="cc_pd_model.train",
                inputs=[feature_store_dataset(feature_version, feature_as_of_date)],
                outputs=[model_training_dataset(str(run.info.run_id), "cc_pd_model")],
                event_type="START",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Lineage START emission failed (suppressed): %s", exc)

        mlflow.log_params(best_params)
        mlflow.log_metric("cv_auc",         mean_auc)
        mlflow.log_metric("cv_ks",          mean_ks)
        mlflow.log_metric("cv_brier",       mean_brier)
        mlflow.log_metric("cv_logloss",     mean_logloss)
        mlflow.log_metric("cv_avg_prec",    mean_ap)
        mlflow.log_metric("final_ks",       ks_val)
        mlflow.log_metric("n_train",        len(y))
        mlflow.log_metric("default_rate",   float(y.mean()))
        mlflow.log_artifact(str(MODEL_PATH))
        mlflow.log_artifact(str(SCORECARD_PATH))
        mlflow.log_artifact(str(KS_PLOT))
        mlflow.log_artifact(str(IMPORTANCE_PLOT))
        mlflow.log_artifact(str(CALIB_PLOT))
        mlflow.log_artifact(str(MODEL_CARD_PATH))
        mlflow.set_tags({
            "dataset": "cc_pd_5m_synthetic",
            "version": "v1",
            "monotone_constraints_applied": "true",
            "monotone_verification_passed": str(mono_ok).lower(),
            "n_constrained_features": str(n_constrained),
        })

        if reject_inference_method is not None:
            mlflow.set_tags({
                "reject_inference_method": str(reject_inference_method),
                "bias_adjustment_factor": str(bias_adjustment_factor),
            })

        # ── P3.3: OpenLineage COMPLETE emission (best-effort) ────────────
        try:
            from feature_pipeline.lineage import LineageClient, feature_store_dataset, model_training_dataset

            feature_version = os.getenv("FEATURE_SET_VERSION", "unknown")
            feature_as_of_date = os.getenv("FEATURE_AS_OF_DATE", "unknown")
            lc = LineageClient(
                transport=os.getenv("OPENLINEAGE_TRANSPORT", "console"),
                endpoint=os.getenv("OPENLINEAGE_ENDPOINT"),
                api_key=os.getenv("OPENLINEAGE_API_KEY"),
            )
            lc.emit_dataset_event(
                run_id=str(run.info.run_id),
                job_name="cc_pd_model.train",
                inputs=[feature_store_dataset(feature_version, feature_as_of_date)],
                outputs=[model_training_dataset(str(run.info.run_id), "cc_pd_model")],
                event_type="COMPLETE",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Lineage COMPLETE emission failed (suppressed): %s", exc)

    log.info("=" * 60)
    log.info("Training complete.")
    log.info("  CV AUC  : %.4f", mean_auc)
    log.info("  CV KS   : %.4f", mean_ks)
    log.info("  CV Brier: %.4f", mean_brier)
    log.info("  Model   : %s", MODEL_PATH)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-tuning", action="store_true",
                    help="Skip Optuna and use default params")
    ap.add_argument("--sample", type=int, default=None,
                    help="Sub-sample N rows for faster dev runs")
    ap.add_argument("--reject-inference", action="store_true", default=False,
                    help="Enable reject inference using a rejected-applications dataset")
    ap.add_argument("--rejected-data-path", default=None,
                    help="Path to rejected applications CSV/Parquet (no default_flag column)")
    ap.add_argument("--reject-inference-method", choices=["augmentation", "parceling"],
                    default="augmentation")
    ap.add_argument("--augmentation-weight", type=float, default=0.5)
    ap.add_argument("--parceling-threshold-bad", type=float, default=0.5)
    train(ap.parse_args())
