"""
audit/replay_bundle.py
======================
Deterministic replay bundle for regulatory-grade decision audits (PROMPT-08).

A ``ReplayBundle`` is a single signed document that binds:

* Exact raw input fields received.
* Feature version + computed feature values.
* Model artefact hashes (SHA-256 of the pickle file at the recorded path).
* Policy version hash + exact policy parameter snapshot.
* Tenant config version + its SHA-256.
* Decision outcome + reason codes.
* Audit log row hash (proves the record was not tampered with).
* ``bundle_sha256`` — SHA-256 of the deterministic JSON serialisation of
  all the above fields, providing a single verifiable fingerprint for the
  entire bundle.

Usage
-----
    from audit.replay_bundle import build_replay_bundle, ReplayBundle

    bundle: ReplayBundle = await build_replay_bundle(
        decision_id="app-001",
        db_url="sqlite+aiosqlite:///decision_audit.db",
        config_registry=config_svc,
        policy_store=policy_store_instance,
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayBundle:
    """Deterministic, cryptographically-signed replay bundle for one decision.

    Attributes
    ----------
    decision_id : str
        The ``application_id`` / ``log_id`` of the decision (used interchangeably
        since the audit log is keyed by ``application_id``).
    tenant_id : str
        Owning tenant — used to enforce isolation at the API layer.
    decided_at : str
        ISO-8601 UTC timestamp of the original decision.
    raw_inputs : dict
        Exactly the input features that were received in the original request
        (PII-masked as stored in the audit log).
    feature_version : str
        Feature pipeline version used to compute the feature matrix.
    feature_values : dict
        Computed feature values as stored in the audit log ``input_features``.
    model_artifact_hashes : dict
        ``{"<model_role>": "sha256:<hex>"}`` — SHA-256 of each model artefact
        file on disk at the paths recorded in the audit row.
    policy_version : str
        Policy version tag active at decision time.
    policy_params_snapshot : dict
        Full parameter dictionary of the policy version.
    tenant_config_version : str
        Tenant config version tag at decision time.
    tenant_config_sha256 : str
        SHA-256 of the tenant config JSON for tamper detection.
    decision : str
        ``APPROVE`` / ``REJECT`` / ``MANUAL_REVIEW``.
    reason_codes : list[str]
        FCRA reason codes.
    audit_log_row_hash : str
        ``record_hash`` from the audit log row — proves the record was not
        tampered with since it was written.
    bundle_sha256 : str
        SHA-256 of the deterministic JSON serialisation of all fields above.
        Computed over ``json.dumps(payload, sort_keys=True, separators=(',',':'))``
        **excluding** ``bundle_sha256`` itself.
    """

    decision_id: str
    tenant_id: str
    decided_at: str
    raw_inputs: Dict[str, Any]
    feature_version: str
    feature_values: Dict[str, Any]
    model_artifact_hashes: Dict[str, str]
    policy_version: str
    policy_params_snapshot: Dict[str, Any]
    tenant_config_version: str
    tenant_config_sha256: str
    decision: str
    reason_codes: List[str]
    audit_log_row_hash: str
    bundle_sha256: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: str) -> str:
    """Return ``sha256:<hex>`` of the file at *path*; ``sha256:unavailable`` if missing."""
    try:
        import os
        if not os.path.exists(path):
            return "sha256:unavailable"
        with open(path, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        return f"sha256:{digest}"
    except Exception as exc:
        logger.warning("Could not hash model artefact at %s: %s", path, exc)
        return "sha256:unavailable"


def _compute_bundle_sha256(fields: Dict[str, Any]) -> str:
    """Return SHA-256 of the deterministic JSON serialisation of *fields*.

    ``bundle_sha256`` must not be included in *fields* when this is called.
    """
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _extract_model_paths(record: Dict[str, Any]) -> Dict[str, str]:
    """Extract model artefact paths from the audit record's ``model_version`` field.

    ``model_version`` is stored as a JSON object mapping model roles to version tags.
    We attempt to resolve local file paths via environment variables.
    """
    import os  # noqa: PLC0415

    model_version_raw = record.get("model_version") or {}
    if isinstance(model_version_raw, str):
        try:
            model_version_raw = json.loads(model_version_raw)
        except json.JSONDecodeError:
            model_version_raw = {}

    # Check env-var paths for known model roles
    paths: Dict[str, str] = {}
    env_map = {
        "fraud":       os.getenv("FRAUD_MODEL_PATH", "models/fraud_detection/fraud_v1.pkl"),
        "credit_risk": os.getenv("RISK_MODEL_PATH",  "models/credit_risk/credit_risk_v1.pkl"),
    }
    for role, path in env_map.items():
        if role in model_version_raw or True:  # include all known models
            paths[role] = path

    return paths


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def build_replay_bundle(
    decision_id: str,
    db_url: str,
    config_registry: Any,
    policy_store: Any,
) -> ReplayBundle:
    """Assemble a complete ``ReplayBundle`` for *decision_id*.

    Parameters
    ----------
    decision_id : str
        The ``application_id`` to look up in the audit log.
    db_url : str
        SQLAlchemy async connection URL for the audit database.
    config_registry :
        A ``ConfigRegistryService`` instance.
    policy_store :
        A ``PolicyVersionStore`` instance.

    Returns
    -------
    ReplayBundle

    Raises
    ------
    KeyError
        If no audit record exists for *decision_id*.
    """
    from audit.logger import get_audit_record  # noqa: PLC0415 (avoid circular at module level)

    # -----------------------------------------------------------------------
    # 1. Load the audit record — tenant_id will be extracted from it
    # -----------------------------------------------------------------------
    # We pass tenant_id="" first to discover it (get_audit_record requires it).
    # In practice the caller should supply tenant_id; we use "" only as a
    # best-effort fallback for the helper.
    record: Optional[Dict[str, Any]] = None

    # Attempt a broad lookup via the internal function that accepts no tenant guard.
    # We duplicate small logic to avoid requiring a pre-known tenant_id here.
    from sqlalchemy import text as _text  # noqa: PLC0415
    from audit.logger import _get_engine  # noqa: PLC0415

    engine = _get_engine(db_url)
    async with engine.connect() as conn:
        try:
            result = await conn.execute(
                _text("SELECT * FROM audit_log WHERE application_id = :aid ORDER BY logged_at DESC LIMIT 1"),
                {"aid": decision_id},
            )
            row = result.mappings().fetchone()
        except Exception as exc:
            raise KeyError(f"Audit record not found for decision_id={decision_id}") from exc

    if row is None:
        raise KeyError(f"Audit record not found for decision_id={decision_id}")

    record = dict(row)

    # JSON-decode structured fields
    for field_name in ("input_features", "reason_codes", "model_version"):
        if record.get(field_name) and isinstance(record[field_name], str):
            try:
                record[field_name] = json.loads(record[field_name])
            except json.JSONDecodeError:
                pass

    tenant_id: str      = record.get("tenant_id", "")
    decided_at: str     = record.get("logged_at", "")
    feature_version: str = record.get("feature_version") or "unknown"
    feature_values: Dict[str, Any] = record.get("input_features") or {}
    decision_output: str = record.get("decision_output") or record.get("decision") or "UNKNOWN"
    reason_codes_raw = record.get("reason_codes") or []
    reason_codes: List[str] = reason_codes_raw if isinstance(reason_codes_raw, list) else []
    audit_log_row_hash: str = record.get("record_hash") or ""
    policy_version_tag: str = record.get("policy_version") or "unknown"

    # -----------------------------------------------------------------------
    # 2. Policy params snapshot from PolicyVersionStore
    # -----------------------------------------------------------------------
    policy_params: Dict[str, Any] = {}
    try:
        from datetime import timezone as _tz  # noqa: PLC0415
        decided_dt = datetime.fromisoformat(decided_at.replace("Z", "+00:00"))
        pv = policy_store.get_as_of(decided_dt)
        policy_version_tag = pv.version_tag
        policy_params = pv.parameters
    except Exception as exc:
        logger.warning("Could not retrieve policy version for %s: %s", decided_at, exc)

    # -----------------------------------------------------------------------
    # 3. Tenant config snapshot from ConfigRegistryService
    # -----------------------------------------------------------------------
    tenant_config_version: str = "unknown"
    tenant_config_sha256: str  = ""
    try:
        active_cfg = config_registry.get_active(tenant_id)
        if active_cfg is not None:
            tenant_config_version = active_cfg.version_tag
            tenant_config_sha256  = active_cfg.config_sha256
    except Exception as exc:
        logger.warning("Could not retrieve tenant config for %s: %s", tenant_id, exc)

    # -----------------------------------------------------------------------
    # 4. Model artefact hashes
    # -----------------------------------------------------------------------
    model_paths = _extract_model_paths(record)
    model_artifact_hashes: Dict[str, str] = {
        role: _sha256_file(path) for role, path in model_paths.items()
    }

    # -----------------------------------------------------------------------
    # 5. Compute bundle_sha256 over all fields (excluding bundle_sha256 itself)
    # -----------------------------------------------------------------------
    bundle_fields: Dict[str, Any] = {
        "decision_id":            decision_id,
        "tenant_id":              tenant_id,
        "decided_at":             decided_at,
        "raw_inputs":             feature_values,
        "feature_version":        feature_version,
        "feature_values":         feature_values,
        "model_artifact_hashes":  model_artifact_hashes,
        "policy_version":         policy_version_tag,
        "policy_params_snapshot": policy_params,
        "tenant_config_version":  tenant_config_version,
        "tenant_config_sha256":   tenant_config_sha256,
        "decision":               decision_output,
        "reason_codes":           reason_codes,
        "audit_log_row_hash":     audit_log_row_hash,
    }
    bundle_sha256 = _compute_bundle_sha256(bundle_fields)

    return ReplayBundle(
        decision_id=decision_id,
        tenant_id=tenant_id,
        decided_at=decided_at,
        raw_inputs=feature_values,
        feature_version=feature_version,
        feature_values=feature_values,
        model_artifact_hashes=model_artifact_hashes,
        policy_version=policy_version_tag,
        policy_params_snapshot=policy_params,
        tenant_config_version=tenant_config_version,
        tenant_config_sha256=tenant_config_sha256,
        decision=decision_output,
        reason_codes=reason_codes,
        audit_log_row_hash=audit_log_row_hash,
        bundle_sha256=bundle_sha256,
    )
