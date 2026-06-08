import pandas as pd
import numpy as np

# Load parquet or csv
df = pd.read_csv('data/raw/LendingClubData/loan.csv', low_memory=False)

# Sample 100,000 rows
df = df.sample(n=100000, replace=False, random_state=42)

def extract_term(x):
    if pd.isna(x):
        return 36
    return int(str(x).replace('months', '').strip())

def grade_to_score(g):
    mapping = {'A': 750, 'B': 700, 'C': 650, 'D': 600, 'E': 550, 'F': 500, 'G': 450}
    return mapping.get(str(g).upper(), 650)

# Map columns
df_mapped = pd.DataFrame()
df_mapped['application_id'] = [f"LC-{i}" for i in range(len(df))]
df_mapped['tenant_id'] = 'platform-default'
df_mapped['loan_amount'] = df['loan_amnt']
df_mapped['loan_purpose'] = df['purpose']
df_mapped['loan_term_months'] = df['term'].apply(extract_term)
df_mapped['annual_income'] = df['annual_inc']
df_mapped['employment_status'] = np.where(df['emp_title'].isna(), 'unemployed', 'employed')
df_mapped['employer_tenure_months'] = 60 # Arbitrary default for LC dataset missing exact months
df_mapped['dti'] = df['dti'] / 100.0
df_mapped['debt_to_income_ratio'] = df['dti'] / 100.0
df_mapped['existing_debt'] = df_mapped['dti'] * df_mapped['annual_income'] / 12
df_mapped['existing_debt_amount'] = df_mapped['existing_debt']
df_mapped['credit_score'] = df['grade'].apply(grade_to_score)
df_mapped['num_open_accounts'] = df['open_acc']
df_mapped['num_derogatory_marks'] = df['pub_rec']
df_mapped['months_since_last_delinquency'] = df['mths_since_last_delinq']
df_mapped['borrower_state'] = df['addr_state']
df_mapped['channel'] = 'web'

# Alt data defaults
df_mapped['rent_payment_months'] = 12
df_mapped['utility_payment_months'] = 12
df_mapped['mobile_data_score'] = 0.8
df_mapped['bank_account_age_months'] = 48
df_mapped['avg_monthly_cash_inflow'] = df_mapped['annual_income'] / 12
df_mapped['avg_monthly_cash_outflow'] = df_mapped['avg_monthly_cash_inflow'] * 0.8

# Cleanup
df_mapped = df_mapped.fillna({
    'num_open_accounts': 0,
    'num_derogatory_marks': 0,
    'months_since_last_delinquency': 0,
    'credit_score': 650,
    'annual_income': 50000,
    'dti': 0.2,
    'debt_to_income_ratio': 0.2,
    'existing_debt': 1000,
    'existing_debt_amount': 1000
})
df_mapped = df_mapped.dropna(subset=['application_id', 'loan_amount', 'loan_term_months'])

output_path = 'data/raw/loans/lc_batch_100k.csv'
df_mapped.to_csv(output_path, index=False)
print(f"Saved {len(df_mapped)} mapped LendingClub records to {output_path}")
