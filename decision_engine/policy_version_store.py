"""
Policy Version Store
======================
Provides point-in-time versioning and replay for credit card origination
policy parameters.

Regulatory basis
----------------
SR 11-7 requires that model governance records include the exact policy
thresholds in effect at the time each credit decision was made.  This module
implements an append-only, immutable policy ledger so that:

  1. Every policy change is recorded with a timestamp and author.
  2. Any historical decision can be replayed using the policy version that
     was active at the time of the decision.
  3. A rollback operation publishes a new version pointing to a prior
     parameter set (never mutates history).
  4. An audit trail can be exported as JSON for examination submissions.

Storage
-------
Policy versions are persisted to a SQLite database (default: ``policy_versions.db``
in the project root) or any SQLAlchemy-compatible URL.  This keeps the store
completely self-contained without a running PostgreSQL instance.

Usage
-----
    from decision_engine.policy_version_store import PolicyVersionStore

    store = PolicyVersionStore()

    # Publish a new version from the live policy module
    from decision_engine.cc_origination_policy import extract_current_policy_parameters
    params = extract_current_policy_parameters()
    version_id = store.publish(params, author="alice@example.com", note="Q1 2025 refresh")

    # Look up the active version
    active = store.get_active()

    # Replay a historical decision
    policy_at_decision = store.get_as_of(some_datetime)

    # Rollback to a prior version (creates a new version row)
    store.rollback(target_version_id=3, author="bob@example.com", note="Emergency rollback")
"""
from __future__ import annotations

import base64
import dataclasses
import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default SQLite DB path relative to the project root
_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "policy_versions.db"

# DDL for the policy_versions table
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS policy_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    version_tag     TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    author          TEXT NOT NULL,
    note            TEXT,
    effective_from  TEXT NOT NULL,   -- ISO-8601 UTC
    superseded_at   TEXT,            -- ISO-8601 UTC; NULL = currently active
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pv_effective ON policy_versions(effective_from);
CREATE INDEX IF NOT EXISTS idx_pv_active    ON policy_versions(is_active);
"""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PolicyVersion:
    """Snapshot of the origination policy at a point in time.

    Attributes
    ----------
    id : int
        Auto-incremented primary key.
    version_tag : str
        Human-readable tag, e.g. ``"v1.0"`` or ``"rollback-to-v2"``.
    parameters : Dict[str, Any]
        Full policy parameter dictionary produced by
        ``extract_current_policy_parameters()``.
    author : str
        Identity of who published this version.
    note : str
        Free-text change description for audit trail.
    effective_from : datetime
        UTC time from which this version is considered active.
    superseded_at : Optional[datetime]
        UTC time when this version was replaced.  ``None`` = active.
    is_active : bool
        ``True`` for the single currently active version.
    created_at : datetime
        Insertion timestamp.
    """
    id: int
    version_tag: str
    parameters: Dict[str, Any]
    author: str
    note: str
    effective_from: datetime
    superseded_at: Optional[datetime]
    is_active: bool
    created_at: datetime


class PolicyVersionNotFoundError(Exception):
    """Raised when no policy version satisfies the requested query."""


# ---------------------------------------------------------------------------
# RSA-2048 PSS signing helpers (PV-007)
# ---------------------------------------------------------------------------


def sign_version(version_payload: dict, private_key_pem: bytes) -> str:
    """Sign the canonical JSON representation of *version_payload* using RSA-2048 PSS.

    Parameters
    ----------
    version_payload:
        Arbitrary dict describing the policy version (fields are sorted for determinism).
    private_key_pem:
        PEM-encoded RSA private key bytes.

    Returns
    -------
    str
        Base64-encoded RSA-PSS signature string.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    canonical = json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    signature = private_key.sign(
        canonical,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def verify_version_signature(
    version_payload: dict,
    signature_b64: str,
    public_key_pem: bytes,
) -> bool:
    """Verify the RSA-PSS signature of *version_payload*.

    Parameters
    ----------
    version_payload:
        The same dict that was passed to ``sign_version()``.
    signature_b64:
        Base64-encoded signature string returned by ``sign_version()``.
    public_key_pem:
        PEM-encoded RSA public key bytes corresponding to the signing key.

    Returns
    -------
    bool
        ``True`` if the signature is valid; ``False`` otherwise (including
        any ``InvalidSignature`` or decoding errors).
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        canonical = json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
        sig_bytes = base64.b64decode(signature_b64)
        public_key = serialization.load_pem_public_key(public_key_pem)
        public_key.verify(
            sig_bytes,
            canonical,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, Exception):
        return False


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class PolicyVersionStore:
    """Append-only ledger for origination policy versions.

    Thread-safe via a per-instance ``threading.Lock``.

    Parameters
    ----------
    db_path :
        Path to the SQLite database file.  Created automatically on first use.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._lock = threading.Lock()
        self._init_db()

    # ── Private helpers ────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS policy_versions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    version_tag     TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    author          TEXT NOT NULL,
                    note            TEXT,
                    effective_from  TEXT NOT NULL,
                    superseded_at   TEXT,
                    is_active       INTEGER NOT NULL DEFAULT 1,
                    created_at      TEXT NOT NULL,
                    rsa_signature   TEXT,
                    signing_key_id  TEXT
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pv_effective ON policy_versions(effective_from)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pv_active ON policy_versions(is_active)"
            )
            # Migration guard: add RSA signing columns to existing databases
            for col, ddl in [
                ("rsa_signature",  "ALTER TABLE policy_versions ADD COLUMN rsa_signature TEXT"),
                ("signing_key_id", "ALTER TABLE policy_versions ADD COLUMN signing_key_id TEXT"),
            ]:
                try:
                    conn.execute(ddl)
                    logger.info("policy_versions: added column '%s'", col)
                except sqlite3.OperationalError:
                    pass  # Column already exists
            conn.commit()

    @staticmethod
    def _row_to_version(row: sqlite3.Row) -> PolicyVersion:
        return PolicyVersion(
            id=row["id"],
            version_tag=row["version_tag"],
            parameters=json.loads(row["parameters_json"]),
            author=row["author"],
            note=row["note"] or "",
            effective_from=datetime.fromisoformat(row["effective_from"]),
            superseded_at=(
                datetime.fromisoformat(row["superseded_at"])
                if row["superseded_at"]
                else None
            ),
            is_active=bool(row["is_active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    # ── Public API ─────────────────────────────────────────────────────────

    def publish(
        self,
        parameters: Dict[str, Any],
        author: str,
        note: str = "",
        version_tag: Optional[str] = None,
        effective_from: Optional[datetime] = None,
    ) -> int:
        """Publish a new policy version and deactivate the current one.

        Parameters
        ----------
        parameters :
            Full policy parameter dictionary.
        author :
            Identity string (email, user ID, or system name).
        note :
            Human-readable change description for audit trail.
        version_tag :
            Optional explicit tag; auto-numbered as ``"v{n}"`` if omitted.
        effective_from :
            UTC datetime from which this version is active.  Defaults to now.

        Returns
        -------
        int
            The ``id`` of the newly published row.
        """
        now = self._now()
        eff = (effective_from or datetime.now(timezone.utc)).isoformat()

        with self._lock, self._connect() as conn:
            # Auto-number tag
            if version_tag is None:
                row = conn.execute(
                    "SELECT MAX(id) AS max_id FROM policy_versions"
                ).fetchone()
                next_n = (row["max_id"] or 0) + 1
                version_tag = f"v{next_n}"

            # Supersede the current active version
            conn.execute(
                "UPDATE policy_versions SET is_active=0, superseded_at=? WHERE is_active=1",
                (now,),
            )

            cur = conn.execute(
                """
                INSERT INTO policy_versions
                    (version_tag, parameters_json, author, note,
                     effective_from, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    version_tag,
                    json.dumps(parameters, default=str, sort_keys=True),
                    author,
                    note,
                    eff,
                    now,
                ),
            )
            conn.commit()
            new_id = cur.lastrowid

        # Optional RSA-PSS signing (PV-007)
        _pem_env = os.environ.get("POLICY_SIGNING_KEY_PEM", "")
        rsa_signature: Optional[str] = None
        signing_key_id: Optional[str] = None
        if _pem_env:
            try:
                version_payload = {
                    "version_tag": version_tag,
                    "parameters_json": json.dumps(parameters, default=str, sort_keys=True),
                    "author": author,
                    "note": note,
                    "effective_from": eff,
                    "created_at": now,
                }
                rsa_signature = sign_version(version_payload, _pem_env.encode())
                signing_key_id = os.environ.get("POLICY_SIGNING_KEY_ID", "default")
            except Exception as _sign_exc:
                logger.warning("RSA signing failed (stored NULL): %s", _sign_exc)

        if rsa_signature is not None:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "UPDATE policy_versions SET rsa_signature=?, signing_key_id=? WHERE id=?",
                    (rsa_signature, signing_key_id, new_id),
                )
                conn.commit()

        logger.info(
            "Policy version %s (id=%d) published by %s — '%s'",
            version_tag, new_id, author, note,
        )
        return new_id

    def get_active(self) -> PolicyVersion:
        """Return the currently active policy version.

        Raises
        ------
        PolicyVersionNotFoundError
            If no version has been published yet.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM policy_versions WHERE is_active=1 ORDER BY id DESC LIMIT 1"
            ).fetchone()

        if row is None:
            raise PolicyVersionNotFoundError("No active policy version found.")
        return self._row_to_version(row)

    def get_as_of(self, as_of: datetime) -> PolicyVersion:
        """Return the policy version that was active at *as_of*.

        Parameters
        ----------
        as_of :
            UTC datetime of the historical decision to replay.

        Returns
        -------
        PolicyVersion

        Raises
        ------
        PolicyVersionNotFoundError
            If no version was active at the requested time.
        """
        iso = as_of.isoformat()
        with self._lock, self._connect() as conn:
            # The active-at-time version is:
            # effective_from <= as_of  AND  (superseded_at IS NULL OR superseded_at > as_of)
            row = conn.execute(
                """
                SELECT * FROM policy_versions
                WHERE effective_from <= ?
                  AND (superseded_at IS NULL OR superseded_at > ?)
                ORDER BY effective_from DESC
                LIMIT 1
                """,
                (iso, iso),
            ).fetchone()

        if row is None:
            raise PolicyVersionNotFoundError(
                f"No policy version active at {as_of.isoformat()}"
            )
        return self._row_to_version(row)

    def get_by_id(self, version_id: int) -> PolicyVersion:
        """Fetch a specific policy version by its primary key."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM policy_versions WHERE id=?", (version_id,)
            ).fetchone()
        if row is None:
            raise PolicyVersionNotFoundError(f"Policy version id={version_id} not found.")
        return self._row_to_version(row)

    def list_versions(self, limit: int = 100) -> List[PolicyVersion]:
        """Return all policy versions ordered by effective_from descending."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM policy_versions ORDER BY effective_from DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_version(r) for r in rows]

    def rollback(
        self,
        target_version_id: int,
        author: str,
        note: str = "",
    ) -> int:
        """Rollback to a prior version by publishing its parameters as a new version.

        This never mutates history — it inserts a new row with the parameters of
        ``target_version_id``.

        Parameters
        ----------
        target_version_id :
            ``id`` of the version to restore.
        author :
            Who triggered the rollback.
        note :
            Rollback rationale for the audit trail.

        Returns
        -------
        int
            The ``id`` of the newly published rollback version.
        """
        target = self.get_by_id(target_version_id)
        rollback_tag = f"rollback-to-{target.version_tag}"
        rollback_note = note or f"Rollback to policy {target.version_tag} (id={target_version_id})"

        return self.publish(
            parameters=target.parameters,
            author=author,
            note=rollback_note,
            version_tag=rollback_tag,
        )

    def export_audit_trail(self, limit: int = 1000) -> str:
        """Serialise the full policy version history to a JSON string."""
        versions = self.list_versions(limit=limit)
        return json.dumps(
            [dataclasses.asdict(v) for v in versions],
            default=str,
            indent=2,
        )


# ---------------------------------------------------------------------------
# Extractor — reads live parameters from cc_origination_policy
# ---------------------------------------------------------------------------


def extract_current_policy_parameters() -> Dict[str, Any]:
    """Extract the current policy parameter dictionary from the live policy module.

    Returns a nested dict:
      ``{"product_policies": {product_name: {field: value, ...}, ...}}``
    """
    from decision_engine.cc_origination_policy import PRODUCT_POLICIES
    import dataclasses as _dc

    params: Dict[str, Any] = {"product_policies": {}}
    for name, policy in PRODUCT_POLICIES.items():
        params["product_policies"][name] = _dc.asdict(policy)
    return params
