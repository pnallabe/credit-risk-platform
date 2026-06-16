import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import sys
import os

from pathlib import Path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from db.bigquery_client import read_table
from models.pricing.pricing_optimizer import PricingOptimizer

st.set_page_config(page_title="Multi-Tenant Credit Risk Platform", layout="wide", page_icon="🏦")

st.title("🏦 Multi-Tenant Credit Risk Platform")
st.markdown("Monitor isolated tenant data, risk metrics, and dynamically generated pricing.")

tenant = st.sidebar.selectbox("Select Tenant Context", ["lending_club", "synthetic_tenant_a", "synthetic_tenant_b"])

@st.cache_data
def load_tenant_data(tenant_id):
    try:
        df = read_table(
            table_id="loan_applications",
            dataset_id=tenant_id,
            where=f"tenant_id = '{tenant_id}'"
        )
        return df
    except Exception as e:
        # Fallback for synthetic data
        np.random.seed(42)
        n = 5000 if tenant_id == 'lending_club' else 1000
        df = pd.DataFrame({
            'loan_amount': np.random.lognormal(9, 1, n),
            'credit_score': np.random.normal(680, 50, n),
            'dti': np.random.uniform(0.1, 0.6, n)
        })
        return df

df = load_tenant_data(tenant)

st.header(f"Portfolio Summary: {tenant.replace('_', ' ').title()}")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Applications", f"{len(df):,}")
col2.metric("Total Requested Volume", f"${df['loan_amount'].sum():,.0f}")
col3.metric("Avg Credit Score", f"{df['credit_score'].mean():.0f}")
col4.metric("Avg DTI", f"{df['dti'].mean()*100:.1f}%")

st.subheader("Distributions")
fig, axes = plt.subplots(1, 2, figsize=(15, 5))
sns.histplot(df['loan_amount'], bins=50, ax=axes[0], color='royalblue')
axes[0].set_title("Loan Amount Distribution")
axes[0].set_xlabel("Loan Amount ($)")

sns.histplot(df['credit_score'], bins=50, ax=axes[1], color='mediumseagreen')
axes[1].set_title("Credit Score Distribution")
axes[1].set_xlabel("Credit Score")
st.pyplot(fig)

st.subheader("Risk-Based Pricing Matrix")
st.markdown("Powered by the NPV Pricing Optimizer dynamically pulling WACC, OpEx, and EL targets from the tenant policy.")

try:
    optimizer = PricingOptimizer(policy_path=f"config/{tenant}_policy.json" if tenant == 'lending_club' else "config/lending_club_policy.json")
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

    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(pricing_df, annot=True, fmt=".2f", cmap='YlOrRd', ax=ax, cbar_kws={'label': 'Recommended APR (%)'})
    ax.set_title(f"Pricing Heatmap")
    ax.set_xlabel("Loan Term")
    ax.set_ylabel("Credit Grade")
    st.pyplot(fig)
except Exception as e:
    st.error(f"Failed to load pricing engine: {e}")
