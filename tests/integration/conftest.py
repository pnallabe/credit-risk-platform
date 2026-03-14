"""
Shared fixtures for integration tests.

Uses an in-memory SQLite database so the full pipeline
runs without an external PostgreSQL server.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio

# -----------------------------------------------------------------------
# Path setup — make project root importable
# -----------------------------------------------------------------------
ROOT = Path(__file__).parents[2]
DECISION_API_SRC = ROOT / "decision-api" / "src"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(DECISION_API_SRC.parent) not in sys.path:
    sys.path.insert(0, str(DECISION_API_SRC.parent))

# Force SQLite for tests so no external DB is required
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_integration.db")
os.environ.setdefault("JWT_SECRET", "your-secret-key-change-in-production")


# -----------------------------------------------------------------------
# App fixture — creates the FastAPI test client per-session
# -----------------------------------------------------------------------

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="session")
async def app_client():
    """Async HTTPX test client wrapping the decision-api FastAPI app."""
    import httpx
    from src.main import app  # noqa: E402

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


# -----------------------------------------------------------------------
# Low-risk application fixture
# -----------------------------------------------------------------------

@pytest.fixture()
def low_risk_application():
    return {
        "application_id": "test-low-risk-001",
        "customer_id": "cust-001",
        "credit_score": 780,
        "annual_income": 120000.0,
        "employment_status": "employed",
        "employer_tenure_months": 60,
        "debt_to_income_ratio": 0.10,
        "existing_debt_amount": 5000.0,
        "loan_amount": 15000.0,
        "loan_purpose": "home_improvement",
        "loan_term_months": 36,
        "num_open_accounts": 8,
        "num_derogatory_marks": 0,
        "months_since_last_delinquency": None,
    }


# -----------------------------------------------------------------------
# High-risk application fixture
# -----------------------------------------------------------------------

@pytest.fixture()
def high_risk_application():
    return {
        "application_id": "test-high-risk-001",
        "customer_id": "cust-002",
        "credit_score": 520,
        "annual_income": 22000.0,
        "employment_status": "unemployed",
        "employer_tenure_months": 0,
        "debt_to_income_ratio": 0.60,
        "existing_debt_amount": 13200.0,
        "loan_amount": 40000.0,
        "loan_purpose": "personal",
        "loan_term_months": 60,
        "num_open_accounts": 1,
        "num_derogatory_marks": 4,
        "months_since_last_delinquency": 3,
    }


# -----------------------------------------------------------------------
# Fraud-indicative application fixture
# -----------------------------------------------------------------------

@pytest.fixture()
def fraud_application():
    return {
        "application_id": "test-fraud-001",
        "customer_id": "cust-003",
        "credit_score": 310,
        "annual_income": 8000.0,
        "employment_status": "unemployed",
        "employer_tenure_months": 0,
        "debt_to_income_ratio": 0.65,
        "existing_debt_amount": 5200.0,
        "loan_amount": 99000.0,
        "loan_purpose": "personal",
        "loan_term_months": 12,
        "num_open_accounts": 0,
        "num_derogatory_marks": 5,
        "months_since_last_delinquency": 1,
    }
