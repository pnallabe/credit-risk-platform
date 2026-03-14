"""
Audit Logger
============
Async module for writing and replaying loan decision audit records to/from
PostgreSQL (production) or SQLite in-memory (CI / tests).

PII Masking
-----------
Before persisting, sensitive fields are masked:
  - SSN      → SHA-256 hash (hex digest)
  - bank_account → last 4 digits only, e.g. "****1234"
  - customer_id  → SHA-256 hash (hex digest)

Public API
----------
>>> from audit.logger import log_decision, get_audit_record
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PII masking utilities
# ---------------------------------------------------------------------------


def _sha256(value: str) -> str:
    """Return the hex SHA-256 digest of *value*."""
    return hashlib.sha256(value.encode()).hexdigest()


def _mask_bank_account(value: str) -> str:
    """Return '****' + last 4 digits of a bank account number."""
    value = str(value).replace(" ", "").replace("-", "")
    return "****" + value[-4:] if len(value) >= 4 else "****"


def mask_pii(features: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of *features* with PII fields masked.

    Masked fields:
      ssn          → SHA-256 hash
      bank_account → last-4 mask
      customer_id  → SHA-256 hash
    """
    masked = dict(features)
    for field in ("ssn",):
        if field in masked and masked[field]:
            masked[field] = _sha256(str(masked[field]))
    for field in ("bank_account",):
        if field in masked and masked[field]:
            masked[field] = _mask_bank_account(str(masked[field]))
    for field in ("customer_id",):
        if field in masked and masked[field]:
            masked[field] = _sha256(str(masked[field]))
    return masked


# ---------------------------------------------------------------------------
# DDL — create audit_log table if it does not exist
# ---------------------------------------------------------------------------

_CREATE_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS audit_log (
    log_id                TEXT PRIMARY KEY,
    application_id        TEXT NOT NULL,
    logged_at             TEXT NOT NULL,
    input_features        TEXT,
    model_version         TEXT,
    feature_version       TEXT,
    fraud_score           REAL,
    risk_score            REAL,
    decision_output       TEXT,
    reason_codes          TEXT,
    decision_latency_ms   INTEGER
);
"""

_INSERT_AUDIT = """
INSERT INTO audit_log (
    log_id, application_id, logged_at, input_features,
    model_version, feature_version,
    fraud_score, risk_score,
    decision_output, reason_codes, decision_latency_ms
) VALUES (
    :log_id, :application_id, :logged_at, :input_features,
    :model_version, :feature_version,
    :fraud_score, :risk_score,
    :decision_output, :reason_codes, :decision_latency_ms
)
"""

_SELECT_AUDIT = """
SELECT * FROM audit_log WHERE application_id = :application_id
ORDER BY logged_at DESC LIMIT 1
"""


# ---------------------------------------------------------------------------
# Engine cache (avoid re-creating engines for the same db_url)
# ---------------------------------------------------------------------------

_ENGINE_CACHE: Dict[str, AsyncEngine] = {}


def _get_engine(db_url: str) -> AsyncEngine:
    if db_url not in _ENGINE_CACHE:
        _ENGINE_CACHE[db_url] = create_async_engine(db_url, echo=False)
    return _ENGINE_CACHE[db_url]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def log_decision(
    decision_result: Any,
    feature_version: str,
    model_versions: Dict[str, str],
    input_features: Dict[str, Any],
    db_url: str,
) -> str:
    """Persist a decision audit record and return the generated ``log_id``.

    Parameters
    ----------
    decision_result:
        A ``DecisionResult`` dataclass (or any object with the attributes
        ``application_id``, ``decision``, ``reason_codes``,
        ``decision_latency_ms``, and optionally ``recommended_rate``).
        Can also be a plain ``dict``.
    feature_version:
        Version string of the feature pipeline that produced the features.
    model_versions:
        Dict mapping model names to versions, e.g.
        ``{"fraud": "v1", "credit_risk": "v1"}``.
        ``fraud_score`` is read from key ``"fraud_score"`` if present,
        ``risk_score`` from ``"risk_score"``.
    input_features:
        Raw feature dict (will be PII-masked before storage).
    db_url:
        SQLAlchemy async connection URL.
        Use ``"sqlite+aiosqlite:///:memory:"`` for tests.

    Returns
    -------
    str
        The UUID ``log_id`` for the inserted audit record.
    """
    log_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Support both dataclass and dict decision_result
    if isinstance(decision_result, dict):
        dr = decision_result
        application_id = dr.get("application_id", "")
        decision_output = dr.get("decision", "")
        reason_codes = dr.get("reason_codes", [])
        decision_latency_ms = dr.get("decision_latency_ms", 0)
    else:
        application_id = getattr(decision_result, "application_id", "")
        decision_output = getattr(decision_result, "decision", "")
        reason_codes = getattr(decision_result, "reason_codes", [])
        decision_latency_ms = getattr(decision_result, "decision_latency_ms", 0)

    # Extract scores from model_versions dict (or input_features for convenience)
    fraud_score = float(model_versions.get("fraud_score", input_features.get("fraud_probability", 0.0)))
    risk_score = float(model_versions.get("risk_score", input_features.get("pd_score", 0.0)))

    model_version_str = json.dumps(
        {k: v for k, v in model_versions.items() if k not in ("fraud_score", "risk_score")}
    )

    masked_features = mask_pii(input_features)

    params: Dict[str, Any] = {
        "log_id": log_id,
        "application_id": str(application_id),
        "logged_at": now,
        "input_features": json.dumps(masked_features),
        "model_version": model_version_str,
        "feature_version": feature_version,
        "fraud_score": fraud_score,
        "risk_score": risk_score,
        "decision_output": str(decision_output),
        "reason_codes": json.dumps(reason_codes),
        "decision_latency_ms": int(decision_latency_ms),
    }

    engine = _get_engine(db_url)

    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_AUDIT_TABLE))
        await conn.execute(text(_INSERT_AUDIT), params)

    logger.info(
        "Audit log written: log_id=%s application_id=%s decision=%s",
        log_id,
        application_id,
        decision_output,
    )
    return log_id


async def get_audit_record(
    application_id: str,
    db_url: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent audit record for *application_id*.

    Parameters
    ----------
    application_id:
        UUID string of the loan application.
    db_url:
        SQLAlchemy async connection URL.

    Returns
    -------
    dict or None
        Dictionary of all audit_log columns, with ``input_features``,
        ``reason_codes``, and ``model_version`` JSON-decoded.
        Returns ``None`` if no record is found.
    """
    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_AUDIT), {"application_id": application_id}
            )
        except Exception:
            # Table may not exist yet in tests
            return None

        row = result.mappings().fetchone()
        if row is None:
            return None

        record: Dict[str, Any] = dict(row)

        # JSON-decode structured fields
        for field_name in ("input_features", "reason_codes", "model_version"):
            if record.get(field_name):
                try:
                    record[field_name] = json.loads(record[field_name])
                except (json.JSONDecodeError, TypeError):
                    pass  # leave as-is

    return record
