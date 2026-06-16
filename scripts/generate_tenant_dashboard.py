import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import logging
import os
import sys

from pathlib import Path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from db.bigquery_client import read_table
from models.pricing.pricing_optimizer import PricingOptimizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import argparse

def generate_dashboard(tenant_id):
    logger.info("Generating Analytics Dashboard for Tenant: %s", tenant_id)

    os.makedirs(f'reports/{tenant_id}', exist_ok=True)

    try:
        df = read_table(
            table_id="loan_applications",
            dataset_id=tenant_id,
            where=f"tenant_id = '{tenant_id}'"
        )
    except Exception as e:
        logger.warning("Failed to load from BQ: %s. Using synthetic data for reporting.", e)
        df = pd.DataFrame({
            'loan_amount': np.random.lognormal(9, 1, 10000),
            'credit_score': np.random.normal(680, 50, 10000),
            'dti': np.random.uniform(0.1, 0.6, 10000)
        })

    logger.info("--- PORTFOLIO SUMMARY ---")
    logger.info("Total Applications: %d", len(df))
    logger.info("Total Loan Volume Requested: $%.2f", df['loan_amount'].sum())
    logger.info("Average Credit Score: %.1f", df['credit_score'].mean())
    logger.info("Average DTI: %.2f%%", df['dti'].mean() * 100)

    plt.figure(figsize=(10, 6))
    sns.histplot(df['loan_amount'], bins=50, kde=True, color='blue')
    plt.title(f"{tenant_id.replace('_', ' ').title()} - Loan Amount Distribution")
    plt.xlabel("Loan Amount ($)")
    plt.ylabel("Frequency")
    plt.savefig(f'reports/{tenant_id}/loan_amount_dist.png')
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.histplot(df['credit_score'], bins=50, kde=True, color='green')
    plt.title(f"{tenant_id.replace('_', ' ').title()} - Credit Score Distribution")
    plt.xlabel("Credit Score")
    plt.ylabel("Frequency")
    plt.savefig(f'reports/{tenant_id}/credit_score_dist.png')
    plt.close()

    optimizer = PricingOptimizer(tenant_id=tenant_id)
    grades = ['A', 'B', 'C', 'D', 'E']
    pds = [0.02, 0.05, 0.10, 0.18, 0.30]

    rates = []
    for pd_val in pds:
        row = []
        for term in [36, 60]:
            lgd = 0.85 if term == 36 else 0.95
            rate = optimizer.calculate_interest_rate(10000, pd_val, 1.0, lgd)
            row.append(rate)
        rates.append(row)

    pricing_df = pd.DataFrame(rates, index=grades, columns=['36 Months', '60 Months'])

    plt.figure(figsize=(8, 6))
    sns.heatmap(pricing_df, annot=True, fmt=".2f", cmap='YlOrRd', cbar_kws={'label': 'Recommended APR (%)'})
    plt.title(f"{tenant_id.replace('_', ' ').title()} - Risk-Based Pricing Heatmap")
    plt.xlabel("Loan Term")
    plt.ylabel("Credit Grade")
    plt.savefig(f'reports/{tenant_id}/pricing_heatmap.png')
    plt.close()

    logger.info("Dashboard assets generated in reports/%s/", tenant_id)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tenant_id', type=str, default='lending_club')
    args = parser.parse_args()
    generate_dashboard(args.tenant_id)
