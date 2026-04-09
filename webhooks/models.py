"""Data models for the webhook delivery framework (GAP-16)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EventType = Literal[
    "decision.approved",
    "decision.rejected",
    "decision.manual_review",
    "batch.complete",
    "batch.failed",
    "adverse_action.generated",
    "model.drift_alert",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WebhookRegistration:
    """Represents a tenant's webhook endpoint registration.

    Attributes
    ----------
    webhook_id:  UUID for this registration.
    tenant_id:   Owning tenant.
    target_url:  HTTPS URL to POST events to.
    secret:      HMAC signing secret.  At creation time this is the plaintext
                 value (returned to the caller once and never stored).  When
                 hydrated from the DB, this should be treated as the *hash*
                 (or left blank) — callers should not rely on it.
    events:      List of EventType values this endpoint subscribes to.
                 ``["*"]`` subscribes to all events.
    is_active:   Whether the registration is active.
    created_at:  ISO-8601 UTC timestamp.
    description: Optional human-readable label.
    """

    webhook_id: str
    tenant_id: str
    target_url: str
    secret: str
    events: list[str]
    is_active: bool
    created_at: str
    description: str = ""


@dataclass
class WebhookDeliveryAttempt:
    """A single delivery attempt for a webhook event.

    Attributes
    ----------
    attempt_id:      UUID for this delivery attempt.
    webhook_id:      Webhook registration this attempt belongs to.
    tenant_id:       Tenant that owns the webhook.
    event_type:      EventType string.
    payload_json:    JSON-serialised payload sent to the target.
    response_status: HTTP status code from the target; ``None`` if the
                     connection failed before a response was received.
    response_body:   First 2 KB of response body; ``None`` on connection failure.
    delivered_at:    ISO-8601 UTC timestamp of the attempt.
    duration_ms:     Round-trip time in milliseconds.
    success:         ``True`` if the target returned HTTP 2xx.
    error_message:   Human-readable error if success is ``False``.
    attempt_number:  1-based retry counter (1 = first attempt).
    """

    attempt_id: str
    webhook_id: str
    tenant_id: str
    event_type: str
    payload_json: str
    response_status: Optional[int]
    response_body: Optional[str]
    delivered_at: str
    duration_ms: int
    success: bool
    error_message: Optional[str] = None
    attempt_number: int = 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sign_payload(secret: str, payload_bytes: bytes) -> str:
    """Return ``'sha256=<hex>'`` HMAC-SHA256 digest of *payload_bytes*.

    Usage::

        sig = sign_payload(registration.secret, body)
        headers["X-ILOL-Signature"] = sig

    Parameters
    ----------
    secret:        Plain-text signing secret.
    payload_bytes: Raw request body bytes to sign.
    """
    digest = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
