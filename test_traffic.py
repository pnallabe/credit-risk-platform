import requests, json, time, os
jwt_token = os.environ.get("JWT_TOKEN")
headers = {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}

payload = {
    "application_id": "app-123",
    "customer_id": "cust-456",
    "credit_score": 750,
    "annual_income": 85000,
    "loan_amount": 15000,
    "loan_term_months": 36,
    "dti_ratio": 0.25,
    "employment_length_years": 5.0,
    "bank_account_age_months": 24,
    "avg_monthly_cash_inflow": 7000,
    "avg_monthly_cash_outflow": 4000,
    "channel": "web"
}

print("Sending 50 requests to decision-api...")
for i in range(50):
    payload["application_id"] = f"app-test-{i}"
    res = requests.post("http://localhost:8081/v1/decisions", headers=headers, json=payload)
    if i % 10 == 0:
        print(f"Sent {i} requests. Status: {res.status_code}")
print("Done.")
