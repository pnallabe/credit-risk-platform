from __future__ import annotations

import json
from unittest import mock

from monitoring.alert_router import (
    AlertRouter,
    EmailChannel,
    LogOnlyChannel,
    SlackWebhookChannel,
    build_channels_from_env,
)


def test_slack_channel_sends_correct_payload() -> None:
    channel = SlackWebhookChannel("https://example.com/webhook")

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    with mock.patch("urllib.request.urlopen", return_value=_Resp()) as m:
        ok = channel.send(subject="Subj", body="Body", severity="CRITICAL")
        assert ok is True

        req = m.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert "CRITICAL" in payload["text"]
        assert "Subj" in payload["text"]


def test_email_channel_sends() -> None:
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=465,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        use_tls=True,
        username=None,
        password=None,
    )

    server = mock.MagicMock()
    server.__enter__.return_value = server
    server.__exit__.return_value = False

    with mock.patch("smtplib.SMTP_SSL", return_value=server) as m:
        ok = channel.send(subject="Hello", body="World", severity="HIGH")
        assert ok is True
        assert m.called
        server.sendmail.assert_called_once()


def test_failed_channel_does_not_abort() -> None:
    channel = SlackWebhookChannel("https://example.com/webhook")

    with mock.patch.object(channel, "send", side_effect=ConnectionError("boom")):
        router = AlertRouter(channels={"CRITICAL": [channel]})
        alert = router.route("CRITICAL", "subj", "body")
        assert alert.severity == "CRITICAL"


def test_build_channels_from_env_fallback(monkeypatch) -> None:
    for k in [
        "ALERT_SLACK_WEBHOOK_URL",
        "ALERT_EMAIL_SMTP_HOST",
        "ALERT_EMAIL_TO",
        "ALERT_EMAIL_FROM",
        "ALERT_EMAIL_SMTP_PASSWORD",
        "ALERT_EMAIL_SMTP_PORT",
        "ALERT_EMAIL_SMTP_USERNAME",
    ]:
        monkeypatch.delenv(k, raising=False)

    channels = build_channels_from_env()
    assert set(channels.keys()) == {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for sev, chs in channels.items():
        assert len(chs) == 1
        assert isinstance(chs[0], LogOnlyChannel)
