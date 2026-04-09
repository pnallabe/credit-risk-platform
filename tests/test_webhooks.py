"""Tests for GAP-16: webhooks package (models, store, dispatcher)."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from webhooks.dispatcher import WebhookDispatcher, _MAX_ATTEMPTS
from webhooks.models import WebhookDeliveryAttempt, WebhookRegistration, sign_payload
from webhooks.store import WebhookStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store() -> WebhookStore:
    return WebhookStore(db_path=":memory:")


@pytest.fixture()
def dispatcher(store: WebhookStore) -> WebhookDispatcher:
    return WebhookDispatcher(store=store)


def _make_reg(store: WebhookStore, tenant_id: str = "t1", events: list | None = None) -> WebhookRegistration:
    return store.register(
        tenant_id=tenant_id,
        target_url="https://example.com/hook",
        secret="s3cr3t",  # pragma: allowlist secret
        events=events or ["decision.approved"],
        description="test hook",
    )


# ---------------------------------------------------------------------------
# WebhookStore — registration tests
# ---------------------------------------------------------------------------


class TestWebhookStore:
    def test_register_returns_registration(self, store: WebhookStore) -> None:
        reg = _make_reg(store)
        assert isinstance(reg, WebhookRegistration)
        assert reg.webhook_id != ""
        assert reg.tenant_id == "t1"
        assert reg.is_active is True

    def test_secret_not_stored_plaintext(self, store: WebhookStore) -> None:
        reg = _make_reg(store, tenant_id="t2")
        # Reload from DB — secret field should be the SHA-256 hash, not "s3cr3t"
        loaded = store.get(reg.webhook_id)
        assert loaded is not None
        assert loaded.secret != "s3cr3t"  # pragma: allowlist secret
        assert len(loaded.secret) == 64  # SHA-256 hex = 64 chars

    def test_list_for_tenant_returns_registration(self, store: WebhookStore) -> None:
        reg = _make_reg(store)
        results = store.list_for_tenant("t1")
        ids = [r.webhook_id for r in results]
        assert reg.webhook_id in ids

    def test_deactivate_removes_from_list(self, store: WebhookStore) -> None:
        reg = _make_reg(store)
        removed = store.deactivate(reg.webhook_id, tenant_id="t1")
        assert removed is True
        listed = store.list_for_tenant("t1")
        assert all(r.webhook_id != reg.webhook_id for r in listed)

    def test_deactivate_wrong_tenant_returns_false(self, store: WebhookStore) -> None:
        reg = _make_reg(store, tenant_id="t1")
        result = store.deactivate(reg.webhook_id, tenant_id="t_other")
        assert result is False

    def test_list_for_event_subscribed(self, store: WebhookStore) -> None:
        reg = store.register("t3", "https://x.com/h", "s", ["decision.approved"], "")
        results = store.list_for_event("t3", "decision.approved")
        assert any(r.webhook_id == reg.webhook_id for r in results)

    def test_list_for_event_wildcard(self, store: WebhookStore) -> None:
        reg = store.register("t4", "https://x.com/h2", "s", ["*"], "")
        results = store.list_for_event("t4", "batch.complete")
        assert any(r.webhook_id == reg.webhook_id for r in results)

    def test_list_for_event_not_subscribed(self, store: WebhookStore) -> None:
        store.register("t5", "https://x.com/h3", "s", ["decision.approved"], "")
        results = store.list_for_event("t5", "batch.complete")
        assert results == []

    def test_deactivated_not_in_list_for_event(self, store: WebhookStore) -> None:
        reg = _make_reg(store, tenant_id="t6")
        store.deactivate(reg.webhook_id, "t6")
        results = store.list_for_event("t6", "decision.approved")
        assert all(r.webhook_id != reg.webhook_id for r in results)

    def test_delivery_log_persisted(self, store: WebhookStore) -> None:
        reg = _make_reg(store)
        attempt = WebhookDeliveryAttempt(
            attempt_id=str(uuid.uuid4()),
            webhook_id=reg.webhook_id,
            tenant_id="t1",
            event_type="decision.approved",
            payload_json='{"x":1}',
            response_status=200,
            response_body="ok",
            delivered_at="2026-01-01T00:00:00+00:00",
            duration_ms=42,
            success=True,
            attempt_number=1,
        )
        store.log_attempt(attempt)
        log = store.get_delivery_log(reg.webhook_id)
        assert len(log) == 1
        assert log[0].success is True

    def test_tenant_isolation(self, store: WebhookStore) -> None:
        store.register("tenant_a", "https://a.com", "sa", ["*"], "")
        store.register("tenant_b", "https://b.com", "sb", ["*"], "")
        a_list = store.list_for_tenant("tenant_a")
        assert all(r.tenant_id == "tenant_a" for r in a_list)


# ---------------------------------------------------------------------------
# sign_payload tests
# ---------------------------------------------------------------------------


class TestSignPayload:
    def test_signature_format(self) -> None:
        sig = sign_payload("mysecret", b'{"event":"test"}')  # pragma: allowlist secret
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64

    def test_signature_verifiable(self) -> None:
        secret = "super-secret-key"  # pragma: allowlist secret
        body = b'{"foo":"bar"}'
        sig = sign_payload(secret, body)
        hex_part = sig[len("sha256="):]
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(hex_part, expected)

    def test_different_secrets_different_sigs(self) -> None:
        body = b'{"x":1}'
        sig_a = sign_payload("secret-a", body)  # pragma: allowlist secret
        sig_b = sign_payload("secret-b", body)  # pragma: allowlist secret
        assert sig_a != sig_b

    def test_different_payloads_different_sigs(self) -> None:
        secret = "same-secret"  # pragma: allowlist secret
        assert sign_payload(secret, b"abc") != sign_payload(secret, b"xyz")


# ---------------------------------------------------------------------------
# WebhookDispatcher tests
# ---------------------------------------------------------------------------


def _http_200_mock():
    """Return a context-manager mock that simulates HTTP 200."""
    resp = MagicMock()
    resp.status = 200
    resp.read.return_value = b"ok"
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=resp)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _http_500_mock():
    import urllib.error
    exc = urllib.error.HTTPError(
        url="https://example.com", code=500, msg="Internal Server Error",
        hdrs=None, fp=None  # type: ignore[arg-type]
    )
    exc.read = MagicMock(return_value=b"err")
    return exc


class TestWebhookDispatcher:
    def test_dispatch_returns_1_on_success(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        store.register("t1", "https://example.com/hook", "s3cr3t", ["decision.approved"], "")
        with patch("urllib.request.urlopen", return_value=_http_200_mock()):
            count = dispatcher.dispatch("t1", "decision.approved", {"x": 1})
        assert count == 1

    def test_dispatch_logs_success_attempt(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        reg = store.register("t2", "https://example.com/hook", "s3cr3t", ["decision.approved"], "")
        with patch("urllib.request.urlopen", return_value=_http_200_mock()):
            dispatcher.dispatch("t2", "decision.approved", {"msg": "ok"})
        log = store.get_delivery_log(reg.webhook_id)
        assert len(log) >= 1
        assert log[0].success is True

    def test_dispatch_no_webhooks_returns_0(
        self, dispatcher: WebhookDispatcher
    ) -> None:
        count = dispatcher.dispatch("no_such_tenant", "decision.approved", {})
        assert count == 0

    def test_retry_on_500_then_200(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        reg = store.register("t3", "https://example.com/hook", "s3cr3t", ["decision.rejected"], "")
        call_count = {"n": 0}

        def _side_effect(req, timeout=10):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise _http_500_mock()
            return _http_200_mock()

        with patch("urllib.request.urlopen", side_effect=_side_effect):
            with patch("time.sleep"):  # skip actual delays
                count = dispatcher.dispatch("t3", "decision.rejected", {"x": 2})

        assert count == 1
        log = store.get_delivery_log(reg.webhook_id)
        success_entry = next((a for a in log if a.success), None)
        assert success_entry is not None
        assert success_entry.attempt_number == 2

    def test_permanent_failure_after_max_attempts(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        reg = store.register("t4", "https://example.com/hook", "s3cr3t", ["batch.failed"], "")

        with patch("urllib.request.urlopen", side_effect=_http_500_mock()):
            with patch("time.sleep"):
                count = dispatcher.dispatch("t4", "batch.failed", {"x": 3})

        assert count == 0
        log = store.get_delivery_log(reg.webhook_id)
        assert len(log) == _MAX_ATTEMPTS
        assert all(not a.success for a in log)

    def test_connection_error_logged(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        store.register("t5", "https://example.com/hook", "s3cr3t", ["decision.approved"], "")
        with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError("refused")):
            with patch("time.sleep"):
                count = dispatcher.dispatch("t5", "decision.approved", {})
        assert count == 0

    def test_event_not_subscribed_skipped(
        self, dispatcher: WebhookDispatcher, store: WebhookStore
    ) -> None:
        store.register("t6", "https://example.com/hook", "s3cr3t", ["decision.approved"], "")
        with patch("urllib.request.urlopen") as mock_open:
            count = dispatcher.dispatch("t6", "batch.complete", {"x": 1})
        assert count == 0
        mock_open.assert_not_called()
