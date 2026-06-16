import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_squared_error, mean_absolute_error
from sklearn.model_selection import train_test_split
import joblib
import json
import logging
import os
import datetime

try:
    import mlflow
except ImportError:
    mlflow = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def load_synthetic_data(n=500):
    np.random.seed(42)
    loan_amounts = np.random.lognormal(mean=10, sigma=1, size=n)
    collateral_ltv = np.random.uniform(0.5, 1.5, size=n)

    # Simulate recovery amount: higher LTV -> lower recovery -> higher LGD
    base_recovery_rate = np.clip(1.2 - collateral_ltv, 0.0, 1.0)
    noise = np.random.normal(0, 0.1, size=n)
    recovery_rate = np.clip(base_recovery_rate + noise, 0.0, 1.0)
    recovery_amounts = loan_amounts * recovery_rate

    df = pd.DataFrame({
        'loan_amount': loan_amounts,
        'recovery_amount': recovery_amounts,
        'collateral_type': np.random.choice(['real_estate', 'vehicle', 'none'], n),
        'collateral_ltv': collateral_ltv,
        'time_in_default_months': np.random.randint(1, 24, n),
        'product_type': np.random.choice(['auto', 'personal', 'mortgage'], n),
        'borrower_state': np.random.choice(['CA', 'TX', 'NY', 'FL'], n)
    })

    # Calculate target LGD
    df['lgd_target'] = np.clip(1.0 - (df['recovery_amount'] / df['loan_amount']), 0.0, 1.0)
    return df

def feature_engineering(df):
    df_features = pd.DataFrame()

    # collateral_coverage_ratio = 1 / collateral_ltv (if ltv > 0)
    df_features['collateral_coverage_ratio'] = np.where(df['collateral_ltv'] > 0, 1.0 / df['collateral_ltv'], 0.0)

    df_features['secured_flag'] = (df['collateral_type'] != 'none').astype(int)
    df_features['log_loan_amount'] = np.log1p(df['loan_amount'])

    # One-hot encode product_type, simplified mapping
    df_features['is_auto'] = (df['product_type'] == 'auto').astype(int)
    df_features['is_personal'] = (df['product_type'] == 'personal').astype(int)
    df_features['is_mortgage'] = (df['product_type'] == 'mortgage').astype(int)

    # Keep the original collateral_ltv as it's the constraint target
    df_features['collateral_ltv'] = df['collateral_ltv']

    feature_cols = [
        'collateral_coverage_ratio', 'secured_flag', 'log_loan_amount',
        'is_auto', 'is_personal', 'is_mortgage', 'collateral_ltv'
    ]

    return df_features[feature_cols], df['lgd_target'], feature_cols

def update_model_card(mse, mae):
    card_path = 'models/credit_risk/lgd_model_card.json'
    if os.path.exists(card_path):
        with open(card_path, 'r') as f:
            card = json.load(f)
    else:
        card = {}

    card['metrics'] = {
        'rmse': float(np.sqrt(mse)),
        'mae': float(mae)
    }
    card['training_date'] = datetime.datetime.now().isoformat()
    card['status'] = 'trained'

    with open(card_path, 'w') as f:
        json.dump(card, f, indent=2)

def train_lgd_model():
    logger.info("Loading synthetic LGD data...")
    df = load_synthetic_data(500)

    X, y, feature_cols = feature_engineering(df)

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Monotonicity constraints: +1 for collateral_ltv, 0 for others
    # collateral_ltv is the last feature
    monotone_constraints = tuple([1 if col == 'collateral_ltv' else 0 for col in feature_cols])

    model = xgb.XGBRegressor(
        objective='reg:squarederror',
        n_estimators=50,
        max_depth=3,
        learning_rate=0.1,
        monotone_constraints=monotone_constraints,
        random_state=42
    )

    logger.info("Training XGBoost LGD model...")
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    # Enforce bounds
    preds = np.clip(preds, 0.05, 0.95)

    mse = mean_squared_error(y_test, preds)
    mae = mean_absolute_error(y_test, preds)
    logger.info(f"LGD Model - RMSE: {np.sqrt(mse):.4f} | MAE: {mae:.4f}")

    # Save model artifact
    os.makedirs('models/credit_risk', exist_ok=True)
    artifact_path = 'models/credit_risk/lgd_model_v1.pkl'
    joblib.dump(model, artifact_path)
    logger.info(f"Model saved to {artifact_path}")

    # MLflow logging
    if mlflow is not None:
        try:
            mlflow.set_experiment("LGD_Model_Training")
            with mlflow.start_run(run_name="lgd_v1"):
                mlflow.log_param("model_type", "XGBRegressor")
                mlflow.log_metric("rmse", float(np.sqrt(mse)))
                mlflow.log_metric("mae", float(mae))
                # For a real pipeline, we would log the artifact here too
                # mlflow.sklearn.log_model(model, "model")
        except Exception as e:
            logger.warning(f"MLflow logging failed: {e}")

    # Update model card
    update_model_card(mse, mae)

if __name__ == '__main__':
    train_lgd_model()
