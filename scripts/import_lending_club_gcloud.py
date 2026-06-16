import pandas as pd
import numpy as np
import logging
from datetime import datetime

# Setup paths to import project modules
import sys
from pathlib import Path
ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from db.bigquery_client import ensure_dataset, ensure_table, write_dataframe
from db.bigquery_schema import LOAN_APPLICATIONS_SCHEMA, LOAN_APPLICATIONS_PARTITION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    dataset_id = "lending_club"
    project_id = "ai-risk-workflow"

    logger.info("Ensuring dataset %s exists", dataset_id)
    ensure_dataset(dataset_id=dataset_id, project=project_id)

    logger.info("Ensuring table loan_applications exists")
    ensure_table(
        table_id="loan_applications",
        schema=LOAN_APPLICATIONS_SCHEMA,
        dataset_id=dataset_id,
        project=project_id,
        partition_field=LOAN_APPLICATIONS_PARTITION
    )

    logger.info("Loading LendingClub data from CSV (this might take a minute)...")
    # Using 10,000 sample for demonstration due to memory limits, but can be scaled up
    df = pd.read_csv('data/raw/LendingClubData/loan.csv', low_memory=False)
    df = df.sample(n=100000, replace=False, random_state=42)

    def extract_term(x):
        if pd.isna(x):
            return 36
        return int(str(x).replace('months', '').strip())

    def grade_to_score(g):
        mapping = {'A': 750, 'B': 700, 'C': 650, 'D': 600, 'E': 550, 'F': 500, 'G': 450}
        return mapping.get(str(g).upper(), 650)

    logger.info("Mapping columns to canonical schema...")
    df_mapped = pd.DataFrame()
    df_mapped['application_id'] = [f"LC-BQ-{i}" for i in range(len(df))]
    df_mapped['tenant_id'] = 'lending_club'

    # We will use issue_d for submitted_at, but issue_d is Mon-YYYY e.g., 'Dec-2015'
    # Fallback to now if missing
    def parse_issue_d(d):
        try:
            return pd.to_datetime(d, format='%b-%Y')
        except:
            return datetime.utcnow()

    df_mapped['submitted_at'] = df['issue_d'].apply(parse_issue_d)
    df_mapped['loan_amount'] = df['loan_amnt']
    df_mapped['loan_purpose'] = df['purpose'].fillna('other')
    df_mapped['loan_term_months'] = df['term'].apply(extract_term)
    df_mapped['annual_income'] = df['annual_inc'].fillna(50000.0)
    df_mapped['employment_status'] = np.where(df['emp_title'].isna(), 'unemployed', 'employed')
    df_mapped['employer_tenure_months'] = 60.0
    df_mapped['dti'] = df['dti'] / 100.0
    df_mapped['existing_debt'] = df_mapped['dti'] * df_mapped['annual_income'] / 12
    df_mapped['credit_score'] = df['grade'].apply(grade_to_score)
    df_mapped['num_open_accounts'] = df['open_acc'].fillna(0)
    df_mapped['num_derogatory_marks'] = df['pub_rec'].fillna(0)
    df_mapped['months_since_last_delinquency'] = df['mths_since_last_delinq'].fillna(999.0)
    df_mapped['borrower_state'] = df['addr_state'].fillna('XX')
    df_mapped['channel'] = 'web'

    # Alt data
    df_mapped['rent_payment_months'] = 12
    df_mapped['utility_payment_months'] = 12
    df_mapped['mobile_data_score'] = 0.8
    df_mapped['bank_account_age_months'] = 48
    df_mapped['avg_monthly_cash_inflow'] = df_mapped['annual_income'] / 12
    df_mapped['avg_monthly_cash_outflow'] = df_mapped['avg_monthly_cash_inflow'] * 0.8
    df_mapped['is_thin_file'] = False
    df_mapped['data_split'] = np.where(np.random.rand(len(df_mapped)) < 0.8, 'train', 'test')
    df_mapped['schema_version'] = '1.0'
    df_mapped['inserted_at'] = pd.Timestamp.utcnow()

    # Drop where critical features missing
    df_mapped = df_mapped.dropna(subset=['application_id', 'loan_amount', 'loan_term_months', 'submitted_at'])

    logger.info("Writing %d rows to BigQuery project=%s dataset=%s table=loan_applications",
                len(df_mapped), project_id, dataset_id)

    res = write_dataframe(
        df=df_mapped,
        table_id="loan_applications",
        schema=LOAN_APPLICATIONS_SCHEMA,
        dataset_id=dataset_id,
        project=project_id,
        partition_field=LOAN_APPLICATIONS_PARTITION
    )
    logger.info("Upload complete: %s", res)

if __name__ == '__main__':
    main()
