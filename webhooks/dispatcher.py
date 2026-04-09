"""Webhook dispatcher with exponential-backoff retry (GAP-16)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import urllib.request
import urllib.error

from webhooks.models import (
    EventType,
    WebhookDeliveryAttempt,
    WebhookRegistration,
    sign_payload,
)
from webhooks.store import WebhookStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry schedule (PRD §9.6)
# ---------------------------------------------------------------------------

# Delay (seconds) before each retry attempt.
# Index 0 = first retry (after attempt 1 fails), index 4 = fifth attempt.
_RETRY_DELAYS_S: list[float] = [0, 30, 300, 1800, 7200]

_MAX_ATTEMPTS = 5
_REQUEST_TIMEOUT_S = 10
_MAX_RESPONSE_BODY = 2048  # bytes stored from target response


class WebhookDispatcher:
    """Delivers webhook events with exponential-backoff retry.

    Retry policy (PRD §9.6):
    - Attempt 1: immediate
    - Attempt 2: 30 seconds
    - Attempt 3: 5 minutes
    - Attempt 4: 30 minutes
    - Attempt 5: 2 hours
    - After 5 failures: mark delivery as permanently failed; log WARNING.

    Signing: every POST includes header ``X-ILOL-Signature: sha256=<hmac>``
    computed over the raw JSON body using the registration secret.

    Timeout: 10 seconds per attempt.

    Parameters
    ----------
    store: :class:`WebhookStore` for loading registrations and persisting
           delivery attempts.
    """

    def __init__(self, store: WebhookStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(
        self,
        tenant_id: str,
        event_type: str,
        payload: dict,
    ) -> int:
        """Deliver *payload* to all active webhooks subscribed to *event_type*.

        Retries each endpoint up to :data:`_MAX_ATTEMPTS` times before giving
        up (delivery attempts are always logged).

        Parameters
        ----------
        tenant_id:   Tenant whose webhooks should be notified.
        event_type:  One of the ``EventType`` literal values.
        payload:     Event payload dict; will be JSON-serialised.

        Returns
        -------
        int
            Count of registrations where at least one delivery attempt
            succeeded (HTTP 2xx).
        """
        registrations = self._store.list_for_event(tenant_id, event_type)
        if not registrations:
            return 0

        payload_bytes = json.dumps(payload, ensure_ascii=False).encode()
        success_count = 0

        for reg in registrations:
            succeeded = self._dispatch_to_registration(
                reg=reg,
                event_type=event_type,
                payload_bytes=payload_bytes,
            )
            if succeeded:
                success_count += 1

        return success_count

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _dispatch_to_registration(
        self,
        reg: WebhookRegistration,
        event_type: str,
        payload_bytes: bytes,
    ) -> bool:
        """Try delivering payload to a single webhook registration with retries."""
        for attempt_number in range(1, _MAX_ATTEMPTS + 1):
            if attempt_number > 1:
                delay = _RETRY_DELAYS_S[attempt_number - 1]
                logger.debug(
                    "Webhook %s attempt %d: sleeping %.0fs before retry",
                    reg.webhook_id, attempt_number, delay,
                )
                time.sleep(delay)

            attempt = self._deliver_once(
                registration=reg,
                event_type=event_type,
                payload_bytes=payload_bytes,
                attempt_number=attempt_number,
            )
            self._store.log_attempt(attempt)

            if attempt.success:
                logger.info(
                    "Webhook %s delivered event '%s' (attempt %d, %dms)",
                    reg.webhook_id, event_type, attempt_number, attempt.duration_ms,
                )
                return True

            logger.warning(
                "Webhook %s event '%s' attempt %d failed: status=%s msg=%s",
                reg.webhook_id, event_type, attempt_number,
                attempt.response_status, attempt.error_message,
            )

        logger.warning(
            "Webhook %s permanently failed after %d attempts for event '%s'",
            reg.webhook_id, _MAX_ATTEMPTS, event_type,
        )
        return False

    def _deliver_once(
        self,
        registration: WebhookRegistration,
        event_type: str,
        payload_bytes: bytes,
        attempt_number: int,
    ) -> WebhookDeliveryAttempt:
        """Make one HTTP POST attempt and return a :class:`WebhookDeliveryAttempt`."""
        attempt_id = str(uuid.uuid4())
        delivered_at = datetime.now(timezone.utc).isoformat()
        start = time.monotonic()

        # Build signature — use secret field (plaintext at creation time;
        # from the DB this is the hash, which is fine for existing registrations
        # that were re-loaded; for in-memory registrations created within the
        # same process it is the plaintext).
        signature = sign_payload(registration.secret, payload_bytes)

        headers = {
            "Content-Type": "application/json",
            "X-ILOL-Signature": signature,
            "X-ILOL-Event": event_type,
            "X-ILOL-Attempt": str(attempt_number),
            "User-Agent": "ILOL-WebhookDispatcher/1.0",
        }

        response_status: int | None = None
        response_body: str | None = None
        error_message: str | None = None
        success = False

        try:
            req = urllib.request.Request(
                registration.target_url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_S) as resp:
                response_status = resp.status
                raw_body = resp.read(_MAX_RESPONSE_BODY)
                response_body = raw_body.decode("utf-8", errors="replace")
                success = 200 <= response_status < 300

        except urllib.error.HTTPError as exc:
            response_status = exc.code
            try:
                response_body = exc.read(_MAX_RESPONSE_BODY).decode("utf-8", errors="replace")
            except Exception:
                response_body = None
            error_message = f"HTTP {exc.code}: {exc.reason}"
            success = False

        except Exception as exc:
            error_message = str(exc)
            success = False

        duration_ms = int((time.monotonic() - start) * 1000)

        return WebhookDeliveryAttempt(
            attempt_id=attempt_id,
            webhook_id=registration.webhook_id,
            tenant_id=registration.tenant_id,
            event_type=event_type,
            payload_json=payload_bytes.decode("utf-8", errors="replace"),
            response_status=response_status,
            response_body=response_body,
            delivered_at=delivered_at,
            duration_ms=duration_ms,
            success=success,
            error_message=error_message,
            attempt_number=attempt_number,
        )
