from __future__ import annotations

import json
import logging
import os
import smtplib
import ssl
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol

log = logging.getLogger("alert_router")


class NotificationChannel(Protocol):
    def send(self, subject: str, body: str, severity: str) -> bool:
        """Send a notification. Returns True on success."""


class SlackWebhookChannel:
    def __init__(self, webhook_url: str):
        self._webhook_url = str(webhook_url)

    def send(self, subject: str, body: str, severity: str) -> bool:
        payload = {"text": f"*[{severity}]* {subject}\n{body}"}
        data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            self._webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        # Retry on rate-limit (429) and transient 5xx.
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = getattr(resp, "status", 200)
                    if 200 <= int(status) < 300:
                        return True
                    if int(status) == 429 or int(status) >= 500:
                        time.sleep(0.25 * attempt)
                        continue
                    return False
            except Exception as exc:  # noqa: BLE001
                # Don't log webhook URL.
                if attempt < 3:
                    time.sleep(0.25 * attempt)
                    continue
                log.warning("Slack send failed after retries: %s", exc)
                return False
        return False


class EmailChannel:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_addr: str,
        to_addrs: List[str],
        use_tls: bool = True,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.smtp_host = str(smtp_host)
        self.smtp_port = int(smtp_port)
        self.from_addr = str(from_addr)
        self.to_addrs = [str(a).strip() for a in to_addrs if str(a).strip()]
        self.use_tls = bool(use_tls)
        self.username = None if username is None else str(username)
        self.password = None if password is None else str(password)

    def send(self, subject: str, body: str, severity: str) -> bool:
        _ = severity
        msg = f"Subject: {subject}\nFrom: {self.from_addr}\nTo: {', '.join(self.to_addrs)}\n\n{body}"

        try:
            if self.use_tls and self.smtp_port == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=10) as server:
                    if self.username and self.password:
                        server.login(self.username, self.password)
                    server.sendmail(self.from_addr, self.to_addrs, msg)
                    return True

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                if self.use_tls:
                    context = ssl.create_default_context()
                    server.starttls(context=context)
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.sendmail(self.from_addr, self.to_addrs, msg)
                return True
        except Exception as exc:  # noqa: BLE001
            # Do not log password.
            log.warning("Email send failed: %s", exc)
            return False


class LogOnlyChannel:
    def __init__(self, logger_name: str = "alert_router"):
        self._logger = logging.getLogger(logger_name)

    def send(self, subject: str, body: str, severity: str) -> bool:
        msg = f"[{severity}] {subject}\n{body}"
        sev = str(severity).upper()
        if sev in {"HIGH", "CRITICAL"}:
            self._logger.error(msg)
        else:
            self._logger.warning(msg)
        return True


@dataclass
class AlertRecord:
    severity: str
    subject: str
    body: str
    sent_to_channels: List[str] = field(default_factory=list)


class AlertRouter:
    def __init__(self, channels: Optional[Dict[str, List[NotificationChannel]]] = None):
        self.channels: Dict[str, List[NotificationChannel]] = channels or {
            "CRITICAL": [LogOnlyChannel()],
            "HIGH": [LogOnlyChannel()],
            "MEDIUM": [LogOnlyChannel()],
            "LOW": [LogOnlyChannel()],
        }

    def route(self, severity: str, subject: str, body: str) -> AlertRecord:
        sev = str(severity).upper()
        alert = AlertRecord(severity=sev, subject=str(subject), body=str(body))

        chan_list = self.channels.get(sev, [])
        for ch in chan_list:
            try:
                ok = ch.send(subject=alert.subject, body=alert.body, severity=sev)
                if ok:
                    alert.sent_to_channels.append(ch.__class__.__name__)
                else:
                    log.warning("Channel returned failure for severity=%s channel=%s", sev, ch.__class__.__name__)
            except Exception as exc:  # noqa: BLE001
                log.warning("Channel exception for severity=%s channel=%s: %s", sev, ch.__class__.__name__, exc)
                continue

        return alert

    def send_alert(self, severity: str, title: str, body: str) -> AlertRecord:
        """Synchronous convenience wrapper around :meth:`route`.

        Parameters
        ----------
        severity:
            One of ``"CRITICAL"``, ``"HIGH"``, ``"MEDIUM"``, ``"LOW"``.
        title:
            Short alert title (used as email subject / Slack header).
        body:
            Full alert body text.

        Returns
        -------
        AlertRecord
            Record of which channels the alert was dispatched to.
        """
        return self.route(severity=severity, subject=title, body=body)


def build_channels_from_env() -> Dict[str, List[NotificationChannel]]:
    webhook = os.getenv("ALERT_SLACK_WEBHOOK_URL")
    smtp_host = os.getenv("ALERT_EMAIL_SMTP_HOST")
    email_to = os.getenv("ALERT_EMAIL_TO")
    email_from = os.getenv("ALERT_EMAIL_FROM")
    email_pass = os.getenv("ALERT_EMAIL_SMTP_PASSWORD")

    any_configured = False
    base: Dict[str, List[NotificationChannel]] = {
        "CRITICAL": [],
        "HIGH": [],
        "MEDIUM": [],
        "LOW": [],
    }

    if webhook:
        any_configured = True
        slack = SlackWebhookChannel(webhook_url=webhook)
        for sev in base:
            base[sev].append(slack)

    if smtp_host and email_to and email_from:
        any_configured = True
        to_addrs = [a.strip() for a in email_to.split(",") if a.strip()]
        email = EmailChannel(
            smtp_host=smtp_host,
            smtp_port=int(os.getenv("ALERT_EMAIL_SMTP_PORT", "465")),
            from_addr=email_from,
            to_addrs=to_addrs,
            use_tls=True,
            username=os.getenv("ALERT_EMAIL_SMTP_USERNAME"),
            password=email_pass,
        )
        base["CRITICAL"].append(email)
        base["HIGH"].append(email)

    if not any_configured:
        log.warning("No alert notification env vars found; using LogOnlyChannel for all severities")
        return {sev: [LogOnlyChannel()] for sev in base}

    # Ensure every severity has at least a log fallback
    for sev in base:
        if not base[sev]:
            base[sev] = [LogOnlyChannel()]

    return base


DEFAULT_ALERT_ROUTER = AlertRouter(channels=build_channels_from_env())


async def check_adverse_action_deadlines(
    db_url: str,
    tenant_id: str,
    router: "AlertRouter",
    warn_days_before: int = 5,
) -> int:
    """Query adverse_action_log for PENDING notices approaching their 30-day deadline.

    Fires a CRITICAL alert via *router* for each notice found.

    Parameters
    ----------
    db_url:
        SQLAlchemy async DB URL.
    tenant_id:
        Tenant to check.
    router:
        :class:`AlertRouter` instance used to dispatch alerts.
    warn_days_before:
        Alert window in days before the deadline.

    Returns
    -------
    int
        Count of notices alerted.
    """
    try:
        from compliance.adverse_action_store import get_pending_deadline_notices  # lazy
    except ImportError as exc:
        log.warning("check_adverse_action_deadlines: import failed: %s", exc)
        return 0

    try:
        notices = await get_pending_deadline_notices(db_url, tenant_id, warn_days_before)
    except Exception as exc:
        log.warning(
            "check_adverse_action_deadlines: failed to query notices: %s", exc
        )
        return 0

    count = 0
    for notice in notices:
        notice_id = notice.get("notice_id", "unknown")
        application_id = notice.get("application_id", "unknown")
        deadline_date = notice.get("deadline_date", "unknown")

        router.send_alert(
            severity="CRITICAL",
            title="Adverse Action Deadline Approaching",
            body=(
                f"Notice {notice_id} for application {application_id} "
                f"must be delivered by {deadline_date}. Status: PENDING."
            ),
        )
        count += 1

    return count
