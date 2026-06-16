# Real-World Financial Data Sources

Datasets are organised by domain and rated on **column transparency**:
- ✅ **Real columns** — all feature names are interpretable business terms
- ⚠️ **Partially named** — mix of real and coded/enumerated columns
- ❌ **Anonymised** — columns are PCA components (V1–V28) or opaque codes (B_1…D_145)

> Jump to: [Loans](#loans) · [Transactions](#bank-transactions--payments) · [Credit Cards](#credit-cards) · [Avoid](#datasets-to-avoid-for-feature-engineering) · [Column Maps](#detailed-column-maps)

---

## Loans

| Dataset | Columns | Size | Licence | Download |
|---|---|---|---|---|
| **LendingClub (2007–2020)** | ✅ Real | 2.5 GB | CC0 | [Kaggle](https://www.kaggle.com/datasets/wordsforthewise/lending-club) |
| **Fannie Mae Single-Family Performance** | ✅ Real | ~25 GB/yr | Free (registration) | [fanniemae.com](https://www.fanniemae.com/research-and-insights/datasets/mortgage-data) |
| **Freddie Mac Single-Family Loan-Level** | ✅ Real | ~20 GB/yr | Free (registration) | [freddiemac.com](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset) |
| **HMDA (2018–2024)** | ✅ Real | ~1 GB/yr | Public Domain | [CFPB HMDA Explorer](https://ffiec.cfpb.gov/data-browser/data/2023/NATIONAL/ALL?output=csv) |
| **SBA Loan Guarantee Data** | ✅ Real | ~800 MB | Public Domain | [data.sba.gov](https://data.sba.gov/dataset/sbac-loan/) |
| **Prosper Loan Data** | ⚠️ Partial | 125 MB | CC BY-SA | [Kaggle](https://www.kaggle.com/datasets/yousuf28/propser-loan) |
| **Home Credit Default Risk** | ⚠️ Partial | 700 MB | Competition | [Kaggle](https://www.kaggle.com/c/home-credit-default-risk) |

**Best pick**: LendingClub for volume + real column names; HMDA for regulatory / fair-lending work.

---

## Bank Transactions / Payments

| Dataset | Columns | Size | Licence | Download |
|---|---|---|---|---|
| **Berka Financial Dataset (PKDD'99)** | ✅ Real | 6 MB | Academic Free | [Kaggle](https://www.kaggle.com/datasets/nitishabharathi/bank-dataset) |
| **PaySim Mobile Money Simulation** | ✅ Real | 470 MB | CC BY-SA | [Kaggle](https://www.kaggle.com/datasets/ealaxi/paysim1) |
| **BankSim** | ✅ Real | 2 MB | Academic | [ResearchGate paper](https://doi.org/10.5220/0004905801580165) |
| **IEEE-CIS Fraud Detection** | ❌ Anonymised | 1.3 GB | Competition | [Kaggle](https://www.kaggle.com/c/ieee-fraud-detection/data) |
| **ULB Credit Card Fraud (mlg-ulb)** | ❌ Anonymised | 144 MB | DbCL | [Kaggle](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) |

**Best pick**: Berka for a complete relational banking dataset (accounts + transactions + loans + cards); PaySim for 6M+ transaction volume with fraud labels.

---

## Credit Cards

| Dataset | Columns | Size | Licence | Download |
|---|---|---|---|---|
| **UCI Default of Credit Card Clients** | ✅ Real | 3 MB | CC BY 4.0 | [UCI ML Repo](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients) |
| **Give Me Some Credit (Kaggle 2011)** | ✅ Real | 7 MB | Competition | [Kaggle](https://www.kaggle.com/c/GiveMeSomeCredit/data) |
| **American Express Default Prediction** | ❌ Anonymised | 50 GB | Competition | [Kaggle](https://www.kaggle.com/competitions/amex-default-prediction) |
| **ULB Credit Card Fraud** | ❌ Anonymised | 144 MB | DbCL | [Kaggle](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud) |

**Best pick**: UCI Default for a clean, fully-named 30k-row benchmark; Give Me Some Credit for bureau-style features.

---

## Datasets to Avoid for Feature Engineering

These are popular but **all features are anonymised** — not useful when you need real column names to align with your schema:

| Dataset | Why anonymised | What you get instead |
|---|---|---|
| **ULB Credit Card Fraud** | Issuer confidentiality | V1–V28 (PCA) + Amount + Time |
| **IEEE-CIS Fraud Detection** | Vesta Corp NDA | V1–V339, C1–C14, D1–D15, M1–M9, id_01–id_38 |
| **American Express Default Prediction** | Amex IP protection | B_1–B_41, D_1–D_145, P_2–P_4, R_1–R_28, S_2–S_27 |

---

## Detailed Column Maps

Column-to-schema mappings for every ✅ dataset above, so you can write ETL adapters directly against the existing ORM models in [db/orm_models_extended.py](db/orm_models_extended.py).

---

### LendingClub — `customers` + `loan_applications` + `loans` + `loan_payments`

```
loan_amnt            → loan_applications.requested_amount
funded_amnt          → loans.original_principal
term                 → loans.loan_term_months          ("36 months" / "60 months")
int_rate             → loans.interest_rate
installment          → loans.monthly_payment
grade                → loan_applications.risk_grade
sub_grade            → loan_applications.risk_sub_grade
emp_title            → customers.employer_name
emp_length           → customers.employment_length_years
home_ownership       → customers.home_ownership_status  (RENT / OWN / MORTGAGE)
annual_inc           → customers.annual_income
verification_status  → loan_applications.income_verification_status
issue_d              → loans.origination_date
loan_status          → loans.status                    (Fully Paid / Charged Off / Current …)
purpose              → loan_applications.loan_purpose   (debt_consolidation / home_improvement …)
addr_state           → customers.state
dti                  → loan_applications.debt_to_income_ratio
delinq_2yrs          → customers.delinquencies_last_2yrs
fico_range_low       → customers.fico_score_low
fico_range_high      → customers.fico_score_high
revol_bal            → customers.revolving_balance
revol_util           → customers.revolving_utilization
open_acc             → customers.open_credit_lines
pub_rec              → customers.public_records
total_pymnt          → loans.total_paid_amount
recoveries           → loans.recovery_amount
last_pymnt_amnt      → loan_payments.amount            (most recent row)
out_prncp            → loans.current_balance
```

**Download** (requires `kaggle` CLI):
```bash
pip install kaggle
# Place ~/.kaggle/kaggle.json   (kaggle.com → Account → API → Create Token)
kaggle datasets download -d wordsforthewise/lending-club -p data/raw/loans/ --unzip
```

---

### Fannie Mae Single-Family — `loans` + `loan_payments`

**Origination file** (one row per loan):
```
CreditScore           → customers.fico_score
FirstPaymentDate      → loans.first_payment_date
MaturityDate          → loans.maturity_date
OrigInterestRate      → loans.interest_rate
OrigUPB               → loans.original_principal
OLTV                  → loan_applications.loan_to_value_ratio
OCLTV                 → loan_applications.combined_ltv
ODTI                  → loan_applications.debt_to_income_ratio
NumBorrowers          → loan_applications.number_of_borrowers
LoanPurpose           → loan_applications.loan_purpose  (P=Purchase R=Refi C=CashOut)
PropertyState         → customers.state
PropertyType          → loan_applications.property_type  (SF/CO/MH/PU/CP)
PostalCode            → customers.zip_code
Channel               → loan_applications.origination_channel  (R=Retail B=Broker C=Correspondent)
SellerName            → loan_applications.lender_name
ServicerName          → loans.servicer_name
LoanSequenceNumber    → loans.external_loan_id
SuperConformingFlag   → loans.super_conforming
```

**Monthly performance file** (one row per loan per month):
```
LoanSequenceNumber              → loan_payments.loan_id
MonthlyReportingPeriod          → loan_payments.payment_date
CurrentActualUPB                → loan_payments.remaining_balance
CurrentLoanDelinquencyStatus    → loans.days_past_due  (0 1 2 … XX=foreclosure RA=REO)
CurrentInterestRate             → loan_payments.interest_rate_at_payment
LoanAge                         → (derived) months since origination
ModificationFlag                → loan_modifications.is_modified
ZeroBalanceCode                 → loans.payoff_reason  (01=PP 02=3rd-party 03=short 06=charge-off)
```

**Download**: Register at [fanniemae.com](https://www.fanniemae.com/research-and-insights/datasets/mortgage-data) → Single Family → Loan Performance Data.

---

### HMDA (2023) — `loan_applications` fair-lending columns

Full CFPB data dictionary: [cfpb.github.io/hmda-platform](https://cfpb.github.io/hmda-platform/#hmda-api-documentation)

```
loan_amount                      → loan_applications.requested_amount
combined_loan_to_value_ratio     → loan_applications.loan_to_value_ratio
interest_rate                    → loans.interest_rate
rate_spread                      → loans.rate_spread_bps         (basis pts above APOR)
loan_term                        → loans.loan_term_months
debt_to_income_ratio             → loan_applications.debt_to_income_ratio
income                           → customers.annual_income        (000s omitted)
property_value                   → loan_applications.collateral_value
action_taken                     → loan_applications.decision
    1 = Originated
    2 = Approved, not accepted
    3 = Denied
    4 = Withdrawn
    5 = Incomplete
    6 = Purchased
    7 = Pre-approval denied
    8 = Pre-approval approved
denial_reason_1 … denial_reason_4 → loan_applications.denial_reason_primary …
loan_type                        → loan_applications.loan_type
    1=Conventional  2=FHA  3=VA  4=USDA/RHS
loan_purpose                     → loan_applications.loan_purpose
    1=Purchase  2=Home improvement  31=Refinancing  32=CashOut  4=Other
lien_status                      → loans.lien_position            (1=First  2=Subordinate)
applicant_race_1                 → customers.race                 (ECOA field)
applicant_ethnicity_1            → customers.ethnicity
applicant_sex                    → customers.gender
state_code                       → customers.state
county_code                      → customers.county_fips
census_tract                     → customers.census_tract
```

**Direct download** (no login — ~900 MB CSV):
```bash
curl -L "https://ffiec.cfpb.gov/data-browser/data/2023/NATIONAL/ALL?output=csv" \
     -o data/raw/loans/hmda_2023.csv
```

---

### SBA Loan Guarantee Data — `loans` + `customers`

```
LoanNr_ChkDgt   → loans.external_loan_id
Name            → customers.business_name
City            → customers.city
State           → customers.state
Zip             → customers.zip_code
Bank            → loan_applications.lender_name
BankState       → loan_applications.lender_state
NAICS           → customers.naics_code              (6-digit industry code)
ApprovalDate    → loan_applications.application_date
ApprovalFY      → loan_applications.fiscal_year
Term            → loans.loan_term_months
NoEmp           → customers.number_of_employees
NewExist        → customers.business_type           (1=Existing  2=New)
CreateJob       → customers.jobs_created
RetainedJob     → customers.jobs_retained
UrbanRural      → customers.location_type           (U=Urban  R=Rural  S=Suburban)
RevLineCr       → loans.is_revolving_line           (Y/N)
LowDoc          → loan_applications.low_doc_program  (Y/N)
DisbursementDate → loans.origination_date
DisbursementGross → loans.original_principal
MIS_Status      → loans.status                      (P I F = Paid In Full, CHGOFF = Charged Off)
ChgOffPrinGr    → loans.charge_off_amount
GrAppv          → loan_applications.gross_approval_amount
SBA_Appv        → loan_applications.sba_guaranteed_amount
```

**Direct download** (no login):
```bash
curl -L "https://data.sba.gov/dataset/sbac-loan/resource/aab20768-a5e5-4826-87a5-73bf585b8267/download/foia-504-fy1991-fy2009-asof-230930.csv" \
     -o data/raw/loans/sba_loans.csv
```

---

### Berka Financial Dataset — `bank_accounts` + `transactions` (5 relational tables)

All field values are in Czech but the column names are English.

**`account.asc`** → `bank_accounts`:
```
account_id   → bank_accounts.id
district_id  → bank_accounts.branch_id
frequency    → bank_accounts.statement_frequency  (monthly / weekly / transaction)
date         → bank_accounts.opened_at
```

**`trans.asc`** → `transactions`:
```
trans_id     → transactions.id
account_id   → transactions.account_id
date         → transactions.initiated_at              (YYMMDD)
type         → transactions.direction                 (PRIJEM=credit  VYDAJ=debit  VYBER=withdrawal)
operation    → transactions.method
    "cash withdrawal"
    "remittance to another bank"
    "collection from another bank"
    "credit card withdrawal"
    "credit in cash"
amount       → transactions.amount
balance      → transactions.running_balance
k_symbol     → transactions.category
    "interest credited"
    "household"
    "insurance payment"
    "pension retirement"
    "negative balance"
    "statement charges"
    "sanction interest"
bank         → transactions.counterparty_bank_code
account      → transactions.counterparty_account_id
```

**`loan.asc`** → `loans`:
```
loan_id      → loans.id
account_id   → loans.account_id
date         → loans.origination_date
amount       → loans.original_principal
duration     → loans.loan_term_months
payments     → loans.monthly_payment
status       → loans.status
    A = contract finished, no problems
    B = contract finished, loan not paid
    C = running contract, OK so far
    D = running contract, client in debt
```

**`card.asc`** → `card_accounts`:
```
card_id      → card_accounts.id
disp_id      → card_accounts.disposition_id          (links to client)
type         → card_accounts.product_type            (classic / junior / gold)
issued       → card_accounts.issued_date
```

**`client.asc`** → `customers`:
```
client_id    → customers.id
birth_number → customers.date_of_birth               (YYMMDD; odd month prefix = female)
district_id  → customers.district_id
```

```bash
kaggle datasets download -d nitishabharathi/bank-dataset \
    -p data/raw/transactions/ --unzip
```

---

### PaySim — `transactions` + `fraud_alerts`

```
step           → transactions.initiated_at   (integer hour; 1–744 over 30 days)
type           → transactions.type
    CASH_IN    = cash deposit
    CASH_OUT   = cash withdrawal
    DEBIT      = direct debit
    PAYMENT    = merchant payment
    TRANSFER   = account-to-account
amount         → transactions.amount
nameOrig       → transactions.sender_account_id      (e.g. C123456789)
oldbalanceOrg  → (pre-tx balance, use to derive running_balance)
newbalanceOrig → transactions.running_balance
nameDest       → transactions.receiver_account_id    (C=customer  M=merchant)
oldbalanceDest → (receiver pre-tx balance)
newbalanceDest → (receiver post-tx balance)
isFraud        → fraud_alerts.is_fraud               (ground-truth label)
isFlaggedFraud → fraud_alerts.rule_triggered         (only flags transfers > 200k)
```

```bash
kaggle datasets download -d ealaxi/paysim1 \
    -p data/raw/transactions/ --unzip
```

---

### UCI Default of Credit Card Clients — `card_accounts` + `card_statements`

Full variable description: [UCI ML Repository](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients)

```
LIMIT_BAL   → card_accounts.credit_limit
SEX         → customers.gender              (1=male  2=female)
EDUCATION   → customers.education_level    (1=grad  2=university  3=high school  4=other)
MARRIAGE    → customers.marital_status     (1=married  2=single  3=other)
AGE         → customers.age
PAY_0       → card_statements[Sep].payment_status
PAY_2       → card_statements[Aug].payment_status
PAY_3       → card_statements[Jul].payment_status
PAY_4       → card_statements[Jun].payment_status
PAY_5       → card_statements[May].payment_status
PAY_6       → card_statements[Apr].payment_status
    -2 = no consumption   -1 = paid in full   0 = revolving credit
     1 = 1-month delay     2 = 2-month delay   … up to 9
BILL_AMT1   → card_statements[Sep].statement_balance
BILL_AMT2   → card_statements[Aug].statement_balance
BILL_AMT3   → card_statements[Jul].statement_balance
BILL_AMT4   → card_statements[Jun].statement_balance
BILL_AMT5   → card_statements[May].statement_balance
BILL_AMT6   → card_statements[Apr].statement_balance
PAY_AMT1    → card_statements[Sep].amount_paid
PAY_AMT2    → card_statements[Aug].amount_paid
PAY_AMT3    → card_statements[Jul].amount_paid
PAY_AMT4    → card_statements[Jun].amount_paid
PAY_AMT5    → card_statements[May].amount_paid
PAY_AMT6    → card_statements[Apr].amount_paid
default.payment.next.month → card_accounts.is_defaulted   (target label)
```

**Direct download** (no login):
```bash
curl -L "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip" \
     -o data/raw/credit_cards/uci_default.zip \
  && unzip data/raw/credit_cards/uci_default.zip -d data/raw/credit_cards/
```

---

### Give Me Some Credit — `customers` bureau-style columns

```
SeriousDlqin2yrs                      → customers.target_default_90d     (binary label)
RevolvingUtilizationOfUnsecuredLines  → customers.revolving_utilization   (0–1+)
age                                   → customers.age
NumberOfTime30-59DaysPastDueNotWorse  → customers.delinquencies_30_59d
DebtRatio                             → customers.debt_to_income_ratio
MonthlyIncome                         → customers.monthly_income
NumberOfOpenCreditLinesAndLoans       → customers.open_credit_lines
NumberOfTimes90DaysLate               → customers.delinquencies_90d_plus
NumberRealEstateLoansOrLines          → customers.real_estate_loans_count
NumberOfTime60-89DaysPastDueNotWorse  → customers.delinquencies_60_89d
NumberOfDependents                    → customers.number_of_dependents
```

```bash
kaggle competitions download -c GiveMeSomeCredit \
    -p data/raw/credit_cards/
```

---

## Quick-Start: Download All Three Recommended Datasets

```bash
# Install kaggle CLI and authenticate
pip install kaggle
# Place ~/.kaggle/kaggle.json  (kaggle.com → Account → API → Create Token)

# 1. Loans — LendingClub (2.5 GB, CC0, real column names)
kaggle datasets download -d wordsforthewise/lending-club \
    -p data/raw/loans/ --unzip

# 2. Transactions — Berka (6 MB, free, real column names)
kaggle datasets download -d nitishabharathi/bank-dataset \
    -p data/raw/transactions/ --unzip

# 3. Credit Cards — UCI Default (3 MB, CC BY 4.0, real column names)
curl -L "https://archive.ics.uci.edu/static/public/350/default+of+credit+card+clients.zip" \
     -o data/raw/credit_cards/uci_default.zip \
  && unzip data/raw/credit_cards/uci_default.zip -d data/raw/credit_cards/
```

Total download: ~2.7 GB. All three have fully interpretable column names.

---

## Data Licences

| Licence | Commercial use | Redistribution |
|---|---|---|
| Public Domain / US Gov | ✅ | ✅ |
| CC0 | ✅ | ✅ |
| CC BY 4.0 | ✅ (attribution) | ✅ |
| CC BY-SA | ✅ (share-alike) | ✅ |
| Academic Free | ✅ (research) | case-by-case |
| Kaggle Competition | ❌ non-commercial | ❌ |

> Always verify the current licence on the source site before production use.
