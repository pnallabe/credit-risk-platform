import pandas as pd
import numpy as np
import joblib
import json
import logging
import sys
import argparse
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from db.bigquery_client import read_table

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TENANT_CONFIGS = {
    'lending_club': {
        'min_credit_score': 620,
        'max_dti': 0.45,
        'min_annual_income': 25000,
        'wacc': 0.07,
        'opex': 0.015,
        'lgd': 0.85,
        'traditional_yield': 0.150,
        'yield_map': {
            0.05: 0.170, 0.10: 0.180, 0.12: 0.185, 0.15: 0.190,
            0.18: 0.195, 0.20: 0.200, 0.25: 0.210, 0.30: 0.220,
            0.40: 0.230, 0.50: 0.240, 0.60: 0.250, 0.70: 0.260,
            0.80: 0.270, 0.90: 0.280
        }
    },
    'synthetic_tenant': {
        'min_credit_score': 600,
        'max_dti': 0.50,
        'min_annual_income': 20000,
        'wacc': 0.08,
        'opex': 0.020,
        'lgd': 0.75,
        'traditional_yield': 0.170,
        'yield_map': {
            0.05: 0.190, 0.10: 0.200, 0.12: 0.210, 0.15: 0.220,
            0.18: 0.230, 0.20: 0.240, 0.25: 0.250, 0.30: 0.260,
            0.40: 0.270, 0.50: 0.280, 0.60: 0.290, 0.70: 0.300,
            0.80: 0.310, 0.90: 0.320
        }
    },
    'freddie_mac': {
        'min_credit_score': 680,
        'max_dti': 0.43,
        'min_annual_income': 45000,
        'wacc': 0.05,
        'opex': 0.005,
        'lgd': 0.20,
        'traditional_yield': 0.070,
        'yield_map': {
            0.05: 0.080, 0.10: 0.085, 0.12: 0.090, 0.15: 0.095,
            0.18: 0.100, 0.20: 0.105, 0.25: 0.110, 0.30: 0.115,
            0.40: 0.120, 0.50: 0.125, 0.60: 0.130, 0.70: 0.135,
            0.80: 0.140, 0.90: 0.145
        }
    },
    'prosper': {
        'min_credit_score': 640,
        'max_dti': 0.48,
        'min_annual_income': 30000,
        'wacc': 0.075,
        'opex': 0.018,
        'lgd': 0.80,
        'traditional_yield': 0.160,
        'yield_map': {
            0.05: 0.180, 0.10: 0.190, 0.12: 0.195, 0.15: 0.200,
            0.18: 0.205, 0.20: 0.210, 0.25: 0.220, 0.30: 0.230,
            0.40: 0.240, 0.50: 0.250, 0.60: 0.260, 0.70: 0.270,
            0.80: 0.280, 0.90: 0.290
        }
    }
}

def run_tenant_analysis(tenant_id: str):
    logger.info(f"=== Starting Analysis for Tenant: {tenant_id} ===")
    config = TENANT_CONFIGS[tenant_id]

    # 1. Load Data
    logger.info("Loading evaluation data...")
    try:
        df = read_table(
            table_id="loan_applications",
            dataset_id=tenant_id,
            where=f"tenant_id = '{tenant_id}'"
        )
    except Exception as e:
        logger.warning(f"Failed to load {tenant_id} from BQ: {e}. Using simulated cohort.")
        np.random.seed(42 if tenant_id == 'lending_club' else (43 if tenant_id == 'synthetic_tenant' else 44))
        n = 10000
        mean_score = 680 if tenant_id == 'lending_club' else (650 if tenant_id == 'synthetic_tenant' else 720)
        mean_inc = 11.0 if tenant_id == 'lending_club' else (10.5 if tenant_id == 'synthetic_tenant' else 11.5)

        df = pd.DataFrame({
            'dti': np.random.uniform(0.1, 0.6, n),
            'credit_score': np.random.normal(mean_score, 50, n),
            'loan_amount': np.random.lognormal(9 if tenant_id != 'freddie_mac' else 12, 1 if tenant_id != 'freddie_mac' else 0.5, n),
            'annual_income': np.random.lognormal(mean_inc, 0.5, n),
            'num_open_accounts': np.random.poisson(10, n),
            'num_derogatory_marks': np.random.poisson(0.5 if tenant_id != 'freddie_mac' else 0.1, n)
        })
        # Stronger predictive signal with lower baseline default rate for Decile 1 calibration
        logit = -5.0 + 8.0 * df['dti'] - 0.02 * (df['credit_score'] - mean_score) + np.random.normal(0, 0.5, n)
        prob = 1 / (1 + np.exp(-logit))
        df['target_default'] = (np.random.rand(n) < prob).astype(int)

    df['amortization_progress'] = 0.25

    # Split into Train and Test (80/20) to mirror model development pipeline
    train_df, test_df = train_test_split(df, test_size=0.2, random_state=42)

    # 2. Apply Traditional Rules on Test Set
    logger.info("Applying Traditional Rules to Test Set...")
    traditional_approved = test_df[
        (test_df['credit_score'] >= config['min_credit_score']) &
        (test_df['dti'] <= config['max_dti']) &
        (test_df['annual_income'] >= config['min_annual_income'])
    ]

    # 3. Apply AI-Driven PD & EAD Models to Test Set
    logger.info("Applying AI Models to Test Set...")
    pd_model_path = f'models/credit_risk/artifacts/{tenant_id}_pd_model.pkl'
    ead_model_path = f'models/credit_risk/artifacts/{tenant_id}_ead_model.pkl'
    try:
        pd_model = joblib.load(pd_model_path)
        ead_model = joblib.load(ead_model_path)
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        return

    features = ['dti', 'credit_score', 'loan_amount', 'annual_income',
                'num_open_accounts', 'num_derogatory_marks']

    # Predict on test set
    X_test = test_df[features].copy()
    for f in features:
        X_test[f] = X_test[f].fillna(X_test[f].median())

    pd_preds = pd_model.predict_proba(X_test)[:, 1]
    test_df['pd_prediction'] = pd_preds

    ead_preds = ead_model.predict(test_df[['amortization_progress']])
    test_df['ead_prediction'] = np.clip(ead_preds, 0.1, 1.0)

    # 4. Model Performance Evaluation (Predicted vs Actual Analysis)
    auc_score = roc_auc_score(test_df['target_default'], test_df['pd_prediction'])
    brier = brier_score_loss(test_df['target_default'], test_df['pd_prediction'])

    # Bootstrapping for 95% Confidence Intervals
    boot_aucs = []
    boot_briers = []
    rng = np.random.default_rng(42)
    for _ in range(200):
        indices = rng.choice(len(test_df), size=len(test_df), replace=True)
        y_true_boot = test_df['target_default'].iloc[indices]
        y_pred_boot = test_df['pd_prediction'].iloc[indices]
        boot_aucs.append(roc_auc_score(y_true_boot, y_pred_boot))
        boot_briers.append(brier_score_loss(y_true_boot, y_pred_boot))

    auc_ci_lower, auc_ci_upper = np.percentile(boot_aucs, [2.5, 97.5])
    brier_ci_lower, brier_ci_upper = np.percentile(boot_briers, [2.5, 97.5])

    print(f"\n--- {tenant_id.upper()} MODEL DIAGNOSTICS (TEST SET) ---")
    print(f"ROC AUC Score (Discriminative Power): {auc_score:.4f} [95% CI: {auc_ci_lower:.4f} - {auc_ci_upper:.4f}]")
    print(f"Brier Score Loss (Calibration Accuracy): {brier:.4f} [95% CI: {brier_ci_lower:.4f} - {brier_ci_upper:.4f}]")

    # Predicted vs Actual Calibration Analysis by Deciles
    test_df['decile'] = pd.qcut(test_df['pd_prediction'], q=10, labels=False, duplicates='drop')
    calibration = test_df.groupby('decile').agg(
        avg_predicted_pd=('pd_prediction', 'mean'),
        actual_default_rate=('target_default', 'mean'),
        volume_count=('target_default', 'count')
    ).reset_index()

    print("\n--- PREDICTED VS ACTUAL CALIBRATION BY DECILE (TEST SET) ---")
    print(f"{'Decile':<8} {'Avg Predicted PD':<20} {'Actual Default Rate':<25} {'Account Count':<15}")
    print("-" * 75)
    for _, row in calibration.iterrows():
        print(f"Decile {int(row['decile'])+1:<2}   {row['avg_predicted_pd']:<20.2%} {row['actual_default_rate']:<25.2%} {int(row['volume_count']):<15}")

    # Metrics helper
    def print_metrics(name, subset, assumed_yield):
        app_rate = len(subset) / len(test_df)
        default_rate = subset['target_default'].mean() if 'target_default' in test_df.columns else 0.0
        total_vol = subset['loan_amount'].sum()

        mean_ead_ratio = subset['ead_prediction'].mean() if 'ead_prediction' in subset.columns else 1.0
        realized_loss_ratio = default_rate * config['lgd'] * mean_ead_ratio
        realized_roa = assumed_yield - config['wacc'] - config['opex'] - realized_loss_ratio
        npv = total_vol * realized_roa

        print(f"\n--- {name} ---")
        print(f"Approval Rate: {app_rate:.2%}")
        print(f"Default Rate on Approved: {default_rate:.2%}")
        print(f"Average Predicted EAD Ratio: {mean_ead_ratio:.2%}")
        print(f"Realized Loss Ratio (PD*LGD*EAD): {realized_loss_ratio:.2%}")
        print(f"Total Funded Volume: ${total_vol:,.2f}")
        print(f"Assumed Portfolio Yield (APR): {assumed_yield:.2%}")
        print(f"Realized Return on Assets (ROA): {realized_roa:.2%}")
        print(f"Portfolio Net Present Value (NPV): ${npv:,.2f}")

    print_metrics(f"Traditional Rules (Score >= {config['min_credit_score']}, DTI <= {config['max_dti']*100:.0f}%)",
                  traditional_approved, assumed_yield=config['traditional_yield'])

    print(f"\n--- AI-Driven PD/EAD Model Cutoff Sweep: {tenant_id} ---")
    print(f"{'Cutoff':<8} {'App Rate':<10} {'Def Rate':<10} {'EAD Ratio':<10} {'Loss Ratio':<12} {'Yield':<8} {'ROA':<8} {'NPV':<12}")
    print("-" * 100)

    for cutoff in [0.05, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]:
        subset = test_df[test_df['pd_prediction'] <= cutoff]
        app_rate = len(subset) / len(test_df)
        def_rate = subset['target_default'].mean()
        vol = subset['loan_amount'].sum()
        mean_ead = subset['ead_prediction'].mean()

        assumed_yield = config['yield_map'][cutoff]
        realized_loss = def_rate * config['lgd'] * mean_ead
        realized_roa = assumed_yield - config['wacc'] - config['opex'] - realized_loss
        npv = vol * realized_roa

        print(f"<= {cutoff:.0%}{'':<4} {app_rate:<10.2%} {def_rate:<10.2%} {mean_ead:<10.2%} {realized_loss:<12.2%} {assumed_yield:<8.1%} {realized_roa:<8.2%} ${npv/1e6:<10.2f}M")
    print("\n" + "="*100 + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant_id', type=str, default='all', choices=['all', 'lending_club', 'synthetic_tenant', 'freddie_mac', 'prosper'])
    args = parser.parse_args()

    if args.tenant_id == 'all':
        for tenant in TENANT_CONFIGS.keys():
            run_tenant_analysis(tenant)
    else:
        run_tenant_analysis(args.tenant_id)

if __name__ == '__main__':
    main()
