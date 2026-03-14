"""
Integration tests for feature_pipeline/feature_store.py

Uses a SQLite in-memory database (via aiosqlite) as a drop-in replacement
for PostgreSQL so the test suite runs in CI without a live database.

SQLite schema differences handled:
- JSONB → TEXT (serialised JSON)
- gen_random_uuid() / UUID type → TEXT with Python uuid default
- TIMESTAMPTZ → TIMESTAMP
- ARRAY(Text) → not used in the features table
- No ON CONFLICT … DO UPDATE; using INSERT OR REPLACE instead
"""

from __future__ import annotations

import json

import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from feature_pipeline.feature_store import write_features
from feature_pipeline.features import FeaturePipelineConfig, compute_features


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS features (
    id                          INTEGER         PRIMARY KEY AUTOINCREMENT,
    application_id              TEXT            NOT NULL,
    feature_set_version         TEXT            NOT NULL,
    computed_at                 TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
    credit_utilization          REAL,
    income_stability_score      REAL,
    repayment_capacity          REAL,
    debt_service_coverage_ratio REAL,
    credit_age_months           INTEGER,
    payment_history_score       REAL,
    feature_json                TEXT,
    UNIQUE (application_id, feature_set_version)
);
"""


@pytest_asyncio.fixture()
async def sqlite_engine() -> AsyncEngine:
    """In-memory SQLite async engine with the features table pre-created."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(SQLITE_SCHEMA))
    yield engine
    await engine.dispose()


@pytest.fixture()
def raw_df() -> pd.DataFrame:
    """Small raw loan application DataFrame (10 rows)."""
    import uuid

    n = 10
    return pd.DataFrame(
        {
            "application_id": [str(uuid.uuid4()) for _ in range(n)],
            "customer_id": [str(uuid.uuid4()) for _ in range(n)],
            "credit_score": [700] * n,
            "annual_income": [80_000.0] * n,
            "employment_status": ["employed"] * n,
            "employer_tenure_months": [24] * n,
            "debt_to_income_ratio": [0.30] * n,
            "existing_debt_amount": [15_000.0] * n,
            "loan_amount": [20_000.0] * n,
            "loan_purpose": ["personal"] * n,
            "loan_term_months": [36] * n,
            "num_open_accounts": [5] * n,
            "num_derogatory_marks": [0] * n,
            "months_since_last_delinquency": [float("nan")] * n,
            "state": ["CA"] * n,
            "zip_code_prefix": ["900"] * n,
            "submitted_at": pd.to_datetime(["2024-06-01"] * n),
        }
    )


@pytest.fixture()
def feature_df(raw_df) -> pd.DataFrame:
    """DataFrame with engineered features already computed."""
    config = FeaturePipelineConfig()
    return compute_features(raw_df, config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_returns_correct_metadata(sqlite_engine, feature_df):
    """write_features should return rows_written, duration_seconds, feature_version."""
    config = FeaturePipelineConfig(version="1.0.0")
    result = await write_features(feature_df, config, db_url="", engine=sqlite_engine)

    assert result["rows_written"] == len(feature_df)
    assert result["feature_version"] == "1.0.0"
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.0


@pytest.mark.asyncio
async def test_rows_persisted_to_db(sqlite_engine, feature_df):
    """Rows written must be readable from the DB."""
    config = FeaturePipelineConfig(version="1.0.0")
    await write_features(feature_df, config, db_url="", engine=sqlite_engine)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM features"))
        count = result.scalar()

    assert count == len(feature_df)


@pytest.mark.asyncio
async def test_upsert_does_not_duplicate(sqlite_engine, feature_df):
    """Writing the same data twice must not create duplicate rows."""
    config = FeaturePipelineConfig(version="1.0.0")
    await write_features(feature_df, config, db_url="", engine=sqlite_engine)
    await write_features(feature_df, config, db_url="", engine=sqlite_engine)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM features"))
        count = result.scalar()

    assert count == len(feature_df)


@pytest.mark.asyncio
async def test_feature_json_round_trips(sqlite_engine, feature_df):
    """feature_json must deserialise back to a dict with expected keys."""
    config = FeaturePipelineConfig(version="1.0.0")
    await write_features(feature_df, config, db_url="", engine=sqlite_engine)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT feature_json FROM features LIMIT 1")
        )
        raw_json = result.scalar()

    assert raw_json is not None
    parsed = json.loads(raw_json)
    assert "months_since_delinquency" in parsed
    assert "employment_encoded" in parsed


@pytest.mark.asyncio
async def test_multiple_versions_stored_separately(sqlite_engine, feature_df):
    """Rows with different feature_set_version values must coexist."""
    config_v1 = FeaturePipelineConfig(version="1.0.0")
    config_v2 = FeaturePipelineConfig(version="2.0.0")

    await write_features(feature_df, config_v1, db_url="", engine=sqlite_engine)
    await write_features(feature_df, config_v2, db_url="", engine=sqlite_engine)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM features WHERE feature_set_version = '1.0.0'")
        )
        v1_count = result.scalar()
        result = await conn.execute(
            text("SELECT COUNT(*) FROM features WHERE feature_set_version = '2.0.0'")
        )
        v2_count = result.scalar()

    assert v1_count == len(feature_df)
    assert v2_count == len(feature_df)


@pytest.mark.asyncio
async def test_large_batch_written_in_chunks(sqlite_engine, raw_df):
    """Dataset larger than CHUNK_SIZE (1000) should still write correctly."""
    import uuid

    # Replicate the 10-row df 120 times → 1200 rows
    big_df = pd.concat([raw_df] * 120, ignore_index=True)
    # Give unique application_ids to avoid UNIQUE conflicts
    big_df["application_id"] = [str(uuid.uuid4()) for _ in range(len(big_df))]

    config = FeaturePipelineConfig(version="1.0.0")
    feature_big_df = compute_features(big_df, config)

    result = await write_features(
        feature_big_df, config, db_url="", engine=sqlite_engine
    )

    assert result["rows_written"] == 1200

    async with sqlite_engine.connect() as conn:
        r = await conn.execute(text("SELECT COUNT(*) FROM features"))
        count = r.scalar()
    assert count == 1200


@pytest.mark.asyncio
async def test_scalar_feature_values_stored_correctly(sqlite_engine, feature_df):
    """Numeric scalar features must be stored with correct approximate values."""
    config = FeaturePipelineConfig(version="1.0.0")
    await write_features(feature_df, config, db_url="", engine=sqlite_engine)

    async with sqlite_engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT credit_utilization, income_stability_score, repayment_capacity "
                "FROM features LIMIT 1"
            )
        )
        row = result.fetchone()

    assert row is not None
    # credit_utilization for income=80k, debt=15k → 15000/(80000*0.4) = 0.46875
    assert abs(row[0] - 0.46875) < 1e-3
    # repayment_capacity for dti=0.30 → 0.70
    assert abs(row[2] - 0.70) < 1e-3
