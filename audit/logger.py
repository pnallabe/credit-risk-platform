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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# PROMPT-05: Import tracing — no-op if opentelemetry-sdk is not installed
try:
    from observability.tracing import TRACER, span as _trace_span
except ImportError:  # pragma: no cover
    TRACER = None  # type: ignore[assignment]
    import contextlib as _contextlib
    _trace_span = _contextlib.nullcontext  # type: ignore[assignment]

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
    tenant_id             TEXT NOT NULL,
    application_id        TEXT NOT NULL,
    logged_at             TEXT NOT NULL,
    input_features        TEXT,
    model_version         TEXT,
    feature_version       TEXT,
    fraud_score           REAL,
    risk_score            REAL,
    decision_output       TEXT,
    reason_codes          TEXT,
    decision_latency_ms   INTEGER,
    -- Section 19: CC Originations Valuation fields (NULL = non-valuation decision)
    scenario_weighted_cnpv      REAL,
    cnpv_base                   REAL,
    cnpv_worsening              REAL,
    cnpv_recession              REAL,
    ftp_rate_bps                REAL,
    rwa_usd                     REAL,
    capital_available_usd       REAL,
    acquisition_signal          TEXT,
    recommended_apr             REAL,
    recommended_credit_limit    INTEGER,
    scenario_name               TEXT,
    model_version_valuation     TEXT,
    policy_version              TEXT,
    record_hash       TEXT,
    previous_hash     TEXT,
    hash_algorithm    TEXT NOT NULL DEFAULT 'sha256'
);
"""

_INSERT_AUDIT = """
INSERT INTO audit_log (
    log_id, tenant_id, application_id, logged_at, input_features,
    model_version, feature_version,
    fraud_score, risk_score,
    decision_output, reason_codes, decision_latency_ms,
    scenario_weighted_cnpv, cnpv_base, cnpv_worsening, cnpv_recession,
    ftp_rate_bps, rwa_usd, capital_available_usd,
    acquisition_signal, recommended_apr, recommended_credit_limit,
    scenario_name, model_version_valuation, policy_version
) VALUES (
    :log_id, :tenant_id, :application_id, :logged_at, :input_features,
    :model_version, :feature_version,
    :fraud_score, :risk_score,
    :decision_output, :reason_codes, :decision_latency_ms,
    :scenario_weighted_cnpv, :cnpv_base, :cnpv_worsening, :cnpv_recession,
    :ftp_rate_bps, :rwa_usd, :capital_available_usd,
    :acquisition_signal, :recommended_apr, :recommended_credit_limit,
    :scenario_name, :model_version_valuation, :policy_version
)
"""

_INSERT_AUDIT_WITH_HASH = """
INSERT INTO audit_log (
    log_id, tenant_id, application_id, logged_at, input_features,
    model_version, feature_version,
    fraud_score, risk_score,
    decision_output, reason_codes, decision_latency_ms,
    scenario_weighted_cnpv, cnpv_base, cnpv_worsening, cnpv_recession,
    ftp_rate_bps, rwa_usd, capital_available_usd,
    acquisition_signal, recommended_apr, recommended_credit_limit,
    scenario_name, model_version_valuation, policy_version,
    record_hash, previous_hash, hash_algorithm
) VALUES (
    :log_id, :tenant_id, :application_id, :logged_at, :input_features,
    :model_version, :feature_version,
    :fraud_score, :risk_score,
    :decision_output, :reason_codes, :decision_latency_ms,
    :scenario_weighted_cnpv, :cnpv_base, :cnpv_worsening, :cnpv_recession,
    :ftp_rate_bps, :rwa_usd, :capital_available_usd,
    :acquisition_signal, :recommended_apr, :recommended_credit_limit,
    :scenario_name, :model_version_valuation, :policy_version,
    :record_hash, :previous_hash, :hash_algorithm
)
"""

_SELECT_AUDIT = """
SELECT * FROM audit_log
WHERE tenant_id = :tenant_id AND application_id = :application_id
ORDER BY logged_at DESC LIMIT 1
"""


# ---------------------------------------------------------------------------
# DDL — portfolio_audit_log table (Section 20.12.2)
# ---------------------------------------------------------------------------

_CREATE_PORTFOLIO_AUDIT_TABLE = """
CREATE TABLE IF NOT EXISTS portfolio_audit_log (
    log_id                  TEXT PRIMARY KEY,
    account_id              TEXT NOT NULL,    -- SHA-256 hashed (PII)
    review_month            TEXT NOT NULL,    -- YYYY-MM
    recommended_action      TEXT NOT NULL,    -- HOLD/CLI/CLD/APR_UP/APR_DOWN
    action_confidence       REAL,
    guardrail_override      INTEGER,          -- 1 if guardrail changed ML recommendation
    guardrail_reason        TEXT,
    current_credit_limit    INTEGER,
    proposed_credit_limit   INTEGER,
    current_apr             REAL,
    proposed_apr            REAL,
    cnpv_delta_base         REAL,
    cnpv_delta_worsening    REAL,
    cnpv_delta_recession    REAL,
    scenario_weighted_delta REAL,
    incremental_rwa_usd     REAL,
    model_version_portfolio TEXT,
    feature_version         TEXT,
    policy_version          TEXT,
    logged_at               TEXT NOT NULL,
    record_hash       TEXT,
    previous_hash     TEXT,
    hash_algorithm    TEXT NOT NULL DEFAULT 'sha256'
);
"""

_INSERT_PORTFOLIO_AUDIT = """
INSERT INTO portfolio_audit_log (
    log_id, account_id, review_month,
    recommended_action, action_confidence,
    guardrail_override, guardrail_reason,
    current_credit_limit, proposed_credit_limit,
    current_apr, proposed_apr,
    cnpv_delta_base, cnpv_delta_worsening, cnpv_delta_recession,
    scenario_weighted_delta, incremental_rwa_usd,
    model_version_portfolio, feature_version, policy_version,
    logged_at
) VALUES (
    :log_id, :account_id, :review_month,
    :recommended_action, :action_confidence,
    :guardrail_override, :guardrail_reason,
    :current_credit_limit, :proposed_credit_limit,
    :current_apr, :proposed_apr,
    :cnpv_delta_base, :cnpv_delta_worsening, :cnpv_delta_recession,
    :scenario_weighted_delta, :incremental_rwa_usd,
    :model_version_portfolio, :feature_version, :policy_version,
    :logged_at
)
"""

_INSERT_PORTFOLIO_AUDIT_WITH_HASH = """
INSERT INTO portfolio_audit_log (
    log_id, account_id, review_month,
    recommended_action, action_confidence,
    guardrail_override, guardrail_reason,
    current_credit_limit, proposed_credit_limit,
    current_apr, proposed_apr,
    cnpv_delta_base, cnpv_delta_worsening, cnpv_delta_recession,
    scenario_weighted_delta, incremental_rwa_usd,
    model_version_portfolio, feature_version, policy_version,
    logged_at,
    record_hash, previous_hash, hash_algorithm
) VALUES (
    :log_id, :account_id, :review_month,
    :recommended_action, :action_confidence,
    :guardrail_override, :guardrail_reason,
    :current_credit_limit, :proposed_credit_limit,
    :current_apr, :proposed_apr,
    :cnpv_delta_base, :cnpv_delta_worsening, :cnpv_delta_recession,
    :scenario_weighted_delta, :incremental_rwa_usd,
    :model_version_portfolio, :feature_version, :policy_version,
    :logged_at,
    :record_hash, :previous_hash, :hash_algorithm
)
"""

_SELECT_PORTFOLIO_AUDIT = """
SELECT * FROM portfolio_audit_log WHERE account_id = :account_id
ORDER BY logged_at DESC LIMIT 100
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
# Hash chain helper (module-level so adverse_action_store can import it)
# ---------------------------------------------------------------------------

async def compute_chain_hash(
    conn: Any,
    log_id: str,
    logged_at: str,
    canonical_payload: str,
    partition_value: str,
    table: str = "audit_log",
    partition_field: str = "tenant_id",
    timestamp_field: str = "logged_at",
    id_field: str = "log_id",
) -> tuple:
    """Compute (record_hash, previous_hash) for a new chain entry.

    Parameters
    ----------
    conn:
        Active SQLAlchemy async connection (must be inside a transaction so
        no other row can be inserted between the SELECT and the caller's INSERT).
    log_id:
        UUID of the row being inserted.
    logged_at:
        ISO-8601 UTC timestamp of the row being inserted.
    canonical_payload:
        ``json.dumps(..., sort_keys=True, separators=(',',':'))`` of the
        fields relevant to the table (decision fields for audit_log, etc.).
    partition_value:
        Value of the partition key (tenant_id for audit_log,
        account_id for portfolio_audit_log, etc.).
    table:
        Table name to query for the previous hash.
    partition_field:
        Column name used to scope the chain per partition.

    Returns
    -------
    tuple[str, str]
        ``(record_hash, previous_hash)`` where ``previous_hash`` is the
        empty string ``""`` for the very first row in the partition.
    """
    query = text(
        f"SELECT record_hash FROM {table}"
        f" WHERE {partition_field} = :pval"
        f" ORDER BY {timestamp_field} DESC, {id_field} ASC LIMIT 1"
    )
    result = await conn.execute(query, {"pval": partition_value})
    row = result.fetchone()
    previous_hash: str = (row[0] or "") if row else ""

    raw = previous_hash + "|" + log_id + "|" + logged_at + "|" + canonical_payload
    record_hash = _sha256(raw)
    return record_hash, previous_hash


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def log_decision(
    decision_result: Any,
    feature_version: str,
    model_versions: Dict[str, str],
    input_features: Dict[str, Any],
    db_url: str,
    tenant_id: str,
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
    tenant_id:
        Opaque tenant identifier from JWT claims.  Required — any call
        site that cannot supply this value has a security gap.

    Returns
    -------
    str
        The UUID ``log_id`` for the inserted audit record.
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required for audit log writes")

    with _trace_span("audit.log_decision", TRACER):
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
        # Section 19: also mask origination_id -> SHA-256 in CC valuation records
        if "origination_id" in masked_features and masked_features["origination_id"]:
            masked_features["origination_id"] = _sha256(str(masked_features["origination_id"]))

        # Extract CC valuation fields (all must be present if decision_result carries them;
        # None is stored as NULL — NOT permitted in compliance records — callers must supply values)
        dr_dict = decision_result if isinstance(decision_result, dict) else vars(decision_result) if hasattr(decision_result, "__dict__") else {}

        params: Dict[str, Any] = {
            "log_id": log_id,
            "tenant_id": tenant_id,
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
            # CC valuation fields (Section 19) — None if not a valuation decision
            "scenario_weighted_cnpv":   dr_dict.get("scenario_weighted_cnpv"),
            "cnpv_base":                dr_dict.get("cnpv_base"),
            "cnpv_worsening":           dr_dict.get("cnpv_worsening"),
            "cnpv_recession":           dr_dict.get("cnpv_recession"),
            "ftp_rate_bps":             dr_dict.get("ftp_rate_bps"),
            "rwa_usd":                  dr_dict.get("rwa_usd"),
            "capital_available_usd":    dr_dict.get("capital_available_usd"),
            "acquisition_signal":       dr_dict.get("acquisition_signal"),
            "recommended_apr":          dr_dict.get("recommended_apr"),
            "recommended_credit_limit": dr_dict.get("recommended_credit_limit"),
            "scenario_name":            dr_dict.get("scenario_name"),
            "model_version_valuation":  dr_dict.get("model_version_valuation"),
            "policy_version":           dr_dict.get("policy_version"),
        }

        # Build canonical payload for hash chain (keys sorted alphabetically)
        canonical_payload = json.dumps(
            {
                "decision_output": params["decision_output"],
                "fraud_score": params["fraud_score"],
                "reason_codes": params["reason_codes"],
                "risk_score": params["risk_score"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        engine = _get_engine(db_url)

        async with engine.begin() as conn:
            await conn.execute(text(_CREATE_AUDIT_TABLE))
            try:
                record_hash, previous_hash = await compute_chain_hash(
                    conn, log_id, now, canonical_payload, tenant_id, table="audit_log"
                )
                hash_params = {
                    **params,
                    "record_hash": record_hash,
                    "previous_hash": previous_hash,
                    "hash_algorithm": "sha256",
                }
                await conn.execute(text(_INSERT_AUDIT_WITH_HASH), hash_params)
            except Exception as _hash_exc:
                logger.debug(
                    "Hash chain write skipped (pre-migration schema): %s", _hash_exc
                )
                await conn.execute(text(_INSERT_AUDIT), params)

        logger.info(
            "Audit log written: log_id=%s tenant_id=%s application_id=%s decision=%s",
            log_id,
            tenant_id,
            application_id,
            decision_output,
        )
        return log_id


async def get_audit_record(
    application_id: str,
    db_url: str,
    tenant_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent audit record for *application_id*.

    Parameters
    ----------
    application_id:
        UUID string of the loan application.
    db_url:
        SQLAlchemy async connection URL.
    tenant_id:
        Opaque tenant identifier — enforces row-level tenant isolation.
        A missing or empty tenant_id raises ``ValueError``.

    Returns
    -------
    dict or None
        Dictionary of all audit_log columns, with ``input_features``,
        ``reason_codes``, and ``model_version`` JSON-decoded.
        Returns ``None`` if no record is found for this tenant.
    """
    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required for audit log reads")
    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_AUDIT),
                {"tenant_id": tenant_id, "application_id": application_id},
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


# ---------------------------------------------------------------------------
# Section 20 — Portfolio Action Audit
# ---------------------------------------------------------------------------


async def log_portfolio_action(
    account_id: str,
    review_month: str,
    action_result: Dict[str, Any],
    feature_version: str,
    model_version_portfolio: str,
    policy_version: str,
    db_url: str,
) -> str:
    """Persist a portfolio action audit record and return the generated ``log_id``.

    Parameters
    ----------
    account_id:
        Raw account / origination ID — will be SHA-256 hashed before storage.
    review_month:
        YYYY-MM string for the review cycle.
    action_result:
        Dict returned by ``decision_engine.portfolio_review`` for one account.
        Expected keys: final_action, action_confidence, guardrail_reason,
        current_credit_limit, new_credit_limit, current_apr, new_apr,
        cnpv_delta_base, cnpv_delta_worsening, cnpv_delta_recession,
        cnpv_delta_scenario_weighted, incremental_rwa_usd.
    feature_version:
        Feature pipeline version string.
    model_version_portfolio:
        MLflow version of the portfolio action model.
    policy_version:
        Credit policy version used for this review batch.
    db_url:
        SQLAlchemy async connection URL.

    Returns
    -------
    str — UUID log_id.
    """
    log_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc).isoformat()

    guardrail_reason = action_result.get("guardrail_reason", "") or ""
    guardrail_override = 1 if bool(guardrail_reason) else 0

    params: Dict[str, Any] = {
        "log_id":                   log_id,
        "account_id":               _sha256(str(account_id)),
        "review_month":             review_month,
        "recommended_action":       str(action_result.get("final_action", "HOLD")),
        "action_confidence":        float(action_result.get("action_confidence", 0.0)),
        "guardrail_override":       guardrail_override,
        "guardrail_reason":         guardrail_reason[:500],
        "current_credit_limit":     int(action_result.get("current_credit_limit", 0)),
        "proposed_credit_limit":    int(action_result.get("new_credit_limit", 0)),
        "current_apr":              float(action_result.get("current_apr", 0.0)),
        "proposed_apr":             float(action_result.get("new_apr", 0.0)),
        "cnpv_delta_base":          float(action_result.get("cnpv_delta_base", 0.0)),
        "cnpv_delta_worsening":     float(action_result.get("cnpv_delta_worsening", 0.0)),
        "cnpv_delta_recession":     float(action_result.get("cnpv_delta_recession", 0.0)),
        "scenario_weighted_delta":  float(action_result.get("cnpv_delta_scenario_weighted", 0.0)),
        "incremental_rwa_usd":      float(action_result.get("incremental_rwa_usd", 0.0)),
        "model_version_portfolio":  model_version_portfolio,
        "feature_version":          feature_version,
        "policy_version":           policy_version,
        "logged_at":                now,
    }

    # Build canonical payload for hash chain
    canonical_payload = json.dumps(
        {
            "model_version_portfolio": params["model_version_portfolio"],
            "policy_version": params["policy_version"],
            "recommended_action": params["recommended_action"],
            "scenario_weighted_delta": params["scenario_weighted_delta"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_PORTFOLIO_AUDIT_TABLE))
        try:
            record_hash, previous_hash = await compute_chain_hash(
                conn, log_id, params["logged_at"], canonical_payload,
                params["account_id"], table="portfolio_audit_log",
                partition_field="account_id",
            )
            hash_params = {
                **params,
                "record_hash": record_hash,
                "previous_hash": previous_hash,
                "hash_algorithm": "sha256",
            }
            await conn.execute(text(_INSERT_PORTFOLIO_AUDIT_WITH_HASH), hash_params)
        except Exception as _hash_exc:
            logger.debug(
                "Hash chain write skipped (pre-migration schema): %s", _hash_exc
            )
            await conn.execute(text(_INSERT_PORTFOLIO_AUDIT), params)

    logger.info(
        "Portfolio audit log written: log_id=%s account_id=***%s action=%s",
        log_id,
        str(account_id)[-4:],
        params["recommended_action"],
    )
    return log_id


async def get_portfolio_audit_records(
    account_id: str,
    db_url: str,
) -> List[Dict[str, Any]]:
    """Retrieve all portfolio audit records for ``account_id`` (hashed lookup).

    Returns
    -------
    List of dicts, newest first.  Returns empty list if no records found.
    SLA: < 100ms indexed lookup on account_id.
    """
    hashed_id = _sha256(str(account_id))
    engine    = _get_engine(db_url)

    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_PORTFOLIO_AUDIT), {"account_id": hashed_id}
            )
        except Exception:
            return []

        rows = result.mappings().fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Section 21 — governance_approval_log  (MRM lifecycle decisions — immutable)
# ---------------------------------------------------------------------------

_CREATE_GOVERNANCE_APPROVAL_LOG = """
CREATE TABLE IF NOT EXISTS governance_approval_log (
    approval_id         TEXT PRIMARY KEY,
    model_name          TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    action              TEXT NOT NULL,
    from_stage          TEXT,
    to_stage            TEXT,
    performed_by        TEXT NOT NULL,
    approved_by         TEXT,
    performed_at        TEXT NOT NULL,
    governance_metrics  TEXT,
    notes               TEXT,
    mlflow_run_id       TEXT
);
"""
# action values: REGISTER / PROMOTE_STAGING / PROMOTE_PRODUCTION / ARCHIVE /
#                VALIDATION_PASS / VALIDATION_FAIL / GOVERNANCE_OVERRIDE /
#                REVIEW_DUE
# Retention: 7 years.  No UPDATE, no DELETE.

_INSERT_GOVERNANCE_APPROVAL = """
INSERT INTO governance_approval_log (
    approval_id, model_name, model_version, action,
    from_stage, to_stage,
    performed_by, approved_by, performed_at,
    governance_metrics, notes, mlflow_run_id
) VALUES (
    :approval_id, :model_name, :model_version, :action,
    :from_stage, :to_stage,
    :performed_by, :approved_by, :performed_at,
    :governance_metrics, :notes, :mlflow_run_id
)
"""

_SELECT_GOVERNANCE_LOG = """
SELECT * FROM governance_approval_log
WHERE model_name = :model_name
ORDER BY performed_at DESC
LIMIT :limit OFFSET :offset
"""


async def log_governance_action(
    model_name: str,
    model_version: str,
    action: str,
    from_stage: Optional[str],
    to_stage: Optional[str],
    performed_by: str,
    approved_by: Optional[str],
    governance_metrics: Dict[str, Any],
    notes: str,
    mlflow_run_id: Optional[str],
    db_url: str,
) -> str:
    """Write an immutable governance approval record.

    Parameters
    ----------
    model_name:       MLflow registered model name.
    model_version:    Model version string.
    action:           Lifecycle action (REGISTER, PROMOTE_PRODUCTION, etc.).
    from_stage:       Source stage (None for initial registration).
    to_stage:         Target stage.
    performed_by:     Email or service-account of the person/system acting.
    approved_by:      Second approver email (required for PROMOTE_PRODUCTION).
    governance_metrics: Metrics snapshot at time of decision (JSON-serialisable).
    notes:            Free-text rationale.
    mlflow_run_id:    Associated MLflow run ID (for cross-reference).
    db_url:           SQLAlchemy async DB URL.

    Returns
    -------
    str — UUID ``approval_id`` of the inserted record.
    """
    approval_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    params: Dict[str, Any] = {
        "approval_id":        approval_id,
        "model_name":         model_name,
        "model_version":      str(model_version),
        "action":             action,
        "from_stage":         from_stage,
        "to_stage":           to_stage,
        "performed_by":       performed_by,
        "approved_by":        approved_by,
        "performed_at":       now,
        "governance_metrics": json.dumps(governance_metrics),
        "notes":              notes[:2000] if notes else "",
        "mlflow_run_id":      mlflow_run_id,
    }

    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_GOVERNANCE_APPROVAL_LOG))
        await conn.execute(text(_INSERT_GOVERNANCE_APPROVAL), params)

    logger.info(
        "Governance action logged: approval_id=%s model=%s v%s action=%s",
        approval_id, model_name, model_version, action,
    )
    return approval_id


async def get_governance_audit_log(
    model_name: str,
    db_url: str,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Retrieve paginated governance audit log for *model_name*.

    Returns list of dicts newest-first; ``governance_metrics`` is JSON-decoded.
    """
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_GOVERNANCE_LOG),
                {"model_name": model_name, "limit": limit, "offset": offset},
            )
        except Exception:
            return []
        rows = result.mappings().fetchall()
    records = [dict(r) for r in rows]
    for rec in records:
        if rec.get("governance_metrics"):
            try:
                rec["governance_metrics"] = json.loads(rec["governance_metrics"])
            except (json.JSONDecodeError, TypeError):
                pass
    return records


# ---------------------------------------------------------------------------
# Section 21 — model_validation_log  (SR 11-7 independent validation records)
# ---------------------------------------------------------------------------

_CREATE_MODEL_VALIDATION_LOG = """
CREATE TABLE IF NOT EXISTS model_validation_log (
    validation_id       TEXT PRIMARY KEY,
    model_name          TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    validator_email     TEXT NOT NULL,
    validation_date     TEXT NOT NULL,
    validation_type     TEXT NOT NULL,
    outcome             TEXT NOT NULL,
    conditions          TEXT,
    findings            TEXT,
    test_scripts_ref    TEXT,
    approved_for_prod   INTEGER NOT NULL,
    notes               TEXT
);
"""
# validation_type: INITIAL / ANNUAL / TRIGGERED
# outcome: PASS / PASS_WITH_CONDITIONS / FAIL
# approved_for_prod: 1 = True, 0 = False
# test_scripts_ref: git SHA of the validation test scripts

_INSERT_MODEL_VALIDATION = """
INSERT INTO model_validation_log (
    validation_id, model_name, model_version,
    validator_email, validation_date, validation_type,
    outcome, conditions, findings, test_scripts_ref,
    approved_for_prod, notes
) VALUES (
    :validation_id, :model_name, :model_version,
    :validator_email, :validation_date, :validation_type,
    :outcome, :conditions, :findings, :test_scripts_ref,
    :approved_for_prod, :notes
)
"""

_SELECT_MODEL_VALIDATIONS = """
SELECT * FROM model_validation_log
WHERE model_name = :model_name
ORDER BY validation_date DESC
"""


async def log_model_validation(
    model_name: str,
    model_version: str,
    validator_email: str,
    validation_type: str,
    outcome: str,
    conditions: Optional[List[str]],
    findings: Optional[Dict[str, Any]],
    test_scripts_ref: Optional[str],
    approved_for_prod: bool,
    notes: str,
    db_url: str,
    submitted_by: Optional[str] = None,
) -> str:
    """Write a model validation log entry.

    Parameters
    ----------
    validator_email:    Independent validator email.  Must differ from
                        *submitted_by* (SR 11-7 four-eyes requirement).
    validation_type:    INITIAL | ANNUAL | TRIGGERED
    outcome:            PASS | PASS_WITH_CONDITIONS | FAIL
    conditions:         List of required remediation items (for PASS_WITH_CONDITIONS).
    findings:           Detailed findings dict.
    test_scripts_ref:   Git SHA of the validation test scripts.
    approved_for_prod:  Whether the validator approved for production promotion.
    submitted_by:       Email of the developer/submitter who built the model.
                        When provided, the function enforces SR 11-7 independence:
                        validator_email must differ from submitted_by.

    Returns
    -------
    str — UUID ``validation_id``.

    Raises
    ------
    SeparationOfDutiesViolation
        If *submitted_by* equals *validator_email* (same person cannot both
        build and independently validate a model).
    """
    # SR 11-7: Independent Model Validation — enforce separation of duties
    if submitted_by and validator_email.lower().strip() == submitted_by.lower().strip():
        from compliance.rbac import SeparationOfDutiesViolation  # local import avoids circular
        raise SeparationOfDutiesViolation(
            f"Validator ({validator_email}) and model submitter ({submitted_by}) must be "
            "different people — SR 11-7 independence requirement."
        )

    validation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    params: Dict[str, Any] = {
        "validation_id":    validation_id,
        "model_name":       model_name,
        "model_version":    str(model_version),
        "validator_email":  validator_email,
        "validation_date":  now,
        "validation_type":  validation_type,
        "outcome":          outcome,
        "conditions":       json.dumps(conditions or []),
        "findings":         json.dumps(findings or {}),
        "test_scripts_ref": test_scripts_ref,
        "approved_for_prod": 1 if approved_for_prod else 0,
        "notes":            notes[:2000] if notes else "",
    }

    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_MODEL_VALIDATION_LOG))
        await conn.execute(text(_INSERT_MODEL_VALIDATION), params)

    logger.info(
        "Model validation logged: validation_id=%s model=%s v%s outcome=%s",
        validation_id, model_name, model_version, outcome,
    )
    return validation_id


async def get_model_validations(
    model_name: str,
    db_url: str,
) -> List[Dict[str, Any]]:
    """Retrieve all validation log entries for *model_name*, newest first.

    ``conditions`` and ``findings`` are JSON-decoded.
    Returns empty list if no records found.
    """
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_MODEL_VALIDATIONS), {"model_name": model_name}
            )
        except Exception:
            return []
        rows = result.mappings().fetchall()
    records = [dict(r) for r in rows]
    for rec in records:
        for field_name in ("conditions", "findings"):
            if rec.get(field_name):
                try:
                    rec[field_name] = json.loads(rec[field_name])
                except (json.JSONDecodeError, TypeError):
                    pass
        rec["approved_for_prod"] = bool(rec.get("approved_for_prod", 0))
    return records


async def check_validation_independence(
    model_name: str,
    model_version: str,
    validator_email: str,
    db_url: str,
) -> bool:
    """Return True if validator_email differs from the model developer email.

    Reads the MLflow run tags (``developer_email`` tag) to verify independence.
    If the tag is absent, logs a warning and returns True (cannot enforce).
    """
    try:
        import mlflow
        from mlflow.tracking import MlflowClient
        client = MlflowClient()
        mv = client.get_model_version(model_name, model_version)
        if mv.run_id:
            run = mlflow.get_run(mv.run_id)
            developer_email = run.data.tags.get("developer_email", "")
            if developer_email and developer_email.lower() == validator_email.lower():
                logger.error(
                    "Independence violation: validator_email=%s matches developer_email "
                    "for model %s v%s — rejecting validation.",
                    validator_email, model_name, model_version,
                )
                return False
    except Exception as exc:
        logger.warning("Could not verify validation independence: %s", exc)
    return True


# ---------------------------------------------------------------------------
# Section 21 — adverse_action_notice_queue  (FCRA/ECOA 30-day dispatch SLA)
# ---------------------------------------------------------------------------

_CREATE_ADVERSE_ACTION_QUEUE = """
CREATE TABLE IF NOT EXISTS adverse_action_notice_queue (
    notice_id           TEXT PRIMARY KEY,
    account_id          TEXT NOT NULL,
    action_type         TEXT NOT NULL,
    reason_codes        TEXT NOT NULL,
    review_month        TEXT NOT NULL,
    model_version       TEXT NOT NULL,
    enqueued_at         TEXT NOT NULL,
    dispatch_deadline   TEXT NOT NULL,
    dispatched_at       TEXT,
    dispatch_channel    TEXT,
    dispatch_status     TEXT DEFAULT 'PENDING'
);
"""
# action_type: CLD / APR_UP / DECLINE
# reason_codes: JSON array — minimum 2 items (FCRA requirement)
# dispatch_deadline = enqueued_at + 30 days
# dispatch_status: PENDING / SENT / FAILED

_INSERT_ADVERSE_ACTION = """
INSERT INTO adverse_action_notice_queue (
    notice_id, account_id, action_type, reason_codes,
    review_month, model_version,
    enqueued_at, dispatch_deadline,
    dispatched_at, dispatch_channel, dispatch_status
) VALUES (
    :notice_id, :account_id, :action_type, :reason_codes,
    :review_month, :model_version,
    :enqueued_at, :dispatch_deadline,
    :dispatched_at, :dispatch_channel, :dispatch_status
)
"""

_SELECT_PENDING_ADVERSE_ACTIONS = """
SELECT * FROM adverse_action_notice_queue
WHERE dispatch_status = 'PENDING'
ORDER BY dispatch_deadline ASC
"""

_SELECT_OVERDUE_ADVERSE_ACTIONS = """
SELECT * FROM adverse_action_notice_queue
WHERE dispatch_status = 'PENDING'
  AND dispatch_deadline < :now
ORDER BY dispatch_deadline ASC
"""


async def enqueue_adverse_action_notice(
    account_id: str,
    action_type: str,
    reason_codes: List[str],
    review_month: str,
    model_version: str,
    dispatch_channel: Optional[str],
    db_url: str,
) -> str:
    """Enqueue an adverse action notice for 30-day FCRA/ECOA dispatch.

    Parameters
    ----------
    account_id:       Raw account ID (NOT hashed — needed for delivery routing).
    action_type:      CLD | APR_UP | DECLINE
    reason_codes:     Minimum 2 CFPB/FCRA reason codes (raises ValueError if < 2).
    review_month:     YYYY-MM of the review batch.
    model_version:    MLflow version of the portfolio action model.
    dispatch_channel: EMAIL | MAIL | SMS (None = not yet assigned).

    Returns
    -------
    str — UUID ``notice_id``.

    Raises
    ------
    ValueError
        If ``reason_codes`` contains fewer than 2 items (FCRA minimum).
    """
    if len(reason_codes) < 2:
        raise ValueError(
            f"FCRA requires minimum 2 reason codes; received {len(reason_codes)} "
            f"for account_id={account_id} action={action_type}."
        )

    notice_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    # Dispatch deadline = 30 calendar days from enqueue
    deadline = now.replace(microsecond=0) + timedelta(days=30)

    params: Dict[str, Any] = {
        "notice_id":        notice_id,
        "account_id":       account_id,    # NOT hashed — delivery system needs it
        "action_type":      action_type,
        "reason_codes":     json.dumps(reason_codes),
        "review_month":     review_month,
        "model_version":    model_version,
        "enqueued_at":      now.isoformat(),
        "dispatch_deadline": deadline.isoformat(),
        "dispatched_at":    None,
        "dispatch_channel": dispatch_channel,
        "dispatch_status":  "PENDING",
    }

    engine = _get_engine(db_url)
    async with engine.begin() as conn:
        await conn.execute(text(_CREATE_ADVERSE_ACTION_QUEUE))
        await conn.execute(text(_INSERT_ADVERSE_ACTION), params)

    logger.info(
        "Adverse action notice enqueued: notice_id=%s account=***%s action=%s deadline=%s",
        notice_id, str(account_id)[-4:], action_type, deadline.date(),
    )
    return notice_id


async def get_adverse_action_pending(
    db_url: str,
) -> List[Dict[str, Any]]:
    """Return all PENDING adverse action notices, sorted by dispatch_deadline ASC.

    ``reason_codes`` is JSON-decoded.  Overdue records (deadline < now) appear first
    since they are sorted ascending.
    """
    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text(_SELECT_PENDING_ADVERSE_ACTIONS))
        except Exception:
            return []
        rows = result.mappings().fetchall()
    records = [dict(r) for r in rows]
    now_iso = datetime.now(timezone.utc).isoformat()
    for rec in records:
        if rec.get("reason_codes"):
            try:
                rec["reason_codes"] = json.loads(rec["reason_codes"])
            except (json.JSONDecodeError, TypeError):
                pass
        rec["overdue"] = bool(
            rec.get("dispatch_deadline") and rec["dispatch_deadline"] < now_iso
        )
    return records


async def get_adverse_action_overdue(
    db_url: str,
) -> List[Dict[str, Any]]:
    """Return all adverse action notices that have breached their 30-day SLA.

    A record is overdue if ``dispatch_status = PENDING`` AND
    ``dispatch_deadline < NOW()``.
    """
    engine = _get_engine(db_url)
    now_iso = datetime.now(timezone.utc).isoformat()
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(_SELECT_OVERDUE_ADVERSE_ACTIONS), {"now": now_iso}
            )
        except Exception:
            return []
        rows = result.mappings().fetchall()
    records = [dict(r) for r in rows]
    for rec in records:
        if rec.get("reason_codes"):
            try:
                rec["reason_codes"] = json.loads(rec["reason_codes"])
            except (json.JSONDecodeError, TypeError):
                pass
        rec["overdue"] = True
    return records


# ---------------------------------------------------------------------------
# P2-D — adverse_action_log table (Reg B compliance notices)
# ---------------------------------------------------------------------------

_CREATE_ADVERSE_ACTION_TABLE = """
CREATE TABLE IF NOT EXISTS adverse_action_log (
    notice_id           TEXT PRIMARY KEY,
    application_id      TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    action_date         TEXT NOT NULL,
    deadline_date       TEXT NOT NULL,
    reason_codes        TEXT NOT NULL,
    form_type           TEXT NOT NULL,
    credit_score_used   INTEGER,
    bureau_name         TEXT,
    generated_at        TEXT NOT NULL,
    delivery_channel    TEXT,
    delivered_at        TEXT,
    delivery_status     TEXT NOT NULL DEFAULT 'PENDING',
    notice_hash         TEXT,
    record_hash         TEXT,
    previous_hash       TEXT
);
CREATE INDEX IF NOT EXISTS idx_aa_tenant_app  ON adverse_action_log(tenant_id, application_id);
CREATE INDEX IF NOT EXISTS idx_aa_deadline    ON adverse_action_log(deadline_date);
CREATE INDEX IF NOT EXISTS idx_aa_status      ON adverse_action_log(delivery_status);
"""


# ---------------------------------------------------------------------------
# P1-A — Schema migration: idempotently add hash-chain columns
# ---------------------------------------------------------------------------

async def migrate_audit_schema(db_url: str) -> None:
    """Idempotently add hash-chain columns to audit_log and portfolio_audit_log.

    Safe to call multiple times.  If the columns already exist, no
    ``ALTER TABLE`` is issued.  If the table doesn't exist yet, the base DDL
    creates it (including the hash columns).

    Parameters
    ----------
    db_url:
        SQLAlchemy async connection URL.  Supports both
        ``sqlite+aiosqlite://`` and ``postgresql+asyncpg://`` schemes.
    """
    is_postgres = db_url.startswith("postgresql")
    engine = _get_engine(db_url)

    tables_to_migrate = [
        ("audit_log", _CREATE_AUDIT_TABLE),
        ("portfolio_audit_log", _CREATE_PORTFOLIO_AUDIT_TABLE),
        ("adverse_action_log", _CREATE_ADVERSE_ACTION_TABLE),
    ]
    new_columns = [
        ("record_hash", "TEXT"),
        ("previous_hash", "TEXT"),
        ("hash_algorithm", "TEXT NOT NULL DEFAULT 'sha256'"),
    ]

    for table_name, create_ddl in tables_to_migrate:
        try:
            async with engine.begin() as conn:
                # Ensure the table exists first
                for stmt in create_ddl.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        await conn.execute(text(stmt))

                # Discover existing columns
                if is_postgres:
                    result = await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :tbl"
                        ),
                        {"tbl": table_name},
                    )
                    existing_cols = {row[0] for row in result}
                else:
                    result = await conn.execute(
                        text(f"PRAGMA table_info({table_name})")
                    )
                    existing_cols = {row[1] for row in result.fetchall()}

                for col_name, col_type in new_columns:
                    if col_name not in existing_cols:
                        await conn.execute(
                            text(
                                f"ALTER TABLE {table_name}"
                                f" ADD COLUMN {col_name} {col_type}"
                            )
                        )
                        logger.info(
                            "Added column %s to %s", col_name, table_name
                        )
        except Exception as exc:
            logger.error(
                "migrate_audit_schema failed for table=%s: %s", table_name, exc
            )
            raise


async def audit_schema_version(db_url: str) -> str:
    """Return ``'v2-hash-chain'`` if ``record_hash`` column exists, else ``'v1-no-chain'``.

    Never raises — returns ``'v1-no-chain'`` on any error.
    """
    try:
        engine = _get_engine(db_url)
        is_postgres = db_url.startswith("postgresql")
        async with engine.connect() as conn:
            if is_postgres:
                result = await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'audit_log' AND column_name = 'record_hash'"
                    )
                )
                row = result.fetchone()
                return "v2-hash-chain" if row else "v1-no-chain"
            else:
                result = await conn.execute(text("PRAGMA table_info(audit_log)"))
                cols = {row[1] for row in result.fetchall()}
                return "v2-hash-chain" if "record_hash" in cols else "v1-no-chain"
    except Exception:
        return "v1-no-chain"


# ---------------------------------------------------------------------------
# G5-D — Bulk fetch for regulatory reporting
# ---------------------------------------------------------------------------


async def get_audit_records_by_period(
    tenant_id: str,
    period_start: "date",  # noqa: F821 — imported as string to avoid circular import
    period_end: "date",
    db_url: str,
    max_records: int = 50_000,
) -> List[Dict[str, Any]]:
    """Fetch all audit log records for *tenant_id* in [period_start, period_end].

    Records are ordered oldest-first.  A safety cap of *max_records* rows is
    applied to prevent memory exhaustion on large tenants.

    Parameters
    ----------
    tenant_id:
        Opaque tenant identifier.  Required; raises ``ValueError`` if empty.
    period_start / period_end:
        Inclusive date range.  Both are required.
    db_url:
        SQLAlchemy async connection URL.
    max_records:
        Maximum number of rows to return (default: 50 000).

    Returns
    -------
    list of dict
        Each dict has the same shape as a single ``get_audit_record()`` return
        value; structured fields (``input_features``, ``reason_codes``,
        ``model_version``) are JSON-decoded when possible.
    """
    from datetime import date  # lazy import to avoid top-level cycle

    if not tenant_id or not tenant_id.strip():
        raise ValueError("tenant_id is required for audit log bulk reads")

    start_str = period_start.isoformat() if hasattr(period_start, "isoformat") else str(period_start)
    end_str = period_end.isoformat() if hasattr(period_end, "isoformat") else str(period_end)

    # End of day for period_end: include records logged up to 23:59:59 on that date.
    end_str_inclusive = end_str + "T23:59:59"

    engine = _get_engine(db_url)

    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                text(
                    """
                    SELECT *
                    FROM audit_log
                    WHERE tenant_id = :tenant_id
                      AND logged_at >= :start_ts
                      AND logged_at <= :end_ts
                    ORDER BY logged_at ASC
                    LIMIT :max_records
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "start_ts": start_str,
                    "end_ts": end_str_inclusive,
                    "max_records": int(max_records),
                },
            )
        except Exception:
            # Table may not exist in tests / fresh environments
            return []

        rows = result.mappings().fetchall()

    records: List[Dict[str, Any]] = []
    for row in rows:
        record: Dict[str, Any] = dict(row)
        for field_name in ("input_features", "reason_codes", "model_version"):
            if record.get(field_name):
                try:
                    record[field_name] = json.loads(record[field_name])
                except (json.JSONDecodeError, TypeError):
                    pass
        records.append(record)

    return records
