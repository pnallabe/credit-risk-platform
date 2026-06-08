import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, mean_absolute_error
import joblib
import logging
import os

from db.bigquery_client import read_table

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import argparse

def load_data(tenant_id):
    logger.info("Loading EAD data for tenant %s...", tenant_id)
    np.random.seed(42)
    n = 2000
    df = pd.DataFrame({
        'loan_amount': np.random.lognormal(9, 1, n),
        'loan_term_months': np.random.choice([36, 60], n),
        'months_on_book': np.random.randint(1, 60, n)
    })

    ead_fraction = np.clip(1.0 - (df['months_on_book'] / df['loan_term_months']) + np.random.normal(0, 0.1, n), 0.1, 1.0)
    df['target_ead'] = df['loan_amount'] * ead_fraction
    return df

def feature_engineering(df):
    df['ead_ratio'] = df['target_ead'] / df['loan_amount']
    df['amortization_progress'] = df['months_on_book'] / df['loan_term_months']
    features = ['amortization_progress']
    return df[features], df['ead_ratio']

def train_model(tenant_id):
    df = load_data(tenant_id)
    X, y = feature_engineering(df)

    logger.info("Training Linear Regression EAD model on %d samples", len(X))
    model = LinearRegression()
    model.fit(X, y)

    y_pred = model.predict(X)
    mse = mean_squared_error(y, y_pred)
    mae = mean_absolute_error(y, y_pred)
    logger.info("EAD Ratio MSE: %.4f | MAE: %.4f", mse, mae)

    os.makedirs('models/credit_risk/artifacts', exist_ok=True)
    joblib.dump(model, f'models/credit_risk/artifacts/{tenant_id}_ead_model.pkl')
    logger.info(f"Model saved to artifacts/{tenant_id}_ead_model.pkl")

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant_id', type=str, default='lending_club')
    args = parser.parse_args()
    train_model(args.tenant_id)
