import pandas as pd
import numpy as np
from sklearn.tree import DecisionTreeRegressor
from sklearn.metrics import mean_squared_error
import joblib
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import argparse

def load_data(tenant_id):
    logger.info("Loading LGD data for tenant %s...", tenant_id)
    np.random.seed(42)
    n = 2000
    df = pd.DataFrame({
        'loan_amount': np.random.lognormal(9, 1, n),
        'loan_purpose': np.random.choice(['debt_consolidation', 'home_improvement', 'business', 'other'], n),
        'collateralized': np.random.choice([0, 1], n)
    })

    lgd_base = np.where(df['collateralized'] == 1, 0.4, 0.85)
    lgd_purpose = np.where(df['loan_purpose'] == 'business', -0.1, 0.05)

    df['target_lgd'] = np.clip(lgd_base + lgd_purpose + np.random.normal(0, 0.1, n), 0.1, 1.0)
    return df

def feature_engineering(df):
    df_encoded = pd.get_dummies(df, columns=['loan_purpose'])
    features = [c for c in df_encoded.columns if c not in ['target_lgd', 'loan_amount']]
    return df_encoded[features], df_encoded['target_lgd'], features

def train_model(tenant_id):
    df = load_data(tenant_id)
    X, y, feature_cols = feature_engineering(df)

    logger.info("Training Decision Tree LGD model on %d samples", len(X))
    model = DecisionTreeRegressor(max_depth=3, random_state=42)
    model.fit(X, y)

    y_pred = model.predict(X)
    mse = mean_squared_error(y, y_pred)
    logger.info("LGD MSE: %.4f", mse)

    os.makedirs('models/lgd/artifacts', exist_ok=True)
    joblib.dump({'model': model, 'features': feature_cols}, f'models/lgd/artifacts/{tenant_id}_lgd_model.pkl')
    logger.info(f"Model saved to artifacts/{tenant_id}_lgd_model.pkl")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant_id', type=str, default='lending_club')
    args = parser.parse_args()
    train_model(args.tenant_id)
