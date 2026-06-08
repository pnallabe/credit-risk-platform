import pandas as pd
import numpy as np

# Load parquet
df = pd.read_parquet('data/raw/loans/personal_loan_applications.parquet')

# Sample 100000 rows (use replace=True in case there are fewer than 100k rows)
df = df.sample(n=100000, replace=True, random_state=42)

# Map columns
df_mapped = pd.DataFrame()
df_mapped['application_id'] = df['application_id']
df_mapped['tenant_id'] = 'platform-default'  # Required by ingestion validation
df_mapped['loan_amount'] = df['requested_amount']
df_mapped['loan_purpose'] = df['loan_purpose']
df_mapped['loan_term_months'] = df['term_months']
df_mapped['annual_income'] = df['annual_income']
df_mapped['employment_status'] = df['employment_status']
df_mapped['employer_tenure_months'] = 24  # Default
df_mapped['dti'] = df['dti']
df_mapped['debt_to_income_ratio'] = df['dti']
df_mapped['existing_debt'] = df['dti'] * df['annual_income'] / 12  # Approximation
df_mapped['existing_debt_amount'] = df_mapped['existing_debt']
df_mapped['credit_score'] = df['fico_score']
df_mapped['num_open_accounts'] = np.random.randint(2, 10, size=len(df))
df_mapped['num_derogatory_marks'] = df['num_derog_marks']
df_mapped['months_since_last_delinquency'] = np.where(df['num_derog_marks'] > 0, 12, np.nan)
df_mapped['borrower_state'] = df['state']
df_mapped['channel'] = df['channel']

# Add alternative data defaults
df_mapped['rent_payment_months'] = 12
df_mapped['utility_payment_months'] = 12
df_mapped['mobile_data_score'] = 0.8
df_mapped['bank_account_age_months'] = 48
df_mapped['avg_monthly_cash_inflow'] = df['annual_income'] / 12
df_mapped['avg_monthly_cash_outflow'] = df['annual_income'] / 12 * 0.8

# Save to CSV
output_path = 'data/raw/loans/test_batch_100k.csv'
df_mapped = df_mapped.fillna({
    'num_open_accounts': 0,
    'num_derogatory_marks': 0,
    'months_since_last_delinquency': 0,
    'credit_score': 0
})
df_mapped = df_mapped.dropna(subset=['application_id', 'loan_amount', 'annual_income'])
df_mapped.to_csv(output_path, index=False)
print(f"Saved mapped CSV to {output_path}")
