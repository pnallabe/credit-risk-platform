"""SQLite-backed store for webhook registrations and delivery logs (GAP-16)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from webhooks.models import WebhookDeliveryAttempt, WebhookRegistration

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_registrations (
    webhook_id    TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL,
    target_url    TEXT NOT NULL,
    secret_hash   TEXT NOT NULL,    -- SHA-256 of the secret; original not stored
    events_json   TEXT NOT NULL,    -- JSON array of subscribed event types
    is_active     INTEGER NOT NULL DEFAULT 1,
    description   TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_wh_tenant ON webhook_registrations (tenant_id);

CREATE TABLE IF NOT EXISTS webhook_delivery_log (
    attempt_id      TEXT PRIMARY KEY,
    webhook_id      TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    response_status INTEGER,
    response_body   TEXT,
    delivered_at    TEXT NOT NULL,
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    success         INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    attempt_number  INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS ix_wdl_webhook ON webhook_delivery_log (webhook_id);
CREATE INDEX IF NOT EXISTS ix_wdl_event   ON webhook_delivery_log (event_type);
"""


def _hash_secret(secret: str) -> str:
    """One-way SHA-256 hash of the signing secret."""
    return hashlib.sha256(secret.encode()).hexdigest()


class WebhookStore:
    """SQLite-backed store for webhook registrations and delivery logs.

    Parameters
    ----------
    db_path: Path to the SQLite file.  Use ``":memory:"`` for tests.
    """

    def __init__(self, db_path: str = "./webhooks.db") -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_SCHEMA)
            conn.commit()
            conn.close()

    # ------------------------------------------------------------------
    # Registration methods
    # ------------------------------------------------------------------

    def register(
        self,
        tenant_id: str,
        target_url: str,
        secret: str,
        events: List[str],
        description: str = "",
    ) -> WebhookRegistration:
        """Create a new webhook registration.

        The plaintext *secret* is returned in the :class:`WebhookRegistration`
        so the caller can deliver it to the tenant exactly once.  Only its
        SHA-256 hash is persisted.
        """
        webhook_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        secret_hash = _hash_secret(secret)
        events_json = json.dumps(events)

        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO webhook_registrations
                    (webhook_id, tenant_id, target_url, secret_hash,
                     events_json, is_active, description, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (webhook_id, tenant_id, target_url, secret_hash,
                 events_json, description, created_at),
            )
            conn.commit()
            conn.close()

        return WebhookRegistration(
            webhook_id=webhook_id,
            tenant_id=tenant_id,
            target_url=target_url,
            secret=secret,   # plaintext returned once to caller
            events=events,
            is_active=True,
            created_at=created_at,
            description=description,
        )

    def get(self, webhook_id: str) -> Optional[WebhookRegistration]:
        """Return a registration by ID, or ``None`` if not found."""
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT * FROM webhook_registrations WHERE webhook_id = ?",
                (webhook_id,),
            ).fetchone()
            conn.close()
        if row is None:
            return None
        return self._row_to_registration(row)

    def list_for_tenant(self, tenant_id: str) -> List[WebhookRegistration]:
        """Return all active registrations for *tenant_id*."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM webhook_registrations WHERE tenant_id = ? AND is_active = 1",
                (tenant_id,),
            ).fetchall()
            conn.close()
        return [self._row_to_registration(r) for r in rows]

    def list_for_event(
        self, tenant_id: str, event_type: str
    ) -> List[WebhookRegistration]:
        """Return active registrations subscribed to *event_type* (or ``'*'``)."""
        all_active = self.list_for_tenant(tenant_id)
        return [
            r for r in all_active
            if "*" in r.events or event_type in r.events
        ]

    def deactivate(self, webhook_id: str, tenant_id: str) -> bool:
        """Soft-delete a registration.  Returns ``True`` if a row was updated."""
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "UPDATE webhook_registrations SET is_active = 0 "
                "WHERE webhook_id = ? AND tenant_id = ?",
                (webhook_id, tenant_id),
            )
            conn.commit()
            conn.close()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Delivery log methods
    # ------------------------------------------------------------------

    def log_attempt(self, attempt: WebhookDeliveryAttempt) -> None:
        """Persist a delivery attempt record."""
        with self._lock:
            conn = self._connect()
            conn.execute(
                """
                INSERT INTO webhook_delivery_log
                    (attempt_id, webhook_id, tenant_id, event_type,
                     payload_json, response_status, response_body,
                     delivered_at, duration_ms, success,
                     error_message, attempt_number)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.attempt_id,
                    attempt.webhook_id,
                    attempt.tenant_id,
                    attempt.event_type,
                    attempt.payload_json,
                    attempt.response_status,
                    attempt.response_body,
                    attempt.delivered_at,
                    attempt.duration_ms,
                    1 if attempt.success else 0,
                    attempt.error_message,
                    attempt.attempt_number,
                ),
            )
            conn.commit()
            conn.close()

    def get_delivery_log(
        self, webhook_id: str, limit: int = 50
    ) -> List[WebhookDeliveryAttempt]:
        """Return the most-recent delivery attempts for *webhook_id*."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM webhook_delivery_log WHERE webhook_id = ? "
                "ORDER BY delivered_at DESC LIMIT ?",
                (webhook_id, limit),
            ).fetchall()
            conn.close()
        return [self._row_to_attempt(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_registration(row: sqlite3.Row) -> WebhookRegistration:
        return WebhookRegistration(
            webhook_id=row["webhook_id"],
            tenant_id=row["tenant_id"],
            target_url=row["target_url"],
            secret=row["secret_hash"],   # hash only; plaintext never stored
            events=json.loads(row["events_json"]),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            description=row["description"] or "",
        )

    @staticmethod
    def _row_to_attempt(row: sqlite3.Row) -> WebhookDeliveryAttempt:
        return WebhookDeliveryAttempt(
            attempt_id=row["attempt_id"],
            webhook_id=row["webhook_id"],
            tenant_id=row["tenant_id"],
            event_type=row["event_type"],
            payload_json=row["payload_json"],
            response_status=row["response_status"],
            response_body=row["response_body"],
            delivered_at=row["delivered_at"],
            duration_ms=row["duration_ms"],
            success=bool(row["success"]),
            error_message=row["error_message"],
            attempt_number=row["attempt_number"],
        )
